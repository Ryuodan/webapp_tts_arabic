# Arabic TTS Studio — استوديو تحويل النص العربي إلى كلام

A local web studio for Arabic text-to-speech built around **OmniVoice**, with a
Saudi-HQ fine-tuned checkpoint shipped in the repo, built-in cloned voices, and
LLM agents that write and prepare the Arabic script for you.

## The two models

The interface exposes exactly two model cards — the same OmniVoice worker
running one of two checkpoints (one in memory at a time, swapped on demand):

| Card | Checkpoint | Use |
| --- | --- | --- |
| ⭐ **OmniVoice المحسّن** (default) | `saudi_hq_ft/checkpoint-2500` — fine-tuned on high-quality Saudi audio (eval/loss 4.4111) | Production Arabic/Saudi speech |
| 🌐 **OmniVoice الأصلي** | stock `k2-fsa/OmniVoice` (0.6B, 24 kHz, 600+ languages) | Baseline for comparison |

Compare mode generates the same text with both versions side by side.

## Built-in cloned voices

Server-side reference voices under [voices/](voices/) — pick them from the
"صوت جاهز" dropdown, no upload needed:

- **عبير (Abeer)** — Saudi female voice artist (6 s reference).
- **أحمد (Ahmed)** — MSA male, from
  [IbrahimSalah/Arabic-TTS-Spark](https://huggingface.co/IbrahimSalah/Arabic-TTS-Spark)
  (upstream is licensed for **non-commercial research** — keep that in mind).

A manually uploaded reference in the cloning panel overrides the dropdown.
Add a voice by dropping `voices/<id>/voice.json` + a reference wav (see the
existing ones for the format).

## Quick start

```bash
# 1. One-time: gateway conda env + worker web deps
bash setup_webapp.sh

# 2. One-time: reassemble the fine-tuned checkpoint (committed as split parts,
#    because GitHub caps files at 100 MB; verifies SHA-256)
bash scripts/assemble_omnivoice_checkpoint.sh

# 3. Optional: cp .env.example .env and adjust (OPENAI_API_KEY enables the
#    compose/text-prep agents; TTS_WORKDIR moves output/model dirs)

# 4. Run — workers in the background, gateway in the foreground
bash start.sh            # open http://localhost:8025
```

Requirements: conda, plus an `omnivoice-tts` env that can `import omnivoice`
(the worker loads the model lazily on first request; on CPU a load takes a few
minutes and ~6–7 GB RAM).

## Architecture

```
static/           frontend (vanilla JS, RTL Arabic UI) — studio, API console, log console
server.py         gateway :8025 — serves the frontend, proxies /api/* to workers,
                  keeps only one heavyweight model in RAM (single-model mode)
reqlog.py         request log: body summarising, SQLite store, ASGI middleware
workers/          omnivoice_server.py :8082 — the only active worker; handles both
                  model variants (`variant` form field) and built-in voices
compose.py        ✨ Auto-Compose agent: job + persona -> Arabic script + settings
textprep.py       Text-Prep agent: number/abbrev normalization + optional tashkeel
voices/           bundled clone-voice references (abeer, ahmed)
models/omnivoice/ fine-tuned checkpoint (split parts + metadata + assembly docs)
```

Key endpoints: `POST /api/{model}/synthesize` (`model` ∈ `omnivoice_ft`,
`omnivoice_base`), `GET /api/status`, `GET /api/{model}/history`,
`GET /audio/{model}/{file}`, `POST /api/compose`, `POST /api/prepare`.

## Request log — 📊 سجل الطلبات

Every `/api/` call the gateway serves is recorded and browsable at
**[logs.html](static/logs.html)** (linked from the header of both other pages):

- **Usage** — request volume over time, per-endpoint call counts, error counts,
  average/median/p95/slowest response times, bytes in and out.
- **Per request** — what was sent, what came back, the HTTP status, the elapsed
  time and the caller, filterable by endpoint, status, time window or free text.
  Rows for a synthesis carry a player for the wav that call produced.

Storage is a SQLite file at `$TTS_WORKDIR/logs/requests.db`, capped at
`TTS_LOG_RETENTION` rows (default 5000). **Uploaded audio is never stored** — a
file part is reduced to its name, type and size, text fields are clipped, and the
UI's status-polling calls are skipped unless `TTS_LOG_STATUS_POLLS=1`. Set
`TTS_LOG_REQUESTS=0` to turn the whole thing off; see [.env.example](.env.example).

The same data is available over HTTP: `GET /api/logs`, `GET /api/logs/stats`,
`GET /api/logs/{id}`, `DELETE /api/logs`.

## The fine-tuned checkpoint

`models/omnivoice/best_finetuned/` carries the full checkpoint: config and
tokenizer committed as-is, the 2.45 GB `model.safetensors` as 25 split parts
(`git push` also caps packs at 2 GB, hence two weight commits). The worker
resolves the fine-tuned variant in this order:

1. `OMNIVOICE_FINETUNED_MODEL_ID` env var
2. repo-local `models/omnivoice/best_finetuned/` (after assembly)
3. `$TTS_WORKDIR/omnivoice/checkpoints/best_finetuned` (training-project symlink)

Selection details and hashes: [models/omnivoice/README.md](models/omnivoice/README.md)
and [BEST_FINETUNED_CHECKPOINT.md](models/omnivoice/BEST_FINETUNED_CHECKPOINT.md).

## Retired engines

VoxCPM2 and Fish S2 Pro workers are disabled (`start.sh` no longer launches
them); their old recordings remain playable from the history endpoints.
