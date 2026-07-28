# Arabic TTS Improvement Plan: VoxCPM2 and OmniVoice

Verified on: 2026-06-25

This document explains how to clone, run, and fine-tune **VoxCPM2** and **OmniVoice** with the goal of improving Arabic text-to-speech quality.

## Executive Recommendation

Start with **VoxCPM2**.

Reasons:

- VoxCPM2 officially supports Arabic.
- The upstream repo documents both **LoRA fine-tuning** and **full fine-tuning**.
- The fine-tuning data format is simple JSONL.
- LoRA is the most practical first step for improving a voice, style, domain, or Arabic dialect without needing a very large GPU setup.

Use **OmniVoice** as the second experiment.

Reasons:

- OmniVoice supports 600+ languages and many Arabic variants.
- It has an official fine-tuning script.
- It is smaller than VoxCPM2, around 0.6B parameters, but the fine-tuning workflow is less direct than VoxCPM2's LoRA path.

## Confirmed Model Facts

### VoxCPM2

Official links:

- GitHub: <https://github.com/OpenBMB/VoxCPM>
- Hugging Face: <https://huggingface.co/openbmb/VoxCPM2>
- Fine-tuning docs: <https://voxcpm.readthedocs.io/en/latest/finetuning/finetune.html>
- Quick start docs: <https://voxcpm.readthedocs.io/en/latest/quickstart.html>

Confirmed details:

- 2B parameter model.
- Supports 30 languages, including Arabic.
- Outputs 48 kHz audio.
- Apache-2.0 license.
- Supports voice design, controllable voice cloning, and high-fidelity cloning with reference audio plus transcript.
- Supports both LoRA fine-tuning and full SFT fine-tuning.
- Official hardware estimate:
  - VoxCPM2 LoRA: about 20 GB VRAM.
  - VoxCPM2 full fine-tuning: about 40 GB VRAM.

### OmniVoice

Official links:

- GitHub: <https://github.com/k2-fsa/OmniVoice>
- Hugging Face: <https://huggingface.co/k2-fsa/OmniVoice>
- Fine-tuning examples: <https://github.com/k2-fsa/OmniVoice/tree/master/examples>
- Language list: <https://github.com/k2-fsa/OmniVoice/blob/master/docs/languages.md>

Confirmed details:

- Around 0.6B parameters.
- Supports 600+ languages.
- Apache-2.0 license.
- Supports voice cloning and voice design.
- Official examples include training, fine-tuning, and evaluation.
- OmniVoice language documentation includes Standard Arabic and several dialects.

## Phase 1: Baseline Before Fine-Tuning

Before training anything, create a baseline so improvement can be measured.

Prepare a small Arabic evaluation set:

- 100 to 300 Arabic sentences.
- Include Modern Standard Arabic.
- Include the target dialect if the product needs it, such as Egyptian, Gulf, Levantine, Moroccan, or Saudi/Najdi.
- Include numbers, dates, names, abbreviations, punctuation, and long sentences.
- Keep a separate set that will never be used in training.

Suggested categories:

- Simple MSA sentences.
- News-style sentences.
- Conversational Arabic.
- Domain-specific product sentences.
- Numbers and dates.
- Names of people, cities, companies, and products.
- Difficult Arabic pronunciation cases.

Example test sentences:

```text
مرحبا، هذا اختبار لجودة النطق العربي.
وصلت الشحنة في الخامس والعشرين من يونيو عام ألفين وستة وعشرين.
سعر الاشتراك الشهري هو مئة وتسعة وتسعون جنيها.
يرجى التأكد من كتابة الاسم ورقم الهاتف بشكل صحيح.
```

For each model:

1. Generate audio from the baseline model.
2. Run Arabic ASR on the generated audio.
3. Calculate WER/CER where possible.
4. Ask native Arabic listeners to rate:
   - pronunciation,
   - naturalness,
   - dialect accuracy,
   - speaker similarity if cloning is used,
   - stability on long text.

## Phase 2: VoxCPM2 Setup

Clone and install:

```bash
git clone https://github.com/OpenBMB/VoxCPM.git
cd VoxCPM
python -m venv .venv
source .venv/bin/activate
pip install -e .
pip install torch torchaudio
```

Quick Arabic test:

```bash
voxcpm design \
  --text "مرحبا، هذا اختبار للصوت العربي." \
  --output arabic_test.wav
```

Run the web demo:

```bash
python app.py
```

The web UI normally runs on:

```text
http://localhost:8808
```

## Phase 3: VoxCPM2 Fine-Tuning

### Data Format

VoxCPM2 expects JSONL with one sample per line.

Basic format:

```jsonl
{"audio": "/data/ar/wavs/0001.wav", "text": "النص العربي المطابق للصوت."}
{"audio": "/data/ar/wavs/0002.wav", "text": "يجب أن يطابق النص التسجيل بدقة."}
```

Voice cloning format with reference audio:

```jsonl
{"audio": "/data/ar/wavs/0001.wav", "text": "النص الهدف.", "ref_audio": "/data/ar/refs/speaker_ref.wav"}
```

Recommended audio rules:

- WAV is preferred.
- Clips should usually be 3 to 30 seconds.
- Remove clips shorter than 1 second.
- Trim trailing silence to less than 0.5 seconds.
- Remove noisy clips.
- Normalize volume.
- Make sure transcript and audio match exactly.

### LoRA Fine-Tuning

LoRA is the recommended first attempt.

Use it for:

- one Arabic speaker,
- one dialect,
- one speaking style,
- product/domain vocabulary,
- pronunciation improvement with limited data.

Official command:

```bash
python scripts/train_voxcpm_finetune.py \
  --config_path conf/voxcpm_v2/voxcpm_finetune_lora.yaml
```

Recommended LoRA settings:

- `r: 32` for single-speaker adaptation.
- `r: 64` for style, dialect, or language/domain adaptation.
- Keep base model frozen.
- Save multiple checkpoints.
- Stop early if generated audio starts ignoring the input text.

Example config values to review:

```yaml
pretrained_path: /path/to/VoxCPM2/
train_manifest: /path/to/train.jsonl
val_manifest: /path/to/val.jsonl
sample_rate: 16000
out_sample_rate: 48000
batch_size: 16
grad_accum_steps: 1
learning_rate: 0.0001
max_batch_tokens: 8192
save_path: /path/to/checkpoints/lora

lora:
  enable_lm: true
  enable_dit: true
  enable_proj: false
  r: 32
  alpha: 32
  dropout: 0.0
```

LoRA inference:

```bash
python scripts/test_voxcpm_lora_infer.py \
  --lora_ckpt /path/to/checkpoints/lora/latest \
  --text "مرحبا من النموذج المحسن." \
  --output output.wav
```

Python inference:

```python
from voxcpm import VoxCPM
import soundfile as sf

model = VoxCPM.from_pretrained(
    "openbmb/VoxCPM2",
    lora_weights_path="/path/to/checkpoints/lora/latest",
)

wav = model.generate(text="مرحبا من النموذج المحسن.")
sf.write("output.wav", wav, model.tts_model.sample_rate)
```

### Full Fine-Tuning

Only use full fine-tuning if LoRA is not enough.

Use it for:

- large-scale Arabic improvement,
- a new Arabic dialect with enough data,
- broad pronunciation and robustness improvement,
- large production customization.

Official command:

```bash
python scripts/train_voxcpm_finetune.py \
  --config_path conf/voxcpm_v2/voxcpm_finetune_all.yaml
```

Important full fine-tuning notes:

- Use a lower learning rate than LoRA, around `1e-5`.
- Full fine-tuning is more likely to overfit.
- Keep validation audio and listen to each checkpoint.
- For broad Arabic/dialect improvement, expect to need much more data than for one-speaker LoRA.

## Phase 4: OmniVoice Setup

Clone and install:

```bash
git clone https://github.com/k2-fsa/OmniVoice.git
cd OmniVoice
python -m venv .venv
source .venv/bin/activate
pip install -e .
pip install torch torchaudio
```

Run local demo:

```bash
omnivoice-demo --ip 0.0.0.0 --port 8001
```

Python test:

```python
from omnivoice import OmniVoice
import soundfile as sf
import torch

model = OmniVoice.from_pretrained(
    "k2-fsa/OmniVoice",
    device_map="cuda:0",
    dtype=torch.float16,
)

audio = model.generate(
    text="مرحبا، هذا اختبار للصوت العربي.",
    ref_audio="ref.wav",
    ref_text="النص الموجود في التسجيل المرجعي.",
)

sf.write("out.wav", audio[0], 24000)
```

OmniVoice reference audio tips from upstream:

- Use a 3 to 10 second reference clip.
- Use same-language reference audio when possible.
- Cross-lingual cloning can carry the accent of the reference language.
- Normalize Arabic numerals to words before synthesis.

## Phase 5: OmniVoice Fine-Tuning

OmniVoice fine-tuning uses the official example script:

```bash
bash examples/run_finetune.sh
```

Before running it, edit the variables at the top of `examples/run_finetune.sh`:

```bash
TRAIN_JSONL="data/arabic_train.jsonl"
DEV_JSONL="data/arabic_dev.jsonl"
GPU_IDS="0,1"
NUM_GPUS=2
OUTPUT_DIR="exp/omnivoice_arabic_finetune"
```

OmniVoice JSONL format:

```jsonl
{"id": "ar_0001", "audio_path": "/data/ar/wavs/0001.wav", "text": "النص العربي.", "language_id": "arb"}
{"id": "eg_0001", "audio_path": "/data/eg/wavs/0001.wav", "text": "النص باللهجة المصرية.", "language_id": "arz"}
```

Notes:

- `id`, `audio_path`, and `text` are mandatory.
- `language_id` is optional, but it is useful for Arabic dialect control.
- Use the language IDs from OmniVoice's language documentation.
- Standard Arabic is listed as `arb`.
- Egyptian Arabic is commonly `arz`.

The script does two main things:

1. Tokenizes audio into WebDataset shards.
2. Launches fine-tuning with `accelerate`.

## Arabic Data Strategy

### Data Amount Targets

For VoxCPM2 LoRA:

- 5 to 10 minutes: possible single-speaker adaptation.
- 30 to 120 minutes: better single-speaker adaptation.
- 2 to 10 hours: stronger speaker/style adaptation.
- 50 to 500 clips: useful domain/style adaptation.

For broader Arabic improvement:

- 10+ hours: useful experiment.
- 50+ hours: meaningful Arabic/domain improvement.
- 100+ hours: stronger dialect and robustness improvement.
- 500+ hours: closer to full language-level adaptation.

### Recommended Data Sources

Best source:

- Your own licensed, clean Arabic recordings.

Useful public/research sources:

- ArVoice: <https://arxiv.org/abs/2505.20506>
- ArVoice dataset: <https://huggingface.co/datasets/MBZUAI/ArVoice>
- Arabic Speech Corpus: <https://en.arabicspeechcorpus.com/>
- ClArTTS paper: <https://arxiv.org/abs/2303.00069>
- FLEURS Arabic for evaluation: <https://huggingface.co/datasets/google/fleurs>

Important licensing note:

- Check each dataset license before commercial use.
- Some Arabic datasets are research-only or non-commercial.
- Do not train on voices unless you have permission to use them.

### Arabic Text Normalization

Arabic needs careful text preparation before fine-tuning.

Recommended normalization:

- Convert digits to Arabic words.
- Normalize Arabic and Indic digits.
- Remove tatweel.
- Normalize punctuation.
- Normalize whitespace.
- Decide whether to normalize alef forms.
- Decide whether to normalize ya/alef maqsura.
- Decide whether to keep or remove diacritics.
- Keep transcripts consistent across the entire dataset.

Diacritics:

- Diacritics can improve pronunciation if they are correct.
- Wrong diacritics can make quality worse.
- For MSA, a high-quality diacritized dataset is valuable.
- For dialects, forced MSA diacritics may be harmful if they do not match actual pronunciation.

Numbers:

- Always verbalize numbers.
- Example: `2026` should become a spoken form, not raw digits.
- For product speech, manually check prices, dates, phone numbers, and IDs.

## Arabic Dataset Shortlist

Use this order for Arabic cloning and fine-tuning data:

1. **NileTTS** for Egyptian Arabic.
2. **ArVoice** for Modern Standard Arabic.
3. **Arabic Speech Corpus** for a small clean studio-recorded Arabic TTS baseline.
4. **ClArTTS** for Classical/formal Arabic.
5. **Common Voice, FLEURS, QASR, SADA, and ARCADE** mainly for evaluation, dialect coverage, ASR checks, or noisy adaptation after filtering.

For real production voice cloning, the best dataset is still your own consented recording session: 30-120 minutes from the exact target speaker, recorded cleanly, with exact transcripts and explicit permission.

### NileTTS

Links:

- Dataset: <https://huggingface.co/datasets/KickItLikeShika/NileTTS-dataset>
- Code: <https://github.com/KickItLikeShika/NileTTS>
- Paper: <https://arxiv.org/abs/2602.15675>
- Fine-tuned model: <https://huggingface.co/KickItLikeShika/NileTTS-XTTS>

Best use:

- Egyptian Arabic TTS fine-tuning.
- Egyptian Arabic pronunciation adaptation.
- XTTS-style cloning/fine-tuning experiments.
- VoxCPM2 or OmniVoice LoRA/domain adaptation after metadata conversion.

Confirmed details:

- 38.1 hours.
- 9,521 utterances.
- 2 speakers: 1 male, 1 female.
- Domains: medical, sales/customer service, and general conversation.
- WAV, 24 kHz.
- Apache-2.0 license.
- Metadata format:

```text
audio_file|text|speaker_name
wav/sales_audioid_chunkidx.wav|مرحبا، إزيك النهارده؟|SPEAKER_01
```

Important caveat:

- The audio is synthetic, generated through a NotebookLM-based pipeline. It is useful for dialect adaptation, but it is not a real human-speaker consent dataset.

### ArVoice

Links:

- Dataset: <https://huggingface.co/datasets/MBZUAI/ArVoice>
- Paper: <https://arxiv.org/abs/2505.20506>

Best use:

- MSA fine-tuning.
- Diacritized Arabic training.
- Multi-speaker Arabic TTS experiments.

Confirmed details:

- Hugging Face dataset has a CC-BY-4.0 license label.
- Dataset viewer shows 23.1k rows.
- Train/test split is available.
- Paper reports 83.52 total hours across human and synthetic parts.
- Paper reports around 10 hours of human voices from 7 speakers.
- Transcripts are diacritized.

Important caveat:

- The paper says professionally recorded subsets are granted to qualified researchers under a Data Usage Agreement, while public parts are available through Hugging Face. Verify exactly which subset you are using before commercial use.

### Arabic Speech Corpus

Link:

- Official site: <https://en.arabicspeechcorpus.com/>

Best use:

- Small clean Arabic TTS baseline.
- Quick VoxCPM2 LoRA experiments.
- Fine-tuning a single Arabic voice.
- Testing Arabic transcript normalization and phoneme coverage.

Confirmed details:

- 1813 WAV files.
- 1813 text utterance files.
- TextGrid phoneme labels.
- Orthographic and phonetic transcripts.
- Recorded in a professional studio.
- Official site says it is licensed under Creative Commons Attribution 4.0 International.

Important caveat:

- It is small.
- The orthographic transcript is in Buckwalter format, so convert it to Arabic script for most modern TTS workflows.

### ClArTTS

Link:

- Paper: <https://arxiv.org/abs/2303.00069>

Best use:

- Classical Arabic TTS.
- Single-speaker Arabic fine-tuning experiments.
- Testing diacritized Arabic.

Confirmed details:

- About 12 hours.
- Single male speaker.
- 10,334 utterances.
- Manually transcribed and annotated.
- Fully diacritized transcripts.
- Built from LibriVox audiobook material.
- Paper says released for research use.

Important caveat:

- Classical Arabic, not necessarily modern conversational Arabic.
- Check current dataset access and license before commercial use.

### Useful but Not Ideal for Direct TTS Fine-Tuning

Common Voice Arabic:

- Good for broad speaker/accent exposure and ASR evaluation.
- Usually CC0/public-domain style.
- Not clean TTS data: quality varies, speaker identity is fragmented, and clips need filtering.

FLEURS Arabic:

- Dataset: <https://huggingface.co/datasets/google/fleurs>
- Good for evaluation and multilingual baseline tests.
- Hugging Face shows Arabic Egypt subset `ar_eg`.
- CC-BY-4.0 license.
- Small and ASR-oriented, so not ideal for voice cloning.

QASR:

- Paper: <https://arxiv.org/abs/2106.13000>
- 2,000 hours from Al Jazeera broadcast, sampled at 16 kHz.
- Useful for ASR, speaker/dialect research, or noisy pre-adaptation after heavy filtering.
- Not clean direct TTS data.

SADA:

- Paper: <https://arxiv.org/abs/2508.12968>
- 668 hours from Saudi television shows.
- Useful for Saudi/dialect ASR experiments and dialect exposure after filtering.
- Not clean direct TTS data.

ARCADE:

- Dataset: <https://huggingface.co/datasets/riotu-lab/ARCADE-full>
- Paper: <https://arxiv.org/abs/2601.02209>
- 6,907 annotations and 3,790 unique audio segments across 58 cities in 19 Arab countries.
- Useful for dialect identification and regional Arabic audio examples.
- Not suitable for direct TTS fine-tuning unless you transcribe and clean it yourself.

### Dataset Conversion Examples

VoxCPM2 JSONL:

```jsonl
{"audio": "/absolute/path/to/audio.wav", "text": "النص المطابق للصوت."}
```

VoxCPM2 JSONL with reference audio:

```jsonl
{"audio": "/absolute/path/to/target.wav", "text": "النص الهدف.", "ref_audio": "/absolute/path/to/reference.wav"}
```

OmniVoice JSONL:

```jsonl
{"id": "nile_000001", "audio_path": "/data/NileTTS/wav/sales_audioid_chunkidx.wav", "text": "مرحبا، إزيك النهارده؟", "language_id": "arz"}
```

Use `arz` for Egyptian Arabic when using OmniVoice language IDs.

### Cloning Data Advice

For cloning one Arabic voice, do not rely on public datasets unless the speaker/license explicitly allows cloning.

Best recording recipe:

- 30-120 minutes of clean speech from the target speaker.
- 3-15 second clips.
- 24 kHz or 48 kHz WAV.
- Quiet room, same microphone, consistent distance.
- Exact transcripts.
- Include numbers, names, dates, questions, statements, and emotional variation.
- Keep 10 percent as validation.

## Evaluation Plan

Evaluate every model and checkpoint using the same held-out test set.

Automatic metrics:

- Arabic ASR WER.
- Arabic ASR CER.
- Speaker similarity if cloning is required.
- Duration ratio compared with expected speech length.
- Failure rate: empty audio, repeated audio, does not stop, wrong language.

Human evaluation:

- Pronunciation accuracy.
- Naturalness.
- Dialect correctness.
- Prosody and pacing.
- Speaker similarity.
- Listening fatigue on long outputs.

Acceptance criteria example:

- WER/CER improves compared with the baseline.
- Native listeners prefer fine-tuned output over base output.
- No increase in repeated or runaway generation.
- Numbers and names are pronounced correctly.
- The model still follows arbitrary new input text.

## Practical Execution Plan

1. Create the Arabic evaluation set.
2. Run baseline VoxCPM2 and OmniVoice generations.
3. Score outputs with ASR and human listening.
4. Prepare a clean Arabic training set.
5. Start with VoxCPM2 LoRA.
6. Evaluate checkpoints every 500 to 1000 steps.
7. Pick the best LoRA checkpoint by listening tests, not training loss alone.
8. Run the same dataset through OmniVoice fine-tuning.
9. Compare VoxCPM2 LoRA vs OmniVoice fine-tuned output.
10. Only attempt VoxCPM2 full fine-tuning if LoRA cannot fix the Arabic issue.

## Expected Best Path

For this project, the most efficient path is:

1. Use VoxCPM2 base for Arabic.
2. Add Arabic text normalization before synthesis.
3. Fine-tune VoxCPM2 with LoRA on clean Arabic data.
4. Keep OmniVoice as a comparison model.
5. Move to full fine-tuning only after a measured LoRA failure.

## Safety and Responsible Use

Both VoxCPM2 and OmniVoice support voice cloning. Use them only with consent.

Rules:

- Do not clone a person's voice without permission.
- Do not use generated speech for impersonation, fraud, scams, or disinformation.
- Label generated audio where appropriate.
- Keep records of dataset licenses and speaker consent.

## Source Links

- VoxCPM GitHub: <https://github.com/OpenBMB/VoxCPM>
- VoxCPM2 Hugging Face: <https://huggingface.co/openbmb/VoxCPM2>
- VoxCPM2 quick start: <https://voxcpm.readthedocs.io/en/latest/quickstart.html>
- VoxCPM2 fine-tuning guide: <https://voxcpm.readthedocs.io/en/latest/finetuning/finetune.html>
- OmniVoice GitHub: <https://github.com/k2-fsa/OmniVoice>
- OmniVoice Hugging Face: <https://huggingface.co/k2-fsa/OmniVoice>
- OmniVoice examples: <https://github.com/k2-fsa/OmniVoice/tree/master/examples>
- OmniVoice language list: <https://github.com/k2-fsa/OmniVoice/blob/master/docs/languages.md>
- NileTTS dataset: <https://huggingface.co/datasets/KickItLikeShika/NileTTS-dataset>
- NileTTS code: <https://github.com/KickItLikeShika/NileTTS>
- NileTTS paper: <https://arxiv.org/abs/2602.15675>
- ArVoice paper: <https://arxiv.org/abs/2505.20506>
- ArVoice dataset: <https://huggingface.co/datasets/MBZUAI/ArVoice>
- Arabic Speech Corpus: <https://en.arabicspeechcorpus.com/>
- ClArTTS paper: <https://arxiv.org/abs/2303.00069>
- FLEURS dataset: <https://huggingface.co/datasets/google/fleurs>
- QASR paper: <https://arxiv.org/abs/2106.13000>
- SADA paper: <https://arxiv.org/abs/2508.12968>
- ARCADE dataset: <https://huggingface.co/datasets/riotu-lab/ARCADE-full>
- ARCADE paper: <https://arxiv.org/abs/2601.02209>
