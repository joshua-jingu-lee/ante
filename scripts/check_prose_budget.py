#!/usr/bin/env python3
"""Fail when the agent-instruction prose line count differs from the baseline.

Measured files: ``.agent/commands/*.md``, ``.agent/agents/*.md``,
``.agent/skills/*.md``, ``AGENTS.md``, ``docs/runbooks/0*.md`` and
``docs/runbooks/README.md``. Files whose name starts with ``.`` and symbolic
links are not counted. A line is one ``\\n`` byte, the same as ``wc -l``.

Exit 0: the total equals the baseline in ``.agent/prose-baseline.txt``.
Exit 1: the total is above or below the baseline.
Exit 2: the baseline file is missing or does not hold a single number.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

BASELINE_PATH = Path(".agent") / "prose-baseline.txt"
TARGET_GLOBS = (
    ".agent/commands/*.md",
    ".agent/agents/*.md",
    ".agent/skills/*.md",
    "AGENTS.md",
    "docs/runbooks/0*.md",
    "docs/runbooks/README.md",
)

EXIT_OK = 0
EXIT_MISMATCH = 1
EXIT_BAD_BASELINE = 2


class BaselineError(RuntimeError):
    """Raised when the baseline file cannot be read as a line count."""


def target_files(root: Path) -> list[Path]:
    """Return the measured files under ``root`` in a stable order."""
    found: set[Path] = set()
    for pattern in TARGET_GLOBS:
        for path in root.glob(pattern):
            if path.name.startswith(".") or path.is_symlink() or not path.is_file():
                continue
            found.add(path)
    return sorted(found)


def count_lines(path: Path) -> int:
    return path.read_bytes().count(b"\n")


def measure(root: Path) -> int:
    return sum(count_lines(path) for path in target_files(root))


def read_baseline(root: Path) -> int:
    path = root / BASELINE_PATH
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise BaselineError(f"baseline file not found: {BASELINE_PATH}") from exc
    except (OSError, UnicodeDecodeError) as exc:
        raise BaselineError(f"cannot read {BASELINE_PATH}: {exc}") from exc
    return parse_baseline(text)


def parse_baseline(text: str) -> int:
    """Return the line count held by the baseline file text."""
    value = text.strip()
    if not value.isascii() or not value.isdigit():
        raise BaselineError(
            f"{BASELINE_PATH} must hold one non-negative integer, got {value!r}"
        )
    return int(value)


def judge(actual: int, baseline: int) -> tuple[int, str]:
    if actual == baseline:
        return EXIT_OK, f"prose budget ok: {actual} lines (baseline {baseline})"
    if actual > baseline:
        return EXIT_MISMATCH, (
            f"prose budget exceeded: {actual} lines, baseline {baseline} "
            f"(+{actual - baseline}).\n"
            "Turn the new rule into a check or a test instead of prose, "
            "or remove the same number of lines elsewhere in this PR."
        )
    return EXIT_MISMATCH, (
        f"prose shrank: {actual} lines, baseline {baseline} "
        f"(-{baseline - actual}).\n"
        f"Lower the baseline: write {actual} to {BASELINE_PATH}."
    )


def run(root: Path) -> tuple[int, str]:
    try:
        baseline = read_baseline(root)
    except BaselineError as exc:
        return EXIT_BAD_BASELINE, str(exc)
    return judge(measure(root), baseline)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check the agent-instruction prose line count against the baseline."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="repository root (default: the checkout containing this script)",
    )
    args = parser.parse_args(argv)
    code, message = run(args.root)
    stream = sys.stdout if code == EXIT_OK else sys.stderr
    print(message, file=stream)
    return code


if __name__ == "__main__":
    sys.exit(main())
