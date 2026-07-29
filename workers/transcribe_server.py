"""Cohere Transcribe Arabic (INT8) ASR worker — run inside the transcribe-asr conda env (port 8084).

Speech → text, the inverse of the TTS workers. The model is loaded lazily on the
first request (or via POST /load) because the INT8 checkpoint is ~2.4 GB.

Long audio needs no special handling here: the feature extractor splits anything
longer than its `max_audio_clip_s` into chunks and the processor reassembles the
per-chunk transcripts from `audio_chunk_index`.
"""
import asyncio
import gc
import os
import pathlib
import tempfile
import time
import uuid
from contextlib import suppress

import soundfile as sf
import torch
import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile

from _common import output_dir, register_audio_route, write_sidecar

OUT_DIR = output_dir("TRANSCRIBE_OUT_DIR", "outputs_transcribe")
# The one transcription model. Pinned rather than configurable: everything downstream
# (16 kHz features, the ar/en decoder prompt, the chunk-reassembly decode) is specific
# to this checkpoint, so a swapped id would not be a drop-in anyway.
MODEL_ID = "NAMAA-Space/cohere-transcribe-arabic-07-2026-int8"
DEVICE = os.getenv("TRANSCRIBE_DEVICE", "auto")
MAX_NEW_TOKENS = int(os.getenv("TRANSCRIBE_MAX_NEW_TOKENS", "256"))
# Same knob the TTS workers read — one upload limit across every worker.
MAX_UPLOAD_BYTES = int(os.getenv("TTS_MAX_UPLOAD_BYTES", str(25 * 1024 * 1024)))
MODEL_IDLE_SECONDS = int(os.getenv("TTS_MODEL_IDLE_SECONDS", "900"))
SAMPLE_RATE = 16_000            # fixed by the model's feature extractor

# The checkpoint is Arabic + English only. Arabic dialects all share the "ar" decoder
# prompt — there is no per-dialect token, so the TTS dialect selector does not apply here.
_LANGUAGES = {"ar", "en"}

app = FastAPI(title="Cohere Transcribe Arabic Worker", docs_url=None, redoc_url=None)
_model = None
_processor = None
_lock = asyncio.Lock()          # one generate() at a time — the GPU is shared with the TTS workers
_last_used = 0.0
_idle_task = None


def _do_load():
    global _model, _processor
    if _model is not None:
        return
    from transformers import AutoProcessor, CohereAsrForConditionalGeneration
    _processor = AutoProcessor.from_pretrained(MODEL_ID)
    _model = CohereAsrForConditionalGeneration.from_pretrained(MODEL_ID, device_map=DEVICE)
    _model.eval()


def _cleanup_runtime_memory():
    gc.collect()
    with suppress(Exception):
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    with suppress(Exception):
        import ctypes
        ctypes.CDLL("libc.so.6").malloc_trim(0)


def _do_unload(reason: str = "manual") -> bool:
    """Drop the ~2.4 GB checkpoint so a TTS model can take the memory.

    The gateway calls this on every other worker before it runs one, so the ASR model
    must release just like the TTS ones do — otherwise single-model mode is a no-op here.
    """
    global _model, _processor
    was_loaded = _model is not None
    _model = _processor = None
    if was_loaded:
        _cleanup_runtime_memory()
    return was_loaded


async def _idle_unload_loop():
    sleep_s = min(60, max(5, MODEL_IDLE_SECONDS // 3 if MODEL_IDLE_SECONDS else 60))
    while True:
        await asyncio.sleep(sleep_s)
        if MODEL_IDLE_SECONDS <= 0 or _model is None or _last_used <= 0:
            continue
        if time.monotonic() - _last_used < MODEL_IDLE_SECONDS:
            continue
        async with _lock:
            if _model is not None and time.monotonic() - _last_used >= MODEL_IDLE_SECONDS:
                await asyncio.to_thread(_do_unload, "idle")


@app.on_event("startup")
async def startup():
    global _idle_task
    if MODEL_IDLE_SECONDS > 0:
        _idle_task = asyncio.create_task(_idle_unload_loop())


@app.on_event("shutdown")
async def shutdown():
    if _idle_task:
        _idle_task.cancel()
        with suppress(asyncio.CancelledError):
            await _idle_task


@app.post("/unload")
async def unload_endpoint():
    async with _lock:
        unloaded = await asyncio.to_thread(_do_unload, "manual")
    return {"status": "unloaded" if unloaded else "not_loaded"}


async def _ensure_loaded():
    await asyncio.get_event_loop().run_in_executor(None, _do_load)


def _run(audio, language: str, punctuation: bool) -> str:
    """Blocking transcription — always called from the executor under _lock."""
    inputs = _processor(audio, sampling_rate=SAMPLE_RATE, return_tensors="pt",
                        language=language, punctuation=punctuation)
    # Chunk bookkeeping is for the decoder only; generate() would choke on it.
    chunk_index = inputs.pop("audio_chunk_index", None)
    inputs = inputs.to(_model.device, dtype=_model.dtype)

    with torch.inference_mode():
        outputs = _model.generate(**inputs, max_new_tokens=MAX_NEW_TOKENS)

    decode_kwargs = {"skip_special_tokens": True}
    if chunk_index is not None:            # long-form: stitch the chunks back together
        decode_kwargs.update(audio_chunk_index=chunk_index, language=language)
    return _processor.decode(outputs, **decode_kwargs).strip()


@app.get("/health")
async def health():
    return {
        "model": "Cohere Transcribe Arabic",
        "status": "ok",
        "ready": _model is not None,
        "model_loaded": _model is not None,
        "model_id": MODEL_ID,
        "sample_rate": SAMPLE_RATE,
    }


@app.post("/load")
async def load_endpoint():
    await _ensure_loaded()
    return {"status": "loaded", "model_id": MODEL_ID}


@app.post("/transcribe")
async def transcribe(
    audio: UploadFile = File(...),
    language: str = Form("ar"),
    punctuation: bool = Form(True),
):
    lang = (language or "ar").strip().lower()
    if lang not in _LANGUAGES:
        raise HTTPException(400, f"Unsupported language '{lang}' — expected one of {sorted(_LANGUAGES)}")

    data = await audio.read()
    if not data:
        raise HTTPException(400, "Empty audio upload")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"Uploaded audio is too large; max {MAX_UPLOAD_BYTES // (1024 * 1024)} MB")

    await _ensure_loaded()

    # Decode + resample off the event loop; load_audio handles wav/mp3/m4a/webm via ffmpeg.
    suffix = pathlib.Path(audio.filename or "").suffix or ".wav"
    fd, tmp = tempfile.mkstemp(suffix=suffix)
    try:
        os.write(fd, data)
        os.close(fd)
        from transformers.audio_utils import load_audio
        loop = asyncio.get_event_loop()
        try:
            samples = await loop.run_in_executor(
                None, lambda: load_audio(tmp, sampling_rate=SAMPLE_RATE))
        except Exception as e:
            raise HTTPException(400, f"Could not decode audio: {e}")

        try:
            async with _lock:
                global _last_used
                t0 = time.perf_counter()
                text = await loop.run_in_executor(
                    None, lambda: _run(samples, lang, punctuation))
                elapsed = time.perf_counter() - t0
                _last_used = time.monotonic()      # feeds the idle-unload loop
        except Exception as e:
            raise HTTPException(500, str(e))
    finally:
        os.unlink(tmp)

    # Keep the normalized 16 kHz mono input so the run replays from the shared history UI.
    out_path = OUT_DIR / f"transcribe_{uuid.uuid4().hex[:12]}.wav"
    sf.write(str(out_path), samples, SAMPLE_RATE)
    duration = len(samples) / SAMPLE_RATE

    result = {
        "filename": out_path.name,
        "model": "transcribe",
        "text": text,
        "language": lang,
        "elapsed_s": round(elapsed, 2),
        "duration_s": round(duration, 2),
        "rtf": round(elapsed / max(duration, 0.01), 3),
        "sample_rate": SAMPLE_RATE,
    }
    write_sidecar(out_path, {
        "params": {"language": lang, "punctuation": punctuation},
        "source_filename": audio.filename or "",
        "created": time.time(),
        **result,
    })
    return result


register_audio_route(app, OUT_DIR)


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8084, log_level="info")
