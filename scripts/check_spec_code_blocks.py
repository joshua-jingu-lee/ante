#!/usr/bin/env python3
"""Fail when code copied into ``docs/specs`` differs from the baseline.

Measured files: regular ``docs/specs/**/*.md`` files. Files whose name starts
with ``.`` and symbolic links are not counted. Three values are measured:

- ``python``, ``sql``: lines inside fenced code blocks whose language is
  exactly that word.
- ``py_line_refs``: line references to ``.py`` files outside code blocks.

A fence opens on a line of zero or more spaces or tabs, then three or more
backticks or tildes, then an info string. Unlike CommonMark the indentation
width does not matter. A backtick fence whose info string holds a backtick is
not a fence. The block closes on a line of the same character, at least as
long as the opening run, with only spaces or tabs around it. Any other line,
fence-shaped or not, is content (no nesting). Fence lines are not counted. The
language is the lowercased first word of the info string; the rest of the info
string is ignored.

A line reference is zero or more of ``[A-Za-z0-9_./-]``, then ``.py:``, then a
list of items separated by ``,`` where each item is ``N`` or ``N-M``. Each item
counts as one, so adding an item to a list raises the count. Path prefixes and
backticks around the reference do not matter. ``.md:``, ``.pyi:`` and ``#L``
references are not counted.

Known limits:

- Removing or changing the language of a block hides it. Blocks without a
  language are already outside this check, so closing that gap would mean
  classifying every block.
- Block quotes (``>``) and ``<pre>`` are not counted.
- Only the totals are compared, so moving lines between files passes.
- Only digits right after ``.py:`` count. Prose such as ``line N``, a
  reference split by backticks, ``L<N>`` and other extensions are not counted.

Baseline update: when another change moves a value, write each key on its own
line with the value measured again on the latest main just before merging.

Exit 0: all three values equal ``scripts/spec_code_block_baseline.json``.
Exit 1: any value is above or below the baseline.
Exit 2: the decision could not be made: an unclosed block, a file that is not
UTF-8 or cannot be read, or a missing or malformed baseline.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

BASELINE_PATH = Path("scripts") / "spec_code_block_baseline.json"
SPECS_DIR = Path("docs") / "specs"
BASELINE_KEYS = ("python", "sql", "py_line_refs")

EXIT_OK = 0
EXIT_MISMATCH = 1
EXIT_ERROR = 2

OPEN_FENCE_RE = re.compile(r"^[ \t]*(?P<fence>`{3,}|~{3,})(?P<info>.*)$")
LINE_REF_RE = re.compile(
    r"[A-Za-z0-9_./-]*\.py:(?P<items>[0-9]+(?:-[0-9]+)?(?:,[0-9]+(?:-[0-9]+)?)*)"
)

GROWTH_ADVICE = (
    "If the block or reference copies code, remove it and point to the code "
    "file and name, or to the generated document under "
    "docs/architecture/generated/ (no line numbers).\n"
    "If it describes a design that is not implemented yet, raise the baseline; "
    "that change goes through Gate A.\n"
    "Do not dodge the check by changing the block's language."
)


class CheckError(RuntimeError):
    """Raised when a spec file or the baseline cannot be judged."""


@dataclass
class Counts:
    python: int = 0
    sql: int = 0
    py_line_refs: int = 0

    def as_dict(self) -> dict[str, int]:
        return {key: getattr(self, key) for key in BASELINE_KEYS}


def target_files(root: Path) -> list[Path]:
    """Return the measured files under ``root`` in a stable order."""
    found: list[Path] = []
    for path in (root / SPECS_DIR).glob("**/*.md"):
        if path.name.startswith(".") or path.is_symlink() or not path.is_file():
            continue
        found.append(path)
    return sorted(found)


def _count_refs(line: str) -> int:
    return sum(
        match.group("items").count(",") + 1 for match in LINE_REF_RE.finditer(line)
    )


def _is_close(line: str, char: str, length: int) -> bool:
    stripped = line.strip(" \t")
    return len(stripped) >= length and stripped == char * len(stripped)


def count_text(text: str, name: str = "<text>") -> Counts:
    """Count block lines and line references in one Markdown text."""
    counts = Counts()
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    fence: tuple[str, int, str, int] | None = None
    for number, line in enumerate(lines, start=1):
        if fence is not None:
            char, length, language, _ = fence
            if _is_close(line, char, length):
                fence = None
            elif language == "python":
                counts.python += 1
            elif language == "sql":
                counts.sql += 1
            continue
        match = OPEN_FENCE_RE.match(line)
        if match is not None:
            run, info = match.group("fence"), match.group("info")
            if not (run[0] == "`" and "`" in info):
                words = info.split()
                language = words[0].lower() if words else ""
                fence = (run[0], len(run), language, number)
                continue
        counts.py_line_refs += _count_refs(line)
    if fence is not None:
        raise CheckError(f"{name}:{fence[3]}: code block is not closed")
    return counts


def measure(root: Path) -> Counts:
    total = Counts()
    for path in target_files(root):
        rel = path.relative_to(root).as_posix()
        try:
            text = path.read_bytes().decode("utf-8")
        except UnicodeDecodeError as exc:
            raise CheckError(f"{rel} is not UTF-8: {exc}") from exc
        except OSError as exc:
            raise CheckError(f"cannot read {rel}: {exc}") from exc
        counts = count_text(text, rel)
        total.python += counts.python
        total.sql += counts.sql
        total.py_line_refs += counts.py_line_refs
    return total


def parse_baseline(text: str) -> dict[str, int]:
    """Validate baseline JSON text; raise ``CheckError`` when it is malformed."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CheckError(f"{BASELINE_PATH} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise CheckError(f"{BASELINE_PATH} must hold a JSON object")
    if set(data) != set(BASELINE_KEYS):
        missing = sorted(set(BASELINE_KEYS) - set(data))
        extra = sorted(set(data) - set(BASELINE_KEYS))
        raise CheckError(
            f"{BASELINE_PATH} must have exactly the keys {list(BASELINE_KEYS)} "
            f"(missing {missing}, extra {extra})"
        )
    values: dict[str, int] = {}
    for key in BASELINE_KEYS:
        value = data[key]
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise CheckError(
                f"{BASELINE_PATH}: {key!r} must be a non-negative integer, "
                f"got {value!r}"
            )
        values[key] = value
    return values


def read_baseline(root: Path) -> dict[str, int]:
    path = root / BASELINE_PATH
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise CheckError(f"baseline file not found: {BASELINE_PATH}") from exc
    except (OSError, UnicodeDecodeError) as exc:
        raise CheckError(f"cannot read {BASELINE_PATH}: {exc}") from exc
    return parse_baseline(text)


def judge(actual: Counts, baseline: dict[str, int]) -> tuple[int, str]:
    values = actual.as_dict()
    if values == baseline:
        summary = ", ".join(f"{key} {values[key]}" for key in BASELINE_KEYS)
        return EXIT_OK, f"spec code blocks ok: {summary} (baseline {BASELINE_PATH})"
    parts = [f"spec code block check failed against {BASELINE_PATH}:"]
    grew = False
    lower: list[str] = []
    for key in BASELINE_KEYS:
        got, want = values[key], baseline[key]
        if got == want:
            continue
        parts.append(f"{key}: actual {got}, baseline {want} ({got - want:+d})")
        if got > want:
            grew = True
        else:
            lower.append(f"Lower {key} to {got}.")
    if grew:
        parts.append(GROWTH_ADVICE)
    parts.extend(lower)
    return EXIT_MISMATCH, "\n".join(parts)


def run(root: Path) -> tuple[int, str]:
    try:
        baseline = read_baseline(root)
        actual = measure(root)
    except CheckError as exc:
        return EXIT_ERROR, str(exc)
    return judge(actual, baseline)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check python/sql block lines and .py line references in "
        "docs/specs against the baseline."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="repository root (default: the checkout containing this script)",
    )
    args = parser.parse_args(argv)
    try:
        code, message = run(args.root)
    except Exception as exc:
        code = EXIT_ERROR
        message = f"spec code block check error: {type(exc).__name__}: {exc}"
    stream = sys.stdout if code == EXIT_OK else sys.stderr
    print(message, file=stream)
    return code


if __name__ == "__main__":
    sys.exit(main())
