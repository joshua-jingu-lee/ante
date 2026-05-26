"""Tests for :func:`ante.cli.db_context.open_cli_db` lifecycle context manager.

Plan v2 SSOT — 8 시나리오:
1. ``open_cli_db``가 connect된 :class:`Database`를 yield 한다.
2. normal exit에서 ``close()``가 호출된다.
3. body 예외가 발생해도 ``close()``가 호출된다.
4. ``asyncio.CancelledError`` cancellation 경로에서도 ``close()``가 호출된다.
5. ``get_db_path(ctx)``가 ctx로부터 명시적으로 resolve된다 (``--config-dir``).
6. ``read_only=True``는 ``Database.__init__``에 전달되지 않는다 (#1854 옵션 B).
7. ``ctx=None``은 ``ValueError``로 명시적으로 거부된다 (legacy fallback 의존 안 함).
8. body 예외와 ``db.close()`` 실패가 함께 발생할 때 body 예외만 surface한다.

본 테스트는 ``open_cli_db`` helper 자체의 lifecycle invariant만 검증한다.
기존 22 callsite 변경/migration은 #1856/#1857에서 다룬다.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import click
import pytest

from ante.cli.db_context import open_cli_db
from ante.cli.main import cli


def _make_ctx_with_config_dir(config_dir: Path) -> click.Context:
    """root ``cli`` group을 사용해 ``--config-dir``가 반영된 ctx를 만든다."""
    ctx = click.Context(cli, obj={"config_dir": config_dir})
    return ctx


def _bootstrap_config_dir(tmp_path: Path) -> Path:
    """`ante init` 결과와 동등한 최소 config_dir 구조를 만든다.

    ``get_db_path``는 system.toml 부재 시 default ``<config_dir>/db/ante.db``로
    폴백하므로 (Config.load 기본값) 별도 system.toml 작성은 불필요하다.
    db 디렉토리만 미리 만들어 ``Database.connect``가 실패하지 않도록 한다.
    """
    cfg_dir = tmp_path / "cfg"
    (cfg_dir / "db").mkdir(parents=True, exist_ok=True)
    return cfg_dir


@pytest.mark.asyncio
async def test_open_cli_db_yields_connected_database(tmp_path: Path) -> None:
    """1) ``open_cli_db``가 yield하는 객체는 connect된 Database 인스턴스다."""
    cfg_dir = _bootstrap_config_dir(tmp_path)
    ctx = _make_ctx_with_config_dir(cfg_dir)
    async with open_cli_db(ctx) as db:
        # writer/reader 연결이 살아 있어 fetch 가능해야 한다.
        row = await db.fetch_one("SELECT 1 AS one")
        assert row == {"one": 1}


@pytest.mark.asyncio
async def test_open_cli_db_closes_on_normal_exit(tmp_path: Path) -> None:
    """2) normal exit path에서 ``Database.close()``가 호출된다."""
    cfg_dir = _bootstrap_config_dir(tmp_path)
    ctx = _make_ctx_with_config_dir(cfg_dir)
    captured: dict[str, Any] = {}
    with patch("ante.cli.db_context.Database") as db_cls:
        instance = db_cls.return_value
        instance.connect = AsyncMock()
        instance.close = AsyncMock()
        captured["instance"] = instance
        async with open_cli_db(ctx) as db:
            assert db is instance
    captured["instance"].connect.assert_awaited_once()
    captured["instance"].close.assert_awaited_once()


@pytest.mark.asyncio
async def test_open_cli_db_closes_on_exception(tmp_path: Path) -> None:
    """3) body에서 일반 예외가 발생해도 ``close()``가 호출된다."""
    cfg_dir = _bootstrap_config_dir(tmp_path)
    ctx = _make_ctx_with_config_dir(cfg_dir)
    with patch("ante.cli.db_context.Database") as db_cls:
        instance = db_cls.return_value
        instance.connect = AsyncMock()
        instance.close = AsyncMock()

        class _BodyError(RuntimeError):
            pass

        with pytest.raises(_BodyError):
            async with open_cli_db(ctx):
                raise _BodyError("boom")
        instance.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_open_cli_db_closes_on_cancellation(tmp_path: Path) -> None:
    """4) ``asyncio.CancelledError`` (BaseException 계열)도 close를 보장한다."""
    cfg_dir = _bootstrap_config_dir(tmp_path)
    ctx = _make_ctx_with_config_dir(cfg_dir)
    with patch("ante.cli.db_context.Database") as db_cls:
        instance = db_cls.return_value
        instance.connect = AsyncMock()
        instance.close = AsyncMock()

        with pytest.raises(asyncio.CancelledError):
            async with open_cli_db(ctx):
                raise asyncio.CancelledError()
        instance.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_open_cli_db_uses_ctx_db_path(tmp_path: Path) -> None:
    """5) ``get_db_path(ctx)``가 ctx로부터 resolve되어 Database에 전달된다."""
    cfg_dir = _bootstrap_config_dir(tmp_path)
    ctx = _make_ctx_with_config_dir(cfg_dir)
    expected_db_path = str(cfg_dir / "db" / "ante.db")
    with patch("ante.cli.db_context.Database") as db_cls:
        instance = db_cls.return_value
        instance.connect = AsyncMock()
        instance.close = AsyncMock()
        async with open_cli_db(ctx):
            pass
    db_cls.assert_called_once_with(expected_db_path)


@pytest.mark.asyncio
async def test_open_cli_db_read_only_not_passed_to_database_init(
    tmp_path: Path,
) -> None:
    """6) ``read_only=True``는 hint일 뿐 ``Database.__init__``에 전달되지 않는다.

    #1854 contract 옵션 B — Database API 시그니처 변경 금지.
    """
    cfg_dir = _bootstrap_config_dir(tmp_path)
    ctx = _make_ctx_with_config_dir(cfg_dir)
    expected_db_path = str(cfg_dir / "db" / "ante.db")
    with patch("ante.cli.db_context.Database") as db_cls:
        instance = db_cls.return_value
        instance.connect = AsyncMock()
        instance.close = AsyncMock()
        async with open_cli_db(ctx, read_only=True):
            pass
    # 위치 인자 1개(db_path)만 전달, read_only는 kwargs에 없어야 한다.
    db_cls.assert_called_once_with(expected_db_path)
    call = db_cls.call_args
    assert "read_only" not in call.kwargs


@pytest.mark.asyncio
async def test_open_cli_db_rejects_none_ctx() -> None:
    """7) ``ctx=None``은 ``ValueError``로 명시 거부된다 (legacy fallback 의존 안 함)."""
    with pytest.raises(ValueError, match="explicit Click context"):
        async with open_cli_db(None):  # type: ignore[arg-type]
            pass


@pytest.mark.asyncio
async def test_open_cli_db_preserves_original_exception_when_close_fails(
    tmp_path: Path,
) -> None:
    """8) body 예외 + ``close()`` 실패가 함께 발생해도 body의 원래 예외만 surface한다.

    ``close()`` 실패가 caller의 traceback을 가리거나 chain하지 않아야 한다.
    """
    cfg_dir = _bootstrap_config_dir(tmp_path)
    ctx = _make_ctx_with_config_dir(cfg_dir)

    class _BodyError(RuntimeError):
        pass

    class _CloseError(RuntimeError):
        pass

    with patch("ante.cli.db_context.Database") as db_cls:
        instance = db_cls.return_value
        instance.connect = AsyncMock()
        instance.close = AsyncMock(side_effect=_CloseError("close-failed"))

        with pytest.raises(_BodyError) as excinfo:
            async with open_cli_db(ctx):
                raise _BodyError("body-failed")
        # surface된 예외는 body의 _BodyError여야 한다.
        assert "body-failed" in str(excinfo.value)
        # close 실패는 swallow되었으므로 __context__/cause로 노출되지 않아야 한다
        # (inner try/except가 close 예외를 삼킨다).
        assert not isinstance(excinfo.value.__cause__, _CloseError)
