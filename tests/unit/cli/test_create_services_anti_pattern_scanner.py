"""``scripts/scan_create_services_anti_pattern.py`` 자체 회귀 테스트 (#1900).

scanner 가 새로 검출해야 하는 ``patch(...)`` 형태를 fixture 소스로 만들어
``scan_paths`` 가 위반을 정확히 보고하고, 기존 PASS 케이스(올바른 helper
사용)는 그대로 통과시키는지 확인한다.

Codex 브랜치 리뷰 attempt 1 finding 2건:

* Finding 1: ``patch(target, return_value=(db, ...))`` (default MagicMock + tuple
  return_value) 가 누락되어 회귀 검출 실패
* Finding 2: ``patch(target, MagicMock(return_value=(db, ...)))`` (2번째
  positional ``new``) 가 누락되어 회귀 검출 실패
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
