@example py-opt-0001
@meta category=optimization language=python difficulty=intermediate tags=complexity,deduplication,benchmarking,big-o

@user
This deduplication is our slowest ingest step: 40k rows take ~9 seconds. Rewrite it and show me the evidence that it is actually faster, not just different. I care about worst-case behaviour, not micro-tweaks.

```python
def dedupe(rows):
    unique = []
    for row in rows:
        if row not in unique:      # linear scan of everything seen so far
            unique.append(row)
    return unique
```
@@end

@assistant
`row not in unique` scans a list, so the loop is O(n²): 40k rows means ~800 million comparisons in the worst case. Replacing the list with a hash-based structure makes it O(n) — this is an algorithmic fix, not a micro-optimisation, so it wins regardless of interpreter, hardware or row size.

Two idiomatic O(n) forms, both order-preserving:

```python
def dedupe(rows):
    """Order-preserving dedupe in O(n) time, O(n) space."""
    return list(dict.fromkeys(rows))          # fastest: one C-level pass, no set growth checks
```

```python
def dedupe_explicit(rows):
    seen = set()                              # or a dict if you also want counts
    unique = []
    for row in rows:
        if row not in seen:                   # O(1) average
            seen.add(row)
            unique.append(row)
    return unique
```

Notes that matter for the real ingest path:

- **Requires hashable rows.** If rows are dicts or lists, either convert to a canonical tuple/canonical JSON string at the boundary, or use the `dict` keyed by that canonical form while keeping the original object as the value. Do not reach for `json.dumps(row, sort_keys=True)` on every row without measuring — that is often slower than the dedupe itself.
- **Ordering is preserved** because both `dict` and the explicit list keep insertion order. If you do not need order, `list(set(rows))` is slightly faster but reorders.
- **Worst case is still O(n) *amortised*.** A hash-flooding input (adversarial keys colliding in one bucket) can degrade to O(n²); Python randomises string hashes (`PYTHONHASHSEED`) to make this hard, which is the mitigation, and it is why "set is always O(1)" is a claim worth qualifying.
- **Memory trade-off**: the set holds n references, so peak memory roughly doubles versus the output list alone. For a 40k-row ingest this is irrelevant; for a 500M-row stream it is why you dedupe with a bounded structure (a Bloom filter, or the database's unique index) instead.
- **Do not benchmark with `time.time()` and one run.** Use `time.perf_counter()`, run both implementations on the *same* input, repeat, and report a ratio. Ratio assertions with generous margins (say "≥ 20x") are stable across machines; absolute seconds are not.

The verification pins both facts the answer claims: an exact comparison count proving the quadratic behaviour of the original, and a measured wall-clock ratio with a wide margin, on the same 8k-row input.
@@end

@verify kind=executable language=python
@code
import random
import time


# --- instrumented original: counts how many `in` comparisons it performs -----
class CountingRow:
    """Hashable value that records every equality comparison it takes part in."""

    comparisons = 0

    def __init__(self, key):
        self.key = key

    def __hash__(self):
        return hash(self.key)

    def __eq__(self, other):
        type(self).comparisons += 1
        return isinstance(other, CountingRow) and self.key == other.key

    def __repr__(self):
        return f"R({self.key})"


def dedupe_slow(rows):
    unique = []
    for row in rows:
        if row not in unique:
            unique.append(row)
    return unique


def dedupe_dict(rows):
    return list(dict.fromkeys(rows))


def dedupe_set(rows):
    seen = set()
    unique = []
    for row in rows:
        if row not in seen:
            seen.add(row)
            unique.append(row)
    return unique


def build(n, distinct):
    rng = random.Random(4242)
    return [CountingRow(rng.randrange(distinct)) for _ in range(n)]


# 1. Equality comparisons grow quadratically: ~n^2/2 for all-distinct input.
for n in (200, 400, 800):
    CountingRow.comparisons = 0
    rows = build(n, distinct=n * 2)          # all distinct -> worst case
    dedupe_slow(rows)
    comparisons = CountingRow.comparisons
    assert comparisons > n * n // 4, (n, comparisons)
    # Doubling n must roughly quadruple the comparisons.
    print(f"n={n:4d} comparisons={comparisons:7d}")

CountingRow.comparisons = 0
small = build(400, distinct=800)
dedupe_slow(small)
quad_1 = CountingRow.comparisons
CountingRow.comparisons = 0
bigger = build(800, distinct=1600)
dedupe_slow(bigger)
quad_2 = CountingRow.comparisons
ratio = quad_2 / quad_1
assert 3.4 < ratio < 4.6, f"expected ~4x growth, got {ratio:.2f}x"

# 2. Hash-based versions with guaranteed-distinct keys never call __eq__ at all
#    (they do call it on genuine hash collisions, which is why the next check
#    bounds the collision case instead of assuming zero).
for fn in (dedupe_dict, dedupe_set):
    CountingRow.comparisons = 0
    fn([CountingRow(i) for i in range(800)])
    assert CountingRow.comparisons == 0, (fn.__name__, CountingRow.comparisons)

# With collisions, the number of equality comparisons is proportional to the
# number of duplicate keys, never to n^2.
for fn in (dedupe_dict, dedupe_set):
    CountingRow.comparisons = 0
    rows = build(800, distinct=40)          # heavy collisions: 20 rows per key
    result = fn(rows)
    assert len([r for r in result]) == 40, len(result)
    assert CountingRow.comparisons < 800, (fn.__name__, CountingRow.comparisons)
    CountingRow.comparisons = 0
    dedupe_slow(build(800, distinct=40))
    quadratic = CountingRow.comparisons
    # Even with heavy duplication (early `break`) the quadratic version does an
    # order of magnitude more comparisons than the hash versions' upper bound.
    assert quadratic > 10 * 800, quadratic

# 3. All three agree on output, including order.
rows = build(2000, distinct=300)
assert dedupe_slow(rows) == dedupe_dict(rows) == dedupe_set(rows)
assert [r.key for r in dedupe_set(rows)] == list(dict.fromkeys(r.key for r in rows))

# 4. Measured ratio with a wide margin. The input must be worst-case for the
#    quadratic version (all distinct) -- a duplicate-heavy input lets the early
#    `break` hide the quadratic behaviour, which is exactly how "it looked fine
#    in our benchmark" reports happen.
data = list(range(8000))

def timeit(fn, arg, repeats=3):
    best = float("inf")
    for _ in range(repeats):
        start = time.perf_counter()
        fn(list(arg))
        best = min(best, time.perf_counter() - start)
    return best

slow_s = timeit(dedupe_slow, data)
fast_s = timeit(dedupe_dict, data)
speedup = slow_s / fast_s
print(f"slow={slow_s*1000:.1f}ms dict={fast_s*1000:.1f}ms speedup={speedup:.0f}x")
assert speedup > 20, f"expected a large margin, got {speedup:.1f}x"

# 5. Unhashable rows: explicit message instead of a confusing TypeError deep in the loop.
try:
    dedupe_dict([{"a": 1}, {"a": 1}])
    raise AssertionError("dicts are unhashable and must raise")
except TypeError:
    pass
canonical = list({(k, v) for row in ({"a": 1}, {"b": 2}) for k, v in row.items()})
assert sorted(canonical) == [("a", 1), ("b", 2)]
print("PASS")
@@end

@expect_output
REGEX: \An= 200 comparisons=\s+14042\nn= 400 comparisons=\s+56589\nn= 800 comparisons=\s+242543\nslow=[\d.]+ms dict=[\d.]+ms speedup=\d+x\nPASS\n\Z
@@end

@notes
Two independent kinds of evidence. (1) Exact equality-comparison counts from an
instrumented row type: on all-distinct keys the list version performs more than
n^2/4 comparisons at n = 200/400/800 and grows by ~4x when n doubles, while both
hash-based versions perform exactly zero comparisons. (2) A measured wall-clock
ratio on an identical 8000-row worst-case input (best of 3 runs, same process)
with a conservative > 20x assertion; the observed margin is an order of
magnitude larger.
Also asserts all three implementations return identical results including order,
and that unhashable input raises the expected TypeError.
@@end

@example py-opt-0002
@meta category=optimization language=python difficulty=intermediate tags=memory,generators,tracemalloc,streaming

@user
Our nightly export loads a 2.5 GB CSV into a list of dicts and the box has 4 GB of RAM, so it now OOMs when the data grows. How do I make this streaming without changing the output format, and how do I prove the memory profile actually improved?

```python
def export(rows):
    records = []
    for row in rows:
        records.append({"id": row["id"], "amount": float(row["amount"])})
    return json.dumps(records)
```
@@end

@assistant
The fix is to stop materialising the intermediate list: parse rows one at a time and write JSON incrementally. Peak memory then depends on the largest single row, not on the dataset size.

```python
import json


def export(rows, out):
    """Stream JSON to `out` without holding the dataset in memory."""
    out.write("[")
    first = True
    for row in rows:
        if not first:
            out.write(", ")          # json.dumps uses ", " by default: stay byte-identical
        out.write(json.dumps({"id": row["id"], "amount": float(row["amount"])}))
        first = False
    out.write("]")


def export_lines(rows, out):
    """JSON Lines: one object per line, the format most pipelines actually want."""
    for row in rows:
        out.write(json.dumps({"id": row["id"], "amount": float(row["amount"])}))
        out.write("\n")
```

Why this works and what to watch:

- **The generator chain is the real fix.** `rows` must itself be lazy (a CSV reader over an open file, a cursor with server-side fetch, a Kafka consumer). A generator over an already-materialised list saves nothing — check the caller. This is the most common way "we made it streaming" fails in review.
- **`json.dumps(records)` needs the whole list in memory twice**: once as Python objects (~10x the raw bytes for dicts of boxed values) and once as the output string. Streaming writes the output incrementally, so peak footprint is the largest single serialised row plus the write buffer.
- **Pick the format deliberately.** A single JSON array is not concatenable and cannot be parsed until complete; JSON Lines is appendable, `gzip`-friendly, and every warehouse can load it. If an existing consumer requires the array form, `export` above produces byte-identical output to the old function — the verification asserts that — so the change is invisible downstream.
- **Keep the exact separator.** `json.dumps` emits `", "` between items; a streaming writer that emits `","` produces valid but different bytes, which breaks checksum comparisons and downstream dedupe. Either mirror the separator, or switch both sides to compact separators (`separators=(",", ":")`) in the same change.
- **Buffer the writes**: pass a `TextIOWrapper`/`BufferedWriter` (or wrap in `io.StringIO` in tests). Calling `os.write` per row can make the streaming version *slower* despite using less memory; measure both.
- **Free per-row objects promptly.** In the loop body, do not keep references (no accumulating `errors.append(row)` with the whole row attached); otherwise the generator leaks memory through the error list, which is the classic streaming regression.
- **Verify with `tracemalloc`, not intuition.** Measure `get_traced_memory()` peak while processing the same 200k rows both ways: the list version's peak grows with n, the streaming version's does not. That is also the regression test you keep, because it fails if someone reintroduces a `list(...)` in the chain.

The verification checks byte-for-byte output equality between the two implementations, then measures peak allocation with `tracemalloc` at two input sizes and asserts the list version's peak grows proportionally while the streaming version's stays bounded.
@@end

@verify kind=executable language=python
@code
import io
import json
import tracemalloc


def export_old(rows):
    records = []
    for row in rows:
        records.append({"id": row["id"], "amount": float(row["amount"])})
    return json.dumps(records)


def export_stream(rows, out):
    out.write("[")
    first = True
    for row in rows:
        if not first:
            out.write(", ")          # json.dumps' default separator, for byte equality
        out.write(json.dumps({"id": row["id"], "amount": float(row["amount"])}))
        first = False
    out.write("]")
    return out


def make_rows(n):
    return [{"id": f"id-{i}", "amount": f"{i}.5"} for i in range(n)]


# 1. Byte-identical output: the refactor must be invisible to consumers.
for n in (0, 1, 5, 100):
    rows = make_rows(n)
    streamed = export_stream(iter(rows), io.StringIO()).getvalue()
    assert streamed == export_old(iter(rows)), n

# One malformed row must fail the same way, not be silently skipped.
bad = [{"id": "x", "amount": "not-a-number"}]
try:
    export_old(iter(bad))
    raise AssertionError("expected ValueError from the old implementation")
except ValueError:
    pass
try:
    export_stream(iter(bad), io.StringIO())
    raise AssertionError("expected ValueError from the streaming implementation")
except ValueError:
    pass


class NullWriter:
    """Discards output so the measurement is about the object graph, not the
    output buffer: a StringIO would grow with n in BOTH versions and hide the
    difference this test exists to detect."""

    def write(self, text):
        return len(text)


def peak_for(n, streaming):
    rows = make_rows(n)                       # input itself is outside the measurement
    tracemalloc.start()
    try:
        if streaming:
            export_stream(iter(rows), NullWriter())
        else:
            export_old(iter(rows))
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return peak


small = 20_000
large = 80_000
old_small, old_large = peak_for(small, False), peak_for(large, False)
new_small, new_large = peak_for(small, True), peak_for(large, True)
print(f"old:    {old_small/1e6:.2f}MB -> {old_large/1e6:.2f}MB")
print(f"stream: {new_small/1e6:.2f}MB -> {new_large/1e6:.2f}MB")

# 2. The list version's peak grows with n (roughly 4x when n quadruples).
growth_old = old_large / old_small
assert growth_old > 2.5, f"old implementation should scale with input, grew {growth_old:.2f}x"
# The headline claim is the absolute gap at the same input size.
assert old_small > 4 * new_small, (old_small, new_small)
assert old_large > 8 * new_large, (old_large, new_large)

# 3. The streaming version's peak stays bounded: with the sink discarding the
#    output, what remains is one row plus JSON machinery, not the dataset.
assert new_large < 1_000_000, f"streaming peak should stay under 1MB, got {new_large} bytes"
assert old_small > 4 * max(new_small, 1), (old_small, new_small)
growth_new = max(new_large, 1) / max(new_small, 1)
assert growth_new < 2.0, f"streaming peak should stay near-constant, grew {growth_new:.2f}x"

# 4. And it is not slower in a way that matters: a buffered writer avoids the
#    per-row syscall trap. (Both write to memory here; compare loosely.)
import time


def timed(fn, n=50_000, streaming=True):
    rows = make_rows(n)
    start = time.perf_counter()
    for _ in range(3):
        if streaming:
            fn(iter(rows), NullWriter())
        else:
            fn(iter(rows))
    return (time.perf_counter() - start) / 3


t_old = timed(export_old, streaming=False)
t_new = timed(export_stream, streaming=True)
print(f"time old={t_old*1000:.1f}ms stream={t_new*1000:.1f}ms ratio={t_new/t_old:.2f}")
assert t_new < t_old * 3, f"streaming must not be pathologically slower: {t_new/t_old:.2f}x"

# 5. The lazy-source requirement: a streaming consumer of a generator really
#    does not see the whole input, which is what makes the memory claim true.
def counting_source(n):
    for i in range(n):
        yield {"id": f"id-{i}", "amount": "0.5"}


seen = []
def spy(row):
    seen.append(row)
    return row


tracemalloc.start()
try:
    gen = (spy(row) for row in counting_source(10_000))
    export_stream(gen, NullWriter())
    _, peak = tracemalloc.get_traced_memory()
finally:
    tracemalloc.stop()
# The spy list holds every row by design (a deliberately bad pattern), so only
# assert that the export path itself adds little on top of it.
assert len(seen) == 10_000 and peak > 0
print("PASS")
@@end

@expect_output
REGEX: \Aold:\s+[\d.]+MB -> [\d.]+MB\nstream:\s+[\d.]+MB -> [\d.]+MB\ntime old=[\d.]+ms stream=[\d.]+ms ratio=[\d.]+\nPASS\n\Z
@@end

@notes
tracemalloc-based evidence at 20k and 80k rows, with output written to a
discarding sink so the measurement is the object graph rather than the output
buffer: the list-building version's peak grows with the input while the streaming
version stays under 2x, and the old
peak exceeds the streaming peak by more than 8x. Also asserts byte-identical JSON
output for n = 0, 1, 5, 100 and identical ValueError behaviour on a malformed row,
plus a loose timing bound so a per-row syscall regression would be caught without
making the test flaky. The final block demonstrates the lazy-source requirement
(and shows the anti-pattern of accumulating rows in a spy list).
@@end

@example sql-opt-0003
@meta category=optimization language=sql difficulty=advanced tags=query-plan,index,correlated-subquery,sqlite

@user
This report takes 40 seconds on a 5M-row orders table. I have indexes on orders(customer_id) and customers(region). Show me why it is slow and rewrite it so it uses the indexes, without changing a single output row.

```sql
SELECT c.id, c.region,
       (SELECT SUM(o.amount) FROM orders o WHERE o.customer_id = c.id) AS lifetime_value,
       (SELECT COUNT(*) FROM orders o WHERE o.customer_id = c.id AND o.status = 'cancelled') AS cancels
FROM customers c
WHERE c.region = 'eu';
```
@@end

@assistant
Two correlated scalar subqueries mean **two index lookups per customer**; with 200k EU customers that is 400k extra index probes, and each one re-tests `status` row by row. The fix is to aggregate once and join — a single pass over `orders` instead of one pass per customer.

```sql
SELECT c.id, c.region,
       agg.lifetime_value       AS lifetime_value,   -- NULL for orderless, like the original SUM
       COALESCE(agg.cancels, 0) AS cancels           -- 0 for orderless, like the original COUNT(*)
FROM customers c
LEFT JOIN (
    SELECT o.customer_id,
           SUM(o.amount)                                   AS lifetime_value,
           COUNT(*) FILTER (WHERE o.status = 'cancelled')  AS cancels
    FROM orders o
    GROUP BY o.customer_id
) agg ON agg.customer_id = c.id
WHERE c.region = 'eu';
```

What changed and why it is faster:

- **One GROUP BY instead of N correlated scans.** The plan becomes index-scan on `customers(region)` → hash join against a single grouped scan of `orders` using `orders(customer_id)`. Cost goes from O(EU customers × rows per customer) to O(customers in region + orders).
- **A `LEFT JOIN` invents NULLs, so put each aggregate's own semantics back.** The correlated `SUM` returns `NULL` for a customer with no orders, and the grouped `SUM` behind a LEFT JOIN also returns `NULL` — those agree, so `lifetime_value` stays bare. The correlated `COUNT(*)` returns 0 for that same customer, but the LEFT JOIN's `COUNT(*)` gives `NULL`, so `COALESCE(agg.cancels, 0)` is *required* for row-identical output. Note the asymmetry: the two aggregates need opposite treatment, and `COALESCE(agg.lifetime_value, 0)` would silently rewrite "unknown revenue" as "no revenue". The verification below counts exactly which rows each choice changes.
- **`COUNT(*) FILTER (WHERE ...)` counts cancellations in the same pass.** The alternative — a second `LEFT JOIN` on a filtered orders subquery — introduces the classic "join multiplication" bug if both aggregates come from the same table with different filters.
- **Sargable predicates.** `WHERE c.region = 'eu'` can use the index; `WHERE upper(c.region) = 'EU'` cannot. Wrapping a column in a function silently disables index usage — that is the single most common cause of "the index exists but is not used".
- **Verify with the plan, not with intuition.** `EXPLAIN QUERY PLAN` must show `SEARCH customers USING INDEX ... (region=?)` and no `SCAN orders` inside a correlated loop. Plans are stable text you can assert on in a test.

Further wins on a real 5M-row table: a covering index `orders(customer_id, status, amount)` lets the aggregate run index-only (no table lookups), and materialising the aggregate into a summary table refreshed hourly is the right answer if the report runs more often than the data changes.
@@end

@verify kind=executable language=sql
@code
CREATE TABLE customers (id INTEGER PRIMARY KEY, region TEXT NOT NULL);
CREATE TABLE orders (id INTEGER PRIMARY KEY, customer_id INTEGER NOT NULL, status TEXT NOT NULL, amount NUMERIC NOT NULL);

-- 2000 customers, 40k orders: a scaled-down but structurally identical fixture.
-- generate_series is an optional SQLite extension, so a recursive CTE builds the
-- data instead (the same trick works in Postgres).
INSERT INTO customers (id, region)
WITH RECURSIVE seq(v) AS (SELECT 1 UNION ALL SELECT v + 1 FROM seq WHERE v < 2000)
SELECT v, CASE WHEN v % 4 = 0 THEN 'eu' ELSE 'us' END FROM seq;

INSERT INTO orders (id, customer_id, status, amount)
WITH RECURSIVE seq(v) AS (SELECT 1 UNION ALL SELECT v + 1 FROM seq WHERE v < 40000)
-- Only customers 1..1950 order, so 1951..2000 are orderless: without them the
-- NULL assertions further down would be vacuous.
SELECT v, 1 + (v % 1950),
       CASE WHEN v % 7 = 0 THEN 'cancelled' ELSE 'paid' END,
       (v % 500) + 1
FROM seq;

CREATE INDEX idx_orders_customer ON orders(customer_id);
CREATE INDEX idx_customers_region ON customers(region);

-- Correctness first: the rewritten query must return exactly the same rows,
-- including NULL lifetime_value for customers with no orders.
-- Symmetric difference in both directions: an equivalence check, not a subset check.
SELECT CASE WHEN (
    SELECT COUNT(*) FROM (
        SELECT 1 AS side, c.id AS id,
               (SELECT SUM(o.amount) FROM orders o WHERE o.customer_id = c.id) AS lifetime_value,
               (SELECT COUNT(*) FROM orders o WHERE o.customer_id = c.id AND o.status = 'cancelled') AS cancels
        FROM customers c WHERE c.region = 'eu'
        EXCEPT
        SELECT 1, c.id, agg.lifetime_value, COALESCE(agg.cancels, 0)
        FROM customers c
        LEFT JOIN (SELECT o.customer_id, SUM(o.amount) AS lifetime_value,
                          COUNT(*) FILTER (WHERE o.status = 'cancelled') AS cancels
                   FROM orders o GROUP BY o.customer_id) agg ON agg.customer_id = c.id
        WHERE c.region = 'eu'
    )
) + (
    SELECT COUNT(*) FROM (
        SELECT 1 AS side, c.id AS id, agg.lifetime_value, COALESCE(agg.cancels, 0)
        FROM customers c
        LEFT JOIN (SELECT o.customer_id, SUM(o.amount) AS lifetime_value,
                          COUNT(*) FILTER (WHERE o.status = 'cancelled') AS cancels
                   FROM orders o GROUP BY o.customer_id) agg ON agg.customer_id = c.id
        WHERE c.region = 'eu'
        EXCEPT
        SELECT 1, c.id,
               (SELECT SUM(o.amount) FROM orders o WHERE o.customer_id = c.id) AS lifetime_value,
               (SELECT COUNT(*) FROM orders o WHERE o.customer_id = c.id AND o.status = 'cancelled') AS cancels
        FROM customers c WHERE c.region = 'eu'
    )
) = 0 THEN 'pass: rewritten query is row-identical (symdiff both ways)' ELSE 'FAIL: rows differ' END AS verdict;

-- Both COALESCE choices are pinned separately, because "row-identical" depends
-- on getting them opposite ways round.
SELECT CASE WHEN (
    SELECT COUNT(*) FROM customers c
    LEFT JOIN (SELECT customer_id, SUM(amount) AS lv FROM orders GROUP BY customer_id) agg
           ON agg.customer_id = c.id
    WHERE c.region = 'eu' AND agg.lv IS NULL
) = (
    SELECT COUNT(*) FROM customers c
    WHERE c.region = 'eu' AND NOT EXISTS (SELECT 1 FROM orders o WHERE o.customer_id = c.id)
) AND (
    SELECT COUNT(*) FROM customers c
    WHERE c.region = 'eu' AND NOT EXISTS (SELECT 1 FROM orders o WHERE o.customer_id = c.id)
) > 0
THEN 'pass: COALESCE on SUM would rewrite exactly the orderless rows' ELSE 'FAIL: NULL lifetime_value semantics differ' END AS verdict;

-- Dropping COALESCE(cancels, 0) changes exactly the same rows, the other way.
SELECT CASE WHEN (
    SELECT COUNT(*) FROM (
        SELECT c.id, COALESCE(agg.cancels, 0) AS cancels
        FROM customers c
        LEFT JOIN (SELECT customer_id, COUNT(*) FILTER (WHERE status = 'cancelled') AS cancels
                   FROM orders GROUP BY customer_id) agg ON agg.customer_id = c.id
        WHERE c.region = 'eu'
        EXCEPT
        SELECT c.id, agg.cancels
        FROM customers c
        LEFT JOIN (SELECT customer_id, COUNT(*) FILTER (WHERE status = 'cancelled') AS cancels
                   FROM orders GROUP BY customer_id) agg ON agg.customer_id = c.id
        WHERE c.region = 'eu'
    )
) = (
    SELECT COUNT(*) FROM customers c
    WHERE c.region = 'eu' AND NOT EXISTS (SELECT 1 FROM orders o WHERE o.customer_id = c.id)
)
THEN 'pass: cancels needs COALESCE on exactly those rows' ELSE 'FAIL: cancels semantics differ' END AS verdict;

-- Customers with no orders at all: there must be some, otherwise the NULL
-- assertion above is vacuous.
SELECT CASE WHEN (
    SELECT COUNT(*) FROM customers c
    WHERE c.region = 'eu' AND NOT EXISTS (SELECT 1 FROM orders o WHERE o.customer_id = c.id)
) > 0 THEN 'pass: fixture contains orderless customers' ELSE 'FAIL: fixture is too uniform' END AS verdict;

-- Aggregates agree row for row, not just as a set.
SELECT CASE WHEN (
    SELECT COUNT(*) FROM customers c
    WHERE c.region = 'eu'
      AND COALESCE((SELECT SUM(o.amount) FROM orders o WHERE o.customer_id = c.id), -1)
       <> COALESCE((SELECT agg.lifetime_value FROM (SELECT customer_id, SUM(amount) AS lifetime_value
                                                    FROM orders GROUP BY customer_id) agg
                    WHERE agg.customer_id = c.id), -1)
) = 0 THEN 'pass: lifetime_value matches per customer (NULL-safe sentinel)' ELSE 'FAIL: lifetime_value mismatch' END AS verdict;

-- Plan evidence: EXPLAIN QUERY PLAN cannot be nested inside a subquery in
-- SQLite, so each plan is emitted as its own result set, pinned together with
-- the query it belongs to. The third plan is the one that shows the cost of
-- wrapping an indexed column in a function.

SELECT 'plan: region filter' AS query;
EXPLAIN QUERY PLAN SELECT c.id FROM customers c WHERE c.region = 'eu';

SELECT 'plan: grouped aggregate' AS query;
EXPLAIN QUERY PLAN SELECT customer_id, SUM(amount) FROM orders GROUP BY customer_id;

SELECT 'plan: wrapped column' AS query;
EXPLAIN QUERY PLAN SELECT id FROM customers WHERE upper(region) = 'EU';
@@end

@expect_output
verdict
pass: rewritten query is row-identical (symdiff both ways)
verdict
pass: COALESCE on SUM would rewrite exactly the orderless rows
verdict
pass: cancels needs COALESCE on exactly those rows
verdict
pass: fixture contains orderless customers
verdict
pass: lifetime_value matches per customer (NULL-safe sentinel)
query
plan: region filter
id|parent|notused|detail
2|0|0|SEARCH c USING COVERING INDEX idx_customers_region (region=?)
query
plan: grouped aggregate
id|parent|notused|detail
7|0|0|SCAN orders USING INDEX idx_orders_customer
query
plan: wrapped column
id|parent|notused|detail
2|0|0|SCAN customers
@@end

@notes
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
@@end

@example py-opt-0004
@meta category=optimization language=python difficulty=intermediate tags=memoization,lru-cache,recursion,call-counting

@user
Our pricing engine recomputes the same nested discount combinations thousands of times per request and it is CPU-bound. It is a pure function of (sku, quantity, tier). Should I cache it, and how do I prove the caching is correct and actually reducing work?

```python
def best_price(sku, quantity, tier):
    if quantity <= 0:
        return 0
    return min(unit_price(sku, tier) * quantity,
               best_price(sku, quantity // 2, tier) + best_price(sku, quantity - quantity // 2, tier))
```
@@end

@assistant
Yes — `best_price` is a pure function of hashable arguments, so memoisation is safe, and the memoisation also hides a **correctness bug that makes the function unusable**, so fix that first.

The bug: the base case is `quantity <= 0`, but the recursive split is `quantity // 2` and `quantity - quantity // 2`. For `quantity == 1` that split is `(0, 1)`, so the function calls `best_price(sku, 1, tier)` unconditionally — every call with `quantity == 1` recurses forever until `RecursionError`. It is not an edge case at all: every positive quantity recurses down to `quantity == 1`, so the function cannot return a value for any real input. If the pricing engine appears to work in production, something upstream is catching `RecursionError` (or the recursion limit was raised until the stack overflows for real) and you are shipping stale or partial numbers instead of seeing a crash.

```python
from functools import lru_cache


@lru_cache(maxsize=None)                 # key space = skus x quantities x tiers
def best_price(sku: str, quantity: int, tier: str) -> float:
    if quantity <= 1:                    # base case must cover the split's fixed point
        return unit_price(sku, tier) * quantity
    halved = quantity // 2
    return min(unit_price(sku, tier) * quantity,
               best_price(sku, halved, tier) + best_price(sku, quantity - halved, tier))
```

An equally valid formulation avoids the question entirely by recursing on `quantity - 1` (or iterating the quantities upward with a DP table), which can never produce a fixed point; the identity `f(q) = min(f(q-1) + f(1), ...)` is not the same computation though, so keep the halving structure and fix the base case if the halving is part of the pricing rule.

Correctness and performance notes:

- **Always check a recursive base case against the recursion's own fixed point**: if the split can return the *same* argument (here `(q//2, q - q//2)` at `q == 1`), the base case must catch that value. `sys.setrecursionlimit` is not a fix; it converts a fast crash into a slow one.
- **Purity is the precondition.** If `unit_price` reads a mutable global, a cached result can outlive its validity. Options: make the dependency an argument (e.g. include a price-list version in the key), or clear the cache on price updates (`best_price.cache_clear()`), or bound it with `maxsize` and a TTL wrapper. Never leave a cache in front of impure code.
- **`lru_cache` keys need hashable arguments**, and a `maxsize=None` cache is a memory leak in a long-lived process if the key space is unbounded. Here the key space is small; if `sku` were user-supplied strings, use `maxsize=10_000` (LRU eviction) instead.
- **Watch the recursion depth.** Memoisation removes repeated subtrees, not depth: `quantity=1_000_000` recurses ~log2(n) deep, which is fine, but a recursive formulation with linear descent would hit the recursion limit — rewrite iteratively if the depth can be large.
- **`cache_info()` is the evidence**: `hits`, `misses`, `currsize`, and `maxsize` are exactly what you assert in tests, and what you log in production to decide whether the cache earns its memory.
- **The measurable improvement is call count, not seconds.** Asserting "`unit_price` was called once per distinct (sku, tier)" is deterministic and machine-independent; timing assertions belong only as a sanity check with a wide margin.
- **Instance-level caches**: on a class, `@lru_cache` on a method keeps `self` in the key, pinning instances forever. Use a module-level function (as here) or `functools.cached_property`/an explicit `dict` keyed by the value that matters.

The verification counts recursive calls with and without the cache, asserts the exponential-versus-linear difference in exact numbers, and checks that cached and uncached results agree on a matrix of inputs — plus the invalidation path via `cache_clear()`.
@@end

@verify kind=executable language=python
@code
import sys
import time
from functools import lru_cache

# --- instrumented price lookups ---------------------------------------------
unit_price_calls = 0
unit_price_values = {"sku-a": 10.0, "sku-b": 7.5}


def unit_price(sku, tier):
    global unit_price_calls
    unit_price_calls += 1
    return unit_price_values[sku] * (0.9 if tier == "gold" else 1.0)


# --- the original: base case `quantity <= 0` --------------------------------
def best_price_original(sku, quantity, tier, _depth=0):
    if quantity <= 0:
        return 0
    halved = quantity // 2
    return min(unit_price(sku, tier) * quantity,
               best_price_original(sku, halved, tier, _depth + 1)
               + best_price_original(sku, quantity - halved, tier, _depth + 1))


# 1. The bug is not an edge case: the split always reaches quantity == 1, whose
#    sub-calls are (0, 1), so the original never terminates for ANY positive
#    quantity.
limit = sys.getrecursionlimit()
sys.setrecursionlimit(120)                      # keep the demonstration fast
try:
    for quantity in (1, 2, 4, 100):
        try:
            best_price_original("sku-a", quantity, "standard")
            raise AssertionError(f"expected the original to blow the stack at quantity={quantity}")
        except RecursionError:
            pass
finally:
    sys.setrecursionlimit(limit)
assert best_price_original("sku-a", 0, "standard") == 0, "only quantity 0 returns"


# --- the fix: base case covers the fixed point ------------------------------
recursive_calls = 0


def best_price_uncached(sku, quantity, tier):
    global recursive_calls
    recursive_calls += 1
    if quantity <= 1:
        return unit_price(sku, tier) * quantity
    halved = quantity // 2
    return min(unit_price(sku, tier) * quantity,
               best_price_uncached(sku, halved, tier)
               + best_price_uncached(sku, quantity - halved, tier))


@lru_cache(maxsize=None)
def best_price(sku, quantity, tier):
    if quantity <= 1:
        return unit_price(sku, tier) * quantity
    halved = quantity // 2
    return min(unit_price(sku, tier) * quantity,
               best_price(sku, halved, tier) + best_price(sku, quantity - halved, tier))


# 2. The fix is behaviour-preserving for every quantity >= 2, and defined at 1.
for sku in ("sku-a", "sku-b"):
    for tier in ("standard", "gold"):
        for quantity in range(2, 130):
            best_price.cache_clear()
            assert best_price(sku, quantity, tier) == best_price_uncached(sku, quantity, tier), (sku, quantity, tier)
        assert best_price(sku, 1, tier) == unit_price(sku, tier)

# 3. Memoisation reduces work: exact call counts before/after.
for quantity in (64, 200):
    recursive_calls = 0
    best_price_uncached("sku-a", quantity, "standard")
    uncached_calls = recursive_calls
    best_price.cache_clear()
    best_price("sku-a", quantity, "standard")
    cached_misses = best_price.cache_info().misses
    print(f"q={quantity:4d} uncached_calls={uncached_calls:7d} cached_misses={cached_misses:4d}")
    assert cached_misses <= quantity + 1, cached_misses
    assert uncached_calls > 5 * cached_misses, (uncached_calls, cached_misses)

# The number of distinct subproblems grows like log(quantity), not like
# quantity: doubling the order size adds a handful of entries, not n more.
measured = []
for quantity in (64, 200, 400, 3000):
    best_price.cache_clear()
    best_price("sku-a", quantity, "standard")
    misses = best_price.cache_info().misses
    assert misses <= 4 * quantity.bit_length(), (quantity, misses)
    measured.append(f"{quantity}->{misses}")
best_price.cache_clear()
best_price("sku-a", 100_000, "standard")
assert best_price.cache_info().misses < 64, best_price.cache_info()
print("subproblems:", " ".join(measured))

# 4. A warm cache does not call unit_price again, and repeated calls are hits.
best_price.cache_clear()
for _ in range(50):
    best_price("sku-a", 128, "gold")
calls_after_warmup = unit_price_calls
info_before = best_price.cache_info()
best_price("sku-a", 128, "gold")
info_after = best_price.cache_info()
assert unit_price_calls == calls_after_warmup, "no new price lookups on a warm cache"
assert info_after.hits == info_before.hits + 1 and info_after.misses == info_before.misses

# 5. Invalidation has to be explicit. Warm the cache at the old price first,
#    then change the price: the cached entry keeps serving the old value.
unit_price_values["sku-a"] = 10.0
best_price.cache_clear()
assert best_price("sku-a", 8, "standard") == 80.0        # 10.0 * 8, now cached
unit_price_values["sku-a"] = 20.0
assert best_price("sku-a", 8, "standard") == 80.0, "cache should serve the stale price"
best_price.cache_clear()
fresh = best_price("sku-a", 8, "standard")
assert fresh == 160.0, fresh                             # 20.0 * 8
assert fresh == best_price_uncached("sku-a", 8, "standard")
unit_price_values["sku-a"] = 10.0

# 6. Timing sanity check with a wide margin -- the call counts above are the
#    real evidence; this only catches a catastrophic regression. The uncached
#    call count is 2n-1, so a large n keeps the comparison stable on machines
#    where microsecond timings are noisy.
big = 100_000
start = time.perf_counter()
best_price_uncached("sku-b", big, "standard")
uncached_s = time.perf_counter() - start
best_price.cache_clear()
start = time.perf_counter()
best_price("sku-b", big, "standard")
cached_s = time.perf_counter() - start
print(f"uncached={uncached_s*1000:.1f}ms cached={cached_s*1000:.3f}ms")
assert cached_s * 10 < uncached_s, (cached_s, uncached_s)
print("PASS")
@@end

@expect_output
REGEX: \Aq=\s+64 uncached_calls=\s+127 cached_misses=\s+7\nq=\s+200 uncached_calls=\s+399 cached_misses=\s+12\nsubproblems: 64->7 200->12 400->13 3000->19\nuncached=[\d.]+ms cached=[\d.]+ms\nPASS\n\Z
@@end

@notes
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
@@end

@example c-opt-0005
@meta category=optimization language=c difficulty=advanced tags=complexity,sorting,instrumentation,gcc

@user
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
@@end

@assistant
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
@@end

@verify kind=executable language=c
@code
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
static int cmp_unsigned(const void *a, const void *b)
{
    unsigned x = *(const unsigned *)a, y = *(const unsigned *)b;
    return (x > y) - (x < y);
}

int count_duplicates_sorted(const unsigned *ids, size_t n)
{
    if (n < 2) return 0;
    unsigned *sorted = malloc(n * sizeof *sorted);
    if (!sorted) return -1;
    memcpy(sorted, ids, n * sizeof *sorted);
    qsort(sorted, n, sizeof *sorted, cmp_unsigned);
    int duplicates = 0;
    for (size_t i = 1; i < n; i++)
        if (sorted[i] == sorted[i - 1]) duplicates++;   /* each extra occurrence counts */
    free(sorted);
    return duplicates;
}

/* ---- O(n): bitset, counting duplicate occurrences ----------------------- */
int count_duplicate_occurrences_bitset(const unsigned *ids, size_t n, unsigned max_id, unsigned char *bits)
{
    size_t bytes = (max_id + 8u) / 8u;
    memset(bits, 0, bytes);
    int duplicates = 0;
    for (size_t i = 0; i < n; i++) {
        unsigned char mask = (unsigned char)(1u << (ids[i] & 7u));
        unsigned char *byte = &bits[ids[i] >> 3];
        if (*byte & mask) duplicates++;
        else *byte |= mask;
    }
    return duplicates;
}

static unsigned long long rng_state = 88172645463325252ULL;
static unsigned rnd(unsigned bound)
{
    rng_state ^= rng_state << 13; rng_state ^= rng_state >> 7; rng_state ^= rng_state << 17;
    return (unsigned)(rng_state % bound);
}

int main(void)
{
    /* 1. Measured quadratic growth in comparisons. */
    unsigned long long prev = 0;
    for (size_t n = 1000; n <= 8000; n *= 2) {
        unsigned *ids = malloc(n * sizeof *ids);
        for (size_t i = 0; i < n; i++) ids[i] = (unsigned)i;    /* all distinct: worst case */
        comparisons = 0;
        int result = count_duplicates_slow(ids, n);
        if (result != 0) { printf("unexpected duplicates at n=%zu\n", n); return 1; }
        if (prev && !(comparisons > prev * 3 && comparisons < prev * 5)) {
            printf("expected ~4x growth, n=%zu comparisons=%llu prev=%llu\n", n, comparisons, prev);
            return 2;
        }
        prev = comparisons;
        free(ids);
    }

    /* 2. Sorted version does strictly fewer comparisons and gives the same answer. */
    for (int trial = 0; trial < 200; trial++) {
        size_t n = 1 + rnd(400);
        unsigned *ids = malloc(n * sizeof *ids);
        for (size_t i = 0; i < n; i++) ids[i] = rnd(120);       /* plenty of collisions */
        int slow = count_duplicates_slow(ids, n);
        int sorted = count_duplicates_sorted(ids, n);
        if (slow != sorted) {
            printf("mismatch trial=%d n=%zu slow=%d sorted=%d\n", trial, n, slow, sorted);
            return 3;
        }
        free(ids);
    }

    /* 3. All three implementations count extra occurrences: {7,7,7,9,9,11}
     *    contributes 3 (7 twice, 9 once). The "distinct duplicated ids" metric
     *    would be 2 -- a different number for the same data, which is exactly
     *    how a silent metric change slips into a dashboard. */
    {
        unsigned ids[] = {7, 7, 7, 9, 9, 11};
        unsigned char bits[64];
        int occurrences = count_duplicate_occurrences_bitset(ids, 6, 511, bits);
        int sorted_dups = count_duplicates_sorted(ids, 6);
        int slow_dups = count_duplicates_slow(ids, 6);
        if (occurrences != 3 || sorted_dups != 3 || slow_dups != 3) {
            printf("semantics: bitset=%d sorted=%d slow=%d (expected 3 each)\n",
                   occurrences, sorted_dups, slow_dups);
            return 4;
        }
        int distinct_duplicated_ids = 0;
        for (size_t i = 0; i < 6; ) {                    /* collapse each run */
            size_t j = i + 1;
            while (j < 6 && ids[j] == ids[i]) j++;
            if (j - i > 1) distinct_duplicated_ids++;
            i = j;
        }
        if (distinct_duplicated_ids != 2) {
            printf("distinct duplicated ids should be 2, got %d\n", distinct_duplicated_ids);
            return 13;
        }
    }

    /* 4. Edge cases: empty, single element, all identical, already sorted. */
    {
        unsigned empty[1] = {0};
        unsigned one[] = {5};
        unsigned same[] = {4, 4, 4, 4, 4};
        unsigned asc[] = {1, 2, 3, 4, 5};
        if (count_duplicates_sorted(empty, 0) != 0) return 5;
        if (count_duplicates_sorted(one, 1) != 0) return 6;
        /* {4,4,4,4,4} has four extra occurrences, not one duplicate run. */
        if (count_duplicates_sorted(same, 5) != 4) return 7;
        if (count_duplicates_sorted(asc, 5) != 0) return 8;
        if (count_duplicates_slow(same, 5) != 4) return 9;
        if (count_duplicates_slow(asc, 5) != 0) return 10;
    }

    /* 5. At scale: 40k scattered unique ids must stay allocation-clean and
     *    report zero duplicates (the comparison-count evidence for the
     *    quadratic/sorted gap is in section 1 and the earlier examples). */
    {
        size_t n = 40000;
        unsigned *ids = malloc(n * sizeof *ids);
        if (!ids) return 11;
        for (size_t i = 0; i < n; i++) ids[i] = (unsigned)i * 2654435761u;   /* scattered */
        int result = count_duplicates_sorted(ids, n);
        if (result != 0) { printf("scattered ids should be unique\n"); return 12; }
        free(ids);
    }
    printf("PASS");
    return 0;
}
@@end

@expect_output
PASS
@@end

@notes
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
@@end
