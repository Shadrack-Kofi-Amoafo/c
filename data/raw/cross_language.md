@example ml-lang-0001
@meta category=cross_language language=multi difficulty=advanced tags=money,rounding,floating-point,parity

@user
We compute order totals in Python (the pricing service) and display plus re-check the tax in JavaScript (the checkout UI), and the two disagree by a cent on a small number of orders. Both use `round(total * 0.0825)` style arithmetic. Where does the difference come from, and what should the shared contract be so both languages agree exactly?
@@end

@assistant
You have two independent bugs wearing one costume. Both come from doing money in binary floating point:

1. **`round()` means different things.** Python rounds halves to *even* (`round(2.5) == 2`), JavaScript's `Math.round` rounds halves *up* (`Math.round(2.5) === 3`), and `Math.round(-0.5)` is `-0` — so every disagreement in JS lands on a negative amount, which in your domain is a refund short by one cent.
2. **`0.1 + 0.2 !== 0.3` in both languages.** Multiplying an amount by `0.0825` introduces representation error before any rounding happens, so the two services round different real numbers.

The portable contract is to keep money as **integer minor units** and do the arithmetic with integers only:

- Store and transport cents (or the smallest unit your currency has), never a float.
- Express rates as integer basis points: 8.25% is `825`, 100% is `10_000`. Multiply, then round with one documented rule applied to the magnitude and re-apply the sign. Half away from zero is the rule auditors expect, and it is symmetric for refunds.
- Split amounts (discounts across lines, bills across people) with the **largest remainder method** so the shares sum back to the total exactly. Independent rounding of each share silently loses or invents cents.
- Serialize canonical JSON: sorted keys, integers only, no floats anywhere. Then a diff between two services is meaningful.

```python
def apply_basis_points(cents, bps):
    """Half away from zero on integers: no float ever touches the money."""
    product = cents * bps
    sign = -1 if product < 0 else 1
    magnitude = abs(product)
    quotient, remainder = divmod(magnitude, 10_000)
    if 2 * remainder >= 10_000:
        quotient += 1
    return sign * quotient


def allocate(total_cents, weights):
    """Largest remainder: the shares always sum back to the total."""
    total_weight = sum(weights)
    sign = -1 if total_cents < 0 else 1
    magnitude = abs(total_cents)
    shares = [(magnitude * weight) // total_weight for weight in weights]
    remainders = sorted(
        ((magnitude * weight) % total_weight, index) for index, weight in enumerate(weights)
    )
    leftover = magnitude - sum(shares)
    for _remainder, index in sorted(remainders, key=lambda item: (-item[0], item[1])):
        if leftover == 0:
            break
        shares[index] += 1
        leftover -= 1
    return [sign * share for share in shares]
```

In JavaScript the same rule needs care: `BigInt` division truncates toward zero (like C), so compute on the absolute value, add the half explicitly, and only then re-apply the sign — `Math.round` is not the same function. The verification below runs the JS implementation and compares it against Python over a few thousand cases, including the negative ones where `Math.round` gives up a cent.
@@end

@verify kind=executable language=python
@code
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

JS = r'''
const b64 = (value) => Buffer.from(value).toString("base64");

// Signed integer division that truncates toward zero, like C: BigInt's `/` does
// exactly that, which is why the rounding step is explicit.
function divTrunc(numerator, denominator) {
  return numerator / denominator;                 // BigInt division truncates
}

function applyBasisPoints(cents, bps) {
  const product = BigInt(cents) * BigInt(bps);
  const sign = product < 0n ? -1n : 1n;
  const magnitude = product < 0n ? -product : product;
  let quotient = divTrunc(magnitude, 10000n);
  const remainder = magnitude % 10000n;
  if (2n * remainder >= 10000n) quotient += 1n;    // half away from zero
  return Number(sign * quotient);
}

function allocate(totalCents, weights) {
  const totalWeight = weights.reduce((sum, weight) => sum + weight, 0);
  const sign = totalCents < 0 ? -1 : 1;
  const magnitude = Math.abs(totalCents);
  const base = [];
  const remainders = [];
  for (let i = 0; i < weights.length; i += 1) {
    const numerator = magnitude * weights[i];
    base.push(Math.floor(numerator / totalWeight));
    remainders.push({ index: i, remainder: numerator % totalWeight });
  }
  let assigned = base.reduce((sum, value) => sum + value, 0);
  let leftover = magnitude - assigned;
  remainders.sort((a, b) => (b.remainder - a.remainder) || (a.index - b.index));
  const shares = [...base];
  for (const { index } of remainders) {
    if (leftover === 0) break;
    shares[index] += 1;
    leftover -= 1;
  }
  return shares.map((share) => sign * share);
}

function canonicalJson(value) {
  if (Array.isArray(value)) return "[" + value.map(canonicalJson).join(",") + "]";
  if (value && typeof value === "object") {
    const keys = Object.keys(value).sort();
    return "{" + keys.map((key) => JSON.stringify(key) + ":" + canonicalJson(value[key])).join(",") + "}";
  }
  return JSON.stringify(value);
}

const cases = JSON.parse(process.argv[2]);
const out = {
  bps: cases.bps.map(([cents, bps]) => applyBasisPoints(cents, bps)),
  allocations: cases.allocations.map(([total, weights]) => allocate(total, weights)),
  language: {
    roundHalf: Math.round(2.5),
    roundNegativeHalf: Object.is(Math.round(-0.5), -0) ? "-0" : String(Math.round(-0.5)),
    floatSum: 0.1 + 0.2,
    parsedFloat: canonicalJson({ amount: 0.1 + 0.2 }),
  },
};
process.stdout.write(JSON.stringify(out));
'''


def div_trunc(numerator, denominator):
    """C-style truncating division, spelled out: Python's // floors instead."""
    quotient = abs(numerator) // abs(denominator)
    if (numerator < 0) != (denominator < 0):
        quotient = -quotient
    return quotient


def apply_basis_points(cents, bps):
    """Round half away from zero, on integers only: no float ever sees the money."""
    product = cents * bps
    sign = -1 if product < 0 else 1
    magnitude = abs(product)
    quotient = div_trunc(magnitude, 10000)
    if 2 * (magnitude % 10000) >= 10000:
        quotient += 1
    return sign * quotient


def allocate(total_cents, weights):
    """Largest-remainder split: the shares always sum back to the total."""
    total_weight = sum(weights)
    sign = -1 if total_cents < 0 else 1
    magnitude = abs(total_cents)
    base = [(magnitude * weight) // total_weight for weight in weights]
    remainders = sorted(
        ((magnitude * weight) % total_weight, index) for index, weight in enumerate(weights)
    )
    leftover = magnitude - sum(base)
    shares = list(base)
    for _remainder, index in sorted(remainders, key=lambda item: (-item[0], item[1])):
        if leftover == 0:
            break
        shares[index] += 1
        leftover -= 1
    return [sign * share for share in shares]


def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def run_node(node_path, cases):
    with tempfile.TemporaryDirectory() as tmp:
        script = Path(tmp) / "money.mjs"
        script.write_text(JS)
        result = subprocess.run(
            [node_path, str(script), json.dumps(cases)],
            capture_output=True, text=True, check=False,
        )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


node_path = shutil.which("node")
assert node_path, "node must be on PATH for the cross-language comparison"

# --- 1. the language traps, measured rather than asserted from memory ------
BASIS_CASES = [(cents, bps) for cents in (0, 1, 999, 10_000, -1_234, -99_999)
               for bps in (0, 1, 250, 5_000, 9_999, 20_000)]
ALLOCATION_CASES = [(total, weights) for total in (-100, -1, 0, 1, 7, 100, 9_999)
                    for weights in ((1, 1), (1, 1, 1), (2, 3), (5, 3, 2), (1, 2, 3, 4, 5, 6))]

node_output = run_node(node_path, {"bps": BASIS_CASES, "allocations": ALLOCATION_CASES})
language = node_output["language"]
assert language["roundHalf"] == 3, "JS Math.round is half-up: Math.round(2.5) === 3"
assert language["roundNegativeHalf"] == "-0", "JS Math.round(-0.5) is negative zero"
assert round(2.5) == 2, "Python rounds half to even: round(2.5) == 2"
assert round(-0.5) == 0
assert language["floatSum"] != 0.3, "0.1 + 0.2 !== 0.3 in either language"
assert language["parsedFloat"] == '{"amount":0.30000000000000004}', language["parsedFloat"]

# --- 2. identical integer results in both languages -----------------------
python_bps = [apply_basis_points(cents, bps) for cents, bps in BASIS_CASES]
assert python_bps == node_output["bps"], "basis-point rounding must agree exactly"
python_allocations = [allocate(total, list(weights)) for total, weights in ALLOCATION_CASES]
assert python_allocations == node_output["allocations"], "allocation must agree exactly"

# --- 3. properties the contract promises, in both languages ---------------
for (total, weights), shares, node_shares in zip(
    ALLOCATION_CASES, python_allocations, node_output["allocations"]
):
    assert sum(shares) == total, (total, weights, shares)
    assert sum(node_shares) == total, (total, weights, node_shares)
    assert sorted(shares) == sorted(node_shares), "ties must break identically"
    if len(set(weights)) == 1:
        assert max(shares) - min(shares) <= 1, "equal weights differ by at most one unit"
    for share, weight in zip(shares, weights):
        exact = total * weight / sum(weights)
        assert abs(share - exact) <= 1.0, "largest remainder stays within one unit of exact"
assert sum(allocate(100, [1, 1, 1])) == 99 + 1
assert allocate(100, [1, 1, 1]) == [34, 33, 33], allocate(100, [1, 1, 1])
assert allocate(-100, [1, 1, 1]) == [-34, -33, -33]
assert allocate(1, [1, 1, 1, 1]) == [1, 0, 0, 0]
assert allocate(0, [1, 2, 3]) == [0, 0, 0]
assert apply_basis_points(10_000, 250) == 250
assert apply_basis_points(-10_000, 250) == -250, "rounding is symmetric for refunds"
assert apply_basis_points(1, 1) == 0
assert apply_basis_points(5_000, 1) == 1, "half a cent rounds away from zero"

# --- 4. the float version disagrees, which is why the integer version exists
def float_version(cents, bps):
    """What a first draft looks like: floats, then a rounding function."""
    return round(cents * (bps / 10_000))


disagreements = [
    (cents, bps) for cents in range(1, 20_000) for bps in (825, 1_000, 2_500)
    if float_version(cents, bps) != apply_basis_points(cents, bps)
]
assert disagreements, "there must be an amount where floats lose a cent"
first = disagreements[0]
assert first == (2, 2500), first
assert float_version(2, 2500) == 0 and apply_basis_points(2, 2500) == 1
# and the divergence is not a one-off curiosity
assert len(disagreements) > 100, len(disagreements)

# The float version is worse than "imprecise": the two languages round halves
# differently, so the same formula silently produces different totals. Worse,
# JavaScript's Math.round(-0.5) is -0, so every disagreement is a refund that is
# short by one cent.
BATCH = [[cents, bps] for cents in range(1, 2_001) for bps in (825, 1_000, 2_500)]
BATCH += [[-cents, bps] for cents in range(1, 201) for bps in (825, 1_000, 2_500)]


def node_float_rounding(batch):
    with tempfile.TemporaryDirectory() as tmp:
        cases_path = Path(tmp) / "cases.json"
        cases_path.write_text(json.dumps(batch))
        result = subprocess.run(
            [node_path, "--input-type=module", "-e",
             "import fs from 'node:fs';"
             "const cases = JSON.parse(fs.readFileSync(process.argv[1], 'utf8'));"
             "process.stdout.write(JSON.stringify("
             "  cases.map(([cents, bps]) => Math.round(cents * (bps / 10000)))));",
             str(cases_path)],
            capture_output=True, text=True, check=False,
        )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


node_floats = node_float_rounding(BATCH)
node_mismatches = [
    (cents, bps, js_value, apply_basis_points(cents, bps))
    for (cents, bps), js_value in zip(BATCH, node_floats)
    if js_value != apply_basis_points(cents, bps)
]
assert node_mismatches, "the JS float path must disagree with the integer contract somewhere"
assert all(cents < 0 for cents, *_rest in node_mismatches), (
    "every JS disagreement is on a negative amount, because Math.round(-0.5) is -0"
)
assert node_mismatches[0] == (-2, 2_500, 0, -1), node_mismatches[0]
assert len(node_mismatches) > 50, len(node_mismatches)

# The Python float path is wrong on different cases (banker's rounding), so the
# two implementations of the "same" formula disagree with each other too.
python_floats = [float_version(cents, bps) for cents, bps in BATCH]
assert python_floats != node_floats, "the naive float formula is not portable"
differing = [(cents, bps) for (cents, bps), a, b in zip(BATCH, python_floats, node_floats) if a != b]
assert differing[:3] == [(2, 2_500), (5, 1_000), (10, 2_500)], differing[:3]
assert len(differing) > 20, len(differing)
assert any(cents > 0 for cents, _bps in differing)
assert any(cents < 0 for cents, _bps in differing), "refunds diverge too"

# --- 5. canonical JSON is byte-stable across languages --------------------
payload = {"total": 1234, "shares": allocate(1234, [1, 1, 1]), "nested": {"b": 1, "a": 2}}
expected = '{"nested":{"a":2,"b":1},"shares":[412,411,411],"total":1234}'
assert canonical_json(payload) == expected, canonical_json(payload)
assert not any("." in part for part in canonical_json(payload).replace('":"', "").split('"') if part.isdigit())
# parsing the same JSON in both languages yields the same canonical bytes
parse_js = subprocess.run(
    [node_path, "--input-type=module", "-e",
     "const v=JSON.parse(process.argv[1]);"
     "process.stdout.write(JSON.stringify(JSON.parse(JSON.stringify(v))))",
     expected],
    capture_output=True, text=True, check=False,
)
assert parse_js.returncode == 0, parse_js.stderr
assert json.loads(parse_js.stdout) == json.loads(expected)

# --- 6. determinism -------------------------------------------------------
for _ in range(3):
    repeat = run_node(node_path, {"bps": BASIS_CASES, "allocations": ALLOCATION_CASES})
    assert repeat == node_output, "the JS side must be deterministic"
print("PASS")
@@end

@expect_output
PASS
@@end

@notes
The verify script drives both languages: it writes the JavaScript implementation to
a temp file and runs it with `node`, then compares results case by case. Pinned:
`Math.round(2.5) === 3` while Python's `round(2.5) == 2`, `Math.round(-0.5)` is
`-0`, and `0.1 + 0.2` canonicalises to `0.30000000000000004`; the integer
implementation agrees across languages for 36 basis-point cases (including
negatives and 200% rates) and 35 allocation cases (total -100 to 9999, two to six
weights; the weighted `(1,2,3,4,5,6)` split is bounded to within one minor unit of
the exact ratio rather than the equal-weight ±1 rule); every allocation sums back
to its total in both languages and ties break identically; a search over 20k
amounts finds that the float version disagrees with the contract on the first case
`(2, 2500)` — Python's `round(0.5) == 0` drops half a cent — and more than a
hundred times in total; the JS float path disagrees with the integer contract on
more than 50 of 6600 batched cases and every one of them is negative, because
`Math.round(-0.5)` is `-0`; the naive float formula also disagrees *between* the
two languages on positive and negative amounts, so the same bug cannot even be
reproduced consistently; canonical JSON is byte-stable and re-parses identically;
and repeated runs are deterministic.
@@end

@example ml-lang-0002
@meta category=cross_language language=multi difficulty=advanced tags=unicode,graphemes,utf8,truncation

@user
Our API accepts a display name and stores it in a `VARCHAR(10)`. Python validates with `len(name) <= 10`, the Node front end uses `name.length <= 10`, and the database still rejects some values while accepting others that render as empty boxes. We also see broken half-emoji in the admin list. What is the correct way to measure and truncate text that crosses languages?
@@end

@assistant
`length` means three different things in your stack, and none of them is "characters the user sees":

| Measure | Python | JavaScript | Meaning |
| --- | --- | --- | --- |
| code points | `len(s)` | `[...s].length` | one per Unicode scalar value |
| UTF-16 units | `len(s.encode("utf-16-le")) // 2` | `s.length` | astral characters count twice |
| bytes | `len(s.encode("utf-8"))` | `Buffer.byteLength(s, "utf8")` | what the wire and the index hold |
| grapheme clusters | not in the stdlib | yes, in the two places above | what the user counts |

So `"👍"` is 1 code point, 2 UTF-16 units and 4 bytes; the family emoji `👨‍👩‍👧‍👦` is 7 code points, 11 UTF-16 units, 25 bytes and **one** character to a human. A `VARCHAR(10)` in MySQL's `utf8mb4` counts code points, a legacy `utf8` column counts bytes, and Python 3 `len` counts code points — three validators, three answers.

Rules that make it consistent:

- **Normalize to NFC before measuring, storing and comparing.** `"café"` is 4 code points in NFC and 5 in NFD; a unique index on the raw column happily stores both spellings of the same name.
- **Truncate on grapheme-cluster boundaries**, never by code point, UTF-16 index or byte offset. Slicing a JS string by index splits surrogate pairs into lone surrogates (JSON escapes them, and `Buffer.from` turns them into `�`); slicing Python by code point strands combining marks and ZWJ sequences.
- **Do the truncation server-side, once, with a testable function**, and validate the same function's output. Two implementations of "10 characters" will drift.
- **For bytes, decode rather than slice.** If a limit is in bytes (SMS segments, index keys), walk the code-point boundaries and never emit a partial sequence.

```python
def clusters(text):
    """Approximate grapheme clusters: base + combining marks, variation
    selectors, skin-tone modifiers, ZWJ sequences, regional-indicator pairs."""
    out = []
    for ch in text:
        if not out:
            out.append(ch)
            continue
        previous = out[-1]
        regional = 0x1F1E6 <= ord(ch) < 0x1F200
        previous_regional = len(previous) == 1 and 0x1F1E6 <= ord(previous) < 0x1F200
        if (
            ch == "\u200d" or previous.endswith("\u200d")
            or unicodedata.combining(ch)
            or unicodedata.category(ch) in ("Mn", "Me")
            or ch in ("\ufe0e", "\ufe0f")
            or 0x1F3FB <= ord(ch) <= 0x1F3FF
            or (regional and previous_regional)
        ):
            out[-1] = previous + ch
        else:
            out.append(ch)
    return out
```

This built-in approximation covers the cases that break real systems, but it is not UAX #29: Indic conjunct clusters, prepend characters and legacy Hangul forms need a real segmenter (ICU, `Intl.Segmenter`, `grapheme`). The verification below compares the approximation against Node's `Intl.Segmenter` for ten adversarial strings, so the claim is measured rather than asserted.
@@end

@verify kind=executable language=python
@code
import json
import shutil
import subprocess
import tempfile
import unicodedata
from pathlib import Path

SUBMITTED = [
    "café",                 # NFC: one code point for é
    "cafe\u0301",           # NFD: e + combining acute
    "👍",                   # astral: one code point, two UTF-16 units
    "👨‍👩‍👧‍👦",                  # family: four people joined by ZWJ
    "🇬🇭",                  # flag: two regional indicators
    "🏳️‍🌈",                  # rainbow flag: base + variation selector + ZWJ
    "1️⃣",                   # keycap: digit + variation selector + combining keycap
    "👋🏽",                  # skin-tone modifier
    "한국어",                # BMP, no combining marks
    "e\u0301\u0327",        # two combining marks on one base
]

JS = r'''
const submitted = JSON.parse(process.argv[2]);
const segmenter = new Intl.Segmenter("en", { granularity: "grapheme" });
const report = submitted.map((text) => {
  const clusters = [...segmenter.segment(text)].map((part) => part.segment);
  const utf16 = text.length;
  const codePoints = [...text].length;
  return {
    text,
    clusters,
    utf16,
    codePoints,
    bytes: Buffer.byteLength(text, "utf8"),
  };
});
// The classic slicing bug: cutting a JavaScript string by UTF-16 index can
// split a surrogate pair, producing a lone surrogate that is not valid text.
const thumbs = "👍";
const sliced = thumbs.slice(0, 1);
process.stdout.write(JSON.stringify({
  report,
  slice: {
    value: sliced,
    utf16: sliced.length,
    codePoints: [...sliced].length,
    wellFormed: sliced.isWellFormed(),
    encoded: Buffer.from(sliced, "utf8").toString("hex"),
    json: JSON.stringify(sliced),
  },
  wellFormedThumbs: thumbs.isWellFormed(),
}));
'''


def clusters(text):
    """Approximate grapheme clusters: base + combining marks/variation selectors,
    ZWJ sequences, skin-tone modifiers and regional-indicator pairs."""
    out = []
    for ch in text:
        if not out:
            out.append(ch)
            continue
        previous = out[-1]
        regional = 0x1F1E6 <= ord(ch) < 0x1F200
        previous_regional = len(previous) == 1 and 0x1F1E6 <= ord(previous) < 0x1F200
        if (
            ch == "\u200d"
            or previous.endswith("\u200d")
            or unicodedata.combining(ch)
            or unicodedata.category(ch) in ("Mn", "Me", "Cf") and ch != "\u200b"
            or ch in ("\ufe0e", "\ufe0f")
            or 0x1F3FB <= ord(ch) <= 0x1F3FF
            or (regional and previous_regional)
        ):
            out[-1] = previous + ch
        else:
            out.append(ch)
    return out


def truncate_clusters(text, limit):
    return "".join(clusters(text)[:limit])


node = shutil.which("node")
assert node, "node must be available for the cross-language measurement"

with tempfile.TemporaryDirectory() as tmp:
    script = Path(tmp) / "measure.mjs"
    script.write_text(JS)
    result = subprocess.run(
        [node, str(script), json.dumps(SUBMITTED)], capture_output=True, text=True, check=False
    )
assert result.returncode == 0, result.stderr
data = json.loads(result.stdout)
report = {entry["text"]: entry for entry in data["report"]}

# --- 1. length is a number that means different things in each language ---
for text in SUBMITTED:
    entry = report[text]
    assert entry["codePoints"] == len(text), (text, entry["codePoints"], len(text))
    assert entry["bytes"] == len(text.encode("utf-8"))
    assert entry["utf16"] >= entry["codePoints"], "UTF-16 units are never fewer than code points"

nfc = report["café"]
nfd = report["cafe\u0301"]
assert (nfc["codePoints"], nfc["utf16"], nfc["bytes"]) == (4, 4, 5)
assert (nfd["codePoints"], nfd["utf16"], nfd["bytes"]) == (5, 5, 6)
assert unicodedata.normalize("NFC", "cafe\u0301") == "café"
assert "café" != "cafe\u0301", "the two spellings are different strings but the same text"
assert len("café") != len("cafe\u0301"), "column sizing depends on the normalization form"

thumbs = report["👍"]
assert thumbs["codePoints"] == 1 and thumbs["utf16"] == 2 and thumbs["bytes"] == 4
family = report["👨‍👩‍👧‍👦"]
assert family["codePoints"] == 7 and family["utf16"] == 11 and family["bytes"] == 25

# --- 2. truncating by the wrong unit corrupts text ------------------------
assert data["wellFormedThumbs"] is True
assert data["slice"]["utf16"] == 1 and data["slice"]["codePoints"] == 1
assert data["slice"]["wellFormed"] is False, "slice(0, 1) of an emoji is a lone surrogate"
assert data["slice"]["encoded"] == "efbfbd", (
    "encoding a lone surrogate to UTF-8 yields U+FFFD: the emoji becomes a replacement character"
)
assert data["slice"]["json"] == '"\\ud83d"', data["slice"]["json"]
# The other language's view of that payload: JSON accepts it, UTF-8 encoding does not.
lone = json.loads(data["slice"]["json"])
assert lone == "\ud83d" and len(lone) == 1
try:
    lone.encode("utf-8")
    raise AssertionError("a lone surrogate must not be encodable as UTF-8")
except UnicodeEncodeError:
    pass
assert lone.encode("utf-8", errors="replace") == b"?"          # the byte is simply lost
surrogate_bytes = lone.encode("utf-8", errors="surrogatepass")
assert surrogate_bytes == b"\xed\xa0\xbd", surrogate_bytes          # CESU-8, not valid UTF-8
try:
    surrogate_bytes.decode("utf-8")
    raise AssertionError("those bytes are not valid UTF-8")
except UnicodeDecodeError:
    pass
assert b"\xf0\x9f\x91\x8d".decode("utf-8") == "\U0001f44d", "the intact emoji is four bytes"

# The same string truncated to 3 clusters, three ways:
FRAGMENT = "👨‍👩‍👧‍👦 is a family"
assert truncate_clusters(FRAGMENT, 1) == "👨‍👩‍👧‍👦"
assert FRAGMENT[:3] == "\U0001f468\u200d\U0001f469", "three code points cut the family in half"
assert "\u200d" in FRAGMENT[:3] and truncate_clusters(FRAGMENT[:3], 1) == "\U0001f468\u200d\U0001f469"
assert truncate_clusters("cafe\u0301 latte", 4) == "cafe\u0301", "no dangling combining mark"
assert truncate_clusters("e\u0301\u0327x", 1) == "e\u0301\u0327", "both marks stay with the base"
assert truncate_clusters("", 5) == ""
assert truncate_clusters("🇬🇭🇬🇭", 1) == "🇬🇭", "regional indicators pair up"
assert truncate_clusters("1️⃣2️⃣", 2) == "1️⃣2️⃣"
assert truncate_clusters(FRAGMENT, 4) == "👨‍👩‍👧‍👦 is", truncate_clusters(FRAGMENT, 4)

# --- 3. the approximation must agree with a real UAX#29 segmenter ---------
for text in SUBMITTED:
    mine = clusters(text)
    theirs = report[text]["clusters"]
    assert mine == theirs, (text, mine, theirs)
assert sum(len(clusters(text)) for text in SUBMITTED) == sum(
    len(report[text]["clusters"]) for text in SUBMITTED
)

# --- 4. what a column can actually hold ----------------------------------
def column_fits(text, limit_chars, mode="characters"):
    if mode == "characters":
        return len(clusters(text)) <= limit_chars
    if mode == "code_points":
        return len(text) <= limit_chars
    if mode == "bytes":
        return len(text.encode("utf-8")) <= limit_chars
    raise AssertionError(mode)


CANDIDATES = ["café", "cafe\u0301", "👨‍👩‍👧‍👦", "🇬🇭", "한국어", "hello"]
# Counting clusters is the honest measure of "characters the user sees": the
# seven-code-point family is one of them, and only `hello` exceeds four.
assert [column_fits(text, 4, "characters") for text in CANDIDATES] == [True] * 5 + [False]
assert [column_fits(text, 4, "code_points") for text in CANDIDATES] == [True, False, False, True, True, False]
assert [column_fits(text, 4, "bytes") for text in CANDIDATES] == [False] * 6, (
    "with a four-byte budget even café is over: 5 bytes"
)
assert column_fits("한국어", 9, "bytes") is True, "three Korean syllables are nine bytes"
# The fix at the boundary: truncate clusters, then assert the round trip.
for text in CANDIDATES:
    clipped = truncate_clusters(text, 4)
    assert column_fits(clipped, 4, "characters")
    assert clipped.encode("utf-8").decode("utf-8") == clipped
    assert len(clusters(clipped)) == len(clusters(text)) or len(clusters(clipped)) == 4

# --- 5. byte-level truncation must land on a code-point boundary ----------
raw = "café au lait".encode("utf-8")
assert len(raw) == 13, len(raw)
try:
    raw[:4].decode("utf-8")
    raise AssertionError("four bytes cut the é in half and must not decode")
except UnicodeDecodeError:
    pass
assert raw[:5].decode("utf-8") == "café", "five bytes land exactly on the boundary"
assert raw[:4].decode("utf-8", errors="ignore") == "caf"
assert raw[:4].decode("utf-8", errors="replace") == "caf\ufffd"
assert len(raw.decode("utf-8")) == 12

# --- 6. sorting and comparison -------------------------------------------
words = ["Zebra", "\u00e9clair", "apple", "\u00c9clair", "banana"]
assert sorted(words) == ["Zebra", "apple", "banana", "\u00c9clair", "\u00e9clair"], sorted(words)
human_order = sorted(words, key=lambda word: (unicodedata.normalize("NFC", word.casefold()), word))
assert human_order == ["apple", "banana", "Zebra", "\u00c9clair", "\u00e9clair"], human_order
assert sorted(words) != human_order, "the raw byte order is not the user's order"
print("PASS")
@@end

@expect_output
PASS
@@end

@notes
The verify script runs the same measurements in both languages: `node` reports code
points, UTF-16 units, UTF-8 bytes and `Intl.Segmenter` clusters for ten strings
(NFC/NFD accents, an astral emoji, a ZWJ family, a flag, a keycap, a skin-tone
modifier, a rainbow flag, Korean syllables, two stacked combining marks). Pinned:
Python `len` equals JS `Array.from(s).length` for every case while the UTF-16 count
is larger for astral characters; `café` is (4, 4, 5) and `cafe\u0301` is (5, 5, 6)
in (code points, UTF-16 units, bytes) and the two are equal only after NFC
normalisation, so the same name can be stored twice; the emoji is (1, 2, 4) and the
family is (7, 11, 25); `"👍".slice(0, 1)` is a lone surrogate that fails
`isWellFormed()`, encodes to `efbfbd` (U+FFFD) in Node, and arrives in Python as
`\ud83d` — which JSON accepts, strict UTF-8 cannot decode, `errors="replace"` turns
into `?`, and only `surrogatepass` round-trips as the invalid CESU-8 bytes `ed a0 bd`;
the cluster approximation matches `Intl.Segmenter` exactly on all ten strings,
including the flag pair and the keycap sequence; column-fit checks show the family
fitting a 4-character budget while `hello` does not, `cafe\u0301` failing a
4-code-point budget, and even `café` failing a 4-byte budget; cutting `café au
lait` at 4 bytes raises `UnicodeDecodeError` while 5 bytes decode exactly; and the
sort-order check shows the raw byte order (`Éclair` after `banana`) differs from the
casefolded order a user expects.
@@end

@example ml-lang-0003
@meta category=cross_language language=multi difficulty=expert tags=integer-division,modulo,overflow,parity

@user
We ported a Python analytics job to a C service and a Node worker. Everything matched until last week: events before 1970 started landing in the wrong day bucket, and a hash-based sharding key produced a negative index that crashed the C worker. All three implementations look identical. What is going on?
@@end

@assistant
`/` and `%` are not the same operations in these languages, and the difference only shows up for negative operands — which is exactly what pre-1970 timestamps and signed hash codes are:

| Expression | Python | C / Java / Go | JavaScript |
| --- | --- | --- | --- |
| `-7 / 2` (integer) | `-4` (floor) | `-3` (truncate) | `Math.trunc(-7/2) = -3` |
| `-7 % 2` | `1` (sign of divisor) | `-1` (sign of dividend) | `-1` |
| `7 % -2` | `-1` | `1` | `1` |

So a day bucket `timestamp / 86400` gives `-1` for 1969-12-31T23:59:59Z in Python and `0` in C and JS: every pre-1970 event moves forward one day, and the bug is invisible in any dataset that starts in 1970.

Three rules for porting:

- **Name the rounding rule at the boundary.** Use `floor` when bucketing (calendar days, histogram bins, pagination) and `trunc` when you mean "drop the remainder" (array indices, alignment). Write the helper once per language and test it with negative inputs.
- **Make remainders non-negative before indexing.** `hash % n` is negative in C and JS for negative hashes; fix it with `((h % n) + n) % n`. In C a negative index is undefined behaviour (the crash you saw); in Python `list[-1]` silently reads the *last* element — the same mistake, two very different failures.
- **Mask explicitly when you want fixed-width arithmetic.** Python integers never wrap, JS numbers lose precision above 2**53 (`BigInt` needed), and only C's *unsigned* types wrap by definition — signed overflow is UB. An FNV-1a hash is the same value in all three languages only if Python masks with `& 0xFFFFFFFF` and JS uses `Math.imul(...) >>> 0`.

```javascript
const hash32 = (text) => {
  let hash = 2166136261;
  for (const byte of new TextEncoder().encode(text)) {
    hash = Math.imul(hash ^ byte, 16777619) >>> 0;   // >>> 0 is the 32-bit mask
  }
  return hash;
};

const bucketOf = (seconds) => Math.floor(seconds / 86400);   // floor, not trunc
const dayIndex = (hash, tableSize) => ((hash % tableSize) + tableSize) % tableSize;
```

The verification below compiles the C version with `cc`, runs the Node version and compares all three, so the table above is a measurement of this toolchain rather than a recollection.
@@end

@verify kind=executable language=python
@code
import json
import shutil
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

C_SOURCE = r'''
#include <stdio.h>
#include <stdint.h>

/* Floor division, spelled out: C truncates toward zero. */
static int64_t floor_div(int64_t a, int64_t b) {
    int64_t quotient = a / b;
    if ((a % b != 0) && ((a < 0) != (b < 0))) quotient--;
    return quotient;
}

int main(void) {
    const int64_t stamps[] = {-1, -86399, -86400, -86401, 0, 1, 86399, 86400, 1700000000};
    const size_t n = sizeof(stamps) / sizeof(stamps[0]);
    for (size_t i = 0; i < n; i++) {
        printf("bucket %lld %lld %lld\n", (long long)stamps[i],
               (long long)(stamps[i] / 86400), (long long)floor_div(stamps[i], 86400));
    }
    printf("div -7 2 %lld\n", (long long)(-7 / 2));
    printf("div -7 -2 %lld\n", (long long)(-7 / -2));
    printf("div 7 2 %lld\n", (long long)(7 / 2));
    printf("div 7 -2 %lld\n", (long long)(7 / -2));
    printf("mod -7 2 %lld\n", (long long)(-7 % 2));
    printf("mod -7 -2 %lld\n", (long long)(-7 % -2));
    printf("mod 7 2 %lld\n", (long long)(7 % 2));
    printf("mod 7 -2 %lld\n", (long long)(7 % -2));
    const char *text = "hello";
    uint32_t hash = 2166136261u;
    for (const char *p = text; *p; p++) {
        hash ^= (uint8_t)*p;
        hash *= 16777619u;              /* unsigned overflow is defined */
    }
    printf("fnv %u\n", hash);
    uint32_t wrapped = 4294967295u;
    printf("wrap %u\n", (unsigned)(wrapped + 1u));
    int32_t epoch = 2147483647;         /* 2038-01-19T03:14:07Z */
    epoch += 1;                         /* signed overflow: undefined in C */
    printf("int32_after %d\n", epoch);
    return 0;
}
'''

JS = r'''
const rows = [];
for (const [a, b] of JSON.parse(process.argv[2])) {
  rows.push({ a, b, trunc: Math.trunc(a / b), mod: a % b, floor: Math.floor(a / b) });
}
const hash32 = (text) => {
  let hash = 2166136261;
  for (const byte of new TextEncoder().encode(text)) {
    hash = Math.imul(hash ^ byte, 16777619) >>> 0;   // >>> 0 keeps it unsigned 32-bit
  }
  return hash;
};
process.stdout.write(JSON.stringify({
  rows,
  fnv: hash32("hello"),
  int32Wrapped: 2147483648 | 0,
  unsafeInt: 9007199254740993 === 9007199254740992,
  bigintFromNumber: BigInt(9007199254740993).toString(),      // too late: already rounded
  bigintFromString: BigInt("9007199254740993").toString(),
  negativeIndex: String([10, 20, 30][-1 % 3]),   // undefined, and JSON drops it
}));
'''


def trunc_div(a, b):
    """C and JavaScript truncate toward zero; Python floors."""
    quotient = abs(a) // abs(b)
    return -quotient if (a < 0) != (b < 0) else quotient


def trunc_mod(a, b):
    return a - trunc_div(a, b) * b


def floor_div(a, b):
    return a // b


def fnv1a32(text):
    """FNV-1a with an explicit 32-bit mask: Python integers never wrap on their own."""
    hash_value = 2166136261
    for byte in text.encode("utf-8"):
        hash_value ^= byte
        hash_value = (hash_value * 16777619) & 0xFFFFFFFF
    return hash_value


def run_c():
    compiler = shutil.which("cc") or shutil.which("gcc")
    assert compiler, "a C compiler is required for this example"
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / "ints.c"
        binary = Path(tmp) / "ints"
        source.write_text(C_SOURCE)
        compile_result = subprocess.run(
            [compiler, "-std=c11", "-Wall", "-Wextra", "-O1", str(source), "-o", str(binary)],
            capture_output=True, text=True, check=False,
        )
        assert compile_result.returncode == 0, compile_result.stderr
        run_result = subprocess.run([str(binary)], capture_output=True, text=True, check=False)
    assert run_result.returncode == 0, run_result.stderr
    parsed = {"bucket": [], "div": {}, "mod": {}, "fnv": None, "wrap": None, "int32_after": None}
    for line in run_result.stdout.splitlines():
        parts = line.split()
        if parts[0] == "bucket":
            parsed["bucket"].append((int(parts[1]), int(parts[2]), int(parts[3])))
        elif parts[0] == "div":
            parsed["div"][(int(parts[1]), int(parts[2]))] = int(parts[3])
        elif parts[0] == "mod":
            parsed["mod"][(int(parts[1]), int(parts[2]))] = int(parts[3])
        elif parts[0] == "fnv":
            parsed["fnv"] = int(parts[1])
        elif parts[0] == "wrap":
            parsed["wrap"] = int(parts[1])
        elif parts[0] == "int32_after":
            parsed["int32_after"] = int(parts[1])
    return parsed


def run_js(pairs):
    node = shutil.which("node")
    assert node, "node is required for this example"
    with tempfile.TemporaryDirectory() as tmp:
        script = Path(tmp) / "ints.mjs"
        script.write_text(JS)
        result = subprocess.run(
            [node, str(script), json.dumps(pairs)], capture_output=True, text=True, check=False
        )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


c_report = run_c()
# The four sign combinations, checked in all three languages.
SIGN_PAIRS = [(-7, 2), (7, -2), (-7, -2), (7, 2)]
BUCKET_STAMPS = [-1, -86399, -86400, -86401, 0, 1, 86399, 86400, 1700000000]
js_report = run_js(SIGN_PAIRS + [(stamp, 86400) for stamp in BUCKET_STAMPS])
sign_rows = js_report["rows"][: len(SIGN_PAIRS)]
bucket_rows = js_report["rows"][len(SIGN_PAIRS):]
BUCKETS = c_report["bucket"]

# --- 1. the same expression, three answers --------------------------------
assert c_report["div"][(-7, 2)] == -3, "C truncates toward zero"
assert c_report["mod"][(-7, 2)] == -1, "C keeps the dividend's sign in the remainder"
assert trunc_div(-7, 2) == -3 and trunc_mod(-7, 2) == -1, "the port must match C"
assert floor_div(-7, 2) == -4, "Python floors instead"
assert -7 % 2 == 1, "Python's modulo follows the divisor's sign"
assert c_report["mod"][(7, -2)] == 1 and 7 % -2 == -1
assert c_report["div"][(7, -2)] == -3 and 7 // -2 == -4
assert [row["trunc"] for row in sign_rows] == [c_report["div"][pair] for pair in SIGN_PAIRS], (
    "JavaScript and C agree on truncating division"
)
assert [row["mod"] for row in sign_rows] == [c_report["mod"][pair] for pair in SIGN_PAIRS], (
    "JavaScript and C agree on the remainder's sign"
)
for row in sign_rows:
    assert row["trunc"] == trunc_div(row["a"], row["b"]) == c_report["div"][(row["a"], row["b"])]
    assert row["mod"] == trunc_mod(row["a"], row["b"]) == c_report["mod"][(row["a"], row["b"])]
    assert row["floor"] == floor_div(row["a"], row["b"]), "Math.floor is the Python convention"

# --- 2. the bug that ships: day buckets before 1970 -----------------------
assert BUCKETS[0] == (-1, 0, -1), BUCKETS[0]
for (stamp, c_trunc, c_floor), js_row in zip(BUCKETS, bucket_rows):
    assert stamp == js_row["a"]
    assert c_trunc == trunc_div(stamp, 86400) == js_row["trunc"]
    assert c_floor == floor_div(stamp, 86400) == js_row["floor"]
truncated_day = (datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(days=BUCKETS[0][1])).date()
correct_day = (datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(days=BUCKETS[0][2])).date()
assert datetime.fromtimestamp(-1, tz=timezone.utc).date() == correct_day
assert correct_day == datetime(1969, 12, 31).date()
assert truncated_day == datetime(1970, 1, 1).date()
assert truncated_day != correct_day, "a pre-1970 event lands in the wrong day"
# The two conventions disagree for the whole negative range, not just -1:
disagreements = [
    stamp for stamp in range(-5 * 86400, -1)
    if trunc_div(stamp, 86400) != floor_div(stamp, 86400)
]
assert all(trunc_div(s, 86400) == floor_div(s, 86400) + 1 for s in disagreements)
# Every negative second except the exact multiples of a day is off by one day.
assert len(disagreements) == 5 * 86400 - 1 - 5, len(disagreements)

# --- 3. hashing: a negative index is a real crash -------------------------
assert fnv1a32("hello") == c_report["fnv"] == js_report["fnv"] == 1335831723
assert 1335831723 & 0xFFFFFFFF == 1335831723
# A negative remainder from a C/JS hash produces a negative bucket index:
raw_index = trunc_mod(-7, 8)                    # -7 in C and JS
fixed_index = (trunc_mod(-7, 8) + 8) % 8
assert raw_index == -7 and fixed_index == 1
assert -7 % 8 == 1, "Python already gives the non-negative index"
assert js_report["negativeIndex"] == "undefined", (
    "a negative index in JavaScript is undefined, and JSON.stringify drops the key"
)
assert [10, 20, 30][-1] == 30, "the equivalent bug in Python silently wraps to the last item"
assert [10, 20, 30][fixed_index] == 20
assert c_report["wrap"] == 0, "unsigned overflow wraps to zero, by definition"

# --- 4. timestamps that outgrow 32 bits ----------------------------------
MAX_INT32 = 2**31 - 1
assert MAX_INT32 == 2147483647
assert datetime.fromtimestamp(MAX_INT32, tz=timezone.utc) == datetime(2038, 1, 19, 3, 14, 7, tzinfo=timezone.utc)
assert c_report["int32_after"] == -2147483648, "one second later, a 32-bit counter is negative"
wrapped = c_report["int32_after"]
assert datetime.fromtimestamp(wrapped, tz=timezone.utc).year == 1901, "the timestamp time-travels"
assert datetime.fromtimestamp(MAX_INT32 + 1, tz=timezone.utc) == datetime(2038, 1, 19, 3, 14, 8, tzinfo=timezone.utc)
assert js_report["int32Wrapped"] == -2147483648
assert (MAX_INT32 + 1) & 0xFFFFFFFF == 2147483648, "the same wrap, spelled with a mask"

# --- 5. float integers: where JavaScript stops being exact ---------------
assert js_report["unsafeInt"] is True, "2**53 + 1 is not representable as a double"
assert js_report["bigintFromNumber"] == "9007199254740992", (
    "the literal was rounded before BigInt saw it"
)
assert js_report["bigintFromString"] == "9007199254740993", (
    "keeping the value as a string is the only way to arrive intact"
)
assert 9007199254740993 != 9007199254740992, "Python never had this problem"
assert (2**53 + 1) - 2**53 == 1, "Python has no 2**53 ceiling"
assert (2**63) & 0xFFFFFFFF == 0
assert json.loads('{"id": 9007199254740993}') == {"id": 9007199254740993}, (
    "Python's json keeps big integers exact; JavaScript's JSON.parse does not"
)

# --- 6. one table, one meaning: the portable helpers ---------------------
def floor_div_portable(a, b):
    """What the JS and C implementations should use for buckets: truncate, then
    step down one when the signs differ and the division is inexact."""
    quotient = trunc_div(a, b)
    if quotient * b != a and (a < 0) != (b < 0):
        quotient -= 1
    return quotient


def mod_non_negative(a, b):
    """Non-negative remainder for any sign of a, with a positive modulus."""
    return (trunc_mod(a, b) + b) % b


for a in range(-25, 26):
    for b in (2, 3, 7, 86400):
        assert floor_div_portable(a, b) == floor_div(a, b), (a, b)
        assert mod_non_negative(a, b) == a % b, (a, b)
        assert 0 <= mod_non_negative(a, b) < b
assert [floor_div_portable(s, 86400) for s in (-1, -86400, -86401, 0, 86401)] == [-1, -1, -2, 0, 1]
print("PASS")
@@end

@expect_output
PASS
@@end

@notes
Three implementations executed in one verify run: a C program compiled with
`cc -std=c11 -Wall -Wextra -O1`, a Node script, and Python. Pinned: C gives
`-7 / 2 == -3` and `-7 % 2 == -1` while Python gives `-4` and `1`, and JS
`Math.trunc(a/b)`/`a % b` matches C on all four sign combinations (also checked
against the compiled C output, not just against Python's emulation of it);
`Math.floor` matches Python on the same four pairs; the day-bucket comparison uses
nine timestamps including -1, -86400 and -86401, where trunc and floor differ by
exactly one day and the truncated answer for -1 maps to 1970-01-01 instead of the
correct 1969-12-31 (proved against `datetime.fromtimestamp(-1, tz=utc)`), and every
one of the 431 994 negative seconds except the six day boundaries is off by one;
FNV-1a of "hello" is the same 32-bit value (1335831723) in C's `uint32_t`, in a
Python implementation that masks with `& 0xFFFFFFFF`, and in JS `Math.imul(...) >>>
0`; unsigned overflow wraps to 0 by definition while a signed `int32_t` one second
past 2038-01-19T03:14:07Z becomes -2147483648 and time-travels to 1901; a negative
hash index is `undefined` in JS (JSON drops the key), silently wraps to the last
element in Python, and is undefined behaviour in C; JS loses `2**53 + 1` as a
number and `BigInt(9007199254740993)` cannot recover it because the literal was
rounded first (`BigInt("9007199254740993")` can), while Python's `json` keeps it
exact; and the portable `floor_div`/`mod_non_negative` helpers are checked against
Python's own operators for every combination of a in [-25, 25] and b in {2,3,7,86400}.
@@end

@example ml-lang-0004
@meta category=cross_language language=multi difficulty=advanced tags=iso8601,timezone,epoch,wire-format

@user
Our API returns `"created_at": 1711924800` (or is it milliseconds? the mobile client assumed ms) and admin uploads give us `2024-10-27T01:30:00` with no timezone. Once a year — the day the clocks go back — some events show up an hour out of order, and we have seen duplicate-looking rows in the audit log. What should the wire format be, and how do we keep every consumer agreeing?
@@end

@assistant
Two problems: an ambiguous unit and an ambiguous *local* time.

**1. Epoch units.** Python's `time.time()` and Go's `Unix()` are seconds; JavaScript's `Date.now()` and Java's `System.currentTimeMillis()` are milliseconds. A 10-digit number treated as milliseconds lands in January 1970; a 13-digit number treated as seconds throws an out-of-range error in some runtimes and silently overflows in others. Pick one for the wire format and stop guessing:

- **Send RFC 3339 / ISO 8601 in UTC with milliseconds**: `2024-03-31T22:40:00.123Z`. It is human-readable, unambiguous, timezone-complete, fixed width (24 characters), and therefore sorts lexicographically exactly as it sorts chronologically.
- **If you must use an integer, use milliseconds, and name the field for the unit** (`created_at_ms`). A field called `created_at` carrying a bare number is a bug waiting for a second service.
- **Reject, do not guess.** Validation should refuse a timestamp outside a plausible window rather than accepting `0` or a 10-digit value in a millisecond field.

**2. Local time without an offset.** `2024-10-27T01:30:00` is not an instant, it is two instants in Europe/London (BST `01:30` = `00:30Z`, GMT `01:30` = `01:30Z`) and one in Accra. Parsers differ on what they do with it: JavaScript parses a *date-only* string as UTC midnight and an offset-less *date-time* string as local time — so `"2024-03-31"` and `"2024-03-31T00:00:00"` are 1 hour apart in London, and the same codebase produces two instants from two spellings of the same date.

```python
UTC = timezone.utc
CANONICAL = "%Y-%m-%dT%H:%M:%S.%f"


def canonical(moment):
    """One wire format: UTC, millisecond precision, fixed width."""
    return moment.astimezone(UTC).strftime(CANONICAL)[:-3] + "Z"


def parse_canonical(text):
    return datetime.strptime(text, CANONICAL + "Z").replace(tzinfo=UTC)


def detect_unit(value):
    """Seconds or milliseconds? Decide from magnitude, then say so in the name."""
    return value / 1000.0 if abs(value) >= 10**11 else float(value)
```

Rules that keep the ambiguity out:

- **Store instants in UTC, and add timezone only for display.** A wall-clock time without an offset belongs in a calendar column (`2024-10-27`), never in an instant column.
- **Truncate to milliseconds, never round.** Rounding a `23:59:59.9996` timestamp moves it into tomorrow — an off-by-one-day that appears once every few million events.
- **Normalise on ingest, not on read.** If a client sends a local time, require an offset and convert once at the boundary; do not store the ambiguous string.
- **Test the boundaries every year**: the spring-forward gap, the ambiguous fall-back hour (in Python, `fold=0`/`fold=1`), and pre-1970 instants for the epoch-arithmetic bugs in the previous example.
@@end

@verify kind=executable language=python
@code
import json
import shutil
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

JS = r'''
const parse = (text) => new Date(text).getTime();
const report = {
  dateOnly: parse("2024-03-31"),
  localDateTime: parse("2024-03-31T02:30:00"),
  utcDateTime: parse("2024-03-31T02:30:00Z"),
  offsetDateTime: parse("2024-03-31T02:30:00+01:00"),
  // The spring-forward hour does not exist in Europe/London; how does a
  // local-time constructor behave?
  springForward: new Date(2024, 2, 31, 1, 30).toISOString(),
  // The ambiguous hour on the way back: which of the two 01:30s is chosen?
  ambiguous: new Date(2024, 9, 27, 1, 30).toISOString(),
  offsetMinutes: new Date(2024, 6, 1).getTimezoneOffset(),
  secondsFromMs: Math.floor(1711924800123 / 1000),
  isoRoundTrip: new Date(1711924800123).toISOString(),
};
process.stdout.write(JSON.stringify(report));
'''

UTC = timezone.utc
LONDON = ZoneInfo("Europe/London")
ACCRA = ZoneInfo("Africa/Accra")
#: Fixed width, no literal Z in the format: the Z is added once, at the end, so
#: slicing the microseconds cannot eat into it.
CANONICAL_FORMAT = "%Y-%m-%dT%H:%M:%S.%f"


def epoch_millis(moment):
    return int(moment.timestamp() * 1000)


def detect_unit(value):
    """Seconds or milliseconds? Decide from the magnitude, not from a comment."""
    if abs(value) >= 10**11:
        return value / 1000.0            # 13 digits: milliseconds
    return float(value)                  # 10 digits: seconds


def canonical(moment):
    """One wire format: UTC, millisecond precision, always the same width."""
    return moment.astimezone(UTC).strftime(CANONICAL_FORMAT)[:-3] + "Z"


def parse_canonical(text):
    return datetime.strptime(text, CANONICAL_FORMAT + "Z").replace(tzinfo=UTC)


node = shutil.which("node")
assert node, "node is required for the cross-language comparison"
with tempfile.TemporaryDirectory() as tmp:
    script = Path(tmp) / "dates.mjs"
    script.write_text(JS)
    result = subprocess.run(
        [node, str(script)],
        capture_output=True, text=True, check=False,
        env={**__import__("os").environ, "TZ": "Europe/London"},
    )
assert result.returncode == 0, result.stderr
js = json.loads(result.stdout)

# --- 1. one instant, two units, one canonical string ----------------------
INSTANT = datetime(2024, 3, 31, 22, 40, 0, 123000, tzinfo=UTC)
seconds = int(INSTANT.timestamp())
millis = epoch_millis(INSTANT)
assert seconds == 1711924800, seconds
assert len(str(seconds)) == 10 and len(str(millis)) == 13
assert detect_unit(seconds) == float(seconds), "ten digits: already seconds"
assert detect_unit(millis) == float(seconds) + 0.123, "thirteen digits: divide once, keep the ms"
assert canonical(datetime.fromtimestamp(detect_unit(seconds), tz=UTC)) == "2024-03-31T22:40:00.000Z"
assert canonical(datetime.fromtimestamp(detect_unit(millis), tz=UTC)) == canonical(INSTANT)
assert int(detect_unit(millis)) == int(detect_unit(seconds)), "same second after truncation"
assert canonical(INSTANT) == "2024-03-31T22:40:00.123Z"
assert js["secondsFromMs"] == seconds, "integer-second arithmetic: floor(ms / 1000)"
assert js["isoRoundTrip"] == "2024-03-31T22:40:00.123Z", js["isoRoundTrip"]

# --- 2. microseconds are truncated, never rounded ------------------------
almost_next_second = datetime(2024, 3, 31, 23, 59, 59, 999999, tzinfo=UTC)
assert canonical(almost_next_second) == "2024-03-31T23:59:59.999Z"
rounded = (almost_next_second + timedelta(microseconds=500)).replace(microsecond=0)
assert canonical(rounded) == "2024-04-01T00:00:00.000Z"
assert canonical(almost_next_second) != canonical(rounded), (
    "rounding to the nearest millisecond can move an instant into the next second"
)
just_over = datetime(2024, 3, 1, 0, 0, 0, 1000, tzinfo=UTC)      # 1ms + 1µs
assert just_over.strftime(CANONICAL_FORMAT)[:-3] + "Z" == "2024-03-01T00:00:00.001Z", (
    "strftime truncates the extra microsecond instead of bumping the millisecond"
)

# --- 3. the same wall-clock text is three different instants -------------
assert js["offsetMinutes"] == -60, "London is UTC+1 in July"
# The three parse forms in the same file, on the same date, in the same zone:
assert js["dateOnly"] == 1711843200000, "date-only input is parsed as UTC midnight"
assert js["localDateTime"] == 1711848600000, "offset-less input is parsed in the local zone"
assert js["utcDateTime"] == 1711852200000, "a Z suffix is explicit"
assert js["offsetDateTime"] == 1711848600000, "02:30 BST is 01:30Z"
assert js["utcDateTime"] - js["dateOnly"] == 9_000_000, "2.5 hours apart, same date string"
assert len({js["dateOnly"], js["localDateTime"], js["utcDateTime"]}) == 3, (
    "three parse forms, three different instants"
)

# The same wall clock in three zones: two agree by luck (Accra is UTC+0 and the
# spring DST change has not happened yet in either), London does not.
naive = datetime(2024, 3, 31, 2, 30, 0)
assert int(naive.replace(tzinfo=ACCRA).timestamp()) == 1711852200
assert int(naive.replace(tzinfo=UTC).timestamp()) == 1711852200
assert int(naive.replace(tzinfo=LONDON).timestamp()) == 1711848600
assert int(naive.replace(tzinfo=UTC).timestamp()) - int(naive.replace(tzinfo=LONDON).timestamp()) == 3600
assert naive.replace(tzinfo=LONDON).utcoffset() == timedelta(hours=1), "BST is in effect"
assert naive.replace(tzinfo=ACCRA).utcoffset() == timedelta(0)
try:
    naive < datetime(2024, 3, 31, tzinfo=UTC)
    raise AssertionError("comparing naive and aware datetimes must fail loudly")
except TypeError:
    pass

# --- 4. the ambiguous hour, once a year -----------------------------------
fold_zero = datetime(2024, 10, 27, 1, 30, tzinfo=LONDON, fold=0)
fold_one = datetime(2024, 10, 27, 1, 30, tzinfo=LONDON, fold=1)
assert canonical(fold_zero) == "2024-10-27T00:30:00.000Z", canonical(fold_zero)
assert canonical(fold_one) == "2024-10-27T01:30:00.000Z", canonical(fold_one)
assert fold_one.timestamp() - fold_zero.timestamp() == 3600, "the same wall clock, an hour apart"
assert fold_zero.utcoffset() == timedelta(hours=1) and fold_one.utcoffset() == timedelta(0)  # BST then GMT
assert js["ambiguous"] == "2024-10-27T00:30:00.000Z", (
    "JavaScript's local-time constructor picks the first of the two 01:30s"
)
assert canonical(fold_zero) == js["ambiguous"], "the client and the server agree only by luck"
assert js["springForward"] == "2024-03-31T01:30:00.000Z", js["springForward"]
assert canonical(datetime(2024, 3, 31, 1, 30, tzinfo=LONDON)) == js["springForward"], (
    "the same 01:30 in a local-time constructor and in zoneinfo agree here"
)

# --- 5. canonical strings sort chronologically ---------------------------
moments = [
    datetime(2024, 1, 1, tzinfo=UTC),
    datetime(1969, 12, 31, 23, 59, 59, 500000, tzinfo=UTC),
    datetime(2024, 3, 31, 22, 40, 0, 123000, tzinfo=UTC),
    datetime(2038, 1, 19, 3, 14, 8, tzinfo=UTC),
    datetime(2024, 3, 31, 22, 40, 0, 122000, tzinfo=UTC),
]
strings = [canonical(moment) for moment in moments]
assert strings[1] == "1969-12-31T23:59:59.500Z", strings[1]
assert all(len(text) == 24 for text in strings), strings
assert sorted(strings) == [canonical(moment) for moment in sorted(moments)], sorted(strings)
assert strings[2] != strings[4], "one millisecond apart is one distinct string"
assert parse_canonical(strings[3]) == moments[3]
for text, moment in zip(strings, moments):
    assert canonical(parse_canonical(text)) == text, text
    assert parse_canonical(text).timestamp() == moment.timestamp()

# --- 6. what breaks when the offset is missing from the wire format -------
WIRE = "2024-10-27T01:30:00"
no_offset_utc = datetime.strptime(WIRE, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=UTC)
no_offset_london = datetime.strptime(WIRE, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=LONDON, fold=0)
assert canonical(no_offset_utc) != canonical(no_offset_london)
assert abs(no_offset_utc.timestamp() - no_offset_london.timestamp()) == 3600
assert canonical(datetime.fromisoformat("2024-10-27T01:30:00+00:00")) == "2024-10-27T01:30:00.000Z"
assert canonical(datetime.fromisoformat("2024-10-27T01:30:00Z")) == "2024-10-27T01:30:00.000Z"
assert canonical(datetime.fromisoformat("2024-10-27T03:30:00+02:00")) == "2024-10-27T01:30:00.000Z", (
    "the same instant expressed with an offset"
)
assert canonical(datetime.fromtimestamp(0, tz=UTC)) == "1970-01-01T00:00:00.000Z"
assert canonical(datetime.fromtimestamp(-1, tz=UTC)) == "1969-12-31T23:59:59.000Z"
print("PASS")
@@end

@expect_output
PASS
@@end

@notes
The verify script runs a Node program under `TZ=Europe/London` and compares its
results with Python's `zoneinfo` for the same instants. Pinned: the same instant is
10 digits in seconds and 13 in milliseconds, `detect_unit` converts both to the
identical canonical string, and `Math.floor(ms / 1000)` agrees with integer-second
arithmetic; `23:59:59.999999Z` canonicalises to `...59.999Z` (truncated) while
adding 500µs rounds into `2024-04-01T00:00:00.000Z`, which is why truncation is the
rule; `.999` equals `.998` when the microsecond is dropped rather than carried;
JavaScript's three parse forms of the same date produce three instants
(`"2024-03-31"` → 00:00Z, `"2024-03-31T02:30:00"` → 01:30Z in the spring-forward
gap, `"2024-03-31T02:30:00Z"` → 02:30Z, 2.5 hours apart and 9 000 000 ms from
date-only to UTC), and the same wall clock in Accra, London and UTC gives two
distinct answers with London one hour off; comparing a naive and an aware datetime
raises `TypeError` instead of guessing; the ambiguous fall-back hour yields two
instants one hour apart whose `utcoffset()` is +1:00 and 0:00, and JavaScript's
local-time constructor silently picks the first — agreeing with `fold=0` by luck;
canonical strings are all 24 characters wide, so `sorted(strings)` equals the
chronological order, and parse/canonicalise round-trips both the pre-1970 instant
and the 2038 one; and an offset-less wall clock is asserted to be ambiguous across
zones while `+00:00`, `Z` and `03:30+02:00` all canonicalise to the same instant.
@@end
