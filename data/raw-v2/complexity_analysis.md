@example cplx-0001
@meta category=complexity_analysis language=python difficulty=intermediate tags=quadratic,membership,measurement,instrumentation

@user
This function is called with a few thousand items and takes minutes. The code reads like a single pass, and review signed it off as O(n):

```python
def new_items(candidates, known):
    return [item for item in candidates if item not in known]
```

`known` is a list built by an earlier stage. Is the review right? Show me how to *measure* the complexity rather than argue about it — we cannot add a profiler to production.
@@end

@assistant
The review counted the outer loop and missed the inner one: `item not in known` on a **list** is a linear scan (O(len(known)) equality comparisons) inside a loop over `candidates`, so the function is O(n·m) — quadratic when the two sizes are comparable. The list comprehension hides a nested loop; that is the whole trap. With 4000 candidates and 4000 known items that is up to 16 million comparisons, which is exactly the "minutes" behaviour.

Convert the membership side to a `set` (or `dict`) and the inner scan becomes an O(1) hash lookup, making the function O(n) plus the one-time O(m) build:

```python
def new_items(candidates, known):
    known_set = set(known)                       # O(m) once
    return [item for item in candidates if item not in known_set]   # O(n) lookups
```

When you cannot rebuild the collection (a streaming source, or `known` changing), keep a running set and update it as you go — the invariant is "the thing you query for membership is hashable and hashed".

**Measuring complexity without a profiler.** Count the operations you care about, not the wall clock: give the elements an `__eq__`/`__hash__` that increments a counter, run the function at three sizes, and compare growth. A quadratic shows up as a 4× increase per doubling of input; a linear one as 2×. That is a property of the algorithm, so it survives different machines, noisy CI and cold caches — and it can live in a test:

```python
class Probe:
    comparisons = 0

    def __init__(self, value):
        self.value = value

    def __eq__(self, other):
        Probe.comparisons += 1
        return self.value == other.value

    def __hash__(self):
        return hash(self.value)
```

Two rules for this technique: count only the operations the complexity claim depends on (comparisons here — including hashing in the set version), and pin the *ratio*, not the absolute count, when the counts depend on interpreter details. The verification below does both, and also shows why a range-based `for i in range(len(...))` reading of the code makes the nesting obvious: the comprehension is a loop body, so the "single pass" reading was never true.
@@end

@verify kind=executable language=python
@code
class Probe:
    """Counts the equality comparisons the algorithm performs."""

    comparisons = 0
    hashes = 0

    def __init__(self, value):
        self.value = value

    def __eq__(self, other):
        Probe.comparisons += 1
        return self.value == other.value

    def __hash__(self):
        Probe.hashes += 1
        return hash(self.value)

    def __repr__(self):
        return f"Probe({self.value})"


def new_items_list(candidates, known):
    """The reviewed version: `in` on a list, hidden inside a comprehension."""
    return [item for item in candidates if item not in known]


def new_items_set(candidates, known):
    known_set = set(known)
    return [item for item in candidates if item not in known_set]


def measure(func, size):
    candidates = [Probe(i) for i in range(size)]
    known = [Probe(i) for i in range(0, size, 2)]      # half overlap
    Probe.comparisons = 0
    Probe.hashes = 0
    result = func(candidates, known)
    return {
        "comparisons": Probe.comparisons,
        "hashes": Probe.hashes,
        "found": len(result),
    }


SIZES = (500, 1000, 2000)
list_runs = [measure(new_items_list, size) for size in SIZES]
set_runs = [measure(new_items_set, size) for size in SIZES]

# 1. the same function, three sizes: the call counts expose the inner loop
for size, run in zip(SIZES, list_runs):
    print(f"list membership n={size}: comparisons={run['comparisons']} found={run['found']}")
for size, run in zip(SIZES, set_runs):
    print(f"set membership  n={size}: comparisons={run['comparisons']} "
          f"hashes={run['hashes']} found={run['found']}")

# 2. the growth factor is the fingerprint: 4x per doubling is quadratic, 2x linear
list_ratios = [round(list_runs[i + 1]["comparisons"] / list_runs[i]["comparisons"], 2)
               for i in range(len(SIZES) - 1)]
set_ratios = [round(set_runs[i + 1]["comparisons"] / max(set_runs[i]["comparisons"], 1), 2)
              for i in range(len(SIZES) - 1)]
print("list comparison growth per doubling:", list_ratios)
print("set comparison growth per doubling:", set_ratios)

# 3. both versions agree on the answer: this is a performance defect, not a logic one
assert [item.value for item in new_items_list([Probe(i) for i in range(10)],
                                              [Probe(i) for i in range(0, 10, 2)])] == \
       [item.value for item in new_items_set([Probe(i) for i in range(10)],
                                             [Probe(i) for i in range(0, 10, 2)])] == \
       [1, 3, 5, 7, 9]
print("same result from both versions:", True)

# 4. the counting method is what makes the claim testable: pin the ratio, not the
#    absolute numbers, so the test survives interpreter changes
assert 3.8 < list_ratios[0] < 4.2, list_ratios
assert 3.8 < list_ratios[1] < 4.2, list_ratios
assert all(ratio <= 2.1 for ratio in set_ratios), set_ratios
assert list_runs[2]["comparisons"] > 1_000_000, list_runs[2]
assert set_runs[2]["comparisons"] < 5_000, set_runs[2]
assert set_runs[2]["hashes"] >= 2000, "the set path pays for hashing, and it is cheap"
assert list_ratios[1] / set_ratios[1] > 1.5, "quadratic versus linear, measured"
print("PASS")
@@end

@expect_output
list membership n=500: comparisons=93875 found=250
list membership n=1000: comparisons=375250 found=500
list membership n=2000: comparisons=1500500 found=1000
set membership  n=500: comparisons=250 hashes=750 found=250
set membership  n=1000: comparisons=500 hashes=1500 found=500
set membership  n=2000: comparisons=1000 hashes=3000 found=1000
list comparison growth per doubling: [4.0, 4.0]
set comparison growth per doubling: [2.0, 2.0]
same result from both versions: True
PASS
@@end

@notes
Measures both versions with an instrumented element type and pins the growth
signature rather than a wall-clock number: list membership comparison counts grow
close to 4× per doubling of input (quadratic — ~1.5 million comparisons at n=2000
against 1000 for the set version) while the set version stays at ~2× and performs only a few thousand equality
comparisons (it pays hashes instead — also counted, so the trade-off is visible). Both
versions are asserted to return identical results, which frames this as a performance
defect rather than a logic bug. The assertion pins the ratio band (3.8-4.2) so the
check is a property of the algorithm, not of the machine.
@@end

@example cplx-0002
@meta category=complexity_analysis language=javascript difficulty=advanced tags=sorting,comparators,schwartzian-transform,measurement

@user
Sorting our catalogue takes 40 seconds. The comparator does a little work (it normalises a name and falls back to a locale rule), and the code sorts once per request:

```javascript
const byDisplayName = (a, b) =>
  normalise(a.name).localeCompare(normalise(b.name), "en", { sensitivity: "base" });

catalogue.sort(byDisplayName);
```

Someone suggested "cache `normalise` results in a Map" as the fix. Is the comparator being called once per element, or more? Tell me how to measure it and what the right fix is.
@@end

@assistant
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
@@end

@verify kind=executable language=javascript
@code
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

// --- version 1: the comparator does the work ---------------------------------
normaliseCalls.count = 0;
let comparatorCalls = 0;
const sortedPlain = [...catalogue].sort((a, b) => {
  comparatorCalls += 1;
  return byDisplayName(a, b);
});
const plainNormaliseCalls = normaliseCalls.count;   // counted inside the comparator

// --- version 2: decorate, sort, undecorate -----------------------------------
normaliseCalls.count = 0;
let keyComparatorCalls = 0;
const decorated = catalogue.map((item) => ({ item, key: normalise(item.name) }));
const keysComputed = normaliseCalls.count;
decorated.sort((a, b) => {
  keyComparatorCalls += 1;
  return a.key.localeCompare(b.key, "en", { sensitivity: "base" });
});
const sortedDecorated = decorated.map((entry) => entry.item);

// --- measurement report ------------------------------------------------------
const n = catalogue.length;
console.log("n =", n, "| n*log2(n) =", Math.round(n * Math.log2(n)));
console.log("plain sort: comparator calls =", comparatorCalls,
            "| normalise calls =", plainNormaliseCalls);
console.log("decorate: keys computed =", keysComputed,
            "| key comparator calls =", keyComparatorCalls);

// every comparison normalises both operands in the plain version
const ratio = plainNormaliseCalls / keysComputed;
console.log("expensive calls: plain =", plainNormaliseCalls,
            "| decorate =", keysComputed, "| ratio =", ratio.toFixed(1));

// --- both versions sort identically -----------------------------------------
const ids = (items) => items.map((item) => item.id).join(",");
console.log("same order:", ids(sortedPlain) === ids(sortedDecorated));
const keyOf = (item) => normalise(item.name);
const isSorted = (items) => items.every((item, index) =>
  index === 0 || keyOf(items[index - 1]) <= keyOf(items[index]));
console.log("plain sorted:", isSorted(sortedPlain), "| decorate sorted:", isSorted(sortedDecorated));

function assert(condition, message) {
  if (!condition) throw new Error(message || "assertion failed");
}

assert(comparatorCalls > n, "the comparator is called more than once per element");
assert(comparatorCalls > n * Math.log2(n) * 0.8,
       `comparator calls should be on the order of n log n, got ${comparatorCalls}`);
assert(comparatorCalls < n * Math.log2(n) * 2.5, "and inside the sorting bound");
assert(keysComputed === n, `keys must be computed once per element, got ${keysComputed}`);
assert(ratio > 8, `the decorate version must remove most expensive calls, ratio ${ratio}`);
assert(ids(sortedPlain) === ids(sortedDecorated), "same ordering");
assert(isSorted(sortedPlain) && isSorted(sortedDecorated));
console.log("PASS");
@@end

@expect_output
n = 1000 | n*log2(n) = 9966
plain sort: comparator calls = 8632 | normalise calls = 17264
decorate: keys computed = 1000 | key comparator calls = 8632
expensive calls: plain = 17264 | decorate = 1000 | ratio = 17.3
same order: true
plain sorted: true | decorate sorted: true
PASS
@@end

@notes
Counts calls in both versions on a deterministic 1000-item catalogue and pins the
comparison: the plain comparator runs ~n log n times (each call normalising two names,
so ~2·n log n expensive calls), while decorate–sort–undecorate computes each key
exactly n times and then sorts precomputed keys — the ratio is asserted to exceed 8×.
Both versions are asserted to produce the identical order and to be correctly sorted
under the same key, so the optimisation is shown to be behaviour-preserving; the call
counts are deterministic for a fixed input, so no timing is involved.
@@end

@example cplx-0003
@meta category=complexity_analysis language=python difficulty=intermediate tags=recursion,memoisation,exponential,call-counting

@user
Our pricing service computes a "rollup" recursively and gets slower every quarter as the rule set grows. The single-argument version looks linear:

```python
def rollup(depth):
    if depth < 2:
        return depth
    return rollup(depth - 1) + rollup(depth - 2)
```

Two calls per level, so O(n) — but it takes 3 seconds at depth 32 and would take 3000 at depth 42. Where is the extra time going, and what is the correct complexity statement?
@@end

@assistant
The "two calls per level" reading counts the *edges*, not the *nodes*. `rollup` does not do two calls per level in total; it does two calls **per node**, and the number of nodes grows exponentially: this is the Fibonacci recursion, `T(n) = T(n-1) + T(n-2) + O(1)`, whose solution is `T(n) = Θ(φⁿ)` with `φ ≈ 1.618`. Growing by a factor of φ per extra level is why depth 32 takes seconds and depth 42 would take ~100× longer (the 3000 s you extrapolated).

The reason the work explodes is that the same subproblem is solved many times: `rollup(n-2)` is computed once inside `rollup(n)`'s first branch and again inside its second branch, then again in each of their branches. The call count for depth 32 is in the millions while there are only 33 distinct arguments — a 5-order-of-magnitude redundancy. The fix is to make each subproblem be solved once:

```python
from functools import lru_cache

@lru_cache(maxsize=None)
def rollup(depth):
    if depth < 2:
        return depth
    return rollup(depth - 1) + rollup(depth - 2)
```

With memoisation the call tree becomes a call *path*: `Θ(n)` distinct states, each computed once, `Θ(1)` work per state → `Θ(n)` time and `Θ(n)` memory for the cache. An iterative version is the same complexity with `O(1)` memory and no recursion-limit risk:

```python
def rollup_iterative(depth):
    previous, current = 0, 1
    for _ in range(depth):
        previous, current = current, previous + current
    return previous
```

Three things to take away for complexity reasoning:

- **Count the recursion tree, not the edges.** A recurrence with two recursive calls is usually exponential unless the calls shrink the input fast (like binary search's `T(n/2) + O(1)`); a good sanity check is to count invocations for n, n+1, n+2 and look for a constant ratio ~φ or ~2.
- **Overlapping subproblems are the diagnosis, not the symptom.** If the number of distinct arguments is small and the number of calls is huge, memoisation is the correct fix — dynamic programming is that insight applied bottom-up.
- **Extrapolate with the measured ratio, not linearly.** Once you know the growth factor per level, you can say exactly how bad the next quarter's rule set will be — which is what turns "it is slow" into a scheduling decision. In production, this is also true of other super-linear patterns: the same discipline (measure the ratio, name the exponent) applies to recursion depth, `n` in queries, and cache misses.
@@end

@verify kind=executable language=python
@code
import sys
from functools import lru_cache

sys.setrecursionlimit(10_000)


def rollup_naive(depth, counter=None):
    if counter is not None:
        counter[0] += 1
    if depth < 2:
        return depth
    return rollup_naive(depth - 1, counter) + rollup_naive(depth - 2, counter)


@lru_cache(maxsize=None)
def rollup_memo(depth):
    if depth < 2:
        return depth
    return rollup_memo(depth - 1) + rollup_memo(depth - 2)


def rollup_iterative(depth):
    previous, current = 0, 1
    for _ in range(depth):
        previous, current = current, previous + current
    return previous


def count_calls(depth):
    counter = [0]
    value = rollup_naive(depth, counter)
    return value, counter[0]


def count_memo_calls(depth):
    rollup_memo.cache_clear()
    value = rollup_memo(depth)
    info = rollup_memo.cache_info()
    return value, info.currsize, info.misses


# 1. the call counts, at sizes where instrumenting is still cheap
rows = []
for depth in (10, 15, 20, 25, 30):
    value, calls = count_calls(depth)
    rows.append((depth, value, calls))
    print(f"naive depth={depth}: value={value} calls={calls}")

# 2. the growth ratio per level: ~phi for the naive version, ~1 for memoised
ratios = [round(rows[i + 1][2] / rows[i][2], 3) for i in range(len(rows) - 1)]
print("naive growth ratio per +5 levels:", ratios, "(phi^5 = 11.09)")

# 3. the same value for far less work: distinct states, not call nodes
for depth in (25, 30, 35):
    value_naive, calls = count_calls(depth)
    value_memo, cached_states, misses = count_memo_calls(depth)
    print(f"depth={depth}: naive calls={calls} | memo states={cached_states} "
          f"misses={misses} | same value={value_naive == value_memo}")

# 4. memoised growth is linear in the argument, which is the whole fix
memo_misses = [count_memo_calls(depth)[2] for depth in (100, 200, 400)]
print("memo misses at depth 100/200/400:", memo_misses)

# 5. iterative: same answers, constant memory
print("iterative agrees at depth 100:", rollup_iterative(100) == rollup_memo(100))

assert rows[0][1] == 55 and rows[4][1] == 832040, "values are Fibonacci numbers"
assert all(11.0 < ratio < 11.2 for ratio in ratios), ratios      # phi^5 per 5 levels
assert rows[4][2] > 2_000_000, "depth 30 needs millions of calls for 31 distinct states"
assert count_memo_calls(30)[1] == 31, "the memoised version touches 31 states"
assert memo_misses == [101, 201, 401], memo_misses                 # linear in depth
assert rollup_iterative(100) == rollup_memo(100) == 354224848179261915075
print("PASS")
@@end

@expect_output
naive depth=10: value=55 calls=177
naive depth=15: value=610 calls=1973
naive depth=20: value=6765 calls=21891
naive depth=25: value=75025 calls=242785
naive depth=30: value=832040 calls=2692537
naive growth ratio per +5 levels: [11.147, 11.095, 11.091, 11.09] (phi^5 = 11.09)
depth=25: naive calls=242785 | memo states=26 misses=26 | same value=True
depth=30: naive calls=2692537 | memo states=31 misses=31 | same value=True
depth=35: naive calls=29860703 | memo states=36 misses=36 | same value=True
memo misses at depth 100/200/400: [101, 201, 401]
iterative agrees at depth 100: True
PASS
@@end

@notes
Counts recursive invocations for increasing depth and pins the exponent: the naive
version's call count multiplies by ~11 per +5 levels (φ⁵ = 11.09) and exceeds two
million calls at depth 30 while touching only 31 distinct arguments — the redundancy
that makes it exponential. The memoised version is asserted to fill 31 cache entries
for the same answer and to grow linearly (101/201/401 misses for depths
100/200/400), and the iterative version agrees with it exactly on depth 100. Both
implementations are asserted to return the Fibonacci values, so the complexity change
is behaviour-preserving.
@@end

@example cplx-0004
@meta category=complexity_analysis language=python difficulty=advanced tags=amortised-analysis,dynamic-array,reallocation,memory

@user
A colleague claims our ingest loop is O(n) "because `list.append` is O(1)". Another says a single append can be O(n) "because the list has to grow". Our buffer does 100k appends per batch and the p99 latency spikes occasionally. Who is right, and how do I verify the amortised argument instead of repeating it?
@@end

@assistant
Both statements are true at different granularities, and the reconciliation is the amortised analysis: `list.append` is **O(1) amortised** and **O(n) worst case**. The occasional spike is the reallocation — when the internal array is full, CPython allocates a larger block and copies every existing element. Each individual append is therefore O(1) most of the time and O(k) at a reallocation, where k is the current length.

The amortised argument is that over n appends the *total* copying work is bounded by a constant times n: capacities grow geometrically (CPython uses roughly `newsize = size + size // 8`, i.e. 1.125×, plus a small constant), so the copies form a geometric series `c₁ + c₂ + … ≈ n/(1 - 1/1.125) ≈ 9n` slots. From that follows the two facts worth remembering:

- **Total work is O(n)**, so the average cost per append is O(1) — no amount of adversarial input changes that for a growing list.
- **A single append can still be O(n)**, which is exactly what produces p99 spikes. Amortised bounds say nothing about tail latency; if the spike matters, preallocate or batch (`bytearray`, `array`, or building via `extend(chunk)` where the chunk size is known), or bound the growth with a fixed-size ring buffer.

**How to verify it instead of repeating it** — count reallocations and copied slots, don't time anything. On CPython `sys.getsizeof(list)` exposes the allocated capacity (the object header is constant), so you can watch the capacity jump and sum the copies:

```python
import sys

HEADER = sys.getsizeof([])          # list object without slots


def capacity(items):
    return (sys.getsizeof(items) - HEADER) // 8     # 8 bytes per slot on 64-bit


def count_growth(appends):
    data, capacities, copied = [], [], 0
    for index in range(appends):
        before = capacity(data)
        data.append(index)
        after = capacity(data)
        if after != before:
            capacities.append(after)
            copied += before                # every existing slot is copied on growth
    return data, capacities, copied
```

This is deterministic (it depends only on the growth policy of your interpreter), and it turns the argument into two assertions: `len(capacities) == O(log n)` and `copied < 2 * n`. If the numbers ever stop holding after a refactor or an interpreter upgrade, the "O(1) amortised" claim in your comments is stale — which is the kind of assumption that should be tested rather than documented.
@@end

@verify kind=executable language=python
@code
import sys

HEADER = sys.getsizeof([])


def capacity(items):
    """Allocated slots of a CPython list (8 bytes per slot, constant header)."""
    return (sys.getsizeof(items) - HEADER) // 8


def count_growth(appends):
    data, capacities, copied = [], [], 0
    for index in range(appends):
        before = capacity(data)
        data.append(index)
        after = capacity(data)
        if after != before:
            capacities.append((index + 1, before, after))
            copied += before                     # reallocation copies live elements
    return data, capacities, copied


def ingest_with_preallocation(items):
    """The p99 fix: one allocation, no growth during the loop."""
    data = [None] * len(items)
    for index, item in enumerate(items):
        data[index] = item
    return data


# 1. the raw numbers for a realistic batch
N = 100_000
data, growths, copied = count_growth(N)
print("appends:", N, "| reallocations:", len(growths), "| slots copied:", copied)
print("copies per append (amortised):", round(copied / N, 3))
print("final capacity:", capacity(data), "| length:", len(data))

# 2. the growth policy: a fixed geometric factor, which is what makes the sum finite
factors = [round(after / before, 4) for _length, before, after in growths if before > 1000]
print("steady-state growth factors (before > 1000):", factors[:12])
print("first ten growth steps (length, before, after):", growths[:10])

# 3. the worst case really is O(n): print the largest single reallocation
largest = max(growths, key=lambda row: row[1])
print("largest single copy:", largest, "slots")

# 4. amortised total is linear: doubling n roughly doubles the copied slots
totals = []
for size in (25_000, 50_000, 100_000):
    _data, _growths, total_copied = count_growth(size)
    totals.append((size, total_copied))
    print(f"n={size}: copied={total_copied}")

copy_ratios = [round(totals[i + 1][1] / totals[i][1], 3) for i in range(len(totals) - 1)]
print("copy-growth per doubling:", copy_ratios)

# 5. the tail-latency fix: exactly one allocation instead of many
preallocated = ingest_with_preallocation(list(range(N)))
print("preallocated capacity == length:", capacity(preallocated) == len(preallocated))
print("preallocated reallocations: 0")

# 6. capacity is amortised memory, not exact: the list holds up to ~12.5% slack
slack = capacity(data) / len(data)
print("capacity slack after the batch:", round(slack, 4))

assert len(growths) < 100, "reallocations must be logarithmic, not linear"
assert copied < 12 * N, "the geometric series stays linear: ~9n copies, not n log n"
assert copied > 5 * N, "and it is not free either: the copies are real work"
assert all(1.11 < factor < 1.14 for factor in factors), factors
assert largest[1] > 65_000, "the largest single copy is O(n) - the p99 spike"
assert all(1.6 < ratio < 2.4 for ratio in copy_ratios), copy_ratios
assert capacity(preallocated) == len(preallocated)
assert 1.0 <= slack < 1.15, slack
print("PASS")
@@end

@expect_output
appends: 100000 | reallocations: 66 | slots copied: 798128
copies per append (amortised): 7.981
final capacity: 100116 | length: 100000
steady-state growth factors (before > 1000): [1.1309, 1.1286, 1.1282, 1.1288, 1.1275, 1.127, 1.1268, 1.1266, 1.1262, 1.1268, 1.1268, 1.1261]
first ten growth steps (length, before, after): [(1, 0, 4), (5, 4, 8), (9, 8, 16), (17, 16, 24), (25, 24, 32), (33, 32, 40), (41, 40, 52), (53, 52, 64), (65, 64, 76), (77, 76, 92)]
largest single copy: (88989, 88988, 100116) slots
n=25000: copied=216636
n=50000: copied=441712
n=100000: copied=798128
copy-growth per doubling: [2.039, 1.807]
preallocated capacity == length: True
preallocated reallocations: 0
capacity slack after the batch: 1.0012
PASS
@@end

@notes
Verifies the amortised claim by counting reallocations and copied slots through
`sys.getsizeof` (deterministic on CPython, no timing): 100 000 appends produce fewer
than 100 reallocations with a total copy cost under 12n — measured ~8n — the steady-state growth factor is ~1.125, and the
copied-slot total roughly doubles when n doubles — the measured evidence for
"O(1) amortised". The same run pins the worst case: the largest single reallocation
copies tens of thousands of slots, which is the p99 spike, and the preallocated
variant is shown to allocate exactly once with no slack. The assertion band on the
growth factor documents which interpreter detail the claim depends on.
@@end
