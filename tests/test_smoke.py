"""End-to-end smoke test over real processes and real sockets.

Everything else in the suite mocks a boundary. This one starts an actual uvicorn worker
and the actual gateway, then drives them over HTTP — so it catches what in-process tests
cannot: a worker that fails to import, a port that does not match start.sh, an ASGI-level
mistake in the proxy, or a static file the server refuses to hand out.

The ASR worker itself is stood up from a stub script rather than the real one, because the
real one needs a CUDA GPU and a 2.4 GB checkpoint. Its contract is covered by
test_transcribe_worker.py; what is under test here is the wiring around it.
"""
import pathlib
import socket
import subprocess
import sys
import time

import httpx
import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent

STUB_WORKER = '''
import sys, uvicorn
from fastapi import FastAPI, File, Form, UploadFile

app = FastAPI()

@app.get("/health")
async def health():
    return {"model": "stub", "status": "ok", "ready": True, "model_loaded": True}

@app.post("/load")
async def load():
    return {"status": "loaded"}

@app.post("/transcribe")
async def transcribe(audio: UploadFile = File(...), language: str = Form("ar"),
                     punctuation: bool = Form(True)):
    data = await audio.read()
    return {"filename": "stub.wav", "model": "transcribe", "text": "مرحباً",
            "language": language, "punctuation": punctuation, "bytes": len(data)}

uvicorn.run(app, host="127.0.0.1", port=int(sys.argv[1]), log_level="error")
'''


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def port_taken(port):
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def wait_for(url, deadline=25.0):
    end = time.time() + deadline
    while time.time() < end:
        try:
            httpx.get(url, timeout=1.0)
            return True
        except httpx.HTTPError:
            time.sleep(0.2)
    return False


@pytest.fixture(scope="module")
def stack(tmp_path_factory):
    """A real gateway on a free port, with a real ASR worker process behind it on 8084."""
    # server.py pins the worker ports, so anything else holding one makes these
    # assertions meaningless — skip rather than report a bogus pass or failure.
    if port_taken(8082):
        pytest.skip("port 8082 is held by another process; cannot assert worker state")
    if port_taken(8084):
        pytest.skip("port 8084 is held by another process; cannot start the stub worker")

    tmp = tmp_path_factory.mktemp("smoke")
    stub = tmp / "stub_worker.py"
    stub.write_text(STUB_WORKER, encoding="utf-8")

    port = free_port()
    procs = [
        subprocess.Popen([sys.executable, str(stub), "8084"],
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT),
        subprocess.Popen([sys.executable, str(ROOT / "server.py"), "--port", str(port)],
                         env={"PATH": "/usr/bin:/bin", "TTS_WORKDIR": str(tmp),
                              "PYTHONPATH": str(ROOT)},
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT),
    ]
    base = f"http://127.0.0.1:{port}"
    try:
        if not (wait_for(f"{base}/api/status") and wait_for("http://127.0.0.1:8084/health")):
            logs = b"\n".join(p.stdout.read() if p.poll() is not None else b"" for p in procs)
            pytest.fail(f"stack did not come up:\n{logs.decode(errors='replace')}")
        yield base
    finally:
        for p in procs:
            p.terminate()
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()


@pytest.mark.slow
def test_gateway_reports_the_asr_worker_over_a_real_socket(stack):
    body = httpx.get(f"{stack}/api/status", timeout=5).json()
    assert body["transcribe"]["model_loaded"] is True
    assert body["omnivoice"]["status"] == "offline"      # not started here
    assert body["_memory_policy"]["single_model_mode"] is True


@pytest.mark.slow
def test_transcription_round_trip(stack, wav_file):
    r = httpx.post(f"{stack}/api/transcribe", timeout=30,
                   files={"audio": ("clip.wav", wav_file.read_bytes(), "audio/wav")},
                   data={"language": "ar", "punctuation": "false"})
    assert r.status_code == 200
    body = r.json()
    assert body["text"] == "مرحباً"
    assert body["punctuation"] is False
    assert body["bytes"] == wav_file.stat().st_size     # nothing lost in the proxy


@pytest.mark.slow
def test_large_upload_survives_the_proxy(stack):
    blob = b"\x7f" * (5 * 1024 * 1024)
    r = httpx.post(f"{stack}/api/transcribe", timeout=60,
                   files={"audio": ("big.wav", blob, "audio/wav")})
    assert r.status_code == 200 and r.json()["bytes"] == len(blob)


@pytest.mark.slow
def test_warm_up_and_per_model_status(stack):
    assert httpx.post(f"{stack}/api/transcribe/load", timeout=30).json()["status"] == "loaded"
    assert httpx.get(f"{stack}/api/transcribe/status", timeout=5).json()["ready"] is True


@pytest.mark.slow
@pytest.mark.parametrize("path", ["/", "/api.html", "/logs.html", "/app.js", "/api.js",
                                  "/api.css", "/logs.js", "/logs.css"])
def test_frontend_is_reachable(stack, path):
    r = httpx.get(f"{stack}{path}", timeout=5)
    assert r.status_code == 200 and r.content


@pytest.mark.slow
@pytest.mark.parametrize("path", ["/api", "/api/"])
def test_api_docs_shortcut_redirects_to_the_page(stack, path):
    """Relative Location only — nginx strips /arabic-tts/, so an absolute one escapes it."""
    r = httpx.get(f"{stack}{path}", timeout=5, follow_redirects=False)
    assert r.status_code == 302
    assert not r.headers["location"].startswith("/")
    assert httpx.get(f"{stack}{path}", timeout=5).status_code == 200


@pytest.mark.slow
def test_offline_workers_degrade_instead_of_erroring(stack):
    r = httpx.post(f"{stack}/api/omnivoice/synthesize", data={"text": "مرحباً"}, timeout=10)
    assert r.status_code == 503 and "start.sh" in r.json()["detail"]


@pytest.mark.slow
def test_worker_ports_match_the_start_script(stack):
    """A port renamed in one place and not the other is a silent outage."""
    import server

    start = (ROOT / "start.sh").read_text(encoding="utf-8")
    stop = (ROOT / "stop.sh").read_text(encoding="utf-8")
    for name, url in server.WORKER_URLS.items():
        port = httpx.URL(url).port
        assert f"{port}" in start, f"{name} port {port} missing from start.sh"
        assert f"{port}" in stop, f"{name} port {port} missing from stop.sh"


@pytest.mark.slow
def test_every_worker_script_is_launched_and_stopped():
    start = (ROOT / "start.sh").read_text(encoding="utf-8")
    stop = (ROOT / "stop.sh").read_text(encoding="utf-8")
    for script in (ROOT / "workers").glob("*_server.py"):
        assert script.name in stop, f"{script.name} is never stopped"
        if script.name not in ("fish_server.py", "voxcpm2_server.py"):   # retired workers
            assert script.name in start, f"{script.name} is never started"
