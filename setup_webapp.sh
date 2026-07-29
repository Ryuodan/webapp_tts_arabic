#!/usr/bin/env bash
# Install FastAPI/uvicorn into each TTS conda env so the worker servers can run.
# Run once before starting the webapp: bash setup_webapp.sh
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONDA_EXE="${CONDA_EXE:-/home/m.sayed/miniconda3/bin/conda}"
GATEWAY_ENV="${GATEWAY_ENV:-arabic-tts-web}"
PKGS=(fastapi "uvicorn[standard]" python-multipart soundfile)
# Cohere Transcribe (INT8) needs the model stack on top of PKGS; bitsandbytes does the
# 8-bit dequant, librosa decodes/resamples arbitrary uploads to the model's 16 kHz mono.
ASR_ENV="${ASR_ENV:-transcribe-asr}"
# transformers is floored, not left open: CohereAsrForConditionalGeneration landed in 5.8
# (the checkpoint reports transformers_version 5.8.1). Without the floor, re-running this
# against an existing env leaves an older transformers in place and the model class is
# simply missing at load time.
ASR_PKGS=("transformers>=5.8" accelerate bitsandbytes librosa)

if [[ ! -x "$CONDA_EXE" ]]; then
  CONDA_EXE="$(command -v conda || true)"
fi

if [[ -z "$CONDA_EXE" ]]; then
  echo "Could not find conda. Set CONDA_EXE=/path/to/conda and retry." >&2
  exit 1
fi

env_exists() {
  "$CONDA_EXE" env list | grep -q "^$1[[:space:]]"
}

if ! env_exists "$GATEWAY_ENV"; then
  echo "Creating gateway conda env: ${GATEWAY_ENV}"
  "$CONDA_EXE" env create -f "${SCRIPT_DIR}/environment.yml"
fi

echo "Installing gateway dependencies in ${GATEWAY_ENV}..."
"$CONDA_EXE" run -n "$GATEWAY_ENV" python -m pip install --quiet -r "${SCRIPT_DIR}/requirements.txt"

for env_name in omnivoice-tts voxcpm2-tts; do
  if env_exists "$env_name"; then
    echo "Installing worker web dependencies in ${env_name}..."
    "$CONDA_EXE" run -n "$env_name" python -m pip install --quiet "${PKGS[@]}"
  else
    echo "Skipping missing worker env: ${env_name}"
  fi
done

# ── ASR env ─────────────────────────────────────────────────────
# Unlike the TTS envs (which ship with their models), this one is created here.
# pip's default torch wheel is the CUDA build on Linux — the INT8 checkpoint needs a GPU.
if ! env_exists "$ASR_ENV"; then
  echo "Creating ASR conda env: ${ASR_ENV}"
  "$CONDA_EXE" create -y -q -n "$ASR_ENV" python=3.11
fi
echo "Installing ASR dependencies in ${ASR_ENV} (torch + transformers — this takes a few minutes)..."
"$CONDA_EXE" run -n "$ASR_ENV" python -m pip install --quiet torch "${PKGS[@]}" "${ASR_PKGS[@]}"

echo ""
echo "All done. Run: bash start.sh"
