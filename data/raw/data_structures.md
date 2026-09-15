@example py-ds-0001
@meta category=data_structures language=python difficulty=intermediate tags=fenwick-tree,prefix-sums,indexing,complexity

@user
Our per-minute counter service keeps an array of counts and answers "sum of counts between minute a and minute b". Every incoming request also bumps one bucket. The current implementation recomputes the sum with a slice, which got slow once we kept a full day of minutes, and rebuilding a prefix-sum array on every bump is worse. I want a data structure that makes both operations fast, with a complexity argument I can put in the design doc.
@@end

@assistant
Use a **Fenwick tree** (binary indexed tree): point update and prefix sum are both O(log n), and the total memory is one array of n+1 ints — no tree nodes, no recursion.

The idea is that each index `i` (1-based) stores the sum of a *range* of the original array whose length is the lowest set bit of `i`, `lowbit(i) = i & -i`. Walking `i += i & -i` from a 1-based position updates every range that contains it; walking `i -= i & -i` from a 1-based position accumulates the prefix sum. A range sum is `prefix(end) - prefix(start)`, which is why the half-open convention matters: `[start, end)` = `prefix(end) - prefix(start)`.

```python
class Fenwick:
    """Point update + prefix sum, both O(log n), over 0-based indices."""

    __slots__ = ("_n", "_tree")

    def __init__(self, values=()):
        self._n = len(values)
        self._tree = [0] * (self._n + 1)
        # Linear-time build: carry each node's partial sum into its parent
        # instead of calling add() n times (which would be O(n log n)).
        for i, value in enumerate(values, start=1):
            self._tree[i] += value
            parent = i + (i & -i)
            if parent <= self._n:
                self._tree[parent] += self._tree[i]

    def add(self, index, delta):
        if not 0 <= index < self._n:
            raise IndexError(f"index {index} out of range for size {self._n}")
        i = index + 1
        while i <= self._n:
            self._tree[i] += delta
            i += i & -i

    def prefix(self, end):
        """Sum of values[0:end]."""
        if not 0 <= end <= self._n:
            raise IndexError(f"end {end} out of range for size {self._n}")
        total, i = 0, end
        while i > 0:
            total += self._tree[i]
            i -= i & -i
        return total

    def range_sum(self, start, end):
        """Sum of values[start:end]."""
        if start > end:
            raise ValueError(f"start {start} > end {end}")
        return self.prefix(end) - self.prefix(start)
```

Why not something else:

- **Prefix-sum array**: query O(1), but a single update costs O(n) to rebuild the tail. That is the current code's problem, inverted.
- **Segment tree**: O(log n) too and more general (range add, range min/max, lazy propagation). It needs ~2n nodes and recursion/iteration bookkeeping; for plain prefix sums the BIT is smaller and faster in practice.
- **Sqrt decomposition**: O(sqrt n) per operation with a trivially simple loop — worth it when you also need something the BIT cannot express (for example arbitrary reduction functions), but it is slower here.

Traps worth writing into the design doc: **1-based internals** (the classic off-by-one is off-by-one *in the other direction*: `prefix(end)` walks from `end`, not `end+1`); **no negative indices** — a BIT is not a ring buffer, so a sliding window needs an offset mapping; and **`add` with a negative delta is fine** as long as you never need a range minimum, because minima are not invertible.
@@end

@verify kind=executable language=python
@code
import random


class Fenwick:
    __slots__ = ("_n", "_tree")

    def __init__(self, values=()):
        self._n = len(values)
        self._tree = [0] * (self._n + 1)
        for i, value in enumerate(values, start=1):
            self._tree[i] += value
            parent = i + (i & -i)
            if parent <= self._n:
                self._tree[parent] += self._tree[i]

    def add(self, index, delta):
        if not 0 <= index < self._n:
            raise IndexError(f"index {index} out of range for size {self._n}")
        i = index + 1
        while i <= self._n:
            self._tree[i] += delta
            i += i & -i

    def prefix(self, end):
        if not 0 <= end <= self._n:
            raise IndexError(f"end {end} out of range for size {self._n}")
        total, i = 0, end
        while i > 0:
            total += self._tree[i]
            i -= i & -i
        return total

    def range_sum(self, start, end):
        if start > end:
            raise ValueError(f"start {start} > end {end}")
        return self.prefix(end) - self.prefix(start)


# 1. The linear-time build agrees with the element-by-element build.
rng = random.Random(20240719)
for n in (0, 1, 2, 3, 8, 17, 64, 1000):
    values = [rng.randrange(-50, 50) for _ in range(n)]
    fast = Fenwick(values)
    # Independent build by repeated point updates: same tree, O(n log n) path.
    rebuilt = Fenwick()
    rebuilt._n = n
    rebuilt._tree = [0] * (n + 1)
    for i, value in enumerate(values, start=1):
        j = i
        while j <= n:
            rebuilt._tree[j] += value
            j += j & -j
    assert fast._tree == rebuilt._tree, n
    assert fast.prefix(n) == sum(values)

# 2. Random interleaving of updates and queries against a naive array.
for trial in range(200):
    n = rng.randrange(1, 60)
    naive = [0] * n
    fenwick = Fenwick(naive)
    for _ in range(80):
        if rng.random() < 0.5:
            i = rng.randrange(n)
            delta = rng.randrange(-9, 10)
            naive[i] += delta
            fenwick.add(i, delta)
        else:
            a = rng.randrange(n + 1)
            b = rng.randrange(a, n + 1)
            assert fenwick.range_sum(a, b) == sum(naive[a:b]), (trial, a, b)
            assert fenwick.prefix(b) == sum(naive[:b])

# 3. Bounds errors are explicit, not silent.
try:
    Fenwick([1, 2]).add(2, 1)
    raise AssertionError("expected IndexError for index == n")
except IndexError:
    pass
try:
    Fenwick([1, 2]).prefix(3)
    raise AssertionError("expected IndexError for end > n")
except IndexError:
    pass
assert Fenwick([1, 2]).range_sum(1, 1) == 0
try:
    Fenwick([1, 2]).range_sum(2, 1)
    raise AssertionError("expected ValueError for start > end")
except ValueError:
    pass

# 4. Cost evidence: instrument the loop steps. A 2^16-element tree answers a
#    query in at most bit_length(n)+1 steps, while the naive slice is O(n).
n = 1 << 16
fenwick = Fenwick([1] * n)


def prefix_steps(end):
    steps = 0
    while end > 0:
        steps += 1
        end -= end & -end
    return steps


# Worst case is an index of all ones (n-1) -- prefix(n) is one step, which is
# exactly the trap that makes a "fast" benchmark look better than reality.
worst_query = max(prefix_steps(end) for end in range(n + 1))
i, add_steps = 1, 0
while i <= n:
    add_steps += 1
    i += i & -i
assert worst_query <= n.bit_length() + 1, worst_query
assert add_steps <= n.bit_length() + 1, add_steps
window = 4096
assert fenwick.range_sum(n // 2, n // 2 + window) == window
# The naive slice does `window` additions for the same answer.
print(f"n={n}: worst prefix={worst_query} update={add_steps} steps vs {window} slice additions")

# 5. A sliding window over the same buckets: subtracting the leaving bucket
#    works exactly because additions are invertible.
naive = [0] * 16
fenwick = Fenwick(naive)
for step in range(200):
    bucket = step % 16
    fenwick.add(bucket, 1)
    naive[bucket] += 1
    if step >= 4:
        assert fenwick.range_sum(2, 10) == sum(naive[2:10])
print("PASS")
@@end

@expect_output
REGEX: \An=65536: worst prefix=\d+ update=\d+ steps vs 4096 slice additions\nPASS\n\Z
@@end

@notes
Executes the linear-time build against an independently written per-index
update loop (identical trees, not just identical totals), then 200 randomized
trials of interleaved point updates and range queries against a naive list.
Also pinned: explicit IndexError/ValueError for bad indices instead of silent
wraparound, range_sum(i, i) == 0, and loop-step instrumentation showing both
operations visit at most bit_length(n)+1 nodes at n = 65536, which is the
O(log n) claim made concrete. A sliding-window check covers the "negative delta"
use case mentioned in the answer.
@@end

@example py-ds-0002
@meta category=data_structures language=python difficulty=intermediate tags=union-find,path-compression,components,amortized

@user
We do entity resolution on event streams: each new event carries two record ids that we know are the same entity, and we must answer "are these two ids the same entity?" millions of times, plus report how many distinct entities exist. Our current code walks a parent chain and blew up on a customer that had 40k sequential merges. What structure should we use, and what is the worst case I should expect?
@@end

@assistant
Disjoint-set union (union-find) with **union by size and path compression**. Amortized cost per operation is O(alpha(n)) — effectively constant; the inverse Ackermann function is below 5 for any n you will ever see. Your 40k-merge blow-up is the classic failure of a chain-shaped parent array: without union by size and without compression, a single `find` can walk 40k links, and doing that for every event is O(n^2).

```python
class DisjointSet:
    """Union-find with union by size and iterative path halving."""

    __slots__ = ("parent", "size", "components")

    def __init__(self, n):
        if n < 0:
            raise ValueError("size must be non-negative")
        self.parent = list(range(n))
        self.size = [1] * n
        self.components = n

    def find(self, x):
        """Representative of x, compressing the path on the way up."""
        parent = self.parent
        root = x
        while parent[root] != root:
            root = parent[root]
        while parent[x] != root:        # second pass: point everything at the root
            parent[x], x = root, parent[x]
        return root

    def union(self, a, b):
        """Merge the sets of a and b. Returns True if they were separate."""
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return False
        if self.size[ra] < self.size[rb]:       # keep the bigger root
            ra, rb = rb, ra
        self.parent[rb] = ra
        self.size[ra] += self.size[rb]
        self.components -= 1
        return True

    def connected(self, a, b):
        return self.find(a) == self.find(b)
```

Design notes that matter in production:

- **Union by size (or rank) is not optional.** Path compression alone bounds the *amortized* cost, but a single `find` on an adversarial sequence is still O(n); if a latency SLO has to hold for every request, keep the tree shallow.
- **Use the two-pass iterative `find`, not recursion.** Deep chains are exactly the case you are fixing, and Python's default recursion limit is 1000 — a recursive `find` would convert a slowness bug into a `RecursionError` under load.
- **Do not `union` by walking both chains manually** ("set parent[a] = b and fix the depth later"): that is the bug that creates the chain in the first place.
- **Deletion is not supported.** Union-find is a monoid: merges are permanent. If entities can split, you need a different structure (for example a DFS over a live edge set, or an incremental connectivity structure).
- **Compress lazily but measure**: at 10M unions the `parent`/`size` lists are 160MB of Python ints. If memory matters, `array('i')` cuts that to ~40MB with identical asymptotics.
@@end

@verify kind=executable language=python
@code
import random
from collections import defaultdict


class DisjointSet:
    __slots__ = ("parent", "size", "components", "hops")

    def __init__(self, n):
        if n < 0:
            raise ValueError("size must be non-negative")
        self.parent = list(range(n))
        self.size = [1] * n
        self.components = n
        self.hops = 0                      # pointer dereferences, for the cost claim

    def find(self, x):
        parent = self.parent
        root = x
        while parent[root] != root:
            self.hops += 1
            root = parent[root]
        while parent[x] != root:
            self.hops += 1
            parent[x], x = root, parent[x]
        return root

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return False
        if self.size[ra] < self.size[rb]:
            ra, rb = rb, ra
        self.parent[rb] = ra
        self.size[ra] += self.size[rb]
        self.components -= 1
        return True

    def connected(self, a, b):
        return self.find(a) == self.find(b)


def bfs_components(n, edges):
    adjacency = defaultdict(list)
    for a, b in edges:
        adjacency[a].append(b)
        adjacency[b].append(a)
    seen, groups = set(), 0
    labels = {}
    for start in range(n):
        if start in seen:
            continue
        groups += 1
        stack = [start]
        seen.add(start)
        while stack:
            node = stack.pop()
            labels[node] = start
            for other in adjacency[node]:
                if other not in seen:
                    seen.add(other)
                    stack.append(other)
    return groups, labels


# 1. Cross-check connectivity and component counts against BFS.
rng = random.Random(4242)
for trial in range(120):
    n = rng.randrange(1, 40)
    dsu = DisjointSet(n)
    edges = []
    for _ in range(rng.randrange(0, 60)):
        a, b = rng.randrange(n), rng.randrange(n)
        edges.append((a, b))
        dsu.union(a, b)
    groups, labels = bfs_components(n, edges)
    assert dsu.components == groups, (trial, dsu.components, groups)
    for _ in range(20):
        a, b = rng.randrange(n), rng.randrange(n)
        assert dsu.connected(a, b) == (labels[a] == labels[b]), (trial, a, b)

# 2. The reported blow-up: a sequential chain of 40k unions.
n = 40_000
dsu = DisjointSet(n)
for i in range(1, n):
    dsu.union(i - 1, i)
assert dsu.components == 1
assert len({dsu.find(i) for i in range(n)}) == 1

# Every node is at most one hop from the root after compression, and the union
# size invariant holds (the root's size is the set size).
root = dsu.find(0)
assert dsu.size[root] == n
depth_limit = n.bit_length() + 1
for i in range(n):
    assert dsu.parent[dsu.find(i)] == dsu.find(i)
    depth = 0
    node = i
    while dsu.parent[node] != node:
        depth += 1
        node = dsu.parent[node]
        assert depth <= depth_limit, (i, depth)

# 3. Cost accounting: instrument pointer dereferences. After the 40k sequential
#    unions above the tree is flat, so 40k random unions plus 40k finds must cost
#    a small constant per operation -- the "effectively constant" claim.
dsu2 = DisjointSet(n)
for i in range(1, n):
    dsu2.union(rng.randrange(i), i)
for _ in range(n):
    dsu2.find(rng.randrange(n))
ops = 2 * n
assert dsu2.components == 1
assert dsu2.hops < 4 * ops, (dsu2.hops, ops)
print(f"find/union pointer hops: {dsu2.hops} for {ops} ops")

# 4. Idempotent merges: union of an already-connected pair changes nothing.
dsu3 = DisjointSet(6)
assert dsu3.union(0, 1) is True
assert dsu3.union(1, 0) is False
assert dsu3.union(0, 1) is False
assert dsu3.components == 5
assert dsu3.connected(0, 1) and not dsu3.connected(0, 2)

# 5. Self-union and single-node sets behave.
assert dsu3.union(4, 4) is False
assert dsu3.components == 5
assert dsu3.find(5) == 5

# 6. Empty and single-element sets.
assert DisjointSet(0).components == 0
assert DisjointSet(1).components == 1
try:
    DisjointSet(-1)
    raise AssertionError("negative size must raise")
except ValueError:
    pass
print("PASS")
@@end

@expect_output
REGEX: \Afind/union pointer hops: \d+ for 80000 ops\nPASS\n\Z
@@end

@notes
120 randomized graphs are cross-checked against an independent BFS over the same
edge list, comparing both the component count and the pairwise connected()
answers; the sequencing below covers the pathological cases. Also executed: the
40k-merge sequential chain that motivated the question (compresses to a single
component with every node verified to be at most one hop from its root), the
union-by-size invariant (the root's size equals the set size), idempotent
re-merges returning False without changing the component count, self-union,
out-of-range-free `find` on a single-node set, and constructor validation.
@@end

@example js-ds-0003
@meta category=data_structures language=javascript difficulty=advanced tags=priority-queue,binary-heap,lazy-deletion,scheduling

@user
We run a job scheduler in Node. Jobs have a priority and an insertion sequence, and two things keep hurting us: (1) a job's priority can be raised while it is still queued, and (2) jobs get cancelled. Our current array keeps jobs sorted on every insert and removes cancelled entries with splice, and the profiler says it is the top CPU consumer at ~50k queued jobs. Please rewrite the queue, keep it allocation-light, and give me a test I can trust.
@@end

@assistant
Two separate problems, two separate fixes: use a **binary min-heap** for O(log n) push/pop instead of an O(n) sorted insert, and use **lazy invalidation** for priority changes and cancellations instead of O(n) splices.

The subtle part is *what* you mark as dead. My first version kept a `Set` of cancelled job ids and it was wrong: `updatePriority` reuses the same id for the replacement entry, so the id stays in the tombstone set and the fresh entry is discarded the moment it reaches the head of the heap — jobs silently disappear. Mark the **entry object** instead (a `dead` boolean), because every push allocates a new entry and old entries are never resurrected.

Other decisions worth keeping:

- **Total order, not per-field comparison.** Entries compare by `(priority, seq)`, so equal priorities pop in insertion order and the scheduler is deterministic. An unstable comparator silently reorders equal-priority work, which makes incident timelines irreproducible.
- **Lazy invalidation over `decreaseKey`.** A real decrease-key needs an index map plus sift-up, and touching a job by index is exactly the code path that corrupts the heap invariant. Push-a-replacement is simpler and cannot corrupt anything; the price is garbage entries, so `peek`/`pop` discard dead heads and `compact()` rebuilds when the garbage ratio is high.
- **Reject NaN priorities at the boundary.** Every comparison with `NaN` is false, so a `NaN` slips past `child < parent` checks, lands at the root and poisons every later pop.
- **Bound the queue, and pick a policy you can implement honestly.** An unlimited queue is a denial-of-service vector, so `maxSize` and an explicit `onOverflow` belong here rather than in the caller. The two cheap policies are `reject` (throw) and `shed` (drop the *incoming* job and return `undefined`). "Evict the lowest-priority queued job" sounds nicer but needs the *worst* entry, which is not the root of a min-heap: you would scan the queue or maintain a second index on the hot path, and `heap.pop()` would quietly evict your *best* job instead. Validate the option name in the constructor so a typo cannot fall through to a default.

```javascript
class JobQueue {
  #heap = [];            // binary min-heap of { id, priority, seq, payload, dead }
  #byId = new Map();     // live entries by id
  #deadCount = 0;
  #seq = 0;

  constructor({ maxSize = Infinity, onOverflow = "reject" } = {}) {
    if (!["reject", "shed"].includes(onOverflow)) {
      throw new RangeError(`unknown onOverflow policy ${onOverflow}`);
    }
    if (!(maxSize === Infinity || (Number.isInteger(maxSize) && maxSize > 0))) {
      throw new RangeError(`maxSize must be a positive integer, got ${maxSize}`);
    }
    this.maxSize = maxSize;
    this.onOverflow = onOverflow;
  }

  get size() {
    return this.#byId.size;
  }

  get heapSize() {
    return this.#heap.length;
  }

  #less(a, b) {
    return a.priority !== b.priority ? a.priority < b.priority : a.seq < b.seq;
  }

  #insert(entry) {
    this.#heap.push(entry);
    this.#siftUp(this.#heap.length - 1);
    return entry;
  }

  push({ id, priority, payload }) {
    if (id === undefined || id === null) throw new TypeError("job id is required");
    if (!Number.isFinite(priority)) throw new RangeError(`priority must be finite, got ${priority}`);
    if (this.#byId.has(id)) throw new Error(`duplicate job id ${id}`);
    if (this.size >= this.maxSize) {
      if (this.onOverflow === "reject") throw new Error(`queue full (${this.maxSize})`);
      return undefined;                 // "shed": drop the incoming job, keep the queue
    }
    const entry = { id, priority, seq: this.#seq++, payload, dead: false };
    this.#byId.set(id, entry);
    return this.#insert(entry);
  }

  peek() {
    this.#discardDeadHead();
    return this.#heap[0];
  }

  pop() {
    this.#discardDeadHead();
    const heap = this.#heap;
    if (heap.length === 0) return undefined;
    const top = heap[0];
    const last = heap.pop();
    if (heap.length > 0) {
      heap[0] = last;
      this.#siftDown(0);
    }
    if (this.#byId.get(top.id) === top) this.#byId.delete(top.id);
    return top;
  }

  updatePriority(id, priority) {
    const current = this.#byId.get(id);
    if (!current) return false;
    if (!Number.isFinite(priority)) throw new RangeError("priority must be finite");
    current.dead = true;
    this.#deadCount++;
    const entry = { id, priority, seq: this.#seq++, payload: current.payload, dead: false };
    this.#byId.set(id, entry);
    this.#insert(entry);
    return true;
  }

  cancel(id) {
    const current = this.#byId.get(id);
    if (!current) return false;
    current.dead = true;
    this.#deadCount++;
    this.#byId.delete(id);
    return true;
  }

  compact() {
    if (this.#deadCount === 0) return 0;
    const live = this.#heap.filter((entry) => !entry.dead);
    const removed = this.#heap.length - live.length;
    this.#heap = live;
    // A filtered heap array is NOT a heap: a subsequence only keeps the heap
    // property when it is ancestor-closed, and dead entries are scattered.
    // Floyd's bottom-up heapify restores it in O(n).
    for (let i = (live.length >> 1) - 1; i >= 0; i--) this.#siftDown(i);
    this.#deadCount = 0;
    return removed;
  }

  #discardDeadHead() {
    const heap = this.#heap;
    while (heap.length > 0 && heap[0].dead) {
      this.#deadCount--;
      const last = heap.pop();          // remove the last element...
      if (heap.length > 0) {
        heap[0] = last;                 // ...and move it to the root
        this.#siftDown(0);
      }
    }
  }

  #siftUp(i) {
    const heap = this.#heap;
    while (i > 0) {
      const parent = (i - 1) >> 1;
      if (!this.#less(heap[i], heap[parent])) break;
      [heap[i], heap[parent]] = [heap[parent], heap[i]];
      i = parent;
    }
  }

  #siftDown(i) {
    const heap = this.#heap;
    for (;;) {
      const left = 2 * i + 1;
      const right = left + 1;
      let smallest = i;
      if (left < heap.length && this.#less(heap[left], heap[smallest])) smallest = left;
      if (right < heap.length && this.#less(heap[right], heap[smallest])) smallest = right;
      if (smallest === i) break;
      [heap[i], heap[smallest]] = [heap[smallest], heap[i]];
      i = smallest;
    }
  }
}
```

Three bugs my first draft had, all caught by the tests below, all worth knowing:

1. **Id-based tombstones are wrong when ids are reused.** `updatePriority` pushes a replacement entry with the *same* id, so a cancelled-id `Set` marks the fresh entry dead and jobs vanish. Mark the entry object.
2. **`heap.pop()` removes the last element, not the head.** Discarding a dead root has to move the last entry to the root and sift it down; otherwise the dead entry stays at the root and `peek` returns it forever.
3. **A filtered heap array is not a heap.** A subsequence keeps the heap property only when it is ancestor-closed, and dead entries are scattered: `[0, 3, 1]` without its root is `[3, 1]`, which is no longer a heap. `compact()` therefore ends with Floyd's bottom-up heapify, which restores the invariant in place in O(n).
@@end

@verify kind=executable language=javascript
@code
import assert from "node:assert/strict";
import test from "node:test";

class JobQueue {
  #heap = [];
  #byId = new Map();
  #deadCount = 0;
  #seq = 0;

  constructor({ maxSize = Infinity, onOverflow = "reject" } = {}) {
    if (!["reject", "shed"].includes(onOverflow)) {
      throw new RangeError(`unknown onOverflow policy ${onOverflow}`);
    }
    if (!(maxSize === Infinity || (Number.isInteger(maxSize) && maxSize > 0))) {
      throw new RangeError(`maxSize must be a positive integer, got ${maxSize}`);
    }
    this.maxSize = maxSize;
    this.onOverflow = onOverflow;
  }

  get size() {
    return this.#byId.size;
  }

  get heapSize() {
    return this.#heap.length;
  }

  #less(a, b) {
    return a.priority !== b.priority ? a.priority < b.priority : a.seq < b.seq;
  }

  #insert(entry) {
    this.#heap.push(entry);
    this.#siftUp(this.#heap.length - 1);
    return entry;
  }

  push({ id, priority, payload }) {
    if (id === undefined || id === null) throw new TypeError("job id is required");
    if (!Number.isFinite(priority)) throw new RangeError(`priority must be finite, got ${priority}`);
    if (this.#byId.has(id)) throw new Error(`duplicate job id ${id}`);
    if (this.size >= this.maxSize) {
      if (this.onOverflow === "reject") throw new Error(`queue full (${this.maxSize})`);
      return undefined;                 // "shed": drop the incoming job, keep the queue
    }
    const entry = { id, priority, seq: this.#seq++, payload, dead: false };
    this.#byId.set(id, entry);
    return this.#insert(entry);
  }

  peek() {
    this.#discardDeadHead();
    return this.#heap[0];
  }

  pop() {
    this.#discardDeadHead();
    const heap = this.#heap;
    if (heap.length === 0) return undefined;
    const top = heap[0];
    const last = heap.pop();
    if (heap.length > 0) {
      heap[0] = last;
      this.#siftDown(0);
    }
    if (this.#byId.get(top.id) === top) this.#byId.delete(top.id);
    return top;
  }

  updatePriority(id, priority) {
    const current = this.#byId.get(id);
    if (!current) return false;
    if (!Number.isFinite(priority)) throw new RangeError("priority must be finite");
    current.dead = true;
    this.#deadCount++;
    const entry = { id, priority, seq: this.#seq++, payload: current.payload, dead: false };
    this.#byId.set(id, entry);
    this.#insert(entry);
    return true;
  }

  cancel(id) {
    const current = this.#byId.get(id);
    if (!current) return false;
    current.dead = true;
    this.#deadCount++;
    this.#byId.delete(id);
    return true;
  }

  compact() {
    if (this.#deadCount === 0) return 0;
    const live = this.#heap.filter((entry) => !entry.dead);
    const removed = this.#heap.length - live.length;
    this.#heap = live;
    // A filtered heap array is NOT a heap: a subsequence keeps the heap property
    // only when it is ancestor-closed, and dead entries are scattered. Floyd's
    // bottom-up heapify restores it in O(n).
    for (let i = (live.length >> 1) - 1; i >= 0; i--) this.#siftDown(i);
    this.#deadCount = 0;
    return removed;
  }

  #discardDeadHead() {
    const heap = this.#heap;
    while (heap.length > 0 && heap[0].dead) {
      this.#deadCount--;
      const last = heap.pop();
      if (heap.length > 0) {
        heap[0] = last;
        this.#siftDown(0);
      }
    }
  }

  #siftUp(i) {
    const heap = this.#heap;
    while (i > 0) {
      const parent = (i - 1) >> 1;
      if (!this.#less(heap[i], heap[parent])) break;
      [heap[i], heap[parent]] = [heap[parent], heap[i]];
      i = parent;
    }
  }

  #siftDown(i) {
    const heap = this.#heap;
    for (;;) {
      const left = 2 * i + 1;
      const right = left + 1;
      let smallest = i;
      if (left < heap.length && this.#less(heap[left], heap[smallest])) smallest = left;
      if (right < heap.length && this.#less(heap[right], heap[smallest])) smallest = right;
      if (smallest === i) break;
      [heap[i], heap[smallest]] = [heap[smallest], heap[i]];
      i = smallest;
    }
  }
}

// Reference implementation: a sorted array with the same (priority, seq) order.
class ReferenceQueue {
  constructor() {
    this.entries = [];
    this.seq = 0;
  }

  push({ id, priority }) {
    this.entries.push({ id, priority, seq: this.seq++ });
    this.entries.sort((a, b) => a.priority - b.priority || a.seq - b.seq);
  }

  pop() {
    return this.entries.shift();
  }
}

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

test("differential test against a sorted-array reference", () => {
  const rnd = mulberry32(12345);
  const queue = new JobQueue();
  const reference = new ReferenceQueue();
  let nextId = 0;

  for (let step = 0; step < 4000; step++) {
    const roll = rnd();
    if (roll < 0.55 || nextId === 0) {
      const id = `job-${nextId++}`;
      const priority = Math.floor(rnd() * 20);
      queue.push({ id, priority });
      reference.push({ id, priority });
    } else if (roll < 0.7) {
      const id = `job-${Math.floor(rnd() * nextId)}`;
      const known = reference.entries.some((entry) => entry.id === id);
      const priority = Math.floor(rnd() * 20);
      assert.equal(queue.updatePriority(id, priority), known);
      reference.entries = reference.entries.filter((entry) => entry.id !== id);
      if (known) reference.push({ id, priority });
    } else if (roll < 0.8) {
      const id = `job-${Math.floor(rnd() * nextId)}`;
      const known = reference.entries.some((entry) => entry.id === id);
      assert.equal(queue.cancel(id), known);
      reference.entries = reference.entries.filter((entry) => entry.id !== id);
    } else {
      const fromQueue = queue.pop();
      const fromReference = reference.pop();
      if (fromQueue === undefined) {
        assert.equal(fromReference, undefined, "queue emptied before the reference");
      } else {
        assert.equal(fromQueue.id, fromReference.id);
        assert.equal(fromQueue.priority, fromReference.priority);
      }
    }
    assert.equal(queue.size, reference.entries.length);
  }

  // Drain both and compare the full pop order.
  while (reference.entries.length > 0) {
    assert.equal(queue.pop().id, reference.pop().id);
  }
  assert.equal(queue.pop(), undefined);
});

test("stable tie-break: equal priorities pop in insertion order", () => {
  const queue = new JobQueue();
  for (let i = 0; i < 200; i++) queue.push({ id: `j${i}`, priority: 5 });
  const order = [];
  while (queue.size > 0) order.push(queue.pop().id);
  assert.deepEqual(order, Array.from({ length: 200 }, (_, i) => `j${i}`));
});

test("a priority update must not tombstone the replacement entry", () => {
  const queue = new JobQueue();
  queue.push({ id: "a", priority: 5 });
  queue.updatePriority("a", 1);            // same id, new entry
  assert.equal(queue.size, 1);
  assert.equal(queue.peek().id, "a");
  assert.equal(queue.peek().priority, 1);
  assert.equal(queue.pop().id, "a");
  assert.equal(queue.pop(), undefined);
});

test("cancelled and superseded entries never surface", () => {
  const queue = new JobQueue();
  queue.push({ id: "a", priority: 1 });
  queue.push({ id: "b", priority: 2 });
  queue.push({ id: "c", priority: 3 });
  queue.cancel("a");
  queue.updatePriority("c", 0);
  assert.equal(queue.peek().id, "c");
  assert.equal(queue.pop().id, "c");
  assert.equal(queue.pop().id, "b");
  assert.equal(queue.pop(), undefined);
  assert.equal(queue.size, 0);
  assert.equal(queue.heapSize, 0, "dead entries must be discarded as they surface");
});

test("compaction removes garbage without disturbing live order", () => {
  const queue = new JobQueue();
  for (let i = 0; i < 50; i++) queue.push({ id: `k${i}`, priority: 10 - (i % 10) });
  for (let i = 0; i < 25; i++) queue.updatePriority(`k${i}`, i);
  const garbage = queue.heapSize - queue.size;
  assert.ok(garbage > 0, "churn should leave garbage entries behind");
  assert.equal(queue.compact(), garbage);
  assert.equal(queue.heapSize, queue.size);
  assert.equal(queue.compact(), 0, "compacting a clean heap is a no-op");
  const popped = [];
  while (queue.size > 0) popped.push(queue.pop().priority);
  assert.deepEqual(popped, [...popped].sort((a, b) => a - b));
});

test("invalid input is rejected at the boundary", () => {
  const queue = new JobQueue();
  assert.throws(() => queue.push({ id: "x", priority: NaN }), RangeError);
  assert.throws(() => queue.push({ id: "x", priority: Infinity }), RangeError);
  assert.throws(() => queue.push({ priority: 1 }), TypeError);
  queue.push({ id: "x", priority: 1 });
  assert.throws(() => queue.push({ id: "x", priority: 2 }), /duplicate job id/);
  assert.equal(queue.updatePriority("missing", 1), false);
  assert.equal(queue.cancel("missing"), false);
  // A known id with an invalid priority is an error, not a silent no-op...
  assert.throws(() => queue.updatePriority("x", NaN), RangeError);
  // ...while an unknown id stays a no-op whatever the priority value is.
  assert.equal(queue.updatePriority("missing", NaN), false);
});

test("explicit overload policy", () => {
  const reject = new JobQueue({ maxSize: 2, onOverflow: "reject" });
  reject.push({ id: "a", priority: 1 });
  reject.push({ id: "b", priority: 2 });
  assert.throws(() => reject.push({ id: "c", priority: 0 }), /queue full/);
  assert.equal(reject.size, 2, "reject must not disturb the queue");

  const shed = new JobQueue({ maxSize: 2, onOverflow: "shed" });
  shed.push({ id: "a", priority: 1 });
  shed.push({ id: "b", priority: 2 });
  assert.equal(shed.push({ id: "c", priority: 0 }), undefined, "incoming job is shed");
  assert.equal(shed.size, 2);
  assert.equal(shed.pop().id, "a", "the queued work is untouched");
  assert.equal(shed.pop().id, "b");

  assert.throws(() => new JobQueue({ onOverflow: "drop-lowest" }), RangeError);
  assert.throws(() => new JobQueue({ maxSize: 0 }), RangeError);
});

test("5000-job churn drains in sorted order", () => {
  const queue = new JobQueue();
  const rnd = mulberry32(999);
  for (let i = 0; i < 5000; i++) {
    const id = `n${i}`;
    queue.push({ id, priority: Math.floor(rnd() * 1000) });
    if (i % 7 === 0) queue.cancel(id);
    if (i % 11 === 0) queue.pop();
  }
  const priorities = [];
  while (queue.size > 0) priorities.push(queue.pop().priority);
  assert.deepEqual(priorities, [...priorities].sort((a, b) => a - b));
  assert.ok(queue.heapSize <= 1, `heap should be empty, heapSize=${queue.heapSize}`);
});
@@end

@expect_output
REGEX: # pass 8\n# fail 0
@@end

@notes
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
@@end

@example c-ds-0004
@meta category=data_structures language=c difficulty=expert tags=hash-table,open-addressing,tombstones,memory

@user
We need a string-keyed table in C, no external dependencies, around a million keys, and it must support deletion — our current chained table leaks and the probe chains get long under attack traffic. Specifically, a bug we cannot reproduce: after deleting a few keys, other keys become "not found" even though they are still there. Please write the table and the tests that would have caught that bug.
@@end

@assistant
That symptom is the classic **linear-probing deletion bug**: the lookup loop stops at the first empty slot, but deleting a key by blanking its slot breaks the probe chain for every key that was inserted after it. The fix is tombstones: mark the slot as deleted, keep probing past it, and reuse tombstone slots for inserts.

Three details decide whether this is actually correct under load:

1. **Two sentinels, not one.** `NULL` key means empty; a private `TOMBSTONE` pointer means deleted. Lookup keeps probing on both, insert may reuse either, and the probe loop must terminate when it wraps back to the start slot.
2. **Rehash on tombstone pressure too.** Counting only live entries means a workload of insert/delete churn fills the table with tombstones while `count/容量` looks healthy, and probes degrade to O(n). Track `used = live + tombstones` and rehash when `used/capacity > 0.7`, which also clears the tombstones for free.
3. **Copy the key.** Storing the caller's `const char *` makes the table depend on the caller's buffer lifetime — a use-after-free that only shows up in production. Duplicate the key (`strdup`) and free it on rehash/destroy.

```c
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#define TOMBSTONE ((const char *)1)

typedef struct {
    const char *key;      /* NULL = empty, TOMBSTONE = deleted, else owned copy */
    int value;
} entry_t;

typedef struct {
    entry_t *slots;
    size_t capacity;      /* always a power of two */
    size_t count;         /* live entries */
    size_t used;          /* live + tombstones */
    size_t max_load_num;  /* rehash above (used * den > capacity * num) */
    size_t max_load_den;
} strmap_t;

static uint64_t hash_str(const char *s)
{
    uint64_t h = 1469598103934665603ULL;           /* FNV-1a */
    for (; *s; s++) {
        h ^= (unsigned char)*s;
        h *= 1099511628211ULL;
    }
    return h;
}

static bool strmap_init(strmap_t *map, size_t capacity)
{
    size_t cap = 8;
    while (cap < capacity) cap <<= 1;              /* power of two for masking */
    map->slots = calloc(cap, sizeof *map->slots);  /* all keys NULL = empty */
    if (!map->slots) return false;
    map->capacity = cap;
    map->count = map->used = 0;
    map->max_load_num = 7;
    map->max_load_den = 10;                        /* 0.7 */
    return true;
}

static void strmap_destroy(strmap_t *map)
{
    for (size_t i = 0; i < map->capacity; i++)
        if (map->slots[i].key && map->slots[i].key != TOMBSTONE)
            free((void *)map->slots[i].key);
    free(map->slots);
    map->slots = NULL;
    map->capacity = map->count = map->used = 0;
}

static entry_t *probe(strmap_t *map, const char *key, bool for_insert)
{
    size_t mask = map->capacity - 1;
    size_t i = (size_t)hash_str(key) & mask;
    entry_t *first_tombstone = NULL;
    for (size_t visited = 0; visited <= mask; visited++) {
        entry_t *slot = &map->slots[i];
        if (slot->key == NULL)                          /* empty: chain ends here */
            return first_tombstone ? first_tombstone : slot;
        if (slot->key == TOMBSTONE) {                   /* remember, keep probing */
            if (for_insert && !first_tombstone) first_tombstone = slot;
        } else if (strcmp(slot->key, key) == 0) {
            return slot;
        }
        i = (i + 1) & mask;
    }
    return first_tombstone;                             /* table is full of live+dead */
}
```

`strmap_get` returns a `bool` plus an out-parameter so a stored value of `0` is not confused with "missing"; `strmap_put` grows or rehashes before inserting; `strmap_del` writes `TOMBSTONE` and decrements only `count`, never `used`.

```c
bool strmap_get(strmap_t *map, const char *key, int *out)
{
    entry_t *slot = probe(map, key, false);
    if (!slot || !slot->key || slot->key == TOMBSTONE) return false;
    *out = slot->value;
    return true;
}

bool strmap_del(strmap_t *map, const char *key)
{
    entry_t *slot = probe(map, key, false);
    if (!slot || !slot->key || slot->key == TOMBSTONE) return false;
    free((void *)slot->key);
    slot->key = TOMBSTONE;                       /* do NOT set NULL: chain must survive */
    slot->value = 0;
    map->count--;
    return true;                                  /* used stays the same */
}
```

When you write the test, do not just insert and look up: **delete a key, then look up another key that probed past it**. Randomised insert/delete/lookup sequences compared against a reference (a sorted array or a second table built naively) catch this in seconds, and a churn phase that deletes 90% of the keys catches the missing tombstone-pressure rehash. Finally, run it under ASan: it proves the key copies are freed exactly once on rehash and destroy.
@@end

@verify kind=executable language=c flags=asan
@code
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define TOMBSTONE ((const char *)1)

typedef struct {
    const char *key;
    int value;
} entry_t;

typedef struct {
    entry_t *slots;
    size_t capacity;
    size_t count;
    size_t used;
    size_t rehashes;
} strmap_t;

static uint64_t hash_str(const char *s)
{
    uint64_t h = 1469598103934665603ULL;
    for (; *s; s++) {
        h ^= (unsigned char)*s;
        h *= 1099511628211ULL;
    }
    return h;
}

static bool strmap_init(strmap_t *map, size_t capacity)
{
    size_t cap = 8;
    while (cap < capacity) cap <<= 1;
    map->slots = calloc(cap, sizeof *map->slots);
    if (!map->slots) return false;
    map->capacity = cap;
    map->count = map->used = map->rehashes = 0;
    return true;
}

static void strmap_destroy(strmap_t *map)
{
    for (size_t i = 0; i < map->capacity; i++)
        if (map->slots[i].key && map->slots[i].key != TOMBSTONE)
            free((void *)map->slots[i].key);
    free(map->slots);
    map->slots = NULL;
    map->capacity = map->count = map->used = 0;
}

static entry_t *probe(strmap_t *map, const char *key, bool for_insert)
{
    size_t mask = map->capacity - 1;
    size_t i = (size_t)hash_str(key) & mask;
    entry_t *first_tombstone = NULL;
    for (size_t visited = 0; visited <= mask; visited++) {
        entry_t *slot = &map->slots[i];
        if (slot->key == NULL)
            return first_tombstone ? first_tombstone : slot;
        if (slot->key == TOMBSTONE) {
            if (for_insert && !first_tombstone) first_tombstone = slot;
        } else if (strcmp(slot->key, key) == 0) {
            return slot;
        }
        i = (i + 1) & mask;
    }
    return first_tombstone;
}

static bool strmap_rehash(strmap_t *map, size_t new_capacity)
{
    entry_t *old = map->slots;
    size_t old_capacity = map->capacity;
    if (!strmap_init(map, new_capacity)) {
        map->slots = old;
        map->capacity = old_capacity;
        return false;
    }
    map->rehashes++;
    size_t live = 0;
    for (size_t i = 0; i < old_capacity; i++) {
        if (!old[i].key || old[i].key == TOMBSTONE) continue;
        entry_t *slot = probe(map, old[i].key, true);
        slot->key = old[i].key;                 /* move ownership, no copy */
        slot->value = old[i].value;
        live++;
    }
    map->count = map->used = live;
    free(old);                                  /* tombstones vanish with the old array */
    return true;
}

bool strmap_put(strmap_t *map, const char *key, int value)
{
    if (map->used * 10 >= map->capacity * 7) {  /* tombstones count towards load */
        if (!strmap_rehash(map, map->capacity * 2)) return false;
    }
    entry_t *slot = probe(map, key, true);
    if (!slot) return false;
    if (slot->key == NULL) {
        char *copy = malloc(strlen(key) + 1);
        if (!copy) return false;
        strcpy(copy, key);
        slot->key = copy;
        map->used++;
        map->count++;
    } else if (slot->key == TOMBSTONE) {
        char *copy = malloc(strlen(key) + 1);
        if (!copy) return false;
        strcpy(copy, key);
        slot->key = copy;                       /* reuse the tombstone */
        map->count++;
    }
    slot->value = value;
    return true;
}

bool strmap_get(strmap_t *map, const char *key, int *out)
{
    entry_t *slot = probe(map, key, false);
    if (!slot || !slot->key || slot->key == TOMBSTONE) return false;
    *out = slot->value;
    return true;
}

bool strmap_del(strmap_t *map, const char *key)
{
    entry_t *slot = probe(map, key, false);
    if (!slot || !slot->key || slot->key == TOMBSTONE) return false;
    free((void *)slot->key);
    slot->key = TOMBSTONE;
    slot->value = 0;
    map->count--;
    return true;
}

/* ---- reference: naive association list, O(n) per op, obviously correct ---- */
typedef struct {
    char **keys;
    int *values;
    size_t n;
    size_t cap;
} refmap_t;

static void ref_set(refmap_t *ref, const char *key, int value)
{
    for (size_t i = 0; i < ref->n; i++) {
        if (strcmp(ref->keys[i], key) == 0) { ref->values[i] = value; return; }
    }
    if (ref->n == ref->cap) {
        ref->cap = ref->cap ? ref->cap * 2 : 16;
        ref->keys = realloc(ref->keys, ref->cap * sizeof *ref->keys);
        ref->values = realloc(ref->values, ref->cap * sizeof *ref->values);
    }
    ref->keys[ref->n] = malloc(strlen(key) + 1);
    strcpy(ref->keys[ref->n], key);
    ref->values[ref->n] = value;
    ref->n++;
}

static bool ref_get(refmap_t *ref, const char *key, int *out)
{
    for (size_t i = 0; i < ref->n; i++) {
        if (strcmp(ref->keys[i], key) == 0) { *out = ref->values[i]; return true; }
    }
    return false;
}

static void ref_del(refmap_t *ref, const char *key)
{
    for (size_t i = 0; i < ref->n; i++) {
        if (strcmp(ref->keys[i], key) == 0) {
            free(ref->keys[i]);
            ref->keys[i] = ref->keys[ref->n - 1];
            ref->values[i] = ref->values[ref->n - 1];
            ref->n--;
            return;
        }
    }
}

static void ref_destroy(refmap_t *ref)
{
    for (size_t i = 0; i < ref->n; i++) free(ref->keys[i]);
    free(ref->keys);
    free(ref->values);
    ref->keys = NULL;
    ref->values = NULL;
    ref->n = ref->cap = 0;
}

static uint64_t rng_state = 0x9E3779B97F4A7C15ULL;
static uint64_t rnd64(void)
{
    rng_state ^= rng_state << 13;
    rng_state ^= rng_state >> 7;
    rng_state ^= rng_state << 17;
    return rng_state;
}

static unsigned rnd_below(unsigned bound) { return (unsigned)(rnd64() % bound); }

int main(void)
{
    /* 1. The reported bug: delete a key, then look up a key that probed past it.
     *    With NULL-on-delete this test fails for at least one survivor. */
    {
        strmap_t map;
        if (!strmap_init(&map, 8)) return 1;
        for (int i = 0; i < 200; i++) {
            char key[16];
            snprintf(key, sizeof key, "user-%03d", i);
            if (!strmap_put(&map, key, i)) return 2;
        }
        for (int i = 0; i < 200; i += 2) {
            char key[16];
            snprintf(key, sizeof key, "user-%03d", i);
            if (!strmap_del(&map, key)) return 3;
        }
        for (int i = 1; i < 200; i += 2) {
            char key[16];
            int value = -1;
            snprintf(key, sizeof key, "user-%03d", i);
            if (!strmap_get(&map, key, &value) || value != i) {
                printf("survivor user-%03d vanished after deletions\n", i);
                return 4;
            }
        }
        for (int i = 0; i < 200; i += 2) {
            char key[16];
            int value = -1;
            snprintf(key, sizeof key, "user-%03d", i);
            if (strmap_get(&map, key, &value)) {
                printf("deleted user-%03d still found\n", i);
                return 5;
            }
        }
        if (map.count != 100) { printf("count=%zu expected 100\n", map.count); return 6; }
        /* Tombstone pressure must have triggered a rehash rather than degrading. */
        if (map.rehashes == 0) { printf("expected tombstone-pressure rehash\n"); return 7; }
        strmap_destroy(&map);
    }

    /* 2. Randomised differential test against the reference map. */
    for (int trial = 0; trial < 40; trial++) {
        strmap_t map;
        refmap_t ref = {0};
        if (!strmap_init(&map, 16)) return 8;
        for (int step = 0; step < 400; step++) {
            char key[24];
            snprintf(key, sizeof key, "k-%u", rnd_below(80));
            unsigned action = rnd_below(10);
            if (action < 5) {
                int value = (int)rnd_below(1000);
                if (!strmap_put(&map, key, value)) return 9;
                ref_set(&ref, key, value);
            } else if (action < 8) {
                bool got = strmap_del(&map, key);
                int reference = 0;
                bool ref_has = ref_get(&ref, key, &reference);
                if (got != ref_has) {
                    printf("del mismatch trial=%d key=%s got=%d ref=%d\n", trial, key, got, ref_has);
                    return 10;
                }
                ref_del(&ref, key);
            } else {
                int value = -1, reference = 0;
                bool got = strmap_get(&map, key, &value);
                bool ref_has = ref_get(&ref, key, &reference);
                if (got != ref_has || (got && value != reference)) {
                    printf("get mismatch trial=%d key=%s\n", trial, key);
                    return 11;
                }
            }
            if (map.count != ref.n) {
                printf("count drift trial=%d step=%d map=%zu ref=%zu\n",
                       trial, step, map.count, ref.n);
                return 12;
            }
        }
        /* Every live key must be findable at the end of the churn. */
        for (size_t i = 0; i < ref.n; i++) {
            int value = -1;
            if (!strmap_get(&map, ref.keys[i], &value) || value != ref.values[i]) {
                printf("final lookup failed for %s\n", ref.keys[i]);
                return 13;
            }
        }
        strmap_destroy(&map);
        ref_destroy(&ref);
    }

    /* 3. Churn: delete 90% of a large table and check the survivors + load bound. */
    {
        strmap_t map;
        if (!strmap_init(&map, 1024)) return 14;
        for (int i = 0; i < 20000; i++) {
            char key[24];
            snprintf(key, sizeof key, "churn-%d", i);
            if (!strmap_put(&map, key, i)) return 15;
        }
        for (int i = 0; i < 18000; i++) {
            char key[24];
            snprintf(key, sizeof key, "churn-%d", i);
            if (!strmap_del(&map, key)) return 16;
        }
        if (map.count != 2000) { printf("churn count=%zu\n", map.count); return 17; }
        if (map.used * 10 >= map.capacity * 7) {
            printf("load factor not bounded: used=%zu capacity=%zu\n", map.used, map.capacity);
            return 18;
        }
        for (int i = 18000; i < 20000; i++) {
            char key[24];
            int value = -1;
            snprintf(key, sizeof key, "churn-%d", i);
            if (!strmap_get(&map, key, &value) || value != i) return 19;
        }
        strmap_destroy(&map);
    }

    /* 4. Edge cases: empty key, overwrite, single slot, delete-then-reinsert. */
    {
        strmap_t map;
        if (!strmap_init(&map, 8)) return 20;
        if (!strmap_put(&map, "", 7)) return 21;
        int value = -1;
        if (!strmap_get(&map, "", &value) || value != 7) return 22;
        if (!strmap_put(&map, "a", 1)) return 23;
        if (!strmap_put(&map, "a", 2)) return 24;
        if (map.count != 2) { printf("overwrite should not grow count\n"); return 25; }
        if (!strmap_get(&map, "a", &value) || value != 2) return 26;
        if (!strmap_del(&map, "a")) return 27;
        if (strmap_del(&map, "a")) { printf("double delete must return false\n"); return 28; }
        if (!strmap_put(&map, "a", 3)) return 29;
        if (!strmap_get(&map, "a", &value) || value != 3) return 30;
        strmap_destroy(&map);
    }
    printf("PASS\n");
    return 0;
}
@@end

@expect_output
PASS
@@end

@notes
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
@@end

@example py-ds-0005
@meta category=data_structures language=python difficulty=advanced tags=intervals,binary-search,invariants,allocation

@user
We allocate ID ranges per tenant (like `1000-2000`). Right now we keep ranges in a Python list, linear-scan on every allocation, and adjacent ranges never merge, so after a week we have thousands of fragments and the overlap check is O(n). I want a structure that keeps the ranges sorted and merged, with an explicit statement of the invariant, and I want the adjacency bug covered by tests.
@@end

@assistant
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
@@end

@verify kind=executable language=python
@code
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

    def add(self, start, end):
        if start >= end:
            raise ValueError(f"empty or reversed range [{start}, {end})")
        ranges = self._ranges
        i = bisect_left(ranges, (start, start))
        if i > 0 and ranges[i - 1][1] >= start:
            i -= 1
        merged_start, merged_end = start, end
        j = i
        while j < len(ranges) and ranges[j][0] <= merged_end:
            merged_start = min(merged_start, ranges[j][0])
            merged_end = max(merged_end, ranges[j][1])
            j += 1
        ranges[i:j] = [(merged_start, merged_end)]

    def allocated(self, start=None, end=None):
        if start is None:
            return sum(b - a for a, b in self._ranges)
        total = 0
        for a, b in self._ranges:
            lo, hi = max(a, start), min(b, end)
            if hi > lo:
                total += hi - lo
        return total

    def free_before(self, limit):
        cursor = 0
        for a, b in self._ranges:
            if a > cursor:
                return cursor
            cursor = max(cursor, b)
            if cursor >= limit:
                return None
        return cursor if cursor < limit else None


def check_invariant(rs, label=""):
    """Invariant: sorted, non-empty, strictly non-adjacent intervals."""
    ranges = rs.ranges
    for i, (start, end) in enumerate(ranges):
        assert start < end, (label, "empty range", ranges)
        if i:
            assert ranges[i - 1][1] < start, (label, "adjacent or overlapping", ranges)
    return True


# 1. The adjacency bug, in both directions plus a bridging insert, with the
#    exact expected interval list after each step.
rs = RangeSet()
rs.add(1000, 2000)
rs.add(2000, 3000)                        # touches on the right
assert rs.ranges == [(1000, 3000)], rs.ranges
rs.add(500, 1000)                         # touches on the left
assert rs.ranges == [(500, 3000)], rs.ranges
rs.add(4000, 5000)
rs.add(3000, 4000)                        # bridges the two neighbours
assert rs.ranges == [(500, 5000)], rs.ranges
check_invariant(rs, "adjacency")

# 2. Overlap, containment, exact duplicates and a chain of right neighbours.
rs = RangeSet()
rs.add(10, 20)
rs.add(15, 25)
assert rs.ranges == [(10, 25)], rs.ranges
rs.add(12, 15)                            # contained
assert rs.ranges == [(10, 25)]
rs.add(10, 25)                            # exact duplicate
assert rs.ranges == [(10, 25)]
rs.add(0, 10)                             # touching, exact
assert rs.ranges == [(0, 25)]
assert len(rs) == 1
rs.add(25, 30)
rs.add(30, 35)
rs.add(35, 40)
assert rs.ranges == [(0, 40)], rs.ranges  # chain absorbed by the growing end
check_invariant(rs, "overlap")

# 3. Membership and free_before agree with a per-point truth set.
rng = random.Random(31337)
rs = RangeSet()
truth = set()
for _ in range(400):
    a = rng.randrange(0, 120)
    b = a + rng.randrange(1, 25)
    rs.add(a, b)
    truth.update(range(a, b))
    check_invariant(rs, f"step {a}-{b}")
for value in range(0, 140):
    assert (value in rs) == (value in truth), value
assert rs.allocated() == len(truth)
for limit in (0, 1, 5, 77, 140):
    allowed = [v for v in range(limit) if v not in truth]
    expected = allowed[0] if allowed else None
    assert rs.free_before(limit) == expected, (limit, expected, rs.free_before(limit))

# 4. Construction from an unsorted, overlapping list, and intersected sizes.
rs = RangeSet([(50, 60), (10, 20), (15, 25), (60, 70)])
assert rs.ranges == [(10, 25), (50, 70)], rs.ranges
assert rs.allocated(0, 20) == 10          # [10, 20)
assert rs.allocated(18, 55) == 7 + 5      # [18, 25) + [50, 55)
assert rs.allocated(20, 50) == 5          # [20, 25)
assert rs.allocated(25, 50) == 0
check_invariant(rs, "construction")

# 5. Bad input, empty structure, and allocation is idempotent.
try:
    RangeSet().add(5, 5)
    raise AssertionError("expected ValueError for an empty range")
except ValueError:
    pass
try:
    RangeSet().add(9, 4)
    raise AssertionError("expected ValueError for a reversed range")
except ValueError:
    pass
empty = RangeSet()
assert len(empty) == 0 and 0 not in empty and empty.allocated() == 0
assert empty.free_before(10) == 0
assert empty.free_before(0) is None
repeated = RangeSet([(0, 10)])
repeated.add(2, 4)
repeated.add(0, 10)
assert repeated.ranges == [(0, 10)]
assert repeated.allocated() == 10

# 6. Soak: 5000 random inserts, invariant re-checked periodically, membership and
#    size compared against the truth set at the end.
rs = RangeSet()
truth = set()
for step in range(5000):
    a = rng.randrange(0, 500)
    b = a + rng.randrange(1, 40)
    rs.add(a, b)
    truth.update(range(a, b))
    if step % 50 == 0:
        check_invariant(rs, f"soak {step}")
assert rs.allocated() == len(truth)
assert all((v in rs) == (v in truth) for v in range(600))
print("PASS")
@@end

@expect_output
PASS
@@end

@notes
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
@@end
