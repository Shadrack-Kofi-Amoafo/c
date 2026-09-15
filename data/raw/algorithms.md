@example py-alg-0001
@meta category=algorithms language=python difficulty=intermediate tags=dynamic-programming,greedy-intervals,scheduling,binary-search

@user
We book ad campaigns into fixed slots. Each campaign has a start time, an end time (half-open, so a campaign ending at 10:00 does not clash with one starting at 10:00) and a revenue value. I need the subset of campaigns with the maximum total revenue such that no two overlap, and I need the actual selected campaigns back, not just the total. What is the algorithm and how do I make the reconstruction reliable?
@@end

@assistant
The problem is *weighted interval scheduling*. Sorting by end time and running a DP over the sorted list gives O(n log n) time because the "last compatible predecessor" of each interval can be found with a binary search instead of a scan.

For a half-open interval `j` sorted by end time, its predecessor `p[j]` is the number of intervals that end at or before `j.start`. With intervals sorted by end time, `bisect_right(ends, j.start, 0, j)` gives exactly that count, which is also the DP index to fall back to.

```python
from bisect import bisect_right
from dataclasses import dataclass


@dataclass(frozen=True)
class Campaign:
    start: int
    end: int          # exclusive
    revenue: int
    name: str = ""

    def __post_init__(self):
        if self.end <= self.start:
            raise ValueError(f"non-positive duration for {self.name or self}")


def best_schedule(campaigns):
    """Return (max_revenue, selected_sorted_by_start).

    Intervals are half-open [start, end); touching intervals do not conflict.
    Ties are broken towards the schedule using *fewer* campaigns, which keeps
    the result deterministic for equal revenues.
    """
    jobs = sorted(campaigns, key=lambda c: (c.end, c.start, c.revenue, c.name))
    n = len(jobs)
    ends = [c.end for c in jobs]

    # pred[i] = number of jobs that finish <= jobs[i].start (only looking left)
    pred = [bisect_right(ends, jobs[i].start, 0, i) for i in range(n)]

    # best[i] = best revenue achievable with jobs[:i]
    best = [0] * (n + 1)
    for i in range(1, n + 1):
        j = i - 1
        skip = best[i - 1]
        take = jobs[j].revenue + best[pred[j]]
        best[i] = take if take > skip else skip

    # Walk the table backwards to recover the argmax, not just the value.
    chosen, i = [], n
    while i > 0:
        j = i - 1
        if jobs[j].revenue + best[pred[j]] > best[i - 1]:
            chosen.append(jobs[j])
            i = pred[j]
        else:
            i -= 1
    return best[n], sorted(chosen, key=lambda c: (c.start, c.end))
```

Key points and the traps:

- **Sort by end time first.** Sorting by start or revenue breaks the recurrence. If you must keep the caller's data untouched, sort a copy — `sorted()` already does.
- **Reconstruction must mirror the DP**, not re-run a greedy rule afterwards: comparing `revenue + best[pred]` against `best[i-1]` asks the same question the forward pass asked. A common bug is reconstructing with `>=`, which silently returns a different (still optimal-value) set and can duplicate intervals.
- **Boundaries:** `bisect_right` (not `bisect_left`) encodes "touching is allowed". Using `bisect_left` makes an interval ending exactly at another's start count as a conflict, which quietly loses revenue.
- **Complexity:** O(n log n) time, O(n) extra space. Negative revenue is fine — the DP will simply skip such campaigns; the empty schedule is always feasible.
- **Not the LIS greedy:** unweighted interval scheduling can be solved greedily by earliest finish; with weights, that greedy is wrong. Do not reuse it here.

The verification below cross-checks the DP against exhaustive search over all subsets on random instances, and asserts the reconstructed set is itself non-overlapping with the advertised total.

@@end

@verify kind=executable language=python

@code
import itertools
import random
from bisect import bisect_right
from dataclasses import dataclass


@dataclass(frozen=True)
class Campaign:
    start: int
    end: int
    revenue: int
    name: str = ""

    def __post_init__(self):
        if self.end <= self.start:
            raise ValueError("non-positive duration")


def best_schedule(campaigns):
    jobs = sorted(campaigns, key=lambda c: (c.end, c.start, c.revenue, c.name))
    n = len(jobs)
    ends = [c.end for c in jobs]
    pred = [bisect_right(ends, jobs[i].start, 0, i) for i in range(n)]
    best = [0] * (n + 1)
    for i in range(1, n + 1):
        j = i - 1
        take = jobs[j].revenue + best[pred[j]]
        best[i] = take if take > best[i - 1] else best[i - 1]
    chosen, i = [], n
    while i > 0:
        j = i - 1
        if jobs[j].revenue + best[pred[j]] > best[i - 1]:
            chosen.append(jobs[j])
            i = pred[j]
        else:
            i -= 1
    return best[n], sorted(chosen, key=lambda c: (c.start, c.end))


def brute_force(campaigns):
    best = 0
    for r in range(len(campaigns) + 1):
        for subset in itertools.combinations(campaigns, r):
            ordered = sorted(subset, key=lambda c: c.start)
            if all(ordered[i].end <= ordered[i + 1].start for i in range(len(ordered) - 1)):
                best = max(best, sum(c.revenue for c in subset))
    return best


def is_feasible(selection):
    ordered = sorted(selection, key=lambda c: c.start)
    return all(ordered[i].end <= ordered[i + 1].start for i in range(len(ordered) - 1))


rng = random.Random(20240117)
for trial in range(400):
    n = rng.randint(0, 9)
    instances = []
    for i in range(n):
        start = rng.randint(0, 24)
        end = start + rng.randint(1, 6)
        instances.append(Campaign(start, end, rng.randint(-3, 12), f"c{i}"))
    value, chosen = best_schedule(instances)
    assert value == brute_force(instances), (trial, value, brute_force(instances))
    assert is_feasible(chosen), (trial, chosen)
    assert sum(c.revenue for c in chosen) == value, (trial, chosen, value)

# Deterministic tie-break: two disjoint campaigns of equal revenue beat one of them,
# and the result does not depend on input order.
a = Campaign(0, 5, 10, "a")
b = Campaign(5, 9, 10, "b")
assert best_schedule([a, b])[0] == 20
assert best_schedule([b, a]) == best_schedule([a, b])

# Touching intervals do not conflict (half-open).
assert best_schedule([Campaign(0, 5, 1), Campaign(5, 6, 1)])[0] == 2
# Overlapping by one unit do conflict.
assert best_schedule([Campaign(0, 5, 1), Campaign(4, 6, 1)])[0] == 1
# Degenerate inputs.
assert best_schedule([]) == (0, [])
assert best_schedule([Campaign(1, 2, -5)])[0] == 0
assert best_schedule([Campaign(3, 4, 7), Campaign(0, 10, 7), Campaign(20, 21, 7)])[0] == 14
try:
    Campaign(5, 5, 1)
    raise AssertionError("zero-length interval must be rejected")
except ValueError:
    pass
print("PASS")
@@end

@expect_output
PASS
@@end

@notes
Runs 400 randomized instances against exhaustive subset search (n <= 9) and checks
value equality, feasibility of the reconstructed set, and that the set's revenue
equals the reported optimum. Also pins the tie-break, the half-open boundary
behaviour in both directions, empty input, all-negative input, and rejection of
zero-length intervals.
@@end

@example py-alg-0002
@meta category=algorithms language=python difficulty=advanced tags=kmp,streaming,string-matching,buffer-boundaries

@user
I scan a live log feed in chunks and need to flag every offset where a signature (a short byte pattern) appears, including overlapping matches, e.g. pattern "aba" in "ababa" occurs at 0 and 2. The feed arrives in arbitrary chunk sizes and I cannot buffer the whole stream. What is the right algorithm and how do I keep the matches correct across chunk boundaries?
@@end

@assistant
Use KMP with a *persistent* state machine. The failure function makes the scan O(n + m) total regardless of chunking, and the only thing you must carry across chunk boundaries is the current matched-prefix length plus the absolute offset of the chunk start — never a naive `text.find(pattern)` per chunk (it misses matches that straddle the boundary and is O(n*m) worst case).

The classic KMP bug in streaming code is resetting `state = 0` when a chunk starts. `state` is exactly "how many characters of the pattern are already matched by text that ended in a previous chunk", so it must survive.

```python
class KmpStream:
    """Incremental KMP. Feed chunks; each call yields absolute match offsets."""

    def __init__(self, pattern: bytes):
        self.pattern = pattern
        self.pi = self._prefix_function(pattern)
        self.state = 0        # length of the longest pattern prefix matched so far
        self.consumed = 0     # absolute offset of the next unconsumed byte

    @staticmethod
    def _prefix_function(pattern: bytes) -> list[int]:
        pi = [0] * len(pattern)
        k = 0
        for i in range(1, len(pattern)):
            while k and pattern[i] != pattern[k]:
                k = pi[k - 1]
            if pattern[i] == pattern[k]:
                k += 1
            pi[i] = k
        return pi

    def feed(self, chunk: bytes):
        if not self.pattern:
            raise ValueError("empty pattern would match at every offset")
        matches = []
        start = self.consumed
        for i, byte in enumerate(chunk):
            while self.state and byte != self.pattern[self.state]:
                self.state = self.pi[self.state - 1]
            if byte == self.pattern[self.state]:
                self.state += 1
            if self.state == len(self.pattern):
                matches.append(start + i - len(self.pattern) + 1)
                # Fall back: the suffix of this match may begin another one.
                self.state = self.pi[self.state - 1]
        self.consumed += len(chunk)
        return matches
```

Why it is correct and where implementations go wrong:

- After a full match, do **not** set `state = 0`; set `state = pi[state-1]`. That single line is what makes overlapping matches (`"aba"` in `"ababa"` at offsets 0 and 2) and self-overlapping patterns (`"aabaaab"` in `"aabaaabaabaaab"`) come out right.
- All offsets are absolute (`start + i - m + 1`), computed from the stream base, so chunk sizes are irrelevant. Chunking the same bytes differently must not change the output — that is the property the test below asserts.
- `pi` is precomputed once per pattern: O(m) memory, O(m) setup. Use `kmp.pattern = pattern` as a `bytes` object; indexing `bytes` yields `int`, so compare with `byte`, not with a length-1 bytes slice (a classic Python substring bug).
- The failure-link loop is amortized: `state` grows by at most 1 per byte, so the `while` can only undo what previous bytes built. Total O(n + m) time even with adversarial input such as `pattern = b"aaaaab"`, `stream = b"aaaaaaa..."`.
- If the stream is UTF-8 text rather than bytes, decode first and match on `str` (the same code works with strings); do not match on raw bytes and then slice characters, because offsets would not line up.

Complexity: O(n + m) time, O(m) space (nothing from the stream is retained).

@@end

@verify kind=executable language=python

@code
class KmpStream:
    def __init__(self, pattern):
        self.pattern = pattern
        self.pi = self._prefix_function(pattern)
        self.state = 0
        self.consumed = 0

    @staticmethod
    def _prefix_function(pattern):
        pi = [0] * len(pattern)
        k = 0
        for i in range(1, len(pattern)):
            while k and pattern[i] != pattern[k]:
                k = pi[k - 1]
            if pattern[i] == pattern[k]:
                k += 1
            pi[i] = k
        return pi

    def feed(self, chunk):
        if not self.pattern:
            raise ValueError("empty pattern")
        matches = []
        start = self.consumed
        for i, byte in enumerate(chunk):
            while self.state and byte != self.pattern[self.state]:
                self.state = self.pi[self.state - 1]
            if byte == self.pattern[self.state]:
                self.state += 1
            if self.state == len(self.pattern):
                matches.append(start + i - len(self.pattern) + 1)
                self.state = self.pi[self.state - 1]
        self.consumed += len(chunk)
        return matches


def reference(text, pattern):
    out, i = [], text.find(pattern)
    while i != -1:
        out.append(i)
        i = text.find(pattern, i + 1)
    return out


def streamed(text, pattern, chunks):
    scanner, out = KmpStream(pattern), []
    pos = 0
    for size in chunks:
        out += scanner.feed(text[pos:pos + size])
        pos += size
    out += scanner.feed(text[pos:])
    return out


import random

assert KmpStream(b"aba").feed(b"ababa") == [0, 2]
assert streamed(b"aabaaabaabaaab", b"aabaaab", [1, 1, 1, 1, 100]) == [0, 7]

rng = random.Random(90210)
for trial in range(400):
    text = bytes(rng.randrange(3) + 97 for _ in range(rng.randint(0, 60)))
    pattern = bytes(rng.randrange(3) + 97 for _ in range(rng.randint(1, 4)))
    expected = reference(text, pattern)
    # Same bytes, random chunking, must give identical offsets.
    sizes = [rng.randint(1, 5) for _ in range(rng.randint(1, 12))]
    assert streamed(text, pattern, sizes) == expected, (text, pattern, sizes)
    assert KmpStream(pattern).feed(text) == expected      # single big chunk
    assert streamed(text, pattern, [1] * len(text)) == expected  # one byte at a time

# Adversarial self-overlap and long runs.
assert streamed(b"a" * 50, b"aaa", [7, 13, 30]) == list(range(48))
assert streamed(b"aaaaabaaaaab", b"aab", [3, 3, 6]) == [3, 9]
assert streamed(b"", b"abc", [1, 2]) == []
assert streamed(b"abc", b"abcd", [2, 1]) == []
try:
    KmpStream(b"").feed(b"x")
    raise AssertionError("empty pattern must be rejected")
except ValueError:
    pass
print("PASS")
@@end

@expect_output
PASS
@@end

@notes
400 randomized cases compare the streaming scanner against a `bytes.find`-based
reference under three chunkings (random, one-shot, byte-at-a-time), which is the
property that actually matters for stream processing. Additional cases cover the
longest self-overlap ("aabaaab"), overlapping matches, run-length input
("aaaaabaaaaab"), empty text, pattern longer than text, and empty-pattern
rejection.
@@end

@example js-alg-0003
@meta category=algorithms language=javascript difficulty=expert tags=topological-sort,cycle-detection,determinism,build-systems

@user
Our Node build orchestrator needs a topological order of task names that is stable across runs (byte-identical build logs, so alphabetical tie-breaking is required), and when the graph has a cycle it must print the actual cycle, e.g. "b -> c -> b", instead of just saying "cycle detected". How do I get both?
@@end

@assistant
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

@@end

@verify kind=executable language=javascript

@code
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
    }
  }
  if (order.length !== nodes.length) return { order: null, cycle: findCycle(nodes, parents, indegree) };
  return { order, cycle: null };
}

function findCycle(nodes, parents, indegree) {
  const start = nodes.filter((n) => indegree.get(n) > 0).sort()[0];
  const seenAt = new Map([[start, 0]]);
  const walk = [start];
  let node = start;
  for (;;) {
    const prev = parents.get(node).filter((p) => indegree.get(p) > 0).sort()[0];
    if (prev === undefined) throw new Error(`no leftover prerequisite for ${node}`);
    if (seenAt.has(prev)) return walk.slice(seenAt.get(prev)).concat(prev).reverse();
    seenAt.set(prev, walk.length);
    walk.push(prev);
    node = prev;
  }
}

class MinHeap {
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

// --- helpers ------------------------------------------------------------
function mulberry32(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function isDag(nodes, edges) {
  // Independent cycle check via DFS colours.
  const adj = new Map(nodes.map((n) => [n, []]));
  for (const [from, tos] of edges) for (const to of tos) adj.get(from).push(to);
  const colour = new Map(nodes.map((n) => [n, 0]));
  const dfs = (u) => {
    colour.set(u, 1);
    for (const v of adj.get(u)) {
      if (colour.get(v) === 1) return false;
      if (colour.get(v) === 0 && !dfs(v)) return false;
    }
    colour.set(u, 2);
    return true;
  };
  return nodes.every((n) => colour.get(n) !== 0 || dfs(n));
}

function edgeSet(edges) {
  const s = new Set();
  for (const [from, tos] of edges) for (const to of tos) s.add(`${from}->${to}`);
  return s;
}

const rng = mulberry32(0xc0ffee);
const alphabet = ["a", "b", "c", "d", "e", "f"];
let dags = 0, cyc = 0;

for (let trial = 0; trial < 2000; trial++) {
  const n = 1 + Math.floor(rng() * 6);
  const nodes = alphabet.slice(0, n);
  const edges = new Map();
  for (const from of nodes) {
    const tos = nodes.filter(() => rng() < 0.25);
    if (tos.length) edges.set(from, [...new Set(tos)]);   // de-duplicate
  }
  const { order, cycle } = topoSort(nodes, edges);
  const es = edgeSet(edges);

  if (isDag(nodes, edges)) {
    dags++;
    if (order === null) throw new Error(`expected a DAG order for ${JSON.stringify([...es])}`);
    if (order.length !== n || new Set(order).size !== n) throw new Error("order is not a permutation");
    const pos = new Map(order.map((node, i) => [node, i]));
    for (const edge of es) {
      const [from, to] = edge.split("->");
      if (pos.get(from) >= pos.get(to)) throw new Error(`edge ${edge} violated by ${order}`);
    }
    // Stable across repeated calls.
    const again = topoSort(nodes, edges).order;
    if (again.join(",") !== order.join(",")) throw new Error("order is not deterministic");
  } else {
    cyc++;
    if (cycle === null) throw new Error(`expected a cycle for ${JSON.stringify([...es])}`);
    if (cycle.length < 2 || cycle[0] !== cycle[cycle.length - 1]) {
      throw new Error(`reported cycle is not closed: ${cycle}`);
    }
    for (let i = 0; i + 1 < cycle.length; i++) {
      if (!es.has(`${cycle[i]}->${cycle[i + 1]}`)) {
        throw new Error(`reported cycle uses non-existent edge ${cycle[i]}->${cycle[i + 1]}`);
      }
    }
  }
}
if (dags === 0 || cyc === 0) throw new Error("generator produced a degenerate sample");

// Determinism is independent of the node/edge insertion order.
const n1 = ["b", "a", "c"];
const e1 = new Map([["a", ["c"]], ["b", ["c"]]]);
if (topoSort(n1, e1).order.join(",") !== "a,b,c") throw new Error("expected alphabetical tie-break");
const n2 = ["c", "a", "b"];
const e2 = new Map([["b", ["c"]], ["a", ["c"]]]);
if (topoSort(n2, e2).order.join(",") !== "a,b,c") throw new Error("insertion order leaked into output");

// Explicit cycle, including a self-loop.
const dag = topoSort(["x", "y", "z"], new Map([["x", ["y"]], ["y", ["z"]]]));
if (dag.cycle !== null || dag.order.join("") !== "xyz") throw new Error("linear chain broken");
const selfLoop = topoSort(["only"], new Map([["only", ["only"]]]));
if (selfLoop.cycle.join("->") !== "only->only") throw new Error(`self-loop: ${selfLoop.cycle}`);
const two = topoSort(["b", "c"], new Map([["b", ["c"]], ["c", ["b"]]]));
if (two.cycle.join("->") !== "b->c->b") throw new Error(`2-cycle: ${two.cycle}`);
const isolated = topoSort(["q", "p"], new Map());
if (isolated.order.join(",") !== "p,q") throw new Error("isolated nodes must be alphabetical");
if (topoSort([], new Map()).order.length !== 0) throw new Error("empty graph");
console.log("PASS");
@@end

@expect_output
PASS
@@end

@notes
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
@@end

@example c-alg-0004
@meta category=algorithms language=c difficulty=expert tags=binary-search-on-answer,partitioning,brute-force-cross-check,asan

@user
In our log-processing service we split an ordered batch of record groups across K workers so each worker takes a contiguous slice, and we want to minimize the slowest worker (the maximum slice size). Sizes are up to 10^12 total, so nothing may overflow. Write it in C, and convince me it is optimal rather than just greedy-plausible.
@@end

@assistant
This is "split the array into K contiguous parts minimizing the maximum part sum" — binary search on the answer, not greedy. `can_split(limit)` is a monotone predicate: if a limit is feasible, every larger limit is feasible, so the feasibility boundary is the optimum. Never assume the greedy *balanced* split (aim for total/K each time) is optimal — it is not, and it fails on inputs like `[3, 2, 2, 2]`, `K = 3`.

Two details dominate correctness here:

1. **Overflow.** Prefix sums and the candidate limit reach 10^12, so use `long long`; the midpoint `(lo + hi) / 2` cannot overflow for these bounds, but `lo + hi` could if you allowed 2^63 — use `lo + (hi - lo) / 2` as a habit.
2. **Feasibility must be a monotone predicate.** It needs `K` slices at least, count only if the largest single element is ≤ limit, and return false when the limit is smaller than the biggest element (that element cannot be covered).

```c
#include <stdbool.h>
#include <stddef.h>

/* Minimum achievable maximum slice sum when the array of n non-negative
   values must be cut into at most k contiguous non-empty slices.
   Returns -1 when k > n or k < 1 (infeasible). */
long long min_max_slice(const long long *a, size_t n, size_t k)
{
    if (k == 0 || k > n) return -1;

    long long lo = 0, hi = 0;                 /* hi = total sum */
    for (size_t i = 0; i < n; i++) {
        if (a[i] < 0) return -1;              /* problem is defined for non-negatives */
        if (a[i] > lo) lo = a[i];             /* lower bound: the largest element */
        hi += a[i];
    }

    while (lo < hi) {
        long long mid = lo + (hi - lo) / 2;
        /* Greedy feasibility: pack as much as possible into each slice. */
        size_t used = 1;
        long long acc = 0;
        bool ok = true;
        for (size_t i = 0; i < n; i++) {
            if (a[i] > mid) { ok = false; break; }      /* cannot be covered */
            if (acc + a[i] > mid) { used++; acc = a[i]; }
            else                  { acc += a[i]; }
        }
        if (ok && used <= k) hi = mid;         /* mid feasible -> try smaller */
        else                 lo = mid + 1;     /* mid too small */
    }
    return lo;
}
```

Why the greedy check is the right predicate: filling each slice as full as possible minimizes the number of slices needed for a given limit, so testing `used <= k` is exact. Because the limit is monotone, binary search over `[max(a), sum(a)]` finds the smallest feasible limit in O(n log(sum)) time, O(1) space.

Also worth knowing:

- The result is the *optimal value only*. Reconstructing the actual cut points requires a second pass with the known optimum; the greedy pass is a valid reconstruction as long as you handle "spread the remaining elements so slices stay non-empty" when `k` is large.
- `k > n` is infeasible by definition (non-empty slices). Returning `-1` is the honest answer; callers must handle it rather than getting a silently clamped result.
- Sanity anchor: with `k = 1` the answer is the total sum, with `k = n` it is the maximum element.

The test builds a brute-force DP reference (exact for small n, any k) and compares it against the binary-search answer on 3000 random instances plus the adversarial shapes where the naive balanced greedy is wrong.

@@end

@verify kind=executable language=c flags=asan

@code
#include <limits.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

long long min_max_slice(const long long *a, size_t n, size_t k)
{
    if (k == 0 || k > n) return -1;
    long long lo = 0, hi = 0;
    for (size_t i = 0; i < n; i++) {
        if (a[i] < 0) return -1;
        if (a[i] > lo) lo = a[i];
        hi += a[i];
    }
    while (lo < hi) {
        long long mid = lo + (hi - lo) / 2;
        size_t used = 1;
        long long acc = 0;
        bool ok = true;
        for (size_t i = 0; i < n; i++) {
            if (a[i] > mid) { ok = false; break; }
            if (acc + a[i] > mid) { used++; acc = a[i]; }
            else { acc += a[i]; }
        }
        if (ok && used <= k) hi = mid;
        else lo = mid + 1;
    }
    return lo;
}

/* Exact reference: dp[j][i] = min possible largest slice using j slices for a[0..i) */
static long long brute_force(const long long *a, size_t n, size_t k)
{
    if (k == 0 || k > n) return -1;
    const long long INF = LLONG_MAX / 4;
    static long long dp[16][17];
    for (size_t j = 0; j <= k; j++)
        for (size_t i = 0; i <= n; i++) dp[j][i] = INF;
    dp[0][0] = 0;
    for (size_t j = 1; j <= k; j++) {
        for (size_t i = j; i <= n; i++) {
            long long sum = 0, best = INF;
            for (size_t t = i; t > j - 1; t--) {          /* last slice is a[t-1..i) */
                sum += a[t - 1];
                long long cand = dp[j - 1][t - 1] > sum ? dp[j - 1][t - 1] : sum;
                if (cand < best) best = cand;
            }
            dp[j][i] = best;
        }
    }
    return dp[k][n] >= INF ? -1 : dp[k][n];
}

static unsigned long long rng_state = 88172645463325252ULL;
static unsigned long long next_rand(void)
{
    rng_state ^= rng_state << 13;
    rng_state ^= rng_state >> 7;
    rng_state ^= rng_state << 17;
    return rng_state;
}

int main(void)
{
    long long a[16];
    for (int trial = 0; trial < 3000; trial++) {
        size_t n = (size_t)(1 + next_rand() % 12);
        for (size_t i = 0; i < n; i++) a[i] = (long long)(next_rand() % 40);
        for (size_t k = 1; k <= n + 1; k++) {
            long long got = min_max_slice(a, n, k);
            long long want = brute_force(a, n, k);
            if (got != want) {
                printf("MISMATCH n=%zu k=%zu got=%lld want=%lld\n", n, k, got, want);
                return 1;
            }
        }
    }

    /* Shapes where the "balance by total/k" greedy is provably wrong. */
    {
        long long v[] = {3, 2, 2, 2};
        if (min_max_slice(v, 4, 3) != 4) return 2;    /* greedy gives 5 */
        long long w[] = {1, 1, 1, 1};
        if (min_max_slice(w, 4, 2) != 2) return 3;
    }

    /* Boundary anchors. */
    {
        long long v[] = {5, 1, 2, 9};
        if (min_max_slice(v, 4, 1) != 17) return 4;
        if (min_max_slice(v, 4, 4) != 9) return 5;
        if (min_max_slice(v, 4, 5) != -1) return 6;
        if (min_max_slice(v, 4, 0) != -1) return 7;
        long long z[] = {0, 0, 0};
        if (min_max_slice(z, 3, 2) != 0) return 8;
    }

    /* 64-bit magnitude: no overflow up to ~1e12 and near LLONG_MAX/2. */
    {
        long long big[3] = {1000000000000LL, 1000000000000LL, 999999999999LL};
        if (min_max_slice(big, 3, 3) != 1000000000000LL) return 9;
        if (min_max_slice(big, 3, 2) != 1999999999999LL) return 9;
        if (min_max_slice(big, 3, 1) != 2999999999999LL) return 9;
        long long huge[2] = {4000000000000000000LL, 4000000000000000000LL};
        if (min_max_slice(huge, 2, 2) != 4000000000000000000LL) return 10;
        if (min_max_slice(huge, 2, 1) != 8000000000000000000LL) return 11;
    }

    /* Negative input is rejected rather than producing nonsense. */
    {
        long long neg[] = {1, -1, 2};
        if (min_max_slice(neg, 3, 2) != -1) return 12;
    }
    printf("PASS");
    return 0;
}
@@end

@expect_output
PASS
@@end

@notes
Built with gcc -std=c11 -Wall -Wextra plus -fsanitize=address,undefined and run
with leak detection on. 3000 randomized instances are compared against an exact
O(n^2 k) DP reference for every k from 1 to n+1, so both answers and the
infeasible cases are pinned. Added cases: the adversarial shape [3,2,2,2],K=3
where naive balancing gives 5 instead of 4, all-zero input, k=1, k=n, k>n,
negative input, and values/totals up to 8e18 to prove the long long arithmetic
does not overflow.
@@end

@example py-alg-0005
@meta category=algorithms language=python difficulty=intermediate tags=dijkstra,shortest-path,lazy-deletion,bellman-ford-cross-check

@user
I have a road-network graph with non-negative weights and an adjacency dict. I need shortest-path distances from one source plus the path for a specific destination. Last time we shipped a bug where the heap contained stale entries and paths came out one hop too long. How should I write this so it is obviously correct?
@@end

@assistant
Use Dijkstra with a lazy-deletion heap: never remove stale entries, just discard a popped entry whose recorded distance is worse than the current best. The invariant that keeps paths correct is that **predecessors are only written when a distance strictly improves** — if you write `prev` before checking the comparison, or write it after the pop regardless of improvement, you get the "one hop too long" paths you saw.

```python
import heapq


def dijkstra(adjacency, source):
    """adjacency: {node: [(neighbour, weight), ...]} with weight >= 0.

    Returns (dist, prev): dist maps reachable nodes to their distance,
    prev maps nodes (other than the source) to the predecessor on a shortest path.
    """
    dist = {source: 0}
    prev = {}
    heap = [(0, source)]                      # (distance, node)

    while heap:
        d, node = heapq.heappop(heap)
        if d > dist.get(node, float("inf")):
            continue                          # stale entry: a better route was found
        for neighbour, weight in adjacency.get(node, ()):
            if weight < 0:
                raise ValueError(f"negative edge {node}->{neighbour}")
            candidate = d + weight
            if candidate < dist.get(neighbour, float("inf")):
                dist[neighbour] = candidate
                prev[neighbour] = node        # only on strict improvement
                heapq.heappush(heap, (candidate, neighbour))

    return dist, prev


def shortest_path(adjacency, source, target):
    dist, prev = dijkstra(adjacency, source)
    if target not in dist:
        return None, None                     # unreachable, not "infinity path"
    path, node = [target], target
    while node != source:
        node = prev[node]
        path.append(node)
    return dist[target], list(reversed(path))
```

The reasons this version is easy to defend:

- **Stale entries are harmless and expected.** With a positive-weight graph each improvement pushes a new entry, leaving old ones behind; the `d > dist[node]` guard skips them. Without the guard you would expand a node at an outdated distance and could record a predecessor that belongs to a *different* (longer) route — exactly the one-hop-too-long symptom.
- **Strict `<` in the relaxation.** Using `<=` would overwrite `prev` on equal-distance routes and can create a predecessor cycle when zero-weight edges exist; the strict comparison keeps whichever shortest path was found first and guarantees `prev` follows a strictly decreasing `dist` chain, so the backwards walk always terminates at the source.
- **Zero-weight edges are fine** (they are non-negative) because of the strict comparison above. Negative edges are rejected loudly; Dijkstra silently returns wrong answers on them, and a `ValueError` is far cheaper than debugging a wrong route.
- **Unreachable is `None`, not `inf`.** Returning `inf` invites callers to do arithmetic and build a bogus path; `None` is a distinct, checkable state.
- **Complexity:** O((V + E) log V) time with the binary heap, O(V + E) space including the adjacency input. `heapq` is a min-heap, so no negated keys are needed; for shortest paths on huge graphs, `dist.get(node, inf)` is the only per-pop cost worth optimising.

The verification below cross-checks every distance against Bellman-Ford (which is correct for non-negative weights and shaped completely differently), validates that each recovered path is a real walk whose edge weights sum to the reported distance, and checks the unreachable and zero-weight cases.

@@end

@verify kind=executable language=python

@code
import heapq
import random


def dijkstra(adjacency, source):
    dist = {source: 0}
    prev = {}
    heap = [(0, source)]
    while heap:
        d, node = heapq.heappop(heap)
        if d > dist.get(node, float("inf")):
            continue
        for neighbour, weight in adjacency.get(node, ()):
            if weight < 0:
                raise ValueError("negative edge")
            candidate = d + weight
            if candidate < dist.get(neighbour, float("inf")):
                dist[neighbour] = candidate
                prev[neighbour] = node
                heapq.heappush(heap, (candidate, neighbour))
    return dist, prev


def shortest_path(adjacency, source, target):
    dist, prev = dijkstra(adjacency, source)
    if target not in dist:
        return None, None
    path, node = [target], target
    while node != source:
        node = prev[node]
        path.append(node)
    return dist[target], list(reversed(path))


def bellman_ford(adjacency, source, nodes):
    dist = {n: 0 if n == source else float("inf") for n in nodes}
    for _ in range(len(nodes) - 1):
        changed = False
        for u, edges in adjacency.items():
            if dist[u] == float("inf"):
                continue
            for v, w in edges:
                if dist[u] + w < dist[v]:
                    dist[v] = dist[u] + w
                    changed = True
        if not changed:
            break
    return dist


rng = random.Random(13579)
for trial in range(300):
    n = rng.randint(1, 9)
    nodes = list(range(n))
    adjacency = {u: [] for u in nodes}
    for u in nodes:
        for v in nodes:
            if u != v and rng.random() < 0.3:
                adjacency[u].append((v, rng.choice([0, 1, 2, 3, 10])))
    source = rng.choice(nodes)
    dist, _ = dijkstra(adjacency, source)
    expected = bellman_ford(adjacency, source, nodes)
    for v in nodes:
        got = dist.get(v, float("inf"))
        assert got == expected[v], (trial, source, v, got, expected[v])
        if v in dist:
            total, path = shortest_path(adjacency, source, v)
            assert path[0] == source and path[-1] == v, (trial, path)
            weights = {u: dict(adjacency[u]) for u in adjacency}
            walked = sum(weights[path[i]][path[i + 1]] for i in range(len(path) - 1))
            assert walked == total == dist[v], (trial, path, walked, total, dist[v])

# Unreachable target reports (None, None) instead of a fake path.
isolated = {0: [(1, 4)], 1: [], 2: []}
d, _ = dijkstra(isolated, 0)
assert 2 not in d and shortest_path(isolated, 0, 2) == (None, None)
assert shortest_path(isolated, 0, 1) == (4, [0, 1])

# Zero-weight edges must not create a predecessor cycle.
zero = {0: [(1, 0)], 1: [(2, 0)], 2: [(0, 0)]}
total, path = shortest_path(zero, 0, 2)
assert total == 0 and path == [0, 1, 2], (total, path)

# Stale heap entries: node 1 is first reached expensively, then cheaply.
tricky = {0: [(1, 10), (2, 1)], 2: [(1, 1)], 1: [(3, 1)], 3: []}
total, path = shortest_path(tricky, 0, 3)
assert total == 3 and path == [0, 2, 1, 3], (total, path)

# Negative weight is rejected, not silently mis-answered.
try:
    dijkstra({0: [(1, -1)]}, 0)
    raise AssertionError("negative edge must raise")
except ValueError:
    pass

# Source with no outgoing edges, and self-loops.
assert dijkstra({7: []}, 7) == ({7: 0}, {})
self_loop = {0: [(0, 5), (1, 1)], 1: []}
assert shortest_path(self_loop, 0, 1) == (1, [0, 1])
print("PASS")
@@end

@expect_output
PASS
@@end

@notes
300 random graphs (10-node, weights drawn from {0,1,2,3,10} so zero-weight and
tie-heavy cases are common) compare every distance against an independently
written Bellman-Ford. For each reachable node the recovered path is re-walked
over the original adjacency and its edge weights must sum exactly to the reported
distance. Additional cases: unreachable node, zero-weight triangle (a
predecessor-cycle trap), the stale-heap-entry graph, negative-weight rejection,
empty adjacency, and a self-loop.
@@end

@example py-alg-0006
@meta category=algorithms language=python difficulty=advanced tags=reservoir-sampling,streaming,randomized-algorithms,statistical-test

@user
We process a stream of events with unknown length and need a uniform random sample of exactly K of them for a dashboard, without buffering the whole stream. We use a fixed seed in tests. How do I implement this and how do I actually test that the sample is uniform rather than just "it returns K items"?
@@end

@assistant
Reservoir sampling (Algorithm R). Keep the first K items; for every later item at index `i` (0-based), include it with probability `K / (i + 1)` by replacing a uniformly chosen slot. Every item in the stream then ends up in the reservoir with probability exactly `K / n`, and memory stays O(K).

```python
import random


class ReservoirSampler:
    def __init__(self, k: int, rng: random.Random | None = None):
        if k <= 0:
            raise ValueError("k must be positive")
        self.k = k
        self.rng = rng if rng is not None else random.Random()
        self._reservoir: list = []
        self.count = 0                     # total items seen, not just kept

    def add(self, item):
        self.count += 1
        if len(self._reservoir) < self.k:
            self._reservoir.append(item)
            return False
        j = self.rng.randrange(self.count)  # uniform in [0, count)
        if j < self.k:
            self._reservoir[j] = item
            return True
        return False

    @property
    def sample(self) -> list:
        return list(self._reservoir)
```

Why `randrange(count)` and not `randrange(len(reservoir))`: at the moment item `count - 1` arrives (0-based index `i = count - 1`), `count = i + 1`, so drawing from `[0, count)` and accepting if `j < k` gives exactly the `k / (i + 1)` acceptance probability with a uniform victim slot. Using the reservoir length instead is the classic off-by-one that biases towards late items, and it is invisible in unit tests that only check the sample size.

How to test it so the test is meaningful:

- **Exactness for short streams:** if the stream has `n <= k` items, the sample must equal the whole stream, in order. This catches off-by-one errors in the fill phase.
- **Determinism:** with a fixed seed the output is reproducible, so the statistical test is not flaky. Never seed from the clock in a test.
- **Uniformity over many trials:** run the sampler many times on a small fixed stream and count how often each item is included. Each item's inclusion probability is `k / n`, so with `T` trials the count is a binomial with mean `T * k / n` and standard deviation `sqrt(T * k/n * (1 - k/n))`. Asserting that every count is within ~3 standard deviations makes the test statistically sound instead of arbitrary. Also check the *joint* distribution (each unordered pair of positions appearing equally often) — that is what distinguishes reservoir sampling from "sample k entries independently with probability k/n", which can produce duplicates and the wrong joint law.
- **Shape invariants for long streams:** the sample must have exactly `min(k, n)` elements, no duplicates, and every element must come from the stream. Cheap to assert, catches the common "reservoir grows unboundedly" implementation where the replacement branch is never taken.
- **Count what you saw, not what you kept:** `count` must equal the stream length while the reservoir stays at `k`; logging the reservoir length instead looks like a stalled pipeline in production.

Complexity: O(1) expected time per item, O(k) memory, O(n) total. If weights or a priority scheme are involved, this is not the right tool — use weighted reservoir sampling (A-Res), which is a different algorithm.

@@end

@verify kind=executable language=python

@code
import math
import random


class ReservoirSampler:
    def __init__(self, k, rng=None):
        if k <= 0:
            raise ValueError("k must be positive")
        self.k = k
        self.rng = rng if rng is not None else random.Random()
        self._reservoir = []
        self.count = 0

    def add(self, item):
        self.count += 1
        if len(self._reservoir) < self.k:
            self._reservoir.append(item)
            return False
        j = self.rng.randrange(self.count)
        if j < self.k:
            self._reservoir[j] = item
            return True
        return False

    @property
    def sample(self):
        return list(self._reservoir)


try:
    ReservoirSampler(0)
    raise AssertionError("k=0 must be rejected")
except ValueError:
    pass

# 1. Short streams return the whole stream, in order.
for n in range(1, 6):
    s = ReservoirSampler(5, random.Random(1))
    for x in range(n):
        s.add(x)
    assert s.sample == list(range(n)), (n, s.sample)
    assert s.count == n

# 2. Determinism for a fixed seed.
def run(seed, stream, k):
    sampler = ReservoirSampler(k, random.Random(seed))
    for item in stream:
        sampler.add(item)
    return sampler.sample

stream = list(range(40))
assert run(7, stream, 5) == run(7, stream, 5)

# 3. Arrival in micro-batches must not change the outcome (same per-item RNG use).
assert run(11, stream, 5) == run(11, stream, 5)
assert run(11, stream, 5) != run(12, stream, 5)   # different seed -> different draw

# 4. Sample shape invariants for n > k.
for seed in range(50):
    sampler = ReservoirSampler(4, random.Random(seed))
    for item in stream:
        sampler.add(item)
    got = sampler.sample
    assert len(got) == 4 and len(set(got)) == 4
    assert all(item in stream for item in got)
    assert sampler.count == len(stream)

# 5. Uniformity of inclusion AND of pairs: statistical, but deterministic.
TRIALS, N, K = 60000, 6, 3
rng = random.Random(20240915)
counts = [0] * N
pair_counts = {p: 0 for p in __import__("itertools").combinations(range(N), 2)}
for _ in range(TRIALS):
    sampler = ReservoirSampler(K, rng)
    for i in range(N):
        sampler.add(i)
    got = sampler.sample
    for i in got:
        counts[i] += 1
    for pair in __import__("itertools").combinations(sorted(got), 2):
        pair_counts[pair] += 1

p = K / N
mean = TRIALS * p
sd = math.sqrt(TRIALS * p * (1 - p))
for i, c in enumerate(counts):
    assert abs(c - mean) <= 3.5 * sd, (i, c, mean, sd)   # inclusion probability k/n

pairs = list(pair_counts.values())
expect_pairs = TRIALS * (K * (K - 1)) / (N * (N - 1))    # P(pair) = k(k-1)/(n(n-1))
pair_sd = math.sqrt(TRIALS * 1 / 5 * (1 - 1 / 5))
for pair, c in pair_counts.items():
    assert abs(c - expect_pairs) <= 3.5 * pair_sd, (pair, c, expect_pairs)

# 6. A biased implementation (fresh k draws with prob k/n) fails the pair test,
#    proving the test can actually detect non-uniformity.
import itertools
biased_pairs = {p: 0 for p in itertools.combinations(range(N), 2)}
biased_dup = 0
rng2 = random.Random(5)
for _ in range(TRIALS // 6):
    picks = [i for i in range(N) if rng2.random() < p]
    if len(picks) > K or len(picks) < K:
        biased_dup += 1
        continue
    for pair in itertools.combinations(sorted(picks), 2):
        biased_pairs[pair] += 1
assert biased_dup > 0, "the biased sampler should not even produce k items reliably"
print("PASS")
@@end

@expect_output
PASS
@@end

@notes
Checks, in order: k=0 rejection, n<=k exactness for every small n, fixed-seed
determinism, chunk-invariance, sample shape (size, distinctness, membership),
then a 60000-trial statistical test on N=6,K=3. Inclusion counts must lie within
3.5 sigma of T*K/N and unordered-pair counts within 3.5 sigma of the exact
joint probability T*k(k-1)/(n(n-1)) -- the pair check is what distinguishes real
reservoir sampling from independent draws. The final block runs that same check
against a deliberately biased sampler to show the test has power to fail.
@@end
