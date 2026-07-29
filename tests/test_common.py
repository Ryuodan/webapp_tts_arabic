"""workers/_common.py — the helpers all four workers share."""
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import _common
from conftest import fresh_import, write_wav


# ── output_dir ────────────────────────────────────────────────
def test_output_dir_defaults_under_the_workdir(tmp_path, monkeypatch):
    common = fresh_import("_common", monkeypatch, {"TTS_WORKDIR": tmp_path})
    path = common.output_dir("SOME_OUT_DIR", "outputs_x")
    assert path == tmp_path / "outputs_x"
    assert path.is_dir()          # created eagerly so the first write cannot fail


def test_output_dir_env_override_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("SOME_OUT_DIR", str(tmp_path / "elsewhere"))
    assert _common.output_dir("SOME_OUT_DIR", "ignored") == tmp_path / "elsewhere"


def test_output_dir_expands_a_tilde(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("SOME_OUT_DIR", "~/audio")
    assert _common.output_dir("SOME_OUT_DIR", "ignored") == tmp_path / "audio"


def test_output_dir_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("SOME_OUT_DIR", str(tmp_path / "twice"))
    first = _common.output_dir("SOME_OUT_DIR", "x")
    (first / "keep.txt").write_text("data")
    assert _common.output_dir("SOME_OUT_DIR", "x") == first
    assert (first / "keep.txt").exists()      # an existing directory is never clobbered


# ── write_sidecar ─────────────────────────────────────────────
def test_write_sidecar_stores_readable_arabic(tmp_path):
    wav = tmp_path / "clip.wav"
    _common.write_sidecar(wav, {"text": "مرحباً", "rtf": 0.5})

    raw = wav.with_suffix(".json").read_text(encoding="utf-8")
    assert "مرحباً" in raw            # not \u-escaped, so the files stay greppable
    assert json.loads(raw) == {"text": "مرحباً", "rtf": 0.5}


def test_write_sidecar_never_raises(tmp_path):
    """A sidecar is bookkeeping — losing it must not fail a synthesis that already ran."""
    _common.write_sidecar(tmp_path / "missing-dir" / "clip.wav", {"text": "x"})
    _common.write_sidecar(tmp_path / "clip.wav", {"unserialisable": object()})


# ── register_audio_route ──────────────────────────────────────
@pytest.fixture
def served(tmp_path):
    app = FastAPI()
    _common.register_audio_route(app, tmp_path)
    write_wav(tmp_path / "clip.wav")
    return TestClient(app)


def test_audio_route_serves_a_wav(served):
    r = served.get("/audio/clip.wav")
    assert r.status_code == 200 and r.headers["content-type"] == "audio/wav"


def test_audio_route_404s_on_a_missing_file(served):
    assert served.get("/audio/absent.wav").status_code == 404


@pytest.mark.parametrize("name", ["../conftest.py", "..%2f..%2fserver.py", "%2e%2e%2fx"])
def test_audio_route_blocks_traversal(served, name):
    r = served.get(f"/audio/{name}")
    assert r.status_code == 404
    assert b"import" not in r.content


def test_every_worker_uses_the_shared_helpers(fake_torch):
    """Guards the de-duplication: a worker must not grow its own private copy again."""
    import fish_server, omnivoice_server, transcribe_server, voxcpm2_server

    for module in (fish_server, omnivoice_server, transcribe_server, voxcpm2_server):
        assert module.write_sidecar is _common.write_sidecar, module.__name__
        assert "_write_sidecar" not in vars(module), module.__name__
        assert any(route.path == "/audio/{filename}" for route in module.app.routes), \
            module.__name__
