#!/usr/bin/env python3
"""에러 레지스트리 기반 에러 코드 문서 자동 생성/check.

``src/ante/contracts/error_registry.py``에 정의된 ``ErrorSpec`` 상수 전부와
``EXCEPTION_TO_SPEC``에서 docs/architecture/generated/error-codes.md를 생성한다.

SSOT: ``src/ante/contracts/error_registry.py``
-> docs/architecture/generated/error-codes.md

사용법:
    python scripts/generate_error_codes.py
    python scripts/generate_error_codes.py --output <path>
    python scripts/generate_error_codes.py --stdout
    python scripts/generate_error_codes.py --check

    <path> 기본값: docs/architecture/generated/error-codes.md
"""

from __future__ import annotations

import argparse
import difflib
import importlib.util
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = PROJECT_ROOT / "docs" / "architecture" / "generated" / "error-codes.md"
GENERATE_COMMAND = (
    "PYTHONPATH=$PWD/src .venv/bin/python scripts/generate_error_codes.py"
)
_CODE_MARKS = ("`", "|", "\n", "\r")
_PROSE_MARKS = ("|", "\n", "\r")


class UnsupportedValueError(ValueError):
    """생성기가 표기 규칙을 모르는 값."""


def _load_import_guard() -> Any:
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


# ── 칸 표기 ──────────────────────────────────────────────────────────────


def _code(text: str) -> str:
    """코드 칸(백틱으로 감싼다). 칸을 깨는 문자는 실패한다."""
    if not text or any(mark in text for mark in _CODE_MARKS):
        raise UnsupportedValueError(f"unsupported code-cell text: {text!r}")
    return f"`{text}`"


def _prose(text: str) -> str:
    """의미 칸. 개행·파이프·짝이 맞지 않는 백틱은 실패한다."""
    if not text:
        return "—"
    if any(mark in text for mark in _PROSE_MARKS) or text.count("`") % 2:
        raise UnsupportedValueError(f"unsupported description text: {text!r}")
    return text


def class_path(cls: type) -> str:
    """예외 클래스의 모듈 경로(``<module>.<qualname>``)."""
    return f"{cls.__module__}.{cls.__qualname__}"


def registry_specs(namespace: Mapping[str, object]) -> list[Any]:
    """모듈 이름공간의 ``ErrorSpec`` 값(이름 순)."""
    from ante.contracts.errors import ErrorSpec

    return [
        value for _, value in sorted(namespace.items()) if isinstance(value, ErrorSpec)
    ]


def _row_values(specs: list[Any]) -> tuple[str, int, str]:
    values = {(spec.category, spec.exit_code, spec.description) for spec in specs}
    if len(values) != 1:
        raise UnsupportedValueError(
            f"specs of {specs[0].code!r} disagree: {sorted(values)!r}"
        )
    (value,) = values
    return value


# ── Markdown 생성 ────────────────────────────────────────────────────────


def render(specs: Iterable[Any], mapping: Mapping[type, Any]) -> str:
    """``ErrorSpec``과 예외 매핑에서 문서 전체를 만든다(입력 순서에 의존하지 않는다)."""
    by_code: dict[str, list[Any]] = {}
    for spec in specs:
        by_code.setdefault(spec.code, []).append(spec)
    classes: dict[str, list[str]] = {}
    for cls, spec in mapping.items():
        if spec.code not in by_code:
            raise UnsupportedValueError(f"unregistered code in mapping: {spec.code!r}")
        classes.setdefault(spec.code, []).append(class_path(cls))
    codes = sorted(by_code)
    mapped = sum(1 for code in codes if code in classes)
    lines = [
        "# Ante Error Codes",
        "",
        "에러 레지스트리(`src/ante/contracts/error_registry.py`)에 등록된 안정 에러 "
        "코드를 정리한 문서입니다. 레지스트리 모듈의 `ErrorSpec` 상수 전부와 "
        "`EXCEPTION_TO_SPEC`에서 생성합니다.",
        "",
        "> 이 문서는 `scripts/generate_error_codes.py`로 자동 생성됩니다. "
        "직접 편집하지 말고 레지스트리를 수정한 뒤 재생성하세요.",
        "",
        f"> 생성 명령: `{GENERATE_COMMAND}`",
        f"> Check 명령: `{GENERATE_COMMAND} --check`",
        "",
        f"- 코드: **{len(codes)}**개 "
        f"(예외 클래스 매핑 있음 **{mapped}** / 없음 **{len(codes) - mapped}**)",
        "",
        "코드·분류·종료 코드·의미는 그 코드의 `ErrorSpec`의 `code`·`category`·"
        "`exit_code`·`description`에서, 예외 클래스는 `EXCEPTION_TO_SPEC`에서 "
        "그 코드를 가진 `ErrorSpec`에 연결된 클래스에서 얻습니다. 예외 클래스가 "
        "`—`인 코드는 "
        "`EXCEPTION_TO_SPEC`에 연결된 클래스가 없고, 의미가 `—`인 코드는 "
        "`description`이 비어 있습니다. 분류의 뜻과 명명 규칙은 "
        "[error-taxonomy.md](../../specs/contracts/error-taxonomy.md)에서 봅니다.",
        "",
        "## 코드",
        "",
        "| 코드 | 분류 | 종료 코드 | 예외 클래스 | 의미 |",
        "|---|---|---|---|---|",
    ]
    for code in codes:
        category, exit_code, description = _row_values(by_code[code])
        paths = sorted(classes.get(code, []))
        cells = [
            _code(code),
            _code(category),
            str(exit_code),
            "<br>".join(_code(path) for path in paths) if paths else "—",
            _prose(description),
        ]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def render_error_codes() -> str:
    """실제 레지스트리로 문서를 만든다."""
    from ante.contracts import error_registry

    return render(
        registry_specs(vars(error_registry)), error_registry.EXCEPTION_TO_SPEC
    )


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
        description="에러 레지스트리 기반 에러 코드 문서 자동 생성/check",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=(
            "출력 파일 경로. 상대 경로는 저장소 루트 기준으로 해석한다 "
            "(기본: docs/architecture/generated/error-codes.md)"
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

    content = render_error_codes()
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
