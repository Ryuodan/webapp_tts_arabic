"""The three TTS workers, with their model libraries faked.

The logic worth protecting is the dialect/persona injection: each engine takes Arabic a
different way (OmniVoice via an ISO language code, VoxCPM2 via a leading parenthetical,
Fish via a bracketed tag) and the frontend previews the exact string, so any drift here
silently changes what the user hears.
"""
import json

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from conftest import fresh_import


# ══ OmniVoice ═════════════════════════════════════════════════
@pytest.fixture
def omni(tmp_path, monkeypatch, fake_omnivoice):
    module = fresh_import("omnivoice_server", monkeypatch,
                          {"OMNIVOICE_OUT_DIR": tmp_path / "out"})
    client = TestClient(module.app)
    client.module, client.rec = module, fake_omnivoice
    return client


def test_omni_health_and_lazy_load(omni):
    assert omni.get("/health").json()["model_loaded"] is False
    omni.post("/load")
    assert omni.get("/health").json()["model_loaded"] is True


@pytest.mark.parametrize("dialect,code", [
    ("msa", "arb"), ("saudi", "ars"), ("egyptian", "arz"),
    ("", "arb"), ("klingon", "arb"), ("SAUDI", "ars"),
])
def test_omni_dialect_rides_the_language_code(omni, dialect, code):
    """OmniVoice rejects Arabic in `instruct`; the dialect must travel as an ISO 639-3 code."""
    body = omni.post("/synthesize", data={"text": "مرحباً", "dialect": dialect}).json()
    assert omni.rec["generate_kwargs"]["language"] == code
    assert body["model_language"] == code


def test_omni_instruct_carries_only_voice_design_tokens(omni):
    omni.post("/synthesize", data={"text": "مرحباً", "dialect": "saudi",
                                   "gender": "female", "age": "old", "speaker": "low pitch"})
    instruct = omni.rec["generate_kwargs"]["instruct"]
    assert instruct == "low pitch, female, elderly"
    assert "Arabic" not in instruct and "ars" not in instruct


def test_omni_omits_instruct_when_no_persona_is_chosen(omni):
    """An empty instruct is left out entirely so the model picks its own voice."""
    omni.post("/synthesize", data={"text": "مرحباً", "gender": "", "age": "", "speaker": ""})
    assert "instruct" not in omni.rec["generate_kwargs"]


def test_omni_ignores_unknown_persona_values(omni):
    omni.post("/synthesize", data={"text": "مرحباً", "gender": "robot", "age": "ancient"})
    assert "instruct" not in omni.rec["generate_kwargs"]


def test_omni_overrides_are_used_verbatim(omni):
    """Manual-edit mode: the worker must not re-inject anything over the user's string."""
    omni.post("/synthesize", data={"text": "ignored", "gender": "male",
                                   "model_input_override": "نص يدوي",
                                   "model_instruct_override": "whisper"})
    kwargs = omni.rec["generate_kwargs"]
    assert kwargs["text"] == "نص يدوي" and kwargs["instruct"] == "whisper"


def test_omni_reference_audio_is_written_then_cleaned_up(omni, wav_file):
    omni.post("/synthesize", data={"text": "مرحباً", "ref_text": " النص المرجعي "},
              files={"ref_audio": ("ref.wav", wav_file.read_bytes(), "audio/wav")})
    kwargs = omni.rec["generate_kwargs"]
    assert kwargs["ref_text"] == "النص المرجعي"
    import os
    assert not os.path.exists(kwargs["ref_audio"])     # temp file removed after the call


def test_omni_writes_audio_metrics_and_sidecar(omni):
    omni.rec["audio"] = [np.zeros(48_000, dtype=np.float32)]   # 2s at 24 kHz

    body = omni.post("/synthesize", data={"text": "مرحباً", "speaker": "whisper"}).json()

    wav = omni.module.OUT_DIR / body["filename"]
    assert sf.info(str(wav)).samplerate == 24_000
    assert body["duration_s"] == 2.0 and body["sample_rate"] == 24_000
    meta = json.loads(wav.with_suffix(".json").read_text(encoding="utf-8"))
    assert meta["text"] == "مرحباً" and meta["params"] == {"speaker": "whisper"}


def test_omni_generation_failure_is_a_500(omni):
    omni.rec["error"] = "CUDA OOM"
    r = omni.post("/synthesize", data={"text": "مرحباً"})
    assert r.status_code == 500 and "CUDA OOM" in r.json()["detail"]


# ══ VoxCPM2 ═══════════════════════════════════════════════════
@pytest.fixture
def vox(tmp_path, monkeypatch, fake_voxcpm):
    module = fresh_import("voxcpm2_server", monkeypatch, {"VOXCPM2_OUT_DIR": tmp_path / "out"})
    client = TestClient(module.app)
    client.module, client.rec = module, fake_voxcpm
    return client


def test_vox_health_reports_the_models_sample_rate_after_load(vox):
    vox.post("/load")
    assert vox.get("/health").json()["sample_rate"] == 48_000


@pytest.mark.parametrize("dialect,descriptor", [
    ("msa", "Modern Standard Arabic"),
    ("saudi", "Saudi (Najdi) Arabic"),
    ("egyptian", "Egyptian Arabic"),
    ("nonsense", "Modern Standard Arabic"),
])
def test_vox_dialect_rides_the_leading_parenthetical(vox, dialect, descriptor):
    vox.post("/synthesize", data={"text": "مرحباً", "dialect": dialect})
    assert vox.rec["generate_kwargs"]["text"] == f"({descriptor}) مرحباً"


def test_vox_cue_orders_style_then_persona_then_dialect(vox):
    body = vox.post("/synthesize", data={"text": "مرحباً", "dialect": "egyptian",
                                         "style": "calm, formal", "gender": "male",
                                         "age": "young"}).json()
    expected = "(calm, formal, male young adult, Egyptian Arabic) مرحباً"
    assert vox.rec["generate_kwargs"]["text"] == expected
    assert body["model_input"] == expected      # what the UI previews


def test_vox_override_replaces_the_whole_cue(vox):
    vox.post("/synthesize", data={"text": "ignored", "style": "calm",
                                  "model_input_override": "(happy) نص يدوي"})
    assert vox.rec["generate_kwargs"]["text"] == "(happy) نص يدوي"


def test_vox_sampling_parameters_reach_the_model(vox):
    vox.post("/synthesize", data={"text": "مرحباً", "cfg_value": "3.5",
                                  "inference_timesteps": "20"})
    kwargs = vox.rec["generate_kwargs"]
    assert kwargs["cfg_value"] == 3.5 and kwargs["inference_timesteps"] == 20


def test_vox_defaults_match_the_documented_balance(vox):
    vox.post("/synthesize", data={"text": "مرحباً"})
    kwargs = vox.rec["generate_kwargs"]
    assert kwargs["cfg_value"] == 2.0 and kwargs["inference_timesteps"] == 10


def test_vox_cloning_inputs_are_passed_and_cleaned_up(vox, wav_file):
    import os
    audio = wav_file.read_bytes()
    vox.post("/synthesize", data={"text": "مرحباً", "prompt_text": "  نص البرومبت  "},
             files={"reference_wav": ("r.wav", audio, "audio/wav"),
                    "prompt_wav": ("p.wav", audio, "audio/wav")})
    kwargs = vox.rec["generate_kwargs"]
    assert kwargs["prompt_text"] == "نص البرومبت"
    assert not os.path.exists(kwargs["reference_wav_path"])
    assert not os.path.exists(kwargs["prompt_wav_path"])


def test_vox_blank_prompt_text_is_omitted(vox):
    vox.post("/synthesize", data={"text": "مرحباً", "prompt_text": "   "})
    assert "prompt_text" not in vox.rec["generate_kwargs"]


def test_vox_generation_failure_is_a_500(vox):
    vox.rec["error"] = "diffusion diverged"
    assert vox.post("/synthesize", data={"text": "مرحباً"}).status_code == 500


# ══ Fish S2 Pro (retired worker, still shipped) ═══════════════
@pytest.fixture
def fish(tmp_path, monkeypatch):
    binary = tmp_path / "s2"
    model = tmp_path / "s2-pro-q4_k_m.gguf"
    binary.write_text("#!/bin/sh\n")
    model.write_bytes(b"gguf")

    module = fresh_import("fish_server", monkeypatch, {
        "FISH_OUT_DIR": tmp_path / "out", "S2_BIN": binary, "FISH_MODEL": model})

    captured = {}

    class FakeProc:
        returncode = 0

        async def communicate(self):
            return b"", b""

    async def fake_exec(*cmd, **kwargs):
        captured["cmd"] = list(cmd)
        out = cmd[cmd.index("-o") + 1]
        sf.write(out, np.zeros(16_000, dtype=np.float32), 16_000)   # 1s of "audio"
        proc = FakeProc()
        proc.returncode = captured.get("returncode", 0)
        return proc

    monkeypatch.setattr(module.asyncio, "create_subprocess_exec", fake_exec)
    client = TestClient(module.app)
    client.module, client.captured = module, captured
    return client


def test_fish_health_reflects_missing_artifacts(tmp_path, monkeypatch):
    module = fresh_import("fish_server", monkeypatch, {
        "FISH_OUT_DIR": tmp_path / "out", "S2_BIN": tmp_path / "absent"})
    body = TestClient(module.app).get("/health").json()
    assert body["ready"] is False and body["binary_exists"] is False


def test_fish_refuses_to_run_without_its_binary(tmp_path, monkeypatch):
    module = fresh_import("fish_server", monkeypatch, {
        "FISH_OUT_DIR": tmp_path / "out", "S2_BIN": tmp_path / "absent"})
    r = TestClient(module.app).post("/synthesize", data={"text": "مرحباً"})
    assert r.status_code == 503 and "s2 binary" in r.json()["detail"]


@pytest.mark.parametrize("dialect,descriptor", [
    ("msa", "Modern Standard Arabic"), ("egyptian", "Egyptian Arabic"),
])
def test_fish_dialect_rides_the_bracket_tag(fish, dialect, descriptor):
    body = fish.post("/synthesize", data={"text": "مرحباً", "dialect": dialect}).json()
    assert body["model_input"] == f"[speak in {descriptor}] مرحباً"


def test_fish_persona_replaces_the_bare_speak_tag(fish):
    body = fish.post("/synthesize", data={"text": "مرحباً", "dialect": "saudi",
                                          "gender": "female", "age": "middle"}).json()
    assert body["model_input"] == \
        "[female middle-aged voice speaking in Saudi (Najdi) Arabic] مرحباً"


def test_fish_sampling_flags_reach_the_binary(fish):
    fish.post("/synthesize", data={"text": "مرحباً", "temperature": "0.5",
                                   "top_p": "0.9", "top_k": "12", "max_tokens": "512"})
    cmd = fish.captured["cmd"]
    for flag, value in [("--temperature", "0.5"), ("--top-p", "0.9"),
                        ("--top-k", "12"), ("--max-tokens", "512")]:
        assert cmd[cmd.index(flag) + 1] == value
    assert "--normalize" in cmd and "--trim-silence" in cmd


def test_fish_reference_audio_adds_the_prompt_flags(fish, wav_file):
    fish.post("/synthesize", data={"text": "مرحباً", "reference_text": "مرجع"},
              files={"reference_audio": ("r.wav", wav_file.read_bytes(), "audio/wav")})
    cmd = fish.captured["cmd"]
    assert "-pa" in cmd and cmd[cmd.index("-pt") + 1] == "مرجع"


def test_fish_reports_binary_failure(fish):
    fish.captured["returncode"] = 1
    r = fish.post("/synthesize", data={"text": "مرحباً"})
    assert r.status_code == 500 and "s2 error" in r.json()["detail"]


def test_fish_writes_metrics_and_sidecar(fish):
    body = fish.post("/synthesize", data={"text": "مرحباً"}).json()
    wav = fish.module.OUT_DIR / body["filename"]
    assert wav.exists() and body["duration_s"] == 1.0
    meta = json.loads(wav.with_suffix(".json").read_text(encoding="utf-8"))
    assert meta["text"] == "مرحباً" and meta["params"]["temperature"] == 0.7
