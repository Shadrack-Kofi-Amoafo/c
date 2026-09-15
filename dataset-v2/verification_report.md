# Verification report

- examples checked: **48**
- passed: **48**
- failed: **0**
- skipped (toolchain missing): **0**

`executable` = the program under test really ran and its stdout matched the
documented output. `parity` = the algorithm was executed via the Python
reference implementation in `@code` against the same test vectors; the
snippet's syntax was reviewed manually (see the `PARITY:` line in the notes).
`reviewed` = design/vendor-specific artifact with a written checklist.

| example | kind | lang | status | time | evidence |
| --- | --- | --- | --- | --- | --- |
| `algo-0001` | executable | python | PASS | 0.02s | python3: output matched |
| `algo-0002` | executable | python | PASS | 0.01s | python3: output matched |
| `algo-0003` | executable | javascript | PASS | 0.03s | node: output matched |
| `algo-0004` | executable | python | PASS | 0.01s | python3: output matched |
| `api-0001` | executable | python | PASS | 1.06s | python3: output matched |
| `api-0002` | executable | javascript | PASS | 0.04s | node: output matched |
| `api-0003` | executable | python | PASS | 0.01s | python3: output matched |
| `api-0004` | executable | javascript | PASS | 0.03s | node: output matched |
| `arch-0001` | executable | python | PASS | 0.04s | python3: output matched |
| `arch-0002` | executable | python | PASS | 0.03s | python3: output matched |
| `arch-0003` | executable | python | PASS | 0.02s | python3: output matched |
| `arch-0004` | executable | python | PASS | 0.01s | python3: output matched |
| `cplx-0001` | executable | python | PASS | 0.26s | python3: output matched |
| `cplx-0002` | executable | javascript | PASS | 0.12s | node: output matched |
| `cplx-0003` | executable | python | PASS | 1.99s | python3: output matched |
| `cplx-0004` | executable | python | PASS | 0.10s | python3: output matched |
| `conc-0001` | executable | python | PASS | 0.03s | python3: output matched |
| `conc-0002` | executable | python | PASS | 0.56s | python3: output matched |
| `conc-0003` | executable | python | PASS | 0.08s | python3: output matched |
| `conc-0004` | executable | python | PASS | 0.04s | python3: output matched |
| `dbg-r-0001` | executable | python | PASS | 0.01s | python3: output matched |
| `dbg-r-0002` | executable | python | PASS | 0.01s | python3: output matched |
| `dbg-r-0003` | executable | javascript | PASS | 0.03s | node: output matched |
| `dbg-r-0004` | executable | python | PASS | 0.01s | python3: output matched |
| `dep-0001` | executable | python | PASS | 0.08s | python3: output matched |
| `dep-0002` | executable | python | PASS | 0.06s | python3: output matched |
| `dep-0003` | executable | python | PASS | 0.06s | python3: output matched |
| `dep-0004` | executable | python | PASS | 0.02s | python3: output matched |
| `edge-0001` | executable | javascript | PASS | 0.03s | node: output matched |
| `edge-0002` | executable | python | PASS | 0.01s | python3: output matched |
| `edge-0003` | executable | javascript | PASS | 0.03s | node: output matched |
| `edge-0004` | executable | python | PASS | 0.02s | python3: output matched |
| `trc-0001` | executable | python | PASS | 0.01s | python3: output matched |
| `trc-0002` | executable | python | PASS | 0.01s | python3: output matched |
| `trc-0003` | executable | python | PASS | 0.02s | python3: output matched |
| `trc-0004` | executable | javascript | PASS | 0.08s | node: output matched |
| `mem-0001` | executable | python | PASS | 0.02s | python3: output matched |
| `mem-0002` | executable | python | PASS | 0.01s | python3: output matched |
| `mem-0003` | executable | python | PASS | 0.01s | python3: output matched |
| `mem-0004` | executable | python | PASS | 0.02s | python3: output matched |
| `sec-0001` | executable | python | PASS | 0.02s | python3: output matched |
| `sec-0002` | executable | python | PASS | 0.45s | python3: output matched |
| `sec-0003` | executable | python | PASS | 0.02s | python3: output matched |
| `sec-0004` | executable | python | PASS | 0.03s | python3: output matched |
| `stm-0001` | executable | javascript | PASS | 0.03s | node: output matched |
| `stm-0002` | executable | javascript | PASS | 0.17s | node: output matched |
| `stm-0003` | executable | python | PASS | 0.02s | python3: output matched |
| `stm-0004` | executable | javascript | PASS | 0.03s | node: output matched |

## Notes captured during review

### algo-0001

The hang is made deterministic by a step budget and pinned with the stuck state
(`lo=1 hi=2 mid=1 -> new lo=1`), plus a target-by-target table showing exactly which
inputs terminate: targets at or below the first element resolve through `hi = mid` and
return the right index, while anything above the first element can leave `lo`
unchanged and spin — including `target = 20`, an element that *is* present. That is
why a suite of "first element" cases passed. The fixed version is verified against
`bisect.bisect_left` on every sorted array of size 0-4 over values 0-5 crossed with
targets -1..6 (12 440 cases) and on a 500-element array, and the buggy version is
shown to disagree on 1 253 of the same small cases.

### algo-0002

Executes the acyclic counterexample and pins the real mechanism: `A` is settled at 2,
its edge `A -> C` is relaxed to 7, and only afterwards does `B` improve `A` to 1 — the
already-settled guard discards the new heap entry, so `A`'s outgoing edges are never
relaxed again and `C` stays at 7 instead of 6. The shortest-path invariant check
(`dist[u] + w < dist[v]` for any edge) reports exactly `("A", "C", 5, 6, 7)`, which is
the assertion that makes the bug mechanical rather than anecdotal. Relaxation without
freezing (SPFA) and Bellman-Ford agree with the truth on the same graph, the
non-negative variant restores Dijkstra with no improvable edges, and a genuine
negative cycle is shown to be a separate failure that Bellman-Ford's extra pass
detects.

### algo-0003

Pins the failure mode with the caller's own view of the data: for `[3, 2, 4]` with
target 6 the helper returns sorted-array indices whose values sum to 7, so the
returned pair does not satisfy the target, while the already-sorted example returns a
valid pair — that is why the issue's examples passed. A deterministic 400-trial oracle
(brute force reference over random arrays with duplicates, negatives and no-solution
cases) reports zero failures for the hash-map version and a nonzero count for the
sorted-index version, and both fixes (hash map, index carried through the sort) are
asserted to satisfy `nums[i] + nums[j] === target` with distinct indices, including
the `[3, 3]` duplicate case.

### algo-0004

Pins the eviction-order evidence: after `put(a), put(b), get(a), put(c)` the buggy cache
holds `["b", "c"]` and the hot key `a` is gone, while the fixed cache holds `["c", "a"]`.
The same demonstration is repeated for an update (`put(a, 10)`) so "an update is a use"
is covered, and a deterministic 600-operation access pattern with a skewed key
distribution shows the fixed cache earning more hits on identical inputs. Both
versions respect the capacity, which is why the original tests passed, and the
`None`-ambiguity (cached `None` reads the same as a miss) is pinned as a contract
concern rather than a behaviour difference.

### api-0001

Runs a real HTTP server on a loopback port and reproduces the failure that causes double
charges: the first `POST /orders` commits the insert and then loses the response (the
handler closes the connection without writing one, exactly what a dropped response looks
like to the client). The naive client retries and the server ends up with two orders,
ids `[1, 2]`; the idempotent client retries with the same key and ends with one order,
a replayed `200` carrying order id 1 and `replayed: true`. The remaining assertions pin
the parts of the contract teams usually forget: a later third attempt is still a replay
(no new row), reuse of the key with a different payload is a `409` rather than a silent
second order, and a request with no key at all is a `400` rather than a guess.

### api-0002

Runs the same store through both pagination schemes with the interruptions that break
offset paging in production. Part 1 inserts a post between page 1 and page 2 and pins the
two rows that get served twice; part 2 deletes a row from page 1 and pins the row that the
walk skips entirely even though it still exists - the offset page returns the three rows
*after* it, which the assertion states explicitly. Part 3 repeats the insert under a keyset
cursor and shows a six-row walk with no repeats and the new row correctly absent midway,
part 4 walks twelve rows in pages of five and proves the concatenation equals the
ordering exactly, and part 5 sets two rows to the same timestamp with the page boundary
between them, showing that a cursor on the non-unique column alone skips the tied row and
lands on the next distinct timestamp, while the `(createdAt, id)` tiebreaker returns it.

### api-0003

The bug is reproduced and measured on a virtual clock, so every number is exact and no
`sleep` can make the test flaky: 100 requests spread over one second at a capacity of 10
and a rate of 5/s are all allowed by the buggy limiter (the clamp refills it on every
call) versus 14 by the fixed one, which is exactly capacity + rate x elapsed. The three
behaviours that separate a real token bucket from a plausible one are then asserted
rather than asserted-about: 50 calls at the same instant allow exactly 10 (a stale clock
would refill them, and a rejected request must not earn tokens), two seconds of idle
refill to capacity, an hour of idle refills to capacity and no further, and the same
traffic through both implementations differs by a factor of more than five.

### api-0004

Reproduces both incidents against an in-memory endpoint. Mass assignment: the naive
`Object.assign` patch stores `role: "admin"` and `plan: "enterprise"` from the request
body and deletes the `version` field, while the allow-listed version answers `400
not patchable: role` and leaves the record untouched. Lost update: the first editor gets
`200` with a new `ETag` of `"2"`, the second editor's stale `If-Match` gets `412` with the
current version and the write does not land, and re-reading then retrying succeeds with
`ETag "3"` while the first editor's `displayName` survives. The remaining pins cover the
semantics that make PATCH usable: `null` clears a field while an absent key leaves it
alone, an invalid value is `422` with the offending field and no write, and a request with
no `If-Match` at all is refused instead of silently winning.

### arch-0001

Builds both trees on disk and verifies the claim rather than asserting it: an AST scan
finds the one violating edge in the before tree (`shop/orders/service.py` ->
`shop.db.session`) and none in the after tree, while both versions compute the same total
(2000) for the same database - so the refactor preserved behaviour. The domain module's
import list is printed and asserted to be free of `sqlite3`, `shop.db.session` and
`shop.adapters.sqlite_orders`, and the port is shown to be usable with a five-line fake
that returns 40 without opening a file, which is the observable benefit the refactor is
supposed to buy.

### arch-0002

Measures the coupling instead of asserting that ten methods is "too many": an AST pass
lists the public methods of the class (10 before, 7 + 3 after) and the methods each call
site actually uses (download 3, digest 4, archive 3), so the width per consumer is a
number. The wide interface is then shown to be unsatisfiable by anything smaller: a fake
implements all ten methods before and passes `isinstance` against the protocol, and a
three-method fake fails it - while the same three-method fake satisfies the narrow
per-client port and actually runs the download handler end to end. Behaviour is checked
against the pre-split class as an oracle (the CSV output is byte-identical), which is what
makes a split safe rather than merely different.

### arch-0003

Models the call graph with a virtual clock and counts what the provider actually sees.
Both failing topologies are run over 1 000 user actions: three layers of three retries
produce 27 000 provider calls and a 54.0 s worst case for a single action, while one
retry at the edge (two attempts, each capped at 0.75 s, under a shared 1.5 s deadline)
produces 2 000 calls and exactly the deadline - 13.5x fewer calls and 36x less tail
latency, which is the outage the user is
describing, reproduced as arithmetic. The healthy-provider case is asserted too (one call,
0.2 s, both topologies) so the fix cannot be mistaken for a blanket ban on retries, and
the last section shows the deadline doing its job: two attempts, the second clamped to the
remaining budget, total 1.5 s.

### arch-0004

Runs the migration as a decision procedure. Shadowing 200 real-shaped requests finds zero
divergences - the number that makes teams flip too early - while the 24-case boundary
matrix finds the rewrite's off-by-one at exactly `quantity == 100` across all four price
points, and the assertions pin both the diverging inputs and the fact that every response
still came from legacy. The canary then routes a sticky cohort (20% of 500 accounts,
asserted within 15-25%), the new engine's exception on `quantity = 0` is shown falling
back to legacy with the legacy result and an error record, and rollback is one config
change after which zero additional responses come from the new path. The closing step is
the gate itself: after the boundary is fixed, shadowing the same matrix produces no
divergences and no errors - which is the evidence that justifies the flip.

### cplx-0001

Measures both versions with an instrumented element type and pins the growth
signature rather than a wall-clock number: list membership comparison counts grow
close to 4× per doubling of input (quadratic — ~1.5 million comparisons at n=2000
against 1000 for the set version) while the set version stays at ~2× and performs only a few thousand equality
comparisons (it pays hashes instead — also counted, so the trade-off is visible). Both
versions are asserted to return identical results, which frames this as a performance
defect rather than a logic bug. The assertion pins the ratio band (3.8-4.2) so the
check is a property of the algorithm, not of the machine.

### cplx-0002

Counts calls in both versions on a deterministic 1000-item catalogue and pins the
comparison: the plain comparator runs ~n log n times (each call normalising two names,
so ~2·n log n expensive calls), while decorate–sort–undecorate computes each key
exactly n times and then sorts precomputed keys — the ratio is asserted to exceed 8×.
Both versions are asserted to produce the identical order and to be correctly sorted
under the same key, so the optimisation is shown to be behaviour-preserving; the call
counts are deterministic for a fixed input, so no timing is involved.

### cplx-0003

Counts recursive invocations for increasing depth and pins the exponent: the naive
version's call count multiplies by ~11 per +5 levels (φ⁵ = 11.09) and exceeds two
million calls at depth 30 while touching only 31 distinct arguments — the redundancy
that makes it exponential. The memoised version is asserted to fill 31 cache entries
for the same answer and to grow linearly (101/201/401 misses for depths
100/200/400), and the iterative version agrees with it exactly on depth 100. Both
implementations are asserted to return the Fibonacci values, so the complexity change
is behaviour-preserving.

### cplx-0004

Verifies the amortised claim by counting reallocations and copied slots through
`sys.getsizeof` (deterministic on CPython, no timing): 100 000 appends produce fewer
than 100 reallocations with a total copy cost under 12n — measured ~8n — the steady-state growth factor is ~1.125, and the
copied-slot total roughly doubles when n doubles — the measured evidence for
"O(1) amortised". The same run pins the worst case: the largest single reallocation
copies tens of thousands of slots, which is the p99 spike, and the preallocated
variant is shown to allocate exactly once with no slack. The assertion band on the
growth factor documents which interpreter detail the claim depends on.

### conc-0001

Reproduces the lost update deterministically with a `Barrier` that parks both threads
between the read and the write, so the outcome is 1 instead of 2 on every run — no
timing luck involved, which is exactly why the flaky-production / green-CI split
happens. The bytecode listing is printed to justify the claim (separate `LOAD_ATTR`
and `STORE_ATTR`), the locked hammer is asserted to be exact (8 × 2500 = 20 000), and
the contrast with `list.append` (40 000 appends from 8 threads with no loss) shows why
the GIL folklore exists and where it stops being true. The last section pins the
multi-process case: per-object locks cannot protect a counter that lives in a shared
store.

### conc-0002

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

### conc-0003

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

### conc-0004

Pins the lost update with exact numbers rather than a timing race: two connections
read stock = 100, each computes its own new value, and the second commit overwrites the
first (final 50 instead of 20), which is precisely the oversell. Rewriting the same two
decrements as `SET stock = stock - ?` yields 20, the guarded statement
(`AND stock >= ?`) is asserted to change 1 row then 0 rows and leave stock at 70, and a
`BEGIN IMMEDIATE` transaction that re-reads inside the lock also lands on 70. The
connection's `busy_timeout` is pinned as the setting that turns contention into waiting
rather than an immediate "database is locked" failure.

### dbg-r-0001

Reproduces the request-to-request leak and pins the reason it was invisible: a
top-level override does not leak (slot rebinding) while the nested list and dict
are the *same objects* (`is`, not merely equal), so any caller that mutates them
writes into the module-level default. The deep-copy version is shown to isolate a
mutation, and the module default is asserted clean. The isolation assertion is the
test that would have caught it — asserting contents of a single instance cannot.

### dbg-r-0002

Executed on this interpreter, so the interning and small-int-cache claims are
measurements rather than recollections: a literal from the same module is the
identical object, the same text parsed from JSON is not, `int("256")` hits the
cached range while `int("257")` does not, and an id rebuilt by concatenation breaks
an identity lookup that a value comparison handles. The sentinel pattern is
included as the correct use of `is`, and the fix is asserted to preserve behaviour
for both literal and parsed inputs.

### dbg-r-0003

Reproduces the "every button does the last action" symptom in a plain node run and
pins both halves of the trap: the shared `var` binding (all three closures return
one value, the last index) and the reason the single-action test passed (with one
element the final index is also the only index). The `let` and `map` fixes are
asserted to return the registered actions in order, and the last case shows that
invoking the function *inside* the loop yields the correct values even with `var` —
which is exactly what a synchronous unit test does, and why it cannot see the bug.

### dbg-r-0004

Runs the same instant through the buggy and fixed implementations in three process
timezones and pins the divergence: the naive `.date()` difference depends on the
ambient zone (the "today/tomorrow" split customers reported) because the truncation
happens at each zone's own midnight, while the fixed version takes the calendar
zone as an argument and always answers for the customer. The zone-dependent-midnight
table is printed so the mechanism is visible, the naive-versus-aware comparison is
shown to raise instead of guessing, and `is_expired` is asserted to be a pure
instant comparison (zone-independent) before and after the deadline.

### dep-0001

Runs the same package in two subprocesses with different first imports and pins the
asymmetry: `import pkg.models` succeeds while `import pkg.store` fails with
`cannot import name 'Store' from partially initialized module 'pkg.store'`, so the
entry module really does decide the outcome. The second run confirms the mechanism
(the module object is in `sys.modules` while the attribute is missing), the parsed
import graph shows the cycle exists in both directions regardless of order, and the
one-way version is asserted to import and work identically from both entry points.

### dep-0002

A plugin loader's `sys.path.append("app/services")` is reproduced in a subprocess and
the two module objects are inspected side by side: identical `__file__`, different
`__name__`, different class object, `isinstance` False across the copies, distinct
exception classes (so `except` blocks miss), and a module-level registry where the
plugin's write is invisible to the application's copy (1 versus 0) while both names
sit in `sys.modules`. The last case shows the rule: importing the same canonical name
twice returns one shared module, one registry and one class object — identity is per
name, so one name per file is the invariant.

### dep-0003

Both packages are built in a temp directory and imported in subprocesses with
`reportlab` genuinely absent. Pinned: the eager version fails at `import app` for a
host that only serves the API, while the lazy version starts that host with the same
missing package; the feature call fails at the call site with a named
`ExportUnavailable` whose message names the missing library; and the boundary is
checked as an import-graph property (`app.api` cannot reach `reportlab`, `app.export`
can) — the check that keeps an eager import from creeping back in.

### dep-0004

Builds the two modules in memory and pins the binding semantics that explain the
report: before patching, `pricing.now is clock.now` is True (the imported name is a
snapshot), and after `clock.now` is rebound it is False while `pricing.quote` still
returns the real timestamp. Patching `pricing.now` — the name the code actually
looks up — works, the `import clock` variant sees the same patch with no test change,
and the injection form needs no patching at all. The identity check is pinned as the
one-line diagnostic for "my patch does not take effect".

### edge-0001

Pins the failure modes and the size of the error. Representation: `0.1 + 0.2` is
`0.30000000000000004` and `0.1 + 0.7` is `0.7999999999999999`, `Number("10.235")` is
stored just below `10.235`. The two "obvious" fixes are shown disagreeing on the same
input: `(10.235).toFixed(2)` is `"10.23"` while `Math.round(10.235 * 100) / 100` is
`10.24`, and `(1.005).toFixed(2)` is `"1.00"` against a float product of
`100.49999999999999`. Accumulation: 10 000 additions of `0.01` produce
`100.00000000001425` and fail an equality check against 100, while 10 000 additions of one
cent are exactly 10 000 - both asserted. The integer-cents path pins exact totals and
cent-accurate formatting, per-invoice versus per-line tax is shown to differ, and a
string-based `parseAmountToCents` is asserted to round-trip `0.00`, `0.05`, `0.10`,
`10.24`, `999.99`, `-3.05` and `12` through `formatCents` without touching a float.

### edge-0002

Separates the two defects and pins the numbers behind them. Normalisation: the precomposed
and decomposed spellings of `café` are unequal strings of length 4 and 5, one dict keyed by
the raw forms holds two "identical" accounts, and the lookup that misses with the typed
form succeeds after `normalize("NFC", ...)`. Case folding: `"Straße".lower()` does not
match `"STRASSE"` while `casefold()` does, and Turkish `İ` folds to `i` plus a combining
dot under both `lower()` and `casefold()` - pinned as *not* equal to `istanbul`, because
full case folding is not locale tailoring. Truncation: the same name
sliced at 4 code points loses its accent in the decomposed spelling and keeps it in the
precomposed one, and the cluster-preserving helper returns `René` for both and never ends
on a combining mark - while the five-code-point family emoji is shown to be one glyph that
a naive slice splits. The last section pins the byte-versus-character distinction: a
four-byte slice cannot be decoded, `errors="ignore"` silently drops the accent, and a
character limit applied to the text keeps it.

### edge-0003

Reproduces both incidents as values. Precision: two distinct upstream ids (`...993` and
`...992`) parse to the same number and compare equal, `Number.isSafeInteger` is false for
the result, and the same rounding shows up through `parseInt` and through arithmetic
(`id - 1 + 1` does not return the original). Coercion: `2147483648 | 0` is negative,
`4294967296 | 0` and `1 << 31` are shown for what they are, and a millisecond timestamp
masked with `| 0` differs from itself modulo 2^32. The fixes are pinned too: the digits
extracted from the JSON text stay exact and compare unequal as strings, `BigInt` adds
correctly and serialises with an explicit `toString`, a boundary guard fires only on the
unsafe value, and a string-based bucket function keeps the two neighbouring ids in
different buckets - which is what the `| 0` version was silently failing to do.

### edge-0004

Shows the same byte stream parsed at four chunk sizes and pins the difference: the naive
per-chunk parser loses or mangles records at sizes 7 and 13 (fragments that are not JSON,
and names whose accents have been deleted by `errors="ignore"`), while the buffering
parser returns exactly the three original records at every size - including byte-by-byte,
which is the worst case for both the record boundary and the multi-byte character. The
corruption is isolated: the two halves of `café`'s accent byte are shown decoding to `caf`
under `errors="ignore"` (silently), raising `UnicodeDecodeError` under the default
(strictly), producing `\ufffd` under `errors="replace"`, and being reassembled correctly by
an incremental decoder. The last section pins the framing rule that a stream ending
mid-record is truncation, not a record: a complete stream leaves an empty tail, a
truncated one leaves bytes that `json.loads` rejects.

### trc-0001

Traces every pass and pins the mechanism: the scan reads 400 rows of which 342 pass the
filter, the second pass reads 0, and the instrumented yield log contains exactly 342
entries — so nothing
was filtered out, the iterator was simply empty. Also pinned: `iter(stream) is
stream` is True for the generator and False for the list container (the general
test), the summary shows `top: 0` from a silent `max(..., default=0)`, and both
fixes (one `list()` at the boundary, or a single-pass aggregate) produce identical
results.

### trc-0002

The trace is the evidence: with the key already present, the eager version still
emits `load:timeout` (one observable event on what the caller believed was a cache
hit), which is why the log line appeared before any cache-hit logging. Pinned too:
the membership-based fix emits no events for present or zero values and loads only
when the key is missing; the `or` idiom emits no event for `{"timeout": 0}` either
but returns 30 instead of 0, so it hides the eager call rather than fixing it; a
real cache loads exactly once across three calls; and the same eager-evaluation trap
is shown with `setdefault`, whose value argument is computed on both calls even
though the second result is discarded.

### trc-0003

Executes the decorator and pins the contradiction the report could not explain: the
decorated function runs (the call log proves it) yet returns `None`, while `__name__`,
`__doc__`, `str(inspect.signature(...))` and `__wrapped__` all describe the original.
The fixed version is asserted to preserve the return value, the return type and the
signature, and both decorators are shown to propagate the original exception, so the
fix does not trade transparency for logging.

### trc-0004

The trace is produced by running the three versions in a real event loop and
pinning the observed order: the un-awaited `.then` reports `saved` *after* `done`
because a timer is a macrotask while `await` continuations are microtasks; the
synchronous-save variant prints `saved sync` immediately after `start` because the
reaction was queued at registration time; and the joined version forces
`saved` before `done`. The queue-priority demo (`sync`, `micro`, `macro`) pins the
rule that explains all three orders.

### mem-0001

Proves the leak with a weakref sentinel instead of RSS watching: after the connection
handler's cleanup (`del` + `gc.collect()`) the strongly-registered viewer is still alive
and all 50 entries remain, and `gc.get_referrers` is printed to name the retaining
container. The same lifecycle against a `WeakSet` registry drops every entry and the
objects themselves are reclaimed, while a genuinely live object is shown to still be
tracked and reachable by `broadcast` — so the test cannot pass by discarding entries
too eagerly. The final part pins the iteration hazard: a `WeakSet` must be snapshotted
with `list(...)` because entries can vanish mid-loop, and its iteration order is
undefined (it is a hash set), so the names are sorted before comparison rather than
pinned in whatever order the set happened to produce. Each section also runs inside a
function for the same reason the fix works in production: a module-level loop variable
or leftover local is itself a strong reference, and it would keep one object alive and
make the demonstration lie.

### mem-0002

Pins the retention mechanics with numbers: two byte-identical requests create two cache
entries and two renders and *zero* hits (the count is captured before the growth loop) because the argument is a fresh object (identity-based
equality), a weakref sentinel shows the cache keeps the argument alive after `del`, and
202 requests leave 203 entries (the two from part 1, the probe, and 200 more) with zero
hits — the monotonic growth behind the 6 GB. The contrast cases make the lesson usable:
a value-equal string key hits the cache 49 times with a single entry, `maxsize=8` caps the entry count at 8 for 51 distinct keys, and
`cache_clear()` is asserted to release the retained object (the sentinel becomes dead),
which is the operator's remedy as well as the test's teardown.

### mem-0003

Separates the three cases that are usually conflated: (1) an unreachable cycle stays
alive after the last external reference is dropped and is freed by `gc.collect()`;
(2) the same structure kept alive by a registry root is a genuine leak that the
collector cannot fix, and is released only when that root is removed; (3) a tree whose
parent link is a `weakref` is freed by reference counting alone — no collector run
involved. Finalizer-in-cycle behaviour is pinned too (collected, with `gc.garbage`
empty on this interpreter), and the operational tool is demonstrated with
`gc.get_objects()` counts going 0 → 25 → 0, which is the check you would run against a
real leak report (the loop variable has to be deleted too — a stray module-level name
is exactly the kind of root that keeps a cycle alive). The baseline is 0 because the
counts are taken in a fresh process.

### mem-0004

Traces the retention chain with weakrefs at every step: the callback created in `run`
keeps the payload alive after the caller drops it, `gc.get_referrers` plus `__closure__`
name the retainer (the payload is referred to from a tuple — the function's cells) and
the cell contents are printed to show `ParsedFile` sitting in a cell. The
default-argument variant is measured next: `__closure__` has only `path` while
`__defaults__` holds the `ParsedFile`, and the payload stays alive exactly as before —
the same leak with a different attribute. Dropping the callbacks releases both, the
fixed version is asserted to bind only the path, and the last part shows a stored
exception retaining a frame's locals (`payload`) until the exception itself is dropped.

### sec-0001

Demonstrates the vulnerability against a real database instead of describing it: the
`' OR 1=1 --` payload returns all three product rows through the vulnerable query, a
`UNION SELECT` payload returns the token from a different table, and an injected
`ORDER BY` clause is shown to be a genuine injection point (the identifier cannot be
bound). The parameterised version returns the same injected strings as literal searches
(nothing), the sort key is rejected with a `ValueError`, and the products table is still
intact. The last section pins the subtle part of the fix: `%` and `_` must be escaped in
the *value* so a search for "100%" matches the product named "100% wool hat" literally
rather than matching everything.

### sec-0002

Pins the three defects with evidence rather than advice: unsalted SHA-256 produces the
identical digest for identical passwords while salted PBKDF2 records differ for the same
password and verify independently; verification is asserted to accept the correct
password (including a record with lower stored iterations, since the parameters travel
with the hash) and to fail closed on a wrong password, a malformed record and an unknown
algorithm string. The last part makes the timing argument mechanical: a counting
comparison shows the naive `==` examines 1, 17 and 32 bytes depending on where the
mismatch is (so effort leaks the matching prefix), while the constant-time path examines
all 32 every time — the same outcome, different information leak.

### sec-0003

Verifies a real token and then attacks the vulnerable verifier with the tokens that
matter: an `alg: none` token (accepted by the vulnerable code because it ignores the
header, rejected by the fixed one with "unsupported alg"), a token signed with an
attacker's key (rejected), an expired token (accepted by the vulnerable code — it has no
claim checks — and rejected by the fixed one), plus wrong audience, wrong issuer and
`nbf` in the future, each rejected with the specific reason. The comparison section pins
the timing leak mechanically: a `==`-style comparison examines 1, 21 and 32 bytes
depending on the mismatch position, while the constant-time path examines the full
32-byte signature every time.

### sec-0004

Runs ten requests through three implementations and prints the outcome matrix, so the
security property is visible per input rather than asserted in prose: the vulnerable
join serves `/etc/passwd` through `../../`, the `replace("..", "")` fix is bypassed by
`....//` (it collapses back to `../`) and still serves the file, and the resolve-and-check
version refuses every escape attempt — including the sibling directory whose name shares
a prefix with the base, where a string `startswith` check would have accepted it — while
still serving legitimate nested files and allowing inside-base normalisation like
`archive/../notes.txt`. The same check is then applied to a malicious tar member, which
is the write-direction version of the bug.

### stm-0001

Reproduces the "UI does not update" symptom with the mechanism rather than the
symptom: after `push` the store's array length is 2 while the memoised selector returns
the same array object it returned before (so the consumer sees zero rows and is notified
zero times), and `Object.is(previous, next)` confirms the state reference never changed.
The immutable version notifies twice and yields two rows; a second selector that reads
both `rows` and `filter` but keys only on `rows` is shown to stay stale after a filter
change (the state object changed, the array reference did not, so the cache hits), while a selector keyed on what it reads returns the correct one row — the two
distinct bugs (mutation, under-keyed memoisation) are separated by their own assertions.

### stm-0002

Makes the race deterministic by controlling response timing rather than hoping for
network jitter: A is issued first and resolves last, so the naive handler renders
`B,A` and ends with A's data — the user's report reproduced exactly, with the render
order printed as evidence. The sequence-number fix keeps only `B` and records `A` as an
ignored stale response; the abort fix cancels A (in the aborted list, never rendered)
and also ends on `B`. The three implementations share the same fake transport, so the
difference in outcome is attributable to the guard, not to the timing.

### stm-0003

Turns the state machine into an exhaustive test: all 25 (state, event) pairs are
attempted and the observed legal set is asserted equal to the declared transition table,
with the remaining 19 asserted to raise `InvalidTransition` and to name the state — so
the table cannot silently drift from the behaviour. The three impossible sequences from
the report (ship-then-cancel, double refund, cancel-then-ship) are each pinned as
refusals with their message, reachability from `pending` is proved to cover every state
and the terminal states are identified, and the last part shows the same exception
mapped to an HTTP 409 at the boundary rather than leaking a 500.

### stm-0004

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

