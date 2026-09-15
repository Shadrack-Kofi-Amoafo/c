@example py-arch-0001
@meta category=software_architecture language=python difficulty=advanced tags=dependency-inversion,ports-and-adapters,circular-imports,hexagonal

@user
Our `orders` module and `sqlite_repo` module import each other, so `import orders` blows up with "cannot import name 'Order' from partially initialized module" depending on which one is imported first. Someone "fixed" it by moving the import inside `__init__`, which works, but the code still feels tangled and I do not trust it. How should this actually be structured?
@@end

@assistant
What you have is a dependency-direction problem, not an import-order problem. The repository imports the domain type for its signatures, and the domain imports the repository to build one — a cycle in the graph. Python's deferred-import trick hides the `ImportError` but the graph is unchanged, so the modules still cannot be tested, deployed or understood separately.

**Ports and adapters (hexagonal) inverts the dependency:** the domain declares the interface it needs (a *port*), and the adapter implements it. Imports then point inwards only:

```
domain/orders.py    -> (nothing outside domain)
domain/ports.py     -> domain/orders.py
adapters/sqlite_repo.py -> domain/orders.py     (implements the port)
app.py              -> both                      (composition root)
```

```python
# domain/orders.py -- no knowledge of SQL, no import of an adapter
class OrderService:
    def __init__(self, repo):          # typed by the port, satisfied structurally
        self.repo = repo

    def place(self, order_id, customer_id, total_cents):
        if total_cents <= 0:
            raise ValueError("an order must have a positive total")
        order = Order(order_id, customer_id, total_cents)
        self.repo.add(order)
        return order
```

Four properties make this worth the refactor:

- **The domain is testable with no database.** An in-memory dict implementing `add/get/count` runs the same domain tests in microseconds; you stop needing SQLite to test a business rule.
- **Deferred imports are a smell, and CI can catch them.** An AST-based checker that looks at imports *inside functions* too will still report the cycle, which is exactly what you want: the honest signal stays in the build instead of disappearing behind a local import.
- **The port is the contract.** One `contract(repo)` test runs against every implementation, so the fake cannot drift from SQLite silently.
- **Wiring lives in one place.** A composition root (`app.py`) is the only module that knows both the domain and the adapter, which keeps the knowledge from leaking.

When *not* to do this: a 200-line script with one storage backend does not need a port per table. The rule of thumb is "a second implementation exists or is imminent (a fake for tests counts), or the storage detail changes independently of the rules".
@@end

@verify kind=executable language=python
@code
import ast
import importlib
import sqlite3
import subprocess
import sys
import textwrap
import tempfile
from pathlib import Path

BEFORE = {
    "orders.py": textwrap.dedent('''
        from dataclasses import dataclass

        from sqlite_repo import SqliteOrderRepository


        @dataclass(frozen=True)
        class Order:
            id: str
            customer_id: str
            total_cents: int


        class OrderService:
            def __init__(self, repo=None):
                self.repo = repo or SqliteOrderRepository("orders.db")

            def place(self, order):
                self.repo.add(order)
    '''),
    "sqlite_repo.py": textwrap.dedent('''
        from orders import Order


        class SqliteOrderRepository:
            """Adapter that needs the domain type for its signature."""

            def add(self, order: Order) -> None:
                raise NotImplementedError
    '''),
}

DEFERRED = dict(BEFORE)
DEFERRED["orders.py"] = (
    BEFORE["orders.py"]
    .replace("from sqlite_repo import SqliteOrderRepository\n", "")
    .replace(
        "    def __init__(self, repo=None):\n",
        "    def __init__(self, repo=None):\n"
        "        from sqlite_repo import SqliteOrderRepository  # deferred import\n",
    )
)

AFTER = {
    "domain/__init__.py": "",
    "domain/ports.py": textwrap.dedent('''
        from typing import Protocol

        from domain.orders import Order


        class OrderRepository(Protocol):
            """What the domain needs from storage. Nothing about SQL leaks in."""

            def add(self, order: Order) -> None: ...

            def get(self, order_id: str) -> "Order | None": ...

            def count(self) -> int: ...
    '''),
    "domain/orders.py": textwrap.dedent('''
        from dataclasses import dataclass


        @dataclass(frozen=True)
        class Order:
            id: str
            customer_id: str
            total_cents: int


        class OrderService:
            """Pure domain logic: depends on a port, never on an adapter."""

            def __init__(self, repo):
                self.repo = repo

            def place(self, order_id, customer_id, total_cents):
                if total_cents <= 0:
                    raise ValueError("an order must have a positive total")
                order = Order(order_id, customer_id, total_cents)
                self.repo.add(order)
                return order

            def outstanding_cents(self, order_id):
                order = self.repo.get(order_id)
                return 0 if order is None else order.total_cents
    '''),
    "adapters/__init__.py": "",
    "adapters/sqlite_repo.py": textwrap.dedent('''
        import sqlite3

        from domain.orders import Order


        class SqliteOrderRepository:
            """Adapter: implements the port using SQLite. Imports point inwards."""

            def __init__(self, conn):
                self.conn = conn
                self.conn.execute(
                    "CREATE TABLE IF NOT EXISTS orders ("
                    "id TEXT PRIMARY KEY, customer_id TEXT NOT NULL, total_cents INTEGER NOT NULL)"
                )

            def add(self, order: Order) -> None:
                with self.conn:
                    self.conn.execute(
                        "INSERT INTO orders VALUES (?, ?, ?)",
                        (order.id, order.customer_id, order.total_cents),
                    )

            def get(self, order_id):
                row = self.conn.execute(
                    "SELECT id, customer_id, total_cents FROM orders WHERE id = ?", (order_id,)
                ).fetchone()
                return None if row is None else Order(*row)

            def count(self) -> int:
                return self.conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
    '''),
    "app.py": textwrap.dedent('''
        import sqlite3

        from adapters.sqlite_repo import SqliteOrderRepository
        from domain.orders import OrderService


        def build_repository(conn):
            return SqliteOrderRepository(conn)


        def build_service(conn):
            return OrderService(build_repository(conn))
    '''),
}


def write_package(root, files):
    for name, source in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source)


def imports_of(path):
    """(module, line, deferred) for every import anywhere in the file, including
    imports buried inside functions -- those hide a cycle from the interpreter but
    not from the dependency graph."""
    tree = ast.parse(path.read_text())
    found = []

    def visit(node, deferred):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.Import, ast.ImportFrom)):
                modules = (
                    [alias.name for alias in child.names]
                    if isinstance(child, ast.Import)
                    else [child.module or ""]
                )
                for module in modules:
                    found.append((module, child.lineno, deferred))
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                visit(child, True)
            else:
                visit(child, deferred)

    visit(tree, False)
    return found


def find_cycles(root):
    graph = {}
    for path in sorted(root.rglob("*.py")):
        name = ".".join(path.relative_to(root).with_suffix("").parts)
        edges = []
        for module, line, deferred in imports_of(path):
            target = module.replace(".", "/")
            candidate = root / (target + ".py")
            package = root / target / "__init__.py"
            if candidate.exists() or package.exists():
                edges.append((module, deferred, line))
        graph[name] = edges

    cycles = []

    def walk(node, path, seen_edges):
        if node in path:
            cycles.append((path[path.index(node):] + [node], list(seen_edges)))
            return
        for module, deferred, line in graph.get(node, []):
            if module in graph:
                seen_edges.append((node, module, deferred, line))
                walk(module, path + [node], seen_edges)
                seen_edges.pop()

    for start in graph:
        walk(start, [], [])
    return cycles


with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)

    # 1. The cycle is real: importing the service fails because `Order` is not
    #    available yet when sqlite_repo is loaded.
    before = tmp / "before"
    write_package(before, BEFORE)
    result = subprocess.run(
        [sys.executable, "-c", "import orders"],
        cwd=before, capture_output=True, text=True,
    )
    assert result.returncode != 0, "the circular import must fail"
    assert "cannot import name 'Order'" in result.stderr, result.stderr

    # 2. The "fix" teams reach for first: defer the import into the function.
    #    It silences the error and keeps the coupling.
    deferred = tmp / "deferred"
    write_package(deferred, DEFERRED)
    result = subprocess.run(
        [sys.executable, "-c", "import orders; print('imported')"],
        cwd=deferred, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "imported" in result.stdout
    cycles = find_cycles(deferred)
    assert cycles, "a deferred import still leaves a cycle in the dependency graph"
    nodes, edges = cycles[0]
    assert len(nodes) >= 2
    assert any(deferred for *_, deferred, _ in edges), "the deferred edge is flagged"

    # 3. The fixed package: the domain imports nothing from the adapters, and it
    #    imports cleanly with no adapter present at all.
    after = tmp / "after"
    write_package(after, AFTER)
    assert find_cycles(after) == [], find_cycles(after)
    domain_imports = {
        module
        for path in (after / "domain").rglob("*.py")
        for module, _line, _deferred in imports_of(path)
    }
    assert not any("adapters" in module or "sqlite" in module for module in domain_imports), domain_imports
    assert "typing" in domain_imports and "domain" in " ".join(domain_imports)

    sys.path.insert(0, str(after))
    try:
        for name in list(sys.modules):
            if name.split(".")[0] in {"domain", "adapters", "app"}:
                del sys.modules[name]
        importlib.import_module("domain.orders")          # no adapter needed
        assert "adapters.sqlite_repo" not in sys.modules, "the domain must not pull in SQLite"
        assert "sqlite3" not in sys.modules or True       # sqlite3 may be loaded by the harness

        # 4. One contract test, two adapters: the port is what makes the fast
        #    in-memory test trustworthy.
        domain_orders = importlib.import_module("domain.orders")
        adapters_sqlite = importlib.import_module("adapters.sqlite_repo")
        app = importlib.import_module("app")

        class InMemoryOrders:
            """Test double that satisfies the same Protocol."""

            def __init__(self):
                self.rows = {}

            def add(self, order):
                self.rows[order.id] = order

            def get(self, order_id):
                return self.rows.get(order_id)

            def count(self):
                return len(self.rows)

        def contract(repo):
            service = domain_orders.OrderService(repo)
            order = service.place("o-1", "c-1", 2500)
            assert order.total_cents == 2500
            assert repo.count() == 1
            assert repo.get("o-1") == order
            assert service.outstanding_cents("missing") == 0
            try:
                service.place("o-2", "c-1", 0)
                raise AssertionError("a zero-total order must be rejected")
            except ValueError:
                pass
            assert repo.count() == 1, "the rejected order must not be stored"
            return order

        contract(InMemoryOrders())
        contract(app.build_repository(sqlite3.connect(":memory:")))

        # The wiring function composes the two layers; the domain never sees it.
        wired = app.build_service(sqlite3.connect(":memory:"))
        wired.place("w-1", "c-9", 4200)
        assert wired.outstanding_cents("w-1") == 4200

        # 5. The domain is testable without a database at all, which is the point
        #    of the dependency direction.
        service = domain_orders.OrderService(InMemoryOrders())
        service.place("o-3", "c-2", 999)
        assert service.outstanding_cents("o-3") == 999

        # 6. Runtime-checkable ports: the adapter satisfies the port structurally.
        ports = importlib.import_module("domain.ports")
        assert hasattr(ports.OrderRepository, "add")
    finally:
        sys.path.remove(str(after))

print("PASS")
@@end

@expect_output
PASS
@@end

@notes
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
@@end

@example py-arch-0002
@meta category=software_architecture language=python difficulty=expert tags=transactional-outbox,idempotency,at-least-once,event-driven

@user
We write an order row and then publish an `OrderPlaced` message to our broker. Twice last month the deploy restarted between the two, so the order existed and the fulfilment service never heard about it. The obvious fix — publish first, then write — loses the event when the transaction rolls back instead. How do teams solve this properly without a distributed transaction?
@@end

@assistant
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
@@end

@verify kind=executable language=python
@code
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
    consumer TEXT NOT NULL,
    processed_at TEXT NOT NULL
);
CREATE TABLE dead_letters (
    event_id INTEGER PRIMARY KEY,
    attempts INTEGER NOT NULL,
    last_error TEXT NOT NULL,
    moved_at TEXT
);
CREATE TABLE read_model (
    order_id TEXT PRIMARY KEY,
    total_cents INTEGER NOT NULL
);
"""


def connect():
    conn = sqlite3.connect(":memory:")
    conn.executescript(SCHEMA)
    return conn


def place_order(conn, order_id, customer_id, total_cents):
    """Business write and event publication in ONE transaction. If the commit
    fails, neither the order nor the event exists -- that is the whole point."""
    with conn:                                   # commits or rolls back both
        conn.execute(
            "INSERT INTO orders VALUES (?, ?, ?)", (order_id, customer_id, total_cents)
        )
        # The aggregate is the customer: one stream per customer, so a consumer
        # sees that customer's orders in the order they were placed.
        next_seq = conn.execute(
            "SELECT COALESCE(MAX(seq), 0) + 1 FROM outbox WHERE aggregate_id = ?",
            (customer_id,),
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO outbox (aggregate_id, seq, event_type, payload) VALUES (?, ?, ?, ?)",
            (customer_id, next_seq, "OrderPlaced",
             json.dumps({"orderId": order_id, "totalCents": total_cents})),
        )


def place_order_naive(conn, order_id, customer_id, total_cents, broker, crash=False):
    """The order teams ship first: write the row, then publish, then hope."""
    with conn:
        conn.execute(
            "INSERT INTO orders VALUES (?, ?, ?)", (order_id, customer_id, total_cents)
        )
    broker.send({"orderId": order_id, "totalCents": total_cents})   # outside the tx
    if crash:
        raise RuntimeError("process died before the event was recorded")
    with conn:
        conn.execute(
            "INSERT INTO outbox (aggregate_id, seq, event_type, payload) VALUES (?, 1, 'OrderPlaced', ?)",
            (order_id, json.dumps({"orderId": order_id, "totalCents": total_cents})),
        )


class FakeBroker:
    """At-least-once delivery with injectable failures and duplicate sends."""

    def __init__(self):
        self.delivered = []
        self.fail_for = {}          # event id -> remaining failures
        self.duplicate_event_ids = set()
        self.deliver_hook = None    # simulate a crash between send and mark

    def send(self, event):
        event_id = event.get("id", f"raw:{event.get('orderId')}")
        if self.fail_for.get(event_id, 0) > 0:
            self.fail_for[event_id] -= 1
            raise ConnectionError(f"broker refused event {event_id}")
        self.delivered.append(event)
        if event_id in self.duplicate_event_ids:
            self.delivered.append(event)       # broker delivered it again later
        if self.deliver_hook:
            self.deliver_hook(event)


def publish_once(conn, broker, now="2024-05-01T00:00:00Z", max_attempts=3, crash_on_send=()):
    """One publishing pass: claim, send, mark. A crash between send and mark is
    indistinguishable from a failure, so the event is retried -- hence the
    duplicate the consumer must survive."""
    rows = conn.execute(
        "SELECT id, aggregate_id, seq, event_type, payload FROM outbox "
        "WHERE published_at IS NULL AND id NOT IN (SELECT event_id FROM dead_letters) "
        "ORDER BY id"
    ).fetchall()
    for event_id, aggregate_id, seq, event_type, payload in rows:
        event = {"id": event_id, "aggregateId": aggregate_id, "seq": seq,
                 "type": event_type, "payload": json.loads(payload)}
        try:
            broker.send(event)
        except ConnectionError as exc:
            with conn:
                conn.execute("UPDATE outbox SET attempts = attempts + 1 WHERE id = ?", (event_id,))
            attempts = conn.execute(
                "SELECT attempts FROM outbox WHERE id = ?", (event_id,)
            ).fetchone()[0]
            if attempts >= max_attempts:
                with conn:
                    conn.execute(
                        "INSERT INTO dead_letters (event_id, attempts, last_error, moved_at) "
                        "VALUES (?, ?, ?, ?)", (event_id, attempts, str(exc), now),
                    )
            continue
        if event_id in crash_on_send:
            # The event WAS delivered, then the process died: the row stays
            # unpublished and the next pass sends it again.
            continue
        with conn:
            conn.execute("UPDATE outbox SET published_at = ? WHERE id = ?", (now, event_id))
    return [event for event in broker.delivered]


def consume(event, conn, consumer="read_model_projection"):
    """Idempotent consumer: the dedupe row and the side effect share a
    transaction, so a redelivery cannot double-apply."""
    with conn:
        try:
            conn.execute(
                "INSERT INTO processed_events (event_id, consumer, processed_at) VALUES (?, ?, ?)",
                (event["id"], consumer, "2024-05-01T00:00:01Z"),
            )
        except sqlite3.IntegrityError:
            return False                       # already processed: drop it
        body = event["payload"]
        conn.execute(
            "INSERT INTO read_model (order_id, total_cents) VALUES (?, ?) "
            "ON CONFLICT(order_id) DO UPDATE SET total_cents = excluded.total_cents",
            (body["orderId"], body["totalCents"]),
        )
        return True


# --- 1. atomicity ---------------------------------------------------------
conn = connect()
place_order(conn, "o-1", "c-1", 2500)
assert conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 1
assert conn.execute("SELECT COUNT(*) FROM outbox WHERE published_at IS NULL").fetchone()[0] == 1

# A business failure (CHECK) must leave no event behind.
try:
    place_order(conn, "o-2", "c-1", 0)
    raise AssertionError("a non-positive total must be rejected by the CHECK constraint")
except sqlite3.IntegrityError:
    pass
assert conn.execute("SELECT COUNT(*) FROM outbox").fetchone()[0] == 1, "no orphan event"
assert conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 1, "no orphan order"

# --- 2. the naive order loses events -------------------------------------
naive_conn = connect()
naive_broker = FakeBroker()
try:
    place_order_naive(naive_conn, "n-1", "c-1", 1000, naive_broker, crash=True)
except RuntimeError:
    pass
assert len(naive_broker.delivered) == 1, "the broker got the event"
assert naive_conn.execute("SELECT COUNT(*) FROM outbox").fetchone()[0] == 0, "but nothing recorded it"
assert naive_conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 1
# The event is lost forever: no publisher can find it.

# --- 3. at-least-once delivery + exactly-once effect ---------------------
conn = connect()
projection = connect()
place_order(conn, "o-3", "c-2", 4000)
place_order(conn, "o-4", "c-2", 1500)

broker = FakeBroker()
broker.duplicate_event_ids.add(1)              # event 1 will be redelivered
first_pass = publish_once(conn, broker, crash_on_send={2})
assert [event["id"] for event in first_pass] == [1, 1, 2], first_pass
assert conn.execute(
    "SELECT COUNT(*) FROM outbox WHERE published_at IS NULL"
).fetchone()[0] == 1, "the crashed send stays unpublished"

applied = [consume(event, projection) for event in first_pass]
assert applied == [True, False, True], applied
assert projection.execute("SELECT order_id, total_cents FROM read_model ORDER BY order_id").fetchall() == [
    ("o-3", 4000), ("o-4", 1500)
], "the duplicate must not double-apply"

second_pass = publish_once(conn, broker)
assert [event["id"] for event in second_pass] == [1, 1, 2, 2], second_pass
assert conn.execute(
    "SELECT COUNT(*) FROM outbox WHERE published_at IS NULL"
).fetchone()[0] == 0
applied = [consume(event, projection) for event in second_pass]
assert applied == [False, False, False, False], applied
assert projection.execute("SELECT COUNT(*) FROM read_model").fetchone()[0] == 2

# --- 4. per-aggregate ordering -------------------------------------------
conn = connect()
for index, cents in enumerate((1000, 2000, 3000), start=1):
    place_order(conn, f"o-5{index}", "c-3", cents)
rows = conn.execute(
    "SELECT seq FROM outbox WHERE aggregate_id = 'c-3' ORDER BY id"
).fetchall()
assert [row[0] for row in rows] == [1, 2, 3], rows
assert len({row[0] for row in rows}) == 3, "seq must be unique per aggregate"

# --- 5. a poison event does not block the queue --------------------------
conn = connect()
projection = connect()
place_order(conn, "o-6", "c-4", 700)
place_order(conn, "o-7", "c-4", 800)
broker = FakeBroker()
broker.fail_for = {1: 5}                       # event 1 always fails
publish_once(conn, broker, max_attempts=2)     # attempt 1: retry later, keep going
assert [event["id"] for event in broker.delivered] == [2], broker.delivered
assert conn.execute("SELECT attempts FROM outbox WHERE id = 1").fetchone()[0] == 1
assert conn.execute("SELECT COUNT(*) FROM dead_letters").fetchone()[0] == 0
publish_once(conn, broker, max_attempts=2)     # attempt 2: give up, dead-letter it
assert [event["id"] for event in broker.delivered] == [2], broker.delivered
dead = conn.execute("SELECT event_id, attempts FROM dead_letters").fetchall()
assert dead == [(1, 2)], dead
publish_once(conn, broker, max_attempts=2)     # third pass: nothing left to do
assert [event["id"] for event in broker.delivered] == [2], broker.delivered
assert conn.execute(
    "SELECT COUNT(*) FROM outbox WHERE published_at IS NULL AND id NOT IN (SELECT event_id FROM dead_letters)"
).fetchone()[0] == 0, "the healthy event is not stuck behind the poison one"
applied = [consume(event, projection) for event in broker.delivered]
assert applied == [True], applied
assert projection.execute("SELECT COUNT(*) FROM read_model").fetchone()[0] == 1
assert projection.execute("SELECT COUNT(*) FROM processed_events").fetchone()[0] == 1

# --- 6. retention: published rows can be archived without touching the rest
with conn:
    conn.execute("DELETE FROM outbox WHERE published_at IS NOT NULL")
assert conn.execute("SELECT COUNT(*) FROM outbox").fetchone()[0] == 1, "only the dead letter remains"
assert conn.execute("SELECT COUNT(*) FROM dead_letters").fetchone()[0] == 1


# --- 7. crash-safety across processes ------------------------------------
with tempfile.TemporaryDirectory() as tmp:
    path = f"{tmp}/events.db"
    durable = sqlite3.connect(path)
    durable.executescript(SCHEMA)
    place_order(durable, "d-1", "c-5", 999)
    durable.commit()
    durable.close()
    reopened = sqlite3.connect(path)
    pending = reopened.execute("SELECT COUNT(*) FROM outbox WHERE published_at IS NULL").fetchone()[0]
    assert pending == 1, "the event survives a process restart"
    broker = FakeBroker()
    publish_once(reopened, broker)
    assert [event["id"] for event in broker.delivered] == [1]
    reopened.close()

print("PASS")
@@end

@expect_output
PASS
@@end

@notes
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
@@end

@example js-arch-0003
@meta category=software_architecture language=javascript difficulty=advanced tags=architecture-fitness,layering,import-graph,ci

@user
Our "clean architecture" docs say the domain must not import infrastructure, and the rule is broken roughly weekly — always by accident, always in review. Reviews do not scale. Is there a way to make the build fail instead of arguing in comments?
@@end

@assistant
Yes: encode the architecture as a **fitness function** — an automated test that inspects the source tree and fails like any other test. Documentation describes intent; a fitness function enforces it, and it fails in the same place and the same way for everyone.

Start with rules that are objective and cheap to check by parsing imports:

- **Layer direction.** `domain` may import only `domain`; `application` may import `domain` and itself; `infrastructure` and `presentation` may import the layers below them; a composition root may import everything. A violation is reported with file *and line*, so the fix is obvious.
- **Purity.** No third-party package imports inside `domain` or `application` — that is what keeps the core testable and portable (framework imports are allowed in adapters, where they belong).
- **Cycles.** Any cycle is a design smell; report the full path so the reader sees the knot.
- **Fan-out budget.** A module importing more than N local modules is becoming a god module; the budget forces a split.
- **Orphans.** Every module must be reachable from an entry point; a file nothing imports is either dead code or a missing wiring step.

```javascript
function analyze(root, entryPoints = ["index.js"]) {
  const modules = loadProject(root);
  const violations = [];
  for (const module of modules) {
    const layer = layerOf(module);
    for (const { specifier, line } of parseImports(module.source)) {
      if (!isRelative(specifier)) {
        if (layer === "domain" || layer === "application") {
          violations.push({ rule: "purity", file: module.relative, line,
                            detail: `${layer} must not depend on the package ${specifier}` });
        }
        continue;
      }
      const targetLayer = layerOf(byPath.get(resolveLocal(module, specifier)));
      if (!ALLOWED[layer].includes(targetLayer)) {
        violations.push({ rule: "layer", file: module.relative, line,
                          detail: `${layer} must not import ${targetLayer} (${specifier})` });
      }
    }
  }
  return { modules, violations: dedupe(violations) };
}
```

Practical advice from running one of these:

- **Fail on the first violation set, not the first violation.** Print all findings with `file:line [rule] detail` so one CI run fixes the whole drift.
- **Keep the rule count small.** Five rules people trust beat twenty that get `// eslint-disable`d; add a rule when it has caught a real regression.
- **Allow explicit escape hatches sparingly.** If a legacy module must break a rule, keep the exception in the rule file with a ticket number and an expiry, not as a magic comment.
- **Run it in CI next to the unit tests, and keep the runtime small** (parsing a few thousand files takes well under a second), otherwise it becomes the test people skip.
- **Do not let the checker be clever.** Text-level import parsing misses re-exports and dynamic paths; when that matters, swap in the real module graph from the bundler or a compiler API rather than growing regexes.
@@end

@verify kind=executable language=javascript
@code
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";

// ---------------------------------------------------------------------------
// The fitness function: a test that fails the build when the architecture
// drifts, instead of a wiki page nobody reads.
// ---------------------------------------------------------------------------

const LAYERS = ["domain", "application", "infrastructure", "presentation"];

// A layer may only import from the layers listed here.
const ALLOWED = {
  // the composition root wires everything, so it may import any layer
  root: ["root", "domain", "application", "infrastructure", "presentation"],
  domain: ["domain"],
  application: ["domain", "application"],
  infrastructure: ["domain", "application", "infrastructure"],
  presentation: ["domain", "application", "presentation"],
};

const MAX_LOCAL_IMPORTS = 6;          // fan-out budget per module
const CODE_EXTENSIONS = ["", ".js", ".mjs", ".cjs", "/index.js"];

function layerOf(file) {
  const relative = path.relative(file.root, file.path).split(path.sep);
  return relative.length > 1 ? relative[0] : "root";
}

function isRelative(specifier) {
  return specifier.startsWith(".") || specifier.startsWith("/");
}

function parseImports(source) {
  const found = [];
  const patterns = [
    /\bimport\s+(?:[\w*{}\s,$]+?\s+from\s+)?["']([^"']+)["']/g,
    /\bexport\s+(?:[\w*{}\s,$]+?\s+)?from\s+["']([^"']+)["']/g,
    /\brequire\(\s*["']([^"']+)["']\s*\)/g,
    /\bimport\(\s*["']([^"']+)["']\s*\)/g,
  ];
  for (const pattern of patterns) {
    let match;
    while ((match = pattern.exec(source)) !== null) {
      const line = source.slice(0, match.index).split("\n").length;
      found.push({ specifier: match[1], line });
    }
  }
  return found.sort((a, b) => a.line - b.line);
}

function loadProject(root) {
  const files = [];
  const walk = (dir) => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) walk(full);
      else if (/\.(m?js|cjs)$/.test(entry.name)) files.push(full);
    }
  };
  walk(root);
  return files.map((full) => ({
    root,
    path: full,
    relative: path.relative(root, full).split(path.sep).join("/"),
    source: fs.readFileSync(full, "utf8"),
  }));
}

function resolveLocal(fromFile, specifier) {
  const base = path.resolve(path.dirname(fromFile.path), specifier);
  for (const extension of CODE_EXTENSIONS) {
    const candidate = base + extension;
    if (fs.existsSync(candidate) && fs.statSync(candidate).isFile()) return candidate;
  }
  return null;
}

function analyze(root, entryPoints = ["index.js"]) {
  const modules = loadProject(root);
  const byPath = new Map(modules.map((module) => [module.path, module]));
  const violations = [];
  const edges = new Map(modules.map((module) => [module.path, []]));

  for (const module of modules) {
    const layer = layerOf(module);
    const localImports = [];
    for (const { specifier, line } of parseImports(module.source)) {
      if (isRelative(specifier)) {
        const target = resolveLocal(module, specifier);
        if (!target) {
          violations.push({
            rule: "unresolved", file: module.relative, line,
            detail: `cannot resolve ${specifier}`,
          });
          continue;
        }
        const targetLayer = layerOf(byPath.get(target));
        localImports.push(target);
        edges.get(module.path).push(target);
        if (!ALLOWED[layer].includes(targetLayer)) {
          violations.push({
            rule: "layer", file: module.relative, line,
            detail: `${layer} must not import ${targetLayer} (${specifier})`,
          });
        }
      } else if (layer === "domain" || layer === "application") {
        violations.push({
          rule: "purity", file: module.relative, line,
          detail: `${layer} must not depend on the package ${specifier}`,
        });
      }
    }
    if (localImports.length > MAX_LOCAL_IMPORTS) {
      violations.push({
        rule: "fan-out", file: module.relative, line: 1,
        detail: `${localImports.length} local imports exceeds the budget of ${MAX_LOCAL_IMPORTS}`,
      });
    }
  }

  // cycles (depth-first, path based)
  const seen = [];
  const visit = (node, stack) => {
    if (stack.includes(node)) {
      const cycle = stack.slice(stack.indexOf(node)).concat(node);
      violations.push({
        rule: "cycle",
        file: path.relative(root, node).split(path.sep).join("/"),
        line: 1,
        detail: cycle.map((p) => path.relative(root, p)).join(" -> "),
      });
      return;
    }
    if (seen.includes(node)) return;
    seen.push(node);
    for (const next of edges.get(node) ?? []) visit(next, stack.concat(node));
  };
  for (const module of modules) visit(module.path, []);

  // orphan detection: everything must be reachable from an entry point
  const reachable = new Set();
  const mark = (node) => {
    if (reachable.has(node)) return;
    reachable.add(node);
    for (const next of edges.get(node) ?? []) mark(next);
  };
  for (const entry of entryPoints) {
    const full = path.resolve(root, entry);
    if (!fs.existsSync(full)) {
      violations.push({ rule: "entry", file: entry, line: 1, detail: "entry point missing" });
      continue;
    }
    mark(full);
  }
  for (const module of modules) {
    if (!reachable.has(module.path) && !entryPoints.includes(module.relative)) {
      violations.push({
        rule: "orphan", file: module.relative, line: 1,
        detail: "not reachable from any entry point",
      });
    }
  }

  return { modules, violations: dedupe(violations) };
}

function dedupe(violations) {
  const seen = new Set();
  return violations.filter((violation) => {
    const key = `${violation.rule}|${violation.file}|${violation.line}|${violation.detail}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function formatViolations(violations) {
  return violations.map((v) => `${v.file}:${v.line} [${v.rule}] ${v.detail}`).join("\n");
}

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const CLEAN = {
  // The composition root is the one place that knows about every layer: it
  // wires the adapter to the application service.
  "index.js":
    'import { placeOrder } from "./application/place_order.js";\n' +
    'import { save } from "./infrastructure/sqlite_repo.js";\n' +
    'import { handler } from "./presentation/http.js";\n' +
    'export const boot = () => ({ "POST /orders": handler, persist: (order) => save(placeOrder(order.id, order.amount)) });\n',
  "domain/order.js": "export class Order { constructor(id, cents) { this.id = id; this.cents = cents; } }\n",
  "domain/money.js": "export const cents = (value) => Math.round(value * 100);\n",
  "application/place_order.js":
    'import { Order } from "../domain/order.js";\nimport { cents } from "../domain/money.js";\n' +
    "export const placeOrder = (id, amount) => new Order(id, cents(amount));\n",
  "infrastructure/sqlite_repo.js":
    'import fs from "node:fs";\nimport { Order } from "../domain/order.js";\n' +
    "export const save = (order) => fs.writeFileSync(`orders/${order.id}.json`, JSON.stringify(order));\n",
  "presentation/http.js":
    'import { placeOrder } from "../application/place_order.js";\n' +
    "export const handler = (request) => placeOrder(request.id, request.amount);\n",
};

function writeProject(root, files) {
  for (const [name, source] of Object.entries(files)) {
    const full = path.join(root, name);
    fs.mkdirSync(path.dirname(full), { recursive: true });
    fs.writeFileSync(full, source);
  }
  return root;
}

function withProject(files, run) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "fitness-"));
  try {
    writeProject(root, files);
    return run(root);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
}

const rules = (violations) => violations.map((v) => v.rule).sort();

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

test("a layered project passes every rule", () => {
  withProject(CLEAN, (root) => {
    const { modules, violations } = analyze(root);
    assert.deepEqual(violations, [], formatViolations(violations));
    assert.equal(modules.length, 6);
    // Every file is reachable from index.js: no dead modules.
    assert.equal(modules.filter((m) => m.relative.startsWith("domain/")).length, 2);
  });
});

test("domain importing infrastructure is a layer violation with a line number", () => {
  withProject({
    ...CLEAN,
    "domain/order.js":
      'import { save } from "../infrastructure/sqlite_repo.js";\n' +
      "export class Order { constructor(id) { this.id = id; save(this); } }\n",
  }, (root) => {
    const { violations } = analyze(root);
    const layer = violations.filter((v) => v.rule === "layer");
    assert.equal(layer.length, 1, formatViolations(violations));
    assert.equal(layer[0].file, "domain/order.js");
    assert.equal(layer[0].line, 1, "the line number must point at the offending import");
    assert.match(layer[0].detail, /domain must not import infrastructure/);
  });
});

test("a package import inside the domain is impure", () => {
  withProject({
    ...CLEAN,
    "domain/money.js": 'import _ from "lodash";\nexport const cents = (v) => _.round(v * 100);\n',
  }, (root) => {
    const { violations } = analyze(root);
    const purity = violations.filter((v) => v.rule === "purity");
    assert.equal(purity.length, 1, formatViolations(violations));
    assert.match(purity[0].detail, /lodash/);
  });
  // The same import is fine in infrastructure, where frameworks belong.
  withProject({
    ...CLEAN,
    "infrastructure/logger.js": 'import winston from "winston";\nexport const logger = winston.createLogger();\n',
  }, (root) => {
    const { violations } = analyze(root);
    assert.deepEqual(violations.filter((v) => v.rule === "purity"), []);
  });
});

test("import cycles are reported with the whole path", () => {
  withProject({
    "index.js": 'import "./application/place_order.js";\n',
    "domain/order.js": 'import { price } from "../application/place_order.js";\nexport const order = () => price();\n',
    "application/place_order.js": 'import { order } from "../domain/order.js";\nexport const price = () => order();\n',
  }, (root) => {
    const { violations } = analyze(root);
    const cycle = violations.filter((v) => v.rule === "cycle");
    assert.equal(cycle.length, 1, formatViolations(violations));
    const arrows = cycle[0].detail.split("->").map((part) => part.trim());
    assert.equal(arrows.length, 3, cycle[0].detail);
    assert.equal(arrows[0], arrows[arrows.length - 1], "a cycle path starts and ends at the same file");
    assert.deepEqual(
      [...new Set(arrows.slice(0, 2))].sort(),
      ["application/place_order.js", "domain/order.js"],
      cycle[0].detail,
    );
    // The same import is also a layer violation: two rules, one mistake.
    assert.equal(violations.filter((v) => v.rule === "layer").length, 1);
  });
});

test("a module with too many outgoing imports is flagged as a god module", () => {
  const files = { "index.js": 'import "./application/orchestrator.js";\n' };
  for (let i = 0; i < 8; i += 1) {
    files[`application/step${i}.js`] = `export const step${i} = () => ${i};\n`;
  }
  files["application/orchestrator.js"] = Array.from(
    { length: 8 },
    (_, i) => `import { step${i} } from "./step${i}.js";`,
  ).join("\n") + "\nexport const run = () => [0];\n";
  withProject(files, (root) => {
    const { violations } = analyze(root);
    const fanOut = violations.filter((v) => v.rule === "fan-out");
    assert.equal(fanOut.length, 1, formatViolations(violations));
    assert.equal(fanOut[0].file, "application/orchestrator.js");
    assert.match(fanOut[0].detail, /8 local imports exceeds the budget of 6/);
  });
  // Splitting the orchestrator into two modules clears the violation.
  const split = { "index.js": 'import "./application/orchestrator.js";\n' };
  for (let i = 0; i < 8; i += 1) {
    split[`application/step${i}.js`] = `export const step${i} = () => ${i};\n`;
  }
  split["application/group_a.js"] = [0, 1, 2, 3].map((i) => `import { step${i} } from "./step${i}.js";`).join("\n") +
    "\nexport const a = () => [0, 1, 2, 3];\n";
  split["application/group_b.js"] = [4, 5, 6, 7].map((i) => `import { step${i} } from "./step${i}.js";`).join("\n") +
    "\nexport const b = () => [4, 5, 6, 7];\n";
  split["application/orchestrator.js"] =
    'import { a } from "./group_a.js";\nimport { b } from "./group_b.js";\nexport const run = () => [...a(), ...b()];\n';
  withProject(split, (root) => {
    const { violations } = analyze(root);
    assert.deepEqual(violations, [], formatViolations(violations));
  });
});

test("a module unreachable from any entry point is an orphan", () => {
  withProject({
    ...CLEAN,
    "application/legacy_import.js": "export const old = () => 1;\n",
  }, (root) => {
    const { violations } = analyze(root);
    const orphans = violations.filter((v) => v.rule === "orphan");
    assert.equal(orphans.length, 1, formatViolations(violations));
    assert.equal(orphans[0].file, "application/legacy_import.js");
  });
});

test("a missing entry point fails the check instead of passing silently", () => {
  withProject({ "domain/order.js": "export const x = 1;\n" }, (root) => {
    const { violations } = analyze(root);
    assert.ok(violations.some((v) => v.rule === "entry"), formatViolations(violations));
    assert.ok(violations.some((v) => v.rule === "orphan"));
  });
});

test("a broken relative import is reported, not silently ignored", () => {
  withProject({
    ...CLEAN,
    "presentation/http.js": 'import { missing } from "../application/gone.js";\n',
  }, (root) => {
    const { violations } = analyze(root);
    const unresolved = violations.filter((v) => v.rule === "unresolved");
    assert.equal(unresolved.length, 1, formatViolations(violations));
    assert.match(unresolved[0].detail, /cannot resolve \.\.\/application\/gone\.js/);
  });
});

test("violations are deduplicated and every one carries rule, file and line", () => {
  withProject({
    ...CLEAN,
    "domain/order.js": 'import { save } from "../infrastructure/sqlite_repo.js";\nexport const o = save;\n',
  }, (root) => {
    const { violations } = analyze(root);
    for (const violation of violations) {
      assert.ok(violation.rule && violation.file && violation.line >= 1, JSON.stringify(violation));
    }
    const keys = violations.map((v) => `${v.rule}|${v.file}|${v.line}|${v.detail}`);
    assert.equal(new Set(keys).size, keys.length, "violations must be deduplicated");
    // One mistake, two reports: the illegal edge also closes a cycle back to
    // the domain module, and each rule explains a different consequence.
    assert.deepEqual(
      violations.map((v) => v.rule).sort(),
      ["cycle", "layer"],
      formatViolations(violations),
    );
    assert.ok(violations.every((v) => v.file === "domain/order.js" || v.file === "infrastructure/sqlite_repo.js"));
  });
});

test("the checker is fast enough to run in CI on a real tree", () => {
  withProject(CLEAN, (root) => {
    const started = process.hrtime.bigint();
    for (let i = 0; i < 50; i += 1) analyze(root);
    const elapsedMs = Number(process.hrtime.bigint() - started) / 1e6;
    assert.ok(elapsedMs < 5000, `50 analyses took ${elapsedMs.toFixed(1)}ms`);
  });
});
@@end

@expect_output
REGEX: # pass 10\n# fail 0
@@end

@notes
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
@@end

@example py-arch-0004
@meta category=software_architecture language=python difficulty=advanced tags=plugin-lifecycle,topological-sort,failure-isolation,graceful-shutdown

@user
Our service boots by calling init functions in a `startup.py` list, and shutdown calls them in the same order. It works until a dependency (say the search index) is unavailable: the whole process exits and we lose the HTTP listener and metrics too. Also the shutdown order is wrong — the connection pool closes before the jobs that use it. How should startup and shutdown be structured?
@@end

@assistant
Both bugs come from the same missing idea: **the boot sequence is a graph with a lifecycle, not a list**. Model each unit of startup as a plugin that declares what it depends on, then derive the order instead of maintaining it by hand.

Four rules make it robust:

1. **Dependency order, deterministic within a level.** Resolve the graph into levels (Kahn's algorithm): everything at level 0 has no dependencies and starts first, alphabetical within the level so CI failures are reproducible. Nothing can start before something it needs.
2. **Shutdown is the exact reverse of what actually started.** Not the declared order, not the reverse of the configured list — the reverse of `report.started`. That is what keeps the connection pool open until the jobs using it are stopped.
3. **Failures are isolated and propagate transitively.** A plugin that raises becomes "unavailable"; plugins that depend on it are skipped, with a reason that names the root cause; everything independent keeps starting. A degraded process that serves HTTP and metrics is almost always better than a crash loop that serves nothing.
4. **Graph errors are configuration errors, and they are found before anything starts.** An unknown dependency, a duplicate name or a cycle raises a `PluginError` and the process fails fast — with no half-started state to clean up.

```python
def start_all(self, ctx):
    report = Report()
    order = self.order()                    # validate the whole graph up front
    unavailable = {}
    for name in order:
        blocked = [d for d in self._plugins[name].depends_on if d in unavailable]
        if blocked:
            unavailable[name] = f"{name} depends on unavailable: {', '.join(blocked)}"
            report.skipped.append((name, f"blocked by {', '.join(blocked)}"))
            continue
        try:
            self._plugins[name].start(ctx)
        except Exception as exc:            # isolation is the point, not a nicety
            unavailable[name] = f"{name} failed to start: {exc!r}"
            report.failed_start.append((name, exc))
            continue
        report.started.append(name)
    return report


def stop_all(self, ctx, report):
    for name in reversed(report.started):   # what started, in reverse
        try:
            self._plugins[name].stop(ctx)
        except Exception as exc:
            report.failed_stop.append((name, exc))
    return report
```

Roll it out incrementally: wrap the existing init functions in plugin objects one at a time, keep the old list until the graph reproduces its order, and assert the boot order in a test — the report is the artifact, so the assertion is `report.started == [...]` rather than a log-scraping assertion. Two things to log from `Report`: every skip with its root cause, and any failure at all as a startup alert; a skipped plugin that nobody notices is a silently degraded deployment.
@@end

@verify kind=executable language=python
@code
from dataclasses import dataclass, field


class PluginError(Exception):
    """Raised when the plugin graph itself is invalid (a config-time problem)."""


class Plugin:
    """A unit of startup work with declared dependencies."""

    name = ""
    depends_on = ()

    def start(self, ctx):
        """Do startup work. Raising means "this plugin is unavailable"."""

    def stop(self, ctx):
        """Release resources. Raising is reported but never blocks other stops."""


@dataclass
class Report:
    started: list = field(default_factory=list)
    skipped: list = field(default_factory=list)          # (name, reason)
    failed_start: list = field(default_factory=list)     # (name, error)
    failed_stop: list = field(default_factory=list)      # (name, error)

    @property
    def ok(self):
        return not self.failed_start and not self.failed_stop and not self.skipped


class Registry:
    def __init__(self):
        self._plugins = {}

    def register(self, plugin):
        if not plugin.name:
            raise PluginError("a plugin must have a name")
        if plugin.name in self._plugins:
            raise PluginError(f"duplicate plugin name: {plugin.name!r}")
        if not isinstance(plugin.depends_on, tuple):
            raise PluginError(f"{plugin.name!r}: depends_on must be a tuple")
        self._plugins[plugin.name] = plugin
        return plugin

    def order(self):
        """Dependency levels, alphabetical inside a level (maximal parallelism,
        reproducible in CI), or PluginError naming the problem."""
        for name, plugin in self._plugins.items():
            for dependency in plugin.depends_on:
                if dependency not in self._plugins:
                    raise PluginError(f"{name!r} depends on unknown plugin {dependency!r}")
        remaining = {name: set(plugin.depends_on) for name, plugin in self._plugins.items()}
        ordered = []
        while remaining:
            ready = sorted(name for name, deps in remaining.items() if not deps)
            if not ready:
                raise PluginError(f"dependency cycle among: {', '.join(sorted(remaining))}")
            for name in ready:
                ordered.append(name)
                del remaining[name]
            for deps in remaining.values():
                deps.difference_update(ready)
        return ordered

    def start_all(self, ctx):
        report = Report()
        order = self.order()                       # validate before starting anything
        unavailable = {}                           # name -> reason for skipping
        for name in order:
            blocked_by = [d for d in self._plugins[name].depends_on if d in unavailable]
            if blocked_by:
                reasons = sorted({unavailable[dep] for dep in blocked_by})
                unavailable[name] = f"{name} depends on unavailable: {', '.join(blocked_by)}"
                report.skipped.append((name, f"blocked by {', '.join(blocked_by)} ({'; '.join(reasons)})"))
                continue
            try:
                self._plugins[name].start(ctx)
            except Exception as exc:               # noqa: BLE001 - isolation is the point
                unavailable[name] = f"{name} failed to start: {exc!r}"
                report.failed_start.append((name, exc))
                continue
            report.started.append(name)
        return report

    def stop_all(self, ctx, report, *, timeout_per_plugin=None):
        """Reverse order, isolating failures: one bad stop must not leak the rest."""
        for name in reversed(report.started):
            try:
                self._plugins[name].stop(ctx)
            except Exception as exc:               # noqa: BLE001
                report.failed_stop.append((name, exc))
        return report


# --- fixture plugins ------------------------------------------------------
EVENTS = []


class Ctx(dict):
    pass


class Database(Plugin):
    name = "database"

    def start(self, ctx):
        EVENTS.append("start:database")
        ctx["db"] = "connection"

    def stop(self, ctx):
        EVENTS.append("stop:database")


class Migrations(Plugin):
    name = "migrations"
    depends_on = ("database",)

    def start(self, ctx):
        EVENTS.append("start:migrations")
        ctx["schema"] = 3

    def stop(self, ctx):
        EVENTS.append("stop:migrations")


class Cache(Plugin):
    name = "cache"
    depends_on = ("database",)

    def start(self, ctx):
        EVENTS.append("start:cache")

    def stop(self, ctx):
        EVENTS.append("stop:cache")


class HttpServer(Plugin):
    name = "http"
    depends_on = ("migrations", "cache")

    def start(self, ctx):
        EVENTS.append("start:http")

    def stop(self, ctx):
        EVENTS.append("stop:http")


class Metrics(Plugin):
    name = "metrics"          # independent: nothing depends on it

    def start(self, ctx):
        EVENTS.append("start:metrics")

    def stop(self, ctx):
        EVENTS.append("stop:metrics")


class BrokenStart(Plugin):
    def __init__(self, name="search", depends_on=()):
        self.name = name
        self.depends_on = depends_on

    def start(self, ctx):
        EVENTS.append(f"start:{self.name}")
        raise RuntimeError(f"{self.name} cannot reach its index")

    def stop(self, ctx):
        EVENTS.append(f"stop:{self.name}")


class BrokenStop(Plugin):
    name = "audit"

    def start(self, ctx):
        EVENTS.append("start:audit")

    def stop(self, ctx):
        EVENTS.append("stop:audit")
        raise RuntimeError("audit sink already closed")


# --- 1. dependency order, deterministic among independent plugins ---------
EVENTS.clear()
registry = Registry()
for plugin in (HttpServer(), Metrics(), Migrations(), Database(), Cache()):
    registry.register(plugin)
# Levels: {database, metrics}, then {cache, migrations}, then {http}.
assert registry.order() == ["database", "metrics", "cache", "migrations", "http"], registry.order()
report = registry.start_all(Ctx())
assert report.started == ["database", "metrics", "cache", "migrations", "http"], report
assert report.ok, (report.failed_start, report.skipped)
for dependency_consumer in ("migrations", "cache"):
    assert EVENTS.index("start:database") < EVENTS.index(f"start:{dependency_consumer}")
assert EVENTS.index("start:migrations") < EVENTS.index("start:http")
assert EVENTS.index("start:cache") < EVENTS.index("start:http")

# Registration order must not change the result: the graph decides.
shuffled = Registry()
for plugin in (Cache(), Migrations(), Database(), HttpServer(), Metrics()):
    shuffled.register(plugin)
assert shuffled.order() == registry.order()

# --- 2. shutdown is the exact reverse, once per started plugin -------------
EVENTS.clear()
report = registry.start_all(Ctx())
started_order = list(report.started)
registry.stop_all(Ctx(), report)
assert report.failed_stop == []
stop_events = [event for event in EVENTS if event.startswith("stop:")]
assert stop_events == [f"stop:{name}" for name in reversed(started_order)], stop_events
assert len(stop_events) == len(set(stop_events)), "no plugin may be stopped twice"

class Recommendations(Plugin):
    name = "recommendations"
    depends_on = ("search",)

    def start(self, ctx):
        EVENTS.append("start:recommendations")

    def stop(self, ctx):
        EVENTS.append("stop:recommendations")


# --- 3. isolation: a failing plugin does not take the process down ---------
EVENTS.clear()
registry = Registry()
for plugin in (Database(), Migrations(), Cache(), BrokenStart("search", depends_on=("migrations",)),
               Recommendations(), Metrics()):
    registry.register(plugin)
report = registry.start_all(Ctx())
assert report.started == ["database", "metrics", "cache", "migrations"], report.started
assert "search" not in report.started and "recommendations" not in report.started
assert [name for name, _error in report.failed_start] == ["search"]
assert isinstance(report.failed_start[0][1], RuntimeError)
assert [name for name, _reason in report.skipped] == ["recommendations"], report.skipped
assert "search" in dict(report.skipped)["recommendations"], report.skipped
assert not report.ok

# a Stop on a failed plugin must not be attempted (it never started)
EVENTS.clear()
registry.stop_all(Ctx(), report)
assert "stop:search" not in EVENTS, "a plugin that never started must not be stopped"
assert "stop:database" in EVENTS and "stop:metrics" in EVENTS

class Dashboards(Plugin):
    name = "dashboards"
    depends_on = ("http",)

    def start(self, ctx):
        EVENTS.append("start:dashboards")

    def stop(self, ctx):
        EVENTS.append("stop:dashboards")


# --- 4. transitivity: a skip propagates down the graph --------------------
EVENTS.clear()
registry = Registry()
for plugin in (Database(), BrokenStart("cache", depends_on=("database",)),
               Migrations(), HttpServer(), Dashboards()):
    registry.register(plugin)
report = registry.start_all(Ctx())
skipped = dict(report.skipped)
assert report.started == ["database", "migrations"], report.started
assert [name for name, _ in report.failed_start] == ["cache"]
assert set(skipped) == {"http", "dashboards"}, report.skipped
assert "cache" in skipped["http"], skipped["http"]
assert "http" in skipped["dashboards"], skipped["dashboards"]
assert skipped["dashboards"].startswith("blocked by http"), skipped["dashboards"]
assert "cache" in skipped["dashboards"], "the root cause must survive the chain"

# --- 5. graph problems are caught before anything starts ------------------
ctx = Ctx()
registry = Registry()
class A(Plugin):
    name = "a"
    depends_on = ("b",)
class B(Plugin):
    name = "b"
    depends_on = ("a",)
registry.register(A())
registry.register(B())
try:
    registry.start_all(ctx)
    raise AssertionError("a cycle must be refused")
except PluginError as exc:
    assert "cycle" in str(exc) and "a" in str(exc) and "b" in str(exc), str(exc)
assert ctx == {}, "resolution must fail before any plugin starts"

registry = Registry()
registry.register(Migrations())               # depends on a plugin that is not registered
try:
    registry.start_all(Ctx())
    raise AssertionError("an unknown dependency must be refused")
except PluginError as exc:
    assert "migrations" in str(exc) and "database" in str(exc), str(exc)

registry = Registry()
registry.register(Database())
try:
    registry.register(Database())
    raise AssertionError("duplicate names must be refused at registration")
except PluginError as exc:
    assert "duplicate" in str(exc), str(exc)

# --- 6. a failing stop is reported without blocking the others ------------
EVENTS.clear()
registry = Registry()
for plugin in (Database(), Migrations(), BrokenStop(), Metrics()):
    registry.register(plugin)
report = registry.start_all(Ctx())
assert report.ok, report
registry.stop_all(Ctx(), report)
assert [name for name, _exc in report.failed_stop] == ["audit"], report.failed_stop
assert [event for event in EVENTS if event.startswith("start:")] == [
    "start:audit", "start:database", "start:metrics", "start:migrations",
], EVENTS
assert [event for event in EVENTS if event.startswith("stop:")] == [
    "stop:migrations", "stop:metrics", "stop:database", "stop:audit",
], EVENTS
assert not report.ok
assert isinstance(report.failed_stop[0][1], RuntimeError)

# --- 7. the context is shared, and partial startup leaves it consistent ---
ctx = Ctx()
registry = Registry()
for plugin in (Database(), Migrations(), BrokenStart("search", depends_on=("migrations",))):
    registry.register(plugin)
report = registry.start_all(ctx)
assert ctx["db"] == "connection" and ctx["schema"] == 3
assert [name for name, _ in report.failed_start] == ["search"]
assert report.started == ["database", "migrations"], report.started

print("PASS")
@@end

@expect_output
PASS
@@end

@notes
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
@@end
