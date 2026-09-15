"""Parser for the authoring format used in ``data/raw/*.md``.

The authoring format is deliberately boring so it can be reviewed in a diff and
parsed without a YAML/JSON dependency.  One example looks like this::

    @example py-debug-0001
    @meta category=debugging language=python difficulty=intermediate tags=asyncio,deadlock

    @user
    Why does this hang?
    @@end

    @assistant
    Because ...
    @@end

    @verify kind=executable language=python
    @code
    print("PASS")
    @@end

    @expect_output
    PASS
    @@end

Block rules
-----------
* ``@key`` opens a block; the block runs until a line that is exactly ``@@end``.
* Blank lines inside a block are preserved; leading/trailing blank lines are
  trimmed from the block value.
* A line beginning with ``@`` that is not ``@@end`` is ordinary content, so
  decorators and annotations inside code samples are safe.
* ``@@end`` must be the only thing on its line, at column 0.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

END_MARKER = "@@end"

#: Blocks that may appear inside an example, in authoring order.
KNOWN_BLOCKS = (
    "system",
    "user",
    "assistant",
    "code",
    "expect_output",
    "notes",
)


class FormatError(ValueError):
    """Raised when an authoring file is malformed."""


@dataclass
class Example:
    """One raw training example, exactly as authored."""

    id: str
    meta: dict[str, str]
    blocks: dict[str, str]
    source_file: str = ""
    source_line: int = 0
    extra_meta: dict[str, str] = field(default_factory=dict)

    def block(self, name: str, default: str = "") -> str:
        return self.blocks.get(name, default)

    # -- typed accessors -------------------------------------------------
    @property
    def category(self) -> str:
        return self.meta.get("category", "")

    @property
    def language(self) -> str:
        return self.meta.get("language", "")

    @property
    def difficulty(self) -> str:
        return self.meta.get("difficulty", "")

    @property
    def tags(self) -> list[str]:
        raw = self.meta.get("tags", "")
        return [t.strip() for t in raw.split(",") if t.strip()]

    @property
    def verify_kind(self) -> str:
        return self.extra_meta.get("kind", "none")

    @property
    def verify_language(self) -> str:
        return self.extra_meta.get("language", self.language)


def _parse_meta_line(line: str) -> dict[str, str]:
    """``category=debugging language=python tags=a,b`` -> dict."""
    out: dict[str, str] = {}
    for token in line.split():
        if "=" not in token:
            raise FormatError(f"@meta token {token!r} is not key=value")
        key, _, value = token.partition("=")
        out[key.strip()] = value.strip()
    return out


def parse_text(text: str, source_file: str = "<string>") -> list[Example]:
    """Parse an authoring document into :class:`Example` objects."""
    lines = text.replace("\r\n", "\n").split("\n")
    examples: list[Example] = []
    current: Example | None = None
    block_name: str | None = None
    block_lines: list[str] = []

    def flush_block() -> None:
        nonlocal block_name, block_lines
        if current is not None and block_name is not None:
            if block_name in current.blocks:
                raise FormatError(
                    f"{source_file}:{current.id}: block @{block_name} repeated"
                )
            current.blocks[block_name] = "\n".join(block_lines).strip("\n")
        block_name, block_lines = None, []

    for lineno, line in enumerate(lines, start=1):
        if block_name is not None:
            if line == END_MARKER:
                flush_block()
                continue
            if line.startswith(END_MARKER):  # e.g. "@@end   " typo
                raise FormatError(
                    f"{source_file}:{lineno}: trailing text after {END_MARKER!r}: {line!r}"
                )
            # An exact block keyword here means the author forgot to close the
            # previous block; failing loudly beats swallowing the rest of the file.
            if line in {f"@{b}" for b in KNOWN_BLOCKS} | {"@example", "@meta", "@verify"}:
                raise FormatError(
                    f"{source_file}:{lineno}: encountered {line!r} while block "
                    f"@{block_name} is still open (missing {END_MARKER})"
                )
            block_lines.append(line)
            continue

        stripped = line.strip()
        if not stripped:
            continue

        if stripped.startswith("@example"):
            flush_block()
            parts = stripped.split()
            if len(parts) != 2:
                raise FormatError(f"{source_file}:{lineno}: '@example' needs exactly one id")
            current = Example(id=parts[1], meta={}, blocks={}, source_file=source_file, source_line=lineno)
            examples.append(current)
            continue

        if current is None:
            raise FormatError(f"{source_file}:{lineno}: content before first '@example'")

        if stripped.startswith("@meta"):
            flush_block()
            _, _, rest = stripped.partition(" ")
            for key, value in _parse_meta_line(rest).items():
                if key in current.meta:
                    raise FormatError(f"{source_file}:{lineno}: duplicate @meta key {key!r}")
                current.meta[key] = value
            continue

        if stripped.startswith("@verify"):
            flush_block()
            _, _, rest = stripped.partition(" ")
            for key, value in _parse_meta_line(rest).items():
                current.extra_meta[key] = value
            continue

        matched = next((b for b in KNOWN_BLOCKS if stripped == f"@{b}"), None)
        if matched is None:
            raise FormatError(
                f"{source_file}:{lineno}: unexpected line {line!r} "
                f"(expected @example/@meta/@verify/@{'|@'.join(KNOWN_BLOCKS)}/{END_MARKER})"
            )
        block_name, block_lines = matched, []

    flush_block()
    if block_name is not None:
        raise FormatError(f"{source_file}: unterminated block @{block_name} at end of file")
    return examples


def parse_file(path: str | Path) -> list[Example]:
    path = Path(path)
    return parse_text(path.read_text(encoding="utf-8"), source_file=path.name)


def iter_raw_examples(raw_dir: str | Path) -> Iterator[Example]:
    for path in sorted(Path(raw_dir).glob("*.md")):
        yield from parse_file(path)
