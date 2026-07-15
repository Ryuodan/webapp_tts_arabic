# OmniVoice fine-tuned model

The webapp's OmniVoice worker automatically loads the best Saudi-HQ fine-tuned
checkpoint when it is present on disk. The checkpoint weights are too large for
Git (2.45 GB `model.safetensors`), so only the selection metadata is versioned
here; the paths inside `BEST_FINETUNED_CHECKPOINT.md` are relative to the TTS
work directory (`TTS_WORKDIR`, default `~/tts-05172026`).

`workers/omnivoice_server.py` exposes two selectable variants (the UI's
"نسخة النموذج" select, sent as the `variant` form field; only one is kept in
memory at a time):

- `finetuned` — `OMNIVOICE_FINETUNED_MODEL_ID` env var if set, otherwise
  `$TTS_WORKDIR/omnivoice/checkpoints/best_finetuned`, a symlink maintained in
  the training project pointing at the best available checkpoint (currently
  `saudi_hq_ft/checkpoint-2500`, eval/loss 4.4111). The variant is offered only
  when the weights exist; it is the default when available.
- `base` — the stock model (`OMNIVOICE_BASE_MODEL_ID`, default
  `k2-fsa/OmniVoice` from Hugging Face).

Verify what the worker sees via its `/health` endpoint (`variants`,
`default_variant`, `loaded_variant` fields).
