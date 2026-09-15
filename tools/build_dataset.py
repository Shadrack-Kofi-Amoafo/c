"""Validate the raw authoring files and emit the SFT-ready dataset.

Usage::

    python3 tools/build_dataset.py            # validate + write dataset/
    python3 tools/build_dataset.py --check     # validate only (CI gate)

Outputs (all regenerated, all deterministic):

    dataset/examples.jsonl          full records: metadata + messages + verification
    dataset/sft_messages.jsonl      {"id", "messages"}   (chat/messages tuning)
    dataset/sft_alpaca.jsonl        {"instruction","input","output"} (alpaca tuning)
    dataset/sft_sharegpt.json      {"conversations":[{"from","value"}]}
    dataset/stats.json              coverage and difficulty distribution
    dataset/VALIDATION.md           the validation report

Exit code is non-zero if any hard gate fails, so this doubles as a CI check.
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from example_format import Example, iter_raw_examples  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
OUT_DIR = ROOT / "dataset"
SYSTEM_PROMPT = (ROOT / "data" / "system_prompt.txt").read_text(encoding="utf-8").strip()

CATEGORIES = {
    "code_generation",
    "code_understanding",
    "debugging",
    "refactoring",
    "optimization",
    "algorithms",
    "data_structures",
    "api_usage",
    "software_architecture",
    "testing",
    "security",
    "cross_language",
}
LANGUAGES = {
    "python",
    "javascript",
    "typescript",
    "sql",
    "c",
    "cpp",
    "go",
    "rust",
    "java",
    "bash",
    "yaml",
    "multi",
}
DIFFICULTIES = ("easy", "intermediate", "advanced", "expert")
VERIFY_KINDS = {"executable", "parity", "reviewed"}
ID_RE = re.compile(r"^[a-z]{1,4}(-[a-z0-9]+){1,4}$")

#: Categories whose answers must contain runnable code.
CODE_CATEGORIES = {
    "code_generation",
    "debugging",
    "refactoring",
    "optimization",
    "algorithms",
    "data_structures",
    "api_usage",
    "testing",
    "security",
    "cross_language",
}

MIN_USER = 90
MIN_ASSISTANT = 320
MAX_ASSISTANT = 9000

#: Sentences that appear in too many examples are boilerplate, not teaching.
BOILERPLATE_LIMIT = 2


class Validator:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def error(self, where: str, msg: str) -> None:
        self.errors.append(f"{where}: {msg}")

    def warn(self, where: str, msg: str) -> None:
        self.warnings.append(f"{where}: {msg}")


def fuzzy_ratio(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


def normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", text.lower())


def sentences(text: str) -> list[str]:
    # Strip fenced code before sentence extraction: code is expected to repeat.
    prose = re.sub(r"```.*?```", " ", text, flags=re.S)
    prose = re.sub(r"`[^`]*`", " ", prose)
    parts = re.split(r"(?<=[.!?:])\s+", prose.replace("\n", " "))
    return [normalize(p).strip() for p in parts if len(normalize(p).strip()) >= 45]


def validate(examples: list[Example]) -> Validator:
    v = Validator()
    seen_ids: Counter[str] = Counter()

    for ex in examples:
        where = f"{ex.source_file}:{ex.id}"

        # --- identity / metadata ---------------------------------------
        seen_ids[ex.id] += 1
        if not ID_RE.match(ex.id):
            v.error(where, "id must be like 'py-debug-0001' (lowercase, dash-separated)")
        if not ex.category:
            v.error(where, "missing category in @meta")
        elif ex.category not in CATEGORIES:
            v.error(where, f"unknown category {ex.category!r}")
        if not ex.language:
            v.error(where, "missing language in @meta")
        elif ex.language not in LANGUAGES:
            v.error(where, f"unknown language {ex.language!r}")
        if ex.difficulty not in DIFFICULTIES:
            v.error(where, f"difficulty must be one of {DIFFICULTIES}, got {ex.difficulty!r}")

        tags = ex.tags
        if not 2 <= len(tags) <= 6:
            v.error(where, f"expected 2-6 tags, got {len(tags)}: {tags}")
        if any(t != t.lower() or " " in t for t in tags):
            v.error(where, f"tags must be lowercase single words: {tags}")

        # --- message content -------------------------------------------
        user, assistant = ex.block("user"), ex.block("assistant")
        if not user:
            v.error(where, "missing @user block")
        elif not MIN_USER <= len(user) <= 6000:
            v.error(where, f"@user length {len(user)} outside [{MIN_USER}, 6000]")
        if not assistant:
            v.error(where, "missing @assistant block")
        elif not MIN_ASSISTANT <= len(assistant) <= MAX_ASSISTANT:
            v.error(where, f"@assistant length {len(assistant)} outside [{MIN_ASSISTANT}, {MAX_ASSISTANT}]")
        if "```" not in assistant and ex.category in CODE_CATEGORIES:
            v.error(where, f"@assistant for category {ex.category} contains no fenced code block")
        if assistant.strip().startswith(("Sure", "Certainly", "Great question", "Absolutely")):
            v.error(where, "@assistant opens with filler ("f"{assistant[:24]!r})")
        if re.search(r"\b(As an AI|I cannot browse|I don't have access)\b", assistant):
            v.error(where, "@assistant contains model-disclaimer boilerplate")

        # --- the user turn must be a request, not a quiz-stub ----------
        if len(user.splitlines()) == 1 and not user.strip().endswith(("?", ".", "!", ":")):
            v.warn(where, "@user is a single unterminated line; may read as a stub")

        # --- verification block ----------------------------------------
        vk = ex.verify_kind
        if vk == "none":
            v.error(where, "missing @verify block (every example must declare its evidence)")
        elif vk not in VERIFY_KINDS:
            v.error(where, f"verify kind must be one of {sorted(VERIFY_KINDS)}, got {vk!r}")
        notes = ex.block("notes")
        if vk in {"parity", "reviewed"} and not notes:
            v.error(where, f"@verify kind={vk} requires a @notes block explaining the evidence")
        if vk == "parity" and "PARITY:" not in notes:
            v.error(where, "@notes for a parity example must contain a 'PARITY:' line")
        if vk in {"executable", "parity"} and not ex.block("code"):
            v.error(where, f"@verify kind={vk} requires a @code block")
        if vk == "executable" and not ex.block("expect_output"):
            v.error(where, "@verify kind=executable requires @expect_output")

    # --- cross-example duplication and boilerplate ---------------------
    ids = [ex.id for ex in examples]
    dupes = [i for i, n in seen_ids.items() if n > 1]
    for d in dupes:
        v.error("dataset", f"duplicate example id {d!r}")

    prompts = [(ex.id, normalize(ex.block("user"))) for ex in examples]
    for i, (id_a, a) in enumerate(prompts):
        for id_b, b in prompts[i + 1 :]:
            if a == b:
                v.error("dataset", f"identical prompts: {id_a} == {id_b}")
                continue
            if abs(len(a) - len(b)) > 60:
                continue
            ratio = fuzzy_ratio(a, b)
            if ratio > 0.82:
                v.error("dataset", f"near-duplicate prompts ({ratio:.2f}): {id_a} ~ {id_b}")

    boiler: dict[str, list[str]] = defaultdict(list)
    for ex in examples:
        for s in set(sentences(ex.block("assistant"))):
            boiler[s].append(ex.id)
    for sentence, ids_using in sorted(boiler.items()):
        if len(ids_using) > BOILERPLATE_LIMIT:
            v.warn(
                "boilerplate",
                f"same sentence in {len(ids_using)} examples {ids_using[:6]}: {sentence[:70]!r}",
            )

    # --- coverage gates ------------------------------------------------
    by_cat = Counter(ex.category for ex in examples)
    for cat in sorted(CATEGORIES):
        if by_cat[cat] < 4:
            v.error("coverage", f"category {cat} has only {by_cat[cat]} examples (need >= 4)")

    by_lang = Counter(ex.language for ex in examples)
    for lang in LANGUAGES - {"multi"}:
        if by_lang[lang] < 1:
            v.warn("coverage", f"language {lang} is not covered by any example")

    by_diff = Counter(ex.difficulty for ex in examples)
    for diff in DIFFICULTIES:
        if by_diff[diff] < 3:
            v.warn("coverage", f"difficulty {diff} appears only {by_diff[diff]} times")

    # every category needs at least one example whose code actually ran
    executed = defaultdict(int)
    for ex in examples:
        if ex.verify_kind == "executable":
            executed[ex.category] += 1
    for cat in sorted(CATEGORIES):
        if executed[cat] < 1:
            v.error("coverage", f"category {cat} has no executable-verified example")
    return v


def build_records(examples: list[Example]) -> list[dict]:
    records = []
    for ex in examples:
        system = ex.block("system") or SYSTEM_PROMPT
        verification = {"kind": ex.verify_kind}
        if ex.verify_kind != "reviewed":
            verification["language"] = ex.verify_language
        # Carry any other @verify options through (mode=, flags=, ...): dropping
        # them silently changes how the artifact is checked.
        for key, value in ex.extra_meta.items():
            if key not in {"kind", "language"}:
                verification[key] = value
        if ex.block("code"):
            verification["code"] = ex.block("code")
        if ex.block("expect_output"):
            verification["expect_output"] = ex.block("expect_output")
        if ex.block("notes"):
            verification["notes"] = ex.block("notes")
        records.append(
            {
                "id": ex.id,
                "category": ex.category,
                "language": ex.language,
                "difficulty": ex.difficulty,
                "tags": ex.tags,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": ex.block("user")},
                    {"role": "assistant", "content": ex.block("assistant")},
                ],
                "verification": verification,
            }
        )
    return records


def to_alpaca(rec: dict) -> dict:
    # Fold the system prompt into the instruction: alpaca records have no
    # system role, so dropping it silently would change the task.
    sys_msg = rec["messages"][0]["content"]
    return {
        "id": rec["id"],
        "instruction": f"{sys_msg}\n\n{rec['messages'][1]['content']}",
        "input": "",
        "output": rec["messages"][2]["content"],
    }


def to_sharegpt(rec: dict) -> dict:
    names = {"system": "system", "user": "human", "assistant": "gpt"}
    return {
        "id": rec["id"],
        "conversations": [{"from": names[m["role"]], "value": m["content"]} for m in rec["messages"]],
    }


def write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="validate only, write nothing")
    ap.add_argument(
        "--raw-dir", type=Path, default=RAW_DIR,
        help="authoring directory to read (default: data/raw)",
    )
    ap.add_argument(
        "--out-dir", type=Path, default=OUT_DIR,
        help="directory to write the emitted datasets into (default: dataset)",
    )
    args = ap.parse_args()

    raw_dir, out_dir = args.raw_dir, args.out_dir
    examples = list(iter_raw_examples(raw_dir))
    validator = validate(examples)
    records = build_records(examples)

    by_cat = Counter(r["category"] for r in records)
    by_lang = Counter(r["language"] for r in records)
    by_diff = Counter(r["difficulty"] for r in records)
    by_kind = Counter(r["verification"]["kind"] for r in records)
    chars_assistant = sum(len(r["messages"][2]["content"]) for r in records)

    stats = {
        "examples": len(records),
        "categories": dict(sorted(by_cat.items())),
        "languages": dict(sorted(by_lang.items())),
        "difficulties": {d: by_diff[d] for d in DIFFICULTIES},
        "verification_kinds": dict(sorted(by_kind.items())),
        "assistant_chars_total": chars_assistant,
        "estimated_tokens_total": round(chars_assistant / 3.6),
    }

    lines = ["# Dataset validation report", ""]
    lines += [
        f"- examples: **{len(records)}**",
        f"- verification: " + ", ".join(f"{k}={v}" for k, v in sorted(by_kind.items())),
        f"- categories: " + ", ".join(f"{k}={v}" for k, v in sorted(by_cat.items())),
        f"- languages: " + ", ".join(f"{k}={v}" for k, v in sorted(by_lang.items())),
        f"- difficulty: " + ", ".join(f"{d}={by_diff[d]}" for d in DIFFICULTIES),
        f"- assistant text: {chars_assistant:,} chars (~{stats['estimated_tokens_total']:,} tokens)",
        "",
    ]
    lines.append("## Errors")
    lines += [f"- {e}" for e in validator.errors] or ["- none"]
    lines.append("")
    lines.append("## Warnings")
    lines += [f"- {w}" for w in validator.warnings] or ["- none"]
    lines.append("")
    report = "\n".join(lines)

    if args.check:
        print(report)
        return 1 if validator.errors else 0

    out_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(out_dir / "examples.jsonl", records)
    write_jsonl(
        out_dir / "sft_messages.jsonl",
        [{"id": r["id"], "messages": r["messages"]} for r in records],
    )
    write_jsonl(out_dir / "sft_alpaca.jsonl", [to_alpaca(r) for r in records])
    with (out_dir / "sft_sharegpt.json").open("w", encoding="utf-8") as fh:
        json.dump([to_sharegpt(r) for r in records], fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    with (out_dir / "stats.json").open("w", encoding="utf-8") as fh:
        json.dump(stats, fh, indent=2, sort_keys=True)
        fh.write("\n")
    (out_dir / "VALIDATION.md").write_text(report, encoding="utf-8")

    print(report)
    return 1 if validator.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
