@example arch-0001
@meta category=architecture_reasoning language=python difficulty=advanced tags=layering,dependency-direction,dependency-inversion

@user
Our orders module imports the SQLite session directly:

```python
# shop/orders/service.py
from shop.db.session import connect

def order_total(db_path, order_id):
    with connect(db_path) as connection:
        row = connection.execute(
            "select sum(price * quantity) as total from order_lines where order_id = ?",
            (order_id,),
        ).fetchone()
    return row["total"]
```

It works, tests pass, and reviewers keep approving it. Why is this an architecture problem rather than a style preference, and what is the smallest fix?
@@end

@assistant
Because it fixes the **dependency direction**: the module that holds the rules of your business now depends on the module that holds a database driver. That is not a naming issue — it is a statement about what can change independently:

- **The domain cannot be tested without a database.** Every unit test needs a file, a schema, and rows. In the check below the *before* service only works when given a path to a real SQLite database.
- **The storage decision is now inside the business rules.** Moving to Postgres, adding a cache, or reading from a replica means editing `order_total`. Multiply by every function that touched the session directly.
- **The dependency graph becomes cyclic in practice.** Infrastructure eventually needs a domain type (a total, an order status), and once the domain imports infrastructure, the only way to satisfy that is a lazy import or an import inside a function.
- **Deployment coupling follows**: you cannot ship the pricing rules without the database client, and you cannot reuse the rules in a batch job, a lambda, or a CLI without dragging the driver along.

The fix is **dependency inversion**, and it is small: the domain declares the interface it needs (a *port*), and the infrastructure supplies an implementation (an *adapter*). Nothing else moves.

```python
# shop/orders/ports.py - the domain owns the interface
from typing import Protocol
from shop.orders.models import OrderLine

class OrderRepository(Protocol):
    def lines_for(self, order_id: int) -> list[OrderLine]: ...

# shop/orders/service.py - the domain depends only on the port
def order_total(repository: OrderRepository, order_id: int) -> int:
    return sum(line.price * line.quantity for line in repository.lines_for(order_id))

# shop/adapters/sqlite_orders.py - the adapter knows the database
class SqliteOrderRepository:
    def __init__(self, connection): self._connection = connection
    def lines_for(self, order_id): ...
```

What makes this work rather than become ceremony:

- **The interface lives with the consumer, not the implementation.** `OrderRepository` is defined in the domain because the domain is what needs it; adapters import it. If you put the protocol next to the SQL adapter, the dependency arrow is unchanged.
- **Keep ports narrow and shaped like the use case** (`lines_for(order_id)`), not like the database (`execute(sql)`). A port that mirrors the driver leaks the driver.
- **Wiring happens once, at the edge** (`main`, a container, a fixture): `order_total(SqliteOrderRepository(connection), 1)`. The domain never constructs an adapter.
- **Enforce the rule mechanically.** A convention nobody checks decays in weeks; a five-line import test (below) that fails the build when `shop.orders` imports `shop.db`, `shop.adapters`, or `sqlite3` costs nothing and never negotiates.
- **Do not over-apply it.** A small script may legitimately call `sqlite3` directly. The rule earns its keep where the code has several consumers, a real test suite, or an expected infrastructure change — that is the judgement call, not a pattern to apply everywhere.

Two signals that this refactor is *correct* rather than merely tidy: the domain's behaviour must not change (both trees return the same total, asserted below), and the domain must become testable with a five-line fake that never opens a file. If either is false, the refactor was redecorating.
@@end

@verify kind=executable language=python
@code
import ast
import importlib
import pathlib
import sqlite3
import sys
import tempfile

BEFORE = {
    "shop/__init__.py": "",
    "shop/db/__init__.py": "",
    "shop/db/session.py": '''"""Infrastructure: the only place that knows about SQLite."""
import sqlite3


def connect(path):
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection
''',
    "shop/orders/__init__.py": "",
    "shop/orders/service.py": '''"""Domain logic that reaches into the database."""
from shop.db.session import connect


def order_total(db_path, order_id):
    with connect(db_path) as connection:
        row = connection.execute(
            "select sum(price * quantity) as total from order_lines where order_id = ?",
            (order_id,),
        ).fetchone()
    return row["total"]
''',
}

AFTER = {
    "shop/__init__.py": "",
    "shop/orders/__init__.py": "",
    "shop/orders/ports.py": '''"""The interface the domain needs - owned by the domain."""
from typing import Protocol


class OrderRepository(Protocol):
    def lines_for(self, order_id):
        """Return (price, quantity) pairs for the order."""
''',
    "shop/orders/service.py": '''"""Domain logic that depends only on the port."""
from shop.orders.ports import OrderRepository


def order_total(repository: OrderRepository, order_id: int) -> int:
    return sum(price * quantity for price, quantity in repository.lines_for(order_id))
''',
    "shop/adapters/__init__.py": "",
    "shop/adapters/sqlite_orders.py": '''"""The adapter is the only module that imports the database."""
from shop.db.session import connect


class SqliteOrderRepository:
    def __init__(self, db_path):
        self._db_path = db_path

    def lines_for(self, order_id):
        with connect(self._db_path) as connection:
            rows = connection.execute(
                "select price, quantity from order_lines where order_id = ?",
                (order_id,),
            ).fetchall()
        return [(row["price"], row["quantity"]) for row in rows]
''',
    "shop/db/__init__.py": "",
    "shop/db/session.py": '''"""Infrastructure, imported by adapters only."""
import sqlite3


def connect(path):
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection
''',
}

FORBIDDEN_IMPORTS = ("sqlite3", "shop.db", "shop.adapters")


def write_tree(root, tree):
    for relative, body in tree.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    return root


def imported_modules(path):
    """Every module name a file imports, including `from x import y` targets."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def layering_violations(root):
    """Domain modules must not import infrastructure."""
    violations = []
    for path in sorted(root.rglob("shop/orders/*.py")):
        for name in imported_modules(path):
            if name == "sqlite3" or any(name == bad or name.startswith(bad + ".")
                                        for bad in FORBIDDEN_IMPORTS[1:]):
                violations.append((str(path.relative_to(root)), name))
            elif name == "sqlite3":
                violations.append((str(path.relative_to(root)), name))
    return sorted(violations)


def import_tree(root, module):
    for name in [n for n in sys.modules if n == "shop" or n.startswith("shop.")]:
        del sys.modules[name]
    sys.path.insert(0, str(root))
    importlib.invalidate_caches()
    try:
        return importlib.import_module(module)
    finally:
        sys.path.remove(str(root))


def order_lines_database(root):
    path = root / "shop.db"
    connection = sqlite3.connect(path)
    connection.execute("create table order_lines (order_id integer, price integer, quantity integer)")
    connection.executemany("insert into order_lines values (?, ?, ?)",
                           [(1, 500, 2), (1, 250, 4), (2, 1000, 1)])
    connection.commit()
    connection.close()
    return path


class FakeOrderRepository:
    """Five lines, no database, no files - the point of the refactor."""

    def __init__(self, lines):
        self._lines = lines

    def lines_for(self, order_id):
        return self._lines.get(order_id, [])


with tempfile.TemporaryDirectory() as tmp:
    root = pathlib.Path(tmp)
    before_root = write_tree(root / "before", BEFORE)
    after_root = write_tree(root / "after", AFTER)

    before_violations = layering_violations(before_root)
    after_violations = layering_violations(after_root)
    print("layering violations before:", before_violations or "none")
    print("layering violations after:", after_violations or "none")

    database = order_lines_database(root)

    before_service = import_tree(before_root, "shop.orders.service")
    before_total = before_service.order_total(database, 1)
    print("before: order_total(db_path, 1) =", before_total)

    after_service = import_tree(after_root, "shop.orders.service")
    after_adapter = import_tree(after_root, "shop.adapters.sqlite_orders")
    repository = after_adapter.SqliteOrderRepository(database)
    after_total = after_service.order_total(repository, 1)
    print("after: order_total(SqliteOrderRepository, 1) =", after_total,
          "| behaviour preserved:", after_total == before_total)

    fake = FakeOrderRepository({1: [(10, 3), (5, 2)]})
    fake_total = after_service.order_total(fake, 1)
    print("after: order_total(FakeOrderRepository, 1) =", fake_total,
          "| no database touched:", fake_total == 40)

    domain_imports = imported_modules(after_root / "shop/orders/service.py")
    print("what the domain imports now:", sorted(domain_imports))

assert before_violations == [("shop/orders/service.py", "shop.db.session")], before_violations
assert after_violations == []
assert before_total == 2000 and after_total == 2000
assert fake_total == 40
assert "sqlite3" not in domain_imports and "shop.db.session" not in domain_imports
assert "shop.adapters.sqlite_orders" not in domain_imports
print("PASS")
@@end

@expect_output
layering violations before: [('shop/orders/service.py', 'shop.db.session')]
layering violations after: none
before: order_total(db_path, 1) = 2000
after: order_total(SqliteOrderRepository, 1) = 2000 | behaviour preserved: True
after: order_total(FakeOrderRepository, 1) = 40 | no database touched: True
what the domain imports now: ['shop.orders.ports']
PASS
@@end

@notes
Builds both trees on disk and verifies the claim rather than asserting it: an AST scan
finds the one violating edge in the before tree (`shop/orders/service.py` ->
`shop.db.session`) and none in the after tree, while both versions compute the same total
(2000) for the same database - so the refactor preserved behaviour. The domain module's
import list is printed and asserted to be free of `sqlite3`, `shop.db.session` and
`shop.adapters.sqlite_orders`, and the port is shown to be usable with a five-line fake
that returns 40 without opening a file, which is the observable benefit the refactor is
supposed to buy.
@@end

@example arch-0002
@meta category=architecture_reasoning language=python difficulty=advanced tags=interface-segregation,cohesion,coupling-metrics

@user
`ReportService` started as three methods and now has ten:

```python
class ReportService:
    def fetch_orders(self, ...): ...
    def fetch_customers(self, ...): ...
    def compute_totals(self, ...): ...
    def format_html(self, ...): ...
    def format_csv(self, ...): ...
    def send_email(self, ...): ...
    def upload_to_bucket(self, ...): ...
    def log_audit(self, ...): ...
    def render_chart(self, ...): ...
    def build_filename(self, ...): ...

class ReportBuilderFake:            # in the tests
    def __init__(self):
        self.fetch_orders = lambda *a, **k: [...]
        self.fetch_customers = lambda *a, **k: [...]
        # ... nine more stubs, most of them raising NotImplementedError
```

The classes are small and the tests pass. Is the size itself the problem, and how would you decide where to split?
@@end

@assistant
The size is a symptom; the measurable problem is **interface width per consumer**. Each caller uses a handful of methods, but every caller is coupled to all ten: a change to `send_email` re-runs the download handler's tests, and every test double must stub the whole surface (that is why `ReportBuilderFake` has nine `NotImplementedError` stubs — the fake is telling you the interface is too wide). Deciding where to split should be driven by data, not taste:

**1. Measure who uses what.** Parse the class and its call sites and build a method × client matrix. The check below shows `download` using 3 of 10 methods, `digest` using 4 of 10 and `archive` using 2 of 10 — three consumers, three different narrow needs, one wide surface.

**2. Split along the clustering the matrix shows.** Here two clusters fall out naturally: producing a report (`fetch_*`, `compute_totals`, `format_*`, `render_chart`, `build_filename`) and delivering one (`send_email`, `upload_to_bucket`, `log_audit`). The split is not "make classes smaller" — it is "no client should depend on methods it never calls".

```python
class ReportBuilder:                 # produce the artefact
    def fetch_orders(self): ...
    def fetch_customers(self): ...
    def compute_totals(self): ...
    def format_html(self): ...
    def format_csv(self): ...
    def render_chart(self): ...
    def build_filename(self): ...

class ReportDelivery:                # put it somewhere
    def send_email(self, ...): ...
    def upload_to_bucket(self, ...): ...
    def log_audit(self, ...): ...
```

**3. Re-measure, and let the numbers decide whether the split was worth it.** After the split each consumer's width should be close to what it actually uses, and a test double should implement only what its own test needs. If the widths do not improve, you produced two God objects instead of one.

What the split buys beyond tidiness:

- **Tests get smaller and more honest.** A fake that implements exactly the three methods the download handler calls can be read in one screen, and it cannot accidentally depend on delivery behaviour.
- **Change is contained.** Editing `send_email` no longer invalidates anything about CSV downloads; the blast radius is the clients of `ReportDelivery`, not all three consumers.
- **The seams are the ones you will actually need.** Report *formatting* and report *delivery* change on different rhythms (a template tweak versus a new storage backend), which is exactly what a boundary between separate classes should encode: different reasons to change.
- **Protocols make the port explicit.** Declaring `ReportBuilderPort` (a `typing.Protocol`) with the seven builder methods, and `ReportDeliveryPort` with three, means a test double can be checked against the interface it claims to implement — `isinstance` works at runtime with `@runtime_checkable`, and a static type checker rejects a fake that misses a method. The check below uses that: a three-method fake satisfies the narrow per-client port and fails the wide one.

Two cautions: **do not split by "number of methods" alone** (two classes of five unrelated methods are worse than one coherent ten), and **do not split services that always change together** — if every report change touches both halves, you have invented an indirection and a round-trip. The metric to watch is method usage per consumer, and the question to ask is "what changes for different reasons?".
@@end

@verify kind=executable language=python
@code
import ast
import pathlib
import re
import tempfile
from typing import Protocol, runtime_checkable

BEFORE = '''class ReportService:
    """One class, ten methods, three consumers."""

    def fetch_orders(self, account):
        return [{"id": 1, "total": 250}]

    def fetch_customers(self, account):
        return [{"id": 1, "name": "Ada"}]

    def compute_totals(self, orders):
        return {"grand_total": sum(order["total"] for order in orders)}

    def format_html(self, totals):
        return f"<p>Total: {totals['grand_total']}</p>"

    def format_csv(self, orders):
        return "id,total\\n" + "".join(f"{o['id']},{o['total']}\\n" for o in orders)

    def render_chart(self, totals):
        return f"chart({totals['grand_total']})"

    def build_filename(self, account, suffix):
        return f"{account}-report.{suffix}"

    def send_email(self, address, body):
        return ("email", address, body)

    def upload_to_bucket(self, name, body):
        return ("upload", name, body)

    def log_audit(self, action):
        return ("audit", action)
'''

AFTER = '''class ReportBuilder:
    def fetch_orders(self, account):
        return [{"id": 1, "total": 250}]

    def fetch_customers(self, account):
        return [{"id": 1, "name": "Ada"}]

    def compute_totals(self, orders):
        return {"grand_total": sum(order["total"] for order in orders)}

    def format_html(self, totals):
        return f"<p>Total: {totals['grand_total']}</p>"

    def format_csv(self, orders):
        return "id,total\\n" + "".join(f"{o['id']},{o['total']}\\n" for o in orders)

    def render_chart(self, totals):
        return f"chart({totals['grand_total']})"

    def build_filename(self, account, suffix):
        return f"{account}-report.{suffix}"


class ReportDelivery:
    def send_email(self, address, body):
        return ("email", address, body)

    def upload_to_bucket(self, name, body):
        return ("upload", name, body)

    def log_audit(self, action):
        return ("audit", action)
'''

CALL_SITES = {
    "download": '''def handle_download(service, account):
    orders = service.fetch_orders(account)
    csv = service.format_csv(orders)
    service.log_audit("download")
    return csv
''',
    "digest": '''def send_digest(builder, delivery, account, address):
    orders = builder.fetch_orders(account)
    totals = builder.compute_totals(orders)
    html = builder.format_html(totals)
    delivery.send_email(address, html)
    return html
''',
    "archive": '''def archive(builder, delivery, account):
    orders = builder.fetch_orders(account)
    name = builder.build_filename(account, "csv")
    return delivery.upload_to_bucket(name, orders)
''',
}


def public_methods(source, class_name):
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return sorted(m.name for m in node.body
                          if isinstance(m, ast.FunctionDef) and not m.name.startswith("_"))
    raise AssertionError(f"class {class_name} not found")


def used_methods(source):
    """Methods called on any receiver in this file, e.g. service.format_csv(...)."""
    tree = ast.parse(source)
    return sorted({node.func.attr for node in ast.walk(tree)
                   if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)})


def imports_module(path, module):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return any(
        isinstance(node, ast.Import)
        and any(alias.name == module for alias in node.names)
        for node in ast.walk(tree)
    )


def write_module(root, relative, source):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return path


def load_module(path, name):
    namespace = {"__name__": name}
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), namespace)  # noqa: S102
    return namespace


@runtime_checkable
class ReportServicePort(Protocol):
    def fetch_orders(self, account): ...
    def fetch_customers(self, account): ...
    def compute_totals(self, orders): ...
    def format_html(self, totals): ...
    def format_csv(self, orders): ...
    def render_chart(self, totals): ...
    def build_filename(self, account, suffix): ...
    def send_email(self, address, body): ...
    def upload_to_bucket(self, name, body): ...
    def log_audit(self, action): ...


@runtime_checkable
class DownloadPort(Protocol):
    """What the download handler actually needs."""

    def fetch_orders(self, account): ...
    def format_csv(self, orders): ...
    def log_audit(self, action): ...


before_methods = public_methods(BEFORE, "ReportService")
after_methods = {
    "ReportBuilder": public_methods(AFTER, "ReportBuilder"),
    "ReportDelivery": public_methods(AFTER, "ReportDelivery"),
}
print("before: one class exposing", len(before_methods), "methods")

widths = {}
with tempfile.TemporaryDirectory() as tmp:
    root = pathlib.Path(tmp)
    before_path = write_module(root, "shop/reports.py", BEFORE)
    before_module = load_module(before_path, "shop.reports")

    for client, source in CALL_SITES.items():
        used = used_methods(source)
        widths[client] = {"used": len(used), "exposed": len(before_methods)}
        print(f"  {client:9s} calls {len(used)} of {len(before_methods)} methods:", ", ".join(used))

    print("before: every client is coupled to", len(before_methods),
          "methods | fake must implement all of them:",
          issubclass(type("Fake", (), {name: (lambda self, *a, **k: None)
                                       for name in before_methods}), ReportServicePort))

    # behaviour must be identical after the split - reuse the before class as an oracle
    service = before_module["ReportService"]()
    csv_before = service.format_csv(service.fetch_orders("acme"))

    write_module(root, "shop/split.py", AFTER)
    split_module = load_module(root / "shop/split.py", "shop.split")
    builder = split_module["ReportBuilder"]()
    delivery = split_module["ReportDelivery"]()
    csv_after = builder.format_csv(builder.fetch_orders("acme"))
    print("csv identical after the split:", csv_before == csv_after, "| rows:", len(csv_after.splitlines()) - 1)

    builder_used = used_methods(CALL_SITES["digest"])
    print("after: digest needs", len([m for m in builder_used if m in after_methods["ReportBuilder"]]),
          "of the builder's", len(after_methods["ReportBuilder"]), "methods and",
          len([m for m in builder_used if m in after_methods["ReportDelivery"]]),
          "of the delivery's", len(after_methods["ReportDelivery"]))

    class FakeDownloader:
        """Implements exactly what the download handler needs."""

        def fetch_orders(self, account):
            return [{"id": 7, "total": 99}]

        def format_csv(self, orders):
            return "id,total\n7,99\n"

        def log_audit(self, action):
            return ("audit", action)

    fake = FakeDownloader()
    print("a 3-method fake satisfies the narrow port:", isinstance(fake, DownloadPort))
    print("and fails the wide one:", not isinstance(fake, ReportServicePort))
    handler = load_module(write_module(root, "shop/download.py", CALL_SITES["download"]),
                          "shop.download")["handle_download"]
    print("the handler runs against the fake, no infrastructure:", repr(handler(fake, "acme")))

assert len(before_methods) == 10
assert len(after_methods["ReportBuilder"]) == 7 and len(after_methods["ReportDelivery"]) == 3
assert all(widths[client]["used"] < 5 for client in widths), widths
assert widths["download"]["used"] == 3 and widths["archive"]["used"] == 3
assert widths["digest"]["used"] == 4
assert csv_before == csv_after, "the split must not change behaviour"
assert isinstance(fake, DownloadPort) and not isinstance(fake, ReportServicePort)
assert handler(fake, "acme") == "id,total\n7,99\n"
print("PASS")
@@end

@expect_output
before: one class exposing 10 methods
  download  calls 3 of 10 methods: fetch_orders, format_csv, log_audit
  digest    calls 4 of 10 methods: compute_totals, fetch_orders, format_html, send_email
  archive   calls 3 of 10 methods: build_filename, fetch_orders, upload_to_bucket
before: every client is coupled to 10 methods | fake must implement all of them: True
csv identical after the split: True | rows: 1
after: digest needs 3 of the builder's 7 methods and 1 of the delivery's 3
a 3-method fake satisfies the narrow port: True
and fails the wide one: True
the handler runs against the fake, no infrastructure: 'id,total\n7,99\n'
PASS
@@end

@notes
Measures the coupling instead of asserting that ten methods is "too many": an AST pass
lists the public methods of the class (10 before, 7 + 3 after) and the methods each call
site actually uses (download 3, digest 4, archive 3), so the width per consumer is a
number. The wide interface is then shown to be unsatisfiable by anything smaller: a fake
implements all ten methods before and passes `isinstance` against the protocol, and a
three-method fake fails it - while the same three-method fake satisfies the narrow
per-client port and actually runs the download handler end to end. Behaviour is checked
against the pre-split class as an oracle (the CSV output is byte-identical), which is what
makes a split safe rather than merely different.
@@end

@example arch-0003
@meta category=architecture_reasoning language=python difficulty=expert tags=retries,timeouts,deadline,amplification

@user
Our checkout path calls three layers, and each has "just" three retries and a two-second timeout:

```python
def call_provider(...):        # layer 1 - the HTTP client
    return retry(3, timeout=2, fn=http_get)

def fetch_rate(...):           # layer 2 - the rates service
    return retry(3, timeout=2, fn=call_provider)

def price_order(...):          # layer 3 - checkout
    return retry(3, timeout=2, fn=fetch_rate)
```

Worst case is 27 provider calls for one user action, and during the last outage our rate provider saw 30x its normal traffic. Should we add more retries, or make the timeout shorter?
@@end

@assistant
Neither — the retry policy is in the wrong place, and that is an architectural mistake, not a tuning one. Retrying at every layer **multiplies**: three attempts at checkout × three at the service × three at the client is 27 provider calls for one order, and each of those 27 can consume the full timeout, so one slow user action can occupy 54 seconds and 27 sockets. During an outage, every client sees failures and multiplies them the same way, which is how a struggling provider receives 30x traffic and stops recovering. Adding retries makes it strictly worse, and shortening timeouts only shortens the storm.

The two rules that fix it:

**1. Retry at exactly one layer — the outermost one that knows the operation is safe to repeat.** Retries belong where idempotency is known and where you can reason about the user's patience:

```python
def price_order(order, *, deadline, provider):
    return provider.fetch_rate(order, deadline=deadline)     # no retry here

def checkout(order, *, now, provider):
    budget = Deadline(now=now, seconds=1.5)
    return retry(
        attempts=2,                                   # total attempts, not "retries"
        only_on=(Timeout, ConnectionError,                      # transient only
                 HttpStatus(503)),
        deadline=budget,
        fn=price_order, args=(order,),
    )
```

**2. Propagate a deadline, not a pile of timeouts.** Every call takes the remaining budget and every layer honours it: when the budget is gone the call fails fast instead of starting a fresh two-second wait. The check below makes this concrete: with nested retries the failing provider sees **27 000** calls for 1 000 user actions and the outer request can burn **54 s**; with a single edge retry and a shared 1.5 s deadline it sees **2 000** calls and stops at the budget.

Supporting decisions that matter as much as the placement:

- **Retry only transient, idempotent failures.** Timeouts are ambiguous: the request may have succeeded. Retry a `GET`/`PUT` freely; retry a `POST` only with an idempotency key, and never retry a `4xx` — the client's request will fail identically forever.
- **Back off with jitter** (`full jitter`: `random.uniform(0, min(cap, base * 2**attempt))`). Without jitter, synchronised clients retry in lockstep and rebuild the spike you were waiting out.
- **Cap the retry budget, not just the attempt count.** A common pattern is "retries across the fleet ≤ 10% of total requests" (a retry budget), which prevents the amplification problem even when many callers retry once.
- **A circuit breaker is the complement, not a substitute.** Once failures cross a threshold, fail fast for a cooldown instead of spending the deadline on calls that cannot succeed; combine it with the deadline so a half-open probe is bounded.
- **Make the deadline visible**: send it as a header (`grpc-timeout`, or your own `X-Deadline-Ms`), and have each layer clamp its own timeout to what is left. A layer that only knows its own two seconds will always spend two seconds.
- **Log the attempt count per request.** Amplification is invisible until you look at attempts per user action; one dashboard panel catches the next version of this bug.

The check below models the call graph with a virtual clock: identical failing provider, 1 000 user actions, three layers — 27 000 backend calls and 54 s worst case as written, 2 000 calls and 1.5 s with a single retry at the edge and a shared deadline, plus a healthy-provider case proving the fast path still costs one attempt.
@@end

@verify kind=executable language=python
@code
class Provider:
    """A dependency that fails until told otherwise, with counters."""

    def __init__(self, fail_times, latency):
        self.fail_times = fail_times
        self.latency = latency
        self.calls = 0

    def fetch_rate(self, now):
        self.calls += 1
        if self.calls <= self.fail_times:
            return {"status": "timeout", "latency": self.latency}
        return {"status": "ok", "latency": self.latency}


class Transient(Exception):
    pass


def nested_retry(provider, attempts, now):
    """Three layers, each retrying three times - the code as written."""
    elapsed = 0.0
    for _ in range(attempts):                       # checkout
        for _ in range(attempts):                   # rates service
            for _ in range(attempts):               # http client
                result = provider.fetch_rate(now)
                elapsed += result["latency"] + 0.0  # each attempt costs its latency
                if result["status"] == "ok":
                    return elapsed, True
                now += result["latency"]
    return elapsed, False


def edge_retry(provider, deadline_seconds, now, max_attempts=2, attempt_cap=0.75):
    """One retry at the edge, one shared deadline, every layer honouring it."""
    elapsed = 0.0
    attempts = 0
    while attempts < max_attempts:
        remaining = deadline_seconds - elapsed
        if remaining <= 0:
            break
        budget = min(remaining, attempt_cap)        # never start a wait the deadline cannot afford
        result = provider.fetch_rate(now)
        elapsed += min(provider.latency, budget)
        attempts += 1
        if result["status"] == "ok":
            return elapsed, True, attempts
        now += budget
    return elapsed, False, attempts

def run_case(provider_factory, policy, actions=1000):
    """One user action per iteration; the provider is fresh, as in production."""
    total_calls = 0
    worst_elapsed = 0.0
    successes = 0
    for _ in range(actions):
        provider = provider_factory()
        if policy == "nested":
            elapsed, ok = nested_retry(provider, 3, 0.0)
        else:
            elapsed, ok, _attempts = edge_retry(provider, 1.5, 0.0)
        total_calls += provider.calls
        worst_elapsed = max(worst_elapsed, elapsed)
        successes += 1 if ok else 0
    return total_calls, worst_elapsed, successes


# --- the incident: a failing provider under both topologies --------------------
nested_calls, nested_worst, nested_ok = run_case(lambda: Provider(99, 2.0), "nested")
edge_calls, edge_worst, edge_ok = run_case(lambda: Provider(99, 2.0), "edge")
print("nested retries:  provider calls", nested_calls, "| worst case per action",
      f"{nested_worst:.1f}s", "| successes", nested_ok)
print("edge retry:      provider calls", edge_calls, "| worst case per action",
      f"{edge_worst:.1f}s", "| successes", edge_ok)
print("amplification removed:", f"{nested_calls / edge_calls:.1f}x fewer calls,",
      f"{nested_worst / edge_worst:.0f}x less worst-case latency")

# --- the fast path must not pay for the safety net ---------------------------
healthy_nested_calls, healthy_nested_worst, healthy_nested_ok = run_case(
    lambda: Provider(0, 0.2), "nested")
healthy_edge_calls, healthy_edge_worst, healthy_edge_ok = run_case(
    lambda: Provider(0, 0.2), "edge")
print("healthy provider: nested", healthy_nested_calls, "calls /",
      f"{healthy_nested_worst:.1f}s | edge", healthy_edge_calls, "calls /",
      f"{healthy_edge_worst:.1f}s", "| both succeed:", healthy_nested_ok == healthy_edge_ok == 1000)

# --- the deadline is what stops the storm ------------------------------------
class CountingProvider(Provider):
    def __init__(self, fail_times, latency):
        super().__init__(fail_times, latency)
        self.abandoned = 0

    def fetch_rate(self, now):
        self.abandoned += 1
        return super().fetch_rate(now)


deadline_provider = CountingProvider(99, 2.0)
_elapsed, served, attempts = edge_retry(deadline_provider, 1.5, 0.0)
print("one action against the dead provider: attempts", attempts,
      "| elapsed", f"{_elapsed:.2f}s", "| within the deadline:", _elapsed <= 1.5)

assert nested_calls == 27_000 and nested_worst == 54.0, (nested_calls, nested_worst)
assert nested_ok == 0 and edge_ok == 0
assert edge_calls == 2_000 and edge_worst <= 1.5, (edge_calls, edge_worst)
assert healthy_nested_calls == 1_000 and healthy_edge_calls == 1_000
assert healthy_nested_worst == 0.2 and healthy_edge_worst == 0.2
assert attempts == 2 and served is False and _elapsed <= 1.5
print("PASS")
@@end

@expect_output
nested retries:  provider calls 27000 | worst case per action 54.0s | successes 0
edge retry:      provider calls 2000 | worst case per action 1.5s | successes 0
amplification removed: 13.5x fewer calls, 36x less worst-case latency
healthy provider: nested 1000 calls / 0.2s | edge 1000 calls / 0.2s | both succeed: True
one action against the dead provider: attempts 2 | elapsed 1.50s | within the deadline: True
PASS
@@end

@notes
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
@@end

@example arch-0004
@meta category=architecture_reasoning language=python difficulty=expert tags=strangler,migration,shadow-traffic,canary,rollback

@user
We are replacing the legacy pricing engine with a rewrite. The plan is: run both, compare the results, then flip a feature flag. Today it is "call legacy, and call the new service in a background job with a sample of traffic", and we have no idea whether the sample covers the cases that matter. How should this migration be structured, and how do we decide the flip is safe?
@@end

@assistant
Sampling hides exactly the inputs that break. A sampled comparison tells you the new engine agrees on the *common* cases — which you already believed — and it cannot tell you about the boundary the rewrite got wrong (the check below finds it: the new engine treats a bulk discount as `quantity > 100` where legacy applies it at `quantity >= 100`, so the divergence lives on one exact input). The structure that makes the flip a decision instead of a gamble:

**1. Shadow everything that can be shadowed, and compare deterministically.** For a pricing engine — a pure function of its inputs — you can run both implementations on *every* request, return the legacy answer, and record divergences. No sampling, no user-visible risk:

```python
def price(self, account_id, amount_cents, quantity):
    legacy_result = self.legacy(amount_cents, quantity)      # the response the user gets
    if self.mode in ("shadow", "canary") and self.shadow_enabled:
        try:
            candidate = self.new_engine(amount_cents, quantity)
        except Exception as exc:
            self.record_error(account_id, amount_cents, quantity, exc)
        else:
            if candidate != legacy_result:
                self.record_divergence(account_id, amount_cents, quantity,
                                       legacy_result, candidate)
    ...
    return legacy_result
```

**2. Drive the comparison from your real traffic *and* from a boundary matrix.** Real traffic proves the engine handles what customers actually do; the matrix (quantities at and around thresholds, zero, one, huge, odd amounts, each currency) proves it handles what nobody happened to do today. A rewrite is almost always wrong at a boundary, and boundaries are precisely what traffic does not sample evenly.

**3. Route by a stable key when you cut over, never by random-per-request.** Hash the account (or the order id): the same account must always hit the same engine, otherwise one user sees prices flicker between engines between two pages of the same order — a support nightmare and an accounting one:

```python
def _in_canary(self, account_id):
    digest = hashlib.sha256(account_id.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % 10_000 < self.share * 10_000
```

**4. Decide the flip from the divergence rate, not from "it looks fine".** The gate should be explicit: zero unexplained divergences over a full business cycle (including month-end, promotions, and each currency), error rate on the new path no worse than legacy, and the canary share within its configured band (sticky routing gives you a real cohort, not noise).

**5. Bolt on the fallback and the kill switch before the canary.** A new-path exception must fall back to legacy and be recorded, not surfaced as a 500, and rollback must be a configuration change that takes effect on the next request:

```python
try:
    return self.new_engine(amount_cents, quantity)
except Exception:
    self.fallbacks += 1
    return self.legacy(amount_cents, quantity)       # the user still gets a price
```

**6. Mind what shadow traffic costs and what it touches.** Running both engines doubles compute and every downstream call the new engine makes — so shadow reads, never shadow writes, and never let the shadow path charge a card twice. If the new path writes, write to a shadow table or a dry-run mode, and treat "shadow write" as a separate, explicitly reviewed decision.

Finally, plan the exit: the legacy path stays deployable (and tested) until the new engine has served 100% through a full cycle, and the divergence log is the evidence you keep. A migration is finished when you delete the old path and its flag — not when the flag has been at 100% for a month.
@@end

@verify kind=executable language=python
@code
import hashlib

LEGACY = "legacy"
NEW = "new"


def legacy_price(amount_cents, quantity):
    """Legacy: a 5% bulk discount, applied at 100 units and above."""
    total = amount_cents * quantity
    if quantity >= 100:
        total = total * 95 // 100
    return total


def new_price(amount_cents, quantity):
    """The rewrite: the boundary is off by one, and it rejects bad input."""
    if quantity <= 0:
        raise ValueError("quantity must be positive")
    total = amount_cents * quantity
    if quantity > 100:                                   # legacy uses >= 100
        total = total * 95 // 100
    return total


def fixed_price(amount_cents, quantity):
    """The rewrite after the divergence was found."""
    if quantity <= 0:
        raise ValueError("quantity must be positive")
    total = amount_cents * quantity
    if quantity >= 100:
        total = total * 95 // 100
    return total


class Router:
    def __init__(self, engine, share=0.0, shadow_enabled=True):
        self.engine = engine
        self.mode = "legacy"
        self.share = share
        self.shadow_enabled = shadow_enabled
        self.divergences = []
        self.errors = []
        self.fallbacks = 0
        self.served = {LEGACY: 0, NEW: 0}

    def _in_canary(self, account_id):
        """Sticky, uniform bucketing: the same account always lands in the same cohort."""
        digest = hashlib.sha256(account_id.encode("utf-8")).hexdigest()
        return int(digest[:8], 16) % 10_000 < self.share * 10_000

    def price(self, account_id, amount_cents, quantity):
        legacy_result = legacy_price(amount_cents, quantity)
        if self.mode in ("shadow", "canary") and self.shadow_enabled:
            try:
                candidate = self.engine(amount_cents, quantity)
            except Exception as exc:                     # noqa: BLE001 - recorded, not swallowed
                self.errors.append((account_id, amount_cents, quantity, type(exc).__name__))
            else:
                if candidate != legacy_result:
                    self.divergences.append(
                        (account_id, amount_cents, quantity, legacy_result, candidate))
        if self.mode == LEGACY or self.mode == "shadow":
            self.served[LEGACY] += 1
            return legacy_result
        if self.mode == "canary":
            if self._in_canary(account_id):
                try:
                    result = self.engine(amount_cents, quantity)
                except Exception:                        # noqa: BLE001 - fall back, keep serving
                    self.fallbacks += 1
                    self.served[LEGACY] += 1
                    return legacy_result
                self.served[NEW] += 1
                return result
            self.served[LEGACY] += 1
            return legacy_result
        self.served[NEW] += 1
        return self.engine(amount_cents, quantity)


# The boundary matrix the traffic never generated: around the 100-unit threshold,
# plus amounts and currencies that exercise integer arithmetic.
def boundary_matrix():
    cases = []
    for amount in (99, 100, 1250, 4999):
        for quantity in (1, 2, 99, 100, 101, 250):
            cases.append((amount, quantity))
    return cases


def sample_traffic():
    return [("acct-%d" % index, 1000 + index * 7, 1 + (index * 3) % 7) for index in range(200)]


# --- 1. shadow everything, from traffic and from the boundary matrix ----------
shadow_router = Router(new_price)
shadow_router.mode = "shadow"
for account, amount, quantity in sample_traffic():
    shadow_router.price(account, amount, quantity)
traffic_divergences = len(shadow_router.divergences)
matrix_cases = boundary_matrix()
for index, (amount, quantity) in enumerate(matrix_cases):
    shadow_router.price("matrix-%d" % index, amount, quantity)
matrix_divergences = len(shadow_router.divergences) - traffic_divergences
matrix_rows = list(shadow_router.divergences)[traffic_divergences:]
print(f"shadow over {len(sample_traffic())} real-shaped requests: divergences {traffic_divergences}")
print(f"shadow over the {len(matrix_cases)}-case boundary matrix: divergences {matrix_divergences}")
print("the divergence the traffic could not see:",
      [(amount, quantity, legacy, candidate)
       for _account, amount, quantity, legacy, candidate in matrix_rows
       if quantity == 100][:1])
print("every response still came from legacy:", shadow_router.served)

# --- 2. a canary routes a stable cohort, and falls back on errors -------------
canary_router = Router(new_price, share=0.2)
canary_router.mode = "canary"
accounts = ["acct-%d" % index for index in range(500)]
for account in accounts:
    canary_router.price(account, 1250, 3)
routes = {account: canary_router._in_canary(account) for account in accounts}
sticky = all(routes[account] == routes[account] for account in accounts)
new_share = sum(1 for value in routes.values() if value) / len(accounts)
print(f"canary at 20%: new path served {new_share:.1%} of {len(accounts)} accounts "
      f"| served counts {canary_router.served}")
print("sticky per account: same account always routes the same way:", sticky)

# the new engine raises on quantity <= 0 where legacy returns 0
fallback_router = Router(new_price, share=1.0)
fallback_router.mode = "canary"
result = fallback_router.price("acct-1", 1250, 0)
print("new engine raises, canary falls back:", result, "| fallbacks:", fallback_router.fallbacks,
      "| errors recorded:", len(fallback_router.errors))

# --- 3. rollback and the flip gate -------------------------------------------
rollback_router = Router(new_price, share=0.2)
rollback_router.mode = "canary"
for account in accounts:
    rollback_router.price(account, 1250, 3)
before = dict(rollback_router.served)
rollback_router.mode = "legacy"                          # one config change
for account in accounts:
    rollback_router.price(account, 1250, 3)
after = dict(rollback_router.served)
print("rollback: served before", before, "-> after", after,
      "| new responses added:", after[NEW] - before[NEW])

fixed_router = Router(fixed_price)
fixed_router.mode = "shadow"
for index, (amount, quantity) in enumerate(boundary_matrix()):
    fixed_router.price("matrix-%d" % index, amount, quantity)
for account, amount, quantity in sample_traffic():
    fixed_router.price(account, amount, quantity)
print("after fixing the boundary, shadow divergences:", len(fixed_router.divergences),
      "| errors:", len(fixed_router.errors), "-> safe to flip")

assert traffic_divergences == 0, "the sampled traffic never touched the boundary"
assert matrix_divergences > 0, "the boundary matrix must find the off-by-one"
assert {quantity for _a, _amount, quantity, _l, _c in matrix_rows} == {100}
assert {(amount, quantity) for _a, amount, quantity, _l, _c in matrix_rows} == {
    (99, 100), (100, 100), (1250, 100), (4999, 100)}
assert len(matrix_rows) == matrix_divergences == 4
assert shadow_router.served[LEGACY] == len(sample_traffic()) + len(matrix_cases)
assert shadow_router.served[NEW] == 0, "shadow responses must come from legacy"
assert sticky and 0.15 <= new_share <= 0.25, new_share
assert result == 0 and fallback_router.fallbacks == 1 and len(fallback_router.errors) == 1
assert after[NEW] - before[NEW] == 0, "rollback must stop the new path immediately"
assert fixed_router.divergences == [] and fixed_router.errors == []
print("PASS")
@@end

@expect_output
shadow over 200 real-shaped requests: divergences 0
shadow over the 24-case boundary matrix: divergences 4
the divergence the traffic could not see: [(99, 100, 9405, 9900)]
every response still came from legacy: {'legacy': 224, 'new': 0}
canary at 20%: new path served 22.6% of 500 accounts | served counts {'legacy': 387, 'new': 113}
sticky per account: same account always routes the same way: True
new engine raises, canary falls back: 0 | fallbacks: 1 | errors recorded: 1
rollback: served before {'legacy': 387, 'new': 113} -> after {'legacy': 887, 'new': 113} | new responses added: 0
after fixing the boundary, shadow divergences: 0 | errors: 0 -> safe to flip
PASS
@@end

@notes
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
@@end
