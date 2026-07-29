"""Gateway (server.py) — routing, proxying, error mapping, history and file serving.

The workers are replaced by an httpx MockTransport keyed on port, so these tests cover
the gateway's own logic (including the streaming request body) without any worker running.
"""
import json
from urllib.parse import parse_qsl

import httpx
import pytest
from fastapi.testclient import TestClient

from conftest import fresh_import, write_wav

# Every OmniVoice alias is the same worker; only the ASR worker has its own port.
PORTS = {"omnivoice": 8082, "omnivoice_ft": 8082, "omnivoice_base": 8082, "transcribe": 8084}


@pytest.fixture
def gateway(tmp_path, monkeypatch):
    """server.py with its WORKDIR pointed at tmp_path, plus a scripted worker transport."""
    server = fresh_import("server", monkeypatch, {"TTS_WORKDIR": tmp_path})

    routes = {}          # (port, path) -> dict | httpx.Response | Exception
    seen = []            # every request the gateway made

    def handler(request):
        seen.append(request)
        key = (request.url.port, request.url.path)
        reply = routes.get(key, httpx.Response(404, text=f"no stub for {key}"))
        if isinstance(reply, Exception):
            raise reply
        if isinstance(reply, httpx.Response):
            return reply
        return httpx.Response(200, json=reply)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    # The gateway builds its client in the lifespan; TestClient runs it, so overwrite after.
    with TestClient(server.app) as test_client:
        server._client = client
        test_client.routes = routes
        test_client.seen = seen
        test_client.workdir = tmp_path
        test_client.server = server
        yield test_client


def stub(client, model, path, reply):
    client.routes[(PORTS[model], path)] = reply


# ── /api/status ───────────────────────────────────────────────
def test_status_reports_every_worker(gateway):
    stub(gateway, "omnivoice", "/health", {"model": "OmniVoice", "model_loaded": True})
    stub(gateway, "transcribe", "/health", {"model": "Cohere", "model_loaded": False})

    body = gateway.get("/api/status").json()

    assert set(body) == set(gateway.server.WORKER_URLS) | {"_memory_policy"}
    assert body["transcribe"]["model_loaded"] is False
    # All three OmniVoice aliases share one worker, so they report one health payload.
    for alias in ("omnivoice", "omnivoice_ft", "omnivoice_base"):
        assert body[alias]["model_loaded"] is True


def test_status_polls_each_worker_once_not_once_per_alias(gateway):
    stub(gateway, "omnivoice", "/health", {"model": "OmniVoice", "model_loaded": True})
    stub(gateway, "transcribe", "/health", {"model": "Cohere", "model_loaded": True})

    gateway.get("/api/status")

    health_calls = [r for r in gateway.seen if r.url.path == "/health"]
    assert len(health_calls) == len(set(gateway.server.WORKER_URLS.values()))


def test_status_reports_an_unreachable_worker_as_offline(gateway):
    stub(gateway, "omnivoice", "/health", {"model_loaded": True})
    stub(gateway, "transcribe", "/health", httpx.ConnectError("down"))

    body = gateway.get("/api/status").json()

    assert body["transcribe"] == {"model": "transcribe", "status": "offline",
                                  "ready": False, "model_loaded": False}


def test_status_advertises_the_memory_policy(gateway):
    stub(gateway, "omnivoice", "/health", {"model_loaded": True})
    stub(gateway, "transcribe", "/health", {"model_loaded": True})
    policy = gateway.get("/api/status").json()["_memory_policy"]
    assert policy["single_model_mode"] is True and policy["max_request_mb"] > 0


# ── Synthesis proxy ───────────────────────────────────────────
def test_synthesize_forwards_body_and_returns_worker_json(gateway):
    stub(gateway, "omnivoice", "/synthesize", {"filename": "o.wav", "model": "omnivoice"})

    r = gateway.post("/api/omnivoice/synthesize", data={"text": "مرحباً", "dialect": "saudi"})

    assert r.status_code == 200
    assert r.json()["filename"] == "o.wav"

    sent = gateway.seen[-1]
    assert sent.url.port == PORTS["omnivoice"] and sent.url.path == "/synthesize"
    # Body arrives byte-for-byte, so Arabic survives the hop unchanged.
    fields = dict(parse_qsl(sent.content.decode()))
    assert fields == {"text": "مرحباً", "dialect": "saudi"}
    assert sent.headers["content-type"] == "application/x-www-form-urlencoded"


def test_synthesize_forwards_large_bodies_intact(gateway):
    """Uploads under the cap must reach the worker byte-for-byte."""
    stub(gateway, "omnivoice_base", "/synthesize", {"filename": "v.wav"})
    blob = b"\x00" * (2 * 1024 * 1024)

    r = gateway.post("/api/omnivoice_base/synthesize", data={"text": "hi"},
                     files={"reference_wav": ("ref.wav", blob, "audio/wav")})

    assert r.status_code == 200
    assert gateway.seen[-1].content.count(b"\x00") >= len(blob)


def test_synthesize_drops_hop_by_hop_headers(gateway):
    stub(gateway, "omnivoice", "/synthesize", {"ok": True})
    gateway.post("/api/omnivoice/synthesize", data={"text": "hi"})
    forwarded = gateway.seen[-1].headers
    assert "host" not in {k.lower() for k in forwarded} or forwarded["host"] != "testserver"


@pytest.mark.parametrize("model", ["fish", "unknown", "transcribe"])
def test_synthesize_rejects_non_tts_models(gateway, model):
    """`transcribe` has a worker but is not a speech-out model — it must not be reachable here."""
    r = gateway.post(f"/api/{model}/synthesize", data={"text": "hi"})
    assert r.status_code == 404
    assert model in r.json()["detail"]


def test_synthesize_offline_worker_is_503(gateway):
    stub(gateway, "omnivoice", "/synthesize", httpx.ConnectError("refused"))
    r = gateway.post("/api/omnivoice/synthesize", data={"text": "hi"})
    assert r.status_code == 503
    assert "start.sh" in r.json()["detail"]


def test_synthesize_timeout_is_504(gateway):
    stub(gateway, "omnivoice_base", "/synthesize", httpx.ReadTimeout("slow"))
    r = gateway.post("/api/omnivoice_base/synthesize", data={"text": "hi"})
    assert r.status_code == 504


def test_synthesize_propagates_worker_error(gateway):
    stub(gateway, "omnivoice", "/synthesize", httpx.Response(500, text="CUDA OOM"))
    r = gateway.post("/api/omnivoice/synthesize", data={"text": "hi"})
    assert r.status_code == 500
    assert "CUDA OOM" in r.json()["detail"]


# ── Single-model memory policy ────────────────────────────────
def test_synthesis_unloads_the_other_workers_first(gateway):
    """One checkpoint resident at a time — the ASR model must release before TTS runs."""
    stub(gateway, "omnivoice_ft", "/synthesize", {"filename": "o.wav"})
    stub(gateway, "transcribe", "/unload", {"status": "unloaded"})

    gateway.post("/api/omnivoice_ft/synthesize", data={"text": "مرحباً"})

    calls = [(r.url.port, r.url.path) for r in gateway.seen]
    assert (PORTS["transcribe"], "/unload") in calls
    assert calls.index((PORTS["transcribe"], "/unload")) < \
        calls.index((PORTS["omnivoice_ft"], "/synthesize"))


def test_transcription_unloads_the_tts_worker_first(gateway):
    """The reverse direction: a 2.4 GB ASR load must not land on top of OmniVoice."""
    stub(gateway, "transcribe", "/transcribe", {"text": "مرحباً"})
    stub(gateway, "omnivoice", "/unload", {"status": "unloaded"})

    gateway.post("/api/transcribe", files={"audio": ("c.wav", b"x")})

    calls = [(r.url.port, r.url.path) for r in gateway.seen]
    assert calls.index((PORTS["omnivoice"], "/unload")) < \
        calls.index((PORTS["transcribe"], "/transcribe"))


def test_aliases_of_the_active_worker_are_not_unloaded(gateway):
    """The three OmniVoice aliases are one process; unloading it mid-request would thrash."""
    stub(gateway, "omnivoice_ft", "/synthesize", {"filename": "o.wav"})
    stub(gateway, "transcribe", "/unload", {"status": "unloaded"})

    gateway.post("/api/omnivoice_ft/synthesize", data={"text": "مرحباً"})

    unloads = {r.url.port for r in gateway.seen if r.url.path == "/unload"}
    assert PORTS["omnivoice"] not in unloads


def test_a_dead_worker_does_not_block_the_unload_sweep(gateway):
    """Best-effort: an offline peer must not fail the request that triggered the sweep."""
    stub(gateway, "omnivoice_ft", "/synthesize", {"filename": "o.wav"})
    stub(gateway, "transcribe", "/unload", httpx.ConnectError("down"))

    r = gateway.post("/api/omnivoice_ft/synthesize", data={"text": "مرحباً"})
    assert r.status_code == 200


def test_unload_endpoint_is_exposed_for_every_worker(gateway):
    for model in ("omnivoice_ft", "transcribe"):
        stub(gateway, model, "/unload", {"status": "unloaded"})
        assert gateway.post(f"/api/{model}/unload").json() == {"status": "unloaded"}
    assert gateway.post("/api/nope/unload").status_code == 404


# ── Request size cap ──────────────────────────────────────────
def test_oversized_request_is_rejected_before_reaching_a_worker(gateway):
    gateway.server.MAX_REQUEST_BYTES = 1024
    stub(gateway, "transcribe", "/transcribe", {"text": "unreachable"})

    r = gateway.post("/api/transcribe", files={"audio": ("big.wav", b"\x00" * 4096)})

    assert r.status_code == 413 and "too large" in r.json()["detail"]
    assert not [c for c in gateway.seen if c.url.path == "/transcribe"]


def test_oversized_synthesis_is_rejected_too(gateway):
    gateway.server.MAX_REQUEST_BYTES = 1024
    r = gateway.post("/api/omnivoice_ft/synthesize",
                     files={"ref": ("r.wav", b"\x00" * 4096)})
    assert r.status_code == 413


# ── Transcription proxy ───────────────────────────────────────
def test_transcribe_forwards_to_the_asr_worker(gateway, wav_file):
    stub(gateway, "transcribe", "/transcribe", {"text": "مرحباً", "model": "transcribe"})

    r = gateway.post("/api/transcribe",
                     files={"audio": ("clip.wav", wav_file.read_bytes(), "audio/wav")},
                     data={"language": "ar", "punctuation": "false"})

    assert r.status_code == 200
    assert r.json()["text"] == "مرحباً"
    sent = gateway.seen[-1]
    assert sent.url.port == PORTS["transcribe"] and sent.url.path == "/transcribe"
    assert b"clip.wav" in sent.content and b"punctuation" in sent.content


def test_transcribe_offline_worker_is_503(gateway, wav_file):
    stub(gateway, "transcribe", "/transcribe", httpx.ConnectError("refused"))
    r = gateway.post("/api/transcribe", files={"audio": ("c.wav", b"x")})
    assert r.status_code == 503
    assert "transcribe" in r.json()["detail"]


def test_transcribe_timeout_is_504(gateway):
    stub(gateway, "transcribe", "/transcribe", httpx.ReadTimeout("slow"))
    r = gateway.post("/api/transcribe", files={"audio": ("c.wav", b"x")})
    assert r.status_code == 504


# ── load / per-model status ───────────────────────────────────
@pytest.mark.parametrize("model", ["omnivoice", "omnivoice_ft", "omnivoice_base", "transcribe"])
def test_load_and_status_cover_every_worker(gateway, model):
    stub(gateway, model, "/load", {"status": "loaded"})
    stub(gateway, model, "/health", {"model": model, "model_loaded": True})

    assert gateway.post(f"/api/{model}/load").json() == {"status": "loaded"}
    assert gateway.get(f"/api/{model}/status").json()["model_loaded"] is True


def test_status_of_offline_worker_does_not_raise(gateway):
    stub(gateway, "transcribe", "/health", httpx.ConnectError("down"))
    body = gateway.get("/api/transcribe/status").json()
    assert body["status"] == "offline" and body["ready"] is False


def test_load_unknown_model_is_404(gateway):
    assert gateway.post("/api/nope/load").status_code == 404
    assert gateway.get("/api/nope/status").status_code == 404


# ── History ───────────────────────────────────────────────────
def make_output(workdir, model_dir, name, meta=None, mtime=None):
    import os
    out = workdir / model_dir
    out.mkdir(parents=True, exist_ok=True)
    wav = write_wav(out / name)
    if meta is not None:
        wav.with_suffix(".json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    if mtime is not None:
        os.utime(wav, (mtime, mtime))
    return wav


def test_history_surfaces_transcripts_and_metrics(gateway):
    make_output(gateway.workdir, "outputs_transcribe", "transcribe_a.wav", {
        "text": "مرحباً بالعالم", "language": "ar",
        "params": {"language": "ar", "punctuation": True},
        "duration_s": 12.5, "rtf": 0.4, "elapsed_s": 5.0,
        "created": 1.0, "secret": "should not leak",
    })

    item = gateway.get("/api/transcribe/history").json()[0]

    assert item["filename"] == "transcribe_a.wav"
    assert item["text"] == "مرحباً بالعالم"
    assert item["language"] == "ar"          # ASR-only key must survive the whitelist
    assert item["params"]["punctuation"] is True
    assert item["duration_s"] == 12.5 and item["rtf"] == 0.4
    assert "secret" not in item              # only whitelisted keys are surfaced
    assert item["size_bytes"] > 0 and "mtime" in item


def test_history_is_newest_first_and_honours_limit(gateway):
    for i, ts in enumerate([1_000_000, 3_000_000, 2_000_000]):
        make_output(gateway.workdir, "outputs_omnivoice", f"o{i}.wav", {}, mtime=ts)

    names = [i["filename"] for i in gateway.get("/api/omnivoice/history").json()]
    assert names == ["o1.wav", "o2.wav", "o0.wav"]
    assert len(gateway.get("/api/omnivoice/history?limit=2").json()) == 2


def test_history_tolerates_missing_and_corrupt_sidecars(gateway):
    make_output(gateway.workdir, "outputs_voxcpm2", "clean.wav", None)
    bad = make_output(gateway.workdir, "outputs_voxcpm2", "broken.wav", {})
    bad.with_suffix(".json").write_text("{not json", encoding="utf-8")

    items = gateway.get("/api/voxcpm2/history").json()
    assert len(items) == 2
    assert all("filename" in i for i in items)      # a bad sidecar never sinks the listing


def test_history_of_unwritten_model_is_empty(gateway):
    assert gateway.get("/api/transcribe/history").json() == []


def test_history_unknown_model_is_404(gateway):
    assert gateway.get("/api/nope/history").status_code == 404


# ── Audio serving ─────────────────────────────────────────────
def test_serves_audio_with_no_store(gateway):
    make_output(gateway.workdir, "outputs_transcribe", "t.wav")
    r = gateway.get("/audio/transcribe/t.wav")
    assert r.status_code == 200
    assert r.headers["content-type"] == "audio/wav"
    assert r.headers["cache-control"] == "no-store"   # history reuses filenames after a clear
    assert len(r.content) > 0


@pytest.mark.parametrize("name", ["../../server.py", "..%2f..%2fserver.py", "/etc/passwd"])
def test_audio_path_traversal_is_blocked(gateway, name):
    r = gateway.get(f"/audio/transcribe/{name}")
    assert r.status_code == 404
    assert b"def " not in r.content        # never a source file


def test_audio_unknown_model_or_missing_file_is_404(gateway):
    assert gateway.get("/audio/nope/x.wav").status_code == 404
    assert gateway.get("/audio/transcribe/absent.wav").status_code == 404


def test_fish_outputs_stay_readable(gateway):
    """Fish is retired as a worker but its old recordings must still serve."""
    make_output(gateway.workdir, "outputs", "fish_old.wav", {"text": "قديم"})
    assert gateway.get("/api/fish/history").json()[0]["text"] == "قديم"
    assert gateway.get("/audio/fish/fish_old.wav").status_code == 200


# ── Agent endpoints ───────────────────────────────────────────
def test_prepare_skips_the_llm_when_nothing_is_requested(gateway, monkeypatch):
    import textprep
    monkeypatch.setattr(textprep, "prepare_text",
                        lambda *a, **k: pytest.fail("LLM must not be called"))

    body = gateway.post("/api/prepare", json={"text": "نص", "normalize": False,
                                              "diacritize": False}).json()
    assert body["text"] == "نص" and body["normalized"] == "" and body["normalize"] is False


def test_prepare_returns_agent_output(gateway, monkeypatch):
    import textprep
    monkeypatch.setattr(textprep, "prepare_text",
                        lambda text, dialect, normalize, diacritize: {
                            "text": "مُحضَّر", "dialect": dialect, "normalize": normalize})

    body = gateway.post("/api/prepare", json={"text": "نص", "dialect": "egyptian"}).json()
    assert body["text"] == "مُحضَّر" and body["dialect"] == "egyptian"
    assert body["normalize"] is True          # server default


@pytest.mark.parametrize("payload,status", [
    ({}, 400),                       # missing text
    ({"text": "   "}, 400),          # blank text
])
def test_prepare_validates_input(gateway, payload, status):
    assert gateway.post("/api/prepare", json=payload).status_code == status


def test_prepare_maps_missing_key_to_503_and_failures_to_502(gateway, monkeypatch):
    import textprep

    def boom_config(*a, **k):
        raise RuntimeError("OPENAI_API_KEY is not set")
    monkeypatch.setattr(textprep, "prepare_text", boom_config)
    assert gateway.post("/api/prepare", json={"text": "نص"}).status_code == 503

    def boom_api(*a, **k):
        raise ValueError("upstream 429")
    monkeypatch.setattr(textprep, "prepare_text", boom_api)
    r = gateway.post("/api/prepare", json={"text": "نص"})
    assert r.status_code == 502 and "429" in r.json()["detail"]


def test_compose_passes_every_preference_through(gateway, monkeypatch):
    import compose as compose_mod
    seen = {}

    def fake(job, gender, age, dialect, brief):
        seen.update(job=job, gender=gender, age=age, dialect=dialect, brief=brief)
        return {"text": "نص"}
    monkeypatch.setattr(compose_mod, "compose", fake)

    r = gateway.post("/api/compose", json={"job": "booking", "gender": "female",
                                           "age": "young", "dialect": "saudi", "brief": "ملاحظة"})
    assert r.status_code == 200 and r.json()["text"] == "نص"
    assert seen == {"job": "booking", "gender": "female", "age": "young",
                    "dialect": "saudi", "brief": "ملاحظة"}


def test_compose_requires_a_job(gateway):
    assert gateway.post("/api/compose", json={"job": "  "}).status_code == 400
    assert gateway.post("/api/compose", content=b"not json").status_code == 400


# ── Static hosting ────────────────────────────────────────────
@pytest.mark.parametrize("path", ["/", "/index.html", "/api.html", "/app.js", "/api.js",
                                  "/style.css", "/api.css"])
def test_frontend_assets_are_served(gateway, path):
    assert gateway.get(path).status_code == 200


def test_api_routes_win_over_the_static_mount(gateway):
    """The catch-all mount is last; an API path must never fall through to a 404 page."""
    stub(gateway, "omnivoice", "/health", {"model_loaded": True})
    assert gateway.get("/api/status").headers["content-type"].startswith("application/json")
