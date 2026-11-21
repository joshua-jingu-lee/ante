#!/usr/bin/env python3
"""Fail when the CLI and IPC error exits differ from the baseline.

The sources are parsed with ``ast`` only; nothing under ``src/`` is imported.

Count keys, per file in ``src/ante/cli/**/*.py``:

- ``cli_error_calls``: calls ``<anything>.error(...)`` whose attribute name is
  exactly ``error``.
- ``cli_exits``: ``raise SystemExit`` with or without a call, ``raise`` of a
  name or attribute named ``Exit`` (``click.exceptions.Exit(...)``),
  ``.exit(...)`` on a receiver named ``ctx``, and ``.exit(...)`` on the ``sys``
  module or a name it was imported as.
- ``ipc_error_code_reads``: ``getattr(<anything>, "ipc_error_code", ...)``.

The count keys skip the entry hook, ``AuthenticatedGroup.main`` in
``src/ante/cli/middleware.py``. A tree without that function is exit 2.

Set key ``unregistered_codes``, over all of ``src/ante/**/*.py`` with no hook
exclusion: non-empty string literals in an error-code position that are not a
``code=`` value of an ``ErrorSpec(...)`` call in
``src/ante/contracts/error_registry.py``. The positions are:

1. the value of a ``code=`` keyword argument;
2. the value of a ``"code"`` key in a dict literal;
3. a ``code = ...`` or ``code: T = ...`` statement directly in a class body;
4. the value assigned to an ``ipc_error_code`` attribute, or to
   ``ipc_error_code`` directly in a class body;
5. the default of ``getattr(_, "ipc_error_code", D)``,
   ``getattr(_, "code", D)`` and ``_.get("code", D)``;
6. the second positional argument of ``<x>.error(...)``, unless the name just
   before ``.error``, without leading ``_``, starts with ``log``; and the
   second positional argument of ``_emit_auth_error(...)``;
7. a literal operand of an ``or`` whose expression is in positions 1 to 6, or
   whose other operand reads a code (``getattr(_, "code"|"ipc_error_code",
   ...)``, ``_.get("code", ...)``, ``_.code``, ``_.ipc_error_code``).

Known limits: codes that reach an exit outside these positions are not seen:
a code held in a variable or a module constant, a positional argument of a
module helper (``_exit_with_error(fmt, "CODE", ...)``), a conditional
expression, an f-string or a return value. Exits through helpers such as
``emit_cli_error`` are not counted either.
``self.ctx.exit(...)`` and ``click.get_current_context().exit(...)`` are not
counted as exits.
``setattr(e, "ipc_error_code", ...)`` and tuple assignments are not positions.

Exit 0: all four keys equal ``scripts/entry_ratchet_baseline.json``.
Exit 1: a count differs from the baseline in either direction, or the code
set differs. Only the comparison produces this code.
Exit 2: every other failure: a missing or malformed baseline, a source file
that cannot be read or parsed, a missing hook function or registry, or any
unexpected exception.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

BASELINE_PATH = Path("scripts") / "entry_ratchet_baseline.json"
CLI_GLOB = "src/ante/cli/**/*.py"
SOURCE_GLOB = "src/ante/**/*.py"
HOOK_PATH = "src/ante/cli/middleware.py"
HOOK_CLASS = "AuthenticatedGroup"
HOOK_FUNCTION = "main"
REGISTRY_PATH = "src/ante/contracts/error_registry.py"

CLI_ERROR_CALLS = "cli_error_calls"
CLI_EXITS = "cli_exits"
IPC_ERROR_CODE_READS = "ipc_error_code_reads"
UNREGISTERED_CODES = "unregistered_codes"
COUNT_KEYS = (CLI_ERROR_CALLS, CLI_EXITS, IPC_ERROR_CODE_READS)
BASELINE_KEYS = frozenset((*COUNT_KEYS, UNREGISTERED_CODES))

EXIT_OK = 0
EXIT_MISMATCH = 1
EXIT_ERROR = 2

CODE_ATTRS = frozenset({"code", "ipc_error_code"})
EXIT_NAMES = frozenset({"SystemExit", "Exit"})
LOGGER_PREFIX = "log"

ALTERNATIVES = (
    "새 에러 출구와 새 에러 코드 대신:\n"
    "  - 명령 안에서 끝내지 말고 타입 예외를 던진다\n"
    f"  - 그 예외와 코드를 에러 레지스트리({REGISTRY_PATH})에 등록한다"
)
MOVE_HINT = "파일을 옮기거나 나눈 것이면 기준선의 키를 새 경로로 옮긴다."


class CheckError(RuntimeError):
    """Raised when the measurement or the baseline cannot be trusted."""


@dataclass(frozen=True)
class Measurement:
    cli_error_calls: dict[str, int]
    cli_exits: dict[str, int]
    ipc_error_code_reads: dict[str, int]
    unregistered_codes: frozenset[str]

    def counts(self, key: str) -> dict[str, int]:
        value: dict[str, int] = getattr(self, key)
        return value


def target_files(root: Path, pattern: str) -> list[Path]:
    return sorted(path for path in root.glob(pattern) if path.is_file())


def _parse_file(root: Path, path: Path) -> ast.Module:
    rel = path.relative_to(root).as_posix()
    try:
        return ast.parse(path.read_bytes(), filename=rel)
    except Exception as exc:
        raise CheckError(
            f"cannot read or parse {rel}: {type(exc).__name__}: {exc}"
        ) from exc


def _terminal_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _string(node: ast.expr | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def hook_nodes(tree: ast.Module) -> set[int]:
    """Return the ids of every node inside ``AuthenticatedGroup.main``."""
    for node in tree.body:
        if not (isinstance(node, ast.ClassDef) and node.name == HOOK_CLASS):
            continue
        for item in node.body:
            if (
                isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                and item.name == HOOK_FUNCTION
            ):
                return {id(child) for child in ast.walk(item)}
    raise CheckError(
        f"hook function {HOOK_CLASS}.{HOOK_FUNCTION} not found in {HOOK_PATH}"
    )


def sys_aliases(tree: ast.Module) -> set[str]:
    aliases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "sys":
                    aliases.add(alias.asname or "sys")
    return aliases


def is_error_call(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "error"
    )


def is_exit(node: ast.AST, sys_names: set[str]) -> bool:
    if isinstance(node, ast.Raise) and node.exc is not None:
        raised = node.exc.func if isinstance(node.exc, ast.Call) else node.exc
        return _terminal_name(raised) in EXIT_NAMES
    if not (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "exit"
        and isinstance(node.func.value, ast.Name)
    ):
        return False
    receiver = node.func.value.id
    return receiver == "ctx" or receiver in sys_names


def _is_getattr_of(node: ast.AST, names: frozenset[str]) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "getattr"
        and len(node.args) >= 2
        and _string(node.args[1]) in names
    )


def is_ipc_error_code_read(node: ast.AST) -> bool:
    return _is_getattr_of(node, frozenset({"ipc_error_code"}))


def _is_get_code(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get"
        and len(node.args) >= 1
        and _string(node.args[0]) == "code"
    )


def reads_code(node: ast.expr) -> bool:
    if isinstance(node, ast.Attribute):
        return node.attr in CODE_ATTRS
    return _is_getattr_of(node, CODE_ATTRS) or _is_get_code(node)


def count_cli_file(tree: ast.Module, skip: set[int]) -> tuple[int, int, int]:
    """Return (error calls, exits, ipc_error_code reads) outside ``skip``."""
    sys_names = sys_aliases(tree)
    errors = exits = reads = 0
    for node in ast.walk(tree):
        if id(node) in skip:
            continue
        errors += is_error_call(node)
        exits += is_exit(node, sys_names)
        reads += is_ipc_error_code_read(node)
    return errors, exits, reads


def _is_logger_receiver(func: ast.Attribute) -> bool:
    name = _terminal_name(func.value)
    return name is not None and name.lstrip("_").startswith(LOGGER_PREFIX)


def _call_positions(node: ast.Call) -> Iterator[ast.expr]:
    for keyword in node.keywords:
        if keyword.arg == "code":
            yield keyword.value
    if _is_getattr_of(node, CODE_ATTRS) and len(node.args) >= 3:
        yield node.args[2]
    if _is_get_code(node) and len(node.args) >= 2:
        yield node.args[1]
    if len(node.args) < 2:
        return
    func = node.func
    if (
        isinstance(func, ast.Attribute)
        and func.attr == "error"
        and not _is_logger_receiver(func)
    ) or _terminal_name(func) == "_emit_auth_error":
        yield node.args[1]


def _class_positions(node: ast.ClassDef) -> Iterator[ast.expr]:
    for item in node.body:
        if isinstance(item, ast.Assign):
            if any(
                isinstance(target, ast.Name) and target.id in CODE_ATTRS
                for target in item.targets
            ):
                yield item.value
        elif (
            isinstance(item, ast.AnnAssign)
            and item.value is not None
            and isinstance(item.target, ast.Name)
            and item.target.id in CODE_ATTRS
        ):
            yield item.value


def _attribute_positions(node: ast.Assign | ast.AnnAssign) -> Iterator[ast.expr]:
    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
    if node.value is None:
        return
    if any(
        isinstance(target, ast.Attribute) and target.attr == "ipc_error_code"
        for target in targets
    ):
        yield node.value


def code_positions(tree: ast.Module) -> Iterator[ast.expr]:
    """Yield the expressions in positions 1 to 6 of the whole tree."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            yield from _call_positions(node)
        elif isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values, strict=True):
                if key is not None and _string(key) == "code":
                    yield value
        elif isinstance(node, ast.ClassDef):
            yield from _class_positions(node)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            yield from _attribute_positions(node)


def _literal_operands(node: ast.BoolOp) -> Iterator[str]:
    for operand in node.values:
        value = _string(operand)
        if value is not None:
            yield value


def code_literals(tree: ast.Module) -> set[str]:
    """Return the non-empty string literals in an error-code position."""
    found: set[str] = set()
    for expr in code_positions(tree):
        value = _string(expr)
        if value is not None:
            found.add(value)
        elif isinstance(expr, ast.BoolOp) and isinstance(expr.op, ast.Or):
            found.update(_literal_operands(expr))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.BoolOp)
            and isinstance(node.op, ast.Or)
            and any(reads_code(operand) for operand in node.values)
        ):
            found.update(_literal_operands(node))
    found.discard("")
    return found


def registered_codes(tree: ast.Module) -> set[str]:
    codes: set[str] = set()
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call) and _terminal_name(node.func) == "ErrorSpec"
        ):
            continue
        for keyword in node.keywords:
            value = _string(keyword.value) if keyword.arg == "code" else None
            if value:
                codes.add(value)
    return codes


def measure(root: Path) -> Measurement:
    trees = {
        path.relative_to(root).as_posix(): _parse_file(root, path)
        for path in target_files(root, SOURCE_GLOB)
    }
    if HOOK_PATH not in trees:
        raise CheckError(
            f"hook function {HOOK_CLASS}.{HOOK_FUNCTION} not found: "
            f"{HOOK_PATH} is missing"
        )
    if REGISTRY_PATH not in trees:
        raise CheckError(f"error registry not found: {REGISTRY_PATH}")
    registered = registered_codes(trees[REGISTRY_PATH])
    if not registered:
        raise CheckError(f"no ErrorSpec(code=...) found in {REGISTRY_PATH}")
    hook = hook_nodes(trees[HOOK_PATH])
    counts: dict[str, dict[str, int]] = {key: {} for key in COUNT_KEYS}
    cli_paths = {
        path.relative_to(root).as_posix() for path in target_files(root, CLI_GLOB)
    }
    codes: set[str] = set()
    for rel, tree in trees.items():
        codes |= code_literals(tree)
        if rel not in cli_paths:
            continue
        skip = hook if rel == HOOK_PATH else set()
        for key, value in zip(COUNT_KEYS, count_cli_file(tree, skip), strict=True):
            if value:
                counts[key][rel] = value
    return Measurement(
        counts[CLI_ERROR_CALLS],
        counts[CLI_EXITS],
        counts[IPC_ERROR_CODE_READS],
        frozenset(codes - registered),
    )


def baseline_json(measurement: Measurement) -> str:
    """Serialize a measurement in the baseline file format."""
    data: dict[str, object] = {
        key: dict(sorted(measurement.counts(key).items())) for key in COUNT_KEYS
    }
    data[UNREGISTERED_CODES] = sorted(measurement.unregistered_codes)
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _read_counts(data: dict[str, object], key: str) -> dict[str, int]:
    value = data[key]
    if not isinstance(value, dict):
        raise CheckError(f"{BASELINE_PATH}: {key!r} must be an object")
    counts: dict[str, int] = {}
    for path, count in value.items():
        if not _is_int(count) or count < 0:
            raise CheckError(
                f"{BASELINE_PATH}: {key}[{path!r}] must be a non-negative integer, "
                f"got {count!r}"
            )
        counts[path] = count
    return counts


def _read_codes(data: dict[str, object]) -> frozenset[str]:
    value = data[UNREGISTERED_CODES]
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise CheckError(
            f"{BASELINE_PATH}: {UNREGISTERED_CODES!r} must be a list of strings"
        )
    if value != sorted(set(value)):
        raise CheckError(
            f"{BASELINE_PATH}: {UNREGISTERED_CODES!r} must be sorted with no duplicates"
        )
    return frozenset(value)


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
    return Measurement(
        _read_counts(data, CLI_ERROR_CALLS),
        _read_counts(data, CLI_EXITS),
        _read_counts(data, IPC_ERROR_CODE_READS),
        _read_codes(data),
    )


def read_baseline(root: Path) -> Measurement:
    path = root / BASELINE_PATH
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise CheckError(f"baseline file not found: {BASELINE_PATH}") from exc
    except (OSError, UnicodeDecodeError) as exc:
        raise CheckError(f"cannot read {BASELINE_PATH}: {exc}") from exc
    return parse_baseline(text)


def _diff_counts(
    key: str,
    actual: dict[str, int],
    baseline: dict[str, int],
    lines: list[str],
    lower: list[str],
) -> bool:
    grew = False
    for path in sorted(set(actual) | set(baseline)):
        if path in actual and actual[path] == baseline.get(path):
            continue
        got = actual.get(path, 0)
        want = baseline.get(path, 0)
        lines.append(f"{key}\t{path}: actual {got}, baseline {want} ({got - want:+d})")
        if got > want:
            grew = True
        elif got == 0:
            lower.append(f"  - {key}에서 {path!r} 키를 지운다")
        else:
            lower.append(f"  - {key}[{path!r}]를 {got}로 낮춘다")
    return grew


def judge(actual: Measurement, baseline: Measurement) -> tuple[int, str]:
    lines: list[str] = []
    lower: list[str] = []
    grew = False
    for key in COUNT_KEYS:
        grew |= _diff_counts(
            key, actual.counts(key), baseline.counts(key), lines, lower
        )
    added = sorted(actual.unregistered_codes - baseline.unregistered_codes)
    removed = sorted(baseline.unregistered_codes - actual.unregistered_codes)
    lines.extend(f"{UNREGISTERED_CODES}\t+ {code}" for code in added)
    lines.extend(f"{UNREGISTERED_CODES}\t- {code}" for code in removed)
    lower.extend(f"  - {UNREGISTERED_CODES}에서 {code!r}를 지운다" for code in removed)
    if not lines:
        totals = ", ".join(
            f"{key} {sum(actual.counts(key).values())}" for key in COUNT_KEYS
        )
        return EXIT_OK, (
            f"entry ratchet ok: {totals}, "
            f"{UNREGISTERED_CODES} {len(actual.unregistered_codes)} "
            f"(baseline {BASELINE_PATH})"
        )
    parts = [f"entry ratchet failed against {BASELINE_PATH}:", *lines]
    if grew or added:
        parts.append(ALTERNATIVES)
    if grew:
        parts.append(MOVE_HINT)
    if lower:
        parts.append(f"줄어든 값은 {BASELINE_PATH}의 기준선을 실측으로 낮춘다:")
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
        description="Check CLI and IPC error exits against a baseline."
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
        message = f"entry ratchet error: {type(exc).__name__}: {exc}"
    stream = sys.stdout if code == EXIT_OK else sys.stderr
    print(message, file=stream)
    return code


if __name__ == "__main__":
    sys.exit(main())
