"""Arabic TTS Studio — main gateway server (port 8080).
Serves the frontend and proxies synthesis requests to model workers.
Workers must be started separately (see start.sh).
"""
import asyncio
import json
import os
import pathlib
from contextlib import asynccontextmanager
from typing import Optional

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

BASE_DIR  = pathlib.Path(__file__).parent
STATIC    = BASE_DIR / "static"
WORKDIR   = pathlib.Path(os.getenv("TTS_WORKDIR", "~/tts-05172026")).expanduser()

OUTPUT_DIRS = {
    # Keep old Fish/VoxCPM2 recordings serveable, but they are no longer active workers.
    "fish":      WORKDIR / "outputs",
    "voxcpm2":   WORKDIR / "outputs_voxcpm2",
    # The two interface models are OmniVoice variants sharing one worker + output dir.
    "omnivoice":      WORKDIR / "outputs_omnivoice",
    "omnivoice_ft":   WORKDIR / "outputs_omnivoice",
    "omnivoice_base": WORKDIR / "outputs_omnivoice",
}

_OMNIVOICE_URL = "http://127.0.0.1:8082"
WORKER_URLS = {
    # Aliases for the SAME worker; the frontend fixes the `variant` form field per model.
    "omnivoice":      _OMNIVOICE_URL,
    "omnivoice_ft":   _OMNIVOICE_URL,
    "omnivoice_base": _OMNIVOICE_URL,
}

# Which worker-side model variant each alias warms on /load ("" = worker default).
MODEL_VARIANT = {
    "omnivoice_ft":   "finetuned",
    "omnivoice_base": "base",
}

SINGLE_MODEL_MODE = os.getenv("TTS_SINGLE_MODEL", "1").lower() not in {"0", "false", "no", "off"}
MAX_REQUEST_BYTES = int(os.getenv("TTS_MAX_REQUEST_BYTES", str(32 * 1024 * 1024)))

_client: Optional[httpx.AsyncClient] = None
_model_gate = asyncio.Lock()


async def _read_limited_body(request: Request) -> bytes:
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_REQUEST_BYTES:
                raise HTTPException(413, f"Request is too large; max {MAX_REQUEST_BYTES // (1024 * 1024)} MB")
        except ValueError:
            pass

    body = await request.body()
    if len(body) > MAX_REQUEST_BYTES:
        raise HTTPException(413, f"Request is too large; max {MAX_REQUEST_BYTES // (1024 * 1024)} MB")
    return body


async def _unload_other_models(active_model: str):
    if not SINGLE_MODEL_MODE:
        return
    active_url = WORKER_URLS[active_model]
    for model, url in WORKER_URLS.items():
        if url == active_url:       # aliases of the active worker included
            continue
        try:
            await _client.post(f"{url}/unload", timeout=60.0)
        except Exception:
            pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _client
    _client = httpx.AsyncClient(timeout=httpx.Timeout(connect=5.0, read=900.0, write=300.0, pool=5.0))
    yield
    await _client.aclose()


app = FastAPI(title="Arabic TTS Studio", lifespan=lifespan, docs_url=None, redoc_url=None)


@app.middleware("http")
async def frontend_cache_policy(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path
    if request.method == "GET" and not path.startswith(("/api/", "/audio/")):
        # The UI uses query-versioned assets, but the HTML itself must not pin an old
        # bundle reference in browser/proxy caches after a frontend deployment.
        response.headers["Cache-Control"] = "no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
    return response


@app.get("/api/status")
async def status():
    # One health call per unique worker URL; aliases reuse the same payload.
    by_url = {}
    for url in set(WORKER_URLS.values()):
        try:
            r = await _client.get(f"{url}/health", timeout=3.0)
            by_url[url] = r.json()
        except Exception:
            by_url[url] = None
    results = {}
    for model, url in WORKER_URLS.items():
        health = by_url[url]
        if health is None:
            results[model] = {"model": model, "status": "offline", "ready": False, "model_loaded": False}
        else:
            results[model] = health
    results["_memory_policy"] = {
        "single_model_mode": SINGLE_MODEL_MODE,
        "max_request_mb": MAX_REQUEST_BYTES // (1024 * 1024),
    }
    return results


@app.post("/api/{model}/synthesize")
async def synthesize(model: str, request: Request):
    if model not in WORKER_URLS:
        raise HTTPException(404, f"Unknown model: {model}")

    body    = await _read_limited_body(request)
    headers = {k: v for k, v in request.headers.items()
               if k.lower() not in ("host", "content-length")}
    async with _model_gate:
        await _unload_other_models(model)
        try:
            r = await _client.post(f"{WORKER_URLS[model]}/synthesize",
                                   content=body, headers=headers)
        except httpx.ConnectError:
            raise HTTPException(503, f"{model} worker is not running — check start.sh")
        except httpx.ReadTimeout:
            raise HTTPException(504, f"{model} synthesis timed out (>5 min)")

    if r.status_code != 200:
        raise HTTPException(r.status_code, r.text)
    return JSONResponse(r.json())


@app.post("/api/{model}/load")
async def load_model(model: str):
    if model not in WORKER_URLS:
        raise HTTPException(404, f"Unknown model: {model}")
    async with _model_gate:
        await _unload_other_models(model)
        try:
            variant = MODEL_VARIANT.get(model, "")
            r = await _client.post(f"{WORKER_URLS[model]}/load",
                                   params={"variant": variant} if variant else None,
                                   timeout=900.0)
            return JSONResponse(r.json())
        except httpx.ConnectError:
            raise HTTPException(503, f"{model} worker is not running")
        except httpx.ReadTimeout:
            raise HTTPException(504, f"{model} model load timed out (>15 min)")


@app.post("/api/{model}/unload")
async def unload_model(model: str):
    if model not in WORKER_URLS:
        raise HTTPException(404, f"Unknown model: {model}")
    async with _model_gate:
        try:
            r = await _client.post(f"{WORKER_URLS[model]}/unload", timeout=60.0)
            return JSONResponse(r.json())
        except httpx.ConnectError:
            raise HTTPException(503, f"{model} worker is not running")
        except httpx.ReadTimeout:
            raise HTTPException(504, f"{model} model unload timed out")


@app.get("/api/{model}/status")
async def model_status(model: str):
    if model not in WORKER_URLS:
        raise HTTPException(404, f"Unknown model: {model}")
    try:
        r = await _client.get(f"{WORKER_URLS[model]}/health", timeout=3.0)
        return JSONResponse(r.json())
    except Exception:
        return JSONResponse({"model": model, "status": "offline", "ready": False, "model_loaded": False})


@app.get("/api/{model}/history")
async def history(model: str, limit: int = 100):
    if model not in OUTPUT_DIRS:
        raise HTTPException(404, f"Unknown model: {model}")
    out_dir = OUTPUT_DIRS[model]
    if not out_dir.exists():
        return []
    wavs = sorted(out_dir.glob("*.wav"), key=lambda p: p.stat().st_mtime, reverse=True)
    items = []
    for w in wavs[:limit]:
        item = {
            "filename":   w.name,
            "model":      model,
            "size_bytes": w.stat().st_size,
            "mtime":      w.stat().st_mtime,
        }
        sidecar = w.with_suffix(".json")
        if sidecar.exists():
            try:
                meta = json.loads(sidecar.read_text(encoding="utf-8"))
                # surface the saved inputs alongside file info
                for k in ("text", "instruct", "params", "reference_text",
                          "prompt_text", "duration_s", "rtf", "elapsed_s"):
                    if k in meta:
                        item[k] = meta[k]
            except Exception:
                pass
        items.append(item)
    return items


@app.get("/audio/{model}/{filename}")
async def serve_audio(model: str, filename: str):
    if model not in OUTPUT_DIRS:
        raise HTTPException(404, "Unknown model")
    safe = pathlib.Path(filename).name          # prevent path traversal
    path = OUTPUT_DIRS[model] / safe
    if not path.exists():
        raise HTTPException(404, "Audio file not found")
    return FileResponse(str(path), media_type="audio/wav",
                        headers={"Cache-Control": "no-store"})


@app.post("/api/compose")
async def compose(request: Request):
    """Auto-Compose agent: a job + voice prefs -> Arabic script + settings for BOTH engines."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body")
    job = (body.get("job") or "").strip()
    if not job:
        raise HTTPException(400, "Missing 'job'")

    try:
        from compose import compose as run_compose
    except Exception as e:
        raise HTTPException(503, f"Compose agent unavailable (install deps?): {e}")

    try:
        result = await asyncio.to_thread(
            run_compose,
            job,
            body.get("gender", ""),
            body.get("age", ""),
            body.get("dialect", "msa"),
            body.get("brief", ""),
        )
    except RuntimeError as e:                 # missing OPENAI_API_KEY, etc.
        raise HTTPException(503, str(e))
    except Exception as e:                     # OpenAI / validation failure
        raise HTTPException(502, f"Compose failed: {e}")
    return JSONResponse(result)


@app.post("/api/prepare")
async def prepare(request: Request):
    """Text-Prep agent: rewrite raw Arabic for TTS (normalize numbers/abbrev + optional tashkeel).
    Operates ONLY on the text string — the workers/models are untouched."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body")
    text = (body.get("text") or "").strip()
    if not text:
        raise HTTPException(400, "Missing 'text'")
    normalize  = bool(body.get("normalize", True))
    diacritize = bool(body.get("diacritize", False))
    if not (normalize or diacritize):                  # nothing to do — skip the LLM call
        return JSONResponse({"original": text, "normalized": "", "diacritized": "",
                             "text": text, "notes": "", "normalize": False, "diacritize": False})

    try:
        from textprep import prepare_text
    except Exception as e:
        raise HTTPException(503, f"Text-prep agent unavailable (install deps?): {e}")

    try:
        result = await asyncio.to_thread(
            prepare_text, text, body.get("dialect", "msa"), normalize, diacritize)
    except RuntimeError as e:                 # missing OPENAI_API_KEY, etc.
        raise HTTPException(503, str(e))
    except Exception as e:                     # OpenAI / validation failure
        raise HTTPException(502, f"Prepare failed: {e}")
    return JSONResponse(result)


# Serve frontend — must be last so API routes take priority
app.mount("/", StaticFiles(directory=str(STATIC), html=True), name="static")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--host", default="0.0.0.0")
    args = parser.parse_args()
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
