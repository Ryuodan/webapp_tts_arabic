# Arabic TTS Studio — استوديو تحويل النص العربي إلى كلام

A local web studio for Arabic text-to-speech built around **OmniVoice**, with a
Najdi fine-tuned checkpoint shipped in the repo, a library of tagged clone voices you can
add your own to, a tashkeel agent with an original-vs-tashkeel comparison, and LLM agents
(Groq or OpenAI) that write and prepare the Arabic script for you.

## Using the studio

The page opens on the three things a clip needs, top to bottom:

1. **Text** — type or paste what should be spoken. **✨ Add tashkeel** is optional.
2. **Voice** — one card per voice. Click a card to pick it; **▶** on the card plays that
   voice's reference clip without picking it. The six voices the Najdi models trained on
   come first.
3. **Generate speech** — the clip appears in **Output**, with WAV and MP3 downloads, and
   stays in **History**.

Everything else is folded under the button and opens with a click: **Model** (Najdi v4 or
its continuation), **Compare**, and **Transcription**. A panel you open stays open the
next time you load the page.

## The two models

The interface exposes two models — the same OmniVoice worker running one of two
fine-tuned checkpoints. Each loads the first time it is used and stays in memory until it
has been idle for 15 minutes (`TTS_MODEL_IDLE_SECONDS`), so switching between the two
after that is immediate; both loaded take about 4 GB of GPU memory:

| Card | API id | Checkpoint | Use |
| --- | --- | --- | --- |
| 🎙️ **OmniVoice النجدي v4** (default) | `omnivoice_najdi` | `najdi_v4_ft/checkpoint-6250` — the best all-round of eleven models in the v4 eval | Saudi speech, Najdi or MSA, in six trained voices: Nasser by default, or any other saved voice on request |
| 🎧 **OmniVoice النجدي v4 — تكملة** (v4 continued) | `omnivoice_najdi_v4c` | `najdi_v4c_ft/checkpoint-1000` — v4 step 6250 trained 1,000 more steps on four of its six voices | The same voices and the same use; listen to both and keep the one that sounds better for the voice |

Najdi v4 is selected when the studio opens; the **Model** panel under the Generate button
switches to the continuation, and **Compare → Every model** generates the same text with
both, side by side.

The stock model (`omnivoice_base`, `k2-fsa/OmniVoice`, 0.6B, 24 kHz, 600+ languages) is no
longer a card. The worker still serves it to API calls, as a baseline and for cloning an
unseen voice's exact timbre.

### Najdi v4 (`omnivoice_najdi`)

Fine-tuned on Saudi customer-support speech (`najdi_v4_ft`: 31,186 clips, 54 hours, six
voices; 6,500 steps). Three fifths of it is Najdi (33 h); the rest is MSA, spoken (13 h)
and formal (8 h). Its **house voice is Nasser**, the Najdi male support agent: a request
that names no `voice` (and uploads no `ref_audio`) clones `voices/nasser`, and `voice` can
name any of the other five trained voices, or any other built-in or uploaded voice — see
the [voice library](#voice-library). Whenever a reference is cloned, on any model, gender
is kept out of the `instruct` string: the clip already fixes the speaker's sex, so sending
it again could only contradict it.

```bash
curl -F 'text=هلا والله' \
     http://localhost:8025/api/omnivoice_najdi/synthesize      # Nasser
curl -F 'text=هلا والله' -F 'voice=nora' \
     http://localhost:8025/api/omnivoice_najdi/synthesize      # Nora
```

Neither call names a `dialect`: each saved voice is spoken in its own (Saudi for both of
these). See [the dialect follows the voice](#the-dialect-follows-the-voice).

The weights ship with the repo in `models/omnivoice/najdi_v4_6250/` (split parts); the
worker resolves them in this order:

1. `OMNIVOICE_NAJDI_MODEL_ID` env var
2. repo-local `models/omnivoice/najdi_v4_6250/` (after assembly)
3. `$OMNIVOICE_FINETUNE_DIR/checkpoints/najdi_v4_ft/checkpoint-6250`
   (default dir: `../omnivoice-finetune`, the training project)

The card is offline when none exists. **Why step 6250:** the training project's v4 eval
screened all 26 checkpoints of the run by held-out loss on four corpora no run trained on —
Nasser's clips, Joud's, and the four new voices' test clips in Najdi and in MSA — and step
6250 had the lowest mean (3.6692; steps 6000 and 6500 are within 0.0003 of it).

**Best all-round.** The benchmark then set it against ten other models: the stock model,
every earlier run's best checkpoint, and a 1,000-step continuation of this run. Each spoke
283 held-out sentences (100 Saudi broadcast, 60 Najdi in Nasser's style, 35 Najdi in other
voices, 28 MSA, and 30 Najdi and 30 MSA from the new voices) four ways: its own voice,
cloning Nasser, and cloning two Saudi voices no model had heard (Abeer and a SADA
broadcaster) — 12,452 clips. Ranked on five axes — Saudi accent, CER, UTMOS, similarity to
the unseen voices and held-out loss — it has the best mean rank: 4.6, ahead of the stock
model and the continuation (5.0 each) and of v3 step 1950 (5.4). Averaged over the three
Saudi sets:

| model | mean rank ↓ | held-out loss ↓ | CER ↓ | clips heard as Gulf ↑ | UTMOS ↑ | similarity, unseen voices ↑ |
| --- | --- | --- | --- | --- | --- | --- |
| **v4 step 6250 (this card)** | **4.6** | **4.50** | 0.072 | 71% | 3.45 | 0.62 |
| v4 continuation (`najdi_v4c_ft/checkpoint-1000`) | 5.0 | 4.51 | **0.070** | 71% | 3.43 | 0.63 |
| v3 step 1950 (the previous card) | 5.4 | 4.73 | 0.081 | **89%** | **3.54** | 0.62 |
| stock `k2-fsa/OmniVoice` | 5.0 | 4.64 | 0.074 | 22% | 3.52 | **0.75** |

**What it trades against v3.** It reads the text more accurately, on Saudi sentences (CER
0.072 against 0.081) and on MSA (0.054 against 0.064; both differences are significant),
and it knows four more voices. It pays in accent and in UTMOS (3.45 against 3.54). The accent loss is in the voices it did not train on:
cloning Nasser, 94% of its clips are heard as Gulf (v3: 95%), but cloning the two unseen
voices it is 53% (v3: 84%, stock: 12%), and 84% with no reference at all (v3: 92%). For
the most Saudi-sounding speech, pick one of the six trained voices.

Accent is judged by a spoken-dialect classifier, because CER cannot hear it: the ASR
favours MSA-like speech, which is why the stock model has a low CER while sounding the
least Saudi. Like v3, this model pulls an unseen voice's timbre toward its own voices
(similarity 0.62 against 0.75 for the stock model). The voice tags below say which voices
that applies to.

Provenance and hashes:
[models/omnivoice/najdi_v4_6250_checkpoint.json](models/omnivoice/najdi_v4_6250_checkpoint.json).
It replaced the v3 step-1950 checkpoint (`models/omnivoice/najdi_mix_v3_1950/`); the API
id `omnivoice_najdi` is unchanged.

### Najdi v4 continued (`omnivoice_najdi_v4c`)

The same model one short run later: `najdi_v4c_ft` starts from v4 step 6250 and trains
1,000 more steps at a third of the learning rate (1e-5) on four of the six voices — Nasser,
Joud, Nora and Firas, 26,094 clips, 43 hours. Ali and Majed were left out because an audit
of the training audio found them reading Najdi text with an MSA-like accent (P(Gulf) 0.47
and 0.53 on their own Najdi clips) and with the lowest UTMOS of the six. The model still
knows both voices from v4. The checkpoint is the run's last step, fixed before training.

It is called like the other card, and Nasser is its house voice too:

```bash
curl -F 'text=هلا والله' -F 'voice=joud' \
     http://localhost:8025/api/omnivoice_najdi_v4c/synthesize
```

**Against v4.** In the same benchmark the two are level on most scores, including the two
ways the studio uses them: cloning Nasser, and cloning the two unseen voices. Its mean rank
over the five axes is 5.0 against v4's 4.6. The scores where they differ beyond noise:

| | v4 step 6250 | v4 continued |
| --- | --- | --- |
| UTMOS, Saudi sets, all voices ↑ | **3.45** | 3.43 |
| P(Gulf), the new voices' Najdi lines ↑ | 0.68 | **0.75** |
| P(Gulf), the new voices' MSA lines | 0.55 | 0.69 |
| Similarity to the reference, the new voices' MSA lines ↑ | 0.66 | **0.67** |
| No reference clip: CER ↓ | 0.048 | **0.034** |
| No reference clip: P(Gulf) ↑ | 0.72 | **0.85** |
| No reference clip: UTMOS ↑ | **3.24** | 3.21 |

The continuation sounds more Saudi, on MSA text as well, and its clearest gains are with no
reference clip, which neither card does (a request without a voice clones Nasser). So the
benchmark does not pick one for studio use, which is why both are cards.

Its weights are in `models/omnivoice/najdi_v4c_1000/`, resolved like v4's:
`OMNIVOICE_NAJDI_V4C_MODEL_ID`, then that folder, then
`$OMNIVOICE_FINETUNE_DIR/checkpoints/najdi_v4c_ft/checkpoint-1000`. Provenance and hashes:
[models/omnivoice/najdi_v4c_1000_checkpoint.json](models/omnivoice/najdi_v4c_1000_checkpoint.json).

## Voice library

The **Voice** panel shows one card per voice. Click a card to pick it, or **▶** on the
card to hear its reference clip first. The cards come in three groups — the voices the
Najdi models trained on, voices they clone from their clip alone, and your uploads — and
the line under them says what the picked voice is.

### Built-in voices

Shipped with the repo under [voices/](voices/), each tagged with what it is:

| Voice | id | What it is |
| --- | --- | --- |
| **ناصر (Nasser)** | `nasser` | Najdi male support agent · **trained into the Najdi models** — their house voice |
| **جود (Joud)** | `joud` | Najdi female support agent · **trained into the Najdi models** |
| **نورة (Nora)** | `nora` | Najdi female support agent · **trained into the Najdi models** |
| **علي (Ali)** | `ali` | Najdi male support agent · **trained into the Najdi models** |
| **فراس (Firas)** | `firas` | Najdi male support agent · **trained into the Najdi models** |
| **ماجد (Majed)** | `majed` | Najdi male support agent · **trained into the Najdi models** |
| **راشد (Rashed)** | `rashed` | Najdi male support agent · synthetic voice · cloned from the clip only |
| **ريم (Reem)** | `reem` | Najdi female support agent · synthetic voice · cloned from the clip only |
| **عبير (Abeer)** | `abeer` | Saudi female voice artist · human recording · cloned from the clip only |
| **مذيع سادا (SADA broadcaster)** | `sada_male` | Saudi male, from Saudi television (SADA 2022) · human recording · cloned from the clip only |
| **أحمد (Ahmed)** | `ahmed` | MSA male, from [IbrahimSalah/Arabic-TTS-Spark](https://huggingface.co/IbrahimSalah/Arabic-TTS-Spark) · cloned from the clip only |

- **Trained into the Najdi models** means the speaker is one of the six synthesiser voices
  of `najdi_v4`, the data `omnivoice_najdi` was fine-tuned on, so the model knows the voice
  and its accent. These are the ones to start with. Nasser recorded Najdi only; the other
  five also recorded MSA. `omnivoice_najdi_v4c` trained further on four of them and knows
  Ali and Majed from v4 only.
- **Cloned from the clip only** means no model here trained on the voice. Its accent then
  follows the clip and the dialect the voice is spoken with (see
  [the dialect follows the voice](#the-dialect-follows-the-voice)), and it comes out less
  Saudi than a trained voice. Both Najdi models also pull the timbre toward their own
  voices (see the benchmark table above). When the exact timbre matters most, call
  `omnivoice_base` over the API.
- Rashed and Reem are the two voices of the earlier synthetic `najdi_cs` support sets,
  which name their agents Rashed, Fahad and Khaled, and Reem, Noura and Sara. Speaker
  embeddings show one male and one female voice behind those names. Reem is not Nora.
- Ahmed and the SADA broadcaster come from sources licensed for **non-commercial** use —
  keep that in mind.

**How the reference clips were chosen.** The clone copies the reference's pace, pitch and
mood, so each voice's clip was picked by cloning with the shipped v4 checkpoint: held-out
candidates near the speaker's natural pace, the best of them each cloned on unseen
sentences, and the clones scored for similarity to the speaker, UTMOS, accent and pace,
with the error rate as a gate.

The first pick took clips of 5–9 s and looked only at how the clones measured, which gave
Majed a frustrated customer's line and Ali one the data's judge had marked down. The second
(2026-10-05) took clips of 9.5–18 s in the manner a support voice should have: an agent
speaking warmly or calmly where the voice has such a line. Since 2026-10-06 every voice
uses the longest clip that does not measure worse than any other candidate of that voice
(two standard errors over six sentences), except Nasser, Ali and Majed, whose clips were
chosen by ear:

| Voice | Clip | Clones: similarity to the speaker | UTMOS | pace vs their own | Against the short clip |
| --- | --- | --- | --- | --- | --- |
| Nasser | 10.5 s, cheerful agent · by ear | 0.88 | 3.44 | 0.94× | level on both |
| Joud | 9.8 s, relieved agent | 0.88 | 2.91 | 1.00× | level on both |
| Nora | 14.4 s, cheerful agent | 0.90 | 3.48 | 1.02× | level on both |
| Ali | 14.1 s, agent · by ear | 0.83 | 3.35 | 1.09× | UTMOS +0.25, similarity −0.04 |
| Firas | 12.6 s, hurried agent | 0.87 | 3.04 | 1.09× | similarity +0.03, UTMOS level |
| Majed | 10.8 s, formal customer · by ear | 0.90 | 2.70 | 1.17× | level on both; a weaker Saudi accent |
| Reem | 11.1 s | 0.83 | 3.30 | 0.95× | similarity level, UTMOS −0.12 (within noise) |
| Abeer | 8.9 s | 0.70 | 3.34 | – | level on both; P(Gulf) 0.58 against 0.83 (within noise) |

A longer clip did not by itself make the clones measure better: for every voice the long
clip is within noise of the short one on most scores, and what changes is the manner the
clone copies, which the scores do not see. Three of these are worth a listen for that
reason: Joud's line has the agent reading out an order number and a code, Firas's is
tagged hurried in the data, and Abeer's longer cut measured less Saudi on six sentences. Rashed, the SADA broadcaster and Ahmed keep their
6 s clips: Rashed's segments stop at 7.7 s, no second recording of the broadcaster exists
in the data, and Ahmed has one clip. Majed's own recordings score low on UTMOS, and so do
his clones. Details and numbers: [voices/README.md](voices/README.md).

### The dialect follows the voice

The studio names no dialect. The worker speaks each saved voice with the OmniVoice language
code in its `voice.json` (`language`): `ars`, Saudi, for the ten Saudi voices, and `arb`,
MSA, for Ahmed. An uploaded voice is spoken with the dialect it was saved with (`arb` if
it was saved with none), and a request without a voice with `arb`. A `dialect` the request names (`msa`, `saudi`, `egyptian`) always wins.

Each voice was cloned on 20 held-out Najdi lines and 20 held-out MSA lines with both codes.
The code is an accent control: `ars` moves every voice toward a Saudi accent and `arb`
toward MSA, while similarity to the speaker, UTMOS and error rate barely move (at most 0.02
in similarity and 0.10 in UTMOS, in either direction).

| Voice | Spoken with | P(Gulf) on Najdi text, `arb` → `ars` | P(MSA) on MSA text, `arb` → `ars` |
| --- | --- | --- | --- |
| Nasser | `ars` | 0.99 → 0.99 | 0.00 → 0.00 |
| Joud | `ars` | 0.91 → 0.98 | 0.00 → 0.00 |
| Nora | `ars` | 0.95 → 0.99 | 0.00 → 0.00 |
| Ali | `ars` | 0.40 → 0.47 | 0.54 → 0.43 |
| Firas | `ars` | 0.93 → 0.96 | 0.12 → 0.06 |
| Majed | `ars` | 0.68 → 0.73 | 0.64 → 0.67 |
| Rashed | `ars` | 0.32 → 0.61 | 0.86 → 0.70 |
| Reem | `ars` | 0.88 → 0.94 | 0.31 → 0.11 |
| Abeer | `ars` | 0.54 → 0.63 | 0.72 → 0.58 |
| SADA broadcaster | `ars` | 0.59 → 0.84 | 0.69 → 0.43 |
| Ahmed | `arb` | 0.52 → 0.68 | 0.75 → 0.59 |

`ars` helps most where the accent was weakest, which is the voices the model did not train
on: Rashed and the SADA broadcaster gain 0.29 and 0.25. Nasser, Joud, Nora and Firas were
already Saudi and stay so. Ali is the least Saudi-sounding of the trained voices with
either code. The cost is on MSA text: a Saudi voice reads it with more of a Saudi accent
(Reem's P(MSA) falls from 0.31 to 0.11). For MSA read as MSA, pick Ahmed, who keeps `arb`
for that reason, or send `dialect=msa` over the API.

### Your own voices

**➕ Add a voice** under the cards: give it a name, drop a WAV of one speaker
(2–30 s; 6–14 s of clean speech in the manner you want back clones best, since the clone
copies the clip's pace and mood), and check **what is said in the
clip** — the studio fills that in with the transcription model when its worker is running,
otherwise type it (or leave it empty and OmniVoice transcribes the clip itself with Whisper
on every use, which is slower and downloads a model the first time). Pick the **dialect of
the voice** (Saudi unless you change it): it is what the voice is spoken with, and a voice
no model trained on gains the most from the right one. **✓ Save voice** and it becomes the
selected voice on every model straight away.

Uploaded voices are stored outside the repo, in `$TTS_WORKDIR/voices_custom/<id>/`
(`voice.json` + `ref.wav`, set `TTS_CUSTOM_VOICES_DIR` to move it), so they survive restarts
and a `git pull` and never show up in `git status`. Names are unique; **🗑 Delete** (shown for
uploaded voices only) removes one for good. Built-in voices can't be deleted from the studio —
add or remove those as `voices/<id>/voice.json` + a reference wav in the repo.

Over the API: `GET /api/voices` lists them all, each with its `tags`, plus each model's default voice;
`POST /api/voices` (multipart `name`, `audio`, optional `ref_text` and `dialect`) adds one,
`GET /api/voices/{voice_id}/audio` plays one, `DELETE /api/voices/{voice_id}` removes an
uploaded one; pass the id as `voice` to `/api/{model}/synthesize`.

## Tashkeel — original vs diacritized

**✨ Add tashkeel** under the text box sends the text to the Text-Prep agent
([textprep.py](textprep.py), `POST /api/prepare` with tashkeel only), which returns a fully
diacritized copy in the text's register — Najdi for the Najdi card, so it does not force
MSA case endings onto colloquial speech. The copy appears in its own box, editable, and never
replaces the original; **Generate speaks: Original | Tashkeel** picks which one is synthesized.
If the original changes, the tashkeel is redone automatically before it is spoken.

**Marks: Full tashkeel | Shadda only** beside the button picks what the copy carries: every
haraka on every word of the sentence, or the shadda alone, with the rest of the sentence
left unmarked. The agent diacritizes the whole sentence once either way — that is where it
places the shadda best — and the studio keeps both forms, so switching is instant and needs
no second call. Runs are marked *Tashkeel* or *Shadda only* accordingly. Over the API it is
`marks: "full" | "shadda"` on `POST /api/prepare`; the answer always carries both forms as
`diacritized_full` and `diacritized_shadda`.

**Marks: Lite tashkeel** is the third choice, for text that should read naturally without
being covered in harakat. The agent writes this copy itself: the shadda on every doubled
letter, the sukun on every consonant with no vowel after it, added commas and full stops
where a speaker pauses, and a short vowel only on a word that could be misread — a homograph
(عَلِم / عِلْم), a passive verb (عُقِد), an unusual name:

> أبشر طال عمرك طلبك وصلنا وبنكلمك خلال ساعة ونعلمك وش صار عليه →
> أبْشرْ طالْ عمْركْ، طلبكْ وصلْنا، وبنْكلّمكْ خلالْ ساعةْ، ونعلّمكْ وشْ صارْ عليهْ.

It is a separate request to the agent (`marks: "lite"`, answered as `diacritized_lite` with
the other two forms empty), so switching to or from it asks the agent once; the studio then
keeps every form made for the text. Runs are marked *Lite tashkeel*.

The agent writes the lite copy at low reasoning effort (`LITE_REASONING_EFFORT`, OpenAI
only): on six MSA and Najdi sentences gpt-5.5 took 11–18 s a sentence at `low` against
28–59 s at its default, kept every letter both ways, and agreed with its own full tashkeel
on all 26 shaddas and 86 of 97 sukuns both ways. At `low` it misread one passive verb as
active (عَقَد for عُقِد), which the default got right.

**Compare → Original vs tashkeel** (the panel's default mode) generates the selected model twice, once
per version, side by side — making the tashkeel (or the shadda-only or lite copy, when that
is the chosen mark) first if there is none yet. **Compare → Every
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

# 2. Reassemble the two fine-tuned checkpoints (committed as split parts, because
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
workers/          omnivoice_server.py :8082 — the only active worker; handles the three
                  model variants (`variant` form field) and built-in voices
compose.py        ✨ Auto-Compose agent: job + persona -> Arabic script + settings
textprep.py       Text-Prep agent: number/abbrev normalization + optional tashkeel
llm.py            the agents' chat model: Groq (default openai/gpt-oss-120b) or OpenAI
voices/           bundled clone voices, tagged (nasser, joud, nora, ali, firas, majed,
                  rashed, reem, abeer, sada_male, ahmed); uploaded ones live in
                  $TTS_WORKDIR/voices_custom
models/omnivoice/ fine-tuned checkpoints najdi_v4_6250 and najdi_v4c_1000 (split parts
                  + metadata)
```

Key endpoints: `POST /api/{model}/synthesize` (`model` ∈ `omnivoice_najdi`,
`omnivoice_najdi_v4c`, `omnivoice_base`), `GET /api/status`, `GET /api/{model}/history`,
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

## The fine-tuned checkpoints

`models/omnivoice/najdi_v4_6250/` and `models/omnivoice/najdi_v4c_1000/` each carry a full
checkpoint: config and tokenizer committed as-is, the 2.45 GB `model.safetensors` as 25
split parts (`git push` also caps packs at 2 GB, so push each checkpoint's weights as two
commits). Resolution order is listed under [Najdi v4](#najdi-v4-omnivoice_najdi) and
[Najdi v4 continued](#najdi-v4-continued-omnivoice_najdi_v4c) above; selection details and
hashes: [models/omnivoice/README.md](models/omnivoice/README.md).

## Retired engines

The Saudi-HQ fine-tune (`omnivoice_ft`, `saudi_hq_ft/checkpoint-2500`) is retired;
`/api/omnivoice_ft/...` now 404s. VoxCPM2 and Fish S2 Pro workers are disabled (`start.sh` no longer launches
them); their old recordings remain playable from the history endpoints.
