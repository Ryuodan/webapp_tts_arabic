"""Arabic TTS Studio — main gateway server (port 8080).
Serves the frontend and proxies synthesis requests to model workers.
Workers must be started separately (see start.sh).
"""
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
    # Keep old Fish/S2 Pro recordings serveable, but do not expose it as an active worker.
    "fish":      WORKDIR / "outputs",
    "omnivoice": WORKDIR / "outputs_omnivoice",
    "voxcpm2":   WORKDIR / "outputs_voxcpm2",
}

WORKER_URLS = {
    "omnivoice": "http://127.0.0.1:8082",
    "voxcpm2":   "http://127.0.0.1:8083",
}

_client: Optional[httpx.AsyncClient] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _client
    _client = httpx.AsyncClient(timeout=httpx.Timeout(connect=5.0, read=900.0, write=300.0, pool=5.0))
    yield
    await _client.aclose()


app = FastAPI(title="Arabic TTS Studio", lifespan=lifespan, docs_url=None, redoc_url=None)


@app.get("/api/status")
async def status():
    results = {}
    for model, url in WORKER_URLS.items():
        try:
            r = await _client.get(f"{url}/health", timeout=3.0)
            results[model] = r.json()
        except Exception:
            results[model] = {"model": model, "status": "offline", "ready": False, "model_loaded": False}
    return results


@app.post("/api/{model}/synthesize")
async def synthesize(model: str, request: Request):
    if model not in WORKER_URLS:
        raise HTTPException(404, f"Unknown model: {model}")

    body    = await request.body()
    headers = {k: v for k, v in request.headers.items()
               if k.lower() not in ("host", "content-length")}
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
    try:
        r = await _client.post(f"{WORKER_URLS[model]}/load", timeout=900.0)
        return JSONResponse(r.json())
    except httpx.ConnectError:
        raise HTTPException(503, f"{model} worker is not running")
    except httpx.ReadTimeout:
        raise HTTPException(504, f"{model} model load timed out (>15 min)")


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
    return [
        {
            "filename":   w.name,
            "model":      model,
            "size_bytes": w.stat().st_size,
            "mtime":      w.stat().st_mtime,
        }
        for w in wavs[:limit]
    ]


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


# Serve frontend — must be last so API routes take priority
app.mount("/", StaticFiles(directory=str(STATIC), html=True), name="static")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--host", default="0.0.0.0")
    args = parser.parse_args()
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
