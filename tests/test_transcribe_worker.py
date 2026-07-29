"""ASR worker (workers/transcribe_server.py) with the transformers stack faked.

The behaviours that matter and are easy to regress: the short-form vs long-form decode
split, keeping `audio_chunk_index` away from generate(), input validation, and persisting
a normalized wav + sidecar so the run shows up in history.
"""
import json

import numpy as np
import pytest
from fastapi.testclient import TestClient

from conftest import fresh_import

NAMAA_CHECKPOINT = "NAMAA-Space/cohere-transcribe-arabic-07-2026-int8"


@pytest.fixture
def asr(tmp_path, monkeypatch, fake_transformers):
    module = fresh_import("transcribe_server", monkeypatch,
                          {"TRANSCRIBE_OUT_DIR": tmp_path / "out"})
    client = TestClient(module.app)
    client.module = module
    client.rec = fake_transformers
    client.out_dir = module.OUT_DIR
    return client


def post(client, upload, **data):
    return client.post("/transcribe", files=upload(), data=data)


# ── Lifecycle ─────────────────────────────────────────────────
def test_health_reports_unloaded_until_the_model_is_pulled_in(asr):
    body = asr.get("/health").json()
    assert body["model_loaded"] is False and body["ready"] is False
    assert body["sample_rate"] == 16_000
    assert body["model_id"] == NAMAA_CHECKPOINT


def test_the_checkpoint_is_pinned_and_not_overridable(tmp_path, monkeypatch, fake_transformers):
    """Only the NAMAA build is supported; env must not be able to point this elsewhere."""
    module = fresh_import("transcribe_server", monkeypatch, {
        "TRANSCRIBE_OUT_DIR": tmp_path / "o",
        "TRANSCRIBE_MODEL_ID": "someone-else/whisper-small",   # a knob that must not exist
    })
    assert module.MODEL_ID == NAMAA_CHECKPOINT


def test_load_endpoint_warms_the_model(asr):
    assert asr.post("/load").json()["status"] == "loaded"
    assert asr.get("/health").json()["model_loaded"] is True
    assert asr.rec["eval_called"] is True     # inference mode, not training


def test_model_is_loaded_lazily_on_first_request(asr, upload):
    assert "model_from_pretrained" not in asr.rec
    post(asr, upload)
    model_id, kwargs = asr.rec["model_from_pretrained"]
    assert model_id == NAMAA_CHECKPOINT
    assert kwargs["device_map"] == "auto"


def test_model_is_loaded_only_once(asr, upload):
    post(asr, upload)
    asr.rec.pop("model_from_pretrained")
    post(asr, upload)
    assert "model_from_pretrained" not in asr.rec


# ── Transcription ─────────────────────────────────────────────
def test_returns_stripped_transcript_and_metrics(asr, upload):
    asr.rec["samples"] = np.zeros(32_000, dtype=np.float32)      # 2s at 16 kHz

    body = post(asr, upload).json()

    assert body["text"] == "مرحباً بالعالم"                       # surrounding blanks trimmed
    assert body["model"] == "transcribe" and body["language"] == "ar"
    assert body["duration_s"] == 2.0
    assert body["sample_rate"] == 16_000
    assert body["elapsed_s"] >= 0 and body["rtf"] >= 0


def test_audio_is_resampled_to_the_models_rate(asr, upload):
    post(asr, upload)
    suffix, rate = asr.rec["load_audio"]
    assert rate == 16_000 and suffix == ".wav"


def test_upload_extension_is_preserved_for_the_decoder(asr, upload):
    """load_audio picks its backend from the suffix — an mp3 must not arrive named .wav."""
    post(asr, lambda: upload("podcast.mp3"))
    assert asr.rec["load_audio"][0] == ".mp3"


def test_extensionless_upload_falls_back_to_wav(asr, upload):
    post(asr, lambda: upload("recording"))
    assert asr.rec["load_audio"][0] == ".wav"


@pytest.mark.parametrize("language", ["ar", "en"])
def test_language_reaches_the_decoder_prompt(asr, upload, language):
    body = post(asr, upload, language=language).json()
    assert asr.rec["processor_kwargs"]["language"] == language
    assert body["language"] == language


def test_language_is_normalised(asr, upload):
    assert post(asr, upload, language="  AR  ").json()["language"] == "ar"


@pytest.mark.parametrize("bad", ["fr", "arabic", "ar-SA", "xx"])
def test_unsupported_language_is_rejected(asr, upload, bad):
    r = post(asr, upload, language=bad)
    assert r.status_code == 400
    assert "Unsupported language" in r.json()["detail"]


@pytest.mark.parametrize("sent,expected", [("true", True), ("false", False)])
def test_punctuation_toggle_reaches_the_processor(asr, upload, sent, expected):
    post(asr, upload, punctuation=sent)
    assert asr.rec["processor_kwargs"]["punctuation"] is expected


def test_punctuation_defaults_to_on(asr, upload):
    post(asr, upload)
    assert asr.rec["processor_kwargs"]["punctuation"] is True


# ── Short-form vs long-form ───────────────────────────────────
def test_short_form_decodes_without_chunk_arguments(asr, upload):
    asr.rec["chunks"] = None
    post(asr, upload)
    assert asr.rec["decode_kwargs"] == {"skip_special_tokens": True}


def test_long_form_passes_chunk_index_to_the_decoder(asr, upload):
    """Chunked audio is reassembled by the processor, which needs the index and language."""
    asr.rec["chunks"] = [0, 1, 2]
    post(asr, upload, language="en")
    assert asr.rec["decode_kwargs"] == {"skip_special_tokens": True,
                                        "audio_chunk_index": [0, 1, 2], "language": "en"}


@pytest.mark.parametrize("chunks", [None, [0, 1]])
def test_generate_never_receives_chunk_bookkeeping(asr, upload, chunks):
    """`audio_chunk_index` is a decode-time argument; generate() would reject it."""
    asr.rec["chunks"] = chunks
    post(asr, upload)
    assert "audio_chunk_index" not in asr.rec["generate_kwargs"]
    assert asr.rec["generate_kwargs"] == {"input_features": "FEATURES", "max_new_tokens": 256}


def test_inputs_are_moved_to_the_models_device_and_dtype(asr, upload):
    post(asr, upload)
    args, kwargs = asr.rec["batch"].moved_to
    assert args == (asr.module._model.device,) and kwargs == {"dtype": asr.module._model.dtype}


def test_max_new_tokens_is_configurable(tmp_path, monkeypatch, fake_transformers, upload):
    module = fresh_import("transcribe_server", monkeypatch,
                          {"TRANSCRIBE_OUT_DIR": tmp_path / "o", "TRANSCRIBE_MAX_NEW_TOKENS": "64"})
    TestClient(module.app).post("/transcribe", files=upload())
    assert fake_transformers["generate_kwargs"]["max_new_tokens"] == 64


# ── Validation ────────────────────────────────────────────────
def test_empty_upload_is_rejected(asr):
    r = asr.post("/transcribe", files={"audio": ("empty.wav", b"", "audio/wav")})
    assert r.status_code == 400 and "Empty" in r.json()["detail"]


def test_missing_upload_is_a_422(asr):
    assert asr.post("/transcribe", data={"language": "ar"}).status_code == 422


def test_oversized_upload_is_rejected_before_the_model_runs(tmp_path, monkeypatch,
                                                            fake_transformers, upload):
    module = fresh_import("transcribe_server", monkeypatch,
                          {"TRANSCRIBE_OUT_DIR": tmp_path / "o", "TTS_MAX_UPLOAD_BYTES": "128"})
    r = TestClient(module.app).post("/transcribe", files=upload())
    assert r.status_code == 413 and "too large" in r.json()["detail"]
    assert "generate_kwargs" not in fake_transformers      # never reached the GPU


def test_upload_cap_is_the_one_every_worker_shares(tmp_path, monkeypatch, fake_transformers):
    """One knob for all workers — a per-worker override would drift from the others."""
    env = {"TTS_MAX_UPLOAD_BYTES": "4096",
           "TRANSCRIBE_OUT_DIR": tmp_path / "asr", "OMNIVOICE_OUT_DIR": tmp_path / "tts"}
    asr = fresh_import("transcribe_server", monkeypatch, env)
    tts = fresh_import("omnivoice_server", monkeypatch, env)

    assert asr.MAX_UPLOAD_BYTES == tts.MAX_UPLOAD_BYTES == 4096


def test_undecodable_audio_is_a_client_error(asr, upload):
    asr.rec["load_error"] = "unknown format"
    r = post(asr, upload)
    assert r.status_code == 400 and "Could not decode audio" in r.json()["detail"]


def test_inference_failure_is_a_server_error(asr, upload):
    asr.rec["decode_error"] = "CUDA out of memory"
    r = post(asr, upload)
    assert r.status_code == 500 and "CUDA out of memory" in r.json()["detail"]


# ── Persistence ───────────────────────────────────────────────
def test_saves_the_normalized_audio_and_a_sidecar(asr, upload):
    import soundfile as sf

    body = post(asr, lambda: upload("meeting.m4a"), language="ar", punctuation="false").json()

    wav = asr.out_dir / body["filename"]
    assert wav.exists() and wav.name.startswith("transcribe_")
    info = sf.info(str(wav))
    assert info.samplerate == 16_000 and info.channels == 1   # normalized, replayable

    meta = json.loads(wav.with_suffix(".json").read_text(encoding="utf-8"))
    assert meta["text"] == "مرحباً بالعالم"
    assert meta["params"] == {"language": "ar", "punctuation": False}
    assert meta["source_filename"] == "meeting.m4a"
    assert meta["created"] > 0


def test_each_run_gets_its_own_file(asr, upload):
    names = {post(asr, upload).json()["filename"] for _ in range(3)}
    assert len(names) == 3


def test_saved_audio_is_served_back(asr, upload):
    name = post(asr, upload).json()["filename"]
    r = asr.get(f"/audio/{name}")
    assert r.status_code == 200 and r.headers["content-type"] == "audio/wav"


def test_audio_route_rejects_traversal(asr):
    assert asr.get("/audio/../../server.py").status_code == 404
