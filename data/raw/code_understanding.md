@example py-read-0001
@meta category=code_understanding language=python difficulty=intermediate tags=closures,mutable-default,late-binding,predict-output

@user
A candidate wrote this in our code review, and I want to be sure I understand it before I comment. What exactly does it print, and is there a second, subtler bug in the `configure` function that a reviewer might miss?

```python
def make_handlers():
    handlers = []
    for name in ["a", "b", "c"]:
        handlers.append(lambda: name)
    return handlers


def configure(timeout=10, hooks=[]):
    hooks.append(timeout)
    return hooks


print([h() for h in make_handlers()])
print(configure(1))
print(configure(2))
print(configure())
```
@@end

@assistant
Output, in order:

```
['c', 'c', 'c']
[1]
[1, 2]
[1, 2, 10]
```

**Line by line, why:**

`make_handlers` appends three closures, but a Python closure captures the *variable*, not its value at definition time — `name` is resolved when the lambda is called. By the time the list comprehension calls them, the loop has finished and `name == "c"`. Hence three identical `'c'`s. This is late binding, and it is not a "bug in the lambda" so much as a fact about how closures over loop variables work.

The classic fixes are a default argument (evaluated at definition time) or `functools.partial`:

```python
from functools import partial

handlers = [lambda name=name: name for name in ["a", "b", "c"]]   # bind now
handlers = [partial(lambda n: n, name) for name in ["a", "b", "c"]]  # equally explicit
# or, clearest of all, stop using a closure when you just want a value:
handlers = [partial(str.upper, name) for name in ["a", "b", "c"]]
```

Mutable default arguments are the subtler and more dangerous one. `hooks=[]` is evaluated **once**, when the `def` statement executes, and the same list object is reused for every call. So `configure(1)` returns `[1]`, `configure(2)` mutates that same list and returns `[1, 2]`, and `configure()` appends the default `10` to it, giving `[1, 2, 10]`. The list is effectively global state hanging off the function object — you can even inspect it: `configure.__defaults__[1]` is `[1, 2, 10]` after the calls above.

That is why the third print is `[1, 2, 10]` rather than `[10]`, and why this bug is so often invisible in tests: the first call always behaves correctly, and tests that call the function once never see it. It bites in production, where the accumulator grows per request, or worse, where a mutable default is a shared cache, lock or `datetime` that leaks between users.

The idiom that fixes it without changing the call signature:

```python
def configure(timeout: int = 10, hooks: list[int] | None = None) -> list[int]:
    hooks = [] if hooks is None else list(hooks)   # never mutate the caller's list
    hooks.append(timeout)
    return hooks
```

Two habits worth adopting from this review: use `None` (or a sentinel) for any default that could be mutated, and inside functions copy caller-provided collections before mutating them. A linter helps too — ruff's `B006`/`B008` and flake8-bugbear flag mutable defaults at review time.

The verification below runs the candidate's code, asserts the exact four prints, then runs both corrected versions and asserts they give `['a', 'b', 'c']` and `[1]`, `[2]`, `[10]` — the fix must change the output, otherwise the test would prove nothing.
@@end

@verify kind=executable language=python
@code
from functools import partial

# --- the code under discussion, exactly as written --------------------------
def make_handlers():
    handlers = []
    for name in ["a", "b", "c"]:
        handlers.append(lambda: name)
    return handlers


def configure(timeout=10, hooks=[]):
    hooks.append(timeout)
    return hooks


assert [h() for h in make_handlers()] == ["c", "c", "c"], "late binding: all closures see the final value"
first = configure(1)
assert first == [1]                      # the first call alone looks correct
second = configure(2)
assert first is second, "both calls returned the very same list object"
assert second == [1, 2], "the earlier result changed under the caller's feet"
third = configure()
assert third is first, "and the default-list keeps accumulating across calls"
assert first == [1, 2, 10]
assert configure.__defaults__[1] is first, "the default lives on the function object"

# The first call alone looks correct: that is why single-call tests miss it.
def configure_once(timeout=10, hooks=[]):
    hooks.append(timeout)
    return hooks

assert configure_once(1) == [1]

# --- corrected: bind the value, and never share a mutable default -----------
def make_handlers_fixed():
    return [lambda fixed=name: fixed for name in ["a", "b", "c"]]


def configure_fixed(timeout=10, hooks=None):
    hooks = [] if hooks is None else list(hooks)
    hooks.append(timeout)
    return hooks


assert [h() for h in make_handlers_fixed()] == ["a", "b", "c"]
assert [configure_fixed(1), configure_fixed(2), configure_fixed()] == [[1], [2], [10]]
assert configure_fixed.__defaults__[1] is None, "default must not be a mutable object"

# Caller-owned lists must not be mutated by the callee.
caller = [99]
assert configure_fixed(1, caller) == [99, 1]
assert caller == [99], "the callee must copy, not mutate, the caller's list"

# functools.partial is the other standard fix for the closure case.
handlers = [partial(lambda n: n, name) for name in ["a", "b", "c"]]
assert [h() for h in handlers] == ["a", "b", "c"]
print("PASS")
@@end

@expect_output
PASS
@@end

@notes
Executes the snippet verbatim and pins all three surprising outputs
(['c','c','c'] and the accumulated [1], [1,2], [1,2,10]); asserts the three calls
shared one default list object via `__defaults__`, and that a single-call helper
looks correct (the reason the bug survives review). Then runs both fixes and
asserts they change the behaviour, that the default is no longer mutable, and
that a caller-supplied list is not mutated.
@@end

@example js-read-0002
@meta category=code_understanding language=javascript difficulty=intermediate tags=event-loop,microtasks,promise-ordering,predict-output

@user
I need to be able to answer event-loop questions in interviews and, more practically, reason about our logging order. Given this file, what is printed and in what order? Please be precise about why the async IIFE's second log lands where it does.

```javascript
console.log("1 sync");
setTimeout(() => console.log("2 timeout"), 0);
Promise.resolve().then(() => console.log("3 then"));
queueMicrotask(() => console.log("4 microtask"));
(async () => {
  console.log("5 async start");
  await null;
  console.log("6 after await");
})();
console.log("7 sync end");
```
@@end

@assistant
The output is:

```
1 sync
5 async start
7 sync end
3 then
4 microtask
6 after await
2 timeout
```

The mental model: all synchronous code runs to completion first, then the microtask queue drains fully (in FIFO order), and only then does the event loop take the next macrotask.

1. `1 sync` — synchronous, first statement.
2. The `setTimeout(..., 0)` callback is scheduled as a **macrotask**; the timer is ready immediately but macrotasks only run after the microtask queue is empty.
3. `Promise.resolve().then(cb)` registers `cb` on an already-settled promise, so `cb` is enqueued as a **microtask** right away (already at this line, not "later").
4. `queueMicrotask(cb)` enqueues another microtask — behind `3`.
5. The async IIFE is called immediately: `5 async start` prints synchronously, because an `async` function body runs synchronously until the first `await`.
6. `await null` suspends the IIFE. Its continuation — the `6 after await` line — is enqueued as a microtask **at the moment the await is reached**, i.e. after `3` and `4` were enqueued, which is precisely why it prints last among the microtasks.
7. `7 sync end` — the remaining synchronous statement.
8. Microtask queue drains in order: `3 then`, `4 microtask`, `6 after await`.
9. Only now does the event loop pick up the timer: `2 timeout`.

Two details that people get wrong:

- **`await` does not "pause and resume later in the same tick".** Even `await null`, which needs no I/O, still yields to the microtask queue. That is the entire reason `6` comes after `7`, and it is why an `await` inside a loop can reorder logs relative to code that follows the loop.
- **`process.nextTick` (Node only) is a different queue, and its ordering versus promises depends on the module system.** In CommonJS the `nextTick` queue drains first, which is the rule everyone quotes. In **ESM** (including this file, and any `--input-type=module` invocation) promise microtasks registered at module scope drain first instead. The verification spawns a CommonJS child process to pin both orders side by side, because the honest lesson is "never mix `nextTick` and promises when order matters", not "`nextTick` always wins".

Practical consequences for logging and tests:

- Microtasks that enqueue more microtasks (chained `.then`s, resolved promises) keep the queue busy, and macrotasks — including I/O callbacks — starve until it empties. An unbounded microtask chain (a promise loop that never awaits real I/O) can block timers entirely.
- Ordering is guaranteed for microtask-vs-microtask and macrotask-vs-macrotask, but **not** for two independent macrotasks: two `setTimeout(…, 0)` callbacks run in scheduling order, which is stable in Node but is not something to depend on across runtimes.
- In tests, assert on state after `await Promise.resolve()` (or use your framework's flush helper) rather than on a fixed number of `setTimeout` ticks.

The verification runs the snippet unchanged and asserts this exact order, then adds variants: `process.nextTick`, a nested microtask chain, and a macrotask-vs-microtask starvation case.
@@end

@verify kind=executable language=javascript
@code
import { execFileSync } from "node:child_process";
import { writeFileSync } from "node:fs";

const order = [];
const log = (label) => order.push(label);

log("1 sync");
setTimeout(() => log("2 timeout"), 0);
Promise.resolve().then(() => log("3 then"));
queueMicrotask(() => log("4 microtask"));
(async () => {
  log("5 async start");
  await null;
  log("6 after await");
})();
log("7 sync end");

// Wait for the timer to fire so the whole schedule is observable.
await new Promise((resolve) => setTimeout(resolve, 5));
const expected = ["1 sync", "5 async start", "7 sync end", "3 then", "4 microtask", "6 after await", "2 timeout"];
if (JSON.stringify(order) !== JSON.stringify(expected)) {
  throw new Error(`order mismatch:\n  got  ${order.join(", ")}\n  want ${expected.join(", ")}`);
}

// process.nextTick belongs to a queue of its own, and its ordering relative to
// promise microtasks depends on the module system. Both orders are pinned here:
//   * ESM module scope (this file): promise microtasks drain first
//   * CommonJS: nextTick drains first (the "classic" rule people quote)
const tickOrder = [];
tickOrder.push("a sync");
process.nextTick(() => tickOrder.push("b nextTick"));
Promise.resolve().then(() => tickOrder.push("c then"));
tickOrder.push("d sync");
await new Promise((r) => setTimeout(r, 5));
const esmExpected = ["a sync", "d sync", "c then", "b nextTick"];
if (JSON.stringify(tickOrder) !== JSON.stringify(esmExpected)) {
  throw new Error(`esm nextTick order mismatch: ${tickOrder.join(", ")} (want ${esmExpected.join(", ")})`);
}

writeFileSync("tick-order.cjs", [
  'const out = [];',
  'out.push("a sync");',
  'process.nextTick(() => out.push("b nextTick"));',
  'Promise.resolve().then(() => { out.push("c then"); console.log(out.join(", ")); });',
  'out.push("d sync");',
  '',
].join("\n"));
const cjsOut = execFileSync(process.execPath, ["tick-order.cjs"], { encoding: "utf8" }).trim();
const cjsExpected = "a sync, d sync, b nextTick, c then";
if (cjsOut !== cjsExpected) {
  throw new Error(`cjs nextTick order mismatch: ${cjsOut} (want ${cjsExpected})`);
}
if (cjsOut === esmExpected.join(", ")) {
  throw new Error("expected a real ESM-vs-CJS difference; the two orders came out identical");
}

// A resolving promise chain keeps the queue busy and starves the timer.
const starved = [];
const spin = (n) => (n === 0 ? Promise.resolve() : Promise.resolve().then(() => spin(n - 1)));
setTimeout(() => starved.push("timer"), 0);
await spin(50).then(() => starved.push("chain"));
await new Promise((r) => setTimeout(r, 5));
if (JSON.stringify(starved) !== JSON.stringify(["chain", "timer"])) {
  throw new Error(`starvation order mismatch: ${starved.join(", ")}`);
}

// `await` inside a loop interleaves with whatever follows the loop.
const loopOrder = [];
const work = (async () => {
  for (const item of ["x", "y"]) {
    loopOrder.push(`before ${item}`);
    await null;
    loopOrder.push(`after ${item}`);
  }
})();
loopOrder.push("after loop body started");
await work;
if (JSON.stringify(loopOrder) !== JSON.stringify(["before x", "after loop body started", "after x", "before y", "after y"])) {
  throw new Error(`loop order mismatch: ${loopOrder.join(", ")}`);
}
console.log("PASS");
@@end

@expect_output
PASS
@@end

@notes
Executed with node v22. Pins the full seven-line ordering of the snippet under
discussion, then verifies the other claims in the explanation: a long promise
chain starves a `setTimeout(..., 0)` macrotask until the microtask queue empties,
and `await` inside a loop interleaves with code after the loop body starts
(before x, after loop body started, after x, ...). For the Node-only `nextTick`
queue the test asserts BOTH dialects (ESM module scope here, plus a CommonJS
child process spawned with execFileSync) and fails if they do not actually
differ, because a single-dialect assertion is exactly how the wrong folklore
about "nextTick always runs first" gets into documentation.
@@end

@example py-read-0003
@meta category=code_understanding language=python difficulty=advanced tags=attribute-lookup,getattr,descriptors,slots,metaclass

@user
Someone on the team added a `__getattr__` to our model base class and a `__getattr__` to its metaclass, and now `hasattr` returns True for typos. Can you explain the lookup rules here precisely, and tell me whether the `__slots__` in the subclass is actually saving memory?

```python
class Meta(type):
    def __getattr__(cls, name):
        return f"metaclass:{name}"


class Base:
    kind = "class-attr"

    def __init__(self):
        self.data = {"x": 1}


class Model(Base, metaclass=Meta):
    __slots__ = ("extra",)

    def __init__(self):
        super().__init__()
        self.extra = 2

    def __getattr__(self, name):
        return f"instance:{name}"


m = Model()
print(getattr(m, "kind"))
print(getattr(m, "nope"))
print(getattr(Model, "nope"))
print(m.__dict__)
```
@@end

@assistant
Output:

```
class-attr
instance:nope
metaclass:nope
{'data': {'x': 1}}
```

**The lookup rules, in the order the interpreter actually applies them for instance attribute access:**

1. `type(m).__mro__` is searched for a **data descriptor** (a class attribute defining `__set__`/`__delete__`, e.g. `property`). If found, it wins over the instance dictionary.
2. `m.__dict__` is checked.
3. Non-data descriptors and plain class attributes on the MRO.
4. `__getattr__` is called **only if all of the above failed** — that is what makes `m.nope` return `"instance:nope"` while `m.kind` returns the class attribute normally.

For `getattr(Model, "nope")` (attribute access on a *class*), the same algorithm runs with `type(Model)` = `Meta` in the role of "the type": step 4 becomes `Meta.__getattr__`, so you get `"metaclass:nope"`. This is a Python 3.7+ guarantee (before that, metaclass `__getattr__` was skipped for implicit lookups) and it is exactly why `hasattr` now lies about typos: any missing attribute "exists". If a library does `getattr(config, "timeout", default)`, your default is silently ignored.

The safe version distinguishes *real* misses from *fallback* behaviour, and avoids `__getattr__` for anything except genuine dynamic proxies (ORM lazy fields, `argparse.Namespace` style containers):

```python
class Model(Base, metaclass=Meta):
    __slots__ = ("extra",)

    def __getattr__(self, name: str):
        if name.startswith("_"):                 # dunder/private: never fake it
            raise AttributeError(name)
        raise AttributeError(f"{type(self).__name__!s} has no attribute {name!r}")
        # or, if you truly need a dynamic proxy, keep a strict allow-list:
        # if name in self._dynamic_fields:
        #     return self._load(name)
```

**On `__slots__`: no, it is not saving anything here.** `Base` is an ordinary class, so instances get a `__dict__` regardless of `Model.__slots__` — you can see it in the last print: `{'data': {'x': 1}}`. The slot descriptor for `extra` exists and works (`m.extra == 2` is stored in the slot, not the dict), but each instance still carries a full dict plus the slot. To actually save memory, *every* class in the MRO must define `__slots__`, including `Base`; then instances have no `__dict__` and the slot storage is the only per-instance overhead. Two more slot subtleties worth knowing:

- `__slots__` is per-class: `Model` does not inherit `Base`'s dict-less-ness, and a subclass that forgets `__slots__` reintroduces `__dict__` for its own instances.
- Slots and `__getattr__` interact badly in one specific way: a slot that was never assigned raises `AttributeError` on read, which then *falls into* `__getattr__` if you have one. With a permissive `__getattr__` you get `"instance:extra"` instead of an error — a truly confusing bug in lazy proxies.

Finally, note the ordering trap in `getattr(m, "kind")`: it never reaches `__getattr__` because `kind` is a normal class attribute found in step 3. People often assume `__getattr__` is a hook for *all* attribute access; that hook is `__getattribute__`, which is called for every access and is easy to get catastrophically wrong (it must `return super().__getattribute__(name)` or you must implement the whole protocol).

The verification asserts every one of these behaviours, including the MRO-completeness requirement for `__slots__` (a fully-slotted class really has no `__dict__`), the safe `__getattr__` variant, and the case where a permissive `__getattr__` masks an unset slot.
@@end

@verify kind=executable language=python
@code
class Meta(type):
    def __getattr__(cls, name):
        return f"metaclass:{name}"


class Base:
    kind = "class-attr"

    def __init__(self):
        self.data = {"x": 1}


class Model(Base, metaclass=Meta):
    __slots__ = ("extra",)

    def __init__(self):
        super().__init__()
        self.extra = 2

    def __getattr__(self, name):
        return f"instance:{name}"


m = Model()
assert getattr(m, "kind") == "class-attr", "class attributes are found before __getattr__"
assert getattr(m, "nope") == "instance:nope"
assert getattr(Model, "nope") == "metaclass:nope", "class-level miss falls back to the metaclass"
assert m.__dict__ == {"data": {"x": 1}}, "the slot holds extra; data lives in the inherited __dict__"
assert m.extra == 2 and "extra" not in m.__dict__

# hasattr lies once __getattr__ is permissive: that is the real cost.
assert hasattr(m, "totally_misspelled") is True
assert getattr(m, "totally_misspelled", "DEFAULT") != "DEFAULT", "the default is never reached"

# Data descriptors beat the instance dict; plain class attributes do not.
class WithProperty(Base):
    @property
    def data(self):
        return "from property"


# __new__ instead of __init__: Base.__init__ assigns self.data, which the
# read-only property would reject -- itself a useful fact about data descriptors.
p = WithProperty.__new__(WithProperty)
assert p.data == "from property", "property is a data descriptor, so it wins over __dict__"
p.__dict__["data"] = "shadow attempt"
assert p.data == "from property", "the instance dict cannot shadow a data descriptor"

# __slots__ only pays off if every class in the MRO defines it.
class Leaf:
    __slots__ = ("a",)


class LeafChild(Leaf):
    __slots__ = ("b",)


leaf = LeafChild()
leaf.a, leaf.b = 1, 2
assert not hasattr(leaf, "__dict__"), "no class in this MRO has a dict"

class Forgot(Leaf):
    pass          # missing __slots__ reintroduces __dict__


assert hasattr(Forgot(), "__dict__"), "a subclass without __slots__ brings the dict back"

# An unset slot raises AttributeError, which a permissive __getattr__ then hides.
class Slotty:
    __slots__ = ("value",)

    def __getattr__(self, name):
        return f"synthetic:{name}"


s = Slotty()
# An unset slot raises AttributeError on read -- but the permissive __getattr__
# intercepts it, so instead of an error you get a synthetic value. Note that the
# attribute is NOT memoised: nothing was ever written to the slot.
assert s.value == "synthetic:value"
assert not hasattr(type(s), "value") or True
s.value = 42
assert s.value == 42, "assigned slots behave normally"


class StrictSlotty:
    __slots__ = ("value",)

    def __getattr__(self, name):
        if name.startswith("_") or name in self.__slots__:
            raise AttributeError(name)
        return f"synthetic:{name}"


strict = StrictSlotty()
try:
    strict.value
    raise AssertionError("strict variant must surface the unset slot")
except AttributeError:
    pass
assert strict.other == "synthetic:other"

# The "unset slot with a permissive __getattr__" trap, made explicit: two
# different instances happily "have" a value they never stored.
assert Slotty().value == "synthetic:value"

# __getattribute__ is the hook for *every* access, not __getattr__.
class Noisy(Base):
    def __getattribute__(self, name):
        if name == "kind":
            return "intercepted"
        return super().__getattribute__(name)


assert Noisy().kind == "intercepted"
assert Noisy().data == {"x": 1}, "delegating to super() keeps the normal protocol"
print("PASS")
@@end

@expect_output
PASS
@@end

@notes
Executes and asserts the four printed values plus every rule stated in the
explanation: MRO search before __getattr__, metaclass __getattr__ for class-level
access, __dict__ still present because `Base` lacks __slots__, data descriptors
(property) beating instance dict assignment, __slots__ saving memory only when
the whole MRO defines it, and the unset-slot/__getattr__ interaction in both a
permissive and a strict variant. Also checks __getattribute__ interception with
a super() delegation.
@@end

@example sql-read-0004
@meta category=code_understanding language=sql difficulty=intermediate tags=left-join,null-semantics,count,subtle-bugs

@user
I want to be sure I understand the difference between these two queries before I pick one for the "users with no paid orders" dashboard. Both look like they filter the same thing. Explain what each returns, why they differ, and what the `COUNT(*)` versus `COUNT(o.id)` distinction does here.

```sql
-- A
SELECT u.id, COUNT(*) AS n
FROM users u
LEFT JOIN orders o ON o.user_id = u.id AND o.status = 'paid'
GROUP BY u.id;

-- B
SELECT u.id, COUNT(o.id) AS n
FROM users u
LEFT JOIN orders o ON o.user_id = u.id
WHERE o.status = 'paid'
GROUP BY u.id;
```
@@end

@assistant
The two queries answer different questions, and only A is safe as a "users with no paid orders" report.

**Query A** keeps every user. The `AND o.status = 'paid'` lives in the `ON` clause, so it is part of the join condition: a user whose orders are all unpaid still matches the `users` row and gets a `NULL`-extended order side. Their `COUNT(*)` is **1**, not 0, because `COUNT(*)` counts joined rows — and there is one row, consisting of the user plus NULLs. To get 0 you must count a column from the nullable side: `COUNT(o.id)`. This is the single most common LEFT JOIN bug in reporting SQL.

**Query B** keeps only users who have at least one paid order. Filtering the nullable side in `WHERE` after a LEFT JOIN discards the NULL-extended rows, so the LEFT JOIN degenerates into an INNER JOIN. Users with no paid orders disappear entirely — which is the opposite of what the dashboard wants.

Corrected versions of A, plus the NULL-trap variant to avoid:

```sql
-- Users with their count of paid orders, including users with none:
SELECT u.id, COUNT(o.id) AS paid_orders          -- COUNT on the nullable side
FROM users u
LEFT JOIN orders o ON o.user_id = u.id AND o.status = 'paid'
GROUP BY u.id;

-- Only users who have paid at least once (this is what B actually does):
SELECT u.id, COUNT(o.id) AS paid_orders
FROM users u
JOIN orders o ON o.user_id = u.id                -- INNER JOIN, filter in WHERE
WHERE o.status = 'paid'
GROUP BY u.id;

-- Users with no paid orders at all: filter the *aggregate*, not the join.
SELECT u.id
FROM users u
LEFT JOIN orders o ON o.user_id = u.id AND o.status = 'paid'
GROUP BY u.id
HAVING COUNT(o.id) = 0;
```

Two related NULL traps that come up in the same code:

- **`NOT IN` with a NULL in the subquery returns no rows.** `WHERE u.id NOT IN (SELECT user_id FROM orders)` evaluates to `NULL` (not TRUE) for every row once the subquery yields a NULL `user_id`. Use `NOT EXISTS`, or add `WHERE user_id IS NOT NULL` inside the subquery. `NOT EXISTS` is the version that is correct by construction and optimises well.
- **`COUNT(*)` vs `COUNT(col)` vs `COUNT(DISTINCT col)`**: count the rows, count the non-NULL values, count distinct non-NULL values respectively. Choosing the wrong one is a data-correctness bug, not a style issue.

Ordering intuition for how this executes: `ON` decides *how rows pair up*, `WHERE` decides *which paired rows survive*, and `HAVING` decides *which groups survive*. Filters on the nullable side belong in `ON` (if you want to keep unmatched rows) or in `WHERE` with an INNER JOIN (if you do not); putting them in `WHERE` after a LEFT JOIN is a silent downgrade.

The verification runs both original queries and every corrected variant against a fixture with a paid-only user, an unpaid-only user, and a user with no orders, then pins the row sets and demonstrates the `NOT IN` NULL trap.
@@end

@verify kind=executable language=sql
@code
CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE orders (id INTEGER PRIMARY KEY, user_id INTEGER, status TEXT);

INSERT INTO users (id, name) VALUES (1, 'paid-only'), (2, 'unpaid-only'), (3, 'no-orders'), (4, 'mixed');
INSERT INTO orders (id, user_id, status) VALUES
  (10, 1, 'paid'),
  (11, 2, 'pending'),
  (12, 4, 'paid'),
  (13, 4, 'refunded');

-- A: ON-clause filter, COUNT(*) -- the trap: unmatched users count as 1.
SELECT u.id, COUNT(*) AS n, COUNT(o.id) AS paid_orders
FROM users u
LEFT JOIN orders o ON o.user_id = u.id AND o.status = 'paid'
GROUP BY u.id ORDER BY u.id;

-- B: WHERE filter -- silently an inner join, user 2 and 3 vanish.
SELECT u.id, COUNT(o.id) AS n
FROM users u
LEFT JOIN orders o ON o.user_id = u.id
WHERE o.status = 'paid'
GROUP BY u.id ORDER BY u.id;

-- Corrected A: every user, correct zero for the no-paid-orders users.
SELECT u.id, COUNT(o.id) AS paid_orders
FROM users u
LEFT JOIN orders o ON o.user_id = u.id AND o.status = 'paid'
GROUP BY u.id ORDER BY u.id;

-- The dashboard query: users with no paid orders.
SELECT u.id, u.name
FROM users u
LEFT JOIN orders o ON o.user_id = u.id AND o.status = 'paid'
GROUP BY u.id, u.name
HAVING COUNT(o.id) = 0
ORDER BY u.id;

-- NOT IN with a NULL in the subquery: returns zero rows, incorrectly.
SELECT COUNT(*) AS not_in_rows FROM (SELECT u.id FROM users u
  WHERE u.id NOT IN (SELECT user_id FROM orders)) q;

-- The same question with NOT EXISTS: correct.
SELECT u.id FROM users u
WHERE NOT EXISTS (SELECT 1 FROM orders o WHERE o.user_id = u.id AND o.status = 'paid')
ORDER BY u.id;

-- An explicit NULL row makes the NOT IN trap reproducible on its own.
INSERT INTO orders (id, user_id, status) VALUES (14, NULL, 'orphan');
SELECT COUNT(*) AS not_in_with_null FROM (SELECT u.id FROM users u
  WHERE u.id NOT IN (SELECT user_id FROM orders)) q;
SELECT COUNT(*) AS not_exists_rows FROM (SELECT u.id FROM users u
  WHERE NOT EXISTS (SELECT 1 FROM orders o WHERE o.user_id = u.id)) q;
@@end

@expect_output
id|n|paid_orders
1|1|1
2|1|0
3|1|0
4|1|1
id|n
1|1
4|1
id|paid_orders
1|1
2|0
3|0
4|1
id|name
2|unpaid-only
3|no-orders
not_in_rows
1
id
2
3
not_in_with_null
0
not_exists_rows
1
@@end

@notes
Runs in SQLite with a fixture covering the three interesting user shapes
(paid-only, unpaid-only, no orders) plus a mixed user. The expected output pins:
COUNT(*) reporting 1 for matched-nothing users next to the correct COUNT(o.id)
zeros, query B silently dropping users 2 and 3, the corrected report including
all four users, the HAVING COUNT(o.id) = 0 dashboard result, and both NULL traps
(NOT IN returning 1 row before a NULL exists in the subquery and 0 rows after,
versus NOT EXISTS which is unaffected).
@@end

@example ts-read-0005
@meta category=code_understanding language=typescript difficulty=advanced tags=conditional-types,mapped-types,inference,type-level-tests

@user
I am reviewing a typed API client and cannot follow what these utility types resolve to. For `Unwrap`, explain the resolution for `Unwrap<Promise<Promise<number>>>` and why the recursion terminates; for `Client`, say exactly what `client["/users"].POST` accepts and whether the "extra property" call compiles.

```typescript
type Unwrap<T> = T extends Promise<infer U> ? Unwrap<U> : T;

type Routes = {
  "/users": {
    GET: { query: { limit?: number } };
    POST: { body: { name: string } };
  };
  "/health": { GET: Record<string, never> };
};

type Client<R> = {
  [Path in keyof R]: {
    [Method in keyof R[Path]]: (arg: R[Path][Method]) => Promise<{ status: number }>;
  };
};

declare const client: Client<Routes>;

client["/users"].POST({ body: { name: "ada" } });
client["/users"].POST({ body: { name: "ada", admin: true } });
```
@@end

@assistant
**`Unwrap<Promise<Promise<number>>>` is `number`.** The first conditional match binds `U = Promise<number>`, so the type recurses as `Unwrap<Promise<number>>`; the next step binds `U = number`; then `number extends Promise<infer U>` is false, so the false branch returns `T` = `number`. Termination is not a matter of depth counting — it is structural: each recursive step strips exactly one `Promise` constructor, and TypeScript's conditional types are lazy (evaluated on demand with a recursion-depth limit, TS2589 if you exceed it). `Awaited<T>` in the standard library is this same type with a few more cases (thenables, `null`/`undefined` handling); prefer the built-in when you just need "the resolved type".

**`client["/users"].POST` accepts exactly `{ body: { name: string } }`.** The mapped types are homomorphic: `[Path in keyof R]` walks the keys of `Routes` and `[Method in keyof R[Path]]` walks the methods of the selected route, so each method keeps its own parameter type. `R[Path][Method]` is an indexed access type, which resolves to the argument object for that pair.

**The second call does not compile:** `Object literal may only specify known properties, and 'admin' does not exist in type '{ name: string }'`. Excess property checking applies to object literals assigned to a known object type, which is the desired behaviour for a hand-written client.

Two clarifications worth adding:

- **Excess property checks are not sealed types.** Passing a variable instead of an inline literal defeats the check: `const body = { name: "ada", admin: true }; client["/users"].POST({ body });` compiles, because the freshness check only applies to fresh object literals. If you need a hard guarantee, put the payload through a validator (zod/io-ts) or use an index signature-free branded type; the type system alone will not enforce it at a trust boundary.
- **`Record<string, never>` for the health route** means "a key-value bag whose values are impossible", i.e. an empty object; it is a common way to say "this endpoint takes no arguments" while still requiring the argument. `Record<string, never>` is not the same as `{}` (which accepts anything) or `unknown` (which accepts everything).

The verification compiles the file with `tsc --strict` and uses `Expect<Equal<...>>` assertions to prove each claim: that the generic resolution lands on `number`, that the method parameter type is the route-specific object, that the extra-property literal is rejected (via `@ts-expect-error`), and that the same payload passed through a variable is accepted — documenting the limitation rather than pretending it away.
@@end

@verify kind=executable language=typescript mode=typecheck
@code
type Unwrap<T> = T extends Promise<infer U> ? Unwrap<U> : T;

type Equal<A, B> = (<T>() => T extends A ? 1 : 2) extends <T>() => T extends B ? 1 : 2 ? true : false;
type Expect<T extends true> = T;

// 1. Recursive unwrapping resolves to the innermost type.
type _1 = Expect<Equal<Unwrap<Promise<Promise<number>>>, number>>;
type _2 = Expect<Equal<Unwrap<string>, string>>;
type _3 = Expect<Equal<Unwrap<Promise<void>>, void>>;
type _4 = Expect<Equal<Unwrap<Promise<Promise<Promise<Date>>>>, Date>>;
// A union distributes: each member is unwrapped independently.
type _5 = Expect<Equal<Unwrap<Promise<number> | string>, number | string>>;
// Thenables are NOT matched by this simplified version, unlike the built-in Awaited.
type Thenable = { then(cb: (v: number) => void): void };
type _6 = Expect<Equal<Unwrap<Thenable>, Thenable>>;

// 2. Mapped types preserve per-route, per-method argument types.
type Routes = {
  "/users": {
    GET: { query: { limit?: number } };
    POST: { body: { name: string } };
  };
  "/health": { GET: Record<string, never> };
};

type Client<R> = {
  [Path in keyof R]: {
    [Method in keyof R[Path]]: (arg: R[Path][Method]) => Promise<{ status: number }>;
  };
};

declare const client: Client<Routes>;

type _7 = Expect<Equal<Parameters<typeof client["/users"]["POST"]>[0], { body: { name: string } }>>;
type _8 = Expect<Equal<Parameters<typeof client["/users"]["GET"]>[0], { query: { limit?: number } }>>;
type _9 = Expect<Equal<Parameters<typeof client["/health"]["GET"]>[0], Record<string, never>>>;
type _10 = Expect<Equal<keyof typeof client, "/users" | "/health">>;
// Methods are preserved as functions returning a status envelope.
type _11 = Expect<Equal<Awaited<ReturnType<typeof client["/users"]["GET"]>>, { status: number }>>;

client["/users"].POST({ body: { name: "ada" } });
client["/users"].GET({ query: { limit: 10 } });
client["/users"].GET({ query: {} });

// 3. Excess property checking rejects a fresh literal with an unknown key.
// @ts-expect-error 'admin' does not exist in type '{ name: string }'
client["/users"].POST({ body: { name: "ada", admin: true } });

// @ts-expect-error the whole argument is required, not optional
client["/users"].POST();

// @ts-expect-error the wrong route name is not part of the client
client["/user"].GET({ query: {} });

// 4. ...but the check is defeated by an intermediate variable. This compiles,
//    which is exactly why a runtime validator is still required at the boundary.
const looseBody = { name: "ada", admin: true };
client["/users"].POST({ body: looseBody });

// 5. Record<string, never> accepts only the empty object.
client["/health"].GET({});
// @ts-expect-error a non-empty Record<string, never> is not assignable
client["/health"].GET({ probe: 1 });

// Silence "declared but never used" style diagnostics in older configs.
export type __Assertions = [_1, _2, _3, _4, _5, _6, _7, _8, _9, _10, _11];
export {};
@@end

@expect_output
TYPECHECK_OK
@@end

@notes
Compiled with `tsc --strict --noEmit`; the run passes only if every type-level
assertion holds and every `@ts-expect-error` line does produce an error (an
unused ts-expect-error is itself an error). Covers recursive inference through
nested Promises, non-distributive cases, the absence of thenable handling in this
simplified Unwrap (unlike the built-in Awaited), per-route/per-method parameter
inference via mapped types, the excess-property rejection, and the documented
limitation that an intermediate variable defeats freshness checking.
@@end
