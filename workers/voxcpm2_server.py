"""VoxCPM2 TTS worker — run inside the voxcpm2-tts conda env (port 8083).
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
OUT_DIR = pathlib.Path(os.getenv("VOXCPM2_OUT_DIR", str(WORKDIR / "outputs_voxcpm2"))).expanduser()
OUT_DIR.mkdir(parents=True, exist_ok=True)
VOXCPM2_MODEL_ID = os.getenv("VOXCPM2_MODEL_ID", "openbmb/VoxCPM2")
VOXCPM2_DEVICE = os.getenv("VOXCPM2_DEVICE", "auto")
VOXCPM2_OPTIMIZE = os.getenv("VOXCPM2_OPTIMIZE", "0").lower() in {"1", "true", "yes", "on"}

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
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _do_load)


@app.get("/health")
async def health():
    return {
        "model": "VoxCPM2",
        "status": "ok",
        "ready": _model is not None,
        "model_loaded": _model is not None,
        "sample_rate": _sample_rate,
    }


@app.post("/load")
async def load_endpoint():
    await _ensure_loaded()
    return {"status": "loaded", "sample_rate": _sample_rate}


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
    await _ensure_loaded()

    ref_tmp: str | None = None
    prompt_tmp: str | None = None

    try:
        if reference_wav and reference_wav.filename:
            data = await reference_wav.read()
            fd, ref_tmp = tempfile.mkstemp(suffix=".wav")
            os.write(fd, data)
            os.close(fd)

        if prompt_wav and prompt_wav.filename:
            data = await prompt_wav.read()
            fd, prompt_tmp = tempfile.mkstemp(suffix=".wav")
            os.write(fd, data)
            os.close(fd)

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
            loop = asyncio.get_event_loop()
            t0 = time.perf_counter()
            wav = await loop.run_in_executor(None, lambda: _model.generate(**kwargs))
            elapsed = time.perf_counter() - t0

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
