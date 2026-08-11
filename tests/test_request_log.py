"""Request log — body summarising, the SQLite store, and the gateway middleware.

The middleware sits outside the router, so these go through the real gateway with the
workers stubbed out (same MockTransport trick as test_gateway.py): what gets logged is a
property of the whole stack, not of the store alone.
"""
import json
import time

import httpx
import pytest
from fastapi.testclient import TestClient

import reqlog
from conftest import fresh_import

PORTS = {"omnivoice_ft": 8082, "transcribe": 8084}


# ── Fixtures ──────────────────────────────────────────────────
@pytest.fixture
def gateway(tmp_path, monkeypatch):
    """server.py with a tmp WORKDIR (so the log db is disposable) and scripted workers."""
    server = fresh_import("server", monkeypatch, {"TTS_WORKDIR": tmp_path})
    routes = {}

    def handler(request):
        reply = routes.get((request.url.port, request.url.path),
                           httpx.Response(404, text="no stub"))
        if isinstance(reply, Exception):
            raise reply
        return reply if isinstance(reply, httpx.Response) else httpx.Response(200, json=reply)

    with TestClient(server.app) as client:
        server._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        client.routes = routes
        client.server = server
        yield client


def stub(client, model, path, reply):
    client.routes[(PORTS[model], path)] = reply


def rows(client, **params):
    return client.get("/api/logs", params=params).json()["items"]


@pytest.fixture
def store(tmp_path):
    log = reqlog.RequestLog(tmp_path / "logs" / "requests.db", retention=3)
    yield log
    log.close()


def entry(**overrides):
    base = {"ts": 1_000_000.0, "method": "POST", "path": "/api/prepare", "route": "/api/prepare",
            "model": None, "status": 200, "duration_ms": 12.0, "req_bytes": 10, "resp_bytes": 20,
            "client": "127.0.0.1", "user_agent": "pytest", "request": None, "response": None,
            "error": None}
    base.update(overrides)
    return base


# ── Body capture ──────────────────────────────────────────────
def test_capture_keeps_both_ends_of_a_body_past_the_cap():
    capture = reqlog.BodyCapture(limit=4)
    for chunk in (b"AB", b"CD", b"EF", b"GH"):
        capture.add(chunk)
    assert capture.total == 8
    assert capture.head == b"ABCD" and capture.tail == b"EFGH"
    assert capture.truncated and capture.chunks() == (b"ABCD", b"EFGH")


def test_capture_under_the_cap_is_not_truncated():
    capture = reqlog.BodyCapture(limit=64)
    capture.add(b"hello")
    assert not capture.truncated and capture.chunks() == (b"hello",)


# ── Summarising ───────────────────────────────────────────────
def capture_of(data: bytes, limit=reqlog.MAX_CAPTURE_BYTES):
    capture = reqlog.BodyCapture(limit=limit)
    capture.add(data)
    return capture


def test_json_body_is_summarised_as_json():
    body = json.dumps({"text": "مرحباً", "normalize": True}).encode()
    assert reqlog.summarize("application/json", capture_of(body)) == \
        {"text": "مرحباً", "normalize": True}


def test_long_strings_are_clipped():
    body = json.dumps({"text": "ا" * (reqlog.MAX_FIELD_CHARS + 500)}).encode()
    summary = reqlog.summarize("application/json", capture_of(body))
    assert len(summary["text"]) < reqlog.MAX_FIELD_CHARS + 60
    assert summary["text"].endswith("chars)")


def test_urlencoded_body_is_summarised_as_fields():
    assert reqlog.summarize("application/x-www-form-urlencoded",
                            capture_of(b"text=hi&dialect=saudi")) == \
        {"text": "hi", "dialect": "saudi"}


def multipart(parts, boundary=b"BOUND"):
    """Build a multipart body from (name, filename|None, content_type|None, value) tuples."""
    out = b""
    for name, filename, content_type, value in parts:
        disposition = f'form-data; name="{name}"'
        if filename:
            disposition += f'; filename="{filename}"'
        out += b"--" + boundary + b"\r\n"
        out += f"Content-Disposition: {disposition}\r\n".encode()
        if content_type:
            out += f"Content-Type: {content_type}\r\n".encode()
        out += b"\r\n" + value + b"\r\n"
    return out + b"--" + boundary + b"--\r\n"


def test_multipart_records_a_file_by_name_never_by_content():
    body = multipart([("language", None, None, b"ar"),
                      ("audio", "clip.wav", "audio/wav", b"RIFF\x00SECRETAUDIO")])
    summary = reqlog.summarize("multipart/form-data; boundary=BOUND", capture_of(body))

    assert summary["language"] == "ar"
    assert summary["audio"] == {"filename": "clip.wav", "content_type": "audio/wav", "bytes": 16}
    assert "SECRETAUDIO" not in json.dumps(summary)


def test_multipart_keeps_the_fields_around_a_file_too_large_to_capture():
    """The head/tail capture is what makes an upload's small fields survive the cap."""
    body = multipart([("audio", "big.wav", "audio/wav", b"\x00" * 200_000),
                      ("language", None, None, b"ar"),
                      ("punctuation", None, None, b"false")])
    summary = reqlog.summarize("multipart/form-data; boundary=BOUND",
                               capture_of(body, limit=2048))

    assert summary["language"] == "ar" and summary["punctuation"] == "false"
    # The part the window cut is named but never sized from the fragment we saw.
    assert summary["audio"]["filename"] == "big.wav" and summary["audio"]["bytes"] is None


def test_binary_body_is_reduced_to_its_size():
    summary = reqlog.summarize("audio/wav", capture_of(b"\x00" * 500))
    assert summary == "<500 bytes of audio/wav>"


def test_empty_body_summarises_to_nothing():
    assert reqlog.summarize("application/json", reqlog.BodyCapture()) is None


def test_an_oversized_summary_is_stored_as_valid_json():
    """A clipped payload must still round-trip, or the console renders a parse error."""
    text = reqlog._dump({"blob": "x" * (reqlog.MAX_SUMMARY_CHARS * 2)})
    assert len(text) < reqlog.MAX_SUMMARY_CHARS + 200
    assert isinstance(json.loads(text), str)


# ── Store ─────────────────────────────────────────────────────
def test_records_round_trip_through_the_store(store):
    log_id = store.record(entry(request={"text": "مرحباً"}, response={"filename": "a.wav"}))

    item = store.get(log_id)
    assert item["request"] == {"text": "مرحباً"} and item["response"] == {"filename": "a.wav"}
    assert item["ok"] is True and item["duration_ms"] == 12.0


def test_query_filters_and_paginates(store):
    store.record(entry(route="/api/prepare", status=200, ts=100.0))
    store.record(entry(route="/api/compose", status=502, ts=200.0, error="boom"))
    store.record(entry(route="/api/compose", status=200, ts=300.0))

    assert store.query()["total"] == 3
    assert [i["route"] for i in store.query()["items"]] == \
        ["/api/compose", "/api/compose", "/api/prepare"]          # newest first
    assert store.query(route="/api/compose")["total"] == 2
    assert store.query(status="error")["total"] == 1
    assert store.query(status="ok")["total"] == 2
    assert store.query(status="502")["total"] == 1
    assert store.query(since=250.0)["total"] == 1
    assert store.query(q="boom")["total"] == 1

    page = store.query(limit=1, offset=1)
    assert page["total"] == 3 and len(page["items"]) == 1


def test_search_reaches_into_the_recorded_bodies(store):
    store.record(entry(request={"text": "مرحباً بالعالم"}))
    store.record(entry(request={"text": "something else"}))
    assert store.query(q="بالعالم")["total"] == 1


def test_retention_caps_the_stored_rows(store):
    for i in range(reqlog.PRUNE_EVERY * 2):
        store.record(entry(ts=float(i)))
    assert store.query()["total"] == store.retention == 3
    # The rows kept are the newest ones.
    assert [i["ts"] for i in store.query()["items"]] == [99.0, 98.0, 97.0]


def test_clear_empties_the_log(store):
    store.record(entry())
    store.record(entry())
    assert store.clear() == 2
    assert store.query()["total"] == 0


def test_stats_summarise_the_window(store):
    store.retention = 0                       # keep every row for the maths below
    for ms, status in [(10, 200), (20, 200), (30, 500), (40, 200)]:
        store.record(entry(duration_ms=ms, status=status, route="/api/prepare",
                           ts=time.time()))

    stats = store.stats(hours=1, buckets=4)
    totals = stats["totals"]
    assert totals["count"] == 4 and totals["errors"] == 1 and totals["error_rate"] == 0.25
    assert totals["avg_ms"] == 25.0 and totals["max_ms"] == 40.0
    # Nearest-rank percentiles: with four samples the 50th lands on the third.
    assert totals["p50_ms"] == 30.0 and totals["p95_ms"] == 40.0

    endpoint = stats["endpoints"][0]
    assert endpoint["route"] == "/api/prepare" and endpoint["count"] == 4
    assert endpoint["errors"] == 1
    assert len(stats["timeline"]) == 4
    assert sum(b["count"] for b in stats["timeline"]) == 4


def test_stats_window_excludes_older_rows(store):
    store.retention = 0
    store.record(entry(ts=time.time()))
    store.record(entry(ts=time.time() - 10 * 3600))
    assert store.stats(hours=1)["totals"]["count"] == 1
    assert store.stats(hours=0)["totals"]["count"] == 2        # 0 = everything retained


# ── Middleware, through the gateway ───────────────────────────
def test_a_proxied_call_is_logged_with_its_inputs_outputs_and_timing(gateway):
    stub(gateway, "omnivoice_ft", "/synthesize", {"filename": "o.wav", "model": "omnivoice_ft"})

    gateway.post("/api/omnivoice_ft/synthesize", data={"text": "مرحباً", "dialect": "saudi"})

    item = rows(gateway)[0]
    assert item["method"] == "POST" and item["path"] == "/api/omnivoice_ft/synthesize"
    assert item["route"] == "/api/{model}/synthesize"    # rows group by the route template
    assert item["model"] == "omnivoice_ft"
    assert item["status"] == 200 and item["ok"] is True
    assert item["request"] == {"text": "مرحباً", "dialect": "saudi"}
    assert item["response"] == {"filename": "o.wav", "model": "omnivoice_ft"}
    assert item["duration_ms"] >= 0 and item["error"] is None
    assert item["req_bytes"] > 0 and item["resp_bytes"] > 0


def test_an_upload_is_logged_without_its_audio(gateway):
    stub(gateway, "transcribe", "/transcribe", {"text": "مرحباً"})
    audio = b"RIFF" + b"\x01" * 100_000

    gateway.post("/api/transcribe", files={"audio": ("clip.wav", audio, "audio/wav")},
                 data={"language": "ar", "punctuation": "false"})

    item = rows(gateway)[0]
    assert item["request"]["audio"]["filename"] == "clip.wav"
    assert item["request"]["language"] == "ar" and item["request"]["punctuation"] == "false"
    assert item["req_bytes"] > 100_000                  # the true size is still recorded
    assert len(json.dumps(item)) < 20_000               # …but the audio itself is not stored


def test_a_failing_call_records_the_status_and_the_reason(gateway):
    stub(gateway, "omnivoice_ft", "/synthesize", httpx.Response(500, text="CUDA OOM"))

    gateway.post("/api/omnivoice_ft/synthesize", data={"text": "hi"})

    item = rows(gateway)[0]
    assert item["status"] == 500 and item["ok"] is False
    assert "CUDA OOM" in item["error"]


def test_the_query_string_is_kept_on_the_logged_path(gateway):
    gateway.get("/api/omnivoice_ft/history?limit=5")
    assert rows(gateway)[0]["path"] == "/api/omnivoice_ft/history?limit=5"


def test_status_polling_and_the_console_itself_are_not_logged(gateway):
    stub(gateway, "omnivoice_ft", "/health", {"model_loaded": True})
    stub(gateway, "transcribe", "/health", {"model_loaded": True})

    gateway.get("/api/status")
    gateway.get("/api/omnivoice_ft/status")
    gateway.get("/api/logs/stats")
    gateway.get("/api/logs")

    assert rows(gateway) == []


def test_non_api_paths_are_not_logged(gateway):
    gateway.get("/index.html")
    gateway.get("/style.css")
    assert rows(gateway) == []


def test_the_console_endpoints_filter_the_same_way_the_store_does(gateway):
    stub(gateway, "omnivoice_ft", "/synthesize", {"filename": "o.wav"})
    stub(gateway, "transcribe", "/transcribe", httpx.Response(503, text="down"))
    gateway.post("/api/omnivoice_ft/synthesize", data={"text": "hi"})
    gateway.post("/api/transcribe", files={"audio": ("c.wav", b"x")})

    assert len(rows(gateway)) == 2
    assert len(rows(gateway, status="error")) == 1
    assert len(rows(gateway, route="/api/transcribe")) == 1
    assert len(rows(gateway, model="omnivoice_ft")) == 1
    assert len(rows(gateway, q="down")) == 1
    assert len(rows(gateway, hours=0.0001)) == 2          # both are seconds old


def test_a_single_entry_is_addressable_by_id(gateway):
    stub(gateway, "omnivoice_ft", "/synthesize", {"filename": "o.wav"})
    gateway.post("/api/omnivoice_ft/synthesize", data={"text": "hi"})

    log_id = rows(gateway)[0]["id"]
    assert gateway.get(f"/api/logs/{log_id}").json()["id"] == log_id
    assert gateway.get("/api/logs/999999").status_code == 404


def test_stats_and_clear_are_exposed(gateway):
    stub(gateway, "omnivoice_ft", "/synthesize", {"filename": "o.wav"})
    gateway.post("/api/omnivoice_ft/synthesize", data={"text": "hi"})

    stats = gateway.get("/api/logs/stats?hours=24").json()
    assert stats["totals"]["count"] == 1
    assert stats["endpoints"][0]["route"] == "/api/{model}/synthesize"

    assert gateway.get("/api/logs").json()["total"] == 1
    assert gateway.delete("/api/logs").json() == {"deleted": 1}
    assert gateway.get("/api/logs").json()["total"] == 0


def test_a_broken_log_never_breaks_the_request(gateway, monkeypatch):
    """Logging is bookkeeping — a failure in it must not cost the caller their response."""
    stub(gateway, "omnivoice_ft", "/synthesize", {"filename": "o.wav"})
    monkeypatch.setattr(gateway.server.request_log, "record",
                        lambda entry: (_ for _ in ()).throw(RuntimeError("disk full")))

    r = gateway.post("/api/omnivoice_ft/synthesize", data={"text": "hi"})
    assert r.status_code == 200 and r.json()["filename"] == "o.wav"


def test_logging_can_be_switched_off(tmp_path, monkeypatch):
    server = fresh_import("server", monkeypatch,
                          {"TTS_WORKDIR": tmp_path, "TTS_LOG_REQUESTS": "0"})
    with TestClient(server.app) as client:
        assert server.request_log is None
        assert client.get("/api/logs").status_code == 503
        assert not (tmp_path / "logs").exists()
