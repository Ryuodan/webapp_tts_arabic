# OmniVoice fine-tuned model

The webapp's OmniVoice worker automatically loads the best Saudi-HQ fine-tuned
checkpoint when it is present on disk. The checkpoint weights are too large for
Git (2.45 GB `model.safetensors`), so only the selection metadata is versioned
here; the paths inside `BEST_FINETUNED_CHECKPOINT.md` are relative to the TTS
work directory (`TTS_WORKDIR`, default `~/tts-05172026`).

Resolution order in `workers/omnivoice_server.py`:

1. `OMNIVOICE_MODEL_ID` env var, if set (HF id or local checkpoint path).
2. `$TTS_WORKDIR/omnivoice/checkpoints/best_finetuned` — a symlink maintained
   in the training project pointing at the best available checkpoint
   (currently `saudi_hq_ft/checkpoint-2500`, eval/loss 4.4111).
3. Fallback: the stock `k2-fsa/OmniVoice` from Hugging Face.

Verify which model is active via the worker's `/health` endpoint
(`model_id` + `finetuned` fields).
