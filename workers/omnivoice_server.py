"""OmniVoice TTS worker — run inside the omnivoice-tts conda env (port 8082).
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
OUT_DIR = pathlib.Path(os.getenv("OMNIVOICE_OUT_DIR", str(WORKDIR / "outputs_omnivoice"))).expanduser()
OUT_DIR.mkdir(parents=True, exist_ok=True)
REPO_DIR = pathlib.Path(__file__).resolve().parents[1]
OMNIVOICE_BASE_MODEL_ID = os.getenv("OMNIVOICE_BASE_MODEL_ID", "k2-fsa/OmniVoice")
# Best Saudi-HQ fine-tuned checkpoint (see models/omnivoice/BEST_FINETUNED_CHECKPOINT.md).
# The repo ships it as split parts — run scripts/assemble_omnivoice_checkpoint.sh once after
# pulling to produce model.safetensors. The training-project symlink is the fallback source.
REPO_CHECKPOINT = REPO_DIR / "models" / "omnivoice" / "best_finetuned"
FINETUNED_CHECKPOINT = WORKDIR / "omnivoice" / "checkpoints" / "best_finetuned"


def _finetuned_model_id() -> str | None:
    env = os.getenv("OMNIVOICE_FINETUNED_MODEL_ID")
    if env:
        return env
    for candidate in (REPO_CHECKPOINT, FINETUNED_CHECKPOINT):
        if (candidate / "model.safetensors").exists():
            return str(candidate)
    return None


# Selectable model variants; "finetuned" is present only when its weights exist.
MODEL_VARIANTS = {"base": OMNIVOICE_BASE_MODEL_ID}
_ft_id = _finetuned_model_id()
if _ft_id:
    MODEL_VARIANTS["finetuned"] = _ft_id
DEFAULT_VARIANT = "finetuned" if "finetuned" in MODEL_VARIANTS else "base"
OMNIVOICE_DEVICE = os.getenv("OMNIVOICE_DEVICE", "auto")
MODEL_IDLE_SECONDS = int(os.getenv("TTS_MODEL_IDLE_SECONDS", "900"))
MAX_TEXT_CHARS = int(os.getenv("TTS_MAX_TEXT_CHARS", "8000"))
MAX_UPLOAD_BYTES = int(os.getenv("TTS_MAX_UPLOAD_BYTES", str(25 * 1024 * 1024)))
CLEANUP_AFTER_SYNTH = os.getenv("TTS_CLEANUP_AFTER_SYNTH", "1").lower() not in {"0", "false", "no", "off"}

# Arabic is forced for every request. OmniVoice selects the dialect via its NATIVE language
# code (ISO 639-3), not the instruct field: instruct is a closed EN/ZH voice-design vocab
# (gender/age/pitch/style/accent) with no Arabic accent token, so any Arabic string placed
# there is rejected with "Unsupported instruct items". Each dialect maps to a real OmniVoice
# language code instead — these are all present in the model's 600+ language set.
_ARABIC_DIALECT_LANG = {
    "msa":      "arb",   # Modern Standard Arabic
    "saudi":    "ars",   # Najdi (central Saudi) Arabic
    "egyptian": "arz",   # Egyptian Arabic
}


def _dialect_language(dialect: str) -> str:
    return _ARABIC_DIALECT_LANG.get((dialect or "msa").strip().lower(), _ARABIC_DIALECT_LANG["msa"])


# Built-in cloned voices bundled with the repo: voices/<id>/voice.json + reference wav.
VOICES_DIR = pathlib.Path(os.getenv("TTS_VOICES_DIR", str(REPO_DIR / "voices"))).expanduser()


def _load_builtin_voices() -> dict:
    voices = {}
    for meta_path in sorted(VOICES_DIR.glob("*/voice.json")):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            wav = meta_path.parent / meta["ref_audio"]
            if wav.is_file():
                meta["ref_audio_path"] = str(wav)
                voices[str(meta.get("id", meta_path.parent.name)).lower()] = meta
        except Exception:
            continue  # a broken voice dir must not take the worker down
    return voices


_BUILTIN_VOICES = _load_builtin_voices()


# gender + age are native OmniVoice voice-design attributes; empty = model's choice.
_GENDERS = {"male": "male", "female": "female"}
_AGES = {"young": "young adult", "middle": "middle-aged", "old": "elderly"}


def _attr(mapping: dict, value: str) -> str:
    return mapping.get((value or "").strip().lower(), "")

app = FastAPI(title="OmniVoice Worker", docs_url=None, redoc_url=None)
_models = {}            # variant -> OmniVoice instance
_active_variant = ""    # most recently loaded/used variant ("" = none)
_lock = asyncio.Lock()
_idle_task: asyncio.Task | None = None
_last_used_by_variant = {}
_last_unload_reason = ""
SAMPLE_RATE = 24_000


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


def _do_unload(reason: str = "manual", variant: str | None = None) -> bool:
    global _active_variant, _last_unload_reason
    if variant:
        was_loaded = variant in _models
        _models.pop(variant, None)
        _last_used_by_variant.pop(variant, None)
        if _active_variant == variant:
            _active_variant = next(iter(_models), "")
    else:
        was_loaded = bool(_models)
        _models.clear()
        _last_used_by_variant.clear()
        _active_variant = ""
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


def _do_load(variant: str = ""):
    global _active_variant
    variant = variant or DEFAULT_VARIANT
    if variant in _models:
        _active_variant = variant
        return _models[variant]
    import torch
    from omnivoice import OmniVoice
    device = "cuda:0" if OMNIVOICE_DEVICE == "auto" and torch.cuda.is_available() else (
        "cpu" if OMNIVOICE_DEVICE == "auto" else OMNIVOICE_DEVICE
    )
    dtype  = torch.float16 if torch.cuda.is_available() else torch.float32
    model = OmniVoice.from_pretrained(MODEL_VARIANTS[variant], device_map=device, dtype=dtype)
    _models[variant] = model
    _active_variant = variant
    return model


async def _ensure_loaded(variant: str = ""):
    async with _lock:
        loop = asyncio.get_running_loop()
        loaded = await loop.run_in_executor(None, _do_load, variant)
        _last_used_by_variant[variant or _active_variant or DEFAULT_VARIANT] = time.monotonic()
        return loaded


async def _idle_unload_loop():
    sleep_s = min(60, max(5, MODEL_IDLE_SECONDS // 3 if MODEL_IDLE_SECONDS else 60))
    while True:
        await asyncio.sleep(sleep_s)
        if MODEL_IDLE_SECONDS <= 0 or not _models:
            continue
        now = time.monotonic()
        stale = [
            variant for variant in list(_models)
            if now - _last_used_by_variant.get(variant, now) >= MODEL_IDLE_SECONDS
        ]
        if not stale:
            continue
        async with _lock:
            now = time.monotonic()
            for variant in list(_models):
                if now - _last_used_by_variant.get(variant, now) >= MODEL_IDLE_SECONDS:
                    await asyncio.to_thread(_do_unload, "idle", variant)


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
    loaded_variants = sorted(_models)
    active_variant = _active_variant if _active_variant in _models else ""
    idle_seconds = 0
    if active_variant and _last_used_by_variant.get(active_variant):
        idle_seconds = round(time.monotonic() - _last_used_by_variant[active_variant], 1)
    return {
        "model": "OmniVoice",
        "variants": MODEL_VARIANTS,
        "default_variant": DEFAULT_VARIANT,
        "loaded_variant": active_variant or None,
        "loaded_variants": loaded_variants,
        "model_id": MODEL_VARIANTS[active_variant or DEFAULT_VARIANT],
        "finetuned_available": "finetuned" in MODEL_VARIANTS,
        "voices": sorted(_BUILTIN_VOICES),
        "status": "ok",
        "ready": bool(_models),
        "model_loaded": bool(_models),
        "rss_mb": _rss_mb(),
        "idle_seconds": idle_seconds,
        "idle_timeout_s": MODEL_IDLE_SECONDS,
        "last_unload_reason": _last_unload_reason,
    }


@app.post("/load")
async def load_endpoint(variant: str = ""):
    variant = (variant or "").strip().lower()
    if variant and variant not in MODEL_VARIANTS:
        raise HTTPException(400, f"Model variant '{variant}' is not available on this server "
                                 f"(available: {', '.join(sorted(MODEL_VARIANTS))})")
    await _ensure_loaded(variant)
    return {
        "status": "loaded",
        "variant": _active_variant,
        "loaded_variants": sorted(_models),
        "rss_mb": _rss_mb(),
    }


@app.post("/unload")
async def unload_endpoint():
    async with _lock:
        unloaded = await asyncio.to_thread(_do_unload, "manual")
    return {"status": "unloaded" if unloaded else "not_loaded", "rss_mb": _rss_mb()}


@app.post("/synthesize")
async def synthesize(
    text: str = Form(...),
    dialect: str = Form("msa"),
    gender: str = Form(""),
    age: str = Form(""),
    speaker: str = Form(""),
    voice: str = Form(""),
    variant: str = Form(""),
    model_input_override: str = Form(""),
    model_instruct_override: str = Form(""),
    ref_audio: UploadFile | None = File(None),
    ref_text: str | None = Form(None),
):
    _validate_text(text)
    _validate_text(model_input_override, "model_input_override")
    _validate_text(ref_text or "", "ref_text")

    voice_id = (voice or "").strip().lower()
    builtin = _BUILTIN_VOICES.get(voice_id) if voice_id else None
    if voice_id and not builtin:
        raise HTTPException(400, f"Unknown built-in voice: {voice_id}")

    req_variant = (variant or "").strip().lower() or DEFAULT_VARIANT
    if req_variant not in MODEL_VARIANTS:
        available = ", ".join(sorted(MODEL_VARIANTS))
        raise HTTPException(400, f"Model variant '{req_variant}' is not available on this server "
                                 f"(available: {available})")

    ref_tmp = await _save_upload_tmp(ref_audio)

    out_path = OUT_DIR / f"omnivoice_{uuid.uuid4().hex[:12]}.wav"
    # Non-empty overrides are used verbatim (frontend manual-edit mode).
    eff_text = (model_input_override or "").strip() or text
    kwargs: dict = {"text": eff_text}
    # A user-uploaded reference always wins over a built-in voice.
    if ref_tmp:
        kwargs["ref_audio"] = ref_tmp
    elif builtin:
        kwargs["ref_audio"] = builtin["ref_audio_path"]
    if ref_text and ref_text.strip():
        kwargs["ref_text"] = ref_text.strip()
    elif not ref_tmp and builtin and builtin.get("ref_text"):
        kwargs["ref_text"] = builtin["ref_text"]

    # The Arabic dialect rides OmniVoice's language code — never the instruct field.
    kwargs["language"] = _dialect_language(dialect)

    instruct_override = (model_instruct_override or "").strip()
    if instruct_override:
        kwargs["instruct"] = instruct_override
    else:
        # Voice-design instruct = optional user prompt + gender/age, all from OmniVoice's closed
        # EN/ZH vocab. Omitted entirely when empty so the model picks a voice on its own.
        attrs = []
        if speaker and speaker.strip():
            attrs.append(speaker.strip())
        for frag in (_attr(_GENDERS, gender), _attr(_AGES, age)):
            if frag:
                attrs.append(frag)
        if attrs:
            # OmniVoice's documented voice-design kwarg is `instruct` (older builds used `speaker`).
            kwargs["instruct"] = ", ".join(attrs)

    try:
        async with _lock:
            loop = asyncio.get_running_loop()
            model = await loop.run_in_executor(None, _do_load, req_variant)
            t0 = time.perf_counter()
            audio = await loop.run_in_executor(None, lambda: model.generate(**kwargs))
            elapsed = time.perf_counter() - t0
            _last_used_by_variant[req_variant] = time.monotonic()
    except Exception as e:
        raise HTTPException(500, str(e))
    finally:
        if ref_tmp:
            os.unlink(ref_tmp)

    audio_data = audio[0]
    sf.write(str(out_path), audio_data, SAMPLE_RATE)
    duration = len(audio_data) / SAMPLE_RATE

    result = {
        "filename": out_path.name,
        "model": "omnivoice",
        "model_id": MODEL_VARIANTS[req_variant],
        "model_variant": req_variant,
        "voice": voice_id,
        "model_input": eff_text,
        "model_instruct": kwargs.get("instruct", ""),
        "model_language": kwargs.get("language", ""),
        "elapsed_s": round(elapsed, 2),
        "duration_s": round(duration, 2),
        "rtf": round(elapsed / max(duration, 0.01), 3),
        "sample_rate": SAMPLE_RATE,
    }
    _write_sidecar(out_path, {
        "text": text,
        "instruct": speaker,          # voice description / instruction
        "params": {"speaker": speaker, "voice": voice_id, "variant": req_variant},
        "reference_text": kwargs.get("ref_text", ref_text),
        "has_reference_audio": "ref_audio" in kwargs,
        "created": time.time(),
        **result,
    })
    del audio, audio_data
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
    uvicorn.run(app, host="127.0.0.1", port=8082, log_level="info")
