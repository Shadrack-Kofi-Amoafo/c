@example stm-0001
@meta category=state_management language=javascript difficulty=intermediate tags=immutability,react,memoisation,reference-equality

@user
A component does not re-render when we add a row, even though the data really is updated:

```javascript
// store.js
export const store = { rows: [], filter: "all" };

export function addRow(row) {
  store.rows.push(row);          // mutate in place
}

// selectors.js
const cache = new Map();

export function selectVisibleRows(state) {
  if (cache.get("rows") === state.rows) return cache.get("value");   // memoisation
  const value = state.rows.filter((row) => state.filter === "all" || row.status === state.filter);
  cache.set("rows", state.rows);
  cache.set("value", value);
  return value;
}

// component reads selectVisibleRows(store) and only re-renders when the value changes
```

The array length grows, the UI does not. Why does memoisation hide the update, and what is the rule?
@@end

@assistant
Because the memoisation key is the **reference**, and `push` does not change the reference. `store.rows` is the same array object before and after `addRow`, so the guard `cache.get("rows") === state.rows` is true on the second call and the selector returns the *cached* array — the `filter` result from when the array was empty. The subscriber never learns anything happened, so no re-render. Nothing is wrong with the memoisation: it is correct given its assumption that "same reference means same value", and the mutation violates that assumption.

The rule is that **state is immutable from the outside**: a state update produces a new object graph, and every consumer that needs to notice the change can compare by reference (that is what `React.memo`, `useSelector`, `shouldComponentUpdate` and memoised selectors all do).

```javascript
export function addRow(row) {
  store = { ...store, rows: [...store.rows, row] };   // new object, new array
}
```

```javascript
// or, when the shape gets deeper: an external immutability helper
import { produce } from "immer";

function addRow(row) {
  store = produce(store, (draft) => { draft.rows.push(row); });   // copy-on-write inside
}
```

What to do in practice:

- **Keep mutations inside the updater.** `produce`/`useReducer` let you write `push` in code while producing a new graph; the mutation is on a draft, not on the live state.
- **Update every level of the path.** `{...state, rows: [...state.rows, row]}` — mutating `state.user.profile` requires a new `state`, a new `user`, and a new `profile`; forgetting a level is the classic "the child did not re-render" bug.
- **In a reducer, return new objects and never return the same reference for a change.** `return state` means "nothing changed"; if you mutated first, the store has changed but the subscribers think it has not — the worst of both worlds.
- **Fix stale caches by keying on what you actually use.** A selector that reads `state.filter` and `state.rows` should cache both, or drop the manual cache and use `useMemo`/`createSelector` (which handle this and are easier to invalidate).
- **Diagnose it in one line**: `Object.is(previous, next)` — if a changed store yields `true`, something mutated in place. My verification pins exactly that, plus the "length grew but the selector returned the old array" symptom.
@@end

@verify kind=executable language=javascript
@code
// A minimal store + memoised selector: the same mechanism as any reference-equality
// subscription (React.memo, useSelector, shouldComponentUpdate).
function createStore(initial) {
  let state = initial;
  const subscribers = [];
  return {
    getState: () => state,
    setState: (next) => {
      const previous = state;
      state = next;
      subscribers.forEach((fn) => fn(previous, state));
    },
    subscribe: (fn) => subscribers.push(fn),
  };
}

function createSelector(select) {
  let lastInput = undefined;
  let lastValue = undefined;
  return (state) => {
    if (Object.is(lastInput, state)) return lastValue;
    lastInput = state;
    lastValue = select(state);
    return lastValue;
  };
}

const visibleRows = createSelector((state) =>
  state.rows.filter((row) => state.filter === "all" || row.status === state.filter));

// --- version 1: mutate the array in place -------------------------------------
const mutatingStore = createStore({ rows: [], filter: "all" });
let mutatingRenders = 0;
mutatingStore.subscribe(() => { mutatingRenders += 1; });

const rowA = { id: 1, status: "open" };
const rowB = { id: 2, status: "closed" };

const beforeMutation = mutatingStore.getState();
const selectedBefore = visibleRows(beforeMutation);
mutatingStore.getState().rows.push(rowA);              // the code under review
const selectedAfterPush = visibleRows(mutatingStore.getState());
const afterMutation = mutatingStore.getState();

console.log("rows in the store:", afterMutation.rows.length);
console.log("selector returned the same array:", Object.is(selectedBefore, selectedAfterPush));
console.log("selector value length:", selectedAfterPush.length);
console.log("state reference changed:", !Object.is(beforeMutation, afterMutation));
console.log("subscribers notified:", mutatingRenders);

// --- version 2: immutable update ----------------------------------------------
const immutableStore = createStore({ rows: [], filter: "all" });
let immutableRenders = 0;
immutableStore.subscribe(() => { immutableRenders += 1; });

const addRow = (state, row) => ({ ...state, rows: [...state.rows, row] });
immutableStore.setState(addRow(immutableStore.getState(), rowA));
immutableStore.setState(addRow(immutableStore.getState(), rowB));
console.log("immutable: selector value after two adds:", visibleRows(immutableStore.getState()).length);
console.log("immutable: subscribers notified:", immutableRenders);

// --- version 3: a selector that reads two fields but keys on one --------------
function createRowsKeyedSelector(select) {
  let lastRows = undefined;
  let lastValue = undefined;
  return (state) => {
    if (Object.is(lastRows, state.rows)) return lastValue;    // keys on rows only
    lastRows = state.rows;
    lastValue = select(state);
    return lastValue;
  };
}

const underKeyed = createRowsKeyedSelector((state) =>
  state.rows.filter((row) => state.filter === "all" || row.status === state.filter));
const filteredStore = createStore({ rows: [rowA, rowB], filter: "all" });
console.log("all rows:", underKeyed(filteredStore.getState()).length);
filteredStore.setState({ ...filteredStore.getState(), filter: "open" });   // rows unchanged
console.log("after changing only the filter:", underKeyed(filteredStore.getState()).length,
            "(should be 1)");

// --- version 4: keying on the whole state (or every field used) is correct ----
const wholeStateCache = new Map();
function selectVisibleRowsCorrectly(state) {
  if (wholeStateCache.has(state)) return wholeStateCache.get(state);
  const value = state.rows.filter((row) => state.filter === "all" || row.status === state.filter);
  wholeStateCache.set(state, value);
  return value;
}
console.log("correct selector after the filter change:",
            selectVisibleRowsCorrectly(filteredStore.getState()).length);

function assert(condition, message) {
  if (!condition) throw new Error(message || "assertion failed");
}

assert(Object.is(selectedBefore, selectedAfterPush),
       "the memoised selector returns the stale array");
assert(selectedAfterPush.length === 0, "and the change is invisible to subscribers");
assert(mutatingRenders === 0, "no notification was sent for the mutation");
assert(!Object.is(beforeMutation, afterMutation) === false,
       "mutating in place keeps the state reference identical");
assert(visibleRows(immutableStore.getState()).length === 2);
assert(immutableRenders === 2, "immutable updates notify every subscriber");
assert(underKeyed(filteredStore.getState()).length === 2,
       "the single-field cache stays stale after a filter change");
assert(selectVisibleRowsCorrectly(filteredStore.getState()).length === 1,
       "keying correctly sees the change");
console.log("PASS");
@@end

@expect_output
rows in the store: 1
selector returned the same array: true
selector value length: 0
state reference changed: false
subscribers notified: 0
immutable: selector value after two adds: 2
immutable: subscribers notified: 2
all rows: 2
after changing only the filter: 2 (should be 1)
correct selector after the filter change: 1
PASS
@@end

@notes
Reproduces the "UI does not update" symptom with the mechanism rather than the
symptom: after `push` the store's array length is 2 while the memoised selector returns
the same array object it returned before (so the consumer sees zero rows and is notified
zero times), and `Object.is(previous, next)` confirms the state reference never changed.
The immutable version notifies twice and yields two rows; a second selector that reads
both `rows` and `filter` but keys only on `rows` is shown to stay stale after a filter
change (the state object changed, the array reference did not, so the cache hits), while a selector keyed on what it reads returns the correct one row — the two
distinct bugs (mutation, under-keyed memoisation) are separated by their own assertions.
@@end

@example stm-0002
@meta category=state_management language=javascript difficulty=advanced tags=async,race-condition,stale-response,cancellation

@user
Users complain that a profile sometimes shows the *previous* person's data. Typing in the search box fires a request per keystroke, and the app writes whatever comes back:

```javascript
let profile = null;

async function search(id) {
  const response = await fetch(`/api/profile/${id}`);
  profile = await response.json();      // last response to arrive wins
  render(profile);
}
```

Clicking A then B lands on A's data. Explain the mechanism and give the standard fix.
@@end

@assistant
This is a **stale-response race**, and its name comes from what is actually being
ordered: the responses, not the requests. Click B's request is issued second but can
resolve first (smaller payload, warmer cache, different server shard), so A's response
arrives after B's and overwrites the newer state. "Last write wins" is only correct if
the last write is the newest request — and there is no guarantee of that over the
network. The same bug shape appears in search-as-you-type, tab switching, pagination,
and any "load then setState" without a guard.

The standard fix is to make the write conditional on the request still being current.
Three variants, from simplest to most complete:

```javascript
// 1. sequence number: only the newest request may write
let latestRequestId = 0;

async function search(id) {
  const requestId = ++latestRequestId;
  const response = await fetch(`/api/profile/${id}`);
  const data = await response.json();
  if (requestId !== latestRequestId) return;      // a newer request superseded us
  profile = data;
  render(profile);
}
```

```javascript
// 2. abort the superseded request: stops the work as well as the write
let controller = null;

async function search(id) {
  controller?.abort();
  controller = new AbortController();
  try {
    const response = await fetch(`/api/profile/${id}`, { signal: controller.signal });
    profile = await response.json();
    render(profile);
  } catch (error) {
    if (error.name !== "AbortError") throw error;   // real failures still surface
  }
}
```

```javascript
// 3. framework equivalent: React's effect cleanup is the same guard
useEffect(() => {
  let cancelled = false;
  fetch(`/api/profile/${id}`)
    .then((response) => response.json())
    .then((data) => { if (!cancelled) setProfile(data); });
  return () => { cancelled = true; };               // runs before the next effect
}, [id]);
```

What to take away: **asynchronous reads are not ordered**, so any handler that writes
shared state after an `await` needs either a currency check, a cancellation, or both.
The other two members of this family are worth auditing at the same time — out-of-order
*writes* (retry sending stale data: version/timestamp the payload and let the server
reject old versions) and deduplicated *effects* (an idempotency key so a retried request
does not apply twice).
@@end

@verify kind=executable language=javascript
@code
// A fetch stand-in whose resolution order we control: this is what a network does to
// requests issued in quick succession.
function createFakeFetch(timings) {
  return (url) => {
    const id = url.split("/").pop();
    const delay = timings[id];
    return new Promise((resolve) => {
      setTimeout(() => resolve({ json: async () => ({ id, name: `Person ${id}` }) }), delay);
    });
  };
}

const timings = { A: 60, B: 10 };              // A is issued first but is slower
const fakeFetch = createFakeFetch(timings);

// --- version 1: whatever arrives last wins ------------------------------------
async function runNaive() {
  let profile = null;
  const renders = [];

  async function search(id) {
    const response = await fakeFetch(`/api/profile/${id}`);
    profile = await response.json();
    renders.push(profile.id);
  }

  await Promise.all([search("A"), search("B")]);      // user clicks A, then B
  return { final: profile?.id, renders };
}

// --- version 2: sequence number ------------------------------------------------
async function runSequenced() {
  let profile = null;
  let latestRequestId = 0;
  const renders = [];
  const ignored = [];

  async function search(id) {
    const requestId = ++latestRequestId;
    const response = await fakeFetch(`/api/profile/${id}`);
    const data = await response.json();
    if (requestId !== latestRequestId) {
      ignored.push(id);
      return;
    }
    profile = data;
    renders.push(profile.id);
  }

  await Promise.all([search("A"), search("B")]);
  return { final: profile?.id, renders, ignored };
}

// --- version 3: abort the superseded request ----------------------------------
function createAbortableFetch(timings) {
  return (url, { signal } = {}) => {
    const id = url.split("/").pop();
    return new Promise((resolve, reject) => {
      const timer = setTimeout(
        () => resolve({ json: async () => ({ id, name: `Person ${id}` }) }),
        timings[id],
      );
      if (signal) {
        signal.addEventListener("abort", () => {
          clearTimeout(timer);
          reject(Object.assign(new Error("aborted"), { name: "AbortError" }));
        });
      }
    });
  };
}

async function runAborted() {
  const abortableFetch = createAbortableFetch(timings);
  let controller = null;
  let profile = null;
  const renders = [];
  const aborted = [];

  async function search(id) {
    controller?.abort();
    controller = new AbortController();
    try {
      const response = await abortableFetch(`/api/profile/${id}`, { signal: controller.signal });
      profile = await response.json();
      renders.push(profile.id);
    } catch (error) {
      if (error.name !== "AbortError") throw error;
      aborted.push(id);
    }
  }

  await Promise.all([search("A"), search("B")]);
  return { final: profile?.id, renders, aborted };
}

const naive = await runNaive();
console.log("naive: render order", naive.renders.join(","), "| final profile:", naive.final);

const sequenced = await runSequenced();
console.log("sequenced: render order", sequenced.renders.join(","),
            "| ignored stale response:", sequenced.ignored.join(","),
            "| final profile:", sequenced.final);

const aborted = await runAborted();
console.log("aborted: render order", aborted.renders.join(","),
            "| aborted request:", aborted.aborted.join(","),
            "| final profile:", aborted.final);

function assert(condition, message) {
  if (!condition) throw new Error(message || "assertion failed");
}

assert(naive.renders.join(",") === "B,A", "the slow first response arrives last");
assert(naive.final === "A", "and it clobbers the newer state");
assert(sequenced.renders.join(",") === "B" && sequenced.final === "B");
assert(sequenced.ignored.join(",") === "A", "the stale response is identified and dropped");
assert(aborted.renders.join(",") === "B" && aborted.final === "B");
assert(aborted.aborted.join(",") === "A", "the superseded request is cancelled, not applied");
console.log("PASS");
@@end

@expect_output
naive: render order B,A | final profile: A
sequenced: render order B | ignored stale response: A | final profile: B
aborted: render order B | aborted request: A | final profile: B
PASS
@@end

@notes
Makes the race deterministic by controlling response timing rather than hoping for
network jitter: A is issued first and resolves last, so the naive handler renders
`B,A` and ends with A's data — the user's report reproduced exactly, with the render
order printed as evidence. The sequence-number fix keeps only `B` and records `A` as an
ignored stale response; the abort fix cancels A (in the aborted list, never rendered)
and also ends on `B`. The three implementations share the same fake transport, so the
difference in outcome is attributable to the guard, not to the timing.
@@end

@example stm-0003
@meta category=state_management language=python difficulty=intermediate tags=state-machine,transitions,validation,exhaustive-testing

@user
Our order service has a `status` field updated by a handful of handlers, and support keeps finding orders in impossible states (a cancelled order that was later shipped, an order refunded twice):

```python
def ship(order):
    order.status = "shipped"
    save(order)

def cancel(order):
    order.status = "cancelled"

def refund(order):
    order.paid -= order.total
```

Each handler is simple; the states are not. How should this be structured so impossible transitions cannot happen, and how do I test that they cannot?
@@end

@assistant
The problem is that the state machine lives nowhere: each handler assigns a status directly, so the set of legal states and legal transitions exists only in the heads of the people who wrote the handlers, and every new handler can add an edge that should not exist. Support is not finding bugs in the handlers; they are finding the *missing* validation.

Make the machine explicit — states, events, and an allowed-transition table — and route every change through one function:

```python
from enum import Enum

class Status(Enum):
    PENDING = "pending"
    PAID = "paid"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"

class Event(Enum):
    PAY = "pay"
    SHIP = "ship"
    DELIVER = "deliver"
    CANCEL = "cancel"
    REFUND = "refund"

TRANSITIONS = {
    (Status.PENDING, Event.PAY): Status.PAID,
    (Status.PENDING, Event.CANCEL): Status.CANCELLED,
    (Status.PAID, Event.SHIP): Status.SHIPPED,
    (Status.PAID, Event.CANCEL): Status.CANCELLED,
    (Status.PAID, Event.REFUND): Status.CANCELLED,
    (Status.SHIPPED, Event.DELIVER): Status.DELIVERED,
}

class InvalidTransition(Exception):
    pass

def apply(order, event):
    target = TRANSITIONS.get((order.status, event))
    if target is None:
        raise InvalidTransition(f"{event.value} is not allowed from {order.status.value}")
    order.status = target
    return order
```

Why a table rather than `if` statements in each handler: the table is a single object you can read, log, document, and *exhaustively test*; the guard is impossible to bypass if the only mutation path goes through `apply`; and new events are additive (a new row) rather than edits sprinkled across handlers. Side effects belong at the same layer — refunding money, sending mail — but keyed off the *event that caused the transition*, not off assignments to a status field.

Two design notes that matter in practice:

- **Make illegal states unrepresentable where you can.** `cancelled` and `shipped` are mutually exclusive, so a single `status` field already prevents "shipped and cancelled" — but a separate `cancelled_at` timestamp or a `paid` boolean duplicates the state and lets the duplicates disagree (your double-refund). Prefer deriving (`is_cancelled = status is Status.CANCELLED`) over storing a second flag.
- **Guard the writes at the boundary too.** The state table protects the domain logic; the API layer should reject requests for events that are invalid in the current state with a 409 rather than a 500, and the database should keep a constraint that the status is one of the known values. Layered guards are not redundancy — they are how you find out that something bypassed the machine.

The test: enumerate **every (state, event) pair**, assert that exactly the legal ones produce a transition and every other pair raises `InvalidTransition`. That is an exhaustive proof over the state space rather than a handful of happy-path tests, and it fails the moment someone adds a transition by accident — a table entry is much easier to review than a diff in the middle of a handler.
@@end

@verify kind=executable language=python
@code
import itertools
from enum import Enum


class Status(Enum):
    PENDING = "pending"
    PAID = "paid"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"


class Event(Enum):
    PAY = "pay"
    SHIP = "ship"
    DELIVER = "deliver"
    CANCEL = "cancel"
    REFUND = "refund"


TRANSITIONS = {
    (Status.PENDING, Event.PAY): Status.PAID,
    (Status.PENDING, Event.CANCEL): Status.CANCELLED,
    (Status.PAID, Event.SHIP): Status.SHIPPED,
    (Status.PAID, Event.CANCEL): Status.CANCELLED,
    (Status.PAID, Event.REFUND): Status.CANCELLED,
    (Status.SHIPPED, Event.DELIVER): Status.DELIVERED,
}


class InvalidTransition(Exception):
    pass


class Order:
    def __init__(self, status=Status.PENDING, total=100):
        self.status = status
        self.total = total
        self.paid = 0
        self.history = [status]

    def apply(self, event):
        target = TRANSITIONS.get((self.status, event))
        if target is None:
            raise InvalidTransition(f"{event.value} is not allowed from {self.status.value}")
        self.status = target
        self.history.append(target)
        return self

    def pay(self):
        return self.apply(Event.PAY)

    def ship(self):
        return self.apply(Event.SHIP)

    def deliver(self):
        return self.apply(Event.DELIVER)

    def cancel(self):
        return self.apply(Event.CANCEL)

    def refund(self):
        if self.status is not Status.PAID:
            raise InvalidTransition(f"refund is not allowed from {self.status.value}")
        self.paid -= self.total
        return self.apply(Event.REFUND)


# --- part 1: the exhaustive table check over every (state, event) pair ----------
allowed = set(TRANSITIONS)
observed_allowed = set()
rejected = []
for status, event in itertools.product(Status, Event):
    order = Order(status)
    try:
        order.apply(event)
        observed_allowed.add((status, event))
    except InvalidTransition as exc:
        rejected.append((status.value, event.value, str(exc)))

print("state x event pairs examined:", len(Status) * len(Event))
print("legal transitions that worked:", len(observed_allowed), "of", len(allowed))
print("illegal transitions rejected:", len(rejected), "of",
      len(Status) * len(Event) - len(allowed))
print("table and behaviour agree:", observed_allowed == allowed)

# --- part 2: the impossible sequences support reported -------------------------
shipped = Order().pay().ship()
try:
    shipped.cancel()
    cancel_outcome = "cancelled a shipped order"
except InvalidTransition as exc:
    cancel_outcome = f"refused: {exc}"
print("ship then cancel:", cancel_outcome)

paid = Order().pay()
paid.refund()
try:
    paid.refund()
    double_refund = "refunded twice"
except InvalidTransition as exc:
    double_refund = f"refused: {exc}"
print("double refund:", double_refund)

cancelled = Order().cancel()
try:
    cancelled.ship()
    ship_after_cancel = "shipped a cancelled order"
except InvalidTransition as exc:
    ship_after_cancel = f"refused: {exc}"
print("cancel then ship:", ship_after_cancel)

# --- part 3: reachability - which states can be reached at all? ----------------
def reachable_states(start=Status.PENDING):
    seen, frontier = {start}, [start]
    while frontier:
        current = frontier.pop()
        for (source, event), target in TRANSITIONS.items():
            if source is current and target not in seen:
                seen.add(target)
                frontier.append(target)
    return seen


def dead_ends():
    return [status for status in Status
            if not any(source is status for source, _event in TRANSITIONS)]


print("reachable from pending:", sorted(status.value for status in reachable_states()))
print("terminal states:", sorted(status.value for status in dead_ends()))
print("unreachable states:", sorted(status.value for status in set(Status) - reachable_states()))

# --- part 4: the boundary guard - the same table serves the API layer ----------
HTTP_STATUS = {InvalidTransition: 409}


def handle_request(order, event):
    try:
        order.apply(event)
    except InvalidTransition as exc:
        code = HTTP_STATUS[type(exc)]
        return {"status": code, "error": str(exc)}
    return {"status": 200, "state": order.status.value}


fresh = Order()
print("api pay:", handle_request(fresh, Event.PAY))
print("api ship:", handle_request(fresh, Event.SHIP))
print("api refund after shipping:", handle_request(fresh, Event.REFUND))
print("history:", [status.value for status in fresh.history])

assert len(Status) * len(Event) == 25
assert observed_allowed == allowed, "every legal transition must be reachable by apply()"
assert len(rejected) == 25 - len(allowed), len(rejected)
assert all("is not allowed from" in message for _s, _e, message in rejected)
assert cancel_outcome == "refused: cancel is not allowed from shipped", cancel_outcome
assert double_refund.startswith("refused: refund is not allowed from cancelled"), double_refund
assert ship_after_cancel == "refused: ship is not allowed from cancelled", ship_after_cancel
assert reachable_states() == set(Status), "every status must be reachable from pending"
assert sorted(status.value for status in dead_ends()) == ["cancelled", "delivered"]
assert handle_request(fresh, Event.REFUND)["status"] == 409, "the boundary maps it to 409"
assert HTTP_STATUS[InvalidTransition] == 409
print("PASS")
@@end

@expect_output
state x event pairs examined: 25
legal transitions that worked: 6 of 6
illegal transitions rejected: 19 of 19
table and behaviour agree: True
ship then cancel: refused: cancel is not allowed from shipped
double refund: refused: refund is not allowed from cancelled
cancel then ship: refused: ship is not allowed from cancelled
reachable from pending: ['cancelled', 'delivered', 'paid', 'pending', 'shipped']
terminal states: ['cancelled', 'delivered']
unreachable states: []
api pay: {'status': 200, 'state': 'paid'}
api ship: {'status': 200, 'state': 'shipped'}
api refund after shipping: {'status': 409, 'error': 'refund is not allowed from shipped'}
history: ['pending', 'paid', 'shipped']
PASS
@@end

@notes
Turns the state machine into an exhaustive test: all 25 (state, event) pairs are
attempted and the observed legal set is asserted equal to the declared transition table,
with the remaining 19 asserted to raise `InvalidTransition` and to name the state — so
the table cannot silently drift from the behaviour. The three impossible sequences from
the report (ship-then-cancel, double refund, cancel-then-ship) are each pinned as
refusals with their message, reachability from `pending` is proved to cover every state
and the terminal states are identified, and the last part shows the same exception
mapped to an HTTP 409 at the boundary rather than leaking a 500.
@@end

@example stm-0004
@meta category=state_management language=javascript difficulty=advanced tags=derived-state,single-source-of-truth,invariants,drift

@user
Our cart store keeps `subtotal` and `itemCount` alongside the items so the header can render without recomputing. After adding a discount feature, the header total sometimes disagrees with the cart contents, and the count is occasionally off by one:

```javascript
const store = { items: [], subtotal: 0, itemCount: 0 };

function addItem(item, quantity) {
  store.items.push({ ...item, quantity });
  store.subtotal += item.price * quantity;
  store.itemCount += quantity;
}

function setQuantity(index, quantity) {
  const item = store.items[index];
  store.subtotal += (quantity - item.quantity) * item.price;   // ok
  item.quantity = quantity;                                    // but itemCount is not updated
}

function applyDiscount(code) {
  store.discount = code;                                       // subtotal not recomputed
}
```

Adding a third code path that forgets one of the derived fields is exactly how this breaks. How should the store be shaped so the totals cannot disagree?
@@end

@assistant
The store has three fields that must satisfy an invariant (`subtotal === sum(items)`, `itemCount === sum(quantities)`) but nothing enforces it, so every code path is responsible for remembering — and one forgotten line breaks the invariant silently. The `setQuantity` path already shows the failure inside the snippet: it updates `subtotal` and the item but leaves `itemCount` stale, which is the "off by one" the header shows. `applyDiscount` is a third path that only touches `discount` and leaves `subtotal` describing the pre-discount cart, which is the disagreement.

The durable shape is **one source of truth plus derived values computed on read**:

```javascript
const store = { items: [], discount: null };

const selectors = {
  subtotal: (state) => state.items.reduce((sum, item) => sum + item.price * item.quantity, 0),
  itemCount: (state) => state.items.reduce((sum, item) => sum + item.quantity, 0),
  total: (state) => {
    const subtotal = selectors.subtotal(state);
    return state.discount ? subtotal * (1 - state.discount.rate) : subtotal;
  },
};
```

Derived values cannot drift because they are not stored: any change to `items` or `discount` is reflected the next time they are read. The performance objection ("the header re-renders on every keystroke") is addressed by memoising the *selector* keyed on the inputs it reads — `createSelector`/`useMemo` — which is a cache of a pure function, not a second copy of the truth, so an incorrect cache is a correctness bug you can test rather than a state that drifts forever.

When recomputation is genuinely too expensive (a 10 000-row financial report), keep a cache instead of a second state store:

```javascript
const cached = createSelector(
  [(state) => state.items, (state) => state.discount],
  (items, discount) => computeTotals(items, discount),      // recomputed only when inputs change
);
```

Three rules that keep this shape honest:

- **One writer.** Mutations go through a reducer (`addItem`, `setQuantity`, `applyDiscount`) that returns a new state; no code path assigns to a derived field, because there is no derived field.
- **Express invariants as tests over randomised operation sequences**, not as examples: apply N random operations, then assert `subtotal === recomputed` and `itemCount === total quantity`. This is the test that catches the next forgotten path, and it works for the stored version only if you also assert the invariant after every step.
- **Round money consistently in one place.** `item.price * item.quantity` in floating point accumulates error; compute in integer minor units (cents) or round at a single boundary, otherwise "subtotal disagrees with items" will come back as a rounding story rather than a stale-state story.
@@end

@verify kind=executable language=javascript
@code
// --- the stored version under review -------------------------------------------
function createStoredStore() {
  const store = { items: [], subtotal: 0, itemCount: 0, discount: null };
  return {
    getState: () => store,
    addItem(item, quantity) {
      store.items.push({ ...item, quantity });
      store.subtotal += item.price * quantity;
      store.itemCount += quantity;
    },
    setQuantity(index, quantity) {
      const item = store.items[index];
      store.subtotal += (quantity - item.quantity) * item.price;
      item.quantity = quantity;                       // itemCount is forgotten
    },
    applyDiscount(code, rate) {
      store.discount = { code, rate };                // subtotal is not recomputed
    },
    displayedTotals() {                               // what the header renders
      const subtotal = store.subtotal;
      return {
        subtotal,
        itemCount: store.itemCount,
        total: store.discount ? subtotal * (1 - store.discount.rate) : subtotal,
      };
    },
  };
}

// --- the derived version -------------------------------------------------------
function createDerivedStore() {
  const store = { items: [], discount: null };
  return {
    getState: () => store,
    addItem(item, quantity) {
      store.items.push({ ...item, quantity });
    },
    setQuantity(index, quantity) {
      store.items[index] = { ...store.items[index], quantity };
    },
    applyDiscount(code, rate) {
      store.discount = { code, rate };
    },
    subtotal() {
      return store.items.reduce((sum, item) => sum + item.price * item.quantity, 0);
    },
    itemCount() {
      return store.items.reduce((sum, item) => sum + item.quantity, 0);
    },
    total() {
      const subtotal = this.subtotal();
      return store.discount ? subtotal * (1 - store.discount.rate) : subtotal;
    },
    displayedTotals() {                               // what the header renders
      return { subtotal: this.subtotal(), itemCount: this.itemCount(), total: this.total() };
    },
  };
}

const CATALOGUE = [
  { sku: "a", price: 10 },
  { sku: "b", price: 25 },
];

function truthOf(state) {
  return {
    subtotal: state.items.reduce((sum, item) => sum + item.price * item.quantity, 0),
    itemCount: state.items.reduce((sum, item) => sum + item.quantity, 0),
  };
}

// --- part 1: the drift, step by step ------------------------------------------
const stored = createStoredStore();
stored.addItem(CATALOGUE[0], 2);            // 2 x 10 = 20
stored.addItem(CATALOGUE[1], 1);            // + 25 = 45, count 3
console.log("stored after adds: subtotal", stored.getState().subtotal,
            "| itemCount", stored.getState().itemCount);
stored.setQuantity(0, 5);                   // subtotal += 30 -> 75, itemCount stays 3
console.log("stored after setQuantity: subtotal", stored.getState().subtotal,
            "| itemCount", stored.getState().itemCount, "(should be 6)");
console.log("stored fields vs truth:", stored.getState().subtotal, stored.getState().itemCount,
            "vs", truthOf(stored.getState()));

// --- part 2: the same sequence with derived values ----------------------------
const derived = createDerivedStore();
derived.addItem(CATALOGUE[0], 2);
derived.addItem(CATALOGUE[1], 1);
derived.setQuantity(0, 5);
console.log("derived after the same sequence: subtotal", derived.subtotal(),
            "| itemCount", derived.itemCount());

// --- part 3: the discount path shows the same class of bug --------------------
stored.applyDiscount("SAVE10", 0.1);
console.log("stored after discount: subtotal", stored.getState().subtotal,
            "| discount", stored.getState().discount.code);
derived.applyDiscount("SAVE10", 0.1);
console.log("derived after discount: subtotal", derived.subtotal(), "| total", derived.total());

// --- part 4: randomised operation sequences, checking the invariant every step --
function randomOperations() {
  // A deterministic 32-bit PRNG (mulberry32). Exact integer arithmetic via Math.imul:
  // a naive `seed * multiplier` overflows float precision and the sequence degenerates.
  let state = 20240915;
  const next = (bound) => {
    state = (state + 0x6d2b79f5) >>> 0;
    let t = state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    const value = ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    return Math.floor(value * bound);
  };
  const operations = [];
  for (let index = 0; index < 400; index += 1) {
    const kind = next(3);
    operations.push(
      kind === 0 ? { kind: "add", item: CATALOGUE[next(2)], quantity: 1 + next(4) }
      : kind === 1 ? { kind: "setQuantity", index: next(4), quantity: 1 + next(4) }
      : { kind: "discount", code: "SAVE", rate: 0.1 * next(3) },
    );
  }
  return operations;
}

function replay(factory) {
  const store = factory();
  let driftSteps = 0;
  let appliedOps = 0;
  for (const operation of randomOperations()) {
    if (operation.kind === "add") {
      store.addItem(operation.item, operation.quantity);
      appliedOps += 1;
    } else if (operation.kind === "setQuantity") {
      if (operation.index >= store.getState().items.length) continue;
      store.setQuantity(operation.index, operation.quantity);
      appliedOps += 1;
    } else {
      store.applyDiscount(operation.code, operation.rate);
      appliedOps += 1;
    }
    const shown = store.displayedTotals();          // what the UI would render
    const truth = truthOf(store.getState());        // what the cart actually contains
    if (shown.subtotal !== truth.subtotal || shown.itemCount !== truth.itemCount) driftSteps += 1;
  }
  return { driftSteps, appliedOps };
}

const storedReplay = replay(createStoredStore);
const derivedReplay = replay(createDerivedStore);
console.log("stored store: steps with a broken invariant:", storedReplay.driftSteps,
            "of", storedReplay.appliedOps, "operations");
console.log("derived store: steps with a broken invariant:", derivedReplay.driftSteps);

function assert(condition, message) {
  if (!condition) throw new Error(message || "assertion failed");
}

assert(stored.getState().itemCount === 3, "stored count is stale after setQuantity");
assert(stored.getState().itemCount !== derived.itemCount(), "the two stores disagree");
assert(derived.itemCount() === 6 && derived.subtotal() === 75, derived.getState());
assert(Math.abs(derived.total() - 67.5) < 1e-9, derived.total());
assert(stored.getState().subtotal === 75,
       "the stored subtotal happens to be right: the discount path is the drift");
assert(storedReplay.driftSteps > 0, "the stored store drifts under random operations");
assert(storedReplay.driftSteps < storedReplay.appliedOps,
       "and the drift is intermittent, which is why it was missed");
assert(derivedReplay.driftSteps === 0, "the derived store never drifts");
assert(storedReplay.appliedOps === derivedReplay.appliedOps, "same operation sequence");
console.log("PASS");
@@end

@expect_output
stored after adds: subtotal 45 | itemCount 3
stored after setQuantity: subtotal 75 | itemCount 3 (should be 6)
stored fields vs truth: 75 3 vs { subtotal: 75, itemCount: 6 }
derived after the same sequence: subtotal 75 | itemCount 6
stored after discount: subtotal 75 | discount SAVE10
derived after discount: subtotal 75 | total 67.5
stored store: steps with a broken invariant: 339 of 395 operations
derived store: steps with a broken invariant: 0
PASS
@@end

@notes
Pins the drift with numbers instead of prose: after `setQuantity(0, 5)` the stored store
reports `itemCount` 3 while the true count is 6 (the field was forgotten in that code
path), and the same sequence read from derived selectors is right. The discount path is
then shown to leave the stored subtotal describing the pre-discount cart while the
derived `total()` is 67.5. The decisive evidence is the randomised replay: 400
deterministic operations applied to both stores, comparing *what the UI would render*
(`displayedTotals`) with the truth recomputed from the items after every step — a
nonzero, but partial, drift count for the stored version (which is why the bug survived
casual testing) and exactly zero for the derived one — the test that catches the *next* forgotten path, with the same operation sequence
asserted for both stores so the comparison is fair.
@@end
