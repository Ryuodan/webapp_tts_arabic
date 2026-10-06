# OmniVoice fine-tuned models

The two fine-tuned checkpoints the studio runs ship here, as split parts:

| Dir | Variant / card | Source | Metadata |
| --- | --- | --- | --- |
| `najdi_v4_6250/` | `najdi` / `omnivoice_najdi` | `najdi_v4_ft/checkpoint-6250` (the best all-round of the eleven models in the v4 eval) | `najdi_v4_6250_checkpoint.json` |
| `najdi_v4c_1000/` | `najdi_v4c` / `omnivoice_najdi_v4c` | `najdi_v4c_ft/checkpoint-1000` (v4 step 6250 trained 1,000 more steps on four of its six voices) | `najdi_v4c_1000_checkpoint.json` |

GitHub rejects files over 100 MB, so each 2.45 GB `model.safetensors` is committed as
split `model.safetensors.part-*` chunks. `bash scripts/assemble_omnivoice_checkpoint.sh`
concatenates them and verifies the SHA-256 recorded in the metadata (both checkpoints, or
the ones named as arguments); `start.sh` runs it automatically when parts are newer than
the assembled file. The assembled
`model.safetensors` stays gitignored; the config/tokenizer files next to the parts are
committed as-is.

Both Najdi variants clone `voices/nasser` unless the request names another voice. `najdi`
trained on six speakers, each with a voice under `voices/`: Nasser, Joud, Nora, Ali, Firas
and Majed. Every other voice is cloned from its clip alone (see `voices/README.md`).
`najdi_v4c` continues it for 1,000 steps at a learning rate of 1e-5 on four of the six
(Nasser, Joud, Nora, Firas; 26,094 clips, 43 hours), leaving out Ali and Majed, whose
training audio read Najdi text with an MSA-like accent. Its checkpoint is the last step of
that run, fixed in advance. In the v4 benchmark the two are level on most scores; the
metadata file lists the ones that differ.

The `najdi` checkpoint has been, in order: the Nasser-only `nasser_800/`, `najdi_mix_1000/`
(`najdi_mix_v2_ft`), `najdi_mix_v3_1800/`, `nasser_800/` again, `najdi_mix_v3_1950/`, and
now `najdi_v4_6250/` — the lowest held-out loss of the 26 checkpoints of the v4 run, and
the best mean rank in the benchmark. Nothing loads the earlier ones.
The Saudi-HQ fine-tune (`best_finetuned/`, `omnivoice_ft`) is retired.

Both interface cards ride the same worker on port 8082, which loads a variant the first
time it is asked for and unloads it after 15 idle minutes (`TTS_MODEL_IDLE_SECONDS`). It
serves three variants:

- `najdi` — resolved in order: `OMNIVOICE_NAJDI_MODEL_ID` env var → repo-local
  `models/omnivoice/najdi_v4_6250/` (after assembly) →
  `$OMNIVOICE_FINETUNE_DIR/checkpoints/najdi_v4_ft/checkpoint-6250` (training
  project). Offered only when weights exist.
- `najdi_v4c` — resolved the same way: `OMNIVOICE_NAJDI_V4C_MODEL_ID` env var →
  repo-local `models/omnivoice/najdi_v4c_1000/` →
  `$OMNIVOICE_FINETUNE_DIR/checkpoints/najdi_v4c_ft/checkpoint-1000`. Offered only when
  weights exist.
- `base` — the stock model (`OMNIVOICE_BASE_MODEL_ID`, default `k2-fsa/OmniVoice`
  from Hugging Face). The worker default; it has no card in the studio and is reached
  over the API as `omnivoice_base`.

Verify what the worker sees via its `/health` endpoint (`variants`,
`default_variant`, `loaded_variant` fields).
