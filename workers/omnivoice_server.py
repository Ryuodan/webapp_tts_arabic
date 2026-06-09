"""OmniVoice TTS worker — run inside the omnivoice-tts conda env (port 8082).
Model is loaded lazily on first synthesis request.
"""
import asyncio
import os
import pathlib
import tempfile
import time
import uuid

import soundfile as sf
import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

OUT_DIR = pathlib.Path("~/tts-05172026/outputs_omnivoice").expanduser()
OUT_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="OmniVoice Worker", docs_url=None, redoc_url=None)
_model = None
_lock = asyncio.Lock()
SAMPLE_RATE = 24_000


def _do_load():
    global _model
    if _model is not None:
        return
    import torch
    from omnivoice import OmniVoice
    device = "cuda:0" if torch.cuda.is_available() else "cpu"
    dtype  = torch.float16 if torch.cuda.is_available() else torch.float32
    _model = OmniVoice.from_pretrained("k2-fsa/OmniVoice", device_map=device, dtype=dtype)


async def _ensure_loaded():
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _do_load)


@app.get("/health")
async def health():
    return {
        "model": "OmniVoice",
        "status": "ok",
        "ready": _model is not None,
        "model_loaded": _model is not None,
    }


@app.post("/load")
async def load_endpoint():
    await _ensure_loaded()
    return {"status": "loaded"}


@app.post("/synthesize")
async def synthesize(
    text: str = Form(...),
    speaker: str = Form(""),
    ref_audio: UploadFile | None = File(None),
    ref_text: str | None = Form(None),
):
    await _ensure_loaded()

    ref_tmp: str | None = None
    if ref_audio and ref_audio.filename:
        data = await ref_audio.read()
        fd, ref_tmp = tempfile.mkstemp(suffix=".wav")
        os.write(fd, data)
        os.close(fd)

    out_path = OUT_DIR / f"omnivoice_{uuid.uuid4().hex[:12]}.wav"
    kwargs: dict = {"text": text}
    if ref_tmp:
        kwargs["ref_audio"] = ref_tmp
    if ref_text and ref_text.strip():
        kwargs["ref_text"] = ref_text.strip()
    if speaker and speaker.strip():
        kwargs["speaker"] = speaker.strip()

    try:
        async with _lock:
            loop = asyncio.get_event_loop()
            t0 = time.perf_counter()
            audio = await loop.run_in_executor(None, lambda: _model.generate(**kwargs))
            elapsed = time.perf_counter() - t0
    except Exception as e:
        raise HTTPException(500, str(e))
    finally:
        if ref_tmp:
            os.unlink(ref_tmp)

    sf.write(str(out_path), audio[0], SAMPLE_RATE)
    duration = len(audio[0]) / SAMPLE_RATE

    return {
        "filename": out_path.name,
        "model": "omnivoice",
        "elapsed_s": round(elapsed, 2),
        "duration_s": round(duration, 2),
        "rtf": round(elapsed / max(duration, 0.01), 3),
        "sample_rate": SAMPLE_RATE,
    }


@app.get("/audio/{filename}")
async def get_audio(filename: str):
    path = OUT_DIR / pathlib.Path(filename).name
    if not path.exists():
        raise HTTPException(404, "Audio file not found")
    return FileResponse(str(path), media_type="audio/wav")


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8082, log_level="info")
