# Sample review: 10 examples from each dataset

Generated from the emitted datasets (`dataset/examples.jsonl`, `dataset-v2/examples.jsonl`),
so these are the exact records a training run would consume. Assistant turns and pinned
verification outputs are reproduced in full; the verification program is truncated to its
first 22 lines for readability (the complete program is in the JSONL).

## Dataset 1 - 57 examples, 12 categories (showing 10)

### 1. `py-code-0004` - code_generation / python / advanced

*tags: ttl-cache, single-flight, threading, eviction*

**User turn**

Implement a bounded TTL cache we can safely share across worker threads: max N entries, entries expire after T seconds, least-recently-used eviction, and — importantly — when a key is missing, only one thread may compute it while the others wait for that result rather than stampeding the database.

**Assistant turn**

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

**Verification** - `kind=executable language=python`

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
    done: threading.Event
    value: V | None = None
    error: BaseException | None = None

... [195 more lines of the executable check]
```

Pinned output of that program:

```text
PASS
```

---

### 2. `sql-read-0004` - code_understanding / sql / intermediate

*tags: left-join, null-semantics, count, subtle-bugs*

**User turn**

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

**Assistant turn**

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

**Verification** - `kind=executable language=sql`

```sql
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
... [30 more lines of the executable check]
```

Pinned output of that program:

```text
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
```

---

### 3. `js-dbg-0003` - debugging / javascript / intermediate

*tags: async, foreach, promise, error-handling*

**User turn**

Our publish step reports success but the uploaded files are missing, and sometimes the process logs an unhandled rejection. The code uses `items.forEach(async (item) => { ... })`. Explain what is actually happening and give me the two correct ways to write it.

**Assistant turn**

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

**Verification** - `kind=executable language=javascript`

```javascript
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
... [69 more lines of the executable check]
```

Pinned output of that program:

```text
PASS
```

---

### 4. `ts-ref-0004` - refactoring / typescript / advanced

*tags: discriminated-union, illegal-states, typescript-strict*

**User turn**

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

**Assistant turn**

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

**Verification** - `kind=executable language=typescript`

```typescript
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
... [81 more lines of the executable check]
```

Pinned output of that program:

```text
PASS
```

---

### 5. `c-opt-0005` - optimization / c / advanced

*tags: complexity, sorting, instrumentation, gcc*

**User turn**

This function finds duplicate IDs in a batch and it is the hot spot in our ingest path (batches of ~50k). Rewrite it to be asymptotically better, in C, and give me machine-checkable evidence rather than a benchmark screenshot.

```c
int count_duplicates(const unsigned *ids, size_t n) {
    int duplicates = 0;
    for (size_t i = 0; i < n; i++)
        for (size_t j = i + 1; j < n; j++)
            if (ids[i] == ids[j]) { duplicates++; break; }
    return duplicates;
}
```

**Assistant turn**

The double loop is O(n²): 50k ids means up to 1.25 billion comparisons, which dominates everything else in the ingest path. Sorting first makes it O(n log n) with a trivially cheap single scan, and for dense integer IDs a bitset or hash set makes it O(n).

```c
#include <stdbool.h>
#include <stddef.h>
#include <stdlib.h>

static int cmp_unsigned(const void *a, const void *b)
{
    unsigned x = *(const unsigned *)a, y = *(const unsigned *)b;
    return (x > y) - (x < y);                 /* branch-free three-way compare */
}

/* Counts ids that appear more than once: O(n log n) time, O(n) scratch space. */
int count_duplicates(const unsigned *ids, size_t n)
{
    if (n < 2) return 0;

    unsigned *sorted = malloc(n * sizeof *sorted);
    if (!sorted) return -1;                   /* caller decides how to fail */

    for (size_t i = 0; i < n; i++) sorted[i] = ids[i];
    qsort(sorted, n, sizeof *sorted, cmp_unsigned);

    int duplicates = 0;
    for (size_t i = 1; i < n; i++)
        if (sorted[i] == sorted[i - 1]) duplicates++;   /* each extra occurrence counts */
    free(sorted);
    return duplicates;
}
```

Points that decide whether this is actually faster in your pipeline:

- **Do not sort the caller's array.** Copying costs O(n) memory but keeps the function free of side effects — an in-place sort that the caller did not expect is a nasty bug to find. If the caller can tolerate reordering, dropping the copy saves one pass; make that a separate, clearly named function.
- **Match the original's counting semantics exactly.** The double loop counts each *extra occurrence*: `{7,7,7}` contributes 2, because indices 0 and 1 each find a later equal element. The sorted scan adds one per adjacent equal pair, which is the same number. The tempting "collapse the run and count each duplicated id once" version returns 1 and silently changes a data-quality metric — the cross-check below pins the metric as well as the value.
- **`qsort` is generic; a specialised sort wins.** For integers, radix sort or `qsort_r` with a bucket array is often 2-4x faster than `qsort`, because the comparator callback defeats inlining. If you know the id range, a bitset is O(n) with no sorting at all:

```c
/* Dense ids below max_id: O(n) time, one bit per id. */
int count_duplicates_bitset(const unsigned *ids, size_t n, unsigned max_id, unsigned char *bits)
{
    if (max_id > 8u * 1024u * 1024u) return -1;     /* bound the allocation */
    size_t bytes = (max_id + 8) / 8;
    for (size_t i = 0; i < bytes; i++) bits[i] = 0;
    int duplicates = 0;
    for (size_t i = 0; i < n; i++) {
        unsigned char mask = (unsigned char)(1u << (ids[i] & 7u));
        unsigned char *byte = &bits[ids[i] >> 3];
        if (*byte & mask) duplicates++;             /* already seen: count per occurrence */
        else *byte |= mask;
    }
    return duplicates;
}
```

- **All three implementations count extra occurrences**, so they are interchangeable. A metric like "how many distinct ids are duplicated" is a different function (count runs, not pairs) and deserves a different name; conflating the two is a silent metric change.
- **Evidence, not impressions.** Count comparisons with an instrumented comparator so the O(n²) vs O(n log n) claim is machine-checkable, then assert equality of results against a brute-force reference on random inputs. Timing is only a sanity check, and only with a wide margin.
- **Match the allocator to the lifetime**: a per-batch `malloc`/`free` of n·4 bytes is fine at 50k (200 KB); at 50M ids, allocate one scratch buffer per worker thread and reuse it rather than hammering the allocator.

The verification counts comparisons exactly instead of trusting a stopwatch: the quadratic version's count must grow 3-5x per doubling of n, and both rewrites are cross-checked against it on 200 randomized batches so a changed *counting metric* fails just as loudly as a changed answer.

**Verification** - `kind=executable language=c`

```c
#include <stdbool.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static unsigned long long comparisons = 0;

/* ---- reference: quadratic, with instrumented comparisons ---------------- */
int count_duplicates_slow(const unsigned *ids, size_t n)
{
    int duplicates = 0;
    for (size_t i = 0; i < n; i++) {
        for (size_t j = i + 1; j < n; j++) {
            comparisons++;
            if (ids[i] == ids[j]) { duplicates++; break; }
        }
    }
    return duplicates;
}

/* ---- O(n log n): sort a copy, then scan runs ---------------------------- */
... [132 more lines of the executable check]
```

Pinned output of that program:

```text
PASS
```

---

### 6. `ml-lang-0003` - cross_language / multi / expert

*tags: integer-division, modulo, overflow, parity*

**User turn**

We ported a Python analytics job to a C service and a Node worker. Everything matched until last week: events before 1970 started landing in the wrong day bucket, and a hash-based sharding key produced a negative index that crashed the C worker. All three implementations look identical. What is going on?

**Assistant turn**

`/` and `%` are not the same operations in these languages, and the difference only shows up for negative operands — which is exactly what pre-1970 timestamps and signed hash codes are:

| Expression | Python | C / Java / Go | JavaScript |
| --- | --- | --- | --- |
| `-7 / 2` (integer) | `-4` (floor) | `-3` (truncate) | `Math.trunc(-7/2) = -3` |
| `-7 % 2` | `1` (sign of divisor) | `-1` (sign of dividend) | `-1` |
| `7 % -2` | `-1` | `1` | `1` |

So a day bucket `timestamp / 86400` gives `-1` for 1969-12-31T23:59:59Z in Python and `0` in C and JS: every pre-1970 event moves forward one day, and the bug is invisible in any dataset that starts in 1970.

Three rules for porting:

- **Name the rounding rule at the boundary.** Use `floor` when bucketing (calendar days, histogram bins, pagination) and `trunc` when you mean "drop the remainder" (array indices, alignment). Write the helper once per language and test it with negative inputs.
- **Make remainders non-negative before indexing.** `hash % n` is negative in C and JS for negative hashes; fix it with `((h % n) + n) % n`. In C a negative index is undefined behaviour (the crash you saw); in Python `list[-1]` silently reads the *last* element — the same mistake, two very different failures.
- **Mask explicitly when you want fixed-width arithmetic.** Python integers never wrap, JS numbers lose precision above 2**53 (`BigInt` needed), and only C's *unsigned* types wrap by definition — signed overflow is UB. An FNV-1a hash is the same value in all three languages only if Python masks with `& 0xFFFFFFFF` and JS uses `Math.imul(...) >>> 0`.

```javascript
const hash32 = (text) => {
  let hash = 2166136261;
  for (const byte of new TextEncoder().encode(text)) {
    hash = Math.imul(hash ^ byte, 16777619) >>> 0;   // >>> 0 is the 32-bit mask
  }
  return hash;
};

const bucketOf = (seconds) => Math.floor(seconds / 86400);   // floor, not trunc
const dayIndex = (hash, tableSize) => ((hash % tableSize) + tableSize) % tableSize;
```

The verification below compiles the C version with `cc`, runs the Node version and compares all three, so the table above is a measurement of this toolchain rather than a recollection.

**Verification** - `kind=executable language=python`

```python
import json
import shutil
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

C_SOURCE = r'''
#include <stdio.h>
#include <stdint.h>

/* Floor division, spelled out: C truncates toward zero. */
static int64_t floor_div(int64_t a, int64_t b) {
    int64_t quotient = a / b;
    if ((a % b != 0) && ((a < 0) != (b < 0))) quotient--;
    return quotient;
}

int main(void) {
    const int64_t stamps[] = {-1, -86399, -86400, -86401, 0, 1, 86399, 86400, 1700000000};
    const size_t n = sizeof(stamps) / sizeof(stamps[0]);
    for (size_t i = 0; i < n; i++) {
... [231 more lines of the executable check]
```

Pinned output of that program:

```text
PASS
```

---

### 7. `js-alg-0003` - algorithms / javascript / expert

*tags: topological-sort, cycle-detection, determinism, build-systems*

**User turn**

Our Node build orchestrator needs a topological order of task names that is stable across runs (byte-identical build logs, so alphabetical tie-breaking is required), and when the graph has a cycle it must print the actual cycle, e.g. "b -> c -> b", instead of just saying "cycle detected". How do I get both?

**Assistant turn**

Kahn's algorithm gives the stable order if you replace the "ready" queue with a min-heap keyed by name; a FIFO queue produces whatever order the hash map happened to iterate in.

For the cycle, the property to exploit is that the leftover set is closed under **predecessors**: a node survives Kahn only because some prerequisite of it was never emitted, so every leftover node has at least one leftover prerequisite. Walking *backwards* along prerequisites therefore never leaves the leftover set and must revisit a node, which yields a real cycle. (Walking forwards along dependents does **not** work — a survivor can have all of its own dependents already emitted. That mistake is why naive cycle reporters print "cycle detected" with no path.)

```javascript
// nodes: string[]; edges: Map<string, string[]>  a -> [things that depend on a]
export function topoSort(nodes, edges) {
  const indegree = new Map(nodes.map((n) => [n, 0]));
  const children = new Map(nodes.map((n) => [n, []]));   // out-edges: dependents
  const parents = new Map(nodes.map((n) => [n, []]));    // in-edges:  prerequisites
  for (const [from, tos] of edges) {
    if (!children.has(from)) throw new Error(`unknown node: ${from}`);
    for (const to of tos) {
      if (!children.has(to)) throw new Error(`unknown node: ${to}`);
      children.get(from).push(to);
      parents.get(to).push(from);
      indegree.set(to, indegree.get(to) + 1);
    }
  }

  const heap = new MinHeap();                            // deterministic tie-break
  for (const [node, degree] of indegree) if (degree === 0) heap.push(node);

  const order = [];
  while (heap.size > 0) {
    const node = heap.pop();
    order.push(node);
    for (const next of children.get(node)) {
      const degree = indegree.get(next) - 1;
      indegree.set(next, degree);
      if (degree === 0) heap.push(next);
    }
  }

  if (order.length !== nodes.length) {
    return { order: null, cycle: findCycle(nodes, parents, indegree) };
  }
  return { order, cycle: null };
}

function findCycle(nodes, parents, indegree) {
  // Deterministic, human-friendly entry point into the leftover set.
  const start = nodes.filter((n) => indegree.get(n) > 0).sort()[0];
  const seenAt = new Map([[start, 0]]);
  const walk = [start];              // walk[k] is a prerequisite of walk[k-1]
  let node = start;
  for (;;) {
    // Never empty: a leftover node's positive in-degree is owed to a leftover
    // prerequisite. Sort so the reported cycle does not depend on edge order.
    const prev = parents.get(node).filter((p) => indegree.get(p) > 0).sort()[0];
    if (seenAt.has(prev)) {
      // walk is reversed (prerequisite order), so flip it to edge direction.
      return walk.slice(seenAt.get(prev)).concat(prev).reverse();
    }
    seenAt.set(prev, walk.length);
    walk.push(prev);
    node = prev;
  }
}

class MinHeap {                                     // small binary heap, string keys
  constructor() { this.items = []; }
  get size() { return this.items.length; }
  push(v) {
    const a = this.items; a.push(v);
    let i = a.length - 1;
    while (i > 0) {
      const p = (i - 1) >> 1;
      if (a[p] <= a[i]) break;
      [a[p], a[i]] = [a[i], a[p]]; i = p;
    }
  }
  pop() {
    const a = this.items, top = a[0], last = a.pop();
    if (a.length) {
      a[0] = last;
      let i = 0;
      for (;;) {
        const l = 2 * i + 1, r = l + 1;
        let m = i;
        if (l < a.length && a[l] < a[m]) m = l;
        if (r < a.length && a[r] < a[m]) m = r;
        if (m === i) break;
        [a[m], a[i]] = [a[i], a[m]]; i = m;
      }
    }
    return top;
  }
}
```

Design notes worth keeping:

- **Determinism has three sources** and all must be handled: heap tie-breaking (done), iterating `indegree`/`children` in insertion order (JS `Map` guarantees this, so build them from the caller's `nodes` array), and the choice of start node plus candidate prerequisite in `findCycle` (both sorted).
- **The walk in `findCycle` terminates in ≤ n steps** and can only repeat inside the leftover set, because every candidate list it filters is non-empty by the closure property above.
- **Self-loops** (`a -> a`) fall out for free: `a` keeps in-degree ≥ 1, the walk goes `a -> a`, and the cycle is `["a", "a"]`, which reads correctly as "a -> a".
- **The returned cycle is in edge direction** (`b -> c -> b`), which is what a human debugging a build cycle needs. Getting the orientation wrong is easy when you walk backwards; the test below validates every consecutive pair against the real edge set.
- **Duplicate edges** must be de-duplicated by the caller (or counted consistently): adding `a -> b` twice makes `b` need two satisfactions, and the order silently shrinks. Normalize with a `Set` per node if the input is untrusted.
- **Complexity:** O(V + E + V log V) time — the heap costs log V per push, and each edge is relaxed once. The cycle walk is O(V log V) worst case. O(V + E) space.

The test below checks the three properties that matter — every edge respected, byte-identical output across runs and across input permutations, and the reported cycle being a genuine cycle of the graph — over thousands of random graphs, including ones with duplicates and self-loops removed.

**Verification** - `kind=executable language=javascript`

```javascript
function topoSort(nodes, edges) {
  const indegree = new Map(nodes.map((n) => [n, 0]));
  const children = new Map(nodes.map((n) => [n, []]));
  const parents = new Map(nodes.map((n) => [n, []]));
  for (const [from, tos] of edges) {
    for (const to of tos) {
      children.get(from).push(to);
      parents.get(to).push(from);
      indegree.set(to, indegree.get(to) + 1);
    }
  }
  const heap = new MinHeap();
  for (const [node, degree] of indegree) if (degree === 0) heap.push(node);

  const order = [];
  while (heap.size > 0) {
    const node = heap.pop();
    order.push(node);
    for (const next of children.get(node)) {
      const degree = indegree.get(next) - 1;
      indegree.set(next, degree);
      if (degree === 0) heap.push(next);
... [147 more lines of the executable check]
```

Pinned output of that program:

```text
PASS
```

---

### 8. `py-ds-0005` - data_structures / python / advanced

*tags: intervals, binary-search, invariants, allocation*

**User turn**

We allocate ID ranges per tenant (like `1000-2000`). Right now we keep ranges in a Python list, linear-scan on every allocation, and adjacent ranges never merge, so after a week we have thousands of fragments and the overlap check is O(n). I want a structure that keeps the ranges sorted and merged, with an explicit statement of the invariant, and I want the adjacency bug covered by tests.

**Assistant turn**

Keep a **sorted list of disjoint, non-adjacent half-open intervals** and use `bisect` to find the one splice window that the new range touches. Insert is O(log n) to locate plus O(k) to replace the k merged neighbours; membership is O(log n). The container is still a plain list — what makes it fast is the invariant, and what makes it *correct* is treating "touches" and "overlaps" as the same condition.

The invariant, stated so a reviewer can check it:

1. `ranges[i].end <= ranges[i+1].start` — ordered and disjoint.
2. `ranges[i].end < ranges[i+1].start` — **non-adjacent**: touching intervals are merged. This is the half the current code is missing, and it is why the list fragments.
3. Every interval is non-empty (`start < end`), so each allocated set has exactly one representation.

```python
from bisect import bisect_left


class RangeSet:
    """Sorted, disjoint, non-adjacent half-open [start, end) intervals."""

    __slots__ = ("_ranges",)

    def __init__(self, ranges=()):
        self._ranges = []
        for start, end in sorted(ranges):
            self.add(start, end)

    def __len__(self):
        return len(self._ranges)

    def __contains__(self, value):
        i = bisect_left(self._ranges, (value, float("inf")))
        return i > 0 and self._ranges[i - 1][1] > value

    def add(self, start, end):
        if start >= end:
            raise ValueError(f"empty or reversed range [{start}, {end})")
        ranges = self._ranges
        # First interval that starts at or after `start`; the only interval that
        # can touch or overlap on the left is its predecessor.
        i = bisect_left(ranges, (start, start))
        if i > 0 and ranges[i - 1][1] >= start:      # >= covers touching too
            i -= 1
        merged_start, merged_end = start, end
        j = i
        while j < len(ranges) and ranges[j][0] <= merged_end:
            merged_start = min(merged_start, ranges[j][0])
            merged_end = max(merged_end, ranges[j][1])
            j += 1
        ranges[i:j] = [(merged_start, merged_end)]

    def allocated(self, start=None, end=None):
        """Total allocated size, optionally restricted to [start, end)."""
        if start is None:
            return sum(b - a for a, b in self._ranges)
        total = 0
        for a, b in self._ranges:
            lo, hi = max(a, start), min(b, end)
            if hi > lo:
                total += hi - lo
        return total

    def free_before(self, limit):
        """First value in [0, limit) that is not allocated, or None."""
        cursor = 0
        for a, b in self._ranges:
            if a > cursor:
                return cursor
            cursor = max(cursor, b)
            if cursor >= limit:
                return None
        return cursor if cursor < limit else None
```

The three lines that decide correctness:

- **`>= start` on the left neighbour.** Overlap (`>`) and adjacency (`==`) both mean "this interval must be absorbed". Writing `>` leaves adjacent-left intervals unmerged — one form of the bug.
- **`<= merged_end` in the absorb loop.** Comparing against the *growing* `merged_end` (not the original `end`) is what lets one insert absorb a chain of neighbours, and because the comparison is `<=` it also absorbs a right-hand neighbour that merely touches. Writing `<` is the other form of the bug.
- **`bisect_left(ranges, (start, start))`.** Intervals are tuples, so lexicographic comparison works directly and no key function is needed. Note the probe value carries `start` in the second slot: `(start, start)` sorts before any interval that begins at `start`.

Complexity notes for the design doc: `add` is O(log n + k) where k is the number of intervals merged (amortised O(log n) if you also count deletions from the list), `__contains__` is O(log n), `allocated` is O(n) over intervals but O(1) amortised per point of allocation because it iterates the merged list, not the values; and `free_before` is deliberately O(n) prefix-shaped work — if it gets hot, keep a separate free-list structure rather than complicating this invariant. Two more production points: the list is not thread-safe (guard `add` with a lock, since `bisect` plus slice assignment is a read-modify-write), and `add` with an empty or reversed range must raise rather than silently vanish, because a silent no-op on `add(5, 5)` hides an off-by-one upstream.

**Verification** - `kind=executable language=python`

```python
import random
from bisect import bisect_left


class RangeSet:
    __slots__ = ("_ranges",)

    def __init__(self, ranges=()):
        self._ranges = []
        for start, end in sorted(ranges):
            self.add(start, end)

    def __len__(self):
        return len(self._ranges)

    @property
    def ranges(self):
        return list(self._ranges)

    def __contains__(self, value):
        i = bisect_left(self._ranges, (value, float("inf")))
        return i > 0 and self._ranges[i - 1][1] > value
... [140 more lines of the executable check]
```

Pinned output of that program:

```text
PASS
```

---

### 9. `py-sec-0001` - security / python / advanced

*tags: password-hashing, scrypt, constant-time, key-versioning*

**User turn**

Our user table stores `sha256(password)` — no salt, one round. A penetration test flagged it and gave us two weeks. What should we store instead, and how do we migrate existing rows without forcing 200k users to reset their passwords? We are on Python 3.11 stdlib only.

**Assistant turn**

Unsalted SHA-256 is the worst case: one GPU rig tries billions of guesses per second, and an identical password produces an identical hash, so a single rainbow table cracks every user at once. Replace it with a **memory-hard** KDF — `hashlib.scrypt` is in the stdlib and designed so that brute-forcing costs memory, not just CPU.

The design that survives a review:

- **Per-user random salt** (16+ bytes from `secrets`), stored beside the hash. Salt defeats rainbow tables and makes identical passwords hash differently.
- **A versioned record**, not a bare digest: `scrypt$1$n=16384,r=8,p=1$<salt>$<hash>`. Versioning is what lets you raise the cost factor next year without a flag day.
- **Constant-time comparison** with `secrets.compare_digest`. `==` short-circuits, which leaks the length of the correct prefix through timing.
- **Verify on login, upgrade on success.** The only moment you hold the plaintext is login, so that is where you re-hash the legacy rows. No forced reset, and the work is spread over normal traffic.
- **Parameter sets you can defend.** `n=16384, r=8, p=1` needs ~16MB per hash (128·n·r bytes); tune against your login budget and record the parameters *in* the record so verification never depends on today's constants.
- **A pepper for defence in depth** — an HMAC of the password with a key stored outside the database (env/KMS) — means a database dump alone is not enough. Apply it as `hmac(pepper, password)` before the KDF, and treat rotating the pepper as a login-time migration too.

```python
import base64
import hashlib
import hmac
import secrets

SCRYPT_N, SCRYPT_R, SCRYPT_P = 16384, 8, 1
SALT_BYTES = 16
CURRENT_VERSION = 1


def _peppered(password: str, pepper: bytes) -> bytes:
    return hmac.new(pepper, password.encode("utf-8"), hashlib.sha256).digest()


def hash_password(password: str, *, pepper: bytes = b"", version: int = CURRENT_VERSION) -> str:
    if not password:
        raise ValueError("empty password")
    salt = secrets.token_bytes(SALT_BYTES)
    digest = hashlib.scrypt(
        _peppered(password, pepper), salt=salt,
        n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32, maxmem=64 * 1024 * 1024,
    )
    return "$".join([
        "scrypt", str(version),
        f"n={SCRYPT_N},r={SCRYPT_R},p={SCRYPT_P}",
        base64.b64encode(salt).decode(),
        base64.b64encode(digest).decode(),
    ])


def verify_password(password: str, record: str, *, pepper: bytes = b"") -> tuple[bool, bool]:
    """Return (ok, needs_rehash). Legacy sha256 records are supported for migration."""
    if record.startswith("scrypt$"):
        _, version, params, salt_b64, digest_b64 = record.split("$")
        settings = dict(part.split("=") for part in params.split(","))
        n, r, p = int(settings["n"]), int(settings["r"]), int(settings["p"])
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
        candidate = hashlib.scrypt(
            _peppered(password, pepper), salt=salt, n=n, r=r, p=p,
            dklen=len(expected), maxmem=64 * 1024 * 1024,
        )
        ok = secrets.compare_digest(candidate, expected)
        needs_rehash = ok and (
            int(version) != CURRENT_VERSION or (n, r, p) != (SCRYPT_N, SCRYPT_R, SCRYPT_P)
        )
        return ok, needs_rehash
    if record.startswith("sha256$"):
        legacy = hashlib.sha256(password.encode("utf-8")).hexdigest()
        ok = secrets.compare_digest(legacy, record.split("$", 1)[1])
        return ok, ok          # a legacy record is always upgraded on success
    raise ValueError("unrecognised password record")


def login(password: str, record: str, *, pepper: bytes = b"") -> tuple[bool, str | None]:
    """Verify and, on success, return a fresh record when the old one is weak."""
    ok, needs_rehash = verify_password(password, record, pepper=pepper)
    if not ok:
        return False, None
    if needs_rehash:
        return True, hash_password(password, pepper=pepper)
    return True, None
```

Two more things the ticket will not mention but the review will ask about:

- **Rate limiting is not optional.** A perfect KDF still falls to online guessing if the endpoint allows unlimited attempts; the login handler needs a per-account and per-IP limiter, and the timing of "unknown user" must match "wrong password" (hash a dummy record so the response time does not reveal account existence).
- **`dklen` / `maxmem` are part of the parameters.** `hashlib.scrypt` raises `ValueError: memory limit exceeded` if OpenSSL's default `maxmem` (32MB) is below `128·n·r`; passing `maxmem` explicitly avoids a login outage on the day you raise `n`.

**Verification** - `kind=executable language=python`

```python
import base64
import hashlib
import hmac
import secrets
import time

SCRYPT_N, SCRYPT_R, SCRYPT_P = 16384, 8, 1
SALT_BYTES = 16
CURRENT_VERSION = 1


def _peppered(password, pepper):
    return hmac.new(pepper, password.encode("utf-8"), hashlib.sha256).digest()


def hash_password(password, *, pepper=b"", version=CURRENT_VERSION, salt=None):
    if not password:
        raise ValueError("empty password")
    salt = salt or secrets.token_bytes(SALT_BYTES)
    digest = hashlib.scrypt(
        _peppered(password, pepper), salt=salt,
        n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32, maxmem=64 * 1024 * 1024,
... [116 more lines of the executable check]
```

Pinned output of that program:

```text
PASS
```

---

### 10. `py-arch-0002` - software_architecture / python / expert

*tags: transactional-outbox, idempotency, at-least-once, event-driven*

**User turn**

We write an order row and then publish an `OrderPlaced` message to our broker. Twice last month the deploy restarted between the two, so the order existed and the fulfilment service never heard about it. The obvious fix — publish first, then write — loses the event when the transaction rolls back instead. How do teams solve this properly without a distributed transaction?

**Assistant turn**

This is the dual-write problem: two independent systems (the database and the broker) cannot be updated atomically without a distributed transaction, which you do not want. The standard answer is the **transactional outbox**: write the event into a table *in the same transaction* as the business row, then relay it to the broker from a separate process.

That changes the delivery guarantee to **at-least-once**, because a relay can crash after the broker accepted the message but before marking it published. Therefore the consumer must be **idempotent** — it deduplicates by event id inside the same transaction as its side effect. Exactly-once *effects* from at-least-once *delivery* is the achievable goal.

Two consequences people miss:

- **Never publish inside the transaction.** If you hold a database transaction while calling the broker, a slow broker stalls the write path and a broker success followed by a rollback resurrects the lost event. The relay should read pending rows, send, then mark — and it is fine if it sends a duplicate.
- **A poison event must not stall the queue.** Give the relay an attempt counter, dead-letter after N failures, and continue with the rest of the batch. Without that, one malformed payload blocks every later event for that aggregate.

```python
def place_order(conn, order_id, customer_id, total_cents):
    """Business row and event in ONE transaction: the event exists exactly when
    the order does, so a crash can no longer lose one without the other."""
    with conn:
        conn.execute("INSERT INTO orders VALUES (?, ?, ?)", (order_id, customer_id, total_cents))
        next_seq = conn.execute(
            "SELECT COALESCE(MAX(seq), 0) + 1 FROM outbox WHERE aggregate_id = ?", (customer_id,)
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO outbox (aggregate_id, seq, event_type, payload) VALUES (?, ?, ?, ?)",
            (customer_id, next_seq, "OrderPlaced", json.dumps({"orderId": order_id})),
        )


def consume(event, conn, consumer="read_model_projection"):
    """Idempotent consumer: the dedupe row and the side effect are one unit."""
    with conn:
        try:
            conn.execute("INSERT INTO processed_events VALUES (?, ?, ?)",
                         (event["id"], consumer, now()))
        except sqlite3.IntegrityError:
            return False            # already applied: a redelivery, not a new fact
        apply_projection(conn, event["payload"])
        return True
```

Operational notes that belong with this pattern: publish in aggregate order (`seq` per aggregate) when consumers care about order, keep a retention job that trims published outbox rows, and monitor the **age of the oldest unpublished row** — that lag is the health signal of the relay, and a stalled outbox is invisible in business metrics until fulfilment starts missing orders.

**Verification** - `kind=executable language=python`

```python
import json
import sqlite3
import tempfile

SCHEMA = """
CREATE TABLE orders (
    id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL,
    total_cents INTEGER NOT NULL CHECK (total_cents > 0)
);
CREATE TABLE outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    aggregate_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    payload TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    published_at TEXT,
    UNIQUE (aggregate_id, seq)
);
CREATE TABLE processed_events (
    event_id INTEGER PRIMARY KEY,
... [250 more lines of the executable check]
```

Pinned output of that program:

```text
PASS
```

---

## Dataset 2 - 48 examples, 12 categories (showing 10)

### 1. `dbg-r-0001` - debugging_reasoning / python / intermediate

*tags: shallow-copy, mutable-state, aliasing, defaults*

**User turn**

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

**Assistant turn**

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

**Verification** - `kind=executable language=python`

```python
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
... [47 more lines of the executable check]
```

Pinned output of that program:

```text
second call sees: ['email', 'sms']
top-level override leaks: False
nested list is the same object: True
nested dict is the same object: True
deep copy after the leak: ['email', 'sms']
module default is now: ['email', 'sms']
safe factory, second call: ['email']
PASS
```

---

### 2. `trc-0004` - execution_tracing / javascript / advanced

*tags: microtasks, event-loop, async-ordering, tracing*

**User turn**

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

**Assistant turn**

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

**Verification** - `kind=executable language=javascript`

```javascript
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
... [65 more lines of the executable check]
```

Pinned output of that program:

```text
interleaved order: ["start 1","validated 1","done 1","saved 1"]
synchronous save: ["start sync 1","saved sync 1","validated sync 1"]
joined order: ["start joined 1","validated joined 1","saved joined 1","done joined 1"]
queue priority: ["sync","micro","macro"]
PASS
```

---

### 3. `dep-0001` - dependency_reasoning / python / advanced

*tags: circular-imports, entry-points, partial-init, tracing*

**User turn**

This package works when the worker imports it, and crashes when the CLI imports it — same code, same environment, different first import:

```
pkg/models.py   from pkg.store import Store
                class User: ...
                def load(store: Store): ...

pkg/store.py    import pkg.models as models
                class Store:
                    def default_user(self): return models.User("anon")
```

`ImportError: cannot import name 'Store' from partially initialized module 'pkg.store' (most likely due to a circular import)` happens with `python -c "import pkg.store"`, while `python -c "import pkg.models"` succeeds. Why does the *entry module* decide this, and what is the correct fix rather than moving the import inside the function?

**Assistant turn**

Both modules are in a cycle; you only see it from one side because of *when* each name becomes available during import.

Python imports a module by creating the module object, putting it in `sys.modules`, then executing its body top to bottom. A cycle is survivable exactly when the second module only needs something that already exists at that moment:

- `import pkg.models` first: `models` starts executing → `from pkg.store import Store` runs `store` → `store` executes `import pkg.models as models`. That binds the **module object**, which already exists (partially initialised is enough), and `store` never touches `models.User` at import time — only inside `default_user`. So `store` finishes, `Store` exists, and `models` gets its name. Order works.
- `import pkg.store` first: `store` starts executing → `import pkg.models as models` runs `models` → `models` executes `from pkg.store import Store`, but `store`'s body has not reached `class Store` yet, so the attribute is missing → `ImportError`.

So the rule is: **a cycle is only "safe" because of which names are looked up before the cycle closes — and that depends on which module the process imports first.** That is why it survives test suites (which import the entry point) and breaks when a different entry point, a plugin loader, or `python -m pkg.store` starts elsewhere. `from x import name` needs the attribute immediately; `import x` plus attribute access at call time needs nothing.

The durable fix is to break the cycle, not to hide it: make the dependency point one way, with the storage layer depending on the domain.

```python
# pkg/models.py -- imports nothing from the storage layer
class User:
    def __init__(self, name): self.name = name

def load(repository, name):                 # any object with .get() will do
    return repository.get(name)


# pkg/store.py -- depends on the domain, which is the only order that holds
import pkg.models as models

class Store:
    def default_user(self): return models.User("anon")

    def get(self, name): return self.default_user()


# pkg/__init__.py -- optional convenience wiring, still one direction
from pkg.models import User
from pkg.store import Store
```

If you cannot break the cycle yet, the least-bad interim is a *function-local* import (`def load(store): from pkg.store import Store`) — it defers the lookup past module execution, but it does not remove the cycle, so the modules still cannot be imported, tested or deployed independently. Detect that case in CI with an import-graph check that walks into function bodies; a cycle that only the interpreter tolerates is still a cycle.

**Verification** - `kind=executable language=python`

```python
import re
import subprocess
import sys
import tempfile
from pathlib import Path

CYCLIC = {
    "pkg/__init__.py": "",
    "pkg/models.py": (
        "from pkg.store import Store\n\n\n"
        "class User:\n"
        "    def __init__(self, name):\n"
        "        self.name = name\n\n\n"
        "def load(store: Store):\n"
        "    return store.default_user()\n"
    ),
    "pkg/store.py": (
        "import pkg.models as models\n\n\n"
        "class Store:\n"
        "    def default_user(self):\n"
        '        return models.User("anon")\n'
    ),
... [97 more lines of the executable check]
```

Pinned output of that program:

```text
import pkg.models -> 0 ok models first
import pkg.store  -> 1 ImportError: cannot import name 'Store' from partially initialized module 'pkg.store' (most likely due to a circular import) (<pkg>/pkg/store.py)
partial-init evidence captured: True
models imports: ['pkg.store']
store imports: ['pkg.models']
fixed, models first -> 0 ok models first
fixed, store first  -> 0 ok store first anon
PASS
```

---

### 4. `algo-0002` - algorithmic_reasoning / python / advanced

*tags: shortest-path, negative-weights, preconditions, invariants*

**User turn**

We use Dijkstra for routing and added one edge with a negative cost (a discount leg between two hops). The sample graph in our tests still passes and most routes look right, but some destinations come out too expensive. A teammate says "negative weights are fine if there is no negative cycle". Here is the relaxation loop:

```python
def dijkstra(graph, source):
    dist = {node: inf for node in graph}
    dist[source] = 0
    heap = [(0, source)]
    settled = set()
    while heap:
        d, node = heappop(heap)
        if node in settled:          # lazy deletion: skip stale entries
            continue
        settled.add(node)
        for neighbour, weight in graph[node]:
            if dist[node] + weight < dist[neighbour]:
                dist[neighbour] = dist[node] + weight
                heappush(heap, (dist[neighbour], neighbour))
    return dist
```

Is the teammate right? Give a graph with no negative cycle where this returns a wrong answer, and state the precondition that is actually doing the work.

**Assistant turn**

The teammate is wrong, and the precise way this implementation breaks is more interesting than "the wrong node gets popped": a settled node's **outgoing edges are relaxed once and never again**, so its descendants inherit a distance computed from a value that is later corrected.

Counterexample, acyclic (so there is no negative cycle to blame):

```
S -> A weight 2
S -> B weight 3
B -> A weight -2
A -> C weight 5
```

Dijkstra pops `S(0)`, relaxes `A=2` and `B=3`; pops `A(2)`, marks it settled and relaxes `C = 2 + 5 = 7`; pops `B(3)` and relaxes `A` to `3 - 2 = 1`. `A` is already settled, so the heap entry is discarded by the lazy-deletion guard and — this is the part that bites — **`A`'s own outgoing edges are never relaxed again**. The returned distances are `A = 1` (patched after settling, so `A` itself looks right) and `C = 7`, while the true shortest path is `S → B → A → C = 6`.

So the symptom is not "the answer for the discounted node is wrong"; it is "edges leaving a node whose distance improved late keep the stale value", which is why only *some* destinations are too expensive. A useful invariant to check the output against: in a correct shortest-path result, no edge may still be improvable (`dist[u] + w >= dist[v]` for every edge), and no setted node may be re-improved. Run the check and this result fails on `A -> C`.

The precondition that makes Dijkstra correct is **all edge weights non-negative**, not "no negative cycle". Non-negativity is what lets the heap pop be final: every future path to a node is at least as long as the popped distance, so no later relaxation can improve it, and relaxing each node once is enough. With any negative edge you must either re-relax (SPFA/Bellman-Ford) or pre-process the graph so the weights become non-negative:

```python
def bellman_ford(graph, source):
    """Correct with negative edges; raises when a negative cycle is reachable."""
    dist = {node: float("inf") for node in graph}
    dist[source] = 0
    edges = [(u, v, w) for u, neighbours in graph.items() for v, w in neighbours]
    for _ in range(len(graph) - 1):
        changed = False
        for u, v, w in edges:
            if dist[u] + w < dist[v]:
                dist[v] = dist[u] + w
                changed = True
        if not changed:                      # converged early
            break
    for u, v, w in edges:                    # one more pass: an improvement is a cycle
        if dist[u] + w < dist[v]:
            raise ValueError("negative cycle reachable from the source")
    return dist
```

Practical guidance: if the "negative" edge came from a discount, model it as a non-negative surcharge on the following leg (weight distribution), or run Bellman-Ford/Jhonson-style re-weighting. And always keep a validation step in routing code: check the shortest-path invariant on the returned distances, because the failure mode here is a plausible-looking tree with a few inflated costs, not an exception.

**Verification** - `kind=executable language=python`

```python
from heapq import heappop, heappush

GRAPH = {
    "S": [("A", 2), ("B", 3)],
    "A": [("C", 5)],
    "B": [("A", -2)],
    "C": [],
}


def dijkstra(graph, source):
    dist = {node: float("inf") for node in graph}
    dist[source] = 0
    heap = [(0, source)]
    settled = set()
    pops = []
    while heap:
        d, node = heappop(heap)
        if node in settled:
            continue
        settled.add(node)
        pops.append((node, d))
... [97 more lines of the executable check]
```

Pinned output of that program:

```text
dijkstra distances: {'S': 0, 'A': 1, 'B': 3, 'C': 7}
settled order: [('S', 0), ('A', 2), ('B', 3), ('C', 7)]
true distances: {'S': 0, 'A': 1, 'B': 3, 'C': 6}
A settled at: [2] | final dist[A]: 1
edges still improvable in the dijkstra result: [('A', 'C', 5, 6, 7)]
without settling: {'S': 0, 'A': 1, 'B': 3, 'C': 6}
bellman-ford: {'S': 0, 'A': 1, 'B': 3, 'C': 6}
non-negative graph: {'S': 0, 'A': 2, 'B': 3, 'C': 7}
improvable edges there: []
negative cycle detected: negative cycle reachable from the source
PASS
```

---

### 5. `cplx-0002` - complexity_analysis / javascript / advanced

*tags: sorting, comparators, schwartzian-transform, measurement*

**User turn**

Sorting our catalogue takes 40 seconds. The comparator does a little work (it normalises a name and falls back to a locale rule), and the code sorts once per request:

```javascript
const byDisplayName = (a, b) =>
  normalise(a.name).localeCompare(normalise(b.name), "en", { sensitivity: "base" });

catalogue.sort(byDisplayName);
```

Someone suggested "cache `normalise` results in a Map" as the fix. Is the comparator being called once per element, or more? Tell me how to measure it and what the right fix is.

**Assistant turn**

A comparison sort calls the comparator **O(n log n) times**, not n times: each comparison needs two keys, so the expensive work inside the comparator is paid twice per comparison — roughly `2 · n log₂ n` normalisation calls, ~20 000 of them for n = 1000. Caching normalisation in a `Map` reduces the cost per call but keeps the O(n log n) call count, so it is a constant-factor improvement at best.

The fix that changes the number of calls is the **decorate–sort–undecorate** ("Schwartzian transform") pattern: compute each key once (n calls), sort the pairs by the precomputed key, then unwrap. In JavaScript that is `map` → `sort` → `map`, and the comparator then compares two already-computed strings:

```javascript
const decorated = catalogue.map((item) => ({
  item,
  key: normalise(item.name),
}));

decorated.sort((a, b) => a.key.localeCompare(b.key, "en", { sensitivity: "base" }));

const sorted = decorated.map((entry) => entry.item);
```

Why this is usually the right fix in JavaScript:

- The expensive part (normalisation, `localeCompare` construction, regex work) runs **n times instead of ~2n log n**.
- `localeCompare` on pre-normalised keys is still a comparison, but V8 can avoid rebuilding collators per call; the remaining work is the comparison itself, which is inherent to comparison sorting.
- The comparator must remain a **pure, consistent total order**. A comparator that returns different results for the same pair on different calls makes the algorithm's behaviour implementation-defined; a precomputed key makes equality and ordering stable, which is also the intended semantic (sort by the normalised name, not by the raw one).

Measure it before changing anything: wrap the comparator to count invocations and count calls to `normalise`. The counts are deterministic for a given input and V8 build — no timing needed:

```javascript
let comparatorCalls = 0;
catalogue.sort((a, b) => { comparatorCalls += 1; return byDisplayName(a, b); });
// comparatorCalls ≈ 2n log n; the decorate version: n key computations and no
// normalise() inside the comparator at all.
```

Two caveats: if the sort runs once on a small array (< 100 elements) the constant-factor version is fine and simpler — measure first; and if the ordering rule is *not* a total order (this comparator is: normalised name, ties broken arbitrarily), a decorate pass can expose instability across equal keys, so include a tie-breaker in the key when the order must be deterministic.

**Verification** - `kind=executable language=javascript`

```javascript
// Deterministic catalogue: 1000 items, names with mixed case and accents.
let seed = 987654321;
const nextRandom = () => {
  seed = (seed * 1103515245 + 12345) % 2147483648;
  return seed;
};

const WORDS = ["zebra", "Ápple", "banana", "Cherry", "apple", "élan", "delta"];
const catalogue = Array.from({ length: 1000 }, (_, index) => ({
  id: index,
  name: `${WORDS[nextRandom() % WORDS.length]}-${nextRandom() % 1000}`,
}));

const normaliseCalls = { count: 0 };
const normalise = (name) => {
  normaliseCalls.count += 1;
  return name.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
};

const byDisplayName = (a, b) =>
  normalise(a.name).localeCompare(normalise(b.name), "en", { sensitivity: "base" });

... [54 more lines of the executable check]
```

Pinned output of that program:

```text
n = 1000 | n*log2(n) = 9966
plain sort: comparator calls = 8632 | normalise calls = 17264
decorate: keys computed = 1000 | key comparator calls = 8632
expensive calls: plain = 17264 | decorate = 1000 | ratio = 17.3
same order: true
plain sorted: true | decorate sorted: true
PASS
```

---

### 6. `conc-0003` - concurrency / python / advanced

*tags: deadlock, lock-ordering, rlock, timeouts*

**User turn**

Our transfer service locks two account objects and occasionally stops serving requests entirely — a thread dump shows every worker waiting on a mutex. It happens more when one particular pair of accounts is involved:

```python
def transfer(from_account, to_account, amount):
    with from_account.lock:
        with to_account.lock:
            from_account.balance -= amount
            to_account.balance += amount
```

Why does it hang, and how should it be written so it cannot hang? I would also like a test that proves the deadlock exists instead of waiting for it to happen in production.

**Assistant turn**

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

**Verification** - `kind=executable language=python`

```python
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
... [116 more lines of the executable check]
```

Pinned output of that program:

```text
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
```

---

### 7. `mem-0003` - memory_behavior / python / advanced

*tags: reference-cycles, garbage-collection, finalizers, leaks*

**User turn**

Two things confuse me about Python memory:

1. A tree built with parent pointers (`node.parent = parent`, `parent.children.append(node)`) is deleted by setting the root to `None`, but our memory usage does not drop.
2. Some of our objects are only released after an explicit `gc.collect()`, and one class with a `__del__` seems to be released by the collector in newer Python but not in an old 2.7-era service we still run.

Does refcounting not free cycles? What should I actually rely on?

**Assistant turn**

Reference counting frees an object when its count hits zero; **a cycle never hits zero**, because every member keeps the others' counts positive. That is exactly your tree: `root → child` and `child → parent`, so dropping the external reference leaves the cycle intact. When the object also has a finalizer (`__del__`, or a `weakref` callback in some cases), the language has to decide whether it can safely run the finalizer — historically (Python 2 and early 3.x) a cycle containing a `__del__` was declared uncollectable, which is the "old service" behaviour you are remembering.

In modern CPython (3.4+) the cycle detector handles finalizers: the collector finds unreachable cycles, runs finalizers in a defined order, and re-checks. So the practical rules are:

- **Refcounting plus the generational GC** is the model: refcounts handle the acyclic majority immediately and deterministically; the GC handles cycles. Rely on *both*, and do not assume memory drops at the exact statement where you drop a reference.
- **Cycles are not automatically leaks.** They are only leaks if something still reaches them from a root (a module global, a registry, a live exception's traceback, a generator frame). `gc.collect()` freeing your objects proves they were unreachable; if memory does not drop, something *is* still reachable — the search is for the root, not for the collector.
- **Finalizers are for correctness, not cleanup.** Use `weakref.finalize` or `contextlib.ExitStack` for resource release; `__del__` is unreliable in ordering and can resurrect objects, and its exceptions are swallowed (printed to stderr at best).
- **You can break cycles structurally**: a parent pointer that does not keep the parent alive (`weakref.ref`), `__slots__` plus explicit `close()`, or clearing children on detach (`node.parent = None; node.children.clear()`).

The structural fix that makes the lifetime deterministic:

```python
import weakref


class Node:
    """A tree node whose parent link does not keep the parent alive."""

    __slots__ = ("name", "parent", "children")

    def __init__(self, name, parent=None):
        self.name = name
        self.parent = weakref.ref(parent) if parent is not None else (lambda: None)
        self.children = []
        if parent is not None:
            parent.children.append(self)

    def detach(self):
        if self.parent is not None:
            self.parent.children.remove(self)
        self.parent = None
```

With the parent link weak, dropping the last external reference to the root drops the whole
tree by refcounting alone - no cycle, no collector, no delay. The trade-off is that the
parent can disappear while the child is alive, so `self.parent()` must be checked for
`None` (and the child must not assume the parent still exists).

One important operational detail: the generations matter for *when* (gen-0 collection is frequent, gen-2 rare), not for *whether* — and objects that define `__del__` used to be the classic "uncollectable" line in `gc.garbage`, which modern CPython no longer produces for ordinary cases. On CPython, weakref and `gc.get_objects()` counting give you a deterministic test: build the cycle, drop it, assert the object is unreachable-but-alive (refcounting alone cannot free it), then `gc.collect()` and assert it is gone. My verification also pins the structural fix — a weak parent pointer — where refcounting alone frees the whole tree with no collector involvement, which is the difference between "eventually" and "at the moment you detach".

**Verification** - `kind=executable language=python`

```python
import gc
import weakref


class Node:
    """Tree node with a strong parent link: cycles by construction."""

    def __init__(self, name):
        self.name = name
        self.parent = None
        self.children = []

    def add(self, child):
        child.parent = self                       # strong reference back up
        self.children.append(child)
        return child


class WeakNode:
    """Same tree, but the parent link does not keep the parent alive."""

    def __init__(self, name):
... [93 more lines of the executable check]
```

Pinned output of that program:

```text
cycle alive immediately after dropping all references: True
reachable after gc.collect(): False
collector did work: True
still reachable through a registry after gc: True
that is a leak, not a collector limitation: True
released once the root is gone: True
acyclic-by-weakref tree freed without gc: True
finalizer cycle alive before gc: True
finalizer cycle collected by modern gc: True
gc.garbage empty (no uncollectable objects): True
live-tracking via gc.get_objects: 0 25 0
count returns to the baseline: True
PASS
```

---

### 8. `stm-0004` - state_management / javascript / advanced

*tags: derived-state, single-source-of-truth, invariants, drift*

**User turn**

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

**Assistant turn**

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

**Verification** - `kind=executable language=javascript`

```javascript
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
... [146 more lines of the executable check]
```

Pinned output of that program:

```text
stored after adds: subtotal 45 | itemCount 3
stored after setQuantity: subtotal 75 | itemCount 3 (should be 6)
stored fields vs truth: 75 3 vs { subtotal: 75, itemCount: 6 }
derived after the same sequence: subtotal 75 | itemCount 6
stored after discount: subtotal 75 | discount SAVE10
derived after discount: subtotal 75 | total 67.5
stored store: steps with a broken invariant: 339 of 395 operations
derived store: steps with a broken invariant: 0
PASS
```

---

### 9. `api-0001` - api_behavior / python / advanced

*tags: http, idempotency, retries, post*

**User turn**

Our checkout service creates an order with `POST /orders`. The mobile client retries on a timeout and now customers are occasionally charged twice, because the first request did create the order — the response just never arrived:

```python
def create_order(payload):
    for attempt in range(3):
        try:
            return http_post("/orders", payload)          # 201 with the new order
        except Timeout:
            continue
    raise
```

The API is a plain `POST /orders` that inserts a row. What is the correct server-side fix, and how do we test it?

**Assistant turn**

A retry after a lost response is indistinguishable from a genuine second purchase *unless the client identifies the operation*. The transport can fail after the server has committed, and at-least-once delivery is all any client can offer, so the guarantee has to be built at the API level with an **idempotency key**:

- The client generates a UUID **once per logical operation** (not per attempt) and sends it in a header: `Idempotency-Key: 8f0d...`.
- The server, on receiving the request, records `(key → response)` and returns that same response for every repeat of that key — same status, same body, no second row.
- The key must be stored **atomically with the write** (same transaction, or a unique index on the key) so two concurrent retries cannot both insert.

```python
def create_order(request):
    key = request.headers.get("Idempotency-Key")
    if key is None:
        return Response(400, {"error": "Idempotency-Key header is required"})

    with db.transaction():
        existing = orders.find_by_key(key)              # row locked by the unique index
        if existing is not None:
            if existing.request_fingerprint != fingerprint(request.body):
                # the same key with a different payload is a client bug, not a retry
                return Response(409, {"error": "key reused with a different payload"})
            return Response(existing.status, existing.body)      # replay, no new write
        order = insert_order(request.body, key=key)              # one insert, one key
    return Response(201, order)
```

Details that decide whether this actually holds:

- **Store the response, not just a flag.** A replay must return the original status and body (including the order id); a flag alone cannot reconstruct them.
- **Reject key reuse with a different payload (409).** Otherwise a buggy client that reuses one key for two different carts silently loses the second order.
- **Expire keys explicitly** (24 h is typical) — an unbounded table of request/response bodies is its own outage, and the retention window must exceed your retry window.
- **Require the key on unsafe methods only.** `GET`, `PUT`, `DELETE` and `PATCH` are already idempotent by HTTP semantics if implemented properly; `POST` is the one that needs help (and `PUT`/`DELETE` still need to be genuinely idempotent on the server).
- **Do not just retry server-side or deduplicate on payload equality**: two legitimate identical orders exist in the real world, and payload hashing cannot tell them apart.

The test is the part teams skip: you cannot force a real network failure from inside the client, so a deterministic test **drops the response on the first attempt while still committing the write** — exactly what a lost response looks like to the client — and then asserts how many orders exist afterwards. That is the check below: the naive client ends up with two orders and the idempotent client with one.

**Verification** - `kind=executable language=python`

```python
import http.client
import json
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ORDER = {"sku": "hat-42", "quantity": 2}


class OrderStore:
    def __init__(self):
        self.orders = []
        self.by_key = {}

    def create(self, payload, key):
        if key is not None and key in self.by_key:
            order, fingerprint = self.by_key[key]
            if fingerprint != json.dumps(payload, sort_keys=True):
                raise KeyReuse("the same key was sent with a different payload")
            return order, True                       # replayed response, no new row
        order = {"id": len(self.orders) + 1, "sku": payload["sku"],
... [145 more lines of the executable check]
```

Pinned output of that program:

```text
naive client: attempts 2 | final status 201 | order id 2
orders created by the server: 2 | ids: [1, 2]
idempotent client: attempts 2 | final status 200 | order id 1 | replayed: True
orders created by the server: 1 | ids: [1]
third attempt with the same key: 200 | replayed: True | orders: 1
same key, different payload: 409 | error: the same key was sent with a different payload | orders: 1
no idempotency key: 400 | error: Idempotency-Key header is required
PASS
```

---

### 10. `arch-0004` - architecture_reasoning / python / expert

*tags: strangler, migration, shadow-traffic, canary, rollback*

**User turn**

We are replacing the legacy pricing engine with a rewrite. The plan is: run both, compare the results, then flip a feature flag. Today it is "call legacy, and call the new service in a background job with a sample of traffic", and we have no idea whether the sample covers the cases that matter. How should this migration be structured, and how do we decide the flip is safe?

**Assistant turn**

Sampling hides exactly the inputs that break. A sampled comparison tells you the new engine agrees on the *common* cases — which you already believed — and it cannot tell you about the boundary the rewrite got wrong (the check below finds it: the new engine treats a bulk discount as `quantity > 100` where legacy applies it at `quantity >= 100`, so the divergence lives on one exact input). The structure that makes the flip a decision instead of a gamble:

**1. Shadow everything that can be shadowed, and compare deterministically.** For a pricing engine — a pure function of its inputs — you can run both implementations on *every* request, return the legacy answer, and record divergences. No sampling, no user-visible risk:

```python
def price(self, account_id, amount_cents, quantity):
    legacy_result = self.legacy(amount_cents, quantity)      # the response the user gets
    if self.mode in ("shadow", "canary") and self.shadow_enabled:
        try:
            candidate = self.new_engine(amount_cents, quantity)
        except Exception as exc:
            self.record_error(account_id, amount_cents, quantity, exc)
        else:
            if candidate != legacy_result:
                self.record_divergence(account_id, amount_cents, quantity,
                                       legacy_result, candidate)
    ...
    return legacy_result
```

**2. Drive the comparison from your real traffic *and* from a boundary matrix.** Real traffic proves the engine handles what customers actually do; the matrix (quantities at and around thresholds, zero, one, huge, odd amounts, each currency) proves it handles what nobody happened to do today. A rewrite is almost always wrong at a boundary, and boundaries are precisely what traffic does not sample evenly.

**3. Route by a stable key when you cut over, never by random-per-request.** Hash the account (or the order id): the same account must always hit the same engine, otherwise one user sees prices flicker between engines between two pages of the same order — a support nightmare and an accounting one:

```python
def _in_canary(self, account_id):
    digest = hashlib.sha256(account_id.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % 10_000 < self.share * 10_000
```

**4. Decide the flip from the divergence rate, not from "it looks fine".** The gate should be explicit: zero unexplained divergences over a full business cycle (including month-end, promotions, and each currency), error rate on the new path no worse than legacy, and the canary share within its configured band (sticky routing gives you a real cohort, not noise).

**5. Bolt on the fallback and the kill switch before the canary.** A new-path exception must fall back to legacy and be recorded, not surfaced as a 500, and rollback must be a configuration change that takes effect on the next request:

```python
try:
    return self.new_engine(amount_cents, quantity)
except Exception:
    self.fallbacks += 1
    return self.legacy(amount_cents, quantity)       # the user still gets a price
```

**6. Mind what shadow traffic costs and what it touches.** Running both engines doubles compute and every downstream call the new engine makes — so shadow reads, never shadow writes, and never let the shadow path charge a card twice. If the new path writes, write to a shadow table or a dry-run mode, and treat "shadow write" as a separate, explicitly reviewed decision.

Finally, plan the exit: the legacy path stays deployable (and tested) until the new engine has served 100% through a full cycle, and the divergence log is the evidence you keep. A migration is finished when you delete the old path and its flag — not when the flag has been at 100% for a month.

**Verification** - `kind=executable language=python`

```python
import hashlib

LEGACY = "legacy"
NEW = "new"


def legacy_price(amount_cents, quantity):
    """Legacy: a 5% bulk discount, applied at 100 units and above."""
    total = amount_cents * quantity
    if quantity >= 100:
        total = total * 95 // 100
    return total


def new_price(amount_cents, quantity):
    """The rewrite: the boundary is off by one, and it rejects bad input."""
    if quantity <= 0:
        raise ValueError("quantity must be positive")
    total = amount_cents * quantity
    if quantity > 100:                                   # legacy uses >= 100
        total = total * 95 // 100
    return total
... [146 more lines of the executable check]
```

Pinned output of that program:

```text
shadow over 200 real-shaped requests: divergences 0
shadow over the 24-case boundary matrix: divergences 4
the divergence the traffic could not see: [(99, 100, 9405, 9900)]
every response still came from legacy: {'legacy': 224, 'new': 0}
canary at 20%: new path served 22.6% of 500 accounts | served counts {'legacy': 387, 'new': 113}
sticky per account: same account always routes the same way: True
new engine raises, canary falls back: 0 | fallbacks: 1 | errors recorded: 1
rollback: served before {'legacy': 387, 'new': 113} -> after {'legacy': 887, 'new': 113} | new responses added: 0
after fixing the boundary, shadow divergences: 0 | errors: 0 -> safe to flip
PASS
```

---
