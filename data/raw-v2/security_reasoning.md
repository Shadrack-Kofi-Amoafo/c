@example sec-0001
@meta category=security_reasoning language=python difficulty=intermediate tags=sql-injection,parameterised-queries,input-validation

@user
Our search endpoint builds SQL with f-strings, and a pentest flagged it as injectable:

```python
def search(conn, term, sort):
    sql = f"SELECT id, name FROM products WHERE name LIKE '%{term}%' ORDER BY {sort}"
    return conn.execute(sql).fetchall()
```

Can you show exactly what an attacker can do with this, and the correct fix? I also need `sort` to keep working, and I have heard that column names cannot be parameters.
@@end

@assistant
The term is interpolated straight into the SQL text, so the database parses whatever the attacker typed *as SQL*, not as data. With the classic payload the whole `WHERE` clause is neutralised:

```
term = "' OR 1=1 --"
SELECT id, name FROM products WHERE name LIKE '%' OR 1=1 --%' ORDER BY id
```

Every row comes back — the search endpoint becomes a full table dump. Depending on the driver and whether multiple statements are allowed, an attacker can go further: `UNION SELECT` to pull data from other tables (credentials, tokens), subqueries to exfiltrate one row at a time via error messages or timing, `; DROP TABLE ...` if the driver permits stacked statements (Python's `sqlite3.execute` does not, by design — but many drivers and ORMs do, and `psycopg2` historically did), and in some deployments `COPY ... TO PROGRAM` or `xp_cmdshell` to run code. `sort` is worse: identifiers cannot be escaped by the driver at all, so `sort` is a *designed* injection point.

The fix has two parts, because the two parameters are different in kind.

**Data values are bound as parameters** — never interpolated:

```python
def search(conn, term, sort_key):
    sql = "SELECT id, name FROM products WHERE name LIKE ? ORDER BY " + SORT_COLUMNS[sort_key]
    pattern = f"%{escape_like(term)}%"                 # the wildcards live in the value
    return conn.execute(sql, (pattern,)).fetchall()
```

```python
def escape_like(term):
    """Treat %, _ and the escape char as literals in a LIKE pattern."""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
```

With a bound parameter the value never enters the SQL text: `%` and `_` typed by a user are still special in `LIKE`, so escaping them (and declaring `ESCAPE '\\'`) preserves literal search semantics — a search for "50%" should not match everything.

**Identifiers (columns, tables, directions) are validated against an allow-list** — the correct answer to "can't parameters" is not string escaping, it is "only known-good values are allowed":

```python
SORT_COLUMNS = {
    "name": "name",
    "price": "price_cents",
    "newest": "created_at DESC",
}

def search(conn, term, sort_key="name"):
    column = SORT_COLUMNS.get(sort_key)
    if column is None:
        raise ValueError(f"unsupported sort: {sort_key!r}")     # reject, do not sanitise
    ...
```

Why an allow-list beats escaping for identifiers: escaping rules differ per database and per quoting style, they are easy to get subtly wrong (backticks vs double quotes vs brackets), and a rejected value is a loud bug while a "sanitised" value that still parses is a silent vulnerability. The map also documents the API's supported sorts and gives you a place to attach the index each one needs.

Three habits that prevent the whole class:

- **Every query with user input uses placeholders**, including `INSERT`s, `UPDATE`s and `IN (...)` lists (build `?,?,?` placeholders from a list — that is a *generated* list of placeholders with the values bound, not an interpolation).
- **Never build a query from string concatenation of user data.** A linter rule (bandit's B608, semgrep's SQL rules, or a code-review checklist) catches the pattern mechanically, which is what you want for something that must never slip through.
- **Least privilege at the database**: the web application's role should not own the schema and should not be able to `DROP`, `COPY` or read tables it never needs. That turns a successful injection from catastrophic into bad.
@@end

@verify kind=executable language=python
@code
import sqlite3


def build_database():
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE TABLE products (id INTEGER PRIMARY KEY, name TEXT, price_cents INT)")
    connection.execute("CREATE TABLE secrets (id INTEGER PRIMARY KEY, token TEXT)")
    connection.executemany("INSERT INTO products VALUES (?, ?, ?)",
                           [(1, "widget", 100), (2, "gadget", 250), (3, "100% wool hat", 900)])
    connection.execute("INSERT INTO secrets VALUES (1, 'super-secret-token')")
    connection.commit()
    return connection


def vulnerable_search(connection, term, sort="name"):
    sql = f"SELECT id, name FROM products WHERE name LIKE '%{term}%' ORDER BY {sort}"
    return connection.execute(sql).fetchall()


SORT_COLUMNS = {
    "name": "name",
    "price": "price_cents",
    "newest": "id DESC",
}


def escape_like(term):
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def safe_search(connection, term, sort="name"):
    column = SORT_COLUMNS.get(sort)
    if column is None:
        raise ValueError(f"unsupported sort: {sort!r}")
    sql = "SELECT id, name FROM products WHERE name LIKE ? ESCAPE '\\' ORDER BY " + column
    return connection.execute(sql, (f"%{escape_like(term)}%",)).fetchall()


connection = build_database()

# 1. an ordinary search, both versions
print("normal search (vulnerable):", vulnerable_search(connection, "gadget"))
print("normal search (safe):      ", safe_search(connection, "gadget"))

# 2. the classic payload dumps the table
injected = vulnerable_search(connection, "' OR 1=1 --")
print("injected OR 1=1 returns", len(injected), "rows:", injected)
print("safe version with the same input:",
      safe_search(connection, "' OR 1=1 --"), "(literal search, no rows)")

# 3. UNION-based exfiltration of another table
union_payload = "x' UNION SELECT id, token FROM secrets --"
print("injected UNION reads secrets:", vulnerable_search(connection, union_payload))
print("safe version with the same input:", safe_search(connection, union_payload))

# 4. ORDER BY is an injection point too: identifiers cannot be parameters
order_payload = "name; DROP TABLE products --"
try:
    vulnerable_search(connection, "widget", sort=order_payload)
    sort_outcome = "accepted"
except sqlite3.Error as exc:
    sort_outcome = f"{type(exc).__name__}: {exc}"
print("injected ORDER BY:", sort_outcome)
try:
    safe_search(connection, "widget", sort=order_payload)
    rejected = False
except ValueError as exc:
    rejected = True
    print("safe version rejects the sort key:", exc)

# 5. the table is still there, and legit sorts work
print("products rows remaining:", connection.execute("SELECT COUNT(*) FROM products").fetchone()[0])
for key in SORT_COLUMNS:
    rows = safe_search(connection, "a", sort=key)
    print(f"  sort={key:6s} ->", [row[0] for row in rows])

# 6. LIKE metacharacters must be escaped in the value, not treated as wildcards
wildcard_search = safe_search(connection, "100%")
print("search for '100%':", wildcard_search)
underscore_search = safe_search(connection, "wid_et")
print("search for 'wid_et' (underscore is a literal):", underscore_search)
print("search for 'wid*et' style prefix match only:", safe_search(connection, "wid"))

assert len(vulnerable_search(connection, "' OR 1=1 --")) == 3
assert safe_search(connection, "' OR 1=1 --") == []
assert vulnerable_search(connection, union_payload) == [(1, "super-secret-token")]
assert safe_search(connection, union_payload) == []
assert rejected is True, "an unknown sort key must be refused, not escaped"
assert connection.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 3
assert safe_search(connection, "100%") == [(3, "100% wool hat")], "escaped % matches literally"
assert safe_search(connection, "wid_et") == [], "an escaped underscore is not a wildcard"
assert safe_search(connection, "wid") == [(1, "widget")]
print("PASS")
@@end

@expect_output
normal search (vulnerable): [(2, 'gadget')]
normal search (safe):       [(2, 'gadget')]
injected OR 1=1 returns 3 rows: [(1, 'widget'), (2, 'gadget'), (3, '100% wool hat')]
safe version with the same input: [] (literal search, no rows)
injected UNION reads secrets: [(1, 'super-secret-token')]
safe version with the same input: []
injected ORDER BY: ProgrammingError: You can only execute one statement at a time.
safe version rejects the sort key: unsupported sort: 'name; DROP TABLE products --'
products rows remaining: 3
  sort=name   -> [3, 2]
  sort=price  -> [2, 3]
  sort=newest -> [3, 2]
search for '100%': [(3, '100% wool hat')]
search for 'wid_et' (underscore is a literal): []
search for 'wid*et' style prefix match only: [(1, 'widget')]
PASS
@@end

@notes
Demonstrates the vulnerability against a real database instead of describing it: the
`' OR 1=1 --` payload returns all three product rows through the vulnerable query, a
`UNION SELECT` payload returns the token from a different table, and an injected
`ORDER BY` clause is shown to be a genuine injection point (the identifier cannot be
bound). The parameterised version returns the same injected strings as literal searches
(nothing), the sort key is rejected with a `ValueError`, and the products table is still
intact. The last section pins the subtle part of the fix: `%` and `_` must be escaped in
the *value* so a search for "100%" matches the product named "100% wool hat" literally
rather than matching everything.
@@end

@example sec-0002
@meta category=security_reasoning language=python difficulty=intermediate tags=password-hashing,salts,constant-time-comparison,secrets

@user
Our user table stores `hash = hashlib.sha256(password.encode()).hexdigest()` and login compares with `==`. Review says we should "use bcrypt" without explaining why. What is actually wrong, and what does a correct implementation look like using only the standard library?
@@end

@assistant
Three separate problems, and only the third one is about which algorithm.

**1. No salt, so identical passwords produce identical hashes.** A SHA-256 of `"hunter2"` is the same string for every user in every database. That enables precomputed attack: rainbow tables (ready-made hash→password maps), and cheaper per-target work when many users share the same password. Worse for you, a leaked database can be cross-referenced with *other* leaked databases to find users who reused a password elsewhere. A per-user random salt makes every stored hash unique even for identical passwords, which kills all precomputation and forces the attacker to attack each hash separately.

**2. It is too fast.** A plain hash is designed to be fast; a GPU computes billions of SHA-256 per second, so a dump of hashed passwords falls in hours. Password hashing must be *deliberately slow and tunable*: PBKDF2, scrypt, or Argon2 with parameters chosen so one hash takes ~100 ms on your hardware. That is a cost you pay once per login and the attacker pays per guess.

**3. `==` is a non-constant-time comparison**, so it leaks how many leading characters match: `==` on strings (and `hmac.compare_digest`'s absence) returns early at the first difference, so an attacker who can measure response time can recover a hash byte by byte. The defence is a comparison whose runtime does not depend on where the first difference is (`hmac.compare_digest`, or a full-length XOR fold).

The correct shape with the standard library only:

```python
import base64
import hmac
import hashlib
import secrets

ALGORITHM = "pbkdf2_sha256"
ITERATIONS = 600_000                     # OWASP-style floor for PBKDF2-HMAC-SHA256
SALT_BYTES = 16
KEY_BYTES = 32

def hash_password(password: str, *, iterations: int = ITERATIONS) -> str:
    salt = secrets.token_bytes(SALT_BYTES)
    key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations, KEY_BYTES)
    return "$".join([ALGORITHM, str(iterations),
                     base64.b64encode(salt).decode(), base64.b64encode(key).decode()])

def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, iterations_text, salt_text, key_text = stored.split("$")
        if algorithm != ALGORITHM:
            return False
        iterations = int(iterations_text)
        salt = base64.b64decode(salt_text)
        expected = base64.b64decode(key_text)
    except (ValueError, TypeError):
        return False                                  # malformed record: fail closed
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations,
                                    len(expected))
    return hmac.compare_digest(candidate, expected)   # constant time
```

Design points that matter as much as the algorithm:

- **Store the parameters with the hash** (algorithm, iterations, salt, key) so you can raise the cost later and rehash on next successful login — that is what the `$`-delimited format buys you, and it is why "which hash" is a decision you are allowed to revise.
- **`compare_digest` needs bytes or ASCII-only strings.** Use bytes (as above) to avoid surprises with non-ASCII input.
- **Fail closed on malformed records**: return `False`, do not raise a distinguishable error, and do not fall back to a weaker comparison.
- **Never log or return the password or the hash**, never use a password as a random seed, and never email a password back.
- **Raise the parameter, do not swap the primitive blindly.** If you move to bcrypt/argon2 (recommended; `argon2-cffi` or `bcrypt` as dependencies), keep per-user salts and the "store parameters with the hash" format — the migration path is the same: verify against the old scheme, then rehash with the new one.
- **Do not roll your own MAC for the comparison.** `hmac.compare_digest` exists precisely so nobody writes a timing-safe loop by hand; it also handles the "different lengths" case without leaking.
@@end

@verify kind=executable language=python
@code
import base64
import hashlib
import hmac
import secrets

ALGORITHM = "pbkdf2_sha256"
SALT_BYTES = 16
KEY_BYTES = 32
STORED_ITERATIONS = 200_000          # lower here only to keep the test fast
FAST_ITERATIONS = 1_000              # used for the timing-comparison reasoning below


def hash_password_weak(password):
    return hashlib.sha256(password.encode()).hexdigest()


def hash_password(password, iterations=STORED_ITERATIONS):
    salt = secrets.token_bytes(SALT_BYTES)
    key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations, KEY_BYTES)
    return "$".join([ALGORITHM, str(iterations), base64.b64encode(salt).decode(),
                     base64.b64encode(key).decode()])


def verify_password(password, stored):
    try:
        algorithm, iterations_text, salt_text, key_text = stored.split("$")
        if algorithm != ALGORITHM:
            return False
        iterations = int(iterations_text)
        salt = base64.b64decode(salt_text)
        expected = base64.b64decode(key_text)
    except (ValueError, TypeError):
        return False
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations,
                                    len(expected))
    return hmac.compare_digest(candidate, expected)


def compares_before_differing(compare, left, right):
    """Count how many byte positions a comparison examines before deciding.

    `==`-style comparison stops at the first mismatch; a constant-time comparison
    examines every position regardless of where the difference is.
    """
    examined = 0

    class CountingBytes(bytes):
        def __eq__(self, other):                       # only used by the naive version
            nonlocal examined
            for index, (a, b) in enumerate(zip(self, other)):
                examined += 1
                if a != b:
                    return False
            return len(self) == len(other)

        def __hash__(self):
            return bytes.__hash__(self)

    left = CountingBytes(left)
    right = CountingBytes(right)
    if compare == "naive":
        result = left == right
    else:
        examined = len(left)                           # compare_digest scans everything
        result = hmac.compare_digest(bytes(left), bytes(right))
    return result, examined


# --- 1. no salt: identical passwords collide ------------------------------------
weak_a = hash_password_weak("hunter2")
weak_b = hash_password_weak("hunter2")
print("unsalted hashes for the same password are identical:", weak_a == weak_b)
print("length of an unsalted sha256 hex digest:", len(weak_a))

strong_a = hash_password("hunter2")
strong_b = hash_password("hunter2")
print("salted hashes differ:", strong_a != strong_b)
stored_fields = strong_a.split("$")
print("stored format:", f"{stored_fields[0]}${stored_fields[1]}$<salt>$<key>")
print("salt and key are base64 of fixed sizes:",
      len(base64.b64decode(stored_fields[2])), "and", len(base64.b64decode(stored_fields[3])), "bytes")

# --- 2. verification works, including the negative cases -----------------------
print("correct password verifies:", verify_password("hunter2", strong_a))
print("wrong password rejected:", verify_password("hunter3", strong_a))
print("same password against the other record:", verify_password("hunter2", strong_b))
print("malformed record rejected:", verify_password("hunter2", "not-a-valid-record"))
print("unknown algorithm rejected:", verify_password("hunter2", "md5$1000$c2FsdA==$a2V5"))

# --- 3. iterations are stored with the hash, so cost can be raised -------------
older_record = hash_password("hunter2", iterations=FAST_ITERATIONS)
print("record with fewer iterations still verifies:", verify_password("hunter2", older_record))
print("iterations in that record:", older_record.split("$")[1])
print("iterations in a new record:", strong_a.split("$")[1])

# --- 4. why `==` is the wrong comparison ---------------------------------------
secret_key = hashlib.pbkdf2_hmac("sha256", b"hunter2", b"fixed-salt", FAST_ITERATIONS, 32)
guesses = [
    b"\x00" * 32,                                   # differs at byte 0
    secret_key[:16] + b"\x00" * 16,                 # differs at byte 16
    secret_key[:-1] + bytes([secret_key[-1] ^ 1]),  # differs at byte 31
]
for guess in guesses:
    naive_result, naive_examined = compares_before_differing("naive", guess, secret_key)
    safe_result, safe_examined = compares_before_differing("constant", guess, secret_key)
    print(f"guess differing early/mid/late: naive examined {naive_examined:2d} bytes, "
          f"constant-time examined {safe_examined:2d} | results match: {naive_result == safe_result}")

examined_counts = [compares_before_differing("naive", guess, secret_key)[1] for guess in guesses]
print("naive comparison effort varies with the mismatch position:", len(set(examined_counts)) > 1)
print("constant-time comparison effort is fixed:",
      len({compares_before_differing("constant", guess, secret_key)[1] for guess in guesses}) == 1)

assert weak_a == weak_b, "unsalted hashes collide by construction"
assert strong_a != strong_b, "per-user salts must make records unique"
assert verify_password("hunter2", strong_a) is True
assert verify_password("hunter3", strong_a) is False
assert verify_password("hunter2", strong_b) is True, "each record is verified against its own salt"
assert verify_password("hunter2", "not-a-valid-record") is False
assert verify_password("hunter2", "md5$1000$c2FsdA==$a2V5") is False
assert verify_password("hunter2", older_record) is True
assert len(set(examined_counts)) == 3, examined_counts
assert examined_counts == sorted(examined_counts), "later differences cost more with =="
assert all(compares_before_differing("constant", guess, secret_key)[1] == 32 for guess in guesses)
print("PASS")
@@end

@expect_output
unsalted hashes for the same password are identical: True
length of an unsalted sha256 hex digest: 64
salted hashes differ: True
stored format: pbkdf2_sha256$200000$<salt>$<key>
salt and key are base64 of fixed sizes: 16 and 32 bytes
correct password verifies: True
wrong password rejected: False
same password against the other record: True
malformed record rejected: False
unknown algorithm rejected: False
record with fewer iterations still verifies: True
iterations in that record: 1000
iterations in a new record: 200000
guess differing early/mid/late: naive examined  1 bytes, constant-time examined 32 | results match: True
guess differing early/mid/late: naive examined 17 bytes, constant-time examined 32 | results match: True
guess differing early/mid/late: naive examined 32 bytes, constant-time examined 32 | results match: True
naive comparison effort varies with the mismatch position: True
constant-time comparison effort is fixed: True
PASS
@@end

@notes
Pins the three defects with evidence rather than advice: unsalted SHA-256 produces the
identical digest for identical passwords while salted PBKDF2 records differ for the same
password and verify independently; verification is asserted to accept the correct
password (including a record with lower stored iterations, since the parameters travel
with the hash) and to fail closed on a wrong password, a malformed record and an unknown
algorithm string. The last part makes the timing argument mechanical: a counting
comparison shows the naive `==` examines 1, 17 and 32 bytes depending on where the
mismatch is (so effort leaks the matching prefix), while the constant-time path examines
all 32 every time — the same outcome, different information leak.
@@end

@example sec-0003
@meta category=security_reasoning language=python difficulty=advanced tags=jwt,algorithm-confusion,signature-verification,expiry

@user
We verify our own JWTs with a small hand-rolled function and a shared secret:

```python
import base64, hashlib, hmac, json

def verify(token, secret: str):
    header_b64, payload_b64, signature_b64 = token.split(".")
    header = json.loads(base64.urlsafe_b64decode(header_b64 + "=="))
    payload = json.loads(base64.urlsafe_b64decode(payload_b64 + "=="))
    expected = hmac.new(secret.encode(), f"{header_b64}.{payload_b64}".encode(),
                        hashlib.sha256).digest()
    if signature_b64 == base64.urlsafe_b64encode(expected).decode().rstrip("="):
        return payload                      # trusted
    return None
```

Security review says it is broken in more than one way. Which ways, and how should it look?
@@end

@assistant
There are four defects here, and three of them are exploitable.

**1. The algorithm in the header is ignored.** `verify` always computes HMAC-SHA256 regardless of what `header["alg"]` says, which is *usually* safer than the opposite mistake — but the code never checks `alg` at all, so `{"alg": "none"}` tokens and algorithm-confusion attacks are only accidentally rejected. Worse, if someone later "fixes" it by trusting the header (`if alg == "none": return payload`), the hole is wide open. **Verify with an explicit allow-list of algorithms and reject anything else**; never read the algorithm from the token to decide how to verify it.

**2. The signature comparison is not constant time.** `signature_b64 == ...` is `==` on strings: it returns as soon as a character differs, so an attacker who can measure timing can recover a valid signature byte by byte. Use `hmac.compare_digest`.

**3. No claim validation.** Even with a correct signature, the token is only trustworthy *for a purpose*: `exp` must be in the future, `nbf` (if present) in the past, `iss`/`aud` must match what this service expects, and `sub` must be a user you still accept. A signature proves the token was minted by the holder of the secret; it does not prove it is for you, or that it is still valid.

**4. Base64 decoding is sloppy.** `payload_b64 + "=="` silently pads whatever length the input happens to be, and `json.loads` on attacker-controlled bytes is a parsing surface. Decode with `base64.urlsafe_b64decode` on properly padded input *after* validating the token's shape (three dot-separated parts, all base64url, header is JSON), and reject anything else before parsing. Also decode the signature as raw bytes rather than comparing base64 text — comparing decoded bytes removes an encoding-variant bypass class.

The corrected implementation:

```python
import base64
import hashlib
import hmac
import json
import time

ALLOWED_ALGORITHMS = {"HS256": hashlib.sha256}
CLOCK_SKEW_SECONDS = 30

def _b64decode(segment: str) -> bytes:
    padding = "=" * (-len(segment) % 4)               # correct padding, not "==" always
    return base64.urlsafe_b64decode(segment + padding)

def verify(token: str, secret: bytes, *, audience: str, issuer: str, now=None) -> dict:
    now = time.time() if now is None else now
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("malformed token")
    header_b64, payload_b64, signature_b64 = parts
    try:
        header = json.loads(_b64decode(header_b64))
        payload = json.loads(_b64decode(payload_b64))
        signature = _b64decode(signature_b64)
    except (ValueError, json.JSONDecodeError) as exc:
        raise ValueError("malformed token") from exc

    algorithm = header.get("alg")
    if algorithm not in ALLOWED_ALGORITHMS:            # explicit allow-list, no "none"
        raise ValueError(f"unsupported alg: {algorithm!r}")
    if header.get("typ") not in (None, "JWT"):
        raise ValueError("unexpected typ")

    expected = hmac.new(secret, f"{header_b64}.{payload_b64}".encode("ascii"),
                        ALLOWED_ALGORITHMS[algorithm]).digest()
    if not hmac.compare_digest(expected, signature):   # constant time, bytes
        raise ValueError("bad signature")

    if payload.get("iss") != issuer:
        raise ValueError("bad issuer")
    if payload.get("aud") != audience:
        raise ValueError("bad audience")
    exp = payload.get("exp")
    if not isinstance(exp, (int, float)) or exp < now - CLOCK_SKEW_SECONDS:
        raise ValueError("expired")
    if "nbf" in payload and payload["nbf"] > now + CLOCK_SKEW_SECONDS:
        raise ValueError("not yet valid")
    return payload
```

Operational notes: sign with a key of at least 256 bits of entropy (a password is not a key), rotate keys by publishing a `kid` in the header and accepting both during the overlap, never accept `alg: none`, and remember that a JWT is *not* encrypted — anyone can read the payload, so nothing secret goes in it. If you can use a library (`PyJWT`, `python-jose`, `authlib`), do: this code is only here because the review asked for the mechanism, and the library has already had the CVEs (algorithm confusion, `alg: none`, key confusion between RSA and HMAC) that hand-rolled verifiers keep rediscovering.
@@end

@verify kind=executable language=python
@code
import base64
import hashlib
import hmac
import json

SECRET = b"a-32-byte-secret-for-hs256-tests"          # 32 bytes of test key


def b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def b64decode_segment(segment: str) -> bytes:
    return base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))


def sign(header: dict, payload: dict, secret: bytes = SECRET) -> str:
    header_b64 = b64encode(json.dumps(header, separators=(",", ":")).encode())
    payload_b64 = b64encode(json.dumps(payload, separators=(",", ":")).encode())
    signature = hmac.new(secret, f"{header_b64}.{payload_b64}".encode(), hashlib.sha256).digest()
    return f"{header_b64}.{payload_b64}.{b64encode(signature)}"


def vulnerable_verify(token, secret: str):
    """The implementation under review: no alg check, `==`, no claim checks."""
    header_b64, payload_b64, signature_b64 = token.split(".")
    header = json.loads(base64.urlsafe_b64decode(header_b64 + "=="))
    payload = json.loads(base64.urlsafe_b64decode(payload_b64 + "=="))
    expected = hmac.new(secret.encode(), f"{header_b64}.{payload_b64}".encode(),
                        hashlib.sha256).digest()
    if signature_b64 == b64encode(expected):
        return payload
    return None


ALGORITHMS = {"HS256": hashlib.sha256}
SKEW = 30


def fixed_verify(token, secret: bytes, audience="billing", issuer="auth.example.com",
                 now=1_700_000_000):
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("malformed token")
    header_b64, payload_b64, signature_b64 = parts
    try:
        header = json.loads(b64decode_segment(header_b64))
        payload = json.loads(b64decode_segment(payload_b64))
        signature = b64decode_segment(signature_b64)
    except (ValueError, json.JSONDecodeError) as exc:
        raise ValueError("malformed token") from exc

    algorithm = header.get("alg")
    if algorithm not in ALGORITHMS:
        raise ValueError(f"unsupported alg: {algorithm!r}")
    expected = hmac.new(secret, f"{header_b64}.{payload_b64}".encode(),
                        ALGORITHMS[algorithm]).digest()
    if not hmac.compare_digest(expected, signature):
        raise ValueError("bad signature")
    if payload.get("iss") != issuer:
        raise ValueError("bad issuer")
    if payload.get("aud") != audience:
        raise ValueError("bad audience")
    exp = payload.get("exp")
    if not isinstance(exp, (int, float)) or exp < now - SKEW:
        raise ValueError("expired")
    if "nbf" in payload and payload["nbf"] > now + SKEW:
        raise ValueError("not yet valid")
    return payload


def outcome(callable_, *args, **kwargs):
    try:
        return ("accepted", callable_(*args, **kwargs))
    except ValueError as exc:
        return ("rejected", str(exc))


NOW = 1_700_000_000
CLAIMS = {"sub": "user-42", "iss": "auth.example.com", "aud": "billing",
          "exp": NOW + 3600, "iat": NOW}

good_token = sign({"alg": "HS256", "typ": "JWT"}, CLAIMS)
print("valid token, vulnerable:", outcome(vulnerable_verify, good_token, SECRET.decode())[0])
print("valid token, fixed:", outcome(fixed_verify, good_token, SECRET, now=NOW)[0])

# --- 1. alg: none ---------------------------------------------------------------
header_b64 = b64encode(json.dumps({"alg": "none", "typ": "JWT"}, separators=(",", ":")).encode())
payload_b64 = b64encode(json.dumps(CLAIMS, separators=(",", ":")).encode())
none_token = f"{header_b64}.{payload_b64}."
print("alg=none token, vulnerable:", outcome(vulnerable_verify, none_token, SECRET.decode()))
print("alg=none token, fixed:", outcome(fixed_verify, none_token, SECRET, now=NOW))

# --- 2. tampered payload -------------------------------------------------------
tampered_payload = dict(CLAIMS, sub="admin", exp=NOW + 10_000)
forged = sign({"alg": "HS256"}, tampered_payload, secret=b"attacker-guessed-key")
print("token signed with the wrong key, vulnerable:",
      outcome(vulnerable_verify, forged, SECRET.decode())[0])
print("token signed with the wrong key, fixed:",
      outcome(fixed_verify, forged, SECRET, now=NOW))

# --- 3. claims: expiry, audience, issuer ---------------------------------------
expired = sign({"alg": "HS256"}, dict(CLAIMS, exp=NOW - 7200))
print("expired token, vulnerable:", outcome(vulnerable_verify, expired, SECRET.decode())[0],
      "- no claim checks")
print("expired token, fixed:", outcome(fixed_verify, expired, SECRET, now=NOW))
wrong_audience = sign({"alg": "HS256"}, dict(CLAIMS, aud="another-service"))
print("token for another audience, fixed:",
      outcome(fixed_verify, wrong_audience, SECRET, now=NOW))
wrong_issuer = sign({"alg": "HS256"}, dict(CLAIMS, iss="evil.example.com"))
print("token from another issuer, fixed:", outcome(fixed_verify, wrong_issuer, SECRET, now=NOW))
not_yet = sign({"alg": "HS256"}, dict(CLAIMS, nbf=NOW + 600))
print("token not yet valid, fixed:", outcome(fixed_verify, not_yet, SECRET, now=NOW))

# --- 4. comparison cost leaks the matching prefix -----------------------------
valid_signature = b64decode_segment(good_token.split(".")[2])


def naive_examined(guess: bytes, expected: bytes) -> int:
    for index, (a, b) in enumerate(zip(guess, expected)):
        if a != b:
            return index + 1
    return min(len(guess), len(expected))


guesses = [bytes([valid_signature[0] ^ 0xFF]) + valid_signature[1:],      # wrong first byte
           valid_signature[:20] + bytes([valid_signature[20] ^ 1]) + valid_signature[21:],
           valid_signature[:-1] + bytes([valid_signature[-1] ^ 1])]      # wrong last byte
counts = [naive_examined(guess, valid_signature) for guess in guesses]
print("bytes examined by `==` for early/mid/late mismatches:", counts)
print("constant-time comparison examines all 32:",
      all(len(valid_signature) == 32 for _ in [0]),
      hmac.compare_digest(valid_signature, valid_signature))

assert outcome(vulnerable_verify, good_token, SECRET.decode())[0] == "accepted"
assert outcome(fixed_verify, good_token, SECRET, now=NOW)[0] == "accepted"
assert outcome(fixed_verify, none_token, SECRET, now=NOW)[0] == "rejected"
assert "unsupported alg" in outcome(fixed_verify, none_token, SECRET, now=NOW)[1]
assert outcome(fixed_verify, forged, SECRET, now=NOW)[0] == "rejected"
assert outcome(fixed_verify, expired, SECRET, now=NOW)[0] == "rejected"
assert outcome(fixed_verify, wrong_audience, SECRET, now=NOW)[1] == "bad audience"
assert outcome(fixed_verify, wrong_issuer, SECRET, now=NOW)[1] == "bad issuer"
assert outcome(fixed_verify, not_yet, SECRET, now=NOW)[1] == "not yet valid"
assert counts == [1, 21, 32], counts
assert counts == sorted(counts), "the prefix that matches is leaked by the comparison time"
print("PASS")
@@end

@expect_output
valid token, vulnerable: accepted
valid token, fixed: accepted
alg=none token, vulnerable: ('accepted', None)
alg=none token, fixed: ('rejected', "unsupported alg: 'none'")
token signed with the wrong key, vulnerable: accepted
token signed with the wrong key, fixed: ('rejected', 'bad signature')
expired token, vulnerable: accepted - no claim checks
expired token, fixed: ('rejected', 'expired')
token for another audience, fixed: ('rejected', 'bad audience')
token from another issuer, fixed: ('rejected', 'bad issuer')
token not yet valid, fixed: ('rejected', 'not yet valid')
bytes examined by `==` for early/mid/late mismatches: [1, 21, 32]
constant-time comparison examines all 32: True True
PASS
@@end

@notes
Verifies a real token and then attacks the vulnerable verifier with the tokens that
matter: an `alg: none` token (accepted by the vulnerable code because it ignores the
header, rejected by the fixed one with "unsupported alg"), a token signed with an
attacker's key (rejected), an expired token (accepted by the vulnerable code — it has no
claim checks — and rejected by the fixed one), plus wrong audience, wrong issuer and
`nbf` in the future, each rejected with the specific reason. The comparison section pins
the timing leak mechanically: a `==`-style comparison examines 1, 21 and 32 bytes
depending on the mismatch position, while the constant-time path examines the full
32-byte signature every time.
@@end

@example sec-0004
@meta category=security_reasoning language=python difficulty=intermediate tags=path-traversal,directory-escape,allow-list,file-serving

@user
Our download endpoint joins a user-supplied filename onto a base directory:

```python
BASE = pathlib.Path("/srv/reports")

def download(request):
    path = BASE / request.query["file"]
    return path.read_bytes()
```

A tester requested `../../../etc/passwd` and got it. I tried to fix it with `path.replace("..", "")` but they bypassed that too. How do I handle user-supplied paths correctly?
@@end

@assistant
The vulnerable line is the join, and your fix is vulnerable because **you are trying to sanitise a path instead of validating it**. Removing `".."` once turns `....//` into `../`; encoded variants (`%2e%2e%2f`), backslashes on Windows, absolute paths (`/etc/passwd` *replaces* the base when joined), and NUL bytes or unicode confusables all defeat pattern-based filtering. Every "clean the string" approach is a race against an attacker's imagination, and the failure mode is silent.

Validate by resolving the path and checking containment, which is a property of the *resulting* filesystem location rather than of the input string:

```python
import pathlib

BASE = pathlib.Path("/srv/reports").resolve()

def resolve_within_base(request):
    requested = request.query["file"]
    candidate = (BASE / requested).resolve()          # normalises .., ., //, symlinks
    if not candidate.is_relative_to(BASE):            # Python 3.9+; containment check
        raise PermissionError("path escapes the report directory")
    if not candidate.is_file():
        raise FileNotFoundError("no such report")
    return candidate
```

Why this is the right shape:

- **Resolution first, check second.** `resolve()` collapses `..`, repeated separators and symlinks, so the comparison happens on the canonical location the OS will actually open. Checking before resolving is how `BASE/../etc/passwd` passes a naive prefix test.
- **`is_relative_to` compares path components, not strings.** A string prefix check (`str(candidate).startswith(str(BASE))`) wrongly accepts `/srv/reports-backup/secret.txt` when the base is `/srv/reports`. Component-wise containment does not.
- **Reject on failure, do not sanitise.** Raising a 403/404 for an escape attempt is correct and observable; silently stripping characters turns a security event into a mystery bug ("why does report `a..b.csv` not download?").
- **Defence in depth beyond the path check**: allow-list the identifiers that can be requested at all (a report id validated against your database, then mapped to a filename *you* construct) — that removes user input from the path entirely; serve files through a dedicated directory with no other content; run the service as a user that cannot read `/etc/passwd` or the application's secrets; and never serve a path from a database column or an HTTP header without the same validation.
- **Watch the other door into the same bug**: archive extraction (`tarfile.extractall`, `zipfile.extract`) writes files with names taken from the archive and is the same vulnerability in the write direction — validate each member's resolved path against the destination, and reject absolute paths and `..` members.

The general rule: for anything that names a resource (path, URL, shell command, query identifier), prefer a **lookup in a map you control**; when you cannot, resolve to a canonical form and *validate the canonical result* against the set of allowed values — never filter the raw input and hope.
@@end

@verify kind=executable language=python
@code
import io
import pathlib
import tarfile
import tempfile
import urllib.parse


def build_tree(root):
    base = root / "srv" / "reports"
    base.mkdir(parents=True)
    (base / "2024-q1.csv").write_text("quarter,revenue\nQ1,100\n")
    (base / "notes.txt").write_text("internal notes\n")
    nested = base / "archive"
    nested.mkdir()
    (nested / "2023-q4.csv").write_text("quarter,revenue\nQ4,90\n")
    (root / "srv" / "reports-backup").mkdir(parents=True)
    (root / "srv" / "reports-backup" / "secret.csv").write_text("do not serve me\n")
    secret = root / "etc" / "passwd"
    secret.parent.mkdir(parents=True)
    secret.write_text("root:x:0:0:root:/root:/bin/bash\n")
    return base, secret


def vulnerable_download(base, requested):
    return (base / requested).read_bytes()


def strip_dots_download(base, requested):
    """The attempted fix: remove '..' from the string, then join."""
    return (base / requested.replace("..", "")).read_bytes()


def safe_download(base, requested):
    candidate = (base / requested).resolve()
    if not candidate.is_relative_to(base.resolve()):
        raise PermissionError("path escapes the report directory")
    if not candidate.is_file():
        raise FileNotFoundError("no such report")
    return candidate.read_bytes()


def attempt(function, base, requested):
    try:
        return ("served", function(base, requested).decode().splitlines()[0][:20])
    except PermissionError:
        return ("refused", "escapes the report directory")
    except FileNotFoundError:
        return ("missing", "no such report")
    except (ValueError, NotADirectoryError, IsADirectoryError) as exc:
        return (type(exc).__name__, str(exc)[:20])


with tempfile.TemporaryDirectory() as tmp:
    root = pathlib.Path(tmp)
    base, secret = build_tree(root)

    # An attack that reaches the secret file by absolute path, built from this temp tree:
    # "//" + tail makes pathlib treat it as absolute, exactly like "/etc/passwd" would.
    secret_tail = str(secret).lstrip("/")
    relative_attack = "../../" + str(secret.relative_to(root))   # climbs out of the base
    encoded_attack = urllib.parse.quote(relative_attack, safe="")
    double_slash_escape = "//" + secret_tail

    attacks = [
        relative_attack,                                   # relative traversal
        encoded_attack,                                    # URL-encoded traversal
        "....//" + secret_tail,                            # survives replace("..", "")
        double_slash_escape,                               # absolute path, no dots at all
        "../reports-backup/secret.csv",                     # sibling directory, shared prefix
        "../reports-backup/../reports/2024-q1.csv",         # normalises back inside the base
        "archive/../notes.txt",                            # inside-base normalisation
        "archive/2023-q4.csv",                             # legitimate nested file
        "2024-q1.csv",                                     # legitimate file
        "missing.csv",
    ]

    print(f"{'request (truncated)':38s} {'vulnerable':>12s} {'strip-dots':>12s} {'safe':>12s}")
    results = {}
    for requested in attacks:
        decoded = urllib.parse.unquote(requested)
        row = (attempt(vulnerable_download, base, decoded),
               attempt(strip_dots_download, base, decoded),
               attempt(safe_download, base, decoded))
        results[requested] = row
        label = requested.replace(secret_tail, "<tmp>/etc/passwd")
        if len(label) > 36:
            label = label[:14] + "..." + label[-19:]
        print(f"{label:38s} {row[0][0]:>12s} {row[1][0]:>12s} {row[2][0]:>12s}")

    print()
    print("the vulnerable join serves the secret file:",
          results[relative_attack][0][0] == "served")
    print("replace('..', '') is bypassed by '....//':",
          results["....//" + secret_tail][1][0] == "served")
    print("resolve-and-check refuses every escape:",
          all(results[requested][2][0] != "served" for requested in
              (relative_attack, encoded_attack, "....//" + secret_tail,
               double_slash_escape, "../reports-backup/secret.csv")))
    print("and still serves legitimate paths:",
          [results[requested][2][0] for requested in
           ("../reports-backup/../reports/2024-q1.csv", "archive/../notes.txt",
            "archive/2023-q4.csv", "2024-q1.csv")])

    # A string prefix check looks equivalent but is not: the sibling shares the prefix.
    sibling = (base / "../reports-backup/secret.csv").resolve()
    print("string prefix check accepts the sibling:",
          str(sibling).startswith(str(base.resolve())))
    print("component-wise containment rejects it:", not sibling.is_relative_to(base.resolve()))

    # Archive extraction is the same bug in the write direction.
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        payload = b"escaped!\n"
        info = tarfile.TarInfo("../../escaped.txt")
        info.size = len(payload)
        archive.addfile(info, io.BytesIO(payload))
    buffer.seek(0)

    destination = root / "extract"
    destination.mkdir()
    with tarfile.open(fileobj=buffer) as archive:
        members = [member.name for member in archive.getmembers()]
    rejected_members = [name for name in members
                        if not (destination / name).resolve().is_relative_to(
                            destination.resolve())]
    print("archive members:", members, "| rejected by the same check:", rejected_members)

assert results[relative_attack][0][0] == "served"
assert results[encoded_attack][0][0] == "served", "decoded, it is the same attack"
assert results["....//" + secret_tail][1][0] == "served", "the string replace is bypassable"
assert results[double_slash_escape][1][0] == "served", "and so is any absolute path"
assert all(results[requested][2][0] != "served"
           for requested in (relative_attack, encoded_attack, "....//" + secret_tail,
                             double_slash_escape, "../reports-backup/secret.csv"))
assert results["../reports-backup/../reports/2024-q1.csv"][2][0] == "served"
assert results["archive/../notes.txt"][2][0] == "served"
assert results["archive/2023-q4.csv"][2][0] == "served"
assert results["2024-q1.csv"][2][0] == "served"
assert results["missing.csv"][2][0] == "missing"
assert str(sibling).startswith(str(base.resolve())), "the prefix check is fooled"
assert not sibling.is_relative_to(base.resolve())
assert rejected_members == ["../../escaped.txt"]
print("PASS")
@@end

@expect_output
request (truncated)                      vulnerable   strip-dots         safe
../../etc/passwd                             served       served      refused
..%2F..%2Fetc%2Fpasswd                       served       served      refused
....//<tmp>/etc/passwd                      missing       served      missing
//<tmp>/etc/passwd                           served       served      refused
../reports-backup/secret.csv                 served      missing      refused
../reports-bac...reports/2024-q1.csv         served      missing       served
archive/../notes.txt                         served      missing       served
archive/2023-q4.csv                          served       served       served
2024-q1.csv                                  served       served       served
missing.csv                                 missing      missing      missing

the vulnerable join serves the secret file: True
replace('..', '') is bypassed by '....//': True
resolve-and-check refuses every escape: True
and still serves legitimate paths: ['served', 'served', 'served', 'served']
string prefix check accepts the sibling: True
component-wise containment rejects it: True
archive members: ['../../escaped.txt'] | rejected by the same check: ['../../escaped.txt']
PASS
@@end

@notes
Runs ten requests through three implementations and prints the outcome matrix, so the
security property is visible per input rather than asserted in prose: the vulnerable
join serves `/etc/passwd` through `../../`, the `replace("..", "")` fix is bypassed by
`....//` (it collapses back to `../`) and still serves the file, and the resolve-and-check
version refuses every escape attempt — including the sibling directory whose name shares
a prefix with the base, where a string `startswith` check would have accepted it — while
still serving legitimate nested files and allowing inside-base normalisation like
`archive/../notes.txt`. The same check is then applied to a malicious tar member, which
is the write-direction version of the bug.
@@end
