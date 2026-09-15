@example trc-0001
@meta category=execution_tracing language=python difficulty=intermediate tags=iterators,generators,exhaustion,tracing

@user
This scanner reads a stream, then reports on it. The report is always empty even though the scan log says it read 400 records, and adding a debug print inside the report loop printed nothing at all.

```python
def scan(rows):
    return (row for row in rows if row["qty"] > 0)      # generator


def summarise(stream):
    total = sum(row["qty"] for row in stream)           # first pass
    top = max((row["qty"] for row in stream), default=0)  # second pass
    return {"total": total, "top": top}


def pipeline(rows):
    stream = scan(rows)
    summary = summarise(stream)
    audit = [row["id"] for row in stream]               # third pass
    return summary, audit
```

Both loops are written against the same `stream`, and the helper looks pure. Where is the information lost, and what is the rule about passing iterables between functions?
@@end

@assistant
`scan` returns a **generator**, and a generator is a one-shot iterator: the first `for` loop that consumes it exhausts it, and every later loop body never executes. The empty print is the giveaway that no data was skipped — the loop simply had nothing to iterate. `sum(...)` consumed all 400 records inside `summarise`, so `max(...)` saw an empty iterator (hence the silent `default=0`) and `audit` was always `[]`.

The underlying rule: **an iterable and an iterator are not interchangeable in a function signature.** `list`, `dict` and `tuple` are re-iterable containers; generators, `map`, `filter`, `zip` and file objects are iterators that are consumed once and then permanently empty. A function that loops twice must either accept a re-iterable container or materialise the iterator once at the top (`rows = list(rows)`).

That also explains the two facts that made this hard to see: `iter(x) is x` is True exactly for iterators, and this identity is what a "is my stream reusable?" check in a code review should look at. A second, subtler consequence: partially consuming an iterator loses the rest — `next(stream)` in one place silently steals the first row from every later consumer, with no error anywhere.

```python
def summarise(rows):
    """Accept an iterable; materialise once so two passes are possible."""
    data = list(rows)                    # one pass here, then reuse the list
    total = sum(row["qty"] for row in data)
    top = max((row["qty"] for row in data), default=0)
    return {"total": total, "top": top, "count": len(data)}


def pipeline(rows):
    stream = scan(rows)
    summary = summarise(stream)          # takes ownership of the iterator
    audit = [row["id"] for row in summary]  # no: audit must be built from the data
    return summary
```

Better still, make ownership explicit in the name — `summarise_once(it)` versus `summarise(rows)` — or return a summary object that carries the rows it consumed. For genuinely large streams, do not materialise: compute both aggregates in a **single** pass and keep only what you need (`total += row["qty"]; top = max(top, row["qty"])`), which also fixes the O(n) memory cost of the `list(...)` version. A trace of `next()` calls, or asserting `iter(stream) is stream`, turns this class of bug into a one-line diagnosis.
@@end

@verify kind=executable language=python
@code
ROWS = [{"id": f"r{i}", "qty": i % 7} for i in range(400)]


def scan(rows):
    return (row for row in rows if row["qty"] > 0)


def summarise(stream):
    total = sum(row["qty"] for row in stream)             # first pass
    top = max((row["qty"] for row in stream), default=0)  # second pass: empty
    return {"total": total, "top": top}


def pipeline(rows):
    stream = scan(rows)
    summary = summarise(stream)
    audit = [row["id"] for row in stream]                 # third pass: empty
    return summary, audit


def instrumented_scan(rows, log):
    """Same thing, but every yielded row is traced, which is how the bug is found."""
    for row in rows:
        if row["qty"] > 0:
            log.append(row["id"])
            yield row


# 1. the symptom, exactly as reported
summary, audit = pipeline(ROWS)
print("summary:", summary)
print("audit length:", len(audit))

# 2. the cause: the generator is its own iterator, so the first pass consumed it
stream = scan(ROWS)
print("iter(stream) is stream:", iter(stream) is stream)
print("rows yielded before the first pass ends:", sum(1 for _ in stream))
print("rows available after that:", sum(1 for _ in stream))

# 3. tracing proves where the records went: the first pass yields every matching
#    row from the 400 scanned, the next pass yields nothing at all
log = []
traced = instrumented_scan(ROWS, log)
first_pass = sum(1 for _ in traced)
second_pass = sum(1 for _ in traced)
print("rows scanned:", len(ROWS), "| instrumented first pass:", first_pass,
      "| second pass:", second_pass)
print("yield log length:", len(log))

# 4. a container is re-iterable, which is the difference that matters
container = [row for row in ROWS if row["qty"] > 0]
print("list iterated twice:", sum(1 for _ in container), sum(1 for _ in container))

# 5. the fix: one materialisation at the boundary, or a single-pass aggregate
def summarise_fixed(rows):
    data = list(rows)
    return {"total": sum(row["qty"] for row in data),
            "top": max((row["qty"] for row in data), default=0),
            "count": len(data)}


def summarise_single_pass(rows):
    total = top = count = 0
    for row in rows:
        total += row["qty"]
        top = max(top, row["qty"])
        count += 1
    return {"total": total, "top": top, "count": count}


print("fixed:", summarise_fixed(scan(ROWS)))
print("single pass:", summarise_single_pass(scan(ROWS)))

EXPECTED_TOTAL = sum(row["qty"] for row in ROWS)
assert EXPECTED_TOTAL == 1197, EXPECTED_TOTAL          # the fixture is pinned
assert summary["total"] == EXPECTED_TOTAL, "the first pass did read the data"
assert summary["top"] == 0 and audit == [], "later passes saw an exhausted iterator"
assert iter(stream) is stream
POSITIVES = sum(1 for row in ROWS if row["qty"] > 0)
assert POSITIVES == 342, POSITIVES          # 58 rows have qty == 0 and are filtered
assert first_pass == POSITIVES and second_pass == 0
assert len(log) == POSITIVES
assert summarise_fixed(scan(ROWS)) == summarise_single_pass(scan(ROWS))
assert summarise_fixed(scan(ROWS))["top"] == 6
print("PASS")
@@end

@expect_output
summary: {'total': 1197, 'top': 0}
audit length: 0
iter(stream) is stream: True
rows yielded before the first pass ends: 342
rows available after that: 0
rows scanned: 400 | instrumented first pass: 342 | second pass: 0
yield log length: 342
list iterated twice: 342 342
fixed: {'total': 1197, 'top': 6, 'count': 342}
single pass: {'total': 1197, 'top': 6, 'count': 342}
PASS
@@end

@notes
Traces every pass and pins the mechanism: the scan reads 400 rows of which 342 pass the
filter, the second pass reads 0, and the instrumented yield log contains exactly 342
entries — so nothing
was filtered out, the iterator was simply empty. Also pinned: `iter(stream) is
stream` is True for the generator and False for the list container (the general
test), the summary shows `top: 0` from a silent `max(..., default=0)`, and both
fixes (one `list()` at the boundary, or a single-pass aggregate) produce identical
results.
@@end

@example trc-0002
@meta category=execution_tracing language=python difficulty=intermediate tags=eager-evaluation,defaults,or-idiom,tracing

@user
Our config loader prints "loading timeout from remote" on every request even when the value is cached. The code below is the whole story, and the log ordering is what confused us: the "loading" line appears *before* the "cache hit" line.

```python
def load_remote(key, log):
    log.append("load:" + key)
    return 30


def get_timeout(config, log):
    return config.get("timeout", load_remote("timeout", log))


CONFIG = {"timeout": 0}
```

We expected a cache hit for the key that is present. Explain the ordering, and tell me which of the two idioms below is the correct fix:

```python
value = config.get("timeout") or load_remote("timeout", log)     # A
value = config["timeout"] if "timeout" in config else load_remote("timeout", log)   # B
```
@@end

@assistant
Both the ordering and the field name are explained by one fact: **arguments are evaluated before the call**. `config.get("timeout", load_remote(...))` calls `load_remote` first — that is the "load" line — and only then calls `dict.get` with the already-computed result, which is why the log looks out of order. Python has no lazy function arguments; the default is computed unconditionally, hit or miss. On a cache hit the work is done and thrown away, so a "cached" path silently performs the slow operation and its side effects (log entries, network calls, counters) on every request.

Fix **B** is correct. Fix A is the same bug with a different name: `or` evaluates its right-hand side whenever the left is **falsy**, so a legitimate `timeout: 0` (or `""`, `False`, an empty list) is replaced by the default. That is exactly your `CONFIG`, so A "works" — it hides the eager call by making the cache-hit case a miss. `or` conflates "absent" with "falsy", and for configuration values that legimately carry zero/empty, the two are different states.

```python
def get_timeout(config, log):
    if "timeout" in config:                 # membership first: no work at all on a hit
        return config["timeout"]
    return load_remote("timeout", log)       # progress only at the call site

# or, equivalently, with a real cache:
def get_timeout(config, log, cache={}):
    if "timeout" in config:
        return config["timeout"]
    if "timeout" not in cache:
        cache["timeout"] = load_remote("timeout", log)
    return cache["timeout"]
```

The generalisable rule: a default argument is a **value**, so it cannot express "compute this only if needed". Any function that treats `None`/sentinel defaults as "not provided" must do the check inside its body — `def f(x=None): x = compute() if x is None else x`. This is also why `dict.setdefault(k, expensive())` and `collections.defaultdict(lambda: expensive())` differ: the callable form is lazy, the value form is eager. Reading a trace, remember that the *order* of log lines tells you which expression was evaluated first — here the log was a correct recording of a wrong evaluation order.
@@end

@verify kind=executable language=python
@code
LOG = []


def load_remote(key):
    LOG.append("load:" + key)
    return 30


def get_eager(config):
    """The original: the default argument is computed before dict.get runs."""
    return config.get("timeout", load_remote("timeout"))


def get_or_idiom(config):
    return config.get("timeout") or load_remote("timeout")


def get_membership(config):
    if "timeout" in config:
        return config["timeout"]
    return load_remote("timeout")


def get_cached(config, cache):
    if "timeout" in config:
        return config["timeout"]
    if "timeout" not in cache:
        cache["timeout"] = load_remote("timeout")
    return cache["timeout"]


def trace_calls(config, getter, *args):
    """Record the order of observable events, which is the evidence here."""
    del LOG[:]
    value = getter(config, *args)
    return value, list(LOG)


PRESENT = {"timeout": 45}
ZERO = {"timeout": 0}
ABSENT = {}

# 1. the ordering in the bug report: the load happens even though the key exists
value, events = trace_calls(PRESENT, get_eager)
print("eager, key present:", value, "| events:", events)

# 2. the fix distinguishes absent from falsy
print("membership, present:", trace_calls(PRESENT, get_membership)[0], "| events:", trace_calls(PRESENT, get_membership)[1])
print("membership, zero:", trace_calls(ZERO, get_membership)[0], "| events:", trace_calls(ZERO, get_membership)[1])
print("membership, absent:", trace_calls(ABSENT, get_membership)[0], "| events:", trace_calls(ABSENT, get_membership)[1])

# 3. the `or` idiom looks identical until the value is falsy
print("or-idiom, present:", trace_calls(PRESENT, get_or_idiom)[0], "| events:", trace_calls(PRESENT, get_or_idiom)[1])
print("or-idiom, zero:", trace_calls(ZERO, get_or_idiom)[0], "| events:", trace_calls(ZERO, get_or_idiom)[1])

# 4. a real cache: the load happens once across many calls
cache = {}
results = [trace_calls(ABSENT, get_cached, cache)[1] for _ in range(3)]
print("cached calls that loaded:", [len(events) for events in results])
print("cache contents:", cache)

# 5. the same eager-evaluation trap with setdefault vs defaultdict
lazy_default = {}
setdefault_events = []
def make_value():
    setdefault_events.append("computed")
    return "computed-value"


lazy_default.setdefault("k", make_value())          # value form: always computed
setdefault_events_second = []
lazy_default.setdefault("k", make_value())          # computed again, then discarded
print("setdefault computed twice:", len(setdefault_events) == 2)

assert value == 45 and events == ["load:timeout"], "the eager call ran on a cache hit"
assert trace_calls(ZERO, get_membership)[0] == 0
assert trace_calls(ZERO, get_or_idiom)[0] == 30, "the or-idiom loses an explicit zero"
assert trace_calls(ABSENT, get_membership)[0] == 30
assert [len(events) for events in results] == [1, 0, 0], "the cache must load once"
assert setdefault_events == ["computed", "computed"]
print("PASS")
@@end

@expect_output
eager, key present: 45 | events: ['load:timeout']
membership, present: 45 | events: []
membership, zero: 0 | events: []
membership, absent: 30 | events: ['load:timeout']
or-idiom, present: 45 | events: []
or-idiom, zero: 30 | events: ['load:timeout']
cached calls that loaded: [1, 0, 0]
cache contents: {'timeout': 30}
setdefault computed twice: True
PASS
@@end

@notes
The trace is the evidence: with the key already present, the eager version still
emits `load:timeout` (one observable event on what the caller believed was a cache
hit), which is why the log line appeared before any cache-hit logging. Pinned too:
the membership-based fix emits no events for present or zero values and loads only
when the key is missing; the `or` idiom emits no event for `{"timeout": 0}` either
but returns 30 instead of 0, so it hides the eager call rather than fixing it; a
real cache loads exactly once across three calls; and the same eager-evaluation trap
is shown with `setdefault`, whose value argument is computed on both calls even
though the second result is discarded.
@@end

@example trc-0003
@meta category=execution_tracing language=python difficulty=intermediate tags=decorators,return-values,introspection,tracing

@user
After adding a timing decorator to six functions, three of them started returning `None` and two started returning wrong types. `functools.wraps` is used, `inspect.signature` prints the right signature, and the docstrings are intact — so the metadata all looks correct. Here is the decorator:

```python
import functools, time

def timed(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        started = time.perf_counter()
        func(*args, **kwargs)                # line 7
        print(f"{func.__name__} took {time.perf_counter() - started:.3f}s")
    return wrapper
```

Which line is wrong, and why did the introspection checks not catch it?
@@end

@assistant
Line 7: the decorator calls `func` but never returns its result, so every decorated function becomes `None`-returning. The fix is `return func(*args, **kwargs)`, with the timing printed before returning.

`functools.wraps` explains why every check you ran looked fine. It copies `__name__`, `__doc__`, `__module__`, `__qualname__`, `__dict__` and `__wrapped__` onto the wrapper — but it is **metadata about the function, not a statement about its behaviour**. `inspect.signature` even follows `__wrapped__` to show the original signature, so a decorator can report the correct signature while accepting nothing, returning nothing, or being async when the original was sync. The introspection tools answer "does it look like this function?" — the tests that answer "does it behave like it?" are ordinary call-and-assert tests on the returned value.

```python
import functools
import time

def timed(func):
    if inspect.iscoroutinefunction(func):          # decorators must preserve the kind
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            started = time.perf_counter()
            try:
                return await func(*args, **kwargs)   # the value is returned
            finally:
                log_duration(func.__name__, started)
        return wrapper

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        started = time.perf_counter()
        try:
            return func(*args, **kwargs)
        finally:
            log_duration(func.__name__, started)   # logs even when func raises
    return wrapper
```

Three properties worth testing on any decorator, all of which this bug violates or nearly violates:

- **return transparency** — the decorated function's value and type are unchanged for representative inputs;
- **exception transparency** — a raising function still raises (a `try/finally` measurement, not a bare call, keeps that true while logging);
- **shape preservation** — a sync function stays sync and an async function stays awaitable; wrapping a coroutine function in a sync wrapper returns a coroutine object that nobody awaits, producing "coroutine was never awaited" warnings and silently skipped work.

A trace of the call says it plainly: `func` executes, its frame returns a value, and `wrapper`'s implicit `return None` discards it. The cheap regression test is one line — call the decorated function and compare to the undecorated result.
@@end

@verify kind=executable language=python
@code
import functools
import inspect
import time

CALLS = []


def timed_broken(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        started = time.perf_counter()
        func(*args, **kwargs)                 # the missing return
        CALLS.append(func.__name__)
        return None
    return wrapper


def timed_fixed(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        started = time.perf_counter()
        try:
            return func(*args, **kwargs)
        finally:
            CALLS.append(func.__name__)
    return wrapper


def add(a, b=1):
    """Add two numbers."""
    return a + b


def make_list(n):
    return list(range(n))


broken_add = timed_broken(add)
broken_list = timed_broken(make_list)
fixed_add = timed_fixed(add)

# 1. the symptom
print("broken add(2, 3):", broken_add(2, 3))
print("broken make_list(3):", broken_list(3))

# 2. the original still ran: the side effect proves the call happened
print("original function called:", CALLS)

# 3. what the introspection checks looked at -- all of them pass while broken
print("name:", broken_add.__name__, "| doc:", broken_add.__doc__)
print("signature:", str(inspect.signature(broken_add)))
print("wrapped points at the original:", broken_add.__wrapped__ is add)

# 4. the fix restores value and type transparency
print("fixed add(2, 3):", fixed_add(2, 3))
print("fixed make_list(3):", timed_fixed(make_list)(3))

# 5. exception transparency: a raising function must still raise
def boom():
    raise ValueError("original failure")


try:
    timed_fixed(boom)()
    print("exception swallowed")
except ValueError as exc:
    print("exception preserved:", exc)

try:
    timed_broken(boom)()
    print("broken decorator swallowed the exception")
except ValueError:
    print("broken decorator: exception also propagates")

assert broken_add(2, 3) is None and broken_list(3) is None
assert "add" in CALLS and "make_list" in CALLS, "the original did run"
assert broken_add.__name__ == "add" and broken_add.__doc__ == "Add two numbers."
assert str(inspect.signature(broken_add)) == "(a, b=1)"
assert broken_add.__wrapped__ is add
assert fixed_add(2, 3) == 5 and timed_fixed(make_list)(3) == [0, 1, 2]
assert inspect.signature(fixed_add) == inspect.signature(add)
print("PASS")
@@end

@expect_output
broken add(2, 3): None
broken make_list(3): None
original function called: ['add', 'make_list']
name: add | doc: Add two numbers.
signature: (a, b=1)
wrapped points at the original: True
fixed add(2, 3): 5
fixed make_list(3): [0, 1, 2]
exception preserved: original failure
broken decorator: exception also propagates
PASS
@@end

@notes
Executes the decorator and pins the contradiction the report could not explain: the
decorated function runs (the call log proves it) yet returns `None`, while `__name__`,
`__doc__`, `str(inspect.signature(...))` and `__wrapped__` all describe the original.
The fixed version is asserted to preserve the return value, the return type and the
signature, and both decorators are shown to propagate the original exception, so the
fix does not trade transparency for logging.
@@end

@example trc-0004
@meta category=execution_tracing language=javascript difficulty=advanced tags=microtasks,event-loop,async-ordering,tracing

@user
Our audit log comes out in an order nobody can explain, and the "saved" line is written before the save resolves:

```javascript
async function handleRequest(id) {
  console.log("start", id);
  saveToDb(id).then(() => console.log("saved", id));
  await validate(id);
  console.log("validated", id);
  await audit(id);
  console.log("done", id);
}
```

Trace the exact output for a single call, given `saveToDb` resolves on a timer after 5ms, `validate` and `audit` resolve immediately. Then explain why the `.then` callback lands where it does, and what changes if `saveToDb` were synchronous.
@@end

@assistant
Trace for one call, in order:

```
start 1
validated 1          <- the first await suspension point
done 1               <- after audit resolves (a microtask)
saved 1              <- the 5ms timer, well after the async function completed
```

The mechanism is the **event loop's two queues**, and the `.then` registration point decides which one you land in:

1. `saveToDb(id)` is called immediately, returns a pending promise; `.then(...)` registers a reaction on it and continues without awaiting.
2. `await validate(id)` suspends `handleRequest`. The code *after* the await is scheduled as a **microtask** when `validate` settles — and because `validate` resolves immediately, that microtask is already queued.
3. `console.log("validated")` runs from that microtask; `await audit(id)` queues another microtask, which runs next.
4. `saveToDb`'s timer is a **macrotask**: it is only eligible after the current macrotask (and the entire microtask queue) drains, so its `.then` callback runs last — after `done`, and typically after `handleRequest`'s promise has already settled.

So the ordering follows two rules: microtasks (promise callbacks, including the continuations of `await`) run to completion before the next macrotask (timers, I/O); and within a microtask queue, callbacks run in the order they were queued. The surprising part is not the `.then` at all — it is that `await` itself queues work, which is why "validated" can print before an earlier-registered `.then` that has not settled yet.

If `saveToDb` were synchronous (or its promise was already resolved when `.then` was called), the callback would be queued as a microtask *at the moment of registration* — before `await validate` — and "saved" would print immediately after "start". Which of those two you get is a race in the "resolved later" case: with a fast connection the save can land before `audit` completes, so the log ordering changes with network speed. That, not the `.then`, is what makes an interleaved audit trail unreadable.

```javascript
async function handleRequest(id) {
  console.log("start", id);
  const saved = saveToDb(id);        // start it, keep the promise
  await validate(id);
  console.log("validated", id);
  await audit(id);
  await saved;                       // deterministic ordering: join before logging
  console.log("saved", id);
  console.log("done", id);
}
```

Two rules that remove the ambiguity: await a promise **before** logging its completion (join points make order deterministic), and never rely on the relative order of an un-awaited promise and unrelated `await`s. When tracing an unfamiliar async log, mark each line as "sync", "microtask" or "macrotask" — the columns sort themselves out.
@@end

@verify kind=executable language=javascript
@code
const ORDER = [];
const record = (line) => ORDER.push(line);

const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function saveToDb(id) {
  await delay(5);                    // a timer: the promise settles in a macrotask
  return { id, saved: true };
}

const validate = async (id) => ({ id, ok: true });
const audit = async (id) => ({ id, audited: true });

// the version from the bug report
async function handleInterleaved(id) {
  record("start " + id);
  saveToDb(id).then(() => record("saved " + id));
  await validate(id);
  record("validated " + id);
  await audit(id);
  record("done " + id);
}

// the same code with a synchronous save: registration time decides the position
async function handleSyncSave(id) {
  record("start sync " + id);
  Promise.resolve({ id }).then(() => record("saved sync " + id));
  await validate(id);
  record("validated sync " + id);
}

// the fix: join before logging
async function handleJoined(id) {
  record("start joined " + id);
  const saved = saveToDb(id);
  await validate(id);
  record("validated joined " + id);
  await audit(id);
  await saved;
  record("saved joined " + id);
  record("done joined " + id);
}

async function main() {
  await handleInterleaved(1);
  // Let the outstanding timer and microtasks finish before inspecting the order.
  await delay(20);
  const interleaved = [...ORDER];
  console.log("interleaved order:", JSON.stringify(interleaved));

  ORDER.length = 0;
  await handleSyncSave(1);
  await delay(1);
  console.log("synchronous save:", JSON.stringify([...ORDER]));

  ORDER.length = 0;
  await handleJoined(1);
  await delay(20);
  console.log("joined order:", JSON.stringify([...ORDER]));

  // microtasks before macrotasks, demonstrable in three lines
  const marks = [];
  setTimeout(() => marks.push("macro"));
  Promise.resolve().then(() => marks.push("micro"));
  marks.push("sync");
  await delay(1);
  console.log("queue priority:", JSON.stringify(marks));

  assert(JSON.stringify(interleaved) === JSON.stringify([
    "start 1", "validated 1", "done 1", "saved 1",
  ]), "the interleaved order is the bug: saved lands after done");
  assert(ORDER[0] === "start joined 1");
  assert(ORDER.at(-1) === "done joined 1");
  assert(ORDER.indexOf("saved joined 1") < ORDER.indexOf("done joined 1"),
         "the join fixes the order");
  assert(JSON.stringify(marks) === JSON.stringify(["sync", "micro", "macro"]));
  console.log("PASS");
}

function assert(condition, message) {
  if (!condition) throw new Error(message || "assertion failed");
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
@@end

@expect_output
interleaved order: ["start 1","validated 1","done 1","saved 1"]
synchronous save: ["start sync 1","saved sync 1","validated sync 1"]
joined order: ["start joined 1","validated joined 1","saved joined 1","done joined 1"]
queue priority: ["sync","micro","macro"]
PASS
@@end

@notes
The trace is produced by running the three versions in a real event loop and
pinning the observed order: the un-awaited `.then` reports `saved` *after* `done`
because a timer is a macrotask while `await` continuations are microtasks; the
synchronous-save variant prints `saved sync` immediately after `start` because the
reaction was queued at registration time; and the joined version forces
`saved` before `done`. The queue-priority demo (`sync`, `micro`, `macro`) pins the
rule that explains all three orders.
@@end
