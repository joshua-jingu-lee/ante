"""명령이 text 줄을 dict의 표현(``str(<이름>)``)으로 정하지 않는다 (#2759).

``src/ante/cli/commands/*.py``에서 ``CommandResult(text=(str(<이름>),))`` 꼴의 자리를
(파일, 둘러싼 함수)로 모아, 안내 문장이 없어 text 줄을 새로 지어야 하는 여섯 자리
(#2884)와 같음을 잠근다. 새 자리(회귀)와 수집 0건(공허 통과)을 함께 막는다.

알려진 한계: ``str(<이름>)`` 꼴만 잡는다 — ``repr(...)``·f-string·``str(<속성>)``은
잡지 않는다.
"""

from __future__ import annotations

import ast
from pathlib import Path

_COMMANDS_DIR = (
    Path(__file__).resolve().parents[3] / "src" / "ante" / "cli" / "commands"
)

_ALLOWED = {
    ("approval.py", "info"),
    ("data.py", "data_list"),
    ("data.py", "schema"),
    ("instrument.py", "instrument_list"),
    ("instrument.py", "search"),
    ("report.py", "schema"),
}


def _is_str_of_name(node: ast.expr) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "str"
        and len(node.args) == 1
        and not node.keywords
        and isinstance(node.args[0], ast.Name)
    )


def _collect(
    node: ast.AST, path: Path, func: str | None, out: set[tuple[str, str | None]]
) -> None:
    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
        func = node.name
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "CommandResult"
    ):
        for kw in node.keywords:
            if (
                kw.arg == "text"
                and isinstance(kw.value, ast.Tuple)
                and len(kw.value.elts) == 1
                and _is_str_of_name(kw.value.elts[0])
            ):
                out.add((path.name, func))
    for child in ast.iter_child_nodes(node):
        _collect(child, path, func, out)


def _dict_repr_text_sites() -> set[tuple[str, str | None]]:
    found: set[tuple[str, str | None]] = set()
    for path in sorted(_COMMANDS_DIR.glob("*.py")):
        _collect(ast.parse(path.read_text(encoding="utf-8")), path, None, found)
    return found


def test_dict_repr_text_sites_are_only_the_known_six() -> None:
    assert _COMMANDS_DIR.is_dir()
    assert _dict_repr_text_sites() == _ALLOWED
