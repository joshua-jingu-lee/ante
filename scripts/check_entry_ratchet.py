#!/usr/bin/env python3
"""Fail when CLI and IPC error exits, IPC request reads or CLI output differ from
the baseline.

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

Request keys, over ``register_all_handlers`` in ``src/ante/ipc/registry.py``
and the calls ``<anything>.register(<str literal>, <name>, ...)`` inside it,
nested blocks included:

- ``ipc_handlers_without_model`` (set): the command names of those calls with
  no ``request_model=`` keyword or ``request_model=None``.
- ``ipc_args_reads`` (count per command): for each command in that set, the
  ``Load`` uses of the second parameter name of the handler, the top-level
  (async) function of the same module named by the second positional
  argument. Every use counts once: subscript, attribute, ``in``, argument.
  Commands with zero are left out.
- ``cli_direct_ipc_send`` (count per file in ``src/ante/cli/**/*.py``, no
  hook exclusion): calls whose callee ends in the name ``ipc_send``.
  Definitions are not calls.

Known limits of the request keys: registrations outside
``register_all_handlers`` or with a non-literal command name are not seen
(``CommandRegistry.register`` itself raises ``TypeError`` without
``request_model`` or with ``request_model=None``). The two IPC keys are at
their end state (``[]`` and ``{}``) and stay as a ban.
``ipc_args_reads`` counts the syntax of the parameter name only: a read
through an alias (``a = args``) counts as the one assignment, ``f(**args)``
counts as one, and a nested function whose parameter has the same name adds
its uses.

Known limits: codes that reach an exit outside these positions are not seen:
a code held in a variable or a module constant, a positional argument of a
module helper (``_exit_with_error(fmt, "CODE", ...)``), a conditional
expression, an f-string or a return value. Exits through helpers such as
``emit_cli_error`` are not counted either.
``self.ctx.exit(...)`` and ``click.get_current_context().exit(...)`` are not
counted as exits.
``setattr(e, "ipc_error_code", ...)`` and tuple assignments are not positions.

Output keys:

- ``raw_legacy_contracts`` (set): the paths of the ``CliCommandContract(...)``
  calls in ``src/ante/contracts/cli_registry.py`` whose
  ``output=OutputContract(...)`` has ``envelope="raw_legacy"``. A path is its
  segments joined by one space (``"account list"``). An
  ``OutputContract(...)`` with keyword arguments only and no ``envelope=`` is
  ``standard``.
- ``cli_direct_output`` (count per file in ``src/ante/cli/commands/**/*.py``):
  calls whose attribute name is ``output``, ``success`` or ``table``, on any
  receiver; calls of a bare name ``print``, ``echo`` or ``secho``;
  ``click.echo(...)`` and ``click.secho(...)``; ``.write(...)`` on ``stdout``
  of the ``sys`` module or a name it was imported as; and every attribute
  named ``is_json``.

Known limits of the output keys: calls through ``import click as ck`` and
``from sys import stdout`` are not counted.

Exit 0: all nine keys equal ``scripts/entry_ratchet_baseline.json``.
Exit 1: a count differs from the baseline in either direction, or a set
differs. Only the comparison produces this code.
Exit 2: every other failure: a missing or malformed baseline, a source file
that cannot be read or parsed, a missing hook function or registry, a missing
``register_all_handlers``, no registration in it, a second positional argument
that is not the name of a top-level function of the module, a handler with
fewer than two parameters, a missing CLI contract registry or no contract in
it, a contract whose ``path=`` is not a tuple of string literals, whose
``output=`` is not an ``OutputContract(...)`` call, has a positional or ``**``
argument, or whose ``envelope=`` is not a string literal, or any unexpected
exception.
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
IPC_REGISTRY_PATH = "src/ante/ipc/registry.py"
IPC_REGISTER_FUNCTION = "register_all_handlers"
CLI_CONTRACTS_PATH = "src/ante/contracts/cli_registry.py"
COMMANDS_GLOB = "src/ante/cli/commands/**/*.py"

CLI_ERROR_CALLS = "cli_error_calls"
CLI_EXITS = "cli_exits"
IPC_ERROR_CODE_READS = "ipc_error_code_reads"
UNREGISTERED_CODES = "unregistered_codes"
IPC_HANDLERS_WITHOUT_MODEL = "ipc_handlers_without_model"
IPC_ARGS_READS = "ipc_args_reads"
CLI_DIRECT_IPC_SEND = "cli_direct_ipc_send"
RAW_LEGACY_CONTRACTS = "raw_legacy_contracts"
CLI_DIRECT_OUTPUT = "cli_direct_output"
ERROR_COUNT_KEYS = (CLI_ERROR_CALLS, CLI_EXITS, IPC_ERROR_CODE_READS)
REQUEST_COUNT_KEYS = (IPC_ARGS_READS, CLI_DIRECT_IPC_SEND)
COUNT_KEYS = (*ERROR_COUNT_KEYS, *REQUEST_COUNT_KEYS, CLI_DIRECT_OUTPUT)
SET_KEYS = (UNREGISTERED_CODES, IPC_HANDLERS_WITHOUT_MODEL, RAW_LEGACY_CONTRACTS)
FILE_COUNT_KEYS = frozenset((*ERROR_COUNT_KEYS, CLI_DIRECT_IPC_SEND, CLI_DIRECT_OUTPUT))
BASELINE_ORDER = (
    *ERROR_COUNT_KEYS,
    UNREGISTERED_CODES,
    IPC_HANDLERS_WITHOUT_MODEL,
    *REQUEST_COUNT_KEYS,
    RAW_LEGACY_CONTRACTS,
    CLI_DIRECT_OUTPUT,
)
BASELINE_KEYS = frozenset(BASELINE_ORDER)

EXIT_OK = 0
EXIT_MISMATCH = 1
EXIT_ERROR = 2

CODE_ATTRS = frozenset({"code", "ipc_error_code"})
EXIT_NAMES = frozenset({"SystemExit", "Exit"})
LOGGER_PREFIX = "log"
CONTRACT_CALL = "CliCommandContract"
OUTPUT_CALL = "OutputContract"
RAW_LEGACY = "raw_legacy"
OUTPUT_ATTRS = frozenset({"output", "success", "table"})
PRINT_NAMES = frozenset({"print", "echo", "secho"})
CLICK_ATTRS = frozenset({"echo", "secho"})

ALTERNATIVES = (
    "새 에러 출구와 새 에러 코드 대신:\n"
    "  - 명령 안에서 끝내지 말고 타입 예외를 던진다\n"
    f"  - 그 예외와 코드를 에러 레지스트리({REGISTRY_PATH})에 등록한다"
)
REQUEST_ALTERNATIVES = (
    "요청 모델 없는 IPC 명령과 인자 사전 읽기 대신:\n"
    "  - 요청 모델(src/ante/ipc/requests.py의 IPCRequest 하위 클래스)을 만들어 "
    "register(..., request_model=...)로 등록한다\n"
    "  - 핸들러는 사전 대신 그 모델의 필드를 읽는다"
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
    ipc_handlers_without_model: frozenset[str]
    ipc_args_reads: dict[str, int]
    cli_direct_ipc_send: dict[str, int]
    raw_legacy_contracts: frozenset[str]
    cli_direct_output: dict[str, int]

    def counts(self, key: str) -> dict[str, int]:
        value: dict[str, int] = getattr(self, key)
        return value

    def members(self, key: str) -> frozenset[str]:
        value: frozenset[str] = getattr(self, key)
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


def count_ipc_send(tree: ast.Module) -> int:
    return sum(
        isinstance(node, ast.Call) and _terminal_name(node.func) == "ipc_send"
        for node in ast.walk(tree)
    )


def _top_functions(
    tree: ast.Module,
) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    return {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _is_model_missing(node: ast.Call) -> bool:
    for keyword in node.keywords:
        if keyword.arg == "request_model":
            value = keyword.value
            return isinstance(value, ast.Constant) and value.value is None
    return True


def _second_param_uses(func: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    params = [*func.args.posonlyargs, *func.args.args]
    if len(params) < 2:
        raise CheckError(
            f"handler {func.name} in {IPC_REGISTRY_PATH} has fewer than two parameters"
        )
    name = params[1].arg
    return sum(
        isinstance(node, ast.Name)
        and node.id == name
        and isinstance(node.ctx, ast.Load)
        for node in ast.walk(func)
    )


def measure_ipc(tree: ast.Module) -> tuple[frozenset[str], dict[str, int]]:
    """Return (commands without a request model, their handlers' args reads)."""
    top = _top_functions(tree)
    register_all = top.get(IPC_REGISTER_FUNCTION)
    if register_all is None:
        raise CheckError(f"{IPC_REGISTER_FUNCTION} not found in {IPC_REGISTRY_PATH}")
    found = 0
    without: set[str] = set()
    reads: dict[str, int] = {}
    for node in ast.walk(register_all):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "register"
            and node.args
        ):
            continue
        command = _string(node.args[0])
        if command is None:
            continue
        found += 1
        handler = node.args[1] if len(node.args) >= 2 else None
        if not (isinstance(handler, ast.Name) and handler.id in top):
            raise CheckError(
                f"register({command!r}) in {IPC_REGISTRY_PATH}: the second "
                "positional argument is not the name of a top-level function"
            )
        if not _is_model_missing(node):
            continue
        without.add(command)
        uses = _second_param_uses(top[handler.id])
        if uses:
            reads[command] = uses
    if not found:
        raise CheckError(
            f"no register(<command>, <handler>, ...) call in "
            f"{IPC_REGISTER_FUNCTION} of {IPC_REGISTRY_PATH}"
        )
    return frozenset(without), reads


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


def _keyword(node: ast.Call, name: str) -> ast.expr | None:
    for keyword in node.keywords:
        if keyword.arg == name:
            return keyword.value
    return None


def _contract_path(node: ast.Call) -> str:
    value = _keyword(node, "path")
    segments = (
        [_string(element) for element in value.elts]
        if isinstance(value, ast.Tuple)
        else [None]
    )
    if not segments or None in segments:
        raise CheckError(
            f"{CLI_CONTRACTS_PATH}:{node.lineno}: {CONTRACT_CALL}: "
            "path is not a tuple of string literals"
        )
    return " ".join(str(segment) for segment in segments)


def _contract_envelope(node: ast.Call, path: str) -> str:
    where = f"{CLI_CONTRACTS_PATH}:{node.lineno}: {CONTRACT_CALL}({path!r})"
    output = _keyword(node, "output")
    if not (
        isinstance(output, ast.Call) and _terminal_name(output.func) == OUTPUT_CALL
    ):
        raise CheckError(f"{where}: output is not an {OUTPUT_CALL}(...) call")
    if output.args or any(keyword.arg is None for keyword in output.keywords):
        raise CheckError(f"{where}: {OUTPUT_CALL}(...) has a positional or ** argument")
    value = _keyword(output, "envelope")
    if value is None:
        return "standard"
    envelope = _string(value)
    if envelope is None:
        raise CheckError(f"{where}: envelope is not a string literal")
    return envelope


def raw_legacy_paths(tree: ast.Module) -> frozenset[str]:
    """Return the paths of the contracts whose envelope is ``raw_legacy``."""
    found = 0
    paths: set[str] = set()
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call) and _terminal_name(node.func) == CONTRACT_CALL
        ):
            continue
        found += 1
        path = _contract_path(node)
        if _contract_envelope(node, path) == RAW_LEGACY:
            paths.add(path)
    if not found:
        raise CheckError(f"no {CONTRACT_CALL}(...) found in {CLI_CONTRACTS_PATH}")
    return frozenset(paths)


def is_direct_output(node: ast.AST, sys_names: set[str]) -> bool:
    if isinstance(node, ast.Attribute):
        return node.attr == "is_json"
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Name):
        return func.id in PRINT_NAMES
    if not isinstance(func, ast.Attribute):
        return False
    if func.attr in OUTPUT_ATTRS:
        return True
    receiver = func.value
    if func.attr in CLICK_ATTRS:
        return isinstance(receiver, ast.Name) and receiver.id == "click"
    return (
        func.attr == "write"
        and isinstance(receiver, ast.Attribute)
        and receiver.attr == "stdout"
        and isinstance(receiver.value, ast.Name)
        and receiver.value.id in sys_names
    )


def count_direct_output(tree: ast.Module) -> int:
    sys_names = sys_aliases(tree)
    return sum(is_direct_output(node, sys_names) for node in ast.walk(tree))


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
    if IPC_REGISTRY_PATH not in trees:
        raise CheckError(
            f"{IPC_REGISTER_FUNCTION} not found: {IPC_REGISTRY_PATH} is missing"
        )
    if CLI_CONTRACTS_PATH not in trees:
        raise CheckError(f"CLI contract registry not found: {CLI_CONTRACTS_PATH}")
    registered = registered_codes(trees[REGISTRY_PATH])
    if not registered:
        raise CheckError(f"no ErrorSpec(code=...) found in {REGISTRY_PATH}")
    hook = hook_nodes(trees[HOOK_PATH])
    without_model, args_reads = measure_ipc(trees[IPC_REGISTRY_PATH])
    raw_legacy = raw_legacy_paths(trees[CLI_CONTRACTS_PATH])
    counts: dict[str, dict[str, int]] = {key: {} for key in COUNT_KEYS}
    cli_paths = {
        path.relative_to(root).as_posix() for path in target_files(root, CLI_GLOB)
    }
    command_paths = {
        path.relative_to(root).as_posix() for path in target_files(root, COMMANDS_GLOB)
    }
    codes: set[str] = set()
    for rel, tree in trees.items():
        codes |= code_literals(tree)
        if rel in command_paths:
            direct = count_direct_output(tree)
            if direct:
                counts[CLI_DIRECT_OUTPUT][rel] = direct
        if rel not in cli_paths:
            continue
        skip = hook if rel == HOOK_PATH else set()
        for key, value in zip(
            ERROR_COUNT_KEYS, count_cli_file(tree, skip), strict=True
        ):
            if value:
                counts[key][rel] = value
        sends = count_ipc_send(tree)
        if sends:
            counts[CLI_DIRECT_IPC_SEND][rel] = sends
    return Measurement(
        counts[CLI_ERROR_CALLS],
        counts[CLI_EXITS],
        counts[IPC_ERROR_CODE_READS],
        frozenset(codes - registered),
        without_model,
        args_reads,
        counts[CLI_DIRECT_IPC_SEND],
        raw_legacy,
        counts[CLI_DIRECT_OUTPUT],
    )


def baseline_json(measurement: Measurement) -> str:
    """Serialize a measurement in the baseline file format."""
    data: dict[str, object] = {}
    for key in BASELINE_ORDER:
        if key in SET_KEYS:
            data[key] = sorted(measurement.members(key))
        else:
            data[key] = dict(sorted(measurement.counts(key).items()))
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


def _read_set(data: dict[str, object], key: str) -> frozenset[str]:
    value = data[key]
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise CheckError(f"{BASELINE_PATH}: {key!r} must be a list of strings")
    if value != sorted(set(value)):
        raise CheckError(f"{BASELINE_PATH}: {key!r} must be sorted with no duplicates")
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
        _read_set(data, UNREGISTERED_CODES),
        _read_set(data, IPC_HANDLERS_WITHOUT_MODEL),
        _read_counts(data, IPC_ARGS_READS),
        _read_counts(data, CLI_DIRECT_IPC_SEND),
        _read_set(data, RAW_LEGACY_CONTRACTS),
        _read_counts(data, CLI_DIRECT_OUTPUT),
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


def _diff_set(
    key: str,
    actual: frozenset[str],
    baseline: frozenset[str],
    lines: list[str],
    lower: list[str],
) -> bool:
    added = sorted(actual - baseline)
    removed = sorted(baseline - actual)
    lines.extend(f"{key}\t+ {member}" for member in added)
    lines.extend(f"{key}\t- {member}" for member in removed)
    lower.extend(f"  - {key}에서 {member!r}를 지운다" for member in removed)
    return bool(added)


def _diff_key(
    key: str,
    actual: Measurement,
    baseline: Measurement,
    lines: list[str],
    lower: list[str],
) -> bool:
    if key in SET_KEYS:
        return _diff_set(key, actual.members(key), baseline.members(key), lines, lower)
    return _diff_counts(key, actual.counts(key), baseline.counts(key), lines, lower)


def _totals(actual: Measurement) -> str:
    parts = []
    for key in BASELINE_ORDER:
        if key in SET_KEYS:
            parts.append(f"{key} {len(actual.members(key))}")
        else:
            parts.append(f"{key} {sum(actual.counts(key).values())}")
    return ", ".join(parts)


def judge(actual: Measurement, baseline: Measurement) -> tuple[int, str]:
    lines: list[str] = []
    lower: list[str] = []
    grew: set[str] = set()
    for key in BASELINE_ORDER:
        if _diff_key(key, actual, baseline, lines, lower):
            grew.add(key)
    if not lines:
        return (
            EXIT_OK,
            f"entry ratchet ok: {_totals(actual)} (baseline {BASELINE_PATH})",
        )
    parts = [f"entry ratchet failed against {BASELINE_PATH}:", *lines]
    if grew & {*ERROR_COUNT_KEYS, UNREGISTERED_CODES}:
        parts.append(ALTERNATIVES)
    if grew & {IPC_HANDLERS_WITHOUT_MODEL, IPC_ARGS_READS}:
        parts.append(REQUEST_ALTERNATIVES)
    if grew & FILE_COUNT_KEYS:
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
        description=(
            "Check CLI and IPC error exits, IPC request reads and CLI output "
            "against a baseline."
        )
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
