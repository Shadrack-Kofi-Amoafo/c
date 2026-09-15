# Dataset authoring

Everything in `dataset/` is generated from the hand-written examples in
`data/raw/`. The raw files are the source of truth; the emitters are disposable.

## Layout

| Path | What it is |
| --- | --- |
| `data/system_prompt.txt` | system prompt shared by every example (no `@system` block) |
| `data/raw/<category>.md` | one file per category, one or more `@example` blocks |
| `dataset/examples.jsonl` | canonical records: id, meta, messages, verification, notes |
| `dataset/sft_*.jsonl` / `sft_sharegpt.json` | the same records in messages / alpaca / sharegpt schemas |
| `dataset/stats.json`, `dataset/VALIDATION.md` | coverage and validation summary |
| `dataset/verification_report.md` | result of executing every verification block |

## Example format

```
@example py-debug-0001
@meta category=debugging language=python difficulty=intermediate tags=asyncio,cancellation

@user
The question, as a user would ask it.
@@end

@assistant
The answer, with a fenced code block for code categories.
@@end

@verify kind=executable language=python
@code
print("PASS")
@@end

@expect_output
PASS
@@end

@notes
What the verification pins, and why it is evidence.
@@end
```

Rules enforced by `tools/build_dataset.py`:

- ids look like `py-debug-0001`; `category` is one of the twelve; `difficulty` is
  `easy`/`intermediate`/`advanced`/`expert`; `tags` are lowercase single words;
- `@user` is 90-6000 chars, `@assistant` is 320-9000 chars and contains a fenced
  code block for the code categories;
- `@verify kind=executable` needs `@code` and `@expect_output` (exact text,
  `CONTAINS:`, or `REGEX:`); `kind=parity` and `kind=reviewed` need `@notes`
  explaining the evidence, and `parity` must contain a `PARITY:` line;
- every category needs at least 4 examples and at least one executable one.

## Commands

```bash
# default dataset: reads data/raw, writes dataset/
python3 tools/build_dataset.py            # validate + emit
python3 tools/build_dataset.py --check    # validate only; exit 1 on errors

# execute every verification block (slow: compiles C, runs node, etc.)
python3 tools/verify_examples.py
python3 tools/verify_examples.py --only py-sec-          # one category by id
python3 tools/verify_examples.py --kind executable --quiet

# fix a hand-edit that left a @code block without its @@end
python3 tools/fix_missing_end_markers.py data/raw/testing.md --write
```

## A second, independent dataset

Both tools take their paths as flags, so a second dataset can live beside this one
without touching any code or overwriting the first:

```bash
mkdir -p data/raw-v2
$EDITOR data/raw-v2/<category>.md          # the same block format
python3 tools/build_dataset.py --raw-dir data/raw-v2 --out-dir dataset-v2
python3 tools/verify_examples.py \
    --dataset dataset-v2/examples.jsonl \
    --report dataset-v2/verification_report.md
```

`--out-dir` also decides where `stats.json` and `VALIDATION.md` are written, and
`--report` defaults to `verification_report.md` next to the dataset it verified.
Categories, languages, difficulties and verify kinds are validated per dataset, so
a second corpus can have its own coverage profile (for example `go`-first
examples verified with `kind=parity`) without weakening the checks on the first.
