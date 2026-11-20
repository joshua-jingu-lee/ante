#!/usr/bin/env python3
"""Fail when comments or docstrings under ``src/ante/`` differ from the baseline.

A docstring here is any expression statement whose value is a string constant:
the first statement of a module, class or function body, and also bare strings
in the middle of a body or after a class attribute. This is wider than
``check_review_scope.py`` on purpose, because such strings can stand in for
comments. Its length is its source lines, from the opening to the closing quote.

Each docstring has exactly one owner, which sets its line limit:

- ``click``: first statement of a function with a decorator whose attribute
  name is ``command`` or ``group``, called or not. No limit.
- ``private``: first statement of any other function whose name starts with
  ``_`` and is not a dunder (``__x__``), nested functions included. Limit 1.
- ``public``: first statement of any other function (dunders, nested
  functions, methods of private classes). Limit 10.
- ``class``: first statement of a class body. Limit 10.
- ``module``: first statement of the module. Limit 3.
- ``attribute``: a string statement directly in a module or class body right
  after an ``Assign`` or ``AnnAssign``. Limit 3.
- ``other``: every other string statement, including those after an
  assignment inside a function body. Limit 0.

Measured per file in ``src/ante/**/*.py``:

- comments: ``COMMENT`` tokens outside the allow list (rule-coded ``noqa``,
  coded ``type: ignore[...]``, ``pragma: no cover``, the shebang line).
- docstring history: docstring source lines matching an issue number,
  ``Refs``, ``attempt N``, ``Codex``, ``Finding`` or ``SPLIT-N``.
- docstring excess: the sum of ``max(0, lines - limit)`` over its docstrings.

Measured in total: docstring source lines.

Known limits of docstring excess: it is a per-file sum, so shortening one
docstring and lengthening another in the same file by as much still passes.
The ``click`` test reads the attribute name only, so a function decorated with
``.command`` or ``.group`` of a non-Click object has no limit, and a bare-name
decorator (``@command()`` after ``from click import command``) is not
``click``.

Exit 0: all four values equal ``scripts/comment_baseline.json``.
Exit 1: any value is above or below the baseline. Only the comparison
produces this code.
Exit 2: every other failure: Python older than 3.13, a missing or malformed
baseline, a source file that cannot be read, tokenized or parsed, or any
unexpected exception.
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
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypeGuard

BASELINE_PATH = Path("scripts") / "comment_baseline.json"
TARGET_GLOB = "src/ante/**/*.py"
BASELINE_KEYS = frozenset(
    {"comments", "docstring_history", "docstring_excess", "docstring_lines"}
)
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
    "  - 이력은 커밋 메시지에 쓴다"
)
MOVE_HINT = "파일을 옮기거나 나눈 것이면 기준선의 키를 새 경로로 옮긴다."

CLICK = "click"
PRIVATE = "private"
PUBLIC = "public"
CLASS = "class"
MODULE = "module"
ATTRIBUTE = "attribute"
OTHER = "other"
LIMITS: dict[str, int | None] = {
    CLICK: None,
    PRIVATE: 1,
    PUBLIC: 10,
    CLASS: 10,
    MODULE: 3,
    ATTRIBUTE: 3,
    OTHER: 0,
}
CLICK_DECORATOR_ATTRS = frozenset({"command", "group"})
FUNCTION_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)
STATEMENT_NODES = (ast.stmt, ast.excepthandler, ast.match_case)

EXCESS_ALTERNATIVES = (
    "상한: private 함수 1줄, 모듈·속성 3줄, public 함수·클래스 10줄, "
    "그 밖의 문자열 문장 0줄, Click 명령은 없음.\n"
    "상한을 넘긴 독스트링 대신:\n"
    "  - 독스트링을 줄인다\n"
    "  - 불변식은 테스트로 옮긴다"
)


class CheckError(RuntimeError):
    """Raised when the measurement or the baseline cannot be trusted."""


@dataclass(frozen=True)
class Docstring:
    start: int
    end: int
    owner: str
    name: str

    @property
    def lines(self) -> int:
        return self.end - self.start + 1

    @property
    def limit(self) -> int | None:
        return LIMITS[self.owner]

    @property
    def excess(self) -> int:
        limit = self.limit
        return 0 if limit is None else max(0, self.lines - limit)


@dataclass(frozen=True)
class Measurement:
    comments: dict[str, int]
    docstring_history: dict[str, int]
    docstring_excess: dict[str, int]
    docstring_lines: int
    oversized: dict[str, list[Docstring]] = field(default_factory=dict, compare=False)


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


def is_string_statement(node: ast.AST) -> TypeGuard[ast.Expr]:
    return (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    )


def _span(node: ast.stmt) -> tuple[int, int]:
    end = node.end_lineno if node.end_lineno is not None else node.lineno
    return node.lineno, end


def docstring_spans(tree: ast.AST) -> list[tuple[int, int]]:
    return sorted(_span(node) for node in ast.walk(tree) if is_string_statement(node))


def is_click_decorator(decorator: ast.expr) -> bool:
    target = decorator.func if isinstance(decorator, ast.Call) else decorator
    return isinstance(target, ast.Attribute) and target.attr in CLICK_DECORATOR_ATTRS


def is_dunder(name: str) -> bool:
    return len(name) > 4 and name.startswith("__") and name.endswith("__")


def function_owner(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    if any(is_click_decorator(decorator) for decorator in node.decorator_list):
        return CLICK
    if node.name.startswith("_") and not is_dunder(node.name):
        return PRIVATE
    return PUBLIC


def _qualname(scope: tuple[str, ...], name: str | None = None) -> str:
    parts = scope if name is None else (*scope, name)
    return ".".join(parts) if parts else "<module>"


def _target_name(node: ast.Assign | ast.AnnAssign) -> str:
    target = node.targets[0] if isinstance(node, ast.Assign) else node.target
    return ast.unparse(target).replace(" ", "")


def _classify(
    parent: ast.AST,
    body: list[ast.stmt],
    index: int,
    scope: tuple[str, ...],
) -> tuple[str, str]:
    first = index == 0
    if isinstance(parent, ast.Module) and first:
        return MODULE, "<module>"
    if isinstance(parent, ast.ClassDef) and first:
        return CLASS, _qualname(scope)
    if isinstance(parent, FUNCTION_NODES) and first:
        return function_owner(parent), _qualname(scope)
    previous = body[index - 1] if index else None
    if isinstance(parent, (ast.Module, ast.ClassDef)) and isinstance(
        previous, (ast.Assign, ast.AnnAssign)
    ):
        return ATTRIBUTE, _qualname(scope, _target_name(previous))
    return OTHER, _qualname(scope)


def _collect(node: ast.AST, scope: tuple[str, ...], found: list[Docstring]) -> None:
    for name, value in ast.iter_fields(node):
        if not isinstance(value, list):
            continue
        for index, child in enumerate(value):
            if not isinstance(child, STATEMENT_NODES):
                continue
            if is_string_statement(child):
                if name == "body":
                    owner, label = _classify(node, value, index, scope)
                else:
                    owner, label = OTHER, _qualname(scope)
                found.append(Docstring(*_span(child), owner, label))
            if isinstance(child, (*FUNCTION_NODES, ast.ClassDef)):
                _collect(child, (*scope, child.name), found)
            else:
                _collect(child, scope, found)


def classify_docstrings(tree: ast.Module) -> list[Docstring]:
    """Give every string statement of the tree its owner, in source order."""
    found: list[Docstring] = []
    _collect(tree, (), found)
    return sorted(found, key=lambda doc: (doc.start, doc.end))


def is_history_line(line: str) -> bool:
    return any(pattern.search(line) for pattern in HISTORY_PATTERNS)


def _parse(data: bytes) -> tuple[ast.Module, list[str]]:
    encoding, _ = tokenize.detect_encoding(io.BytesIO(data).readline)
    source = data.decode(encoding)
    return ast.parse(source), LINE_BREAK_RE.split(source)


def measure_docstrings(data: bytes) -> tuple[int, int]:
    """Return (history line count, total docstring line count) for one file."""
    tree, lines = _parse(data)
    history = 0
    total = 0
    for start, end in docstring_spans(tree):
        total += end - start + 1
        history += sum(1 for line in lines[start - 1 : end] if is_history_line(line))
    return history, total


def oversized_docstrings(data: bytes) -> list[Docstring]:
    """Return the docstrings of one file that are longer than their limit."""
    tree, _ = _parse(data)
    return [doc for doc in classify_docstrings(tree) if doc.excess]


def measure(root: Path) -> Measurement:
    comments: dict[str, int] = {}
    history: dict[str, int] = {}
    excess: dict[str, int] = {}
    oversized: dict[str, list[Docstring]] = {}
    docstring_lines = 0
    for path in target_files(root):
        rel = path.relative_to(root).as_posix()
        try:
            data = path.read_bytes()
            comment_count = count_comments(data)
            history_count, line_count = measure_docstrings(data)
            long_docstrings = oversized_docstrings(data)
        except Exception as exc:
            raise CheckError(
                f"cannot read, tokenize or parse {rel}: {type(exc).__name__}: {exc}"
            ) from exc
        if comment_count:
            comments[rel] = comment_count
        if history_count:
            history[rel] = history_count
        if long_docstrings:
            excess[rel] = sum(doc.excess for doc in long_docstrings)
            oversized[rel] = long_docstrings
        docstring_lines += line_count
    return Measurement(comments, history, excess, docstring_lines, oversized)


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
    return parse_baseline(text)


def parse_baseline(text: str) -> Measurement:
    """Validate baseline JSON text; raise ``CheckError`` when it is malformed."""
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
        _read_counts(data, "docstring_excess"),
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
    excess_grew = _diff_counts(
        "docstring_excess",
        actual.docstring_excess,
        baseline.docstring_excess,
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
            f"{sum(actual.docstring_excess.values())} docstring excess lines, "
            f"{actual.docstring_lines} docstring lines (baseline {BASELINE_PATH})"
        )
    parts = [f"comment check failed against {BASELINE_PATH}:", *lines]
    if grew:
        parts.append(ALTERNATIVES)
    if excess_grew:
        parts.append("상한을 넘는 독스트링(경로:줄 소유자 이름 줄 수>상한):")
        for path in sorted(actual.docstring_excess):
            if actual.docstring_excess[path] <= baseline.docstring_excess.get(path, 0):
                continue
            parts.extend(
                f"  {path}:{doc.start} {doc.owner} {doc.name} {doc.lines}>{doc.limit}"
                for doc in actual.oversized.get(path, [])
            )
        parts.append(EXCESS_ALTERNATIVES)
    if grew or excess_grew:
        parts.append(MOVE_HINT)
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
        description="Check src/ante comments and docstrings against a baseline."
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
        message = f"comment check error: {type(exc).__name__}: {exc}"
    stream = sys.stdout if code == EXIT_OK else sys.stderr
    print(message, file=stream)
    return code


if __name__ == "__main__":
    sys.exit(main())
