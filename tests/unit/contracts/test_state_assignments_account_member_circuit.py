"""계좌·멤버 상태를 쓰는 자리가 전이 함수 하나로 모였는지 잠그는 구조 테스트 (#2657).

대상 파일은 ``src/ante/account/service.py`` 와 ``src/ante/member/service.py``
다(두 상태를 쓰는 곳이 이 두 파일뿐이다).

**상태 대입**: 대상이 ``.status`` 속성인 ``Assign``/``AnnAssign``/``AugAssign``
이다. 우변은 보지 않는다. 대상은 튜플·리스트·``Starred`` 안까지 펼친다.
파일마다 모듈 수준 함수 ``_transition_status`` 의 본문 안에 정확히 1개, 밖에
0개여야 한다.

**생성자 키워드**: 이름이 ``status`` 인 키워드 인자를 가진 호출이다. 감싸는
함수와 호출 대상 이름의 쌍이 계좌는 ``_row_to_account`` 1곳, 멤버는
``_row_to_member``·``bootstrap_master``·``register`` 3곳뿐이어야 한다.
``setattr(..., "status", ...)`` 호출은 0개여야 한다.

**호출 자리**: ``_transition_status`` 를 부르는 곳마다 (감싸는 함수, 위치 인자
목록)이 리터럴 표와 같아야 한다. 호출은 ``status = _transition_status(...)``
문이고, 같은 메서드에서 ``SET status`` 를 쓰는 ``self._db.execute`` 보다 앞에
있으며, 그 ``execute`` 의 인자 튜플 첫 원소는 이름 ``status`` 다.

알려진 한계: ``**kwargs`` 언패킹으로 넘기는 ``status``, ``__dict__``·
``object.__setattr__``·``dataclasses.replace`` 를 거치는 쓰기, 다른 파일의
쓰기는 보지 않는다.
"""

from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_ACCOUNT = _REPO_ROOT / "src" / "ante" / "account" / "service.py"
_MEMBER = _REPO_ROOT / "src" / "ante" / "member" / "service.py"
_TRANSITION_FUNC = "_transition_status"

_FILES = pytest.mark.parametrize("path", [_ACCOUNT, _MEMBER], ids=["account", "member"])


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


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


@_FILES
def test_transition_function_is_a_module_level_function(path):
    tree = _parse(path)
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


@_FILES
def test_status_is_assigned_only_inside_transition_function(path):
    tree = _parse(path)
    owner = _enclosing_functions(tree)
    where = Counter(owner[id(node)] for node in _status_assignments(tree))
    assert dict(where) == {_TRANSITION_FUNC: 1}


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        (_ACCOUNT, [("_row_to_account", "Account")]),
        (
            _MEMBER,
            [
                ("_row_to_member", "Member"),
                ("bootstrap_master", "Member"),
                ("register", "Member"),
            ],
        ),
    ],
    ids=["account", "member"],
)
def test_status_keyword_only_in_known_constructors(path, expected):
    tree = _parse(path)
    owner = _enclosing_functions(tree)
    sites = sorted(
        (owner[id(node)], _callee_name(node))
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and any(kw.arg == "status" for kw in node.keywords)
    )
    assert sites == expected


@_FILES
def test_no_setattr_of_status(path):
    tree = _parse(path)
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


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        (
            _ACCOUNT,
            [
                ("activate", ("account", "AccountStatus.ACTIVE")),
                ("delete", ("account", "AccountStatus.DELETED")),
                ("suspend", ("account", "AccountStatus.SUSPENDED")),
            ],
        ),
        (
            _MEMBER,
            [
                ("reactivate", ("member", "MemberStatus.ACTIVE", "'reactivate'")),
                ("revoke", ("member", "MemberStatus.REVOKED", "'revoke'")),
                ("suspend", ("member", "MemberStatus.SUSPENDED", "'suspend'")),
            ],
        ),
    ],
    ids=["account", "member"],
)
def test_transition_function_call_sites(path, expected):
    tree = _parse(path)
    owner = _enclosing_functions(tree)
    calls = sorted(
        (owner[id(node)], tuple(ast.unparse(arg) for arg in node.args))
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and _callee_name(node) == _TRANSITION_FUNC
    )
    assert all(not node.keywords for node in _transition_calls(tree))
    assert calls == expected


def _transition_calls(tree: ast.Module) -> list[ast.Call]:
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and _callee_name(node) == _TRANSITION_FUNC
    ]


def _status_update(method: ast.AsyncFunctionDef) -> ast.Call:
    found = [
        node
        for node in ast.walk(method)
        if isinstance(node, ast.Call)
        and _callee_name(node) == "execute"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
        and "SET status" in " ".join(node.args[0].value.split())
    ]
    assert len(found) == 1, method.name
    return found[0]


@_FILES
def test_transition_precedes_the_status_update_and_feeds_it(path):
    tree = _parse(path)
    methods = {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef)
    }
    owner = _enclosing_functions(tree)
    callers = sorted(owner[id(call)] for call in _transition_calls(tree))
    assert len(callers) == 3
    for name in callers:
        method = methods[name]
        assigns = [
            node
            for node in ast.walk(method)
            if isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Call)
            and _callee_name(node.value) == _TRANSITION_FUNC
        ]
        assert len(assigns) == 1, name
        assert [ast.unparse(t) for t in assigns[0].targets] == ["status"], name
        update = _status_update(method)
        assert assigns[0].lineno < update.lineno, name
        params = update.args[1]
        assert isinstance(params, ast.Tuple), name
        assert ast.unparse(params.elts[0]) == "status", name
