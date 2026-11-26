"""계좌·멤버·회로차단기 상태를 쓰는 자리가 전이 함수로 모였는지 잠그는 구조 테스트.

대상 파일은 ``src/ante/account/service.py`` 와 ``src/ante/member/service.py``
다(두 상태를 쓰는 곳이 이 두 파일뿐이다).

**상태 대입**: 대상이 ``.status`` 속성인 ``Assign``/``AnnAssign``/``AugAssign``
이다. 우변은 보지 않는다. 대상은 튜플·리스트·``Starred`` 안까지 펼친다.
파일마다 모듈 수준 함수 ``_transition_status`` 의 본문 안에 정확히 1개, 밖에
0개여야 한다. 계좌 파일만 예외로 ``_restore_status`` 안에 1개를 더 허용한다.

**되돌리기** (#2667): ``_restore_status`` 는 계좌 파일의 모듈 수준 함수이고,
부르는 곳은 ``activate``·``delete`` 의 ``except BaseException`` 처리기뿐이다.
그 처리기는 ``SET status`` UPDATE를 감싼 ``try`` 에 달려 있고 마지막 문이
인자 없는 ``raise`` 다. 되돌릴 값은 전이 호출보다 앞에서 잡는다. ``suspend``
에는 되돌리기가 없고, ``SET status`` UPDATE를 감싼 ``try`` 의 처리기는
``.status`` 를 쓰지 않는다(#2858: 쓰기가 실패해도 정지를 유지한다).

**생성자 키워드**: 이름이 ``status`` 인 키워드 인자를 가진 호출이다. 감싸는
함수와 호출 대상 이름의 쌍이 계좌는 ``_row_to_account`` 1곳, 멤버는
``_row_to_member``·``bootstrap_master``·``register`` 3곳뿐이어야 한다.
``setattr(..., "status", ...)`` 호출은 0개여야 한다.

**호출 자리**: ``_transition_status`` 를 부르는 곳마다 (감싸는 함수, 위치 인자
목록)이 리터럴 표와 같아야 한다. 호출은 ``status = _transition_status(...)``
문이고, 같은 메서드에서 ``SET status`` 를 쓰는 ``self._db.execute`` 보다 앞에
있으며, 그 ``execute`` 의 인자 튜플 첫 원소는 이름 ``status`` 다. 계좌의
``suspend_all`` 만 예외다(#3077): UPDATE가 없고, 전이 호출 바로 다음 문이
미기록 표시 ``self._unpersisted_suspensions.add(account_id)`` 이며, 둘 다 유일한
``self.suspend(...)`` 호출보다 앞이고, 함수의 첫 ``await`` 는 전이를 감싼 루프보다
뒤다(메모리≠DB는 반드시 표시되고, 차단은 어느 구독자보다 먼저 끝난다).

**기존 검사**: 호출보다 앞 줄의 ``raise``·``return``·``self._assert_*`` 호출이
메서드마다 리터럴 목록과 같다(기존 검사를 표 검사로 대체하지 않는다).

**회로차단기** (``src/ante/broker/circuit_breaker.py``): 대상이 ``._state``
속성인 대입(같은 세 노드 종류, 같은 펼침)은 ``_transition`` 안 1개와
``__init__`` 1개뿐이다. ``_transition`` 을 부르는 곳마다 (감싸는 함수, 첫 위치
인자)가 리터럴 표와 같다. ``_transition`` 안에서 표를 읽고 ``raise`` 하는
``if`` 는 ``self._state`` 대입·``logger`` 호출·``_publish_event`` 호출보다
앞 줄에 있다.

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
_CIRCUIT = _REPO_ROOT / "src" / "ante" / "broker" / "circuit_breaker.py"
_TRANSITION_FUNC = "_transition_status"
_RESTORE_FUNC = "_restore_status"

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


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        (_ACCOUNT, {_TRANSITION_FUNC: 1, _RESTORE_FUNC: 1}),
        (_MEMBER, {_TRANSITION_FUNC: 1}),
    ],
    ids=["account", "member"],
)
def test_status_is_assigned_only_inside_transition_function(path, expected):
    tree = _parse(path)
    owner = _enclosing_functions(tree)
    where = Counter(owner[id(node)] for node in _status_assignments(tree))
    assert dict(where) == expected


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
                ("suspend_all", ("account", "AccountStatus.SUSPENDED")),
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


@pytest.mark.parametrize(
    ("path", "with_update", "without_update"),
    [
        (_ACCOUNT, ["activate", "delete", "suspend"], ["suspend_all"]),
        (_MEMBER, ["reactivate", "revoke", "suspend"], []),
    ],
    ids=["account", "member"],
)
def test_transition_precedes_the_status_update_and_feeds_it(
    path, with_update, without_update
):
    tree = _parse(path)
    methods = {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef)
    }
    owner = _enclosing_functions(tree)
    callers = sorted(owner[id(call)] for call in _transition_calls(tree))
    assert callers == sorted(with_update + without_update)
    for name in with_update:
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


def test_suspend_all_marks_unpersisted_right_after_transition_before_any_await():
    method = _async_methods(_parse(_ACCOUNT))["suspend_all"]
    reason = "#3077: 전체 정지는 await 전에 전 계좌를 정지·미기록 표시한다"
    parent_of = {
        id(child): node
        for node in ast.walk(method)
        for child in ast.iter_child_nodes(node)
    }
    (call,) = [
        node
        for node in ast.walk(method)
        if isinstance(node, ast.Call) and _callee_name(node) == _TRANSITION_FUNC
    ]
    transition = parent_of[id(call)]
    assert isinstance(transition, ast.Expr), reason
    block = parent_of[id(transition)]
    body = block.body
    index = next(i for i, stmt in enumerate(body) if stmt is transition)
    assert index + 1 < len(body), reason
    mark = body[index + 1]
    assert ast.unparse(mark) == "self._unpersisted_suspensions.add(account_id)", reason
    (suspend_call,) = [
        node
        for node in ast.walk(method)
        if isinstance(node, ast.Call) and ast.unparse(node.func) == "self.suspend"
    ]
    assert transition.lineno < mark.lineno < suspend_call.lineno, reason
    assert not any(
        isinstance(node, ast.Call)
        and _callee_name(node) == "execute"
        and "SET status" in ast.unparse(node)
        for node in ast.walk(method)
    ), reason
    loop: ast.AST = block
    while not isinstance(loop, ast.For):
        loop = parent_of[id(loop)]
    first_await = min(
        node.lineno
        for node in ast.walk(method)
        if isinstance(node, ast.Await | ast.AsyncFor | ast.AsyncWith)
    )
    assert first_await > (loop.end_lineno or 0), reason


def _async_methods(tree: ast.Module) -> dict[str, ast.AsyncFunctionDef]:
    return {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef)
    }


def _restore_handlers(tree: ast.Module) -> list[tuple[str, ast.Try, ast.ExceptHandler]]:
    owner = _enclosing_functions(tree)
    found: list[tuple[str, ast.Try, ast.ExceptHandler]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        for handler in node.handlers:
            calls = [
                call
                for stmt in handler.body
                for call in ast.walk(stmt)
                if isinstance(call, ast.Call) and _callee_name(call) == _RESTORE_FUNC
            ]
            if calls:
                found.append((owner[id(node)], node, handler))
    return found


def test_restore_is_called_only_in_activate_and_delete_failure_handlers():
    tree = _parse(_ACCOUNT)
    owner = _enclosing_functions(tree)
    module_level = [
        node.name for node in tree.body if isinstance(node, ast.FunctionDef)
    ]
    assert _RESTORE_FUNC in module_level
    calls = sorted(
        (owner[id(node)], tuple(ast.unparse(arg) for arg in node.args))
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and _callee_name(node) == _RESTORE_FUNC
    )
    args = ("account", "previous_status", "previous_updated_at")
    assert calls == [("activate", args), ("delete", args)]

    handlers = _restore_handlers(tree)
    assert sorted(name for name, _, _ in handlers) == ["activate", "delete"]
    methods = _async_methods(tree)
    for name, try_node, handler in handlers:
        assert handler.type is not None and ast.unparse(handler.type) == (
            "BaseException"
        ), name
        assert handler.name is None, name
        last = handler.body[-1]
        assert isinstance(last, ast.Raise) and last.exc is None, name
        update = _status_update(methods[name])
        assert any(update in list(ast.walk(stmt)) for stmt in try_node.body), name
        (transition,) = [
            call
            for call in ast.walk(methods[name])
            if isinstance(call, ast.Call) and _callee_name(call) == _TRANSITION_FUNC
        ]
        captures = [
            node
            for node in ast.walk(methods[name])
            if isinstance(node, ast.Assign)
            and [ast.unparse(t) for t in node.targets]
            == ["(previous_status, previous_updated_at)"]
            and ast.unparse(node.value) == "(account.status, account.updated_at)"
        ]
        assert len(captures) == 1, name
        assert captures[0].lineno < transition.lineno, name


def test_suspend_write_failure_never_restores_status():
    tree = _parse(_ACCOUNT)
    suspend = _async_methods(tree)["suspend"]
    reason = "#2858: suspend는 상태 쓰기가 실패해도 정지를 되돌리지 않는다"
    restores = [
        node
        for node in ast.walk(suspend)
        if isinstance(node, ast.Call) and _callee_name(node) == _RESTORE_FUNC
    ]
    assert restores == [], reason
    update = _status_update(suspend)
    wrapping = [
        node
        for node in ast.walk(suspend)
        if isinstance(node, ast.Try)
        and any(update in list(ast.walk(stmt)) for stmt in node.body)
    ]
    assert len(wrapping) == 1, reason
    handler_writes = [
        ast.unparse(node)
        for handler in wrapping[0].handlers
        for stmt in handler.body
        for node in _status_assignments(ast.Module(body=[stmt], type_ignores=[]))
    ]
    assert handler_writes == [], reason
    assert [ast.unparse(h.type) for h in wrapping[0].handlers if h.type] == [
        "Exception",
        "BaseException",
    ], reason


def _guards_before_transition(method: ast.AsyncFunctionDef) -> list[str]:
    (call,) = [
        node
        for node in ast.walk(method)
        if isinstance(node, ast.Call) and _callee_name(node) == _TRANSITION_FUNC
    ]
    guards: list[tuple[int, str]] = []
    for node in ast.walk(method):
        if getattr(node, "lineno", call.lineno) >= call.lineno:
            continue
        if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call):
            guards.append((node.lineno, f"raise {_callee_name(node.exc)}"))
        elif isinstance(node, ast.Return):
            guards.append((node.lineno, "return"))
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr.startswith("_assert_")
        ):
            guards.append((node.lineno, node.func.attr))
    return [name for _, name in sorted(guards)]


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        (
            _ACCOUNT,
            {
                "activate": ["raise AccountDeletedException", "return"],
                "delete": [
                    "raise AccountStructuralChangeRequiresStoppedServerError",
                    "raise AccountDeletedException",
                    "raise AccountHasActiveBotsError",
                ],
                "suspend": [
                    "raise AccountDeletedException",
                    "raise AccountAlreadySuspendedError",
                ],
                "suspend_all": [],
            },
        ),
        (
            _MEMBER,
            {
                "reactivate": ["_assert_master", "raise MemberStateConflictError"],
                "revoke": [
                    "_assert_master",
                    "_assert_not_master",
                    "raise MemberStateConflictError",
                ],
                "suspend": [
                    "_assert_master",
                    "_assert_not_master",
                    "raise MemberStateConflictError",
                ],
            },
        ),
    ],
    ids=["account", "member"],
)
def test_existing_guards_stay_before_the_transition(path, expected):
    tree = _parse(path)
    owner = _enclosing_functions(tree)
    methods = {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef)
    }
    callers = sorted(owner[id(call)] for call in _transition_calls(tree))
    guards = {name: _guards_before_transition(methods[name]) for name in callers}
    assert guards == expected


def _attribute_assignments(tree: ast.Module, attr: str) -> list[ast.stmt]:
    found: list[ast.stmt] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign | ast.AugAssign):
            targets = [node.target]
        else:
            continue
        flat = [t for target in targets for t in _flatten_targets(target)]
        if any(isinstance(t, ast.Attribute) and t.attr == attr for t in flat):
            found.append(node)
    return found


def test_circuit_state_is_assigned_only_in_init_and_transition():
    tree = _parse(_CIRCUIT)
    owner = _enclosing_functions(tree)
    where = Counter(owner[id(node)] for node in _attribute_assignments(tree, "_state"))
    assert dict(where) == {"__init__": 1, "_transition": 1}


def test_circuit_transition_call_sites():
    tree = _parse(_CIRCUIT)
    owner = _enclosing_functions(tree)
    calls = sorted(
        (owner[id(node)], ast.unparse(node.args[0]))
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and _callee_name(node) == "_transition"
    )
    assert calls == [
        ("record_failure", "CircuitState.OPEN"),
        ("record_failure", "CircuitState.OPEN"),
        ("record_success", "CircuitState.CLOSED"),
        ("state", "CircuitState.HALF_OPEN"),
    ]


def test_circuit_table_check_precedes_assignment_log_and_event():
    tree = _parse(_CIRCUIT)
    (method,) = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_transition"
    ]
    assert [a.arg for a in method.args.args] == ["self", "new_state", "reason"]
    guards = [
        node
        for node in method.body
        if isinstance(node, ast.If)
        and "CIRCUIT_STATE_TRANSITIONS" in ast.unparse(node.test)
        and any(isinstance(stmt, ast.Raise) for stmt in node.body)
    ]
    assert len(guards) == 1
    guard_line = guards[0].lineno
    later = [
        node.lineno
        for node in _attribute_assignments(tree, "_state")
        if node.lineno >= method.lineno and node.lineno <= (method.end_lineno or 0)
    ]
    later += [
        node.lineno
        for node in ast.walk(method)
        if isinstance(node, ast.Call)
        and _callee_name(node) in {"warning", "_publish_event"}
    ]
    assert len(later) == 3
    assert all(guard_line < line for line in later)
