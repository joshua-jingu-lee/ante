"""리포트 상태와 IPC 서버 상태를 쓰는 자리를 잠그는 구조 테스트 (#2688).

리포트 상태의 전이표는 모든 쌍을 허용하고, IPC 서버 상태의 전이표는 앞으로만
허용한다(#2687). 이 테스트는 「상태를 쓰는 자리가 어디인지」를 잠가, 새 쓰기
자리가 생기면 표와 특성 테스트를 함께 다시 보게 한다.

**IPC 서버 상태 대입**: ``src/ante/ipc/server.py`` 에서 대상이 ``._state``
속성인 ``Assign``/``AnnAssign``/``AugAssign`` (대상은 튜플·리스트·
``Starred`` 안까지 펼친다)의 (둘러싼 함수, 값)이 리터럴 목록 5개와 같다.
``src/ante`` 의 다른 파일에서 값이 ``IPCServerState.<멤버>`` 인 대입은 0이다.

**리포트 상태 SQL**: ``src/ante`` 의 문자열 상수를 공백을 정규화하고 대문자로
바꿔 읽는다. ``UPDATE reports`` 를 담고 ``SET`` 절(``SET`` 과 ``WHERE`` 사이,
쉼표로 나눈 각 항의 ``=`` 왼쪽)에 ``status`` 가 있는 것은
``ReportStore.update_status`` 안의 1개뿐이다. ``INSERT [OR …] INTO reports``·
``REPLACE INTO reports`` 를 담은 것은 ``ReportStore.submit`` 안의 1개뿐이다.
``ReportStore.upsert_draft`` 의 ``UPDATE reports`` 는 ``SET`` 절에 ``status`` 가
없다.

**리포트 생성자**: ``StrategyReport(...)`` 호출의 ``status=`` 키워드는 (파일,
둘러싼 함수, 값)이 리터럴 목록 3곳과 같다. ``StrategyReport(...)`` 호출에
``**`` 인자는 0이다. ``src/ante/report/`` 아래와 ``src/ante/cli/commands/report.py``
에서 대상이 ``.status`` 속성인 대입은 0이다.

뒤쪽 대조군은 목록마다 실제 소스에 자리를 하나 더하거나 빼서 판정이 달라지는지
본다.

알려진 한계: ``setattr``, ``dataclasses.replace``, ``tests/`` 안의 ``_state``
직접 대입(여러 테스트가 픽스처로 쓴다), 테이블 기본값(``DEFAULT 'submitted'``),
결재 실행기가 넘기는 대상 인자, f-string(``JoinedStr``)으로 만든 SQL은 세지
않는다. 다음도 세지 않는다.

- ``StrategyReport`` 에 ``status`` 를 위치 인자·``*args`` 로 넘기는 생성
- ``UPDATE OR <conflict> reports``
- ``SET`` 안의 서브쿼리와 행 값 대입(``SET (a, status) = …``)
- ``+`` 로 이어 붙인 SQL
- ``ipc/server.py`` 밖에서의 ``_state`` 대입과 ``main.py`` 의 ``.status`` 대입
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SRC = _REPO_ROOT / "src" / "ante"
_IPC_SERVER = "src/ante/ipc/server.py"
_REPORT_STORE = "src/ante/report/store.py"
_REPORT_DRAFT = "src/ante/report/draft.py"
_REPORT_CLI = "src/ante/cli/commands/report.py"

_UPDATE_REPORTS = re.compile(r"\bUPDATE\s+REPORTS\b")
_INSERT_REPORTS = re.compile(r"\b(?:INSERT(?:\s+OR\s+\w+)?|REPLACE)\s+INTO\s+REPORTS\b")

EXPECTED_IPC_STATE_ASSIGNMENTS = [
    ("__init__", "IPCServerState.STOPPED"),
    ("start", "IPCServerState.RUNNING"),
    ("stop_accepting", "IPCServerState.SHUTTING_DOWN"),
    ("stop_dispatching", "IPCServerState.DRAINING"),
    ("unlink_socket", "IPCServerState.STOPPED"),
]

EXPECTED_STATUS_UPDATES = [(_REPORT_STORE, "ReportStore.update_status")]
EXPECTED_INSERTS = [(_REPORT_STORE, "ReportStore.submit")]

EXPECTED_CONSTRUCTOR_STATUS = [
    (_REPORT_CLI, "submit._submit", "ReportStatus.SUBMITTED"),
    (_REPORT_DRAFT, "ReportDraftGenerator.generate_draft", "ReportStatus.DRAFT"),
    (_REPORT_STORE, "ReportStore._row_to_report", "ReportStatus(row['status'])"),
]


def _real_sources() -> dict[str, str]:
    return {
        path.relative_to(_REPO_ROOT).as_posix(): path.read_text(encoding="utf-8")
        for path in sorted(_SRC.rglob("*.py"))
    }


def _owners(tree: ast.Module) -> dict[int, str]:
    owner: dict[int, str] = {}

    def visit(node: ast.AST, chain: tuple[str, ...]) -> None:
        for child in ast.iter_child_nodes(node):
            inner = chain
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                inner = (*chain, child.name)
            owner[id(child)] = ".".join(chain) or "<module>"
            visit(child, inner)

    visit(tree, ())
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


def _assignments(tree: ast.Module) -> list[ast.Assign | ast.AnnAssign | ast.AugAssign]:
    found: list[ast.Assign | ast.AnnAssign | ast.AugAssign] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign | ast.AnnAssign | ast.AugAssign):
            found.append(node)
    return found


def _targets(node: ast.Assign | ast.AnnAssign | ast.AugAssign) -> list[ast.expr]:
    raw = node.targets if isinstance(node, ast.Assign) else [node.target]
    return [t for target in raw for t in _flatten_targets(target)]


def _assigns_attribute(node: ast.Assign | ast.AnnAssign | ast.AugAssign, attr: str):
    return any(isinstance(t, ast.Attribute) and t.attr == attr for t in _targets(node))


def _leaf(owner: str) -> str:
    return owner.rsplit(".", 1)[-1]


def ipc_state_assignments(source: str) -> list[tuple[str, str]]:
    tree = ast.parse(source)
    owner = _owners(tree)
    return sorted(
        (
            _leaf(owner[id(node)]),
            ast.unparse(node.value) if node.value is not None else "",
        )
        for node in _assignments(tree)
        if _assigns_attribute(node, "_state")
    )


def _is_ipc_state_value(value: ast.expr | None) -> bool:
    return (
        isinstance(value, ast.Attribute)
        and isinstance(value.value, ast.Name)
        and value.value.id == "IPCServerState"
    )


def ipc_state_values_elsewhere(sources: dict[str, str]) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for path, source in sources.items():
        if path == _IPC_SERVER:
            continue
        tree = ast.parse(source)
        for node in _assignments(tree):
            if _is_ipc_state_value(node.value):
                found.append((path, ast.unparse(node)))
    return sorted(found)


def _normalized(text: str) -> str:
    return " ".join(text.split()).upper()


def _set_columns(sql: str) -> set[str]:
    match = re.search(r"\bSET\b(.*?)(?:\bWHERE\b|$)", sql)
    if match is None:
        return set()
    return {
        item.split("=", 1)[0].strip()
        for item in match.group(1).split(",")
        if "=" in item
    }


def _sql_constants(sources: dict[str, str]) -> list[tuple[str, str, str]]:
    found: list[tuple[str, str, str]] = []
    for path, source in sources.items():
        tree = ast.parse(source)
        owner = _owners(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                found.append((path, owner[id(node)], _normalized(node.value)))
    return found


def report_status_updates(sources: dict[str, str]) -> list[tuple[str, str]]:
    return sorted(
        (path, owner)
        for path, owner, sql in _sql_constants(sources)
        if _UPDATE_REPORTS.search(sql) and "STATUS" in _set_columns(sql)
    )


def report_inserts(sources: dict[str, str]) -> list[tuple[str, str]]:
    return sorted(
        (path, owner)
        for path, owner, sql in _sql_constants(sources)
        if _INSERT_REPORTS.search(sql)
    )


def upsert_draft_update_columns(sources: dict[str, str]) -> list[set[str]]:
    return [
        _set_columns(sql)
        for path, owner, sql in _sql_constants(sources)
        if path == _REPORT_STORE
        and owner == "ReportStore.upsert_draft"
        and _UPDATE_REPORTS.search(sql)
    ]


def _strategy_report_calls(tree: ast.Module) -> list[ast.Call]:
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Name) and node.func.id == "StrategyReport")
            or (
                isinstance(node.func, ast.Attribute)
                and node.func.attr == "StrategyReport"
            )
        )
    ]


def constructor_status_keywords(
    sources: dict[str, str],
) -> list[tuple[str, str, str]]:
    found: list[tuple[str, str, str]] = []
    for path, source in sources.items():
        tree = ast.parse(source)
        owner = _owners(tree)
        for call in _strategy_report_calls(tree):
            for kw in call.keywords:
                if kw.arg == "status":
                    found.append((path, owner[id(call)], ast.unparse(kw.value)))
    return sorted(found)


def constructor_double_star(sources: dict[str, str]) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for path, source in sources.items():
        tree = ast.parse(source)
        for call in _strategy_report_calls(tree):
            if any(kw.arg is None for kw in call.keywords):
                found.append((path, ast.unparse(call)))
    return sorted(found)


def _in_report_scope(path: str) -> bool:
    return path.startswith("src/ante/report/") or path == _REPORT_CLI


def report_status_attribute_assignments(
    sources: dict[str, str],
) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for path, source in sources.items():
        if not _in_report_scope(path):
            continue
        tree = ast.parse(source)
        for node in _assignments(tree):
            if _assigns_attribute(node, "status"):
                found.append((path, ast.unparse(node)))
    return sorted(found)


# ── 실제 트리 ────────────────────────────────────────────────────


def test_ipc_state_is_assigned_only_at_known_sites():
    sources = _real_sources()
    assert ipc_state_assignments(sources[_IPC_SERVER]) == EXPECTED_IPC_STATE_ASSIGNMENTS


def test_ipc_state_values_are_not_assigned_elsewhere():
    assert ipc_state_values_elsewhere(_real_sources()) == []


def test_report_status_is_updated_only_in_update_status():
    assert report_status_updates(_real_sources()) == EXPECTED_STATUS_UPDATES


def test_reports_are_inserted_only_in_submit():
    assert report_inserts(_real_sources()) == EXPECTED_INSERTS


def test_upsert_draft_update_does_not_set_status():
    columns = upsert_draft_update_columns(_real_sources())
    assert len(columns) == 1
    assert "STATUS" not in columns[0]
    assert "DETAIL_JSON" in columns[0]


def test_strategy_report_status_keyword_only_in_known_constructors():
    assert constructor_status_keywords(_real_sources()) == EXPECTED_CONSTRUCTOR_STATUS


def test_strategy_report_has_no_double_star_arguments():
    assert constructor_double_star(_real_sources()) == []


def test_report_status_attribute_is_never_assigned():
    assert report_status_attribute_assignments(_real_sources()) == []


# ── 대조군 ───────────────────────────────────────────────────────


def _replace_once(source: str, old: str, new: str) -> str:
    assert source.count(old) == 1, old
    return source.replace(old, new)


def _with(path: str, old: str, new: str) -> dict[str, str]:
    sources = _real_sources()
    sources[path] = _replace_once(sources[path], old, new)
    return sources


def test_control_extra_ipc_state_assignment_is_caught():
    source = _with(
        _IPC_SERVER,
        "        closing = self._closing_server\n",
        "        self._state = IPCServerState.DRAINING\n"
        "        closing = self._closing_server\n",
    )[_IPC_SERVER]
    found = ipc_state_assignments(source)
    assert len(found) == 6
    assert ("drain_connections", "IPCServerState.DRAINING") in found


def test_control_missing_ipc_state_assignment_is_caught():
    source = _with(
        _IPC_SERVER,
        "        self._state = IPCServerState.DRAINING\n",
        "        pass\n",
    )[_IPC_SERVER]
    found = ipc_state_assignments(source)
    assert len(found) == 4
    assert found != EXPECTED_IPC_STATE_ASSIGNMENTS


def test_control_changed_ipc_state_value_is_caught():
    source = _with(
        _IPC_SERVER,
        "        self._state = IPCServerState.STOPPED\n        logger.info(",
        "        self._state = IPCServerState.DRAINING\n        logger.info(",
    )[_IPC_SERVER]
    assert ("unlink_socket", "IPCServerState.DRAINING") in ipc_state_assignments(source)


def test_control_tuple_ipc_state_assignment_is_caught():
    source = _with(
        _IPC_SERVER,
        "        closing = self._closing_server\n",
        "        self._state, x = IPCServerState.DRAINING, 1\n"
        "        closing = self._closing_server\n",
    )[_IPC_SERVER]
    assert len(ipc_state_assignments(source)) == 6


def test_control_ipc_state_value_elsewhere_is_caught():
    sources = _with(
        _REPORT_DRAFT,
        "class ReportDraftGenerator:\n",
        "_FAKE = IPCServerState.STOPPED\n\n\nclass ReportDraftGenerator:\n",
    )
    assert ipc_state_values_elsewhere(sources) == [
        (_REPORT_DRAFT, "_FAKE = IPCServerState.STOPPED")
    ]


def test_control_extra_status_update_is_caught():
    sources = _with(
        _REPORT_STORE,
        '            "DELETE FROM reports WHERE report_id = ?",\n',
        '            "UPDATE reports SET user_notes = ?, status = ? '
        'WHERE report_id = ?",\n',
    )
    assert report_status_updates(sources) == [
        (_REPORT_STORE, "ReportStore.delete"),
        (_REPORT_STORE, "ReportStore.update_status"),
    ]


def test_control_missing_status_update_is_caught():
    sources = _with(
        _REPORT_STORE,
        "               SET status = ?, user_notes = ?, reviewed_at = ?\n",
        "               SET user_notes = ?, reviewed_at = ?\n",
    )
    assert report_status_updates(sources) == []


def test_control_extra_insert_is_caught():
    sources = _with(
        _REPORT_STORE,
        '            "DELETE FROM reports WHERE report_id = ?",\n',
        '            "INSERT OR REPLACE INTO reports (report_id) VALUES (?)",\n',
    )
    assert report_inserts(sources) == [
        (_REPORT_STORE, "ReportStore.delete"),
        (_REPORT_STORE, "ReportStore.submit"),
    ]


def test_control_missing_insert_is_caught():
    sources = _with(
        _REPORT_STORE,
        '            """INSERT INTO reports\n',
        '            """INSERT INTO reports_copy\n',
    )
    assert report_inserts(sources) == []


def test_control_status_in_upsert_draft_update_is_caught():
    sources = _with(
        _REPORT_STORE,
        "                   SET strategy_version = ?, strategy_path = ?,\n",
        "                   SET strategy_version = ?, strategy_path = ?, status = ?,\n",
    )
    columns = upsert_draft_update_columns(sources)
    assert len(columns) == 1
    assert "STATUS" in columns[0]
    assert report_status_updates(sources) == [
        (_REPORT_STORE, "ReportStore.update_status"),
        (_REPORT_STORE, "ReportStore.upsert_draft"),
    ]


def test_control_extra_constructor_status_is_caught():
    sources = _with(
        _REPORT_STORE,
        '            "DELETE FROM reports WHERE report_id = ?",\n',
        '            "DELETE FROM reports WHERE report_id = ?",\n'
        "            StrategyReport(status=ReportStatus.ADOPTED),\n",
    )
    found = constructor_status_keywords(sources)
    assert len(found) == 4
    assert (_REPORT_STORE, "ReportStore.delete", "ReportStatus.ADOPTED") in found


def test_control_missing_constructor_status_is_caught():
    sources = _with(
        _REPORT_DRAFT,
        "            status=ReportStatus.DRAFT,\n",
        "",
    )
    assert len(constructor_status_keywords(sources)) == 2


def test_control_double_star_constructor_is_caught():
    sources = _with(
        _REPORT_DRAFT,
        "            status=ReportStatus.DRAFT,\n",
        "            status=ReportStatus.DRAFT,\n            **extra,\n",
    )
    assert len(constructor_double_star(sources)) == 1


def test_control_status_attribute_assignment_is_caught():
    sources = _with(
        _REPORT_STORE,
        '            "DELETE FROM reports WHERE report_id = ?",\n'
        "            (report_id,),\n"
        "        )\n",
        '            "DELETE FROM reports WHERE report_id = ?",\n'
        "            (report_id,),\n"
        "        )\n"
        "        report.status = ReportStatus.ARCHIVED\n",
    )
    assert report_status_attribute_assignments(sources) == [
        (_REPORT_STORE, "report.status = ReportStatus.ARCHIVED")
    ]
