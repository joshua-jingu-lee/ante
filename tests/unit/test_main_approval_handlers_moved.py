"""#2692: 결재 실행기·사전 검증기는 ``main.py`` 에 정의되지 않는다."""

from __future__ import annotations

import ast
from pathlib import Path

import ante

MAIN_PY = Path(ante.__file__).resolve().parent / "main.py"


def test_main_defines_no_exec_or_validate_functions() -> None:
    tree = ast.parse(MAIN_PY.read_text(encoding="utf-8"))
    names = sorted(
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        and node.name.startswith(("_exec_", "_validate_"))
    )
    assert names == []


def test_main_py_is_parsed() -> None:
    tree = ast.parse(MAIN_PY.read_text(encoding="utf-8"))
    names = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }
    assert "_init_approval" in names
