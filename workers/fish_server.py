"""Fish Audio S2 Pro TTS worker — run inside the arabic-tts conda env (port 8081)."""
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

WORKDIR   = pathlib.Path(os.getenv("TTS_WORKDIR", "~/tts-05172026")).expanduser()
S2_BIN    = pathlib.Path(os.getenv("S2_BIN", str(WORKDIR / "s2.cpp" / "build" / "s2"))).expanduser()
TOKENIZER = pathlib.Path(os.getenv("FISH_TOKENIZER", str(WORKDIR / "model" / "tokenizer.json"))).expanduser()
OUT_DIR   = pathlib.Path(os.getenv("FISH_OUT_DIR", str(WORKDIR / "outputs"))).expanduser()
OUT_DIR.mkdir(parents=True, exist_ok=True)
S2_CUDA_DEVICE = os.getenv("S2_CUDA_DEVICE", "-1")
S2_THREADS = os.getenv("S2_THREADS", str(os.cpu_count() or 4))

# Arabic is forced for every request; the dialect steers the in-text [tag] S2 reads.
_ARABIC_DIALECTS = {
    "msa":       "Modern Standard Arabic",
    "egyptian":  "Egyptian Arabic",
    "gulf":      "Gulf Arabic",
    "levantine": "Levantine Arabic",
    "iraqi":     "Iraqi Arabic",
    "maghrebi":  "Maghrebi Arabic",
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

_MODEL_CANDIDATES = [
    "s2-pro-q4_k_m.gguf",
    "s2-pro-q5_k_m.gguf",
    "s2-pro-q6_k.gguf",
    "s2-pro-q3_k.gguf",
    "s2-pro-q2_k.gguf",
]
if os.getenv("FISH_MODEL"):
    MODEL = pathlib.Path(os.environ["FISH_MODEL"]).expanduser()
else:
    MODEL = next(
        (WORKDIR / "model" / name for name in _MODEL_CANDIDATES if (WORKDIR / "model" / name).exists()),
        WORKDIR / "model" / _MODEL_CANDIDATES[0],
    )

app = FastAPI(title="Fish S2 Pro Worker", docs_url=None, redoc_url=None)
_lock = asyncio.Lock()


@app.get("/health")
async def health():
    return {
        "model": "Fish S2 Pro",
        "status": "ok",
        "ready": S2_BIN.exists() and MODEL.exists(),
        "binary_exists": S2_BIN.exists(),
        "model_exists": MODEL.exists(),
        "model_loaded": True,  # always ready (subprocess-based)
    }


@app.post("/synthesize")
async def synthesize(
    text: str = Form(...),
    dialect: str = Form("msa"),
    gender: str = Form(""),
    age: str = Form(""),
    temperature: float = Form(0.7),
    top_p: float = Form(0.8),
    top_k: int = Form(30),
    max_tokens: int = Form(2048),
    reference_audio: UploadFile | None = File(None),
    reference_text: str | None = Form(None),
):
    if not S2_BIN.exists():
        raise HTTPException(503, "s2 binary not built — run create_env.sh first")
    if not MODEL.exists():
        raise HTTPException(503, f"Model GGUF not found at {MODEL}")

    out_path = OUT_DIR / f"fish_{uuid.uuid4().hex[:12]}.wav"
    ref_tmp: str | None = None

    # Force Arabic + dialect (+ optional gender/age persona) via a free-form S2 tag.
    desc = _arabic_descriptor(dialect)
    persona = _persona(gender, age)
    tag = f"{persona} voice speaking in {desc}" if persona else f"speak in {desc}"
    eff_text = f"[{tag}] {text}"

    if reference_audio and reference_audio.filename:
        data = await reference_audio.read()
        fd, ref_tmp = tempfile.mkstemp(suffix=".wav")
        os.write(fd, data)
        os.close(fd)

    cmd = [
        str(S2_BIN),
        "-m", str(MODEL),
        "-t", str(TOKENIZER),
        "--text", eff_text,
        "-c", S2_CUDA_DEVICE,
        "-threads", S2_THREADS,
        "--normalize",
        "--trim-silence",
        "--temperature", str(temperature),
        "--top-p", str(top_p),
        "--top-k", str(top_k),
        "--max-tokens", str(max_tokens),
        "-o", str(out_path),
    ]
    if ref_tmp and reference_text:
        cmd += ["-pa", ref_tmp, "-pt", reference_text]

    try:
        async with _lock:
            t0 = time.perf_counter()
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            elapsed = time.perf_counter() - t0
    finally:
        if ref_tmp:
            os.unlink(ref_tmp)

    if proc.returncode != 0:
        raise HTTPException(500, f"s2 error: {stderr.decode()[-1500:]}")
    if not out_path.exists():
        raise HTTPException(500, "s2 produced no output file")

    info = sf.info(str(out_path))
    return {
        "filename": out_path.name,
        "model": "fish",
        "model_input": eff_text,
        "elapsed_s": round(elapsed, 2),
        "duration_s": round(info.duration, 2),
        "rtf": round(elapsed / max(info.duration, 0.01), 3),
        "sample_rate": info.samplerate,
    }


@app.get("/audio/{filename}")
async def get_audio(filename: str):
    path = OUT_DIR / pathlib.Path(filename).name
    if not path.exists():
        raise HTTPException(404, "Audio file not found")
    return FileResponse(str(path), media_type="audio/wav")


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8081, log_level="info")
