"""CLI offline command DB lifecycle async context manager."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import click

from ante.core.database import Database

_ORIGINAL_DATABASE = Database

__all__ = ["open_cli_db", "Database"]


@asynccontextmanager
async def open_cli_db(
    ctx: click.Context,
    *,
    read_only: bool = False,
    db_path_override: str | None = None,
) -> AsyncIterator[Database]:
    """CLI offline command DB lifecycle context manager.

    Cleanup invariant:
        - normal exit / exception / cancellation (BaseException) 모든 경로에서
          ``Database.close()``를 호출한다.
        - ``close()`` 자체가 예외를 던져도 body의 원래 예외를 가리지 않는다.

    Raises:
        ValueError: ``ctx is None``.
    """
    if ctx is None:
        raise ValueError(
            "open_cli_db requires explicit Click context (legacy fallback deprecated)"
        )
    from ante.cli import main as _cli_main
    from ante.core import database as _core_db

    db_path = (
        db_path_override if db_path_override is not None else _cli_main.get_db_path(ctx)
    )
    _local_db_cls = globals().get("Database", _ORIGINAL_DATABASE)
    _module_db_cls = _core_db.Database
    if _local_db_cls is not _ORIGINAL_DATABASE:
        _db_cls = _local_db_cls
    elif _module_db_cls is not _ORIGINAL_DATABASE:
        _db_cls = _module_db_cls
    else:
        _db_cls = _ORIGINAL_DATABASE
    if read_only:
        db = _db_cls(db_path, read_only=True)
    else:
        db = _db_cls(db_path)
    await db.connect()
    try:
        yield db
    except BaseException:
        try:
            await db.close()
        except Exception:
            pass
        raise
    else:
        await db.close()
