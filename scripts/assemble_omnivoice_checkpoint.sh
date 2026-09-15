#!/usr/bin/env bash
# Reassemble the fine-tuned OmniVoice checkpoints from the split parts committed to git.
#
# GitHub rejects files over 100 MB, so each 2.45 GB model.safetensors under models/omnivoice/
# is versioned as model.safetensors.part-* chunks. Run this once after cloning or pulling;
# the OmniVoice worker then picks the checkpoints up automatically.
#
#   best_finetuned  Saudi-HQ fine-tune (saudi_hq_ft/checkpoint-2500)    -> finetuned variant
#   nasser_800      Nasser Najdi fine-tune (najdi_male_ft_cont, step 800) -> nasser variant
#
# Usage: bash scripts/assemble_omnivoice_checkpoint.sh [best_finetuned|nasser_800 ...]
#        (no arguments = every checkpoint)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../models/omnivoice" && pwd)"

declare -A EXPECTED_SHA=(
  [best_finetuned]="5f2b8938ccdcebe95038caef452dd945bbada1e0c3ac34b2956ed2ed293a7e3f"
  [nasser_800]="ee5ebb04c4b9a64c90cd1001a4c6199ecc93f51fa2e6f64bc839bd27129379a1"
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
[[ ${#names[@]} -eq 0 ]] && names=(best_finetuned nasser_800)

status=0
for name in "${names[@]}"; do
  assemble "$name" || status=1
done
[[ $status -eq 0 ]] && echo "The OmniVoice worker will use them automatically."
exit $status
