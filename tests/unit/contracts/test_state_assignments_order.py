"""주문 추적기 상태를 쓰는 자리가 표에 묶였는지 잠그는 구조 테스트 (#2707).

**상태 리터럴**: ``src/ante/trade/order_tracker.py`` 의 문자열 상수
(``ast.Constant``. 모듈·클래스·함수 본문 첫 문의 독스트링은 빼고, ``JoinedStr``
의 조각은 넣는다) 가운데 값이 7개 상태 문자열 중 하나와 정확히 같은 것은 7개이고
모두 ``OrderStatus`` 클래스 본문의 멤버 대입 값이다. 작은따옴표로 감싼 상태
문자열(``'open'`` 등)을 담은 상수는 ``ORDER_TRACKER_SCHEMA`` 의 ``DEFAULT 'open'``
하나뿐이다.

**상태를 쓰는 SQL**: ``src/ante`` 의 문자열 상수를 공백을 정규화하고 대문자로
바꿔 읽는다. ``UPDATE order_tracker`` 를 담고 ``SET`` 절(``SET`` 과 ``WHERE``
사이, 쉼표로 나눈 각 항의 ``=`` 왼쪽)에 ``status`` 가 있는 것은
``record_fill``·``mark_terminal``·``expire_stale`` 안의 3개뿐이고, 셋 다
``status`` 항의 오른쪽이 ``?`` 다. ``INSERT [OR …] INTO order_tracker``·
``REPLACE INTO order_tracker`` 를 담은 것은 ``open`` 안의 1개뿐이다.

**레코드 생성자**: ``src/ante`` 전체에서 ``OrderTrackerRecord(...)`` 호출과
``OrderTrackerRecord`` 클래스 본문 안의 ``cls(...)`` 호출의 ``status=`` 키워드는
3개이고 (둘러싼 함수, 값의 ``ast.unparse``)가 리터럴 목록과 같다.

**고정된 바깥 리터럴**: ``gateway/gateway.py`` 의 ``_on_order_modify`` 와
``main.py`` 의 ``_subscribe_order_tracker`` (중첩 함수 포함)에서 값이 상태
문자열인 상수의 다중집합이 리터럴 목록과 같고, 그 값은 ``OrderStatus`` 의 값이다.

뒤쪽 대조군은 목록마다 실제 소스에 자리를 하나 더하거나 빼서 판정이 달라지는지
본다.

알려진 한계: 위 두 함수 밖의 다른 파일에 있는 같은 문자열(「어휘의 경계」의
다른 개념과 구분할 수 없다), ``tests/`` 안의 리터럴, DDL의 기본값, 상태를 읽는
SQL은 세지 않는다. 다음도 세지 않는다.

- f-string(``JoinedStr``)·``+`` 로 만든 쓰기 SQL
- ``UPDATE OR <conflict> order_tracker``
- ``SET`` 절 파서가 놓치는 쓰기 형태: 행 값 대입(``SET (status, …) = (…)``)과
  따옴표로 감싼 열 이름(``SET "status" = …``)
- ``setattr``·``object.__setattr__``·``dataclasses.replace`` 로 레코드를 바꾸는 것
- 바인딩되는 값이 ``OrderStatus`` 멤버인지(동작 테스트가 본다)
"""

from __future__ import annotations

import ast
import re
from collections import Counter
from pathlib import Path

from ante.trade.order_tracker import OrderStatus

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SRC = _REPO_ROOT / "src" / "ante"
_TRACKER = "src/ante/trade/order_tracker.py"
_GATEWAY = "src/ante/gateway/gateway.py"
_MAIN = "src/ante/main.py"
_APPLIER = "src/ante/trade/fill_applier.py"

_STATUS_VALUES = {
    "open",
    "partially_filled",
    "filled",
    "cancelled",
    "rejected",
    "failed",
    "expired",
}
_QUOTED = re.compile(r"'([a-z_]+)'")
_UPDATE_TRACKER = re.compile(r"\bUPDATE\s+ORDER_TRACKER\b")
_INSERT_TRACKER = re.compile(
    r"\b(?:INSERT(?:\s+OR\s+\w+)?|REPLACE)\s+INTO\s+ORDER_TRACKER\b"
)

EXPECTED_STATUS_LITERALS = [
    ("OrderStatus.CANCELLED", "cancelled"),
    ("OrderStatus.EXPIRED", "expired"),
    ("OrderStatus.FAILED", "failed"),
    ("OrderStatus.FILLED", "filled"),
    ("OrderStatus.OPEN", "open"),
    ("OrderStatus.PARTIALLY_FILLED", "partially_filled"),
    ("OrderStatus.REJECTED", "rejected"),
]

EXPECTED_QUOTED_LITERALS = [("ORDER_TRACKER_SCHEMA", "'open'")]

EXPECTED_STATUS_UPDATES = [
    (_TRACKER, "OrderTracker.expire_stale"),
    (_TRACKER, "OrderTracker.mark_terminal"),
    (_TRACKER, "OrderTracker.record_fill"),
]

EXPECTED_INSERTS = [(_TRACKER, "OrderTracker.open")]

EXPECTED_RECORD_STATUS_KEYWORDS = [
    (_TRACKER, "from_row", "row['status']"),
    (_TRACKER, "mirror_fill_to_cache", "new_status or record.status"),
    (_TRACKER, "open", "OrderStatus.OPEN.value"),
]

EXPECTED_OUTER_LITERALS = {
    (_GATEWAY, "_on_order_modify"): Counter({"open": 1}),
    (_MAIN, "_subscribe_order_tracker"): Counter(
        {"cancelled": 1, "rejected": 1, "failed": 1}
    ),
}


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


def _docstrings(tree: ast.Module) -> set[int]:
    found: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(
            node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef
        ):
            first = node.body[0] if node.body else None
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                found.add(id(first.value))
    return found


def _string_constants(tree: ast.Module) -> list[ast.Constant]:
    docs = _docstrings(tree)
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docs
    ]


def _order_status_member_values(tree: ast.Module) -> dict[int, str]:
    found: dict[int, str] = {}
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "OrderStatus":
            for stmt in node.body:
                if (
                    isinstance(stmt, ast.Assign)
                    and isinstance(stmt.value, ast.Constant)
                    and len(stmt.targets) == 1
                    and isinstance(stmt.targets[0], ast.Name)
                ):
                    found[id(stmt.value)] = f"OrderStatus.{stmt.targets[0].id}"
    return found


def status_literals(sources: dict[str, str]) -> list[tuple[str, str]]:
    tree = ast.parse(sources[_TRACKER])
    owner = _owners(tree)
    members = _order_status_member_values(tree)
    found: list[tuple[str, str]] = []
    for node in _string_constants(tree):
        if node.value in _STATUS_VALUES:
            where = members.get(id(node), owner[id(node)])
            found.append((where, node.value))
    return sorted(found)


def _module_assign_names(tree: ast.Module) -> dict[int, str]:
    names: dict[int, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names[id(node.value)] = target.id
    return names


def quoted_literals(sources: dict[str, str]) -> list[tuple[str, str]]:
    tree = ast.parse(sources[_TRACKER])
    owner = _owners(tree)
    assigned = _module_assign_names(tree)
    found: list[tuple[str, str]] = []
    for node in _string_constants(tree):
        for word in _QUOTED.findall(node.value):
            if word in _STATUS_VALUES:
                where = assigned.get(id(node), owner[id(node)])
                found.append((where, f"'{word}'"))
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
        if _UPDATE_TRACKER.search(sql) and "STATUS" in _set_terms(sql)
    )


def status_updates(sources: dict[str, str]) -> list[tuple[str, str]]:
    return [(path, owner) for path, owner, _ in _status_update_sql(sources)]


def status_update_values(sources: dict[str, str]) -> list[str]:
    return [_set_terms(sql)["STATUS"] for _, _, sql in _status_update_sql(sources)]


def tracker_inserts(sources: dict[str, str]) -> list[tuple[str, str]]:
    return sorted(
        (path, owner)
        for path, owner, sql in _sql_constants(sources)
        if _INSERT_TRACKER.search(sql)
    )


def _is_record_call(node: ast.Call, owner: str) -> bool:
    func = node.func
    if isinstance(func, ast.Name) and func.id == "OrderTrackerRecord":
        return True
    if isinstance(func, ast.Attribute) and func.attr == "OrderTrackerRecord":
        return True
    return (
        isinstance(func, ast.Name)
        and func.id == "cls"
        and owner.split(".")[0] == "OrderTrackerRecord"
    )


def record_status_keywords(sources: dict[str, str]) -> list[tuple[str, str, str]]:
    found: list[tuple[str, str, str]] = []
    for path, source in sources.items():
        tree = ast.parse(source)
        owner = _owners(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _is_record_call(node, owner[id(node)]):
                for keyword in node.keywords:
                    if keyword.arg == "status":
                        found.append(
                            (path, _leaf(owner[id(node)]), ast.unparse(keyword.value))
                        )
    return sorted(found)


def outer_literals(
    sources: dict[str, str],
) -> dict[tuple[str, str], Counter[str]]:
    found: dict[tuple[str, str], Counter[str]] = {}
    for path, func_name in EXPECTED_OUTER_LITERALS:
        tree = ast.parse(sources[path])
        counter: Counter[str] = Counter()
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
                and node.name == func_name
            ):
                for inner in ast.walk(node):
                    if (
                        isinstance(inner, ast.Constant)
                        and isinstance(inner.value, str)
                        and inner.value in _STATUS_VALUES
                    ):
                        counter[inner.value] += 1
        found[(path, func_name)] = counter
    return found


# ── 실제 트리 ────────────────────────────────────────────────────


def test_status_literals_are_only_order_status_members():
    assert status_literals(_real_sources()) == EXPECTED_STATUS_LITERALS


def test_quoted_status_literal_is_only_the_schema_default():
    assert quoted_literals(_real_sources()) == EXPECTED_QUOTED_LITERALS


def test_status_is_updated_only_in_three_methods_with_a_parameter():
    sources = _real_sources()
    assert status_updates(sources) == EXPECTED_STATUS_UPDATES
    assert status_update_values(sources) == ["?", "?", "?"]


def test_order_tracker_is_inserted_only_in_open():
    assert tracker_inserts(_real_sources()) == EXPECTED_INSERTS


def test_record_status_keywords_are_known_sites():
    assert record_status_keywords(_real_sources()) == EXPECTED_RECORD_STATUS_KEYWORDS


def test_outer_status_literals_are_fixed():
    found = outer_literals(_real_sources())
    assert found == EXPECTED_OUTER_LITERALS
    values = {value for counter in found.values() for value in counter}
    assert values <= {member.value for member in OrderStatus}


# ── 대조군 ───────────────────────────────────────────────────────


def _replace_once(source: str, old: str, new: str) -> str:
    assert source.count(old) == 1, old
    return source.replace(old, new)


def _with(path: str, old: str, new: str) -> dict[str, str]:
    sources = _real_sources()
    sources[path] = _replace_once(sources[path], old, new)
    return sources


def test_control_extra_status_literal_is_caught():
    sources = _with(
        _TRACKER,
        "            if new_status == OrderStatus.FILLED or",
        '            if new_status == "filled" or',
    )
    found = status_literals(sources)
    assert len(found) == 8
    assert ("OrderTracker.mirror_fill_to_cache", "filled") in found


def test_control_status_literal_in_f_string_is_caught():
    sources = _with(
        _TRACKER,
        'raise ValueError(f"비-terminal status: {status!r}")',
        'raise ValueError(f"비-terminal status: {status!r}{"open"}")',
    )
    assert ("OrderTracker.mark_terminal", "open") in status_literals(sources)


def test_control_missing_status_member_is_caught():
    sources = _with(_TRACKER, '    EXPIRED = "expired"\n', "")
    assert len(status_literals(sources)) == 6


def test_control_extra_quoted_literal_is_caught():
    sources = _with(
        _TRACKER,
        "                   SET status = ?, terminal_at = ?\n"
        "                 WHERE account_id = ?",
        "                   SET status = 'expired', terminal_at = ?\n"
        "                 WHERE account_id = ?",
    )
    assert quoted_literals(sources) == [
        ("ORDER_TRACKER_SCHEMA", "'open'"),
        ("OrderTracker.expire_stale", "'expired'"),
    ]
    assert status_update_values(sources) == ["'EXPIRED'", "?", "?"]


def test_control_missing_quoted_literal_is_caught():
    sources = _with(
        _TRACKER,
        "    status              TEXT NOT NULL DEFAULT 'open',\n",
        "    status              TEXT NOT NULL,\n",
    )
    assert quoted_literals(sources) == []


def test_control_extra_status_update_in_another_file_is_caught():
    sources = _with(
        _APPLIER,
        "logger = logging.getLogger(__name__)\n",
        "logger = logging.getLogger(__name__)\n"
        '_SQL = "update  order_tracker set last_polled_at = ?,status = ?"\n',
    )
    assert status_updates(sources) == [
        (_APPLIER, "<module>"),
        (_TRACKER, "OrderTracker.expire_stale"),
        (_TRACKER, "OrderTracker.mark_terminal"),
        (_TRACKER, "OrderTracker.record_fill"),
    ]
    assert status_update_values(sources) == ["?", "?", "?", "?"]


def test_control_missing_status_update_is_caught():
    sources = _with(
        _TRACKER,
        "                  SET status = ?, terminal_at = ?\n"
        "                WHERE order_id = ?",
        "                  SET terminal_at = ?\n                WHERE order_id = ?",
    )
    assert status_updates(sources) == [
        (_TRACKER, "OrderTracker.expire_stale"),
        (_TRACKER, "OrderTracker.record_fill"),
    ]


def test_control_extra_insert_is_caught():
    sources = _with(
        _APPLIER,
        "logger = logging.getLogger(__name__)\n",
        "logger = logging.getLogger(__name__)\n"
        '_SQL = "INSERT OR REPLACE INTO order_tracker (order_id) VALUES (?)"\n',
    )
    assert tracker_inserts(sources) == [
        (_APPLIER, "<module>"),
        (_TRACKER, "OrderTracker.open"),
    ]


def test_control_missing_insert_is_caught():
    sources = _with(
        _TRACKER,
        '            """INSERT INTO order_tracker\n',
        '            """INSERT INTO order_tracker_copy\n',
    )
    assert tracker_inserts(sources) == []


def test_control_extra_record_status_keyword_is_caught():
    sources = _with(
        _APPLIER,
        "        assert isinstance(record, OrderTrackerRecord)\n"
        '        fill_dedup_key = ""\n',
        "        assert isinstance(record, OrderTrackerRecord)\n"
        "        OrderTrackerRecord(status=result.new_status)\n"
        '        fill_dedup_key = ""\n',
    )
    found = record_status_keywords(sources)
    assert len(found) == 4
    assert (_APPLIER, "_apply_locked", "result.new_status") in found


def test_control_extra_cls_status_keyword_is_caught():
    sources = _with(
        _TRACKER,
        "        remaining = self.ordered_qty - self.recorded_filled_qty\n",
        "        remaining = self.ordered_qty - self.recorded_filled_qty\n"
        '        cls(status="x")\n',
    )
    found = record_status_keywords(sources)
    assert (_TRACKER, "to_open_order_dict", "'x'") in found


def test_control_missing_record_status_keyword_is_caught():
    sources = _with(
        _TRACKER,
        "                status=new_status or record.status,\n",
        "",
    )
    assert len(record_status_keywords(sources)) == 2


def test_control_extra_outer_literal_is_caught():
    sources = _with(
        _MAIN,
        "        else:\n            return\n        if not event.order_id:\n",
        "        else:\n            status = 'expired'\n"
        "        if not event.order_id:\n",
    )
    assert outer_literals(sources)[(_MAIN, "_subscribe_order_tracker")] == Counter(
        {"cancelled": 1, "rejected": 1, "failed": 1, "expired": 1}
    )


def test_control_missing_outer_literal_is_caught():
    sources = _with(
        _GATEWAY,
        'record.status != "open"',
        "record.status != OPEN",
    )
    assert outer_literals(sources)[(_GATEWAY, "_on_order_modify")] == Counter()
