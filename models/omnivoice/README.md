# OmniVoice fine-tuned model

One fine-tuned checkpoint ships here, as split parts:

| Dir | Variant / card | Source | Metadata |
| --- | --- | --- | --- |
| `nasser_800/` | `najdi` / `omnivoice_najdi` | `najdi_male_ft_cont/checkpoint-400` (global step 800, Nasser only) | `nasser_800_checkpoint.json` |

GitHub rejects files over 100 MB, so the 2.45 GB `model.safetensors` is committed as
split `model.safetensors.part-*` chunks. `bash scripts/assemble_omnivoice_checkpoint.sh`
concatenates them and verifies the SHA-256 recorded in the metadata; `start.sh` runs it
automatically when parts are newer than the assembled file. The assembled
`model.safetensors` stays gitignored; the config/tokenizer files next to the parts are
committed as-is.

The Najdi variant always clones `voices/nasser` and accepts no other reference. This
Nasser-only checkpoint is back after the two-voice fine-tunes (`najdi_mix_1000/` from
`najdi_mix_v2_ft`, then `najdi_mix_v3_1800/` from `najdi_mix_v3_ft`), which are removed.
The Saudi-HQ fine-tune (`best_finetuned/`, `omnivoice_ft`) is retired.

Both interface cards ride the same worker on port 8082, which keeps one variant in
memory at a time and swaps on demand:

- `najdi` — resolved in order: `OMNIVOICE_NAJDI_MODEL_ID` env var → repo-local
  `models/omnivoice/nasser_800/` (after assembly) →
  `$OMNIVOICE_FINETUNE_DIR/checkpoints/najdi_male_ft_cont/checkpoint-400` (training
  project). Offered only when weights exist.
- `base` — the stock model (`OMNIVOICE_BASE_MODEL_ID`, default `k2-fsa/OmniVoice`
  from Hugging Face). The worker default.

Verify what the worker sees via its `/health` endpoint (`variants`,
`default_variant`, `loaded_variant` fields).
