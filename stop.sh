#!/usr/bin/env bash
# Kill all TTS worker and gateway processes.
echo "Stopping Arabic TTS Studio processes..."
screen -S arabic-tts-web -X quit 2>/dev/null && echo "  stopped gateway screen" || true
screen -S fish-tts-worker -X quit 2>/dev/null && echo "  stopped fish worker screen" || true
screen -S omnivoice-tts-worker -X quit 2>/dev/null && echo "  stopped omnivoice worker screen" || true
screen -S voxcpm2-tts-worker -X quit 2>/dev/null && echo "  stopped voxcpm2 worker screen" || true
pkill -f "fish_server.py"      && echo "  stopped fish_server"      || true
pkill -f "omnivoice_server.py" && echo "  stopped omnivoice_server" || true
pkill -f "voxcpm2_server.py"   && echo "  stopped voxcpm2_server"   || true
pkill -f "webapp/server.py"    && echo "  stopped gateway server"    || true
pkill -f "webapp_tts_arabic/server.py" && echo "  stopped gateway server" || true
echo "Done."
