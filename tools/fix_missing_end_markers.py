"""One-off repair helper: insert missing ``@@end`` markers.

When a block keyword (``@user``, ``@assistant``, ``@code`` ...) or a ``@verify``
directive appears while a content block is still open, the intended terminator
was ``@@end``.  This script inserts it and reports every insertion so the diff
can be reviewed.

``@verify`` is a terminator but never opens a block: the ``@code`` line after it
does.  Getting that distinction wrong inserts a stray ``@@end``.

Usage: python3 tools/fix_missing_end_markers.py data/raw/*.md [--write]
"""

from __future__ import annotations

import sys
from pathlib import Path

OPENERS = {"@system", "@user", "@assistant", "@code", "@expect_output", "@notes", "@example", "@meta"}
END = "@@end"


def is_terminator(line: str) -> bool:
    return line in OPENERS or line.startswith("@verify ")


def repair(text: str) -> tuple[str, list[tuple[int, str, str]]]:
    lines = text.split("\n")
    out: list[str] = []
    insertions: list[tuple[int, str, str]] = []
    open_block: str | None = None
    for lineno, line in enumerate(lines, start=1):
        stripped = line.strip()
        if open_block is not None:
            if line == END:
                open_block = None
                out.append(line)
                continue
            if is_terminator(stripped):
                insertions.append((lineno, open_block, stripped))
                while out and out[-1].strip() == "":   # keep exactly one blank line
                    out.pop()
                out.append(END)
                out.append("")
                open_block = None
        if open_block is None and stripped in OPENERS:
            open_block = stripped
        out.append(line)
    return "\n".join(out), insertions


def main() -> int:
    args = [a for a in sys.argv[1:] if a != "--write"]
    write = "--write" in sys.argv
    total = 0
    for name in args:
        path = Path(name)
        fixed, insertions = repair(path.read_text(encoding="utf-8"))
        for lineno, block, keyword in insertions:
            print(f"{path.name}:{lineno}: closing {block} before {keyword}")
        total += len(insertions)
        if write and insertions:
            path.write_text(fixed, encoding="utf-8")
    print(f"{total} marker(s) {'inserted' if write else 'would be inserted'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
