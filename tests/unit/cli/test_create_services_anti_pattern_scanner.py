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

Codex 브랜치 리뷰 attempt 4 finding 1/2/3 (last attempt fix):

* Finding 1: ``new_callable=MagicMock + return_value=tuple`` (그리고 generic
  ``Mock``/custom callable) 누락. ``AsyncMock`` 외 callable 도 ``return_value=
  tuple`` 이면 동일 anti-pattern 으로 catch.
* Finding 2: decorator stack mock arg slot 매핑이 Python ``patch`` 실제 주입
  규칙과 불일치. ``new=`` 는 slot 자체 소비 안 함 (skip). ``new_callable=`` 은
  slot 소비 + alias 검사. ``no new/no new_callable`` 은 slot 소비 + alias 검사.
* Finding 3: ``_async_def_stubs`` 가 visitor 진행 중 수집되어, patch site 보다
  파일 아래쪽 stub 은 참조 불가. ``scan_file`` 이 2-pass 로 동작하도록 변경
  (pre-collect → visit).

Codex 브랜치 리뷰 attempt 5 finding 1/2 (final fix):

* Finding 1: target-specific stub call-signature validation. production
  factory 의 positional/kwonly args 를 정확히 수집해 ``new=<stub>`` /
  ``side_effect=<stub>`` 가 production positional args 를 받을 수 있는지
  검증. 예: ``treasury._create_treasury(account_id, *, ctx=None)`` 의 stub 이
  ``ctx=None`` 만 받으면 호출 시 TypeError → ``async-stub-positional-arity-
  mismatch`` 위반.
* Finding 2: class-level ``@patch(...)`` decorator 가 클래스 내 모든 test
  method 의 body 에 mock arg 를 주입한다. method args 매핑은 ``self`` 다음
  ``method-level decorator (innermost-first)`` → ``class-level decorator
  (innermost-first)`` 순서. method body 의 ``mock_arg.return_value = tuple``
  도 동일 검사 대상.
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


# ── Attempt 4 Finding 1: new_callable 비-AsyncMock variants ──────────────────


def test_new_callable_magicmock_tuple_return_is_violation(
    tmp_path: Path, allowlist: set[str]
) -> None:
    """``new_callable=MagicMock + return_value=tuple`` 도 위반 — codex review
    attempt 4 finding 1.

    ``patch`` 는 ``new_callable()`` 결과에 ``return_value=tuple`` 을 설정하므로
    callable 종류와 무관하게 동일 anti-pattern. ``AsyncMock`` 만 별도 카테고리,
    나머지는 통합 ``tuple-return-on-patch`` 보고.
    """
    src = f"""
        from unittest.mock import MagicMock, patch

        def test_x():
            with patch(
                "{TARGET}",
                new_callable=MagicMock,
                return_value=(1, 2, 3, 4),
            ):
                pass
        """
    p = _write(tmp_path, src)
    vs = scan_file(p, allowlist)
    assert len(vs) == 1, [v.format() for v in vs]
    assert vs[0].kind == "tuple-return-on-patch"
    assert vs[0].target == TARGET


def test_new_callable_mock_tuple_return_is_violation(
    tmp_path: Path, allowlist: set[str]
) -> None:
    """``new_callable=Mock + return_value=tuple`` (generic ``Mock``) 도 위반.

    Python ``unittest.mock`` 의 ``Mock`` 도 동일 메커니즘으로 ``return_value`` 가
    호출 결과를 결정한다. scanner 는 callable identity 와 무관하게 ``return_value
    =tuple`` 형태를 통합 catch.
    """
    src = f"""
        from unittest.mock import Mock, patch

        def test_x():
            with patch(
                "{TARGET}",
                new_callable=Mock,
                return_value=(1, 2, 3, 4),
            ):
                pass
        """
    p = _write(tmp_path, src)
    vs = scan_file(p, allowlist)
    assert len(vs) == 1, [v.format() for v in vs]
    assert vs[0].kind == "tuple-return-on-patch"
    assert vs[0].target == TARGET


def test_new_callable_custom_factory_tuple_return_is_violation(
    tmp_path: Path, allowlist: set[str]
) -> None:
    """``new_callable=<custom_callable> + return_value=tuple`` 도 위반.

    Custom factory 객체 (이름이 ``MagicMock``/``AsyncMock``/``Mock`` 아님) 에도
    ``return_value=tuple`` 이 설정되면 동일 anti-pattern.
    """
    src = f"""
        from unittest.mock import patch

        class MyFactory:
            pass

        def test_x():
            with patch(
                "{TARGET}",
                new_callable=MyFactory,
                return_value=(1, 2, 3, 4),
            ):
                pass
        """
    p = _write(tmp_path, src)
    vs = scan_file(p, allowlist)
    assert len(vs) == 1, [v.format() for v in vs]
    assert vs[0].kind == "tuple-return-on-patch"
    assert vs[0].target == TARGET


# ── Attempt 4 Finding 2: decorator slot mapping accuracy ────────────────────


def test_decorator_with_new_kwarg_skips_slot(
    tmp_path: Path, allowlist: set[str]
) -> None:
    """``@patch(target, new=X)`` 는 mock arg slot 자체를 소비하지 않는다.

    codex review attempt 4 finding 2: ``new=`` 가 지정된 decorator 는 mock arg
    를 주입하지 않으므로 후속 decorator 의 slot 매핑이 한 칸 앞당겨져야 한다.

    예::

        @patch("X.fn1", new=stub)        # no slot (new 지정)
        @patch("Y.fn2")                  # slot 0 (innermost-first)
        def test(self, mock_fn2): ...    # ← mock_fn2 가 fn2 에 매핑

    여기서 ``fn2`` 가 allowlist 의 TARGET 이면 ``mock_fn2.return_value = tuple``
    body 할당이 위반이어야 한다. 만약 scanner 가 ``new=`` slot 을 잘못 소비하면
    mock_fn2 가 fn1 (new 지정) 에 매핑되어 위반을 놓친다.
    """
    src = f"""
        from unittest.mock import patch

        def stub():
            ...

        class TestX:
            @patch("ante.cli.commands.unrelated.helper", new=stub)
            @patch("{TARGET}")
            def test_y(self, mock_target):
                mock_target.return_value = (1, 2, 3, 4)
        """
    p = _write(tmp_path, src)
    vs = scan_file(p, allowlist)
    assert len(vs) == 1, [v.format() for v in vs]
    assert vs[0].kind == "tuple-return-on-patch-decorator-alias"
    assert vs[0].target == TARGET


def test_decorator_with_new_callable_includes_slot_and_alias(
    tmp_path: Path, allowlist: set[str]
) -> None:
    """``@patch(target, new_callable=MagicMock)`` 은 mock arg slot 소비 + alias
    검사 대상.

    codex review attempt 4 finding 2: ``new_callable=`` 은 ``new=`` 와 달리
    mock arg 를 주입한다 (``new_callable()`` 결과). 따라서 slot 을 소비하고
    body 의 ``alias.return_value = tuple`` 할당도 검사해야 한다.
    """
    src = f"""
        from unittest.mock import MagicMock, patch

        class TestX:
            @patch("{TARGET}", new_callable=MagicMock)
            def test_y(self, mock_target):
                mock_target.return_value = (1, 2, 3, 4)
        """
    p = _write(tmp_path, src)
    vs = scan_file(p, allowlist)
    assert len(vs) == 1, [v.format() for v in vs]
    assert vs[0].kind == "tuple-return-on-patch-decorator-alias"
    assert vs[0].target == TARGET


def test_decorator_stack_mixed_new_and_new_callable_maps_correctly(
    tmp_path: Path, allowlist: set[str]
) -> None:
    """``new=`` / ``new_callable=`` / no-new 혼합 stack 의 slot 매핑 정확성.

    codex review attempt 4 finding 2 — 종합 케이스::

        @patch("U.fn0", new=stub_obj)            # no slot
        @patch("V.fn1", new_callable=MagicMock)  # slot 0
        @patch("TARGET")                         # slot 1 (innermost-first)
        def test(self, mock_target, mock_fn1): ...

    ``mock_target`` → ``TARGET`` (innermost), ``mock_fn1`` → V.fn1.
    body 에서 ``mock_target.return_value = tuple`` 이 위반.
    """
    src = f"""
        from unittest.mock import MagicMock, patch

        def stub_obj():
            ...

        class TestX:
            @patch("ante.cli.commands.unrelated.helper_a", new=stub_obj)
            @patch("ante.cli.commands.unrelated.helper_b", new_callable=MagicMock)
            @patch("{TARGET}")
            def test_y(self, mock_target, mock_fn1):
                mock_target.return_value = (1, 2, 3, 4)
                mock_fn1.return_value = (9, 9)  # allowlist 밖 → 무시
        """
    p = _write(tmp_path, src)
    vs = scan_file(p, allowlist)
    # 오직 TARGET 의 alias body 할당만 위반 (다른 두 patch 는 allowlist 밖)
    assert len(vs) == 1, [v.format() for v in vs]
    assert vs[0].kind == "tuple-return-on-patch-decorator-alias"
    assert vs[0].target == TARGET


# ── Attempt 4 Finding 3: 2-pass stub collection (file order independence) ────


def test_patch_with_stub_defined_below_detected(
    tmp_path: Path, allowlist: set[str]
) -> None:
    """``new=<stub>`` 의 stub 정의가 patch site 보다 파일 아래에 있어도 검출.

    codex review attempt 4 finding 3: scanner 가 ``visitor.visit(tree)`` 진행
    중 stub 을 수집하면 patch site 검사 시점에 아직 등록되지 않아 위반을 놓친다.
    ``scan_file`` 이 2-pass 로 동작하면 (pre-collect → visit) 파일 순서와
    무관하게 stub 참조가 resolve 된다.

    여기서는 ``_stub_below`` 가 ``@asynccontextmanager`` 도 아니고 ``ctx=`` kwarg
    도 받지 않으므로 ``async-def-stub-not-ctxmgr`` 위반이어야 한다.
    """
    src = f"""
        from unittest.mock import patch

        def test_x():
            with patch("{TARGET}", new=_stub_below):
                pass

        async def _stub_below():
            # async ctxmgr 가 아니라 단순 coroutine.
            return (1, 2, 3, 4)
        """
    p = _write(tmp_path, src)
    vs = scan_file(p, allowlist)
    # _stub_below 가 ctxmgr 가 아니므로 위반 1건 검출.
    assert len(vs) == 1, [v.format() for v in vs]
    assert vs[0].kind == "async-def-stub-not-ctxmgr"
    assert vs[0].target == TARGET


# ── Attempt 5 Finding 1: target-specific stub call-signature validation ──────


# treasury._create_treasury 는 ``account_id`` positional + ``*, ctx`` kwarg-only.
# allowlist 에 들어있어 시그니처 매칭 테스트의 production 모사로 활용한다.
TREASURY_TARGET = "ante.cli.commands.treasury._create_treasury"


def test_stub_missing_production_positional_arg_is_violation(
    tmp_path: Path, allowlist: set[str]
) -> None:
    """``new=<stub>`` 의 stub 이 production 의 positional arg 를 받지 못하면
    호출 시 ``TypeError`` 발생. scanner 가 ``async-stub-positional-arity-
    mismatch`` 위반으로 잡아야 한다.

    예: ``treasury._create_treasury(account_id, *, ctx)`` 의 stub 이 ``ctx=None``
    만 받으면 production 이 ``stub("acc", ctx=ctx)`` 호출 시 fail.
    """
    src = f"""
        from contextlib import asynccontextmanager
        from unittest.mock import patch

        @asynccontextmanager
        async def _stub(ctx=None):
            yield ("t", "db")

        def test_x():
            with patch("{TREASURY_TARGET}", new=_stub):
                pass
        """
    p = _write(tmp_path, src)
    vs = scan_file(p, allowlist)
    assert len(vs) == 1, [v.format() for v in vs]
    assert vs[0].kind == "async-stub-positional-arity-mismatch"
    assert vs[0].target == TREASURY_TARGET


def test_stub_with_vararg_swallows_positional_not_violation(
    tmp_path: Path, allowlist: set[str]
) -> None:
    """stub 이 ``*args`` 를 가지면 production positional 을 모두 swallow.

    이 경우 ``ctx`` 가 production 에서 kwarg-only 라도 stub 이 ``**kwargs`` /
    ``ctx=`` kwarg 도 받으면 OK. 여기서는 ``*args, **kwargs`` 형태로 통과를
    기대한다.
    """
    src = f"""
        from contextlib import asynccontextmanager
        from unittest.mock import patch

        @asynccontextmanager
        async def _stub(*args, **kwargs):
            yield ("t", "db")

        def test_x():
            with patch("{TREASURY_TARGET}", new=_stub):
                pass
        """
    p = _write(tmp_path, src)
    vs = scan_file(p, allowlist)
    assert vs == [], [v.format() for v in vs]


def test_stub_with_exact_positional_match_not_violation(
    tmp_path: Path, allowlist: set[str]
) -> None:
    """stub 이 production positional args 를 같은 이름으로 정확히 받으면 통과.

    treasury: ``account_id`` positional + ``ctx`` kwonly. stub 이 같은 시그니처
    를 재현하면 호환.
    """
    src = f"""
        from contextlib import asynccontextmanager
        from unittest.mock import patch

        @asynccontextmanager
        async def _stub(account_id, *, ctx=None):
            yield ("t", "db")

        def test_x():
            with patch("{TREASURY_TARGET}", new=_stub):
                pass
        """
    p = _write(tmp_path, src)
    vs = scan_file(p, allowlist)
    assert vs == [], [v.format() for v in vs]


def test_stub_with_ctx_only_for_ctx_first_target_not_violation(
    tmp_path: Path, allowlist: set[str]
) -> None:
    """production positional 이 단일 ``ctx`` 인 factory 의 stub 은 ``ctx=None``
    만 받아도 OK (``await factory(ctx=ctx)`` 또는 ``factory(ctx)`` 둘 다 가능).

    예: ``bot._create_services(ctx)`` 의 stub 이 ``ctx=None`` 만 받아도 호환.
    """
    src = f"""
        from contextlib import asynccontextmanager
        from unittest.mock import patch

        @asynccontextmanager
        async def _stub(ctx=None):
            yield (1, 2, 3, 4)

        def test_x():
            with patch("{TARGET}", new=_stub):
                pass
        """
    p = _write(tmp_path, src)
    vs = scan_file(p, allowlist)
    assert vs == [], [v.format() for v in vs]


def test_side_effect_stub_positional_arity_mismatch_is_violation(
    tmp_path: Path, allowlist: set[str]
) -> None:
    """``side_effect=<stub>`` 에도 동일한 positional arity 검증 적용.

    treasury 의 ``side_effect`` stub 이 ``ctx`` kwarg-only 만 받으면 ``account_id``
    positional 누락으로 fail.
    """
    src = f"""
        from contextlib import asynccontextmanager
        from unittest.mock import patch

        @asynccontextmanager
        async def _stub(*, ctx=None):
            yield ("t", "db")

        def test_x():
            with patch("{TREASURY_TARGET}", side_effect=_stub):
                pass
        """
    p = _write(tmp_path, src)
    vs = scan_file(p, allowlist)
    assert len(vs) == 1, [v.format() for v in vs]
    assert vs[0].kind == "async-stub-side-effect-positional-arity-mismatch"
    assert vs[0].target == TREASURY_TARGET


# ── Attempt 5 Finding 2: class-level @patch decorator method body mapping ────


def test_class_decorator_patch_method_body_assignment_is_violation(
    tmp_path: Path, allowlist: set[str]
) -> None:
    """class-level ``@patch("target")`` 데코레이터가 클래스 내 모든 test method
    의 body 에 mock arg 를 주입한다 (codex review attempt 5 finding 2).

    body 의 ``mock_arg.return_value = tuple`` 도 위반으로 잡아야 한다.
    """
    src = f"""
        from unittest.mock import patch

        @patch("{TARGET}")
        class TestX:
            def test_a(self, mock_services):
                mock_services.return_value = (1, 2, 3, 4)
        """
    p = _write(tmp_path, src)
    vs = scan_file(p, allowlist)
    assert len(vs) == 1, [v.format() for v in vs]
    assert vs[0].kind == "tuple-return-on-patch-decorator-alias"
    assert vs[0].target == TARGET


def test_class_decorator_stack_methods_mapped_correctly(
    tmp_path: Path, allowlist: set[str]
) -> None:
    """다중 class-level ``@patch(...)`` decorator stack — innermost-first 매핑.

    여러 method 가 같은 stack 을 공유하며, 각 method 의 self 다음 인자에
    innermost-first 로 매핑된다.
    """
    other_target = next(t for t in allowlist if t.endswith(".system._create_services"))
    src = f"""
        from unittest.mock import patch

        @patch("{TARGET}")              # outer
        @patch("{other_target}")        # innermost (적용 먼저)
        class TestX:
            def test_a(self, mock_inner, mock_outer):
                # innermost = other_target, outer = TARGET
                mock_inner.return_value = (1, 2)
                mock_outer.return_value = (1, 2, 3, 4)

            def test_b(self, mock_inner, mock_outer):
                # 별도 method 에서도 같은 매핑
                mock_outer.return_value = (9, 9, 9, 9)
        """
    p = _write(tmp_path, src)
    vs = scan_file(p, allowlist)
    # test_a 에서 2건 + test_b 에서 1건 = 3건
    assert len(vs) == 3, [v.format() for v in vs]
    kinds = {v.kind for v in vs}
    targets = {v.target for v in vs}
    assert kinds == {"tuple-return-on-patch-decorator-alias"}
    assert targets == {TARGET, other_target}


def test_class_decorator_with_method_decorator_combined_mapping(
    tmp_path: Path, allowlist: set[str]
) -> None:
    """method-level + class-level decorator 가 같이 있는 경우 매핑 순서.

    method args = ``self`` + method-decorator slots (innermost-first) +
    class-decorator slots (innermost-first).

    여기서:

    * method-level @patch("ipc_helpers.IPCClient") (innermost method) → mock_ipc
    * class-level @patch("TARGET") (class decorator) → mock_services

    method body 에서 ``mock_services.return_value = tuple`` 만 위반.
    """
    src = f"""
        from unittest.mock import patch

        @patch("{TARGET}")
        class TestX:
            @patch("ante.cli.commands.ipc_helpers.IPCClient")
            def test_a(self, mock_ipc, mock_services):
                mock_services.return_value = (1, 2, 3, 4)
                mock_ipc.return_value = (9, 9)  # allowlist 밖 → 무시
        """
    p = _write(tmp_path, src)
    vs = scan_file(p, allowlist)
    assert len(vs) == 1, [v.format() for v in vs]
    assert vs[0].kind == "tuple-return-on-patch-decorator-alias"
    assert vs[0].target == TARGET


def test_class_decorator_with_new_kwarg_skips_slot(
    tmp_path: Path, allowlist: set[str]
) -> None:
    """class-level ``@patch(target, new=X)`` 는 slot 자체 소비 안 함.

    method args 매핑 시 class decorator slot 도 ``new=`` 면 skip 되어야 한다.
    """
    src = f"""
        from unittest.mock import patch

        def stub_obj():
            ...

        @patch("ante.cli.commands.unrelated.helper", new=stub_obj)  # no slot
        @patch("{TARGET}")                                          # slot 0
        class TestX:
            def test_a(self, mock_services):
                # mock_services 는 TARGET 에 매핑 (new= 가 slot 소비 안 함)
                mock_services.return_value = (1, 2, 3, 4)
        """
    p = _write(tmp_path, src)
    vs = scan_file(p, allowlist)
    assert len(vs) == 1, [v.format() for v in vs]
    assert vs[0].kind == "tuple-return-on-patch-decorator-alias"
    assert vs[0].target == TARGET


def test_class_decorator_non_allowlist_target_not_violation(
    tmp_path: Path, allowlist: set[str]
) -> None:
    """class decorator 가 allowlist 밖 target 이면 mock arg slot 은 소비되지만
    위반 아님.
    """
    src = """
        from unittest.mock import patch

        @patch("ante.cli.commands.unrelated.helper")
        class TestX:
            def test_a(self, mock_helper):
                mock_helper.return_value = (1, 2)
        """
    p = _write(tmp_path, src)
    vs = scan_file(p, allowlist)
    assert vs == [], [v.format() for v in vs]
