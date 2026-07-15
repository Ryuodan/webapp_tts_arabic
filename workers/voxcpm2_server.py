"""VoxCPM2 TTS worker — run inside the voxcpm2-tts conda env (port 8083).
Model is loaded lazily on first synthesis request.
"""
import asyncio
from contextlib import suppress
import gc
import json
import os
import pathlib
import tempfile
import time
import uuid

import soundfile as sf
import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

WORKDIR = pathlib.Path(os.getenv("TTS_WORKDIR", "~/tts-05172026")).expanduser()
OUT_DIR = pathlib.Path(os.getenv("VOXCPM2_OUT_DIR", str(WORKDIR / "outputs_voxcpm2"))).expanduser()
OUT_DIR.mkdir(parents=True, exist_ok=True)
VOXCPM2_MODEL_ID = os.getenv("VOXCPM2_MODEL_ID", "openbmb/VoxCPM2")
VOXCPM2_DEVICE = os.getenv("VOXCPM2_DEVICE", "auto")
VOXCPM2_OPTIMIZE = os.getenv("VOXCPM2_OPTIMIZE", "0").lower() in {"1", "true", "yes", "on"}
MODEL_IDLE_SECONDS = int(os.getenv("TTS_MODEL_IDLE_SECONDS", "900"))
MAX_TEXT_CHARS = int(os.getenv("TTS_MAX_TEXT_CHARS", "8000"))
MAX_UPLOAD_BYTES = int(os.getenv("TTS_MAX_UPLOAD_BYTES", str(25 * 1024 * 1024)))
CLEANUP_AFTER_SYNTH = os.getenv("TTS_CLEANUP_AFTER_SYNTH", "1").lower() not in {"0", "false", "no", "off"}

# Arabic is forced for every request; the dialect rides VoxCPM2's leading-parenthetical style cue.
_ARABIC_DIALECTS = {
    "msa":      "Modern Standard Arabic",
    "saudi":    "Saudi (Najdi) Arabic",
    "egyptian": "Egyptian Arabic",
}


def _arabic_descriptor(dialect: str) -> str:
    return _ARABIC_DIALECTS.get((dialect or "msa").strip().lower(), _ARABIC_DIALECTS["msa"])


# Optional voice persona — empty value means "let the model decide".
_GENDERS = {"male": "male", "female": "female"}
_AGES = {"young": "young adult", "middle": "middle-aged", "old": "elderly"}


def _persona(gender: str, age: str) -> str:
    g = _GENDERS.get((gender or "").strip().lower(), "")
    a = _AGES.get((age or "").strip().lower(), "")
    return " ".join(p for p in (g, a) if p)

app = FastAPI(title="VoxCPM2 Worker", docs_url=None, redoc_url=None)
_model = None
_sample_rate = 48_000
_lock = asyncio.Lock()
_idle_task: asyncio.Task | None = None
_last_used = 0.0
_last_unload_reason = ""


def _rss_mb() -> float | None:
    try:
        for line in pathlib.Path("/proc/self/status").read_text(encoding="utf-8").splitlines():
            if line.startswith("VmRSS:"):
                return round(int(line.split()[1]) / 1024, 1)
    except Exception:
        return None
    return None


def _cleanup_runtime_memory():
    gc.collect()
    with suppress(Exception):
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    with suppress(Exception):
        import ctypes
        ctypes.CDLL("libc.so.6").malloc_trim(0)


def _do_unload(reason: str = "manual") -> bool:
    global _model, _last_unload_reason
    was_loaded = _model is not None
    _model = None
    _last_unload_reason = reason
    if was_loaded:
        _cleanup_runtime_memory()
    return was_loaded


def _validate_text(value: str, field: str = "text"):
    if len(value or "") > MAX_TEXT_CHARS:
        raise HTTPException(413, f"{field} is too long; max {MAX_TEXT_CHARS} characters")


async def _save_upload_tmp(upload: UploadFile | None) -> str | None:
    if not upload or not upload.filename:
        return None

    fd, path = tempfile.mkstemp(suffix=".wav")
    size = 0
    try:
        while True:
            chunk = await upload.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                raise HTTPException(413, f"Uploaded audio is too large; max {MAX_UPLOAD_BYTES // (1024 * 1024)} MB")
            os.write(fd, chunk)
    except Exception:
        with suppress(Exception):
            os.unlink(path)
        raise
    finally:
        os.close(fd)
    return path


def _do_load():
    global _model, _sample_rate
    if _model is not None:
        return
    from voxcpm import VoxCPM
    _model = VoxCPM.from_pretrained(
        VOXCPM2_MODEL_ID,
        device=VOXCPM2_DEVICE,
        optimize=VOXCPM2_OPTIMIZE,
        load_denoiser=False,
    )
    _sample_rate = _model.tts_model.sample_rate


async def _ensure_loaded():
    global _last_used
    async with _lock:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _do_load)
        _last_used = time.monotonic()


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


@app.get("/health")
async def health():
    idle_seconds = round(time.monotonic() - _last_used, 1) if _model is not None and _last_used else 0
    return {
        "model": "VoxCPM2",
        "status": "ok",
        "ready": _model is not None,
        "model_loaded": _model is not None,
        "sample_rate": _sample_rate,
        "rss_mb": _rss_mb(),
        "idle_seconds": idle_seconds,
        "idle_timeout_s": MODEL_IDLE_SECONDS,
        "last_unload_reason": _last_unload_reason,
    }


@app.post("/load")
async def load_endpoint():
    await _ensure_loaded()
    return {"status": "loaded", "sample_rate": _sample_rate, "rss_mb": _rss_mb()}


@app.post("/unload")
async def unload_endpoint():
    async with _lock:
        unloaded = await asyncio.to_thread(_do_unload, "manual")
    return {"status": "unloaded" if unloaded else "not_loaded", "sample_rate": _sample_rate, "rss_mb": _rss_mb()}


@app.post("/synthesize")
async def synthesize(
    text: str = Form(...),
    dialect: str = Form("msa"),
    gender: str = Form(""),
    age: str = Form(""),
    style: str = Form(""),
    cfg_value: float = Form(2.0),
    inference_timesteps: int = Form(10),
    model_input_override: str = Form(""),
    reference_wav: UploadFile | None = File(None),
    prompt_wav: UploadFile | None = File(None),
    prompt_text: str | None = Form(None),
):
    _validate_text(text)
    _validate_text(model_input_override, "model_input_override")
    _validate_text(prompt_text or "", "prompt_text")

    ref_tmp: str | None = None
    prompt_tmp: str | None = None

    try:
        ref_tmp = await _save_upload_tmp(reference_wav)
        prompt_tmp = await _save_upload_tmp(prompt_wav)

        out_path = OUT_DIR / f"voxcpm2_{uuid.uuid4().hex[:12]}.wav"
        # A non-empty override is used verbatim (frontend manual-edit mode); otherwise force
        # Arabic + dialect (+ optional gender/age) via the leading-parenthetical style cue.
        override = (model_input_override or "").strip()
        if override:
            eff_text = override
        else:
            # Leading parenthetical cue = free style (optional) + persona + forced Arabic dialect.
            parts = [p for p in ((style or "").strip(), _persona(gender, age),
                                 _arabic_descriptor(dialect)) if p]
            eff_text = f"({', '.join(parts)}) {text}"
        kwargs: dict = {
            "text": eff_text,
            "cfg_value": cfg_value,
            "inference_timesteps": inference_timesteps,
        }
        if ref_tmp:
            kwargs["reference_wav_path"] = ref_tmp
        if prompt_tmp:
            kwargs["prompt_wav_path"] = prompt_tmp
        if prompt_text and prompt_text.strip():
            kwargs["prompt_text"] = prompt_text.strip()

        async with _lock:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, _do_load)
            t0 = time.perf_counter()
            wav = await loop.run_in_executor(None, lambda: _model.generate(**kwargs))
            elapsed = time.perf_counter() - t0
            global _last_used
            _last_used = time.monotonic()

    except Exception as e:
        raise HTTPException(500, str(e))
    finally:
        if ref_tmp:
            os.unlink(ref_tmp)
        if prompt_tmp:
            os.unlink(prompt_tmp)

    sf.write(str(out_path), wav, _sample_rate)
    duration = len(wav) / _sample_rate

    result = {
        "filename": out_path.name,
        "model": "voxcpm2",
        "model_input": eff_text,
        "elapsed_s": round(elapsed, 2),
        "duration_s": round(duration, 2),
        "rtf": round(elapsed / max(duration, 0.01), 3),
        "sample_rate": _sample_rate,
    }
    _write_sidecar(out_path, {
        "text": text,
        "instruct": prompt_text,      # prompt text / parenthetical instruction
        "params": {
            "style": style,
            "cfg_value": cfg_value,
            "inference_timesteps": inference_timesteps,
        },
        "prompt_text": prompt_text,
        "has_reference_audio": bool(ref_tmp),
        "has_prompt_audio": bool(prompt_tmp),
        "created": time.time(),
        **result,
    })
    del wav
    if CLEANUP_AFTER_SYNTH:
        _cleanup_runtime_memory()
    return result


def _write_sidecar(wav_path: pathlib.Path, meta: dict):
    try:
        wav_path.with_suffix(".json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass  # never fail synthesis over a sidecar write


@app.get("/audio/{filename}")
async def get_audio(filename: str):
    path = OUT_DIR / pathlib.Path(filename).name
    if not path.exists():
        raise HTTPException(404, "Audio file not found")
    return FileResponse(str(path), media_type="audio/wav")


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8083, log_level="info")
