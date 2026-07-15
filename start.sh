#!/usr/bin/env bash
# Start enabled TTS workers + the main gateway server.
# Usage: bash start.sh [--port 8025]
#
# If a previous instance is already running (screen sessions or stray
# processes), it is stopped first via stop.sh, then everything starts fresh.
# Workers run as background processes; gateway runs in the foreground.
# Kill with Ctrl-C (trap shuts down all workers automatically).

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ -f "${SCRIPT_DIR}/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${SCRIPT_DIR}/.env"
  set +a
fi

PIDS=()
WORKER_PORTS=()
WORKER_NAMES=()
CONDA_EXE="${CONDA_EXE:-/home/m.sayed/miniconda3/bin/conda}"
GATEWAY_ENV="${GATEWAY_ENV:-arabic-tts-web}"
WORKER_WAIT="${WORKER_WAIT:-30}"   # max seconds to wait for workers to bind

if [[ ! -x "$CONDA_EXE" ]]; then
  CONDA_EXE="$(command -v conda || true)"
fi

if [[ -z "$CONDA_EXE" ]]; then
  echo "Could not find conda. Set CONDA_EXE=/path/to/conda and retry." >&2
  exit 1
fi

# ── optional flags ──────────────────────────────────────────────
PORT=8025   # nginx proxies /arabic-tts/ -> 127.0.0.1:8025
while [[ $# -gt 0 ]]; do
  case $1 in --port) PORT=$2; shift 2;; *) shift;; esac
done

log() { echo "[$(date +%H:%M:%S)] $*"; }

port_busy() { ss -ltn "( sport = :$1 )" 2>/dev/null | grep -q LISTEN; }

# ── stop any previous instance ──────────────────────────────────
if pgrep -f "${SCRIPT_DIR}/server\.py|${SCRIPT_DIR}/workers/" >/dev/null \
   || port_busy 8082 || port_busy 8083 || port_busy "$PORT"; then
  log "Previous instance detected — stopping it first..."
  bash "${SCRIPT_DIR}/stop.sh"
fi

for p in 8082 8083 "$PORT"; do
  if port_busy "$p"; then
    log "✖ Port $p is still in use by another process:"
    ss -ltnp "( sport = :$p )" 2>/dev/null | tail -n +2 | sed 's/^/    /'
    log "  Stop that process (or use --port for the gateway) and retry."
    exit 1
  fi
done

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
  WORKER_PORTS+=("$port")
  WORKER_NAMES+=("${script##*/}")
  log "  PID ${PIDS[-1]}"
}

# ── helper: kill a process and all of its descendants ──────────
# (kill on the 'conda run' wrapper alone would orphan the python child)
kill_tree() {
  local pid=$1 child
  for child in $(pgrep -P "$pid" 2>/dev/null); do
    kill_tree "$child"
  done
  kill "$pid" 2>/dev/null || true
}

# ── cleanup on exit ──────────────────────────────────────────────
cleanup() {
  trap - EXIT INT TERM
  log "Shutting down workers..."
  for pid in "${PIDS[@]}"; do
    kill_tree "$pid"
    log "  killed PID $pid (and children)"
  done
  wait 2>/dev/null || true
  log "Done."
}
trap cleanup EXIT INT TERM

# ── start workers ───────────────────────────────────────────────
# Fish S2 Pro is intentionally disabled; it slows down the whole server on this host.
start_worker omnivoice-tts "${SCRIPT_DIR}/workers/omnivoice_server.py" 8082
start_worker voxcpm2-tts   "${SCRIPT_DIR}/workers/voxcpm2_server.py"   8083

# ── wait for workers to bind their ports ────────────────────────
deadline=$(( $(date +%s) + WORKER_WAIT ))
for i in "${!WORKER_PORTS[@]}"; do
  port=${WORKER_PORTS[$i]}
  name=${WORKER_NAMES[$i]}
  until port_busy "$port"; do
    if ! kill -0 "${PIDS[$i]}" 2>/dev/null; then
      log "✖ ${name} exited before binding port ${port} — check its output above."
      break
    fi
    if (( $(date +%s) >= deadline )); then
      log "⚠  ${name} has not bound port ${port} after ${WORKER_WAIT}s — continuing anyway."
      break
    fi
    sleep 1
  done
  port_busy "$port" && log "✓ ${name} is listening on port ${port}"
done

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
