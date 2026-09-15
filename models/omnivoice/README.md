# OmniVoice fine-tuned models

Two fine-tuned checkpoints ship here, both as split parts:

| Dir | Variant / card | Source | Metadata |
| --- | --- | --- | --- |
| `best_finetuned/` | `finetuned` / `omnivoice_ft` | `saudi_hq_ft/checkpoint-2500` | `best_finetuned_checkpoint.json` |
| `nasser_800/` | `nasser` / `omnivoice_nasser` | `najdi_male_ft_cont/checkpoint-400` (global step 800) | `nasser_800_checkpoint.json` |

`bash scripts/assemble_omnivoice_checkpoint.sh` rebuilds both (or name one); `start.sh`
runs it automatically when parts are newer than the assembled file. The Nasser
variant always clones `voices/nasser`.

## Saudi-HQ checkpoint (`best_finetuned/`)

The best Saudi-HQ fine-tuned checkpoint (`saudi_hq_ft/checkpoint-2500`,
eval/loss 4.4111) ships WITH the repo in `best_finetuned/`. GitHub rejects
files over 100 MB, so the 2.45 GB `model.safetensors` is committed as split
`model.safetensors.part-*` chunks. After cloning or pulling, assemble it once:

```bash
bash scripts/assemble_omnivoice_checkpoint.sh
```

The script concatenates the parts and verifies the SHA-256 recorded in
`best_finetuned_checkpoint.json`. The assembled `model.safetensors` stays
gitignored; the config/tokenizer files next to the parts are committed as-is.

The interface exposes the two model versions as separate cards ("OmniVoice
المحسّن" and "OmniVoice الأصلي"); both ride the same worker on port 8082, which
keeps one variant in memory at a time and swaps on demand:

- `finetuned` — resolved in order: `OMNIVOICE_FINETUNED_MODEL_ID` env var →
  repo-local `models/omnivoice/best_finetuned/` (after assembly) →
  `$TTS_WORKDIR/omnivoice/checkpoints/best_finetuned` (training-project
  symlink). Offered only when weights exist; the default when available.
- `base` — the stock model (`OMNIVOICE_BASE_MODEL_ID`, default
  `k2-fsa/OmniVoice` from Hugging Face).

Verify what the worker sees via its `/health` endpoint (`variants`,
`default_variant`, `loaded_variant` fields).
