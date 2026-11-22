"""봇 상태를 쓰는 자리가 전이 함수로 모였는지 잠그는 구조 테스트 (#2699).

**상태 대입**: ``src/ante/bot/bot.py``·``src/ante/bot/manager.py`` 에서 대상이
``.status`` 속성인 ``Assign``/``AnnAssign``/``AugAssign`` (대상은 튜플·리스트·
``Starred`` 안까지 펼친다)의 (파일, 둘러싼 함수, 값의 ``ast.unparse``)가 리터럴
목록 4개와 같다. 전이 함수 안의 1개, 생성자의 초기값 1개, 복원(``load_from_db``)
2개다. ``src/ante`` 의 다른 파일에서 대상이 속성이고 값이 ``BotStatus.<멤버>``
이거나 ``BotStatus(...)`` 호출인 대입은 0이다.

**전이 함수**: ``src/ante/bot/`` 안에서 ``_transition_status`` 는 ``bot.py`` 의
모듈 수준 함수 하나다. 그것을 부르는 곳의 (파일, 둘러싼 함수, 둘째 인자)가
리터럴 목록 6개와 같다. 다른 모듈의 같은 이름 함수(계좌·멤버·결재)는 그 모듈의
구조 테스트가 잠근다.

**봇 상태 SQL**: ``src/ante`` 의 문자열 상수를 공백을 정규화하고 대문자로 바꿔
읽는다. ``UPDATE bots`` 를 담고 ``SET`` 절(``SET`` 과 ``WHERE`` 사이, 쉼표로 나눈
각 항의 ``=`` 왼쪽)에 ``status`` 가 있는 것은 ``BotManager.delete_bot`` 과
``cold_path_remove_bot`` 안의 2개뿐이고, 둘 다 ``status`` 항의 오른쪽이 ``?``
다. ``INSERT [OR …] INTO bots``·``REPLACE INTO bots`` 를 담은 것은
``BotManager._save_bot_config`` 안의 1개뿐이고, 열 목록과 ``DO UPDATE SET`` 절에
``status`` 가 없다.

뒤쪽 대조군은 목록마다 실제 소스에 자리를 하나 더하거나 빼서 판정이 달라지는지
본다.

알려진 한계: ``setattr``, ``__dict__`` 쓰기, ``tests/`` 안의 ``status`` 직접
대입(여러 테스트가 픽스처로 쓴다), 테이블 기본값(``DEFAULT 'created'``), 상태
리터럴을 읽는 SQL, ``DELETE FROM bots`` (행 삭제)는 세지 않는다. 다음도 세지
않는다.

- f-string(``JoinedStr``)·``+`` 로 만든 SQL
- ``UPDATE OR <conflict> bots``
- ``SET`` 안의 서브쿼리와 행 값 대입(``SET (a, status) = …``)
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SRC = _REPO_ROOT / "src" / "ante"
_BOT = "src/ante/bot/bot.py"
_MANAGER = "src/ante/bot/manager.py"
_COLD_PATH = "src/ante/bot/cold_path.py"
_RECONCILE = "src/ante/bot/reconcile_scheduler.py"
_BOT_PACKAGE = "src/ante/bot/"
_TRANSITION_FUNC = "_transition_status"

_UPDATE_BOTS = re.compile(r"\bUPDATE\s+BOTS\b")
_INSERT_BOTS = re.compile(r"\b(?:INSERT(?:\s+OR\s+\w+)?|REPLACE)\s+INTO\s+BOTS\b")

EXPECTED_STATUS_ASSIGNMENTS = [
    (_BOT, "__init__", "BotStatus.CREATED"),
    (_BOT, "_transition_status", "target"),
    (_MANAGER, "load_from_db", "BotStatus(status_str)"),
    (_MANAGER, "load_from_db", "BotStatus.CREATED"),
]

EXPECTED_TRANSITION_CALLS = [
    (_BOT, "_run_loop", "BotStatus.ERROR"),
    (_BOT, "_run_loop", "BotStatus.ERROR"),
    (_BOT, "start", "BotStatus.RUNNING"),
    (_BOT, "stop", "BotStatus.STOPPED"),
    (_BOT, "stop", "BotStatus.STOPPING"),
    (_MANAGER, "delete_bot", "BotStatus.DELETED"),
]

EXPECTED_STATUS_UPDATES = [
    (_COLD_PATH, "cold_path_remove_bot"),
    (_MANAGER, "BotManager.delete_bot"),
]

EXPECTED_INSERTS = [(_MANAGER, "BotManager._save_bot_config")]


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


def _leaf(owner: str) -> str:
    return owner.rsplit(".", 1)[-1]


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
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign | ast.AnnAssign | ast.AugAssign)
    ]


def _targets(node: ast.Assign | ast.AnnAssign | ast.AugAssign) -> list[ast.expr]:
    raw = node.targets if isinstance(node, ast.Assign) else [node.target]
    return [t for target in raw for t in _flatten_targets(target)]


def status_assignments(sources: dict[str, str]) -> list[tuple[str, str, str]]:
    found: list[tuple[str, str, str]] = []
    for path in (_BOT, _MANAGER):
        tree = ast.parse(sources[path])
        owner = _owners(tree)
        for node in _assignments(tree):
            if any(
                isinstance(t, ast.Attribute) and t.attr == "status"
                for t in _targets(node)
            ):
                value = ast.unparse(node.value) if node.value is not None else ""
                found.append((path, _leaf(owner[id(node)]), value))
    return sorted(found)


def _is_bot_status_value(value: ast.expr | None) -> bool:
    if isinstance(value, ast.Call):
        value = value.func
        return isinstance(value, ast.Name) and value.id == "BotStatus"
    return (
        isinstance(value, ast.Attribute)
        and isinstance(value.value, ast.Name)
        and value.value.id == "BotStatus"
    )


def bot_status_values_elsewhere(sources: dict[str, str]) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for path, source in sources.items():
        if path in (_BOT, _MANAGER):
            continue
        tree = ast.parse(source)
        for node in _assignments(tree):
            if any(isinstance(t, ast.Attribute) for t in _targets(node)) and (
                _is_bot_status_value(node.value)
            ):
                found.append((path, ast.unparse(node)))
    return sorted(found)


def _callee_name(call: ast.Call) -> str:
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ast.unparse(func)


def _bot_module_sources(sources: dict[str, str]) -> dict[str, str]:
    return {p: s for p, s in sources.items() if p.startswith(_BOT_PACKAGE)}


def transition_calls(sources: dict[str, str]) -> list[tuple[str, str, str]]:
    found: list[tuple[str, str, str]] = []
    for path, source in _bot_module_sources(sources).items():
        tree = ast.parse(source)
        owner = _owners(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _callee_name(node) == _TRANSITION_FUNC:
                second = ast.unparse(node.args[1]) if len(node.args) > 1 else ""
                found.append((path, _leaf(owner[id(node)]), second))
    return sorted(found)


def transition_function_definitions(sources: dict[str, str]) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for path, source in _bot_module_sources(sources).items():
        tree = ast.parse(source)
        owner = _owners(tree)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
                and node.name == _TRANSITION_FUNC
            ):
                found.append((path, owner[id(node)]))
    return sorted(found)


def _normalized(text: str) -> str:
    return " ".join(text.split()).upper()


def _set_terms(sql: str) -> dict[str, str]:
    match = re.search(r"\bSET\b(.*?)(?:\bWHERE\b|$)", sql)
    if match is None:
        return {}
    terms: dict[str, str] = {}
    for item in match.group(1).split(","):
        if "=" in item:
            left, right = item.split("=", 1)
            terms[left.strip()] = right.strip()
    return terms


def _sql_constants(sources: dict[str, str]) -> list[tuple[str, str, str]]:
    found: list[tuple[str, str, str]] = []
    for path, source in sources.items():
        tree = ast.parse(source)
        owner = _owners(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                found.append((path, owner[id(node)], _normalized(node.value)))
    return found


def _status_update_sql(sources: dict[str, str]) -> list[tuple[str, str, str]]:
    return sorted(
        (path, owner, sql)
        for path, owner, sql in _sql_constants(sources)
        if _UPDATE_BOTS.search(sql) and "STATUS" in _set_terms(sql)
    )


def status_updates(sources: dict[str, str]) -> list[tuple[str, str]]:
    return [(path, owner) for path, owner, _ in _status_update_sql(sources)]


def status_update_values(sources: dict[str, str]) -> list[str]:
    return [_set_terms(sql)["STATUS"] for _, _, sql in _status_update_sql(sources)]


def _insert_sql(sources: dict[str, str]) -> list[tuple[str, str, str]]:
    return sorted(
        (path, owner, sql)
        for path, owner, sql in _sql_constants(sources)
        if _INSERT_BOTS.search(sql)
    )


def bot_inserts(sources: dict[str, str]) -> list[tuple[str, str]]:
    return [(path, owner) for path, owner, _ in _insert_sql(sources)]


def insert_columns(sources: dict[str, str]) -> list[tuple[set[str], set[str]]]:
    found: list[tuple[set[str], set[str]]] = []
    for _, _, sql in _insert_sql(sources):
        listed = re.search(r"\bINTO\s+BOTS\s*\(([^)]*)\)", sql)
        columns = {c.strip() for c in listed.group(1).split(",")} if listed else set()
        found.append((columns, set(_set_terms(sql))))
    return found


# ── 실제 트리 ────────────────────────────────────────────────────


def test_transition_function_is_one_module_level_function_in_bot_py():
    assert transition_function_definitions(_real_sources()) == [(_BOT, "<module>")]


def test_status_is_assigned_only_at_known_sites():
    assert status_assignments(_real_sources()) == EXPECTED_STATUS_ASSIGNMENTS


def test_bot_status_values_are_not_assigned_elsewhere():
    assert bot_status_values_elsewhere(_real_sources()) == []


def test_transition_function_call_sites():
    assert transition_calls(_real_sources()) == EXPECTED_TRANSITION_CALLS


def test_bot_status_is_updated_only_in_delete_paths_with_a_parameter():
    sources = _real_sources()
    assert status_updates(sources) == EXPECTED_STATUS_UPDATES
    assert status_update_values(sources) == ["?", "?"]


def test_bots_are_inserted_only_in_save_bot_config_without_status():
    sources = _real_sources()
    assert bot_inserts(sources) == EXPECTED_INSERTS
    ((columns, update_columns),) = insert_columns(sources)
    assert columns == {"BOT_ID", "NAME", "STRATEGY_ID", "ACCOUNT_ID", "CONFIG_JSON"}
    assert "STATUS" not in update_columns
    assert "CONFIG_JSON" in update_columns


# ── 대조군 ───────────────────────────────────────────────────────


def _replace_once(source: str, old: str, new: str) -> str:
    assert source.count(old) == 1, old
    return source.replace(old, new)


def _with(path: str, old: str, new: str) -> dict[str, str]:
    sources = _real_sources()
    sources[path] = _replace_once(sources[path], old, new)
    return sources


def test_control_extra_status_assignment_is_caught():
    sources = _with(
        _MANAGER,
        "        deleted = _transition_status(bot, BotStatus.DELETED)\n",
        "        deleted = _transition_status(bot, BotStatus.DELETED)\n"
        "        bot.status = BotStatus.DELETED\n",
    )
    found = status_assignments(sources)
    assert len(found) == 5
    assert (_MANAGER, "delete_bot", "BotStatus.DELETED") in found


def test_control_tuple_status_assignment_is_caught():
    sources = _with(
        _BOT,
        "        self._orders_closed = True\n\n        if self._task",
        "        self.status, x = BotStatus.STOPPING, 1\n"
        "        self._orders_closed = True\n\n        if self._task",
    )
    assert (_BOT, "stop", "(BotStatus.STOPPING, 1)") in status_assignments(sources)


def test_control_missing_status_assignment_is_caught():
    sources = _with(
        _MANAGER,
        "                bot.status = BotStatus.CREATED\n",
        "                pass\n",
    )
    assert len(status_assignments(sources)) == 3


def test_control_bot_status_value_elsewhere_is_caught():
    sources = _with(
        _RECONCILE,
        "logger = logging.getLogger(__name__)\n",
        "logger = logging.getLogger(__name__)\n"
        "logger.status = BotStatus.STOPPED\n"
        "logger.restored = BotStatus('stopped')\n",
    )
    assert bot_status_values_elsewhere(sources) == [
        (_RECONCILE, "logger.restored = BotStatus('stopped')"),
        (_RECONCILE, "logger.status = BotStatus.STOPPED"),
    ]


def test_control_extra_transition_call_is_caught():
    sources = _with(
        _MANAGER,
        "        bot = self._get_bot(bot_id)\n"
        "        if bot.status == BotStatus.RUNNING:\n"
        "            raise BotStateConflict(\n",
        "        bot = self._get_bot(bot_id)\n"
        "        _transition_status(bot, BotStatus.RUNNING)\n"
        "        if bot.status == BotStatus.RUNNING:\n"
        "            raise BotStateConflict(\n",
    )
    found = transition_calls(sources)
    assert len(found) == 7
    assert (_MANAGER, "start_bot", "BotStatus.RUNNING") in found


def test_control_missing_transition_call_is_caught():
    sources = _with(
        _BOT,
        "        _transition_status(self, BotStatus.STOPPED)\n",
        "        self.status = BotStatus.STOPPED\n",
    )
    assert (_BOT, "stop", "BotStatus.STOPPED") not in transition_calls(sources)
    assert len(transition_calls(sources)) == 5
    assert (_BOT, "stop", "BotStatus.STOPPED") in status_assignments(sources)


def test_control_transition_function_as_method_is_caught():
    sources = _with(
        _BOT,
        "    def __init__(\n        self,\n        config: BotConfig,\n",
        "    def _transition_status(self, target: BotStatus) -> None:\n"
        "        pass\n\n"
        "    def __init__(\n        self,\n        config: BotConfig,\n",
    )
    assert transition_function_definitions(sources) == [
        (_BOT, "<module>"),
        (_BOT, "Bot"),
    ]


def test_control_literal_status_update_is_caught():
    sources = _with(
        _COLD_PATH,
        "UPDATE bots SET status = ?, updated_at",
        "UPDATE bots SET status = 'deleted', updated_at",
    )
    assert status_updates(sources) == EXPECTED_STATUS_UPDATES
    assert status_update_values(sources) == ["'DELETED'", "?"]


def test_control_extra_status_update_is_caught():
    sources = _with(
        _MANAGER,
        '                "DELETE FROM bots WHERE bot_id = ?",\n',
        '                "update   bots set name = ?,status = ? WHERE bot_id = ?",\n',
    )
    assert status_updates(sources) == [
        (_COLD_PATH, "cold_path_remove_bot"),
        (_MANAGER, "BotManager.delete_bot"),
        (_MANAGER, "BotManager.delete_bot"),
    ]


def test_control_missing_status_update_is_caught():
    sources = _with(
        _COLD_PATH,
        "UPDATE bots SET status = ?, updated_at",
        "UPDATE bots SET updated_at",
    )
    assert status_updates(sources) == [(_MANAGER, "BotManager.delete_bot")]


def test_control_extra_insert_is_caught():
    sources = _with(
        _COLD_PATH,
        '        "SELECT bot_id, account_id, status FROM bots"\n',
        '        "INSERT OR REPLACE INTO bots (bot_id) VALUES (?)"\n'
        '        "SELECT bot_id, account_id, status FROM bots"\n',
    )
    assert bot_inserts(sources) == [
        (_COLD_PATH, "cold_path_remove_bot"),
        (_MANAGER, "BotManager._save_bot_config"),
    ]


def test_control_missing_insert_is_caught():
    sources = _with(
        _MANAGER,
        '            """INSERT INTO bots\n',
        '            """INSERT INTO bots_copy\n',
    )
    assert bot_inserts(sources) == []


def test_control_status_in_insert_columns_is_caught():
    sources = _with(
        _MANAGER,
        "               (bot_id, name, strategy_id, account_id, config_json)\n",
        "               (bot_id, name, strategy_id, account_id, config_json, status)\n",
    )
    ((columns, _),) = insert_columns(sources)
    assert "STATUS" in columns


def test_control_status_in_insert_update_is_caught():
    sources = _with(
        _MANAGER,
        "                 config_json = excluded.config_json,\n",
        "                 config_json = excluded.config_json,\n"
        "                 status = excluded.status,\n",
    )
    ((_, update_columns),) = insert_columns(sources)
    assert "STATUS" in update_columns
