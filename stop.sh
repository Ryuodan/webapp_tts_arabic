#!/usr/bin/env bash
# Kill all TTS worker and gateway processes (screen sessions + stray
# processes), then wait until their ports are actually released.
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORTS=(8025 8082 8083)
PATTERNS=(
  "${APP_DIR}/workers/fish_server.py"
  "${APP_DIR}/workers/omnivoice_server.py"
  "${APP_DIR}/workers/voxcpm2_server.py"
  "${APP_DIR}/server.py"
)

echo "Stopping Arabic TTS Studio processes..."

# legacy screen sessions
for s in arabic-tts-web fish-tts-worker omnivoice-tts-worker voxcpm2-tts-worker; do
  screen -S "$s" -X quit 2>/dev/null && echo "  stopped screen session '$s'"
done

# matches both the 'conda run' wrapper and the python process it spawned
for pat in "${PATTERNS[@]}"; do
  pkill -f "$pat" 2>/dev/null && echo "  stopped $(basename "$pat")"
done

# wait for ports to be released; escalate to SIGKILL after 5s
busy=""
for i in {1..10}; do
  busy=""
  for p in "${PORTS[@]}"; do
    ss -ltn "( sport = :$p )" 2>/dev/null | grep -q LISTEN && busy="$busy $p"
  done
  [[ -z "$busy" ]] && break
  if [[ $i -eq 5 ]]; then
    echo "  ports still busy:${busy} — sending SIGKILL"
    for pat in "${PATTERNS[@]}"; do pkill -9 -f "$pat" 2>/dev/null; done
  fi
  sleep 1
done

if [[ -n "$busy" ]]; then
  echo "  ⚠ ports still in use:${busy} — likely another app, check: ss -ltnp"
fi
echo "Done."
