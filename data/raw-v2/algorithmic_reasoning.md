@example algo-0001
@meta category=algorithmic_reasoning language=python difficulty=intermediate tags=binary-search,invariants,infinite-loop,off-by-one

@user
Our "find the insertion point" helper hangs on some inputs and returns instantly on others. The unit tests only ever search for values at or below the first element, so they never see it:

```python
def lower_bound(items, target):
    lo, hi = 0, len(items)
    while lo < hi:
        mid = (lo + hi) // 2
        if items[mid] < target:
            lo = mid           # line 5
        else:
            hi = mid
    return lo
```

Reproduce the hang deterministically, explain which invariant line 5 breaks, and give the corrected update. I want the general rule for writing these loops, not just this fix.
@@end

@assistant
Line 5 must be `lo = mid + 1`. With `lo = mid`, the loop can reach a state where `hi == lo + 1`: then `mid == lo`, and if `items[mid] < target` we assign `lo = mid`, which is the value it already had — **no progress**, so the loop spins forever. The hang needs the target to be absent (or larger than everything) in the tail of the range, which is exactly the case an "element exists" test suite never covers. With `items = [10, 20]` and `target = 25`: `lo=0, hi=2, mid=1`, `items[1] = 20 < 25` → `lo = 1`; next iteration `lo=1, hi=2, mid=1` again → infinite.

The general rule for these loops is to write the **invariant first**, then derive both updates from it:

- `lo` = "everything before `lo` is < target" (candidate range start);
- `hi` = "everything from `hi` on is >= target" (one past the end).

Given that invariant, when `items[mid] < target`, the element at `mid` is *known* to be below the answer, so the new `lo` must be `mid + 1` — leaving `mid` inside the range would allow the state that cannot progress. When `items[mid] >= target`, `mid` may be the answer, so `hi = mid` is correct (it shrinks because `mid < hi` while the loop condition holds). Two consequences follow mechanically: the range `[lo, hi)` always shrinks, so termination is structural; and the answer is `lo` (the first index satisfying the predicate), which is why half-open ranges are the right mental model.

```python
def lower_bound(items, target):
    lo, hi = 0, len(items)
    while lo < hi:
        mid = lo + (hi - lo) // 2        # overflow-safe form for fixed-width ints
        if items[mid] < target:
            lo = mid + 1                 # mid is excluded: it cannot be the answer
        else:
            hi = mid                     # mid is a candidate: keep it
    return lo
```

How to reason about any loop like this:

- **Name the invariant and check that every update preserves it.** If an update can leave the state unchanged, termination is not guaranteed.
- **Prove the range shrinks every iteration** (`hi - lo` strictly decreases) — that is the termination argument, and it fails loudly for `lo = mid`.
- **Test the boundaries, not just the happy path**: empty list, target before the first element, target after the last, target equal to `items[0]` and to `items[-1]`, duplicates (which `lower_bound` must place at the first occurrence). An exhaustive test over all prefixes of a small array plus all targets in range catches every version of this bug — and takes milliseconds.
@@end

@verify kind=executable language=python
@code
import bisect


def lower_bound_buggy(items, target, limit=50):
    lo, hi = 0, len(items)
    steps = 0
    while lo < hi:
        steps += 1
        if steps > limit:
            return "no progress after %d steps (lo=%d hi=%d)" % (limit, lo, hi)
        mid = (lo + hi) // 2
        if items[mid] < target:
            lo = mid                       # the defect
        else:
            hi = mid
    return lo


def lower_bound_fixed(items, target):
    lo, hi = 0, len(items)
    while lo < hi:
        mid = lo + (hi - lo) // 2
        if items[mid] < target:
            lo = mid + 1
        else:
            hi = mid
    return lo


ITEMS = [10, 20]

# 1. the hang, made deterministic by a step budget
print("missing target on the tail:", lower_bound_buggy(ITEMS, 25))

# 2. which targets terminate? The pattern is the whole explanation: every target
#    that resolves through `hi = mid` down to 0 terminates, everything else hangs.
print("budgeted results for " + str(ITEMS) + ":")
for target in (-5, 0, 5, 10, 12, 20, 25):
    result = lower_bound_buggy(ITEMS, target)
    print(f"  target {target}: {result}")

# 3. the state that cannot progress, printed at the moment it repeats
lo, hi = 1, 2
mid = (lo + hi) // 2
print("stuck state: lo=%d hi=%d mid=%d -> new lo=%d" % (lo, hi, mid, mid))

# 4. the invariant, checked exhaustively for the fixed version over every array of
#    small sorted values and every target in and around the range
def check_exhaustively():
    values = range(0, 6)
    checked = 0
    for size in range(0, 5):
        for mask in range(len(values) ** size):
            digits, rest = [], mask
            for _ in range(size):
                digits.append(rest % len(values))
                rest //= len(values)
            items = sorted(digits)
            for target in range(-1, 7):
                expected = bisect.bisect_left(items, target)
                got = lower_bound_fixed(items, target)
                assert got == expected, (items, target, got, expected)
                checked += 1
    return checked


checked = check_exhaustively()
print("exhaustive cases verified:", checked)   # sizes 0-4 x targets -1..6

# 5. the buggy version fails where the fixed one does not: count the disagreement
disagreements = 0
for size in range(1, 4):
    for mask in range(6 ** size):
        digits, rest = [], mask
        for _ in range(size):
            digits.append(rest % 6)
            rest //= 6
        items = sorted(digits)
        for target in range(-1, 7):
            if lower_bound_buggy(items, target) != bisect.bisect_left(items, target):
                disagreements += 1
print("buggy disagreements:", disagreements)

# 6. bisect_left agrees with the fixed version on a larger array too
big = sorted(i * 3 for i in range(500))
assert all(lower_bound_fixed(big, t) == bisect.bisect_left(big, t) for t in range(-2, 1505))
print("large array agrees with bisect:", True)

assert lower_bound_buggy(ITEMS, 25).startswith("no progress")
assert lower_bound_buggy(ITEMS, 5) == 0 and lower_bound_buggy(ITEMS, 10) == 0, (
    "every target the tests use terminates, with the right answer"
)
assert lower_bound_buggy(ITEMS, 12).startswith("no progress")
assert lower_bound_buggy(ITEMS, 20).startswith("no progress"), (
    "a present element is not enough: the hang depends on which branch runs"
)
assert lower_bound_fixed(ITEMS, 20) == 1
assert checked == 12440, checked
assert disagreements > 0, "the buggy version must fail somewhere"
assert lower_bound_fixed([], 5) == 0
assert lower_bound_fixed([1, 1, 1], 1) == 0
assert lower_bound_fixed([1, 1, 1], 2) == 3
print("PASS")
@@end

@expect_output
missing target on the tail: no progress after 50 steps (lo=1 hi=2)
budgeted results for [10, 20]:
  target -5: 0
  target 0: 0
  target 5: 0
  target 10: 0
  target 12: no progress after 50 steps (lo=0 hi=1)
  target 20: no progress after 50 steps (lo=0 hi=1)
  target 25: no progress after 50 steps (lo=1 hi=2)
stuck state: lo=1 hi=2 mid=1 -> new lo=1
exhaustive cases verified: 12440
buggy disagreements: 1253
large array agrees with bisect: True
PASS
@@end

@notes
The hang is made deterministic by a step budget and pinned with the stuck state
(`lo=1 hi=2 mid=1 -> new lo=1`), plus a target-by-target table showing exactly which
inputs terminate: targets at or below the first element resolve through `hi = mid` and
return the right index, while anything above the first element can leave `lo`
unchanged and spin — including `target = 20`, an element that *is* present. That is
why a suite of "first element" cases passed. The fixed version is verified against
`bisect.bisect_left` on every sorted array of size 0-4 over values 0-5 crossed with
targets -1..6 (12 440 cases) and on a 500-element array, and the buggy version is
shown to disagree on 1 253 of the same small cases.
@@end

@example algo-0002
@meta category=algorithmic_reasoning language=python difficulty=advanced tags=shortest-path,negative-weights,preconditions,invariants

@user
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
@@end

@assistant
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
@@end

@verify kind=executable language=python
@code
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
        for neighbour, weight in graph[node]:
            if dist[node] + weight < dist[neighbour]:
                dist[neighbour] = dist[node] + weight
                heappush(heap, (dist[neighbour], neighbour))
    return dist, pops


def spfa(graph, source):
    """Relaxation that never freezes a node: correctness without the heapq order."""
    dist = {node: float("inf") for node in graph}
    dist[source] = 0
    queue, queued = [source], {source}
    while queue:
        node = queue.pop(0)
        queued.discard(node)
        for neighbour, weight in graph[node]:
            if dist[node] + weight < dist[neighbour]:
                dist[neighbour] = dist[node] + weight
                if neighbour not in queued:
                    queue.append(neighbour)
                    queued.add(neighbour)
    return dist


def bellman_ford(graph, source):
    dist = {node: float("inf") for node in graph}
    dist[source] = 0
    edges = [(u, v, w) for u, neighbours in graph.items() for v, w in neighbours]
    for _ in range(len(graph) - 1):
        changed = False
        for u, v, w in edges:
            if dist[u] + w < dist[v]:
                dist[v] = dist[u] + w
                changed = True
        if not changed:
            break
    for u, v, w in edges:
        if dist[u] + w < dist[v]:
            raise ValueError("negative cycle reachable from the source")
    return dist


def improvable_edges(graph, dist):
    """A shortest-path result must leave no edge that can still be improved."""
    return [
        (u, v, w, dist[u] + w, dist[v])
        for u, neighbours in graph.items()
        for v, w in neighbours
        if dist[u] + float(w) < dist[v]
    ]


# 1. the counterexample: no negative cycle, and a destination that is too expensive
dist_dijkstra, pops = dijkstra(GRAPH, "S")
truth = bellman_ford(GRAPH, "S")
print("dijkstra distances:", dist_dijkstra)
print("settled order:", pops)
print("true distances:", truth)

# 2. the mechanism: the discount node's distance improved *after* it was settled,
#    and its outgoing edge was never relaxed again
print("A settled at:", [d for node, d in pops if node == "A"], "| final dist[A]:", dist_dijkstra["A"])
violations = improvable_edges(GRAPH, dist_dijkstra)
print("edges still improvable in the dijkstra result:", violations)

# 3. relaxations that do not freeze nodes get it right on the same graph
print("without settling:", spfa(GRAPH, "S"))
print("bellman-ford:", bellman_ford(GRAPH, "S"))

# 4. with non-negative weights Dijkstra is exact again, and the invariant holds
NON_NEGATIVE = {
    "S": [("A", 2), ("B", 3)],
    "A": [("C", 5)],
    "B": [("A", 2)],
    "C": [],
}
print("non-negative graph:", dijkstra(NON_NEGATIVE, "S")[0])
print("improvable edges there:", improvable_edges(NON_NEGATIVE, dijkstra(NON_NEGATIVE, "S")[0]))

# 5. a negative cycle is the *other* failure mode, and Bellman-Ford detects it
CYCLE = {"S": [("A", 1)], "A": [("B", -2)], "B": [("A", -2)]}
try:
    bellman_ford(CYCLE, "S")
    print("negative cycle: not detected")
except ValueError as exc:
    print("negative cycle detected:", exc)

assert dist_dijkstra["A"] == 1, "the discount node itself looks correct"
assert dist_dijkstra["C"] == 7, "its successor keeps the stale distance"
assert truth["C"] == 6 and truth["A"] == 1, "the true shortest paths"
assert dist_dijkstra["C"] != truth["C"], "the reported symptom: a destination too expensive"
assert violations == [("A", "C", 5, 6, 7)], violations
assert spfa(GRAPH, "S") == truth
assert bellman_ford(GRAPH, "S") == truth
assert dijkstra(NON_NEGATIVE, "S")[0] == bellman_ford(NON_NEGATIVE, "S")
assert improvable_edges(NON_NEGATIVE, dijkstra(NON_NEGATIVE, "S")[0]) == []
print("PASS")
@@end

@expect_output
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
@@end

@notes
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
@@end

@example algo-0003
@meta category=algorithmic_reasoning language=javascript difficulty=intermediate tags=two-pointer,index-mapping,duplicates,oracle-testing

@user
Our `twoSum` helper is fast and passes the examples in the issue, but support keeps sending screenshots where the returned indices point at the wrong numbers. It sorts, walks with two pointers, and returns the two positions:

```javascript
function twoSum(nums, target) {
  const sorted = [...nums].sort((a, b) => a - b);
  let i = 0, j = sorted.length - 1;
  while (i < j) {
    const sum = sorted[i] + sorted[j];
    if (sum === target) return [i, j];
    if (sum < target) i += 1; else j -= 1;
  }
  return [];
}
```

Why are the indices sometimes right and sometimes wrong, and what is the correct fix if I want to keep the two-pointer scan?
@@end

@assistant
The indices are positions in `sorted`, not in `nums` — two different arrays. They coincide only when sorting happens to be a no-op for those positions, which is why `[2, 7, 11, 15]` with target 9 looks correct (already sorted) and `[3, 2, 4]` with target 6 does not: the answer values are `3` and `3`... concretely, sorting gives `[2, 3, 4]`, the scan finds indices `0` and `2`, and the caller reads `nums[0] = 3` and `nums[2] = 4`, which sum to 7, not 6. The returned numbers are both wrong while the *set* of values is right — a bug that survives any test asserting on values rather than on the caller's view.

It is worth being precise about what the two-pointer version does and does not promise, because that determines which test finds it: it returns a pair of positions **in the sorted array**, so the pair of *values* is always correct when the scan succeeds — asserting on the values (`nums[i] + nums[j]`) can therefore pass while the returned indices are wrong for the caller. Without sorting, the standard one-pass hash map keeps the original indices, and the first-occurrence rule stays well defined:

```javascript
function twoSum(nums, target) {
  const seen = new Map();                       // value -> original index
  for (let index = 0; index < nums.length; index += 1) {
    const needed = target - nums[index];
    if (seen.has(needed)) return [seen.get(needed), index];
    if (!seen.has(nums[index])) seen.set(nums[index], index);   // first occurrence wins
  }
  return [];
}
```

If you must keep the sort (for example to reuse a shared sorted structure), carry the original index *with* the value: map to `{value, index}` pairs and return those indices; never compute an index in one array and dereference it in another.

The lesson generalises: **whenever you permute data, every index the function returns must be an index into the array the caller passed.** Sort-with-index (decorate–sort–undecorate) is the standard way to keep that promise, and it is exactly what a brute-force oracle test catches here — compare the helper against the O(n²) double loop on many arrays, including duplicates, negate cases and no-solution cases, and assert the returned indices actually satisfy `nums[i] + nums[j] === target`.
@@end

@verify kind=executable language=javascript
@code
function twoSumSortedIndices(nums, target) {
  const sorted = [...nums].sort((a, b) => a - b);
  let i = 0, j = sorted.length - 1;
  while (i < j) {
    const sum = sorted[i] + sorted[j];
    if (sum === target) return [i, j];
    if (sum < target) i += 1; else j -= 1;
  }
  return [];
}

function twoSumFixed(nums, target) {
  const seen = new Map();
  for (let index = 0; index < nums.length; index += 1) {
    const needed = target - nums[index];
    if (seen.has(needed)) return [seen.get(needed), index];
    if (!seen.has(nums[index])) seen.set(nums[index], index);
  }
  return [];
}

function twoSumWithIndexCarried(nums, target) {
  const decorated = nums.map((value, index) => ({ value, index }))
    .sort((a, b) => a.value - b.value);
  let i = 0, j = decorated.length - 1;
  while (i < j) {
    const sum = decorated[i].value + decorated[j].value;
    if (sum === target) return [decorated[i].index, decorated[j].index];
    if (sum < target) i += 1; else j -= 1;
  }
  return [];
}

function bruteForce(nums, target) {
  for (let i = 0; i < nums.length; i += 1) {
    for (let j = i + 1; j < nums.length; j += 1) {
      if (nums[i] + nums[j] === target) return [i, j];
    }
  }
  return [];
}

const satisfies = (nums, target, pair) =>
  pair.length === 2 && pair[0] !== pair[1] && nums[pair[0]] + nums[pair[1]] === target;

// 1. the passing example: already sorted, so the indices line up
console.log("sorted input:", JSON.stringify(twoSumSortedIndices([2, 7, 11, 15], 9)));

// 2. the failing example: sorted indices point at the wrong values
const BAD = [3, 2, 4], TARGET = 6;
const badPair = twoSumSortedIndices(BAD, TARGET);
console.log("unsorted input, returned indices:", JSON.stringify(badPair));
console.log("values the caller sees:", JSON.stringify(badPair.map((i) => BAD[i])),
            "sum:", badPair.map((i) => BAD[i]).reduce((a, b) => a + b, 0));

// 3. duplicates: the same element must not be used twice
const DUP = [3, 3], DUP_TARGET = 6;
// the naive "scan for the complement" version can also return the same index twice
console.log("duplicates, sorted-indices version:", JSON.stringify(twoSumSortedIndices(DUP, DUP_TARGET)),
            "| hash map:", JSON.stringify(twoSumFixed(DUP, DUP_TARGET)));

// 4. the fixes
console.log("hash map:", JSON.stringify(twoSumFixed(BAD, TARGET)),
            "satisfies:", satisfies(BAD, TARGET, twoSumFixed(BAD, TARGET)));
console.log("index carried through the sort:",
            JSON.stringify(twoSumWithIndexCarried(BAD, TARGET)));

// 5. an oracle test over many arrays: the check that would have caught it
let seed = 12345;
const nextRandom = () => {
  seed = (seed * 1103515245 + 12345) % 2147483648;    // deterministic LCG
  return seed;
};
let checked = 0, sortedIndexFailures = 0, hashFailures = 0;
for (let trial = 0; trial < 400; trial += 1) {
  const size = 2 + (nextRandom() % 6);
  const nums = Array.from({ length: size }, () => (nextRandom() % 11) - 5);
  const target = (nextRandom() % 15) - 7;
  const expected = bruteForce(nums, target);
  const fromHash = twoSumFixed(nums, target);
  const fromSorted = twoSumSortedIndices(nums, target);
  checked += 1;
  if (expected.length === 0
      ? fromHash.length !== 0
      : !satisfies(nums, target, fromHash)) hashFailures += 1;
  if (expected.length === 0
      ? fromSorted.length !== 0
      : !satisfies(nums, target, fromSorted)) sortedIndexFailures += 1;
}

function assert(condition, message) {
  if (!condition) throw new Error(message || "assertion failed");
}

console.log("oracle trials:", checked,
            "| hash-map failures:", hashFailures,
            "| sorted-index failures:", sortedIndexFailures);

assert(JSON.stringify(twoSumSortedIndices([2, 7, 11, 15], 9)) === "[0,1]",
       "on an already sorted input the helper looks correct");
assert(!satisfies(BAD, TARGET, badPair), "the reported bug: indices do not satisfy the target");
assert(JSON.stringify(twoSumFixed(BAD, TARGET)) === "[1,2]");
assert(satisfies(BAD, TARGET, twoSumFixed(BAD, TARGET)));
assert(satisfies(BAD, TARGET, twoSumWithIndexCarried(BAD, TARGET)));
assert(satisfies(DUP, DUP_TARGET, twoSumFixed(DUP, DUP_TARGET)));
assert(JSON.stringify(twoSumFixed(DUP, DUP_TARGET)) === "[0,1]",
       "the two indices must be distinct elements");
assert(hashFailures === 0, "the hash map must match the oracle");
assert(sortedIndexFailures > 0, "the oracle must catch the sorted-index version");
console.log("PASS");
@@end

@expect_output
sorted input: [0,1]
unsorted input, returned indices: [0,2]
values the caller sees: [3,4] sum: 7
duplicates, sorted-indices version: [0,1] | hash map: [0,1]
hash map: [1,2] satisfies: true
index carried through the sort: [1,2]
oracle trials: 400 | hash-map failures: 0 | sorted-index failures: 109
PASS
@@end

@notes
Pins the failure mode with the caller's own view of the data: for `[3, 2, 4]` with
target 6 the helper returns sorted-array indices whose values sum to 7, so the
returned pair does not satisfy the target, while the already-sorted example returns a
valid pair — that is why the issue's examples passed. A deterministic 400-trial oracle
(brute force reference over random arrays with duplicates, negatives and no-solution
cases) reports zero failures for the hash-map version and a nonzero count for the
sorted-index version, and both fixes (hash map, index carried through the sort) are
asserted to satisfy `nums[i] + nums[j] === target` with distinct indices, including
the `[3, 3]` duplicate case.
@@end

@example algo-0004
@meta category=algorithmic_reasoning language=python difficulty=advanced tags=lru-cache,data-structures,access-order,hashing

@user
Our LRU cache evicts the wrong entries — sometimes the hottest key disappears right after being used:

```python
from collections import OrderedDict

class LruCache:
    def __init__(self, capacity):
        self.capacity = capacity
        self.data = OrderedDict()

    def get(self, key):
        return self.data.get(key)          # line 9

    def put(self, key, value):
        self.data[key] = value
        if len(self.data) > self.capacity:
            self.data.popitem(last=False)  # evict the oldest entry
```

The `OrderedDict` is doing the ordering, `popitem(last=False)` evicts the front, and the tests (put/get/evict with distinct keys) pass. Why does an entry that was just read get evicted, and what else is wrong in this class?
@@end

@assistant
The cache never *records the read*. `OrderedDict` only reorders on insertion and on explicit `move_to_end`; a plain `get` leaves the entry where it was. So the ordering is insertion order, not recency, and `popitem(last=False)` evicts the key that was inserted first — regardless of how recently it was used. Your test passes because it never reuses a key before evicting: with distinct keys, insertion order and access order are indistinguishable.

Fix line 9 with a lookup that also refreshes position (and handle the miss path without refreshing):

```python
from collections import OrderedDict

class LruCache:
    def __init__(self, capacity):
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        self.capacity = capacity
        self.data = OrderedDict()

    def get(self, key, default=None):
        if key not in self.data:            # membership first: no false refresh on a miss
            return default
        self.data.move_to_end(key)          # this is the "recently used" bookkeeping
        return self.data[key]

    def put(self, key, value):
        if key in self.data:
            self.data.move_to_end(key)      # an update is a use
        self.data[key] = value
        while len(self.data) > self.capacity:
            self.data.popitem(last=False)
```

Three further defects worth fixing at the same time, all in the same five lines:

- **`put` of an existing key does not refresh it** either, so an updated key keeps its old position and can be evicted immediately.
- **The cache reports a hit and a miss identically** (`None` either way). A stored `None` is indistinguishable from a miss, which silently breaks callers that cache optional values; use a sentinel or a separate `__contains__` contract for callers.
- **No thread safety.** `OrderedDict` operations are individually lock-protected in CPython, but the read–refresh–evict sequence is not atomic, so two threads can exceed the capacity or evict a key another thread just refreshed. Wrap mutations in a `threading.Lock` if the cache is shared (or use `functools.lru_cache`, which is thread-safe and does all of this in C).

And the reason this bug class is so easy to miss: the *invariant* of an LRU is "the eviction victim is the least recently used key", not "the oldest key". A test that only asserts capacity and hit/miss counts cannot see the difference — the test has to build an access pattern with an explicit hot key and assert that it survives an eviction. My verification does exactly that with the sequence `put(a), put(b), get(a), put(c)`: the hot key `a` must survive, and with the bug it is the one evicted.
@@end

@verify kind=executable language=python
@code
import random
from collections import OrderedDict

HITS = 0


class LruCache:
    """The implementation under review: get() never refreshes recency."""

    def __init__(self, capacity):
        self.capacity = capacity
        self.data = OrderedDict()

    def get(self, key):
        return self.data.get(key)

    def put(self, key, value):
        self.data[key] = value
        if len(self.data) > self.capacity:
            self.data.popitem(last=False)

    def keys_lru_to_mru(self):
        return list(self.data)


class FixedLru:
    def __init__(self, capacity):
        self.capacity = capacity
        self.data = OrderedDict()
        self.hits = 0

    def get(self, key, default=None):
        if key not in self.data:
            return default
        self.data.move_to_end(key)
        self.hits += 1
        return self.data[key]

    def put(self, key, value):
        if key in self.data:
            self.data.move_to_end(key)
        self.data[key] = value
        while len(self.data) > self.capacity:
            self.data.popitem(last=False)

    def keys_lru_to_mru(self):
        return list(self.data)


# 1. the reported symptom: a hot key is evicted
cache = LruCache(2)
cache.put("a", 1)
cache.put("b", 2)
cache.get("a")                     # a is the most recently used key
cache.put("c", 3)                  # should evict b
print("buggy cache after get(a), put(c):", cache.keys_lru_to_mru())
print("hot key a present:", cache.get("a") is not None)

# 2. the fix: same sequence, the hot key survives
fixed = FixedLru(2)
fixed.put("a", 1)
fixed.put("b", 2)
assert fixed.get("a") == 1
fixed.put("c", 3)
print("fixed cache after get(a), put(c):", fixed.keys_lru_to_mru())

# 3. an update is also a use: the refreshed key must not be the victim
stale = LruCache(2)
stale.put("a", 1)
stale.put("b", 2)
stale.put("a", 10)                 # update: the buggy version keeps a at the front
stale.put("c", 3)
print("buggy cache after put(a, 10), put(c):", stale.keys_lru_to_mru())

refreshed = FixedLru(2)
refreshed.put("a", 1)
refreshed.put("b", 2)
refreshed.put("a", 10)
refreshed.put("c", 3)
print("fixed cache after put(a, 10), put(c):", refreshed.keys_lru_to_mru())

# 4. an access pattern with a hot key: identical inputs, different hit counts
PATTERN = []
generator = random.Random(7)
for _ in range(600):
    PATTERN.append(("get" if generator.random() < 0.7 else "put", generator.choice("abcdefgh")))


def replay(cache_class):
    store = cache_class(3)
    hits = 0
    for operation, key in PATTERN:
        if operation == "get":
            if store.get(key) is not None:
                hits += 1
        else:
            store.put(key, "v" + key)
    return hits


buggy_hits = replay(LruCache)
fixed_hits = replay(FixedLru)
print("hits over 600 operations: buggy =", buggy_hits, "| fixed =", fixed_hits)

# 5. capacity is respected by both, which is why the old tests passed
print("capacity respected (buggy):", len(cache.data) <= 2, "| (fixed):", len(fixed.data) <= 2)

# 6. the None ambiguity: a cached None is indistinguishable from a miss
ambiguous = FixedLru(2)
ambiguous.put("nullable", None)
print("cached None reads as:", ambiguous.get("nullable"), "| miss reads as:", ambiguous.get("absent"))

assert cache.get("a") is None, "the hot key was evicted (the bug)"
assert "a" in fixed.keys_lru_to_mru(), "the fixed cache keeps the hot key"
assert fixed.keys_lru_to_mru() == ["a", "c"], fixed.keys_lru_to_mru()
assert stale.keys_lru_to_mru() == ["b", "c"], stale.keys_lru_to_mru()
assert refreshed.keys_lru_to_mru() == ["a", "c"], refreshed.keys_lru_to_mru()
assert fixed_hits > buggy_hits, (buggy_hits, fixed_hits)
assert len(cache.data) <= 2 and len(fixed.data) <= 2
assert ambiguous.get("nullable") is None and ambiguous.get("absent") is None
print("PASS")
@@end

@expect_output
buggy cache after get(a), put(c): ['b', 'c']
hot key a present: False
fixed cache after get(a), put(c): ['a', 'c']
buggy cache after put(a, 10), put(c): ['b', 'c']
fixed cache after put(a, 10), put(c): ['a', 'c']
hits over 600 operations: buggy = 170 | fixed = 172
capacity respected (buggy): True | (fixed): True
cached None reads as: None | miss reads as: None
PASS
@@end

@notes
Pins the eviction-order evidence: after `put(a), put(b), get(a), put(c)` the buggy cache
holds `["b", "c"]` and the hot key `a` is gone, while the fixed cache holds `["c", "a"]`.
The same demonstration is repeated for an update (`put(a, 10)`) so "an update is a use"
is covered, and a deterministic 600-operation access pattern with a skewed key
distribution shows the fixed cache earning more hits on identical inputs. Both
versions respect the capacity, which is why the original tests passed, and the
`None`-ambiguity (cached `None` reads the same as a miss) is pinned as a contract
concern rather than a behaviour difference.
@@end
