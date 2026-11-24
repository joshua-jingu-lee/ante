"""「테이블 없음」 판별 리터럴이 공용 술어 한 곳에만 있는지 잠그는 구조 테스트.

``src/ante`` 의 모든 ``.py`` 를 ``ast.parse`` 하고 문자열 상수(docstring·f-string
조각 포함) 중 ``"no such table"`` 을 대소문자 구분 없이 포함하는 것의 위치를
(상대경로, 감싸는 함수명) 집합으로 모은다. 그 집합은
``ante.core.database.is_missing_table`` 정의 한 곳과 정확히 같아야 한다.

알려진 한계: ``+`` 연산으로 쪼갠 리터럴과 바이트 리터럴은 잡지 못한다.
"""

from __future__ import annotations

import ast
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SRC = _REPO_ROOT / "src" / "ante"
_NEEDLE = "no such table"
_EXPECTED = {("src/ante/core/database.py", "is_missing_table")}
_MIN_FILES = 100


def _literal_sites(path: Path) -> set[tuple[str, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    rel = path.relative_to(_REPO_ROOT).as_posix()
    sites: set[tuple[str, str]] = set()

    def visit(node: ast.AST, func: str) -> None:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            func = node.name
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and _NEEDLE in node.value.lower()
        ):
            sites.add((rel, func))
        for child in ast.iter_child_nodes(node):
            visit(child, func)

    visit(tree, "<module>")
    return sites


def test_missing_table_literal_only_in_shared_predicate() -> None:
    files = sorted(_SRC.rglob("*.py"))
    assert len(files) >= _MIN_FILES, f"스캔한 파일이 너무 적다: {len(files)}"
    found: set[tuple[str, str]] = set()
    for path in files:
        found |= _literal_sites(path)
    assert found == _EXPECTED
