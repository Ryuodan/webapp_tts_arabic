# Built-in clone voices

One folder per voice: a reference clip and a `voice.json` describing it. The OmniVoice
worker loads every folder at start-up and serves them through `GET /api/voices`; the
studio's **Voice** picker lists them. Voices uploaded from the studio live outside the
repo, in `$TTS_WORKDIR/voices_custom/`.

| id | Who | Tags | Reference |
| --- | --- | --- | --- |
| `nasser` | Nasser, Najdi male support agent. House voice of `omnivoice_najdi` | male · najdi · trained · synthetic · support | 5.8 s |
| `joud` | Joud, Najdi female support agent | female · najdi · trained · synthetic · support | 6.7 s |
| `rashed` | Rashed, the male voice of the `najdi_cs` support sets | male · najdi · unseen · synthetic · support | 5.8 s |
| `reem` | Reem, the female voice of the `najdi_cs` support sets | female · najdi · unseen · synthetic · support | 7.9 s |
| `abeer` | Abeer, Saudi voice artist | female · saudi · unseen · human · artist | 6.0 s |
| `sada_male` | A male speaker from Saudi television (SADA 2022) | male · saudi · unseen · human · broadcast | 6.1 s |
| `ahmed` | Ahmed, MSA male (Arabic-TTS-Spark) | male · msa · unseen · reader | 6.0 s |

## Tags

`tags` in `voice.json` says what a voice is. The studio shows each tag as a chip under the
picker and groups the picker by `trained`.

| Tag | Meaning |
| --- | --- |
| `male`, `female` | The speaker's sex |
| `najdi`, `saudi`, `msa` | Najdi (central Saudi) dialect, Saudi dialect in general, Modern Standard Arabic |
| `trained` | The speaker is in the Najdi model's training data (`najdi_mix_v3`), so the model knows the voice and its accent |
| `unseen` | No model here trained on the voice. It is cloned from the reference clip alone |
| `synthetic` | The clip is a speech synthesiser's output |
| `human` | The clip is a recording of a person |
| `support`, `artist`, `broadcast`, `reader` | Customer-support agent, voice artist, broadcast speech, read speech |

A tag without a translation in `static/i18n.js` (`vtag.<tag>`) is shown as written.

`trained` and `unseen` matter because the Najdi model treats them differently. In the
Saudi benchmark it kept a Saudi accent with voices it had never heard, but pulled their
timbre toward its own: similarity to an unseen voice's reference was 0.62, against 0.75
for the stock model. Each `voice.json` records the same check for its own clip under
`clone_check`.

## How the reference clips were chosen

OmniVoice copies the reference's pace, pitch and energy, so the clip matters as much as
the checkpoint. `scripts/pick_voice_refs.py` in the training project (`omnivoice-finetune`)
screens the held-out candidates of each voice (5–9 s, near the speaker's natural pace),
clones eight unseen sentences from the best of them with the shipped checkpoint, exactly
as the worker calls it, and scores the clones: similarity to the speaker, UTMOS, accent
and pace, with character error rate as a gate.

| Voice | Candidates | Result |
| --- | --- | --- |
| `nasser` | 123 held-out clips, 10 cloned | The current clip stays: the best alternative was within noise of it (similarity +0.015 ± 0.008, UTMOS +0.03 ± 0.04) and is an angry line |
| `joud` | 178 held-out clips, 10 cloned | New clip: similarity 0.874 (next 0.865), UTMOS 3.11 (next 3.07), 0.97× her natural pace |
| `rashed` | 29 segments, 8 cloned | Similarity 0.749 (next 0.738), UTMOS 3.40 |
| `reem` | 42 segments, 8 cloned | Similarity 0.791 (next 0.763), UTMOS 3.56 |
| `abeer`, `sada_male`, `ahmed` | one clip each | Scored for the record, not chosen among alternatives |

The `najdi_cs` sets name their agents Rashed, Fahad and Khaled, and Reem, Noura and Sara,
but speaker embeddings show one male and one female synthesiser voice behind them
(similarity 0.89 and 0.87 across each one's recordings), so each is one voice here.

## Adding a built-in voice

Create `voices/<id>/voice.json` beside a mono WAV:

```json
{
  "id": "sara",
  "label": "سارة — نجدية",
  "gender": "female",
  "language": "ars",
  "order": 8,
  "tags": ["female", "najdi", "unseen", "human"],
  "ref_audio": "sara_ref_6s.wav",
  "ref_text": "what is said in the clip",
  "sample_rate": 24000,
  "duration_s": 6.0,
  "source": "where the clip came from",
  "notes": "who this is"
}
```

`order` sets the position in the picker. Then add the id to the starting lists in
`static/app.js` (`voiceCatalog`, with the same tags) and `static/api.js` (`VOICES`), and a
display name under `voice.<id>` in `static/i18n.js`. `tests/test_frontend_contract.py`
fails if these drift apart.

## Licences

`ahmed` comes from a repository licensed for non-commercial research. `sada_male` comes
from SADA 2022, which is published for non-commercial use. Check both before using those
voices commercially. `abeer` is cut from a voice artist's demo sample.
