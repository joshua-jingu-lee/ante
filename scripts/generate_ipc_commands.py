#!/usr/bin/env python3
"""CommandRegistry 기반 IPC 명령 문서 자동 생성/check.

새 ``CommandRegistry``에 ``register_all_handlers``를 부르고(서버를 띄우지 않는다)
등록된 ``CommandSpec``과 요청 모델, CLI 계약의 ``ipc_command``에서
docs/architecture/generated/ipc-commands.md를 생성한다.

SSOT: ``src/ante/ipc/registry.py``·``src/ante/ipc/requests.py``·
``src/ante/contracts/cli_registry.py`` -> docs/architecture/generated/ipc-commands.md

사용법:
    python scripts/generate_ipc_commands.py
    python scripts/generate_ipc_commands.py --output <path>
    python scripts/generate_ipc_commands.py --stdout
    python scripts/generate_ipc_commands.py --check

    <path> 기본값: docs/architecture/generated/ipc-commands.md
"""

from __future__ import annotations

import argparse
import difflib
import importlib.util
import json
import sys
import types
import typing
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from pydantic import AfterValidator, SecretStr
from pydantic.fields import FieldInfo

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = (
    PROJECT_ROOT / "docs" / "architecture" / "generated" / "ipc-commands.md"
)
GENERATE_COMMAND = (
    "PYTHONPATH=$PWD/src .venv/bin/python scripts/generate_ipc_commands.py"
)
SCALARS: dict[Any, str] = {str: "str", int: "int", float: "float", bool: "bool"}


class UnsupportedFieldError(TypeError):
    """생성기가 표기 규칙을 모르는 필드."""


def _load_import_guard():
    guard_path = PROJECT_ROOT / "scripts" / "check_import_path.py"
    spec = importlib.util.spec_from_file_location("check_import_path", guard_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load import guard: {guard_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _assert_current_worktree_import_path() -> None:
    guard = _load_import_guard()
    try:
        guard.check_import_path(PROJECT_ROOT)
    except guard.ImportPathCheckError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc


# ── 타입 표기 ────────────────────────────────────────────────────────────


def _ipc_request() -> type:
    from ante.ipc.requests import IPCRequest

    return IPCRequest


def _validator_aliases() -> dict[Any, str]:
    """``Annotated[str, AfterValidator(f)]`` 별칭의 검증 함수 -> 별칭 이름."""
    from ante.ipc import requests

    aliases: dict[Any, str] = {}
    for name in ("AccountId", "IsoDate"):
        for marker in typing.get_args(getattr(requests, name))[1:]:
            aliases[marker.func] = name
    return aliases


def _validated(base: Any, metadata: Sequence[Any]) -> str:
    aliases = _validator_aliases()
    if base is not str or len(metadata) != 1:
        raise UnsupportedFieldError(f"unsupported metadata: {base!r} {metadata!r}")
    marker = metadata[0]
    if not isinstance(marker, AfterValidator) or marker.func not in aliases:
        raise UnsupportedFieldError(f"unsupported validator: {marker!r}")
    return aliases[marker.func]


def type_name(annotation: Any, metadata: Sequence[Any] = ()) -> str:
    """필드 타입의 표기. 규칙 밖의 타입은 ``UnsupportedFieldError``."""
    if metadata:
        return _validated(annotation, metadata)
    origin = typing.get_origin(annotation)
    args = typing.get_args(annotation)
    if origin is typing.Annotated:
        return _validated(args[0], args[1:])
    if origin in (typing.Union, types.UnionType):
        rest = [arg for arg in args if arg is not type(None)]
        if len(rest) != 1 or len(args) != 2:
            raise UnsupportedFieldError(f"unsupported union: {annotation!r}")
        return f"{type_name(rest[0])} | None"
    if origin is typing.Literal:
        if not all(isinstance(arg, str) for arg in args):
            raise UnsupportedFieldError(f"unsupported literal: {annotation!r}")
        return "Literal[" + ", ".join(json.dumps(arg) for arg in args) + "]"
    if origin is list and len(args) == 1:
        return f"list[{type_name(args[0])}]"
    if origin is dict and len(args) == 2:
        return f"dict[{type_name(args[0])}, {type_name(args[1])}]"
    if annotation is Any:
        return "Any"
    if annotation in SCALARS:
        return SCALARS[annotation]
    if annotation is SecretStr:
        return "SecretStr"
    if isinstance(annotation, type) and issubclass(annotation, _ipc_request()):
        return annotation.__name__
    raise UnsupportedFieldError(f"unsupported type: {annotation!r}")


def _contains(annotation: Any, target: Any) -> bool:
    if annotation is target:
        return True
    return any(_contains(arg, target) for arg in typing.get_args(annotation))


def _default(info: FieldInfo) -> str:
    factory = info.default_factory
    if factory is not None:
        if not isinstance(factory, type) or not issubclass(factory, _ipc_request()):
            raise UnsupportedFieldError(f"unsupported default_factory: {factory!r}")
        return f"{factory.__name__}()"
    try:
        return json.dumps(info.default, ensure_ascii=False)
    except TypeError as exc:
        raise UnsupportedFieldError(f"unsupported default: {info.default!r}") from exc


def _escape(text: str) -> str:
    return text.replace("|", "\\|")


def field_cell(name: str, info: FieldInfo) -> str:
    """요청 필드 하나의 표기. 비밀값 필드는 기본값을 싣지 않는다."""
    declared = f"{name}: {type_name(info.annotation, info.metadata)}"
    if info.is_required():
        return _escape(f"`{declared}` (필수)")
    if _contains(info.annotation, SecretStr):
        return _escape(f"`{declared}` (선택)")
    return _escape(f"`{declared} = {_default(info)}`")


def _fields_cell(model: type) -> str:
    cells = [field_cell(name, info) for name, info in model.model_fields.items()]
    return "<br>".join(cells) if cells else "—"


def _nested_in(annotation: Any) -> list[type]:
    found: list[type] = []
    if isinstance(annotation, type) and issubclass(annotation, _ipc_request()):
        found.append(annotation)
    for arg in typing.get_args(annotation):
        found.extend(_nested_in(arg))
    return found


def nested_models(models: Iterable[type]) -> list[type]:
    """요청 모델의 필드 타입으로 쓰인 ``IPCRequest`` 하위 모델(중복 없이)."""
    found: list[type] = []
    pending = list(models)
    seen: set[type] = set()
    while pending:
        model = pending.pop(0)
        if model in seen:
            continue
        seen.add(model)
        for info in model.model_fields.values():
            for inner in _nested_in(info.annotation):
                if inner not in found:
                    found.append(inner)
                pending.append(inner)
    return found


# ── Markdown 생성 ────────────────────────────────────────────────────────


def _code_list(values: Iterable[str]) -> str:
    items = [f"`{value}`" for value in sorted(values)]
    return ", ".join(items) if items else "—"


def render(specs: Iterable[Any], contracts: Iterable[Any]) -> str:
    """등록 명령과 CLI 계약에서 문서 전체를 만든다(입력 순서에 의존하지 않는다)."""
    ordered = sorted(specs, key=lambda spec: spec.name)
    paths: dict[str, list[str]] = {}
    for contract in contracts:
        if contract.ipc_command is not None:
            path = "ante " + " ".join(contract.path)
            paths.setdefault(contract.ipc_command, []).append(path)
    mutating = sum(1 for spec in ordered if spec.is_mutating)
    lines = [
        "# Ante IPC Commands",
        "",
        "`CommandRegistry`에 등록된 IPC 명령과 그 요청 모델을 정리한 문서입니다. "
        "`register_all_handlers`의 등록 값, `src/ante/ipc/requests.py`의 요청 모델, "
        "CLI 계약의 `ipc_command`에서 생성합니다.",
        "",
        "> 이 문서는 `scripts/generate_ipc_commands.py`로 자동 생성됩니다. "
        "직접 편집하지 말고 등록·요청 모델·CLI 계약을 수정한 뒤 재생성하세요.",
        "",
        f"> 생성 명령: `{GENERATE_COMMAND}`",
        f"> Check 명령: `{GENERATE_COMMAND} --check`",
        "",
        f"- 명령: **{len(ordered)}**개 "
        f"(mutating **{mutating}** / read-only **{len(ordered) - mutating}**)",
        "",
        "## 명령",
        "",
        "| IPC 명령 | 분류 | `required_services` | `audit_action` "
        "| 요청 모델 | 요청 필드 | CLI 경로 |",
        "|---|---|---|---|---|---|---|",
    ]
    for spec in ordered:
        kind = "mutating" if spec.is_mutating else "read-only"
        audit = f"`{spec.audit_action}`" if spec.audit_action else "—"
        cells = [
            f"`{spec.name}`",
            kind,
            _code_list(spec.required_services),
            audit,
            f"`{spec.request_model.__name__}`",
            _fields_cell(spec.request_model),
            _code_list(paths.get(spec.name, [])),
        ]
        lines.append("| " + " | ".join(cells) + " |")
    lines += [
        "",
        "## 중첩 요청 모델",
        "",
        "| 모델 | 요청 필드 |",
        "|---|---|",
    ]
    nested = nested_models(spec.request_model for spec in ordered)
    for model in sorted(nested, key=lambda model: model.__name__):
        lines.append(f"| `{model.__name__}` | {_fields_cell(model)} |")
    return "\n".join(lines) + "\n"


def render_ipc_commands() -> str:
    """실제 등록과 CLI 계약으로 문서를 만든다."""
    from ante.contracts.cli_registry import all_contracts
    from ante.ipc.registry import CommandRegistry, register_all_handlers

    registry = CommandRegistry()
    register_all_handlers(registry)
    return render(registry.iter_specs(), all_contracts())


# ── check ────────────────────────────────────────────────────────────────


def _display_path(output_path: Path) -> Path:
    try:
        return output_path.relative_to(PROJECT_ROOT)
    except ValueError:
        return output_path


def _check_output(output_path: Path, content: str) -> int:
    current = output_path.read_text(encoding="utf-8") if output_path.exists() else ""
    rel_output = _display_path(output_path)
    if current == content:
        print(f"{rel_output} is up to date.")
        return 0
    print(f"{rel_output} is stale.")
    print(f"Run: {GENERATE_COMMAND}")
    print()
    diff = list(
        difflib.unified_diff(
            current.splitlines(),
            content.splitlines(),
            fromfile=f"a/{rel_output}",
            tofile=f"b/{rel_output}",
            lineterm="",
        )
    )
    max_lines = 120
    for line in diff[:max_lines]:
        print(line)
    if len(diff) > max_lines:
        print(f"... diff truncated ({len(diff) - max_lines} more lines)")
    return 1


def main(argv: list[str] | None = None) -> int:
    """스크립트 진입점."""
    parser = argparse.ArgumentParser(
        description="CommandRegistry 기반 IPC 명령 문서 자동 생성/check",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=(
            "출력 파일 경로. 상대 경로는 저장소 루트 기준으로 해석한다 "
            "(기본: docs/architecture/generated/ipc-commands.md)"
        ),
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="파일 대신 stdout으로 출력",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="파일을 수정하지 않고 generated 문서가 최신인지 확인",
    )
    args = parser.parse_args(argv)
    _assert_current_worktree_import_path()

    output_path = args.output
    if not output_path.is_absolute():
        output_path = PROJECT_ROOT / output_path

    if args.stdout and args.check:
        parser.error("--stdout and --check cannot be used together")

    content = render_ipc_commands()
    if args.stdout:
        sys.stdout.write(content)
        return 0
    if args.check:
        return _check_output(output_path, content)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")
    print(f"Generated {_display_path(output_path)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
