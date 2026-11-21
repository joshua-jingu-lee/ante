#!/usr/bin/env python3
"""Build the before/after table of #2683 for IPC commands moved to request models.

Run with ``src`` on ``PYTHONPATH`` (the script also puts ``<root>/src`` first).

``build --command C [--command C ...] [--requests FILE] [--cli-records FILE]``

Run on the base tree, once per bundle. For each command C it writes the
request set into FILE (other commands already in FILE are kept):

- ``cli``: every (command, args) the CLI contract test records for C
  (``record_cli_requests`` in ``tests/unit/cli/test_cli_ipc_request_contract.py``,
  or the JSON list given with ``--cli-records``).
- reject candidates over the keys the base handler reads. A key is the string
  literal of ``args[<literal>]`` or ``args.get(<literal>, ...)`` where ``args``
  is the handler's second parameter. Any other use of that parameter is an
  input error. A command with an ``account_id_policy`` other than ``none``
  also reads ``account_id``. From the first ``cli`` args: ``missing`` (keys
  read with ``[]`` only), ``value`` (the key set to ``"5"``, ``7``, ``true``,
  ``null``), ``extra`` (one unknown key), ``array`` (the args as a list),
  ``account`` (``account_id`` set to ``"default"``, ``""``, ``"bad_id!"``),
  ``nan`` (``NaN`` at a key whose ``cli`` value is a float).

``record [--requests FILE] --out RECORD``

Dispatch every request through the real ``register_all_handlers`` and
``IPCServer._dispatch``. The services are one deterministic double: an
attribute is a double named by its path, a call is recorded as
``[path, args, kwargs]`` and returns the double ``<path>()``, awaiting returns
``<path>!``. A row is ``status``, ``code``, ``message``, ``result`` and
``calls``; ``result`` and ``calls`` are ``json.dumps(sort_keys=True,
default=repr)`` after values of a type other than ``str``, ``int``, ``float``,
``bool``, ``None``, ``list``, ``tuple`` and ``dict`` are replaced by their
``repr``. The record also keeps the three request keys of
``scripts/check_entry_ratchet.py`` for the tree it ran on.

``compare [--requests FILE] --before A --before B --after C [--allow-code CODE]``

Rows that differ between A and B are ``비결정`` and leave the comparison. For
each other request:

- ``같음``: every column is equal.
- ``다름`` when a row is missing in a record, for a ``cli`` row that is not
  ``같음``, and for a ``value`` row whose value has the JSON type of the
  ``cli`` value and that is not ``같음``, unless the after model narrows that
  field (a ``Literal`` or an ``AfterValidator`` type).
- ``거부로 바뀜``: calls before, ``VALIDATION_ERROR`` and no calls after.
- ``코드 바뀜``: no calls either side, the before code is in the allowed set
  (``EXECUTION_ERROR`` and each ``--allow-code``), ``VALIDATION_ERROR`` after.
- ``메시지 바뀜``: ``VALIDATION_ERROR`` and no calls either side, only the
  message differs, and the row is an ``account`` row or its field has an
  ``AfterValidator`` type.
- ``다름``: any other difference, and any row that is not ``같음`` whose after
  message or result contains a string value of its request (two characters
  or more).

Exit 0: no ``다름`` row.
Exit 1: a ``다름`` row.
Exit 2: unreadable input, a record row not in the request set, an
unsupported handler read, or any other failure.
"""

from __future__ import annotations

import argparse
import ast
import asyncio
import importlib.util
import json
import logging
import os
import sys
import typing
from collections import Counter
from collections.abc import Generator, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

EXIT_OK = 0
EXIT_DIFFERENT = 1
EXIT_ERROR = 2

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REQUESTS = Path("scripts/ipc_request_set.json")
IPC_REGISTRY_PATH = "src/ante/ipc/registry.py"
CLI_CONTRACT_TEST = "tests/unit/cli/test_cli_ipc_request_contract.py"
VALIDATION_ERROR = "VALIDATION_ERROR"
DEFAULT_ALLOWED = ("EXECUTION_ERROR",)
EXTRA_KEY = "zz_extra"
EXTRA_VALUE = "zz-extra-value"
ARRAY_ITEM = "zz-array-item"
VALUES: tuple[tuple[str, Any], ...] = (
    ("str5", "5"),
    ("int7", 7),
    ("true", True),
    ("null", None),
)
BAD_ACCOUNTS = (("default", "default"), ("empty", ""), ("bad", "bad_id!"))
CLASSES = ("같음", "거부로 바뀜", "코드 바뀜", "메시지 바뀜", "다름")
RATCHET_KEYS = (
    "ipc_handlers_without_model",
    "ipc_args_reads",
    "cli_direct_ipc_send",
)
PLAIN = (str, int, float, bool, type(None))


class InputError(Exception):
    pass


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise InputError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise InputError(f"cannot read {path}: {exc}") from None


def _write_json(path: Path, data: Any) -> None:
    text = json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True)
    path.write_text(text + "\n", encoding="utf-8")


def _json_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    return "object"


@dataclass(frozen=True)
class Registration:
    handler: str
    policy: str


def _registrations(tree: ast.Module) -> dict[str, Registration]:
    found: dict[str, Registration] = {}
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "register"
            and len(node.args) >= 2
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
            and isinstance(node.args[1], ast.Name)
        ):
            continue
        policy = "none"
        for keyword in node.keywords:
            if keyword.arg == "account_id_policy" and isinstance(
                keyword.value, ast.Constant
            ):
                policy = str(keyword.value.value)
        found[node.args[0].value] = Registration(node.args[1].id, policy)
    return found


def _literal(node: ast.expr) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def handler_reads(
    func: ast.FunctionDef | ast.AsyncFunctionDef,
) -> dict[str, bool]:
    params = [*func.args.posonlyargs, *func.args.args]
    if len(params) < 2:
        raise InputError(f"{func.name}: fewer than two parameters")
    name = params[1].arg
    parents = {
        child: parent
        for parent in ast.walk(func)
        for child in ast.iter_child_nodes(parent)
    }
    reads: dict[str, bool] = {}
    for node in ast.walk(func):
        if not (
            isinstance(node, ast.Name)
            and node.id == name
            and isinstance(node.ctx, ast.Load)
        ):
            continue
        parent = parents[node]
        key: str | None = None
        required = False
        if isinstance(parent, ast.Subscript) and parent.value is node:
            key = _literal(parent.slice)
            required = True
        elif isinstance(parent, ast.Attribute) and parent.attr == "get":
            call = parents.get(parent)
            if isinstance(call, ast.Call) and call.func is parent and call.args:
                key = _literal(call.args[0])
        if key is None:
            raise InputError(
                f"{func.name}: unsupported use of {name}: {ast.unparse(parent)}"
            )
        reads[key] = reads.get(key, False) or required
    return reads


def _command_keys(root: Path, command: str) -> dict[str, bool]:
    tree = ast.parse((root / IPC_REGISTRY_PATH).read_text(encoding="utf-8"))
    top = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    registration = _registrations(tree).get(command)
    if registration is None or registration.handler not in top:
        raise InputError(f"{command}: no register(...) call with a handler")
    keys = handler_reads(top[registration.handler])
    if registration.policy != "none" and "account_id" not in keys:
        keys["account_id"] = registration.policy == "required"
    return keys


def _cli_records(root: Path, path: Path | None) -> list[dict[str, Any]]:
    if path is not None:
        data = _read_json(path)
        if not isinstance(data, list):
            raise InputError(f"{path}: expected a JSON list")
        return data
    if not os.environ.get("ANTE_DB_ENCRYPTION_KEY"):
        from cryptography.fernet import Fernet

        os.environ["ANTE_DB_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
    module = _load_module("_ipc_cli_contract", root / CLI_CONTRACT_TEST)
    return [
        {"command": s.command, "args": s.args, "row": s.row.row_id}
        for s in module.record_cli_requests()
    ]


def build_requests(
    command: str, keys: dict[str, bool], cli: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    mine = [record for record in cli if record["command"] == command]
    if not mine:
        raise InputError(f"{command}: the CLI records do not send it")
    base = mine[0]["args"]
    if not isinstance(base, dict):
        raise InputError(f"{command}: the first CLI args are not an object")
    out: list[dict[str, Any]] = [
        {"name": f"{command}:cli:{i}", "kind": "cli", "args": r["args"]}
        for i, r in enumerate(mine)
    ]
    for key in sorted(keys):
        if keys[key] and key in base:
            rest = {k: v for k, v in base.items() if k != key}
            out.append(
                {
                    "name": f"{command}:missing:{key}",
                    "kind": "missing",
                    "key": key,
                    "args": rest,
                }
            )
        for label, value in VALUES:
            same = key in base and _json_type(value) == _json_type(base[key])
            out.append(
                {
                    "name": f"{command}:value:{key}:{label}",
                    "kind": "value",
                    "key": key,
                    "same_type": same,
                    "args": {**base, key: value},
                }
            )
    out.append(
        {
            "name": f"{command}:extra",
            "kind": "extra",
            "args": {**base, EXTRA_KEY: EXTRA_VALUE},
        }
    )
    out.append({"name": f"{command}:array", "kind": "array", "args": [ARRAY_ITEM]})
    if "account_id" in keys:
        for label, value in BAD_ACCOUNTS:
            out.append(
                {
                    "name": f"{command}:account:{label}",
                    "kind": "account",
                    "key": "account_id",
                    "args": {**base, "account_id": value},
                }
            )
    floats = sorted(
        {
            k
            for r in mine
            if isinstance(r["args"], dict)
            for k, v in r["args"].items()
            if isinstance(v, float)
        }
    )
    for key in floats:
        out.append(
            {
                "name": f"{command}:nan:{key}",
                "kind": "nan",
                "key": key,
                "args": {**base, key: float("nan")},
            }
        )
    return out


def _requests(path: Path) -> dict[str, dict[str, Any]]:
    data = _read_json(path)
    commands = data.get("commands") if isinstance(data, dict) else None
    if not isinstance(commands, dict) or not commands:
        raise InputError(f"{path}: no commands")
    named: dict[str, dict[str, Any]] = {}
    for command, rows in commands.items():
        for row in rows:
            if row["name"] in named:
                raise InputError(f"{path}: duplicate request {row['name']}")
            named[row["name"]] = {**row, "command": command}
    return named


def cmd_build(args: argparse.Namespace) -> int:
    root: Path = args.root
    path = root / args.requests
    data: dict[str, Any] = {"commands": {}}
    if path.exists():
        data = _read_json(path)
    cli = _cli_records(root, args.cli_records)
    for command in args.command:
        data["commands"][command] = build_requests(
            command, _command_keys(root, command), cli
        )
    _write_json(path, data)
    total = sum(len(rows) for rows in data["commands"].values())
    print(f"requests: {total} in {len(data['commands'])} commands")
    return EXIT_OK


class _Double:
    def __init__(self, path: str, calls: list[Any]) -> None:
        self._path = path
        self._calls = calls

    def __getattr__(self, name: str) -> _Double:
        if name.startswith("__"):
            raise AttributeError(name)
        return _Double(f"{self._path}.{name}", self._calls)

    def __call__(self, *args: Any, **kwargs: Any) -> _Double:
        self._calls.append([self._path, list(args), kwargs])
        return _Double(f"{self._path}()", self._calls)

    def __await__(self) -> Generator[Any, None, _Double]:
        yield from ()
        return _Double(f"{self._path}!", self._calls)

    def __iter__(self) -> Iterator[Any]:
        return iter(())

    def __repr__(self) -> str:
        return self._path


def _plain(value: Any) -> Any:
    if type(value) in PLAIN:
        return value
    if type(value) in (list, tuple):
        return [_plain(v) for v in value]
    if type(value) is dict:
        return {str(k): _plain(v) for k, v in value.items()}
    return repr(value)


def _dump(value: Any) -> str:
    return json.dumps(_plain(value), sort_keys=True, default=repr, ensure_ascii=False)


def _ratchet(root: Path) -> dict[str, int]:
    checker = _load_module("_entry_ratchet", root / "scripts/check_entry_ratchet.py")
    measured = checker.measure(root)
    return {
        "ipc_handlers_without_model": len(measured.ipc_handlers_without_model),
        "ipc_args_reads": sum(measured.ipc_args_reads.values()),
        "cli_direct_ipc_send": sum(measured.cli_direct_ipc_send.values()),
    }


async def _dispatch_all(requests: dict[str, dict[str, Any]]) -> dict[str, Any]:
    from ante.ipc.registry import CommandRegistry, register_all_handlers
    from ante.ipc.server import IPCServer, IPCServerState

    registry = CommandRegistry()
    register_all_handlers(registry)
    rows: dict[str, Any] = {}
    for name in sorted(requests):
        request = requests[name]
        calls: list[Any] = []
        services: Any = _Double("svc", calls)
        server = IPCServer("/unused.sock", services, registry)
        server._state = IPCServerState.RUNNING
        response = await server._dispatch(
            {
                "id": "req-1",
                "command": request["command"],
                "args": request["args"],
                "actor": "ipc-diff",
            }
        )
        error = response.get("error") or {}
        rows[name] = {
            "status": response.get("status"),
            "code": error.get("code"),
            "message": error.get("message"),
            "result": _dump(response.get("result")),
            "calls": _dump(calls),
        }
    return rows


def cmd_record(args: argparse.Namespace) -> int:
    root: Path = args.root
    requests = _requests(root / args.requests)
    logging.disable(logging.CRITICAL)
    rows = asyncio.run(_dispatch_all(requests))
    _write_json(args.out, {"rows": rows, "ratchet": _ratchet(root)})
    print(f"recorded: {len(rows)} rows")
    return EXIT_OK


def _field_info(command: str, key: str | None) -> Any:
    if key is None:
        return None
    from ante.ipc.registry import CommandRegistry, register_all_handlers

    registry = CommandRegistry()
    register_all_handlers(registry)
    spec = registry.get(command)
    model = spec.request_model if spec is not None else None
    if model is None:
        return None
    return model.model_fields.get(key)


def _validated(info: Any) -> bool:
    from pydantic.functional_validators import AfterValidator

    return info is not None and any(
        isinstance(item, AfterValidator) for item in info.metadata
    )


def _narrowed(info: Any) -> bool:
    if info is None:
        return False
    return typing.get_origin(info.annotation) is typing.Literal or _validated(info)


def _strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)


def classify(
    request: dict[str, Any],
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    allowed: frozenset[str],
) -> tuple[str, str]:
    if before is None or after is None:
        return "다름", "missing in a record"
    if before == after:
        return "같음", ""
    kind = request["kind"]
    if kind == "cli":
        return "다름", "a CLI request changed"
    info = _field_info(request["command"], request.get("key"))
    if kind == "value" and request.get("same_type") and not _narrowed(info):
        return "다름", "a value of the CLI JSON type changed"
    for text in _strings(request["args"]):
        if len(text) >= 2 and (
            text in (after["message"] or "") or text in after["result"]
        ):
            return "다름", f"the after response reflects {text!r}"
    rejected = after["status"] == "error" and after["code"] == VALIDATION_ERROR
    no_calls = before["calls"] == "[]" and after["calls"] == "[]"
    if rejected and before["calls"] != "[]" and after["calls"] == "[]":
        return "거부로 바뀜", ""
    if rejected and no_calls and before["code"] in allowed:
        return "코드 바뀜", ""
    only_message = {k for k in before if before[k] != after[k]} == {"message"}
    if (
        rejected
        and no_calls
        and only_message
        and before["code"] == VALIDATION_ERROR
        and (kind == "account" or _validated(info))
    ):
        return "메시지 바뀜", ""
    return "다름", "another difference"


def _rows(path: Path, names: set[str]) -> tuple[dict[str, Any], dict[str, int]]:
    data = _read_json(path)
    rows = data.get("rows") if isinstance(data, dict) else None
    if not isinstance(rows, dict) or not rows:
        raise InputError(f"{path}: no rows")
    unknown = sorted(set(rows) - names)
    if unknown:
        raise InputError(f"{path}: rows not in the request set: {', '.join(unknown)}")
    return rows, data.get("ratchet") or {}


def _outcome(row: dict[str, Any]) -> str:
    head = row["code"] if row["status"] == "error" else row["status"]
    return f"{head} {row['message']}" if row["message"] else str(head)


def cmd_compare(args: argparse.Namespace) -> int:
    root: Path = args.root
    requests = _requests(root / args.requests)
    names = set(requests)
    if len(args.before) != 2:
        raise InputError("compare needs --before twice")
    (b1, ratchet_before), (b2, _) = (_rows(p, names) for p in args.before)
    after, ratchet_after = _rows(args.after, names)
    allowed = frozenset((*DEFAULT_ALLOWED, *args.allow_code))
    unstable = sorted(n for n in names if n in b1 and n in b2 and b1[n] != b2[n])
    counts: Counter[str] = Counter()
    code_changes: Counter[str] = Counter()
    changed: list[str] = []
    different: list[str] = []
    for name in sorted(names):
        request = requests[name]
        if name in unstable and request["kind"] != "cli":
            continue
        if name in unstable:
            cls, reason = "다름", "a CLI request is not deterministic"
        else:
            cls, reason = classify(request, b1.get(name), after.get(name), allowed)
        counts[cls] += 1
        if cls == "다름":
            different.append(f"  {name}: {reason}")
            continue
        if cls == "같음":
            continue
        before_row, after_row = b1[name], after[name]
        if cls == "코드 바뀜":
            code_changes[f"{before_row['code']} -> {after_row['code']}"] += 1
        changed.append(
            f"  {cls} {name}: {_outcome(before_row)} -> {_outcome(after_row)}"
        )
    lines = [f"rows: {len(names)}"]
    lines += [f"{cls} {counts[cls]}" for cls in CLASSES]
    lines.append(f"비결정 {len(unstable)}")
    lines += [f"  {name}" for name in unstable]
    lines.append("code changes:")
    lines += [f"  {key} {n}" for key, n in sorted(code_changes.items())]
    lines.append("changed rows:")
    lines += changed
    lines.append("different rows:")
    lines += different
    lines.append(
        "ratchet: "
        + ", ".join(
            f"{key} {ratchet_before.get(key)} -> {ratchet_after.get(key)}"
            for key in RATCHET_KEYS
        )
    )
    print("\n".join(lines))
    return EXIT_DIFFERENT if counts["다름"] else EXIT_OK


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=ROOT)
    sub = parser.add_subparsers(dest="action", required=True)
    build = sub.add_parser("build")
    build.add_argument("--command", action="append", required=True)
    build.add_argument("--requests", type=Path, default=DEFAULT_REQUESTS)
    build.add_argument("--cli-records", type=Path, default=None)
    record = sub.add_parser("record")
    record.add_argument("--requests", type=Path, default=DEFAULT_REQUESTS)
    record.add_argument("--out", type=Path, required=True)
    compare = sub.add_parser("compare")
    compare.add_argument("--requests", type=Path, default=DEFAULT_REQUESTS)
    compare.add_argument("--before", type=Path, action="append", required=True)
    compare.add_argument("--after", type=Path, required=True)
    compare.add_argument("--allow-code", action="append", default=[])
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    sys.path.insert(0, str(args.root / "src"))
    actions = {"build": cmd_build, "record": cmd_record, "compare": cmd_compare}
    try:
        return actions[args.action](args)
    except Exception as exc:
        print(f"ipc request diff error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
