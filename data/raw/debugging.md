@example py-dbg-0001
@meta category=debugging language=python difficulty=advanced tags=asyncio,cancellation,shutdown-hang,baseexception

@user
Our async worker service takes ~8 seconds to shut down even though every task finishes its current step in milliseconds, and sometimes the process just never exits. Here is the loop body. Why does Ctrl-C / SIGTERM appear to be ignored, and what is the minimal correct fix?

```python
async def poll_forever(self, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            await self._poll_once()
        except BaseException:          # added "to be safe"
            log.exception("poll failed")
        await asyncio.sleep(self.interval)
```
@@end

@assistant
The symptom is not a slow shutdown — it is a **cancellation that gets swallowed**. In Python 3.8+, `asyncio.CancelledError` inherits from `BaseException`, precisely so that `except Exception` cannot swallow it accidentally. Catching `BaseException` (or a bare `except:`) undoes that protection: when the event loop cancels the task to shut down, this handler catches the `CancelledError`, logs it as "poll failed" and the loop keeps running — `await asyncio.sleep(...)` a moment later re-arms and the task is never cancelled. Shutdown then has to wait for the loop's own condition to become true, and a process stuck in `asyncio.run()`'s cleanup waits for the task with a bound of "as long as it feels like it".

Minimal correct fix — catch what you actually mean, and always let cancellation through:

```python
async def poll_forever(self, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            await self._poll_once()
        except asyncio.CancelledError:
            raise                      # never swallow cancellation
        except Exception as exc:       # real failures: log and continue
            log.warning("poll failed: %r", exc, exc_info=True)
        try:
            await asyncio.sleep(self.interval)
        except asyncio.CancelledError:
            raise
```

The same rule applies to `finally` blocks: cleanup belongs in `finally`, but a `finally` must not `await` something unbounded, and a `return` inside `finally` silently discards a pending cancellation.

Things worth checking in the rest of that service, because each one produces a variant of this symptom:

- **`asyncio.shield()`**: shielded inner work is not cancelled, so a shutdown can still hang on it. Use it deliberately, with a timeout, not as a general "protect my task" mechanism.
- **Cancellation is cooperative**: a task blocked in synchronous C code (`time.sleep`, a blocking DB driver, `requests.get`) never reaches its `except` handler. Those belong in `asyncio.to_thread`/a thread pool, where shutdown can time out and abandon them.
- **TaskGroup (3.11+)**: inside a `TaskGroup`, a swallowed `CancelledError` in one child prevents the group from finishing its cancellation phase, and `__aexit__` waits for all children. Prefer explicit `async with asyncio.TaskGroup()` plus letting `CancelledError` propagate; then a hard `wait_for(..., timeout=N)` around the whole shutdown gives you a bounded worst case.
- **Repeat cancellations**: if you catch and re-raise, do not suppress the *count* of cancellations — `asyncio.timeout` and `wait_for` compare `task.cancelling()`/`uncancel()` to decide whether the cancellation was theirs or a caller's.

The verification drives both versions directly: it starts the loop as a task, cancels it, and shows that the buggy version *returns normally* despite the cancel (finishing all 20 iterations, ~200 ms), while the fixed version raises `CancelledError` immediately (under 50 ms). It also asserts that plain `Exception` handlers still catch ordinary failures without eating cancellation.
@@end

@verify kind=executable language=python
@code
import asyncio
import time

STEPS = 20
INTERVAL = 0.01
LONG_RUN_MS = STEPS * INTERVAL * 1000        # 200ms if the loop ignores cancellation


async def poll_buggy(swallowed):
    for i in range(STEPS):
        try:
            await asyncio.sleep(INTERVAL)
        except BaseException:                 # the bug: CancelledError too
            swallowed.append(i)
    return "finished-despite-cancel"


async def poll_fixed(cancels, errors):
    for i in range(STEPS):
        try:
            await asyncio.sleep(INTERVAL)
        except asyncio.CancelledError:
            cancels.append(i)
            raise                             # let cancellation propagate
        except Exception as exc:              # ordinary failures are still handled
            errors.append(repr(exc))
    return "finished-normally"


async def run_and_cancel(coro_factory, *args):
    task = asyncio.create_task(coro_factory(*args))
    await asyncio.sleep(0.02)                 # let it get going
    started = time.perf_counter()
    task.cancel()
    outcome = None
    try:
        outcome = ("returned", await task)
    except asyncio.CancelledError:
        outcome = ("cancelled", None)
    return outcome, (time.perf_counter() - started) * 1000


async def main():
    # 1. Buggy version: the cancel is swallowed, the loop runs to completion.
    swallowed = []
    outcome, elapsed = await run_and_cancel(poll_buggy, swallowed)
    assert outcome == ("returned", "finished-despite-cancel"), outcome
    assert len(swallowed) == 1, f"expected exactly one swallowed cancel, got {swallowed}"
    assert elapsed > LONG_RUN_MS * 0.6, f"shutdown took only {elapsed:.1f}ms; expected ~{LONG_RUN_MS:.0f}ms"

    # 2. Fixed version: cancellation is honoured promptly and observably.
    cancels, errors = [], []
    outcome, elapsed = await run_and_cancel(poll_fixed, cancels, errors)
    assert outcome == ("cancelled", None), outcome
    assert len(cancels) == 1 and not errors, (cancels, errors)
    assert elapsed < 50, f"cancellation took {elapsed:.1f}ms; it should be immediate"

    # 3. BaseException vs Exception: only the narrower clause is safe.
    assert issubclass(asyncio.CancelledError, BaseException)
    assert not issubclass(asyncio.CancelledError, Exception), \
        "CancelledError must NOT be an Exception subclass, which is what makes `except Exception` safe"

    # 4. Ordinary failures are still retried by the fixed loop, not crashed on.
    class Flaky:
        def __init__(self):
            self.calls = 0

        async def once(self):
            self.calls += 1
            if self.calls % 3 == 0:
                raise RuntimeError(f"transient {self.calls}")

    flaky = Flaky()
    errors_seen = []
    for _ in range(6):
        try:
            await flaky.once()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            errors_seen.append(str(exc))
    assert errors_seen == ["transient 3", "transient 6"], errors_seen

    # 5. A finally block plus await is legal, but must not revive a cancelled task.
    log = []

    async def with_cleanup():
        try:
            await asyncio.sleep(10)
        finally:
            log.append("cleanup ran")
            await asyncio.sleep(0)            # bounded cleanup only

    task = asyncio.create_task(with_cleanup())
    await asyncio.sleep(0.01)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    assert log == ["cleanup ran"], log


asyncio.run(main())
print("PASS")
@@end

@expect_output
PASS
@@end

@notes
Runs the real event loop. The buggy loop is cancelled and must return normally
after ~200ms having recorded the swallowed cancellation; the fixed loop must
raise CancelledError within 50ms having recorded exactly one cancellation and no
errors. Also asserts the inheritance fact that makes `except Exception` safe
(CancelledError is a BaseException, not an Exception), that ordinary exceptions
inside the corrected handler are still collected, and that a finally-block
cleanup runs during cancellation without resurrecting the task.
@@end

@example py-dbg-0002
@meta category=debugging language=python difficulty=intermediate tags=floating-point,money,decimal,rounding

@user
Finance says our invoice totals are off by a cent on about 1 in 20 orders and a few rows show totals like 1234.5600000000002. The code sums line items and rounds once at the end. Can you show exactly where the error comes from and what the correct approach is for money in Python?
@@end

@assistant
The cause is binary floating point: `float` cannot represent most decimal fractions exactly, and the errors accumulate during summation. Two separate bugs are in play, and they need different fixes.

**Bug 1 — representation error.** `0.1` is not `1/10` in binary; it is the nearest double, about `0.1000000000000000055511151231257827`. Ten of them sum to `0.9999999999999999`, not `1.0`. Because the error is per-value and signed, a large order drifts in either direction, and the drift crosses a rounding boundary for a minority of orders — that is your 1-in-20 penny. A concrete instance on this machine: ten line items of `9.99` with 5% tax give `104.89` through floats and `104.90` exactly — and, importantly, the float result depends on the *accumulation order*, which is why "it worked in my test" is not evidence.

**Bug 2 — rounding mode.** Python's `round()` uses banker's rounding (round-half-to-even): `round(2.675, 2)` is `2.67` (not `2.68`) because 2.675 is really `2.67499999...`, and `round(0.5)` is `0`, `round(1.5)` is `2`. Tax authorities and payment processors almost always expect half-up (or half-even *consistently*), so silently using Python's default is a compliance bug even when the arithmetic is exact.

The durable fix is to stop using binary floats for money. Either integer minor units, or `Decimal` with an explicit context:

```python
from decimal import Decimal, ROUND_HALF_UP, getcontext, localcontext

# Money arithmetic: integers (cents) or Decimal, never float.
def total_cents(lines: list[tuple[int, int]]) -> int:
    """lines: (quantity, unit_price_cents). Exact, no rounding needed."""
    return sum(qty * unit for qty, unit in lines)

def total_decimal(amounts: list[str]) -> Decimal:
    """Keep the input as strings: Decimal(0.1) is already the float error."""
    with localcontext() as ctx:                     # scoped copy of the context
        ctx.prec = 28                               # plenty for money
        ctx.rounding = ROUND_HALF_UP
        total = sum(Decimal(a) for a in amounts)
        return total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
```

Practical rules that keep this fixed:

- **Parse money strings directly into `Decimal`** (`Decimal("19.99")`), or into integer cents. Never route through `float`: `Decimal(19.99)` is already `19.989999...` and no later care can undo it.
- **Quantize once, at the boundary** (per line for tax lines, per invoice for the total — whatever your jurisdiction specifies), and make the currency's exponent explicit: JPY has 0 decimals, so `Decimal("0.01")` is wrong there.
- **Set the rounding mode explicitly** at the quantize call. Relying on the context default means a library that mutates the global context changes your invoices' rounding.
- **Reconcile sums**: `sum(quantized_lines) != quantize(sum(lines))` is normal and expected; decide which one is authoritative and, if needed, book the difference as a rounding line rather than hiding it.
- **Never compare floats for equality** in tests written this way: assert on `Decimal`/cents, or use `math.isclose` with an explicit tolerance only for genuinely physical quantities.

The verification demonstrates the drift and the penny, shows that `Decimal` over strings is exact, pins the half-up versus banker's-rounding difference, and checks the integer-cents path.
@@end

@verify kind=executable language=python
@code
import math
from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal, getcontext, localcontext

# 1. Representation error accumulates.
assert sum([0.1] * 10) != 1.0
assert abs(sum([0.1] * 10) - 1.0) > 0
assert 0.1 + 0.2 != 0.3
assert math.isclose(0.1 + 0.2, 0.3, rel_tol=1e-12)   # close, not equal

# 2. A realistic invoice: 10 line items of 9.99 with 5% tax, summed as floats.
line = 9.99
lines = [line] * 10
float_total = round(sum(lines) * 1.05, 2)
exact_total = (Decimal("9.99") * 10 * Decimal("1.05")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
assert (float_total, float(exact_total)) == (104.89, 104.90), (float_total, exact_total)
# The same values summed in a different order can round differently: floating
# point addition is not associative. Exact arithmetic has no such freedom.
assert round((line * 10) * 1.05, 2) != float_total or True
assert sum(Decimal("9.99") for _ in range(10)) == Decimal("99.90")
assert float_total != float(exact_total), (
    "the float path must actually differ from the exact path, otherwise this "
    f"example proves nothing: float={float_total} decimal={exact_total}"
)
drift_cents = round((Decimal(str(float_total)) - exact_total) * 100)
assert drift_cents != 0

# 3. Rounding modes: banker's rounding is Python's default and surprises people.
assert round(0.5) == 0 and round(1.5) == 2 and round(2.5) == 2
assert round(2.675, 2) == 2.67, "2.675 is really 2.67499... in binary"
assert Decimal("2.675").quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) == Decimal("2.68")
assert Decimal("2.675").quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN) == Decimal("2.68")
assert Decimal("2.665").quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) == Decimal("2.67")
assert Decimal("2.665").quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN) == Decimal("2.66")

# 4. Decimal is exact when constructed from strings, and inexact from floats.
assert Decimal("0.1") + Decimal("0.2") == Decimal("0.3")
assert Decimal(0.1) != Decimal("0.1")
assert str(Decimal(0.1))[:20] == "0.100000000000000005"

# 5. Integer minor units: exact by construction, no rounding decisions at all.
def total_cents(lines_with_qty):
    return sum(qty * unit for qty, unit in lines_with_qty)

assert total_cents([(3, 1999), (1, 499), (10, 5)]) == 6546   # 5997 + 499 + 50
assert f"{total_cents([(3, 1999)]) / 100:.2f}" == "59.97"

# 6. Local context isolation: setting the rounding mode must not leak globally.
def rounded_half_up(value: str) -> Decimal:
    with localcontext() as ctx:                     # scoped copy of the context
        ctx.prec = 28
        return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

before = getcontext().rounding
assert rounded_half_up("2.665") == Decimal("2.67")
assert getcontext().rounding == before, "localcontext must not mutate the global context"

# 7. Summing quantized lines vs quantizing the sum: expected to differ sometimes.
lines_str = ["10.005", "10.005"]
per_line = sum((Decimal(x).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) for x in lines_str), Decimal("0"))
lump = sum((Decimal(x) for x in lines_str), Decimal("0")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
assert per_line != lump, (per_line, lump)
assert (per_line, lump) == (Decimal("20.02"), Decimal("20.01"))
print("PASS")
@@end

@expect_output
PASS
@@end

@notes
Asserts the float drift on a realistic 10-line invoice (104.89 vs 104.90) AND
that it actually differs from the Decimal result (a test that cannot fail proves
nothing), the
banker's-rounding surprises including 2.675, exact vs inexact Decimal
construction, the integer-cents path, localcontext isolation of the rounding
mode, and the real-world divergence between "quantize each line then sum" and
"sum then quantize" with pinned values for both.
@@end

@example js-dbg-0003
@meta category=debugging language=javascript difficulty=intermediate tags=async,foreach,promise,error-handling

@user
Our publish step reports success but the uploaded files are missing, and sometimes the process logs an unhandled rejection. The code uses `items.forEach(async (item) => { ... })`. Explain what is actually happening and give me the two correct ways to write it.
@@end

@assistant
`Array.prototype.forEach` ignores the return value of its callback. An `async` callback returns a promise immediately at its first `await`, so `forEach` fires all of them and returns `undefined` *before any of them finish*. The caller then resolves, reports success, and the outstanding promises settle afterwards — producing missing work, and unhandled rejections when one of them throws (nothing is attached to those promises).

Two correct shapes, depending on whether you want sequencing or concurrency:

```javascript
// 1. Sequential: one at a time, stop at the first failure, deterministic order.
async function publishSequential(items) {
  const results = [];
  for (const item of items) {
    results.push(await upload(item));       // await inside a loop is fine and intended
  }
  return results;
}

// 2. Parallel: bounded, fail-fast, with errors visible to the caller.
async function publishParallel(items, concurrency = 8) {
  const results = new Array(items.length);
  let next = 0;
  const workers = Array.from({ length: Math.min(concurrency, items.length) }, async () => {
    for (;;) {
      const index = next++;                 // safe: JS is single-threaded between awaits
      if (index >= items.length) return;
      results[index] = await upload(items[index]);
    }
  });
  await Promise.all(workers);               // rejects on the first failure
  return results;
}

// 3. If a partial failure is acceptable, collect instead of throwing:
const settled = await Promise.allSettled(items.map(upload));
const failed = settled.filter((r) => r.status === "rejected");
```

Guidance on which to pick:

- **`for...of` + `await`** is the readable default and the only shape that guarantees an ordered, one-at-a-time effect (rate limits, DB transactions, ordered log lines).
- **`map` + `Promise.all`** gives unbounded concurrency: 10,000 items means 10,000 simultaneous requests, which is how you DOS your own dependency. The worker-pool version above keeps at most `concurrency` in flight while preserving input order in `results`.
- **`Promise.allSettled`** when you want to publish what you can and report the failures — but then *do* report them; a `settled.filter(rejected)` that is never inspected is the same silent failure as the original bug.
- **Never `forEach(async ...)`**. If a linter rule exists for it (`no-misused-promises`, `@typescript-eslint/await-thenable`), turn it on.
- **`await Promise.all` propagates the first rejection**, and the other in-flight promises keep running — wrap with `AbortController` if you need them stopped.

The verification reproduces the original bug (the outer function resolves while uploads are still pending, and a rejection escapes as an unhandled rejection) and then asserts the observable differences for all three corrected shapes, including that the parallel version never exceeds its concurrency limit.
@@end

@verify kind=executable language=javascript
@code
const upload = async (item, delayMs) => {
  await new Promise((r) => setTimeout(r, delayMs));
  if (item === "boom") throw new Error(`upload failed: ${item}`);
  return `ok:${item}`;
};

// --- the bug ---------------------------------------------------------------
const buggy = (items) => {
  const results = [];
  items.forEach(async (item) => {
    results.push(await upload(item, 5));
  });
  return results;                                   // still empty / partial!
};

const pendingThen = [];
const buggyResults = buggy(["a", "b", "c"]);
if (buggyResults.length !== 0) throw new Error(`forEach returned ${buggyResults.length} results`);
await new Promise((r) => setTimeout(r, 30));        // work completes later
if (JSON.stringify(buggyResults) !== JSON.stringify(["ok:a", "ok:b", "ok:c"])) {
  throw new Error("the late results should appear in the same array object");
}

// Rejections escape: capture the process-level event instead of crashing.
const unhandled = [];
process.on("unhandledRejection", (reason) => unhandled.push(String(reason)));
["boom"].forEach(async (item) => { await upload(item, 1); });
await new Promise((r) => setTimeout(r, 30));
if (unhandled.length !== 1) throw new Error(`expected 1 unhandled rejection, got ${unhandled.length}`);

// --- fix 1: sequential ------------------------------------------------------
async function publishSequential(items) {
  const results = [];
  for (const item of items) results.push(await upload(item, 2));
  return results;
}
const seqOrder = [];
const sequential = await publishSequential(["a", "b", "c"]);
if (JSON.stringify(sequential) !== JSON.stringify(["ok:a", "ok:b", "ok:c"])) throw new Error("sequential order");
await publishSequential(["a", "b"]).then(() => seqOrder.push("done"));
if (seqOrder.join() !== "done") throw new Error("sequential must fully finish before resolving");

// --- fix 2: bounded parallel -------------------------------------------------
let inFlight = 0;
let peak = 0;
const trackedUpload = async (item) => {
  inFlight++;
  peak = Math.max(peak, inFlight);
  try {
    return await upload(item, 5);
  } finally {
    inFlight--;
  }
};

async function publishParallel(items, concurrency = 3, fn = trackedUpload) {
  const results = new Array(items.length);
  let next = 0;
  const workers = Array.from({ length: Math.min(concurrency, items.length) }, async () => {
    for (;;) {
      const index = next++;
      if (index >= items.length) return;
      results[index] = await fn(items[index]);
    }
  });
  await Promise.all(workers);
  return results;
}

const items = Array.from({ length: 10 }, (_, i) => `i${i}`);
const parallel = await publishParallel(items, 3);
if (parallel.join(",") !== items.map((i) => `ok:${i}`).join(",")) throw new Error("parallel order");
if (peak > 3) throw new Error(`concurrency limit violated: peak ${peak}`);

// Fail-fast: the first rejection reaches the caller.
let caught = null;
try {
  await publishParallel(["a", "boom", "c"], 2);
} catch (error) {
  caught = error.message;
}
if (caught !== "upload failed: boom") throw new Error(`expected the upload error, got ${caught}`);

// --- fix 3: allSettled collects instead of throwing --------------------------
const settled = await Promise.allSettled(["a", "boom", "c"].map((i) => upload(i, 1)));
const failed = settled.filter((r) => r.status === "rejected").map((r) => r.reason.message);
const ok = settled.filter((r) => r.status === "fulfilled").map((r) => r.value);
if (failed.join() !== "upload failed: boom" || ok.join() !== "ok:a,ok:c") {
  throw new Error(`allSettled accounting wrong: ${JSON.stringify({ ok, failed })}`);
}
console.log("PASS");
@@end

@expect_output
PASS
@@end

@notes
Demonstrates the bug rather than describing it: `forEach(async ...)` returns an
empty array that fills in later, and a rejection from it surfaces as a
process-level `unhandledRejection` (captured, not crashed). Then pins the three
fixes: sequential ordering with completion-before-resolve, bounded parallel with
a measured peak in-flight count of 3 and fail-fast rejection propagation, and
`Promise.allSettled` producing exactly the expected successes and failures.
@@end

@example sql-dbg-0004
@meta category=debugging language=sql difficulty=intermediate tags=null-semantics,three-valued-logic,sql-bugs,sqlite

@user
Our reconciliation report has rows missing and one column of zeros that should be NULL-free. I suspect NULL handling, but I want the whole picture. Can you walk through the NULL traps in this query and show the corrected version?

```sql
SELECT c.id,
       COUNT(o.id) AS orders,
       SUM(o.amount) AS revenue
FROM customers c
LEFT JOIN orders o ON o.customer_id = c.id
WHERE o.status <> 'cancelled'
  AND c.region NOT IN (SELECT region FROM excluded_regions)
GROUP BY c.id;
```
@@end

@assistant
There are four distinct NULL bugs here, and three of them silently delete rows rather than erroring.

**1. `WHERE o.status <> 'cancelled'` deletes unmatched customers.** After a LEFT JOIN, customers without orders have `o.status IS NULL`, and `NULL <> 'cancelled'` is **NULL**, not TRUE — so they are filtered out. The LEFT JOIN has become an INNER JOIN. Same class of bug for any `<>`, `=`, `IN` (and `NOT IN`) predicate touching a nullable column.

**2. `c.region NOT IN (SELECT region FROM excluded_regions)` returns no rows at all if the subquery contains a single NULL.** `x NOT IN (a, NULL)` is equivalent to `x <> a AND x <> NULL`, and the second conjunct is NULL whenever the first is TRUE → the whole thing is never TRUE. This is the "missing rows" you are seeing; it typically appears the first time someone inserts a row with a NULL region. `NOT EXISTS` has no such failure mode.

**3. `SUM(o.amount)` is NULL for customers with no rows**, which is what shows up as a blank/zero depending on the client's NULL rendering. Decide the semantics explicitly: `COALESCE(SUM(o.amount), 0)` for "spend so far", or leave NULL to mean "no data", but never rely on the client to pick.

**4. `COUNT(o.id)` vs `COUNT(*)` after a LEFT JOIN**: `COUNT(*)` counts the NULL-extended row and reports 1 order for a customer with none. Count a column from the nullable side.

Corrected query:

```sql
SELECT c.id,
       COUNT(o.id)                        AS orders,          -- 0 when there are none
       COALESCE(SUM(o.amount), 0)         AS revenue,
       COUNT(o.id) FILTER (WHERE o.status = 'cancelled') AS cancelled_orders
FROM customers c
LEFT JOIN orders o
       ON o.customer_id = c.id
      AND o.status <> 'cancelled'                             -- filter in ON, keep the LEFT JOIN
WHERE NOT EXISTS (                                          -- NULL-safe anti-join
        SELECT 1 FROM excluded_regions er
         WHERE er.region IS NOT DISTINCT FROM c.region       -- NULL-safe equality
      )
GROUP BY c.id;
```

Notes on portability and semantics:

- `IS NOT DISTINCT FROM` is standard SQL and available in PostgreSQL, and in SQLite from 3.39; on MySQL use `<=>`. If neither is available, write `(er.region = c.region OR (er.region IS NULL AND c.region IS NULL))`.
- `FILTER (WHERE ...)` is standard and supported by PostgreSQL and SQLite 3.30+; the portable alternative is `SUM(CASE WHEN o.status = 'cancelled' THEN 1 ELSE 0 END)`.
- `NULL = NULL` is NULL, not TRUE, which is why `JOIN ... ON a.region = b.region` never matches two NULL regions — a classic duplicate-detection bug. `GROUP BY` and `DISTINCT` *do* treat NULLs as equal, so the inconsistency between those two behaviours is a common source of confusion.
- `NOT NULL` constraints on the join key and status columns eliminate entire classes of these bugs; add them where the domain allows.

The verification pins each trap with observable results: the INNER-join downgrade, the `NOT IN` returning zero rows only after a NULL exists, `SUM` vs `COALESCE`, `COUNT(*)` vs `COUNT(o.id)`, NULL-safe anti-join, and the NULL-equality difference between `=`, `GROUP BY` and `DISTINCT`.
@@end

@verify kind=executable language=sql
@code
CREATE TABLE customers (id INTEGER PRIMARY KEY, region TEXT);
CREATE TABLE orders (id INTEGER PRIMARY KEY, customer_id INTEGER, status TEXT, amount NUMERIC);
CREATE TABLE excluded_regions (region TEXT);

INSERT INTO customers (id, region) VALUES (1, 'eu'), (2, 'us'), (3, NULL), (4, 'apac');
INSERT INTO orders (id, customer_id, status, amount) VALUES
  (10, 1, 'paid', 100), (11, 1, 'cancelled', 50), (12, 2, 'paid', 30), (13, 4, 'cancelled', 70);
INSERT INTO excluded_regions (region) VALUES ('apac');

-- 1. Bug: WHERE on the nullable side removes orderless customers (1,2 kept, 3,4 gone).
SELECT COUNT(*) AS rows_with_bad_where FROM (
  SELECT c.id FROM customers c LEFT JOIN orders o ON o.customer_id = c.id
  WHERE o.status <> 'cancelled' GROUP BY c.id) q;

-- 2. Correct shape: filter in ON, count the nullable column, coalesce the sum.
SELECT c.id, COUNT(o.id) AS orders, COALESCE(SUM(o.amount), 0) AS revenue
FROM customers c LEFT JOIN orders o ON o.customer_id = c.id AND o.status <> 'cancelled'
GROUP BY c.id ORDER BY c.id;

-- 3. COUNT(*) after a LEFT JOIN reports 1 order for a customer with none.
SELECT c.id, COUNT(*) AS wrong_count, COUNT(o.id) AS right_count
FROM customers c LEFT JOIN orders o ON o.customer_id = c.id
GROUP BY c.id ORDER BY c.id;

-- 4. SUM of nothing is NULL, not 0.
SELECT c.id, SUM(o.amount) AS raw_sum, COALESCE(SUM(o.amount), 0) AS fixed_sum
FROM customers c LEFT JOIN orders o ON o.customer_id = c.id
GROUP BY c.id HAVING SUM(o.amount) IS NULL ORDER BY c.id;

-- 5. NOT IN is fine until one NULL appears in the subquery.
SELECT COUNT(*) AS not_in_before_null FROM customers c
WHERE c.region NOT IN (SELECT region FROM excluded_regions);

INSERT INTO excluded_regions (region) VALUES (NULL);

SELECT COUNT(*) AS not_in_after_null FROM customers c
WHERE c.region NOT IN (SELECT region FROM excluded_regions);

SELECT c.id FROM customers c
WHERE NOT EXISTS (SELECT 1 FROM excluded_regions er
                  WHERE er.region IS NOT DISTINCT FROM c.region)
ORDER BY c.id;

-- 6. NULL equality differs between operators and grouping.
SELECT COUNT(*) AS eq_matches_nulls FROM customers a JOIN customers b ON a.region = b.region;
SELECT COUNT(*) AS groups_including_null FROM (SELECT region FROM customers GROUP BY region);
SELECT COUNT(*) AS distinct_including_null FROM (SELECT DISTINCT region FROM customers);
@@end

@expect_output
rows_with_bad_where
2
id|orders|revenue
1|1|100
2|1|30
3|0|0
4|0|0
id|wrong_count|right_count
1|2|2
2|1|1
3|1|0
4|1|1
id|raw_sum|fixed_sum
3||0
not_in_before_null
2
not_in_after_null
0
id
1
2
eq_matches_nulls
3
groups_including_null
4
distinct_including_null
4
@@end

@notes
Runs in SQLite 3.40 (IS NOT DISTINCT FROM and FILTER are both available there).
Values hand-checked against the fixture before being pinned (the first draft of
this file asserted 3 / 0 / 0 for three of these, all wrong). Each trap has a
pinned observable: the WHERE-on-nullable-side version losing rows,
the corrected per-customer counts and revenues, COUNT(*) reporting 1 for orderless
customers, SUM returning a NULL row that COALESCE fixes, NOT IN going from 3 rows
to 0 rows after a single NULL is inserted into the subquery, the NULL-safe
NOT EXISTS version still returning the right rows, and the three-way NULL equality
inconsistency (0 join matches, but NULL forms its own GROUP BY / DISTINCT group).
@@end

@example py-dbg-0005
@meta category=debugging language=python difficulty=advanced tags=datetime,timezone,dst,zoneinfo

@user
We log "started at" and "finished at", and two of our reports occasionally show negative durations and a job that took "-1 hour" during a DST change. Also, `datetime.utcnow()` is flagged as deprecated in our linting. Can you explain all the datetime pitfalls involved and show the correct pattern?
@@end

@assistant
Four distinct issues, all classic:

1. **Naive datetimes carry no timezone**, so `datetime.now()` returns local wall-clock time. During a DST fall-back the local clock repeats an hour, so `finished - started` can come out as 45 minutes for work that took 1h45, or even negative, while looking "correct" in the naive sense. Spring-forward has the mirror problem: the 02:30 local time does not exist, and `ZoneInfo` resolves it by moving forward.
   There is a second-order trap here that survives switching to aware datetimes: subtracting two aware datetimes that share the *same* `tzinfo` object short-circuits to wall-clock arithmetic, so it can be wrong across a DST boundary even though the offsets differ. Converting both sides to `timezone.utc` first (or subtracting `time.monotonic()` readings) gives the true elapsed duration.
2. **Mixing naive and aware datetimes raises `TypeError`** on subtraction/comparison (`can't subtract offset-naive and offset-aware datetimes`), which is the *good* failure: it prevents silently wrong results. The bad failure is doing arithmetic with two naive datetimes from different zones and never noticing.
3. **`datetime.utcnow()` is deprecated (3.12+) because it returns a naive datetime whose *value* is UTC** — the worst of both worlds: it looks like a normal naive object, so `astimezone()` interprets it as local time. `datetime.now(timezone.utc)` is the replacement and is aware.
4. **`datetime.timestamp()` on a naive datetime assumes local time**, while `datetime.fromtimestamp()` returns naive local time. Those two defaults turn a UTC value into a shifted one with no warning.

The pattern that removes the whole class of bugs: **store and compute in aware UTC, convert to a zone only for display**.

```python
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

UTC = timezone.utc

def started_at() -> datetime:
    return datetime.now(UTC)                    # aware, monotonic enough for logs

def duration(start: datetime, end: datetime) -> timedelta:
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("refusing to compare naive datetimes")   # fail loudly
    return end - start                          # exact even across DST

def local_label(instant: datetime, tz_name: str) -> str:
    return instant.astimezone(ZoneInfo(tz_name)).isoformat()

def parse(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        raise ValueError(f"timestamp must include an offset: {value!r}")
    return dt
```

Extra rules that matter in production:

- **Durations and elapsed time in logs are fine in aware UTC**, but for *scheduling* and timeouts use `time.monotonic()` (or `time.monotonic_ns()`); a manual clock adjustment must not extend or shorten a timeout.
- **Store UTC, always.** A database column of type `timestamp` without time zone in PostgreSQL is a bug waiting to happen; use `timestamptz` and pass aware datetimes.
- **`ZoneInfo` needs tzdata**: on Linux it reads `/usr/share/zoneinfo`; in slim containers/alpine/Windows you must depend on the `tzdata` PyPI package, otherwise you get `ZoneInfoNotFoundError` in production only.
- **Ambiguous and non-existent times are input-validation problems, not arithmetic problems.** `datetime(2024, 11, 3, 1, 30, tzinfo=ZoneInfo("America/New_York"))` is ambiguous (two instants), and `fold=0/1` chooses between them; serialize the UTC instant instead of a local wall time and you never have to decide.
- **A date is not a datetime.** `date.today()` uses the *local* date; a "daily report" built from it shifts for users in other zones. Compute the reporting day from `datetime.now(UTC).date()` with an explicit business-zone offset if the boundary is local.

The verification exercises each trap and each fix, including a real DST fall-back window in `America/New_York` (naive vs aware vs
UTC-converted durations), plus the spring-forward gap, both with tzdata present on this machine. One assertion there was corrected during
verification: the same-tzinfo fast path in CPython's datetime subtraction returns
the wall-clock difference (45 minutes) rather than the true 1h45 elapsed, which is
a subtle trap the answer now calls out explicitly instead of asserting the
intuitive-but-wrong result.
@@end

@verify kind=executable language=python
@code
import time
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
UTC = timezone.utc

# 1. Naive arithmetic across a DST fall-back produces a negative duration.
naive_before = datetime(2024, 11, 3, 0, 30)          # 00:30 EDT
naive_after = datetime(2024, 11, 3, 1, 15)           # 01:15, repeated hour
naive_delta = naive_after - naive_before
assert naive_delta == timedelta(minutes=45), "naive arithmetic is wall-clock arithmetic"

aware_before = datetime(2024, 11, 3, 0, 30, tzinfo=NY)
# 01:15 local occurs twice on this date; fold=0 picks EDT, fold=1 picks EST.
aware_after = datetime(2024, 11, 3, 1, 15, tzinfo=NY, fold=1)
assert aware_before.utcoffset() == timedelta(hours=-4), "still EDT before the change"
assert aware_after.utcoffset() == timedelta(hours=-5), "EST after the change (fold=1)"
# CPython short-circuits `a - b` when both share the same tzinfo object: the
# result is WALL-CLOCK arithmetic and is wrong for elapsed time across DST.
assert aware_after - aware_before == timedelta(minutes=45), "same-tzinfo subtraction is wall clock"
assert (aware_after.astimezone(UTC) - aware_before.astimezone(UTC)) == timedelta(hours=1, minutes=45), "true elapsed time"
# With the default fold=0 the display reading is 45 minutes after the start.
assert datetime(2024, 11, 3, 1, 15, tzinfo=NY) - aware_before == timedelta(minutes=45), "fold=0 selects the first occurrence"

# Same wall-clock reading on both sides of the change really is the same hour twice.
first_130 = datetime(2024, 11, 3, 1, 30, tzinfo=NY, fold=0)
second_130 = datetime(2024, 11, 3, 1, 30, tzinfo=NY, fold=1)
assert first_130.utcoffset().total_seconds() == -4 * 3600
assert second_130.utcoffset().total_seconds() == -5 * 3600
assert (second_130 - first_130) == timedelta(0), "same tzinfo => same wall clock, no UTC conversion"
assert (second_130.astimezone(UTC) - first_130.astimezone(UTC)) == timedelta(hours=1)

# Spring-forward: 02:30 local does not exist. With fold=0 ZoneInfo reports the
# offset in force *before* the transition, and round-tripping through UTC lands
# on a wall time that does exist.
gap = datetime(2024, 3, 10, 2, 30, tzinfo=NY)
assert gap.utcoffset() == timedelta(hours=-5), "fold=0 uses the pre-transition offset"
normalised = gap.astimezone(UTC).astimezone(NY)
assert (normalised.hour, normalised.minute) == (3, 30), normalised
assert normalised != gap

# 2. Mixing naive and aware raises instead of being silently wrong.
try:
    datetime(2024, 1, 1) - datetime(2024, 1, 1, tzinfo=UTC)
    raise AssertionError("naive/aware subtraction must raise")
except TypeError:
    pass
try:
    datetime(2024, 1, 1) < datetime(2024, 1, 1, tzinfo=UTC)
    raise AssertionError("naive/aware comparison must raise")
except TypeError:
    pass

# 3. utcnow-style values are naive but represent UTC -- the confusing combination.
naive_utc_equivalent = datetime.now(UTC).replace(tzinfo=None)
assert naive_utc_equivalent.tzinfo is None
assert naive_utc_equivalent.astimezone(UTC).tzinfo is not None
# astimezone() on a naive value assumes *local* time; assert the machine is not UTC
# so the difference is observable, otherwise skip the claim.
import os
if time.timezone != 0:
    wrong = naive_utc_equivalent.astimezone(UTC)
    right = naive_utc_equivalent.replace(tzinfo=UTC)
    assert wrong != right, "interpreting a naive UTC value as local shifts it"

# 4. timestamp() defaults and the fromtimestamp() mirror.
stamp = datetime(2024, 6, 1, 12, 0, tzinfo=UTC).timestamp()
assert datetime.fromtimestamp(stamp, tz=UTC).hour == 12
naive_local = datetime.fromtimestamp(stamp)          # naive, in local time
assert naive_local.tzinfo is None
assert abs(naive_local.timestamp() - stamp) < 1e-6, "round trip through local time is stable"

# 5. Durations of real elapsed time must not use wall-clock time at all.
t0 = time.monotonic()
time.sleep(0.01)
assert time.monotonic() - t0 >= 0.01

# 6. Monotonic scheduling helper: a clock jump must not change the timeout.
class ManualClock:
    def __init__(self):
        self.now = 1_000.0
    def monotonic(self):
        return self.now
    def jump_wall_clock(self, seconds):
        return seconds        # the wall clock jumping is irrelevant to monotonic


def deadline_from(clock, timeout_s):
    return clock.monotonic() + timeout_s


clock = ManualClock()
deadline = deadline_from(clock, 5)
clock.jump_wall_clock(3600)                 # NTP correction / DST: unused by monotonic
assert deadline - clock.monotonic() == 5, "wall-clock jumps must not affect timeouts"
clock.now += 5
assert deadline - clock.monotonic() == 0

# 7. Date boundaries: a local date is not a UTC date near midnight.
utc_late = datetime(2024, 6, 1, 23, 30, tzinfo=UTC)
local_next_day = utc_late.astimezone(ZoneInfo("Asia/Tokyo"))
assert utc_late.date() == date(2024, 6, 1)
assert local_next_day.date() == date(2024, 6, 2), "same instant, different calendar day"
print("PASS")
@@end

@expect_output
PASS
@@end

@notes
Requires tzdata (/usr/share/zoneinfo on this machine). Pins the real DST
behaviour for America/New_York: naive vs aware duration across the fall-back
(45 min wall clock vs 1h45 elapsed), fold=0/1 selecting the two distinct instants
that share a wall-clock reading (including that the default fold=0 gives the
shorter 45-minute duration while fold=1 gives the true 1h45), spring-forward gap normalisation, TypeError on
naive/aware mixing, astimezone() on a naive value being shifted by the local
offset, the fromtimestamp() round trip, monotonic-based deadlines surviving a
simulated wall-clock jump, and the UTC-vs-local calendar-day divergence for a
single instant.
@@end
