#!/usr/bin/env bash
# Start all TTS workers + the main gateway server.
# Usage: bash webapp/start.sh [--port 8080]
#
# Workers run as background processes; gateway runs in the foreground.
# Kill with Ctrl-C (trap shuts down all workers automatically).

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PIDS=()

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

  if ! conda env list | grep -q "^${env_name} "; then
    log "⚠  Conda env '${env_name}' not found — skipping ${script##*/}"
    return
  fi

  log "Starting ${script##*/} (${env_name}, port ${port})..."
  conda run -n "${env_name}" --no-capture-output \
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

# Try to use the gateway with the current active Python env
# (must have fastapi, httpx, uvicorn installed — run setup_webapp.sh first)
python "${SCRIPT_DIR}/server.py" --port "$PORT" 2>/dev/null || \
  uvicorn webapp.server:app --host 0.0.0.0 --port "$PORT" --app-dir "$(dirname "${SCRIPT_DIR}")"
