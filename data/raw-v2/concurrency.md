@example conc-0001
@meta category=concurrency language=python difficulty=intermediate tags=lost-update,read-modify-write,gil,locks

@user
Our request counter under-reports under load — the dashboard total is always a bit lower than the logged request count, and it never reproduces on my laptop. The update path is one line in a Flask hook:

```python
class RequestCounter:
    def __init__(self):
        self.value = 0

    def bump(self):
        self.value += 1        # called from every worker thread
```

I was told "Python has the GIL, so `+= 1` is safe". Is that true?
@@end

@assistant
No. The GIL makes **individual bytecode operations** atomic, not **statements**, and `self.value += 1` compiles to a read, an add and a write:

```
LOAD_FAST self          -> get the counter object
LOAD_ATTR value         -> READ the current value
LOAD_CONST 1
BINARY_OP +=            -> compute
STORE_ATTR value        -> WRITE the new value
```

The GIL can be released between `LOAD_ATTR` and `STORE_ATTR` (bytecode boundaries are exactly where the interpreter checks for thread switches), so two threads can both read 41, both compute 42, and both write 42 — one increment is lost. This is the classic **check-then-act / read-modify-write race**, and it also applies to `count += 1` on a plain int, `cache[key] = cache.get(key, 0) + 1`, and any "read, decide, write" sequence across threads, processes, or requests.

What *is* atomic under the GIL: single built-in operations, such as `list.append`, `dict[k] = v`, or `set.add` — those are one bytecode call into C and the GIL is not released mid-operation. That asymmetry is why the folklore exists: `results.append(x)` from many threads really is safe, and `self.value += 1` really is not.

The fix is to make the operation atomic as seen by other threads:

```python
import threading

class RequestCounter:
    def __init__(self):
        self.value = 0
        self._lock = threading.Lock()

    def bump(self):
        with self._lock:            # one owner at a time: read+add+write is now atomic
            self.value += 1
```

Alternatives, depending on what the counter protects:

- **Use the interpreter's atomic building block**: `collections.Counter` has no atomic `+=` either, but a `threading.Lock` + dict, or a `queue.Queue` of events that a single consumer drains, both avoid the race by construction.
- **Push it into the database**: `UPDATE counters SET n = n + 1 WHERE name = 'requests'` is atomic inside the database, which also covers the multi-*process* case (gunicorn workers) that a lock cannot fix.
- **Sharded counters** for hot paths: N counters indexed by thread id, summed on read.

Two things to keep in mind beyond CPython: the GIL is an implementation detail that is going away in free-threaded builds, where even the "atomic" built-ins need synchronization; and in a multi-process deployment, an in-process lock is worthless — each worker has its own counter object and the lost updates happen at the database or shared-cache layer instead.
@@end

@verify kind=executable language=python
@code
import dis
import threading
from threading import Barrier


class Counter:
    """Read-modify-write with no lock: the code under review."""

    def __init__(self, parties=2):
        self.value = 0
        self.barrier = Barrier(parties)

    def bump(self):
        current = self.value            # READ
        self.barrier.wait()             # both threads are now between read and write
        self.value = current + 1        # WRITE


class LockedCounter:
    def __init__(self):
        self.value = 0
        self._lock = threading.Lock()

    def bump(self):
        with self._lock:
            self.value += 1


def hammer(target, thread_count, per_thread):
    def worker():
        for _ in range(per_thread):
            target.bump()

    threads = [threading.Thread(target=worker) for _ in range(thread_count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()


# 1. the lost update, made deterministic with a barrier instead of hoping for a timing
#    window: both bumps read 0, then both write 1
counter = Counter(2)
threads = [threading.Thread(target=counter.bump) for _ in range(2)]
for thread in threads:
    thread.start()
for thread in threads:
    thread.join()
print("two bumps without a lock:", counter.value, "(expected 2)")

# 2. the bytecode is the explanation: read and write are separate steps
def compiled_bump(self):
    self.value += 1

opnames = [instruction.opname for instruction in dis.get_instructions(compiled_bump)]
print("bytecode:", ",".join(opnames))
print("separate read then write:", "LOAD_ATTR" in opnames and "STORE_ATTR" in opnames)

# 3. with a lock the same hammering is exact
exact = LockedCounter()
hammer(exact, thread_count=8, per_thread=2_500)
print("8 threads x 2500 locked bumps:", exact.value)

# 4. the contrast that keeps the folklore alive: built-in operations are atomic under
#    the GIL, so an append-per-thread really does not lose anything
shared_list = []
def append_worker():
    for index in range(5_000):
        shared_list.append(index)
appenders = [threading.Thread(target=append_worker) for _ in range(8)]
for thread in appenders:
    thread.start()
for thread in appenders:
    thread.join()
print("8 threads x 5000 appends:", len(shared_list))

# 5. a multi-process deployment cannot be fixed by an in-process lock: two objects
#    means two counters, and the update is lost at the shared store instead
first, second = LockedCounter(), LockedCounter()
first.bump()
second.bump()
print("two objects, two counters:", first.value + second.value, "(expected 2)")

assert counter.value == 1, "the barrier guarantees the lost update is deterministic"
assert counter.value != 2
assert "STORE_ATTR" in opnames and "LOAD_ATTR" in opnames
assert opnames.index("LOAD_ATTR") < opnames.index("STORE_ATTR")
assert exact.value == 20_000, exact.value
assert len(shared_list) == 40_000, "built-in append is atomic under the GIL"
assert first.value + second.value == 2 and first.value == second.value == 1
print("PASS")
@@end

@expect_output
two bumps without a lock: 1 (expected 2)
bytecode: RESUME,LOAD_FAST,COPY,LOAD_ATTR,LOAD_CONST,BINARY_OP,SWAP,STORE_ATTR,LOAD_CONST,RETURN_VALUE
separate read then write: True
8 threads x 2500 locked bumps: 20000
8 threads x 5000 appends: 40000
two objects, two counters: 2 (expected 2)
PASS
@@end

@notes
Reproduces the lost update deterministically with a `Barrier` that parks both threads
between the read and the write, so the outcome is 1 instead of 2 on every run — no
timing luck involved, which is exactly why the flaky-production / green-CI split
happens. The bytecode listing is printed to justify the claim (separate `LOAD_ATTR`
and `STORE_ATTR`), the locked hammer is asserted to be exact (8 × 2500 = 20 000), and
the contrast with `list.append` (40 000 appends from 8 threads with no loss) shows why
the GIL folklore exists and where it stops being true. The last section pins the
multi-process case: per-object locks cannot protect a counter that lives in a shared
store.
@@end

@example conc-0002
@meta category=concurrency language=python difficulty=advanced tags=asyncio,event-loop,blocking-calls,to_thread

@user
Our async HTTP service stalls every few seconds: one handler does CPU-ish work and calls a synchronous client library, and during those calls every other in-flight request freezes. Reviewer says "just mark the function `async`, the loop will handle it". The handler looks like:

```python
async def fetch_report(request):
    report = legacy_client.generate(...)     # blocking, ~50-200 ms
    return json_response(report)
```

Why does marking it `async` not help, and how do I show the starvation rather than argue about it?
@@end

@assistant
`async def` is a promise to the *caller*, not a magic wand: the event loop runs your coroutine on a single thread, and a normal function call inside it blocks that thread until it returns. While `legacy_client.generate(...)` runs, the loop cannot service timers, cannot resume other coroutines, cannot accept connections — everything freezes for 50-200 ms, which is exactly the stall you see. Marking the function `async` changes nothing about where the work happens; you need to move the blocking work either off the loop thread or into something the loop can await.

The two correct shapes:

```python
import asyncio

async def fetch_report(request):
    # 1. run blocking I/O / CPU work in a worker thread (default pool)
    report = await asyncio.to_thread(legacy_client.generate, ...)
    return json_response(report)

async def fetch_report_http(request):
    # 2. or use an async client and await the real I/O
    async with httpx.AsyncClient() as client:
        response = await client.get(...)
    return json_response(response.json())
```

Which to choose: `asyncio.to_thread` for a library you cannot replace (it uses the default `ThreadPoolExecutor`, so bound it — the pool's `max_workers` limits concurrency, and a slow library can saturate it); a genuine async client when one exists; `loop.run_in_executor` when you need a dedicated pool; and `multiprocessing`/a worker queue for CPU-bound work in a world without the GIL (or when the work holds the GIL and threads do not help — that is a different diagnosis: check CPU time, not just latency).

**How to show starvation without a profiler.** Schedule a callback with `loop.call_later(...)` and then make the handler block: the loop cannot run the expired timer until the blocking call returns, so the callback is still pending immediately after the call while it has already fired after an `await`. That is a deterministic observation — no wall-clock comparison, no flake:

```python
fired = []
loop.call_later(0.01, lambda: fired.append("timer"))
time.sleep(0.05)                       # blocking: the timer expired but cannot run
pending_right_after = list(fired)      # [] -> starvation, proven
await asyncio.sleep(0.01)              # a short awaited delay: the loop catches up now
```

Practical rules: audit for synchronous calls inside `async def` (DB drivers, `requests`, `time.sleep`, file I/O, DNS, `json.load` on huge payloads); prefer `await asyncio.sleep(...)` over `time.sleep(...)`; and add a loop-lag metric (`loop.time()` sampled by a background task) so this class of regression shows up in production as a number rather than as user complaints.
@@end

@verify kind=executable language=python
@code
import asyncio
import time


class LoopLag:
    """Samples how late the loop is compared with its own schedule."""

    def __init__(self):
        self.samples = []


async def main():
    # --- part 1: a blocking call inside a coroutine starves the loop -------------
    fired = []
    loop = asyncio.get_running_loop()
    loop.call_later(0.01, lambda: fired.append("timer"))
    time.sleep(0.05)                      # the handler that should have been awaited
    pending_after_block = list(fired)
    await asyncio.sleep(0.01)             # a real awaited delay: the loop can run it now
    fired_after_yield = list(fired)
    print("timer fired while blocked:", bool(pending_after_block))
    print("timer fired once the loop was free:", bool(fired_after_yield))

    # --- part 2: the same code moved off the loop --------------------------------
    fired.clear()
    loop.call_later(0.01, lambda: fired.append("timer"))
    await asyncio.to_thread(time.sleep, 0.05)     # blocking work, worker thread
    print("timer fired during to_thread:", bool(fired))

    # --- part 3: awaited I/O never starves ---------------------------------------
    fired.clear()
    loop.call_later(0.01, lambda: fired.append("timer"))
    await asyncio.sleep(0.05)                     # yields to the loop
    print("timer fired during await sleep:", bool(fired))

    # --- part 4: three handlers, timed both ways ---------------------------------
    def blocking_handler(seconds):
        time.sleep(seconds)
        return seconds

    started = loop.time()
    for _ in range(3):
        blocking_handler(0.05)                    # serialised: the loop is the bottleneck
    serial = loop.time() - started

    started = loop.time()
    await asyncio.gather(*(asyncio.to_thread(blocking_handler, 0.05) for _ in range(3)))
    concurrent = loop.time() - started
    print("three handlers serialized:", serial >= 0.15)
    print("three handlers concurrent:", concurrent < 0.13)

    # --- part 5: loop-lag sampling catches the class of bug, not just one call ---
    async def lag_sampler(report):
        while True:
            started = loop.time()
            await asyncio.sleep(0.005)
            report.samples.append(loop.time() - started)

    report = LoopLag()
    sampler = asyncio.create_task(lag_sampler(report))
    await asyncio.sleep(0.03)
    await asyncio.to_thread(time.sleep, 0.1)      # a slow dependency, off-loop
    await asyncio.sleep(0.01)
    sampler.cancel()
    worst = max(report.samples)
    print("loop-lag samples taken:", len(report.samples) > 0)
    print("worst lag stays small with to_thread:", worst < 0.2)

    assert pending_after_block == [], "a blocking call starves the loop: the timer is stuck"
    assert fired_after_yield == ["timer"], "it fires as soon as the loop runs again"
    assert fired == ["timer"], "to_thread keeps the loop servicing timers"
    assert serial >= 0.15 and concurrent < 0.13
    assert max(report.samples) >= 0.005
    assert worst < 0.2


asyncio.run(main())
print("PASS")
@@end

@expect_output
timer fired while blocked: False
timer fired once the loop was free: True
timer fired during to_thread: True
timer fired during await sleep: True
three handlers serialized: True
three handlers concurrent: True
loop-lag samples taken: True
worst lag stays small with to_thread: True
PASS
@@end

@notes
Proves starvation with a pending-timer observation rather than a wall-clock
comparison: a timer scheduled 10 ms out is still unfired immediately after a blocking
`time.sleep(0.05)` inside a coroutine (the loop could not run it), and fires as soon as
the coroutine awaits an actual delay (a bare `sleep(0)` yield only hands control to
ready callbacks; expired timers need a loop iteration) — deterministic, no flake. The same timer is shown to fire during
`asyncio.to_thread(...)` and during `await asyncio.sleep(...)`, three blocking handlers
are shown to serialize when called directly versus run concurrently through the thread
pool, and a loop-lag sampler is included as the production check for this regression
class. Timing assertions use order-of-magnitude margins (0.15 s vs 0.13 s) so they do
not depend on machine speed.
@@end

@example conc-0003
@meta category=concurrency language=python difficulty=advanced tags=deadlock,lock-ordering,rlock,timeouts

@user
Our transfer service locks two account objects and occasionally stops serving requests entirely — a thread dump shows every worker waiting on a mutex. It happens more when one particular pair of accounts is involved:

```python
def transfer(from_account, to_account, amount):
    with from_account.lock:
        with to_account.lock:
            from_account.balance -= amount
            to_account.balance += amount
```

Why does it hang, and how should it be written so it cannot hang? I would also like a test that proves the deadlock exists instead of waiting for it to happen in production.
@@end

@assistant
This is a **lock-ordering deadlock**: the cycle needs only two threads. Thread A calls `transfer(x, y, 10)` and holds `x.lock`, waiting for `y.lock`; thread B calls `transfer(y, x, 10)` and holds `y.lock`, waiting for `x.lock`. Neither can proceed, neither will ever release, and every other worker that needs either account queues up behind them — which is why the service freezes rather than merely slowing down. It happens "more with one particular pair" because a cycle needs two transfers in opposite directions at overlapping times; the probability scales with how often that pair is touched.

The fix that makes the hang structurally impossible is a **global lock order**: both threads must acquire the same locks in the same order, regardless of argument order.

```python
def transfer(from_account, to_account, amount):
    if from_account is to_account:
        with from_account.lock:
            ...                              # single-lock case, no ordering question
        return
    first, second = sorted((from_account, to_account), key=lambda account: account.uid)
    with first.lock:
        with second.lock:
            from_account.balance -= amount
            to_account.balance += amount
```

Key the order on an immutable unique field (`uid`, primary key) — never on `id()`, whose values are memory addresses that get reused after garbage collection, and never on a mutable attribute. Any total order works; consistency is what matters.

Other options and their trade-offs:

- **Timeouts**: `lock.acquire(timeout=0.5)` converts a deadlock into a retryable error. That is a safety net, not a design — the cycle still exists.
- **One lock for the group**: a single service-level lock removes ordering concerns at the cost of throughput; a lock stripe keyed by hash is the middle ground.
- **Try-lock with backoff**: acquire the second with `blocking=False`; on failure, release the first and retry after a random delay. Correct, but it can livelock under contention.
- **Queue the work**: a single-writer executor for account mutations is serial and therefore deadlock-free; throughput becomes the design question.

Two related traps that look identical in a thread dump: `threading.Lock` is **not reentrant** (a thread that re-acquires its own lock blocks forever — use `RLock` when one locked method calls another), and the ordering rule is only as good as its worst call site, so route every multi-lock acquisition through one helper (`lock_pair(a, b)`) instead of trusting reviewers to notice.

For the test, do not wait for a hang and do not race a timeout — **sample the deadlock while it is a stable state**. Each thread takes its first lock, announces it, waits for the other's announcement, and then keeps trying the second lock with `acquire(blocking=False)`. While both are holding, every non-blocking attempt must fail, and that observation is deterministic:

```python
def worker(source, destination, holds, observed, stop, failures):
    source.lock.acquire()
    try:
        holds[source.uid].set()                      # "I hold my lock"
        holds[other.uid].wait()                      # ... and you hold yours
        while not stop.is_set():
            if destination.lock.acquire(blocking=False):
                raise AssertionError("the ordering bug is fixed: this must never succeed")
            failures[source.uid] += 1
    finally:
        source.lock.release()
```

The harness waits until both threads have recorded failed attempts, asserts that both locks are still held and both threads are alive, and only then sets `stop` — so the cycle is proven rather than timed. In production you cannot tell the service to stop, which is why `acquire(timeout=...)` exists as a safety net and a canonical lock order exists as the actual fix.
@@end

@verify kind=executable language=python
@code
import threading


class Account:
    def __init__(self, uid, balance):
        self.uid = uid
        self.balance = balance
        self.lock = threading.Lock()


def transfer_ordered(source, destination, amount):
    """Canonical ordering: the two-lock acquisition is always in uid order."""
    if source is destination:
        with source.lock:
            source.balance -= amount
            destination.balance += amount
        return
    first, second = sorted((source, destination), key=lambda account: account.uid)
    with first.lock:
        with second.lock:
            source.balance -= amount
            destination.balance += amount


# --- part 1: observe the cycle while it is stable -------------------------------
POLLS = 20


class DeadlockDemo:
    """Two threads, two locks, opposite orders.

    The deadlock is a *stable state*, so the harness observes it - both threads hold
    their own lock and are denied the other's - instead of waiting for a timeout and
    hoping the interleaving worked out.
    """

    def __init__(self, x, y):
        self.x, self.y = x, y
        self.holds = {x.uid: threading.Event(), y.uid: threading.Event()}
        self.polled = {x.uid: threading.Event(), y.uid: threading.Event()}
        self.stop = threading.Event()
        self.failures = {x.uid: 0, y.uid: 0}
        self.successes = {x.uid: 0, y.uid: 0}
        self.threads = []

    def worker(self, source, destination):
        source.lock.acquire()
        try:
            self.holds[source.uid].set()
            if not (self.holds[self.x.uid].wait(5) and self.holds[self.y.uid].wait(5)):
                return                                  # the other thread never got there
            polls = 0
            while not self.stop.is_set():
                if destination.lock.acquire(blocking=False):
                    self.successes[source.uid] += 1     # cannot happen while the other holds it
                    destination.lock.release()
                else:
                    self.failures[source.uid] += 1
                polls += 1
                if polls == POLLS:
                    self.polled[source.uid].set()       # evidence recorded, keep holding
        finally:
            source.lock.release()

    def run(self):
        self.threads = [
            threading.Thread(target=self.worker, args=(self.x, self.y)),
            threading.Thread(target=self.worker, args=(self.y, self.x)),
        ]
        for thread in self.threads:
            thread.start()
        both_polled = all(self.polled[uid].wait(5) for uid in (self.x.uid, self.y.uid))
        evidence = {
            "both threads hold their own lock": all(
                account.lock.locked() for account in (self.x, self.y)),
            "both threads are still running": all(thread.is_alive() for thread in self.threads),
            "both threads reached the observation point": both_polled,
            "every attempt at the other lock failed": all(
                count >= POLLS for count in self.failures.values()),
            "attempts at the other lock that succeeded": sum(self.successes.values()),
        }
        self.stop.set()                                 # break the cycle and let them exit
        for thread in self.threads:
            thread.join(timeout=5)
        return evidence, [thread.is_alive() for thread in self.threads]


demo = DeadlockDemo(Account("acct-x", 100), Account("acct-y", 100))
evidence, still_running = demo.run()
for label, value in evidence.items():
    print(f"  {label}: {value}")
print("threads left running after the cycle was broken:", still_running)

# --- part 2: many threads, both directions, exact conservation ------------------
a, b = Account("acct-a", 1_000), Account("acct-b", 1_000)
errors = []


def churn(rounds, first, second):
    try:
        for _ in range(rounds):
            transfer_ordered(first, second, 1)
            transfer_ordered(second, first, 1)
    except Exception as exc:                            # noqa: BLE001 - reported, not swallowed
        errors.append(repr(exc))


workers = [threading.Thread(target=churn, args=(200, a, b)) for _ in range(6)]
for thread in workers:
    thread.start()
for thread in workers:
    thread.join(timeout=10)
print("concurrent churn errors:", errors)
print("balances after 6 x 400 ordered transfers:", a.balance, b.balance)

# --- part 3: the nearby trap - Lock is not reentrant ---------------------------
plain = threading.Lock()
plain.acquire()
reentrant_ok = plain.acquire(timeout=0.05)              # the owner blocks on itself
plain.release()
recursive = threading.RLock()
recursive.acquire()
reentrant_rlock_ok = recursive.acquire(timeout=0.05)
recursive.release()
recursive.release()
print("plain Lock re-acquired by its owner:", reentrant_ok)
print("RLock re-acquired by its owner:", reentrant_rlock_ok)

assert evidence["both threads hold their own lock"] is True
assert evidence["both threads are still running"] is True
assert evidence["both threads reached the observation point"] is True
assert evidence["every attempt at the other lock failed"] is True
assert evidence["attempts at the other lock that succeeded"] == 0
assert still_running == [False, False], "the harness must break the cycle and finish"
assert errors == [], errors
assert a.balance == 1_000 and b.balance == 1_000, (a.balance, b.balance)
assert reentrant_ok is False and reentrant_rlock_ok is True
print("PASS")
@@end

@expect_output
  both threads hold their own lock: True
  both threads are still running: True
  both threads reached the observation point: True
  every attempt at the other lock failed: True
  attempts at the other lock that succeeded: 0
threads left running after the cycle was broken: [False, False]
concurrent churn errors: []
balances after 6 x 400 ordered transfers: 1000 1000
plain Lock re-acquired by its owner: False
RLock re-acquired by its owner: True
PASS
@@end

@notes
Turns the deadlock into an observation instead of a timing experiment. Two threads take
their own first lock, wait for each other with events, and then keep trying the other's
lock with `acquire(blocking=False)`; because a deadlock is a *stable state*, the harness
can sample it while both threads are still holding: both own locks are locked, both
threads are alive, both reached the observation point, every attempt failed and exactly
zero succeeded - all deterministic, with no timeout racing the scheduler. The harness then
sets a stop flag to break the cycle and confirms both threads exit. The same two accounts
are then hammered by six threads x 400 ordered transfers in both directions, asserted to
raise nothing and to conserve the total exactly, and the run pins non-reentrancy of
`threading.Lock` versus `RLock`, because that failure looks identical in a thread dump.
@@end

@example conc-0004
@meta category=concurrency language=python difficulty=advanced tags=lost-update,sql,sqlite,read-modify-write

@user
Two of our services decrement the same inventory counter and we sometimes oversell: both services read `stock`, compute the new value in application code, and write it back. The SQL is trivial:

```python
row = conn.execute("SELECT stock FROM inventory WHERE sku = ?", (sku,)).fetchone()
new_stock = row["stock"] - quantity
conn.execute("UPDATE inventory SET stock = ? WHERE sku = ?", (new_stock, sku))
conn.commit()
```

Each service's own log looks correct. Where do the updates go, and what is the minimal fix?
@@end

@assistant
This is a **lost update**: the read and the write are two separate statements, so nothing stops the other service from reading the same value in between. Concretely, with stock = 100 and two decrements of 30 and 50:

```
A: read 100          B: read 100
A: write 70, commit
                     B: write 50, commit      <- B's value was computed from 100
final: 50                                     <- the 30 decrement vanished
```

Expected 20, actual 50 — an oversell of 30 units. The tell-tale sign is that each service's log shows the writes it made: a lost update is invisible from either side, which is why it often ships as an "intermittent" inventory mismatch.

The minimal fix is to make the arithmetic happen **inside the database**, so the read and the write are one atomic statement:

```python
conn.execute("UPDATE inventory SET stock = stock - ? WHERE sku = ?", (quantity, sku))
```

Now the database serializes the two updates and the result is 100 - 30 - 50 = 20 regardless of interleaving. Guard the invariant in the same statement, which also closes the overselling path:

```python
with conn:                                   # one transaction, commit or rollback
    cursor = conn.execute(
        "UPDATE inventory SET stock = stock - ? WHERE sku = ? AND stock >= ?",
        (quantity, sku, quantity),
    )
    if cursor.rowcount == 0:
        raise InsufficientStock(sku)         # no rows changed: not enough stock
```

If the value must be computed in application code (a pricing rule, a currency conversion), then keep the whole read-modify-write inside **one transaction that takes the write lock up front** — `BEGIN IMMEDIATE` in SQLite, `SELECT ... FOR UPDATE` in Postgres/MySQL — and re-read inside it:

```python
conn.execute("BEGIN IMMEDIATE")              # writer lock: no other writer can interleave
row = conn.execute("SELECT stock FROM inventory WHERE sku = ?", (sku,)).fetchone()
conn.execute("UPDATE inventory SET stock = ? WHERE sku = ?", (row["stock"] - quantity, sku))
conn.commit()
```

Three supporting points that matter in production:

- **A lock in one process cannot protect a row shared by two services.** The concurrency here is in the database, so the fix must be too.
- **Optimistic concurrency** works when writes are rare: add a `version` column, `UPDATE ... WHERE sku = ? AND version = ?`, and retry when `rowcount == 0`. That converts silent loss into a detectable conflict.
- **Set the busy timeout** (`PRAGMA busy_timeout`, connection `timeout=`) so a second writer waits for the lock instead of failing immediately with "database is locked" — a failed write is loud and safe, a silent lost update is neither.
@@end

@verify kind=executable language=python
@code
import os
import sqlite3
import tempfile

EXPECTED = 100 - 30 - 50


def fresh_connection(path):
    connection = sqlite3.connect(path, timeout=2.0)
    connection.row_factory = sqlite3.Row
    return connection


with tempfile.TemporaryDirectory() as tmp:
    path = os.path.join(tmp, "inventory.sqlite")
    setup = sqlite3.connect(path)
    setup.execute("CREATE TABLE inventory (sku TEXT PRIMARY KEY, stock INTEGER NOT NULL)")
    setup.execute("INSERT INTO inventory VALUES ('widget', 100)")
    setup.commit()
    setup.close()

    # --- part 1: application-level read-modify-write, two connections -----------
    a = fresh_connection(path)
    b = fresh_connection(path)
    a_stock = a.execute("SELECT stock FROM inventory WHERE sku = 'widget'").fetchone()["stock"]
    b_stock = b.execute("SELECT stock FROM inventory WHERE sku = 'widget'").fetchone()["stock"]
    a.execute("UPDATE inventory SET stock = ? WHERE sku = 'widget'", (a_stock - 30,))
    a.commit()
    b.execute("UPDATE inventory SET stock = ? WHERE sku = 'widget'", (b_stock - 50,))
    b.commit()
    lost = a.execute("SELECT stock FROM inventory WHERE sku = 'widget'").fetchone()["stock"]
    print("app-level read-modify-write final stock:", lost, "(expected", EXPECTED, ")")
    print("update lost:", lost != EXPECTED)

    # --- part 2: the same two updates as atomic SQL -----------------------------
    a.execute("UPDATE inventory SET stock = 100 WHERE sku = 'widget'")
    a.commit()
    a.execute("UPDATE inventory SET stock = stock - 30 WHERE sku = 'widget'")
    a.commit()
    b.execute("UPDATE inventory SET stock = stock - 50 WHERE sku = 'widget'")
    b.commit()
    atomic = a.execute("SELECT stock FROM inventory WHERE sku = 'widget'").fetchone()["stock"]
    print("atomic SQL final stock:", atomic)

    # --- part 3: the guard that also prevents overselling -----------------------
    a.execute("UPDATE inventory SET stock = 100 WHERE sku = 'widget'")
    a.commit()
    with a:
        cursor = a.execute(
            "UPDATE inventory SET stock = stock - ? WHERE sku = 'widget' AND stock >= ?",
            (30, 30),
        )
        guarded_first = cursor.rowcount
    with b:
        cursor = b.execute(
            "UPDATE inventory SET stock = stock - ? WHERE sku = 'widget' AND stock >= ?",
            (120, 120),                       # more than remains: must not change anything
        )
        guarded_second = cursor.rowcount
    guarded = a.execute("SELECT stock FROM inventory WHERE sku = 'widget'").fetchone()["stock"]
    print("guarded updates rows changed:", guarded_first, guarded_second,
          "| stock:", guarded)

    # --- part 4: a real transaction takes the write lock before reading ----------
    a.execute("UPDATE inventory SET stock = 100 WHERE sku = 'widget'")
    a.commit()
    a.execute("BEGIN IMMEDIATE")              # writer lock held for the whole read-modify-write
    row = a.execute("SELECT stock FROM inventory WHERE sku = 'widget'").fetchone()
    a.execute("UPDATE inventory SET stock = ? WHERE sku = 'widget'", (row["stock"] - 25,))
    a.commit()
    b.execute("BEGIN IMMEDIATE")              # waits for, then sees, a's committed value
    row = b.execute("SELECT stock FROM inventory WHERE sku = 'widget'").fetchone()
    b.execute("UPDATE inventory SET stock = ? WHERE sku = 'widget'", (row["stock"] - 5,))
    b.commit()
    transactional = a.execute("SELECT stock FROM inventory WHERE sku = 'widget'").fetchone()["stock"]
    print("transactional read-modify-write final stock:", transactional, "(expected 70)")

    # --- part 5: configuration that decides what happens under contention --------
    busy_timeout = a.execute("PRAGMA busy_timeout").fetchone()[0]
    print("busy_timeout in ms:", busy_timeout)
    print("journal mode:", a.execute("PRAGMA journal_mode").fetchone()[0])

    a.close()
    b.close()

assert lost == 50, "the lost update, reproduced exactly"
assert lost != EXPECTED
assert atomic == EXPECTED, atomic
assert (guarded_first, guarded_second) == (1, 0), "the guard must refuse the oversell"
assert guarded == 70, guarded
assert transactional == 70, transactional
assert busy_timeout == 2000, busy_timeout
print("PASS")
@@end

@expect_output
app-level read-modify-write final stock: 50 (expected 20 )
update lost: True
atomic SQL final stock: 20
guarded updates rows changed: 1 0 | stock: 70
transactional read-modify-write final stock: 70 (expected 70)
busy_timeout in ms: 2000
journal mode: delete
PASS
@@end

@notes
Pins the lost update with exact numbers rather than a timing race: two connections
read stock = 100, each computes its own new value, and the second commit overwrites the
first (final 50 instead of 20), which is precisely the oversell. Rewriting the same two
decrements as `SET stock = stock - ?` yields 20, the guarded statement
(`AND stock >= ?`) is asserted to change 1 row then 0 rows and leave stock at 70, and a
`BEGIN IMMEDIATE` transaction that re-reads inside the lock also lands on 70. The
connection's `busy_timeout` is pinned as the setting that turns contention into waiting
rather than an immediate "database is locked" failure.
@@end
