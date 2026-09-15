@example py-api-0001
@meta category=api_usage language=python difficulty=advanced tags=http,retries,stdlib,timeouts

@user
Our nightly sync calls a vendor REST API over HTTP. It fails in three ways: transient 503s that a manual retry fixes, 429s with a `Retry-After` header, and occasional hangs where a request never returns. Right now the script retries everything three times with `time.sleep(1)` and it sometimes retries a 400 for an hour. We cannot add dependencies, so this has to be stdlib only. What is the correct retry policy and how do I test it without hitting the network?
@@end

@assistant
Three policies, not one: **which errors are retryable**, **how long to wait**, and **how long to keep trying**. Getting them tangled is why the current script retries a 400.

Rules that decide correctness:

- **Retry only what can succeed on retry.** Connection errors and timeouts; 429, 500, 502, 503, 504. Everything else — 400, 401, 403, 404, 409 — fails fast, and that must include the *body* being useless (a 200 with malformed JSON is not retryable either, or you will hammer the vendor).
- **Honour `Retry-After` when present** (seconds or an HTTP-date), and use it as a *floor*: jittered exponential backoff shorter than the server's ask makes things worse. Parse it as "absent" rather than "falsy" — `Retry-After: 0` is a legitimate value, and `delay = retry_after(...) or jitter` silently ignores it.
- **Full jitter, not fixed sleep.** `sleep(random.uniform(0, min(cap, base * 2**attempt)))` decorrelates clients so a fleet does not retry in lockstep and re-create the outage.
- **Bound the wall clock, not just the attempt count.** Ten attempts with exponential backoff can outlive the sync window; a deadline turns "eventually" into an error you can alert on.
- **Send an idempotency key for non-idempotent methods.** Retrying a POST without one can double-charge a customer; `Idempotency-Key` lets the vendor dedupe.
- **Read or close the error response.** `urllib` leaves the body attached to the `HTTPError`; ignoring it leaks the connection back into the pool with unread bytes, which resurfaces as `ConnectionResetError` on an unrelated later request.

```python
import json
import random
import time
import urllib.error
import urllib.parse
import urllib.request

RETRY_STATUS = {429, 500, 502, 503, 504}


class RetryableError(Exception):
    """The request may succeed if repeated."""


class PermanentError(Exception):
    """The request will never succeed without changing the input."""


def _retry_after_seconds(http_error, now):
    raw = http_error.headers.get("Retry-After")
    if not raw:
        return None
    raw = raw.strip()
    if raw.isdigit():
        return float(raw)
    # HTTP-date form; parsing it is fiddly, so fail soft on a bad value.
    try:
        from email.utils import parsedate_to_datetime

        delta = parsedate_to_datetime(raw).timestamp() - now
        return max(delta, 0.0)
    except (TypeError, ValueError):
        return None


def _read_body(http_error):
    try:
        return http_error.read().decode("utf-8", "replace")
    except Exception:                        # a broken body must not mask the status
        return ""


def get_json(url, *, attempts=5, deadline_s=30.0, base_s=0.2, cap_s=5.0,
             timeout_s=5.0, sleep=time.sleep, monotonic=time.monotonic, rng=random):
    """GET url and decode JSON, retrying only retryable failures."""
    started = monotonic()
    last_error = None
    for attempt in range(attempts):
        if monotonic() - started > deadline_s:
            raise RetryableError(f"deadline {deadline_s}s exceeded after {attempt} attempts") from last_error
        request = urllib.request.Request(url, headers={"Accept": "application/json",
                                                       "User-Agent": "sync/1.0"})
        try:
            with urllib.request.urlopen(request, timeout=timeout_s) as response:
                payload = json.loads(response.read().decode("utf-8"))
            return payload
        except urllib.error.HTTPError as exc:
            body = _read_body(exc)
            if exc.code not in RETRY_STATUS:
                raise PermanentError(f"HTTP {exc.code} for {url}: {body[:200]}") from exc
            last_error = RetryableError(f"HTTP {exc.code}: {body[:200]}")
            delay = _retry_after_seconds(exc, monotonic())
            if delay is None:                # NOT `or`: Retry-After: 0 is valid
                delay = rng.uniform(0, min(cap_s, base_s * 2 ** attempt))
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            last_error = RetryableError(f"network error: {exc!r}")
            delay = rng.uniform(0, min(cap_s, base_s * 2 ** attempt))
        except json.JSONDecodeError as exc:
            raise PermanentError(f"malformed JSON from {url}: {exc}") from exc
        sleep(delay)
    raise RetryableError(f"{attempts} attempts exhausted for {url}") from last_error
```

`urllib.error.URLError` is a `(OSError)` subclass and `TimeoutError`/`ConnectionError` are `OSError` subclasses too, so the ordering of the `except` clauses matters: `HTTPError` first (it is also a `URLError`), then the transport errors, then body-decoding errors which must *not* be retried.

Testing this without a network is the part most codebases skip. Use a real socket on port 0 with a scripted handler — it exercises `urllib`, the headers and the socket layer — and inject `sleep`/`monotonic` so the test finishes in milliseconds and the asserted delays are exact.
@@end

@verify kind=executable language=python
@code
import http.server
import json
import random
import threading
import time
import urllib.error
import urllib.request

RETRY_STATUS = {429, 500, 502, 503, 504}


class RetryableError(Exception):
    pass


class PermanentError(Exception):
    pass


def _retry_after_seconds(http_error, now):
    raw = http_error.headers.get("Retry-After")
    if not raw:
        return None
    raw = raw.strip()
    if raw.isdigit():
        return float(raw)
    try:
        from email.utils import parsedate_to_datetime

        delta = parsedate_to_datetime(raw).timestamp() - now
        return max(delta, 0.0)
    except (TypeError, ValueError):
        return None


def _read_body(http_error):
    try:
        return http_error.read().decode("utf-8", "replace")
    except Exception:
        return ""


def get_json(url, *, attempts=5, deadline_s=30.0, base_s=0.2, cap_s=5.0,
             timeout_s=5.0, sleep=time.sleep, monotonic=time.monotonic, rng=random):
    started = monotonic()
    last_error = None
    for attempt in range(attempts):
        if monotonic() - started > deadline_s:
            raise RetryableError(f"deadline {deadline_s}s exceeded after {attempt} attempts") from last_error
        request = urllib.request.Request(url, headers={"Accept": "application/json",
                                                       "User-Agent": "sync/1.0"})
        try:
            with urllib.request.urlopen(request, timeout=timeout_s) as response:
                payload = json.loads(response.read().decode("utf-8"))
            return payload
        except urllib.error.HTTPError as exc:
            body = _read_body(exc)
            if exc.code not in RETRY_STATUS:
                raise PermanentError(f"HTTP {exc.code} for {url}: {body[:200]}") from exc
            last_error = RetryableError(f"HTTP {exc.code}: {body[:200]}")
            delay = _retry_after_seconds(exc, monotonic())
            if delay is None:                # NOT `or`: Retry-After: 0 is a valid value
                delay = rng.uniform(0, min(cap_s, base_s * 2 ** attempt))
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            last_error = RetryableError(f"network error: {exc!r}")
            delay = rng.uniform(0, min(cap_s, base_s * 2 ** attempt))
        except json.JSONDecodeError as exc:
            raise PermanentError(f"malformed JSON from {url}: {exc}") from exc
        sleep(delay)
    raise RetryableError(f"{attempts} attempts exhausted for {url}") from last_error


class ScriptedHandler(http.server.BaseHTTPRequestHandler):
    """Serves a plan: a list of (status, headers, body) per consecutive request."""

    plan = []
    seen_paths = []
    protocol_version = "HTTP/1.1"

    def do_GET(self):                       # noqa: N802 (http.server API)
        index = len(self.seen_paths)
        self.seen_paths.append(self.path)
        status, headers, body = self.plan[min(index, len(self.plan) - 1)]
        payload = body.encode()
        self.send_response(status)
        for key, value in headers.items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        if payload:
            self.wfile.write(payload)

    def log_message(self, *args):           # keep the test output clean
        pass


class Server:
    def __init__(self, plan):
        handler = type("Handler", (ScriptedHandler,), {"plan": list(plan), "seen_paths": []})
        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        # poll_interval keeps server.stop() fast: the default is 0.5s per server.
        server = self.httpd
        self.thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.02),
                                       daemon=True)
        self.thread.start()
        self.handler = handler
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/v1/items"

    @property
    def requests(self):
        return len(self.handler.seen_paths)

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)


class FakeSleeper:
    """Records sleeps instead of performing them, and moves the clock."""

    def __init__(self):
        self.delays = []
        self.clock = 1000.0

    def sleep(self, seconds):
        self.delays.append(seconds)
        self.clock += seconds

    def monotonic(self):
        return self.clock


# 1. Transient 503s are retried and the successful payload is returned.
server = Server([
    (503, {"Content-Type": "application/json"}, '{"error":"unavailable"}'),
    (503, {"Content-Type": "application/json"}, '{"error":"unavailable"}'),
    (200, {"Content-Type": "application/json"}, '{"items":[1,2,3]}'),
])
try:
    sleeper = FakeSleeper()
    payload = get_json(server.url, sleep=sleeper.sleep, monotonic=sleeper.monotonic,
                       rng=random.Random(1))
    assert payload == {"items": [1, 2, 3]}, payload
    assert server.requests == 3, server.requests
    assert len(sleeper.delays) == 2, sleeper.delays
    assert all(0 <= d <= 5.0 for d in sleeper.delays), sleeper.delays
finally:
    server.stop()

# 2. Retry-After is honoured as a floor, including the HTTP-date form.
server = Server([
    (429, {"Retry-After": "2", "Content-Type": "application/json"}, '{"error":"slow down"}'),
    (200, {"Content-Type": "application/json"}, '{"ok":true}'),
])
try:
    sleeper = FakeSleeper()
    assert get_json(server.url, sleep=sleeper.sleep, monotonic=sleeper.monotonic,
                    rng=random.Random(2)) == {"ok": True}
    assert sleeper.delays == [2.0], sleeper.delays        # header overrides the jitter
finally:
    server.stop()

server = Server([
    (503, {"Retry-After": "Wed, 21 Oct 2015 07:30:00 GMT", "Content-Type": "application/json"},
     '{"error":"later"}'),
    (200, {"Content-Type": "application/json"}, '{"ok":true}'),
])
try:
    sleeper = FakeSleeper()
    sleeper.clock = 1445409000.0                          # one hour before the header date
    assert get_json(server.url, deadline_s=7200.0, sleep=sleeper.sleep,
                    monotonic=sleeper.monotonic, rng=random.Random(3)) == {"ok": True}
    assert sleeper.delays and sleeper.delays[0] > 1000, sleeper.delays
finally:
    server.stop()

# 3. A 400 is permanent: one request, no sleep, and the body is in the message.
server = Server([(400, {"Content-Type": "application/json"}, '{"error":"bad field: sku"}')])
try:
    sleeper = FakeSleeper()
    try:
        get_json(server.url, sleep=sleeper.sleep, monotonic=sleeper.monotonic)
        raise AssertionError("400 must not be retried")
    except PermanentError as exc:
        assert "400" in str(exc) and "bad field: sku" in str(exc), str(exc)
    assert server.requests == 1, server.requests
    assert sleeper.delays == [], sleeper.delays
finally:
    server.stop()

# 4. Exhausted attempts raise RetryableError; the deadline cuts it short earlier.
server = Server([(500, {"Content-Type": "application/json"}, '{"error":"boom"}')])
try:
    sleeper = FakeSleeper()
    try:
        get_json(server.url, attempts=3, sleep=sleeper.sleep, monotonic=sleeper.monotonic,
                 rng=random.Random(4))
        raise AssertionError("expected RetryableError")
    except RetryableError as exc:
        assert "3 attempts exhausted" in str(exc), str(exc)
    assert server.requests == 3, server.requests
    assert len(sleeper.delays) == 3, sleeper.delays
finally:
    server.stop()

server = Server([(500, {"Content-Type": "application/json"}, '{"error":"boom"}')])
try:
    sleeper = FakeSleeper()
    try:
        get_json(server.url, attempts=50, deadline_s=1.0, sleep=sleeper.sleep,
                 monotonic=sleeper.monotonic, rng=random.Random(5))
        raise AssertionError("expected the deadline to fire")
    except RetryableError as exc:
        assert "deadline" in str(exc), str(exc)
    assert server.requests < 50, server.requests
finally:
    server.stop()

# 5. Malformed JSON on a 200 is permanent, not retryable.
server = Server([(200, {"Content-Type": "application/json"}, '{"items": [1, 2')])
try:
    sleeper = FakeSleeper()
    try:
        get_json(server.url, sleep=sleeper.sleep, monotonic=sleeper.monotonic)
        raise AssertionError("malformed JSON must not be retried")
    except PermanentError as exc:
        assert "malformed JSON" in str(exc), str(exc)
    assert server.requests == 1, server.requests
finally:
    server.stop()

# 6. A closed port is retryable (connection error).
server = Server([(200, {"Content-Type": "application/json"}, '{"ok":true}')])
url = server.url
server.stop()
try:
    get_json(url, attempts=2, timeout_s=1.0, base_s=0.01, cap_s=0.02, rng=random.Random(6))
    raise AssertionError("expected a retryable network error")
except RetryableError as exc:
    assert "attempts exhausted" in str(exc), str(exc)

# 7. End-to-end with the real clock. `Retry-After: 0` is a valid floor meaning
#    "retry now": the jittered backoff must NOT be added on top. MidpointRandom
#    makes the jitter (0.1s here) visible if it is wrongly applied.
class MidpointRandom:
    """Deterministic 'jitter': the midpoint of the interval."""

    def uniform(self, low, high):
        return (low + high) / 2


server = Server([
    (503, {"Retry-After": "0", "Content-Type": "application/json"}, '{"error":"retry"}'),
    (200, {"Content-Type": "application/json"}, '{"ok":true}'),
])
try:
    started = time.monotonic()
    assert get_json(server.url, base_s=0.2, cap_s=0.2, rng=MidpointRandom()) == {"ok": True}
    elapsed = time.monotonic() - started
    assert elapsed < 0.05, f"Retry-After: 0 must not add jitter, elapsed={elapsed}"
    assert server.requests == 2, server.requests
finally:
    server.stop()

# 7b. No Retry-After header: the jittered backoff is a real sleep.
server = Server([
    (503, {"Content-Type": "application/json"}, '{"error":"retry"}'),
    (200, {"Content-Type": "application/json"}, '{"ok":true}'),
])
try:
    started = time.monotonic()
    assert get_json(server.url, base_s=0.2, cap_s=0.2, rng=MidpointRandom()) == {"ok": True}
    elapsed = time.monotonic() - started
    assert 0.05 < elapsed < 1.0, f"expected a ~0.1s real sleep, elapsed={elapsed}"
    assert server.requests == 2, server.requests
finally:
    server.stop()
print("PASS")
@@end

@expect_output
PASS
@@end

@notes
Every case talks to a real HTTP server bound to 127.0.0.1:0 (threading
http.server, scripted response plan, one socket per request), so urllib, header
parsing and the transport layer are all exercised; sleeps and the clock are
injected so the deterministic cases run instantly and assert exact delays.
Pinned: a payload is returned after two 503s with bounded jittered delays,
Retry-After is honoured both as seconds and as an HTTP-date (used as a floor, not
as an extra sleep, with the deadline raised so the hour-long wait is simulated),
a 400 produces exactly one request with no sleep and the response body in the
message, exhausted attempts raise RetryableError with the attempt count, the
wall-clock deadline cuts a 50-attempt budget short, malformed JSON on a 200 is
permanent rather than retried, a closed port is retryable, and two end-to-end
cases use the real clock and a midpoint "jitter" to prove the retry loop works
outside the fake-sleeper harness: `Retry-After: 0` adds no delay (and is not
dropped as a falsy value), while a missing header produces a measurable real
sleep.
@@end

@example py-api-0002
@meta category=api_usage language=python difficulty=advanced tags=sqlite,transactions,idempotency,upsert

@user
Our CSV importer uses sqlite3 and we keep finding half-imported batches: when row 900 of 1000 raises, rows 1-899 are already committed. Somebody on the team said to wrap everything in `with conn:` and somebody else said that does nothing and we should use `with conn.cursor()`. Also, when a retried sync job runs after a crash it inserts duplicates. Please explain the transaction semantics properly and give me the importer pattern, with tests that prove the atomicity.
@@end

@assistant
Both teammates were half right, and the distinction is the whole answer.

- **`sqlite3.Connection` is a context manager that commits on success and rolls back on exception — but it does not close the connection.** `with conn:` is a transaction boundary, not resource management.
- **`sqlite3.Cursor` is also a context manager, and its `__exit__` does nothing transactional at all.** `with conn.cursor() as cur:` is purely a way to get a cursor; it will not commit and it will not roll back.
- **`with conn:` acts on the transaction that is already active — it does not start one.** With `isolation_level=None` (autocommit) an `INSERT` is committed the moment it runs, so a later exception inside the block cannot undo it. The importer below owns `BEGIN`/`COMMIT`/`ROLLBACK` explicitly, which is the only version that survives a crash mid-batch.
- The default `isolation_level=""` means sqlite3 *auto-begins* before DML and commits on `conn.commit()`; it does not open a transaction for `SELECT`, and DDL handling differs across versions. Relying on the implicit BEGIN is how "sometimes it is atomic" happens.

```python
import sqlite3


def _connect(path):
    conn = sqlite3.connect(path, isolation_level=None)   # take manual control
    conn.execute("PRAGMA foreign_keys = ON")             # per-connection, not per-database
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")           # do not fail on a writer lock
    return conn


def import_rows(conn, rows, *, batch_size=500):
    """All-or-nothing import. Returns (inserted, skipped_duplicates)."""
    inserted = skipped = 0
    conn.execute("BEGIN IMMEDIATE")                      # one writer, fail fast on lock
    try:
        for row in rows:
            cursor = conn.execute(
                # Dedupe on the primary key only. INSERT OR IGNORE would also
                # swallow CHECK/NOT NULL violations and silently drop bad rows.
                "INSERT INTO readings (id, sku, taken_at, value) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(id) DO NOTHING",
                (row["id"], row["sku"], row["taken_at"], row["value"]),
            )
            if cursor.rowcount == 1:
                inserted += 1
            else:
                skipped += 1
            if inserted and inserted % batch_size == 0:
                conn.execute("SAVEPOINT checkpoint")     # progress mark, not a commit
                conn.execute("RELEASE checkpoint")
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return inserted, skipped
```

Why each line is there:

- **`isolation_level=None` plus explicit `BEGIN IMMEDIATE`.** With auto-begin a statement error does not necessarily leave you at a clean boundary, and `BEGIN IMMEDIATE` takes the write lock up front so two importers cannot deadlock halfway through. It also means a second writer fails fast with `database is locked` instead of blocking your whole sync.
- **Constraints are what turn bad data into a failed import.** SQLite deliberately stores a string in a `REAL` column, so `value REAL NOT NULL` accepts `'not-a-number'` and the batch "succeeds" with garbage in it. `CHECK (value >= 0)` — or a `STRICT` table — makes the bad row fail the way the importer expects.
- **Dedupe with `ON CONFLICT(id) DO NOTHING`, not `INSERT OR IGNORE`.** Retrying after a crash re-inserts nothing and `cursor.rowcount` distinguishes inserted from skipped — but `OR IGNORE` ignores *every* constraint, including `NOT NULL` and `CHECK`, so a bad row is silently counted as a "skipped duplicate" and the data loss looks like healthy progress. `ON CONFLICT(<target>) DO NOTHING` ignores only the duplicate you intend to ignore.
- **Savepoints, not commits, for progress marks.** A `conn.commit()` every 500 rows "to bound rollback size" destroys atomicity and is exactly how you get a half-imported batch.
- **`PRAGMA foreign_keys` is per connection.** Set it in `_connect`, or your constraints silently do nothing on one code path.
- **One connection per thread.** sqlite3 connections are not shareable across threads by default (`check_same_thread=True`); pass `check_same_thread=False` *and* serialise access, or keep a connection per worker.
- **`executemany` is not a drop-in here**: for `INSERT ... ON CONFLICT DO NOTHING` you lose per-row `rowcount`, so use it only where you can count afterwards with a query.
@@end

@verify kind=executable language=python
@code
import os
import sqlite3
import tempfile

SCHEMA = """
CREATE TABLE readings (
    id TEXT PRIMARY KEY,
    sku TEXT NOT NULL,
    taken_at TEXT NOT NULL,
    -- NOT NULL + CHECK is what makes a bad row fail: SQLite would happily store
    -- the string 'not-a-number' in a REAL column otherwise (dynamic typing).
    value REAL NOT NULL CHECK (value >= 0)
);
CREATE TABLE skus (code TEXT PRIMARY KEY);
CREATE TABLE readings_fk (
    id TEXT PRIMARY KEY,
    sku TEXT NOT NULL REFERENCES skus(code)
);
"""


def _connect(path):
    conn = sqlite3.connect(path, isolation_level=None)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def import_rows(conn, rows, *, batch_size=500):
    inserted = skipped = 0
    conn.execute("BEGIN IMMEDIATE")
    try:
        for row in rows:
            cursor = conn.execute(
                "INSERT INTO readings (id, sku, taken_at, value) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(id) DO NOTHING",
                (row["id"], row["sku"], row["taken_at"], row["value"]),
            )
            if cursor.rowcount == 1:
                inserted += 1
            else:
                skipped += 1
            if inserted and inserted % batch_size == 0:
                conn.execute("SAVEPOINT checkpoint")
                conn.execute("RELEASE checkpoint")
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return inserted, skipped


def rows_for(n, start=0, bad=None):
    rows = []
    for i in range(start, start + n):
        row = {"id": f"r{i:05d}", "sku": "SKU-1", "taken_at": "2024-05-01T00:00:00Z",
               "value": float(i)}
        if bad is not None and i == bad:
            row["value"] = -1.0                  # violates CHECK (value >= 0)
        rows.append(row)
    return rows


def count(conn, table="readings"):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


with tempfile.TemporaryDirectory() as tmp:
    path = os.path.join(tmp, "import.db")
    conn = _connect(path)
    conn.executescript(SCHEMA)
    conn.execute("INSERT INTO skus (code) VALUES ('SKU-1')")

    # 1. Success path: everything committed, counts reported.
    inserted, skipped = import_rows(conn, rows_for(1000))
    assert (inserted, skipped) == (1000, 0), (inserted, skipped)
    assert count(conn) == 1000

    # 2. Idempotency: the same batch re-imported inserts nothing.
    inserted, skipped = import_rows(conn, rows_for(1000))
    assert (inserted, skipped) == (0, 1000), (inserted, skipped)
    assert count(conn) == 1000, "re-import must not duplicate"

    # 3. Atomicity: a failure at row 900 leaves ZERO new rows, even though the
    #    failing batch is bound to fail after 500 successful inserts.
    committed = count(conn)
    try:
        import_rows(conn, rows_for(1000, start=5000, bad=5900), batch_size=500)
        raise AssertionError("expected the import to fail")
    except sqlite3.IntegrityError as exc:
        assert "CHECK constraint failed" in str(exc), str(exc)
    assert count(conn) == committed, f"partial import leaked: {count(conn)} != {committed}"

    # 3b. The trap: the same batch with INSERT OR IGNORE "succeeds", reports the
    #     bad row as a skipped duplicate, and quietly drops the data.
    def import_rows_or_ignore(conn, rows):
        inserted = skipped = 0
        conn.execute("BEGIN IMMEDIATE")
        try:
            for row in rows:
                cursor = conn.execute(
                    "INSERT OR IGNORE INTO readings (id, sku, taken_at, value) VALUES (?, ?, ?, ?)",
                    (row["id"], row["sku"], row["taken_at"], row["value"]),
                )
                inserted += cursor.rowcount == 1
                skipped += cursor.rowcount != 1
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        return inserted, skipped

    bad_batch = rows_for(3, start=6000, bad=6001)
    inserted, skipped = import_rows_or_ignore(conn, bad_batch)
    assert (inserted, skipped) == (2, 1), (inserted, skipped)
    assert conn.execute(
        "SELECT COUNT(*) FROM readings WHERE id = 'r06001'"
    ).fetchone()[0] == 0, "the bad row was dropped and nothing said so"
    conn.execute("DELETE FROM readings WHERE id IN ('r06000', 'r06002')")  # autocommit
    assert count(conn) == committed

    # 4. The counts come from the same transaction; after a rollback the
    #    connection is usable again.
    inserted, skipped = import_rows(conn, rows_for(10, start=9000))
    assert (inserted, skipped) == (10, 0), (inserted, skipped)
    assert count(conn) == committed + 10

    # 5. An uncommitted row is invisible to another connection; COMMIT publishes it.
    other = _connect(path)
    assert count(other) == committed + 10
    conn.execute("BEGIN IMMEDIATE")
    conn.execute("INSERT INTO readings VALUES ('manual', 'SKU-1', '2024-05-02', 1.0)")
    assert count(other) == committed + 10, "uncommitted row must be invisible elsewhere"
    conn.execute("COMMIT")
    assert count(other) == committed + 11, "row must be visible after COMMIT"

    # 6. `with conn:` is a transaction boundary, but only around a transaction it
    #    actually owns: with isolation_level=None an INSERT is already committed
    #    when the block raises, so it cannot be rolled back.
    try:
        with conn:                                  # autocommit connection
            conn.execute("INSERT INTO readings VALUES ('cm-1', 'SKU-1', '2024-05-03', 2.0)")
            raise RuntimeError("business rule failed")
    except RuntimeError:
        pass
    assert count(other) == committed + 12, "autocommit: `with conn` cannot undo it"
    conn.execute("DELETE FROM readings WHERE id = 'cm-1'")
    assert count(other) == committed + 11

    # 6b. In the default isolation mode the documented behaviour holds: commit on
    #     success, rollback on exception, no transaction left open.
    defaulted = sqlite3.connect(path)
    with defaulted:
        defaulted.execute("INSERT INTO readings VALUES ('cm-2', 'SKU-1', '2024-05-03', 3.0)")
    assert count(other) == committed + 12
    try:
        with defaulted:
            defaulted.execute("INSERT INTO readings VALUES ('cm-3', 'SKU-1', '2024-05-03', 4.0)")
            raise RuntimeError("business rule failed")
    except RuntimeError:
        pass
    assert count(other) == committed + 12, "context manager must roll back"
    assert defaulted.in_transaction is False, "no transaction should be left open"
    defaulted.close()

    # 7. Big batches: the savepoint path is exercised and stays atomic.
    inserted, skipped = import_rows(conn, rows_for(2500, start=20000), batch_size=100)
    assert (inserted, skipped) == (2500, 0)
    assert count(other) == committed + 2512

    # 8. Foreign keys are enforced per connection (PRAGMA is not persisted).
    try:
        conn.execute("INSERT INTO readings_fk VALUES ('x', 'MISSING')")
        raise AssertionError("foreign key must be enforced")
    except sqlite3.IntegrityError:
        pass

    # 9. A writer lock fails fast with BEGIN IMMEDIATE instead of deadlocking:
    #    the second importer raises "database is locked" after busy_timeout.
    holder = _connect(path)
    holder.execute("BEGIN IMMEDIATE")
    holder.execute("INSERT INTO readings VALUES ('lock', 'SKU-1', '2024-05-04', 4.0)")
    blocked = _connect(path)
    blocked.execute("PRAGMA busy_timeout = 50")
    try:
        import_rows(blocked, rows_for(1, start=40000))
        raise AssertionError("second writer should have been rejected")
    except sqlite3.OperationalError as exc:
        assert "locked" in str(exc), str(exc)
    holder.execute("COMMIT")
    assert count(other) == committed + 2513, "the winner's row must be the only one added"
    blocked.close()
    holder.close()
    other.close()
    conn.close()
print("PASS")
@@end

@expect_output
PASS
@@end

@notes
Runs against a real file-backed SQLite database (temp dir), not `:memory:`, so a
second connection can observe the first one's transactions — which is what makes
the commit/rollback claims testable. Pinned: the success path imports 1000 rows
exactly once; re-importing the identical batch inserts 0 and reports 1000 skipped
(ON CONFLICT(id) DO NOTHING on the primary key = idempotency); a failure at row
900 of a 1000-row batch (bound to fail after 500 successful inserts, so the
savepoint path runs) leaves the row count unchanged and surfaces the CHECK
violation; the OR IGNORE trap is reproduced on the same bad batch (no exception,
"2 inserted, 1 skipped", and the bad row is simply gone), which is why the
importer uses ON CONFLICT; an uncommitted row is invisible to another connection
until COMMIT; `with conn:` cannot roll back an autocommitted INSERT
(isolation_level=None) but does commit/rollback correctly in the default
isolation mode, with `in_transaction` false afterwards; a 2500-row batch with
batch_size=100 stays atomic; `PRAGMA foreign_keys=ON` rejects an orphan row; and a
second importer fails fast with "database is locked" instead of deadlocking when
the write lock is held, with the winner's row the only one committed.
@@end

@example js-api-0003
@meta category=api_usage language=javascript difficulty=advanced tags=fetch,abort,pagination,concurrency

@user
We are rewriting a Node sync client from axios to the built-in `fetch`. Two problems in review: someone argued `fetch` throws on HTTP errors (it does not), and the timeout handling uses `Promise.race` with `setTimeout` that is never cleared. We also need cursor pagination with a concurrency cap, and the whole thing must not leak timers or sockets. Show me the client and how you test it.
@@end

@assistant
`fetch` is a thin HTTP transport, not an API client: it resolves for 404 and 500 alike, so **`response.ok` must be checked on every call**, and the body can only be read once. Timeouts belong to `AbortSignal.timeout(ms)`, which cannot leak a timer the way a manual `Promise.race` does — with `Promise.race` the loser keeps running, so a slow response pins memory and (worse) the caller's later `await` sees the abandoned promise settle later and logs an unhandled rejection.

```javascript
export class HttpError extends Error {
  constructor(status, url, body, headers) {
    super(`HTTP ${status} for ${url}`);
    this.name = "HttpError";
    this.status = status;
    this.body = body;
    this.headers = headers;      // Retry-After lives here, so error paths need it
  }
}

export async function fetchJson(url, { signal, timeoutMs = 5000, headers = {} } = {}) {
  // AbortSignal.timeout cannot leak a timer, and combining with anySignal keeps
  // the caller's own cancellation working.
  const timeout = AbortSignal.timeout(timeoutMs);
  const combined = signal ? AbortSignal.any([signal, timeout]) : timeout;

  const response = await fetch(url, {
    headers: { accept: "application/json", ...headers },
    signal: combined,
  });

  const text = await response.text();            // read once; error bodies included
  let payload = null;
  let parseError = null;
  try {
    payload = text === "" ? null : JSON.parse(text);
  } catch (error) {
    parseError = error;
  }

  if (!response.ok) throw new HttpError(response.status, url, payload ?? text, response.headers);

  if (parseError) {
    throw new Error(`invalid JSON from ${url}: ${parseError.message}`);
  }
  return { payload, headers: response.headers };
}

function retryDelayMs(headers, attempt) {
  const raw = headers?.get?.("retry-after");
  const seconds = raw !== null && raw !== undefined && /^\d+$/.test(raw.trim())
    ? Number(raw.trim())
    : null;
  const jitter = Math.random() * Math.min(2000, 100 * 2 ** attempt);
  return Math.max(seconds !== null ? seconds * 1000 : 0, jitter);
}

export async function mapWithConcurrency(items, limit, worker) {
  if (!Number.isInteger(limit) || limit < 1) throw new RangeError("limit must be >= 1");
  const results = new Array(items.length);
  let next = 0;
  async function run() {
    while (true) {
      const index = next++;
      if (index >= items.length) return;
      results[index] = await worker(items[index], index);
    }
  }
  await Promise.all(Array.from({ length: Math.min(limit, items.length) }, run));
  return results;
}

export async function fetchAllPages(baseUrl, { pageSize = 2, maxPages = 10, retries = 2 } = {}) {
  const items = [];
  let cursor = null;
  for (let page = 0; page < maxPages; page++) {
    const url = new URL(baseUrl);
    url.searchParams.set("limit", String(pageSize));
    if (cursor) url.searchParams.set("cursor", cursor);

    let result = null;
    for (let attempt = 0; ; attempt++) {
      try {
        result = await fetchJson(url.toString());
        break;
      } catch (error) {
        const retryable = error.name === "TimeoutError" || error.name === "AbortError" ||
          (error instanceof HttpError && (error.status === 429 || error.status >= 500));
        if (!retryable || attempt >= retries) throw error;
        await new Promise((resolve) => setTimeout(resolve, retryDelayMs(error.headers, attempt)));
      }
    }

    const body = result.payload;
    if (!body || !Array.isArray(body.items)) {
      throw new Error(`unexpected payload from ${url}: ${JSON.stringify(body)?.slice(0, 120)}`);
    }
    items.push(...body.items);
    cursor = body.nextCursor ?? null;
    if (!cursor) break;
  }
  return items;
}
```

Notes for the review, because each one is a bug you will otherwise ship:

- **`AbortSignal.timeout` + `AbortSignal.any`.** The timeout signal is owned by the platform; `AbortSignal.any` composes it with the caller's signal so manual cancellation still works. No `clearTimeout` bookkeeping, no leaked timers.
- **Aborts surface as `TimeoutError`/`AbortError` `DOMException`s**, not as HTTP errors; retry logic has to classify them separately from `HttpError`, and neither should be retried when the caller aborted deliberately.
- **Bounded retries with `Retry-After`** only for 429/5xx and timeouts, and only if the operation is idempotent — the same rule as the Python client. The retry decision needs the *response headers*, so `HttpError` has to carry them; dropping them makes the header unreadable exactly when it matters.
- **`mapWithConcurrency` is the whole concurrency control.** `Promise.all` over N urls opens N sockets; a shared index with `limit` workers keeps the in-flight count bounded without a queue library.
- **Payload shape is validated before use.** `body.items` missing means the vendor changed the contract; failing loudly beats pushing `undefined` into a database.
- **`response.text()` first, then parse.** Reading the body once and parsing from the string lets the error path include the vendor's message, which is what your on-call engineer needs at 3am.

The test spins up a real `http.createServer` on port 0, so the socket path, headers, and abort behaviour are exercised — not mocked.
@@end

@verify kind=executable language=javascript
@code
import assert from "node:assert/strict";
import http from "node:http";
import test from "node:test";

class HttpError extends Error {
  constructor(status, url, body, headers) {
    super(`HTTP ${status} for ${url}`);
    this.name = "HttpError";
    this.status = status;
    this.body = body;
    this.headers = headers;
  }
}

async function fetchJson(url, { signal, timeoutMs = 5000, headers = {} } = {}) {
  const timeout = AbortSignal.timeout(timeoutMs);
  const combined = signal ? AbortSignal.any([signal, timeout]) : timeout;
  const response = await fetch(url, {
    headers: { accept: "application/json", ...headers },
    signal: combined,
  });
  const text = await response.text();
  let payload = null;
  let parseError = null;
  try {
    payload = text === "" ? null : JSON.parse(text);
  } catch (error) {
    parseError = error;
  }
  if (!response.ok) throw new HttpError(response.status, url, payload ?? text, response.headers);
  if (parseError) throw new Error(`invalid JSON from ${url}: ${parseError.message}`);
  return { payload, headers: response.headers };
}

async function mapWithConcurrency(items, limit, worker) {
  if (!Number.isInteger(limit) || limit < 1) throw new RangeError("limit must be >= 1");
  const results = new Array(items.length);
  let next = 0;
  async function run() {
    while (true) {
      const index = next++;
      if (index >= items.length) return;
      results[index] = await worker(items[index], index);
    }
  }
  await Promise.all(Array.from({ length: Math.min(limit, items.length) }, run));
  return results;
}

function retryDelayMs(headers, attempt) {
  const raw = headers?.get?.("retry-after");
  const seconds = raw !== null && raw !== undefined && /^\d+$/.test(raw.trim())
    ? Number(raw.trim())
    : null;
  const jitter = Math.random() * Math.min(2000, 100 * 2 ** attempt);
  return Math.max(seconds !== null ? seconds * 1000 : 0, jitter);
}

async function fetchAllPages(baseUrl, { pageSize = 2, maxPages = 10, retries = 2,
  retryDelay = (ms) => new Promise((resolve) => setTimeout(resolve, ms)) } = {}) {
  const items = [];
  let cursor = null;
  for (let page = 0; page < maxPages; page++) {
    const url = new URL(baseUrl);
    url.searchParams.set("limit", String(pageSize));
    if (cursor) url.searchParams.set("cursor", cursor);
    let result = null;
    for (let attempt = 0; ; attempt++) {
      try {
        result = await fetchJson(url.toString());
        break;
      } catch (error) {
        const retryable = error.name === "TimeoutError" || error.name === "AbortError" ||
          (error instanceof HttpError && (error.status === 429 || error.status >= 500));
        if (!retryable || attempt >= retries) throw error;
        await retryDelay(retryDelayMs(error.headers, attempt));
      }
    }
    const body = result.payload;
    if (!body || !Array.isArray(body.items)) {
      throw new Error(`unexpected payload from ${url}: ${JSON.stringify(body)?.slice(0, 120)}`);
    }
    items.push(...body.items);
    cursor = body.nextCursor ?? null;
    if (!cursor) break;
  }
  return items;
}

// ---- real server, scripted plan ---------------------------------------------
function startServer(handler) {
  const server = http.createServer((req, res) => handler(req, res));
  return new Promise((resolve) => {
    server.listen(0, "127.0.0.1", () => {
      const { port } = server.address();
      resolve({ server, baseUrl: `http://127.0.0.1:${port}`, close: () => new Promise((done) => server.close(done)) });
    });
  });
}

function json(res, status, body, headers = {}) {
  const text = JSON.stringify(body);
  res.writeHead(status, { "content-type": "application/json", "content-length": Buffer.byteLength(text), ...headers });
  res.end(text);
}

test("fetch resolves for HTTP errors, so response.ok is checked explicitly", async () => {
  const app = await startServer((req, res) => json(res, 404, { error: "no such item" }));
  try {
    await assert.rejects(
      () => fetchJson(`${app.baseUrl}/missing`),
      (error) => {
        assert.equal(error.name, "HttpError");
        assert.equal(error.status, 404);
        assert.deepEqual(error.body, { error: "no such item" });
        return true;
      },
    );
  } finally {
    await app.close();
  }
});

test("pagination follows nextCursor and stops when it is absent", async () => {
  const pages = {
    null: { items: [1, 2], nextCursor: "c1" },
    c1: { items: [3, 4], nextCursor: "c2" },
    c2: { items: [5], nextCursor: null },
  };
  const app = await startServer((req, res) => {
    const url = new URL(req.url, "http://localhost");
    if (url.searchParams.get("limit") !== "2") return json(res, 400, { error: "limit" });
    const cursor = url.searchParams.get("cursor");
    return json(res, 200, pages[cursor]);
  });
  try {
    const items = await fetchAllPages(`${app.baseUrl}/items`);
    assert.deepEqual(items, [1, 2, 3, 4, 5]);
  } finally {
    await app.close();
  }
});

test("429 retry honours Retry-After, and retries are bounded", async () => {
  let calls = 0;
  const app = await startServer((req, res) => {
    calls += 1;
    if (calls <= 1) return json(res, 429, { error: "slow down" }, { "retry-after": "1" });
    return json(res, 200, { items: ["ok"], nextCursor: null });
  });
  const waits = [];
  try {
    const items = await fetchAllPages(`${app.baseUrl}/items`, {
      retryDelay: (ms) => {
        waits.push(ms);
        return Promise.resolve();
      },
    });
    assert.deepEqual(items, ["ok"]);
    assert.equal(calls, 2);
    assert.equal(waits.length, 1);
    assert.ok(waits[0] >= 1000, `Retry-After must be a floor, got ${waits[0]}`);
  } finally {
    await app.close();
  }
});

test("retries stop after the configured budget", async () => {
  let calls = 0;
  const app = await startServer((req, res) => {
    calls += 1;
    return json(res, 503, { error: "unavailable" });
  });
  try {
    await assert.rejects(
      () => fetchAllPages(`${app.baseUrl}/items`, { retries: 1, retryDelay: () => Promise.resolve() }),
      (error) => error.status === 503,
    );
    assert.equal(calls, 2, "one initial attempt plus one retry");
  } finally {
    await app.close();
  }
});

test("AbortSignal.timeout produces a TimeoutError and actually aborts the request", async () => {
  let aborted = false;
  const app = await startServer((req, res) => {
    req.on("aborted", () => { aborted = true; });
    setTimeout(() => {
      if (!res.writableEnded) json(res, 200, { items: [], nextCursor: null });
    }, 500);
  });
  try {
    await assert.rejects(
      () => fetchJson(`${app.baseUrl}/slow`, { timeoutMs: 50 }),
      (error) => {
        assert.equal(error.name, "TimeoutError");
        return true;
      },
    );
    await new Promise((resolve) => setTimeout(resolve, 60));
    assert.equal(aborted, true, "the request must be aborted, not merely abandoned");
  } finally {
    await app.close();
  }
});

test("caller-provided signal still cancels when composed with the timeout", async () => {
  const app = await startServer((req, res) => {
    setTimeout(() => { if (!res.writableEnded) json(res, 200, {}); }, 500);
  });
  try {
    const controller = new AbortController();
    setTimeout(() => controller.abort(), 30);
    await assert.rejects(
      () => fetchJson(`${app.baseUrl}/slow`, { signal: controller.signal, timeoutMs: 5000 }),
      (error) => error.name === "AbortError",
    );
  } finally {
    await app.close();
  }
});

test("concurrency stays within the limit and results keep input order", async () => {
  let inFlight = 0;
  let peak = 0;
  const app = await startServer(async (req, res) => {
    inFlight += 1;
    peak = Math.max(peak, inFlight);
    await new Promise((resolve) => setTimeout(resolve, 20));
    inFlight -= 1;
    json(res, 200, { items: [req.url], nextCursor: null });
  });
  try {
    const urls = Array.from({ length: 12 }, (_, i) => `${app.baseUrl}/i${i}`);
    const results = await mapWithConcurrency(urls, 3, async (url) => {
      const { payload } = await fetchJson(url);
      return payload.items[0];
    });
    assert.equal(results.length, 12);
    assert.deepEqual(results, urls.map((url) => new URL(url).pathname));
    assert.ok(peak <= 3, `peak concurrency ${peak} exceeded the limit`);
    assert.ok(peak >= 2, `expected real parallelism, peak was ${peak}`);
    await assert.rejects(() => mapWithConcurrency(urls, 0, async () => 1), RangeError);
  } finally {
    await app.close();
  }
});

test("a non-array payload is rejected instead of silently producing nothing", async () => {
  const app = await startServer((req, res) => json(res, 200, { data: [1, 2] }));
  try {
    await assert.rejects(
      () => fetchAllPages(`${app.baseUrl}/items`),
      /unexpected payload/,
    );
  } finally {
    await app.close();
  }
});
@@end

@expect_output
REGEX: # pass 8\n# fail 0
@@end

@notes
Eight node:test cases against a real http server on an ephemeral port (no fetch
mocking), so abort behaviour, header parsing and socket handling are real. Pinned:
fetch resolving on 404 with `response.ok` turning it into an HttpError carrying
status and parsed body; three-page cursor pagination including the terminating
null cursor and the `limit` query parameter; a 429 whose Retry-After is honoured
as a floor (recorded retry delays, no real sleep); the retry budget stopping
after one retry (server call count asserted); `AbortSignal.timeout` raising
`TimeoutError` **and** the server observing an aborted request rather than a
merely abandoned one; a caller AbortController composed via `AbortSignal.any`
still cancelling; `mapWithConcurrency` keeping the peak in-flight count at or
below the limit while preserving input order, with `limit < 1` rejected; and a
payload missing `items` failing loudly instead of yielding an empty result.
@@end

@example py-api-0004
@meta category=api_usage language=python difficulty=advanced tags=subprocess,pipes,timeouts,deadlock

@user
Our deploy step shells out to `git` and `docker` and it hangs about once a week. The wrapper uses `subprocess.run(cmd, capture_output=True)`, and when a command fails we cannot tell whether stdout or stderr mattered because the traceback shows neither. It also leaves orphaned child processes behind when we move on. What is the correct way to run a child process from Python?
@@end

@assistant
`subprocess.run(..., capture_output=True)` is fine *until* it isn't, for four specific reasons:

1. **No timeout means it can hang forever.** The default is `timeout=None`. A `git fetch` on a wedged TCP connection blocks the deploy indefinitely.
2. **Two buffers, but the traceback shows neither.** `CalledProcessError.__str__` gives you the command and the exit code, not the output that explains the failure. Catch it and carry `stdout`/`stderr` yourself.
3. **`shell=True` with a string command is a shell-injection bug** as soon as any part of it comes from configuration. Pass a list and never interpolate.
4. **Killing the direct child does not kill its children.** `proc.kill()` after `TimeoutExpired` leaves `docker`'s grandchildren running. Start the child in its own process group and signal the group.

```python
import os
import signal
import subprocess
import time


class CommandFailed(RuntimeError):
    def __init__(self, argv, returncode, stdout, stderr):
        super().__init__(f"{' '.join(argv)} exited {returncode}")
        self.argv = argv
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def run(argv, *, timeout_s=30.0, env=None, cwd=None, input_text=None):
    """Run argv to completion, with a real timeout and a killable process group."""
    if not isinstance(argv, (list, tuple)):
        raise TypeError("argv must be a list; shell=True with a string is an injection risk")

    # start_new_session=True puts the child in its own process group, so we can
    # signal the whole tree (docker, git-remote-https, ...) and not just the pid.
    proc = subprocess.Popen(
        list(argv),
        stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",            # never crash on a stray byte in the logs
        cwd=cwd,
        env={**os.environ, **(env or {})},
        start_new_session=True,
    )
    try:
        stdout, stderr = proc.communicate(input=input_text, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        _kill_group(proc)
        stdout, stderr = proc.communicate()      # reap, do not leave a zombie
        raise CommandFailed([*argv, f"(timeout {timeout_s}s)"], -signal.SIGKILL, stdout, stderr)
    if proc.returncode != 0:
        raise CommandFailed(list(argv), proc.returncode, stdout, stderr)
    return stdout, stderr


def _kill_group(proc, grace_s=2.0):
    """SIGTERM the child's process group, then SIGKILL it if it lingers."""
    if proc.poll() is not None:
        return
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except ProcessLookupError:                   # already gone
        return
    deadline = time.monotonic() + grace_s
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return
        time.sleep(0.02)
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except ProcessLookupError:
        pass
```

Points that decide whether this survives production:

- **`communicate()` drains both pipes concurrently**, so it cannot deadlock the way `proc.stdout.read()` followed by `proc.wait()` does when the child fills the stderr pipe while you are reading stdout. That is the classic "it hangs after ~64KB of output" bug, and `communicate()` is the entire fix.
- **`text=True` plus `errors="replace"`.** Decoding errors on a stray byte raise `UnicodeDecodeError` in the middle of a deploy; `errors="replace"` keeps the log and never loses the exit code.
- **Reap after killing.** Skipping the second `communicate()` leaves a zombie and can lose the tail of the output that explains the failure.
- **`stdin=DEVNULL` unless you mean to write.** Inheriting stdin lets a child swallow your terminal input or hang waiting for something to type.
- **Timeouts belong to the operation, not to the call site.** A `git fetch` that legitimately takes 90s needs 90s; a 30s default that "worked in testing" silently kills healthy work on a slow network. Pass it per call.
- **Log stdout and stderr separately.** Merging them loses the ability to alert on stderr and to diff stdout against expectations.
- **`SIGTERM`, then `SIGKILL` after a grace period.** `docker` and `git` need a moment to clean up; a bare `SIGKILL` leaves lock files and half-written state behind, while a bare `SIGTERM` can be ignored.
@@end

@verify kind=executable language=python
@code
import os
import signal
import subprocess
import sys
import time

PY = sys.executable


class CommandFailed(RuntimeError):
    def __init__(self, argv, returncode, stdout, stderr):
        super().__init__(f"{' '.join(argv)} exited {returncode}")
        self.argv = argv
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _kill_group(proc, grace_s=2.0):
    if proc.poll() is not None:
        return
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + grace_s
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return
        time.sleep(0.02)
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except ProcessLookupError:
        pass


def run(argv, *, timeout_s=30.0, env=None, cwd=None, input_text=None):
    if not isinstance(argv, (list, tuple)):
        raise TypeError("argv must be a list; shell=True with a string is an injection risk")
    proc = subprocess.Popen(
        list(argv),
        stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=cwd,
        env={**os.environ, **(env or {})},
        start_new_session=True,
    )
    try:
        stdout, stderr = proc.communicate(input=input_text, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        _kill_group(proc)
        stdout, stderr = proc.communicate()
        raise CommandFailed([*argv, f"(timeout {timeout_s}s)"], -signal.SIGKILL, stdout, stderr)
    if proc.returncode != 0:
        raise CommandFailed(list(argv), proc.returncode, stdout, stderr)
    return stdout, stderr


PROG_STREAMS = "import sys\nprint('to-stdout')\nprint('to-stderr', file=sys.stderr)\n"
PROG_FAIL = "import sys\nprint('partial work', flush=True)\nprint('boom', file=sys.stderr)\nsys.exit(3)\n"
PROG_FLOOD = ("import sys\n"
              "sys.stdout.write('o' * 1048576)\n"
              "sys.stderr.write('e' * 1048576)\n")
PROG_SLEEP = "import sys, time\nprint('starting', flush=True)\ntime.sleep(30)\n"
PROG_GRANDCHILD = ("import subprocess, sys, time\n"
                   "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])\n"
                   "print(child.pid, flush=True)\n"
                   "time.sleep(30)\n")
PROG_STDIN = "import sys\nprint(repr(sys.stdin.read()))\n"
PROG_STDIN_UPPER = "import sys\nprint(sys.stdin.read().strip().upper())\n"
PROG_STRAY_BYTE = "import sys\nsys.stdout.buffer.write(b'caf\\xe9\\n')\n"

# 1. Success: stdout and stderr stay separate, both decoded as text.
out, err = run([PY, "-c", PROG_STREAMS])
assert out == "to-stdout\n", repr(out)
assert err == "to-stderr\n", repr(err)

# 2. Failure carries both streams and the exit code in a typed error.
try:
    run([PY, "-c", PROG_FAIL])
    raise AssertionError("expected CommandFailed")
except CommandFailed as exc:
    assert exc.returncode == 3, exc.returncode
    assert exc.stdout == "partial work\n", repr(exc.stdout)
    assert exc.stderr == "boom\n", repr(exc.stderr)

# 3. The classic deadlock: the child floods BOTH pipes past the 64KB buffer.
#    communicate() drains them concurrently; read-then-wait would hang here.
out, err = run([PY, "-c", PROG_FLOOD], timeout_s=10.0)
assert len(out) == 1048576 and len(err) == 1048576, (len(out), len(err))

# 4. A timeout kills the process tree and reports what was captured so far.
started = time.monotonic()
try:
    run([PY, "-c", PROG_SLEEP], timeout_s=0.5)
    raise AssertionError("expected the timeout to fire")
except CommandFailed as exc:
    elapsed = time.monotonic() - started
    assert elapsed < 5.0, elapsed
    assert "(timeout 0.5s)" in " ".join(exc.argv)
    assert exc.stdout == "starting\n", repr(exc.stdout)

# 5. The grandchild dies too: start_new_session + killpg reach the whole group.
try:
    run([PY, "-c", PROG_GRANDCHILD], timeout_s=0.6)
    raise AssertionError("expected the timeout to fire")
except CommandFailed as exc:
    grandchild_pid = int(exc.stdout.strip().splitlines()[0])
    time.sleep(0.3)
    try:
        os.kill(grandchild_pid, 0)               # signal 0: does it still exist?
        alive = True
    except ProcessLookupError:
        alive = False
    assert not alive, f"grandchild {grandchild_pid} survived the group kill"

# 6. stdin is closed unless input_text is supplied: no hang, EOF instead.
out, err = run([PY, "-c", PROG_STDIN])
assert out == "''\n", repr(out)
out, err = run([PY, "-c", PROG_STDIN_UPPER], input_text="hello\n")
assert out == "HELLO\n", repr(out)

# 7. A stray non-UTF-8 byte is replaced, not raised.
out, err = run([PY, "-c", PROG_STRAY_BYTE])
assert out.startswith("caf") and out.endswith("\n"), repr(out)
assert out != "caf\\xe9\n", "the byte must have been replaced"

# 8. A string argv is refused (injection guard), and exit codes propagate.
try:
    run("echo hello")
    raise AssertionError("a string argv must be refused")
except TypeError as exc:
    assert "injection" in str(exc), str(exc)
try:
    run([PY, "-c", "import sys; sys.exit(127)"])
    raise AssertionError("expected CommandFailed")
except CommandFailed as exc:
    assert exc.returncode == 127, exc.returncode

# 9. env and cwd are per call and do not mutate the parent.
out, err = run([PY, "-c", "import os; print(os.environ['DEPLOY_STAGE'], os.getcwd())"],
               env={"DEPLOY_STAGE": "canary"}, cwd="/tmp")
assert out.startswith("canary /tmp"), repr(out)
assert "DEPLOY_STAGE" not in os.environ, "the parent environment must not be mutated"
print("PASS")
@@end

@expect_output
PASS
@@end

@notes
Nine cases against real child processes (this interpreter, spawned with -c
programs), so pipes, signals and process groups are genuinely exercised. Pinned:
stdout and stderr stay separate and are decoded as text; a non-zero exit raises
CommandFailed carrying returncode plus both streams (including the partial stdout
written before the failure); 1 MiB written to each stream completes without
deadlock, which is the read-then-wait bug this pattern avoids; a timeout fires in
under a second, reports "(timeout 0.5s)" and still returns the output captured
before the kill; a spawned grandchild is dead after the timeout (start_new_session
plus killpg reach the whole process group, not just the direct child); stdin is
closed unless input_text is supplied, so a reading child gets EOF instead of
hanging, and input_text is delivered when given; a stray non-UTF-8 byte is
replaced rather than raising; a string argv is refused as an injection risk; exit
code 127 propagates verbatim; and env/cwd are applied per call without mutating the
parent's environment.
@@end
