#!/usr/bin/env bash
# Kill all TTS worker and gateway processes.
echo "Stopping Arabic TTS Studio processes..."
pkill -f "fish_server.py"      && echo "  stopped fish_server"      || true
pkill -f "omnivoice_server.py" && echo "  stopped omnivoice_server" || true
pkill -f "voxcpm2_server.py"   && echo "  stopped voxcpm2_server"   || true
pkill -f "webapp/server.py"    && echo "  stopped gateway server"    || true
echo "Done."
