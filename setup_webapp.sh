#!/usr/bin/env bash
# Install FastAPI/uvicorn into each TTS conda env so the worker servers can run.
# Run once before starting the webapp: bash setup_webapp.sh
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONDA_EXE="${CONDA_EXE:-/home/m.sayed/miniconda3/bin/conda}"
GATEWAY_ENV="${GATEWAY_ENV:-arabic-tts-web}"
PKGS=(fastapi "uvicorn[standard]" python-multipart soundfile)

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

echo ""
echo "All done. Run: bash start.sh"
