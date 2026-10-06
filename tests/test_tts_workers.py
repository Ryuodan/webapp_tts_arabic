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
                          {"OMNIVOICE_OUT_DIR": tmp_path / "out",
                           "TTS_CUSTOM_VOICES_DIR": tmp_path / "voices_custom"})
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
    assert meta["text"] == "مرحباً"
    # The sidecar now records which variant/voice/gender produced the clip, not just the
    # prompt. The variant is whatever this host's weights make the default — asserting
    # "base" would fail on any machine that has the fine-tuned checkpoint assembled.
    assert meta["params"] == {"speaker": "whisper", "voice": "", "gender": "",
                              "variant": omni.module.DEFAULT_VARIANT, "voice_label": ""}


# ── Najdi: two fine-tunes whose house voice is Nasser, and any other voice on request ──
@pytest.fixture
def najdi(tmp_path, monkeypatch, fake_omnivoice):
    ckpt = tmp_path / "najdi_v4_ft" / "checkpoint-6250"
    ckpt_v4c = tmp_path / "najdi_v4c_ft" / "checkpoint-1000"
    ckpt.mkdir(parents=True)
    ckpt_v4c.mkdir(parents=True)
    module = fresh_import("omnivoice_server", monkeypatch,
                          {"OMNIVOICE_OUT_DIR": tmp_path / "out",
                           "TTS_CUSTOM_VOICES_DIR": tmp_path / "voices_custom",
                           "OMNIVOICE_NAJDI_MODEL_ID": ckpt,
                           "OMNIVOICE_NAJDI_V4C_MODEL_ID": ckpt_v4c})
    client = TestClient(module.app)
    client.module, client.rec, client.ckpt, client.ckpt_v4c = module, fake_omnivoice, ckpt, ckpt_v4c
    return client


def test_najdi_variant_is_offered_with_its_default_voice(najdi):
    health = najdi.get("/health").json()
    assert health["variants"]["najdi"] == str(najdi.ckpt)
    assert health["variants"]["najdi_v4c"] == str(najdi.ckpt_v4c)
    assert health["variant_default_voices"] == {"najdi": "nasser", "najdi_v4c": "nasser"}
    assert "nasser" in health["voices"]
    assert health["default_variant"] not in ("najdi", "najdi_v4c")     # never the implicit choice


def test_each_najdi_variant_loads_its_own_checkpoint(najdi):
    """v4 and v4 continued are two sets of weights behind one worker."""
    for variant, ckpt in (("najdi_v4c", najdi.ckpt_v4c), ("najdi", najdi.ckpt)):
        body = najdi.post("/synthesize", data={"text": "مرحباً", "variant": variant}).json()
        assert najdi.rec["from_pretrained"][0] == str(ckpt)
        assert body["model_variant"] == variant and body["model_id"] == str(ckpt)
        assert body["voice"] == "nasser"                 # the same house voice on both


def test_najdi_weights_resolve_repo_first_then_training_project(omni, tmp_path, monkeypatch):
    repo, project = tmp_path / "repo_najdi", tmp_path / "project_najdi"
    monkeypatch.delenv("OMNIVOICE_NAJDI_MODEL_ID", raising=False)
    monkeypatch.setattr(omni.module, "REPO_NAJDI_CHECKPOINT", repo)
    monkeypatch.setattr(omni.module, "NAJDI_CHECKPOINT", project)
    assert omni.module._najdi_model_id() is None           # no weights anywhere -> no variant

    project.mkdir(); (project / "model.safetensors").touch()
    assert omni.module._najdi_model_id() == str(project)

    repo.mkdir(); (repo / "model.safetensors").touch()
    assert omni.module._najdi_model_id() == str(repo)


def test_v4c_weights_resolve_the_same_way(omni, tmp_path, monkeypatch):
    repo, project = tmp_path / "repo_v4c", tmp_path / "project_v4c"
    monkeypatch.delenv("OMNIVOICE_NAJDI_V4C_MODEL_ID", raising=False)
    monkeypatch.setattr(omni.module, "REPO_NAJDI_V4C_CHECKPOINT", repo)
    monkeypatch.setattr(omni.module, "NAJDI_V4C_CHECKPOINT", project)
    assert omni.module._najdi_v4c_model_id() is None

    project.mkdir(); (project / "model.safetensors").touch()
    assert omni.module._najdi_v4c_model_id() == str(project)

    repo.mkdir(); (repo / "model.safetensors").touch()
    assert omni.module._najdi_v4c_model_id() == str(repo)

    monkeypatch.setenv("OMNIVOICE_NAJDI_V4C_MODEL_ID", "/elsewhere/v4c")
    assert omni.module._najdi_v4c_model_id() == "/elsewhere/v4c"


def test_najdi_clones_nasser_when_no_voice_is_named(najdi):
    body = najdi.post("/synthesize", data={"text": "مرحباً", "variant": "najdi"}).json()
    kwargs = najdi.rec["generate_kwargs"]
    voice = najdi.module._VOICES["nasser"]
    assert najdi.rec["from_pretrained"][0] == str(najdi.ckpt)
    assert kwargs["ref_audio"] == voice["ref_audio_path"] and kwargs["ref_text"] == voice["ref_text"]
    assert body["voice"] == "nasser" and body["model_variant"] == "najdi"
    assert body["voice_label"] == voice["label"]


def test_najdi_clones_another_voice_when_asked(najdi):
    body = najdi.post("/synthesize", data={"text": "مرحباً", "variant": "najdi",
                                           "voice": "abeer"}).json()
    voice = najdi.module._VOICES["abeer"]
    assert najdi.rec["generate_kwargs"]["ref_audio"] == voice["ref_audio_path"]
    assert body["voice"] == "abeer"


def test_an_uploaded_reference_replaces_the_default_voice(najdi, wav_file):
    body = najdi.post("/synthesize", data={"text": "مرحباً", "variant": "najdi",
                                           "ref_text": "نص المرجع"},
                      files={"ref_audio": ("ref.wav", wav_file.read_bytes(), "audio/wav")}).json()
    kwargs = najdi.rec["generate_kwargs"]
    assert kwargs["ref_audio"] != najdi.module._VOICES["nasser"]["ref_audio_path"]
    assert kwargs["ref_text"] == "نص المرجع"
    assert body["voice"] == "" and body["voice_label"] == ""


@pytest.mark.parametrize("data, code", [
    ({}, "ars"),                                        # the house voice, Nasser: Najdi
    ({"voice": "nora"}, "ars"),
    ({"voice": "ahmed"}, "arb"),                        # an MSA voice stays MSA
    ({"voice": "nora", "dialect": "msa"}, "arb"),       # a dialect the request names wins
    ({"voice": "ahmed", "dialect": "saudi"}, "ars"),
    ({"voice": "nora", "dialect": "klingon"}, "ars"),   # not a dialect: as if none was named
    ({"variant": "base"}, "arb"),                       # no voice at all
    ({"variant": "base", "voice": "nasser"}, "ars"),    # the voice decides, on either model
])
def test_a_saved_voice_is_spoken_in_its_own_dialect(najdi, data, code):
    """The studio names no dialect: each voice.json's `language` picks the code instead."""
    body = najdi.post("/synthesize", data={"text": "مرحباً", "variant": "najdi", **data}).json()
    assert najdi.rec["generate_kwargs"]["language"] == code
    assert body["model_language"] == code


def test_an_uploaded_voice_is_spoken_in_the_dialect_it_was_saved_with(najdi, tmp_path):
    uploaded = add_voice(najdi, voice_wav(tmp_path), dialect="saudi").json()
    assert uploaded["language"] == "ars"
    najdi.post("/synthesize", data={"text": "مرحباً", "variant": "najdi", "voice": uploaded["id"]})
    assert najdi.rec["generate_kwargs"]["language"] == "ars"


def test_voices_without_a_dialect_of_their_own_are_spoken_in_msa(najdi, tmp_path, wav_file):
    """A voice saved with no dialect has none, and a one-off reference is nobody's saved voice."""
    uploaded = add_voice(najdi, voice_wav(tmp_path)).json()
    assert uploaded["language"] == ""
    najdi.post("/synthesize", data={"text": "مرحباً", "variant": "najdi", "voice": uploaded["id"]})
    assert najdi.rec["generate_kwargs"]["language"] == "arb"

    najdi.post("/synthesize", data={"text": "مرحباً", "variant": "najdi", "voice": "nasser"},
               files={"ref_audio": ("ref.wav", wav_file.read_bytes(), "audio/wav")})
    assert najdi.rec["generate_kwargs"]["language"] == "arb"


@pytest.mark.parametrize("variant, voice", [("najdi", ""), ("najdi", "abeer"), ("base", "nasser")])
def test_cloning_keeps_gender_out_of_instruct(najdi, variant, voice):
    """The reference already fixes the speaker's sex — sending gender too could fight it."""
    najdi.post("/synthesize", data={"text": "مرحباً", "variant": variant, "voice": voice,
                                    "gender": "female", "age": "young"})
    assert najdi.rec["generate_kwargs"]["instruct"] == "young adult"


def test_voice_design_without_a_reference_still_uses_gender(najdi):
    najdi.post("/synthesize", data={"text": "مرحباً", "variant": "base", "gender": "female"})
    assert "ref_audio" not in najdi.rec["generate_kwargs"]
    assert najdi.rec["generate_kwargs"]["instruct"] == "female"


def test_the_route_variant_outranks_the_form_field(najdi):
    """The gateway pins ?variant= from the alias; a stale form value must not win."""
    body = najdi.post("/synthesize?variant=najdi",
                      data={"text": "مرحباً", "variant": "base"}).json()
    assert body["model_variant"] == "najdi"


def test_unknown_voice_is_a_400(najdi):
    r = najdi.post("/synthesize", data={"text": "مرحباً", "variant": "najdi", "voice": "nobody"})
    assert r.status_code == 400 and "nobody" in r.json()["detail"]


def test_najdi_without_its_default_voice_files_is_a_503(najdi, monkeypatch):
    monkeypatch.setattr(najdi.module, "_VOICES", {})
    r = najdi.post("/synthesize", data={"text": "مرحباً", "variant": "najdi"})
    assert r.status_code == 503 and "nasser" in r.json()["detail"]


# ── Voice library: named clone voices uploaded from the studio ──
def voice_wav(tmp_path, seconds=3.0, rate=24_000, channels=1, name="voice.wav"):
    shape = (int(seconds * rate), channels) if channels > 1 else int(seconds * rate)
    tone = np.sin(np.linspace(0, 2 * np.pi * 180 * seconds, int(seconds * rate)))
    data = (0.2 * tone).astype(np.float32)
    if channels > 1:
        data = np.stack([data] * channels, axis=1).reshape(shape)
    path = tmp_path / name
    sf.write(str(path), data, rate)
    return path


def add_voice(client, path, name="صوتي", ref_text="هذا نص المرجع", **extra):
    return client.post("/voices", data={"name": name, "ref_text": ref_text, **extra},
                       files={"audio": (path.name, path.read_bytes(), "audio/wav")})


def test_a_named_upload_becomes_a_voice_and_is_used(najdi, tmp_path):
    r = add_voice(najdi, voice_wav(tmp_path), gender="male")
    assert r.status_code == 200, r.text
    voice = r.json()
    assert voice["label"] == "صوتي" and voice["custom"] is True
    assert voice["duration_s"] == 3.0 and voice["gender"] == "male"
    assert "ref_audio_path" not in voice                  # no server paths leak out

    listed = {v["id"]: v for v in najdi.get("/voices").json()["voices"]}
    assert listed[voice["id"]]["label"] == "صوتي" and listed["nasser"]["custom"] is False

    body = najdi.post("/synthesize", data={"text": "مرحباً", "variant": "najdi",
                                           "voice": voice["id"]}).json()
    kwargs = najdi.rec["generate_kwargs"]
    assert kwargs["ref_audio"].startswith(str(tmp_path / "voices_custom"))
    assert kwargs["ref_text"] == "هذا نص المرجع"
    assert body["voice"] == voice["id"] and body["voice_label"] == "صوتي"


def test_voices_are_listed_with_what_they_are(najdi, tmp_path):
    """Built-ins carry the tags from their voice.json, in its `order`; an upload, of which
    only the sex is known, comes after them."""
    uploaded = add_voice(najdi, voice_wav(tmp_path), gender="female").json()
    assert uploaded["tags"] == ["female"]
    assert add_voice(najdi, voice_wav(tmp_path), name="بلا جنس").json()["tags"] == []

    voices = najdi.get("/voices").json()["voices"]
    by_id = {v["id"]: v for v in voices}
    trained = ["nasser", "joud", "nora", "ali", "firas", "majed"]    # the six speakers of najdi_v4
    assert [v["id"] for v in voices][:6] == trained                  # the trained voices lead
    assert [v["id"] for v in voices if "trained" in v["tags"]] == trained
    assert {"male", "najdi", "trained"} <= set(by_id["nasser"]["tags"])
    assert {"female", "najdi", "trained"} <= set(by_id["joud"]["tags"])
    assert "unseen" in by_id["abeer"]["tags"] and "trained" not in by_id["abeer"]["tags"]
    assert [v["custom"] for v in voices] == sorted(v["custom"] for v in voices)


def test_a_voice_json_without_tags_falls_back_to_its_gender(najdi):
    assert najdi.module._voice_tags({"gender": "male"}) == ["male"]
    assert najdi.module._voice_tags({"gender": "", "tags": "male"}) == []    # not a list
    assert najdi.module._voice_tags({"tags": ["female", "", " "]}) == ["female"]


def test_uploaded_voices_survive_a_restart(najdi, tmp_path, monkeypatch, fake_omnivoice):
    vid = add_voice(najdi, voice_wav(tmp_path)).json()["id"]
    again = fresh_import("omnivoice_server", monkeypatch,
                         {"OMNIVOICE_OUT_DIR": tmp_path / "out",
                          "TTS_CUSTOM_VOICES_DIR": tmp_path / "voices_custom"})
    assert again._VOICES[vid]["label"] == "صوتي" and again._VOICES[vid]["custom"] is True


def test_a_stereo_upload_is_stored_as_mono(najdi, tmp_path):
    vid = add_voice(najdi, voice_wav(tmp_path, channels=2)).json()["id"]
    info = sf.info(najdi.module._VOICES[vid]["ref_audio_path"])
    assert info.channels == 1 and info.samplerate == 24_000


def test_the_transcript_is_optional(najdi, tmp_path):
    vid = add_voice(najdi, voice_wav(tmp_path), ref_text="").json()["id"]
    najdi.post("/synthesize", data={"text": "مرحباً", "variant": "najdi", "voice": vid})
    assert "ref_text" not in najdi.rec["generate_kwargs"]  # OmniVoice transcribes it itself


@pytest.mark.parametrize("name, status", [("", 400), ("   ", 400), ("x" * 61, 400)])
def test_a_voice_needs_a_sensible_name(najdi, tmp_path, name, status):
    assert add_voice(najdi, voice_wav(tmp_path), name=name).status_code == status


def test_voice_names_are_unique_including_built_ins(najdi, tmp_path):
    assert add_voice(najdi, voice_wav(tmp_path), name="Sara").status_code == 200
    assert add_voice(najdi, voice_wav(tmp_path), name="  sara ").status_code == 409
    builtin_label = najdi.module._VOICES["nasser"]["label"]
    assert add_voice(najdi, voice_wav(tmp_path), name=builtin_label).status_code == 409


@pytest.mark.parametrize("seconds", [0.5, 31.0])
def test_a_clip_too_short_or_too_long_is_refused(najdi, tmp_path, seconds):
    r = add_voice(najdi, voice_wav(tmp_path, seconds=seconds, rate=8_000))
    assert r.status_code == 400 and "s long" in r.json()["detail"]


def test_an_unreadable_file_or_no_file_is_refused(najdi, tmp_path):
    junk = tmp_path / "junk.wav"; junk.write_bytes(b"not audio at all")
    assert add_voice(najdi, junk).status_code == 400
    assert najdi.post("/voices", data={"name": "no file"}).status_code == 400


def test_an_uploaded_voice_can_be_deleted_but_a_built_in_cannot(najdi, tmp_path):
    vid = add_voice(najdi, voice_wav(tmp_path)).json()["id"]
    vdir = tmp_path / "voices_custom" / vid
    assert vdir.is_dir()

    assert najdi.delete(f"/voices/{vid}").json() == {"deleted": vid}
    assert not vdir.exists() and vid not in najdi.module._VOICES
    assert najdi.delete(f"/voices/{vid}").status_code == 404
    assert najdi.delete("/voices/nasser").status_code == 403
    assert "nasser" in najdi.module._VOICES


def test_a_voice_reference_can_be_played(najdi, tmp_path):
    vid = add_voice(najdi, voice_wav(tmp_path)).json()["id"]
    r = najdi.get(f"/voices/{vid}/audio")
    assert r.status_code == 200 and r.headers["content-type"] == "audio/wav"
    assert najdi.get("/voices/nasser/audio").status_code == 200
    assert najdi.get("/voices/nobody/audio").status_code == 404


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
