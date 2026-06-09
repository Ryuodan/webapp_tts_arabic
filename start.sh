#!/usr/bin/env bash
# Start all TTS workers + the main gateway server.
# Usage: bash webapp/start.sh [--port 8080]
#
# Workers run as background processes; gateway runs in the foreground.
# Kill with Ctrl-C (trap shuts down all workers automatically).

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PIDS=()
CONDA_EXE="${CONDA_EXE:-/home/m.sayed/miniconda3/bin/conda}"
GATEWAY_ENV="${GATEWAY_ENV:-arabic-tts-web}"

if [[ ! -x "$CONDA_EXE" ]]; then
  CONDA_EXE="$(command -v conda || true)"
fi

if [[ -z "$CONDA_EXE" ]]; then
  echo "Could not find conda. Set CONDA_EXE=/path/to/conda and retry." >&2
  exit 1
fi

# ── optional flags ──────────────────────────────────────────────
PORT=8080
while [[ $# -gt 0 ]]; do
  case $1 in --port) PORT=$2; shift 2;; *) shift;; esac
done

log() { echo "[$(date +%H:%M:%S)] $*"; }

# ── helper: start a worker in a conda env ───────────────────────
start_worker() {
  local env_name=$1
  local script=$2
  local port=$3

  if ! "$CONDA_EXE" env list | grep -q "^${env_name}[[:space:]]"; then
    log "⚠  Conda env '${env_name}' not found — skipping ${script##*/}"
    return
  fi

  log "Starting ${script##*/} (${env_name}, port ${port})..."
  "$CONDA_EXE" run -n "${env_name}" --no-capture-output \
    python "${script}" &
  PIDS+=($!)
  log "  PID ${PIDS[-1]}"
}

# ── cleanup on exit ──────────────────────────────────────────────
cleanup() {
  log "Shutting down workers..."
  for pid in "${PIDS[@]}"; do
    kill "$pid" 2>/dev/null && log "  killed PID $pid"
  done
  wait 2>/dev/null
  log "Done."
}
trap cleanup EXIT INT TERM

# ── start workers ───────────────────────────────────────────────
start_worker arabic-tts    "${SCRIPT_DIR}/workers/fish_server.py"      8081
start_worker omnivoice-tts "${SCRIPT_DIR}/workers/omnivoice_server.py" 8082
start_worker voxcpm2-tts   "${SCRIPT_DIR}/workers/voxcpm2_server.py"   8083

# give workers a moment to bind their ports
log "Waiting for workers to start (3s)..."
sleep 3

# ── start gateway ────────────────────────────────────────────────
log "Starting gateway on 0.0.0.0:${PORT}..."
log "Open: http://localhost:${PORT}"
echo ""

if "$CONDA_EXE" env list | grep -q "^${GATEWAY_ENV}[[:space:]]"; then
  "$CONDA_EXE" run -n "$GATEWAY_ENV" --no-capture-output \
    python "${SCRIPT_DIR}/server.py" --port "$PORT"
else
  log "⚠  Gateway env '${GATEWAY_ENV}' not found; using current Python."
  python "${SCRIPT_DIR}/server.py" --port "$PORT"
fi
