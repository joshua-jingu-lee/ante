"""상태 enum마다 전이표가 있는지 기준선으로 잠그는 구조 불변식 테스트.

**상태 enum**: ``src/ante/**/*.py`` 의 ``ast.ClassDef`` (중첩 포함) 가운데
이름이 ``Status`` 나 ``State`` 로 끝나고, 베이스 중 하나의 이름
(``Name.id`` 또는 ``Attribute.attr``)이 ``Enum`` 으로 끝나는 것이다.
식별자는 ``"<저장소 루트 기준 POSIX 경로>::<클래스 이름>"`` 이고, 같은
식별자가 두 번 나오면 실패한다.

**멤버**: 클래스 본문에 바로 있는 ``Assign`` (대상이 이름 하나) 또는 값이
있는 ``AnnAssign`` (대상이 이름) 가운데 이름이 ``_`` 로 시작하지 않는 것.
``_`` 로 시작하는 이름의 대입은 ``_ignore_``·``_order_`` 만 허용한다(멤버가
아니다).

**전이표**: enum ``E`` 와 같은 파일의 모듈 수준 ``Assign`` (대상 이름 하나)
또는 값이 있는 ``AnnAssign`` 가운데, 값이 ``dict`` 리터럴이고, 키가 모두
``E.<멤버>`` 로 ``E`` 의 멤버를 빠짐없이 중복 없이 덮고, 값이 모두
``E.<멤버>`` 만 담은 ``set`` 리터럴, ``set()``, ``frozenset()``,
``frozenset({E.<멤버>, ...})`` 중 하나인 것. 모든 값이 빈 집합인 표(빈
전이표)도 표로 인정한다. 다음은 「표 없음」이다: 멤버가 0개인 enum, 모듈
본문에 바로 있지 않은 enum, 클래스 본문에 대상이 이름 하나인 ``Assign``,
대상이 이름인 ``AnnAssign``, 데코레이터 없는 ``FunctionDef``·
``AsyncFunctionDef``, 값이 문자열 상수인 ``Expr``, ``Pass`` 밖의 문이 있는
enum, 클래스 본문에 이름이 ``_`` 로 시작하는 대입(``_ignore_``·``_order_``
제외)이 있는 enum, 클래스 머리에 키워드 인자가 있는 enum.

**런타임 대조**: 실제 트리의 모듈 본문에 있고 클래스 본문이 닫힌 상태 enum마다
도출한 멤버 이름 집합이 모듈을 import해 얻은 ``__members__`` 의 이름 집합과
같아야 한다. 사본과 가짜 소스에는 하지 않는다.

**판정**: 실측의 「표 없음」 집합이 :data:`BASELINE_WITHOUT_TABLE` 과 집합으로
같을 때만 통과한다. 표를 단 enum은 같은 변경에서 기준선에서 지운다.

판정은 클래스·대입 노드만 읽고 독스트링과 주석을 쓰지 않는다. 소스를
파싱하지 못하면 ``ast.parse`` 의 예외를 그대로 올린다.

알려진 한계: 표가 있는지만 보고 코드가 그 표를 쓰는지는 보지 않는다. 정의
밖의 표 모양(문자열 키, ``MappingProxyType(...)``, ``frozenset([...])``,
함수 호출로 만든 표, 다른 파일의 표)은 「표 없음」이다. 함수형
``Enum("X", ...)``, ``Flag`` 베이스, 이름이 ``Enum`` 으로 끝나지 않는 사용자
베이스, 이름이 ``Status``·``State`` 로 끝나지 않는 enum은 상태 enum으로
세지 않는다. 별칭(``B = A``)도 멤버로 센다. 정적 판별은 클래스 머리의
키워드와 본문 직속 문까지만 보고, 허용한 문의 하위 표현식 안과 클래스
데코레이터는 보지 않는다.
"""

from __future__ import annotations

import ast
import importlib
import shutil
import sys
import textwrap
from pathlib import Path

import pytest

# tests/unit/contracts/test_state_enum_transition_tables.py
# → parents[3] == repository root.
_REPO_ROOT = Path(__file__).resolve().parents[3]

BASELINE_WITHOUT_TABLE: frozenset[str] = frozenset()

MODEL_ENUM = "src/ante/strategy/registry.py::StrategyStatus"
MODEL_TABLE = "src/ante/strategy/registry.py 의 _ALLOWED_TRANSITIONS"

_STATE_SUFFIXES = ("Status", "State")
_INCREASED = "전이표 없는 상태 enum이 늘었다:"
_STALE = "기준선에 있지만 「표 없음」 상태 enum이 아니다:"
_NOT_TOP_NOTE = "모듈 본문에 바로 있지 않다. 모듈 수준으로 옮긴다"
_OPEN_BODY_NOTE = (
    "클래스 본문에 인정하지 않는 문이나 _로 시작하는 이름의 대입이 있다. "
    "클래스 본문을 이름 하나짜리 대입과 메서드만으로 쓴다"
    "(멤버 이름은 _로 시작하지 않는다)"
)
_ALLOWED_UNDERSCORE_NAMES = frozenset({"_ignore_", "_order_"})


def _base_name(base: ast.expr) -> str:
    if isinstance(base, ast.Name):
        return base.id
    if isinstance(base, ast.Attribute):
        return base.attr
    return ""


def _is_state_enum(cls: ast.ClassDef) -> bool:
    if not cls.name.endswith(_STATE_SUFFIXES):
        return False
    return any(_base_name(base).endswith("Enum") for base in cls.bases)


def find_state_enums(root: Path) -> dict[str, tuple[ast.Module, ast.ClassDef, bool]]:
    """``root / "src" / "ante"`` 의 상태 enum을 식별자로 묶어 돌려준다.

    값은 (모듈, 클래스, 모듈 수준 여부)다. 같은 식별자가 두 번 나오면
    ``AssertionError`` 를 올린다. 파싱 예외는 삼키지 않는다.
    """
    found: dict[str, tuple[ast.Module, ast.ClassDef, bool]] = {}
    for path in sorted((root / "src" / "ante").rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        top_level = {id(stmt) for stmt in module.body}
        rel = path.relative_to(root).as_posix()
        for node in ast.walk(module):
            if not isinstance(node, ast.ClassDef) or not _is_state_enum(node):
                continue
            ident = f"{rel}::{node.name}"
            if ident in found:
                raise AssertionError(
                    f"같은 상태 enum 식별자가 두 번 나온다: {ident}. "
                    "한 파일에 같은 이름의 클래스를 두지 않는다."
                )
            found[ident] = (module, node, id(node) in top_level)
    return found


def enum_members(cls: ast.ClassDef) -> list[str]:
    """클래스 본문에 바로 있는 멤버 이름을 정의 순서로 돌려준다."""
    members: list[str] = []
    for stmt in cls.body:
        if (
            isinstance(stmt, ast.Assign)
            and len(stmt.targets) == 1
            and isinstance(stmt.targets[0], ast.Name)
        ):
            name = stmt.targets[0].id
        elif (
            isinstance(stmt, ast.AnnAssign)
            and stmt.value is not None
            and isinstance(stmt.target, ast.Name)
        ):
            name = stmt.target.id
        else:
            continue
        if not name.startswith("_"):
            members.append(name)
    return members


def _is_closed_name(name: str) -> bool:
    return not name.startswith("_") or name in _ALLOWED_UNDERSCORE_NAMES


def has_closed_body(cls: ast.ClassDef) -> bool:
    """클래스 머리와 본문이 멤버 정의가 셀 수 있는 모양이면 참이다."""
    if cls.keywords:
        return False
    for stmt in cls.body:
        if isinstance(stmt, ast.Assign):
            if len(stmt.targets) != 1 or not isinstance(stmt.targets[0], ast.Name):
                return False
            if not _is_closed_name(stmt.targets[0].id):
                return False
        elif isinstance(stmt, ast.AnnAssign):
            if not isinstance(stmt.target, ast.Name):
                return False
            if stmt.value is not None and not _is_closed_name(stmt.target.id):
                return False
        elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if stmt.decorator_list:
                return False
        elif isinstance(stmt, ast.Expr):
            if not _is_docstring_value(stmt.value):
                return False
        elif not isinstance(stmt, ast.Pass):
            return False
    return True


def _is_docstring_value(value: ast.expr) -> bool:
    return isinstance(value, ast.Constant) and isinstance(value.value, str)


def _is_member_ref(node: ast.expr | None, enum_name: str, members: set[str]) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == enum_name
        and node.attr in members
    )


def _is_member_set(node: ast.expr, enum_name: str, members: set[str]) -> bool:
    return isinstance(node, ast.Set) and all(
        _is_member_ref(elt, enum_name, members) for elt in node.elts
    )


def _is_target_value(node: ast.expr, enum_name: str, members: set[str]) -> bool:
    if _is_member_set(node, enum_name, members):
        return True
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
        return False
    if node.keywords:
        return False
    if node.func.id in ("set", "frozenset") and not node.args:
        return True
    return (
        node.func.id == "frozenset"
        and len(node.args) == 1
        and _is_member_set(node.args[0], enum_name, members)
    )


def _is_table(value: ast.expr, enum_name: str, members: set[str]) -> bool:
    if not isinstance(value, ast.Dict):
        return False
    keys = value.keys
    if not all(_is_member_ref(key, enum_name, members) for key in keys):
        return False
    attrs = [key.attr for key in keys if isinstance(key, ast.Attribute)]
    if len(attrs) != len(set(attrs)) or set(attrs) != members:
        return False
    return all(_is_target_value(v, enum_name, members) for v in value.values)


def has_transition_table(
    module: ast.Module, enum_name: str, members: list[str]
) -> bool:
    """모듈 수준에 ``enum_name`` 의 전이표가 하나 이상 있으면 참이다."""
    member_set = set(members)
    if not member_set:
        return False
    for stmt in module.body:
        if (
            isinstance(stmt, ast.Assign)
            and len(stmt.targets) == 1
            and isinstance(stmt.targets[0], ast.Name)
        ):
            value = stmt.value
        elif (
            isinstance(stmt, ast.AnnAssign)
            and stmt.value is not None
            and isinstance(stmt.target, ast.Name)
        ):
            value = stmt.value
        else:
            continue
        if _is_table(value, enum_name, member_set):
            return True
    return False


def measure_tables(root: Path) -> dict[str, bool]:
    """상태 enum 식별자마다 「표 있음」 여부를 돌려준다."""
    result: dict[str, bool] = {}
    for ident, (module, cls, module_level) in find_state_enums(root).items():
        result[ident] = (
            module_level
            and has_closed_body(cls)
            and has_transition_table(module, cls.name, enum_members(cls))
        )
    return result


def diff_against_baseline(
    measured: frozenset[str], baseline: frozenset[str]
) -> tuple[frozenset[str], frozenset[str]]:
    """(기준선에 없이 늘어난 것, 기준선에 있지만 실측에 없는 것)을 돌려준다."""
    return measured - baseline, baseline - measured


def failure_message(
    extra: frozenset[str],
    missing: frozenset[str],
    not_top: frozenset[str],
    open_body: frozenset[str],
) -> str:
    """비교 결과의 실패 메시지다. 차이가 없으면 빈 문자열이다."""
    lines: list[str] = []
    if extra:
        lines.append(_INCREASED)
        for ident in sorted(extra):
            notes = [_NOT_TOP_NOTE] if ident in not_top else []
            if ident in open_body:
                notes.append(_OPEN_BODY_NOTE)
            suffix = f" ({'; '.join(notes)})" if notes else ""
            lines.append(f"  - {ident}{suffix}")
        lines.append(
            f"  같은 파일 모듈 수준에 전이표를 둔다. 본보기는 {MODEL_TABLE} 다. "
            "수명주기가 없으면 빈 전이표(모든 값이 set())를 둔다. "
            "옮기거나 이름을 바꾼 것이면 기준선의 식별자를 고친다."
        )
    if missing:
        lines.append(_STALE)
        lines.extend(f"  - {ident}" for ident in sorted(missing))
        lines.append("  기준선에서 지운다.")
    return "\n".join(lines)


def assert_matches_baseline(root: Path, baseline: frozenset[str]) -> None:
    """``root`` 의 실측을 ``baseline`` 과 비교하고 빈 통과 방지를 함께 단언한다."""
    enums = find_state_enums(root)
    tables = measure_tables(root)
    without = frozenset(ident for ident, ok in tables.items() if not ok)
    not_top = frozenset(ident for ident, (_, _, top) in enums.items() if not top)
    open_body = frozenset(
        ident for ident, (_, cls, _) in enums.items() if not has_closed_body(cls)
    )
    extra, missing = diff_against_baseline(without, baseline)
    problems: list[str] = []
    message = failure_message(extra, missing, not_top, open_body)
    if message:
        problems.append(message)
    if not enums:
        problems.append("상태 enum을 하나도 찾지 못했다.")
    if not tables.get(MODEL_ENUM, False):
        problems.append(
            f"양성 대조군 {MODEL_ENUM} 가 「표 있음」이 아니다. "
            "대조군을 옮기거나 이름을 바꿨으면 테스트의 대조군 식별자를 고친다."
        )
    if problems:
        raise AssertionError("\n".join(problems))


def _module_name(ident: str) -> str:
    parts = Path(ident.split("::", 1)[0]).with_suffix("").parts[1:]
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def runtime_member_mismatches(root: Path) -> list[str]:
    """도출한 멤버 집합이 런타임 ``__members__`` 와 다른 enum을 알린다."""
    problems: list[str] = []
    for ident, (_, cls, module_level) in find_state_enums(root).items():
        if not module_level or not has_closed_body(cls):
            continue
        module = importlib.import_module(_module_name(ident))
        runtime = set(getattr(module, cls.name).__members__)
        derived = set(enum_members(cls))
        if derived != runtime:
            problems.append(
                f"  - {ident}: 런타임에만 {sorted(runtime - derived)}, "
                f"도출에만 {sorted(derived - runtime)}"
            )
    return problems


def assert_runtime_members_match(root: Path) -> None:
    """실제 트리에서 도출한 멤버 집합을 런타임과 대조한다."""
    problems = runtime_member_mismatches(root)
    if problems:
        raise AssertionError(
            "도출한 멤버가 런타임 __members__ 와 다르다:\n"
            + "\n".join(problems)
            + "\n  클래스 본문을 이름 하나짜리 대입과 메서드만으로 쓴다."
        )


def _listed(message: str, header: str) -> set[str]:
    """``message`` 에서 ``header`` 바로 아래 ``  - `` 행의 식별자를 모은다."""
    lines = message.splitlines()
    if header not in lines:
        return set()
    found: set[str] = set()
    for line in lines[lines.index(header) + 1 :]:
        if not line.startswith("  - "):
            break
        found.add(line[4:].split(" ", 1)[0])
    return found


def test_real_tree_matches_baseline() -> None:
    assert_matches_baseline(_REPO_ROOT, BASELINE_WITHOUT_TABLE)


def test_real_tree_members_match_runtime() -> None:
    assert_runtime_members_match(_REPO_ROOT)


def test_runtime_comparison_fails_when_derivation_drops_member(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = enum_members
    monkeypatch.setattr(
        sys.modules[__name__], "enum_members", lambda cls: original(cls)[1:]
    )
    with pytest.raises(AssertionError, match="런타임에만"):
        assert_runtime_members_match(_REPO_ROOT)


def test_runtime_comparison_fails_when_derivation_adds_member(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = enum_members
    monkeypatch.setattr(
        sys.modules[__name__], "enum_members", lambda cls: [*original(cls), "EXTRA"]
    )
    with pytest.raises(AssertionError, match="도출에만"):
        assert_runtime_members_match(_REPO_ROOT)


# ---------------------------------------------------------------------------
# 사본 트리: 실제 소스를 고친 사본에서 같은 단언이 실패한다.
# ---------------------------------------------------------------------------


def _copy_src(tmp_path: Path) -> Path:
    shutil.copytree(
        _REPO_ROOT / "src" / "ante",
        tmp_path / "src" / "ante",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    return tmp_path


def test_copy_with_new_state_enum_fails(tmp_path: Path) -> None:
    root = _copy_src(tmp_path)
    target = root / "src" / "ante" / "audit" / "models.py"
    assert not target.exists()
    target.write_text(
        'from enum import StrEnum\n\n\nclass FooStatus(StrEnum):\n    A = "a"\n',
        encoding="utf-8",
    )
    with pytest.raises(AssertionError) as excinfo:
        assert_matches_baseline(root, BASELINE_WITHOUT_TABLE)
    assert _listed(str(excinfo.value), _INCREASED) == {
        "src/ante/audit/models.py::FooStatus"
    }


def test_copy_with_table_row_removed_fails(tmp_path: Path) -> None:
    root = _copy_src(tmp_path)
    registry = root / "src" / "ante" / "strategy" / "registry.py"
    before = registry.read_text(encoding="utf-8")
    after = before.replace("    StrategyStatus.ARCHIVED: set(),\n", "", 1)
    assert after != before
    registry.write_text(after, encoding="utf-8")

    tables = measure_tables(root)
    without = frozenset(ident for ident, ok in tables.items() if not ok)
    assert len(without) == len(BASELINE_WITHOUT_TABLE) + 1
    extra, missing = diff_against_baseline(without, BASELINE_WITHOUT_TABLE)
    assert extra == frozenset({MODEL_ENUM})
    assert missing == frozenset()

    with pytest.raises(AssertionError) as excinfo:
        assert_matches_baseline(root, BASELINE_WITHOUT_TABLE)
    assert _listed(str(excinfo.value), _INCREASED) == {MODEL_ENUM}


def test_copy_with_model_enum_renamed_fails_only_on_control(tmp_path: Path) -> None:
    root = _copy_src(tmp_path)
    registry = root / "src" / "ante" / "strategy" / "registry.py"
    before = registry.read_text(encoding="utf-8")
    after = before.replace("StrategyStatus", "StrategyState")
    assert after != before
    registry.write_text(after, encoding="utf-8")

    tables = measure_tables(root)
    assert tables["src/ante/strategy/registry.py::StrategyState"] is True
    without = frozenset(ident for ident, ok in tables.items() if not ok)
    assert diff_against_baseline(without, BASELINE_WITHOUT_TABLE) == (
        frozenset(),
        frozenset(),
    )

    with pytest.raises(AssertionError) as excinfo:
        assert_matches_baseline(root, BASELINE_WITHOUT_TABLE)
    message = str(excinfo.value)
    assert MODEL_ENUM in message
    assert "테스트의 대조군 식별자를 고친다" in message
    assert _INCREASED not in message
    assert _STALE not in message


# ---------------------------------------------------------------------------
# 정의역 표: 계약의 정의마다 가짜 소스 한 행.
# ---------------------------------------------------------------------------


def _write_tree(tmp_path: Path, files: dict[str, str]) -> Path:
    for rel, source in files.items():
        path = tmp_path / "src" / "ante" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(source), encoding="utf-8")
    return tmp_path


_ID = "src/ante/m.py::"
_FOO_SOURCE = 'from enum import StrEnum\nclass FooStatus(StrEnum):\n    A = "a"\n'

STATE_ENUM_ROWS = [
    pytest.param(
        """
        from enum import StrEnum
        class FooStatus(StrEnum):
            A = "a"
        """,
        {_ID + "FooStatus": False},
        id="base-StrEnum",
    ),
    pytest.param(
        """
        from enum import Enum
        class FooStatus(Enum):
            A = "a"
        """,
        {_ID + "FooStatus": False},
        id="base-Enum",
    ),
    pytest.param(
        """
        import enum
        class FooStatus(enum.Enum):
            A = "a"
        """,
        {_ID + "FooStatus": False},
        id="base-enum.Enum",
    ),
    pytest.param(
        """
        from enum import IntEnum
        class FooStatus(IntEnum):
            A = 1
        """,
        {_ID + "FooStatus": False},
        id="base-IntEnum",
    ),
    pytest.param(
        """
        from enum import Enum
        class FooStatus(str, Enum):
            A = "a"
        """,
        {_ID + "FooStatus": False},
        id="base-str-Enum-multiple",
    ),
    pytest.param(
        """
        from enum import StrEnum
        class FooState(StrEnum):
            A = "a"
        """,
        {_ID + "FooState": False},
        id="name-State",
    ),
    pytest.param(
        """
        class FooStatus:
            A = "a"
        """,
        {},
        id="no-base",
    ),
    pytest.param(
        """
        from pydantic import BaseModel
        class FooStatus(BaseModel):
            a: str = "a"
        """,
        {},
        id="base-BaseModel",
    ),
    pytest.param(
        """
        from enum import StrEnum
        class FooKind(StrEnum):
            A = "a"
        """,
        {},
        id="name-Kind",
    ),
    pytest.param(
        """
        from enum import StrEnum
        class Outer:
            class FooStatus(StrEnum):
                A = "a"
        T = {FooStatus.A: set()}
        """,
        {_ID + "FooStatus": False},
        id="nested-counted-without-table",
    ),
    pytest.param(
        """
        from enum import StrEnum
        class FooStatus(StrEnum):
            A = "a"
        T = {FooStatus.A: set()}
        """,
        {_ID + "FooStatus": True},
        id="module-level-with-table",
    ),
]


@pytest.mark.parametrize(("source", "expected"), STATE_ENUM_ROWS)
def test_state_enum_domain(
    tmp_path: Path, source: str, expected: dict[str, bool]
) -> None:
    root = _write_tree(tmp_path, {"m.py": source})
    assert measure_tables(root) == expected


def test_nested_enum_message_says_move_to_module_level(tmp_path: Path) -> None:
    root = _write_tree(
        tmp_path,
        {
            "m.py": """
            from enum import StrEnum
            class Outer:
                class FooStatus(StrEnum):
                    A = "a"
            """
        },
    )
    with pytest.raises(AssertionError) as excinfo:
        assert_matches_baseline(root, frozenset())
    message = str(excinfo.value)
    assert _NOT_TOP_NOTE in message
    assert _OPEN_BODY_NOTE not in message
    assert _listed(message, _INCREASED) == {_ID + "FooStatus"}


def test_duplicate_identifier_fails(tmp_path: Path) -> None:
    root = _write_tree(
        tmp_path,
        {
            "m.py": """
            from enum import StrEnum
            class FooStatus(StrEnum):
                A = "a"
            class FooStatus(StrEnum):
                B = "b"
            """
        },
    )
    with pytest.raises(AssertionError, match=r"src/ante/m\.py::FooStatus"):
        find_state_enums(root)


def test_tree_without_state_enum_fails(tmp_path: Path) -> None:
    root = _write_tree(tmp_path, {"m.py": "X = 1\n"})
    with pytest.raises(AssertionError, match="상태 enum을 하나도 찾지 못했다"):
        assert_matches_baseline(root, frozenset())


def test_unparsable_file_raises_syntax_error(tmp_path: Path) -> None:
    root = _write_tree(
        tmp_path,
        {
            "ok.py": _FOO_SOURCE,
            "broken.py": "def f(:\n",
        },
    )
    with pytest.raises(SyntaxError):
        find_state_enums(root)


def _class_of(source: str) -> ast.ClassDef:
    module = ast.parse(textwrap.dedent(source))
    cls = module.body[-1]
    assert isinstance(cls, ast.ClassDef)
    return cls


MEMBER_ROWS = [
    pytest.param('A = "a"', ["A"], id="assign"),
    pytest.param('A: str = "a"', ["A"], id="annassign-with-value"),
    pytest.param('_ignore_ = ["x"]', [], id="ignore"),
    pytest.param('_order_ = "A"', [], id="order"),
    pytest.param("def method(self):\n    return 1", [], id="method"),
    pytest.param("A: str", [], id="annassign-without-value"),
]


@pytest.mark.parametrize(("body", "expected"), MEMBER_ROWS)
def test_member_domain(body: str, expected: list[str]) -> None:
    source = "class FooStatus(StrEnum):\n" + textwrap.indent(body, "    ") + "\n"
    assert enum_members(_class_of(source)) == expected


def test_enum_without_members_has_no_table(tmp_path: Path) -> None:
    root = _write_tree(
        tmp_path,
        {
            "m.py": """
            from enum import StrEnum
            class FooStatus(StrEnum):
                pass
            T = {}
            """
        },
    )
    assert measure_tables(root) == {_ID + "FooStatus": False}


_TABLE_HEADER = """\
from enum import StrEnum
from types import MappingProxyType

class FooStatus(StrEnum):
    A = "a"
    B = "b"

class BarStatus(StrEnum):
    A = "a"
    B = "b"
"""

TABLE_ROWS = [
    pytest.param(
        "T = {FooStatus.A: {FooStatus.B}, FooStatus.B: set()}",
        True,
        id="assign-complete",
    ),
    pytest.param(
        "T: dict[FooStatus, set[FooStatus]] = "
        "{FooStatus.A: {FooStatus.B}, FooStatus.B: set()}",
        True,
        id="annassign-complete",
    ),
    pytest.param("T: dict[FooStatus, set[FooStatus]]", False, id="annassign-no-value"),
    pytest.param(
        "T = {FooStatus.A: frozenset({FooStatus.B}), FooStatus.B: frozenset()}",
        True,
        id="frozenset-values",
    ),
    pytest.param(
        "T = {FooStatus.A: set(), FooStatus.B: set()}", True, id="empty-table"
    ),
    pytest.param(
        "T = {FooStatus.A: set(), FooStatus.B: set()}\n"
        "U = {FooStatus.A: {FooStatus.B}, FooStatus.B: {FooStatus.A}}",
        True,
        id="two-tables",
    ),
    pytest.param("T = {FooStatus.A: set()}", False, id="member-missing"),
    pytest.param(
        "T = {FooStatus.A: set(), FooStatus.A: set(), FooStatus.B: set()}",
        False,
        id="duplicate-key",
    ),
    pytest.param(
        "T = {FooStatus.A: set(), FooStatus.B: set(), BarStatus.A: set()}",
        False,
        id="key-of-other-enum",
    ),
    pytest.param(
        "T = {BarStatus.A: set(), BarStatus.B: set()}",
        False,
        id="keys-only-of-other-enum-with-same-member-names",
    ),
    pytest.param(
        "T = {m.FooStatus.A: set(), m.FooStatus.B: set()}",
        False,
        id="keys-through-module-attribute",
    ),
    pytest.param("T = {A: set(), B: set()}", False, id="keys-bare-names"),
    pytest.param(
        "T = {FooStatus.A: {FooStatus.C}, FooStatus.B: set()}",
        False,
        id="value-non-member",
    ),
    pytest.param(
        "T = {FooStatus.A: {BarStatus.B}, FooStatus.B: set()}",
        False,
        id="value-member-of-other-enum",
    ),
    pytest.param(
        "T = U = {FooStatus.A: set(), FooStatus.B: set()}",
        False,
        id="multiple-targets",
    ),
    pytest.param(
        "obj.t = {FooStatus.A: set(), FooStatus.B: set()}",
        False,
        id="attribute-target",
    ),
    pytest.param('T = {"a": set(), "b": set()}', False, id="string-keys"),
    pytest.param(
        "T = {**other, FooStatus.A: set(), FooStatus.B: set()}",
        False,
        id="double-star",
    ),
    pytest.param(
        "T = {FooStatus.A: [FooStatus.B], FooStatus.B: set()}", False, id="list-value"
    ),
    pytest.param(
        "T = {FooStatus.A: (FooStatus.B,), FooStatus.B: set()}",
        False,
        id="tuple-value",
    ),
    pytest.param(
        "T = {FooStatus.A: set(x), FooStatus.B: set()}", False, id="set-call-with-arg"
    ),
    pytest.param(
        "T = {FooStatus.A: frozenset([FooStatus.B]), FooStatus.B: set()}",
        False,
        id="frozenset-of-list",
    ),
    pytest.param(
        "T = MappingProxyType({FooStatus.A: set(), FooStatus.B: set()})",
        False,
        id="mapping-proxy",
    ),
    pytest.param(
        "def f():\n    T = {FooStatus.A: set(), FooStatus.B: set()}\n    return T",
        False,
        id="dict-inside-function",
    ),
]


@pytest.mark.parametrize(("table", "expected"), TABLE_ROWS)
def test_table_domain(tmp_path: Path, table: str, expected: bool) -> None:
    root = _write_tree(tmp_path, {"m.py": _TABLE_HEADER + "\n" + table + "\n"})
    assert measure_tables(root)[_ID + "FooStatus"] is expected


_BODY_TABLE = "T = {FooStatus.A: set(), FooStatus.B: set()}\n"

BODY_ROWS = [
    pytest.param("", True, id="only-single-name-assigns"),
    pytest.param("if True:\n    C = 'c'", False, id="if-block"),
    pytest.param(
        "try:\n    C = 'c'\nexcept Exception:\n    pass", False, id="try-block"
    ),
    pytest.param("for _i in ('x',):\n    C = 'c'", False, id="for-block"),
    pytest.param("with ctx():\n    C = 'c'", False, id="with-block"),
    pytest.param("C, D = 'c', 'd'", False, id="tuple-target"),
    pytest.param("C = D = 'c'", False, id="multiple-targets"),
    pytest.param("def label(self):\n    return 1", True, id="method"),
    pytest.param("async def fetch(self):\n    return 1", True, id="async-method"),
    pytest.param('"설명."', True, id="docstring"),
    pytest.param("(C := 'c')", False, id="walrus-expression"),
    pytest.param("print()", False, id="call-expression"),
    pytest.param("1", False, id="number-constant-expression"),
    pytest.param("@property\ndef p(self):\n    return 1", False, id="decorated-method"),
    pytest.param(
        "@member\ndef C(self):\n    return 1", False, id="member-decorated-method"
    ),
    pytest.param("pass", True, id="pass"),
    pytest.param("note: str", True, id="annassign-without-value"),
]


@pytest.mark.parametrize(("extra_stmt", "expected"), BODY_ROWS)
def test_class_body_domain(tmp_path: Path, extra_stmt: str, expected: bool) -> None:
    body = "A = 'a'\nB = 'b'\n" + extra_stmt
    source = (
        "from enum import StrEnum\n\nclass FooStatus(StrEnum):\n"
        + textwrap.indent(body, "    ")
        + "\n\n"
        + _BODY_TABLE
    )
    root = _write_tree(tmp_path, {"m.py": source})
    assert measure_tables(root) == {_ID + "FooStatus": expected}


UNDERSCORE_ROWS = [
    pytest.param("_B = 'b'", False, id="leading-underscore"),
    pytest.param("_ = 'z'", False, id="single-underscore"),
    pytest.param("__x = 1", False, id="double-leading-underscore"),
    pytest.param("__x__ = 1", False, id="dunder"),
    pytest.param("_x_ = 1", False, id="sunder"),
    pytest.param("_missing_ = 1", False, id="sunder-outside-allowed"),
    pytest.param("_x__ = 1", False, id="single-leading-double-trailing"),
    pytest.param("_B: str = 'b'", False, id="annassign-with-value"),
    pytest.param("_ignore_ = ['x']", True, id="ignore-allowed"),
    pytest.param("_order_ = 'A B'", True, id="order-allowed"),
    pytest.param("def _helper(self):\n    return 1", True, id="private-method"),
    pytest.param("_x: int", True, id="annassign-without-value"),
]


@pytest.mark.parametrize(("extra_stmt", "expected"), UNDERSCORE_ROWS)
def test_underscore_name_domain(
    tmp_path: Path, extra_stmt: str, expected: bool
) -> None:
    body = "A = 'a'\nB = 'b'\n" + extra_stmt
    source = (
        "from enum import StrEnum\n\nclass FooStatus(StrEnum):\n"
        + textwrap.indent(body, "    ")
        + "\n\n"
        + _BODY_TABLE
    )
    root = _write_tree(tmp_path, {"m.py": source})
    assert measure_tables(root) == {_ID + "FooStatus": expected}


def test_underscore_name_message_says_single_name_assigns(tmp_path: Path) -> None:
    source = (
        "from enum import StrEnum\n\nclass FooStatus(StrEnum):\n"
        "    A = 'a'\n    B = 'b'\n    _C = 'c'\n\n" + _BODY_TABLE
    )
    root = _write_tree(tmp_path, {"m.py": source})
    with pytest.raises(AssertionError) as excinfo:
        assert_matches_baseline(root, frozenset())
    message = str(excinfo.value)
    assert _OPEN_BODY_NOTE in message
    assert "멤버 이름은 _로 시작하지 않는다" in message
    assert _listed(message, _INCREASED) == {_ID + "FooStatus"}


@pytest.mark.parametrize(
    ("bases", "expected"),
    [
        pytest.param("StrEnum", True, id="no-keywords"),
        pytest.param("StrEnum, metaclass=M", False, id="metaclass-keyword"),
    ],
)
def test_class_header_domain(tmp_path: Path, bases: str, expected: bool) -> None:
    source = (
        f"from enum import StrEnum\n\nclass FooStatus({bases}):\n"
        "    A = 'a'\n    B = 'b'\n\n" + _BODY_TABLE
    )
    root = _write_tree(tmp_path, {"m.py": source})
    assert measure_tables(root) == {_ID + "FooStatus": expected}


def test_open_body_message_says_single_name_assigns(tmp_path: Path) -> None:
    source = (
        "from enum import StrEnum\n\nclass FooStatus(StrEnum):\n"
        "    A = 'a'\n    B, C = 'b', 'c'\n\n" + _BODY_TABLE
    )
    root = _write_tree(tmp_path, {"m.py": source})
    with pytest.raises(AssertionError) as excinfo:
        assert_matches_baseline(root, frozenset())
    message = str(excinfo.value)
    assert _OPEN_BODY_NOTE in message
    assert _NOT_TOP_NOTE not in message
    assert _listed(message, _INCREASED) == {_ID + "FooStatus"}


def test_table_in_other_file_is_not_counted(tmp_path: Path) -> None:
    root = _write_tree(
        tmp_path,
        {
            "m.py": _FOO_SOURCE,
            "t.py": "from ante.m import FooStatus\nT = {FooStatus.A: set()}\n",
        },
    )
    assert measure_tables(root) == {_ID + "FooStatus": False}


# ---------------------------------------------------------------------------
# 판정 표.
# ---------------------------------------------------------------------------

_A = "src/ante/a.py::AStatus"
_B = "src/ante/b.py::BStatus"
_C = "src/ante/c.py::CStatus"

JUDGEMENT_ROWS = [
    pytest.param(
        frozenset({_A, _B}),
        frozenset({_A}),
        frozenset({_B}),
        frozenset(),
        id="increased",
    ),
    pytest.param(
        frozenset({_A}),
        frozenset({_A, _B}),
        frozenset(),
        frozenset({_B}),
        id="table-added-baseline-kept",
    ),
    pytest.param(
        frozenset({_A, _C}),
        frozenset({_A, _B}),
        frozenset({_C}),
        frozenset({_B}),
        id="swap-one-out-one-in",
    ),
    pytest.param(
        frozenset({_A, _B}),
        frozenset({_A, _B}),
        frozenset(),
        frozenset(),
        id="equal",
    ),
]


@pytest.mark.parametrize(("measured", "baseline", "extra", "missing"), JUDGEMENT_ROWS)
def test_judgement(
    measured: frozenset[str],
    baseline: frozenset[str],
    extra: frozenset[str],
    missing: frozenset[str],
) -> None:
    assert diff_against_baseline(measured, baseline) == (extra, missing)
    message = failure_message(extra, missing, frozenset(), frozenset())
    if not extra and not missing:
        assert message == ""
        return
    assert _listed(message, _INCREASED) == set(extra)
    assert _listed(message, _STALE) == set(missing)
    if extra:
        assert "같은 파일 모듈 수준에 전이표를 둔다" in message
        assert "빈 전이표" in message
        assert "기준선의 식별자를 고친다" in message
        assert MODEL_TABLE in message
    if missing:
        assert "기준선에서 지운다" in message
    else:
        assert "기준선에서 지운다" not in message
    assert _NOT_TOP_NOTE not in message
    assert _OPEN_BODY_NOTE not in message
