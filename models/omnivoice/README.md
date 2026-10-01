# OmniVoice fine-tuned model

One fine-tuned checkpoint ships here, as split parts:

| Dir | Variant / card | Source | Metadata |
| --- | --- | --- | --- |
| `najdi_mix_v3_1950/` | `najdi` / `omnivoice_najdi` | `najdi_mix_v3_ft/checkpoint-1950` (best model for Nasser in the v3 eval, and the best of nine for Saudi Arabic in the Saudi benchmark) | `najdi_mix_v3_1950_checkpoint.json` |

GitHub rejects files over 100 MB, so the 2.45 GB `model.safetensors` is committed as
split `model.safetensors.part-*` chunks. `bash scripts/assemble_omnivoice_checkpoint.sh`
concatenates them and verifies the SHA-256 recorded in the metadata; `start.sh` runs it
automatically when parts are newer than the assembled file. The assembled
`model.safetensors` stays gitignored; the config/tokenizer files next to the parts are
committed as-is.

The Najdi variant clones `voices/nasser` unless the request names another voice. Nasser
and Joud (`voices/joud`) are the two speakers it trained on; every other voice is cloned
from its clip alone (see `voices/README.md`). Its
checkpoint has been, in order: the Nasser-only `nasser_800/`, `najdi_mix_1000/`
(`najdi_mix_v2_ft`), `najdi_mix_v3_1800/`, `nasser_800/` again, and now
`najdi_mix_v3_1950/` — the lowest loss on Nasser's held-out clips of the 46 models the
v3 eval screened, and the lowest WER when cloning him. The earlier ones are removed.
The Saudi-HQ fine-tune (`best_finetuned/`, `omnivoice_ft`) is retired.

Both interface cards ride the same worker on port 8082, which keeps one variant in
memory at a time and swaps on demand:

- `najdi` — resolved in order: `OMNIVOICE_NAJDI_MODEL_ID` env var → repo-local
  `models/omnivoice/najdi_mix_v3_1950/` (after assembly) →
  `$OMNIVOICE_FINETUNE_DIR/checkpoints/najdi_mix_v3_ft/checkpoint-1950` (training
  project). Offered only when weights exist.
- `base` — the stock model (`OMNIVOICE_BASE_MODEL_ID`, default `k2-fsa/OmniVoice`
  from Hugging Face). The worker default.

Verify what the worker sees via its `/health` endpoint (`variants`,
`default_variant`, `loaded_variant` fields).
