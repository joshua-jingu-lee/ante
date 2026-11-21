"""결재 상태를 쓰는 자리가 전이 함수 하나로 모였는지 잠그는 구조 불변식 테스트 (#2654).

대상 파일은 ``src/ante/approval/service.py`` 하나다(결재 상태를 쓰는 곳이
이 파일뿐이다).

**상태 대입**: 대상이 ``.status`` 속성인 ``Assign``/``AnnAssign``/``AugAssign``
이다. 우변은 보지 않는다. 대상은 튜플·리스트·``Starred`` 안까지 펼친다.
모듈 수준 함수 ``_transition_status`` 의 본문 안에 정확히 1개, 밖에 0개여야
한다.

**생성자 키워드**: 이름이 ``status`` 인 키워드 인자를 가진 호출이다. 감싸는
함수와 호출 대상 이름의 쌍이 ``create``·``_row_to_request`` 의
``ApprovalRequest`` 두 곳뿐이어야 한다. ``setattr(..., "status", ...)`` 호출은
0개여야 한다.

**호출 자리**: ``_transition_status`` 를 부르는 곳마다 (감싸는 함수, 다음
상태 인자, 동작 이름 인자)의 목록이 리터럴 표와 같아야 한다. 모든 호출은
위치 인자 셋으로 부른다.

알려진 한계: ``**kwargs`` 언패킹으로 넘기는 ``status``, ``__dict__``·
``object.__setattr__`` 를 거치는 쓰기, 다른 파일의 쓰기는 보지 않는다.
"""

from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SERVICE = _REPO_ROOT / "src" / "ante" / "approval" / "service.py"
_TRANSITION_FUNC = "_transition_status"


def _parse() -> ast.Module:
    return ast.parse(_SERVICE.read_text(encoding="utf-8"))


def _enclosing_functions(tree: ast.Module) -> dict[int, str]:
    owner: dict[int, str] = {}

    def visit(node: ast.AST, current: str) -> None:
        for child in ast.iter_child_nodes(node):
            name = current
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                name = child.name
            owner[id(child)] = name
            visit(child, name)

    visit(tree, "<module>")
    return owner


def _flatten_targets(target: ast.expr) -> list[ast.expr]:
    if isinstance(target, ast.Tuple | ast.List):
        out: list[ast.expr] = []
        for elt in target.elts:
            out.extend(_flatten_targets(elt))
        return out
    if isinstance(target, ast.Starred):
        return _flatten_targets(target.value)
    return [target]


def _status_assignments(tree: ast.Module) -> list[ast.stmt]:
    found: list[ast.stmt] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign | ast.AugAssign):
            targets = [node.target]
        else:
            continue
        flat = [t for target in targets for t in _flatten_targets(target)]
        if any(isinstance(t, ast.Attribute) and t.attr == "status" for t in flat):
            found.append(node)
    return found


def _callee_name(call: ast.Call) -> str:
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ast.unparse(func)


def test_transition_function_is_a_module_level_function():
    tree = _parse()
    module_level = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == _TRANSITION_FUNC
    ]
    assert len(module_level) == 1
    everywhere = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        and node.name == _TRANSITION_FUNC
    ]
    assert len(everywhere) == 1


def test_status_is_assigned_only_inside_transition_function():
    tree = _parse()
    owner = _enclosing_functions(tree)
    where = Counter(owner[id(node)] for node in _status_assignments(tree))
    assert dict(where) == {_TRANSITION_FUNC: 1}


def test_status_keyword_only_in_two_constructors():
    tree = _parse()
    owner = _enclosing_functions(tree)
    sites = sorted(
        (owner[id(node)], _callee_name(node))
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and any(kw.arg == "status" for kw in node.keywords)
    )
    assert sites == [
        ("_row_to_request", "ApprovalRequest"),
        ("create", "ApprovalRequest"),
    ]


def test_no_setattr_of_status():
    tree = _parse()
    offenders = [
        ast.unparse(node)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and _callee_name(node) == "setattr"
        and len(node.args) >= 2
        and isinstance(node.args[1], ast.Constant)
        and node.args[1].value == "status"
    ]
    assert offenders == []


def test_transition_function_call_sites():
    tree = _parse()
    owner = _enclosing_functions(tree)
    calls = sorted(
        (owner[id(node)], ast.unparse(node.args[1]), ast.unparse(node.args[2]))
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and _callee_name(node) == _TRANSITION_FUNC
    )
    assert calls == [
        ("_execute_approved", "ApprovalStatus.EXECUTION_FAILED", "'execute'"),
        ("_execute_approved", "ApprovalStatus.EXECUTION_FAILED", "'execute'"),
        ("approve", "ApprovalStatus.APPROVED", "'approve'"),
        ("cancel", "ApprovalStatus.CANCELLED", "'cancel'"),
        (
            "cancel_invalid_type_request",
            "ApprovalStatus.CANCELLED",
            "'cancel_invalid_type_request'",
        ),
        ("create", "ApprovalStatus.APPROVED", "'create'"),
        ("expire_stale", "ApprovalStatus.EXPIRED", "'expire_stale'"),
        ("hold", "ApprovalStatus.ON_HOLD", "'hold'"),
        ("reject", "ApprovalStatus.REJECTED", "'reject'"),
        ("reopen", "ApprovalStatus.PENDING", "'reopen'"),
        ("resume", "ApprovalStatus.PENDING", "'resume'"),
    ]
