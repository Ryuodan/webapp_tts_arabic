#!/usr/bin/env bash
# Reassemble the fine-tuned OmniVoice checkpoint from the split parts committed to git.
#
# GitHub rejects files over 100 MB, so each 2.45 GB model.safetensors under models/omnivoice/
# is versioned as model.safetensors.part-* chunks. Run this once after cloning or pulling;
# the OmniVoice worker then picks the checkpoints up automatically.
#
#   najdi_mix_v3_1950  Najdi v3 fine-tune (najdi_mix_v3_ft, step 1950), pinned to Nasser -> najdi variant
#
# Usage: bash scripts/assemble_omnivoice_checkpoint.sh [najdi_mix_v3_1950 ...]
#        (no arguments = every checkpoint)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../models/omnivoice" && pwd)"

declare -A EXPECTED_SHA=(
  [najdi_mix_v3_1950]="e66a5bf7e4c0e4fd5483377a78a59c9ff36d0fcde30683d0800bdf5caea9805a"
)

sha_of() { sha256sum "$1" | cut -d' ' -f1; }

assemble() {
  local name="$1"
  local dir="$ROOT/$name"
  local out="$dir/model.safetensors"
  local expected="${EXPECTED_SHA[$name]:-}"
  if [[ -z "$expected" ]]; then
    echo "✖ Unknown checkpoint '$name' (known: ${!EXPECTED_SHA[*]})" >&2
    return 1
  fi

  echo "── $name"
  if [[ -f "$out" ]]; then
    echo "model.safetensors already exists — verifying..."
    if [[ "$(sha_of "$out")" == "$expected" ]]; then
      echo "✓ Checkpoint already assembled and valid: $out"
      return 0
    fi
    echo "✖ Existing file is corrupt/outdated — reassembling."
    rm -f "$out"
  fi

  local parts=("$dir"/model.safetensors.part-*)
  if [[ ! -e "${parts[0]}" ]]; then
    echo "✖ No model.safetensors.part-* files in $dir — did the pull fetch them?" >&2
    return 1
  fi

  echo "Assembling ${#parts[@]} parts -> $out ..."
  cat "${parts[@]}" > "$out"

  echo "Verifying SHA-256..."
  local actual
  actual="$(sha_of "$out")"
  if [[ "$actual" != "$expected" ]]; then
    echo "✖ SHA-256 mismatch!" >&2
    echo "  expected: $expected" >&2
    echo "  actual:   $actual" >&2
    rm -f "$out"
    return 1
  fi
  echo "✓ Checkpoint assembled and verified: $out"
}

names=("$@")
[[ ${#names[@]} -eq 0 ]] && names=(najdi_mix_v3_1950)

status=0
for name in "${names[@]}"; do
  assemble "$name" || status=1
done
[[ $status -eq 0 ]] && echo "The OmniVoice worker will use them automatically."
exit $status
