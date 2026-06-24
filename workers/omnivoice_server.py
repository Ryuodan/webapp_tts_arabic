"""OmniVoice TTS worker — run inside the omnivoice-tts conda env (port 8082).
Model is loaded lazily on first synthesis request.
"""
import asyncio
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
OMNIVOICE_MODEL_ID = os.getenv("OMNIVOICE_MODEL_ID", "k2-fsa/OmniVoice")
OMNIVOICE_DEVICE = os.getenv("OMNIVOICE_DEVICE", "auto")

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


# gender + age are native OmniVoice voice-design attributes; empty = model's choice.
_GENDERS = {"male": "male", "female": "female"}
_AGES = {"young": "young adult", "middle": "middle-aged", "old": "elderly"}


def _attr(mapping: dict, value: str) -> str:
    return mapping.get((value or "").strip().lower(), "")

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
    device = "cuda:0" if OMNIVOICE_DEVICE == "auto" and torch.cuda.is_available() else (
        "cpu" if OMNIVOICE_DEVICE == "auto" else OMNIVOICE_DEVICE
    )
    dtype  = torch.float16 if torch.cuda.is_available() else torch.float32
    _model = OmniVoice.from_pretrained(OMNIVOICE_MODEL_ID, device_map=device, dtype=dtype)


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
    dialect: str = Form("msa"),
    gender: str = Form(""),
    age: str = Form(""),
    speaker: str = Form(""),
    model_input_override: str = Form(""),
    model_instruct_override: str = Form(""),
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
    # Non-empty overrides are used verbatim (frontend manual-edit mode).
    eff_text = (model_input_override or "").strip() or text
    kwargs: dict = {"text": eff_text}
    if ref_tmp:
        kwargs["ref_audio"] = ref_tmp
    if ref_text and ref_text.strip():
        kwargs["ref_text"] = ref_text.strip()

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

    result = {
        "filename": out_path.name,
        "model": "omnivoice",
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
        "params": {"speaker": speaker},
        "reference_text": ref_text,
        "has_reference_audio": bool(ref_tmp),
        "created": time.time(),
        **result,
    })
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
