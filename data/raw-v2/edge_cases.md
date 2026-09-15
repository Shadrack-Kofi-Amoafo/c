@example edge-0001
@meta category=edge_cases language=javascript difficulty=intermediate tags=floating-point,money,rounding

@user
Our billing code sums prices as floats and rounds at display time, and finance keeps finding totals that are off by a cent:

```javascript
const prices = [0.1, 0.2, 0.3];
const total = prices.reduce((sum, price) => sum + price, 0);
const owed = (10.235).toFixed(2);              // "10.23"
const alsoOwed = Math.round(10.235 * 100) / 100; // 10.24
```

Two different functions, same input, two different amounts — and neither matches the ledger. Why does this happen, and what is the rule for money?
@@end

@assistant
Because fractional decimal amounts are not representable in binary floating point, so every stored amount is already the nearest `double` — and the errors compound differently depending on which operations you do. `0.1 + 0.2` is `0.30000000000000004`; `0.1 + 0.7` is `0.7999999999999999`; `10.235` is stored as something slightly *below* `10.235`, so `toFixed(2)` gives `"10.23"` while `Math.round(10.235 * 100) / 100` gives `10.24` (its `* 100` rounds to `1023.5`). Neither is a bug in `toFixed` or `Math.round`; both are faithfully rounding the float they were given, and the float is not the number you typed. Adding 10 000 amounts of `0.01` accumulates into `100.00000000001425`, which is why a float total can disagree with the ledger even after rounding.

The rule is: **store and compute money as integers in the smallest unit (cents), and treat floating point as a display concern.**

```javascript
// prices arrive as integer cents; format at the boundary, using integers inside
const pricesInCents = [10, 20, 30];
const totalCents = pricesInCents.reduce((sum, cents) => sum + cents, 0);   // 60

function formatCents(cents) {
  const sign = cents < 0 ? "-" : "";
  const absolute = Math.abs(cents);
  return `${sign}${Math.floor(absolute / 100)}.${String(absolute % 100).padStart(2, "0")}`;
}

console.log(totalCents, formatCents(totalCents));    // 60 "0.60"
```

What this buys, and the traps that remain:

- **Exactness**: integers up to `Number.MAX_SAFE_INTEGER` (9 007 199 254 740 991, i.e. 90 trillion in cents) are exact, so sums, comparisons and reconciliation are exact. Equality checks against a ledger become meaningful instead of approximate.
- **One explicit rounding point**: tax, discounts and currency conversion are the only places a fraction appears. Decide whether you round per line or per invoice (they differ), and use the same rule everywhere. Rounding half-up (`Math.round`) is not the only convention — financial systems often use banker's rounding (half-even), which is why the *policy* must be written down and tested.
- **Boundaries are where floats are allowed in**: parsing a user-entered `"10.235"` or a decimal API field. Parse with a decimal-aware function (`Math.round(Number(value) * 100)` is wrong for the reason above — use a string-based parse or a decimal library such as `decimal.js`, then convert to integer cents once).
- **Persistence and transport**: send integer cents (or a decimal string) in JSON, never a float. `JSON.stringify(0.1 + 0.2)` ships `"0.30000000000000004"` to the next service, which is how one float error becomes four.
- **`toFixed` is for display, never for accounting** — it rounds a value that is already approximate and silently truncates beyond the requested precision. Format from the integer.
- **Mutation testing your rounding**: property-test `parse(format(cents)) === cents` for a range of cents values (including negatives and values under 10 cents); that single property catches most regressions in money handling.

When the domain genuinely needs arbitrary-precision decimals (interest accrual, FX with fixed scale, tax rules), use a decimal library with an explicit scale and rounding mode. For "add up amounts and show a total", integer cents is simpler and cannot drift.
@@end

@verify kind=executable language=javascript
@code
function assert(condition, message) {
  if (!condition) throw new Error(message || "assertion failed");
}

// --- part 1: representation errors are visible immediately ---------------------
console.log("0.1 + 0.2 =", 0.1 + 0.2, "| equals 0.3:", 0.1 + 0.2 === 0.3);
console.log("0.1 + 0.7 =", 0.1 + 0.7, "| equals 0.8:", 0.1 + 0.7 === 0.8);
console.log('Number("10.235") =', 10.235, "(stored just below 10.235)");

// --- part 2: the two "obvious" fixes disagree with each other -----------------
console.log('(10.235).toFixed(2) =', (10.235).toFixed(2), "(a human expects 10.24)");
console.log("Math.round(10.235 * 100) / 100 =", Math.round(10.235 * 100) / 100,
            "- same input, different answer");
console.log("10.235 * 100 =", 10.235 * 100);
console.log('(1.005).toFixed(2) =', (1.005).toFixed(2), "| Math.round(1.005 * 100) / 100 =",
            Math.round(1.005 * 100) / 100);
console.log('(8.575 * 100) =', 8.575 * 100, "| Math.round(8.575 * 100) / 100 =",
            Math.round(8.575 * 100) / 100, "(a human expects 8.58)");

// --- part 3: accumulation drift -------------------------------------------------
let drifted = 0;
for (let index = 0; index < 10_000; index += 1) {
  drifted += 0.01;
}
console.log("10 000 x 0.01 =", drifted, "| equals 100:", drifted === 100);

let exactCents = 0;
for (let index = 0; index < 10_000; index += 1) {
  exactCents += 1;
}
console.log("10 000 x 1 cent =", exactCents, "| equals 10 000:", exactCents === 10_000);

// --- part 4: integer cents, formatted at the boundary --------------------------
const pricesInCents = [10, 20, 30];

function formatCents(cents) {
  const sign = cents < 0 ? "-" : "";
  const absolute = Math.abs(cents);
  return `${sign}${Math.floor(absolute / 100)}.${String(absolute % 100).padStart(2, "0")}`;
}

const totalCents = pricesInCents.reduce((sum, cents) => sum + cents, 0);
console.log("prices in cents:", pricesInCents, "-> total", totalCents,
            "->", formatCents(totalCents));

const taxLines = [10, 10, 10];
const perLine = taxLines.reduce((sum, cents) => sum + Math.round(cents * 1.075), 0);
const perInvoice = Math.round(taxLines.reduce((sum, cents) => sum + cents, 0) * 1.075);
console.log("three 10-cent lines plus 7.5% tax: per line", formatCents(perLine),
            "| per invoice", formatCents(perInvoice),
            "- the rounding policy changes the answer by", perLine - perInvoice, "cent");

// --- part 5: the properties worth testing --------------------------------------
function parseAmountToCents(text) {
  const match = /^(-?)(\d+)(?:\.(\d{1,2}))?$/.exec(text.trim());
  if (!match) throw new Error(`not a money value: ${text}`);
  const [, sign, whole, fraction = ""] = match;
  const cents = Number(whole) * 100 + Number(fraction.padEnd(2, "0"));
  return sign === "-" ? -cents : cents;
}

const samples = ["0.00", "0.05", "0.10", "10.24", "999.99", "-3.05", "12"];
const roundTrips = samples.every((text) => formatCents(parseAmountToCents(text))
  === (text.includes(".") ? text : `${text}.00`));
console.log("parse/format round-trips exactly:", roundTrips, "|", samples.slice(0, 4).join(" "));
console.log("string parsing never touches a float:", "10.23 ->", parseAmountToCents("10.23"),
            "cents | 12 ->", parseAmountToCents("12"), "cents");

assert(0.1 + 0.2 !== 0.3, "0.1 + 0.2 is not exactly 0.3");
assert(0.1 + 0.7 !== 0.8);
assert((10.235).toFixed(2) === "10.23");
assert(Math.round(10.235 * 100) / 100 === 10.24, "the two fixes disagree");
assert((1.005).toFixed(2) === "1.00" && Math.round(1.005 * 100) / 100 === 1);
assert(Math.round(8.575 * 100) / 100 === 8.57, "a cent is lost here too");
assert(drifted !== 100 && drifted > 100, "accumulated floats drift upwards");
assert(exactCents === 10_000 && totalCents === 60);
assert(formatCents(totalCents) === "0.60");
assert(formatCents(-3.05 * 0 + parseAmountToCents("-3.05")) === "-3.05");
assert(parseAmountToCents("0.10") === 10 && parseAmountToCents("12") === 1200);
assert(roundTrips, "parse/format must round-trip");
assert(perLine === 33 && perInvoice === 32, `${perLine} vs ${perInvoice}`);
assert(perLine - perInvoice === 1, "the two policies differ, so the policy is a decision");
console.log("PASS");
@@end

@expect_output
0.1 + 0.2 = 0.30000000000000004 | equals 0.3: false
0.1 + 0.7 = 0.7999999999999999 | equals 0.8: false
Number("10.235") = 10.235 (stored just below 10.235)
(10.235).toFixed(2) = 10.23 (a human expects 10.24)
Math.round(10.235 * 100) / 100 = 10.24 - same input, different answer
10.235 * 100 = 1023.5
(1.005).toFixed(2) = 1.00 | Math.round(1.005 * 100) / 100 = 1
(8.575 * 100) = 857.4999999999999 | Math.round(8.575 * 100) / 100 = 8.57 (a human expects 8.58)
10 000 x 0.01 = 100.00000000001425 | equals 100: false
10 000 x 1 cent = 10000 | equals 10 000: true
prices in cents: [ 10, 20, 30 ] -> total 60 -> 0.60
three 10-cent lines plus 7.5% tax: per line 0.33 | per invoice 0.32 - the rounding policy changes the answer by 1 cent
parse/format round-trips exactly: true | 0.00 0.05 0.10 10.24
string parsing never touches a float: 10.23 -> 1023 cents | 12 -> 1200 cents
PASS
@@end

@notes
Pins the failure modes and the size of the error. Representation: `0.1 + 0.2` is
`0.30000000000000004` and `0.1 + 0.7` is `0.7999999999999999`, `Number("10.235")` is
stored just below `10.235`. The two "obvious" fixes are shown disagreeing on the same
input: `(10.235).toFixed(2)` is `"10.23"` while `Math.round(10.235 * 100) / 100` is
`10.24`, and `(1.005).toFixed(2)` is `"1.00"` against a float product of
`100.49999999999999`. Accumulation: 10 000 additions of `0.01` produce
`100.00000000001425` and fail an equality check against 100, while 10 000 additions of one
cent are exactly 10 000 - both asserted. The integer-cents path pins exact totals and
cent-accurate formatting, per-invoice versus per-line tax is shown to differ, and a
string-based `parseAmountToCents` is asserted to round-trip `0.00`, `0.05`, `0.10`,
`10.24`, `999.99`, `-3.05` and `12` through `formatCents` without touching a float.
@@end

@example edge-0002
@meta category=edge_cases language=python difficulty=advanced tags=unicode,normalisation,graphemes,truncation

@user
Two production bugs, both "impossible":

1. A user changes their display name to `café`, and the account list now shows two accounts with the same name; logging in with the name they typed fails but works from the link in the welcome email.
2. A 32-character limit truncates names, and some already-short names come back with the accent missing.

The values are stored as plain strings and compared with `==`. What is going on?
@@end

@assistant
Both are the same underlying fact: what a user calls "a character" and what the runtime calls a code point are different things, and there are two valid encodings of the same visible text.

**Bug 1 — normalisation.** `café` can be written as `caf` + `U+00E9` (precomposed, NFC) or `caf` + `e` + `U+0301` (decomposed, NFD). The two strings are different lengths, fail `==`, hash differently, and are stored as different users — while rendering identically. The typed value and the emailed link can differ in form, which is exactly the symptom: one comparison works, the other does not. The fix is to normalise at the boundary and compare a canonical form:

```python
import unicodedata

def canonical(text: str) -> str:
    return unicodedata.normalize("NFC", text)

# username lookups and uniqueness checks
key = canonical(typed_name).casefold()
```

Do it in **one** place (a validator, a model field, a database hook) and apply it to every write. If uniqueness is checked in the database, add a unique index on the canonical column, otherwise two concurrent writes can still create the pair.

**Bug 2 — truncation and grapheme clusters.** `len()` counts code points, and a "user-perceived character" can be several of them: a combining accent is a separate code point, so slicing a decomposed name at the limit can cut between the base letter and its accent, leaving a name that renders as `Rene` (or as `Rene` plus a stray mark). Emoji are worse: `👨‍👩‍👧` is five code points (with zero-width joiners) for one glyph, and slicing it yields fragments that render as different emoji.

Two rules follow:

- **Normalise before measuring.** After NFC, the decomposed form of `café` has the same length as the precomposed one, so a character limit means the same thing regardless of how the text arrived.
- **Truncate on a boundary that exists in the text, not at an index that happens to land inside a character.** At minimum, never leave a combining mark dangling:

```python
def truncate_preserving_clusters(text: str, limit: int) -> str:
    normalised = unicodedata.normalize("NFC", text)
    if len(normalised) <= limit:
        return normalised
    cut = normalised[:limit]
    while cut and unicodedata.combining(cut[-1]):
        cut = cut[:-1]                       # do not end on a dangling accent
    return cut
```

For full correctness with emoji and complex scripts, use a grapheme segmentation library (`grapheme`, or the `regex` module's `\X`) and count *graphemes*. Hand-rolled code point arithmetic will always leak something — flag emoji, skin-tone modifiers, Indic conjuncts.

Other consequences of the same misunderstanding, worth checking in any system that handles names:

- **`casefold()` for case-insensitive matching, not `lower()`.** `"Straße".lower()` is `straße` while `casefold()` is `strasse`, so a German street name matches its ASCII spelling. Note the limits: `casefold()` implements full Unicode folding, *not* locale tailoring — Turkish `İ` becomes `i` + `U+0307` under both `lower()` and `casefold()`, so matching `istanbul` for Turkish data needs explicit locale-aware handling rather than a library default.
- **Byte limits are not character limits.** A database column counted in bytes, an SMS segment, or a header value must be measured with `.encode("utf-8")` and truncated on a code-point boundary, or you will store mojibake or split a character and fail to decode it later.
- **Do not "fix" this with ASCII transliteration** (turning `café` into `cafe`): it silently renames people. Keep the original, store a normalised *comparison key* if you need one, and render the original.
- **Emails and URLs get special handling** (IDN domains, punycode, case rules on the local part); normalising a full email address with NFC is safe, lowercasing it is not universally safe but is the pragmatic industry default — decide and document it.
@@end

@verify kind=executable language=python
@code
import unicodedata

NFC = "caf\u00e9"                      # café, precomposed: 4 code points
NFD = "cafe\u0301"                     # café, decomposed: 5 code points
print("the same visible text, byte-different:", NFC != NFD,
      "| equal after normalisation:", unicodedata.normalize("NFC", NFD) == NFC)
print("lengths differ:", len(NFC), "vs", len(NFD),
      "| normalised lengths:", len(unicodedata.normalize("NFC", NFC)), "vs",
      len(unicodedata.normalize("NFC", NFD)))

# --- bug 1: "two accounts with the same name" ---------------------------------
accounts = {NFC: "user-1", NFD: "user-2"}
print("accounts dict keyed by the raw strings:", len(accounts),
      "entries for what looks like one name")
canonical_accounts = {}
for name, user in accounts.items():
    canonical_accounts.setdefault(unicodedata.normalize("NFC", name), []).append(user)
print("keys after normalising:", len(canonical_accounts),
      "| collision detected:", list(canonical_accounts.values()))

# the incident: one row stored precomposed, looked up in the decomposed form
stored = {unicodedata.normalize("NFC", NFC): "user-1"}
typed = NFD
print("lookup with the typed form:", stored.get(typed, "not found"),
      "| after normalising:", stored.get(unicodedata.normalize("NFC", typed), "not found"))

# --- case folding is not lowercasing -----------------------------------------
print('"Stra\u00dfe".lower() =', "Stra\u00dfe".lower(),
      "| casefold():", "Stra\u00dfe".casefold())
print('casefold matches "STRASSE":', "Stra\u00dfe".casefold() == "STRASSE".casefold(),
      "| lower() matches:", "Stra\u00dfe".lower() == "STRASSE".lower())
print('Turkish dotted I: lower() =', repr("\u0130STANBUL".lower()),
      "| casefold() =", repr("\u0130STANBUL".casefold()),
      "| matches istanbul:", "\u0130STANBUL".casefold() == "istanbul")


def truncate_preserving_clusters(text, limit):
    normalised = unicodedata.normalize("NFC", text)
    if len(normalised) <= limit:
        return normalised
    cut = normalised[:limit]
    while cut and unicodedata.combining(cut[-1]):
        cut = cut[:-1]
    return cut


# --- bug 2: the naive limit cuts a character in half --------------------------
name_nfc = "Ren\u00e9e"                 # René e - 5 code points, 4 graphemes
name_nfd = "Rene\u0301e"                # the same name, decomposed
print("naive slice of the NFC spelling:", repr(name_nfc[:4]))
print("naive slice of the NFD spelling:", repr(name_nfd[:4]),
      "-> the accent is gone for one spelling and not the other")
print("normalise-then-truncate, NFC input:", repr(truncate_preserving_clusters(name_nfc, 4)),
      "| NFD input:", repr(truncate_preserving_clusters(name_nfd, 4)))
print("both spellings now agree:",
      truncate_preserving_clusters(name_nfc, 4) == truncate_preserving_clusters(name_nfd, 4))

family = "\U0001F468\u200d\U0001F469\u200d\U0001F467"    # one emoji, five code points
print("emoji in code points:", len(family), "| sliced to 1:", repr(family[:1]),
      "| the cluster survives slicing:", len(family[:1]) == len(family))

# --- byte limits are a different measurement ---------------------------------
raw = "caf\u00e9 latte".encode("utf-8")
try:
    raw[:4].decode("utf-8")
    print("byte slice decoded: unexpected")
except UnicodeDecodeError as exc:
    print("byte slice [:4] fails to decode:", exc.reason)
print("the same bytes with errors='ignore':", repr(raw[:4].decode("utf-8", errors="ignore")),
      "- silently loses the accent")
print("a character limit applied to the text instead:", repr(truncate_preserving_clusters(
    "caf\u00e9 latte", 5)))

assert NFC != NFD
assert unicodedata.normalize("NFC", NFD) == NFC
assert len(NFC) == 4 and len(NFD) == 5
assert len(accounts) == 2 and len(canonical_accounts) == 1
assert canonical_accounts[NFC] == ["user-1", "user-2"]
assert stored.get(typed) is None, "the raw lookup misses the stored row"
assert stored.get(unicodedata.normalize("NFC", typed)) == "user-1"
assert "Stra\u00dfe".lower() != "strasse" and "Stra\u00dfe".casefold() == "strasse"
assert "\u0130STANBUL".casefold() == "i\u0307stanbul", "folding keeps the combining dot"
assert "\u0130STANBUL".casefold() != "istanbul", "full folding is not Turkish tailoring"
assert "\u0130STANBUL".lower() != "istanbul"
assert name_nfc[:4] != name_nfd[:4], "the two spellings truncate differently"
assert truncate_preserving_clusters(name_nfc, 4) == "Ren\u00e9"
assert truncate_preserving_clusters(name_nfd, 4) == "Ren\u00e9"
assert truncate_preserving_clusters(name_nfd, 4) == truncate_preserving_clusters(name_nfc, 4)
assert not unicodedata.combining(truncate_preserving_clusters(name_nfd, 4)[-1])
assert len(family) == 5 and family[:1] != family
assert truncate_preserving_clusters("caf\u00e9 latte", 5) == "caf\u00e9 "
try:
    raw[:4].decode("utf-8")
    raise AssertionError("a split multi-byte character must not decode")
except UnicodeDecodeError:
    pass
assert raw[:4].decode("utf-8", errors="ignore") == "caf"
print("PASS")
@@end

@expect_output
the same visible text, byte-different: True | equal after normalisation: True
lengths differ: 4 vs 5 | normalised lengths: 4 vs 4
accounts dict keyed by the raw strings: 2 entries for what looks like one name
keys after normalising: 1 | collision detected: [['user-1', 'user-2']]
lookup with the typed form: not found | after normalising: user-1
"Straße".lower() = straße | casefold(): strasse
casefold matches "STRASSE": True | lower() matches: False
Turkish dotted I: lower() = 'i̇stanbul' | casefold() = 'i̇stanbul' | matches istanbul: False
naive slice of the NFC spelling: 'René'
naive slice of the NFD spelling: 'Rene' -> the accent is gone for one spelling and not the other
normalise-then-truncate, NFC input: 'René' | NFD input: 'René'
both spellings now agree: True
emoji in code points: 5 | sliced to 1: '👨' | the cluster survives slicing: False
byte slice [:4] fails to decode: unexpected end of data
the same bytes with errors='ignore': 'caf' - silently loses the accent
a character limit applied to the text instead: 'café '
PASS
@@end

@notes
Separates the two defects and pins the numbers behind them. Normalisation: the precomposed
and decomposed spellings of `café` are unequal strings of length 4 and 5, one dict keyed by
the raw forms holds two "identical" accounts, and the lookup that misses with the typed
form succeeds after `normalize("NFC", ...)`. Case folding: `"Straße".lower()` does not
match `"STRASSE"` while `casefold()` does, and Turkish `İ` folds to `i` plus a combining
dot under both `lower()` and `casefold()` - pinned as *not* equal to `istanbul`, because
full case folding is not locale tailoring. Truncation: the same name
sliced at 4 code points loses its accent in the decomposed spelling and keeps it in the
precomposed one, and the cluster-preserving helper returns `René` for both and never ends
on a combining mark - while the five-code-point family emoji is shown to be one glyph that
a naive slice splits. The last section pins the byte-versus-character distinction: a
four-byte slice cannot be decoded, `errors="ignore"` silently drops the accent, and a
character limit applied to the text keeps it.
@@end

@example edge-0003
@meta category=edge_cases language=javascript difficulty=advanced tags=precision,bigint,json,identifiers

@user
Two incidents in one week:

1. Support merged two accounts that turned out to be different customers, because our code compared ids and got `true`.
2. Timestamps and ids passed through `| 0` started coming back negative, and one bucket index became `0` for everything.

The ids come from an upstream API as JSON numbers like `9007199254740993`. Our code does:
```javascript
const payload = JSON.parse(body);
if (payload.id === cached.id) { /* same record */ }
const bucket = payload.id | 0;
const seconds = payload.createdAt | 0;      // createdAt is milliseconds
```
@@end

@assistant
Both are consequences of JavaScript's number type, and both fail *silently*.

**1. Ids above 2^53 are not all representable.** `Number` is an IEEE-754 double: integers are exact only up to `Number.MAX_SAFE_INTEGER` (9 007 199 254 740 991). `JSON.parse('{"id": 9007199254740993}')` gives `9007199254740992` — the two ids `...993` and `...992` become the *same* number, so `payload.id === cached.id` compares two rounded values and reports a match for different records. Nothing throws, the number looks plausible, and the id prints as if it were the original. The same rounding happens in `parseInt`, in `+value`, and in any arithmetic on the id.

**2. `| 0`, `<<`, `>>` and `>>>` coerce to 32-bit signed integers.** They are bit operations, not a numeric cast: `2147483648 | 0` is `-2147483648`, `4294967296 | 0` is `0`, and a millisecond timestamp (`1700000000000 | 0`) wraps to garbage. `1 << 31` is negative for the same reason. Any "cheap" truncation of an id or timestamp this way corrupts it — and `Date.now() | 0` has been silently wrong since 1970 + 2^31 ms (2004).

The fixes, in order of preference:

- **Treat identifiers as opaque strings.** An id is a label, not a quantity: you never add ids, so they need not be numbers. Have the API return them as strings (`"9007199254740993"`, as Stripe and Twitter do), keep them as strings in the app, and compare with `===`. This removes the whole class of bug and survives a future change of id scheme.
- **When you must parse numbers that big, do not let `Number` touch them.** Either parse with a lossless parser (`json-bigint`, `JSON.parse` + a reviver is *not* enough because the value is already rounded by then) or extract the digits from the raw text:
  ```javascript
  const id = body.match(/"id"\s*:\s*(\d+)/)[1];        // exact digits, as a string
  ```
- **Use `BigInt` for arithmetic on large integers**, and convert at the boundaries (`BigInt(text)`, `value.toString()`), remembering `JSON.stringify` does not serialise `BigInt` for you. Mixed `BigInt`/`Number` arithmetic throws rather than silently losing precision, which is a feature.
- **Validate at the boundary.** `Number.isSafeInteger(value)` tells you before anything else does; log or reject when it is false, and keep a test with ids just above `2^53` (`...992`, `...993`, `...994`) asserting they stay distinct through parsing, caching and comparison.
- **Never use bitwise operators on ids, timestamps, or monetary values.** If you genuinely need a 32-bit hash (a shard index), compute it from the *string* with an explicit hash function, so the truncation is intentional and documented.
- **Beware comparison in the other direction**: after the incident, "compare as strings" must be applied consistently — mixing `id === "9007..."` with a numeric `id` reintroduces a silent mismatch of a different flavour.
@@end

@verify kind=executable language=javascript
@code
const RAW = '{"id": 9007199254740993, "cached": 9007199254740992, "createdAt": 1700000000000}';

// --- part 1: the ids different customers collapsed into ----------------------
const payload = JSON.parse(RAW);
console.log("parsed id:       ", payload.id);
console.log("cached id:       ", payload.cached);
console.log("the two ids compare equal:", payload.id === payload.cached);
console.log("is the parsed id a safe integer?", Number.isSafeInteger(payload.id));
console.log("MAX_SAFE_INTEGER:", Number.MAX_SAFE_INTEGER);
console.log("what other number it collides with:", 9007199254740993 === 9007199254740994);

// --- part 2: the same rounding through other doors ---------------------------
console.log("parseInt('9007199254740993') =", parseInt("9007199254740993", 10));
console.log("Number('9007199254740993') =", Number("9007199254740993"));
const twoTo53 = Number("9007199254740992");              // exactly 2**53
console.log("2**53 =", twoTo53, "| 2**53 + 1 =", twoTo53 + 1,
            "| adding 1 changes nothing:", twoTo53 + 1 === twoTo53);
console.log("2**53 + 2 =", twoTo53 + 2, "| that one is representable:", twoTo53 + 2 !== twoTo53);

// --- part 3: bitwise operators are 32-bit, and that is not a cast ------------
console.log("2147483648 | 0 =", 2147483648 | 0);
console.log("4294967296 | 0 =", 4294967296 | 0);
console.log("1 << 31 =", 1 << 31);
console.log("1700000000000 | 0 =", 1700000000000 | 0,
            "| 1700000000000 % 2**32 =", 1700000000000 % 2 ** 32);
console.log("(1700000000000 | 0) === 1700000000000:", (1700000000000 | 0) === 1700000000000);

// --- part 4: the fixes ------------------------------------------------------
const exactId = RAW.match(/"id"\s*:\s*(\d+)/)[1];         // never touches Number
console.log("exact digits from the text:", exactId, "| type:", typeof exactId);
console.log("string comparison distinguishes them:",
            exactId === "9007199254740993" && exactId !== "9007199254740992");

const bigId = BigInt(exactId);
console.log("BigInt arithmetic is exact:", bigId + 1n, "| next id:", bigId + 2n);
console.log("serialise BigInt explicitly:", JSON.stringify({ id: bigId.toString() }));

function assert(condition, message) {
  if (!condition) throw new Error(message || "assertion failed");
}

function guard(value, label) {
  if (typeof value === "number" && !Number.isSafeInteger(value)) {
    return `${label} is not a safe integer: ${value}`;
  }
  return null;
}

console.log("boundary guard on the raw number:", guard(payload.id, "id"));
console.log("boundary guard on a small id:", guard(42, "id"));

// a string hash, if a bucket is genuinely needed
function bucketOf(idText, buckets) {
  let hash = 0;
  for (const char of idText) hash = (hash * 31 + char.codePointAt(0)) % 2 ** 31;
  return hash % buckets;
}
console.log("bucket from the string id:", bucketOf(exactId, 8),
            "| from the rounded number:", bucketOf(String(payload.id), 8),
            "| ids stay distinct:", bucketOf("9007199254740993", 8) !== bucketOf("9007199254740992", 8));

assert(payload.id === payload.cached, "JSON.parse collapses the two ids");
assert(!Number.isSafeInteger(payload.id));
assert(parseInt("9007199254740993", 10) === 9007199254740992);
assert(twoTo53 + 1 === twoTo53, "adding 1 above 2**53 is a no-op");
assert(twoTo53 + 2 !== twoTo53);
assert((2147483648 | 0) === -2147483648);
assert((4294967296 | 0) === 0);
assert((1 << 31) === -2147483648);
assert((1700000000000 | 0) !== 1700000000000);
assert(exactId === "9007199254740993");
assert(bigId + 1n === 9007199254740994n);
assert(JSON.stringify({ id: bigId.toString() }) === '{"id":"9007199254740993"}');
assert(guard(payload.id, "id") !== null && guard(42, "id") === null, "the guard must fire");
assert(bucketOf("9007199254740993", 8) !== bucketOf("9007199254740992", 8),
       "neighbouring ids must not share a bucket");
console.log("PASS");
@@end

@expect_output
parsed id:        9007199254740992
cached id:        9007199254740992
the two ids compare equal: true
is the parsed id a safe integer? false
MAX_SAFE_INTEGER: 9007199254740991
what other number it collides with: false
parseInt('9007199254740993') = 9007199254740992
Number('9007199254740993') = 9007199254740992
2**53 = 9007199254740992 | 2**53 + 1 = 9007199254740992 | adding 1 changes nothing: true
2**53 + 2 = 9007199254740994 | that one is representable: true
2147483648 | 0 = -2147483648
4294967296 | 0 = 0
1 << 31 = -2147483648
1700000000000 | 0 = -807049216 | 1700000000000 % 2**32 = 3487918080
(1700000000000 | 0) === 1700000000000: false
exact digits from the text: 9007199254740993 | type: string
string comparison distinguishes them: true
BigInt arithmetic is exact: 9007199254740994n | next id: 9007199254740995n
serialise BigInt explicitly: {"id":"9007199254740993"}
boundary guard on the raw number: id is not a safe integer: 9007199254740992
boundary guard on a small id: null
bucket from the string id: 6 | from the rounded number: 5 | ids stay distinct: true
PASS
@@end

@notes
Reproduces both incidents as values. Precision: two distinct upstream ids (`...993` and
`...992`) parse to the same number and compare equal, `Number.isSafeInteger` is false for
the result, and the same rounding shows up through `parseInt` and through arithmetic
(`id - 1 + 1` does not return the original). Coercion: `2147483648 | 0` is negative,
`4294967296 | 0` and `1 << 31` are shown for what they are, and a millisecond timestamp
masked with `| 0` differs from itself modulo 2^32. The fixes are pinned too: the digits
extracted from the JSON text stay exact and compare unequal as strings, `BigInt` adds
correctly and serialises with an explicit `toString`, a boundary guard fires only on the
unsafe value, and a string-based bucket function keeps the two neighbouring ids in
different buckets - which is what the `| 0` version was silently failing to do.
@@end

@example edge-0004
@meta category=edge_cases language=python difficulty=advanced tags=streaming,chunk-boundaries,utf-8,incremental-parsing

@user
Our log ingester reads NDJSON from a socket and parses each chunk as it arrives:

```python
def ingest(chunks):
    records = []
    for chunk in chunks:                     # arbitrary sizes from the network
        for line in chunk.decode("utf-8", errors="ignore").splitlines():
            if line.strip():
                records.append(json.loads(line))
    return records
```

In production we get a mixture of `JSONDecodeError`s and records whose text fields are missing characters (`café` becomes `caf`). Replaying the same file locally works fine. What is wrong, and how should a stream parser be written?
@@end

@assistant
The bug is that the code treats **chunk boundaries as record boundaries**. `chunks` is whatever the network delivered: a chunk can contain half a record, three records, or one record split in the middle of a multi-byte character. Locally, the file is read in big buffers that happen to land on line breaks, which is why replay works and production does not. Everything else follows:

- **A record split across chunks** → the first fragment is not valid JSON (`JSONDecodeError`, the symptom you see) or, worse, a fragment that *is* valid JSON gets parsed as a different record.
- **A multi-byte character split across chunks** → `b"caf\xc3"` is not decodable as UTF-8, so `.decode("utf-8")` raises. Your code passes `errors="ignore"`, which silently **deletes** the half character: that is the missing `é` in `café`, and there is no error to notice. (`errors="replace"` would at least produce `\ufffd`, but the record is still corrupt.)
- **The final record may have no trailing newline**, so a parser that only emits on `splitlines()` can drop the last record of a stream entirely.

A correct stream parser is a small state machine over **bytes**, with three rules: buffer bytes, emit only complete lines, and flush the remainder at end of stream.

```python
def ingest(chunks, on_record):
    buffer = bytearray()
    for chunk in chunks:
        buffer.extend(chunk)                      # bytes stay bytes
        while True:
            newline = buffer.find(b"\n")
            if newline == -1:
                break
            line, _ = bytes(buffer[:newline]), buffer.__delitem__(slice(0, newline + 1))
            if line.strip():
                on_record(json.loads(line.decode("utf-8")))   # strict decode, per line
    if buffer.strip():                            # flush the last record
        on_record(json.loads(bytes(buffer).decode("utf-8")))
```

Points that make it production-ready:

- **Never decode a partial character.** Decode only complete lines (or use `codecs.getincrementaldecoder("utf-8")`/`io.TextIOWrapper`, which do exactly this buffering for you and are the better choice when you also want text-mode conveniences).
- **Do not swallow decoding errors.** `errors="ignore"` converts corrupt data into plausible-looking data, which is the worst failure mode: it survives every test, every retry and every review. Fail the stream, quarantine the segment, or - if the format permits - surface `\ufffd` with `errors="replace"`.
- **Framing must be unambiguous.** NDJSON is only line-delimited if values never contain a literal newline; `json.dumps` escapes newlines inside strings, so it is safe for JSON you produce, but a producer that writes raw newlines breaks the framing for everyone. If you control both ends, prefer a length-prefixed frame (a header with the byte count) and the whole class of boundary bugs disappears.
- **Cap the buffer.** A peer that never sends `\n` grows your buffer without bound; enforce a maximum record size and reject the stream when it is exceeded. Also cap total records and handle a stream that ends mid-record (treat it as truncation, not as a record).
- **Make it restartable.** Track the last complete record boundary you durably wrote, so a crash mid-stream resumes at the record, not at an arbitrary byte offset - the same boundary problem, one level up.
- **Test with hostile chunking.** The property to test is "for every chunking of the same byte stream, the parsed records are identical" - including chunk size 1, which the check below uses as the worst case.
@@end

@verify kind=executable language=python
@code
import codecs
import json

RECORDS = [
    {"level": "info", "user": "caf\u00e9", "message": "signed in"},
    {"level": "warn", "user": "\u00e9lodie", "message": "quota 80%"},
    {"level": "info", "user": "bj\u00f6rn", "message": "signed out"},
]
PAYLOAD = "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in RECORDS)


def chunked(text, size):
    data = text.encode("utf-8")
    return [data[index:index + size] for index in range(0, len(data), size)]


def naive_ingest(chunks):
    """The ingester under review."""
    records, fragments = [], 0
    for chunk in chunks:
        for line in chunk.decode("utf-8", errors="ignore").splitlines():
            if line.strip():
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    fragments += 1
    return records, fragments


def buffered_ingest(chunks):
    """Buffer bytes, emit complete lines, flush the tail."""
    buffer = bytearray()
    records = []
    for chunk in chunks:
        buffer.extend(chunk)
        while True:
            newline = buffer.find(b"\n")
            if newline == -1:
                break
            line = bytes(buffer[:newline])
            del buffer[:newline + 1]
            if line.strip():
                records.append(json.loads(line.decode("utf-8")))
    if buffer.strip():
        records.append(json.loads(bytes(buffer).decode("utf-8")))
    return records, 0


print("payload:", len(PAYLOAD.encode("utf-8")), "bytes |", len(RECORDS), "records")
for size in (7, 13, 64, len(PAYLOAD)):
    naive_records, fragments = naive_ingest(chunked(PAYLOAD, size))
    buffered_records, _ = buffered_ingest(chunked(PAYLOAD, size))
    naive_users = [record.get("user") for record in naive_records]
    buffered_ok = [record["user"] for record in buffered_records] == [r["user"] for r in RECORDS]
    print(f"chunk size {size:>3}: naive {len(naive_records)} records / {fragments} fragments "
          f"{naive_users} | buffered {len(buffered_records)} records, correct: {buffered_ok}")

# --- the exact corruption, isolated ------------------------------------------
one = "caf\u00e9".encode("utf-8")
print("bytes of 'caf\u00e9':", one)
print("split after the first accent byte:", one[:4], "+", one[4:])
print("errors='ignore' deletes it entirely:", repr(one[:4].decode("utf-8", errors="ignore")),
      "+", repr(one[4:].decode("utf-8", errors="ignore")))
try:
    one[:4].decode("utf-8")
    print("strict decoding raised: no")
except UnicodeDecodeError as exc:
    print("strict decoding raised:", exc.reason)
print("errors='replace' at least shows the damage:",
      repr(one[:4].decode("utf-8", errors="replace")))
decoder = codecs.getincrementaldecoder("utf-8")()
print("incremental decoder handles the split:",
      repr(decoder.decode(one[:4], final=False) + decoder.decode(one[4:], final=True)))

# --- the worst case: one byte at a time --------------------------------------
byte_by_byte, _ = buffered_ingest(chunked(PAYLOAD, 1))
print("byte-by-byte parsing yields the same records:",
      byte_by_byte == RECORDS, "|", [record["user"] for record in byte_by_byte])

# --- a stream that ends mid-record must not be silently accepted -------------
def parse_with_tail_check(chunks):
    buffer = bytearray()
    records = []
    for chunk in chunks:
        buffer.extend(chunk)
        while True:
            newline = buffer.find(b"\n")
            if newline == -1:
                break
            line = bytes(buffer[:newline])
            del buffer[:newline + 1]
            if line.strip():
                records.append(json.loads(line.decode("utf-8")))
    truncated = bytes(buffer)
    return records, truncated


complete_records, tail = parse_with_tail_check(chunked(PAYLOAD, 5))
print("after a complete stream the tail is empty:", tail == b"",
      "| records:", len(complete_records))
truncated_payload = PAYLOAD[:-6]
_partial, partial_tail = parse_with_tail_check(chunked(truncated_payload, 5))
try:
    json.loads(partial_tail.decode("utf-8"))
    print("truncated tail parsed: unexpected")
except json.JSONDecodeError as exc:
    print("truncated tail is not a record:", exc.msg, "| bytes left:", len(partial_tail))

assert len(RECORDS) == 3 and all("user" in record for record in RECORDS)
assert [record["user"] for record in buffered_ingest(chunked(PAYLOAD, 7))[0]] == \
       ["caf\u00e9", "\u00e9lodie", "bj\u00f6rn"]
assert [record["user"] for record in buffered_ingest(chunked(PAYLOAD, 1))[0]] == \
       ["caf\u00e9", "\u00e9lodie", "bj\u00f6rn"]
assert byte_by_byte == RECORDS
naive_small, fragments_small = naive_ingest(chunked(PAYLOAD, 7))
assert len(naive_small) != 3 or fragments_small > 0, "the naive parser must lose or mangle records"
assert any(record.get("user") != RECORDS[index]["user"]
           for index, record in enumerate(naive_small)) or fragments_small > 0
assert one[:4].decode("utf-8", errors="ignore") == "caf"
assert one[:4].decode("utf-8", errors="replace").endswith("\ufffd")
assert tail == b"" and len(complete_records) == 3
assert partial_tail and len(_partial) < 3
print("PASS")
@@end

@expect_output
payload: 181 bytes | 3 records
chunk size   7: naive 0 records / 27 fragments [] | buffered 3 records, correct: True
chunk size  13: naive 0 records / 16 fragments [] | buffered 3 records, correct: True
chunk size  64: naive 1 records / 4 fragments ['café'] | buffered 3 records, correct: True
chunk size 178: naive 2 records / 2 fragments ['café', 'élodie'] | buffered 3 records, correct: True
bytes of 'café': b'caf\xc3\xa9'
split after the first accent byte: b'caf\xc3' + b'\xa9'
errors='ignore' deletes it entirely: 'caf' + ''
strict decoding raised: unexpected end of data
errors='replace' at least shows the damage: 'caf�'
incremental decoder handles the split: 'café'
byte-by-byte parsing yields the same records: True | ['café', 'élodie', 'björn']
after a complete stream the tail is empty: True | records: 3
truncated tail is not a record: Unterminated string starting at | bytes left: 55
PASS
@@end

@notes
Shows the same byte stream parsed at four chunk sizes and pins the difference: the naive
per-chunk parser loses or mangles records at sizes 7 and 13 (fragments that are not JSON,
and names whose accents have been deleted by `errors="ignore"`), while the buffering
parser returns exactly the three original records at every size - including byte-by-byte,
which is the worst case for both the record boundary and the multi-byte character. The
corruption is isolated: the two halves of `café`'s accent byte are shown decoding to `caf`
under `errors="ignore"` (silently), raising `UnicodeDecodeError` under the default
(strictly), producing `\ufffd` under `errors="replace"`, and being reassembled correctly by
an incremental decoder. The last section pins the framing rule that a stream ending
mid-record is truncation, not a record: a complete stream leaves an empty tail, a
truncated one leaves bytes that `json.loads` rejects.
@@end
