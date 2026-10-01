# Arabic TTS Studio — استوديو تحويل النص العربي إلى كلام

A local web studio for Arabic text-to-speech built around **OmniVoice**, with a
Najdi fine-tuned checkpoint shipped in the repo, a library of tagged clone voices you can
add your own to, a tashkeel agent with an original-vs-tashkeel comparison, and LLM agents
(Groq or OpenAI) that write and prepare the Arabic script for you.

## The two models

The interface exposes two model cards — the same OmniVoice worker running one
of two checkpoints (one in memory at a time, swapped on demand):

| Card | API id | Checkpoint | Use |
| --- | --- | --- | --- |
| 🎙️ **OmniVoice النجدي — ناصر** (default) | `omnivoice_najdi` | `najdi_mix_v3_ft/checkpoint-1950` — the best of nine models for Saudi Arabic in the Saudi benchmark | Saudi speech in any voice: Nasser by default, Joud or any other saved voice on request |
| 🌐 **OmniVoice الأصلي** | `omnivoice_base` | stock `k2-fsa/OmniVoice` (0.6B, 24 kHz, 600+ languages) | Baseline for comparison |

Compare mode generates the same text with every available version side by side.

The model is chosen by the URL (`/api/{model}/synthesize`): the gateway forwards the
alias's variant to the worker, so a plain curl call gets the checkpoint it named.

### Najdi (`omnivoice_najdi`)

Fine-tuned on Najdi customer-support speech (`najdi_mix_v3_ft`: 16,288 clips, 21 hours,
from two voices, Nasser and Joud; 2,000 steps). Its **house voice is Nasser**, the Najdi
male support agent: a request that names no `voice` (and uploads no `ref_audio`) clones
`voices/nasser`, and `voice` can name Joud or any other built-in or uploaded voice — see
the [voice library](#voice-library). Whenever a reference is cloned, on either model, gender
is kept out of the `instruct` string: the clip already fixes the speaker's sex, so sending
it again could only contradict it.

```bash
curl -F 'text=هلا والله' -F 'dialect=saudi' \
     http://localhost:8025/api/omnivoice_najdi/synthesize      # Nasser
curl -F 'text=هلا والله' -F 'dialect=saudi' -F 'voice=joud' \
     http://localhost:8025/api/omnivoice_najdi/synthesize      # Joud
```

The weights ship with the repo in `models/omnivoice/najdi_mix_v3_1950/` (split parts); the
worker resolves them in this order:

1. `OMNIVOICE_NAJDI_MODEL_ID` env var
2. repo-local `models/omnivoice/najdi_mix_v3_1950/` (after assembly)
3. `$OMNIVOICE_FINETUNE_DIR/checkpoints/najdi_mix_v3_ft/checkpoint-1950`
   (default dir: `../omnivoice-finetune`, the training project)

The card is offline when none exists. **Why step 1950:** the training project's v3 eval
screened 46 models — the stock model, every earlier run's best checkpoint and all 40 v3
checkpoints — by loss on 251 held-out Nasser clips no model trained on, and step 1950
came out lowest (3.9679). In the full listening eval it then cloned Nasser with the
lowest WER of any model:

| model, cloning Nasser | WER ↓ | similarity to Nasser ↑ | UTMOS ↑ |
| --- | --- | --- | --- |
| **v3 step 1950 (this card)** | **0.186** | 0.850 | 3.51 |
| Nasser-only fine-tune (`najdi_male_ft_cont/checkpoint-400`) | 0.205 | 0.845 | 3.58 |
| stock `k2-fsa/OmniVoice` | 0.205 | 0.800 | 3.62 |
| Nasser's own recordings | 0.214 | 0.864 | 3.42 |

**Best model for Saudi Arabic.** The Saudi benchmark then asked the wider question: which
of the nine models speaks Saudi Arabic best in any voice. Each model spoke 223 held-out
sentences (100 Saudi broadcast, 60 Najdi in Nasser's style, 35 Najdi in other voices,
28 MSA) four ways: its own voice, cloning Nasser, and cloning two Saudi voices no model
had heard (Abeer and a SADA broadcaster) — 8,028 clips. Averaged over the three Saudi sets:

| model | clips heard as Gulf ↑ | CER ↓ | UTMOS ↑ | similarity, unseen voices ↑ |
| --- | --- | --- | --- | --- |
| **v3 step 1950 (this card)** | **89%** | **0.081** | 3.54 | 0.62 |
| Nasser-only, all clips (`najdi_nasser_all_ft/checkpoint-1200`) | 89% | 0.092 | 3.54 | 0.59 |
| Nasser-only (`najdi_male_ft_cont/checkpoint-400`) | 90% | 0.086 | 3.55 | 0.60 |
| `najdi_cs_ft_v2/checkpoint-300` | 59% | 0.084 | 3.44 | 0.74 |
| Saudi-HQ (`saudi_hq_ft/checkpoint-2500`) | 58% | 0.080 | 3.28 | 0.74 |
| stock `k2-fsa/OmniVoice` | 22% | 0.074 | 3.52 | 0.75 |

Accent is judged by a spoken-dialect classifier, because CER cannot hear it: the ASR
favours MSA-like speech, which is why the stock model has the lowest CER while sounding
the least Saudi. The cost of the Najdi training shows in the last column: this card keeps
a Saudi accent with voices it never heard, but pulls their timbre toward Nasser's and
Joud's. The voice tags below say which voices that applies to.

Provenance and hashes:
[models/omnivoice/najdi_mix_v3_1950_checkpoint.json](models/omnivoice/najdi_mix_v3_1950_checkpoint.json).
It replaced the Nasser-only fine-tune (`models/omnivoice/nasser_800/`), which is removed;
the API id `omnivoice_najdi` is unchanged.

## Voice library

Pick the clone voice from the **Voice** dropdown; ▶ Listen plays its reference clip. The
dropdown has three sections — voices the Najdi model trained on, voices it clones from
their clip alone, and your uploads — and the chips under it say what the selected voice is.

### Built-in voices

Shipped with the repo under [voices/](voices/), each tagged with what it is:

| Voice | id | What it is |
| --- | --- | --- |
| **ناصر (Nasser)** | `nasser` | Najdi male support agent · synthetic voice · **trained into the Najdi model** — its house voice |
| **جود (Joud)** | `joud` | Najdi female support agent · synthetic voice · **trained into the Najdi model** |
| **راشد (Rashed)** | `rashed` | Najdi male support agent · synthetic voice · cloned from the clip only |
| **ريم (Reem)** | `reem` | Najdi female support agent · synthetic voice · cloned from the clip only |
| **عبير (Abeer)** | `abeer` | Saudi female voice artist · human recording · cloned from the clip only |
| **مذيع سادا (SADA broadcaster)** | `sada_male` | Saudi male, from Saudi television (SADA 2022) · human recording · cloned from the clip only |
| **أحمد (Ahmed)** | `ahmed` | MSA male, from [IbrahimSalah/Arabic-TTS-Spark](https://huggingface.co/IbrahimSalah/Arabic-TTS-Spark) · cloned from the clip only |

- **Trained into the Najdi model** means the speaker is in `najdi_mix_v3`, the data
  `omnivoice_najdi` was fine-tuned on, so the model knows the voice and its accent. Nasser
  and Joud are the only two.
- **Cloned from the clip only** means no model here trained on the voice. `omnivoice_najdi`
  still speaks it with a Saudi accent, but pulls the timbre toward Nasser's and Joud's
  (see the benchmark table above). When the exact timbre matters more than the accent,
  use `omnivoice_base`.
- Rashed and Reem are the two voices of the earlier synthetic `najdi_cs` support sets,
  which name their agents Rashed, Fahad and Khaled, and Reem, Noura and Sara. Speaker
  embeddings show one male and one female voice behind those names.
- Ahmed and the SADA broadcaster come from sources licensed for **non-commercial** use —
  keep that in mind.

**How the reference clips were chosen.** The clone copies the reference's pace, pitch and
energy, so each voice's clip was picked by cloning with the shipped checkpoint rather than
by ear: held-out candidates of 5–9 s near the speaker's natural pace, the best of them each
cloned on eight unseen sentences, and the clones scored for similarity to the speaker,
UTMOS, accent and pace. Nasser's cheerful 5.8 s greeting stays — the best of 123
alternatives was within noise of it. Joud's clip is new: the most Joud-like of ten
(similarity 0.874) with the highest UTMOS. Details and numbers:
[voices/README.md](voices/README.md).

### Your own voices

**➕ Add a voice** under the dropdown: give it a name, drop a WAV of one speaker
(2–30 s; 5–10 s of clean, natural speech clones best), and check **what is said in the
clip** — the studio fills that in with the transcription model when its worker is running,
otherwise type it (or leave it empty and OmniVoice transcribes the clip itself with Whisper
on every use, which is slower and downloads a model the first time). **✓ Save voice** and it
becomes the selected voice on every model straight away.

Uploaded voices are stored outside the repo, in `$TTS_WORKDIR/voices_custom/<id>/`
(`voice.json` + `ref.wav`, set `TTS_CUSTOM_VOICES_DIR` to move it), so they survive restarts
and a `git pull` and never show up in `git status`. Names are unique; **🗑 Delete** (shown for
uploaded voices only) removes one for good. Built-in voices can't be deleted from the studio —
add or remove those as `voices/<id>/voice.json` + a reference wav in the repo.

Over the API: `GET /api/voices` lists them all, each with its `tags`, plus each model's default voice;
`POST /api/voices` (multipart `name`, `audio`, optional `ref_text`) adds one,
`GET /api/voices/{voice_id}/audio` plays one, `DELETE /api/voices/{voice_id}` removes an
uploaded one; pass the id as `voice` to `/api/{model}/synthesize`.

## Tashkeel — original vs diacritized

**✨ Add tashkeel** under the text box sends the text to the Text-Prep agent
([textprep.py](textprep.py), `POST /api/prepare` with tashkeel only), which returns a fully
diacritized copy in the text's register — Najdi for the Najdi card, so it does not force
MSA case endings onto colloquial speech. The copy appears in its own box, editable, and never
replaces the original; **Generate speaks: Original | Tashkeel** picks which one is synthesized.
If the original changes, the tashkeel is redone automatically before it is spoken.

**Marks: Full tashkeel | Shadda only** under the button picks what the copy carries: every
haraka on every word of the sentence, or the shadda alone, with the rest of the sentence
left unmarked. The agent diacritizes the whole sentence once either way — that is where it
places the shadda best — and the studio keeps both forms, so switching is instant and needs
no second call. Runs are marked *Tashkeel* or *Shadda only* accordingly. Over the API it is
`marks: "full" | "shadda"` on `POST /api/prepare`; the answer always carries both forms as
`diacritized_full` and `diacritized_shadda`.

**Compare → Original vs tashkeel** (the default mode) generates the selected model twice, once
per version, side by side — making the tashkeel (or the shadda-only copy, when that is the
chosen mark) first if there is none yet. **Compare → Every
model** keeps the old behaviour: the same text on every available model. History, the player
and the saved comparisons show the full text of every run, marked *Original* or *Tashkeel*,
with the voice it used.

Tashkeel adds marks and nothing else. Every model tested sometimes rewrote a word as well
(الحين → الحالين), so the letters are checked: a slip gets one corrected retry, and if the
letters still differ the studio says so instead of hiding it.

Colloquial text is diacritized as it is spoken. Asked for case endings (الإعراب), the
models put فصحى endings on a fifth to two fifths of the words in Najdi lines (أخدمكَ، اليومَ);
told that Najdi and Egyptian words end in a sukun or a long vowel, they did so on 1–10%.

The agents need one LLM key in `.env` — `GROQ_API_KEY` (used when present) or
`OPENAI_API_KEY`; see [.env.example](.env.example). Without one the button reports that the
key is missing and everything else keeps working.

### Which Groq model

`openai/gpt-oss-120b` is the default ([llm.py](llm.py)). All eight chat models Groq offered
on 2026-10-01 ran the studio's three LLM jobs through the studio's own code, in JSON mode:
tashkeel of 30 MSA news lines with gold diacritics (WikiNews, from the SadeedDiac-25
benchmark) and of 20 held-out Najdi support lines, 14 lines of numbers, dates and
abbreviations to read out, and 6 compose jobs.

| Model | Valid JSON | MSA: every letter kept | MSA diacritic errors¹ | Najdi: every letter kept | Numbers read right | Compose | Tashkeel, per sentence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **`openai/gpt-oss-120b`** (default) | **100%** | **26 / 30** | **23%** | **19 / 20** | **14 / 14** | 6 / 6 | 5.5–8.7 s |
| `openai/gpt-oss-120b`, effort `low` | 100% | 21 / 30 | 35% | 16 / 20 | 13 / 14 | 6 / 6 | 1.3 s |
| `llama-3.3-70b-versatile` | 100% | 17 / 30 | 50% | 18 / 20 | 13 / 14 | 6 / 6 | 0.5 s |
| `qwen/qwen3.8-27b` (previous default) | 98% | 17 / 30 | 48% | 16 / 20 | 11 / 14 | 6 / 6 | 0.8 s |
| `qwen/qwen3.6-27b` | 98% | 15 / 30 | 58% | 15 / 20 | 14 / 14 | 6 / 6 | 4 s |
| `openai/gpt-oss-20b`, effort `low` | 98% | 8 / 30 | 81% | — | 11 / 14 | 6 / 6 | 1.0 s |

¹ Share of letters with the wrong mark; a line whose letters changed counts as entirely wrong.

`llama-3.1-8b-instant`, `allam-2-7b` and `minimaxai/minimax-m2.7` are not usable here: the
first failed every number line, and the other two broke JSON mode on half and three
quarters of their tashkeel calls.

What separates the default from the rest is the news lines: it kept the letters on 26 of
30 where the other models kept 15 to 17, and it read every number right, where the
previous default turned 1200 into «ألفين ومائتين» and 4:30 into «أربعة فاصلة ثلاثين». The samples are
small, so a difference of two or three lines between neighbouring rows is noise.

It thinks before it answers, which is where its 5–9 s per sentence goes.
`GROQ_REASONING_EFFORT=low` brings that to about 1.3 s for the second row's accuracy, and
`GROQ_MODEL` picks another model. The reasoning models also need room to think: without a
token budget a quarter of this model's tashkeel calls came back empty, so
[llm.py](llm.py) sets one per model.

## Quick start

```bash
# 1. One-time: gateway conda env + worker web deps
bash setup_webapp.sh

# 2. Reassemble the fine-tuned checkpoint (committed as split parts, because
#    GitHub caps files at 100 MB; verifies SHA-256). start.sh also does this
#    automatically whenever a pull brings new parts.
bash scripts/assemble_omnivoice_checkpoint.sh

# 3. Optional: cp .env.example .env and adjust (GROQ_API_KEY or OPENAI_API_KEY
#    enables the tashkeel/text-prep/compose agents; TTS_WORKDIR moves output/model dirs)

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
llm.py            the agents' chat model: Groq (default openai/gpt-oss-120b) or OpenAI
voices/           bundled clone voices, tagged (nasser, joud, rashed, reem, abeer,
                  sada_male, ahmed); uploaded ones live in $TTS_WORKDIR/voices_custom
models/omnivoice/ fine-tuned checkpoint najdi_mix_v3_1950 (split parts + metadata)
```

Key endpoints: `POST /api/{model}/synthesize` (`model` ∈ `omnivoice_najdi`,
`omnivoice_base`), `GET /api/status`, `GET /api/{model}/history`,
`GET /audio/{model}/{file}` (add `?format=mp3` for an MP3), `POST /api/compose`, `POST /api/prepare`, and the voice
library: `GET`/`POST /api/voices`, `GET /api/voices/{voice_id}/audio`,
`DELETE /api/voices/{voice_id}`.

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

`models/omnivoice/najdi_mix_v3_1950/` carries the full checkpoint: config and
tokenizer committed as-is, the 2.45 GB `model.safetensors` as 25 split parts
(`git push` also caps packs at 2 GB, hence two weight commits). Resolution order is
listed under [Najdi](#najdi-omnivoice_najdi) above; selection details and hashes:
[models/omnivoice/README.md](models/omnivoice/README.md).

## Retired engines

The Saudi-HQ fine-tune (`omnivoice_ft`, `saudi_hq_ft/checkpoint-2500`) is retired;
`/api/omnivoice_ft/...` now 404s. VoxCPM2 and Fish S2 Pro workers are disabled (`start.sh` no longer launches
them); their old recordings remain playable from the history endpoints.
