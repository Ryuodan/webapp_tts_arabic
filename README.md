# Arabic TTS Studio — استوديو تحويل النص العربي إلى كلام

A local web studio for Arabic text-to-speech built around **OmniVoice**, with a
Saudi-HQ fine-tuned checkpoint shipped in the repo, built-in cloned voices, and
LLM agents that write and prepare the Arabic script for you.

## The three models

The interface exposes three model cards — the same OmniVoice worker running one
of three checkpoints (one in memory at a time, swapped on demand):

| Card | API id | Checkpoint | Use |
| --- | --- | --- | --- |
| ⭐ **OmniVoice المحسّن** (default) | `omnivoice_ft` | `saudi_hq_ft/checkpoint-2500` — fine-tuned on high-quality Saudi audio (eval/loss 4.4111) | Production Arabic/Saudi speech |
| 🎙️ **OmniVoice النجدي** | `omnivoice_najdi` | `najdi_mix_v2_ft/checkpoint-1000` — base + both Najdi voices, 1,200 steps (best eval loss 3.7266) | Najdi support calls; **clones Nasser or Joud, by gender** |
| 🌐 **OmniVoice الأصلي** | `omnivoice_base` | stock `k2-fsa/OmniVoice` (0.6B, 24 kHz, 600+ languages) | Baseline for comparison |

Compare mode generates the same text with every available version side by side.

The model is chosen by the URL (`/api/{model}/synthesize`): the gateway forwards the
alias's variant to the worker, so a plain curl call gets the checkpoint it named.

### Najdi (`omnivoice_najdi`)

Fine-tuned on **both** Najdi voices at once (7,564 clips: 3,088 Nasser + 3,723 Joud),
so the request's **`gender` picks the speaker**:

| `gender` | Clone voice |
| --- | --- |
| `male` (or omitted) | `voices/nasser` — Nasser, Najdi male support agent |
| `female` | `voices/joud` — Joud, Najdi female support agent |

The worker pins the voice that gender selects and ignores everything else the request
says about it — `voice`, an uploaded `ref_audio`, a `ref_text` — and the studio shows
the voice picker locked to whichever the gender control names. Gender is also kept out
of the `instruct` string here: the reference clip already fixes the speaker's sex, so
sending it again could only contradict the clip.

```bash
curl -F 'text=هلا والله' -F 'gender=female' -F 'dialect=saudi' \
     http://localhost:8025/api/omnivoice_najdi/synthesize      # Joud
```

The weights ship with the repo in `models/omnivoice/najdi_mix_1000/` (split parts, like
the Saudi-HQ checkpoint); the worker resolves them in this order:

1. `OMNIVOICE_NAJDI_MODEL_ID` env var
2. repo-local `models/omnivoice/najdi_mix_1000/` (after assembly)
3. `$OMNIVOICE_FINETUNE_DIR/checkpoints/najdi_mix_v2_ft/checkpoint-1000`
   (default dir: `../omnivoice-finetune`, the training project)

The card is offline when none exists. Step 1000 is the run's lowest eval loss (3.7266)
of its 24 checkpoints — ahead of step 500 (3.7315) and of the final step 1200 (3.8040).
Provenance and hashes:
[models/omnivoice/najdi_mix_1000_checkpoint.json](models/omnivoice/najdi_mix_1000_checkpoint.json).

This card replaces the earlier Nasser-only model (`omnivoice_nasser`,
`najdi_male_ft_cont/checkpoint-400`), which is removed — `/api/omnivoice_nasser/...`
now 404s. Nasser himself is unchanged: `gender=male` here is the same speaker.

## Built-in cloned voices

Server-side reference voices under [voices/](voices/) — pick them from the
"صوت جاهز" dropdown, no upload needed:

- **عبير (Abeer)** — Saudi female voice artist (6 s reference).
- **أحمد (Ahmed)** — MSA male, from
  [IbrahimSalah/Arabic-TTS-Spark](https://huggingface.co/IbrahimSalah/Arabic-TTS-Spark)
  (upstream is licensed for **non-commercial research** — keep that in mind).
- **ناصر (Nasser)** — Najdi male support agent (6.3 s held-out test clip from the
  `najdi_male` data). `omnivoice_najdi` uses it for `gender=male`; the other models can
  pick it too.
- **جود (Joud)** — Najdi female support agent (6.2 s held-out test clip from the
  `najdi_mix_v2` test split — deliberately the same support-agent greeting as Nasser's,
  so the two sound like the same call from either side). `omnivoice_najdi` uses it for
  `gender=female`; the other models can pick it too.

A manually uploaded reference in the cloning panel overrides the dropdown.
Add a voice by dropping `voices/<id>/voice.json` + a reference wav (see the
existing ones for the format).

## Quick start

```bash
# 1. One-time: gateway conda env + worker web deps
bash setup_webapp.sh

# 2. Reassemble the fine-tuned checkpoints (committed as split parts, because
#    GitHub caps files at 100 MB; verifies SHA-256). start.sh also does this
#    automatically whenever a pull brings new parts.
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
voices/           bundled clone-voice references (abeer, ahmed, nasser, joud)
models/omnivoice/ fine-tuned checkpoints best_finetuned + najdi_mix_1000 (split parts + metadata)
```

Key endpoints: `POST /api/{model}/synthesize` (`model` ∈ `omnivoice_ft`,
`omnivoice_najdi`, `omnivoice_base`), `GET /api/status`, `GET /api/{model}/history`,
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

## Updating a server

```bash
git pull && bash start.sh
```

`start.sh` stops the running instance, rebuilds any checkpoint whose parts changed
(about a minute per checkpoint, SHA-256 verified), then starts the workers and gateway.

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
