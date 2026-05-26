"""CLI offline command DB lifecycle async context manager.

Spec / SSOT:
- 부모 에픽: #1818 (CLI offline command factory)
- 선행 contract: docs/specs/contracts/offline-factory.md (#1854)
- DB path resolver: :func:`ante.cli.main.get_db_path`
- Database lifecycle: :class:`ante.core.database.Database`
- cleanup 패턴 선례: #1722 ``_create_account_service`` + #1755 ``except BaseException``

본 helper는 반복되는 ``Database(get_db_path(...))`` + manual ``close()`` 패턴을
async context manager로 캡슐화한다. 후속 callsite migration은 #1856/#1857
에서 다룬다 — 본 PR scope는 helper 추가만이다.

Codex Plan Review v2 lock:
1. ``ctx``는 mandatory (None 명시 거부, legacy ``get_db_path()`` fallback 의존 안 함).
2. cleanup은 ``except BaseException``으로 ``asyncio.CancelledError``까지 catch한다.
3. ``Database.close()``가 실패해도 원래 body 예외를 가린다거나 chain되지 않도록
   inner try/except로 ``close()`` 실패를 무시하고 원래 예외만 surface한다.
4. ``read_only``는 caller hint metadata일 뿐, ``Database`` 생성자에는 전달하지
   않는다 (#1854 contract 옵션 B — Database API 변경 금지).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import click

from ante.cli.main import get_db_path
from ante.core.database import Database

__all__ = ["open_cli_db"]


@asynccontextmanager
async def open_cli_db(
    ctx: click.Context,
    *,
    read_only: bool = False,
) -> AsyncIterator[Database]:
    """CLI offline command DB lifecycle context manager.

    Args:
        ctx: Click 컨텍스트 (mandatory). ``--config-dir`` / ``ANTE_CONFIG_DIR``
            를 통해 결정된 DB 경로를 ``get_db_path(ctx)``로 해석한다.
            ``None``을 전달하면 ``ValueError``를 발생시킨다 — legacy 암시
            fallback에 의존하지 않는다.
        read_only: caller hint. ``Database`` 생성자에는 전달되지 않으며,
            현재는 메타데이터로만 유지된다 (#1854 contract 옵션 B). 후속
            이슈에서 read-only enforcement가 필요하면 이 플래그를 통해
            확장한다.

    Yields:
        ``connect()``가 완료된 :class:`Database` 인스턴스.

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
    # ``read_only`` is a caller hint only; it is intentionally not forwarded
    # to ``Database.__init__`` per #1854 contract option B (no Database API
    # signature change in this PR scope).
    _ = read_only
    db_path = get_db_path(ctx)
    db = Database(db_path)
    await db.connect()
    try:
        yield db
    except BaseException:
        # ``close()`` 실패가 원래 예외(BaseException 포함, CancelledError 등)를
        # 가리지 않도록 inner try/except로 swallow한다. close 실패는 lifecycle
        # leak이지만 caller에게 surface해야 할 것은 body의 원래 예외다.
        try:
            await db.close()
        except Exception:
            pass
        raise
    else:
        await db.close()
