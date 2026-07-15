#!/usr/bin/env bash
# Reassemble the fine-tuned OmniVoice checkpoint from the split parts committed to git.
#
# GitHub rejects files over 100 MB, so models/omnivoice/best_finetuned/model.safetensors
# (2.45 GB) is versioned as model.safetensors.part-* chunks. Run this once after cloning
# or pulling; the OmniVoice worker then picks the checkpoint up automatically.
#
# Usage: bash scripts/assemble_omnivoice_checkpoint.sh
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../models/omnivoice/best_finetuned" && pwd)"
OUT="$DIR/model.safetensors"
EXPECTED_SHA="5f2b8938ccdcebe95038caef452dd945bbada1e0c3ac34b2956ed2ed293a7e3f"

sha_of() { sha256sum "$1" | cut -d' ' -f1; }

if [[ -f "$OUT" ]]; then
  echo "model.safetensors already exists — verifying..."
  if [[ "$(sha_of "$OUT")" == "$EXPECTED_SHA" ]]; then
    echo "✓ Checkpoint already assembled and valid: $OUT"
    exit 0
  fi
  echo "✖ Existing file is corrupt/outdated — reassembling."
  rm -f "$OUT"
fi

parts=("$DIR"/model.safetensors.part-*)
if [[ ! -e "${parts[0]}" ]]; then
  echo "✖ No model.safetensors.part-* files in $DIR — did the pull fetch them?" >&2
  exit 1
fi

echo "Assembling ${#parts[@]} parts -> $OUT ..."
cat "${parts[@]}" > "$OUT"

echo "Verifying SHA-256..."
actual="$(sha_of "$OUT")"
if [[ "$actual" != "$EXPECTED_SHA" ]]; then
  echo "✖ SHA-256 mismatch!" >&2
  echo "  expected: $EXPECTED_SHA" >&2
  echo "  actual:   $actual" >&2
  rm -f "$OUT"
  exit 1
fi

echo "✓ Checkpoint assembled and verified: $OUT"
echo "  The OmniVoice worker will use it automatically (finetuned variant)."
