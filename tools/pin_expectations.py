#!/usr/bin/env python3
"""Pin a verify block's real output into ``@expect_output``.

Authoring aid for new examples: write the verification code, assert what it must
prove, leave ``?PIN?`` as the expectation, then run this tool. It executes the
block exactly as ``tools/verify_examples.py`` would and replaces the placeholder
with what the program actually printed -- so a pinned expectation can never be a
hand-written guess. Refuses to write anything when the assertions fail.

    python3 tools/pin_expectations.py --raw-dir data/raw-v2 [--only py-trace]
"""
from __future__ import annotations

import argparse
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import build_dataset as B
import example_format
import verify_examples as V

PLACEHOLDER = "?PIN?"
EXAMPLE_RE = re.compile(r"^@example\s+(\S+)\s*$")


def spans(text: str) -> list[tuple[str, int, int]]:
    """(example id, start line, end line) for every @example in a document."""
    lines = text.splitlines()
    starts: list[tuple[str, int]] = []
    for index, line in enumerate(lines):
        match = EXAMPLE_RE.match(line)
        if match:
            starts.append((match.group(1), index))
    out = []
    for position, (example_id, start) in enumerate(starts):
        end = starts[position + 1][1] if position + 1 < len(starts) else len(lines)
        out.append((example_id, start, end))
    return out


def pin_file(path: Path, outputs: dict[str, str]) -> list[str]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    changed = []
    for example_id, start, end in reversed(spans(text)):
        if example_id not in outputs:
            continue
        block_start = None
        for index in range(start, end):
            if lines[index].strip() == "@expect_output":
                block_start = index
                break
        if block_start is None:
            continue
        if lines[block_start + 1].strip() != PLACEHOLDER:
            continue
        block_end = block_start + 1
        while block_end < len(lines) and lines[block_end].strip() != "@@end":
            block_end += 1
        body = outputs[example_id].strip("\n")
        lines[block_start + 1 : block_end] = body.splitlines() or [""]
        changed.append(example_id)
    if changed:
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return changed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw-dir", type=Path, default=Path("data/raw-v2"))
    ap.add_argument("--only", default="", help="filter example ids by substring")
    args = ap.parse_args()

    examples = list(example_format.iter_raw_examples(args.raw_dir))
    records = B.build_records(examples)
    by_id = {ex.id: ex.source_file for ex in examples}

    outputs: dict[str, str] = {}
    failures: dict[str, str] = {}
    skipped: list[str] = []
    for rec in records:
        if rec["verification"]["kind"] != "executable":
            skipped.append(f"{rec['id']} ({rec['verification']['kind']})")
            continue
        if args.only and args.only not in rec["id"]:
            continue
        with tempfile.TemporaryDirectory(prefix=f"pin-{rec['id']}-") as tmp:
            outcome = V.execute(rec, Path(tmp))
        # A placeholder expectation never matches, so "output mismatch" with a
        # zero exit code is exactly the state we want to pin. Anything else
        # (crash, timeout, compile error, static check) is a real failure.
        pinned_ok = outcome.status == "PASS" or "output mismatch" in outcome.detail
        if pinned_ok and outcome.stdout.strip():
            outputs[rec["id"]] = outcome.stdout
        else:
            failures[rec["id"]] = f"{outcome.status}: {outcome.detail}"

    files = sorted({by_id[example_id] for example_id in outputs if example_id in by_id})
    touched: list[str] = []
    for name in files:
        raw_path = args.raw_dir / name
        touched += pin_file(raw_path, outputs)

    for example_id in touched:
        print(f"pinned {example_id}: {len(outputs[example_id].strip().splitlines())} line(s)")
    for example_id, detail in failures.items():
        print(f"NOT PINNED {example_id}: {detail}", file=sys.stderr)
    if skipped and not args.only:
        print(f"skipped non-executable: {', '.join(skipped)}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
