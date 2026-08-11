"""Arabic TTS Studio — main gateway server (port 8080).
Serves the frontend and proxies synthesis requests to model workers.
Workers must be started separately (see start.sh).
"""
import asyncio
import json
import os
import pathlib
import time
from contextlib import asynccontextmanager
from typing import Optional

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from reqlog import RequestLog, RequestLogMiddleware

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
    "transcribe":     WORKDIR / "outputs_transcribe",
}

_OMNIVOICE_URL = "http://127.0.0.1:8082"

# Speech-out (TTS) workers — only these answer /api/{model}/synthesize.
TTS_WORKERS = {
    # Aliases for the SAME worker; the frontend fixes the `variant` form field per model.
    "omnivoice":      _OMNIVOICE_URL,
    "omnivoice_ft":   _OMNIVOICE_URL,
    "omnivoice_base": _OMNIVOICE_URL,
}
# Speech-in (ASR) worker — answers /api/transcribe.
ASR_WORKER = "http://127.0.0.1:8084"

# Everything with /health + /load, so status polling, warm-up and the single-model
# memory policy cover the ASR model too — it is as heavy as a TTS checkpoint.
WORKER_URLS = {**TTS_WORKERS, "transcribe": ASR_WORKER}

# Which worker-side model variant each alias warms on /load ("" = worker default).
MODEL_VARIANT = {
    "omnivoice_ft":   "finetuned",
    "omnivoice_base": "base",
}


def _flag(name: str, default: str = "1") -> bool:
    return os.getenv(name, default).lower() not in {"0", "false", "no", "off"}


SINGLE_MODEL_MODE = _flag("TTS_SINGLE_MODEL")
MAX_REQUEST_BYTES = int(os.getenv("TTS_MAX_REQUEST_BYTES", str(32 * 1024 * 1024)))

# ── Request log ───────────────────────────────────────────────
LOG_REQUESTS  = _flag("TTS_LOG_REQUESTS")
LOG_DB        = pathlib.Path(os.getenv("TTS_LOG_DB", str(WORKDIR / "logs" / "requests.db"))).expanduser()
LOG_RETENTION = int(os.getenv("TTS_LOG_RETENTION", "5000"))
# Status polling is the UI's heartbeat (every few seconds, per model); off by default so
# it does not bury the calls anyone actually wants to investigate.
LOG_STATUS_POLLS = _flag("TTS_LOG_STATUS_POLLS", "0")

request_log: Optional[RequestLog] = None
if LOG_REQUESTS:
    try:
        request_log = RequestLog(LOG_DB, retention=LOG_RETENTION)
    except Exception as e:                       # unwritable workdir, locked file, …
        print(f"[gateway] request logging disabled: {e}")


def _should_log(scope) -> bool:
    path = scope.get("path", "")
    if not path.startswith("/api/"):
        return False
    if path.startswith("/api/logs"):             # the console reading its own history
        return False
    if not LOG_STATUS_POLLS and (path == "/api/status" or path.endswith("/status")):
        return False
    return True


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

# `app.routes` is the live list the router matches against, so passing it here keeps the
# route templates resolvable no matter how many endpoints are declared further down.
app.add_middleware(RequestLogMiddleware, store=request_log, routes=app.routes,
                   should_log=_should_log)


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


async def _proxy_post(url: str, model: str, request: Request, timeout_msg: str) -> JSONResponse:
    """Forward a multipart request to a worker under the memory policy, return its JSON.

    The body is size-capped and buffered rather than streamed: the cap is what keeps a
    large upload from filling RAM on this host, and it cannot be enforced on a body that
    is piped straight through. Holding the model gate across the call serialises the
    heavyweight workers so only one checkpoint is resident at a time.
    """
    body    = await _read_limited_body(request)
    headers = {k: v for k, v in request.headers.items()
               if k.lower() not in ("host", "content-length")}
    async with _model_gate:
        await _unload_other_models(model)
        try:
            r = await _client.post(url, content=body, headers=headers)
        except httpx.ConnectError:
            raise HTTPException(503, f"{model} worker is not running — check start.sh")
        except httpx.ReadTimeout:
            raise HTTPException(504, timeout_msg)

    if r.status_code != 200:
        raise HTTPException(r.status_code, r.text)
    return JSONResponse(r.json())


@app.post("/api/{model}/synthesize")
async def synthesize(model: str, request: Request):
    if model not in TTS_WORKERS:
        raise HTTPException(404, f"Unknown model: {model}")
    return await _proxy_post(f"{TTS_WORKERS[model]}/synthesize", model, request,
                             f"{model} synthesis timed out (>15 min)")


@app.post("/api/transcribe")
async def transcribe(request: Request):
    """Speech → Arabic/English text via the Cohere Transcribe worker."""
    return await _proxy_post(f"{ASR_WORKER}/transcribe", "transcribe", request,
                             "transcription timed out (>15 min)")


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
                for k in ("text", "instruct", "params", "reference_text", "prompt_text",
                          "language", "duration_s", "rtf", "elapsed_s"):
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


@app.get("/api", include_in_schema=False)
@app.get("/api/", include_in_schema=False)
async def api_docs(request: Request):
    """/api/ is where people look for the docs; the page itself is static/api.html.

    Redirect rather than serve the file here: api.html links its CSS/JS relatively,
    so served under /api/ every asset would 404. The target must stay relative too —
    nginx proxy_passes with a trailing slash, so the app never sees the /arabic-tts/
    prefix and an absolute /api.html would send the browser to the wrong host root.
    """
    target = "../api.html" if request.url.path.endswith("/") else "api.html"
    return RedirectResponse(target, status_code=302)


# ── Request log (the usage console reads these) ───────────────
def _log_store() -> RequestLog:
    if request_log is None:
        raise HTTPException(503, "Request logging is disabled (TTS_LOG_REQUESTS=0)")
    return request_log


@app.get("/api/logs")
async def list_logs(limit: int = 50, offset: int = 0, hours: float = 0,
                    route: str = "", method: str = "", model: str = "",
                    status: str = "", q: str = ""):
    """Recorded requests, newest first. `status` takes `ok`, `error` or an HTTP code."""
    store = _log_store()
    since = time.time() - hours * 3600 if hours > 0 else None
    return await asyncio.to_thread(
        store.query, limit=max(1, min(limit, 200)), offset=max(0, offset),
        route=route or None, method=method or None, model=model or None,
        status=status or None, since=since, q=q or None)


@app.get("/api/logs/stats")
async def log_stats(hours: float = 24, buckets: int = 24):
    """Totals, per-endpoint timings and a request timeline for the window."""
    store = _log_store()
    return await asyncio.to_thread(store.stats, hours=hours,
                                   buckets=max(1, min(buckets, 200)))


@app.get("/api/logs/{log_id}")
async def log_detail(log_id: int):
    entry = await asyncio.to_thread(_log_store().get, log_id)
    if entry is None:
        raise HTTPException(404, f"No log entry {log_id}")
    return entry


@app.delete("/api/logs")
async def clear_logs():
    deleted = await asyncio.to_thread(_log_store().clear)
    return {"deleted": deleted}


# Serve frontend — must be last so API routes take priority
app.mount("/", StaticFiles(directory=str(STATIC), html=True), name="static")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--host", default="0.0.0.0")
    args = parser.parse_args()
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
