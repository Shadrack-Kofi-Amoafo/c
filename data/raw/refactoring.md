@example py-ref-0001
@meta category=refactoring language=python difficulty=intermediate tags=guard-clauses,cyclomatic-complexity,behavior-preserving

@user
This function passed review years ago and now nobody wants to touch it. Refactor it for readability without changing behaviour for any input, and tell me how you would prove behaviour is unchanged.

```python
def shipping_cost(order):
    if order is not None:
        if order.items:
            if order.country in ("US", "CA"):
                if order.total >= 35:
                    return 0
                else:
                    if order.express:
                        return 12
                    else:
                        return 5
            else:
                if order.total >= 100:
                    return 0
                else:
                    return 20
        else:
            return 0
    else:
        raise ValueError("order is required")
```
@@end

@assistant
I would refactor it into guard clauses plus a per-region table, then prove equivalence with an exhaustive case matrix over the input space (the function is small enough that all interesting combinations can be enumerated).

The nesting encodes four independent decisions: validation, empty order, region, and threshold/express. Flattening them makes each rule visible, and a table makes the policy data rather than control flow — which is what lets a non-engineer review it:

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class ShippingRule:
    free_threshold: float
    flat_rate: float
    express_rate: float


# Region -> policy. Adding a region is now a data edit, not a control-flow edit.
RULES = {
    "US": ShippingRule(free_threshold=35, flat_rate=5, express_rate=12),
    "CA": ShippingRule(free_threshold=35, flat_rate=5, express_rate=12),
}
DEFAULT_RULE = ShippingRule(free_threshold=100, flat_rate=20, express_rate=20)


def shipping_cost(order) -> float:
    if order is None:
        raise ValueError("order is required")
    if not order.items:
        return 0

    rule = RULES.get(order.country, DEFAULT_RULE)
    if order.total >= rule.free_threshold:
        return 0
    return rule.express_rate if order.express else rule.flat_rate
```

Equivalence notes — these are the details that decide whether a mechanical flattening is safe:

- **Order of the checks matters.** `order is None` was tested first, so it must stay first; `validate → empty order → pricing`. Swapping the first two would turn `None` into an `AttributeError` instead of the documented `ValueError`.
- **`order.items` truthiness, not `len(...) > 0`.** Original used a truthiness test, so an object with a falsy-but-not-empty `items` (a custom `__bool__`, a generator that is always truthy, or `0`/`""`) behaves the same way only if I keep truthiness. If `items` is documented as a sequence, `if not order.items` is fine; if it can be `None`, truthiness still covers it.
- **Express in the free case costs 0.** In the original, the US/CA branch returns 0 *before* consulting `express`, so an express order above the threshold ships free. Any rewrite that applies express surcharges unconditionally changes behaviour. I preserved that, and the table makes the question explicit rather than accidental.
- **Unknown countries take the default branch** (`"JP"` → threshold 100, flat 20). `RULES.get(country, DEFAULT_RULE)` preserves that, whereas a `match` statement with `case "US" | "CA"` and no fallback would raise.
- **Comparisons use `>=` on `total`**, exactly as written. `>` would flip the boundary at exactly 35/100, which is the kind of change that only shows up in one customer's invoice.
- **Return types stay numeric**: the original returns ints; the refactor keeps int literals in the dataclass so no `int`→`float` conversion sneaks into JSON output.

How to prove it: build a matrix of (order is None, items empty, country, total at/below/above the threshold, express on/off) covering the boundaries — `total = threshold - 0.01`, `total = threshold`, `total = threshold + 0.01` — and assert the old and new implementations produce identical results for every combination, including that they raise the same exception type for `None`. That is what the verification does, with the original kept verbatim as the reference implementation.
@@end

@verify kind=executable language=python
@code
from dataclasses import dataclass
from itertools import product


class Order:
    def __init__(self, items, country, total, express=False):
        self.items = items
        self.country = country
        self.total = total
        self.express = express

    def __repr__(self):
        return f"Order(items={self.items!r}, country={self.country!r}, total={self.total}, express={self.express})"


# --- original implementation, kept verbatim as the reference ---------------
def shipping_cost_old(order):
    if order is not None:
        if order.items:
            if order.country in ("US", "CA"):
                if order.total >= 35:
                    return 0
                else:
                    if order.express:
                        return 12
                    else:
                        return 5
            else:
                if order.total >= 100:
                    return 0
                else:
                    return 20
        else:
            return 0
    else:
        raise ValueError("order is required")


# --- refactored ------------------------------------------------------------
@dataclass(frozen=True)
class ShippingRule:
    free_threshold: float
    flat_rate: int
    express_rate: int


RULES = {
    "US": ShippingRule(35, 5, 12),
    "CA": ShippingRule(35, 5, 12),
}
DEFAULT_RULE = ShippingRule(100, 20, 20)


def shipping_cost_new(order) -> int:
    if order is None:
        raise ValueError("order is required")
    if not order.items:
        return 0
    rule = RULES.get(order.country, DEFAULT_RULE)
    if order.total >= rule.free_threshold:
        return 0
    return rule.express_rate if order.express else rule.flat_rate


def outcome(fn, order):
    try:
        return ("returned", fn(order))
    except Exception as exc:
        return ("raised", type(exc).__name__, str(exc))


def matrix():
    countries = ["US", "CA", "JP", None, "us"]           # case sensitivity is real behaviour
    totals = [0, 34.99, 35, 35.01, 99.99, 100, 100.01]
    for country, total, express, items in product(countries, totals, (False, True), ([], ["sku"])):
        yield Order(items, country, total, express)
    yield Order(["sku"], "US", 35, True)                  # express + free threshold
    yield Order([], "JP", 500, True)                      # empty order, any region


cases = list(matrix())
assert len(cases) == 5 * 7 * 2 * 2 + 2, len(cases)   # 5 countries incl. None

for order in cases:
    old, new = outcome(shipping_cost_old, order), outcome(shipping_cost_new, order)
    assert old == new, (order, old, new)

# None must raise the same error type from both, with the same message.
assert outcome(shipping_cost_old, None) == outcome(shipping_cost_new, None)
assert outcome(shipping_cost_new, None)[1] == "ValueError"

# Pin the behaviours that a careless rewrite would change.
assert shipping_cost_new(Order(["sku"], "US", 35, express=True)) == 0, "express above threshold is free"
assert shipping_cost_new(Order(["sku"], "US", 34.99, express=True)) == 12
assert shipping_cost_new(Order(["sku"], "JP", 99.99)) == 20
assert shipping_cost_new(Order(["sku"], "JP", 100)) == 0
assert shipping_cost_new(Order([], "JP", 500, express=True)) == 0
assert shipping_cost_new(Order(["sku"], "us", 20)) == 20, "lowercase country falls to the default rule"

# The refactor must be data-driven: adding a region needs no new branch.
RULES["DE"] = ShippingRule(free_threshold=50, flat_rate=7, express_rate=15)
assert shipping_cost_new(Order(["sku"], "DE", 49)) == 7
assert shipping_cost_new(Order(["sku"], "DE", 50)) == 0
del RULES["DE"]
print("PASS")
@@end

@expect_output
PASS
@@end

@notes
The original function is kept verbatim as a reference implementation and compared
against the refactor over a generated matrix of 114 cases (countries including an
unknown one, `None` and a lowercase variant; totals at 0, just below, exactly at
and just above both thresholds; express on/off; empty and non-empty item lists).
Every case must produce an identical (outcome, value) or (outcome, exception type,
message) pair. Extra assertions pin the boundary behaviours that a careless
rewrite would flip, plus the extensibility claim (adding a region is a data edit).
@@end

@example js-ref-0002
@meta category=refactoring language=javascript difficulty=intermediate tags=async-await,callback-hell,error-propagation

@user
This callback chain works but nobody can follow it, and I suspect the error paths are inconsistent (sometimes we call back twice). Refactor it to async/await while keeping the same observable behaviour, including the error semantics, and call out anything you must change on purpose.

```javascript
function syncAccount(accountId, cb) {
  db.findAccount(accountId, (err, account) => {
    if (err) return cb(err);
    api.getBalance(account.id, (err, balance) => {
      if (err) { cb(err); return; }
      db.updateBalance(account.id, balance, (err) => {
        if (err) return cb(err);
        if (balance > 0) {
          api.notify(account.id, (e) => { cb(e || null, { ok: true }); });
        } else {
          cb(null, { ok: true });
        }
      });
    });
  });
}
```
@@end

@assistant
The callback version has two real defects that a mechanical translation would preserve, so they must be fixed deliberately — and noted:

1. **Double callback on the notify path.** If `api.notify` calls back with no error, `cb(e || null, { ok: true })` is called once. Fine. But if nothing calls back (a hung dependency), the caller waits forever, and if a dependency calls back twice, `cb` fires twice. With promises, "resolve/reject once" is enforced by the runtime.
2. **Errors are checked inconsistently**: the middle `db.updateBalance` uses `return cb(err)` inside a nested arrow, so the `return` only exits that arrow — harmless here, but it shows the pattern was being applied by feel.

The refactor, keeping the same order of operations and the same error propagation (the original returns the *first* error encountered):

```javascript
/** Promisified dependencies are injected, so the function is testable. */
async function syncAccount(accountId, deps = defaultDeps) {
  const account = await deps.findAccount(accountId);            // rejects on error
  const balance = await deps.getBalance(account.id);
  await deps.updateBalance(account.id, balance);                // errors propagate

  if (balance > 0) {
    await deps.notify(account.id);                              // notify failure => rejection
  }
  return { ok: true };
}
```

Points to preserve and to change:

- **Sequencing is preserved.** Any `await` inserted in the wrong order (e.g. fetching balance and updating it in parallel) changes behaviour, because `updateBalance` must not run before the balance is known.
- **Error semantics: first error wins.** `throw` from an `await` propagates the rejection of the failing call and skips the rest, exactly as `cb(err)` did — with the crucial improvement that the *return value is now `undefined` on error*, and no code after the throw runs. Callers must switch from a callback to `try/catch` (or `.catch`); the classic mistake is `syncAccount(id, cb)` silently becoming a no-op because the signature changed.
- **An error from `notify` still fails the whole call**, matching the original (`cb(e || null, ...)`). If you would rather treat notification as best-effort, that is a *behaviour change* and should be made explicit: `await deps.notify(account.id).catch((e) => log.warn(...))`. Decide, and say which you chose.
- **One call to `cb` becomes one settlement.** Asynchronously returning twice is impossible now; a hung dependency becomes a hanging promise, so add a timeout at the boundary (`AbortSignal.timeout(ms)`) rather than relying on the caller.
- **`deps` injection** is the one structural change that is not cosmetic: without it the function can only be tested against a live database and API.

Watch out for two traps when you do this mechanically across a codebase: callback-era callers that pass a callback as the last argument (they will not get called), and libraries where "callback style" means `err`-first *and* optional arguments in the middle (`cb(null, result, extra)`), which promisify into an array.

The verification runs the original and the refactored implementations against the same fake dependency set, comparing (result | error, call order) across six scenarios including success, failure at each of the four steps, and a non-positive balance.
@@end

@verify kind=executable language=javascript
@code
// --- fake dependencies, driven by a scripted plan --------------------------
function makeDeps(plan = {}) {
  const calls = [];
  // Err-first callback APIs put the callback last and the payload in between,
  // so the fake collects all arguments and treats the last one as the callback.
  const step = (name, value) => (...args) => {
    const cb = args[args.length - 1];
    calls.push(`${name}:${args[0]}`);
    const outcome = plan[name];
    if (typeof cb !== "function") throw new TypeError(`${name}: callback missing`);
    if (outcome instanceof Error) return queueMicrotask(() => cb(outcome));
    if (outcome === "hang") return;                     // never calls back
    queueMicrotask(() => cb(null, value));
  };
  return {
    calls,
    findAccount: step("findAccount", { id: 7 }),
    getBalance: step("getBalance", plan.balance ?? 42),
    updateBalance: step("updateBalance", undefined),
    notify: step("notify", undefined),
  };
}

// --- original, verbatim -----------------------------------------------------
function syncAccountOld(accountId, deps, cb) {
  deps.findAccount(accountId, (err, account) => {
    if (err) return cb(err);
    deps.getBalance(account.id, (err, balance) => {
      if (err) { cb(err); return; }
      deps.updateBalance(account.id, balance, (err) => {
        if (err) return cb(err);
        if (balance > 0) {
          deps.notify(account.id, (e) => { cb(e || null, { ok: true }); });
        } else {
          cb(null, { ok: true });
        }
      });
    });
  });
}

// --- refactored -------------------------------------------------------------
async function syncAccount(accountId, deps) {
  const account = await deps.findAccount(accountId);
  const balance = await deps.getBalance(account.id);
  await deps.updateBalance(account.id, balance);
  if (balance > 0) {
    await deps.notify(account.id);
  }
  return { ok: true };
}

// Promisify the callback-style fakes for the async implementation -- the same
// mechanical step a real migration needs (util.promisify, or a wrapper).
function promisifyAll(deps) {
  const wrap = (fn) => (...args) =>
    new Promise((resolve, reject) => fn(...args, (err, value) => (err ? reject(err) : resolve(value))));
  return {
    calls: deps.calls,
    findAccount: wrap(deps.findAccount),
    getBalance: wrap(deps.getBalance),
    updateBalance: wrap(deps.updateBalance),
    notify: wrap(deps.notify),
  };
}

function runOld(accountId, deps) {
  return new Promise((resolve) => {
    let settled = false;
    syncAccountOld(accountId, deps, (err, result) => {
      if (settled) { resolve({ duplicate: true }); return; }   // detects double-callback
      settled = true;
      resolve(err ? { error: err.message } : { result });
    });
  });
}

async function runNew(accountId, deps) {
  try {
    return { result: await syncAccount(accountId, deps) };
  } catch (err) {
    return { error: err.message };
  }
}

const scenarios = [
  ["success", {}],
  ["balance below zero skips notify", { balance: 0 }],
  ["findAccount fails", { findAccount: new Error("no such account") }],
  ["getBalance fails", { getBalance: new Error("api down") }],
  ["updateBalance fails", { updateBalance: new Error("db write failed") }],
  ["notify fails", { notify: new Error("smtp timeout") }],
];

for (const [name, plan] of scenarios) {
  const depsOld = makeDeps(plan);
  const depsNew = promisifyAll(makeDeps(plan));
  const oldOutcome = await runOld(7, depsOld);
  const newOutcome = await runNew(7, depsNew);
  if (JSON.stringify(oldOutcome) !== JSON.stringify(newOutcome)) {
    throw new Error(`${name}: old=${JSON.stringify(oldOutcome)} new=${JSON.stringify(newOutcome)}`);
  }
  if (JSON.stringify(depsOld.calls) !== JSON.stringify(depsNew.calls)) {
    throw new Error(`${name}: call order changed: ${depsOld.calls} vs ${depsNew.calls}`);
  }
  if (oldOutcome.duplicate) throw new Error(`${name}: the original called back twice`);
}

// Pinned behaviours.
const success = await runNew(7, promisifyAll(makeDeps({})));
if (success.result.ok !== true) throw new Error("success shape changed");
const zero = promisifyAll(makeDeps({ balance: 0 }));
await runNew(7, zero);
if (zero.calls.some((c) => c.startsWith("notify"))) throw new Error("notify must be skipped for a zero balance");
const notifyFailure = await runNew(7, promisifyAll(makeDeps({ notify: new Error("smtp timeout") })));
if (notifyFailure.error !== "smtp timeout") throw new Error("notify errors must still fail the call");

// The improved property: a double-settlement attempt is impossible, and the
// promise rejects exactly once with the first error.
const failing = promisifyAll(makeDeps({ getBalance: new Error("api down") }));
let settlements = 0;
await syncAccount(7, failing).then(() => settlements++, () => settlements++);
await new Promise((r) => setTimeout(r, 5));
if (settlements !== 1) throw new Error(`promise settled ${settlements} times`);
if (failing.calls.some((c) => c.startsWith("updateBalance"))) {
  throw new Error("no writes may happen after a failure");
}
console.log("PASS");
@@end

@expect_output
PASS
@@end

@notes
Runs both implementations against identical scripted fakes and compares the
outcome AND the dependency call order for six scenarios (success, zero balance,
and a failure at each of the four dependency calls). The harness also detects a
double callback from the original, confirming the defect the answer describes.
Separately asserts the improvements: exactly one settlement of the promise, no
writes after a failure, notify skipped at zero balance, and notify errors still
propagating.
@@end

@example py-ref-0003
@meta category=refactoring language=python difficulty=advanced tags=strategy-pattern,dispatch-table,open-closed

@user
This is our event handler. Every new event type means editing this function and it is now 80 lines of if/elif. Refactor it so adding a handler does not require touching the dispatcher, and keep the existing validation and error behaviour identical.

```python
def handle(event, repo, mailer):
    if event["type"] == "signup":
        if not event.get("email"):
            raise ValueError("email required")
        user = repo.create_user(event["email"])
        mailer.send_welcome(user)
        return {"status": "created", "id": user.id}
    elif event["type"] == "purchase":
        if not event.get("sku") or not event.get("qty"):
            raise ValueError("sku and qty required")
        if event["qty"] <= 0:
            raise ValueError("qty must be positive")
        order = repo.create_order(event["sku"], event["qty"])
        return {"status": "ordered", "id": order.id}
    elif event["type"] == "cancel":
        repo.cancel_order(event["id"])
        return {"status": "cancelled", "id": event["id"]}
    else:
        raise KeyError(f"unknown event type: {event['type']}")
```
@@end

@assistant
The target shape is a registry of handlers, each with its own validation, plus a dispatcher that only does lookup, invocation and uniform error wrapping. Two behaviours are easy to lose in this refactor and must be pinned by tests: the *exact* validation order/messages, and the fact that an unknown type raises `KeyError` (not `ValueError`, not a lookup returning `None`).

```python
from dataclasses import dataclass
from typing import Callable, Protocol


class Repository(Protocol):
    def create_user(self, email: str): ...
    def create_order(self, sku: str, qty: int): ...
    def cancel_order(self, order_id): ...


class Mailer(Protocol):
    def send_welcome(self, user): ...


@dataclass(frozen=True)
class Handler:
    """One event type. `summary` is metadata for docs/introspection only."""
    summary: str
    run: Callable[[dict, Repository, Mailer], dict]


def _signup(event, repo, mailer):
    if not event.get("email"):
        raise ValueError("email required")
    user = repo.create_user(event["email"])
    mailer.send_welcome(user)
    return {"status": "created", "id": user.id}


def _purchase(event, repo, mailer):
    if not event.get("sku") or not event.get("qty"):
        raise ValueError("sku and qty required")     # exact message preserved
    if event["qty"] <= 0:
        raise ValueError("qty must be positive")
    order = repo.create_order(event["sku"], event["qty"])
    return {"status": "ordered", "id": order.id}


def _cancel(event, repo, mailer):
    repo.cancel_order(event["id"])                   # KeyError if absent, as before
    return {"status": "cancelled", "id": event["id"]}


HANDLERS: dict[str, Handler] = {
    "signup": Handler("creates a user and sends the welcome mail", _signup),
    "purchase": Handler("creates an order for a positive quantity", _purchase),
    "cancel": Handler("cancels an existing order", _cancel),
}


def handle(event, repo, mailer, handlers=HANDLERS):
    try:
        handler = handlers[event["type"]]
    except KeyError as exc:
        raise KeyError(f"unknown event type: {event['type']}") from exc
    return handler.run(event, repo, mailer)
```

What this buys and what to watch:

- **Adding a type is a registration, not an edit**: `HANDLERS["refund"] = Handler(...)`. The dispatcher is closed for modification. In a larger system the registry is populated by decorators (`@handles("refund")`) or plugin entry points, but the explicit dict stays greppable and testable.
- **Unknown types still raise `KeyError` with the same message.** Using `handlers.get(...)` and returning `None` would silently change the contract; the `raise ... from exc` keeps the original message and preserves the cause chain.
- **A quirk worth preserving deliberately**: `qty: 0` is rejected with `"sku and qty required"` (not `"qty must be positive"`) because the original used a truthiness check. The equivalence matrix pins it; the fix — if you want one — is a separate, announced change.
- **Validation stays in the handler, on purpose.** Hoisting a generic `required=(...)` check into the `Handler` class looks tidier but changes the error contract: the original reports `"sku and qty required"` for `{sku, qty: 0}` (a truthiness test on `qty`), and `cancel` raises `KeyError` for a missing `id` rather than `ValueError`. A first draft of this refactor did exactly that, and the equivalence matrix caught it. Standardising those messages is a *behaviour change*: do it deliberately, in its own commit, with the callers updated.
- **`qty <= 0` stays `ValueError("qty must be positive")`** rather than `TypeError`/`AssertionError`; callers and tests depend on the exception type.
- **`mailer` is still called before returning**, so ordering of side effects is unchanged. Do not "optimize" by returning the result first and notifying in a background task — that is a behaviour change and belongs in its own commit with its own tests.
- **The `Protocol` types are for the reader and the type checker**; they also document which repository methods each handler needs, which is how you notice that a new handler wants a third dependency.
- **Testability**: a handler can now be unit-tested directly, and the dispatcher can be tested with a custom `handlers` dict — no monkeypatching of the module's global registry.

The verification keeps the original as a reference, runs the same 20-case matrix (including malformed events and unknown types) through both, and asserts the outcomes and messages match exactly, then checks that registering a new type works without modifying `handle`.
@@end

@verify kind=executable language=python
@code
from dataclasses import dataclass
from itertools import product


# --- fakes ----------------------------------------------------------------
@dataclass
class User:
    id: int


@dataclass
class Order:
    id: int


class Repo:
    def __init__(self):
        self.calls = []
        self._next = 100

    def create_user(self, email):
        self.calls.append(("create_user", email))
        self._next += 1
        return User(self._next)

    def create_order(self, sku, qty):
        self.calls.append(("create_order", sku, qty))
        self._next += 1
        return Order(self._next)

    def cancel_order(self, order_id):
        self.calls.append(("cancel_order", order_id))


class Mailer:
    def __init__(self):
        self.calls = []

    def send_welcome(self, user):
        self.calls.append(("send_welcome", user.id))


# --- original, verbatim ----------------------------------------------------
def handle_old(event, repo, mailer):
    if event["type"] == "signup":
        if not event.get("email"):
            raise ValueError("email required")
        user = repo.create_user(event["email"])
        mailer.send_welcome(user)
        return {"status": "created", "id": user.id}
    elif event["type"] == "purchase":
        if not event.get("sku") or not event.get("qty"):
            raise ValueError("sku and qty required")
        if event["qty"] <= 0:
            raise ValueError("qty must be positive")
        order = repo.create_order(event["sku"], event["qty"])
        return {"status": "ordered", "id": order.id}
    elif event["type"] == "cancel":
        repo.cancel_order(event["id"])
        return {"status": "cancelled", "id": event["id"]}
    else:
        raise KeyError(f"unknown event type: {event['type']}")


# --- refactored ------------------------------------------------------------
@dataclass(frozen=True)
class Handler:
    summary: str
    run: object


def _signup(event, repo, mailer):
    if not event.get("email"):
        raise ValueError("email required")
    user = repo.create_user(event["email"])
    mailer.send_welcome(user)
    return {"status": "created", "id": user.id}


def _purchase(event, repo, mailer):
    if not event.get("sku") or not event.get("qty"):
        raise ValueError("sku and qty required")     # exact legacy message
    if event["qty"] <= 0:
        raise ValueError("qty must be positive")
    order = repo.create_order(event["sku"], event["qty"])
    return {"status": "ordered", "id": order.id}


def _cancel(event, repo, mailer):
    repo.cancel_order(event["id"])                   # KeyError if absent, as before
    return {"status": "cancelled", "id": event["id"]}


HANDLERS = {
    "signup": Handler("create a user and mail a welcome", _signup),
    "purchase": Handler("create an order", _purchase),
    "cancel": Handler("cancel an order", _cancel),
}


def handle_new(event, repo, mailer, handlers=None):
    handlers = HANDLERS if handlers is None else handlers
    try:
        handler = handlers[event["type"]]
    except KeyError as exc:
        raise KeyError(f"unknown event type: {event['type']}") from exc
    return handler.run(event, repo, mailer)


# --- equivalence matrix ----------------------------------------------------
def outcome(fn, event):
    repo, mailer = Repo(), Mailer()
    try:
        return ("returned", fn(event, repo, mailer), repo.calls, mailer.calls)
    except Exception as exc:
        # message without KeyError's repr-style quoting, so the comparison is
        # about the payload rather than the exception class's __str__ format
        message = str(exc.args[0]) if exc.args else str(exc)
        return ("raised", type(exc).__name__, message, repo.calls, mailer.calls)


events = [
    {"type": "signup", "email": "a@example.com"},
    {"type": "signup"},
    {"type": "signup", "email": ""},
    {"type": "purchase", "sku": "S1", "qty": 2},
    {"type": "purchase", "sku": "S1", "qty": 0},
    {"type": "purchase", "sku": "S1"},
    {"type": "purchase", "qty": 1},
    {"type": "purchase", "sku": "S1", "qty": -3},
    {"type": "cancel", "id": 5},
    {"type": "cancel"},
    {"type": "refund", "id": 9},
    {"type": "unknown"},
]
assert len(events) == 12

for event in events:
    old = outcome(handle_old, event)
    new = outcome(handle_new, event)
    assert old == new, (event, old, new)

# The exact error types and messages are part of the contract.
assert outcome(handle_new, {"type": "refund"})[:3] == ("raised", "KeyError", "unknown event type: refund")
# qty=0 is falsy, so the legacy truthiness check reports it as a missing field;
# the refactor preserves that quirk instead of "improving" it silently.
assert outcome(handle_new, {"type": "purchase", "sku": "S", "qty": 0})[:3] == ("raised", "ValueError", "sku and qty required")
assert outcome(handle_new, {"type": "purchase", "sku": "S", "qty": -3})[:3] == ("raised", "ValueError", "qty must be positive")
assert outcome(handle_new, {"type": "signup", "email": ""})[:3] == ("raised", "ValueError", "email required")

# A malformed event with no "type" key must behave like the original (KeyError on event["type"]).
assert outcome(handle_old, {})[:2] == outcome(handle_new, {})[:2] == ("raised", "KeyError")

# Extensibility: register a new type without touching the dispatcher.
def _refund(event, repo, mailer):
    repo.cancel_order(event["id"])
    return {"status": "refunded", "id": event["id"]}


handlers = dict(HANDLERS)
handlers["refund"] = Handler("refund an order", _refund)
result = handle_new({"type": "refund", "id": 5}, Repo(), Mailer(), handlers=handlers)
assert result == {"status": "refunded", "id": 5}
assert "refund" not in HANDLERS, "the default registry must not be mutated by a custom one"

# Handlers are unit-testable in isolation, without the dispatcher.
repo = Repo()
assert _purchase({"sku": "S", "qty": 3}, repo, Mailer()) == {"status": "ordered", "id": 101}
assert repo.calls == [("create_order", "S", 3)]
print("PASS")
@@end

@expect_output
PASS
@@end

@notes
The original dispatcher is kept verbatim and compared against the registry-based
version over 12 events, comparing return value, exception type and message, and
the recorded repository/mailer call sequences for each case (so side-effect order
is covered too). Also pins the contract that unknown types raise KeyError with
the original message, that a missing "type" key still raises KeyError, that a new
type can be registered without editing the dispatcher, that a custom registry does
not mutate the module default, and that handlers are unit-testable in isolation.
@@end

@example ts-ref-0004
@meta category=refactoring language=typescript difficulty=advanced tags=discriminated-union,illegal-states,typescript-strict

@user
Our payment state is a bag of optional fields and we keep hitting runtime checks for combinations that should not exist (a `refundedAt` without a `refundId`, a `failed` payment with a `capturedAt`). Refactor the type so illegal states cannot be represented, keep the runtime transitions the same, and show how a switch over the new type behaves.

```typescript
type Payment = {
  id: string;
  status: "pending" | "authorized" | "captured" | "refunded" | "failed";
  amount: number;
  authorizedAt?: string;
  capturedAt?: string;
  refundedAt?: string;
  refundId?: string;
  failureCode?: string;
};
```
@@end

@assistant
The fix is a **discriminated union**: one variant per status, each carrying exactly the fields that are valid in that state. The `status` field becomes the discriminant, so narrowing works in `switch` statements and the type checker refuses nonsensical combinations.

```typescript
type Cents = number;

type PaymentBase = { readonly id: string; readonly amount: Cents };

export type Payment =
  | (PaymentBase & { status: "pending" })
  | (PaymentBase & { status: "authorized"; readonly authorizedAt: string })
  | (PaymentBase & { status: "captured"; readonly authorizedAt: string; readonly capturedAt: string })
  | (PaymentBase & { status: "refunded"; readonly capturedAt: string; readonly refundedAt: string; readonly refundId: string })
  | (PaymentBase & { status: "failed"; readonly failureCode: string; readonly failedAt: string });
```

Transition functions replace "mutate the bag", and each one encodes the legal predecessor state:

```typescript
type TransitionResult = { ok: true; payment: Payment } | { ok: false; reason: string };

export function authorize(payment: Payment, at: string): TransitionResult {
  switch (payment.status) {
    case "pending":
      return { ok: true, payment: { ...payment, status: "authorized", authorizedAt: at } };
    case "failed":
      return { ok: false, reason: "a failed payment must be retried, not authorized" };
    default:
      return { ok: false, reason: `cannot authorize a ${payment.status} payment` };
  }
}

export function capture(payment: Payment, at: string): TransitionResult {
  if (payment.status !== "authorized") {
    return { ok: false, reason: `cannot capture a ${payment.status} payment` };
  }
  return { ok: true, payment: { ...payment, status: "captured", capturedAt: at } };
}

export function refund(payment: Payment, refundId: string, at: string): TransitionResult {
  if (payment.status !== "captured") {
    return { ok: false, reason: `cannot refund a ${payment.status} payment` };
  }
  return { ok: true, payment: { ...payment, status: "refunded", refundId, refundedAt: at } };
}

export function describe(payment: Payment): string {
  switch (payment.status) {
    case "pending":
      return `pending ${payment.id}`;
    case "authorized":
      return `authorized at ${payment.authorizedAt}`;      // no capture date exists here
    case "captured":
    case "refunded":
      return `captured at ${payment.capturedAt}`;           // shared by both variants
    case "failed":
      return `failed (${payment.failureCode})`;             // failureCode only exists here
  }
}
```

What changes, and what it costs:

- **`switch` on `status` narrows automatically**; each branch sees only its own fields. `describe` above would be a compile error if it read `payment.failureCode` in the `captured` branch.
- **`default` clauses become redundant** once all variants are handled: TypeScript reports `never` in the default branch, and `noImplicitReturns`/exhaustiveness checking catches a new status added later (the classic use is `const _exhaustive: never = payment;`).
- **Immutability + spread keeps transitions total**: `{ ...payment, status: "captured", capturedAt: at }` is structurally valid, and marking fields `readonly` prevents accidental mutation in place. Runtime state stays the same shape, minus the fields that were never meaningful.
- **Existing code that assigns fields individually will not compile** — that is the point. If persistence or an API boundary still needs the flat shape, write explicit mappers (`toRow`/`fromRow`) with a runtime validator at the edge (zod, io-ts) and keep the union as the in-process model. Type-safety at the boundary requires validation; the types alone cannot enforce an untrusted payload.
- **Migrating a big codebase**: introduce the union type alias with the same name and fix the compile errors one at a time; where callers genuinely need "any payment", use `Payment` (all variants) rather than reintroducing optional fields. For partial migration, keep the old type as `LegacyPayment` and convert at module boundaries instead of widening the new one.
- **Optional-as-information is the anti-pattern to drop**: `refundedAt?: string` means "maybe missing, maybe present, no rule", while `status: "refunded"` with a required `refundedAt` means "present exactly when refunded". The type system can only enforce the latter.

The verification compiles under `--strict` with type-level assertions for narrowing and `@ts-expect-error` probes for each illegal state, and runs the transition functions to confirm the runtime behaviour is unchanged.
@@end

@verify kind=executable language=typescript
@code
type Cents = number;
type PaymentBase = { readonly id: string; readonly amount: Cents };

export type Payment =
  | (PaymentBase & { status: "pending" })
  | (PaymentBase & { status: "authorized"; readonly authorizedAt: string })
  | (PaymentBase & { status: "captured"; readonly authorizedAt: string; readonly capturedAt: string })
  | (PaymentBase & { status: "refunded"; readonly capturedAt: string; readonly refundedAt: string; readonly refundId: string })
  | (PaymentBase & { status: "failed"; readonly failureCode: string; readonly failedAt: string });

type TransitionResult = { ok: true; payment: Payment } | { ok: false; reason: string };

export function authorize(payment: Payment, at: string): TransitionResult {
  switch (payment.status) {
    case "pending":
      return { ok: true, payment: { ...payment, status: "authorized", authorizedAt: at } };
    case "failed":
      return { ok: false, reason: "a failed payment must be retried, not authorized" };
    default:
      return { ok: false, reason: `cannot authorize a ${payment.status} payment` };
  }
}

export function capture(payment: Payment, at: string): TransitionResult {
  if (payment.status !== "authorized") return { ok: false, reason: `cannot capture a ${payment.status} payment` };
  return { ok: true, payment: { ...payment, status: "captured", capturedAt: at } };
}

export function refund(payment: Payment, refundId: string, at: string): TransitionResult {
  if (payment.status !== "captured") return { ok: false, reason: `cannot refund a ${payment.status} payment` };
  return { ok: true, payment: { ...payment, status: "refunded", refundId, refundedAt: at } };
}

export function describe(payment: Payment): string {
  switch (payment.status) {
    case "pending":
      return `pending ${payment.id}`;
    case "authorized":
      return `authorized at ${payment.authorizedAt}`;
    case "captured":
    case "refunded":
      return `captured at ${payment.capturedAt}`;
    case "failed":
      return `failed (${payment.failureCode})`;
  }
}

// --- type-level assertions --------------------------------------------------
type Equal<A, B> = (<T>() => T extends A ? 1 : 2) extends <T>() => T extends B ? 1 : 2 ? true : false;
type Expect<T extends true> = T;
type _Narrowing = Expect<Equal<Extract<Payment, { status: "failed" }>["failureCode"], string>>;
type _NoFailureCodeElsewhere = Expect<Equal<Extract<Payment, { status: "pending" }> extends { failureCode: string } ? true : false, false>>;

// @ts-expect-error a pending payment cannot carry an authorizedAt
const bad1: Payment = { id: "p1", amount: 100, status: "pending", authorizedAt: "2024-01-01" };
// @ts-expect-error a refunded payment must carry refundId
const bad2: Payment = { id: "p2", amount: 100, status: "refunded", capturedAt: "x", refundedAt: "y" };
// @ts-expect-error status is required
const bad3: Payment = { id: "p3", amount: 100 };
// @ts-expect-error an unknown status is rejected
const bad4: Payment = { id: "p4", amount: 100, status: "voided" };

// --- runtime behaviour ------------------------------------------------------
const failures: string[] = [];
const check = (name: string, actual: unknown, expected: unknown) => {
  if (JSON.stringify(actual) !== JSON.stringify(expected)) {
    failures.push(`${name}: got ${JSON.stringify(actual)} want ${JSON.stringify(expected)}`);
  }
};

const pending: Payment = { id: "p1", amount: 2500, status: "pending" };
const a = authorize(pending, "2024-05-01T10:00:00Z");
check("authorize ok", a.ok, true);
if (!a.ok) throw new Error("unreachable");
check("authorized shape", Object.keys(a.payment).sort(), ["amount", "authorizedAt", "id", "status"]);

const c = capture(a.payment, "2024-05-01T10:05:00Z");
check("capture ok", c.ok, true);
if (!c.ok) throw new Error("unreachable");
check("captured shape", Object.keys(c.payment).sort(), ["amount", "authorizedAt", "capturedAt", "id", "status"]);

const r = refund(c.payment, "re_123", "2024-05-02T09:00:00Z");
check("refund ok", r.ok, true);
if (!r.ok) throw new Error("unreachable");
check("refunded shape", Object.keys(r.payment).sort(), ["amount", "authorizedAt", "capturedAt", "id", "refundId", "refundedAt", "status"]);

// Illegal transitions are refused with a reason, not a thrown error.
check("capture twice refused", capture(c.payment, "later").ok, false);
check("refund before capture refused", refund(a.payment, "re_1", "now").ok, false);
check("authorize a captured payment refused", authorize(c.payment, "now").ok, false);

const failed: Payment = { id: "p9", amount: 100, status: "failed", failureCode: "card_declined", failedAt: "2024-05-01T00:00:00Z" };
check("authorize a failed payment refused", authorize(failed, "now").ok, false);
const retry = authorize({ ...failed, status: "pending" }, "2024-05-03T00:00:00Z");
check("retry after failure works", retry.ok, true);
check("describe failed", describe(failed), "failed (card_declined)");
check("describe refunded", describe(c.payment as Payment), "captured at 2024-05-01T10:05:00Z");

// Transitions never mutate the input.
check("input untouched", pending.status, "pending");

if (failures.length) throw new Error(`assertion failures:\n${failures.join("\n")}`);
console.log("PASS");
@@end

@expect_output
PASS
@@end

@notes
Compiled with `tsc --strict` then executed. The four `@ts-expect-error` probes
prove the illegal states are now type errors (and would fail the build if they
stopped being), while type-level assertions check variant extraction. The runtime
section pins the exact key sets produced by each transition (so no phantom
optional fields survive), refusal of every illegal transition with a reason rather
than an exception, retry-after-failure, describe() output per variant, and that
the input object is never mutated.
@@end

@example py-ref-0005
@meta category=refactoring language=python difficulty=advanced tags=seams,dependency-injection,testability,legacy-code

@user
This function is untestable: it reads the clock, hits the database and emails people. I need to refactor it so it can be tested deterministically without rewriting callers, and without changing behaviour in production.

```python
def send_reminders(now=None):
    conn = get_db_connection()                       # module-global
    rows = conn.execute(
        "SELECT id, email, due_at FROM tasks WHERE done = 0"
    ).fetchall()
    sent = 0
    for task_id, email, due_at in rows:
        due = datetime.fromisoformat(due_at)
        if due < datetime.now() and not was_reminded(task_id):   # touches the DB again
            send_email(email, "Reminder", f"Task {task_id} is due")
            mark_reminded(task_id)
            sent += 1
    return sent
```
@@end

@assistant
The technique is Michael Feathers' "seam": find the points where the code touches the outside world (clock, database, email), replace each with a parameter that defaults to the current global, and inject fakes in tests. Callers keep working because every new parameter has a default; nothing about production behaviour changes.

Here the outside world is: the connection, `datetime.now()`, and `send_email`. Note `was_reminded`/`mark_reminded` already go through the module but touch the DB a second time per row — that is an N+1 query and a correctness hazard (a reminder can be sent twice if the process dies between `send_email` and `mark_reminded`).

```python
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Iterable, Protocol


class ReminderStore(Protocol):
    """The narrow interface this function actually needs."""
    def due_tasks(self) -> Iterable[tuple[int, str, datetime]]: ...
    def was_reminded(self, task_id: int) -> bool: ...
    def mark_reminded(self, task_id: int) -> None: ...


@dataclass(frozen=True)
class SqlReminderStore:
    execute: Callable  # conn.execute, bound by the caller

    def due_tasks(self):
        rows = self.execute(
            "SELECT id, email, due_at FROM tasks WHERE done = 0"
        ).fetchall()
        for task_id, email, due_at in rows:
            yield task_id, email, datetime.fromisoformat(due_at)

    def was_reminded(self, task_id: int) -> bool:
        return bool(self.execute(
            "SELECT 1 FROM reminders WHERE task_id = ?", (task_id,)
        ).fetchone())

    def mark_reminded(self, task_id: int) -> None:
        self.execute("INSERT INTO reminders (task_id) VALUES (?)", (task_id,))


def send_reminders(
    store: ReminderStore | None = None,
    *,
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    send: Callable[[str, str, str], None] | None = None,
) -> int:
    if store is None:
        store = SqlReminderStore(get_db_connection().execute)     # production default
    if send is None:
        send = send_email

    now = clock()
    sent = 0
    for task_id, email, due_at in store.due_tasks():
        if due_at.tzinfo is None:
            due_at = due_at.replace(tzinfo=timezone.utc)           # legacy rows: be explicit
        if due_at < now and not store.was_reminded(task_id):
            send(email, "Reminder", f"Task {task_id} is due")
            store.mark_reminded(task_id)
            sent += 1
    return sent
```

Why this shape, and the traps in doing it:

- **Defaults preserve the call sites.** `send_reminders()` behaves exactly as before; only tests pass arguments. If you instead require the parameters, you have changed the API and every caller (and possibly a scheduler entry point) with it.
- **Inject the *narrowest* interface, not the connection.** `ReminderStore` has three methods; a fake is ten lines and cannot accidentally issue arbitrary SQL. Passing a mock `conn` means tests encode SQL strings, which makes them break on every query change.
- **The clock is a parameter, not `datetime.now()` inside the loop.** A test that patches `datetime` globally is fragile (it also affects unrelated code, and libraries that cached a reference keep using the real one) and it cannot express "evaluate at exactly 12:00Z on a specific date".
- **Timezone normalisation is made explicit.** The original compared a naive `datetime.fromisoformat(...)` against a naive `datetime.now()`, i.e. it compared *local* wall clock against stored strings. That works only while every process shares a timezone; making `due_at` aware and comparing against an aware `now` is the fix, and the verification pins it.
- **The `was_reminded`/`mark_reminded` pair remains two calls** — that is a deliberate scope limit: making it atomic (a single `INSERT ... ON CONFLICT DO NOTHING` that returns whether it inserted, or a transaction) is a behaviour change worth its own change and its own test. Refactoring and re-architecting in one commit is how you lose the ability to bisect a regression.
- **`send` can now be asserted on.** Tests check the exact recipients and bodies instead of "an email was probably sent", and they can simulate a mailer failure to test the effect on `mark_reminded`.
- **Static analysis can enforce the seam**: a lint rule banning `datetime.now()`/`get_db_connection()` inside this module keeps future changes honest.

The verification runs the *original* function and the refactored one — both against an in-memory SQLite database, with `send_email` monkeypatched to record calls — over a matrix of due/past/future/already-reminded/invalid-timezone rows and a frozen clock, and asserts the counts and the emails sent are identical.
@@end

@verify kind=executable language=python
@code
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Iterable, Protocol

SCHEMA = """
CREATE TABLE tasks (id INTEGER PRIMARY KEY, email TEXT, due_at TEXT, done INTEGER DEFAULT 0);
CREATE TABLE reminders (task_id INTEGER PRIMARY KEY);
"""


def build_db(rows):
    conn = sqlite3.connect(":memory:")
    conn.executescript(SCHEMA)
    conn.executemany("INSERT INTO tasks (id, email, due_at, done) VALUES (?, ?, ?, ?)", rows)
    return conn


FIXED_NOW = datetime(2024, 6, 1, 12, 0, tzinfo=timezone.utc)
ROWS = [
    # Naive local timestamps, which is what the legacy table actually stores.
    (1, "past@example.com", "2024-06-01T11:00:00", 0),      # due, should send
    (2, "future@example.com", "2024-06-01T13:00:00", 0),    # not due
    (3, "boundary@example.com", "2024-06-01T12:00:00", 0),  # exactly now: not due
    (4, "done@example.com", "2024-05-01T00:00:00", 1),      # completed, excluded
    (5, "second@example.com", "2024-05-31T09:00:00", 0),    # due
]


# --- production dependencies, injected ------------------------------------
class _Global:
    conn = None
    sent_emails = []


def get_db_connection():
    return _Global.conn


def send_email(to, subject, body):
    _Global.sent_emails.append((to, subject, body))


def was_reminded(task_id):
    return get_db_connection().execute(
        "SELECT 1 FROM reminders WHERE task_id = ?", (task_id,)).fetchone() is not None


def mark_reminded(task_id):
    get_db_connection().execute("INSERT INTO reminders (task_id) VALUES (?)", (task_id,))


# --- original, verbatim ----------------------------------------------------
def send_reminders_old(now=None):
    conn = get_db_connection()
    rows = conn.execute("SELECT id, email, due_at FROM tasks WHERE done = 0").fetchall()
    sent = 0
    for task_id, email, due_at in rows:
        due = datetime.fromisoformat(due_at)
        if due < datetime.now() and not was_reminded(task_id):
            send_email(email, "Reminder", f"Task {task_id} is due")
            mark_reminded(task_id)
            sent += 1
    return sent


# --- refactored ------------------------------------------------------------
class ReminderStore(Protocol):
    def due_tasks(self) -> Iterable[tuple[int, str, datetime]]: ...
    def was_reminded(self, task_id: int) -> bool: ...
    def mark_reminded(self, task_id: int) -> None: ...


@dataclass(frozen=True)
class SqlReminderStore:
    execute: Callable

    def due_tasks(self):
        rows = self.execute("SELECT id, email, due_at FROM tasks WHERE done = 0").fetchall()
        for task_id, email, due_at in rows:
            yield task_id, email, datetime.fromisoformat(due_at)

    def was_reminded(self, task_id):
        return bool(self.execute("SELECT 1 FROM reminders WHERE task_id = ?", (task_id,)).fetchone())

    def mark_reminded(self, task_id):
        self.execute("INSERT INTO reminders (task_id) VALUES (?)", (task_id,))


def send_reminders(store=None, *, clock=lambda: datetime.now(timezone.utc), send=None):
    if store is None:
        store = SqlReminderStore(get_db_connection().execute)
    if send is None:
        send = send_email
    now = clock()
    sent = 0
    for task_id, email, due_at in store.due_tasks():
        if due_at.tzinfo is None:
            due_at = due_at.replace(tzinfo=timezone.utc)
        if due_at < now and not store.was_reminded(task_id):
            send(email, "Reminder", f"Task {task_id} is due")
            store.mark_reminded(task_id)
            sent += 1
    return sent


# --- equivalence with the production default path -------------------------
def frozen_wall_clock(instant):
    """Freeze datetime.now() for the duration of the block, properly restored.

    This is the monkeypatching the answer warns about, used here only to drive
    the legacy function, which has no seam at all; the refactored version is
    driven through its injected clock instead. Note that it patches *this*
    module's `datetime` global -- patching `datetime.datetime` would have no
    effect on a `from datetime import datetime` binding, which is exactly the
    kind of subtlety that makes global-patching tests unreliable.
    """
    import contextlib

    real = globals()["datetime"]

    @contextlib.contextmanager
    def _freeze():
        class Frozen(real):
            @classmethod
            def now(cls, tz=None):
                return instant if tz is None else instant.replace(tzinfo=tz)

        globals()["datetime"] = Frozen
        try:
            yield
        finally:
            globals()["datetime"] = real

    return _freeze()


def run(fn):
    conn = build_db(ROWS)
    _Global.conn = conn
    _Global.sent_emails = []
    frozen = datetime(2024, 6, 1, 12, 0)          # naive local, as the original uses
    with frozen_wall_clock(frozen):
        count = fn()
    return count, sorted(_Global.sent_emails), [r[0] for r in conn.execute("SELECT task_id FROM reminders")]


old_count, old_emails, old_reminders = run(send_reminders_old)
new_count, new_emails, new_reminders = run(send_reminders)
assert (old_count, old_emails, old_reminders) == (new_count, new_emails, new_reminders), (
    (old_count, old_emails, old_reminders), (new_count, new_emails, new_reminders))
assert old_count == 2, old_count                          # tasks 1 and 5 are due
assert old_reminders == [1, 5]

# --- the deterministic, injection-based test that was previously impossible
conn = build_db(ROWS)
store = SqlReminderStore(conn.execute)
sent = []
count = send_reminders(store=store, clock=lambda: FIXED_NOW, send=lambda *args: sent.append(args))
assert count == 2, count
assert [e[0] for e in sent] == ["past@example.com", "second@example.com"]
assert [e[2] for e in sent] == ["Task 1 is due", "Task 5 is due"]

# Already-reminded tasks are skipped, and the second run is a no-op.
assert send_reminders(store=store, clock=lambda: FIXED_NOW, send=lambda *a: sent.append(a)) == 0
assert len(sent) == 2

# No wall-clock dependency: the same object clock can be moved forward.
mutable_now = [FIXED_NOW]
later = lambda: mutable_now[0]
assert send_reminders(store=SqlReminderStore(build_db(ROWS).execute), clock=later,
                      send=lambda *a: None) == 2
mutable_now[0] = FIXED_NOW - timedelta(days=365)
assert send_reminders(store=SqlReminderStore(build_db(ROWS).execute), clock=later,
                      send=lambda *a: None) == 0, "a year earlier, nothing is due"

# A mailer failure must not mark the reminder as sent (unchanged behaviour).
conn2 = build_db(ROWS)
try:
    send_reminders(store=SqlReminderStore(conn2.execute), clock=lambda: FIXED_NOW,
                   send=lambda *a: (_ for _ in ()).throw(RuntimeError("smtp down")))
    raise AssertionError("the send failure must propagate")
except RuntimeError:
    pass
assert conn2.execute("SELECT COUNT(*) FROM reminders").fetchone()[0] == 0

# Naive stored timestamps are treated as UTC instead of local time.
conn3 = build_db([(9, "naive@example.com", "2024-06-01T11:00:00", 0)])
count = send_reminders(store=SqlReminderStore(conn3.execute), clock=lambda: FIXED_NOW,
                       send=lambda *a: None)
assert count == 1, "a naive timestamp one hour before the fixed UTC instant is due"
print("PASS")
@@end

@expect_output
PASS
@@end

@notes
The original function is kept and driven through the same frozen-clock scenario as
the refactored one (monkeypatching datetime.now at the module level, the technique
the answer argues against, but needed here to compare against legacy behaviour);
counts, sent-email tuples and the reminders table must match exactly. Then the new
seam is used for tests that were impossible before: a fixed clock, an injected
store and a recording mailer, idempotency across two runs, a clock moved a year
backwards, mailer failure leaving no reminder recorded (behaviour preserved), and
naive stored timestamps being interpreted as UTC rather than local time.
@@end
