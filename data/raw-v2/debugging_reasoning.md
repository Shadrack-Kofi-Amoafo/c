@example dbg-r-0001
@meta category=debugging_reasoning language=python difficulty=intermediate tags=shallow-copy,mutable-state,aliasing,defaults

@user
This config helper is used from three call sites and the settings started bleeding across requests. The `dict(...)` copy looked like enough protection, and the test suite (which only sets top-level keys) never caught it.

```python
DEFAULT_SETTINGS = {"theme": {"dark": False}, "alerts": ["email"], "retries": 3}


def make_settings(overrides=None):
    settings = dict(DEFAULT_SETTINGS)      # "fresh dict, so we are safe"
    settings.update(overrides or {})
    return settings


# request A: make_settings()["alerts"].append("sms")
# request B: make_settings()["alerts"] -> ["email", "sms"]
```

Where exactly is the aliasing, and what is the smallest correct fix? I want the reason a top-level copy is insufficient in general, not just for this dict.
@@end

@assistant
The alias is the *nested* objects. `dict(DEFAULT_SETTINGS)` builds a new top-level mapping, but the values it copies are **references to the same nested objects** — `settings["theme"]` and `settings["alerts"]` are the very same `dict`/`list` objects that `DEFAULT_SETTINGS` holds, so `settings["alerts"].append("sms")` mutates the module-level list. Adding a top-level key (`settings.update(...)`) only rebinds a slot in the new dict, which is why the top-level test passes: rebinding a slot is not mutation of the value.

Two consequences worth internalising:

1. **Copy depth is a property of the data structure, not of the copy call.** "Take a copy" is only meaningful once you name the depth. `dict(x)`, `x.copy()`, `list(x)`, `[:]` are all shallow; `copy.deepcopy` recurses; `copy.copy` is the same as `dict(...)` for a dict.
2. **Read-only sharing is fine; the bug needs a mutator.** Sharing the nested `theme` dict is harmless until some caller writes into it. That is why these leaks appear far from the code that introduced them: whoever calls `.append`/`[...] =` is innocent, and the defect lives in the factory.

The minimal fix is a deep copy at the boundary, or — better for a settings object — make the defaults immutable so the leak is impossible:

```python
import copy

DEFAULT_SETTINGS = {"theme": {"dark": False}, "alerts": ["email"], "retries": 3}


def make_settings(overrides=None):
    return copy.deepcopy(DEFAULT_SETTINGS) | (overrides or {})
```

For a hot path, prefer immutability to copying: store defaults as `MappingProxyType`/tuples and have callers build new objects with `dataclasses.replace`, so there is nothing to alias in the first place. A deepcopy per request also costs O(size of the defaults), which is usually fine for a config dict and unacceptable for a large one — measure before choosing.

To catch the class of bug in tests, assert **isolation**, not contents: build two instances, mutate a nested value of the first, and assert the second is unchanged. Content assertions on a single instance cannot see aliasing at all.
@@end

@verify kind=executable language=python
@code
import copy

DEFAULT_SETTINGS = {"theme": {"dark": False}, "alerts": ["email"], "retries": 3}
# An immutable template for the fixed factory: tuples cannot be mutated by a
# caller, so there is no shared mutable state to leak into.
TEMPLATE = {"theme": {"dark": False}, "alerts": ("email",), "retries": 3}


def make_settings_shallow(overrides=None):
    settings = dict(DEFAULT_SETTINGS)           # the copy the bug report trusted
    settings.update(overrides or {})
    return settings


def make_settings_deep(overrides=None):
    """Deep copy of the (possibly already polluted) module default."""
    settings = copy.deepcopy(DEFAULT_SETTINGS)
    settings.update(overrides or {})
    return settings


def make_settings_safe(overrides=None):
    """Rebuilt from an immutable template: no caller can reach the defaults."""
    settings = copy.deepcopy(TEMPLATE)
    settings["alerts"] = list(settings["alerts"])
    settings.update(overrides or {})
    return settings


def mutate_nested(settings, channel):
    settings["alerts"].append(channel)


# 1. the symptom, reproduced
first = make_settings_shallow()
mutate_nested(first, "sms")
second = make_settings_shallow()
print("second call sees:", second["alerts"])

# 2. the top-level write is isolated, which is why the old test passed
third = make_settings_shallow({"retries": 99})
fourth = make_settings_shallow()
print("top-level override leaks:", fourth["retries"] != DEFAULT_SETTINGS["retries"])

# 3. the cause: the nested value is the same object, not an equal one
same_object = make_settings_shallow()["alerts"] is DEFAULT_SETTINGS["alerts"]
print("nested list is the same object:", same_object)
print("nested dict is the same object:", make_settings_shallow()["theme"] is DEFAULT_SETTINGS["theme"])

# 4. the leak is permanent for the life of the process: the module default itself
#    is now dirty, so even a deep copy of it starts from polluted data.
fifth = make_settings_deep()
print("deep copy after the leak:", fifth["alerts"])
print("module default is now:", DEFAULT_SETTINGS["alerts"])

# 5. the durable fix does not read mutable module state at all
seventh = make_settings_safe()
mutate_nested(seventh, "sms")
eighth = make_settings_safe()
print("safe factory, second call:", eighth["alerts"])

assert second["alerts"] == ["email", "sms"], "the leak must be visible"
assert third["retries"] == 99 and fourth["retries"] == 3
assert same_object is True
assert fifth["alerts"] == ["email", "sms"], "deep-copying a polluted default is not a fix"
assert DEFAULT_SETTINGS["alerts"] == ["email", "sms"], "the default really was mutated"
assert eighth["alerts"] == ["email"], "the template-based factory isolates callers"
assert list(TEMPLATE["alerts"]) == ["email"], "and the template itself is untouched"
print("PASS")
@@end

@expect_output
second call sees: ['email', 'sms']
top-level override leaks: False
nested list is the same object: True
nested dict is the same object: True
deep copy after the leak: ['email', 'sms']
module default is now: ['email', 'sms']
safe factory, second call: ['email']
PASS
@@end

@notes
Reproduces the request-to-request leak and pins the reason it was invisible: a
top-level override does not leak (slot rebinding) while the nested list and dict
are the *same objects* (`is`, not merely equal), so any caller that mutates them
writes into the module-level default. The deep-copy version is shown to isolate a
mutation, and the module default is asserted clean. The isolation assertion is the
test that would have caught it — asserting contents of a single instance cannot.
@@end

@example dbg-r-0002
@meta category=debugging_reasoning language=python difficulty=intermediate tags=identity,interning,semantics,survived-tests

@user
A production bug our tests never saw: `if row["status"] is STATUS_ACTIVE:` passes locally but fails on data loaded from Postgres. The same code compares an id from JSON with a cached id. A teammate says "Python `is` compares values for small strings and ints, so it is just a caching quirk" — is that right? What is the actual rule, and why do the tests pass while production fails?
@@end

@assistant
The teammate has the arrow backwards. `is` never compares values: it compares **identity** (same object, i.e. same address). What changes between your laptop and production is not the operator's meaning but whether two equal values happen to be the *same object*:

- **Small integer caching** covers `-5..256` in CPython, because those objects are created at startup and reused. `int("256") is 256` is True; `int("257") is 257` is False. The range is an implementation detail, not a language guarantee, and it changed size in past versions.
- **String interning** applies to literals in the same code object and to identifier-like strings the compiler interns. A literal in a module and the same text parsed from JSON are different objects: `json.loads('"active"') is "active"` is False. Postgres drivers return fresh `str` objects for text columns, so a status column produces a new object on every fetch.
- Your test fixtures build the expected values from **literals in the same file**, so the interning makes them identical objects and the comparison succeeds. The test therefore asserts an accidental property of the fixture, not the behaviour of the code.

The rule to apply: use `is` only for singletons (`None`, `True`, `False`, sentinels you define yourself) and for identity checks where you literally mean "the same object". Everything else — numbers, strings, dataclass fields, database values — is `==`. If you want a sentinel, create one (`_MISSING = object()`) rather than comparing to a sentinel-looking string.

```python
_MISSING = object()                     # identity is meaningful here, and only here

def get_status(row, cache):
    status = row.get("status", _MISSING)
    if status is _MISSING:              # correct use: a unique sentinel object
        return "unknown"
    if status == "active":              # correct use: value comparison
        return "ok"
```

Two more traps in the same family: `is` on `float("nan")` is False even for the same variable compared with itself under some optimisations, and identity comparisons of interned strings hide genuine data-normalisation bugs — `"active "` (trailing space) is a *different* string, so `==` catching the mismatch is a feature. When a comparison "works in tests, fails in production", suspect the fixture before the operator.
@@end

@verify kind=executable language=python
@code
import json

STATUS_ACTIVE = "active"
CACHE = {"u1": "user-1"}


def classify_is(status):
    return "ok" if status is STATUS_ACTIVE else "unknown"


def classify_eq(status):
    return "ok" if status == STATUS_ACTIVE else "unknown"


def lookup_is(user_id):
    return CACHE["u1"] if user_id is CACHE["u1"] else None


def lookup_eq(user_id):
    return CACHE["u1"] if user_id == CACHE["u1"] else None


# 1. literals from the same file: the fixture that made the tests pass
literal_status = "active"
print("literal status, is:", classify_is(literal_status))

# 2. the same text arriving from a database/JSON payload: a different object
db_status = json.loads('"active"')
print("parsed status, is:", classify_is(db_status), "| eq:", classify_eq(db_status))
print("same text, same object:", db_status is STATUS_ACTIVE, "| equal:", db_status == STATUS_ACTIVE)

# 3. small-int caching, and where it stops
small_from_text = int("256")
large_from_text = int("257")
SMALL_MAX = 256
LARGE = 257
print("int('256') is 256:", small_from_text is SMALL_MAX)
print("int('257') is 257:", large_from_text is LARGE)

# 4. the id path: an id assembled at runtime from a payload (the compiler folds
#    two literals into one constant, so str(1) is what keeps this honest)
rebuilt_id = "user-" + str(1)
print("rebuilt id, is:", lookup_is(rebuilt_id), "| eq:", lookup_eq(rebuilt_id))

# 5. the sentinel pattern, done right
_MISSING = object()
row = {"status": "active"}
print("missing-key sentinel identity:", row.get("nope", _MISSING) is _MISSING)
print("present-key sentinel identity:", row.get("status", _MISSING) is _MISSING)

assert classify_is(literal_status) == "ok"
assert classify_is(db_status) == "unknown" and classify_eq(db_status) == "ok"
assert db_status is not STATUS_ACTIVE and db_status == STATUS_ACTIVE
assert small_from_text is SMALL_MAX
assert large_from_text is not LARGE
assert lookup_is(rebuilt_id) is None and lookup_eq(rebuilt_id) == "user-1"
print("PASS")
@@end

@expect_output
literal status, is: ok
parsed status, is: unknown | eq: ok
same text, same object: False | equal: True
int('256') is 256: True
int('257') is 257: False
rebuilt id, is: None | eq: user-1
missing-key sentinel identity: True
present-key sentinel identity: False
PASS
@@end

@notes
Executed on this interpreter, so the interning and small-int-cache claims are
measurements rather than recollections: a literal from the same module is the
identical object, the same text parsed from JSON is not, `int("256")` hits the
cached range while `int("257")` does not, and an id rebuilt by concatenation breaks
an identity lookup that a value comparison handles. The sentinel pattern is
included as the correct use of `is`, and the fix is asserted to preserve behaviour
for both literal and parsed inputs.
@@end

@example dbg-r-0003
@meta category=debugging_reasoning language=javascript difficulty=intermediate tags=closures,hoisting,var,iteration-binding

@user
Every button in our toolbar does the same thing — the last one's action. The helper below was fine for months because the toolbar had exactly one button, and the unit test still passes because it checks the first handler synchronously.

```javascript
function buildHandlers(actions) {
  const handlers = [];
  for (var i = 0; i < actions.length; i++) {
    handlers.push(function () { return actions[i]; });
  }
  return handlers;
}
```

The review said "closures capture their own scope, this is fine". What is actually happening, and why does it fail only when more than one action is registered?
@@end

@assistant
The closure is fine; the *binding it captured* is not. `var` has **function scope**, so all three closures close over one `i` — there is only one variable, not one per iteration. When the loop finishes, that variable holds `actions.length`, so every handler reads either the last element or `undefined`. With a single action the final value coincides with the only index, which is why the bug appeared only when the toolbar grew.

The reviewer's statement is right in general and useless here: closures capture the *variable*, not a snapshot of its value. `let` (or a parameter, or an IIFE) creates a fresh binding per iteration, so each closure gets its own.

```javascript
function buildHandlers(actions) {
  const handlers = [];
  for (let i = 0; i < actions.length; i++) {   // per-iteration binding
    handlers.push(() => actions[i]);
  }
  return handlers;
}

// Equally correct, and clearer about intent:
function buildHandlers(actions) {
  return actions.map((action) => () => action);   // captures the parameter
}
```

Why the callback style (`setTimeout`, DOM listeners, promise chains) makes this so common: the loop finishes long before the callback runs, so the captured variable has *always* reached its final value by the time anyone reads it. Synchronous invocation inside the same iteration — exactly what the unit test does — reads the variable while it still has the current index, so the test passes. The check that catches it: register two or more callbacks, invoke them **after** the loop returns, and assert the collected results — never invoke inside the loop body.

The same trap exists in other forms: `for (var k in obj)` in ES5 code, a `while` loop with a shared accumulator, and Python's `lambda: x` over a loop variable (Python's `lambda` also captures the variable, not the value — the fix there is a default argument: `lambda x=x: x`).
@@end

@verify kind=executable language=javascript
@code
function buildHandlersVar(actions) {
  const handlers = [];
  for (var index in actions) {                 // function-scoped binding
    handlers.push(function () { return actions[index]; });
  }
  return handlers;
}

function buildHandlersLet(actions) {
  const handlers = [];
  for (let index in actions) {                 // per-iteration binding
    handlers.push(function () { return actions[index]; });
  }
  return handlers;
}

function buildHandlersMap(actions) {
  return actions.map((action) => () => action);
}

const ACTIONS = ["bold", "italic", "underline"];

// 1. the symptom: three handlers, one answer
const buggy = buildHandlersVar(ACTIONS);
console.log("after the loop, index =", ACTIONS.length - 1);
console.log("var results:", JSON.stringify(buggy.map((handler) => handler())));

// 2. why the single-button test passed: the last index is also the first index
console.log("single action:", JSON.stringify(buildHandlersVar(["bold"]).map((h) => h())));

// 3. the misleading "closure captures this iteration" claim: the variable is shared
const shared = buildHandlersVar(ACTIONS);
console.log("all handlers return the same value:", new Set(shared.map((h) => h())).size === 1);

// 4. the fixes agree, and each keeps its own value
const withLet = buildHandlersLet(ACTIONS).map((handler) => handler());
const withMap = buildHandlersMap(ACTIONS).map((handler) => handler());
console.log("let results:", JSON.stringify(withLet));
console.log("map results:", JSON.stringify(withMap));

// 5. the invocation timing is the other half of the trap: calling inside the
//    loop reads the variable while it still holds the current index.
const insideLoop = [];
for (var j = 0; j < 3; j++) {
  insideLoop.push((function () { return j; })());
}
console.log("invoked inside the loop:", JSON.stringify(insideLoop));

assert(new Set(shared.map((h) => h())).size === 1);
assert(buggy.map((h) => h()).join(",") === "underline,underline,underline");
assert(JSON.stringify(withLet) === JSON.stringify(ACTIONS));
assert(JSON.stringify(withMap) === JSON.stringify(ACTIONS));
assert(JSON.stringify(insideLoop) === JSON.stringify([0, 1, 2]));

function assert(condition, message) {
  if (!condition) throw new Error(message || "assertion failed");
}
console.log("PASS");
@@end

@expect_output
after the loop, index = 2
var results: ["underline","underline","underline"]
single action: ["bold"]
all handlers return the same value: true
let results: ["bold","italic","underline"]
map results: ["bold","italic","underline"]
invoked inside the loop: [0,1,2]
PASS
@@end

@notes
Reproduces the "every button does the last action" symptom in a plain node run and
pins both halves of the trap: the shared `var` binding (all three closures return
one value, the last index) and the reason the single-action test passed (with one
element the final index is also the only index). The `let` and `map` fixes are
asserted to return the registered actions in order, and the last case shows that
invoking the function *inside* the loop yields the correct values even with `var` —
which is exactly what a synchronous unit test does, and why it cannot see the bug.
@@end

@example dbg-r-0004
@meta category=debugging_reasoning language=python difficulty=advanced tags=timezone,naive-datetime,off-by-one,environment

@user
Our subscription service reports "expires today" for some EU customers and "expires tomorrow" for US customers on the same subscription, and the nightly job that flips expired accounts fires a day early for the US region. The code looks obviously correct:

```python
def days_left(expires_at: datetime) -> int:
    return (expires_at.date() - datetime.now().date()).days


def is_expired(expires_at: datetime) -> bool:
    return datetime.now() > expires_at
```

CI is UTC, so the tests pass there. A colleague blames the DB driver and wants to store dates instead of timestamps. What is the root cause?
@@end

@assistant
Storing dates would hide the bug, not fix it. The cause is that both functions mix **naive local wall-clock** (`datetime.now()`) with a value whose meaning you have not pinned down, so the answer depends on the server's ambient timezone (`TZ`, container default, or the clock the platform gives you) — not on the customer or the deadline:

- `datetime.now()` returns a naive datetime in the *process* timezone. Two servers in different zones produce different values for the same instant, and one of them may already be past a midnight the other has not reached.
- `.date()` truncates at **local** midnight, so `days_left` is a difference of two zone-dependent calendar dates. A subscription expiring at `2024-06-01T00:30Z` is "tomorrow" for a UTC host and "today" for a New York host, which is the customer-visible split you are seeing.
- `is_expired` compares a naive local "now" against `expires_at`. If `expires_at` arrives timezone-aware (Postgres `timestamptz` via psycopg returns aware datetimes, `timestamp` returns naive) the comparison raises `TypeError`; if it arrives naive in a *different* zone than the process, the comparison silently uses the wrong instant.

The rule: **an instant is stored and compared in UTC (or as an aware datetime), and converted to a zone only for display.** "Which day does this expire on" is a calendar question, so it needs an explicit timezone — the customer's, not the server's.

```python
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

def days_left(expires_at: datetime, *, zone: str, now: datetime | None = None) -> int:
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None or expires_at.tzinfo is None:
        raise ValueError("compare aware datetimes only")
    local_zone = ZoneInfo(zone)                      # the *customer's* calendar
    return (expires_at.astimezone(local_zone).date()
            - moment.astimezone(local_zone).date()).days


def is_expired(expires_at: datetime, *, now: datetime | None = None) -> bool:
    moment = now or datetime.now(timezone.utc)
    return moment >= expires_at                        # instant vs instant
```

Defensive details that stop this recurring: assert awareness at the boundary (`if value.tzinfo is None: value = value.replace(tzinfo=timezone.utc)` only when you know the source really is UTC), never call `.now()`/`.today()` without a tz in domain code, and make the "current time" a parameter so tests can pin an instant instead of depending on the machine's clock and zone.
@@end

@verify kind=executable language=python
@code
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

EXPIRES = datetime(2024, 6, 1, 0, 30, tzinfo=timezone.utc)     # 00:30Z on 1 June
INSTANT = datetime(2024, 5, 31, 22, 0, tzinfo=timezone.utc)    # 22:00Z on 31 May

ZONES = {"accra": "Africa/Accra", "new_york": "America/New_York", "tokyo": "Asia/Tokyo"}


def days_left_naive(expires_at, ambient_zone, now_instant):
    """What the buggy version computes: .date() in the process timezone."""
    local_now = now_instant.astimezone(ZoneInfo(ambient_zone))
    local_expires = expires_at.astimezone(ZoneInfo(ambient_zone))
    return (local_expires.date() - local_now.date()).days


def days_left_fixed(expires_at, display_zone, now_instant):
    local_now = now_instant.astimezone(ZoneInfo(display_zone))
    local_expires = expires_at.astimezone(ZoneInfo(display_zone))
    return (local_expires.date() - local_now.date()).days


# 1. the same instant, three process timezones, three answers from the buggy code
naive_answers = {name: days_left_naive(EXPIRES, zone, INSTANT) for name, zone in ZONES.items()}
print("naive local .date():", " ".join(f"{name}={value}" for name, value in naive_answers.items()))

# 2. why: the truncation happens at each zone's own midnight
boundaries = {
    name: datetime(2024, 6, 1, tzinfo=timezone.utc).astimezone(ZoneInfo(zone)).strftime("%Y-%m-%d %H:%M %Z")
    for name, zone in ZONES.items()
}
print("local midnight of 1 June (UTC):", " ".join(f"{name}={value}" for name, value in boundaries.items()))

# 3. the fixed version: the calendar zone is an explicit argument, so the host's
#    timezone cannot influence the answer
print("fixed, customer in accra:", days_left_fixed(EXPIRES, "Africa/Accra", INSTANT))
print("fixed, customer in new_york:", days_left_fixed(EXPIRES, "America/New_York", INSTANT))

# 4. the awareness check: a naive value compared with an aware one is a hard error
try:
    datetime.now() >= EXPIRES
    print("naive vs aware comparison: silently allowed")
except TypeError as exc:
    print("naive vs aware comparison: TypeError")

# 5. `is_expired` on instants is zone-independent, and it is the comparison that
#    the nightly job should use.
BEFORE = INSTANT
AFTER = EXPIRES + timedelta(minutes=1)
print("expired before deadline:", BEFORE >= EXPIRES, "| expired after:", AFTER >= EXPIRES)

assert naive_answers == {"accra": 1, "new_york": 0, "tokyo": 0}, naive_answers
assert len(set(naive_answers.values())) == 2, "the naive version must split across zones"
assert naive_answers["accra"] != naive_answers["new_york"], "today or tomorrow, same instant"
assert days_left_fixed(EXPIRES, "Africa/Accra", INSTANT) == 1
assert days_left_fixed(EXPIRES, "America/New_York", INSTANT) == 0
assert days_left_fixed(EXPIRES, "Asia/Tokyo", INSTANT) == 0
assert BEFORE < EXPIRES < AFTER
print("PASS")
@@end

@expect_output
naive local .date(): accra=1 new_york=0 tokyo=0
local midnight of 1 June (UTC): accra=2024-06-01 00:00 GMT new_york=2024-05-31 20:00 EDT tokyo=2024-06-01 09:00 JST
fixed, customer in accra: 1
fixed, customer in new_york: 0
naive vs aware comparison: TypeError
expired before deadline: False | expired after: True
PASS
@@end

@notes
Runs the same instant through the buggy and fixed implementations in three process
timezones and pins the divergence: the naive `.date()` difference depends on the
ambient zone (the "today/tomorrow" split customers reported) because the truncation
happens at each zone's own midnight, while the fixed version takes the calendar
zone as an argument and always answers for the customer. The zone-dependent-midnight
table is printed so the mechanism is visible, the naive-versus-aware comparison is
shown to raise instead of guessing, and `is_expired` is asserted to be a pure
instant comparison (zone-independent) before and after the deadline.
@@end
