#!/usr/bin/env bash
# Install FastAPI/uvicorn into each TTS conda env so the worker servers can run.
# Run once before starting the webapp: bash webapp/setup_webapp.sh
set -e
PKGS="fastapi 'uvicorn[standard]' python-multipart"

echo "Installing webapp dependencies in arabic-tts env..."
conda run -n arabic-tts pip install --quiet $PKGS

echo "Installing webapp dependencies in omnivoice-tts env..."
conda run -n omnivoice-tts pip install --quiet $PKGS

echo "Installing webapp dependencies in voxcpm2-tts env..."
conda run -n voxcpm2-tts pip install --quiet $PKGS

echo "Installing gateway dependencies (current env)..."
pip install --quiet -r "$(dirname "$0")/requirements.txt"

echo ""
echo "All done. Run: bash webapp/start.sh"
