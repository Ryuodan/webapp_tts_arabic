"""Request log — every /api/* call the gateway serves, kept for the usage console.

Three pieces, deliberately self-contained:

* `BodyCapture` / `summarize` — turn the bytes crossing the wire into a small readable
  description. An uploaded wav is never stored: a file part is reduced to its name, type
  and size, and every text field is clipped.
* `RequestLog` — a SQLite store with a row cap, read back by the /api/logs endpoints.
* `RequestLogMiddleware` — pure ASGI, so it can observe the request body the proxy
  routes read in full *and* the response body, without consuming either.

Logging is best-effort throughout: a failure in here must never turn a working request
into a failed one.
"""
import asyncio
import json
import os
import pathlib
import re
import sqlite3
import threading
import time
from typing import Any, Optional
from urllib.parse import parse_qsl

# ── Limits ────────────────────────────────────────────────────
# Bodies are captured head *and* tail: a multipart upload puts its small text fields on
# either side of the file part, so keeping both ends preserves the interesting fields
# even when the audio in the middle runs far past the cap.
MAX_CAPTURE_BYTES  = int(os.getenv("TTS_LOG_MAX_BODY_BYTES", str(16 * 1024)))
MAX_FIELD_CHARS    = int(os.getenv("TTS_LOG_MAX_FIELD_CHARS", "1000"))
MAX_SUMMARY_CHARS  = int(os.getenv("TTS_LOG_MAX_SUMMARY_CHARS", "4000"))
RETENTION_ROWS     = int(os.getenv("TTS_LOG_RETENTION", "5000"))
PRUNE_EVERY        = 50            # inserts between retention sweeps

MAX_KEYS  = 40                     # per object, when clipping a decoded JSON body
MAX_ITEMS = 20                     # per array
MAX_DEPTH = 6


def _clip(text: Any, limit: int = MAX_FIELD_CHARS) -> str:
    text = str(text)
    return text if len(text) <= limit else f"{text[:limit]}… (+{len(text) - limit} chars)"


def _clip_json(value: Any, depth: int = 0) -> Any:
    """Shrink a decoded JSON body to something worth storing on every request."""
    if isinstance(value, str):
        return _clip(value)
    if depth >= MAX_DEPTH:
        return _clip(value)
    if isinstance(value, dict):
        out = {k: _clip_json(v, depth + 1) for k, v in list(value.items())[:MAX_KEYS]}
        if len(value) > MAX_KEYS:
            out["…"] = f"(+{len(value) - MAX_KEYS} more keys)"
        return out
    if isinstance(value, list):
        out = [_clip_json(v, depth + 1) for v in value[:MAX_ITEMS]]
        if len(value) > MAX_ITEMS:
            out.append(f"… (+{len(value) - MAX_ITEMS} more)")
        return out
    return value


# ── Body capture ──────────────────────────────────────────────
class BodyCapture:
    """Keeps the first and last `limit` bytes of a stream, plus its true length."""

    __slots__ = ("limit", "head", "tail", "total")

    def __init__(self, limit: int = MAX_CAPTURE_BYTES):
        self.limit = max(0, limit)
        self.head = b""
        self.tail = b""
        self.total = 0

    def add(self, chunk: bytes) -> None:
        if not chunk:
            return
        self.total += len(chunk)
        if len(self.head) < self.limit:
            self.head += chunk[: self.limit - len(self.head)]
        self.tail = (self.tail + chunk)[-self.limit:] if self.limit else b""

    @property
    def truncated(self) -> bool:
        return self.total > len(self.head)

    def chunks(self) -> tuple:
        return (self.head, self.tail) if self.truncated else (self.head,)


# ── Summarising ───────────────────────────────────────────────
_BOUNDARY  = re.compile(r'boundary="?([^";,]+)"?', re.I)
_PART_NAME = re.compile(rb'name="([^"]*)"')
_PART_FILE = re.compile(rb'filename="([^"]*)"')
_PART_TYPE = re.compile(rb"content-type:\s*([^\r\n]+)", re.I)


def _multipart_fields(chunk: bytes, boundary: bytes):
    """Yield (name, value, complete) for every part whose headers survived the capture.

    `complete` is False for the part the capture window cut in half — the merge upstream
    uses it to prefer a whole part seen in the tail over the fragment seen in the head.
    """
    for segment in chunk.split(b"--" + boundary):
        headers, sep, body = segment.partition(b"\r\n\r\n")
        if not sep:
            continue
        name = _PART_NAME.search(headers)
        if not name:                            # not a part header — binary that happened
            continue                            # to contain a blank line, most likely
        complete = body.endswith(b"\r\n")       # the CRLF that precedes the next boundary
        if complete:
            body = body[:-2]
        field = name.group(1).decode("utf-8", "replace")
        filename = _PART_FILE.search(headers)
        if filename:
            value = {"filename": filename.group(1).decode("utf-8", "replace")}
            part_type = _PART_TYPE.search(headers)
            if part_type:
                value["content_type"] = part_type.group(1).decode("utf-8", "replace").strip()
            # A cut part's byte count would be the capture window's, not the file's; the
            # row's req_bytes carries the real size instead.
            value["bytes"] = len(body) if complete else None
            yield field, value, complete
        else:
            text = body.decode("utf-8", "replace")
            yield field, _clip(text) if complete else _clip(text) + "…", complete


def _multipart_summary(content_type: str, capture: BodyCapture) -> Any:
    match = _BOUNDARY.search(content_type)
    if not match:
        return f"<{capture.total} bytes of multipart/form-data>"
    boundary = match.group(1).encode()
    fields: dict = {}
    for chunk in capture.chunks():
        for name, value, complete in _multipart_fields(chunk, boundary):
            if complete or name not in fields:   # a whole part always beats a fragment
                fields[name] = value
    return fields


def summarize(content_type: str, capture: BodyCapture) -> Any:
    """Describe a captured body as something JSON-serialisable and small."""
    if capture.total == 0:
        return None
    ct = (content_type or "").lower()
    if "multipart/form-data" in ct:
        # The raw header, not the lower-cased copy: boundaries are case-sensitive.
        return _multipart_summary(content_type, capture)

    text = capture.head.decode("utf-8", "replace")
    if "json" in ct:
        try:
            return _clip_json(json.loads(capture.head.decode("utf-8")))
        except Exception:
            return _clip(text)                  # truncated or malformed — show the head
    if "x-www-form-urlencoded" in ct:
        return {k: _clip(v) for k, v in parse_qsl(text)}
    if not ct or ct.startswith("text/"):
        return _clip(text)
    return f"<{capture.total} bytes of {ct.split(';')[0].strip() or 'unknown type'}>"


def _dump(value: Any) -> Optional[str]:
    """Serialise a summary, keeping the stored text valid JSON even when it is too long."""
    if value is None:
        return None
    text = json.dumps(value, ensure_ascii=False)
    if len(text) > MAX_SUMMARY_CHARS:
        text = json.dumps(_clip(text, MAX_SUMMARY_CHARS), ensure_ascii=False)
    return text


def _load(text: Optional[str]) -> Any:
    if text is None:
        return None
    try:
        return json.loads(text)
    except Exception:
        return text


# ── Store ─────────────────────────────────────────────────────
_SCHEMA = """
CREATE TABLE IF NOT EXISTS requests (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          REAL    NOT NULL,
    method      TEXT    NOT NULL,
    path        TEXT    NOT NULL,
    route       TEXT    NOT NULL,
    model       TEXT,
    status      INTEGER NOT NULL,
    duration_ms REAL    NOT NULL,
    req_bytes   INTEGER NOT NULL DEFAULT 0,
    resp_bytes  INTEGER NOT NULL DEFAULT 0,
    client      TEXT,
    user_agent  TEXT,
    request     TEXT,
    response    TEXT,
    error       TEXT
);
CREATE INDEX IF NOT EXISTS requests_ts    ON requests(ts);
CREATE INDEX IF NOT EXISTS requests_route ON requests(route);
"""

_COLUMNS = ("ts", "method", "path", "route", "model", "status", "duration_ms",
            "req_bytes", "resp_bytes", "client", "user_agent", "request", "response", "error")


class RequestLog:
    """SQLite-backed request history with a hard row cap.

    One connection guarded by a lock: only the gateway writes, writes are sub-millisecond,
    and a lock is far less machinery than a pool for a table this small.
    """

    def __init__(self, path, retention: int = RETENTION_ROWS):
        self.path = pathlib.Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.retention = max(0, retention)
        self._lock = threading.Lock()
        self._since_prune = 0
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    # ── writing ───────────────────────────────────────────────
    def record(self, entry: dict) -> int:
        """Insert one request. `request`/`response` may be any JSON-able summary."""
        entry = {**entry, "request": _dump(entry.get("request")),
                 "response": _dump(entry.get("response"))}
        values = [entry.get(c) for c in _COLUMNS]
        placeholders = ", ".join("?" * len(_COLUMNS))
        with self._lock:
            cur = self._conn.execute(
                f"INSERT INTO requests ({', '.join(_COLUMNS)}) VALUES ({placeholders})", values)
            self._since_prune += 1
            if self.retention and self._since_prune >= PRUNE_EVERY:
                self._prune()
            self._conn.commit()
            return cur.lastrowid

    def _prune(self) -> None:
        """Drop everything past the row cap. Called under the lock."""
        self._conn.execute(
            "DELETE FROM requests WHERE id NOT IN "
            "(SELECT id FROM requests ORDER BY id DESC LIMIT ?)", (self.retention,))
        self._since_prune = 0

    def prune(self) -> None:
        with self._lock:
            self._prune()
            self._conn.commit()

    def clear(self) -> int:
        with self._lock:
            deleted = self._conn.execute("DELETE FROM requests").rowcount
            self._conn.commit()
            return max(deleted, 0)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ── reading ───────────────────────────────────────────────
    @staticmethod
    def _row(row: sqlite3.Row) -> dict:
        item = dict(row)
        item["request"] = _load(item.get("request"))
        item["response"] = _load(item.get("response"))
        item["ok"] = item["status"] < 400
        return item

    def _filters(self, route=None, method=None, status=None, since=None, model=None, q=None):
        where, params = [], []
        if route:
            where.append("route = ?"); params.append(route)
        if method:
            where.append("method = ?"); params.append(method.upper())
        if model:
            where.append("model = ?"); params.append(model)
        if since:
            where.append("ts >= ?"); params.append(float(since))
        if status == "ok":
            where.append("status < 400")
        elif status == "error":
            where.append("status >= 400")
        elif status:
            where.append("status = ?"); params.append(int(status))
        if q:
            like = f"%{q}%"
            where.append("(path LIKE ? OR request LIKE ? OR response LIKE ? OR error LIKE ?)")
            params += [like] * 4
        return (" WHERE " + " AND ".join(where) if where else ""), params

    def query(self, *, limit: int = 50, offset: int = 0, **filters) -> dict:
        clause, params = self._filters(**filters)
        with self._lock:
            total = self._conn.execute(
                f"SELECT COUNT(*) FROM requests{clause}", params).fetchone()[0]
            rows = self._conn.execute(
                f"SELECT * FROM requests{clause} ORDER BY id DESC LIMIT ? OFFSET ?",
                params + [int(limit), int(offset)]).fetchall()
        return {"items": [self._row(r) for r in rows], "total": total,
                "limit": int(limit), "offset": int(offset)}

    def get(self, log_id: int) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute("SELECT * FROM requests WHERE id = ?", (log_id,)).fetchone()
        return self._row(row) if row else None

    def stats(self, hours: float = 24.0, buckets: int = 24) -> dict:
        """Totals, per-endpoint breakdown and a timeline for the requested window.

        Aggregated in Python off one SELECT rather than in SQL: percentiles have no SQLite
        equivalent, and the row cap bounds how much this can ever pull.
        """
        now = time.time()
        since = now - hours * 3600 if hours and hours > 0 else None
        clause, params = self._filters(since=since)
        with self._lock:
            rows = self._conn.execute(
                f"SELECT ts, method, route, model, status, duration_ms, req_bytes, resp_bytes "
                f"FROM requests{clause} ORDER BY ts", params).fetchall()
            oldest = self._conn.execute("SELECT MIN(ts) FROM requests").fetchone()[0]
            stored = self._conn.execute("SELECT COUNT(*) FROM requests").fetchone()[0]

        durations = sorted(r["duration_ms"] for r in rows)
        errors = [r for r in rows if r["status"] >= 400]
        window_start = since if since is not None else (oldest if oldest is not None else now)

        by_route: dict = {}
        for r in rows:
            key = (r["method"], r["route"])
            slot = by_route.setdefault(key, {"method": r["method"], "route": r["route"],
                                             "count": 0, "errors": 0, "durations": [],
                                             "last_ts": 0.0})
            slot["count"] += 1
            slot["errors"] += 1 if r["status"] >= 400 else 0
            slot["durations"].append(r["duration_ms"])
            slot["last_ts"] = max(slot["last_ts"], r["ts"])

        endpoints = []
        for slot in by_route.values():
            times = sorted(slot.pop("durations"))
            slot["avg_ms"] = round(sum(times) / len(times), 1)
            slot["p95_ms"] = round(_percentile(times, 0.95), 1)
            slot["max_ms"] = round(times[-1], 1)
            endpoints.append(slot)
        endpoints.sort(key=lambda e: e["count"], reverse=True)

        span = max(now - window_start, 1.0)
        width = span / max(buckets, 1)
        timeline = [{"start": window_start + i * width, "width_s": width, "count": 0, "errors": 0}
                    for i in range(max(buckets, 1))]
        for r in rows:
            index = min(int((r["ts"] - window_start) / width), len(timeline) - 1)
            bucket = timeline[max(index, 0)]
            bucket["count"] += 1
            bucket["errors"] += 1 if r["status"] >= 400 else 0

        return {
            "window_hours": hours,
            "since": window_start,
            "now": now,
            "stored_rows": stored,
            "retention_rows": self.retention,
            "totals": {
                "count": len(rows),
                "errors": len(errors),
                "error_rate": round(len(errors) / len(rows), 4) if rows else 0.0,
                "avg_ms": round(sum(durations) / len(durations), 1) if durations else 0.0,
                "p50_ms": round(_percentile(durations, 0.50), 1),
                "p95_ms": round(_percentile(durations, 0.95), 1),
                "max_ms": round(durations[-1], 1) if durations else 0.0,
                "req_bytes": sum(r["req_bytes"] for r in rows),
                "resp_bytes": sum(r["resp_bytes"] for r in rows),
            },
            "endpoints": endpoints,
            "timeline": timeline,
        }


def _percentile(sorted_values, fraction: float) -> float:
    if not sorted_values:
        return 0.0
    index = min(int(round(fraction * (len(sorted_values) - 1))), len(sorted_values) - 1)
    return sorted_values[index]


# ── Middleware ────────────────────────────────────────────────
def _error_text(response_summary: Any) -> Optional[str]:
    """The message worth showing for a failed request — FastAPI puts it under `detail`."""
    if response_summary is None:
        return None
    if isinstance(response_summary, dict):
        return _clip(response_summary.get("detail", response_summary))
    return _clip(response_summary)


def _header(headers, name: bytes) -> str:
    for key, value in headers or ():
        if key.lower() == name:
            return value.decode("latin-1")
    return ""


class RequestLogMiddleware:
    """Records every request `should_log` accepts into a `RequestLog`.

    Pure ASGI rather than a BaseHTTPMiddleware hook: the request body has to be observed
    while the route still gets to read it, and the response body while it still reaches
    the client — wrapping `receive`/`send` is precisely that, and it also sees exceptions
    that escape the app.
    """

    def __init__(self, app, store: Optional[RequestLog] = None, routes=(), should_log=None):
        self.app = app
        self.store = store
        self.routes = routes          # live list; used to name the matched route template
        self.should_log = should_log or (lambda scope: scope["path"].startswith("/api/"))

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or self.store is None or not self.should_log(scope):
            return await self.app(scope, receive, send)

        request = BodyCapture()
        response = BodyCapture()
        state = {"status": 500, "content_type": ""}

        async def receive_logged():
            message = await receive()
            if message["type"] == "http.request":
                request.add(message.get("body", b""))
            return message

        async def send_logged(message):
            if message["type"] == "http.response.start":
                state["status"] = message["status"]
                state["content_type"] = _header(message.get("headers"), b"content-type")
            elif message["type"] == "http.response.body":
                response.add(message.get("body", b""))
            await send(message)

        started = time.perf_counter()
        error = None
        try:
            await self.app(scope, receive_logged, send_logged)
        except Exception as exc:                      # logged as a 500, then re-raised
            error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            await self._record(scope, request, response, state,
                               (time.perf_counter() - started) * 1000, error)

    def _route_template(self, scope) -> str:
        """The matched route's path pattern, so /api/x/synthesize rows group together."""
        endpoint = scope.get("endpoint")
        if endpoint is not None:
            for route in self.routes:
                if getattr(route, "endpoint", None) is endpoint and getattr(route, "path", ""):
                    return route.path
        return scope.get("path", "")

    async def _record(self, scope, request, response, state, duration_ms, error) -> None:
        try:
            entry = self._entry(scope, request, response, state, duration_ms, error)
            await asyncio.to_thread(self.store.record, entry)
        except Exception:
            pass                                      # never fail a request over its log row

    def _entry(self, scope, request, response, state, duration_ms, error) -> dict:
        headers = scope.get("headers") or ()
        status = state["status"]
        req_summary = summarize(_header(headers, b"content-type"), request)
        resp_summary = summarize(state["content_type"], response)

        if error is None and status >= 400:
            error = _error_text(resp_summary)

        client = _header(headers, b"x-forwarded-for").split(",")[0].strip()
        if not client:
            client = (scope.get("client") or ("", 0))[0] or ""

        query = scope.get("query_string", b"").decode("latin-1")
        return {
            "ts": time.time(),
            "method": scope.get("method", ""),
            "path": scope.get("path", "") + (f"?{query}" if query else ""),
            "route": self._route_template(scope),
            "model": (scope.get("path_params") or {}).get("model"),
            "status": status,
            "duration_ms": round(duration_ms, 2),
            "req_bytes": request.total or int(_header(headers, b"content-length") or 0),
            "resp_bytes": response.total,
            "client": client,
            "user_agent": _clip(_header(headers, b"user-agent"), 200),
            "request": req_summary,
            "response": resp_summary,
            "error": error,
        }
