#!/usr/bin/env bash
# Run the test suite in the gateway conda env.
# Usage: bash test.sh [pytest args...]
#   bash test.sh                     # everything
#   bash test.sh -m "not slow"       # skip the tests that start real processes
#   bash test.sh tests/test_gateway.py -v
#
# No GPU, no API key and no worker env needed: the model libraries and the LLM client
# are faked, so this runs anywhere the gateway itself runs.
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONDA_EXE="${CONDA_EXE:-/home/m.sayed/miniconda3/bin/conda}"
GATEWAY_ENV="${GATEWAY_ENV:-arabic-tts-web}"

if [[ ! -x "$CONDA_EXE" ]]; then
  CONDA_EXE="$(command -v conda || true)"
fi

if [[ -n "$CONDA_EXE" ]] && "$CONDA_EXE" env list | grep -q "^${GATEWAY_ENV}[[:space:]]"; then
  exec "$CONDA_EXE" run -n "$GATEWAY_ENV" --no-capture-output \
    python -m pytest "${@:-$SCRIPT_DIR/tests}"
fi

echo "Gateway env '${GATEWAY_ENV}' not found — using the current Python." >&2
exec python -m pytest "${@:-$SCRIPT_DIR/tests}"
