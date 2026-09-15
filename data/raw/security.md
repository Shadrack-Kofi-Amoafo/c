@example py-sec-0001
@meta category=security language=python difficulty=advanced tags=password-hashing,scrypt,constant-time,key-versioning

@user
Our user table stores `sha256(password)` — no salt, one round. A penetration test flagged it and gave us two weeks. What should we store instead, and how do we migrate existing rows without forcing 200k users to reset their passwords? We are on Python 3.11 stdlib only.
@@end

@assistant
Unsalted SHA-256 is the worst case: one GPU rig tries billions of guesses per second, and an identical password produces an identical hash, so a single rainbow table cracks every user at once. Replace it with a **memory-hard** KDF — `hashlib.scrypt` is in the stdlib and designed so that brute-forcing costs memory, not just CPU.

The design that survives a review:

- **Per-user random salt** (16+ bytes from `secrets`), stored beside the hash. Salt defeats rainbow tables and makes identical passwords hash differently.
- **A versioned record**, not a bare digest: `scrypt$1$n=16384,r=8,p=1$<salt>$<hash>`. Versioning is what lets you raise the cost factor next year without a flag day.
- **Constant-time comparison** with `secrets.compare_digest`. `==` short-circuits, which leaks the length of the correct prefix through timing.
- **Verify on login, upgrade on success.** The only moment you hold the plaintext is login, so that is where you re-hash the legacy rows. No forced reset, and the work is spread over normal traffic.
- **Parameter sets you can defend.** `n=16384, r=8, p=1` needs ~16MB per hash (128·n·r bytes); tune against your login budget and record the parameters *in* the record so verification never depends on today's constants.
- **A pepper for defence in depth** — an HMAC of the password with a key stored outside the database (env/KMS) — means a database dump alone is not enough. Apply it as `hmac(pepper, password)` before the KDF, and treat rotating the pepper as a login-time migration too.

```python
import base64
import hashlib
import hmac
import secrets

SCRYPT_N, SCRYPT_R, SCRYPT_P = 16384, 8, 1
SALT_BYTES = 16
CURRENT_VERSION = 1


def _peppered(password: str, pepper: bytes) -> bytes:
    return hmac.new(pepper, password.encode("utf-8"), hashlib.sha256).digest()


def hash_password(password: str, *, pepper: bytes = b"", version: int = CURRENT_VERSION) -> str:
    if not password:
        raise ValueError("empty password")
    salt = secrets.token_bytes(SALT_BYTES)
    digest = hashlib.scrypt(
        _peppered(password, pepper), salt=salt,
        n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32, maxmem=64 * 1024 * 1024,
    )
    return "$".join([
        "scrypt", str(version),
        f"n={SCRYPT_N},r={SCRYPT_R},p={SCRYPT_P}",
        base64.b64encode(salt).decode(),
        base64.b64encode(digest).decode(),
    ])


def verify_password(password: str, record: str, *, pepper: bytes = b"") -> tuple[bool, bool]:
    """Return (ok, needs_rehash). Legacy sha256 records are supported for migration."""
    if record.startswith("scrypt$"):
        _, version, params, salt_b64, digest_b64 = record.split("$")
        settings = dict(part.split("=") for part in params.split(","))
        n, r, p = int(settings["n"]), int(settings["r"]), int(settings["p"])
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
        candidate = hashlib.scrypt(
            _peppered(password, pepper), salt=salt, n=n, r=r, p=p,
            dklen=len(expected), maxmem=64 * 1024 * 1024,
        )
        ok = secrets.compare_digest(candidate, expected)
        needs_rehash = ok and (
            int(version) != CURRENT_VERSION or (n, r, p) != (SCRYPT_N, SCRYPT_R, SCRYPT_P)
        )
        return ok, needs_rehash
    if record.startswith("sha256$"):
        legacy = hashlib.sha256(password.encode("utf-8")).hexdigest()
        ok = secrets.compare_digest(legacy, record.split("$", 1)[1])
        return ok, ok          # a legacy record is always upgraded on success
    raise ValueError("unrecognised password record")


def login(password: str, record: str, *, pepper: bytes = b"") -> tuple[bool, str | None]:
    """Verify and, on success, return a fresh record when the old one is weak."""
    ok, needs_rehash = verify_password(password, record, pepper=pepper)
    if not ok:
        return False, None
    if needs_rehash:
        return True, hash_password(password, pepper=pepper)
    return True, None
```

Two more things the ticket will not mention but the review will ask about:

- **Rate limiting is not optional.** A perfect KDF still falls to online guessing if the endpoint allows unlimited attempts; the login handler needs a per-account and per-IP limiter, and the timing of "unknown user" must match "wrong password" (hash a dummy record so the response time does not reveal account existence).
- **`dklen` / `maxmem` are part of the parameters.** `hashlib.scrypt` raises `ValueError: memory limit exceeded` if OpenSSL's default `maxmem` (32MB) is below `128·n·r`; passing `maxmem` explicitly avoids a login outage on the day you raise `n`.
@@end

@verify kind=executable language=python
@code
import base64
import hashlib
import hmac
import secrets
import time

SCRYPT_N, SCRYPT_R, SCRYPT_P = 16384, 8, 1
SALT_BYTES = 16
CURRENT_VERSION = 1


def _peppered(password, pepper):
    return hmac.new(pepper, password.encode("utf-8"), hashlib.sha256).digest()


def hash_password(password, *, pepper=b"", version=CURRENT_VERSION, salt=None):
    if not password:
        raise ValueError("empty password")
    salt = salt or secrets.token_bytes(SALT_BYTES)
    digest = hashlib.scrypt(
        _peppered(password, pepper), salt=salt,
        n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32, maxmem=64 * 1024 * 1024,
    )
    return "$".join([
        "scrypt", str(version), f"n={SCRYPT_N},r={SCRYPT_R},p={SCRYPT_P}",
        base64.b64encode(salt).decode(), base64.b64encode(digest).decode(),
    ])


def verify_password(password, record, *, pepper=b""):
    if record.startswith("scrypt$"):
        _, version, params, salt_b64, digest_b64 = record.split("$")
        settings = dict(part.split("=") for part in params.split(","))
        n, r, p = int(settings["n"]), int(settings["r"]), int(settings["p"])
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
        candidate = hashlib.scrypt(
            _peppered(password, pepper), salt=salt, n=n, r=r, p=p,
            dklen=len(expected), maxmem=64 * 1024 * 1024,
        )
        ok = secrets.compare_digest(candidate, expected)
        needs_rehash = ok and (
            int(version) != CURRENT_VERSION or (n, r, p) != (SCRYPT_N, SCRYPT_R, SCRYPT_P)
        )
        return ok, needs_rehash
    if record.startswith("sha256$"):
        legacy = hashlib.sha256(password.encode("utf-8")).hexdigest()
        ok = secrets.compare_digest(legacy, record.split("$", 1)[1])
        return ok, ok          # a legacy record is always upgraded on success
    raise ValueError("unrecognised password record")


def login(password, record, *, pepper=b""):
    ok, needs_rehash = verify_password(password, record, pepper=pepper)
    if not ok:
        return False, None
    if needs_rehash:
        return True, hash_password(password, pepper=pepper)
    return True, None


# 1. Round trip, and the record carries its own parameters (no global constants
#    are needed to verify an old row after the cost factor is raised).
record = hash_password("correct horse battery staple")
assert record.startswith("scrypt$1$n=16384,r=8,p=1$")
assert verify_password("correct horse battery staple", record) == (True, False)
assert verify_password("Correct horse battery staple", record) == (False, False)
assert verify_password("", record) == (False, False)

# 2. Salting: identical passwords give different records, and both verify.
a = hash_password("same-password", salt=b"\x01" * 16)
b = hash_password("same-password", salt=b"\x02" * 16)
assert a != b
assert a.split("$")[3] != b.split("$")[3]
assert verify_password("same-password", a) == (True, False)
assert verify_password("same-password", b) == (True, False)

# 3. No plaintext or fast-hash shortcut: the stored digest is not sha256(password)
#    and the digest differs from any single-round construction.
digest = base64.b64decode(record.split("$")[4])
assert digest != hashlib.sha256(b"correct horse battery staple").digest()
assert digest != hashlib.sha256(b"correct horse battery staple").digest()[:32]
assert len(digest) == 32

# 4. Legacy migration: a sha256 row verifies, and login hands back a fresh scrypt
#    record that supersedes it (this is the no-forced-reset path).
legacy = "sha256$" + hashlib.sha256(b"hunter2").hexdigest()
assert verify_password("hunter2", legacy) == (True, True), "legacy rows must ask to be rehashed"
ok, upgraded = login("hunter2", legacy)
assert ok and upgraded.startswith("scrypt$1$")
assert verify_password("hunter2", upgraded) == (True, False)
assert verify_password("wrong", upgraded) == (False, False)
assert login("wrong", legacy) == (False, None)

# 5. Upgrade-on-login for a weak-but-valid scrypt record: raise the cost factor
#    by hand and confirm the rehash is triggered only on a correct password.
weak = hash_password("rotate-me", version=0)
assert verify_password("rotate-me", weak) == (True, True)
assert verify_password("nope", weak) == (False, False)
ok, refreshed = login("rotate-me", weak)
assert ok and refreshed != weak and "scrypt$1$" in refreshed

# 6. The pepper is required: a record hashed with a pepper must not verify without
#    it, so a stolen database alone is not enough.
pepper = b"kms-key-material"
peppered = hash_password("pepper-me", pepper=pepper)
assert verify_password("pepper-me", peppered, pepper=pepper) == (True, False)
assert verify_password("pepper-me", peppered) == (False, False)
assert verify_password("pepper-me", peppered, pepper=b"wrong") == (False, False)

# 7. Comparison is constant-time by construction; also assert that the failure
#    path does not raise on a truncated digest (a classic oracle: a short record
#    must fail closed, not crash).
short = "$".join(record.split("$")[:4] + [base64.b64encode(b"\x00" * 4).decode()])
assert verify_password("correct horse battery staple", short) == (False, False)
assert verify_password("x", "sha256$deadbeef") == (False, False)
try:
    verify_password("x", "bcrypt$whatever")
    raise AssertionError("unknown schemes must be rejected loudly")
except ValueError:
    pass

# 8. Cost: hashing is deliberately slow (a login must be, an attacker's guess
#    must be worse). Assert a floor and a generous ceiling so the test is not a
#    benchmark.
started = time.perf_counter()
hash_password("timing-probe")
elapsed = time.perf_counter() - started
assert elapsed > 0.001, f"scrypt is suspiciously fast: {elapsed:.6f}s"
assert elapsed < 2.0, f"scrypt is too slow for a login path: {elapsed:.3f}s"

# 9. Empty passwords are refused at the boundary rather than producing a record.
try:
    hash_password("")
    raise AssertionError("empty password must be refused")
except ValueError:
    pass
print("PASS")
@@end

@expect_output
PASS
@@end

@notes
Nine executed cases. Pinned: the record is self-describing
(`scrypt$1$n=16384,r=8,p=1$salt$digest`) and verifies without reference to module
constants; wrong and empty passwords fail; identical passwords with different
salts produce different records that both verify; the stored digest differs from a
single-round SHA-256 of the password; the legacy `sha256$` row verifies and
login returns a fresh scrypt record (the no-forced-reset migration path: the legacy
record reports `needs_rehash`, and a wrong-password attempt must not upgrade
anything); a weak scrypt record
(version 0) triggers rehash-on-success only; a pepper is required for a peppered
record, so a database dump alone cannot be verified offline; truncated and unknown
records fail closed (constant-time comparison must not raise), with unknown
schemes rejected loudly; hashing takes a measurable but login-acceptable amount of
time; and an empty password is refused at the boundary.
@@end

@example py-sec-0002
@meta category=security language=python difficulty=intermediate tags=sql-injection,parameterised-queries,like-escaping,sqlite

@user
A security review flagged our admin search as SQL injectable because it builds the query with an f-string. It also said our `LIKE` search lets a user type `%` and dump the whole table. The obvious fix — parameterising the value — makes the injection go away, but how do I keep the wildcard escaping working, and how do I prove any of this in a test?
@@end

@assistant
Two distinct bugs, and parameterising only fixes the first:

1. **String interpolation of user input** is injectable, and you must parameterise *every* value — including the `LIMIT`, the `ORDER BY` column if it is user-controlled, and the `LIKE` pattern.
2. **Unescaped wildcards in `LIKE`** are an information-disclosure bug that survives parameterisation. `WHERE name LIKE '%' || ? || '%'` with a parameter is *not* injectable, but a user typing `%` matches everything, and `_` matches any single character; a `%a%b%c%` pattern can be used to brute-force a hidden value character by character. Escape `\`, `%` and `_` in the value and add `ESCAPE '\'` to the predicate.

Two more things worth fixing while you are in there:

- **Do not build `ORDER BY` from a raw parameter.** Sorting is syntax, not data: map the user's choice through an allowlist of column names.
- **Run the admin search under a least-privileged connection.** Even a correct query is only as safe as the account executing it; a read-only role bounds the damage of the next mistake.

```python
import sqlite3

ALLOWED_SORTS = {"name": "name", "qty": "qty DESC", "id": "id"}


def escape_like(value: str) -> str:
    """Escape LIKE wildcards. Backslash first, or you escape your escapes."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def search(conn, term: str, *, sort: str = "name", limit: int = 50):
    if sort not in ALLOWED_SORTS:
        raise ValueError(f"unsupported sort key: {sort!r}")
    if not isinstance(limit, int) or not 1 <= limit <= 500:
        raise ValueError("limit out of range")
    pattern = f"%{escape_like(term)}%"
    sql = (
        "SELECT id, name, qty FROM items "
        "WHERE name LIKE ? ESCAPE '\\' "
        f"ORDER BY {ALLOWED_SORTS[sort]} LIMIT ?"      # interpolated from an allowlist only
    )
    return conn.execute(sql, (pattern, limit)).fetchall()


def search_unsafe(conn, term, sort="name", limit=50):
    """The reviewed version: f-string built, wildcards unescaped. Do not use."""
    sql = (f"SELECT id, name, qty FROM items WHERE name LIKE '%{term}%' "
           f"ORDER BY {sort} LIMIT {limit}")
    return conn.execute(sql).fetchall()
```

Why each piece matters:

- **`escape_like` must escape the backslash before `%` and `_`.** Reverse the order and `\` in the user's input becomes an escape character for the *next* character, changing the semantics of the pattern.
- **Parameters bind values, never identifiers.** `ORDER BY ?` binds a string literal — SQLite accepts it and silently sorts by a constant. The allowlist is the only correct mechanism.
- **`LIMIT ?` still needs validation.** Parameterisation prevents injection, not a request for a billion rows.
- **`sqlite3` has no `EXPLAIN`-visible injection guard.** The test is behavioural: send attack strings and assert the result set is what a user would expect (empty), not the whole table.

```python
AJAX_TABLE = [
    ("1", "' OR '1'='1"),
    ("2", "'; DROP TABLE items; --"),
    ("3", "%"),
    ("4", "_"),
    ("5", "100% cotton"),
    ("6", "a_b"),
    ("7", "50\\%"),
]
```

Each of those strings must come back with an empty (or exact-match) result from the safe search, and the `items` table must still exist afterwards.
@@end

@verify kind=executable language=python
@code
import sqlite3

ALLOWED_SORTS = {"name": "name", "qty": "qty DESC", "id": "id"}


def escape_like(value):
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def search(conn, term, *, sort="name", limit=50):
    if sort not in ALLOWED_SORTS:
        raise ValueError(f"unsupported sort key: {sort!r}")
    if not isinstance(limit, int) or not 1 <= limit <= 500:
        raise ValueError("limit out of range")
    pattern = f"%{escape_like(term)}%"
    sql = (
        "SELECT id, name, qty FROM items "
        "WHERE name LIKE ? ESCAPE '\\' "
        f"ORDER BY {ALLOWED_SORTS[sort]} LIMIT ?"
    )
    return conn.execute(sql, (pattern, limit)).fetchall()


def search_unsafe(conn, term, sort="name", limit=50):
    sql = (f"SELECT id, name, qty FROM items WHERE name LIKE '%{term}%' "
           f"ORDER BY {sort} LIMIT {limit}")
    return conn.execute(sql).fetchall()


ITEMS = [
    ("1", "widget", 10),
    ("2", "gadget", 20),
    ("3", "100% cotton shirt", 5),
    ("4", "a_b sensor", 7),
    ("5", "plain", 1),
]


def fresh_conn():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE items (id TEXT PRIMARY KEY, name TEXT NOT NULL, qty INTEGER NOT NULL)")
    conn.executemany("INSERT INTO items VALUES (?, ?, ?)", ITEMS)
    return conn


conn = fresh_conn()

# 1. Normal search works and returns the expected rows.
assert [row[0] for row in search(conn, "gadg")] == ["2"]
assert [row[0] for row in search(conn, "widget")] == ["1"]
assert search(conn, "nothing-matches") == []
assert sorted(row[0] for row in search(conn, "")) == ["1", "2", "3", "4", "5"]
assert [row[0] for row in search(conn, "plain", sort="qty")] == ["5"]

# 2. The wildcards are literal data, not pattern syntax.
assert [row[0] for row in search(conn, "100%")] == ["3"], "the user's % must be literal"
assert [row[0] for row in search(conn, "a_b")] == ["4"], "the user's _ must be literal"
# A bare wildcard now matches only rows containing that character literally.
assert [row[0] for row in search(conn, "%")] == ["3"], "a bare % must not match everything"
assert [row[0] for row in search(conn, "_")] == ["4"], "a bare _ must not match single characters"
# A combination that would be a wildcard pattern is inert for the same reason.
assert search(conn, "%_%") == [], "wildcard sequences must not become active"
# The unsafe version does the opposite: the classic data-disclosure bug.
assert len(search_unsafe(conn, "%")) == len(ITEMS)
assert len(search_unsafe(conn, "_")) == len(ITEMS)

# 3. Escaping composes: a literal backslash stays literal, and escaping is
#    applied to the backslash before the wildcards.
assert [row[0] for row in search(conn, "\\")] == []
assert escape_like("50\\%") == "50\\\\\\%"
assert search(conn, "50\\%") == [], "no name contains a backslash"

# 4. Injection attempts return nothing and leave the schema intact.
ATTACKS = [
    "' OR '1'='1",
    "'; DROP TABLE items; --",
    "' UNION SELECT id, name, qty FROM items --",
    "widget' --",
    "%' OR '1'='1",
]
for attack in ATTACKS:
    assert search(conn, attack) == [], f"attack slipped through: {attack!r}"
assert conn.execute(
    "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='items'"
).fetchone()[0] == 1, "the table must still exist"
assert conn.execute("SELECT COUNT(*) FROM items").fetchone()[0] == len(ITEMS)

# 5. The unsafe version really is exploitable: the same attack string leaks rows,
#    so the test would fail if someone "fixed" the injection by escaping only.
leaked = search_unsafe(conn, "' OR '1'='1")
assert len(leaked) == len(ITEMS), "the unsafe query must leak every row (that is the bug)"

# 6. Structured inputs are validated, not interpolated.
for bad_sort in ("quantity", "name; DROP TABLE items", "(SELECT 1)"):
    try:
        search(conn, "x", sort=bad_sort)
        raise AssertionError(f"sort key must be rejected: {bad_sort!r}")
    except ValueError:
        pass
assert [row[0] for row in search(conn, "widget", sort="qty")] == ["1"]
for bad_limit in (0, -1, 10_000, "50", 1.5):
    try:
        search(conn, "x", limit=bad_limit)
        raise AssertionError(f"limit must be rejected: {bad_limit!r}")
    except ValueError:
        pass
# An allowlisted sort still works after the rejections.
assert [row[0] for row in search(conn, "e", sort="id")] == ["1", "2", "4"]
assert [row[0] for row in search(conn, "e", sort="qty")] == ["2", "1", "4"]

# 7. A least-privileged connection cannot write: even a hypothetical injection
#    cannot mutate data when the role is read-only.
readonly = sqlite3.connect("file::memory:?cache=shared", uri=True)
readonly.execute("CREATE TABLE IF NOT EXISTS guard (id INTEGER PRIMARY KEY)")
readonly.execute("PRAGMA query_only = ON")
try:
    readonly.execute("INSERT INTO guard VALUES (1)")
    raise AssertionError("query_only must block writes")
except sqlite3.OperationalError:
    pass
assert readonly.execute("SELECT COUNT(*) FROM guard").fetchone()[0] == 0

# 8. Injection through the LIKE pattern is also blocked (parameterised), which is
#    the difference between "escape the wildcards" and "trust the pattern".
assert search(conn, "' OR 1=1 --") == []
assert search(conn, "widget' OR '1'='1' --") == []
print("PASS")
@@end

@expect_output
PASS
@@end

@notes
Executed against a real SQLite database. Pinned: normal substring search and the
allowlisted sort work; a user-typed `%` or `_` is treated as a literal (it matches only the row
containing that character, and the combination `%_%` matches nothing) while the
unsafe version returns every row for either character — the
information-disclosure bug reproduced side by side with the fix; escaping handles
backslashes in the right order; five injection payloads (tautology, stacked
DROP TABLE, UNION SELECT, comment truncation, wildcard-prefixed) all return no
rows and the table plus its five rows survive; the unsafe query demonstrably leaks
everything for the same payload, so the test cannot pass by accident; unsupported
sort keys and out-of-range limits raise ValueError while allowlisted sorts still
work; and a `PRAGMA query_only` connection refuses writes, showing the
defence-in-depth layer that bounds the next mistake.
@@end

@example js-sec-0003
@meta category=security language=javascript difficulty=advanced tags=hmac,session-tokens,timing-attack,key-rotation

@user
We issue a session cookie that is base64 JSON of `{userId, expires}` — the review says users can edit their own session. We want signed tokens without pulling in a JWT library, and we need to rotate the signing key without logging everyone out. What is the safest small design, and how do I test the security properties rather than just the happy path?
@@end

@assistant
A signed opaque token, built from `node:crypto`, is a better fit than a JWT here for three reasons: you control the format, there is no `alg` header for an attacker to negotiate, and rotation is a key-id lookup rather than an unknown-kid branch.

Design rules:

- **Sign over the exact bytes you send.** `payloadB64 + "." + signatureB64` where both are base64url; verifying a *re-encoded* payload invites canonicalisation bugs.
- **`timingSafeEqual` for the comparison**, and check lengths first (it throws on unequal lengths). A `===` comparison on the signature leaks the correct prefix byte by byte.
- **Key ids, not key guessing.** The header carries `kid`; look it up in a map and reject unknown kids. Verify with the *matched* key only, then accept any key in the set — that is how rotation works without a flag day.
- **Put `exp` in the signed payload and validate server-side**, with a small leeway for clock skew; do not trust an unsigned `expires` in the cookie.
- **Constant response shape.** Do not distinguish "bad signature" from "expired" in the API response; only in the logs.
- **Sign then encode, never encode then sign the string you already built elsewhere.** The property you want is: the signature covers exactly the bytes in the cookie.

```javascript
import crypto from "node:crypto";

const b64url = (buf) => Buffer.from(buf).toString("base64url");
const fromB64url = (str) => Buffer.from(str, "base64url");

export function sign(payload, { key, kid = "k1" }) {
  const header = b64url(JSON.stringify({ v: 1, kid }));
  const body = b64url(JSON.stringify(payload));
  const signingInput = `${header}.${body}`;
  const mac = crypto.createHmac("sha256", key).update(signingInput).digest();
  return `${signingInput}.${b64url(mac)}`;
}

export function verify(token, { keys, now = Date.now, leewaySeconds = 30 }) {
  if (typeof token !== "string") return { ok: false, reason: "malformed" };
  const parts = token.split(".");
  if (parts.length !== 3) return { ok: false, reason: "malformed" };
  const [headerB64, bodyB64, macB64] = parts;

  let header;
  try {
    header = JSON.parse(fromB64url(headerB64).toString("utf8"));
  } catch {
    return { ok: false, reason: "malformed" };
  }
  const key = keys[header.kid];
  if (!key) return { ok: false, reason: "unknown-key" };

  const expected = crypto.createHmac("sha256", key)
    .update(`${headerB64}.${bodyB64}`).digest();
  const provided = fromB64url(macB64);
  if (provided.length !== expected.length) return { ok: false, reason: "bad-signature" };
  if (!crypto.timingSafeEqual(provided, expected)) return { ok: false, reason: "bad-signature" };

  let payload;
  try {
    payload = JSON.parse(fromB64url(bodyB64).toString("utf8"));
  } catch {
    return { ok: false, reason: "malformed" };
  }
  if (typeof payload.exp !== "number") return { ok: false, reason: "malformed" };
  if (now() / 1000 > payload.exp + leewaySeconds) return { ok: false, reason: "expired" };
  return { ok: true, payload, kid: header.kid };
}
```

The tests that matter are the negative ones: flip one character of the body (signature must fail), strip the signature, swap the payload while keeping the old signature (the attack the review found), pass a token signed with a retired key (must fail), pass an expired token (must fail), and rotate: a token signed with `k1` still verifies while new tokens are issued with `k2`.
@@end

@verify kind=executable language=javascript
@code
import assert from "node:assert/strict";
import crypto from "node:crypto";
import test from "node:test";

const b64url = (buf) => Buffer.from(buf).toString("base64url");
const fromB64url = (str) => Buffer.from(str, "base64url");

function sign(payload, { key, kid = "k1" }) {
  const header = b64url(JSON.stringify({ v: 1, kid }));
  const body = b64url(JSON.stringify(payload));
  const signingInput = `${header}.${body}`;
  const mac = crypto.createHmac("sha256", key).update(signingInput).digest();
  return `${signingInput}.${b64url(mac)}`;
}

function verify(token, { keys, now = Date.now, leewaySeconds = 30 }) {
  if (typeof token !== "string") return { ok: false, reason: "malformed" };
  const parts = token.split(".");
  if (parts.length !== 3) return { ok: false, reason: "malformed" };
  const [headerB64, bodyB64, macB64] = parts;

  let header;
  try {
    header = JSON.parse(fromB64url(headerB64).toString("utf8"));
  } catch {
    return { ok: false, reason: "malformed" };
  }
  const key = keys[header.kid];
  if (!key) return { ok: false, reason: "unknown-key" };

  const expected = crypto.createHmac("sha256", key).update(`${headerB64}.${bodyB64}`).digest();
  const provided = fromB64url(macB64);
  if (provided.length !== expected.length) return { ok: false, reason: "bad-signature" };
  if (!crypto.timingSafeEqual(provided, expected)) return { ok: false, reason: "bad-signature" };

  let payload;
  try {
    payload = JSON.parse(fromB64url(bodyB64).toString("utf8"));
  } catch {
    return { ok: false, reason: "malformed" };
  }
  if (typeof payload.exp !== "number") return { ok: false, reason: "malformed" };
  if (now() / 1000 > payload.exp + leewaySeconds) return { ok: false, reason: "expired" };
  return { ok: true, payload, kid: header.kid };
}

const K1 = crypto.randomBytes(32);
const K2 = crypto.randomBytes(32);
const KEYS = { k1: K1, k2: K2 };
const ISS = 1_700_000_000;
const clockAt = (seconds) => () => seconds * 1000;

test("a freshly signed token verifies and yields the original payload", () => {
  const token = sign({ userId: "u-1", exp: ISS + 3600 }, { key: K1, kid: "k1" });
  const result = verify(token, { keys: KEYS, now: clockAt(ISS) });
  assert.equal(result.ok, true);
  assert.deepEqual(result.payload, { userId: "u-1", exp: ISS + 3600 });
  assert.equal(result.kid, "k1");
});

test("the payload cannot be edited while keeping the signature", () => {
  const token = sign({ userId: "u-1", role: "user", exp: ISS + 3600 }, { key: K1 });
  const [, bodyB64, mac] = token.split(".");
  const forgedBody = b64url(JSON.stringify({ userId: "u-1", role: "admin", exp: ISS + 3600 }));
  const forged = `${token.split(".")[0]}.${forgedBody}.${mac}`;
  assert.notEqual(forgedBody, bodyB64);
  const result = verify(forged, { keys: KEYS, now: clockAt(ISS) });
  assert.equal(result.ok, false);
  assert.equal(result.reason, "bad-signature");
});

test("a token signed with a different key is rejected", () => {
  const token = sign({ userId: "u-1", exp: ISS + 3600 }, { key: crypto.randomBytes(32), kid: "k1" });
  assert.equal(verify(token, { keys: KEYS, now: clockAt(ISS) }).reason, "bad-signature");
});

test("the previous mistake -- unsigned base64 JSON -- is rejected outright", () => {
  const legacy = Buffer.from(JSON.stringify({ userId: "u-1", role: "admin" })).toString("base64url");
  for (const bad of [legacy, `${legacy}.`, `..`, `.${legacy}.`, "", "a.b.c"]) {
    assert.equal(verify(bad, { keys: KEYS }).ok, false, `accepted ${JSON.stringify(bad)}`);
  }
  assert.equal(verify(null, { keys: KEYS }).ok, false);
  assert.equal(verify(12345, { keys: KEYS }).ok, false);
});

test("tampering with the signature itself is detected byte for byte", () => {
  const token = sign({ userId: "u-1", exp: ISS + 3600 }, { key: K1 });
  const [header, body, mac] = token.split(".");
  const macBytes = fromB64url(mac);
  for (let i = 0; i < macBytes.length; i++) {
    const mutated = Buffer.from(macBytes);
    mutated[i] ^= 0x01;
    const candidate = `${header}.${body}.${b64url(mutated)}`;
    assert.equal(verify(candidate, { keys: KEYS, now: clockAt(ISS) }).ok, false, `byte ${i}`);
  }
  const truncated = `${header}.${body}.${mac.slice(0, mac.length - 4)}`;
  assert.equal(verify(truncated, { keys: KEYS, now: clockAt(ISS) }).reason, "bad-signature");
});

test("expiry is enforced from the signed payload, with leeway", () => {
  const token = sign({ userId: "u-1", exp: ISS + 60 }, { key: K1 });
  assert.equal(verify(token, { keys: KEYS, now: clockAt(ISS) }).ok, true);
  assert.equal(verify(token, { keys: KEYS, now: clockAt(ISS + 61) }).ok, true, "in leeway");
  assert.equal(verify(token, { keys: KEYS, now: clockAt(ISS + 95) }).reason, "expired");
  const noExp = sign({ userId: "u-1" }, { key: K1 });
  assert.equal(verify(noExp, { keys: KEYS, now: clockAt(ISS) }).reason, "malformed");
});

test("key rotation: old tokens keep working, new ones use the new kid", () => {
  const oldToken = sign({ userId: "u-1", exp: ISS + 3600 }, { key: K1, kid: "k1" });
  const newToken = sign({ userId: "u-1", exp: ISS + 3600 }, { key: K2, kid: "k2" });
  const now = clockAt(ISS);
  assert.equal(verify(oldToken, { keys: KEYS, now }).ok, true);
  assert.equal(verify(newToken, { keys: KEYS, now }).ok, true);
  assert.equal(verify(newToken, { keys: KEYS, now }).kid, "k2");

  // Retiring K1 must invalidate the old tokens and only the old ones.
  const retired = { k2: K2 };
  assert.equal(verify(oldToken, { keys: retired, now }).ok, false);
  assert.equal(verify(oldToken, { keys: retired, now }).reason, "unknown-key");
  assert.equal(verify(newToken, { keys: retired, now }).ok, true);
});

test("unknown kid and header tampering fail closed", () => {
  const token = sign({ userId: "u-1", exp: ISS + 3600 }, { key: K1, kid: "k1" });
  const [, body, mac] = token.split(".");
  const foreign = `${b64url(JSON.stringify({ v: 1, kid: "nope" }))}.${body}.${mac}`;
  assert.equal(verify(foreign, { keys: KEYS, now: clockAt(ISS) }).reason, "unknown-key");
  const algConfusion = `${b64url(JSON.stringify({ v: 1, kid: "k1", alg: "none" }))}.${body}.`;
  assert.equal(verify(algConfusion, { keys: KEYS, now: clockAt(ISS) }).ok, false);
});

test("timing-safe comparison is used, not string equality", () => {
  // The library guarantee: crypto.timingSafeEqual exists and rejects unequal
  // lengths; the implementation checks lengths before calling it.
  assert.throws(() => crypto.timingSafeEqual(Buffer.alloc(4), Buffer.alloc(8)), RangeError);
  const token = sign({ userId: "u-1", exp: ISS + 3600 }, { key: K1 });
  const [header, body, mac] = token.split(".");
  const shortSig = `${header}.${body}.${mac.slice(0, 8)}`;
  assert.equal(verify(shortSig, { keys: KEYS, now: clockAt(ISS) }).reason, "bad-signature");
});
@@end

@expect_output
REGEX: # pass 9\n# fail 0
@@end

@notes
Nine node:test cases, all negative-first. Pinned: a valid token round-trips its
payload; editing the payload while keeping the signature is rejected (the exact
attack the review found); a token signed with an unknown key is rejected; the
legacy unsigned base64 JSON — and empty, truncated or non-string values — are
rejected outright; every single byte of the signature is flipped in turn and all 32
mutations must fail, plus a truncated signature must fail without throwing
(length check before timingSafeEqual); expiry is enforced from the signed payload
with a 30s leeway and a missing `exp` is malformed; key rotation keeps old tokens
valid while both keys are published and only invalidates them when `k1` is
retired, with the new token carrying `kid: k2`; an injected `kid` fails closed and
an `alg: none` style header change does not help an attacker because the
algorithm is never read from the token; and `crypto.timingSafeEqual` is asserted to
exist with its length contract, documenting why the code checks lengths first.
@@end

@example py-sec-0004
@meta category=security language=python difficulty=advanced tags=zip-slip,path-traversal,archive-extraction,filesystem

@user
Our upload pipeline accepts zipped bundles and extracts them with `zipfile.extractall()`. A tester just proved they can write a file outside the target directory with an entry named `../../etc/cron.d/pwn`. We are on Python 3.11, so `tarfile.data_filter` (3.12) is not available to us. What is the correct way to extract an untrusted archive, and how do I prove it stays inside the directory?
@@end

@assistant
`extractall()` is unsafe by design: it trusts the names inside the archive. Python 3.12 added `tarfile.data_filter` for tar, but `zipfile` still has no equivalent, so an untrusted archive needs an explicit extractor. There are four distinct attacks to handle, not just `..`:

1. **Path traversal (`../`)** — the classic zip-slip, writing outside the destination.
2. **Absolute paths / drive letters** — `/etc/passwd` or `C:\Windows\...` entries that ignore the destination entirely.
3. **Symlinks and hardlinks** — an entry that *is* a symlink to `/etc`, followed by a second entry written through it. Filtering names alone does not stop this, because the symlink itself is created inside the destination.
4. **Resource exhaustion** — a zip bomb: 10KB of archive that expands to 10TB, or a million tiny entries that exhaust inodes.

The extractor below refuses all four, and — importantly — it *verifies after creating each file* that the final resolved path is still inside the destination. Checking before extraction is not enough when symlinks are involved.

```python
import os
import stat
import zipfile

MAX_ENTRIES = 10_000
MAX_TOTAL_BYTES = 512 * 1024 * 1024          # 512MB of extracted data
MAX_COMPRESSION_RATIO = 200                  # reject obvious zip bombs
CHUNK = 1 << 20


class UnsafeArchive(Exception):
    pass


def _resolve_inside(destination, name):
    """Absolute target path, or raise if the entry escapes the destination."""
    target = os.path.realpath(os.path.join(destination, name))
    root = os.path.realpath(destination)
    if target != root and not target.startswith(root + os.sep):
        raise UnsafeArchive(f"entry {name!r} escapes {destination!r}")
    return target


def _reject_weird_name(name):
    """Windows-style separators and drive letters are ambiguous; refuse them."""
    if "\\" in name or (len(name) > 1 and name[1] == ":"):
        raise UnsafeArchive(f"non-POSIX entry name refused: {name!r}")


def _reject_special(entry):
    mode = entry.external_attr >> 16
    if os.path.islink(entry.filename):
        raise UnsafeArchive(f"symlink entry refused: {entry.filename!r}")
    if stat.S_ISLNK(mode) or stat.S_ISCHR(mode) or stat.S_ISBLK(mode) or stat.S_ISFIFO(mode):
        raise UnsafeArchive(f"non-regular entry refused: {entry.filename!r} (mode {mode:#o})")


def extract_archive(archive_path, destination, *, max_entries=MAX_ENTRIES,
                    max_total_bytes=MAX_TOTAL_BYTES,
                    max_ratio=MAX_COMPRESSION_RATIO):
    """Extract a zip archive of untrusted files into destination. Returns the
    list of extracted regular files."""
    os.makedirs(destination, exist_ok=True)
    written = []
    total = 0
    with zipfile.ZipFile(archive_path) as archive:
        entries = archive.infolist()
        if len(entries) > max_entries:
            raise UnsafeArchive(f"too many entries: {len(entries)}")
        for entry in entries:
            _reject_weird_name(entry.filename)
            if entry.is_dir():
                _resolve_inside(destination, entry.filename)     # validate, do not trust
                continue
            _reject_special(entry)
            target = _resolve_inside(destination, entry.filename)
            if entry.file_size > max_total_bytes - total:
                raise UnsafeArchive("archive exceeds the extraction size budget")
            if entry.compress_size and entry.file_size / entry.compress_size > max_ratio:
                raise UnsafeArchive(f"suspicious compression ratio: {entry.filename!r}")
            os.makedirs(os.path.dirname(target), exist_ok=True)
            # Re-check after creating the parent directories: a path could have
            # been swapped by another process between the two calls.
            _resolve_inside(destination, entry.filename)
            size = 0
            with archive.open(entry) as source, open(target, "wb") as sink:
                while chunk := source.read(CHUNK):
                    size += len(chunk)
                    if size > entry.file_size:
                        raise UnsafeArchive(f"entry {entry.filename!r} larger than declared")
                    sink.write(chunk)
            total += size
            written.append(target)
    return written
```

Rules for the review:

- **`os.path.realpath` on both sides, then compare with a separator.** A naive `target.startswith(root)` accepts `/data/uploads-evil` for a root of `/data/uploads`. The `root + os.sep` form (plus the equality case) is the correct check.
- **Refuse links instead of following them.** Deleting a symlink after extraction is a race; not creating it is not.
- **Cap the *decompressed* size, not the archive size.** The ratio check plus a running total is what stops a zip bomb; `entry.file_size` is attacker-controlled metadata, so the streaming loop enforces the declared size too.
- **Reject names you cannot reason about.** A backslash or a `C:` prefix means the archive came from a client with different path rules; guessing what was meant is how escapes are born. Refuse the entry instead.
- **Never extract into a shared location.** A per-job destination directory with `0o700` keeps a partly extracted archive from being read by another job.
- **Consider a seccomp/chroot boundary for real untrusted input.** Extraction hardening reduces the attack surface; it does not make arbitrary archives safe to parse in-process, since decompression bugs (CVEs in zlib) are a separate class.
@@end

@verify kind=executable language=python
@code
import io
import os
import stat
import tempfile
import zipfile

MAX_ENTRIES = 10_000
MAX_TOTAL_BYTES = 512 * 1024 * 1024
MAX_COMPRESSION_RATIO = 200
CHUNK = 1 << 20


class UnsafeArchive(Exception):
    pass


def _resolve_inside(destination, name):
    target = os.path.realpath(os.path.join(destination, name))
    root = os.path.realpath(destination)
    if target != root and not target.startswith(root + os.sep):
        raise UnsafeArchive(f"entry {name!r} escapes {destination!r}")
    return target


def _reject_weird_name(name):
    if "\\" in name or (len(name) > 1 and name[1] == ":"):
        raise UnsafeArchive(f"non-POSIX entry name refused: {name!r}")


def _reject_special(entry):
    mode = entry.external_attr >> 16
    if os.path.islink(entry.filename):
        raise UnsafeArchive(f"symlink entry refused: {entry.filename!r}")
    if stat.S_ISLNK(mode) or stat.S_ISCHR(mode) or stat.S_ISBLK(mode) or stat.S_ISFIFO(mode):
        raise UnsafeArchive(f"non-regular entry refused: {entry.filename!r} (mode {mode:#o})")


def extract_archive(archive_path, destination, *, max_entries=MAX_ENTRIES,
                    max_total_bytes=MAX_TOTAL_BYTES, max_ratio=MAX_COMPRESSION_RATIO):
    os.makedirs(destination, exist_ok=True)
    written = []
    total = 0
    with zipfile.ZipFile(archive_path) as archive:
        entries = archive.infolist()
        if len(entries) > max_entries:
            raise UnsafeArchive(f"too many entries: {len(entries)}")
        for entry in entries:
            _reject_weird_name(entry.filename)
            if entry.is_dir():
                _resolve_inside(destination, entry.filename)
                continue
            _reject_special(entry)
            target = _resolve_inside(destination, entry.filename)
            if entry.file_size > max_total_bytes - total:
                raise UnsafeArchive("archive exceeds the extraction size budget")
            if entry.compress_size and entry.file_size / entry.compress_size > max_ratio:
                raise UnsafeArchive(f"suspicious compression ratio: {entry.filename!r}")
            os.makedirs(os.path.dirname(target), exist_ok=True)
            _resolve_inside(destination, entry.filename)
            size = 0
            with archive.open(entry) as source, open(target, "wb") as sink:
                while chunk := source.read(CHUNK):
                    size += len(chunk)
                    if size > entry.file_size:
                        raise UnsafeArchive(f"entry {entry.filename!r} larger than declared")
                    sink.write(chunk)
            total += size
            written.append(target)
    return written


def make_zip(path, entries):
    """entries: list of (name, bytes) or (name, None, 'symlink', target)."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for entry in entries:
            if len(entry) == 2:
                archive.writestr(entry[0], entry[1])
            else:
                name, _, kind, target = entry
                info = zipfile.ZipInfo(name)
                if kind == "symlink":
                    info.external_attr = (stat.S_IFLNK | 0o777) << 16
                    archive.writestr(info, target)
                else:
                    raise AssertionError(kind)
    return path


def read(path):
    with open(path, "rb") as handle:
        return handle.read()


with tempfile.TemporaryDirectory() as tmp:
    dest = os.path.join(tmp, "dest")
    outside = os.path.join(tmp, "escaped.txt")

    # 1. A benign bundle extracts normally, including nested directories.
    good = make_zip(os.path.join(tmp, "good.zip"), [
        ("app/index.js", b"console.log(1)"),
        ("app/lib/util.js", b"export const x = 1"),
        ("README.md", b"# bundle"),
    ])
    written = extract_archive(good, dest)
    assert len(written) == 3
    assert read(os.path.join(dest, "app", "index.js")) == b"console.log(1)"
    assert read(os.path.join(dest, "README.md")) == b"# bundle"
    assert os.path.isdir(os.path.join(dest, "app", "lib"))

    # 2. Path traversal is refused, in all the shapes that matter.
    for name in ("../escaped.txt", "app/../../escaped.txt", "./../escaped.txt"):
        bad = make_zip(os.path.join(tmp, "traversal.zip"), [(name, b"pwned")])
        try:
            extract_archive(bad, dest)
            raise AssertionError(f"traversal must be refused: {name}")
        except UnsafeArchive:
            pass
        assert not os.path.exists(outside), "nothing may be written outside dest"

    # 3. Absolute paths and drive-letter style names are refused.
    for name in ("/etc/cron.d/pwn", "C:\\Windows\\pwn.ini", "\\\\server\\share\\pwn"):
        bad = make_zip(os.path.join(tmp, "absolute.zip"), [(name, b"pwned")])
        try:
            extract_archive(bad, dest)
            raise AssertionError(f"absolute path must be refused: {name}")
        except UnsafeArchive:
            pass

    # 4. A symlink entry is refused, and so is a file that would be written
    #    *through* a symlink created inside the destination.
    link_zip = make_zip(os.path.join(tmp, "link.zip"), [("link", None, "symlink", "/etc/passwd")])
    try:
        extract_archive(link_zip, dest)
        raise AssertionError("symlink entries must be refused")
    except UnsafeArchive:
        pass
    assert not os.path.lexists(os.path.join(dest, "link"))

    # Pre-planted symlink inside the destination (an attacker who can write there
    # once) must not become an escape hatch.
    pre_planted = os.path.join(dest, "pre")
    os.symlink("/tmp", pre_planted)
    through_link = make_zip(os.path.join(tmp, "through.zip"), [("pre/oops.txt", b"escaped")])
    try:
        extract_archive(through_link, dest)
        raise AssertionError("writing through a symlink must be refused")
    except UnsafeArchive:
        pass
    os.unlink(pre_planted)
    assert not os.path.exists("/tmp/oops.txt")

    # 5. Zip bomb: a huge declared size is refused before extraction, and a high
    #    compression ratio is refused on its own.
    bomb_path = os.path.join(tmp, "bomb.zip")
    with zipfile.ZipFile(bomb_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("zeros.bin", b"\x00" * (5 << 20))
    try:
        extract_archive(bomb_path, dest, max_total_bytes=1 << 20)
        raise AssertionError("the size budget must be enforced")
    except UnsafeArchive as exc:
        assert "budget" in str(exc), str(exc)
    try:
        extract_archive(bomb_path, dest, max_ratio=2)
        raise AssertionError("the compression ratio must be enforced")
    except UnsafeArchive as exc:
        assert "ratio" in str(exc), str(exc)
    # With limits raised to match the job's own budget the same archive extracts
    # to exactly its declared size: the caps are policy, not corruption.
    extract_archive(bomb_path, dest, max_ratio=10_000)
    assert read(os.path.join(dest, "zeros.bin")) == b"\x00" * (5 << 20)

    # 6. Too many entries is refused without extracting any of them.
    many = os.path.join(tmp, "many.zip")
    with zipfile.ZipFile(many, "w") as archive:
        for i in range(50):
            archive.writestr(f"f{i}.txt", b"x")
    try:
        extract_archive(many, dest, max_entries=10)
        raise AssertionError("the entry cap must be enforced")
    except UnsafeArchive as exc:
        assert "too many entries" in str(exc), str(exc)
    assert not os.path.exists(os.path.join(dest, "f0.txt"))

    # 7. A close-but-not-inside sibling directory must not be accepted: the
    #    naive startswith(root) check would let /tmp/.../dest-evil through.
    evil = dest + "-evil"
    os.makedirs(evil, exist_ok=True)
    sibling = make_zip(os.path.join(tmp, "sibling.zip"), [("escape.txt", b"x")])
    assert os.path.commonpath([dest, evil]) == os.path.dirname(dest)
    try:
        _resolve_inside(dest, os.path.join("..", os.path.basename(evil), "escape.txt"))
        raise AssertionError("a sibling directory is still outside the destination")
    except UnsafeArchive:
        pass
    written = extract_archive(sibling, dest)
    assert written and all(path.startswith(os.path.realpath(dest) + os.sep) for path in written)

    # 8. Nested directories are created with the resolved path inside the root.
    nested = make_zip(os.path.join(tmp, "nested.zip"), [("a/b/c/d/e.txt", b"deep")])
    written = extract_archive(nested, dest)
    assert read(os.path.join(dest, "a", "b", "c", "d", "e.txt")) == b"deep"
    assert all(os.path.isfile(path) for path in written)
print("PASS")
@@end

@expect_output
PASS
@@end

@notes
Eight cases against real zip files on disk, covering the four attack classes named
in the answer. Pinned: a benign nested bundle extracts and the extracted paths are
returned; three traversal spellings (`../x`, `a/../../x`, `./../x`) are refused and
nothing appears outside the destination; absolute POSIX names are refused and
Windows-style names (`C:\\Windows\\pwn.ini`, `\\\\server\\share\\pwn`) are refused as
non-POSIX rather than guessed at; symlink entries are refused and not created; a *pre-planted* symlink
inside the destination cannot be used to write outside it (the realpath check
resolves the link and refuses), which is why the extractor validates paths rather
than only names; a 5MB zip bomb is caught by both the total-size budget and the
compression-ratio cap, while extracting fine with sane limits; the entry cap is
enforced before anything is written; a sibling directory named like the
destination cannot be reached (`dest-evil` is still outside `dest`, whereas a naive
`startswith(root)` check would allow it); and deeply nested archive paths resolve
inside the root.
@@end
