# OmniVoice fine-tuned model

The fine-tuned checkpoint the studio runs ships here, as split parts:

| Dir | Variant / card | Source | Metadata |
| --- | --- | --- | --- |
| `najdi_v4_6250/` | `najdi` / `omnivoice_najdi` | `najdi_v4_ft/checkpoint-6250` (the best all-round of the eleven models in the v4 eval) | `najdi_v4_6250_checkpoint.json` |

GitHub rejects files over 100 MB, so the 2.45 GB `model.safetensors` is committed as
split `model.safetensors.part-*` chunks. `bash scripts/assemble_omnivoice_checkpoint.sh`
concatenates them and verifies the SHA-256 recorded in the metadata; `start.sh` runs it
automatically when parts are newer than the assembled file. The assembled
`model.safetensors` stays gitignored; the config/tokenizer files next to the parts are
committed as-is.

The Najdi variant clones `voices/nasser` unless the request names another voice. It
trained on six speakers, each with a voice under `voices/`: Nasser, Joud, Nora, Ali, Firas
and Majed. Every other voice is cloned from its clip alone (see `voices/README.md`). Its
checkpoint has been, in order: the Nasser-only `nasser_800/`, `najdi_mix_1000/`
(`najdi_mix_v2_ft`), `najdi_mix_v3_1800/`, `nasser_800/` again, `najdi_mix_v3_1950/`, and
now `najdi_v4_6250/` — the lowest held-out loss of the 26 checkpoints of the v4 run, and
the best mean rank in the benchmark. Nothing loads the earlier ones.
The Saudi-HQ fine-tune (`best_finetuned/`, `omnivoice_ft`) is retired.

Both interface cards ride the same worker on port 8082, which keeps one variant in
memory at a time and swaps on demand:

- `najdi` — resolved in order: `OMNIVOICE_NAJDI_MODEL_ID` env var → repo-local
  `models/omnivoice/najdi_v4_6250/` (after assembly) →
  `$OMNIVOICE_FINETUNE_DIR/checkpoints/najdi_v4_ft/checkpoint-6250` (training
  project). Offered only when weights exist.
- `base` — the stock model (`OMNIVOICE_BASE_MODEL_ID`, default `k2-fsa/OmniVoice`
  from Hugging Face). The worker default.

Verify what the worker sees via its `/health` endpoint (`variants`,
`default_variant`, `loaded_variant` fields).
