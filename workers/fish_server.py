"""Fish Audio S2 Pro TTS worker — run inside the arabic-tts conda env (port 8081)."""
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

WORKDIR   = pathlib.Path("~/tts-05172026").expanduser()
S2_BIN    = WORKDIR / "s2.cpp" / "build" / "s2"
MODEL     = WORKDIR / "model" / "s2-pro-q6_k.gguf"
TOKENIZER = WORKDIR / "model" / "tokenizer.json"
OUT_DIR   = WORKDIR / "outputs"
OUT_DIR.mkdir(parents=True, exist_ok=True)

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
        raise HTTPException(503, "Model GGUF not found — download s2-pro-q6_k.gguf first")

    out_path = OUT_DIR / f"fish_{uuid.uuid4().hex[:12]}.wav"
    ref_tmp: str | None = None

    if reference_audio and reference_audio.filename:
        data = await reference_audio.read()
        fd, ref_tmp = tempfile.mkstemp(suffix=".wav")
        os.write(fd, data)
        os.close(fd)

    cmd = [
        str(S2_BIN),
        "-m", str(MODEL),
        "-t", str(TOKENIZER),
        "--text", text,
        "-c", "0",
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
    result = {
        "filename": out_path.name,
        "model": "fish",
        "elapsed_s": round(elapsed, 2),
        "duration_s": round(info.duration, 2),
        "rtf": round(elapsed / max(info.duration, 0.01), 3),
        "sample_rate": info.samplerate,
    }
    _write_sidecar(out_path, {
        "text": text,
        "params": {
            "temperature": temperature,
            "top_p": top_p,
            "top_k": top_k,
            "max_tokens": max_tokens,
        },
        "reference_text": reference_text,
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
    uvicorn.run(app, host="127.0.0.1", port=8081, log_level="info")
