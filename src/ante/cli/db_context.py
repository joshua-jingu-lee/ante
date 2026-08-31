"""CLI offline command DB lifecycle async context manager.

Spec / SSOT:
- 부모 에픽: #1818 (CLI offline command factory)
- 선행 contract: docs/specs/contracts/offline-factory.md (#1854)
- DB path resolver: :func:`ante.cli.main.get_db_path`
- Database lifecycle: :class:`ante.core.database.Database`
- cleanup 패턴 선례: #1722 ``_create_account_service`` + #1755 ``except BaseException``

본 helper는 반복되는 ``Database(get_db_path(...))`` + manual ``close()`` 패턴을
async context manager로 캡슐화한다.

Codex Plan Review v2 lock:
1. ``ctx``는 mandatory (None 명시 거부, legacy ``get_db_path()`` fallback 의존 안 함).
2. cleanup은 ``except BaseException``으로 ``asyncio.CancelledError``까지 catch한다.
3. ``Database.close()``가 실패해도 원래 body 예외를 가린다거나 chain되지 않도록
   inner try/except로 ``close()`` 실패를 무시하고 원래 예외만 surface한다.
4. ``read_only=True``일 때만 ``Database(db_path, read_only=True)``로 전달한다
   (#1974 offline-factory.md §2 옵션 A — Database read-only 연결 모드 채택).
   ``read_only=False``이면 기존 ``Database(db_path)`` 호출을 byte-for-byte
   유지한다(kwarg 미전달 — #1856/#1857 patch 호환 및 모든 write 소비자 무영향
   invariant). read-only 모드는 기존 스키마를 부트스트랩 없이 읽는 offline read
   명령(현재 ``backtest history`` — #1974, ``data list`` 의 종목명 보강 — #1984,
   ``report list``/``report view`` — #2114)에만 적용된다 — §4 예외 service
   (`AccountService`/`MemberService`/`ApprovalService`/`AuditLogger`/
   `DynamicConfigService`)는 ``initialize()``가 schema DDL을 발화해야 read가
   가능하므로 schema 분리 전까지 ``read_only=True`` 대상이 아니다.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import click

# ``Database`` 는 ``open_cli_db`` 내부에서 lazy import 되며, 동시에 본 모듈에
# 속성으로 노출되어야 한다 (#1856 ``patch("ante.cli.db_context.Database")``
# 테스트 호환). lazy lookup 은 ``open_cli_db`` 가 매 호출마다
# ``ante.core.database.Database`` 를 다시 가져오도록 한다.
from ante.core.database import Database

# import-time binding 사본. lazy lookup 에서 ``globals()['Database']`` 가
# 원본인지 patch 된 mock 인지 식별하는 reference 다.
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

    Args:
        ctx: Click 컨텍스트 (mandatory). ``--config-dir`` / ``ANTE_CONFIG_DIR``
            를 통해 결정된 DB 경로를 ``get_db_path(ctx)``로 해석한다.
            ``None``을 전달하면 ``ValueError``를 발생시킨다 — legacy 암시
            fallback에 의존하지 않는다.
        read_only: ``True`` 면 ``Database(db_path, read_only=True)`` 로 전달해
            SQLite ``mode=ro`` 단일 reader 연결을 열고 schema/WAL 쓰기를 회피한다
            (#1974 offline-factory.md §2 옵션 A — Database read-only 연결 모드).
            ``False`` (기본) 이면 기존 ``Database(db_path)`` 호출을
            byte-for-byte 유지한다 (kwarg 미전달, 모든 write 소비자 무영향).
            read-only 모드는 기존 스키마를 부트스트랩 없이 읽는 offline read
            명령(현재 ``backtest history`` — #1974, ``data list`` 의 종목명 보강
            — #1984, ``report list``/``report view`` — #2114)에만 사용한다 — §4
            예외 service 는 schema 분리 전까지 ``read_only=True`` 대상이 아니다.
        db_path_override: optional 명시 DB 경로. ``None`` 이면
            ``get_db_path(ctx)`` 로 해석한다. ``approval list/info/review/
            audit-types`` 등 ``--db-path`` Click option 을 지원하는 명령은
            caller 가 본 인자에 명시 경로를 전달해 ctx 의 기본 resolution 을
            override 한다 (offline-factory.md §1.1 — factory 는 Click option
            parsing 을 직접 수행하지 않으며, caller 가 산출한 경로를 입력으로
            받는다).

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
    # #1857: lazy module-attribute access for ``get_db_path`` /
    # ``Database`` to honor test patches of either:
    #   - ``ante.cli.main.get_db_path`` (callsite import binding)
    #   - ``ante.cli.db_context.Database`` (#1856 db_path_override 테스트)
    #   - ``ante.core.database.Database`` (constructor patch — #1857 호환)
    from ante.cli import main as _cli_main
    from ante.core import database as _core_db

    db_path = (
        db_path_override if db_path_override is not None else _cli_main.get_db_path(ctx)
    )
    # patch 우선순위 (둘 다 동시에 patch 되는 경우는 없다고 가정):
    #   1) ``ante.cli.db_context.Database`` 가 patch 된 경우 (#1856 테스트):
    #      ``globals()['Database']`` 가 ``_ORIGINAL_DATABASE`` 와 다른 객체.
    #   2) ``ante.core.database.Database`` 가 patch 된 경우 (#1857 회귀
    #      테스트): ``_core_db.Database`` 가 ``_ORIGINAL_DATABASE`` 와 다름.
    #   3) 둘 다 미patch: 원본 ``Database`` 사용.
    _local_db_cls = globals().get("Database", _ORIGINAL_DATABASE)
    _module_db_cls = _core_db.Database
    if _local_db_cls is not _ORIGINAL_DATABASE:
        _db_cls = _local_db_cls
    elif _module_db_cls is not _ORIGINAL_DATABASE:
        _db_cls = _module_db_cls
    else:
        _db_cls = _ORIGINAL_DATABASE
    # #1974: ``read_only=True`` 일 때만 ``read_only`` kwarg 를 전달한다. False
    # 경로는 기존 ``_db_cls(db_path)`` 호출을 byte-for-byte 유지해 모든 write
    # 소비자·#1856/#1857 patch(mock) 호환을 보존한다 (offline-factory.md §2 옵션 A).
    if read_only:
        db = _db_cls(db_path, read_only=True)
    else:
        db = _db_cls(db_path)
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
