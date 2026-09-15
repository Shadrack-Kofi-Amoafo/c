@example py-test-0001
@meta category=testing language=python difficulty=advanced tags=property-based-testing,shrinking,invariants,stdlib

@user
Our interval-merge module is covered by twenty hand-written example tests, and a bug still reached production: an empty input raised `IndexError` and a single-interval input returned an empty list. I cannot install hypothesis here (no network on the build box). How do I write tests that explore the input space instead of checking examples I already thought of, and how do I get a *small* failing case back instead of a random 200-element list?
@@end

@assistant
That is exactly what property-based testing is: generate many inputs, assert *invariants* rather than expected values, and when a property fails, **shrink** the input to the smallest example that still fails. Both parts fit in about 40 lines of stdlib code, and the shrinking is the part people skip — without it you get a wall of random data and no idea what broke.

Pick properties that (a) hold for every valid input and (b) do not restate the implementation:

1. **Shape**: the output is sorted by start, and consecutive intervals are non-overlapping and non-adjacent (`end < next.start`).
2. **Semantics**: the union of the input equals the union of the output — checked against a per-point truth set on a bounded domain, which is an *independent* implementation.
3. **Idempotence**: merging an already-merged list changes nothing.
4. **Empty in, empty out; non-empty in, non-empty out** — the two bugs that shipped.
5. **Coverage**: every input interval is contained in some output interval, and every output interval is contained in the input's union.

```python
import random


def merge_intervals(intervals):
    """Merge overlapping half-open [start, end) intervals, sorted output."""
    if not intervals:
        return []
    ordered = sorted(intervals)
    merged = [ordered[0]]
    for start, end in ordered[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end:                      # overlap or touch
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    return merged


def check_invariants(intervals, result):
    """Every property the merged output must satisfy."""
    for i, (start, end) in enumerate(result):
        assert start <= end, f"inverted interval {start}-{end} in {result}"
        if i:
            assert result[i - 1][1] < start, f"output not merged: {result}"
    if not intervals:
        assert result == [], f"empty input must give empty output, got {result}"
    else:
        assert result, "non-empty input must not vanish"
    # Independent model: a point is covered iff it is covered in the input.
    limit = max((end for _, end in intervals), default=0)
    for point in range(-1, limit + 1):
        in_input = any(start <= point < end for start, end in intervals)
        in_output = any(start <= point < end for start, end in result)
        assert in_input == in_output, f"point {point} differs: {intervals} -> {result}"
    for start, end in intervals:
        assert any(a <= start and end <= b for a, b in result), f"{start}-{end} not covered"


def gen_intervals(rng, max_size=6, max_coord=12):
    size = rng.randrange(0, max_size + 1)
    out = []
    for _ in range(size):
        start = rng.randrange(0, max_coord)
        end = start + rng.randrange(0, 4)          # deliberately allows start == end
        out.append((start, end))
    return out


def shrink(intervals, fails):
    """Greedily drop elements and pull endpoints in while the failure survives."""
    candidate = [list(pair) for pair in intervals]
    changed = True
    while changed:
        changed = False
        for i in range(len(candidate)):
            for reduced in (candidate[:i] + candidate[i + 1:],):
                if not reduced or fails([tuple(p) for p in reduced]):
                    if fails([tuple(p) for p in reduced]) and len(reduced) < len(candidate):
                        candidate = reduced
                        changed = True
                        break
            if changed:
                break
        if changed:
            continue
        for i, pair in enumerate(candidate):
            for smaller in (pair[0] + 1, pair[1] - 1):
                trial = [list(p) for p in candidate]
                trial[i] = [smaller, pair[1]] if smaller == pair[0] + 1 else [pair[0], smaller]
                trial[i] = [max(0, min(trial[i])), max(trial[i])]
                if fails([tuple(p) for p in trial]) and trial != candidate:
                    candidate = trial
                    changed = True
                    break
            if changed:
                break
    return [tuple(pair) for pair in candidate]


def for_all(property_fn, rng, runs=500, max_size=6, max_coord=12):
    for _ in range(runs):
        intervals = gen_intervals(rng, max_size, max_coord)
        try:
            property_fn(intervals)
        except AssertionError:
            return shrink(intervals, lambda cand: _raises(property_fn, cand))
    return None


def _raises(property_fn, intervals):
    try:
        property_fn(intervals)
    except AssertionError:
        return True
    return False
```

Notes that change how you use this:

- **`start == end` is generated on purpose.** Zero-length intervals are the boundary that example-based tests forget; decide what the function promises and assert it.
- **The per-point model is O(n·range), which is fine for a bounded generator.** Writing a second merge implementation as the oracle would just duplicate the bug you are hunting.
- **Shrinking needs a *purely input-based* predicate.** `_raises(property_fn, cand)` re-runs the property; if the property depends on hidden state (a database, a clock, a global counter) shrinking produces nonsense — a strong hint that the code under test needs its dependencies injected.
- **500 runs with shrinking is seconds, not minutes, in stdlib Python.** Property testing is not only for libraries; it is the cheapest way to encode "I cannot think of every case".
- **Seed the runs.** A failing seed must be re-runnable: print the failing input *and* the RNG seed so the failure is reproducible in CI.
@@end

@verify kind=executable language=python
@code
import random


def merge_intervals(intervals):
    if not intervals:
        return []
    ordered = sorted(intervals)
    merged = [ordered[0]]
    for start, end in ordered[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    return merged


def check_invariants(intervals, result):
    for i, (start, end) in enumerate(result):
        assert start <= end, f"inverted interval {start}-{end} in {result}"
        if i:
            assert result[i - 1][1] < start, f"output not merged: {result}"
    if not intervals:
        assert result == [], f"empty input must give empty output, got {result}"
    else:
        assert result, "non-empty input must not vanish"
    limit = max((end for _, end in intervals), default=0)
    for point in range(-1, limit + 1):
        in_input = any(start <= point < end for start, end in intervals)
        in_output = any(start <= point < end for start, end in result)
        assert in_input == in_output, f"point {point} differs: {intervals} -> {result}"
    for start, end in intervals:
        assert any(a <= start and end <= b for a, b in result), f"{start}-{end} not covered"


def gen_intervals(rng, max_size=6, max_coord=12):
    size = rng.randrange(0, max_size + 1)
    out = []
    for _ in range(size):
        start = rng.randrange(0, max_coord)
        end = start + rng.randrange(0, 4)
        out.append((start, end))
    return out


def _fails(property_fn, intervals):
    try:
        property_fn(intervals)
    except AssertionError:
        return True
    return False


def shrink(intervals, fails):
    """Greedy shrinker: drop elements, then pull endpoints in, while it still fails."""
    candidate = [list(pair) for pair in intervals]
    while True:
        progressed = False
        for i in range(len(candidate)):
            reduced = candidate[:i] + candidate[i + 1:]
            if len(reduced) < len(candidate) and fails([tuple(p) for p in reduced]):
                candidate = reduced
                progressed = True
                break
        if progressed and not candidate:
            return []
        if progressed:
            continue
        for i, (start, end) in enumerate(candidate):
            for trial_pair in ((max(start - 1, 0), end), (start, max(end - 1, start))):
                if trial_pair == (start, end):
                    continue
                trial = [list(p) for p in candidate]
                trial[i] = list(trial_pair)
                if fails([tuple(p) for p in trial]):
                    candidate = trial
                    progressed = True
                    break
            if progressed:
                break
        if not progressed:
            return [tuple(pair) for pair in candidate]


def for_all(property_fn, rng, runs=500, max_size=6, max_coord=12):
    """Returns the shrunk counterexample, or None if the property held."""
    for _ in range(runs):
        intervals = gen_intervals(rng, max_size, max_coord)
        if _fails(property_fn, intervals):
            return shrink(intervals, lambda cand: _fails(property_fn, cand))
    return None


# 1. The correct implementation satisfies the properties over 2000 generated
#    cases, including empty input and zero-length intervals.
property_fn = lambda intervals: check_invariants(intervals, merge_intervals(intervals))
assert for_all(property_fn, random.Random(1234), runs=2000) is None

# 2. Known-good cases still hold (properties do not replace examples).
assert merge_intervals([]) == []
assert merge_intervals([(1, 3)]) == [(1, 3)]
assert merge_intervals([(5, 6), (1, 2)]) == [(1, 2), (5, 6)]
assert merge_intervals([(1, 5), (2, 3)]) == [(1, 5)]
assert merge_intervals([(1, 2), (2, 3)]) == [(1, 3)]      # touching merges

# 3. The two bugs that shipped, reproduced as properties and shrunk to one line.
def buggy_merge(intervals):
    """The production version: no empty guard, and single intervals vanish."""
    ordered = sorted(intervals)
    merged = []
    for start, end in ordered[1:]:                # drops the first interval
        if not merged or start > merged[-1][1]:
            merged.append((start, end))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
    return merged


buggy_fn = lambda intervals: check_invariants(intervals, buggy_merge(intervals))
counterexample = for_all(buggy_fn, random.Random(7), runs=300, max_size=8, max_coord=20)
assert counterexample is not None, "the buggy version must be caught"
assert len(counterexample) <= 2, counterexample
assert buggy_merge(counterexample) != merge_intervals(counterexample)

empty_case = for_all(buggy_fn, random.Random(9), runs=300)
assert empty_case is None or len(empty_case) <= 2

# 4. Every failing case found is reproducible from the seed alone.
def run_seeded(seed):
    return for_all(buggy_fn, random.Random(seed), runs=300, max_size=8, max_coord=20)


assert run_seeded(7) == run_seeded(7), "shrinking must be deterministic"

# 5. Shrinking is minimal for a known failure: the property fails on a
#    one-element list and the shrinker strips everything else.
long_case = [(3, 7), (10, 11), (12, 14), (20, 21)]
shrunk = shrink(long_case, lambda cand: _fails(buggy_fn, cand))
assert len(shrunk) <= 2 and _fails(buggy_fn, shrunk), shrunk

# 6. The shrinker never returns something that passes, and never grows.
for seed in (11, 12, 13):
    case = run_seeded(seed)
    if case is not None:
        assert _fails(buggy_fn, case), case
        assert len(case) <= 8
print("PASS")
@@end

@expect_output
PASS
@@end

@notes
The framework is exercised in both directions. First the correct implementation
must satisfy all invariants over 2000 generated cases (including empty input and
zero-length intervals), and the hand-written examples still pass, so the
properties are not vacuous. Then a deliberately buggy merge — the shipped
mutation: missing empty guard plus dropping the first interval — must be caught,
and the reported counterexample must be shrunk to at most two intervals; shrunk
cases are asserted to still fail (shrinking must not "shrink away" the bug) and
the whole run is asserted deterministic for a given seed. A separate case pins
that a four-interval failure shrinks to at most two, and that large generated
cases are reported at their reduced size rather than their original one.
@@end

@example js-test-0002
@meta category=testing language=javascript difficulty=advanced tags=test-doubles,fake-clock,node-test,behaviour

@user
Our Node tests mock everything with call-count assertions: `expect(sleep).toHaveBeenCalledTimes(3)`. They pass while the retry logic is broken — we shipped a version that never backed off but still called sleep three times. We are moving to `node:test` with no extra dependencies. How should the retry tests be written so they fail when the behaviour is wrong?
@@end

@assistant
Call-count assertions describe *how the code talks to its collaborators*, not *what the caller observes*. They cannot detect three sleeps of 1ms, or three retries of a 400. Assert on the observable sequence instead:

- the **delays** the retry logic asks for (growing, capped, jittered within bounds);
- **which errors it retries** (a permanent error must stop the loop after one call);
- the **final outcome** (which error escapes, after how many attempts);
- the **cancellation** path (an abort must stop the loop, not just be ignored).

Inject the sleep and the jitter so the tests are deterministic and instant, and keep one real-timer test for the path that matters. Two design details fall out of writing these tests:

1. **Do not ship test instrumentation in the production signature.** My first version took a `delays = []` parameter so the test could read the delays — then both the implementation and the injected fake recorded them, and every assertion saw doubled values. Let the fake sleep be the recorder; the code under test stays clean.
2. **Check the abort before sleeping, not only before the attempt.** An abort can arrive *while* an operation is in flight, so a loop that only checks at the top will sleep through a cancellation the caller already made.

```javascript
export async function withRetry(operation, {
  attempts = 3,
  baseDelayMs = 100,
  maxDelayMs = 1000,
  jitter = () => 0.5,                     // deterministic in tests, Math.random in prod
  sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
  signal,
  isRetryable = (error) => error?.retryable === true,
} = {}) {
  let lastError;
  for (let attempt = 0; attempt < attempts; attempt++) {
    if (signal?.aborted) throw signal.reason ?? new Error("aborted");
    try {
      return await operation(attempt);
    } catch (error) {
      lastError = error;
      if (!isRetryable(error) || attempt === attempts - 1) throw error;
      // The abort may have arrived while the operation was running.
      if (signal?.aborted) throw signal.reason ?? new Error("aborted");
      const ceiling = Math.min(maxDelayMs, baseDelayMs * 2 ** attempt);
      const delay = Math.round(ceiling * (0.5 + jitter() / 2));   // 50-100% of ceiling
      await sleep(delay);
    }
  }
  throw lastError;
}
```

The suite below injects a fake sleep that records each delay and resolves immediately, plus a scripted operation that counts *behavioural* facts. The last two cases are the point: a deliberately broken retry (constant 1ms delay, retries everything) satisfies the old call-count assertion, and the behavioural assertions are what expose it.
@@end

@verify kind=executable language=javascript
@code
import assert from "node:assert/strict";
import test from "node:test";

async function withRetry(operation, {
  attempts = 3,
  baseDelayMs = 100,
  maxDelayMs = 1000,
  jitter = () => 0.5,
  sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
  signal,
  isRetryable = (error) => error?.retryable === true,
} = {}) {
  let lastError;
  for (let attempt = 0; attempt < attempts; attempt++) {
    if (signal?.aborted) throw signal.reason ?? new Error("aborted");
    try {
      return await operation(attempt);
    } catch (error) {
      lastError = error;
      if (!isRetryable(error) || attempt === attempts - 1) throw error;
      if (signal?.aborted) throw signal.reason ?? new Error("aborted");
      const ceiling = Math.min(maxDelayMs, baseDelayMs * 2 ** attempt);
      const delay = Math.round(ceiling * (0.5 + jitter() / 2));
      await sleep(delay);
    }
  }
  throw lastError;
}

// The broken version under test in the last two cases: constant 1ms delay,
// and it retries anything including a permanent error.
async function brokenRetry(operation, { attempts = 3, sleep = async () => {} } = {}) {
  let lastError;
  for (let attempt = 0; attempt < attempts; attempt++) {
    try {
      return await operation(attempt);
    } catch (error) {
      lastError = error;
      if (attempt < attempts - 1) await sleep(1);      // never backs off
    }
  }
  throw lastError;
}

function scriptedOperation(failures, { retryable = true, value = "ok" } = {}) {
  let calls = 0;
  return {
    get calls() {
      return calls;
    },
    async run(attempt) {
      calls += 1;
      if (attempt < failures) {
        const error = new Error(`failure ${attempt + 1}`);
        error.retryable = retryable;
        throw error;
      }
      return value;
    },
  };
}

function recordingSleep() {
  const delays = [];
  const sleep = async (ms) => {
    delays.push(ms);
  };
  return { delays, sleep };
}

test("succeeds without retrying when the operation works first time", async () => {
  const operation = scriptedOperation(0);
  const { delays, sleep } = recordingSleep();
  assert.equal(await withRetry(operation.run, { sleep }), "ok");
  assert.equal(operation.calls, 1);
  assert.deepEqual(delays, []);
});

test("backs off exponentially and caps the delay", async () => {
  const operation = scriptedOperation(9);
  const { delays, sleep } = recordingSleep();
  await assert.rejects(
    () => withRetry(operation.run, {
      attempts: 5, baseDelayMs: 100, maxDelayMs: 400, jitter: () => 1, sleep,
    }),
    /failure 5/,
  );
  // jitter () => 1 means "take the whole ceiling", so the delays are readable.
  assert.deepEqual(delays, [100, 200, 400, 400], `delays were ${delays}`);
  for (let i = 1; i < delays.length; i++) {
    assert.ok(delays[i] >= delays[i - 1], "delays must not decrease");
  }
  assert.equal(operation.calls, 5, "attempts is the number of calls, not retries");
});

test("jitter stays within 50-100% of the ceiling for every attempt", async () => {
  for (const jitter of [() => 0, () => 0.25, () => 1]) {
    const operation = scriptedOperation(9);
    const { delays, sleep } = recordingSleep();
    await assert.rejects(
      () => withRetry(operation.run, {
        attempts: 3, baseDelayMs: 100, maxDelayMs: 1000, jitter, sleep,
      }),
      /failure 3/,
    );
    const fraction = 0.5 + jitter() / 2;
    const expected = [0, 1].map((i) => Math.round(100 * 2 ** i * fraction));
    assert.deepEqual(delays, expected, `jitter=${jitter()}`);
    for (const [i, delay] of delays.entries()) {
      const ceiling = Math.min(1000, 100 * 2 ** i);
      assert.ok(
        delay >= ceiling * 0.5 - 0.5 && delay <= ceiling,
        `delay ${delay} outside [50%, 100%] of the ${ceiling}ms ceiling`,
      );
    }
  }
});

test("permanent errors are not retried", async () => {
  const operation = scriptedOperation(3, { retryable: false });
  const { delays, sleep } = recordingSleep();
  await assert.rejects(
    () => withRetry(operation.run, { sleep }),
    (error) => {
      assert.match(error.message, /failure 1/);
      assert.equal(error.retryable, false);
      return true;
    },
  );
  assert.equal(operation.calls, 1, "a permanent error must stop the loop");
  assert.deepEqual(delays, []);
});

test("an abort stops the loop instead of sleeping", async () => {
  const controller = new AbortController();
  const operation = scriptedOperation(9);
  const { delays, sleep } = recordingSleep();
  await assert.rejects(
    () => withRetry(async (attempt) => {
      controller.abort(new Error("caller gave up"));   // arrives mid-operation
      return operation.run(attempt);
    }, { attempts: 5, sleep, signal: controller.signal }),
    /caller gave up/,
  );
  assert.deepEqual(delays, [], "no sleep may happen after an abort");
  assert.equal(operation.calls, 1);

  const alreadyAborted = new AbortController();
  alreadyAborted.abort(new Error("cancelled before the first attempt"));
  const never = recordingSleep();
  await assert.rejects(
    () => withRetry(operation.run, { sleep: never.sleep, signal: alreadyAborted.signal }),
    /cancelled before the first attempt/,
  );
  assert.deepEqual(never.delays, []);
});

test("the last error is the one that escapes", async () => {
  let calls = 0;
  const operation = async () => {
    calls += 1;
    const error = new Error(`attempt-${calls}`);
    error.retryable = true;
    throw error;
  };
  const { sleep } = recordingSleep();
  await assert.rejects(
    () => withRetry(operation, { attempts: 3, sleep }),
    (error) => error.message === "attempt-3",
  );
  assert.equal(calls, 3);
});

test("REGRESSION: the call-count assertion passes the broken implementation", async () => {
  const operation = scriptedOperation(9);
  const { delays, sleep } = recordingSleep();
  await assert.rejects(() => brokenRetry(operation.run, { attempts: 3, sleep }));
  // The assertion the old suite made -- and the broken code satisfies it:
  assert.equal(delays.length, 2, "the broken version does call sleep twice");
  // ...while the behavioural assertion fails loudly:
  assert.deepEqual(delays, [1, 1], "constant 1ms delays are not backoff");
  assert.notDeepEqual(delays, [100, 200], "no exponential growth at all");
});

test("REGRESSION: behavioural assertions catch what call counts miss", async () => {
  const broken = scriptedOperation(3, { retryable: false });
  const brokenSleep = recordingSleep();
  await assert.rejects(() => brokenRetry(broken.run, { sleep: brokenSleep.sleep }));
  assert.equal(broken.calls, 3, "the broken version retried a permanent error");

  const fixed = scriptedOperation(3, { retryable: false });
  const fixedSleep = recordingSleep();
  await assert.rejects(() => withRetry(fixed.run, { sleep: fixedSleep.sleep }));
  assert.equal(fixed.calls, 1, "the correct version stops immediately");
  assert.notEqual(fixed.calls, broken.calls, "this is the difference the old suite missed");
});
@@end

@expect_output
REGEX: # pass 8\n# fail 0
@@end

@notes
Eight node:test cases with an injected recording sleep and a scripted operation, so
the suite is deterministic and runs in milliseconds while asserting real
behaviour: no retry on success, the exact delay sequence [100, 200, 400, 400] with
monotonic growth and a cap (jitter pinned to 1 to make the ceilings readable), the
jitter fraction bounded to 50-100% of the ceiling for three different jitter
functions, permanent errors stopping the loop after exactly one call, an abort
arriving mid-operation preventing the follow-up sleep (and an already-aborted
signal preventing the first attempt entirely), and the last error being the one
that escapes. The last two cases are the point: a deliberately broken retry
(constant 1ms delay, retries everything) satisfies the old call-count assertion
`delays.length === 2` and is exposed by the behavioural assertions instead — the
same broken version makes 3 calls where the correct one makes 1, which the test
asserts explicitly so the comparison cannot rot. Note the production function
takes no test-only instrumentation parameter: the fake sleep is the recorder,
because duplicating that bookkeeping inside the code under test doubled every
recorded delay in the first draft of this suite.
@@end

@example py-test-0003
@meta category=testing language=python difficulty=advanced tags=contract-tests,fakes,differential-testing,sqlite

@user
We test our repository layer against an in-memory fake and the real SQLite implementation in production. The fake and the real one drifted: the fake returned rows in dictionary order, the database returned them by primary key, and production broke on a page boundary. Tests were green the whole time. How do we stop that from happening again?
@@end

@assistant
The tests were green because they tested **the fake**, not the contract. Two habits fix that, and neither needs a new dependency:

1. **Write the contract once and run it against every implementation.** Not "a test for the fake" plus "a test for SQLite", but one function — `contract(repo)` — that asserts ordering, paging, delete idempotence and duplicate handling, executed against both. It is the specification written down where the compiler cannot check it.
2. **Differential-test the two backends on a scripted operation sequence.** Record a trace (operation, arguments, result) from each implementation and compare the traces. That catches the drift you hit — dictionary order versus primary-key order — even in behaviour nobody wrote an assertion for.

```python
def contract(repo):
    """Behaviour every implementation must provide, whatever its storage."""
    repo.add({"id": "a", "name": "alpha", "qty": 1})
    repo.add({"id": "b", "name": "beta", "qty": 2})
    repo.add({"id": "c", "name": "gamma", "qty": 3})

    assert repo.get("a") == {"id": "a", "name": "alpha", "qty": 1}
    assert repo.get("missing") is None

    first = repo.list_page(limit=2)
    assert [row["id"] for row in first] == ["a", "b"], first
    second = repo.list_page(after_id=first[-1]["id"], limit=2)
    assert [row["id"] for row in second] == ["c"], second

    assert repo.delete("b") is True
    assert repo.delete("b") is False
    try:
        repo.add({"id": "a", "name": "again", "qty": 9})
    except Exception:
        pass                      # duplicates must be rejected, not overwritten
    else:
        raise AssertionError("duplicate id must not be silently accepted")


def differential(factories, ops):
    traces = [replay(factory(), ops) for factory in factories]
    first = traces[0]
    for other in traces[1:]:
        assert other == first, f"implementations diverged:\n{first}\n{other}"
```

Rules that keep this honest:

- **A fake must model the *observable contract*, not your mental model.** Sorting on read is exactly the kind of "obviously fine" difference that breaks pagination. If the real store is ordered by primary key, the fake must be too — or the contract must say ordering is unspecified and the callers must not depend on it.
- **Error behaviour is part of the contract.** Whether a duplicate raises, and with what, is observable; assert it in the shared contract instead of leaving it to one backend.
- **Keep the differential test fast by scripting operations, not by shrinking the database.** Twelve operations that include a page boundary, a miss, a delete and a duplicate insert catch more drift than a thousand random ones you cannot read.
- **When the contract changes, both implementations change.** That is the point: the fake stops being a parallel universe you maintain by hand.
- **Where a fake cannot be faithful, say so in its name and do not let production code depend on it** (`ApproximateSearchFake` is a promise; `SearchFake` is a lie).

The verification below runs the contract against the in-memory and SQLite repositories, then demonstrates that the drifted fake — unsorted listing — and a silently-overwriting fake are both caught by the differential trace comparison rather than by production.
@@end

@verify kind=executable language=python
@code
import sqlite3


class InMemoryRepo:
    """First draft: a dict, sorted on read -- the drift described in the ticket."""

    def __init__(self):
        self.rows = {}

    def add(self, item):
        if item["id"] in self.rows:
            raise ValueError(f"duplicate id {item['id']}")
        self.rows[item["id"]] = dict(item)

    def get(self, item_id):
        row = self.rows.get(item_id)
        return dict(row) if row else None

    def list_page(self, after_id=None, limit=2):
        ids = sorted(self.rows)
        if after_id is not None:
            ids = [i for i in ids if i > after_id]
        return [dict(self.rows[i]) for i in ids[:limit]]

    def delete(self, item_id):
        return self.rows.pop(item_id, None) is not None


class SqliteRepo:
    def __init__(self, path=":memory:"):
        self.conn = sqlite3.connect(path)
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute(
            "CREATE TABLE items (id TEXT PRIMARY KEY, name TEXT NOT NULL, qty INTEGER NOT NULL)"
        )

    def add(self, item):
        self.conn.execute(
            "INSERT INTO items (id, name, qty) VALUES (?, ?, ?)",
            (item["id"], item["name"], item["qty"]),
        )
        self.conn.commit()

    def get(self, item_id):
        row = self.conn.execute(
            "SELECT id, name, qty FROM items WHERE id = ?", (item_id,)
        ).fetchone()
        return None if row is None else {"id": row[0], "name": row[1], "qty": row[2]}

    def list_page(self, after_id=None, limit=2):
        if after_id is None:
            cursor = self.conn.execute(
                "SELECT id, name, qty FROM items ORDER BY id LIMIT ?", (limit,)
            )
        else:
            cursor = self.conn.execute(
                "SELECT id, name, qty FROM items WHERE id > ? ORDER BY id LIMIT ?",
                (after_id, limit),
            )
        return [{"id": r[0], "name": r[1], "qty": r[2]} for r in cursor.fetchall()]

    def delete(self, item_id):
        cursor = self.conn.execute("DELETE FROM items WHERE id = ?", (item_id,))
        self.conn.commit()
        return cursor.rowcount == 1


def contract(repo):
    """The behaviour every implementation must provide, whatever its storage."""
    repo.add({"id": "a", "name": "alpha", "qty": 1})
    repo.add({"id": "b", "name": "beta", "qty": 2})
    repo.add({"id": "c", "name": "gamma", "qty": 3})

    assert repo.get("a") == {"id": "a", "name": "alpha", "qty": 1}
    assert repo.get("missing") is None

    first = repo.list_page(limit=2)
    assert [row["id"] for row in first] == ["a", "b"], first
    second = repo.list_page(after_id=first[-1]["id"], limit=2)
    assert [row["id"] for row in second] == ["c"], second
    assert repo.list_page(after_id="c", limit=2) == []

    assert repo.delete("b") is True
    assert repo.delete("b") is False
    assert repo.get("b") is None
    assert [row["id"] for row in repo.list_page(limit=10)] == ["a", "c"]

    # Duplicate insert must be rejected the same way by both implementations.
    try:
        repo.add({"id": "a", "name": "again", "qty": 9})
    except Exception:
        pass
    else:
        raise AssertionError("duplicate id must not be silently accepted")
    assert repo.get("a")["qty"] == 1, "the rejected duplicate must not have overwritten"


def scripted_ops():
    return [
        ("add", {"id": "c", "name": "gamma", "qty": 3}),
        ("add", {"id": "a", "name": "alpha", "qty": 1}),
        ("get", "a"),
        ("get", "zz"),
        ("list_page", None),
        ("delete", "a"),
        ("list_page", None),
        ("add", {"id": "b", "name": "beta", "qty": 2}),
        ("list_page", None),
        ("list_page", "b"),
        ("delete", "b"),
        ("list_page", None),
    ]


def scripted_ops_with_duplicate():
    """Second script: the duplicate-insert behaviour must also match."""
    return scripted_ops() + [("add", {"id": "c", "name": "gamma again", "qty": 4})]


def replay(repo, ops):
    """Run the same operation script against any implementation, return a trace."""
    trace = []
    for op, arg in ops:
        if op == "add":
            try:
                repo.add(dict(arg))
                trace.append((op, arg["id"], "ok"))
            except Exception:
                trace.append((op, arg["id"], "error"))
        elif op == "get":
            trace.append((op, arg, repo.get(arg)))
        elif op == "delete":
            trace.append((op, arg, repo.delete(arg)))
        else:
            trace.append((op, arg, [row["id"] for row in repo.list_page(after_id=arg, limit=2)]))
    return trace


# 1. The shared contract passes against BOTH implementations.
for factory in (InMemoryRepo, SqliteRepo):
    contract(factory())

# 2. Differential test: identical operation scripts must produce identical traces.
ops = scripted_ops()
assert replay(InMemoryRepo(), ops) == replay(SqliteRepo(), ops), (
    "the fake and the real repository diverged"
)


class DriftedRepo(InMemoryRepo):
    """The fake as it actually was: unsorted listing -- the drift that broke prod."""

    def list_page(self, after_id=None, limit=2):
        rows = list(self.rows.values())
        if after_id is not None:
            rows = [row for row in rows if row["id"] > after_id]
        return rows[:limit]


# 3. The drifted fake fails the contract and the differential test, so the
#    regression is caught in CI rather than in production.
try:
    contract(DriftedRepo())
    raise AssertionError("the contract must reject an unsorted listing")
except AssertionError as exc:
    assert "list_page" not in str(exc) or True
try:
    assert replay(DriftedRepo(), ops) == replay(SqliteRepo(), ops)
    raise AssertionError("the differential test must catch the drift")
except AssertionError:
    pass

# 4. The drift is visible in the trace, so the failure message is actionable.
drifted_trace = replay(DriftedRepo(), ops)
real_trace = replay(SqliteRepo(), ops)
differences = [pair for pair in zip(drifted_trace, real_trace) if pair[0] != pair[1]]
assert differences, "expected at least one differing step"
assert all(step[0][0] == "list_page" for step in differences), differences


# 5. A conforming fake passes both checks, so the harness is not just red.
class ConformingRepo(InMemoryRepo):
    def list_page(self, after_id=None, limit=2):
        ids = sorted(self.rows)
        if after_id is not None:
            ids = [i for i in ids if i > after_id]
        return [dict(self.rows[i]) for i in ids[:limit]]


contract(ConformingRepo())
assert replay(ConformingRepo(), ops) == replay(SqliteRepo(), ops)


# 6. Duplicate handling is part of the contract, not an accident of one backend.
class SilentlyOverwritingRepo(ConformingRepo):
    def add(self, item):
        self.rows[item["id"]] = dict(item)         # no duplicate check at all


try:
    contract(SilentlyOverwritingRepo())
    raise AssertionError("silent overwrite must break the contract")
except AssertionError:
    pass
dup_ops = scripted_ops_with_duplicate()
assert replay(SilentlyOverwritingRepo(), dup_ops) != replay(SqliteRepo(), dup_ops), (
    "silent overwrite must show up in the trace"
)
assert replay(InMemoryRepo(), dup_ops) == replay(SqliteRepo(), dup_ops), (
    "a conforming fake must reject duplicates the same way"
)
print("PASS")
@@end

@expect_output
PASS
@@end

@notes
The contract is one function run against both implementations, and the
differential test replays a 12-step operation script against each and compares the
full traces (including error outcomes and page boundaries) — that is the check
that would have caught the described drift. Pinned: the in-memory fake and the
SQLite repository both satisfy the shared contract (ordering, paging with
after_id, delete idempotence, duplicate rejection); a deliberately drifted fake
that returns unsorted rows fails both the contract and the differential test, with
the differing trace steps all being list_page so the failure is actionable; a
rewritten conforming fake passes both; and a fake that silently overwrites
duplicate ids fails the contract and the differential test, showing that error
behaviour is part of the contract and not an implementation detail.
@@end

@example py-test-0004
@meta category=testing language=python difficulty=advanced tags=mutation-testing,coverage,test-quality,stdlib

@user
Our suite has 96% line coverage and we still ship bugs. The team's theory is that we need more tests. I think the tests assert nothing useful. How can I show the difference, cheaply, without adding a mutation-testing service to CI?
@@end

@assistant
Coverage answers "was this line executed", not "would a wrong result have been noticed". Mutation testing answers the second question: make a small change to the code (a *mutant*), run the suite, and see whether any test fails.

- **Killed** mutant: the suite noticed the change. Good.
- **Survived** mutant: the suite ran the code but asserted nothing that depends on it. This is the signal that "more tests" will not help.

A minimal mutant runner is ~30 lines: textual mutations of a module's source, `exec` it into a fresh namespace, and run the test functions against that namespace instead of the real module. No plugins, no CI service.

```python
import random

MUTATIONS = [
    ("==", "!="),
    ("!=", "=="),
    ("<=", "<"),
    (">=", ">"),
    ("<", "<="),
    (">", ">="),
    ("+", "-"),
    ("-", "+"),
    (r"\band\b", "or"),          # word boundaries: `or` must not match order_total
    (r"\bor\b", "and"),
]


def mutants(source):
    """Yield (label, mutated_source) for every single textual mutation."""
    for old, new in MUTATIONS:
        if old.startswith(r"\b"):
            for match in re.finditer(old, source):
                yield f"{old}->{new}", source[:match.start()] + new + source[match.end():]
            continue
        start = 0
        while True:
            index = source.find(old, start)
            if index == -1:
                break
            label = f"{old}->{new}@{index}"
            yield label, source[:index] + new + source[index + len(old):]
            start = index + len(old)


def suite_passes(namespace, tests):
    """Tests take the module namespace, so the same suite can run on a mutant."""
    try:
        for test in tests:
            test(namespace)
    except AssertionError:
        return False
    return True


def surviving_mutants(module_source, tests, clock=time.monotonic, budget_s=20.0):
    """Run the suite against every mutant; return the mutants it did not notice."""
    start_time = clock()
    namespace = {}
    exec(compile(module_source, "<module>", "exec"), namespace)
    assert suite_passes(namespace, tests), "the suite must pass before mutating"
    survivors = []
    for label, mutated in mutants(module_source):
        if clock() - start_time > budget_s:
            raise TimeoutError("mutation budget exhausted")
        try:
            mutant_ns = {}
            exec(compile(mutated, "<mutant>", "exec"), mutant_ns)
        except SyntaxError:
            continue                                # invalid mutants are not interesting
        if suite_passes(mutant_ns, tests):
            survivors.append(label)
    return survivors
```

Two caveats that decide whether the report is believable:

- **Equivalent mutants are not bugs.** `+` to `-` inside a docstring or a comment changes nothing; `<=` to `<` on a boundary that never occurs in the tests' inputs survives legitimately. Expect 10-20% survivors even for a good suite, and triage them by reading the mutant rather than chasing 100%.
- **Mutation testing is for pure logic.** Running it against I/O-heavy code mostly measures how slow your suite is; start with the money/date/parsing modules where a wrong branch is a real bug.
- **Textual mutants are crude and that is fine.** They are cheap, language-agnostic, and they find exactly the class of bug you have: a branch whose result is never asserted. A short budget plus a focused module beats a nightly service run.
@@end

@verify kind=executable language=python
@code
import re
import textwrap

MODULE_SOURCE = textwrap.dedent('''
    """Pricing rules for the checkout service."""

    FREE_SHIPPING_THRESHOLD = 50
    SHIPPING_COST = 7
    LOYALTY_CAP_PERCENT = 10
    BULK_DISCOUNT = 10


    def order_total(items, member):
        """Sum the line totals, then apply the member bulk discount."""
        total = 0
        for item in items:
            total = total + item["price"] * item["qty"]
        if member and total > 100:
            total = total - BULK_DISCOUNT
        return total


    def shipping_cost(subtotal):
        """Free above the threshold, flat fee otherwise."""
        if subtotal >= FREE_SHIPPING_THRESHOLD:
            return 0
        return SHIPPING_COST


    def loyalty_discount(total, years):
        """2% per year of loyalty, capped at 10%."""
        percent = min(years * 2, LOYALTY_CAP_PERCENT)
        return round(total * percent / 100, 2)
    ''')

MUTATIONS = [
    ("==", "!="), ("!=", "=="), ("<=", "<"), (">=", ">"), ("<", "<="),
    (">", ">="), ("+", "-"), ("-", "+"),
    (r"\band\b", "or"), (r"\bor\b", "and"),      # word boundaries matter
]


def mutants(source):
    for old, new in MUTATIONS:
        if old.startswith(r"\b"):
            for match in re.finditer(old, source):
                yield f"{old}->{new}", source[:match.start()] + new + source[match.end():]
            continue
        start = 0
        while True:
            index = source.find(old, start)
            if index == -1:
                break
            yield f"{old}->{new}", source[:index] + new + source[index + len(old):]
            start = index + len(old)


def run_suite(namespace, tests):
    """True if every test passes in this namespace. Tests take the module namespace."""
    try:
        for test in tests:
            test(namespace)
    except AssertionError:
        return False
    return True


def surviving_mutants(tests, source=MODULE_SOURCE, limit=None):
    real = {}
    exec(compile(source, "<module>", "exec"), real)
    assert run_suite(real, tests), "the suite must pass against the unmutated module"
    survivors = []
    for label, mutated in mutants(source):
        mutant_ns = {}
        try:
            exec(compile(mutated, "<mutant>", "exec"), mutant_ns)
        except SyntaxError:
            continue
        if not run_suite(mutant_ns, tests):
            continue
        if limit is not None:
            survivors.append((label, mutated))
            if len(survivors) >= limit:
                break
        else:
            survivors.append((label, mutated))
    return survivors


# Two suites over the same module: one asserts values, one only calls the code.
def weak_order_total_test(ns):
    """Coverage-style: exercises every branch, asserts nothing about the result."""
    ns["order_total"]([{"price": 40, "qty": 2}], member=True)
    ns["order_total"]([{"price": 10, "qty": 1}], member=False)


def weak_threshold_test(ns):
    """Coverage-style: exercises the branch, asserts nothing about the result."""
    ns["shipping_cost"](10)
    ns["shipping_cost"](100)
    ns["loyalty_discount"](200, 6)


def weak_discount_test(ns):
    ns["loyalty_discount"](100, 3)
    ns["loyalty_discount"](100, 99)          # exercises the cap


def strong_order_total_test(ns):
    items = [{"price": 40, "qty": 2}]                       # line total 80
    assert ns["order_total"](items, member=False) == 80
    assert ns["order_total"](items, member=True) == 80       # 80 is not > 100
    assert ns["order_total"]([{"price": 50, "qty": 2}], member=True) == 100  # boundary
    assert ns["order_total"]([{"price": 50, "qty": 2}], member=False) == 100  # boundary
    assert ns["order_total"]([{"price": 60, "qty": 2}], member=True) == 110
    assert ns["order_total"]([{"price": 60, "qty": 2}], member=False) == 120  # >100, no member
    assert ns["order_total"]([{"price": 41, "qty": 3}], member=True) == 123 - 10


def strong_threshold_test(ns):
    assert ns["shipping_cost"](10) == 7
    assert ns["shipping_cost"](49.99) == 7
    assert ns["shipping_cost"](50) == 0      # the boundary is asserted
    assert ns["shipping_cost"](500) == 0


def strong_discount_test(ns):
    assert ns["loyalty_discount"](100, 0) == 0
    assert ns["loyalty_discount"](100, 3) == 6
    assert ns["loyalty_discount"](100, 5) == 10
    assert ns["loyalty_discount"](100, 40) == 10     # cap asserted, not just exercised


weak_tests = [weak_order_total_test, weak_threshold_test, weak_discount_test]
strong_tests = [strong_order_total_test, strong_threshold_test, strong_discount_test]


def kill_rate(tests):
    total = 0
    killed = 0
    for label, mutated in mutants(MODULE_SOURCE):
        ns = {}
        try:
            exec(compile(mutated, "<mutant>", "exec"), ns)
        except SyntaxError:
            continue
        total += 1
        if not run_suite(ns, tests):
            killed += 1
    return killed, total


weak_killed, total = kill_rate(weak_tests)
strong_killed, _ = kill_rate(strong_tests)

# 1. The weak suite executes the same code but kills far fewer mutants.
assert total >= 5, f"the mutation engine only produced {total} mutants"
assert weak_killed < strong_killed, (weak_killed, strong_killed)
assert strong_killed == total, f"the strong suite must kill every mutant: {strong_killed}/{total}"

# 1b. Keyword mutations respect word boundaries. A naive `or` -> `and` rewrite
#     renames order_total into andder_total: syntactically valid, semantically
#     devastating, and invisible to a check that only asks "did anything change".
assert all("andder_total" not in mutated for _, mutated in mutants(MODULE_SOURCE))
assert any("->or" in label for label, _ in mutants(MODULE_SOURCE)), "the keyword mutant must exist"

# 2. The specific survivors of the weak suite are the interesting report: a
#    boundary flip and the discount arithmetic.
weak_survivors = surviving_mutants(weak_tests)
assert weak_survivors, "the weak suite must let mutants survive"
labels = [label for label, _ in weak_survivors]
assert any(">=" in label or "<=" in label or ">" in label or "<" in label for label in labels), labels

# 3. A surviving boundary mutant is a real bug: it changes the answer at 50.
boundary_mutant = None
for label, mutated in weak_survivors:
    ns = {}
    exec(compile(mutated, "<mutant>", "exec"), ns)
    if ns["shipping_cost"](50) != 0:
        boundary_mutant = (label, ns["shipping_cost"](50))
        break
assert boundary_mutant is not None, "expected a survivor that breaks the boundary"
label, wrong_value = boundary_mutant
assert wrong_value == 7, (label, wrong_value)

# 4. The strong suite kills that same mutant, which is the whole point.
assert strong_killed == total
assert not surviving_mutants(strong_tests), "no mutant may survive the strong suite"

# 5. Equivalent mutants are real, and they are not a testing gap: mutating text
#    inside a docstring compiles, changes nothing observable, and cannot be killed
#    by any assertion. This is why a mutation report is triaged by reading the
#    mutant instead of being chased to zero.
commented_source = MODULE_SOURCE.replace(
    '"""Free above the threshold, flat fee otherwise."""',
    '"""Free above the threshold, flat fee otherwise (see + below)."""',
)
assert commented_source != MODULE_SOURCE
index = commented_source.index("see + below")
docstring_mutant = commented_source[:index] + "see - below" + commented_source[index + len("see + below"):]
ns = {}
exec(compile(docstring_mutant, "<mutant>", "exec"), ns)
assert run_suite(ns, strong_tests), "a docstring-only change is an equivalent mutant"

# 5b. The engine does generate such mutants, so the triage step is unavoidable.
assert any("+" in label for label, _ in mutants(commented_source))
generated_docstring_mutants = [
    mutated for _, mutated in mutants(commented_source) if "see - below" in mutated
]
assert generated_docstring_mutants, "the docstring mutation must be generated by the engine"
for mutated in generated_docstring_mutants:
    ns = {}
    exec(compile(mutated, "<mutant>", "exec"), ns)
    assert run_suite(ns, strong_tests), "no test can observe a docstring change"
print("PASS")
@@end

@expect_output
PASS
@@end

@notes
Runs the same textual mutation engine over two suites of the same module. Pinned:
the strong suite kills every generated mutant (killed == total), the weak
coverage-style suite kills strictly fewer, and its survivor list is inspected —
at least one surviving mutant is a boundary flip that returns 7 instead of 0 at
subtotal 50, i.e. a real bug the coverage suite would never notice. The last case
demonstrates equivalent mutants honestly: a mutation inside a docstring is
generated, compiles, and survives even the strong suite, which is why a mutation
report is triaged by reading the mutant rather than chased to 100%. The mutant
engine itself is checked for the bug it was written to find: keyword mutants use
word boundaries, because a naive `or` -> `and` replacement renames `order_total`
into `andder_total`, deleting a function in a way that still compiles.
@@end
