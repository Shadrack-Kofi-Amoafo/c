@example dep-0001
@meta category=dependency_reasoning language=python difficulty=advanced tags=circular-imports,entry-points,partial-init,tracing

@user
This package works when the worker imports it, and crashes when the CLI imports it — same code, same environment, different first import:

```
pkg/models.py   from pkg.store import Store
                class User: ...
                def load(store: Store): ...

pkg/store.py    import pkg.models as models
                class Store:
                    def default_user(self): return models.User("anon")
```

`ImportError: cannot import name 'Store' from partially initialized module 'pkg.store' (most likely due to a circular import)` happens with `python -c "import pkg.store"`, while `python -c "import pkg.models"` succeeds. Why does the *entry module* decide this, and what is the correct fix rather than moving the import inside the function?
@@end

@assistant
Both modules are in a cycle; you only see it from one side because of *when* each name becomes available during import.

Python imports a module by creating the module object, putting it in `sys.modules`, then executing its body top to bottom. A cycle is survivable exactly when the second module only needs something that already exists at that moment:

- `import pkg.models` first: `models` starts executing → `from pkg.store import Store` runs `store` → `store` executes `import pkg.models as models`. That binds the **module object**, which already exists (partially initialised is enough), and `store` never touches `models.User` at import time — only inside `default_user`. So `store` finishes, `Store` exists, and `models` gets its name. Order works.
- `import pkg.store` first: `store` starts executing → `import pkg.models as models` runs `models` → `models` executes `from pkg.store import Store`, but `store`'s body has not reached `class Store` yet, so the attribute is missing → `ImportError`.

So the rule is: **a cycle is only "safe" because of which names are looked up before the cycle closes — and that depends on which module the process imports first.** That is why it survives test suites (which import the entry point) and breaks when a different entry point, a plugin loader, or `python -m pkg.store` starts elsewhere. `from x import name` needs the attribute immediately; `import x` plus attribute access at call time needs nothing.

The durable fix is to break the cycle, not to hide it: make the dependency point one way, with the storage layer depending on the domain.

```python
# pkg/models.py -- imports nothing from the storage layer
class User:
    def __init__(self, name): self.name = name

def load(repository, name):                 # any object with .get() will do
    return repository.get(name)


# pkg/store.py -- depends on the domain, which is the only order that holds
import pkg.models as models

class Store:
    def default_user(self): return models.User("anon")

    def get(self, name): return self.default_user()


# pkg/__init__.py -- optional convenience wiring, still one direction
from pkg.models import User
from pkg.store import Store
```

If you cannot break the cycle yet, the least-bad interim is a *function-local* import (`def load(store): from pkg.store import Store`) — it defers the lookup past module execution, but it does not remove the cycle, so the modules still cannot be imported, tested or deployed independently. Detect that case in CI with an import-graph check that walks into function bodies; a cycle that only the interpreter tolerates is still a cycle.
@@end

@verify kind=executable language=python
@code
import re
import subprocess
import sys
import tempfile
from pathlib import Path

CYCLIC = {
    "pkg/__init__.py": "",
    "pkg/models.py": (
        "from pkg.store import Store\n\n\n"
        "class User:\n"
        "    def __init__(self, name):\n"
        "        self.name = name\n\n\n"
        "def load(store: Store):\n"
        "    return store.default_user()\n"
    ),
    "pkg/store.py": (
        "import pkg.models as models\n\n\n"
        "class Store:\n"
        "    def default_user(self):\n"
        '        return models.User("anon")\n'
    ),
}

ACYCLIC = {
    "pkg/__init__.py": "",
    "pkg/models.py": (
        "class User:\n"
        "    def __init__(self, name):\n"
        "        self.name = name\n\n\n"
        "def load(repository, name):\n"
        "    return repository.get(name)\n"
    ),
    "pkg/store.py": (
        "import pkg.models as models\n\n\n"
        "class Store:\n"
        "    def default_user(self):\n"
        '        return models.User("anon")\n\n\n'
        "    def get(self, name):\n"
        "        return self.default_user()\n"
    ),
}


def write(root, files):
    for name, source in files.items():
        path = Path(root) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source)


def run(root, statement):
    proc = subprocess.run(
        [sys.executable, "-c", statement], cwd=root, capture_output=True, text=True
    )
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def import_order(root):
    """The dependency order that actually matters: names needed at import time."""
    edges = {}
    for path in sorted(Path(root).rglob("*.py")):
        name = ".".join(path.relative_to(root).with_suffix("").parts)
        edges[name] = re.findall(r"^(?:from|import)\s+([\w.]+)", path.read_text(), re.M)
    return edges


with tempfile.TemporaryDirectory() as tmp:
    cyclic = Path(tmp) / "cyclic"
    acyclic = Path(tmp) / "acyclic"
    write(cyclic, CYCLIC)
    write(acyclic, ACYCLIC)

    # 1. the same package, two entry points, two outcomes
    rc_models, out_models, err_models = run(cyclic, "import pkg.models; print('ok models first')")
    rc_store, out_store, err_store = run(cyclic, "import pkg.store; print('ok store first')")
    # The message embeds an absolute path; normalise it so the evidence is stable.
    print("import pkg.models ->", rc_models, out_models or err_models.splitlines()[-1])
    print("import pkg.store  ->", rc_store,
          (err_store.splitlines()[-1] if err_store else out_store).replace(str(cyclic), "<pkg>"))

    # 2. the failure is a *partial* module: the object exists, the attribute does not
    probe = "import sys; import pkg.store"
    rc_probe, _out, err_probe = run(
        cyclic,
        "try:\n"
        "    import pkg.store\n"
        "except ImportError as exc:\n"
        "    import sys\n"
        "    print('pkg.store in sys.modules:', 'pkg.store' in sys.modules)\n"
        "    print('error names the missing attribute:', 'Store' in str(exc))\n",
    )
    print("partial-init evidence captured:", rc_probe == 0)

    # 3. the import graph still contains the cycle, whichever order you run
    edges = import_order(cyclic)
    print("models imports:", edges["pkg.models"])
    print("store imports:", edges["pkg.store"])

    # 4. the fixed package: identical from both entry points, and it builds
    rc_fixed_models, out_fixed_models, err_fixed_models = run(
        acyclic, "import pkg.models; print('ok models first')"
    )
    rc_fixed_store, out_fixed_store, err_fixed_store = run(
        acyclic,
        "import pkg.store; s = pkg.store.Store(); print('ok store first', s.get('x').name)",
    )
    print("fixed, models first ->", rc_fixed_models, out_fixed_models)
    print("fixed, store first  ->", rc_fixed_store, out_fixed_store)

assert rc_models == 0 and "ok models first" in out_models
assert rc_store != 0, "importing the storage layer first must fail in the cyclic package"
assert "partially initialized module" in err_store
assert "cannot import name 'Store'" in err_store
assert rc_probe == 0
assert edges["pkg.models"] == ["pkg.store"] and edges["pkg.store"] == ["pkg.models"]
assert rc_fixed_models == 0 and rc_fixed_store == 0, err_fixed_store
assert out_fixed_store == "ok store first anon"
print("PASS")
@@end

@expect_output
import pkg.models -> 0 ok models first
import pkg.store  -> 1 ImportError: cannot import name 'Store' from partially initialized module 'pkg.store' (most likely due to a circular import) (<pkg>/pkg/store.py)
partial-init evidence captured: True
models imports: ['pkg.store']
store imports: ['pkg.models']
fixed, models first -> 0 ok models first
fixed, store first  -> 0 ok store first anon
PASS
@@end

@notes
Runs the same package in two subprocesses with different first imports and pins the
asymmetry: `import pkg.models` succeeds while `import pkg.store` fails with
`cannot import name 'Store' from partially initialized module 'pkg.store'`, so the
entry module really does decide the outcome. The second run confirms the mechanism
(the module object is in `sys.modules` while the attribute is missing), the parsed
import graph shows the cycle exists in both directions regardless of order, and the
one-way version is asserted to import and work identically from both entry points.
@@end

@example dep-0002
@meta category=dependency_reasoning language=python difficulty=advanced tags=module-identity,sys-path,isinstance,duplicate-state

@user
A plugin loader does `sys.path.append("app/services")` so it can `import billing` directly, while the application itself imports the same file as `app.services.billing`. Now:

- `isinstance(plugin_event, app.services.billing.Invoice)` is `False` for objects the plugin created;
- class-level registries see only half the entries;
- a module-level lock does not guard the other copy.

The file is identical in both cases. Why does importing one file two ways create two worlds, and what is the rule for `sys.path` manipulation?
@@end

@assistant
`sys.modules` is keyed by **module name**, not by file path. The same file reached under two names becomes two independent module objects, each with its own class objects, module globals, registries and locks. Python does not deduplicate by `__file__`; it only checks whether the *name* has been imported before.

So `app.services.billing.Invoice` and `billing.Invoice` are two different classes that happen to come from identical source. Consequences follow mechanically:

- `isinstance` compares identity of the class object → False, as does `except billing.BillingError` catching a `app.services.billing.BillingError`.
- Module-level state (`_registry = {}`, `_lock = threading.Lock()`, caches, `threading.local`) is per module object → two registries, two locks, so "protected" code runs unprotected against the other copy.
- Pickle and dataclasses compare classes by module/qualname, so a pickle round trip across the two names fails with `Can't get attribute`.

The rule for `sys.path`: **it is a search path for top-level names, and every entry you add is a chance to create a second name for something** — which is exactly what happens when you append an inner directory of a package to it. `app/services` on `sys.path` makes `billing` (a different module object) importable; the correct move is to import the package path (`app.services.billing`) and never let one file be reachable under two names.

```python
# wrong: a second identity for the same file
sys.path.append("app/services")
import billing

# right: one canonical import name for every file
from app.services import billing

# if a plugin must stay decoupled from the package layout, load it through the
# package's own loader so the canonical name is what lands in sys.modules
import importlib
billing = importlib.import_module("app.services.billing")
```

Diagnostics to keep in reach: `billing.__name__` and `billing.__file__` (identical file, different name), `"billing" in sys.modules` versus `"app.services.billing" in sys.modules` (both True), and `Invoice is InvoiceAlt` (False). In a running service, `len(sys.modules)` growing with duplicate-looking entries is the fingerprint of this bug — and it is also a memory leak, because both copies stay alive in `sys.modules` forever.
@@end

@verify kind=executable language=python
@code
import json
import subprocess
import sys
import tempfile
from pathlib import Path

BILLING = """
_registry = {}
_lock = object()


class Invoice:
    def __init__(self, amount_cents):
        self.amount_cents = amount_cents


class BillingError(Exception):
    pass


def register(name):
    _registry[name] = True
    return len(_registry)
"""

PROBE = """
import json
import sys

sys.path.append("app/services")          # the plugin loader's shortcut
import billing                            # identity #2
sys.path.insert(0, ".")
from app.services import billing as canonical   # identity #1

report = {
    "same_file": billing.__file__.endswith(canonical.__file__),
    "same_name": billing.__name__ == canonical.__name__,
    "same_class": billing.Invoice is canonical.Invoice,
    "both_in_sys_modules": ("billing" in sys.modules) and ("app.services.billing" in sys.modules),
    "isinstance_across_copies": isinstance(billing.Invoice(1), canonical.Invoice),
    "errors_differ": billing.BillingError is not canonical.BillingError,
}
report["registry_after_plugin_register"] = billing.register("plugin")
report["registry_seen_by_app"] = len(canonical._registry)
report["locks_differ"] = billing._lock is not canonical._lock
print(json.dumps(report, sort_keys=True))
"""

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    (root / "app" / "services").mkdir(parents=True)
    (root / "app" / "__init__.py").write_text("")
    (root / "app" / "services" / "__init__.py").write_text("")
    (root / "app" / "services" / "billing.py").write_text(BILLING)
    (root / "probe.py").write_text(PROBE)
    proc = subprocess.run([sys.executable, "probe.py"], cwd=str(root), capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr

    # 4. one canonical name is enough: importing through the package twice shares state
    canonical_only = subprocess.run(
        [sys.executable, "-c",
         "from app.services import billing\n"
         "from app.services import billing as again\n"
         "billing.register('x')\n"
         "print(billing is again, len(again._registry), billing.Invoice is again.Invoice)"],
        cwd=str(root), capture_output=True, text=True,
    )

report = json.loads(proc.stdout)

# 1. the file is identical, the identity is not
print("same file:", report["same_file"])
print("same module name:", report["same_name"])
print("same class object:", report["same_class"])
print("same lock object:", report["locks_differ"] is False)

# 2. the two symptoms the bug report names
print("isinstance across copies:", report["isinstance_across_copies"])
print("exception classes differ:", report["errors_differ"])

# 3. module-level state is duplicated, with the counts to prove it
print("registry after plugin register:", report["registry_after_plugin_register"])
print("registry seen by the app:", report["registry_seen_by_app"])
print("both names in sys.modules:", report["both_in_sys_modules"])

assert report["same_file"] is True
assert report["same_name"] is False
assert report["same_class"] is False
assert report["isinstance_across_copies"] is False
assert report["errors_differ"] is True
assert report["registry_after_plugin_register"] == 1
assert report["registry_seen_by_app"] == 0, "the app's registry never saw the plugin's write"
assert report["locks_differ"] is True
assert report["both_in_sys_modules"] is True

print("canonical import twice:", canonical_only.stdout.strip())
assert canonical_only.stdout.strip() == "True 1 True", canonical_only.stdout
print("PASS")
@@end

@expect_output
same file: True
same module name: False
same class object: False
same lock object: False
isinstance across copies: False
exception classes differ: True
registry after plugin register: 1
registry seen by the app: 0
both names in sys.modules: True
canonical import twice: True 1 True
PASS
@@end

@notes
A plugin loader's `sys.path.append("app/services")` is reproduced in a subprocess and
the two module objects are inspected side by side: identical `__file__`, different
`__name__`, different class object, `isinstance` False across the copies, distinct
exception classes (so `except` blocks miss), and a module-level registry where the
plugin's write is invisible to the application's copy (1 versus 0) while both names
sit in `sys.modules`. The last case shows the rule: importing the same canonical name
twice returns one shared module, one registry and one class object — identity is per
name, so one name per file is the invariant.
@@end

@example dep-0003
@meta category=dependency_reasoning language=python difficulty=intermediate tags=optional-dependencies,lazy-import,blast-radius,eager-init

@user
Adding one optional feature (PDF export, which needs `reportlab`, a heavy wheel we refuse to install everywhere) made the whole package unimportable on hosts that do not need it. The commit was small:

```python
# app/__init__.py
import reportlab.pdfgen                 # needed by app.export.render_pdf
from app.api import router              # the API, used by every host
```

`ModuleNotFoundError: No module named 'reportlab'` now fails at `import app`, so the API host cannot start. Should we make `reportlab` a hard dependency, or is there something structural to fix?
@@end

@assistant
Making it a hard dependency would work and is the wrong trade: it makes every deployment pay the install size, the C-extension build and the upgrade cadence of a library only one feature uses. The structural bug is *where* the import happens.

`import reportlab.pdfgen` at module scope means "this package cannot be loaded without reportlab" — and because `app/__init__.py` runs before anything inside `app` can be used, the missing dependency takes down the API host too. The blast radius of an optional dependency is exactly the size of the module that imports it eagerly. Two changes fix it:

1. **Import at the point of use, inside the function that needs it.** The failure then happens at the call site, in one feature, with a message you control.
2. **Translate the absence into a domain error once, in the feature module**, so callers do not have to know about the third-party package name.

```python
# app/export.py -- the only module that knows reportlab exists
class ExportUnavailable(RuntimeError):
    """PDF export needs the optional 'pdf' extra: pip install app[pdf]."""


def render_pdf(rows, path):
    try:
        from reportlab.pdfgen import canvas        # lazy: import cost and risk here
    except ImportError as exc:                     # only around the import
        raise ExportUnavailable(str(exc)) from exc
    document = canvas.Canvas(str(path))
    for index, row in enumerate(rows):
        document.drawString(72, 800 - 14 * index, str(row))
    document.save()
    return path


# app/__init__.py -- no optional imports, so the package always imports
from app.api import router
```

Why not `try: import reportlab` at module scope with a `None` fallback? It keeps the import cost on every start (a heavy wheel can add hundreds of milliseconds and pulls plugins into memory), and it turns a missing feature into a `None` that fails later with `AttributeError: 'NoneType' has no attribute 'pdfgen'`, far from the cause. Lazy import + a named exception keeps the failure adjacent to the request that needed it.

Two follow-on rules that stop the same problem reappearing: put optional dependencies in their own extra (`pip install app[pdf]`) so the boundary is declared in packaging, and **test the absent case** — a unit test that simulates the missing module (patch `sys.modules` or import the feature module with a faked finder) proves the API host still starts. Which modules import a feature is an architectural property, so a dependency-boundary check in CI (an import-graph rule: "nothing under `app.api` may reach `reportlab`") keeps it from creeping back.
@@end

@verify kind=executable language=python
@code
import ast
import subprocess
import sys
import tempfile
from pathlib import Path

EAGER = {
    "app/__init__.py": "import reportlab.pdfgen\nfrom app.api import router\n",
    "app/api.py": "router = object()\n",
    "app/export.py": "import reportlab.pdfgen\n\ndef render_pdf(rows):\n    return reportlab.pdfgen\n",
}

LAZY = {
    "app/__init__.py": "from app.api import router\n",
    "app/api.py": "router = object()\n",
    "app/export.py": (
        "class ExportUnavailable(RuntimeError):\n"
        '    """PDF export needs the optional extra."""\n\n\n'
        "def render_pdf(rows):\n"
        "    try:\n"
        "        from reportlab.pdfgen import canvas\n"
        "    except ImportError as exc:\n"
        "        raise ExportUnavailable(str(exc)) from exc\n"
        "    return canvas, rows\n"
    ),
    "app/main.py": (
        "from app.api import router\n"
        "from app.export import ExportUnavailable, render_pdf\n\n\n"
        "def api_only():\n"
        "    return router is not None\n\n\n"
        "def export(rows):\n"
        "    return render_pdf(rows)\n"
    ),
}


def write(root, files):
    for name, source in files.items():
        path = Path(root) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source)


def run(root, statement):
    proc = subprocess.run(
        [sys.executable, "-c", statement], cwd=str(root), capture_output=True, text=True
    )
    last_stderr = proc.stderr.strip().splitlines()[-1] if proc.stderr.strip() else ""
    return proc.returncode, proc.stdout.strip(), last_stderr


def importers(root, target):
    """Modules whose source imports `target`, at module level or inside a function."""
    found = []
    for path in sorted(Path(root).rglob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            if any(name.split(".")[0] == target for name in names):
                found.append(str(path.relative_to(root)))
                break
    return sorted(found)


with tempfile.TemporaryDirectory() as tmp:
    eager = Path(tmp) / "eager"
    lazy = Path(tmp) / "lazy"
    write(eager, EAGER)
    write(lazy, LAZY)

    # 1. the eager version: a host that never exports cannot even import the app
    eager_rc, eager_out, eager_err = run(eager, "import app; print('api host started')")
    print("eager, api host:", eager_rc, eager_err or eager_out)

    # 2. the lazy version: the same missing dependency, and the API host starts
    lazy_rc, lazy_out, lazy_err = run(
        lazy, "from app.main import api_only; print('api host started:', api_only())"
    )
    print("lazy, api host:", lazy_rc, lazy_out or lazy_err)

    # 3. the feature fails at the call site with a named error, not at import time
    export_rc, export_out, export_err = run(
        lazy,
        "from app.main import export\n"
        "from app.export import ExportUnavailable\n"
        "try:\n"
        "    export([])\n"
        "except ExportUnavailable as exc:\n"
        "    print('feature error:', type(exc).__name__,"
        " '| mentions reportlab:', 'reportlab' in str(exc))\n",
    )
    print("lazy, export call:", export_rc, export_out or export_err)

    # 4. the boundary is a property of the import graph, so it can be asserted:
    #    which modules mention the optional package in any import statement?
    eager_mentions = importers(eager, "reportlab")
    lazy_mentions = importers(lazy, "reportlab")
    print("modules mentioning reportlab (eager):", eager_mentions)
    print("modules mentioning reportlab (lazy):", lazy_mentions)

assert eager_rc != 0, "the eager version must fail to import"
assert "ModuleNotFoundError" in eager_err
assert lazy_rc == 0 and lazy_out == "api host started: True", lazy_out
assert export_rc == 0 and export_out.startswith("feature error: ExportUnavailable"), export_out
assert "reportlab" in export_out
assert eager_mentions == ["app/__init__.py", "app/export.py"], eager_mentions
assert lazy_mentions == ["app/export.py"], lazy_mentions
assert "app/api.py" not in lazy_mentions, "the API layer must not mention it"
print("PASS")
@@end

@expect_output
eager, api host: 1 ModuleNotFoundError: No module named 'reportlab'
lazy, api host: 0 api host started: True
lazy, export call: 0 feature error: ExportUnavailable | mentions reportlab: True
modules mentioning reportlab (eager): ['app/__init__.py', 'app/export.py']
modules mentioning reportlab (lazy): ['app/export.py']
PASS
@@end

@notes
Both packages are built in a temp directory and imported in subprocesses with
`reportlab` genuinely absent. Pinned: the eager version fails at `import app` for a
host that only serves the API, while the lazy version starts that host with the same
missing package; the feature call fails at the call site with a named
`ExportUnavailable` whose message names the missing library; and the boundary is
checked as an import-graph property (`app.api` cannot reach `reportlab`, `app.export`
can) — the check that keeps an eager import from creeping back in.
@@end

@example dep-0004
@meta category=dependency_reasoning language=python difficulty=intermediate tags=monkeypatching,name-binding,test-doubles,tracing

@user
Our test freezes time and it does not work for the service under test, though it works for other modules:

```python
# clock.py
def now():
    return datetime.now(timezone.utc)


# pricing.py
from clock import now          # line 2

def quote(payload):
    return {"at": now().isoformat(), **payload}
```

The test does `clock.now = lambda: FROZEN` and asserts `pricing.quote({})["at"] == FROZEN_ISO`. It fails with the real timestamp. Direct calls to `clock.now()` in the same test do return the frozen value. What is `from clock import now` actually doing, and where should the test patch?
@@end

@assistant
`from clock import now` **binds a name in `pricing`'s namespace to the function object that existed at import time.** Rebinding `clock.now` afterwards changes the attribute on the `clock` module; it cannot reach the copy already stored as `pricing.now`. So `pricing.quote` keeps calling the original function — which is why direct `clock.now()` calls are patched and the service under test is not.

This is name binding, not dynamic lookup: Python resolves a global name at call time by looking it up in the *calling module's* globals, so `pricing.now` is the lookup that matters, and that entry was copied when `pricing` was imported. There is no live link back to `clock`.

Three ways to fix it, in order of preference:

```python
# 1. patch where the name is looked up (what the test should do)
monkeypatch.setattr("pricing.now", lambda: FROZEN)      # pytest, undone automatically
# or unittest.mock: patch("pricing.now", lambda: FROZEN)

# 2. inject the dependency instead of importing it, which removes the question
def quote(payload, *, clock_now=now):                    # default bound at def time
    return {"at": clock_now().isoformat(), **payload}
quote({}, clock_now=lambda: FROZEN)                      # no patching at all

# 3. keep the module import and look the attribute up late (accepting more prose)
import clock
def quote(payload):
    return {"at": clock.now().isoformat(), **payload}    # patch clock.now, as expected
```

Rule of thumb: `from module import thing` binds a **snapshot of the reference**; `import module` then `module.thing` performs the lookup at call time. Both are legitimate, but they answer "where do I patch?" differently, and the test must patch the name the code actually reads. `unittest.mock.patch` documents this by convention: you patch the *importing* module (`patch("pricing.now")`), and patching the defining module is only correct for code that reads it there.

The failure mode is quiet by design: the patched function still runs for other callers, so the suite reports a wrong timestamp rather than an error, and a careless reviewer will blame the clock. When a freeze/sabotage patch "does not take effect", the first thing to print is `pricing.now is clock.now` — before the patch it is True, after patching `clock.now` it is False, and that single line identifies the binding being read.
@@end

@verify kind=executable language=python
@code
import sys
import textwrap
import types

CLOCK = textwrap.dedent('''
    def now():
        return "real-now"
''')

PRICING = textwrap.dedent('''
    from clock import now          # copies the reference


    def quote(payload):
        return {"at": now(), **payload}
''')

LATE = textwrap.dedent('''
    import clock                   # looks the attribute up at call time


    def quote(payload):
        return {"at": clock.now(), **payload}
''')


def build(pricing_source, suffix=""):
    """Register real module objects in sys.modules, which is what `import` reads."""
    clock = types.ModuleType("clock" + suffix)
    exec(compile(CLOCK, "clock.py", "exec"), clock.__dict__)
    pricing = types.ModuleType("pricing" + suffix)
    sys.modules["clock" + suffix] = clock
    sys.modules["pricing" + suffix] = pricing
    source = pricing_source.replace("clock", "clock" + suffix)
    exec(compile(source, "pricing.py", "exec"), pricing.__dict__)
    return clock, pricing


FROZEN = "frozen-now"

# 1. the failing patch: rebinding the defining module does not reach the copy
clock, pricing = build(PRICING)
print("before patching: pricing.now is clock.now:", pricing.now is clock.now)
clock.now = lambda: FROZEN
print("direct clock.now():", clock.now())
print("pricing.quote at:", pricing.quote({})["at"])

# 2. patching the importing name works
pricing.now = lambda: FROZEN
print("patched where it is read:", pricing.quote({})["at"])

# 3. the late-lookup variant shows the opposite behaviour
clock_late, pricing_late = build(LATE, "_late")
clock_late.now = lambda: FROZEN
print("late lookup sees the patch:", pricing_late.quote({})["at"])

# 4. the one-line diagnostic
clock2, pricing2 = build(PRICING, "_diag")
before = pricing2.now is clock2.now
clock2.now = lambda: FROZEN
after = pricing2.now is clock2.now
print("identity before patch:", before, "| identity after patching clock.now:", after)

# 5. dependency injection removes the question entirely
def quote_injected(payload, *, clock_now=None):
    clock_now = clock_now or pricing.now
    return {"at": clock_now(), **payload}


print("injected clock:", quote_injected({}, clock_now=lambda: FROZEN)["at"])

assert before is True
assert after is False, "the imported name is a snapshot, not a live link"
assert pricing.quote({})["at"] == FROZEN
assert clock.now() == FROZEN
assert pricing_late.quote({})["at"] == FROZEN
assert quote_injected({}, clock_now=lambda: FROZEN)["at"] == FROZEN
print("PASS")
@@end

@expect_output
before patching: pricing.now is clock.now: True
direct clock.now(): frozen-now
pricing.quote at: real-now
patched where it is read: frozen-now
late lookup sees the patch: frozen-now
identity before patch: True | identity after patching clock.now: False
injected clock: frozen-now
PASS
@@end

@notes
Builds the two modules in memory and pins the binding semantics that explain the
report: before patching, `pricing.now is clock.now` is True (the imported name is a
snapshot), and after `clock.now` is rebound it is False while `pricing.quote` still
returns the real timestamp. Patching `pricing.now` — the name the code actually
looks up — works, the `import clock` variant sees the same patch with no test change,
and the injection form needs no patching at all. The identity check is pinned as the
one-line diagnostic for "my patch does not take effect".
@@end
