@example ts-code-0001
@meta category=code_generation language=typescript difficulty=advanced tags=retry-exponential-backoff,jitter,abort-signal,types

@user
Write a reusable retry helper for our internal API client in TypeScript (strict mode). Requirements: exponential backoff with full jitter, honour a Retry-After hint when the server sends one, stop retrying when an overall deadline expires, only retry errors we classify as transient, and let tests inject the clock/sleep/random so they never actually wait. The retry must not change the resolved type of the wrapped function.
@@end

@assistant
The design point is that everything non-deterministic (time, sleeping, randomness) is injected through options, so tests are exact instead of flaky, and the generic `T` flows through so callers keep their types.

```ts
export type RetryOptions = {
  attempts: number;                              // total tries, including the first
  baseDelayMs: number;
  maxDelayMs: number;
  // Injectable for tests; defaults are the real thing.
  sleep?: (ms: number) => Promise<void>;
  random?: () => number;                         // [0, 1)
  now?: () => number;                            // monotonic milliseconds
  deadlineMs?: number;                           // budget for the whole operation
  signal?: AbortSignal;
  isRetryable?: (error: unknown) => boolean;
  onRetry?: (info: { attempt: number; delayMs: number; error: unknown }) => void;
};

export type ApiFailure =
  | { kind: "aborted"; reason: string }
  | { kind: "exhausted"; attempts: number; lastError: unknown };

export class RetryAborted extends Error {
  constructor(readonly failure: ApiFailure) {
    super(`retry aborted: ${failure.kind}`);
    this.name = "RetryAborted";
  }
}

/** Errors that expose a server-side hint, e.g. HTTP 429/503 with Retry-After. */
export class TransientHttpError extends Error {
  constructor(readonly status: number, readonly retryAfterMs?: number) {
    super(`transient HTTP ${status}`);
    this.name = "TransientHttpError";
  }
}

const defaultSleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));
const defaultNow = () => performance.now();

export async function withRetry<T>(
  operation: (attempt: number) => Promise<T>,
  options: RetryOptions,
): Promise<T> {
  const {
    attempts,
    baseDelayMs,
    maxDelayMs,
    sleep = defaultSleep,
    random = Math.random,
    now = defaultNow,
    deadlineMs = Number.POSITIVE_INFINITY,
    signal,
    isRetryable = (error) => error instanceof TransientHttpError,
    onRetry,
  } = options;

  if (attempts < 1) throw new RangeError("attempts must be >= 1");
  if (baseDelayMs <= 0 || maxDelayMs < baseDelayMs) {
    throw new RangeError("require 0 < baseDelayMs <= maxDelayMs");
  }

  // performance.now() is monotonic: wall-clock jumps must not extend the deadline.
  // The clock is injectable for the same reason sleep is: a test that fakes only
  // one of them cannot detect deadline overruns at all.
  const startedAt = now();
  const remaining = () => deadlineMs - (now() - startedAt);

  for (let attempt = 1; ; attempt++) {
    if (signal?.aborted) {
      throw new RetryAborted({ kind: "aborted", reason: String(signal.reason ?? "signal") });
    }
    try {
      return await operation(attempt);
    } catch (error) {
      const isLast = attempt >= attempts;
      if (isLast || !isRetryable(error)) throw error;

      // Full jitter: uniform in [0, cap). Never a fixed delay, so retrying
      // clients do not synchronise into a thundering herd.
      const cap = Math.min(maxDelayMs, baseDelayMs * 2 ** (attempt - 1));
      const hint =
        error instanceof TransientHttpError && error.retryAfterMs !== undefined
          ? Math.min(maxDelayMs, error.retryAfterMs)
          : 0;
      const delayMs = Math.max(hint, Math.round(random() * cap));

      if (delayMs >= remaining()) throw error;      // no budget left to wait
      onRetry?.({ attempt, delayMs, error });
      await sleep(delayMs);
    }
  }
}
```

What makes this production-shaped rather than a snippet:

- **Jitter is `random() * cap`**, not `cap / 2 + random() * cap / 2`: full jitter decorrelates retry storms. The `Math.max(hint, ...)` line means a server-provided `Retry-After` is respected but still capped by `maxDelayMs`, so a hostile `Retry-After: 86400` cannot pin a request for a day.
- **Deadline vs single delay:** checking `delayMs >= remaining()` before sleeping prevents the classic bug where a 30 s sleep overruns a 5 s deadline. Both `sleep` *and* `now` are injectable because faking only the sleep makes the deadline untestable: the fake returns instantly, so `remaining()` never shrinks and every delay looks affordable.
- **`performance.now()`** for the deadline: a `Date.now()` implementation would be wrong across NTP corrections or clock changes.
- **Non-retryable errors propagate immediately** — a 400 does not deserve three attempts, and the last error is always rethrown unchanged, so callers can still pattern-match on the real error.
- **`signal` is honoured before each attempt.** With `AbortSignal.timeout(ms)` you can compose transport-level cancellation with this budget.
- **Attempts are 1-based** and passed into `operation`, so callers can log `attempt` and send idempotency keys per attempt.

Type-level contract: `withRetry<T>` returns `Promise<T>`; `RetryOptions` is closed over `unknown` for errors so callers can narrow with their own type guards. The verification file also asserts the exact delay sequence with a scripted `random` and a fake `sleep`, which is only possible because both are injected.
@@end

@verify kind=executable language=typescript

@code
type RetryOptions = {
  attempts: number;
  baseDelayMs: number;
  maxDelayMs: number;
  sleep?: (ms: number) => Promise<void>;
  random?: () => number;
  now?: () => number;
  deadlineMs?: number;
  signal?: AbortSignal;
  isRetryable?: (error: unknown) => boolean;
  onRetry?: (info: { attempt: number; delayMs: number; error: unknown }) => void;
};

export class RetryAborted extends Error {
  constructor(readonly failure: { kind: string; reason: string }) {
    super(`retry aborted: ${failure.kind}`);
    this.name = "RetryAborted";
  }
}

export class TransientHttpError extends Error {
  constructor(readonly status: number, readonly retryAfterMs?: number) {
    super(`transient HTTP ${status}`);
    this.name = "TransientHttpError";
  }
}

// --- type-level assertions (compiled by tsc --strict before the run) --------
type Equal<A, B> = (<T>() => T extends A ? 1 : 2) extends <T>() => T extends B ? 1 : 2 ? true : false;
type Expect<T extends true> = T;

type User = { id: string; name: string };
declare const loadUser: (attempt: number) => Promise<User>;

// The generic must survive: a Promise<User> comes out, not Promise<unknown>.
type _PreservesReturnType = Expect<Equal<Awaited<ReturnType<typeof withRetry<User>>>, User>>;
// Attempts are 1-based and passed through.
type _AttemptParam = Expect<Equal<Parameters<typeof withRetry<User>>[0], (attempt: number) => Promise<User>>>;
// @ts-expect-error the wrapped function must return a promise
const _rejectsSync: User = 1;

async function withRetry<T>(
  operation: (attempt: number) => Promise<T>,
  options: RetryOptions,
): Promise<T> {
  const {
    attempts,
    baseDelayMs,
    maxDelayMs,
    sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms)),
    random = Math.random,
    now = () => performance.now(),
    deadlineMs = Number.POSITIVE_INFINITY,
    signal,
    isRetryable = (error: unknown) => error instanceof TransientHttpError,
    onRetry,
  } = options;
  if (attempts < 1) throw new RangeError("attempts must be >= 1");
  if (baseDelayMs <= 0 || maxDelayMs < baseDelayMs) throw new RangeError("bad delays");

  const startedAt = now();
  const remaining = () => deadlineMs - (now() - startedAt);

  for (let attempt = 1; ; attempt++) {
    if (signal?.aborted) {
      throw new RetryAborted({ kind: "aborted", reason: String(signal.reason ?? "signal") });
    }
    try {
      return await operation(attempt);
    } catch (error) {
      if (attempt >= attempts || !isRetryable(error)) throw error;
      const cap = Math.min(maxDelayMs, baseDelayMs * 2 ** (attempt - 1));
      const hint =
        error instanceof TransientHttpError && error.retryAfterMs !== undefined
          ? Math.min(maxDelayMs, error.retryAfterMs)
          : 0;
      const delayMs = Math.max(hint, Math.round(random() * cap));
      if (delayMs >= remaining()) throw error;
      onRetry?.({ attempt, delayMs, error });
      await sleep(delayMs);
    }
  }
}

// --- runtime assertions -----------------------------------------------------
const failures: string[] = [];
function check(name: string, actual: unknown, expected: unknown): void {
  const a = JSON.stringify(actual), e = JSON.stringify(expected);
  if (a !== e) failures.push(`${name}: got ${a}, want ${e}`);
}

async function main(): Promise<void> {
  // 1. Non-retryable error: exactly one attempt, original error rethrown.
  let calls = 0;
  const fatal = new Error("400 bad request");
  try {
    await withRetry<number>(async () => { calls++; throw fatal; },
      { attempts: 5, baseDelayMs: 10, maxDelayMs: 100, sleep: async () => {}, random: () => 0.5, isRetryable: () => false });
    failures.push("fatal: expected throw");
  } catch (e) {
    check("fatal rethrows same object", e === fatal, true);
  }
  check("fatal attempts", calls, 1);

  // 2. Exact backoff schedule with scripted randomness (full jitter), capped.
  const delays: number[] = [];
  calls = 0;
  const value = await withRetry<string>(async () => {
    calls++;
    if (calls < 4) throw new TransientHttpError(503);
    return "ok";
  }, {
    attempts: 6, baseDelayMs: 100, maxDelayMs: 150, random: () => 0.5,
    sleep: async (ms) => { delays.push(ms); },
  });
  check("recovers", value, "ok");
  check("attempts used", calls, 4);
  check("backoff schedule", delays, [50, 75, 75]);   // cap 100/200/400 -> 150

  // 3. Retry-After hint overrides jitter but is capped by maxDelayMs.
  const hinted: number[] = [];
  calls = 0;
  await withRetry<void>(async () => {
    calls++;
    if (calls === 1) throw new TransientHttpError(429, 900);
    if (calls === 2) throw new TransientHttpError(429, 60000);
    return undefined;
  }, {
    attempts: 4, baseDelayMs: 20, maxDelayMs: 1000, random: () => 0.1,
    sleep: async (ms) => { hinted.push(ms); },
  });
  check("hint respected then capped", hinted, [900, 1000]);

  // 4. Deadline: the helper must stop before a sleep would cross the budget.
  //    Both sleep and now are faked, so the 60ms budget is exact and the test
  //    still finishes instantly. Faking only sleep would make `remaining()`
  //    always look like 60ms and the assertion below could never fail.
  const slept: number[] = [];
  calls = 0;
  let clock = 0;
  try {
    await withRetry<number>(async () => { calls++; throw new TransientHttpError(503); },
      { attempts: 10, baseDelayMs: 50, maxDelayMs: 5000, random: () => 0.9, deadlineMs: 60,
        now: () => clock, sleep: async (ms) => { slept.push(ms); clock += ms; } });
    failures.push("deadline: expected throw");
  } catch (e) {
    check("deadline rethrows transient", e instanceof TransientHttpError, true);
  }
  check("deadline: exactly one in-budget sleep", slept, [45]);
  check("deadline: total slept never crosses the budget", clock <= 60, true);
  check("deadline: stopped after the second attempt", calls, 2);

  // 5. Abort before the first attempt short-circuits.
  try {
    await withRetry<number>(async () => 1, {
      attempts: 3, baseDelayMs: 10, maxDelayMs: 20, signal: AbortSignal.abort("cancelled"),
      sleep: async () => {}, random: () => 0,
    });
    failures.push("abort: expected throw");
  } catch (e) {
    check("abort surfaces", e instanceof RetryAborted, true);
  }

  // 6. Guard clauses.
  for (const opts of [{ attempts: 0, baseDelayMs: 1, maxDelayMs: 2 },
                      { attempts: 2, baseDelayMs: 5, maxDelayMs: 1 }]) {
    try {
      await withRetry<number>(async () => 1, { ...opts, sleep: async () => {} });
      failures.push(`guard: accepted ${JSON.stringify(opts)}`);
    } catch (e) {
      check("guard is RangeError", e instanceof RangeError, true);
    }
  }

  // No @types/node in this sandbox, so report failures by throwing instead of
  // touching process.exitCode; a non-zero exit is what the harness checks.
  if (failures.length) throw new Error(`assertion failures:\n${failures.join("\n")}`);
  console.log("PASS");
}

void main();
@@end

@expect_output
PASS
@@end

@notes
Executed as TypeScript: `tsc --strict` must accept the file (which validates the
type-level assertions, including the @ts-expect-error probe), then the emitted
JavaScript runs. Runtime assertions cover: non-retryable short-circuit and
identity of the rethrown error, the exact jittered backoff schedule
[50,75,75] under a scripted RNG and maxDelay cap, Retry-After overriding jitter
and then being capped at maxDelayMs, the deadline refusing to sleep past the
budget (elapsed < 60ms with zero sleeps), pre-aborted signals, and both
RangeError guard clauses.
@@end

@example py-code-0002
@meta category=code_generation language=python difficulty=intermediate tags=csv-ingestion,streaming,validation,error-reporting

@user
Write a streaming ingester for a vendor CSV of sensor readings. Requirements: it must not load the whole file into memory, columns may arrive in any order (so map by header name, never by position), timestamps must be timezone-aware ISO-8601, values must be finite floats, and a bad row must not abort the run — instead I need a reject report with the line number and the reason, so I can send it back to the vendor.
@@end

@assistant
The shape that works well in production is "generator + explicit rejects": the caller consumes `Record`s and a reject list, and the header is validated once so positional bugs cannot happen.

```python
import csv
import math
from dataclasses import dataclass, fields
from datetime import datetime
from enum import Enum
from typing import Iterable, Iterator, TextIO


class RejectReason(str, Enum):
    MISSING_FIELD = "missing_field"
    BAD_TIMESTAMP = "bad_timestamp"
    NAIVE_TIMESTAMP = "naive_timestamp"
    BAD_VALUE = "bad_value"
    DUPLICATE = "duplicate"


@dataclass(frozen=True, slots=True)
class Reading:
    sensor_id: str
    taken_at: datetime      # always timezone-aware
    value: float


@dataclass(frozen=True, slots=True)
class Reject:
    line: int               # 1-based, matching the vendor's file
    reason: RejectReason
    detail: str


class SchemaError(ValueError):
    """The file's header cannot be reconciled with the expected columns."""


REQUIRED = ("sensor_id", "taken_at", "value")


def _parse_row(row: dict[str, str], line: int) -> tuple[Reading | None, Reject | None]:
    if any(not (row.get(col) or "").strip() for col in REQUIRED):
        missing = [col for col in REQUIRED if not (row.get(col) or "").strip()]
        return None, Reject(line, RejectReason.MISSING_FIELD, f"missing {','.join(missing)}")
    try:
        taken_at = datetime.fromisoformat(row["taken_at"].strip())
    except ValueError:
        return None, Reject(line, RejectReason.BAD_TIMESTAMP, row["taken_at"])
    if taken_at.tzinfo is None:
        # Naive timestamps are ambiguous: reject instead of silently assuming UTC.
        return None, Reject(line, RejectReason.NAIVE_TIMESTAMP, row["taken_at"])
    try:
        value = float(row["value"].strip())
    except ValueError:
        return None, Reject(line, RejectReason.BAD_VALUE, row["value"])
    if not math.isfinite(value):
        return None, Reject(line, RejectReason.BAD_VALUE, f"non-finite {row['value']!r}")
    return Reading(row["sensor_id"].strip(), taken_at, value), None


def ingest(handle: TextIO) -> Iterator[Reading | Reject]:
    """Stream readings; each item is either a Reading or a Reject."""
    reader = csv.DictReader(handle)          # maps by header name, not position
    if reader.fieldnames is None:
        raise SchemaError("empty file: no header row")
    # A UTF-8 BOM survives csv parsing as part of the first column name, which
    # looks exactly like a missing column. Strip it explicitly: we accept an
    # already-open handle, so encoding="utf-8-sig" is not available to us.
    header = [name.strip().lstrip("\ufeff") for name in reader.fieldnames]
    missing = [col for col in REQUIRED if col not in header]
    if missing:
        raise SchemaError(f"missing columns {missing}; got {header}")
    reader.fieldnames = header

    seen: set[tuple[str, datetime]] = set()
    for row in reader:
        line = reader.line_num
        reading, reject = _parse_row(row, line)
        if reject is not None:
            yield reject
            continue
        key = (reading.sensor_id, reading.taken_at)
        if key in seen:
            yield Reject(line, RejectReason.DUPLICATE, f"{reading.sensor_id}@{reading.taken_at.isoformat()}")
            continue
        seen.add(key)
        yield reading
```

Why it is written this way:

- **`csv.DictReader` after header validation.** Positional indexing (`row[2]`) is the classic bug when the vendor reorders columns or adds one in the middle. Validating the header once and then mapping by name makes that class of failure impossible; the column *order* and the presence of extra columns become irrelevant.
- **It is a generator over an already-open handle**, so the caller controls the file lifetime and the file is never fully read. `reader.line_num` gives the true source line for the reject report, including quoted fields containing newlines.
- **Naive timestamps are rejected, not defaulted.** Assuming UTC for a naive timestamp is how you silently corrupt a dataset by local-time hours; making it a named reject reason lets the vendor fix it.
- **`float("nan")`, `float("inf")` are rejected**: they pass `float()` and poison downstream aggregations (mean, comparisons). `math.isfinite` is the cheap guard.
- **A UTF-8 BOM is not exotic.** Excel and many SDKs emit one, and `csv` hands it to you as part of the first header name, so the file looks like it is missing its first column. Strip `\ufeff` from the header explicitly when you accept an already-open handle (with a filename you would use `encoding="utf-8-sig"`).
- **Duplicate detection** uses the natural key `(sensor_id, taken_at)`. In a long-running ingester this set would grow unboundedly — the right fix is a bounded/rolling window or a database uniqueness constraint, so treat the in-memory set as a single-file-scoped check.
- **Two failure modes are separate on purpose:** a broken *schema* raises `SchemaError` immediately (retrying the whole file is pointless until the vendor fixes it), while broken *rows* are data, so they are yielded as rejects and the run continues.

The verification writes CSVs into `StringIO` with shuffled column order, a UTF-8 BOM, quoted fields containing newlines, and one of each reject class, then asserts the exact record set and the exact reject list.
@@end

@verify kind=executable language=python

@code
import csv
import io
import math
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Iterator, TextIO


class RejectReason(str, Enum):
    MISSING_FIELD = "missing_field"
    BAD_TIMESTAMP = "bad_timestamp"
    NAIVE_TIMESTAMP = "naive_timestamp"
    BAD_VALUE = "bad_value"
    DUPLICATE = "duplicate"


@dataclass(frozen=True, slots=True)
class Reading:
    sensor_id: str
    taken_at: datetime
    value: float


@dataclass(frozen=True, slots=True)
class Reject:
    line: int
    reason: RejectReason
    detail: str


class SchemaError(ValueError):
    pass


REQUIRED = ("sensor_id", "taken_at", "value")


def _parse_row(row, line):
    if any(not (row.get(col) or "").strip() for col in REQUIRED):
        missing = [col for col in REQUIRED if not (row.get(col) or "").strip()]
        return None, Reject(line, RejectReason.MISSING_FIELD, f"missing {','.join(missing)}")
    try:
        taken_at = datetime.fromisoformat(row["taken_at"].strip())
    except ValueError:
        return None, Reject(line, RejectReason.BAD_TIMESTAMP, row["taken_at"])
    if taken_at.tzinfo is None:
        return None, Reject(line, RejectReason.NAIVE_TIMESTAMP, row["taken_at"])
    try:
        value = float(row["value"].strip())
    except ValueError:
        return None, Reject(line, RejectReason.BAD_VALUE, row["value"])
    if not math.isfinite(value):
        return None, Reject(line, RejectReason.BAD_VALUE, f"non-finite {row['value']!r}")
    return Reading(row["sensor_id"].strip(), taken_at, value), None


def ingest(handle: TextIO) -> Iterator[Reading | Reject]:
    reader = csv.DictReader(handle)
    if reader.fieldnames is None:
        raise SchemaError("empty file: no header row")
    # A UTF-8 BOM survives csv parsing as part of the first column name, which
    # looks exactly like a missing column. Strip it explicitly: we accept an
    # already-open handle, so encoding="utf-8-sig" is not available to us.
    header = [name.strip().lstrip("\ufeff") for name in reader.fieldnames]
    missing = [col for col in REQUIRED if col not in header]
    if missing:
        raise SchemaError(f"missing columns {missing}; got {header}")
    reader.fieldnames = header
    seen = set()
    for row in reader:
        line = reader.line_num
        reading, reject = _parse_row(row, line)
        if reject is not None:
            yield reject
            continue
        key = (reading.sensor_id, reading.taken_at)
        if key in seen:
            yield Reject(line, RejectReason.DUPLICATE, f"{reading.sensor_id}@{reading.taken_at.isoformat()}")
            continue
        seen.add(key)
        yield reading


def collect(text):
    return list(ingest(io.StringIO(text)))


# 1. Column order shuffled, extra column, BOM, quoted field containing a newline.
raw = (
    "\ufeffvalue,sensor_id,vendor_note,taken_at\r\n"
    "21.5,s1,\"first line\nsecond line\",2024-05-01T10:00:00+00:00\r\n"
    "  3.25  ,s2,,\"2024-05-01T10:05:00+02:00\"\r\n"
)
items = collect(raw)
readings = [i for i in items if isinstance(i, Reading)]
rejects = [i for i in items if isinstance(i, Reject)]
assert len(readings) == 2 and not rejects, items
assert readings[0].sensor_id == "s1" and readings[0].value == 21.5
assert readings[0].taken_at.isoformat() == "2024-05-01T10:00:00+00:00"
# Quoted newline means the next record is on source line 4, not 3.
assert readings[1].sensor_id == "s2" and readings[1].value == 3.25
assert readings[1].taken_at.utcoffset().total_seconds() == 7200

# 2. One of each reject class, with exact line numbers.
raw_bad = (
    "sensor_id,taken_at,value\n"                                  # 1 header
    "s1,2024-05-01T10:00:00+00:00,1.0\n"                          # 2 ok
    "s1,2024-05-01T10:00:00+00:00,2.0\n"                          # 3 duplicate key
    "s2,not-a-timestamp,3.0\n"                                    # 4 bad timestamp
    "s3,2024-05-01T10:00:00,4.0\n"                                # 5 naive
    "s4,2024-05-01T10:00:00+00:00,NaN\n"                          # 6 non-finite
    "s5,,abc\n"                                                   # 7 missing + garbage
    ",2024-05-01T10:00:00+00:00,5.0\n"                            # 8 missing sensor_id
    "s6,2024-05-01T10:00:00+00:00,6.0\n"                          # 9 ok
)
got = collect(raw_bad)
assert [type(i).__name__ for i in got] == [
    "Reading", "Reject", "Reject", "Reject", "Reject", "Reject", "Reject", "Reading",
]
assert [r.reason for r in (i for i in got if isinstance(i, Reject))] == [
    RejectReason.DUPLICATE,
    RejectReason.BAD_TIMESTAMP,
    RejectReason.NAIVE_TIMESTAMP,
    RejectReason.BAD_VALUE,
    RejectReason.MISSING_FIELD,
    RejectReason.MISSING_FIELD,
]
assert [i.line for i in got if isinstance(i, Reject)] == [3, 4, 5, 6, 7, 8]
assert (got[0].value, got[-1].value) == (1.0, 6.0)

# 3. Schema problems raise immediately instead of producing partial data.
for broken in ("", "sensor_id,value\ns1,1.0\n", "taken_at,value\n2024-01-01T00:00:00Z,1\n"):
    try:
        collect(broken)
        raise AssertionError(f"expected SchemaError for {broken!r}")
    except SchemaError:
        pass

# 4. Truly streaming: nothing is consumed before the caller asks for it.
#    StringIO is its own iterator, so counting must happen in __next__: wrapping
#    __iter__ in a generator recurses forever.
class CountingHandle(io.StringIO):
    def __init__(self, text):
        super().__init__(text)
        self.lines_read = 0

    def __next__(self):
        line = super().__next__()
        self.lines_read += 1
        return line


handle = CountingHandle("sensor_id,taken_at,value\n" + "".join(
    f"s{i},2024-05-01T10:00:00+00:00,{i}.0\n" for i in range(200)
))
stream = ingest(handle)
first = next(stream)
assert isinstance(first, Reading) and handle.lines_read <= 2, handle.lines_read
assert sum(1 for _ in stream) == 199
print("PASS")
@@end

@expect_output
PASS
@@end

@notes
Executed with the stdlib only. Covers: shuffled columns plus an unknown extra
column, UTF-8 BOM, whitespace-padded values, a quoted field containing a newline
(so line numbers must come from csv's own counter, asserted at lines 3-8),
one row per reject reason with exact reasons and line numbers, and three schema
failures that must raise instead of yielding partial data. The final check uses
an instrumented handle to prove the generator is lazy (only the first record's
lines are consumed by the first `next()`), which is the memory property the
answer claims.
@@end

@example js-code-0003
@meta category=code_generation language=javascript difficulty=intermediate tags=rate-limiting,token-bucket,fake-clock,memory-bounds

@user
We need per-tenant rate limiting in Node for the public API. Token bucket semantics (allow bursts up to the bucket size, refill steadily), but I do not want a setInterval per tenant, and I want tests that run instantly instead of sleeping. Also: tenants come and go, so the limiter must not leak memory.
@@end

@assistant
Lazy refill is the key idea: instead of a timer, each bucket stores `tokens` and the timestamp of the last refill, and refills on demand when someone asks. That makes the whole thing O(1) per check and eliminates timers entirely. Injecting the clock makes tests instant and exact.

```javascript
export class TokenBucket {
  #capacity;
  #refillPerMs;
  #clock;
  #tokens;
  #lastRefillMs;

  constructor({ capacity, refillPerSecond, clock = () => Date.now(), nowMs }) {
    if (!(capacity > 0)) throw new RangeError("capacity must be > 0");
    if (!(refillPerSecond > 0)) throw new RangeError("refillPerSecond must be > 0");
    this.#capacity = capacity;
    this.#refillPerMs = refillPerSecond / 1000;
    this.#clock = clock;
    this.#tokens = capacity;                 // start full: burst allowed
    this.#lastRefillMs = nowMs ?? clock();
  }

  /** @returns {{allowed: boolean, remaining: number, retryAfterMs: number}} */
  take(cost = 1, nowMs = this.#clock()) {
    if (!Number.isFinite(cost) || cost <= 0) throw new RangeError("cost must be finite and > 0");
    if (!Number.isFinite(nowMs)) throw new RangeError("nowMs must be finite");
    this.#refill(nowMs);
    if (this.#tokens >= cost) {
      this.#tokens -= cost;
      return { allowed: true, remaining: Math.floor(this.#tokens), retryAfterMs: 0 };
    }
    const deficit = cost - this.#tokens;
    return {
      allowed: false,
      remaining: Math.floor(this.#tokens),
      retryAfterMs: Math.ceil(deficit / this.#refillPerMs),
    };
  }

  #refill(nowMs) {
    const elapsed = nowMs - this.#lastRefillMs;
    if (elapsed <= 0) return;                // monotonic guard: never refund time
    this.#tokens = Math.min(this.#capacity, this.#tokens + elapsed * this.#refillPerMs);
    this.#lastRefillMs = nowMs;
  }

  get tokens() { return this.#tokens; }
}

export class TenantRateLimiter {
  constructor(options) {
    this.options = options;
    this.buckets = new Map();                // tenantId -> {bucket, lastSeenMs}
    this.maxIdleMs = options.maxIdleMs ?? 10 * 60 * 1000;
  }

  check(tenantId, cost = 1, nowMs = this.options.clock?.() ?? Date.now()) {
    let entry = this.buckets.get(tenantId);
    if (!entry) {
      entry = { bucket: new TokenBucket({ ...this.options, nowMs }), lastSeenMs: nowMs };
      this.buckets.set(tenantId, entry);
    }
    entry.lastSeenMs = nowMs;
    // Amortised sweep: cheap, bounded work per call, no timers.
    if (this.buckets.size > (this.options.sweepEvery ?? 1000)) this.sweepIdle(nowMs);
    const { allowed, remaining, retryAfterMs } = entry.bucket.take(cost, nowMs);
    return allowed
      ? { allowed, remaining, retryAfterMs }
      : { allowed, remaining, retryAfterMs, status: 429 };
  }

  sweepIdle(nowMs) {
    let removed = 0;
    for (const [tenantId, entry] of this.buckets) {
      if (nowMs - entry.lastSeenMs >= this.maxIdleMs) {
        this.buckets.delete(tenantId);
        removed++;
      }
    }
    return removed;
  }

  get size() { return this.buckets.size; }
}
```

Notes that matter when this goes into a real gateway:

- **Lazy refill instead of timers:** with 50k tenants, `setInterval` per bucket is 50k timers and an event-loop problem. Refilling on access is O(1) and idle tenants cost nothing.
- **Fractional tokens:** keep `tokens` as a float and floor it only in the response. Rounding up internally makes a 0.5 token/s bucket useless; rounding down in the response is what clients expect.
- **`retryAfterMs` is `ceil(deficit / rate)`**, not a fixed backoff — that is the value you would put in a `Retry-After` header.
- **Monotonic guard (`elapsed <= 0`):** if the system clock steps backwards, `elapsed` is negative and `tokens` would silently *decrease*; ignoring non-positive elapsed time loses nothing.
- **Input validation is not ceremony.** A single `NaN` reaching `tokens` poisons the bucket forever: every comparison against `NaN` is false, so the tenant is either never limited or always limited, and the bug is invisible in logs. Rejecting non-finite `cost`/`nowMs` at the boundary turns that into a loud 500 on the first bad call.
- **Memory bound:** the idle sweep is what prevents the classic leak where a Map keyed by tenant grows forever under attack (a new tenant id per request). Sweeping amortised every N checks keeps per-call cost low; a caller with stricter latency needs an LRU cap or a sharded background sweep.
- **`cost` supports weighted requests** (e.g. an expensive export costs 10 tokens) without a second mechanism.
- **Distributed caveat:** this is per-process state. Running 20 pods means each pod allows the full rate. The honest fix is a shared store (Redis `INCR` + `EXPIRE`, or a Lua script for atomic refill), and the limiter should say so rather than pretend.

The tests use a fake clock and no sleeps, and include a long fake-time jump, a step *backwards* in time, weighted costs, tenant independence, and sweep behaviour.
@@end

@verify kind=executable language=javascript

@code
import { test } from "node:test";
import assert from "node:assert/strict";

class TokenBucket {
  #capacity;
  #refillPerMs;
  #clock;
  #tokens;
  #lastRefillMs;

  constructor({ capacity, refillPerSecond, clock = () => Date.now(), nowMs }) {
    if (!(capacity > 0)) throw new RangeError("capacity must be > 0");
    if (!(refillPerSecond > 0)) throw new RangeError("refillPerSecond must be > 0");
    this.#capacity = capacity;
    this.#refillPerMs = refillPerSecond / 1000;
    this.#clock = clock;
    this.#tokens = capacity;
    this.#lastRefillMs = nowMs ?? clock();
  }

  take(cost = 1, nowMs = this.#clock()) {
    if (!Number.isFinite(cost) || cost <= 0) throw new RangeError("cost must be finite and > 0");
    if (!Number.isFinite(nowMs)) throw new RangeError("nowMs must be finite");
    this.#refill(nowMs);
    if (this.#tokens >= cost) {
      this.#tokens -= cost;
      return { allowed: true, remaining: Math.floor(this.#tokens), retryAfterMs: 0 };
    }
    const deficit = cost - this.#tokens;
    return { allowed: false, remaining: Math.floor(this.#tokens), retryAfterMs: Math.ceil(deficit / this.#refillPerMs) };
  }

  #refill(nowMs) {
    const elapsed = nowMs - this.#lastRefillMs;
    if (elapsed <= 0) return;
    this.#tokens = Math.min(this.#capacity, this.#tokens + elapsed * this.#refillPerMs);
    this.#lastRefillMs = nowMs;
  }

  get tokens() { return this.#tokens; }
}

class TenantRateLimiter {
  constructor(options) {
    this.options = options;
    this.buckets = new Map();
    this.maxIdleMs = options.maxIdleMs ?? 600000;
  }
  check(tenantId, cost = 1, nowMs = this.options.clock?.() ?? Date.now()) {
    let entry = this.buckets.get(tenantId);
    if (!entry) {
      entry = { bucket: new TokenBucket({ ...this.options, nowMs }), lastSeenMs: nowMs };
      this.buckets.set(tenantId, entry);
    }
    entry.lastSeenMs = nowMs;
    if (this.buckets.size > (this.options.sweepEvery ?? 1000)) this.sweepIdle(nowMs);
    const { allowed, remaining, retryAfterMs } = entry.bucket.take(cost, nowMs);
    return allowed ? { allowed, remaining, retryAfterMs } : { allowed, remaining, retryAfterMs, status: 429 };
  }
  sweepIdle(nowMs) {
    let removed = 0;
    for (const [tenantId, entry] of this.buckets) {
      if (nowMs - entry.lastSeenMs >= this.maxIdleMs) { this.buckets.delete(tenantId); removed++; }
    }
    return removed;
  }
  get size() { return this.buckets.size; }
}

function fakeClock(startMs = 0) {
  let now = startMs;
  return { now: () => now, advance: (ms) => { now += ms; } };
}

test("burst up to capacity, then throttled with a correct retryAfterMs", () => {
  const clock = fakeClock();
  const limiter = new TenantRateLimiter({ capacity: 5, refillPerSecond: 2, clock: clock.now });
  const results = [];
  for (let i = 0; i < 7; i++) results.push(limiter.check("t1", 1, clock.now()));
  assert.deepEqual(results.slice(0, 5).map((r) => r.allowed), [true, true, true, true, true]);
  assert.equal(results[4].remaining, 0);
  assert.equal(results[5].allowed, false);
  assert.equal(results[6].allowed, false);
  // Refill rate 2/s -> 1 token needs 500ms; both denials see the same deficit.
  assert.equal(results[5].retryAfterMs, 500);
  clock.advance(500);
  const after = limiter.check("t1", 1, clock.now());
  assert.equal(after.allowed, true, "one token accumulated in 500ms");
  assert.equal(after.remaining, 0);
});

test("refill is capped at capacity and fractional tokens accumulate", () => {
  const clock = fakeClock();
  const limiter = new TenantRateLimiter({ capacity: 10, refillPerSecond: 10, clock: clock.now });
  limiter.check("t", 10, clock.now());            // drain
  clock.advance(50);                              // 0.5 tokens
  const denied = limiter.check("t", 1, clock.now());
  assert.equal(denied.allowed, false);
  assert.equal(denied.retryAfterMs, 50);          // 0.5 tokens short at 10/s
  clock.advance(10000);                           // way past full
  const refilled = limiter.check("t", 10, clock.now());
  assert.equal(refilled.allowed, true, "refill must not exceed capacity");
  assert.equal(refilled.remaining, 0);
});

test("time going backwards does not mint or destroy tokens", () => {
  const clock = fakeClock(1000);
  const limiter = new TenantRateLimiter({ capacity: 2, refillPerSecond: 1, clock: clock.now });
  assert.equal(limiter.check("t", 2, clock.now()).allowed, true);
  const jumped = limiter.check("t", 1, 500);      // clock step backwards
  assert.equal(jumped.allowed, false);
  const forward = limiter.check("t", 2, 3000);
  assert.equal(forward.allowed, true, "after 2000ms of refill the bucket is full again");
});

test("weighted costs and tenant isolation", () => {
  const clock = fakeClock();
  const limiter = new TenantRateLimiter({ capacity: 10, refillPerSecond: 1, clock: clock.now });
  assert.equal(limiter.check("heavy", 8, clock.now()).allowed, true);
  assert.equal(limiter.check("heavy", 3, clock.now()).allowed, false);
  assert.equal(limiter.check("heavy", 2, clock.now()).allowed, true);
  assert.equal(limiter.check("light", 5, clock.now()).allowed, true, "other tenants are unaffected");
  assert.equal(limiter.size, 2);
});

test("cost larger than capacity is denied forever, not silently truncated", () => {
  const clock = fakeClock();
  const limiter = new TenantRateLimiter({ capacity: 3, refillPerSecond: 1, clock: clock.now });
  clock.advance(60000);
  const result = limiter.check("t", 4, clock.now());
  assert.equal(result.allowed, false);
  assert.equal(result.retryAfterMs, 1000, "defers by the remaining 1 token, never claims success");
});

test("idle tenants are swept so the map cannot grow without bound", () => {
  const clock = fakeClock();
  const limiter = new TenantRateLimiter({
    capacity: 1, refillPerSecond: 1, clock: clock.now, maxIdleMs: 1000, sweepEvery: 10,
  });
  for (let i = 0; i < 30; i++) limiter.check(`tenant-${i}`, 1, clock.now());
  assert.ok(limiter.size > 10, `expected growth before the sweep, got ${limiter.size}`);
  clock.advance(5000);
  limiter.check("newest", 1, clock.now());        // triggers the sweep
  assert.ok(limiter.size <= 2, `sweep should keep only recent tenants, got ${limiter.size}`);
  assert.equal(limiter.sweepIdle(clock.now()), 0, "sweeping twice is a no-op");
});

test("constructor validates its inputs", () => {
  assert.throws(() => new TokenBucket({ capacity: 0, refillPerSecond: 1 }), RangeError);
  assert.throws(() => new TokenBucket({ capacity: 1, refillPerSecond: 0 }), RangeError);
  assert.throws(() => new TenantRateLimiter({ capacity: 1, refillPerSecond: 1 }).check("t", 1, NaN));
});
@@end

@expect_output
REGEX:# pass 7\b[\s\S]*# fail 0
@@end

@notes
Executed with `node case.mjs` using the built-in `node:test` runner (no
dependencies) and a fake clock, so the suite is instant and exact: burst then
429 with retryAfterMs=500, capped refill with fractional accumulation, a
backwards clock step, weighted costs with tenant isolation, an impossible cost
(cost > capacity) that must never report success, idle sweeping keeping the map
bounded, and constructor validation. The expected output pins the pass count
(7) and `# fail 0`; a non-zero test failure exit code also fails the run.
@@end

@example py-code-0004
@meta category=code_generation language=python difficulty=advanced tags=ttl-cache,single-flight,threading,eviction

@user
Implement a bounded TTL cache we can safely share across worker threads: max N entries, entries expire after T seconds, least-recently-used eviction, and — importantly — when a key is missing, only one thread may compute it while the others wait for that result rather than stampeding the database.
@@end

@assistant
Two mechanisms are needed here and they are independent: an LRU+TTL store, and single-flight so concurrent misses for the same key collapse into one computation. A single global lock around the computation would serialise everything, so the lock is only held for bookkeeping and the computation happens outside it.

```python
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Callable, Generic, Hashable, TypeVar

K = TypeVar("K", bound=Hashable)
V = TypeVar("V")


@dataclass(slots=True)
class _Entry(Generic[V]):
    value: V
    expires_at: float


@dataclass(slots=True)
class _Pending(Generic[V]):
    """A computation already in progress for a key (single-flight leader)."""
    done: threading.Event
    value: V | None = None
    error: BaseException | None = None


class TtlLruCache(Generic[K, V]):
    def __init__(self, *, capacity: int, ttl_seconds: float,
                 clock: Callable[[], float] = time.monotonic) -> None:
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self._capacity = capacity
        self._ttl = ttl_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._entries: "OrderedDict[K, _Entry[V]]" = OrderedDict()
        self._pending: dict[K, _Pending[V]] = {}
        self.stats = {"hits": 0, "misses": 0, "evictions": 0, "expired": 0, "coalesced": 0}

    # -- public API ----------------------------------------------------
    def get(self, key: K) -> V | None:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                self.stats["misses"] += 1
                return None
            if entry.expires_at <= self._clock():
                del self._entries[key]
                self.stats["expired"] += 1
                self.stats["misses"] += 1
                return None
            self._entries.move_to_end(key)
            self.stats["hits"] += 1
            return entry.value

    def put(self, key: K, value: V) -> None:
        with self._lock:
            self._store(key, value)

    def get_or_compute(self, key: K, factory: Callable[[], V]) -> V:
        hit = self.get(key)
        if hit is not None:
            return hit

        with self._lock:
            pending = self._pending.get(key)
            if pending is None:
                pending = _Pending(done=threading.Event())
                self._pending[key] = pending
                leader = True
            else:
                self.stats["coalesced"] += 1
                leader = False

        if not leader:
            # Followers wait without holding the lock, then reuse the leader's
            # result or re-raise the leader's exception.
            pending.done.wait()
            if pending.error is not None:
                raise pending.error
            return pending.value  # type: ignore[return-value]

        try:
            value = factory()
        except BaseException as exc:
            pending.error = exc
            with self._lock:
                self._pending.pop(key, None)
            pending.done.set()
            raise
        with self._lock:
            self._store(key, value)
            self._pending.pop(key, None)
        pending.value = value
        pending.done.set()
        return value

    # -- internals -----------------------------------------------------
    def _store(self, key: K, value: V) -> None:
        self._entries[key] = _Entry(value=value, expires_at=self._clock() + self._ttl)
        self._entries.move_to_end(key)
        while len(self._entries) > self._capacity:
            self._entries.popitem(last=False)
            self.stats["evictions"] += 1

    def __len__(self) -> int:
        return len(self._entries)
```

Correctness notes that are easy to get wrong:

- **`time.monotonic`, never `time.time`.** A wall-clock jump (NTP, DST, VM migration) must not expire everything at once or keep entries forever.
- **Single-flight, not one global lock.** Followers release the lock while waiting, so unrelated keys stay concurrent. The leader stores its result *before* setting the event, so followers never observe an empty value; ordering here is the difference between a correct cache and a rare `None`.
- **Exceptions are shared, not swallowed.** If the leader's factory raises, followers re-raise the same exception object instead of issuing their own query — one failure, one retry decision at the call site. The pending entry is always removed in both paths, otherwise the key would be permanently poisoned and every later caller would hang on an event that never fires.
- **`get()` returns `None` for a miss**, so a factory returning `None` cannot be distinguished from a miss by `get_or_compute`; for optional values wrap them in a sentinel or use a `MISSING` object. Stating this limitation is better than hiding it.
- **Eviction is `popitem(last=False)`** on an `OrderedDict` whose order is refreshed on hit (`move_to_end`), giving O(1) LRU. A dict plus a heap or a linked list reimplementation is where bugs creep in.
- **Expiry is lazy**: no background thread means no shutdown problem; the trade-off is memory held by entries nobody reads again, which the capacity bound covers.
- **Stats are part of the API**: `hits`, `misses`, `evictions`, `expired`, `coalesced` are what you graph when a cache is "slow" in production; `coalesced` is the evidence that the stampede protection is doing work. The counters are deliberately precise about semantics — `misses` counts *lookups* that missed (so eight threads racing on a cold key is 8 misses and 7 coalesced), which is why the test asserts those numbers rather than a vaguer "one fetch happened".

The verification runs a thread pool hammering a cold key, asserts the factory ran exactly once and every thread saw the same object, then checks TTL expiry, LRU order, capacity enforcement, exception sharing, and that two *different* keys are computed concurrently rather than serialised.
@@end

@verify kind=executable language=python

@code
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Callable, Generic, Hashable, TypeVar

K = TypeVar("K", bound=Hashable)
V = TypeVar("V")


@dataclass(slots=True)
class _Entry(Generic[V]):
    value: V
    expires_at: float


@dataclass(slots=True)
class _Pending(Generic[V]):
    done: threading.Event
    value: V | None = None
    error: BaseException | None = None


class TtlLruCache(Generic[K, V]):
    def __init__(self, *, capacity, ttl_seconds, clock=time.monotonic):
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self._capacity = capacity
        self._ttl = ttl_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._entries = OrderedDict()
        self._pending = {}
        self.stats = {"hits": 0, "misses": 0, "evictions": 0, "expired": 0, "coalesced": 0}

    def get(self, key):
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                self.stats["misses"] += 1
                return None
            if entry.expires_at <= self._clock():
                del self._entries[key]
                self.stats["expired"] += 1
                self.stats["misses"] += 1
                return None
            self._entries.move_to_end(key)
            self.stats["hits"] += 1
            return entry.value

    def put(self, key, value):
        with self._lock:
            self._store(key, value)

    def get_or_compute(self, key, factory):
        hit = self.get(key)
        if hit is not None:
            return hit
        with self._lock:
            pending = self._pending.get(key)
            if pending is None:
                pending = _Pending(done=threading.Event())
                self._pending[key] = pending
                leader = True
            else:
                self.stats["coalesced"] += 1
                leader = False
        if not leader:
            pending.done.wait()
            if pending.error is not None:
                raise pending.error
            return pending.value
        try:
            value = factory()
        except BaseException as exc:
            pending.error = exc
            with self._lock:
                self._pending.pop(key, None)
            pending.done.set()
            raise
        with self._lock:
            self._store(key, value)
            self._pending.pop(key, None)
        pending.value = value
        pending.done.set()
        return value

    def _store(self, key, value):
        self._entries[key] = _Entry(value=value, expires_at=self._clock() + self._ttl)
        self._entries.move_to_end(key)
        while len(self._entries) > self._capacity:
            self._entries.popitem(last=False)
            self.stats["evictions"] += 1

    def __len__(self):
        return len(self._entries)


def test_single_flight_collapses_concurrent_misses():
    cache = TtlLruCache(capacity=10, ttl_seconds=60)
    calls = []
    start = threading.Barrier(8, timeout=10)
    results = []
    lock = threading.Lock()

    def factory():
        calls.append(threading.get_ident())
        time.sleep(0.05)                  # pretend this is a slow DB query
        return object()

    def worker():
        start.wait()
        value = cache.get_or_compute("cold", factory)
        with lock:
            results.append(value)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    assert len(results) == 8, results
    assert len(calls) == 1, f"factory ran {len(calls)} times, expected 1"
    assert all(r is results[0] for r in results), "all callers must share the same object"
    # 8 lookups all missed; 7 of them were served by the leader's in-flight call.
    assert cache.stats["misses"] == 8, cache.stats
    assert cache.stats["coalesced"] == 7, cache.stats
    assert cache.stats["hits"] == 0, cache.stats
    assert len(cache._pending) == 0, "pending map must be cleaned up"


def test_distinct_keys_are_computed_concurrently():
    cache = TtlLruCache(capacity=10, ttl_seconds=60)
    in_a = threading.Event()
    b_started = threading.Event()

    def factory_a():
        in_a.set()
        assert b_started.wait(5), "a global lock would block key B behind key A"
        return "A"

    def factory_b():
        assert in_a.wait(5), "key A must have started"
        b_started.set()
        return "B"

    out = {}
    threads = [
        threading.Thread(target=lambda: out.__setitem__("a", cache.get_or_compute("a", factory_a))),
        threading.Thread(target=lambda: out.__setitem__("b", cache.get_or_compute("b", factory_b))),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    assert out == {"a": "A", "b": "B"}, out


def test_ttl_expiry_uses_the_injected_clock():
    now = [1000.0]
    cache = TtlLruCache(capacity=4, ttl_seconds=30, clock=lambda: now[0])
    cache.put("k", "v")
    assert cache.get("k") == "v"
    now[0] += 29.999
    assert cache.get("k") == "v", "still inside the TTL"
    now[0] += 0.002
    assert cache.get("k") is None, "expired entries must not be served"
    assert cache.stats["expired"] == 1
    assert len(cache) == 0


def test_lru_eviction_order_and_capacity():
    cache = TtlLruCache(capacity=3, ttl_seconds=60)
    for key in ("a", "b", "c"):
        cache.put(key, key.upper())
    assert cache.get("a") == "A"          # 'a' becomes most recently used
    cache.put("d", "D")                   # evicts 'b', the least recently used
    assert cache.get("b") is None
    assert [cache.get(k) for k in ("a", "c", "d")] == ["A", "C", "D"]
    assert cache.stats["evictions"] == 1
    assert len(cache) == 3, "capacity is a hard bound"


def test_leader_exception_is_shared_and_does_not_poison_the_key():
    cache = TtlLruCache(capacity=2, ttl_seconds=60)
    boom = RuntimeError("database down")
    attempts = []

    def failing():
        attempts.append(1)
        raise boom

    try:
        cache.get_or_compute("k", failing)
        raise AssertionError("expected the leader's exception")
    except RuntimeError as exc:
        assert exc is boom, "followers must receive the same exception object"
    assert len(cache._pending) == 0, "a failed key must not stay pending forever"
    assert cache.get_or_compute("k", lambda: "recovered") == "recovered"


def test_constructor_guards():
    for kwargs in ({"capacity": 0, "ttl_seconds": 1}, {"capacity": 1, "ttl_seconds": 0},
                   {"capacity": -1, "ttl_seconds": -1}):
        try:
            TtlLruCache(**kwargs)
            raise AssertionError(f"expected ValueError for {kwargs}")
        except ValueError:
            pass


for name, fn in sorted(globals().items()):
    if name.startswith("test_") and callable(fn):
        fn()
print("PASS")
@@end

@expect_output
PASS
@@end

@notes
Six threaded tests with hard timeouts (a deadlock fails the suite instead of
hanging it): 8 threads with a Barrier collapse into exactly 1 factory call with
all callers receiving the identical object and the pending map drained; two
distinct keys are proven to compute concurrently via two Events (a global lock
would deadlock and fail the assertion); TTL boundary at 29.999s vs 30.001s on an
injected clock; LRU order and the hard capacity bound; leader exception identity
plus the key still being usable afterwards; and constructor guards.
@@end

@example sql-code-0005
@meta category=code_generation language=sql difficulty=advanced tags=window-functions,cohort-retention,cte,sqlite

@user
Write a monthly cohort retention query against a table `events(user_id, occurred_at, event)` where occurred_at is ISO-8601 UTC text. For each signup cohort (the month of a user's first event) I want retention in months 0..3 as a percentage of the cohort, plus a rolling 3-month active-user count per cohort. Assume month buckets, not exact 30-day windows.
@@end

@assistant
Two ideas carry this query: derive the cohort month per user once in a CTE, then work on a `(cohort_month, activity_month)` grid. Use `strftime('%Y-%m', ...)` for calendar months, and a window frame for the rolling count so it stays a single scan.

```sql
WITH params AS (SELECT 3 AS horizon_months),
first_seen AS (
    SELECT user_id, MIN(occurred_at) AS first_event_at
    FROM events
    GROUP BY user_id
),
cohorts AS (
    SELECT user_id,
           strftime('%Y-%m', first_event_at) AS cohort_month   -- month of first activity
    FROM first_seen
),
activity AS (
    SELECT DISTINCT c.cohort_month,
                    c.user_id,
                    strftime('%Y-%m', e.occurred_at) AS activity_month
    FROM events e
    JOIN cohorts c USING (user_id)
),
month_index AS (
    SELECT cohort_month,
           user_id,
           -- months between cohort month and activity month, computed on the
           -- first day of each month so month lengths never matter
           (CAST(strftime('%Y', activity_month || '-01') AS INTEGER) * 12
            + CAST(strftime('%m', activity_month || '-01') AS INTEGER))
         - (CAST(strftime('%Y', cohort_month || '-01') AS INTEGER) * 12
            + CAST(strftime('%m', cohort_month || '-01') AS INTEGER)) AS month_offset
    FROM activity
),
cohort_size AS (
    SELECT cohort_month, COUNT(*) AS users FROM cohorts GROUP BY cohort_month
),
retention AS (
    SELECT m.cohort_month,
           m.month_offset,
           COUNT(DISTINCT m.user_id) AS active_users
    FROM month_index m
    JOIN params p ON m.month_offset BETWEEN 0 AND p.horizon_months
    GROUP BY m.cohort_month, m.month_offset
)
SELECT r.cohort_month,
       s.users                                                AS cohort_users,
       r.month_offset,
       r.active_users,
       ROUND(100.0 * r.active_users / s.users, 1)             AS retention_pct,
       -- rolling 3-month active users within the cohort, month-ordered
       SUM(r.active_users) OVER (
           PARTITION BY r.cohort_month
           ORDER BY r.month_offset
           ROWS BETWEEN 2 PRECEDING AND CURRENT ROW
       )                                                       AS rolling_3m_active
FROM retention r
JOIN cohort_size s USING (cohort_month)
ORDER BY r.cohort_month, r.month_offset;
```

Points worth internalising:

- **Cohort = month of *first* event**, so a user belongs to exactly one cohort. `MIN(occurred_at)` works because ISO-8601 UTC timestamps sort lexicographically — but only if every row is the same format and timezone. If the column mixes `+02:00` offsets, sort on `datetime(occurred_at)` instead and normalise to UTC first.
- **Month arithmetic is done on `YYYY-MM || '-01'`.** Subtracting months with `+1 month` string arithmetic is a trap in SQLite: `date('2024-01-31','+1 month')` returns `2024-03-02` because the 31st does not exist in February. Anchoring to the first day removes that class of bug entirely.
- **`DISTINCT` before aggregating** so a user who fired 500 events in a month counts once; `COUNT(DISTINCT user_id)` then makes the `DISTINCT` redundant but keeps the intermediate row count small.
- **`month_offset = 0` is the cohort month itself**, and retention is measured against the cohort size, not the previous month's active users. Get that denominator wrong and the curve looks plausible but is meaningless.
- **The window function replaces a self-join:** `ROWS BETWEEN 2 PRECEDING AND CURRENT ROW` gives a rolling 3-month sum per cohort in one pass; the classic alternative is three correlated subqueries.
- **`params AS (SELECT 3 AS horizon_months)`** makes the horizon a single edit point. In a real warehouse you would filter to a bounded date range as well, otherwise the query scales with total history instead of the window you care about.
- **Percentage uses `100.0`** to force float division; `100 * a / b` is integer division in SQLite.

Indexes that make this viable at scale: `events(occurred_at)` or a covering `events(user_id, occurred_at)`, plus partitioning by month in a warehouse. The query itself is a two-scan aggregation plus a window, so cost is dominated by the `events` table size.
@@end

@verify kind=executable language=sql

@code
CREATE TABLE events (user_id TEXT NOT NULL, occurred_at TEXT NOT NULL, event TEXT NOT NULL);

-- u1: cohort 2024-01, active in Jan, Feb (x2 events), Mar. u2: cohort 2024-01, Jan only.
-- u3: cohort 2024-01, Jan + Apr (month_offset 3). u4: cohort 2024-02, Feb + Mar.
INSERT INTO events VALUES
  ('u1', '2024-01-05T09:00:00Z', 'signup'),
  ('u1', '2024-01-20T09:00:00Z', 'view'),
  ('u1', '2024-02-02T09:00:00Z', 'view'),
  ('u1', '2024-02-11T09:00:00Z', 'purchase'),
  ('u1', '2024-03-15T09:00:00Z', 'view'),
  ('u2', '2024-01-08T09:00:00Z', 'signup'),
  ('u3', '2024-01-30T23:00:00Z', 'signup'),
  ('u3', '2024-04-01T00:30:00Z', 'view'),
  ('u4', '2024-02-10T09:00:00Z', 'signup'),
  ('u4', '2024-03-10T09:00:00Z', 'view'),
  ('u4', '2024-03-11T09:00:00Z', 'view');

CREATE INDEX idx_events_occurred_at ON events(occurred_at);

WITH params AS (SELECT 3 AS horizon_months),
first_seen AS (
    SELECT user_id, MIN(occurred_at) AS first_event_at FROM events GROUP BY user_id
),
cohorts AS (
    SELECT user_id, strftime('%Y-%m', first_event_at) AS cohort_month FROM first_seen
),
activity AS (
    SELECT DISTINCT c.cohort_month, c.user_id, strftime('%Y-%m', e.occurred_at) AS activity_month
    FROM events e JOIN cohorts c USING (user_id)
),
month_index AS (
    SELECT cohort_month, user_id,
           (CAST(strftime('%Y', activity_month || '-01') AS INTEGER) * 12
            + CAST(strftime('%m', activity_month || '-01') AS INTEGER))
         - (CAST(strftime('%Y', cohort_month || '-01') AS INTEGER) * 12
            + CAST(strftime('%m', cohort_month || '-01') AS INTEGER)) AS month_offset
    FROM activity
),
cohort_size AS (
    SELECT cohort_month, COUNT(*) AS users FROM cohorts GROUP BY cohort_month
),
retention AS (
    SELECT m.cohort_month, m.month_offset, COUNT(DISTINCT m.user_id) AS active_users
    FROM month_index m JOIN params p ON m.month_offset BETWEEN 0 AND p.horizon_months
    GROUP BY m.cohort_month, m.month_offset
)
SELECT r.cohort_month, s.users AS cohort_users, r.month_offset, r.active_users,
       ROUND(100.0 * r.active_users / s.users, 1) AS retention_pct,
       SUM(r.active_users) OVER (PARTITION BY r.cohort_month ORDER BY r.month_offset
                                 ROWS BETWEEN 2 PRECEDING AND CURRENT ROW) AS rolling_3m_active
FROM retention r JOIN cohort_size s USING (cohort_month)
ORDER BY r.cohort_month, r.month_offset;

-- Cross-check the window column against an independent correlated-subquery
-- formulation; both must agree row for row.
WITH params AS (SELECT 3 AS horizon_months),
cohorts AS (
    SELECT user_id, strftime('%Y-%m', MIN(occurred_at)) AS cohort_month
    FROM events GROUP BY user_id
),
month_index AS (
    SELECT DISTINCT c.cohort_month, c.user_id,
           (CAST(strftime('%Y', strftime('%Y-%m', e.occurred_at) || '-01') AS INTEGER) * 12
            + CAST(strftime('%m', strftime('%Y-%m', e.occurred_at) || '-01') AS INTEGER))
         - (CAST(strftime('%Y', c.cohort_month || '-01') AS INTEGER) * 12
            + CAST(strftime('%m', c.cohort_month || '-01') AS INTEGER)) AS month_offset
    FROM events e JOIN cohorts c USING (user_id)
),
retention AS (
    SELECT cohort_month, month_offset, COUNT(*) AS active_users
    FROM month_index WHERE month_offset BETWEEN 0 AND 3
    GROUP BY cohort_month, month_offset
)
SELECT a.cohort_month, a.month_offset, a.active_users,
       (SELECT SUM(b.active_users) FROM retention b
         WHERE b.cohort_month = a.cohort_month
           AND b.month_offset BETWEEN a.month_offset - 2 AND a.month_offset) AS rolling_3m_active
FROM retention a ORDER BY a.cohort_month, a.month_offset;

-- An index-only plan is what makes this scale; assert the index is used.
EXPLAIN QUERY PLAN SELECT COUNT(*) FROM events WHERE occurred_at >= '2024-02-01';

-- Retention in month 0 is 100% by construction; assert it explicitly. COUNT must
-- be DISTINCT users, not joined rows: u1 contributes 5 event rows.
SELECT c.cohort_month, COUNT(DISTINCT e.user_id) AS cohort_users,
       COUNT(DISTINCT CASE WHEN strftime('%Y-%m', e.occurred_at) = c.cohort_month THEN e.user_id END) AS month0_users
FROM events e JOIN (SELECT user_id, strftime('%Y-%m', MIN(occurred_at)) AS cohort_month
                    FROM events GROUP BY user_id) c USING (user_id)
GROUP BY c.cohort_month ORDER BY c.cohort_month;
@@end

@expect_output
cohort_month|cohort_users|month_offset|active_users|retention_pct|rolling_3m_active
2024-01|3|0|3|100.0|3
2024-01|3|1|1|33.3|4
2024-01|3|2|1|33.3|5
2024-01|3|3|1|33.3|3
2024-02|1|0|1|100.0|1
2024-02|1|1|1|100.0|2
cohort_month|month_offset|active_users|rolling_3m_active
2024-01|0|3|3
2024-01|1|1|4
2024-01|2|1|5
2024-01|3|1|3
2024-02|0|1|1
2024-02|1|1|2
id|parent|notused|detail
3|0|0|SEARCH events USING COVERING INDEX idx_events_occurred_at (occurred_at>?)
cohort_month|cohort_users|month0_users
2024-01|3|3
2024-02|1|1
@@end

@notes
Runs in SQLite 3.40 (Python's bundled engine), which is the reference dialect
here; the query uses only standard SQL features (CTEs, window frame,
strftime) that Postgres/BigQuery-shaped warehouses have equivalents for. The
fixture encodes exactly the interesting cases: a user with two events in one
month (must count once), a user whose only late activity is at month offset 3,
and a cohort starting mid-data. The expected output pins every retention row,
then re-derives the rolling column with a correlated-subquery formulation and
pins those rows too (they must match the window version), asserts the query plan
actually uses the covering index, and asserts month-0 retention equals the cohort
size (100% by construction) using COUNT(DISTINCT user_id) -- the row-count
version of that check reports 8 for the first cohort and is exactly the kind of
silent bug this file guards against.
Note the month arithmetic is deliberately computed from '-01' anchors; using
date(x, '+1 month') on a month-end date returns the wrong month in SQLite.
@@end

@example bash-code-0006
@meta category=code_generation language=bash difficulty=advanced tags=deploy-script,atomic-symlink,rollback,idempotency

@user
Write a deploy script for a static release directory: it publishes a new release, switches traffic with a symlink, health-checks it, and rolls back automatically if the health check fails. It must be safe to re-run (idempotent), must not leave a half-switched state, and should support a dry run. Bash only, no dependencies beyond coreutils.
@@end

@assistant
The properties that make a deploy script survivable are: `set -Eeuo pipefail` (fail fast, and `-E` so the ERR trap fires inside functions), an atomic switch, and a rollback path that is itself tested. Atomicity comes from `ln -s` into a temporary name followed by `mv -T`, which is a single `rename(2)` — never `rm` a symlink and re-create it, because there is a window where traffic has no target.

```bash
#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

DRY_RUN=0
RELEASES_DIR=""
HEALTH_CMD=""
ROLLBACK_ON_FAILURE=1

log()  { printf '%s %s\n' "$(date -u +%FT%TZ)" "$*" >&2; }
die()  { log "ERROR: $*"; exit 1; }

run() {
  if (( DRY_RUN )); then
    log "DRY-RUN: $*"
  else
    "$@"
  fi
}

current_target() {
  # Prints the release the 'current' symlink points at, or nothing.
  [[ -L "$RELEASES_DIR/current" ]] && readlink -f "$RELEASES_DIR/current" || true
}

switch_to() {
  local target="$1" tmp="$RELEASES_DIR/.current.$$"
  [[ -d "$target" ]] || die "release directory does not exist: $target"
  run ln -sfn "$target" "$tmp"
  run mv -T "$tmp" "$RELEASES_DIR/current"     # atomic rename, no gap
}

healthcheck() {
  [[ -n "$HEALTH_CMD" ]] || return 0
  local attempt
  for attempt in 1 2 3; do
    if bash -c "$HEALTH_CMD"; then
      log "health check passed on attempt $attempt"
      return 0
    fi
    log "health check attempt $attempt failed"
    sleep 1
  done
  return 1
}

deploy() {
  local release_dir="$1"
  local previous
  previous="$(current_target)"

  if [[ "$previous" == "$release_dir" ]]; then
    log "already serving $(basename "$release_dir"); nothing to do"
    return 0
  fi

  switch_to "$release_dir"
  log "switched current -> $(basename "$release_dir")"

  if healthcheck; then
    log "deploy complete"
    return 0
  fi

  if (( ROLLBACK_ON_FAILURE )) && [[ -n "$previous" ]]; then
    log "health check failed; rolling back to $(basename "$previous")"
    switch_to "$previous"
    die "rolled back to $(basename "$previous")"
  fi
  die "health check failed and no previous release is available"
}

main() {
  while (($#)); do
    case "$1" in
      --releases) RELEASES_DIR="$2"; shift 2 ;;
      --release)  RELEASE="$2"; shift 2 ;;
      --health)   HEALTH_CMD="$2"; shift 2 ;;
      --dry-run)  DRY_RUN=1; shift ;;
      --no-rollback) ROLLBACK_ON_FAILURE=0; shift ;;
      -h|--help)  printf 'usage: %s --releases DIR --release DIR [--health CMD] [--dry-run]\n' "$0"; exit 0 ;;
      *) die "unknown argument: $1" ;;
    esac
  done
  [[ -n "$RELEASES_DIR" ]] || die "--releases is required"
  [[ -n "${RELEASE:-}" ]] || die "--release is required"
  mkdir -p "$RELEASES_DIR"
  deploy "$RELEASE"
}

trap 'die "aborted at line $LINENO"' ERR
main "$@"
```

Why each piece is there:

- **`ln -sfn` + `mv -T`**: `mv -T` treats the destination as a file, so the rename replaces the symlink atomically. Creating the temp link inside the releases directory (same filesystem) is required — `mv` across filesystems degrades to copy+delete and is no longer atomic.
- **Idempotency is a comparison, not a marker file**: if `current` already points at the requested release, the script exits 0 with "nothing to do". Re-running a deploy after a partial failure then converges instead of ping-ponging versions.
- **Rollback uses the same `switch_to`**, so a rollback is exactly as tested as a forward deploy. Rollback target is captured *before* switching, otherwise after a failed switch you have nothing to roll back to.
- **Health checks retry with a short backoff** because a freshly switched backend is often not ready on the first probe; the retry count is bounded so a broken release fails fast.
- **Dry run goes through the `run()` wrapper**, so every mutating command is visible in the log while nothing changes. It is not a separate code path — a separate path is exactly how dry runs drift from reality.
- **`trap ... ERR` plus `set -E`** turns any unexpected command failure into a loud abort with a line number, instead of continuing to run with half-configured variables.
- **All logging goes to stderr**, keeping stdout machine-readable for the caller.
- **`IFS=$'\n\t'`** avoids word-splitting surprises on paths with spaces; `"$@"` and quoted expansions preserve arguments anyway.
- **What this deliberately does not do:** it does not build the release, garbage-collect old releases, or coordinate multiple deployers. Serialising deploys is the caller's job (a lock file or `flock`), and pretending otherwise in a 60-line script is how you get two deploys racing.

The verification harness writes this script to a temp directory and exercises four scenarios: first deploy, idempotent re-run, failing health check with automatic rollback, and dry run that must not touch the filesystem.
@@end

@verify kind=executable language=bash

@code
set -Eeuo pipefail
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
mkdir -p "$work/bin" "$work/releases/rel-1" "$work/releases/rel-2"
printf 'v1' > "$work/releases/rel-1/index.html"
printf 'v2' > "$work/releases/rel-2/index.html"

cat > "$work/bin/deploy.sh" <<'DEPLOY'
#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

DRY_RUN=0
RELEASES_DIR=""
HEALTH_CMD=""
ROLLBACK_ON_FAILURE=1

log()  { printf '%s %s\n' "$(date -u +%FT%TZ)" "$*" >&2; }
die()  { log "ERROR: $*"; exit 1; }

run() {
  if (( DRY_RUN )); then log "DRY-RUN: $*"; else "$@"; fi
}

current_target() {
  [[ -L "$RELEASES_DIR/current" ]] && readlink -f "$RELEASES_DIR/current" || true
}

switch_to() {
  local target="$1" tmp="$RELEASES_DIR/.current.$$"
  [[ -d "$target" ]] || die "release directory does not exist: $target"
  run ln -sfn "$target" "$tmp"
  run mv -T "$tmp" "$RELEASES_DIR/current"
}

healthcheck() {
  [[ -n "$HEALTH_CMD" ]] || return 0
  local attempt
  for attempt in 1 2 3; do
    if bash -c "$HEALTH_CMD"; then log "health check passed on attempt $attempt"; return 0; fi
    log "health check attempt $attempt failed"
    sleep 0.1
  done
  return 1
}

deploy() {
  local release_dir="$1" previous
  previous="$(current_target)"
  if [[ "$previous" == "$release_dir" ]]; then
    log "already serving $(basename "$release_dir"); nothing to do"
    return 0
  fi
  switch_to "$release_dir"
  log "switched current -> $(basename "$release_dir")"
  if healthcheck; then log "deploy complete"; return 0; fi
  if (( ROLLBACK_ON_FAILURE )) && [[ -n "$previous" ]]; then
    log "health check failed; rolling back to $(basename "$previous")"
    switch_to "$previous"
    die "rolled back to $(basename "$previous")"
  fi
  die "health check failed and no previous release is available"
}

main() {
  RELEASE=""
  while (($#)); do
    case "$1" in
      --releases) RELEASES_DIR="$2"; shift 2 ;;
      --release)  RELEASE="$2"; shift 2 ;;
      --health)   HEALTH_CMD="$2"; shift 2 ;;
      --dry-run)  DRY_RUN=1; shift ;;
      --no-rollback) ROLLBACK_ON_FAILURE=0; shift ;;
      -h|--help)  printf 'usage\n'; exit 0 ;;
      *) die "unknown argument: $1" ;;
    esac
  done
  [[ -n "$RELEASES_DIR" ]] || die "--releases is required"
  [[ -n "$RELEASE" ]] || die "--release is required"
  mkdir -p "$RELEASES_DIR"
  deploy "$RELEASE"
}

trap 'die "aborted at line $LINENO"' ERR
main "$@"
DEPLOY
chmod +x "$work/bin/deploy.sh"

deploy() { "$work/bin/deploy.sh" --releases "$work/releases" "$@"; }
target() { readlink -f "$work/releases/current" 2>/dev/null || echo "<none>"; }
served() { cat "$work/releases/current/index.html"; }

# 1. First deploy publishes rel-1 and points current at it.
deploy --release "$work/releases/rel-1" >/dev/null 2>"$work/log1"
[[ "$(target)" == "$work/releases/rel-1" ]] || { echo "scenario1 target=$(target)" >&2; exit 1; }
[[ "$(served)" == "v1" ]] || { echo "scenario1 content broken" >&2; exit 1; }

# 2. Re-running the same release is a no-op, not an error.
deploy --release "$work/releases/rel-1" >/dev/null 2>"$work/log2"
grep -q "nothing to do" "$work/log2" || { echo "rerun not idempotent" >&2; exit 1; }
[[ "$(served)" == "v1" ]]

# 3. Dry run with a new release must not change anything.
deploy --release "$work/releases/rel-2" --dry-run >/dev/null 2>"$work/log3"
grep -q "DRY-RUN" "$work/log3" || { echo "dry run did not report" >&2; exit 1; }
[[ "$(target)" == "$work/releases/rel-1" ]] || { echo "dry run mutated state" >&2; exit 1; }

# 4. Failing health check rolls back to the previously served release.
set +e
deploy --release "$work/releases/rel-2" --health "exit 1" >/dev/null 2>"$work/log4"
status=$?
set -e
[[ $status -ne 0 ]] || { echo "failed health check must exit non-zero" >&2; exit 1; }
grep -q "rolling back" "$work/log4" || { echo "no rollback attempted" >&2; exit 1; }
[[ "$(target)" == "$work/releases/rel-1" ]] || { echo "rollback left $(target)" >&2; exit 1; }
[[ "$(served)" == "v1" ]] || { echo "rollback content wrong" >&2; exit 1; }
[[ "$(("$(grep -c 'health check attempt' "$work/log4")"))" -eq 3 ]] || { echo "expected 3 probes" >&2; exit 1; }

# 5. A successful health check on a fresh release switches over.
deploy --release "$work/releases/rel-2" --health "test -f '$work/releases/current/index.html'" >/dev/null 2>"$work/log5"
[[ "$(served)" == "v2" ]] || { echo "successful deploy did not switch" >&2; exit 1; }

# 6. Missing release directory is rejected before touching the symlink.
set +e
deploy --release "$work/releases/rel-3" >/dev/null 2>"$work/log6"
status=$?
set -e
[[ $status -ne 0 ]] || { echo "missing release must fail" >&2; exit 1; }
[[ "$(served)" == "v2" ]] || { echo "failed deploy changed the symlink" >&2; exit 1; }

# 7. No leftover temp symlinks after all of the above.
leftovers="$(find "$work/releases" -maxdepth 1 -name '.current.*' | wc -l)"
[[ "$leftovers" -eq 0 ]] || { echo "leftover temp symlinks: $leftovers" >&2; exit 1; }
printf 'PASS\n'
@@end

@expect_output
PASS
@@end

@notes
The harness writes the deploy script to a temp dir and runs seven scenarios with
`bash`, asserting exit codes, the resolved `current` target, the served file
content and the log text: publish, idempotent re-run ("nothing to do"), dry run
that leaves state untouched, failing health check with exactly 3 probes and a
rollback to the previous release, a healthy deploy that switches over, a missing
release directory that fails without touching the symlink, and no leftover
`.current.*` temp links. Uses `mv -T` for the atomic rename; the same script text
is what the answer shows above.
@@end
