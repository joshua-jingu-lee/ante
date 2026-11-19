#!/usr/bin/env python3
"""Fail when comments or docstring history under ``src/ante/`` differ from the baseline.

Measured per file in ``src/ante/**/*.py``:

- comments: ``COMMENT`` tokens outside the allow list (rule-coded ``noqa``,
  coded ``type: ignore[...]``, ``pragma: no cover``, the shebang line).
- docstring history: docstring source lines matching an issue number,
  ``Refs``, ``attempt N``, ``Codex``, ``Finding`` or ``SPLIT-N``.

Measured in total: docstring source lines. A docstring here is any expression
statement whose value is a string constant: the first statement of a module,
class or function body, and also bare strings in the middle of a body or after
a class attribute. This is wider than ``check_review_scope.py`` on purpose,
because such strings can stand in for comments.

Exit 0: all three values equal ``scripts/comment_baseline.json``.
Exit 1: any value is above or below the baseline.
Exit 2: Python is older than 3.13, the baseline is missing or malformed, or a
source file cannot be read, tokenized or parsed.
"""

from __future__ import annotations

import argparse
import ast
import io
import json
import re
import sys
import tokenize
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

BASELINE_PATH = Path("scripts") / "comment_baseline.json"
TARGET_GLOB = "src/ante/**/*.py"
BASELINE_KEYS = frozenset({"comments", "docstring_history", "docstring_lines"})
MIN_PYTHON = (3, 13)

EXIT_OK = 0
EXIT_MISMATCH = 1
EXIT_ERROR = 2

ALLOWED_COMMENT_RE = re.compile(
    r"^(?:\s*(?:#\s*noqa:\s*[A-Z]+\d+(?:\s*,\s*[A-Z]+\d+)*"
    r"|#\s*type:\s*ignore\[[a-z0-9-]+(?:\s*,\s*[a-z0-9-]+)*\]"
    r"|#\s*pragma:\s*no cover))+\s*$"
)
HISTORY_PATTERNS = tuple(
    re.compile(pattern)
    for pattern in (
        r"#\d{3,}",
        r"\bRefs\b",
        r"(?i)\battempt[ -]?\d+",
        r"(?i)\bcodex\b",
        r"(?i)\bfindings?\b",
        r"\bSPLIT-\d+",
    )
)
LINE_BREAK_RE = re.compile(r"\r\n|\r|\n")

ALTERNATIVES = (
    "새 주석 대신:\n"
    "  - 이름을 고치거나 함수로 추출한다\n"
    "  - 불변식은 타입·assert·테스트로 옮긴다\n"
    "  - 이력은 커밋 메시지에 쓴다\n"
    "파일을 옮기거나 나눈 것이면 기준선의 키를 새 경로로 옮긴다."
)


class CheckError(RuntimeError):
    """Raised when the measurement or the baseline cannot be trusted."""


@dataclass(frozen=True)
class Measurement:
    comments: dict[str, int]
    docstring_history: dict[str, int]
    docstring_lines: int


def target_files(root: Path) -> list[Path]:
    return sorted(path for path in root.glob(TARGET_GLOB) if path.is_file())


def is_allowed_comment(token: tokenize.TokenInfo) -> bool:
    if token.start == (1, 0) and token.string.startswith("#!"):
        return True
    return ALLOWED_COMMENT_RE.match(token.string) is not None


def count_comments(data: bytes) -> int:
    tokens = tokenize.tokenize(io.BytesIO(data).readline)
    return sum(
        1
        for token in tokens
        if token.type == tokenize.COMMENT and not is_allowed_comment(token)
    )


def docstring_spans(tree: ast.AST) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            end = node.end_lineno if node.end_lineno is not None else node.lineno
            spans.append((node.lineno, end))
    return sorted(spans)


def is_history_line(line: str) -> bool:
    return any(pattern.search(line) for pattern in HISTORY_PATTERNS)


def measure_docstrings(data: bytes) -> tuple[int, int]:
    """Return (history line count, total docstring line count) for one file."""
    encoding, _ = tokenize.detect_encoding(io.BytesIO(data).readline)
    source = data.decode(encoding)
    tree = ast.parse(source)
    lines = LINE_BREAK_RE.split(source)
    history = 0
    total = 0
    for start, end in docstring_spans(tree):
        total += end - start + 1
        history += sum(1 for line in lines[start - 1 : end] if is_history_line(line))
    return history, total


def measure(root: Path) -> Measurement:
    comments: dict[str, int] = {}
    history: dict[str, int] = {}
    docstring_lines = 0
    for path in target_files(root):
        rel = path.relative_to(root).as_posix()
        try:
            data = path.read_bytes()
            comment_count = count_comments(data)
            history_count, line_count = measure_docstrings(data)
        except Exception as exc:
            raise CheckError(
                f"cannot read, tokenize or parse {rel}: {type(exc).__name__}: {exc}"
            ) from exc
        if comment_count:
            comments[rel] = comment_count
        if history_count:
            history[rel] = history_count
        docstring_lines += line_count
    return Measurement(comments, history, docstring_lines)


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _read_counts(data: dict[str, object], key: str) -> dict[str, int]:
    value = data[key]
    if not isinstance(value, dict):
        raise CheckError(f"{BASELINE_PATH}: {key!r} must be an object")
    counts: dict[str, int] = {}
    for path, count in value.items():
        if not _is_int(count) or count <= 0:
            raise CheckError(
                f"{BASELINE_PATH}: {key}[{path!r}] must be a positive integer, "
                f"got {count!r}"
            )
        counts[path] = count
    return counts


def read_baseline(root: Path) -> Measurement:
    path = root / BASELINE_PATH
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise CheckError(f"baseline file not found: {BASELINE_PATH}") from exc
    except (OSError, UnicodeDecodeError) as exc:
        raise CheckError(f"cannot read {BASELINE_PATH}: {exc}") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CheckError(f"{BASELINE_PATH} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise CheckError(f"{BASELINE_PATH} must hold a JSON object")
    keys = set(data)
    if keys != BASELINE_KEYS:
        missing = sorted(BASELINE_KEYS - keys)
        extra = sorted(keys - BASELINE_KEYS)
        raise CheckError(
            f"{BASELINE_PATH} must have exactly the keys {sorted(BASELINE_KEYS)} "
            f"(missing {missing}, extra {extra})"
        )
    lines = data["docstring_lines"]
    if not _is_int(lines) or lines < 0:
        raise CheckError(
            f"{BASELINE_PATH}: 'docstring_lines' must be a non-negative integer, "
            f"got {lines!r}"
        )
    return Measurement(
        _read_counts(data, "comments"),
        _read_counts(data, "docstring_history"),
        lines,
    )


def _diff_counts(
    kind: str,
    actual: dict[str, int],
    baseline: dict[str, int],
    lines: list[str],
    lower: list[str],
) -> bool:
    grew = False
    for path in sorted(set(actual) | set(baseline)):
        got = actual.get(path, 0)
        want = baseline.get(path, 0)
        if got == want:
            continue
        lines.append(f"{kind}\t{path}: actual {got}, baseline {want} ({got - want:+d})")
        if got > want:
            grew = True
        elif got == 0:
            lower.append(f"  - {kind}에서 {path!r} 키를 지운다")
        else:
            lower.append(f"  - {kind}[{path!r}]를 {got}로 낮춘다")
    return grew


def judge(actual: Measurement, baseline: Measurement) -> tuple[int, str]:
    lines: list[str] = []
    lower: list[str] = []
    grew = _diff_counts("comments", actual.comments, baseline.comments, lines, lower)
    grew |= _diff_counts(
        "docstring_history",
        actual.docstring_history,
        baseline.docstring_history,
        lines,
        lower,
    )
    docstring_grew = False
    got, want = actual.docstring_lines, baseline.docstring_lines
    if got != want:
        lines.append(
            f"docstring_lines: actual {got}, baseline {want} ({got - want:+d})"
        )
        if got > want:
            docstring_grew = True
        else:
            lower.append(f"  - docstring_lines를 {got}로 낮춘다")
    if not lines:
        return EXIT_OK, (
            f"comment check ok: {sum(actual.comments.values())} comments, "
            f"{sum(actual.docstring_history.values())} docstring history lines, "
            f"{actual.docstring_lines} docstring lines (baseline {BASELINE_PATH})"
        )
    parts = [f"comment check failed against {BASELINE_PATH}:", *lines]
    if grew:
        parts.append(ALTERNATIVES)
    if docstring_grew:
        parts.append(
            f"독스트링 총 줄 수가 {got - want}줄 늘었다. 다른 독스트링을 그만큼 줄인다."
        )
    if lower:
        parts.append(f"줄어든 값은 {BASELINE_PATH}의 기준선을 실측으로 낮춘다:")
        parts.extend(lower)
    return EXIT_MISMATCH, "\n".join(parts)


def run(root: Path) -> tuple[int, str]:
    if sys.version_info < MIN_PYTHON:
        return EXIT_ERROR, (
            f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ is required: the tokenizer "
            "reports comments inside f-strings differently on older versions"
        )
    try:
        baseline = read_baseline(root)
        actual = measure(root)
    except CheckError as exc:
        return EXIT_ERROR, str(exc)
    return judge(actual, baseline)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check src/ante comments and docstring history against a baseline."
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
