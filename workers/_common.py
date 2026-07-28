"""Boilerplate shared by every worker in this folder.

Workers are launched as scripts (`python workers/<name>_server.py`, see start.sh),
so their own directory is on sys.path and `from _common import ...` resolves.
"""
import json
import os
import pathlib

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

WORKDIR = pathlib.Path(os.getenv("TTS_WORKDIR", "~/tts-05172026")).expanduser()


def output_dir(env_var: str, default_name: str) -> pathlib.Path:
    """Resolve a worker's output directory from its env override and create it."""
    path = pathlib.Path(os.getenv(env_var, str(WORKDIR / default_name))).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_sidecar(wav_path: pathlib.Path, meta: dict) -> None:
    """Persist a run's inputs/metrics next to its wav; the gateway reads these for /history."""
    try:
        wav_path.with_suffix(".json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass  # never fail a request over a sidecar write


def register_audio_route(app: FastAPI, out_dir: pathlib.Path) -> None:
    """Expose GET /audio/{filename} for direct worker access (the gateway serves its own copy)."""

    @app.get("/audio/{filename}")
    async def get_audio(filename: str):
        path = out_dir / pathlib.Path(filename).name   # basename only — no path traversal
        if not path.exists():
            raise HTTPException(404, "Audio file not found")
        return FileResponse(str(path), media_type="audio/wav")
