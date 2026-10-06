# Built-in clone voices

One folder per voice: a reference clip and a `voice.json` describing it. The OmniVoice
worker loads every folder at start-up and serves them through `GET /api/voices`; the
studio's **Voice** panel shows one card per voice. Voices uploaded from the studio live
outside the repo, in `$TTS_WORKDIR/voices_custom/`.

| id | Who | Tags | Reference |
| --- | --- | --- | --- |
| `nasser` | Nasser, Najdi male support agent. House voice of both Najdi models | male · najdi · trained · synthetic · support | 10.5 s |
| `joud` | Joud, Najdi female support agent | female · najdi · trained · synthetic · support | 9.8 s |
| `nora` | Nora, Najdi female support agent | female · najdi · trained · synthetic · support | 14.4 s |
| `ali` | Ali, Najdi male support agent | male · najdi · trained · synthetic · support | 14.1 s |
| `firas` | Firas, Najdi male support agent | male · najdi · trained · synthetic · support | 12.6 s |
| `majed` | Majed, Najdi male support agent | male · najdi · trained · synthetic · support | 10.8 s |
| `rashed` | Rashed, the male voice of the `najdi_cs` support sets | male · najdi · unseen · synthetic · support | 5.8 s |
| `reem` | Reem, the female voice of the `najdi_cs` support sets | female · najdi · unseen · synthetic · support | 11.1 s |
| `abeer` | Abeer, Saudi voice artist | female · saudi · unseen · human · artist | 8.9 s |
| `sada_male` | A male speaker from Saudi television (SADA 2022) | male · saudi · unseen · human · broadcast | 6.1 s |
| `ahmed` | Ahmed, MSA male (Arabic-TTS-Spark) | male · msa · unseen · reader | 6.0 s |

The six trained voices are the synthesiser voices of `najdi_v4`. The training project
knows the four that came with the October drop as `f2`, `m2`, `m3` and `m4`; the names
are the ones `text-audio-gen` records for them (Nora S, Ali, Firas, Majed). The studio's
second model, `omnivoice_najdi_v4c`, trained 1,000 more steps on Nasser, Joud, Nora and
Firas, and knows Ali and Majed from `najdi_v4` only.

## Tags

`tags` in `voice.json` says what a voice is. The studio lists them under the picked voice
and groups the cards by `trained`.

| Tag | Meaning |
| --- | --- |
| `male`, `female` | The speaker's sex |
| `najdi`, `saudi`, `msa` | Najdi (central Saudi) dialect, Saudi dialect in general, Modern Standard Arabic |
| `trained` | The speaker is in the Najdi models' training data (`najdi_v4`), so the models know the voice and its accent |
| `unseen` | No model here trained on the voice. It is cloned from the reference clip alone |
| `synthetic` | The clip is a speech synthesiser's output |
| `human` | The clip is a recording of a person |
| `support`, `artist`, `broadcast`, `reader` | Customer-support agent, voice artist, broadcast speech, read speech |

A tag without a translation in `static/i18n.js` (`vtag.<tag>`) is shown as written.

`trained` and `unseen` matter because the Najdi models treat them differently. In the v4
benchmark `omnivoice_najdi` cloned Nasser with 94% of the clips heard as Gulf, and two voices it had never
heard with 53%: with an unseen voice the accent follows the clip. It also pulls an unseen
voice's timbre toward its own: similarity to the reference was 0.62, against 0.75 for the
stock model. `omnivoice_najdi_v4c` was level with it on both in the same benchmark. Each
`voice.json` records the same check for its own clip under `clone_check`, made with
`omnivoice_najdi`.

## How the reference clips were chosen

OmniVoice copies the reference's pace, pitch and energy, so the clip matters as much as
the checkpoint. `scripts/pick_voice_refs_v4.py` in the training project (`omnivoice-finetune`)
screens the held-out candidates of each voice (5–9 s, near the speaker's natural pace),
clones eight unseen sentences from the best of them with the shipped checkpoint (language
`arb`), and scores the clones: similarity to the speaker, UTMOS,
accent and pace, with character error rate as a gate. A clip the studio already ships is
replaced only for a gain the sentences agree on (two standard errors). Run of 2026-10-04
with `najdi_v4_ft/checkpoint-6250`:

| Voice | Candidates | Result | Clones: similarity / UTMOS / P(Gulf) / pace |
| --- | --- | --- | --- |
| `nasser` | 123 held-out clips, 10 cloned | The current clip stays: the best alternative was within noise of it (similarity +0.008 ± 0.009, UTMOS +0.00 ± 0.05) | 0.862 / 3.63 / 1.00 / 1.00× |
| `joud` | 194 held-out clips, 10 cloned | The current clip stays (similarity +0.001 ± 0.009, UTMOS +0.07 ± 0.04) | 0.864 / 3.03 / 0.99 / 0.97× |
| `nora` | 39 held-out Najdi clips, 10 cloned | New voice: the most Nora-like clones, at the pace closest to hers | 0.887 / 3.60 / 0.99 / 1.03× |
| `ali` | 25 held-out Najdi clips, 10 cloned | New voice: three clips came out level; settled on 20 more lines (below) | 0.861 / 3.18 / 0.32 / 0.99× |
| `firas` | 14 held-out Najdi clips, 8 cloned | New voice: the most Firas-like clones with the highest UTMOS | 0.844 / 3.31 / 0.96 / 1.08× |
| `majed` | 14 held-out Najdi clips, 8 cloned | New voice: ranked first; confirmed on 20 more lines (below) | 0.889 / 2.85 / 0.78 / 1.17× |
| `rashed` | 29 segments, 8 cloned | The current clip stays (similarity +0.013 ± 0.014, UTMOS −0.08 ± 0.10) | 0.739 / 3.35 / 0.34 / 0.99× |
| `reem` | 42 segments, 8 cloned | New clip, from set 3: it beat the previous one on similarity (+0.022 ± 0.008) and UTMOS (+0.20 ± 0.08) | 0.827 / 3.67 / 0.99 / 0.96× |
| `abeer`, `sada_male`, `ahmed` | one clip each | Scored for the record, not chosen among alternatives | 0.69 / 3.65 / 0.43 · 0.66 / 3.22 / 0.92 · 0.73 / 3.48 / 0.35 |

Eight sentences left two picks open, so `scripts/check_voice_refs_v4.py` cloned 20 more
held-out Najdi lines (`outputs/voice_refs_v4/extra/report.txt`):

- **Ali.** His three best clips were level on eight sentences. On twenty, the picked one
  gave the most Ali-like clones (similarity 0.876, the others 0.852 and 0.835, both gaps
  beyond three standard errors) with the lowest error rate, and UTMOS and accent tied.
- **Majed.** The pick beat the runner-up on UTMOS (+0.10 ± 0.04) and on accent
  (P(Gulf) +0.24 ± 0.07).
- **Language code.** The same lines rendered with `ars` (`dialect=saudi`) instead of `arb`
  showed no change in similarity or UTMOS. P(Gulf) rose for Rashed (0.32 → 0.61,
  +0.29 ± 0.10); for the trained voices it rose by 0.00 to 0.07, which is within noise.
  That led to the check in the next section.

Three things the numbers say about the trained voices: Majed's recordings score low on
UTMOS themselves, so his clones do too; his clones also run faster than he speaks; and Ali
is the least Saudi-sounding of the six to the accent classifier, whichever clip is used.

## Longer clips, in the right manner

That first pick looked only at how the clones measured, and a clone copies its reference's
mood as well as its pace: Majed's clip was a frustrated customer, and Ali's a line the
data's judge gave 66 for naturalness. `scripts/pick_voice_refs_long.py` (2026-10-05) looked
again, for clips of 9.5–18 s and only in the manner a support voice should have: an
agent's line said warmly or calmly, then an agent's neutral line, then a customer's, never
an angry or frustrated one. The best of each voice's candidates by their own audio were
cloned with the shipped checkpoint, as the studio now calls it (language `ars`), on four
short lines and two long sentences, beside the clip the studio shipped
(`outputs/voice_refs_long/report.txt`). The result column is that day's decision; the next
section changed it for Joud, Nora, Firas and Reem:

| Voice | Candidates | Result | Clones: similarity / UTMOS / P(Gulf) / pace |
| --- | --- | --- | --- |
| `nasser` | 11 warm agent lines, 4 cloned | New clip, 10.5 s, chosen by ear: level with the short one (similarity −0.004, UTMOS +0.06), and the lowest error rate of the four. The scores' own pick was a 9.7 s clip with UTMOS +0.14 | 0.882 / 3.44 / 1.00 / 0.94× |
| `joud` | 4 lines, 4 cloned | The short clip stays: three long ones measure worse (UTMOS −0.12 to −0.14) and the fourth, level with it, is an agent reading out digits | 0.880 / 2.93 / 1.00 / 0.97× |
| `nora` | 21 warm agent lines, 5 cloned | New clip, 11.3 s: level with the short one, and the line the judge found most natural | 0.904 / 3.50 / 1.00 / 1.07× |
| `ali` | 9 neutral agent lines and 5 customer lines, 5 cloned | New clip, 14.1 s, chosen by ear: the most natural clones (UTMOS +0.25 over the short one, beyond two standard errors), somewhat less like him (similarity −0.04). The scores' own pick was the 13.1 s clip that kept his voice (−0.006) | 0.832 / 3.35 / 0.70 / 1.09× |
| `firas` | 11 agent lines, 5 cloned | New clip, 11.0 s: similarity +0.034 over the previous one (beyond two standard errors) | 0.879 / 3.07 / 0.99 / 1.06× |
| `majed` | 9 agent lines and 4 customer lines, 5 cloned | New clip, 10.8 s, a customer's formal line, chosen by ear: level with the previous one on similarity (−0.012) and UTMOS, with a weaker Saudi accent (P(Gulf) 0.58 against 0.83). The scores' own pick was a 10.9 s agent's line that kept the accent | 0.895 / 2.70 / 0.58 / 1.17× |
| `reem` | 2 segments | The short clip stays: the longer one is level on similarity and lower on UTMOS (−0.12) | – |
| `sada_male` | 45 held-out SADA clips of 9 s or more | The short clip stays: none is the same speaker (the closest has similarity 0.50) | – |

Length did not buy quality: no voice's best long clip measures clearly better than its short
one except Firas's in similarity and Nasser's in UTMOS. What the longer clips change is the
manner the clone copies, which the scores do not see, so
`python scripts/pick_voice_refs_long.py audition` writes a page to judge them by ear: each
voice's short clip, its long clip and one alternative, with what the model says from each.
Rashed has no segment longer than 7.7 s. The clips replaced are kept in
`outputs/voice_refs_long/previous/`.

## The longest clip that measures no worse

On 2026-10-06 the rule became one line for every voice: the longest candidate that is not
worse than any other candidate of that voice, the short clip included, on similarity,
UTMOS, error rate or accent (two standard errors over the same six sentences). Nasser's,
Ali's and Majed's clips, chosen by ear, were left alone. Four voices changed, and Abeer got
a longer cut of her demo:

| Voice | Clip now | Was | Against the clip it replaced | Longer candidates, and what they lose |
| --- | --- | --- | --- | --- |
| `joud` | 9.8 s, a relieved agent | 6.7 s | similarity ±0.000, UTMOS −0.01 ± 0.04 | 10.8 s: similarity −0.011 ± 0.005 against the short clip · 10.9 s and 12.9 s: UTMOS −0.11 and −0.13 |
| `nora` | 14.4 s, a cheerful agent | 11.3 s | similarity +0.001 ± 0.002, UTMOS −0.02 ± 0.07 | 15.8 s: similarity −0.006 ± 0.003 against her first, short clip |
| `firas` | 12.6 s, an agent in a hurry | 11.0 s | similarity −0.006 ± 0.004, UTMOS −0.03 ± 0.04 | 13.7 s and 14.8 s: similarity −0.026 and −0.023 against the 11.0 s clip · 14.9 s: UTMOS −0.12 |
| `reem` | 11.1 s, from `najdi_cs` set 11 | 6.0 s | similarity +0.005 ± 0.007, UTMOS −0.12 ± 0.07 | 13.1 s: similarity −0.027 ± 0.006 |
| `abeer` | 8.9 s, cut from 9.7–18.6 s of her demo | 6.0 s | similarity +0.018, UTMOS ±0.00, P(Gulf) 0.58 against 0.83; none beyond two standard errors | an 18.3 s cut: similarity +0.073 but P(Gulf) −0.29, both beyond two standard errors |

What the scores cannot say, so listen for it: Joud's line has the agent reading out an
order number and a code letter by letter, Firas's is tagged hurried in the data, Reem's
UTMOS difference is 1.6 standard errors from zero, and Abeer's clones were heard as Gulf
less often with the longer cut, on six sentences. Abeer's check is `scripts/check_abeer_ref.py`
(`outputs/voice_refs_long/abeer/report.txt`); her new clip's text is an ASR transcript.
Rashed, the SADA broadcaster and Ahmed keep their 6 s clips: they have nothing longer.

## The dialect each voice is spoken with

`language` in `voice.json` is the OmniVoice language code the worker uses for the voice
when a request names no `dialect`, which is how the studio calls it: `ars` (Saudi) or `arb`
(MSA). A `dialect` the request does name wins, and a voice without a `language` is spoken
with `arb`. A voice uploaded from the studio gets its `language` from the dialect picked in
the form.

`scripts/check_voice_language_v4.py` cloned 20 held-out Najdi lines and 20 held-out MSA
lines in every voice with both codes (`outputs/voice_refs_v4/language/report.txt`). The
code moves the accent and little else: similarity shifts by at most 0.02 and UTMOS by at
most 0.10, in either direction, and no error rate changes beyond noise except Reem's
(−0.008). So each voice gets the code of the accent it should have:

| Voice | `language` | P(Gulf) on Najdi text, `arb` → `ars` | P(MSA) on MSA text, `arb` → `ars` |
| --- | --- | --- | --- |
| `nasser` | `ars` | 0.99 → 0.99 | 0.00 → 0.00 |
| `joud` | `ars` | 0.91 → 0.98 | 0.00 → 0.00 |
| `nora` | `ars` | 0.95 → 0.99 | 0.00 → 0.00 |
| `ali` | `ars` | 0.40 → 0.47 | 0.54 → 0.43 |
| `firas` | `ars` | 0.93 → 0.96 | 0.12 → 0.06 |
| `majed` | `ars` | 0.68 → 0.73 | 0.64 → 0.67 |
| `rashed` | `ars` | 0.32 → 0.61 | 0.86 → 0.70 |
| `reem` | `ars` | 0.88 → 0.94 | 0.31 → 0.11 |
| `abeer` | `ars` | 0.54 → 0.63 | 0.72 → 0.58 |
| `sada_male` | `ars` | 0.59 → 0.84 | 0.69 → 0.43 |
| `ahmed` | `arb` | 0.52 → 0.68 | 0.75 → 0.59 |

The ten Saudi voices are spoken with `ars`: it never made one sound less Saudi, and it
helped most where the accent was weakest (Rashed, the SADA broadcaster). Ahmed is an MSA
voice and keeps `arb`, which reads MSA text as MSA more often. The cost of `ars` is the
last column: a Saudi voice reads MSA text with more of a Saudi accent. Each `voice.json`
carries its own numbers under `language_check`.

The `najdi_cs` sets name their agents Rashed, Fahad and Khaled, and Reem, Noura and Sara,
but speaker embeddings show one male and one female synthesiser voice behind them
(similarity 0.89 and 0.87 across each one's recordings), so each is one voice here. Reem's
clip comes from the set where she is called Noura; she is not the trained voice Nora.

## Adding a built-in voice

Create `voices/<id>/voice.json` beside a mono WAV:

```json
{
  "id": "sara",
  "label": "سارة — نجدية",
  "gender": "female",
  "language": "ars",
  "order": 12,
  "tags": ["female", "najdi", "unseen", "human"],
  "ref_audio": "sara_ref_6s.wav",
  "ref_text": "what is said in the clip",
  "sample_rate": 24000,
  "duration_s": 6.0,
  "source": "where the clip came from",
  "notes": "who this is"
}
```

`order` sets the position among the cards, and the part of `label` before the dash is the
card's name. `language` is the code the voice is spoken with: `ars` for a Saudi voice, `arb`
for an MSA one. Then add the id to the starting lists in `static/app.js` (`voiceCatalog`, with
the same tags) and `static/api.js` (`VOICES`), and a display name under `voice.<id>` in
`static/i18n.js`. `tests/test_frontend_contract.py` fails if these drift apart.

## Licences

`ahmed` comes from a repository licensed for non-commercial research. `sada_male` comes
from SADA 2022, which is published for non-commercial use. Check both before using those
voices commercially. `abeer` is cut from a voice artist's demo sample.
