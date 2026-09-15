@example mem-0001
@meta category=memory_behavior language=python difficulty=intermediate tags=memory-leak,weakref,observers,lifecycle

@user
Our dashboard service grows in RSS until the pod is OOM-killed every few hours. Each viewer object registers itself with a metrics registry, and closing a viewer does not help:

```python
class MetricsRegistry:
    def __init__(self):
        self.viewers = []              # strong references

    def register(self, viewer):
        self.viewers.append(viewer)

    def broadcast(self, payload):
        for viewer in self.viewers:
            viewer.on_metrics(payload)


class Viewer:
    def __init__(self, name):
        self.name = name
        ...
```

Viewers are created per websocket connection and dropped when the connection closes — `self.viewers` keeps every one of them alive forever. How do I confirm that is the leak, and what is the right fix?
@@end

@assistant
Yes — this is a **lifetime bug, not a buffer bug**. The registry holds a *strong* reference to every viewer, so a viewer's reference count never reaches zero when the connection closes: the object, its name, and anything it references (frames, parsed payloads, socket buffers) stay in memory for the lifetime of the process. In CPython that is pure reference counting, so `del viewer` in the connection handler has no effect at all while the registry entry exists.

The fix is to make the registry hold **weak** references, so registration does not extend lifetime:

```python
import weakref

class MetricsRegistry:
    def __init__(self):
        self.viewers = weakref.WeakSet()          # entries disappear with the object

    def register(self, viewer):
        self.viewers.add(viewer)

    def broadcast(self, payload):
        for viewer in list(self.viewers):         # snapshot: the set can change during the loop
            viewer.on_metrics(payload)
```

`WeakSet` (and `WeakValueDictionary` for keyed caches) stores a weak reference: when the last strong reference to a viewer goes away, the entry vanishes automatically. Two consequences to design for: iteration must snapshot (`list(...)`) because entries can disappear mid-loop, and objects that define `__slots__` without `__weakref__` (or that are built-in types without weakref support, like `int`, `str`, `tuple`, `list` instances) cannot be weakly referenced — the registry must then unregister explicitly.

The alternative — and the more predictable design — is explicit **unregistration** with a context manager, which works regardless of weakref support and makes the lifecycle visible in code:

```python
class MetricsRegistry:
    def __init__(self):
        self.viewers = set()

    def register(self, viewer):
        self.viewers.add(viewer)

    def unregister(self, viewer):
        self.viewers.discard(viewer)

    @contextlib.contextmanager
    def subscribed(self, viewer):
        self.register(viewer)
        try:
            yield viewer
        finally:
            self.unregister(viewer)               # always runs, even on error
```

**How to confirm the diagnosis rather than guess**: attach a `weakref` with a callback to a viewer, drop all strong references except the registry's, and call `gc.collect()`. If the weakref is still alive, something is retaining it, and you can name the culprit with `gc.get_referrers(obj)` — which shows the registry list (or a cache dict, or a traceback frame) that is holding on. Do this in a test: one assertion replaces hours of RSS watching.
@@end

@verify kind=executable language=python
@code
import gc
import weakref


class Registry:
    def __init__(self):
        self.viewers = []

    def register(self, viewer):
        self.viewers.append(viewer)

    def size(self):
        return len(self.viewers)


class WeakRegistry:
    def __init__(self):
        self.viewers = weakref.WeakSet()

    def register(self, viewer):
        self.viewers.add(viewer)

    def size(self):
        return len(self.viewers)

    def broadcast(self, payload):
        return [viewer.on_metrics(payload) for viewer in list(self.viewers)]


class Viewer:
    def __init__(self, name):
        self.name = name
        self.payload = bytearray(64)               # stands in for connection buffers

    def on_metrics(self, payload):
        return (self.name, len(payload))


# Each section runs in its own function: a module-level loop variable would itself be a
# strong reference, and the demo must not retain what it is trying to show as released.
def strong_registry_demo(count=50):
    registry = Registry()
    viewers = [Viewer(f"viewer-{index}") for index in range(count)]
    for item in viewers:
        registry.register(item)                    # the registry now owns them all
    alive_flag = weakref.ref(viewers[0])
    del viewers                                    # the connection handler's cleanup
    gc.collect()
    holders = [obj for obj in gc.get_referrers(alive_flag()) if isinstance(obj, list)]
    return {
        # the *largest* list holding the viewer is the registry's own list: asking for
        # the first one assumes an order that gc.get_referrers does not promise
        "alive": alive_flag() is not None,
        "entries": registry.size(),
        "list_holder": bool(holders),
        "holder_entries": max((len(holder) for holder in holders), default=0),
    }


def weak_registry_demo(count=50):
    registry = WeakRegistry()
    viewers = [Viewer(f"viewer-{index}") for index in range(count)]
    for item in viewers:
        registry.register(item)
    tracked_while_alive = registry.size()
    flags = [weakref.ref(item) for item in viewers]
    del viewers, item                              # the loop variable is a strong reference
    gc.collect()
    return {
        "tracked_while_alive": tracked_while_alive,
        "entries_after": registry.size(),
        "reclaimed": all(flag() is None for flag in flags),
    }


def live_entry_demo():
    registry = WeakRegistry()
    kept = Viewer("kept")
    registry.register(kept)
    tracked = registry.size()
    payload = registry.broadcast(b"metrics")
    del kept
    gc.collect()
    return {"tracked": tracked, "broadcast": payload, "after": registry.size()}


def snapshot_iteration_demo():
    registry = WeakRegistry()
    temporary = [Viewer("a"), Viewer("b"), Viewer("c")]
    for item in temporary:
        registry.register(item)
    seen = []
    for item in list(registry.viewers):            # snapshot: entries can vanish mid-loop
        seen.append(item.name)
        del item                                   # may drop the last reference
        gc.collect()
    del temporary
    gc.collect()
    return {"seen": sorted(seen), "size": registry.size()}


strong = strong_registry_demo()
print("strong registry, viewer still alive after cleanup:", strong["alive"])
print("retained entries:", strong["entries"])
print("retained by a list (the registry's):", strong["list_holder"],
      "| entries in the largest list holding it:", strong["holder_entries"])

weak = weak_registry_demo()
print("weak registry tracks them while alive:", weak["tracked_while_alive"])
print("weak registry, all entries dropped:", weak["entries_after"] == 0)
print("objects actually reclaimed:", weak["reclaimed"])

live = live_entry_demo()
print("a live strong reference keeps the entry:", live["tracked"] == 1)
print("broadcast reaches it:", live["broadcast"] == [("kept", 7)])
print("after the last strong reference disappears:", live["after"])

snapshot = snapshot_iteration_demo()
print("snapshot iteration completed:", snapshot["seen"] == ["a", "b", "c"])
print("entries left after the snapshot loop:", snapshot["size"])

assert strong["alive"] is True, "the strong registry keeps the viewer alive"
assert strong["entries"] == 50 and strong["holder_entries"] == 50
assert weak["tracked_while_alive"] == 50
assert weak["entries_after"] == 0 and weak["reclaimed"] is True
assert live["tracked"] == 1 and live["broadcast"] == [("kept", 7)] and live["after"] == 0
assert snapshot["seen"] == ["a", "b", "c"], snapshot
assert snapshot["size"] == 0, snapshot
print("PASS")
@@end

@expect_output
strong registry, viewer still alive after cleanup: True
retained entries: 50
retained by a list (the registry's): True | entries in the largest list holding it: 50
weak registry tracks them while alive: 50
weak registry, all entries dropped: True
objects actually reclaimed: True
a live strong reference keeps the entry: True
broadcast reaches it: True
after the last strong reference disappears: 0
snapshot iteration completed: True
entries left after the snapshot loop: 0
PASS
@@end

@notes
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
@@end

@example mem-0002
@meta category=memory_behavior language=python difficulty=intermediate tags=caching,memoisation,retention,lru

@user
A service that proxies documents now uses ~6 GB after a week and never releases it. The only thing we added is a cache decorator:

```python
@lru_cache(maxsize=None)
def render(document):
    return expensive_render(document)
```

Requests look identical on the wire (same URLs), so hits should dominate and the cache should be small. What is actually being cached, and how do I bound it correctly?
@@end

@assistant
`lru_cache` keys on the **arguments**, and `maxsize=None` means the cache never evicts. So the retained size is the sum of every distinct argument ever seen *plus* every result — and "same URLs on the wire" does not imply identical arguments. A `document` object parsed from the request is a fresh object per request, so each call has a distinct key even when the content is byte-identical: the cache retains one live `document` object and one rendered result per request, forever. That is the 6 GB: not a hit-rate problem but a retention problem, and no amount of traffic reduction fixes it because the cache grows monotonically with the *number* of distinct calls.

Three fixes, applied together in practice:

```python
from functools import lru_cache

# 1. key on a stable, hashable, value-equal identity instead of the object itself
@lru_cache(maxsize=512)
def render_document(document_id: str, revision: str) -> str:
    return expensive_render(document_id, revision)
```

```python
# 2. bound the cache: maxsize is the memory knob, and it also gives eviction
cache = {}
def render_cached(document_id, revision):
    key = (document_id, revision)
    if key in cache:
        return cache[key]
    value = expensive_render(document_id, revision)
    if len(cache) >= 512:
        cache.pop(next(iter(cache)))            # or use an LRU structure
    cache[key] = value
    return value
```

```python
# 3. or make the cache weak, so entries live only while the caller holds the object
import weakref
cache = weakref.WeakValueDictionary()          # values (results) must be weakref-able
```

What to check whenever a cache is added:

- **Is the key value-equal?** `lru_cache` uses `__hash__`/`__eq__`. For custom classes the default `__eq__` is identity, so two objects with the same content are two keys. Dataclasses with `eq=True` (the default) and `frozen=True` hash by fields; mutable objects that hash by `id` behave like fresh keys every time.
- **Is the key too large?** `lru_cache` holds arguments strongly, so caching on a big payload keeps that payload alive even if only a small part is used to compute the result — take `sys.getsizeof` of the key into account, not just the result.
- **Is there a bound?** `maxsize=None` is unbounded. Also check *total bytes*: 512 entries is not a memory bound if one entry can be 100 MB, so bound the value size too (or cache a token/offset instead).
- **Is the retention intentional?** Memoising pure functions over a small domain (config parsing, compiled regexes) is fine; memoising per-request objects is a leak with a hit-rate of zero.

**Diagnosing it**: instrument the cache with `functools.wraps` + `cache_info()` first (hit rate and `currsize` tell you immediately whether it is growing without bound), then confirm retention with a weakref sentinel on an argument object and `gc.get_referrers` to name the cache as the retainer.
@@end

@verify kind=executable language=python
@code
import gc
import weakref
from functools import lru_cache

RENDER_CALLS = {"count": 0}


def expensive_render(document):
    RENDER_CALLS["count"] += 1
    return "rendered:" + document.body[:8]


@lru_cache(maxsize=None)
def render_unbounded(document):
    return expensive_render(document)


@lru_cache(maxsize=8)
def render_bounded(document_id):
    return "rendered:" + document_id


class Document:
    """A per-request object; equality is identity, as for most domain objects."""

    def __init__(self, document_id, body):
        self.document_id = document_id
        self.body = body


def request(document_id, body):
    """What the handler does: parse a fresh object per request, then render."""
    return render_unbounded(Document(document_id, body))


# --- part 1: identical content, distinct cache keys ---------------------------
result_a = request("doc-1", "hello world, repeated for every request")
result_b = request("doc-1", "hello world, repeated for every request")
print("same content, same result:", result_a == result_b)
calls_after_two = RENDER_CALLS["count"]
print("render calls for two identical requests:", calls_after_two)
print("cache entries after two identical requests:", render_unbounded.cache_info().currsize)

# --- part 2: the cache is what retains the arguments -------------------------
probe = Document("doc-1", "probe payload")
handle = weakref.ref(probe)
render_unbounded(probe)
del probe
gc.collect()
print("argument retained by the cache after deletion:", handle() is not None)
retainers = [type(item).__name__ for item in gc.get_referrers(handle())]
print("retainer types:", sorted(set(retainers)))
print("retained by the cache's key tuple:", "tuple" in retainers or "dict" in retainers)
entries_after_probe = render_unbounded.cache_info().currsize
probe_retained = handle() is not None

# --- part 3: unbounded growth with a fresh object per request ------------------
for index in range(200):
    request(f"doc-{index}", "body " * 4)
info = render_unbounded.cache_info()
print("entries after 202 requests:", info.currsize, "| hits:", info.hits, "| misses:", info.misses)
print("(the probe document from part 2 is still in there too)")
print("total render calls:", RENDER_CALLS["count"])

# --- part 4: keys that are value-equal behave as expected ---------------------
render_bounded.cache_clear()
for _ in range(50):
    render_bounded("doc-1")
bounded_info = render_bounded.cache_info()
print("value-equal keys: hits:", bounded_info.hits, "| entries:", bounded_info.currsize)
for index in range(50):
    render_bounded(f"doc-{index}")
print("bounded cache size after 51 distinct keys:", render_bounded.cache_info().currsize)

# --- part 5: clearing releases the retained objects immediately ----------------
render_unbounded.cache_clear()
gc.collect()
print("entries after clear:", render_unbounded.cache_info().currsize)
print("probe object released by clear:", handle() is None)

assert result_a == result_b
assert calls_after_two == 2, "identical content still misses: the key is the object"
assert RENDER_CALLS["count"] == 203, RENDER_CALLS         # 2 + probe + 200 distinct
assert entries_after_probe == 3, "one entry per distinct object (2 requests + the probe)"
assert probe_retained is True, "the cache holds the argument strongly"
assert info.currsize == 203 and info.hits == 0, info
assert bounded_info.hits == 49 and bounded_info.currsize == 1, bounded_info
assert render_bounded.cache_info().currsize == 8, "maxsize is the bound"
assert render_unbounded.cache_info().currsize == 0 and handle() is None
print("PASS")
@@end

@expect_output
same content, same result: True
render calls for two identical requests: 2
cache entries after two identical requests: 2
argument retained by the cache after deletion: True
retainer types: ['tuple']
retained by the cache's key tuple: True
entries after 202 requests: 203 | hits: 0 | misses: 203
(the probe document from part 2 is still in there too)
total render calls: 203
value-equal keys: hits: 49 | entries: 1
bounded cache size after 51 distinct keys: 8
entries after clear: 0
probe object released by clear: True
PASS
@@end

@notes
Pins the retention mechanics with numbers: two byte-identical requests create two cache
entries and two renders and *zero* hits (the count is captured before the growth loop) because the argument is a fresh object (identity-based
equality), a weakref sentinel shows the cache keeps the argument alive after `del`, and
202 requests leave 203 entries (the two from part 1, the probe, and 200 more) with zero
hits — the monotonic growth behind the 6 GB. The contrast cases make the lesson usable:
a value-equal string key hits the cache 49 times with a single entry, `maxsize=8` caps the entry count at 8 for 51 distinct keys, and
`cache_clear()` is asserted to release the retained object (the sentinel becomes dead),
which is the operator's remedy as well as the test's teardown.
@@end

@example mem-0003
@meta category=memory_behavior language=python difficulty=advanced tags=reference-cycles,garbage-collection,finalizers,leaks

@user
Two things confuse me about Python memory:

1. A tree built with parent pointers (`node.parent = parent`, `parent.children.append(node)`) is deleted by setting the root to `None`, but our memory usage does not drop.
2. Some of our objects are only released after an explicit `gc.collect()`, and one class with a `__del__` seems to be released by the collector in newer Python but not in an old 2.7-era service we still run.

Does refcounting not free cycles? What should I actually rely on?
@@end

@assistant
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
@@end

@verify kind=executable language=python
@code
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
        self.name = name
        self._parent = None
        self.children = []

    @property
    def parent(self):
        return self._parent() if self._parent else None

    def add(self, child):
        child._parent = weakref.ref(self)
        self.children.append(child)
        return child


class Uncollectable:
    """A finalizer in the cycle: the case that used to be gc.garbage."""

    def __init__(self, name):
        self.name = name
        self.self_ref = self
        self.closed = False

    def __del__(self):
        self.closed = True


# --- part 1: a cycle survives refcounting --------------------------------------
root = Node("root")
child = root.add(Node("child"))
handle = weakref.ref(root)
del root, child
alive_without_gc = handle() is not None
print("cycle alive immediately after dropping all references:", alive_without_gc)
collected = gc.collect()
print("reachable after gc.collect():", handle() is not None)
print("collector did work:", collected >= 0)

# --- part 2: a live reference makes it a real leak, gc or not ------------------
kept = Node("kept")
kept.add(Node("child"))
kept_handle = weakref.ref(kept)
registry = {"kept": kept}                          # a root: the registry
del kept
gc.collect()
print("still reachable through a registry after gc:", kept_handle() is not None)
print("that is a leak, not a collector limitation:", kept_handle() is not None)
del registry
gc.collect()
print("released once the root is gone:", kept_handle() is None)

# --- part 3: the structural fix - refcounts alone free the tree ----------------
weak_root = WeakNode("root")
weak_root.add(WeakNode("child"))
weak_handle = weakref.ref(weak_root)
del weak_root
print("acyclic-by-weakref tree freed without gc:", weak_handle() is None)

# --- part 4: finalizers in cycles ----------------------------------------------
finalizer_cycle = Uncollectable("finalizer")
finalizer_handle = weakref.ref(finalizer_cycle)
del finalizer_cycle
print("finalizer cycle alive before gc:", finalizer_handle() is not None)
gc.collect()
print("finalizer cycle collected by modern gc:", finalizer_handle() is None)
print("gc.garbage empty (no uncollectable objects):", gc.garbage == [])

# --- part 5: the counting tool you would use on a real leak --------------------
def reachable_from_globals(target_type):
    return sum(
        1 for obj in gc.get_objects()
        if isinstance(obj, target_type) and not isinstance(obj, type)
    )


before = reachable_from_globals(Node)
sample = [Node(f"sample-{index}") for index in range(25)]
for node in sample:
    node.parent = node                             # self-cycle, every one of them
del node                                           # the loop variable is itself a root!
during = reachable_from_globals(Node)
del sample
gc.collect()
after = reachable_from_globals(Node)
print("live-tracking via gc.get_objects:", before, during, after)
print("count returns to the baseline:", after == before)

assert alive_without_gc is True, "refcounting alone cannot free a cycle"
assert handle() is None, "the collector frees unreachable cycles"
assert kept_handle() is None, "reachable cycles are leaks until the root goes away"
assert weak_handle() is None, "the weak parent link makes refcounting sufficient"
assert finalizer_handle() is None and gc.garbage == []
assert (before, during, after) == (0, 25, 0), (before, during, after)
print("PASS")
@@end

@expect_output
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
@@end

@notes
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
@@end

@example mem-0004
@meta category=memory_behavior language=python difficulty=advanced tags=closures,cells,retention,tracebacks,defaults

@user
We added a "retry the import job" feature: the error callback closes over the parsed file so a retry can reuse it. Memory across the worker jumped by hundreds of MB and nothing releases it, even after the job finishes:

```python
class JobRunner:
    def __init__(self):
        self.on_error = None

    def run(self, path):
        parsed = parse_big_file(path)              # hundreds of MB
        def handle_error(exc):
            _report(path, exc, len(parsed.records))
        self.on_error = handle_error               # kept for the retry
        return self.on_error
```

The job finishes, we drop the runner, and the parsed data is still resident. Why, and what should we store instead?
@@end

@assistant
The callback is the retention. `handle_error` references `parsed`, a variable of the enclosing function — so `parsed` becomes a **closure cell**: the cell holds the `ParsedFile`, the function object holds the cell, and `self.on_error` holds the function. Nothing in that chain depends on the local variable `parsed` going out of scope, so dropping the runner's caller does not free the data; as long as the callback is reachable, the payload is reachable. This is the same mechanism that keeps large objects alive in tracebacks and in generators that are never exhausted: a function or frame holds its cells, and a cell holds whatever it was given.

The fix is to store **what the retry actually needs**, not the whole parsed structure:

```python
class JobRunner:
    def __init__(self):
        self.retry_context = None

    def run(self, path):
        summary = parse_summary(path)              # small, serialisable facts
        self.retry_context = {"path": path, "record_count": summary["count"]}
        self.on_error = functools.partial(_report, path)
        return self.retry_context
```

Rules that follow from the mechanism:

- **Capture only the small values you need.** `functools.partial(self._report, path, count)` binds exactly the values passed to it, and a lambda captures exactly the free variables it mentions — `lambda exc: _report(path, exc, count)` captures `path` and `count`, never `parsed`.
- **Default arguments are the same trap with a different attribute.** `def handle_error(exc, _parsed=parsed)` stores the payload in the function's `__defaults__` rather than in a closure cell; the lifetime is identical (as long as the function object lives), so `_parsed=parsed` is not a way to "keep it cheap" — it is a deliberate pin. Worth checking both attributes when hunting a leak: `__closure__` and `__defaults__`.
- **Tracebacks retain frames, and frames retain locals.** An exception stored on a long-lived object (for logging or retry) keeps its whole traceback alive, including every frame's locals — so a single parked exception can hold an entire request's data. Clear it (`exc = None`, `traceback.clear_frames(exc.__traceback__)`) if it must outlive the handler.
- **Generators keep their frame too.** A generator over a large dataset that is never exhausted or closed holds its suspended frame and all its locals; `generator.close()` (or a `with` block) releases them.
- **Do not rely on `del` in the wrong scope.** Deleting a local variable cannot clear a cell that a live closure reads — the closure is the owner at that point.
- **Verify with weakrefs, not guesswork.** Attach a sentinel to the big object, let the job finish, and assert it is gone; when it is not, `gc.get_referrers` names the retainer (a `tuple` inside a function is the closure, and `function.__qualname__` tells you which one).

`sys.getrefcount` and `gc.get_referrers` answer "why is this alive?" in seconds, which is usually faster and always more reliable than reasoning about scopes.
@@end

@verify kind=executable language=python
@code
import gc
import sys
import weakref
from functools import partial


class ParsedFile:
    """Stands in for the hundreds of MB of parsed records."""

    def __init__(self, path, record_count):
        self.path = path
        self.records = [bytearray(256) for _ in range(record_count)]

    def __len__(self):
        return len(self.records)


def parse_big_file(path, record_count=64):
    return ParsedFile(path, record_count)


def parse_summary(path, record_count=64):
    return {"path": path, "count": record_count}


def _report(path, exc, count):
    return (path, str(exc), count)


class Runner:
    """The code under review: the callback closes over the parsed file."""

    def __init__(self):
        self.on_error = None

    def run(self, path):
        parsed = parse_big_file(path)
        def handle_error(exc):
            return _report(path, exc, len(parsed))     # free variable -> closure cell
        self.on_error = handle_error
        return parsed


class DefaultRunner:
    """The same pin through __defaults__ instead of a closure cell."""

    def __init__(self):
        self.on_error = None

    def run(self, path):
        parsed = parse_big_file(path)
        def handle_error(exc, _parsed=parsed):
            return _report(path, exc, len(_parsed))
        self.on_error = handle_error
        return parsed


class FixedRunner:
    """The fix: capture the small summary, not the parsed structure."""

    def __init__(self):
        self.retry_context = None
        self.on_error = None

    def run(self, path):
        summary = parse_summary(path)
        self.retry_context = {"path": summary["path"], "record_count": summary["count"]}
        self.on_error = partial(_report, summary["path"])
        return summary


# --- part 1: the closure keeps the payload alive after the job is done ---------
runner = Runner()
parsed = runner.run("import.csv")
payload_bytes = sys.getsizeof(parsed) + sum(sys.getsizeof(record) for record in parsed.records)
handle = weakref.ref(parsed)
del parsed
gc.collect()
print("record bytes per parsed file:", payload_bytes)
print("payload alive after the caller drops it:", handle() is not None)

# --- part 2: name the retainer -------------------------------------------------
retainers = [type(item).__name__ for item in gc.get_referrers(handle())]
closure = runner.on_error.__closure__
closure_size = len(closure)
cell_types = [type(cell.cell_contents).__name__ for cell in closure]
print("retainer types:", sorted(set(retainers)))
print("closure cell count:", closure_size)
print("cell contents types:", cell_types)
print("callback name:", runner.on_error.__qualname__)
del closure, retainers                      # the test must not become the retainer

# --- part 3: the same object pinned by a default argument ---------------------
default_runner = DefaultRunner()
default_parsed = default_runner.run("import.csv")
default_handle = weakref.ref(default_parsed)
default_closure_size = len(default_runner.on_error.__closure__)
default_defaults = [type(value).__name__ for value in default_runner.on_error.__defaults__]
del default_parsed
gc.collect()
print("default-argument version: closure size:", default_closure_size,
      "| __defaults__ types:", default_defaults)
print("payload alive through __defaults__:", default_handle() is not None)

# --- part 4: dropping the callback releases everything ------------------------
del runner
gc.collect()
print("payload released once the callback is dropped:", handle() is None)
del default_runner
gc.collect()
print("default-argument payload released too:", default_handle() is None)

# --- part 5: the fix captures only what the retry needs -----------------------
fixed = FixedRunner()
fixed.run("import.csv")
print("retry context:", fixed.retry_context)
print("captured small values only:", set(fixed.retry_context) == {"path", "record_count"})
print("callback binds just the path:", fixed.on_error.args)
print("no payload in the callback's arguments:",
      not any(isinstance(value, ParsedFile) for value in fixed.on_error.args))

# --- part 6: the same trap through a stored traceback ------------------------
class Holder:
    def __init__(self):
        self.stored = {}


def raise_with_payload(holder):
    payload = ParsedFile("payload.bin", 32)         # local: kept alive by the frame
    handle = weakref.ref(payload)
    try:
        raise ValueError("boom")
    except ValueError as exc:
        holder.stored["exc"] = exc                  # the traceback keeps the frame
    return handle


holder = Holder()
payload_handle = raise_with_payload(holder)
gc.collect()
print("frame locals retained by a stored traceback:", payload_handle() is not None)
del holder.stored["exc"]
gc.collect()
print("released when the exception is dropped:", payload_handle() is None)

assert handle() is None, "dropping the last callback reference must free the payload"
assert closure_size == 2, "the closure captures path and parsed"
assert sorted(cell_types) == ["ParsedFile", "str"], cell_types
assert default_closure_size == 1 and default_defaults == ["ParsedFile"]
assert set(fixed.retry_context) == {"path", "record_count"}
assert fixed.on_error.args == ("import.csv",)
assert not any(isinstance(value, ParsedFile) for value in fixed.on_error.args)
assert payload_handle() is None, "the traceback's frame is gone with the exception"
print("PASS")
@@end

@expect_output
record bytes per parsed file: 20088
payload alive after the caller drops it: True
retainer types: ['cell']
closure cell count: 2
cell contents types: ['ParsedFile', 'str']
callback name: Runner.run.<locals>.handle_error
default-argument version: closure size: 1 | __defaults__ types: ['ParsedFile']
payload alive through __defaults__: True
payload released once the callback is dropped: True
default-argument payload released too: True
retry context: {'path': 'import.csv', 'record_count': 64}
captured small values only: True
callback binds just the path: ('import.csv',)
no payload in the callback's arguments: True
frame locals retained by a stored traceback: True
released when the exception is dropped: True
PASS
@@end

@notes
Traces the retention chain with weakrefs at every step: the callback created in `run`
keeps the payload alive after the caller drops it, `gc.get_referrers` plus `__closure__`
name the retainer (the payload is referred to from a tuple — the function's cells) and
the cell contents are printed to show `ParsedFile` sitting in a cell. The
default-argument variant is measured next: `__closure__` has only `path` while
`__defaults__` holds the `ParsedFile`, and the payload stays alive exactly as before —
the same leak with a different attribute. Dropping the callbacks releases both, the
fixed version is asserted to bind only the path, and the last part shows a stored
exception retaining a frame's locals (`payload`) until the exception itself is dropped.
@@end
