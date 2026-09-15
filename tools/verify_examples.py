"""Execute every example's verification block and write an evidence report.

Conventions
-----------
``@verify kind=executable language=<lang>``
    ``@code`` is a self-contained program; the runner compiles/runs it and
    compares stdout against ``@expect_output``.

    Supported languages: python, javascript, typescript, c, cpp, bash, sql.
    * ``sql`` runs in an in-memory SQLite database; every result-producing
      statement prints a ``col|col`` header followed by ``v|v`` rows.
    * ``typescript`` with ``mode=typecheck`` asserts that ``tsc --strict``
      accepts the file (and rejects anything marked ``@ts-expect-error``);
      the runner then prints ``TYPECHECK_OK``.
    * ``c``/``cpp`` accept ``flags=asan`` to build with ASan+UBSan.

``@verify kind=parity language=<lang>``
    The snippet is written in a language with no toolchain in this repo
    (go, rust, java).  ``@code`` is a Python reference implementation of the
    same algorithm plus its test vectors; running it proves the algorithm and
    the documented outputs.  The snippet itself is covered by the static
    checks below and by the explicit review list in ``@notes`` (``PARITY:``).

``@verify kind=reviewed``
    No executable artifact (design docs, migration plans, vendor-specific SQL).
    The runner still applies static checks to ``@code`` when present.

Static checks applied to every snippet, regardless of kind: bracket/paren
balance and unterminated string detection, with language-aware handling of
strings, chars, raw strings, and comments.  This is not a parser, but it has
caught real typos.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "dataset" / "examples.jsonl"
REPORT = ROOT / "dataset" / "verification_report.md"

DEFAULT_TIMEOUT = 25


# --------------------------------------------------------------------------
# static checks
# --------------------------------------------------------------------------
def _drop_heredoc_bodies(code: str) -> str:
    """Blank out shell heredoc bodies so shell-in-shell tests do not false-positive.

    The heredoc payload is written out and executed by the harness itself, so
    bash validates it at run time; statically scanning it twice adds nothing but
    noise.
    """
    out_lines: list[str] = []
    delimiter: str | None = None
    for line in code.split("\n"):
        if delimiter is not None:
            if line.strip() == delimiter:
                delimiter = None
            out_lines.append("")
            continue
        match = re.search(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1", line)
        if match and "#" not in line.split("<<")[0]:
            delimiter = match.group(2)
        out_lines.append(line)
    return "\n".join(out_lines)


def _strip_code_noise(code: str, language: str) -> list[tuple[int, str]]:
    """Return (1-based line number, code-with-strings-and-comments-removed)."""
    out: list[tuple[int, str]] = []
    i, line_no = 0, 1
    line_start = 0
    n = len(code)
    line = []
    raw_quote = "`" if language == "go" else None
    line_comment = {"python": "#", "bash": "#", "yaml": "#", "sql": "--"}.get(language, "//")
    while i < n:
        ch = code[i]
        nxt = code[i + 1] if i + 1 < n else ""
        if ch == "\n":
            out.append((line_no, "".join(line)))
            line, line_no, line_start = [], line_no + 1, i + 1
            i += 1
            continue
        if line_comment and code.startswith(line_comment, i):
            j = code.find("\n", i)
            i = n if j == -1 else j
            continue
        if language not in ("python", "bash", "yaml") and code.startswith("/*", i):
            j = code.find("*/", i + 2)
            i = n if j == -1 else j + 2
            continue
        if language == "python" and code.startswith(ch * 3, i) and ch in "\"'":
            j = code.find(ch * 3, i + 3)          # triple-quoted string / docstring
            if j == -1:
                return out + [(line_no, "".join(line) + "<<UNTERMINATED_TRIPLE_QUOTE>>")]
            i = j + 3
            continue
        if raw_quote and ch == raw_quote:
            j = code.find(ch, i + 1)
            i = n if j == -1 else j + 1
            continue
        quote_chars = "\"'" + ("`" if language in ("javascript", "typescript") else "")
        if ch in quote_chars:
            quote = ch
            j = i + 1
            while j < n:
                if code[j] == "\\" and language in ("python", "javascript", "typescript", "c", "cpp", "java"):
                    j += 2
                    continue
                if code[j] == quote:
                    break
                if code[j] == "\n" and quote != "`":
                    # Unterminated string on this line: report and stop.
                    return out + [(line_no, "".join(line) + "<<UNTERMINATED_STRING>>")]
                j += 1
            if j >= n:
                return out + [(line_no, "".join(line) + "<<UNTERMINATED_STRING>>")]
            if language == "sql":
                line.append("''")  # keep '' identity to avoid false quote pairing
            i = j + 1
            continue
        line.append(ch)
        i += 1
    out.append((line_no, "".join(line)))
    return out


def static_checks(code: str, language: str) -> list[str]:
    """Cheap structural checks. Returns a list of problem descriptions."""
    problems: list[str] = []
    pairs = {")": "(", "]": "[", "}": "{"}
    openers = set("([{")
    stack: list[tuple[str, int]] = []
    if language in ("bash", "sh"):
        code = _drop_heredoc_bodies(code)
    for line_no, stripped in _strip_code_noise(code, language):
        if "<<UNTERMINATED_STRING>>" in stripped:
            problems.append(f"line {line_no}: unterminated string literal")
            break
        if "<<UNTERMINATED_TRIPLE_QUOTE>>" in stripped:
            problems.append(f"line {line_no}: unterminated triple-quoted string")
            break
        for ch in stripped:
            if ch in openers:
                stack.append((ch, line_no))
            elif ch in pairs:
                # `case` labels (`--flag)`, `*)`) are bare `)` in shell.
                if (
                    ch == ")"
                    and language in ("bash", "sh")
                    and stack
                    and stack[-1][0] == "{"
                    and re.fullmatch(r"[^\s()|]+(\|[^\s()|]+)*", "".join(line).strip())
                ):
                    continue
                if not stack:
                    problems.append(f"line {line_no}: unbalanced {ch!r}")
                    return problems
                opening = stack.pop()
                if opening[0] != pairs[ch]:
                    problems.append(
                        f"line {line_no}: {ch!r} closes {opening[0]!r} opened on line {opening[1]}"
                    )
                    return problems
    if stack:
        ch, line_no = stack[-1]
        problems.append(f"line {line_no}: {ch!r} is never closed")
    if code.count("```") % 2:
        problems.append("odd number of ``` fences")
    return problems


# --------------------------------------------------------------------------
# execution
# --------------------------------------------------------------------------
@dataclass
class Outcome:
    id: str
    kind: str
    language: str
    status: str  # PASS | FAIL | SKIP
    detail: str = ""
    notes: list[str] = field(default_factory=list)
    duration_s: float = 0.0


def _compare(stdout: str, expected: str) -> tuple[bool, str]:
    expected = expected.strip()
    if expected.startswith("REGEX:"):
        pattern = expected[len("REGEX:") :].strip()
        m = re.search(pattern, stdout, re.S)
        return (bool(m), f"regex {pattern!r} {'matched' if m else 'did not match'}")
    if expected.startswith("CONTAINS:"):
        needle = expected[len("CONTAINS:") :].strip()
        return (needle in stdout, f"substring {needle!r} {'found' if needle in stdout else 'missing'}")
    ok = stdout.strip() == expected
    if ok:
        return True, "output matched"
    diff = "\n".join(
        list(win := __import__("difflib").unified_diff(
            expected.splitlines(), stdout.strip().splitlines(),
            "expected", "actual", lineterm="",
        ))[:40]
    )
    return False, f"output mismatch:\n```\n{diff}\n```"


def _run(cmd: list[str], cwd: str, timeout: int, env: dict | None = None) -> tuple[int, str, str, bool]:
    full_env = dict(os.environ)
    full_env.update(env or {})
    try:
        proc = subprocess.run(
            cmd, cwd=cwd, timeout=timeout, capture_output=True, text=True, env=full_env
        )
        return proc.returncode, proc.stdout, proc.stderr, False
    except subprocess.TimeoutExpired as exc:
        return -1, exc.stdout or "", f"timed out after {timeout}s", True


def run_sql(code: str, cwd: str, timeout: int) -> tuple[int, str, str]:
    """Execute SQL in an in-memory SQLite db, printing result sets."""
    conn = sqlite3.connect(":memory:")
    out: list[str] = []
    buffer = ""
    statements: list[str] = []
    for line in code.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            statements.append(buffer)
            buffer = ""
    if buffer.strip():
        statements.append(buffer)
    cursor = conn.cursor()
    for stmt in statements:
        stripped = stmt.strip().rstrip(";").strip()
        if not stripped:
            continue
        if re.fullmatch(r"(?is)(CREATE|INSERT|UPDATE|DELETE|DROP|CREATE INDEX).*", stripped) and not re.search(
            r"(?i)\breturning\b", stripped
        ):
            cursor.execute(stripped)
            continue
        cursor.execute(stripped)
        if cursor.description:
            out.append("|".join(d[0] for d in cursor.description))
            for row in cursor.fetchall():
                out.append("|".join("" if v is None else str(v) for v in row))
    conn.commit()
    return 0, "\n".join(out) + ("\n" if out else ""), ""


TS_MODE_TYPECHECK = "typecheck"


def execute(rec: dict, workdir: Path) -> Outcome:
    v = rec["verification"]
    kind = v["kind"]
    language = v.get("language", rec["language"])
    code = v.get("code", "")
    expected = v.get("expect_output", "")
    out = Outcome(rec["id"], kind, language, "PASS" if kind != "reviewed" else "PASS")
    start = time.time()

    if kind == "reviewed":
        out.status = "PASS"
        out.detail = "no executable artifact; review checklist in notes"
        out.duration_s = time.time() - start
        return out

    timeout = DEFAULT_TIMEOUT
    if code.strip() == "":
        out.status = "FAIL"
        out.detail = "empty @code block"
        return out

    try:
        if language == "python":
            src = workdir / "case.py"
            src.write_text(code, encoding="utf-8")
            rc, so, se, to = _run([sys.executable, str(src)], str(workdir), timeout)
            tool = "python3"
        elif language == "javascript":
            ext = ".cjs" if re.search(r"\brequire\s*\(", code) else ".mjs"
            src = workdir / f"case{ext}"
            src.write_text(code, encoding="utf-8")
            rc, so, se, to = _run(["node", str(src)], str(workdir), timeout)
            tool = "node"
        elif language == "typescript":
            tsc = shutil.which("tsc") or str(ROOT / "node_modules" / ".bin" / "tsc")
            if not Path(tsc).exists():
                out.status = "SKIP"
                out.detail = "tsc not installed (`npm i -D typescript` to enable)"
                return out
            src = workdir / "case.ts"
            src.write_text(code, encoding="utf-8")
            mode = v.get("mode", "run")
            if mode == TS_MODE_TYPECHECK:
                rc, so, se, to = _run(
                    [tsc, "--strict", "--noEmit", "--target", "ES2022", "--module", "commonjs",
                     "--lib", "ES2022,DOM", "case.ts"],
                    str(workdir), timeout,
                )
                so = "TYPECHECK_OK\n" if rc == 0 else so
            else:
                rc, so, se, to = _run(
                    [tsc, "--strict", "--target", "ES2022", "--module", "commonjs",
                     "--lib", "ES2022,DOM", "--outDir", "out", "case.ts"],
                    str(workdir), timeout,
                )
                if rc == 0:
                    rc, so, se, to = _run(["node", "out/case.js"], str(workdir), timeout)
            tool = "tsc"
        elif language in ("c", "cpp"):
            src = workdir / ("case.c" if language == "c" else "case.cpp")
            src.write_text(code, encoding="utf-8")
            flags = v.get("flags", "")
            if language == "c":
                cmd = ["gcc", "-std=c11", "-Wall", "-Wextra", "-O1", "-o", "case.bin", str(src)]
            else:
                cmd = ["g++", "-std=c++20", "-Wall", "-Wextra", "-O1", "-o", "case.bin", str(src)]
            env = {}
            if "asan" in flags:
                cmd[1:1] = ["-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-g"]
                env = {"ASAN_OPTIONS": "detect_leaks=1:abort_on_error=0"}
            compile_proc = subprocess.run(cmd, cwd=workdir, capture_output=True, text=True)
            if compile_proc.returncode != 0:
                out.status = "FAIL"
                out.detail = f"compile failed (gcc/g++):\n```\n{compile_proc.stderr[-1500:]}\n```"
                return out
            rc, so, se, to = _run(["./case.bin"], str(workdir), timeout, env)
            tool = "gcc" if language == "c" else "g++"
        elif language == "bash":
            src = workdir / "case.sh"
            src.write_text(code, encoding="utf-8")
            rc, so, se, to = _run(["bash", str(src)], str(workdir), timeout)
            tool = "bash"
        elif language == "sql":
            rc, so, se = run_sql(code, str(workdir), timeout)
            to = False
            tool = "sqlite3(py)"
        else:
            out.status = "SKIP"
            out.detail = f"no runner for language {language!r} (use kind=parity or reviewed)"
            return out
    except Exception as exc:  # pragma: no cover - defensive
        out.status = "FAIL"
        out.detail = f"runner crashed: {exc!r}"
        out.duration_s = time.time() - start
        return out

    out.duration_s = time.time() - start
    if to:
        out.status = "FAIL"
        out.detail = f"{tool}: timeout"
        return out
    if rc != 0:
        out.status = "FAIL"
        out.detail = f"{tool} exit={rc}; stderr:\n```\n{(se or '')[-1200:]}\n```"
        return out
    ok, why = _compare(so, expected)
    if not ok:
        out.status = "FAIL"
        out.detail = f"{tool}: {why}"
        if se:
            out.detail += f"\n\nstderr:\n```\n{se[-800:]}\n```"
        return out
    out.status = "PASS"
    out.detail = f"{tool}: {why}"
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="filter example ids by substring")
    ap.add_argument("--kind", default="", help="filter by verification kind")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument(
        "--dataset", type=Path, default=EXAMPLES,
        help="examples.jsonl to verify (default: dataset/examples.jsonl)",
    )
    ap.add_argument(
        "--report", type=Path, default=None,
        help="where to write the markdown report (default: next to the dataset)",
    )
    args = ap.parse_args()

    dataset_path = args.dataset
    report_path = args.report or dataset_path.parent / "verification_report.md"

    if not dataset_path.exists():
        print(f"missing {dataset_path}; run tools/build_dataset.py first", file=sys.stderr)
        return 2

    records = [json.loads(line) for line in dataset_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if args.only:
        records = [r for r in records if args.only in r["id"]]
    if args.kind:
        records = [r for r in records if r["verification"]["kind"] == args.kind]

    outcomes: list[Outcome] = []
    static_problems: dict[str, list[str]] = {}
    for rec in records:
        v = rec["verification"]
        if v.get("code"):
            problems = static_checks(v["code"], v.get("language", rec["language"]))
            if problems:
                static_problems[rec["id"]] = problems
        with tempfile.TemporaryDirectory(prefix=f"verify-{rec['id']}-") as tmp:
            try:
                outcome = execute(rec, Path(tmp))
            except Exception as exc:
                outcome = Outcome(rec["id"], v["kind"], v.get("language", rec["language"]), "FAIL", f"{exc!r}")
        if rec["id"] in static_problems:
            outcome.notes = ["static: " + "; ".join(static_problems[rec["id"]])]
            if outcome.status == "PASS":
                outcome.status = "FAIL"
                outcome.detail = "static checks failed: " + "; ".join(static_problems[rec["id"]])
        outcomes.append(outcome)
        if not args.quiet:
            mark = {"PASS": "ok  ", "FAIL": "FAIL", "SKIP": "skip"}[outcome.status]
            print(f"{mark} {outcome.id:<28} {outcome.duration_s:5.2f}s  {outcome.detail.splitlines()[0][:90]}")

    passed = sum(o.status == "PASS" for o in outcomes)
    failed = [o for o in outcomes if o.status == "FAIL"]
    skipped = [o for o in outcomes if o.status == "SKIP"]

    lines = [
        "# Verification report",
        "",
        f"- examples checked: **{len(outcomes)}**",
        f"- passed: **{passed}**",
        f"- failed: **{len(failed)}**",
        f"- skipped (toolchain missing): **{len(skipped)}**",
        "",
        "`executable` = the program under test really ran and its stdout matched the",
        "documented output. `parity` = the algorithm was executed via the Python",
        "reference implementation in `@code` against the same test vectors; the",
        "snippet's syntax was reviewed manually (see the `PARITY:` line in the notes).",
        "`reviewed` = design/vendor-specific artifact with a written checklist.",
        "",
        "| example | kind | lang | status | time | evidence |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for o in outcomes:
        first_line = o.detail.splitlines()[0][:160].replace("|", "\\|")
        lines.append(f"| `{o.id}` | {o.kind} | {o.language} | {o.status} | {o.duration_s:.2f}s | {first_line} |")
    if failed:
        lines += ["", "## Failures", ""]
        for o in failed:
            lines += [f"### {o.id}", "", "```", o.detail, "```", ""]
    lines += ["", "## Notes captured during review", ""]
    for rec in records:
        note = rec["verification"].get("notes")
        if note:
            lines += [f"### {rec['id']}", "", note.strip(), ""]

    if not args.only and not args.kind:      # filtered runs must not clobber the report
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n{passed}/{len(outcomes)} passed, {len(failed)} failed, {len(skipped)} skipped -> {report_path}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
