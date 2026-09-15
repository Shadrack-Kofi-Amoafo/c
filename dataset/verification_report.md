# Verification report

- examples checked: **57**
- passed: **57**
- failed: **0**
- skipped (toolchain missing): **0**

`executable` = the program under test really ran and its stdout matched the
documented output. `parity` = the algorithm was executed via the Python
reference implementation in `@code` against the same test vectors; the
snippet's syntax was reviewed manually (see the `PARITY:` line in the notes).
`reviewed` = design/vendor-specific artifact with a written checklist.

| example | kind | lang | status | time | evidence |
| --- | --- | --- | --- | --- | --- |
| `py-alg-0001` | executable | python | PASS | 0.08s | python3: output matched |
| `py-alg-0002` | executable | python | PASS | 0.03s | python3: output matched |
| `js-alg-0003` | executable | javascript | PASS | 0.07s | node: output matched |
| `c-alg-0004` | executable | c | PASS | 0.17s | gcc: output matched |
| `py-alg-0005` | executable | python | PASS | 0.02s | python3: output matched |
| `py-alg-0006` | executable | python | PASS | 0.16s | python3: output matched |
| `py-api-0001` | executable | python | PASS | 0.41s | python3: output matched |
| `py-api-0002` | executable | python | PASS | 0.12s | python3: output matched |
| `js-api-0003` | executable | javascript | PASS | 4.68s | node: regex '# pass 8\\n# fail 0' matched |
| `py-api-0004` | executable | python | PASS | 1.56s | python3: output matched |
| `ts-code-0001` | executable | typescript | PASS | 0.36s | tsc: output matched |
| `py-code-0002` | executable | python | PASS | 0.03s | python3: output matched |
| `js-code-0003` | executable | javascript | PASS | 0.04s | node: regex '# pass 7\\b[\\s\\S]*# fail 0' matched |
| `py-code-0004` | executable | python | PASS | 0.08s | python3: output matched |
| `sql-code-0005` | executable | sql | PASS | 0.00s | sqlite3(py): output matched |
| `bash-code-0006` | executable | bash | PASS | 0.43s | bash: output matched |
| `py-read-0001` | executable | python | PASS | 0.01s | python3: output matched |
| `js-read-0002` | executable | javascript | PASS | 0.08s | node: output matched |
| `py-read-0003` | executable | python | PASS | 0.01s | python3: output matched |
| `sql-read-0004` | executable | sql | PASS | 0.00s | sqlite3(py): output matched |
| `ts-read-0005` | executable | typescript | PASS | 0.33s | tsc: output matched |
| `ml-lang-0001` | executable | python | PASS | 0.22s | python3: output matched |
| `ml-lang-0002` | executable | python | PASS | 0.07s | python3: output matched |
| `ml-lang-0003` | executable | python | PASS | 0.27s | python3: output matched |
| `ml-lang-0004` | executable | python | PASS | 0.07s | python3: output matched |
| `py-ds-0001` | executable | python | PASS | 0.07s | python3: regex '\\An=65536: worst prefix=\\d+ update=\\d+ steps vs 4096 slice additions\\nPASS\\n\\Z' matched |
| `py-ds-0002` | executable | python | PASS | 0.08s | python3: regex '\\Afind/union pointer hops: \\d+ for 80000 ops\\nPASS\\n\\Z' matched |
| `js-ds-0003` | executable | javascript | PASS | 0.11s | node: regex '# pass 8\\n# fail 0' matched |
| `c-ds-0004` | executable | c | PASS | 0.27s | gcc: output matched |
| `py-ds-0005` | executable | python | PASS | 0.02s | python3: output matched |
| `py-dbg-0001` | executable | python | PASS | 0.30s | python3: output matched |
| `py-dbg-0002` | executable | python | PASS | 0.02s | python3: output matched |
| `js-dbg-0003` | executable | javascript | PASS | 0.13s | node: output matched |
| `sql-dbg-0004` | executable | sql | PASS | 0.00s | sqlite3(py): output matched |
| `py-dbg-0005` | executable | python | PASS | 0.03s | python3: output matched |
| `py-opt-0001` | executable | python | PASS | 0.51s | python3: regex '\\An= 200 comparisons=\\s+14042\\nn= 400 comparisons=\\s+56589\\nn= 800 comparisons=\\s+242543\\nslow=[\\d.]+ms dict=[\\d.]+ms speedup=\\d+x\\nP |
| `py-opt-0002` | executable | python | PASS | 2.72s | python3: regex '\\Aold:\\s+[\\d.]+MB -> [\\d.]+MB\\nstream:\\s+[\\d.]+MB -> [\\d.]+MB\\ntime old=[\\d.]+ms stream=[\\d.]+ms ratio=[\\d.]+\\nPASS\\n\\Z' matched |
| `sql-opt-0003` | executable | sql | PASS | 0.18s | sqlite3(py): output matched |
| `py-opt-0004` | executable | python | PASS | 0.06s | python3: regex '\\Aq=\\s+64 uncached_calls=\\s+127 cached_misses=\\s+7\\nq=\\s+200 uncached_calls=\\s+399 cached_misses=\\s+12\\nsubproblems: 64->7 200->12 400- |
| `c-opt-0005` | executable | c | PASS | 0.08s | gcc: output matched |
| `py-ref-0001` | executable | python | PASS | 0.02s | python3: output matched |
| `js-ref-0002` | executable | javascript | PASS | 0.03s | node: output matched |
| `py-ref-0003` | executable | python | PASS | 0.03s | python3: output matched |
| `ts-ref-0004` | executable | typescript | PASS | 0.39s | tsc: output matched |
| `py-ref-0005` | executable | python | PASS | 0.05s | python3: output matched |
| `py-sec-0001` | executable | python | PASS | 0.82s | python3: output matched |
| `py-sec-0002` | executable | python | PASS | 0.02s | python3: output matched |
| `js-sec-0003` | executable | javascript | PASS | 0.06s | node: regex '# pass 9\\n# fail 0' matched |
| `py-sec-0004` | executable | python | PASS | 0.07s | python3: output matched |
| `py-arch-0001` | executable | python | PASS | 0.10s | python3: output matched |
| `py-arch-0002` | executable | python | PASS | 0.05s | python3: output matched |
| `js-arch-0003` | executable | javascript | PASS | 0.08s | node: regex '# pass 10\\n# fail 0' matched |
| `py-arch-0004` | executable | python | PASS | 0.03s | python3: output matched |
| `py-test-0001` | executable | python | PASS | 0.03s | python3: output matched |
| `js-test-0002` | executable | javascript | PASS | 0.05s | node: regex '# pass 8\\n# fail 0' matched |
| `py-test-0003` | executable | python | PASS | 0.02s | python3: output matched |
| `py-test-0004` | executable | python | PASS | 0.03s | python3: output matched |

## Notes captured during review

### py-alg-0001

Runs 400 randomized instances against exhaustive subset search (n <= 9) and checks
value equality, feasibility of the reconstructed set, and that the set's revenue
equals the reported optimum. Also pins the tie-break, the half-open boundary
behaviour in both directions, empty input, all-negative input, and rejection of
zero-length intervals.

### py-alg-0002

400 randomized cases compare the streaming scanner against a `bytes.find`-based
reference under three chunkings (random, one-shot, byte-at-a-time), which is the
property that actually matters for stream processing. Additional cases cover the
longest self-overlap ("aabaaab"), overlapping matches, run-length input
("aaaaabaaaaab"), empty text, pattern longer than text, and empty-pattern
rejection.

### js-alg-0003

2000 random graphs (mixing acyclic and cyclic, with de-duplicated edges) are
classified by an independent DFS colouring check. For acyclic graphs the test
asserts the order is a permutation respecting every edge and identical across
repeated calls; for cyclic graphs it asserts the reported walk is closed and
every step of it is a real edge *in edge direction*, so "cycle detected"
messages cannot be faked and inverted-orientation walks cannot slip through.
Explicit cases pin the alphabetical tie-break, insertion-order independence, a
self-loop, a 2-cycle, isolated nodes, and the empty graph. The predecessor-walk
design was chosen after a forward-walk version failed here on a random graph
whose survivor had no surviving dependents.

### c-alg-0004

Built with gcc -std=c11 -Wall -Wextra plus -fsanitize=address,undefined and run
with leak detection on. 3000 randomized instances are compared against an exact
O(n^2 k) DP reference for every k from 1 to n+1, so both answers and the
infeasible cases are pinned. Added cases: the adversarial shape [3,2,2,2],K=3
where naive balancing gives 5 instead of 4, all-zero input, k=1, k=n, k>n,
negative input, and values/totals up to 8e18 to prove the long long arithmetic
does not overflow.

### py-alg-0005

300 random graphs (10-node, weights drawn from {0,1,2,3,10} so zero-weight and
tie-heavy cases are common) compare every distance against an independently
written Bellman-Ford. For each reachable node the recovered path is re-walked
over the original adjacency and its edge weights must sum exactly to the reported
distance. Additional cases: unreachable node, zero-weight triangle (a
predecessor-cycle trap), the stale-heap-entry graph, negative-weight rejection,
empty adjacency, and a self-loop.

### py-alg-0006

Checks, in order: k=0 rejection, n<=k exactness for every small n, fixed-seed
determinism, chunk-invariance, sample shape (size, distinctness, membership),
then a 60000-trial statistical test on N=6,K=3. Inclusion counts must lie within
3.5 sigma of T*K/N and unordered-pair counts within 3.5 sigma of the exact
joint probability T*k(k-1)/(n(n-1)) -- the pair check is what distinguishes real
reservoir sampling from independent draws. The final block runs that same check
against a deliberately biased sampler to show the test has power to fail.

### py-api-0001

Every case talks to a real HTTP server bound to 127.0.0.1:0 (threading
http.server, scripted response plan, one socket per request), so urllib, header
parsing and the transport layer are all exercised; sleeps and the clock are
injected so the deterministic cases run instantly and assert exact delays.
Pinned: a payload is returned after two 503s with bounded jittered delays,
Retry-After is honoured both as seconds and as an HTTP-date (used as a floor, not
as an extra sleep, with the deadline raised so the hour-long wait is simulated),
a 400 produces exactly one request with no sleep and the response body in the
message, exhausted attempts raise RetryableError with the attempt count, the
wall-clock deadline cuts a 50-attempt budget short, malformed JSON on a 200 is
permanent rather than retried, a closed port is retryable, and two end-to-end
cases use the real clock and a midpoint "jitter" to prove the retry loop works
outside the fake-sleeper harness: `Retry-After: 0` adds no delay (and is not
dropped as a falsy value), while a missing header produces a measurable real
sleep.

### py-api-0002

Runs against a real file-backed SQLite database (temp dir), not `:memory:`, so a
second connection can observe the first one's transactions — which is what makes
the commit/rollback claims testable. Pinned: the success path imports 1000 rows
exactly once; re-importing the identical batch inserts 0 and reports 1000 skipped
(ON CONFLICT(id) DO NOTHING on the primary key = idempotency); a failure at row
900 of a 1000-row batch (bound to fail after 500 successful inserts, so the
savepoint path runs) leaves the row count unchanged and surfaces the CHECK
violation; the OR IGNORE trap is reproduced on the same bad batch (no exception,
"2 inserted, 1 skipped", and the bad row is simply gone), which is why the
importer uses ON CONFLICT; an uncommitted row is invisible to another connection
until COMMIT; `with conn:` cannot roll back an autocommitted INSERT
(isolation_level=None) but does commit/rollback correctly in the default
isolation mode, with `in_transaction` false afterwards; a 2500-row batch with
batch_size=100 stays atomic; `PRAGMA foreign_keys=ON` rejects an orphan row; and a
second importer fails fast with "database is locked" instead of deadlocking when
the write lock is held, with the winner's row the only one committed.

### js-api-0003

Eight node:test cases against a real http server on an ephemeral port (no fetch
mocking), so abort behaviour, header parsing and socket handling are real. Pinned:
fetch resolving on 404 with `response.ok` turning it into an HttpError carrying
status and parsed body; three-page cursor pagination including the terminating
null cursor and the `limit` query parameter; a 429 whose Retry-After is honoured
as a floor (recorded retry delays, no real sleep); the retry budget stopping
after one retry (server call count asserted); `AbortSignal.timeout` raising
`TimeoutError` **and** the server observing an aborted request rather than a
merely abandoned one; a caller AbortController composed via `AbortSignal.any`
still cancelling; `mapWithConcurrency` keeping the peak in-flight count at or
below the limit while preserving input order, with `limit < 1` rejected; and a
payload missing `items` failing loudly instead of yielding an empty result.

### py-api-0004

Nine cases against real child processes (this interpreter, spawned with -c
programs), so pipes, signals and process groups are genuinely exercised. Pinned:
stdout and stderr stay separate and are decoded as text; a non-zero exit raises
CommandFailed carrying returncode plus both streams (including the partial stdout
written before the failure); 1 MiB written to each stream completes without
deadlock, which is the read-then-wait bug this pattern avoids; a timeout fires in
under a second, reports "(timeout 0.5s)" and still returns the output captured
before the kill; a spawned grandchild is dead after the timeout (start_new_session
plus killpg reach the whole process group, not just the direct child); stdin is
closed unless input_text is supplied, so a reading child gets EOF instead of
hanging, and input_text is delivered when given; a stray non-UTF-8 byte is
replaced rather than raising; a string argv is refused as an injection risk; exit
code 127 propagates verbatim; and env/cwd are applied per call without mutating the
parent's environment.

### ts-code-0001

Executed as TypeScript: `tsc --strict` must accept the file (which validates the
type-level assertions, including the @ts-expect-error probe), then the emitted
JavaScript runs. Runtime assertions cover: non-retryable short-circuit and
identity of the rethrown error, the exact jittered backoff schedule
[50,75,75] under a scripted RNG and maxDelay cap, Retry-After overriding jitter
and then being capped at maxDelayMs, the deadline refusing to sleep past the
budget (elapsed < 60ms with zero sleeps), pre-aborted signals, and both
RangeError guard clauses.

### py-code-0002

Executed with the stdlib only. Covers: shuffled columns plus an unknown extra
column, UTF-8 BOM, whitespace-padded values, a quoted field containing a newline
(so line numbers must come from csv's own counter, asserted at lines 3-8),
one row per reject reason with exact reasons and line numbers, and three schema
failures that must raise instead of yielding partial data. The final check uses
an instrumented handle to prove the generator is lazy (only the first record's
lines are consumed by the first `next()`), which is the memory property the
answer claims.

### js-code-0003

Executed with `node case.mjs` using the built-in `node:test` runner (no
dependencies) and a fake clock, so the suite is instant and exact: burst then
429 with retryAfterMs=500, capped refill with fractional accumulation, a
backwards clock step, weighted costs with tenant isolation, an impossible cost
(cost > capacity) that must never report success, idle sweeping keeping the map
bounded, and constructor validation. The expected output pins the pass count
(7) and `# fail 0`; a non-zero test failure exit code also fails the run.

### py-code-0004

Six threaded tests with hard timeouts (a deadlock fails the suite instead of
hanging it): 8 threads with a Barrier collapse into exactly 1 factory call with
all callers receiving the identical object and the pending map drained; two
distinct keys are proven to compute concurrently via two Events (a global lock
would deadlock and fail the assertion); TTL boundary at 29.999s vs 30.001s on an
injected clock; LRU order and the hard capacity bound; leader exception identity
plus the key still being usable afterwards; and constructor guards.

### sql-code-0005

Runs in SQLite 3.40 (Python's bundled engine), which is the reference dialect
here; the query uses only standard SQL features (CTEs, window frame,
strftime) that Postgres/BigQuery-shaped warehouses have equivalents for. The
fixture encodes exactly the interesting cases: a user with two events in one
month (must count once), a user whose only late activity is at month offset 3,
and a cohort starting mid-data. The expected output pins every retention row,
then re-derives the rolling column with a correlated-subquery formulation and
pins those rows too (they must match the window version), asserts the query plan
actually uses the covering index, and asserts month-0 retention equals the cohort
size (100% by construction) using COUNT(DISTINCT user_id) -- the row-count
version of that check reports 8 for the first cohort and is exactly the kind of
silent bug this file guards against.
Note the month arithmetic is deliberately computed from '-01' anchors; using
date(x, '+1 month') on a month-end date returns the wrong month in SQLite.

### bash-code-0006

The harness writes the deploy script to a temp dir and runs seven scenarios with
`bash`, asserting exit codes, the resolved `current` target, the served file
content and the log text: publish, idempotent re-run ("nothing to do"), dry run
that leaves state untouched, failing health check with exactly 3 probes and a
rollback to the previous release, a healthy deploy that switches over, a missing
release directory that fails without touching the symlink, and no leftover
`.current.*` temp links. Uses `mv -T` for the atomic rename; the same script text
is what the answer shows above.

### py-read-0001

Executes the snippet verbatim and pins all three surprising outputs
(['c','c','c'] and the accumulated [1], [1,2], [1,2,10]); asserts the three calls
shared one default list object via `__defaults__`, and that a single-call helper
looks correct (the reason the bug survives review). Then runs both fixes and
asserts they change the behaviour, that the default is no longer mutable, and
that a caller-supplied list is not mutated.

### js-read-0002

Executed with node v22. Pins the full seven-line ordering of the snippet under
discussion, then verifies the other claims in the explanation: a long promise
chain starves a `setTimeout(..., 0)` macrotask until the microtask queue empties,
and `await` inside a loop interleaves with code after the loop body starts
(before x, after loop body started, after x, ...). For the Node-only `nextTick`
queue the test asserts BOTH dialects (ESM module scope here, plus a CommonJS
child process spawned with execFileSync) and fails if they do not actually
differ, because a single-dialect assertion is exactly how the wrong folklore
about "nextTick always runs first" gets into documentation.

### py-read-0003

Executes and asserts the four printed values plus every rule stated in the
explanation: MRO search before __getattr__, metaclass __getattr__ for class-level
access, __dict__ still present because `Base` lacks __slots__, data descriptors
(property) beating instance dict assignment, __slots__ saving memory only when
the whole MRO defines it, and the unset-slot/__getattr__ interaction in both a
permissive and a strict variant. Also checks __getattribute__ interception with
a super() delegation.

### sql-read-0004

Runs in SQLite with a fixture covering the three interesting user shapes
(paid-only, unpaid-only, no orders) plus a mixed user. The expected output pins:
COUNT(*) reporting 1 for matched-nothing users next to the correct COUNT(o.id)
zeros, query B silently dropping users 2 and 3, the corrected report including
all four users, the HAVING COUNT(o.id) = 0 dashboard result, and both NULL traps
(NOT IN returning 1 row before a NULL exists in the subquery and 0 rows after,
versus NOT EXISTS which is unaffected).

### ts-read-0005

Compiled with `tsc --strict --noEmit`; the run passes only if every type-level
assertion holds and every `@ts-expect-error` line does produce an error (an
unused ts-expect-error is itself an error). Covers recursive inference through
nested Promises, non-distributive cases, the absence of thenable handling in this
simplified Unwrap (unlike the built-in Awaited), per-route/per-method parameter
inference via mapped types, the excess-property rejection, and the documented
limitation that an intermediate variable defeats freshness checking.

### ml-lang-0001

The verify script drives both languages: it writes the JavaScript implementation to
a temp file and runs it with `node`, then compares results case by case. Pinned:
`Math.round(2.5) === 3` while Python's `round(2.5) == 2`, `Math.round(-0.5)` is
`-0`, and `0.1 + 0.2` canonicalises to `0.30000000000000004`; the integer
implementation agrees across languages for 36 basis-point cases (including
negatives and 200% rates) and 35 allocation cases (total -100 to 9999, two to six
weights; the weighted `(1,2,3,4,5,6)` split is bounded to within one minor unit of
the exact ratio rather than the equal-weight ±1 rule); every allocation sums back
to its total in both languages and ties break identically; a search over 20k
amounts finds that the float version disagrees with the contract on the first case
`(2, 2500)` — Python's `round(0.5) == 0` drops half a cent — and more than a
hundred times in total; the JS float path disagrees with the integer contract on
more than 50 of 6600 batched cases and every one of them is negative, because
`Math.round(-0.5)` is `-0`; the naive float formula also disagrees *between* the
two languages on positive and negative amounts, so the same bug cannot even be
reproduced consistently; canonical JSON is byte-stable and re-parses identically;
and repeated runs are deterministic.

### ml-lang-0002

The verify script runs the same measurements in both languages: `node` reports code
points, UTF-16 units, UTF-8 bytes and `Intl.Segmenter` clusters for ten strings
(NFC/NFD accents, an astral emoji, a ZWJ family, a flag, a keycap, a skin-tone
modifier, a rainbow flag, Korean syllables, two stacked combining marks). Pinned:
Python `len` equals JS `Array.from(s).length` for every case while the UTF-16 count
is larger for astral characters; `café` is (4, 4, 5) and `cafe\u0301` is (5, 5, 6)
in (code points, UTF-16 units, bytes) and the two are equal only after NFC
normalisation, so the same name can be stored twice; the emoji is (1, 2, 4) and the
family is (7, 11, 25); `"👍".slice(0, 1)` is a lone surrogate that fails
`isWellFormed()`, encodes to `efbfbd` (U+FFFD) in Node, and arrives in Python as
`\ud83d` — which JSON accepts, strict UTF-8 cannot decode, `errors="replace"` turns
into `?`, and only `surrogatepass` round-trips as the invalid CESU-8 bytes `ed a0 bd`;
the cluster approximation matches `Intl.Segmenter` exactly on all ten strings,
including the flag pair and the keycap sequence; column-fit checks show the family
fitting a 4-character budget while `hello` does not, `cafe\u0301` failing a
4-code-point budget, and even `café` failing a 4-byte budget; cutting `café au
lait` at 4 bytes raises `UnicodeDecodeError` while 5 bytes decode exactly; and the
sort-order check shows the raw byte order (`Éclair` after `banana`) differs from the
casefolded order a user expects.

### ml-lang-0003

Three implementations executed in one verify run: a C program compiled with
`cc -std=c11 -Wall -Wextra -O1`, a Node script, and Python. Pinned: C gives
`-7 / 2 == -3` and `-7 % 2 == -1` while Python gives `-4` and `1`, and JS
`Math.trunc(a/b)`/`a % b` matches C on all four sign combinations (also checked
against the compiled C output, not just against Python's emulation of it);
`Math.floor` matches Python on the same four pairs; the day-bucket comparison uses
nine timestamps including -1, -86400 and -86401, where trunc and floor differ by
exactly one day and the truncated answer for -1 maps to 1970-01-01 instead of the
correct 1969-12-31 (proved against `datetime.fromtimestamp(-1, tz=utc)`), and every
one of the 431 994 negative seconds except the six day boundaries is off by one;
FNV-1a of "hello" is the same 32-bit value (1335831723) in C's `uint32_t`, in a
Python implementation that masks with `& 0xFFFFFFFF`, and in JS `Math.imul(...) >>>
0`; unsigned overflow wraps to 0 by definition while a signed `int32_t` one second
past 2038-01-19T03:14:07Z becomes -2147483648 and time-travels to 1901; a negative
hash index is `undefined` in JS (JSON drops the key), silently wraps to the last
element in Python, and is undefined behaviour in C; JS loses `2**53 + 1` as a
number and `BigInt(9007199254740993)` cannot recover it because the literal was
rounded first (`BigInt("9007199254740993")` can), while Python's `json` keeps it
exact; and the portable `floor_div`/`mod_non_negative` helpers are checked against
Python's own operators for every combination of a in [-25, 25] and b in {2,3,7,86400}.

### ml-lang-0004

The verify script runs a Node program under `TZ=Europe/London` and compares its
results with Python's `zoneinfo` for the same instants. Pinned: the same instant is
10 digits in seconds and 13 in milliseconds, `detect_unit` converts both to the
identical canonical string, and `Math.floor(ms / 1000)` agrees with integer-second
arithmetic; `23:59:59.999999Z` canonicalises to `...59.999Z` (truncated) while
adding 500µs rounds into `2024-04-01T00:00:00.000Z`, which is why truncation is the
rule; `.999` equals `.998` when the microsecond is dropped rather than carried;
JavaScript's three parse forms of the same date produce three instants
(`"2024-03-31"` → 00:00Z, `"2024-03-31T02:30:00"` → 01:30Z in the spring-forward
gap, `"2024-03-31T02:30:00Z"` → 02:30Z, 2.5 hours apart and 9 000 000 ms from
date-only to UTC), and the same wall clock in Accra, London and UTC gives two
distinct answers with London one hour off; comparing a naive and an aware datetime
raises `TypeError` instead of guessing; the ambiguous fall-back hour yields two
instants one hour apart whose `utcoffset()` is +1:00 and 0:00, and JavaScript's
local-time constructor silently picks the first — agreeing with `fold=0` by luck;
canonical strings are all 24 characters wide, so `sorted(strings)` equals the
chronological order, and parse/canonicalise round-trips both the pre-1970 instant
and the 2038 one; and an offset-less wall clock is asserted to be ambiguous across
zones while `+00:00`, `Z` and `03:30+02:00` all canonicalise to the same instant.

### py-ds-0001

Executes the linear-time build against an independently written per-index
update loop (identical trees, not just identical totals), then 200 randomized
trials of interleaved point updates and range queries against a naive list.
Also pinned: explicit IndexError/ValueError for bad indices instead of silent
wraparound, range_sum(i, i) == 0, and loop-step instrumentation showing both
operations visit at most bit_length(n)+1 nodes at n = 65536, which is the
O(log n) claim made concrete. A sliding-window check covers the "negative delta"
use case mentioned in the answer.

### py-ds-0002

120 randomized graphs are cross-checked against an independent BFS over the same
edge list, comparing both the component count and the pairwise connected()
answers; the sequencing below covers the pathological cases. Also executed: the
40k-merge sequential chain that motivated the question (compresses to a single
component with every node verified to be at most one hop from its root), the
union-by-size invariant (the root's size equals the set size), idempotent
re-merges returning False without changing the component count, self-union,
out-of-range-free `find` on a single-node set, and constructor validation.

### js-ds-0003

Eight node:test cases, with a differential test as the core: 4000 random
push/priority-update/cancel/pop operations are replayed against a sorted-array
reference sharing the (priority, insertion-order) tie-break, comparing the
popped id and priority on every pop and the live size after every operation,
then draining both queues and comparing the full pop order. Three regression
cases encode bugs found while writing this: a priority update must not discard
the replacement entry that reuses the same id (the id-tombstone bug, its own
test); dead
entries must be discarded as they surface and must not be left behind (the
"heap.pop() removes the last element, not the root" bug, pinned by asserting
heapSize 0 after the drain); and compaction must re-heapify instead of relying on
`filter` preserving the heap property, which it does not — the drained order is
asserted sorted after a compaction. Also pinned:
insertion-order stability for 200 equal-priority jobs, cancelled entries never
surfacing, compaction removing exactly the garbage count while preserving live
order, boundary validation (NaN/Infinity/duplicate id/missing id) including the
ordering of validation versus state change, and both overload policies.

### c-ds-0004

Compiled with -fsanitize=address,undefined so the key-ownership rules in the
answer (copy on insert, free on rehash and destroy, never double-free) are
verified by the sanitizer as well as by the assertions. The first case
reproduces the reported production bug directly: 200 inserts, every second key
deleted, then every survivor must still be found — with NULL-on-delete at least
one survivor disappears, which is the "keys vanish after deletes" symptom. It
also asserts the tombstone-pressure rehash fired. Then 40 randomised trials
(~16k operations) are differentially tested against a naive association list,
comparing insert/delete/lookup results and the live count after every operation,
followed by a full re-lookup of the reference's live keys. A 20k-insert / 18k-
delete churn phase pins the load-factor bound (used, not count, drives rehashing)
and confirms all 2000 survivors are intact; edge cases cover the empty key,
overwrite-not-grow, double delete returning false, and delete-then-reinsert
reusing the tombstone.

### py-ds-0005

The adjacency bug is the first case exercised, in all three shapes: right-touch,
left-touch and a bridging insert, each asserting the exact resulting interval
list, so either of the two comparison slips (`>` instead of `>=`, `<` instead of
`<=`) fails immediately. Also pinned: overlap/containment/exact-duplicate
collapses, a chain of three touching right neighbours absorbed in one insert,
membership and free_before differentially tested against a per-point truth set
over 400 random inserts, intersected sizes including the empty intersection, the
unsorted overlapping constructor input, ValueError for empty and reversed ranges,
idempotent re-inserts, and a 5000-insert soak that re-checks the stated invariant
(sorted, non-empty, strictly non-adjacent) every 50 operations.

### py-dbg-0001

Runs the real event loop. The buggy loop is cancelled and must return normally
after ~200ms having recorded the swallowed cancellation; the fixed loop must
raise CancelledError within 50ms having recorded exactly one cancellation and no
errors. Also asserts the inheritance fact that makes `except Exception` safe
(CancelledError is a BaseException, not an Exception), that ordinary exceptions
inside the corrected handler are still collected, and that a finally-block
cleanup runs during cancellation without resurrecting the task.

### py-dbg-0002

Asserts the float drift on a realistic 10-line invoice (104.89 vs 104.90) AND
that it actually differs from the Decimal result (a test that cannot fail proves
nothing), the
banker's-rounding surprises including 2.675, exact vs inexact Decimal
construction, the integer-cents path, localcontext isolation of the rounding
mode, and the real-world divergence between "quantize each line then sum" and
"sum then quantize" with pinned values for both.

### js-dbg-0003

Demonstrates the bug rather than describing it: `forEach(async ...)` returns an
empty array that fills in later, and a rejection from it surfaces as a
process-level `unhandledRejection` (captured, not crashed). Then pins the three
fixes: sequential ordering with completion-before-resolve, bounded parallel with
a measured peak in-flight count of 3 and fail-fast rejection propagation, and
`Promise.allSettled` producing exactly the expected successes and failures.

### sql-dbg-0004

Runs in SQLite 3.40 (IS NOT DISTINCT FROM and FILTER are both available there).
Values hand-checked against the fixture before being pinned (the first draft of
this file asserted 3 / 0 / 0 for three of these, all wrong). Each trap has a
pinned observable: the WHERE-on-nullable-side version losing rows,
the corrected per-customer counts and revenues, COUNT(*) reporting 1 for orderless
customers, SUM returning a NULL row that COALESCE fixes, NOT IN going from 3 rows
to 0 rows after a single NULL is inserted into the subquery, the NULL-safe
NOT EXISTS version still returning the right rows, and the three-way NULL equality
inconsistency (0 join matches, but NULL forms its own GROUP BY / DISTINCT group).

### py-dbg-0005

Requires tzdata (/usr/share/zoneinfo on this machine). Pins the real DST
behaviour for America/New_York: naive vs aware duration across the fall-back
(45 min wall clock vs 1h45 elapsed), fold=0/1 selecting the two distinct instants
that share a wall-clock reading (including that the default fold=0 gives the
shorter 45-minute duration while fold=1 gives the true 1h45), spring-forward gap normalisation, TypeError on
naive/aware mixing, astimezone() on a naive value being shifted by the local
offset, the fromtimestamp() round trip, monotonic-based deadlines surviving a
simulated wall-clock jump, and the UTC-vs-local calendar-day divergence for a
single instant.

### py-opt-0001

Two independent kinds of evidence. (1) Exact equality-comparison counts from an
instrumented row type: on all-distinct keys the list version performs more than
n^2/4 comparisons at n = 200/400/800 and grows by ~4x when n doubles, while both
hash-based versions perform exactly zero comparisons. (2) A measured wall-clock
ratio on an identical 8000-row worst-case input (best of 3 runs, same process)
with a conservative > 20x assertion; the observed margin is an order of
magnitude larger.
Also asserts all three implementations return identical results including order,
and that unhashable input raises the expected TypeError.

### py-opt-0002

tracemalloc-based evidence at 20k and 80k rows, with output written to a
discarding sink so the measurement is the object graph rather than the output
buffer: the list-building version's peak grows with the input while the streaming
version stays under 2x, and the old
peak exceeds the streaming peak by more than 8x. Also asserts byte-identical JSON
output for n = 0, 1, 5, 100 and identical ValueError behaviour on a malformed row,
plus a loose timing bound so a per-row syscall regression would be caught without
making the test flaky. The final block demonstrates the lazy-source requirement
(and shows the anti-pattern of accumulating rows in a spy list).

### sql-opt-0003

Runs in SQLite 3.40 with a 2000-customer / 40k-order fixture (Euro region = 500
customers, one in four of which has no orders at all). Rather than pinning result
rows -- the first draft of this check did that and mis-computed them -- each
semantic check is an assertion query that prints `pass: ...` or `FAIL: ...`, so
drift shows up as a failure line: set-level and row-level equality between the
correlated and grouped forms, with and without COALESCE (pinning the NULL
semantics separately), plus a guard that the fixture really contains orderless
customers so the NULL assertion is not vacuous. Index usage is pinned from three
standalone EXPLAIN QUERY PLAN result sets (EXPLAIN cannot be nested in a
subquery in SQLite): a covering-index SEARCH for the region filter, an index scan
of orders for the grouped aggregate, and a full SCAN once the indexed column is
wrapped in `upper()` -- which is the difference between an index seek and a full
table scan on a 5M-row table. That plan text is SQLite 3.40-specific.

### py-opt-0004

Three findings pinned by execution. (1) The original base case is wrong: the
halving split always reaches quantity=1, whose sub-calls are (0,1), so it
recurses forever for every positive quantity -- the test lowers the recursion
limit and asserts RecursionError at quantities 1, 2, 4 and 100, and that only
quantity 0 returns. (2) The corrected version is behaviour-identical to the uncached
recursion for every quantity from 2 to 129 across both skus and tiers, and is now
defined at quantity=1. (3) Memoisation cuts calls by orders of magnitude with
exact counts (uncached calls vs cache misses at q=64 and q=200, then the
logarithmic growth of the distinct-subproblem set: 7, 12, 13 and 19 entries for
q=64, 200, 400 and 3000). Also
asserted: a warm cache issues no further unit_price calls, repeated calls are
hits not misses, and changing a price is only visible after an explicit
cache_clear (the documented staleness risk).

### c-opt-0005

Compiled with gcc -std=c11 -Wall -Wextra -O1 (ASan build in CI). Exact comparison
counting replaces benchmarking: for all-distinct inputs the quadratic version's
comparison count must grow by 3-5x each time n doubles (measured across
1000-8000), which is the O(n^2) signature. 200 randomized trials cross-check the
sorted version against the quadratic reference for identical results, including
heavy-collision inputs. Also pinned: the occurrence-counting semantics shared by all
three implementations (3 extra occurrences on {7,7,7,9,9,11}; the
distinct-duplicated-ids metric would be 2, and the test computes both so they
cannot be confused), empty/single/all-identical/sorted edge cases,
and a 40k scattered-unique input so the sorted path is exercised at scale.

### py-ref-0001

The original function is kept verbatim as a reference implementation and compared
against the refactor over a generated matrix of 114 cases (countries including an
unknown one, `None` and a lowercase variant; totals at 0, just below, exactly at
and just above both thresholds; express on/off; empty and non-empty item lists).
Every case must produce an identical (outcome, value) or (outcome, exception type,
message) pair. Extra assertions pin the boundary behaviours that a careless
rewrite would flip, plus the extensibility claim (adding a region is a data edit).

### js-ref-0002

Runs both implementations against identical scripted fakes and compares the
outcome AND the dependency call order for six scenarios (success, zero balance,
and a failure at each of the four dependency calls). The harness also detects a
double callback from the original, confirming the defect the answer describes.
Separately asserts the improvements: exactly one settlement of the promise, no
writes after a failure, notify skipped at zero balance, and notify errors still
propagating.

### py-ref-0003

The original dispatcher is kept verbatim and compared against the registry-based
version over 12 events, comparing return value, exception type and message, and
the recorded repository/mailer call sequences for each case (so side-effect order
is covered too). Also pins the contract that unknown types raise KeyError with
the original message, that a missing "type" key still raises KeyError, that a new
type can be registered without editing the dispatcher, that a custom registry does
not mutate the module default, and that handlers are unit-testable in isolation.

### ts-ref-0004

Compiled with `tsc --strict` then executed. The four `@ts-expect-error` probes
prove the illegal states are now type errors (and would fail the build if they
stopped being), while type-level assertions check variant extraction. The runtime
section pins the exact key sets produced by each transition (so no phantom
optional fields survive), refusal of every illegal transition with a reason rather
than an exception, retry-after-failure, describe() output per variant, and that
the input object is never mutated.

### py-ref-0005

The original function is kept and driven through the same frozen-clock scenario as
the refactored one (monkeypatching datetime.now at the module level, the technique
the answer argues against, but needed here to compare against legacy behaviour);
counts, sent-email tuples and the reminders table must match exactly. Then the new
seam is used for tests that were impossible before: a fixed clock, an injected
store and a recording mailer, idempotency across two runs, a clock moved a year
backwards, mailer failure leaving no reminder recorded (behaviour preserved), and
naive stored timestamps being interpreted as UTC rather than local time.

### py-sec-0001

Nine executed cases. Pinned: the record is self-describing
(`scrypt$1$n=16384,r=8,p=1$salt$digest`) and verifies without reference to module
constants; wrong and empty passwords fail; identical passwords with different
salts produce different records that both verify; the stored digest differs from a
single-round SHA-256 of the password; the legacy `sha256$` row verifies and
login returns a fresh scrypt record (the no-forced-reset migration path: the legacy
record reports `needs_rehash`, and a wrong-password attempt must not upgrade
anything); a weak scrypt record
(version 0) triggers rehash-on-success only; a pepper is required for a peppered
record, so a database dump alone cannot be verified offline; truncated and unknown
records fail closed (constant-time comparison must not raise), with unknown
schemes rejected loudly; hashing takes a measurable but login-acceptable amount of
time; and an empty password is refused at the boundary.

### py-sec-0002

Executed against a real SQLite database. Pinned: normal substring search and the
allowlisted sort work; a user-typed `%` or `_` is treated as a literal (it matches only the row
containing that character, and the combination `%_%` matches nothing) while the
unsafe version returns every row for either character — the
information-disclosure bug reproduced side by side with the fix; escaping handles
backslashes in the right order; five injection payloads (tautology, stacked
DROP TABLE, UNION SELECT, comment truncation, wildcard-prefixed) all return no
rows and the table plus its five rows survive; the unsafe query demonstrably leaks
everything for the same payload, so the test cannot pass by accident; unsupported
sort keys and out-of-range limits raise ValueError while allowlisted sorts still
work; and a `PRAGMA query_only` connection refuses writes, showing the
defence-in-depth layer that bounds the next mistake.

### js-sec-0003

Nine node:test cases, all negative-first. Pinned: a valid token round-trips its
payload; editing the payload while keeping the signature is rejected (the exact
attack the review found); a token signed with an unknown key is rejected; the
legacy unsigned base64 JSON — and empty, truncated or non-string values — are
rejected outright; every single byte of the signature is flipped in turn and all 32
mutations must fail, plus a truncated signature must fail without throwing
(length check before timingSafeEqual); expiry is enforced from the signed payload
with a 30s leeway and a missing `exp` is malformed; key rotation keeps old tokens
valid while both keys are published and only invalidates them when `k1` is
retired, with the new token carrying `kid: k2`; an injected `kid` fails closed and
an `alg: none` style header change does not help an attacker because the
algorithm is never read from the token; and `crypto.timingSafeEqual` is asserted to
exist with its length contract, documenting why the code checks lengths first.

### py-sec-0004

Eight cases against real zip files on disk, covering the four attack classes named
in the answer. Pinned: a benign nested bundle extracts and the extracted paths are
returned; three traversal spellings (`../x`, `a/../../x`, `./../x`) are refused and
nothing appears outside the destination; absolute POSIX names are refused and
Windows-style names (`C:\\Windows\\pwn.ini`, `\\\\server\\share\\pwn`) are refused as
non-POSIX rather than guessed at; symlink entries are refused and not created; a *pre-planted* symlink
inside the destination cannot be used to write outside it (the realpath check
resolves the link and refuses), which is why the extractor validates paths rather
than only names; a 5MB zip bomb is caught by both the total-size budget and the
compression-ratio cap, while extracting fine with sane limits; the entry cap is
enforced before anything is written; a sibling directory named like the
destination cannot be reached (`dest-evil` is still outside `dest`, whereas a naive
`startswith(root)` check would allow it); and deeply nested archive paths resolve
inside the root.

### py-arch-0001

Executed end to end. Pinned: the two-module cycle really fails at import time
(`ImportError: cannot import name 'Order' from partially initialized module`) and
the text of that error is asserted; the deferred-import "fix" makes the import
succeed *and* is still reported as a cycle by an AST checker that walks into
function bodies (so the checker's own value is demonstrated, not claimed); the
fixed package imports `domain.orders` without loading `adapters.sqlite_repo` — no
module under `domain/` imports `sqlite` or `adapters`, asserted from the parsed
import list; the graph is acyclic; one `contract(repo)` function runs against both
an in-memory double and the SQLite adapter and passes for both, including the
rejected non-positive order leaving no row behind; and the composition root wires
adapter to service so a real order can be placed and read back. The naive
`startswith(root)`-style shortcut does not appear here, but the fixture layout does
verify that a deferred import inside `__init__` is still detected.

### py-arch-0002

Executed against SQLite. Pinned: the business write and its event are in one
transaction, and a CHECK-violating order leaves neither an order nor an event (no
orphan row either way); the naive "write then publish outside the transaction"
version loses the event outright — the broker received it, the outbox has zero
rows, so no relay can ever find it, which is the incident reproduced; a simulated
crash between send and mark leaves the row unpublished, the next pass re-sends it
(event ids [1, 1, 2] then [1, 1, 2, 2] with an injected broker redelivery), and the
idempotent consumer applies the duplicate exactly zero extra times (dedupe row and
projection share a transaction, redelivery returns False) with the projection
holding exactly two rows; `seq` is unique and increasing per aggregate across
three orders; a permanently failing event is retried, dead-lettered after the
attempt budget, and the healthy event in the same batch is published anyway (the
queue does not stall); a dead letter survives the retention delete of published
rows; and a fresh connection to the same on-disk database still finds the pending
event after the writer process exits.

### js-arch-0003

Ten node:test cases over real files in a temp directory. Pinned: a correctly
layered project produces zero violations while all six modules are reachable from
the composition root; a `domain` module importing `infrastructure` is reported as a
layer violation at the exact line of the offending import; a package import
(`lodash`) inside `domain` is a purity violation while the same import in an
adapter is not; a two-module cycle is reported once with the full path (asserted as
three arrow-separated segments that start and end at the same file) alongside the
layer violation for the same edge; a module with eight local imports trips the
fan-out budget with the count in the message, and splitting it into two groups
clears the violation; an unreachable file is an orphan; a missing entry point fails
the check instead of passing vacuously; a dangling relative import is reported as
unresolved rather than ignored; violations are deduplicated and every one carries
rule, file and line; and 50 analyses of the fixture complete in well under the
budget, so the rule can live in CI. Note the composition root is allowed to import
every layer — that is where wiring belongs, and the fixture models it.

### py-arch-0004

Executed. Pinned: the dependency order is level-based and alphabetical within a
level (`database, metrics, cache, migrations, http`), and registering the same
plugins in a different order yields the identical order, so the graph — not the
registration call order — decides; every dependency starts before its consumer, and
shutdown events are exactly the reverse of `report.started` with no plugin stopped
twice; a plugin raising on start leaves its dependents skipped with a reason naming
the root cause while independent plugins still start; the skip propagates
transitively (`dashboards` blocked because `http` was skipped, with `cache` still
named as the original cause); a plugin that never started is never stopped while
the successfully started ones still are; a cycle raises `PluginError` naming both
ends before any plugin runs (the context is asserted empty); an unknown dependency
and a duplicate name are refused at their respective boundaries; a plugin whose
`stop()` raises is reported in `failed_stop` while every other plugin still stops in
reverse order; and partial startup leaves the shared context consistent
(`db` and `schema` present, the failing plugin absent from `started`).

### py-test-0001

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

### js-test-0002

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

### py-test-0003

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

### py-test-0004

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

