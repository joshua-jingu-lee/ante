"""명령이 text 줄을 dict의 표현(``str(<이름>)``)으로 정하지 않는다 (#2759, #2884).

``src/ante/cli/commands/*.py``에서 ``CommandResult(text=(..., str(<이름>), ...))`` 꼴의
원소를 (파일, 둘러싼 함수) 목록으로 모아 빈 목록과 비교한다. 한 함수에 자리가 둘이면
두 번 센다. 수집 0건이 공허 통과가 되지 않도록 실제 파일·호출 수와 합성 양성 대조를
함께 본다.

알려진 한계: ``str(<이름>)`` 꼴만 잡는다 — ``repr(...)``·f-string·``str(<속성>)``·
변수 경유 ``text=lines``는 잡지 않는다.
"""

from __future__ import annotations

import ast
from pathlib import Path

_COMMANDS_DIR = (
    Path(__file__).resolve().parents[3] / "src" / "ante" / "cli" / "commands"
)

_ALLOWED: list[tuple[str, str | None]] = []

Site = tuple[str, str | None]


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
    node: ast.AST, name: str, func: str | None, sites: list[Site], calls: list[Site]
) -> None:
    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
        func = node.name
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "CommandResult"
    ):
        calls.append((name, func))
        for kw in node.keywords:
            if kw.arg == "text" and isinstance(kw.value, ast.Tuple):
                sites.extend(
                    (name, func) for elt in kw.value.elts if _is_str_of_name(elt)
                )
    for child in ast.iter_child_nodes(node):
        _collect(child, name, func, sites, calls)


def _scan(source: str, name: str) -> tuple[list[Site], list[Site]]:
    sites: list[Site] = []
    calls: list[Site] = []
    _collect(ast.parse(source), name, None, sites, calls)
    return sites, calls


def _dict_repr_text_sites() -> tuple[int, list[Site], list[Site]]:
    files = sorted(_COMMANDS_DIR.glob("*.py"))
    sites: list[Site] = []
    calls: list[Site] = []
    for path in files:
        found, seen = _scan(path.read_text(encoding="utf-8"), path.name)
        sites.extend(found)
        calls.extend(seen)
    return len(files), sorted(sites, key=repr), calls


def test_no_dict_repr_text_sites_remain() -> None:
    assert _COMMANDS_DIR.is_dir()
    file_count, sites, calls = _dict_repr_text_sites()
    assert file_count > 0
    assert len(calls) > 0
    assert sites == sorted(_ALLOWED, key=repr)


def test_collector_finds_single_and_multi_element_tuples() -> None:
    source = (
        "def one(x):\n"
        "    return CommandResult(data=x, text=(str(x),))\n"
        "\n"
        "def two(x):\n"
        "    CommandResult(data=x, text=('a', str(x)))\n"
        "    return CommandResult(data=x, text=(str(x),))\n"
        "\n"
        "def clean(x):\n"
        "    return CommandResult(data=x, text=('a', 'b'))\n"
    )
    sites, calls = _scan(source, "synthetic.py")
    assert sites == [
        ("synthetic.py", "one"),
        ("synthetic.py", "two"),
        ("synthetic.py", "two"),
    ]
    assert len(calls) == 4
