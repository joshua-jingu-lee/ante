"""``scripts/scan_create_services_anti_pattern.py`` 자체 회귀 테스트 (#1900).

scanner 가 새로 검출해야 하는 ``patch(...)`` 형태를 fixture 소스로 만들어
``scan_paths`` 가 위반을 정확히 보고하고, 기존 PASS 케이스(올바른 helper
사용)는 그대로 통과시키는지 확인한다.

Codex 브랜치 리뷰 attempt 1 finding 2건:

* Finding 1: ``patch(target, return_value=(db, ...))`` (default MagicMock + tuple
  return_value) 가 누락되어 회귀 검출 실패
* Finding 2: ``patch(target, MagicMock(return_value=(db, ...)))`` (2번째
  positional ``new``) 가 누락되어 회귀 검출 실패

Codex 브랜치 리뷰 attempt 2 finding 2:

* ``@patch(...)`` 데코레이터 형태가 누락되어 회귀 검출 실패. ``FunctionDef``/
  ``AsyncFunctionDef``/``ClassDef`` decorator_list 안의 ``patch(...)`` 도
  with-statement 와 동일 로직으로 검사한다.

Codex 브랜치 리뷰 attempt 3 finding 1:

* ``@patch(target)`` 데코레이터로 주입된 mock 인자가 함수 본문에서
  ``mock_cs.return_value = tuple`` 로 사용되는 형태 누락. decorator stack 을
  역순으로 함수 인자에 매핑한 뒤 body 의 할당을 검사한다 (innermost decorator
  → 첫 mock arg 매핑 규칙).
"""

from __future__ import annotations

import importlib.util
import sys
import textwrap
from pathlib import Path

import pytest

# ``scripts/`` 는 패키지가 아니라 스크립트 디렉토리라서 일반 import 가
# 불가능하다. 파일 경로에서 직접 spec 을 만들어 로드한다.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCANNER_PATH = _REPO_ROOT / "scripts" / "scan_create_services_anti_pattern.py"
_MODULE_NAME = "scan_create_services_anti_pattern"
_spec = importlib.util.spec_from_file_location(_MODULE_NAME, _SCANNER_PATH)
assert _spec is not None and _spec.loader is not None
_scanner = importlib.util.module_from_spec(_spec)
# dataclasses 가 cls.__module__ 로 sys.modules lookup 을 수행하므로
# exec_module 호출 전에 등록해야 frozen=True dataclass 가 동작한다.
sys.modules[_MODULE_NAME] = _scanner
_spec.loader.exec_module(_scanner)

discover_async_ctxmgr_factories = _scanner.discover_async_ctxmgr_factories
scan_file = _scanner.scan_file

# 실제 production target — sweep allowlist 에 들어있어야 한다.
TARGET = "ante.cli.commands.bot._create_services"


@pytest.fixture(scope="module")
def allowlist() -> set[str]:
    a = discover_async_ctxmgr_factories()
    # 이 테스트의 전제: bot._create_services 는 allowlist 에 있다.
    assert TARGET in a
    return a


def _write(tmp_path: Path, src: str) -> Path:
    p = tmp_path / "fixture.py"
    p.write_text(textwrap.dedent(src), encoding="utf-8")
    return p


# ── Finding 1: default patch + return_value=tuple ───────────────────────────


def test_default_patch_with_tuple_return_value_kwarg_is_violation(
    tmp_path: Path, allowlist: set[str]
) -> None:
    """``patch(target, return_value=(db, ...))`` 형태도 위반으로 잡아야 한다.

    default MagicMock 이 tuple 을 반환해 ``async with`` 가 ``__aenter__`` 를
    찾지 못한다.
    """
    src = f"""
        from unittest.mock import patch

        def test_x():
            db, eb, mgr, svc = object(), object(), object(), object()
            with patch(
                "{TARGET}",
                return_value=(db, eb, mgr, svc),
            ):
                pass
        """
    p = _write(tmp_path, src)
    vs = scan_file(p, allowlist)
    assert len(vs) == 1, [v.format() for v in vs]
    assert vs[0].kind == "tuple-return-on-patch"
    assert vs[0].target == TARGET


def test_default_patch_with_tuple_return_value_list_form(
    tmp_path: Path, allowlist: set[str]
) -> None:
    """list literal 도 동일 위반 처리."""
    src = f"""
        from unittest.mock import patch

        def test_x():
            with patch("{TARGET}", return_value=[1, 2, 3, 4]):
                pass
        """
    p = _write(tmp_path, src)
    vs = scan_file(p, allowlist)
    assert len(vs) == 1
    assert vs[0].kind == "tuple-return-on-patch"


def test_default_patch_with_scalar_return_value_not_violation(
    tmp_path: Path, allowlist: set[str]
) -> None:
    """tuple/list 가 아닌 ``return_value`` 는 scanner 범위 밖 (false positive 방지)."""
    src = f"""
        from unittest.mock import patch

        def test_x():
            with patch("{TARGET}", return_value=None):
                pass
        """
    p = _write(tmp_path, src)
    vs = scan_file(p, allowlist)
    assert vs == [], [v.format() for v in vs]


# ── Finding 2: positional ``new`` ───────────────────────────────────────────


def test_positional_new_magicmock_with_tuple_return_is_violation(
    tmp_path: Path, allowlist: set[str]
) -> None:
    """``patch(target, MagicMock(return_value=(...)))`` — 2번째 positional ``new``."""
    src = f"""
        from unittest.mock import MagicMock, patch

        def test_x():
            db, eb, mgr, svc = object(), object(), object(), object()
            with patch(
                "{TARGET}",
                MagicMock(return_value=(db, eb, mgr, svc)),
            ):
                pass
        """
    p = _write(tmp_path, src)
    vs = scan_file(p, allowlist)
    assert len(vs) == 1, [v.format() for v in vs]
    assert vs[0].kind == "tuple-return-on-patch"
    assert vs[0].target == TARGET


def test_positional_new_asyncmock_with_tuple_return_is_violation(
    tmp_path: Path, allowlist: set[str]
) -> None:
    """``patch(target, AsyncMock(return_value=(...)))`` 도 same 카테고리로 보고."""
    src = f"""
        from unittest.mock import AsyncMock, patch

        def test_x():
            db, eb, mgr, svc = object(), object(), object(), object()
            with patch(
                "{TARGET}",
                AsyncMock(return_value=(db, eb, mgr, svc)),
            ):
                pass
        """
    p = _write(tmp_path, src)
    vs = scan_file(p, allowlist)
    assert len(vs) == 1, [v.format() for v in vs]
    assert vs[0].kind == "tuple-return-on-patch"


def test_positional_new_magicmock_bare_is_substitute_violation(
    tmp_path: Path, allowlist: set[str]
) -> None:
    """``patch(target, MagicMock())`` — return_value 미설정도 substitute 위반."""
    src = f"""
        from unittest.mock import MagicMock, patch

        def test_x():
            with patch("{TARGET}", MagicMock()):
                pass
        """
    p = _write(tmp_path, src)
    vs = scan_file(p, allowlist)
    assert len(vs) == 1
    assert vs[0].kind == "magicmock-new-substitute"


# ── 기존 Case 회귀 — keyword ``new=`` 분기 유지 ──────────────────────────────


def test_keyword_new_magicmock_with_tuple_return_kept(
    tmp_path: Path, allowlist: set[str]
) -> None:
    """기존 ``new=MagicMock(return_value=(...))`` 형태도 같은 카테고리 보고."""
    src = f"""
        from unittest.mock import MagicMock, patch

        def test_x():
            with patch("{TARGET}", new=MagicMock(return_value=(1, 2))):
                pass
        """
    p = _write(tmp_path, src)
    vs = scan_file(p, allowlist)
    assert len(vs) == 1
    assert vs[0].kind == "tuple-return-on-patch"


def test_keyword_new_callable_asyncmock_with_tuple_return_kept(
    tmp_path: Path, allowlist: set[str]
) -> None:
    """기존 ``new_callable=AsyncMock, return_value=tuple`` 회귀."""
    src = f"""
        from unittest.mock import AsyncMock, patch

        def test_x():
            with patch(
                "{TARGET}",
                new_callable=AsyncMock,
                return_value=(1, 2, 3, 4),
            ):
                pass
        """
    p = _write(tmp_path, src)
    vs = scan_file(p, allowlist)
    assert len(vs) == 1
    assert vs[0].kind == "asyncmock-tuple-return"


def test_with_alias_tuple_return_assignment_kept(
    tmp_path: Path, allowlist: set[str]
) -> None:
    """``with patch(...) as mock_cs: mock_cs.return_value = tuple`` 기존 케이스."""
    src = f"""
        from unittest.mock import patch

        def test_x():
            with patch("{TARGET}") as mock_cs:
                mock_cs.return_value = (1, 2, 3, 4)
        """
    p = _write(tmp_path, src)
    vs = scan_file(p, allowlist)
    assert len(vs) == 1
    assert vs[0].kind == "tuple-return-on-patch"


# ── PASS 케이스 — false positive 회귀 ─────────────────────────────────────


def test_helper_factory_substitute_not_violation(
    tmp_path: Path, allowlist: set[str]
) -> None:
    """``new=mock_bot_services_factory(...)`` 형태는 위반 아님 — helper 가
    이미 async ctxmgr 를 yield 한다.
    """
    src = f"""
        from unittest.mock import patch

        def mock_bot_services_factory(*a, **k):
            ...

        def test_x():
            with patch(
                "{TARGET}",
                new=mock_bot_services_factory(1, 2, 3, 4),
            ):
                pass
        """
    p = _write(tmp_path, src)
    vs = scan_file(p, allowlist)
    assert vs == [], [v.format() for v in vs]


def test_non_allowlist_target_ignored(tmp_path: Path, allowlist: set[str]) -> None:
    """allowlist 밖의 patch target 은 무시."""
    src = """
        from unittest.mock import patch

        def test_x():
            with patch("ante.cli.commands.unrelated.helper", return_value=(1, 2)):
                pass
        """
    p = _write(tmp_path, src)
    vs = scan_file(p, allowlist)
    assert vs == []


# ── Attempt 2 Finding 2: decorator 형태 ─────────────────────────────────────


def test_decorator_patch_with_tuple_return_value_kwarg_is_violation(
    tmp_path: Path, allowlist: set[str]
) -> None:
    """``@patch("target", return_value=tuple)`` 데코레이터 형태도 위반."""
    src = f"""
        from unittest.mock import patch

        @patch("{TARGET}", return_value=(1, 2, 3, 4))
        def test_x(mock_):
            pass
        """
    p = _write(tmp_path, src)
    vs = scan_file(p, allowlist)
    assert len(vs) == 1, [v.format() for v in vs]
    assert vs[0].kind == "tuple-return-on-patch"
    assert vs[0].target == TARGET


def test_decorator_patch_new_callable_asyncmock_tuple_return_is_violation(
    tmp_path: Path, allowlist: set[str]
) -> None:
    """``@patch("target", new_callable=AsyncMock, return_value=tuple)`` 위반."""
    src = f"""
        from unittest.mock import AsyncMock, patch

        @patch(
            "{TARGET}",
            new_callable=AsyncMock,
            return_value=(1, 2, 3, 4),
        )
        def test_x(self, mock_):
            pass
        """
    p = _write(tmp_path, src)
    vs = scan_file(p, allowlist)
    assert len(vs) == 1, [v.format() for v in vs]
    assert vs[0].kind == "asyncmock-tuple-return"


def test_decorator_patch_positional_new_magicmock_tuple_return_is_violation(
    tmp_path: Path, allowlist: set[str]
) -> None:
    """``@patch("target", MagicMock(return_value=tuple))`` 2-positional new."""
    src = f"""
        from unittest.mock import MagicMock, patch

        @patch("{TARGET}", MagicMock(return_value=(1, 2, 3, 4)))
        def test_x(mock_):
            pass
        """
    p = _write(tmp_path, src)
    vs = scan_file(p, allowlist)
    assert len(vs) == 1, [v.format() for v in vs]
    assert vs[0].kind == "tuple-return-on-patch"


def test_decorator_patch_keyword_new_magicmock_substitute_is_violation(
    tmp_path: Path, allowlist: set[str]
) -> None:
    """``@patch("target", new=MagicMock())`` 데코레이터 형태도 substitute 위반."""
    src = f"""
        from unittest.mock import MagicMock, patch

        @patch("{TARGET}", new=MagicMock())
        def test_x():
            pass
        """
    p = _write(tmp_path, src)
    vs = scan_file(p, allowlist)
    assert len(vs) == 1, [v.format() for v in vs]
    assert vs[0].kind == "magicmock-new-substitute"


def test_decorator_stack_multiple_patches_all_reported(
    tmp_path: Path, allowlist: set[str]
) -> None:
    """다중 ``@patch(...)`` decorator stack — 각각 위반으로 보고."""
    other_target = next(t for t in allowlist if t.endswith(".system._create_services"))
    src = f"""
        from unittest.mock import patch

        @patch("{TARGET}", return_value=(1, 2, 3, 4))
        @patch("{other_target}", return_value=(1, 2))
        def test_x(mock_a, mock_b):
            pass
        """
    p = _write(tmp_path, src)
    vs = scan_file(p, allowlist)
    assert len(vs) == 2, [v.format() for v in vs]
    kinds = {v.kind for v in vs}
    targets = {v.target for v in vs}
    assert kinds == {"tuple-return-on-patch"}
    assert targets == {TARGET, other_target}


def test_decorator_patch_helper_factory_not_violation(
    tmp_path: Path, allowlist: set[str]
) -> None:
    """``@patch("target", new=mock_*_factory(...))`` 형태는 위반 아님."""
    src = f"""
        from unittest.mock import patch

        def mock_bot_services_factory(*a, **k):
            ...

        @patch("{TARGET}", new=mock_bot_services_factory(1, 2, 3, 4))
        def test_x():
            pass
        """
    p = _write(tmp_path, src)
    vs = scan_file(p, allowlist)
    assert vs == [], [v.format() for v in vs]


def test_decorator_patch_arg_body_assignment_is_violation(
    tmp_path: Path, allowlist: set[str]
) -> None:
    """``@patch(target)`` 으로 주입된 mock 인자가 body 에서 ``mock_cs.return_value =
    tuple`` 로 사용되는 형태 (attempt 3 finding 1).
    """
    src = f"""
        from unittest.mock import patch

        class TestX:
            @patch("{TARGET}")
            def test_x(self, mock_cs):
                db, eb, mgr, svc = object(), object(), object(), object()
                mock_cs.return_value = (db, eb, mgr, svc)
        """
    p = _write(tmp_path, src)
    vs = scan_file(p, allowlist)
    assert len(vs) == 1, [v.format() for v in vs]
    assert vs[0].kind == "tuple-return-on-patch-decorator-alias"
    assert vs[0].target == TARGET


def test_decorator_patch_arg_body_assignment_list_form(
    tmp_path: Path, allowlist: set[str]
) -> None:
    """list literal 도 동일 위반."""
    src = f"""
        from unittest.mock import patch

        @patch("{TARGET}")
        def test_x(mock_cs):
            mock_cs.return_value = [1, 2, 3, 4]
        """
    p = _write(tmp_path, src)
    vs = scan_file(p, allowlist)
    assert len(vs) == 1, [v.format() for v in vs]
    assert vs[0].kind == "tuple-return-on-patch-decorator-alias"


def test_decorator_patch_arg_body_mock_assignment_violation(
    tmp_path: Path, allowlist: set[str]
) -> None:
    """``mock_cs.return_value = MagicMock(...)`` body 할당도 위반."""
    src = f"""
        from unittest.mock import MagicMock, patch

        @patch("{TARGET}")
        def test_x(mock_cs):
            mock_cs.return_value = MagicMock()
        """
    p = _write(tmp_path, src)
    vs = scan_file(p, allowlist)
    assert len(vs) == 1, [v.format() for v in vs]
    assert vs[0].kind == "mock-return-on-patch-decorator-alias"


def test_decorator_stack_multiple_patches_body_assignment_mapped_correctly(
    tmp_path: Path, allowlist: set[str]
) -> None:
    """다중 ``@patch(...)`` decorator stack — innermost-first 함수 인자 매핑.

    test_cli_bot_treasury_ipc.py:168 의 실제 패턴을 재현::

        @patch("ante.cli.commands.bot._create_services")     # 위 (outer)
        @patch("ante.cli.commands.ipc_helpers.get_socket_path", return_value="/tmp")
        @patch("ante.cli.commands.ipc_helpers.IPCClient")    # 가장 안쪽 (innermost)
        def test_y(self, mock_ipc_cls, mock_socket, mock_services): ...

    가장 안쪽 (``IPCClient``) 부터 첫 mock arg (``mock_ipc_cls``) 에 매핑되고,
    ``mock_services`` 가 가장 바깥쪽 (``_create_services``) 에 매핑된다.

    여기서는 ``mock_services.return_value = tuple`` body 할당이 위반이어야 함.
    """
    src = f"""
        from unittest.mock import patch

        class TestX:
            @patch("{TARGET}")
            @patch("ante.cli.commands.ipc_helpers.get_socket_path", return_value="/tmp")
            @patch("ante.cli.commands.ipc_helpers.IPCClient")
            def test_y(self, mock_ipc_cls, mock_socket, mock_services):
                mock_services.return_value = (1, 2, 3, 4)
        """
    p = _write(tmp_path, src)
    vs = scan_file(p, allowlist)
    # 1건만 — TARGET 의 alias body 할당.
    # 다른 두 decorator (ipc_helpers) 는 allowlist 밖이라 무시.
    assert len(vs) == 1, [v.format() for v in vs]
    assert vs[0].kind == "tuple-return-on-patch-decorator-alias"
    assert vs[0].target == TARGET


def test_decorator_patch_arg_body_no_assignment_not_violation(
    tmp_path: Path, allowlist: set[str]
) -> None:
    """mock arg 가 함수 body 에서 사용되지 않으면 위반 아님 — false positive 방지.

    실제 ``test_cli_bot_treasury_ipc.py:168`` 패턴: ``@patch(...)`` 으로 mock
    을 주입했지만 body 에서 ``mock_services`` 를 참조하지 않는다 (mock 객체가
    호출되지 않아 사실상 noop patch).
    """
    src = f"""
        from unittest.mock import patch

        class TestX:
            @patch("{TARGET}")
            def test_z(self, mock_services):
                # body 에서 mock_services 미사용
                value = 1 + 2
                assert value == 3
        """
    p = _write(tmp_path, src)
    vs = scan_file(p, allowlist)
    assert vs == [], [v.format() for v in vs]


def test_decorator_patch_with_new_kwarg_skips_alias_mapping(
    tmp_path: Path, allowlist: set[str]
) -> None:
    """``new=`` 지정 시 mock arg 주입 안됨 → alias 매핑 스킵.

    Python ``@patch(target, new=X)`` 는 함수 인자에 mock 을 주입하지 않는다
    (``new`` 가 이미 substitute object). 따라서 mock arg slot 도 소비되지 않는다.
    """
    src = f"""
        from unittest.mock import patch

        def helper(*a, **k):
            ...

        class TestX:
            @patch("{TARGET}", new=helper)
            def test_x(self):
                # 함수 인자에 mock 주입 안 됨. body 검사 대상 없음.
                pass
        """
    p = _write(tmp_path, src)
    vs = scan_file(p, allowlist)
    # ``new=`` 자체는 helper (factory 가 아닌 일반 함수) substitute 라서 별도 검사
    # 분기가 없다. body 검사도 alias 없음으로 스킵. 결과: 0건.
    assert vs == [], [v.format() for v in vs]


def test_decorator_patch_object_form_ignored(
    tmp_path: Path, allowlist: set[str]
) -> None:
    """``@patch.object(...)`` 는 첫 인수가 string target 이 아니라 객체. 스킵.

    (sweep 대상 contract는 ``patch("ante.cli.commands...")`` string target이며,
    ``patch.object`` 는 별도 다른 target 카테고리. scanner 가 잘못 잡지 않음.)
    """
    src = f"""
        from unittest.mock import AsyncMock, patch
        from ante.cli.commands import bot

        @patch.object(bot, "_create_services", new_callable=AsyncMock,
                      return_value=(1, 2, 3, 4))
        def test_x(mock_):
            pass

        # 동시에 string-target patch 도 정상 위반으로 보고되는지 확인
        @patch("{TARGET}", return_value=(1, 2, 3, 4))
        def test_y(mock_):
            pass
        """
    p = _write(tmp_path, src)
    vs = scan_file(p, allowlist)
    # patch.object 는 무시, string-target 만 1건 위반
    assert len(vs) == 1, [v.format() for v in vs]
    assert vs[0].kind == "tuple-return-on-patch"
    assert vs[0].target == TARGET
