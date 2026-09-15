@example api-0001
@meta category=api_behavior language=python difficulty=advanced tags=http,idempotency,retries,post

@user
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
@@end

@assistant
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
@@end

@verify kind=executable language=python
@code
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
                 "quantity": payload["quantity"]}
        self.orders.append(order)
        if key is not None:
            self.by_key[key] = (order, json.dumps(payload, sort_keys=True))
        return order, False


class KeyReuse(Exception):
    pass


class BaseHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    drop_responses = 1                                # first request loses its response
    honour_keys = True                                # the fixed server; the naive one ignores keys

    def log_message(self, *args):                     # keep the pinned output clean
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length) or b"{}")
        key = self.headers.get("Idempotency-Key") if self.honour_keys else None
        if self.honour_keys and key is None:
            self.respond(400, {"error": "Idempotency-Key header is required"})
            return
        try:
            order, replayed = self.store.create(payload, key)
        except KeyReuse as exc:
            self.respond(409, {"error": str(exc)})
            return
        if type(self).drop_responses > 0:
            type(self).drop_responses -= 1
            self.close_connection = True              # the write happened; no response
            return
        body = dict(order, replayed=replayed)
        self.respond(200 if replayed else 201, body)

    def respond(self, status, body):
        payload = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


class NaiveHandler(BaseHandler):
    """Before the fix: the endpoint accepts the key and ignores it."""

    honour_keys = False


class IdempotentHandler(BaseHandler):
    pass


def start(handler, store):
    handler.store = store
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, f"http://127.0.0.1:{server.server_address[1]}"


def stop(server, thread):
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def post(base, path, payload, headers=None):
    """Returns (status, body). status is None when the connection died mid-request."""
    request = urllib.request.Request(
        base + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"{}")
    except (http.client.RemoteDisconnected, http.client.BadStatusLine,
            ConnectionError, urllib.error.URLError) as exc:
        return None, {"error": type(exc).__name__}


def retry_until_answered(base, payload, headers=None):
    attempts = 0
    while True:
        attempts += 1
        status, body = post(base, "/orders", payload, headers)
        if status is not None:
            return attempts, status, body


# --- part 1: the naive client, no idempotency key ------------------------------
store = OrderStore()
server, thread, base = start(NaiveHandler, store)
naive_attempts, naive_status, naive_body = retry_until_answered(base, ORDER)
naive_orders = list(store.orders)
print("naive client: attempts", naive_attempts, "| final status", naive_status,
      "| order id", naive_body["id"])
print("orders created by the server:", len(naive_orders),
      "| ids:", [order["id"] for order in naive_orders])
stop(server, thread)

# --- part 2: the same failure with an idempotency key --------------------------
store = OrderStore()
server, thread, base = start(IdempotentHandler, store)
key = "8f0d6c1e-6f2a-4e2f-9c2b-5a4d3c2b1a09"
attempts, status, body = retry_until_answered(base, ORDER, {"Idempotency-Key": key})
print("idempotent client: attempts", attempts, "| final status", status,
      "| order id", body["id"], "| replayed:", body["replayed"])
print("orders created by the server:", len(store.orders),
      "| ids:", [order["id"] for order in store.orders])

# a genuine third attempt (client crashed after receiving, user retried) is a replay too
status3, body3 = post(base, "/orders", ORDER, {"Idempotency-Key": key})
print("third attempt with the same key:", status3, "| replayed:", body3["replayed"],
      "| orders:", len(store.orders))

# the same key with a different payload must not be silently accepted
status4, body4 = post(base, "/orders", {"sku": "hat-42", "quantity": 5},
                      {"Idempotency-Key": key})
print("same key, different payload:", status4, "| error:", body4["error"],
      "| orders:", len(store.orders))

# a missing key is a client bug the server must refuse, not guess about
status5, body5 = post(base, "/orders", ORDER)
print("no idempotency key:", status5, "| error:", body5["error"])
stop(server, thread)

assert naive_attempts == 2 and naive_status == 201, (naive_attempts, naive_status)
assert naive_body["id"] == 2, "the retry created a second order"
assert [order["id"] for order in naive_orders] == [1, 2], naive_orders
assert attempts == 2 and status == 200, (attempts, status)
assert body["replayed"] is True, body
assert len(store.orders) == 1 and store.orders[0]["id"] == 1, store.orders
assert status3 == 200 and body3["replayed"] is True and len(store.orders) == 1
assert status4 == 409 and body4["error"] == "the same key was sent with a different payload"
assert status5 == 400 and body5["error"] == "Idempotency-Key header is required"
print("PASS")
@@end

@expect_output
naive client: attempts 2 | final status 201 | order id 2
orders created by the server: 2 | ids: [1, 2]
idempotent client: attempts 2 | final status 200 | order id 1 | replayed: True
orders created by the server: 1 | ids: [1]
third attempt with the same key: 200 | replayed: True | orders: 1
same key, different payload: 409 | error: the same key was sent with a different payload | orders: 1
no idempotency key: 400 | error: Idempotency-Key header is required
PASS
@@end

@notes
Runs a real HTTP server on a loopback port and reproduces the failure that causes double
charges: the first `POST /orders` commits the insert and then loses the response (the
handler closes the connection without writing one, exactly what a dropped response looks
like to the client). The naive client retries and the server ends up with two orders,
ids `[1, 2]`; the idempotent client retries with the same key and ends with one order,
a replayed `200` carrying order id 1 and `replayed: true`. The remaining assertions pin
the parts of the contract teams usually forget: a later third attempt is still a replay
(no new row), reuse of the key with a different payload is a `409` rather than a silent
second order, and a request with no key at all is a `400` rather than a guess.
@@end

@example api-0002
@meta category=api_behavior language=javascript difficulty=intermediate tags=pagination,offset,keyset,cursor

@user
Our mobile app pages through the feed with `?offset=0&limit=20`, then `?offset=20&limit=20`, and users report seeing the same post twice and occasionally never seeing one at all. The list is sorted newest first:

```javascript
function page(offset, limit) {
  return items.slice(offset, offset + limit);      // items kept newest-first
}
```

Nothing is wrong with the slice. Why does this happen, and what should the API do instead?
@@end

@assistant
Because `offset` is a **position in a list that changes while the client is paging**. The cursor is an integer, but the rows behind it shift:

- **An insert before the offset duplicates rows.** The client reads page 1 (`offset=0`), three new posts are published, then `offset=3` now lands two rows earlier than before — the client sees those rows a second time.
- **A delete before the offset skips rows.** If a post from page 1 is deleted between requests, everything after it shifts forwards and the row that was at the boundary moves to a position before the offset — the client never sees it.
- **Deep offsets are slow**: `OFFSET 100000` makes the database walk and discard 100 000 rows, so late pages get progressively more expensive.

The fix is **keyset (cursor) pagination**: the cursor encodes *where you were in the ordering*, not how many rows you have seen, and the query filters on the ordering key.

```javascript
// GET /feed?limit=20&after=<cursor>
function page(limit, cursor) {
  const ordered = [...items].sort(compareNewestFirst);
  const remaining = cursor === null
    ? ordered
    : ordered.filter((item) => compareNewestFirst(item, cursor) > 0);   // strictly after
  return {
    items: remaining.slice(0, limit),
    next: remaining.length > limit ? cursorOf(remaining[limit - 1]) : null,
  };
}
```

The rules that make it correct:

- **Order by a unique, immutable, indexed key** — `(created_at DESC, id DESC)` is the usual choice. Ordering on a non-unique column alone skips rows that tie, which is why the tiebreaker is not optional (the check below shows exactly that failure).
- **Filter strictly** (`> cursor`, not `>=`), and encode the whole key (`created_at` *and* `id`) in the cursor — opaque and base64-encoded so clients do not build their own.
- **The cursor is a position, not a token of authority**: sign or encode it server-side if it contains anything you would not let a client set (tenant id, filters).
- **Return an explicit `next` cursor and `null` at the end** instead of relying on "fewer rows than the limit" — a page that happens to be exactly full would otherwise look like the end.
- **Inserts and deletes no longer break the walk**: new rows appear before the cursor are ignored (the client can refresh), and deleted rows simply do not appear. The client may miss a row that was deleted, which is correct — it does not exist.
- **Total counts and random access are the trade-off**: `total` requires a separate count query, and "jump to page 37" is not expressible. For a feed, forward-only paging is exactly what the UI does; for an admin table that needs page numbers, keep offset pagination and accept that it is a snapshot of a moving list (or freeze the list server-side).

The test below walks the same store with both schemes while inserting and deleting between pages, and pins the difference: offset paging shows duplicates and then skips a row, keyset paging returns every surviving row exactly once — including when two rows share the same `createdAt`.
@@end

@verify kind=executable language=javascript
@code
function assert(condition, message) {
  if (!condition) throw new Error(message || "assertion failed");
}

class Feed {
  constructor() {
    this.items = [];
    this.nextId = 100;
  }

  reset(count, startAt) {
    this.items = [];
    this.nextId = 100;
    for (let index = 0; index < count; index += 1) {
      this.insert(startAt + index * 2);
    }
    return this.ids();
  }

  insert(createdAt) {
    const item = { id: `item-${this.nextId}`, createdAt };
    this.nextId += 1;
    this.items.unshift(item);
    return item;
  }

  remove(id) {
    const index = this.items.findIndex((item) => item.id === id);
    const [removed] = this.items.splice(index, 1);
    return removed;
  }

  ids() {
    return this.ordered().map((item) => item.id);
  }

  ordered() {
    return [...this.items].sort((a, b) => b.createdAt - a.createdAt || b.id.localeCompare(a.id));
  }

  offsetPage(offset, limit) {
    return this.ordered().slice(offset, offset + limit);
  }

  // keyset on (createdAt, id): strictly after the cursor in the newest-first order
  cursorPage(cursor, limit) {
    if (cursor === null) return this.ordered().slice(0, limit);
    return this.ordered().filter((item) =>
      item.createdAt < cursor.createdAt ||
      (item.createdAt === cursor.createdAt && item.id < cursor.id)).slice(0, limit);
  }

  // the tempting shortcut: keyset on the non-unique column only
  createdAtOnlyPage(cursor, limit) {
    if (cursor === null) return this.ordered().slice(0, limit);
    return this.ordered().filter((item) => item.createdAt < cursor.createdAt).slice(0, limit);
  }
}

const cursorOf = (item) => ({ createdAt: item.createdAt, id: item.id });

// --- part 1: an insert between pages duplicates rows -----------------------------
const feed = new Feed();
const initial = feed.reset(8, 1000);                    // newest first
const offsetFirst = feed.offsetPage(0, 3);
feed.insert(1200);                                      // two posts arrive while paging
feed.insert(1202);
const offsetSecond = feed.offsetPage(3, 3);
const offsetSeen = [...offsetFirst, ...offsetSecond].map((item) => item.id);
const duplicated = offsetSeen.filter((id, index) => offsetSeen.indexOf(id) !== index);
console.log("offset page 1:", offsetFirst.map((item) => item.id).join(", "));
console.log("inserts between pages -> offset page 2:", offsetSecond.map((item) => item.id).join(", "));
console.log("rows served twice:", duplicated.join(", ") || "none");

// --- part 2: a delete between pages skips a row ----------------------------------
feed.reset(8, 1000);
const firstWithDelete = feed.offsetPage(0, 3);
const removed = feed.remove(firstWithDelete[1].id);      // a row from page 1 is deleted
const secondWithDelete = feed.offsetPage(3, 3);
const seenWithDelete = [...firstWithDelete, ...secondWithDelete].map((item) => item.id);
const currentOrder = feed.ids();                          // the list as it is now
const expectedNextRows = currentOrder.slice(3, 6);        // where the walk should continue
const skipped = currentOrder.slice(2, 3).filter((id) => !seenWithDelete.includes(id));
console.log("deleted", removed.id, "between pages -> offset page 2:",
            secondWithDelete.map((item) => item.id).join(", "));
console.log("row skipped entirely (it still exists):", skipped.join(", ") || "none");

// --- part 3: the same interleavings with a cursor --------------------------------
feed.reset(8, 1000);
let cursor = null;
const walked = [];
let page = feed.cursorPage(cursor, 3);
walked.push(...page.map((item) => item.id));
feed.insert(1200);                                       // insert before the cursor
const insertedAfterFirstPage = feed.items.find((item) => item.createdAt === 1200).id;
cursor = cursorOf(page[page.length - 1]);
page = feed.cursorPage(cursor, 3);
walked.push(...page.map((item) => item.id));
console.log("cursor walk:", walked.join(", "));
console.log("rows served twice:", walked.filter((id, index) => walked.indexOf(id) !== index).length);
console.log("newly inserted row correctly not shown mid-walk:",
            !walked.includes(insertedAfterFirstPage), "| inserted row:", insertedAfterFirstPage);

// --- part 4: walking to the end never skips a row --------------------------------
feed.reset(12, 1000);
cursor = null;
const complete = [];
do {
  page = feed.cursorPage(cursor, 5);
  complete.push(...page.map((item) => item.id));
  cursor = page.length === 5 ? cursorOf(page[4]) : null;
} while (cursor !== null);
const expected = feed.ids();
console.log("walk returned", complete.length, "rows of", expected.length,
            "| in order:", complete.join(",") === expected.join(","));

// --- part 5: ties are the reason the cursor needs a tiebreaker -------------------
feed.reset(4, 1000);
feed.items[1].createdAt = feed.items[2].createdAt;        // two rows now share a timestamp
const tieIds = feed.ids();
const firstPage = feed.createdAtOnlyPage(null, 2);
const cursorRow = firstPage[firstPage.length - 1];        // the boundary row
const tiePartner = tieIds[tieIds.indexOf(cursorRow.id) + 1];
const secondByCreatedAtOnly = feed.createdAtOnlyPage(cursorOf(cursorRow), 2);
const withTiebreaker = feed.cursorPage(cursorOf(cursorRow), 2);
const seenByTimestampCursor = [...firstPage, ...secondByCreatedAtOnly].map((item) => item.id);
const skippedByTie = tieIds.filter((id) => !seenByTimestampCursor.includes(id));
console.log("page 1 ends on", cursorRow.id, "(createdAt", cursorRow.createdAt + ")",
            "| the next row shares that timestamp:", tiePartner);
console.log("timestamp-only cursor -> next row:",
            secondByCreatedAtOnly.length ? secondByCreatedAtOnly[0].id : "nothing",
            "| skipped:", skippedByTie.join(", "));
console.log("with the id tiebreaker -> next row:", withTiebreaker[0].id,
            "| same timestamp as the cursor:", withTiebreaker[0].createdAt === cursorRow.createdAt);

assert(duplicated.length === 2, `expected two duplicated rows, got ${duplicated}`);
assert(offsetSeen.length === 6 && offsetSeen.filter((id, i) => offsetSeen.indexOf(id) === i).length === 4);
assert(skipped.length === 1, `expected exactly one skipped row, got ${skipped}`);
assert(secondWithDelete.map((item) => item.id).join(",") === expectedNextRows.join(","),
  "offset page 2 jumped one row too far: it returned the rows after the skipped one");
assert(!firstWithDelete.map((item) => item.id).includes(skipped[0]), "the skipped row was never served");
assert(walked.length === 6);
assert(new Set(walked).size === 6, "the cursor walk must not repeat a row");
assert(complete.length === expected.length && complete.join(",") === expected.join(","));
assert(skippedByTie.length === 1 && skippedByTie[0] === tiePartner,
       `the timestamp-only cursor skips the tied row, got ${skippedByTie}`);
assert(secondByCreatedAtOnly[0].id === tieIds[tieIds.indexOf(tiePartner) + 1],
       "it jumps straight past the tie to the next distinct timestamp");
assert(withTiebreaker[0].id === tiePartner, "the tiebreaker returns the tied row");
assert(withTiebreaker[0].createdAt === cursorRow.createdAt);
assert(initial.length === 8 && tieIds.length === 4);
console.log("PASS");
@@end

@expect_output
offset page 1: item-107, item-106, item-105
inserts between pages -> offset page 2: item-106, item-105, item-104
rows served twice: item-106, item-105
deleted item-106 between pages -> offset page 2: item-103, item-102, item-101
row skipped entirely (it still exists): item-104
cursor walk: item-107, item-106, item-105, item-104, item-103, item-102
rows served twice: 0
newly inserted row correctly not shown mid-walk: true | inserted row: item-108
walk returned 12 rows of 12 | in order: true
page 1 ends on item-102 (createdAt 1002) | the next row shares that timestamp: item-101
timestamp-only cursor -> next row: item-100 | skipped: item-101
with the id tiebreaker -> next row: item-101 | same timestamp as the cursor: true
PASS
@@end

@notes
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
@@end

@example api-0003
@meta category=api_behavior language=python difficulty=intermediate tags=rate-limiting,token-bucket,clock

@user
Our rate limiter is a token bucket, and load tests show it letting through far more traffic than configured — roughly the whole burst, every time:

```python
class TokenBucket:
    def __init__(self, capacity, rate_per_second):
        self.capacity = capacity
        self.rate = rate_per_second
        self.tokens = capacity
        self.updated_at = 0.0

    def allow(self, now):
        elapsed = now - self.updated_at
        self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
        if self.tokens >= 1:
            self.tokens -= 1
            return True
        return False
```

The maths looks right. What is actually broken?
@@end

@assistant
`self.updated_at` is never advanced, so `elapsed` is `now - 0` — the time since the process started. Every call therefore adds the *entire history* of the bucket's life to the token count, which the `min(capacity, ...)` then clamps, so the bucket is refilled to full on essentially every request. A limiter that is always full is not a limiter: the load test was measuring the clamp, not the policy.

The fix is one line, but the surrounding design matters as much:

```python
class TokenBucket:
    def __init__(self, capacity, rate_per_second):
        self.capacity = float(capacity)
        self.rate = float(rate_per_second)
        self.tokens = float(capacity)
        self.updated_at = None

    def allow(self, now):
        if self.updated_at is None:
            self.updated_at = now
        elapsed = now - self.updated_at
        self.updated_at = now                              # <-- advance the clock
        self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
        if self.tokens >= 1.0:
            self.tokens -= 1.0
            return True
        return False
```

Notes that separate a working limiter from a plausible one:

- **Advance `updated_at` on every call, including rejected ones.** If it only moves when a request is allowed, a long stream of rejections makes the next allowed request compute a huge elapsed time — the same bug in a quieter form.
- **Refill lazily from elapsed time; never run a background refill thread.** Lazy refill is exact, has no scheduler drift, and costs one subtraction.
- **Pass the clock in** (`now`) instead of calling `time.monotonic()` inside. That is what makes the limiter testable: the check below drives a virtual clock and asserts exact counts, with no `sleep` and no flakiness. Use a monotonic clock in production (`time.monotonic()`, `performance.now()`), never wall-clock time, which jumps on NTP corrections and DST.
- **Decide where the token is consumed.** Consuming before the handler means a request that fails validation still spends a token; consuming after means a burst can reach the database. Most APIs consume first and refund on 5xx.
- **Burst capacity is a design choice, not a bug**: `capacity` is how large a burst the system tolerates, `rate` is the sustained throughput. A common refinement is a *smoothing* bucket for bursts plus a stricter one for sustained rate.
- **Distributed limiters need shared state** (Redis with an atomic script, or per-instance limits scaled by instance count); an in-process bucket multiplies the effective limit by the number of replicas — the same class of mistake as this one, at the infrastructure layer.
- **Return the contract**: `429` with `Retry-After`, plus `RateLimit-Limit` / `RateLimit-Remaining` headers, so clients can back off instead of retrying blindly.

The check below pins the difference on a virtual clock: over one second at 5 tokens/second with a capacity of 10, the fixed limiter allows 14 requests out of 100 and the buggy one allows the house. It also asserts the two lines teams usually miss — that a rejected request does not *earn* tokens (calling 100 times instantly must not refill the bucket) and that a genuinely idle bucket does refill, up to its capacity and no further.
@@end

@verify kind=executable language=python
@code
class BuggyBucket:
    """Under review: `updated_at` is never advanced."""

    def __init__(self, capacity, rate_per_second):
        self.capacity = float(capacity)
        self.rate = float(rate_per_second)
        self.tokens = float(capacity)
        self.updated_at = 0.0

    def allow(self, now):
        elapsed = now - self.updated_at
        self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
        if self.tokens >= 1.0:
            self.tokens -= 1.0
            return True
        return False


class TokenBucket:
    """Fixed: the refill advances the timestamp on every call."""

    def __init__(self, capacity, rate_per_second):
        self.capacity = float(capacity)
        self.rate = float(rate_per_second)
        self.tokens = float(capacity)
        self.updated_at = None

    def allow(self, now):
        if self.updated_at is None:
            self.updated_at = now
        elapsed = now - self.updated_at
        self.updated_at = now
        self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
        if self.tokens >= 1.0:
            self.tokens -= 1.0
            return True
        return False


class Clock:
    def __init__(self, start=0.0):
        self.now = float(start)

    def advance(self, seconds):
        self.now += seconds
        return self.now


CAPACITY, RATE, REQUESTS = 10, 5, 100
STEP = 0.01


def burst(limiter_class, clock):
    limiter = limiter_class(CAPACITY, RATE)
    allowed = 0
    for _ in range(REQUESTS):
        clock.advance(STEP)
        if limiter.allow(clock.now):
            allowed += 1
    return limiter, allowed


clock = Clock()
buggy, buggy_allowed = burst(BuggyBucket, clock)
print(f"buggy limiter: allowed {buggy_allowed} of {REQUESTS} requests in "
      f"{REQUESTS * STEP:.2f}s (capacity {CAPACITY}, rate {RATE}/s)")

clock = Clock()
fixed, fixed_allowed = burst(TokenBucket, clock)
print(f"fixed limiter: allowed {fixed_allowed} of {REQUESTS} requests in "
      f"{REQUESTS * STEP:.2f}s")
print("fixed limiter stays within capacity + rate x elapsed:",
      fixed_allowed <= CAPACITY + RATE * (REQUESTS * STEP) + 1)

# --- a rejected request must not earn tokens -----------------------------------
clock = Clock()
limiter = TokenBucket(CAPACITY, RATE)
allowed_at_zero = sum(1 for _ in range(50) if limiter.allow(clock.now))
rejected_after_exhaustion = 50 - allowed_at_zero
print("50 calls at the same instant: allowed", allowed_at_zero,
      "| rejected", rejected_after_exhaustion, "(a stale clock would refill them)")

# --- an idle bucket refills, up to capacity and no further ---------------------
clock.advance(2.0)
after_idle = sum(1 for _ in range(50) if limiter.allow(clock.now))
clock.advance(3600.0)                                    # an hour of silence
after_long_idle = sum(1 for _ in range(50) if limiter.allow(clock.now))
print(f"after 2s idle: {after_idle} allowed | after an hour idle: {after_long_idle} allowed "
      f"(capacity {int(limiter.capacity)})")

# --- the buggy version's failure is monotonic in traffic ----------------------
clock = Clock()
buggy_long, buggy_long_allowed = burst(BuggyBucket, clock)
clock = Clock()
fixed_long, fixed_long_allowed = burst(TokenBucket, clock)
print("same traffic, both limiters: buggy", buggy_long_allowed,
      "vs fixed", fixed_long_allowed)

assert buggy_allowed == REQUESTS, buggy_allowed
assert fixed_allowed == 14, fixed_allowed
assert fixed_allowed <= CAPACITY + RATE * (REQUESTS * STEP) + 1
assert allowed_at_zero == CAPACITY and rejected_after_exhaustion == 40
assert after_idle == CAPACITY, after_idle
assert after_long_idle == CAPACITY, "an idle bucket must not exceed its capacity"
assert round(fixed.tokens, 3) <= CAPACITY
assert buggy_long_allowed > fixed_long_allowed * 5, (buggy_long_allowed, fixed_long_allowed)
print("PASS")
@@end

@expect_output
buggy limiter: allowed 100 of 100 requests in 1.00s (capacity 10, rate 5/s)
fixed limiter: allowed 14 of 100 requests in 1.00s
fixed limiter stays within capacity + rate x elapsed: True
50 calls at the same instant: allowed 10 | rejected 40 (a stale clock would refill them)
after 2s idle: 10 allowed | after an hour idle: 10 allowed (capacity 10)
same traffic, both limiters: buggy 100 vs fixed 14
PASS
@@end

@notes
The bug is reproduced and measured on a virtual clock, so every number is exact and no
`sleep` can make the test flaky: 100 requests spread over one second at a capacity of 10
and a rate of 5/s are all allowed by the buggy limiter (the clamp refills it on every
call) versus 14 by the fixed one, which is exactly capacity + rate x elapsed. The three
behaviours that separate a real token bucket from a plausible one are then asserted
rather than asserted-about: 50 calls at the same instant allow exactly 10 (a stale clock
would refill them, and a rejected request must not earn tokens), two seconds of idle
refill to capacity, an hour of idle refills to capacity and no further, and the same
traffic through both implementations differs by a factor of more than five.
@@end

@example api-0004
@meta category=api_behavior language=javascript difficulty=advanced tags=rest,patch,etag,optimistic-concurrency,mass-assignment

@user
Our profile API handles partial updates like this:

```javascript
// PATCH /users/:id  with If-Match support bolted on later
if (!db.users[id]) return reply(404, { error: "no such user" });
if (request.body.version !== db.users[id].version) return reply(409, { error: "stale" });
Object.assign(db.users[id], request.body);
delete db.users[id].version;
return reply(200, db.users[id]);
```

Two incidents since it shipped: a customer changed their own `role` to `admin` with a crafted PATCH, and two admins editing the same profile clobbered each other's edits even though both got `200`. What is wrong, and what does a correct PATCH look like?
@@end

@assistant
Two distinct errors are packed into those five lines.

**Mass assignment.** `Object.assign(record, request.body)` copies *every* key the client sent, including fields the endpoint never intended to be writable: `role`, `id`, `emailVerified`, `plan`, `createdAt`. The client does not need to be malicious — a mobile app that sends its whole local model back on save will escalate a role on its own. The fix is an **explicit allow-list of patchable fields**, validated per field, applied to a copy:

```javascript
const PATCHABLE = {
  displayName: (value) => typeof value === "string" && value.trim().length > 0
    && value.length <= 80 ? value.trim() : invalid("displayName"),
  bio: (value) => value === null || (typeof value === "string" && value.length <= 500)
    ? value : invalid("bio"),
  email: (value) => typeof value === "string" && EMAIL.test(value) ? value : invalid("email"),
};

function applyPatch(record, patch) {
  const unknown = Object.keys(patch).filter((key) => !(key in PATCHABLE));
  if (unknown.length > 0) return { error: 400, detail: `not patchable: ${unknown.join(", ")}` };
  const next = { ...record };
  for (const [key, value] of Object.entries(patch)) next[key] = PATCHABLE[key](value);
  return { record: next };
}
```

**Optimistic concurrency done wrong.** `request.body.version` puts the version *inside the body the client is sending*, which means the client has to read it, keep it, and send it back — and a client that omits it fails the equality check or, worse, sends a freshly read version and overwrites. HTTP already has the mechanism: return an `ETag` with the representation, require `If-Match` on writes, and answer `412 Precondition Failed` (not `409`) when it does not match:

```javascript
// GET /users/:id
reply(200, record, { ETag: `"${record.version}"` });

// PATCH /users/:id
const etag = request.headers["if-match"];
if (!etag) return reply(428, { error: "If-Match is required" });        // precondition required
if (etag !== `"${record.version}"`) {
  return reply(412, { error: "the profile changed", current: record });  // fails, tells why
}
```

The rest of a correct PATCH:

- **`PATCH` is not "merge whatever you sent"**. Either implement JSON Merge Patch (RFC 7396: keys present are replaced, `null` deletes) or JSON Patch (RFC 6902, explicit operations), document which, and be consistent — the check below shows `null` clearing a field while an absent key leaves it alone.
- **Return the updated representation** (200 with the new body) and the **new `ETag`**, so the client can immediately patch again without a re-read.
- **Bump the version inside the same transaction** that applies the change; deriving it from a timestamp invites two updates landing in the same millisecond.
- **`412` means "your copy is stale", `409` means "the request conflicts with the resource's state"** (for example, a duplicate email). Confusing them makes retries impossible to automate: a client should re-read and retry on `412`, and change its request on `409`.
- **Do not accept `version` in the body at all.** If you leave the field writable, it is one more thing an attacker can set, and the ETag becomes decorative.
@@end

@verify kind=executable language=javascript
@code
function assert(condition, message) {
  if (!condition) throw new Error(message || "assertion failed");
}

const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

const PATCHABLE = {
  displayName: (value) => typeof value === "string" && value.trim().length > 0
    && value.length <= 80 ? value.trim() : invalid("displayName"),
  bio: (value) => value === null || (typeof value === "string" && value.length <= 500)
    ? value : invalid("bio"),
  email: (value) => typeof value === "string" && EMAIL.test(value) ? value : invalid("email"),
};

function invalid(field) {
  const error = new Error(`invalid value for ${field}`);
  error.invalidField = field;
  throw error;
}

// --- the endpoint under review ------------------------------------------------
function naivePatch(db, id, body) {
  if (!db.profiles[id]) return { status: 404, body: { error: "no such user" } };
  if (body.version !== db.profiles[id].version) return { status: 409, body: { error: "stale" } };
  Object.assign(db.profiles[id], body);
  delete db.profiles[id].version;
  return { status: 200, body: db.profiles[id] };
}

// --- the fixed endpoint -------------------------------------------------------
function guardedPatch(db, id, body, ifMatch) {
  const record = db.profiles[id];
  if (!record) return { status: 404, body: { error: "no such user" } };
  if (ifMatch === undefined) return { status: 428, body: { error: "If-Match is required" } };
  if (ifMatch !== `"${record.version}"`) {
    return { status: 412, body: { error: "the profile changed", current: record }, headers: {} };
  }
  const unknown = Object.keys(body).filter((key) => !(key in PATCHABLE));
  if (unknown.length > 0) {
    return { status: 400, body: { error: `not patchable: ${unknown.join(", ")}` } };
  }
  const next = { ...record };
  try {
    for (const [key, value] of Object.entries(body)) next[key] = PATCHABLE[key](value);
  } catch (error) {
    return { status: 422, body: { error: error.message, field: error.invalidField } };
  }
  next.version = record.version + 1;
  db.profiles[id] = next;
  return { status: 200, body: next, headers: { ETag: `"${next.version}"` } };
}

const seedProfiles = () => ({
  profiles: {
    "user-1": {
      id: "user-1", displayName: "Ada Lovelace", bio: null,
      email: "ada@example.com", role: "member", version: 1,
    },
  },
});

// --- part 1: mass assignment --------------------------------------------------
let db = seedProfiles();
const escalation = naivePatch(db,
  "user-1", { displayName: "Ada L.", role: "admin", plan: "enterprise", version: 1 });
console.log("naive PATCH with role in the body:", escalation.status,
            "| stored role:", db.profiles["user-1"].role,
            "| plan:", db.profiles["user-1"].plan);
console.log("version field after the naive patch:", db.profiles["user-1"].version);

db = seedProfiles();
const refused = guardedPatch(db, "user-1",
  { displayName: "Ada L.", role: "admin" }, '"1"');
console.log("guarded PATCH with role in the body:", refused.status,
            "|", refused.body.error, "| stored role:", db.profiles["user-1"].role);

// --- part 2: ETag / If-Match and lost updates ---------------------------------
db = seedProfiles();
const read = { etag: `"${db.profiles["user-1"].version}"`, body: db.profiles["user-1"] };
const editorOne = guardedPatch(db, "user-1", { displayName: "Ada Lovelace-Turing" }, read.etag);
console.log("first editor:", editorOne.status, "| new ETag:", editorOne.headers.ETag);
const editorTwo = guardedPatch(db, "user-1", { bio: "mathematician" }, read.etag);
const adaSurvived = db.profiles["user-1"].displayName;   // snapshot before later scenarios
console.log("second editor with the stale ETag:", editorTwo.status,
            "| currentVersion:", editorTwo.body.current.version,
            "| bio still:", JSON.stringify(db.profiles["user-1"].bio),
            "| displayName survived:", adaSurvived === "Ada Lovelace-Turing");
const editorTwoRetry = guardedPatch(db, "user-1", { bio: "mathematician" }, '"2"');
console.log("second editor after re-reading (ETag",
            `"2"` + "):", editorTwoRetry.status, "| new ETag:", editorTwoRetry.headers.ETag,
            "| displayName preserved:", db.profiles["user-1"].displayName);
console.log("missing If-Match:", guardedPatch(db, "user-1", { bio: "x" }).status,
            "| the naive version without a version field:",
            naivePatch(db, "user-1", { bio: "x" }).status);

// --- part 3: JSON Merge Patch semantics ---------------------------------------
db = seedProfiles();
const cleared = guardedPatch(db, "user-1", { bio: null }, '"1"');
console.log("null clears a field:", cleared.status, "| bio in body:", "bio" in cleared.body,
            "| bio value:", JSON.stringify(cleared.body.bio));
const untouched = guardedPatch(db, "user-1", { displayName: "Ada L." }, '"2"');
console.log("absent key leaves the field alone:", untouched.status,
            "| email still:", untouched.body.email, "| version:", untouched.body.version);
const badEmail = guardedPatch(db, "user-1", { email: "not-an-email" }, '"3"');
console.log("invalid value:", badEmail.status, "| field:", badEmail.body.field,
            "| stored email unchanged:", db.profiles["user-1"].email);

assert(escalation.status === 200 && db.profiles["user-1"] !== undefined);
assert(db.profiles["user-1"].role === "member", "the escalation was refused");
assert(db.profiles["user-1"].plan === undefined);
assert(refused.status === 400 && refused.body.error.startsWith("not patchable: role"));
assert(editorOne.status === 200 && editorOne.headers.ETag === '"2"');
assert(editorTwo.status === 412 && editorTwo.body.current.version === 2);
assert(db.profiles["user-1"].bio === null, "the stale write did not land");
assert(editorTwoRetry.status === 200 && editorTwoRetry.headers.ETag === '"3"');
assert(adaSurvived === "Ada Lovelace-Turing", "no lost update: the first editor's write survives");
assert(badEmail.status === 422 && badEmail.body.field === "email");
assert(cleared.status === 200 && "bio" in cleared.body && cleared.body.bio === null);
assert(untouched.body.email === "ada@example.com" && untouched.body.version === 3);
console.log("PASS");
@@end

@expect_output
naive PATCH with role in the body: 200 | stored role: admin | plan: enterprise
version field after the naive patch: undefined
guarded PATCH with role in the body: 400 | not patchable: role | stored role: member
first editor: 200 | new ETag: "2"
second editor with the stale ETag: 412 | currentVersion: 2 | bio still: null | displayName survived: true
second editor after re-reading (ETag "2"): 200 | new ETag: "3" | displayName preserved: Ada Lovelace-Turing
missing If-Match: 428 | the naive version without a version field: 409
null clears a field: 200 | bio in body: true | bio value: null
absent key leaves the field alone: 200 | email still: ada@example.com | version: 3
invalid value: 422 | field: email | stored email unchanged: ada@example.com
PASS
@@end

@notes
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
@@end
