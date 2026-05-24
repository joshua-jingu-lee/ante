"""ante treasury — 자금 현황 조회/관리 커맨드."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict
from datetime import UTC, datetime, timedelta

import click

from ante.account.errors import AccountNotFoundError
from ante.cli._validators import (
    reject_invalid_account_id,
    reject_inverted_date_range,
    validate_iso_date,
    validate_nonnegative_finite_amount,
    validate_positive_finite_amount,
)
from ante.cli.formatter import format_option
from ante.cli.main import get_formatter
from ante.cli.middleware import get_member_id as _get_member_id
from ante.cli.middleware import require_auth, require_scope

logger = logging.getLogger(__name__)


@click.group()
def treasury() -> None:
    """자금 현황 조회·관리."""


def _run(coro):  # noqa: ANN001, ANN202
    return asyncio.run(coro)


async def _create_treasury(account_id: str | None = None):  # noqa: ANN202
    """CLI에서 Treasury를 생성하는 헬퍼.

    ``db.connect()`` 이후의 모든 라이프사이클(``AccountService.initialize`` /
    ``AccountService.get`` / ``Treasury.initialize`` 포함)을 ``except
    BaseException`` 블록으로 감싸 실패 시 ``db.close()``를 보장한다.
    valid-but-missing account_id(예: ``acc-9999``)가 들어오면
    ``account_service.get``이 :class:`AccountNotFoundError`를 raise하는데,
    이 때 aiosqlite 연결이 leak되어 asyncio 종료 시 busy_timeout 대기로 CLI
    프로세스가 6초 이상 hang하는 회귀를 차단한다(#1725). 본 패턴은
    ``_create_account_service`` (#1722) byte-for-byte 동형이다.
    """
    from ante.account.scoping import require_account_id
    from ante.account.service import AccountService
    from ante.cli.main import get_db_path
    from ante.core.database import Database
    from ante.eventbus.bus import EventBus
    from ante.treasury.treasury import Treasury

    validated_account_id = require_account_id(account_id, context="cli.treasury")

    db = Database(get_db_path())
    try:
        await db.connect()
        eventbus = EventBus()
        account_service = AccountService(db=db, eventbus=eventbus)
        await account_service.initialize()
        account = await account_service.get(validated_account_id)
        t = Treasury(
            db,
            eventbus,
            account_id=account.account_id,
            currency=account.currency,
            buy_commission_rate=float(account.buy_commission_rate),
            sell_commission_rate=float(account.sell_commission_rate),
        )
        await t.initialize()
    except BaseException:
        try:
            await db.close()
        except Exception:
            logger.debug(
                "db.close() after init failure raised — ignored", exc_info=True
            )
        raise
    return t, db


async def _create_treasury_manager():  # noqa: ANN202
    """CLI에서 TreasuryManager를 생성하는 헬퍼.

    ``_create_treasury`` 동형 cleanup 패턴(#1722). 현재 사용처
    (``budgets``/``portfolio value`` no-account 분기)는 valid-but-missing
    account_id를 직접 처리하지 않지만, defense-in-depth로 ``initialize_all``
    / ``account_service.list`` 등 lifecycle 실패 시에도 db.close를 보장한다.
    """
    from ante.account.service import AccountService
    from ante.cli.main import get_db_path
    from ante.core.database import Database
    from ante.eventbus.bus import EventBus
    from ante.treasury.manager import TreasuryManager

    db = Database(get_db_path())
    try:
        await db.connect()
        eventbus = EventBus()
        account_service = AccountService(db=db, eventbus=eventbus)
        await account_service.initialize()
        manager = TreasuryManager(db=db, eventbus=eventbus)
        await manager.initialize_all(await account_service.list())
    except BaseException:
        try:
            await db.close()
        except Exception:
            logger.debug(
                "db.close() after init failure raised — ignored", exc_info=True
            )
        raise
    return manager, db


@treasury.command()
@click.option("--account", "account_id", required=True, help="계좌 ID")
@format_option
@click.pass_context
@require_auth
@require_scope("treasury:read")
def status(ctx: click.Context, account_id: str) -> None:
    """자금 현황 요약."""
    fmt = get_formatter(ctx)

    # invalid account_id(`default`/패턴 위반/`""`)를 resource acquisition
    # 이전에 거부한다(#1635 Split B Layer 1). `_create_treasury`는 이미
    # `require_account_id`를 `db.connect()` 이전에 호출하지만(leak-free), CLI
    # 콜백이 non-Click `InvalidAccountIdError`를 명시적으로 catch하지 않아
    # traceback으로 새던 contract-drift를 본 ingress 거부가 닫는다. 에러코드는
    # #1633 SSOT `VALIDATION_ERROR`(helper가 `e.code` 재사용).
    reject_invalid_account_id(account_id, fmt, context="cli.treasury")

    async def _run_status() -> dict:
        t, db = await _create_treasury(account_id)
        try:
            return t.get_summary()
        finally:
            await db.close()

    # valid-but-missing account_id(예: `acc-9999`)는 `account_service.get`에서
    # `AccountNotFoundError`로 raise된다. Click 기본 핸들러가 typed exception을
    # 모르고 traceback/빈 stdout으로 새던 contract-drift를 본 매핑이 닫는다
    # (#1725). 에러코드는 `ACCOUNT_NOT_FOUND` SSOT.
    try:
        result = _run(_run_status())
    except AccountNotFoundError as e:
        fmt.error(str(e), code="ACCOUNT_NOT_FOUND")
        raise SystemExit(1) from e

    if fmt.is_json:
        fmt.output(result)
    else:
        click.echo(f"  계좌 잔고      : {result['account_balance']:>15,.0f}")
        click.echo(f"  매수 가능      : {result['purchasable_amount']:>15,.0f}")
        click.echo(f"  총 평가액      : {result['total_evaluation']:>15,.0f}")
        click.echo(f"  총 손익        : {result['total_profit_loss']:>15,.0f}")
        click.echo(f"  총 할당        : {result['total_allocated']:>15,.0f}")
        click.echo(f"  총 예약        : {result['total_reserved']:>15,.0f}")
        click.echo(f"  미할당         : {result['unallocated']:>15,.0f}")
        click.echo(f"  봇 수          : {result['bot_count']:>15d}")


@treasury.command("transactions")
@click.option("--account", "account_id", default=None, help="계좌 ID 필터")
@click.option(
    "--type",
    "tx_type",
    type=click.Choice(
        ["allocate", "deallocate", "release", "fill", "bot_stopped_release"]
    ),
    default=None,
    help="거래 유형 필터",
)
@click.option("--bot", "bot_id", default=None, help="봇 ID 필터")
@click.option("--from", "from_date", default=None, callback=validate_iso_date)
@click.option("--to", "to_date", default=None, callback=validate_iso_date)
@click.option("--limit", default=20, type=click.IntRange(1, 100), help="조회 수")
@click.option("--offset", default=0, type=click.IntRange(min=0), help="시작 offset")
@format_option
@click.pass_context
@require_auth
@require_scope("treasury:read")
def transactions(
    ctx: click.Context,
    account_id: str | None,
    tx_type: str | None,
    bot_id: str | None,
    from_date: str | None,
    to_date: str | None,
    limit: int,
    offset: int,
) -> None:
    """자금 변동 이력 조회."""
    fmt = get_formatter(ctx)
    if account_id is not None:
        account_id = reject_invalid_account_id(
            account_id, fmt, context="cli.treasury.transactions"
        )
    reject_inverted_date_range(from_date, to_date, fmt)

    async def _run_transactions() -> dict:
        from ante.cli.main import get_db_path
        from ante.core.database import Database

        db = Database(get_db_path(ctx))
        await db.connect()
        try:
            where: list[str] = []
            params: list[str | int] = []
            if account_id:
                where.append("account_id = ?")
                params.append(account_id)
            if tx_type:
                where.append("transaction_type = ?")
                params.append(tx_type)
            if bot_id:
                where.append("bot_id = ?")
                params.append(bot_id)
            if from_date:
                where.append("created_at >= ?")
                params.append(f"{from_date} 00:00:00")
            if to_date:
                where.append("created_at <= ?")
                params.append(f"{to_date} 23:59:59")
            where_sql = (" WHERE " + " AND ".join(where)) if where else ""
            try:
                count_row = await db.fetch_one(
                    f"SELECT COUNT(*) as cnt FROM treasury_transactions{where_sql}",
                    tuple(params),
                )
                rows = await db.fetch_all(
                    f"SELECT * FROM treasury_transactions{where_sql}"
                    " ORDER BY created_at DESC LIMIT ? OFFSET ?",
                    (*params, limit, offset),
                )
            except Exception as e:
                if "no such table" in str(e).lower():
                    return {"items": [], "total": 0}
                raise
            items = [
                {
                    "id": r["id"],
                    "account_id": r["account_id"],
                    "type": r["transaction_type"],
                    "bot_id": r["bot_id"],
                    "amount": r["amount"],
                    "description": r["description"],
                    "created_at": r["created_at"],
                }
                for r in rows
            ]
            return {"items": items, "total": int(count_row["cnt"]) if count_row else 0}
        finally:
            await db.close()

    result = _run(_run_transactions())
    if fmt.is_json:
        fmt.output(result)
    else:
        fmt.table(
            result["items"],
            ["created_at", "account_id", "type", "bot_id", "amount"],
        )


@treasury.command("budgets")
@click.option("--account", "account_id", default=None, help="계좌 ID 필터")
@format_option
@click.pass_context
@require_auth
@require_scope("treasury:read")
def budgets(ctx: click.Context, account_id: str | None) -> None:
    """봇별 예산 목록 조회."""
    fmt = get_formatter(ctx)
    if account_id is not None:
        account_id = reject_invalid_account_id(
            account_id, fmt, context="cli.treasury.budgets"
        )

    async def _run_budgets() -> dict:
        if account_id is not None:
            t, db = await _create_treasury(account_id)
            treasuries = [t]
        else:
            manager, db = await _create_treasury_manager()
            treasuries = manager.list_all()
        try:
            items = []
            for treasury_obj in treasuries:
                for budget in treasury_obj.list_budgets():
                    data = asdict(budget)
                    if hasattr(budget.last_updated, "isoformat"):
                        data["last_updated"] = budget.last_updated.isoformat()
                    items.append(data)
            return {"budgets": items}
        finally:
            await db.close()

    # valid-but-missing account_id(예: `acc-9999`)는 `_create_treasury` 내부의
    # `account_service.get`에서 `AccountNotFoundError`로 raise된다. Click 기본
    # 핸들러가 typed exception을 모르고 traceback/빈 stdout으로 새던
    # contract-drift를 본 매핑이 닫는다 (#1758, status/snapshot #1725 동형).
    # 에러코드는 `ACCOUNT_NOT_FOUND` SSOT.
    try:
        result = _run(_run_budgets())
    except AccountNotFoundError as e:
        fmt.error(str(e), code="ACCOUNT_NOT_FOUND")
        raise SystemExit(1) from e
    except Exception as e:
        fmt.error(str(e), code=getattr(e, "code", "TREASURY_ERROR"))
        raise SystemExit(1) from e

    if fmt.is_json:
        fmt.output(result)
    else:
        fmt.table(
            result["budgets"],
            ["account_id", "bot_id", "allocated", "available", "reserved"],
        )


@treasury.command("set-balance")
@click.argument("amount", type=float, callback=validate_nonnegative_finite_amount)
@click.option("--account", "account_id", required=True, help="계좌 ID")
@format_option
@click.pass_context
@require_auth
@require_scope("treasury:admin")
def set_balance(ctx: click.Context, amount: float, account_id: str) -> None:
    """계좌 총 잔고 수동 설정."""
    fmt = get_formatter(ctx)
    actor = _get_member_id(ctx)
    account_id = reject_invalid_account_id(
        account_id, fmt, context="cli.treasury.set_balance"
    )

    async def _run_set_balance() -> dict:
        from ante.cli.cold_path import is_active_runtime
        from ante.cli.commands.ipc_helpers import ipc_send

        if is_active_runtime():
            return await ipc_send(
                "treasury.set_balance",
                {"account_id": account_id, "balance": amount},
                actor=actor,
            )
        t, db = await _create_treasury(account_id)
        try:
            await t.set_account_balance(amount)
            return {
                "account_id": account_id,
                "total_balance": t.account_balance,
                "updated_at": datetime.now(UTC).isoformat(),
            }
        finally:
            await db.close()

    # valid-but-missing account_id 매핑은 status/snapshot/budgets와 동형이다
    # (#1758, #1725). Click/Exception fallback은 기존(#1722 IPC 분기)을 보존한다.
    try:
        result = _run(_run_set_balance())
    except click.ClickException as e:
        code = getattr(e, "ipc_error_code", "") or "IPC_ERROR"
        message = getattr(e, "ipc_error_message", None) or e.message
        fmt.error(message, code=code)
        raise SystemExit(1) from e
    except AccountNotFoundError as e:
        fmt.error(str(e), code="ACCOUNT_NOT_FOUND")
        raise SystemExit(1) from e
    except Exception as e:
        fmt.error(str(e), code=getattr(e, "code", "TREASURY_ERROR"))
        raise SystemExit(1) from e

    if fmt.is_json:
        fmt.output(result)
    else:
        click.echo(f"계좌 잔고 설정 완료: {account_id} {amount:,.0f}")


@treasury.command()
@click.argument("bot_id")
@click.argument("amount", type=float, callback=validate_positive_finite_amount)
@click.option("--account", "account_id", required=True, help="계좌 ID")
@click.pass_context
@require_auth
@require_scope("treasury:admin")
def allocate(ctx: click.Context, bot_id: str, amount: float, account_id: str) -> None:
    """봇에 예산 할당."""
    fmt = get_formatter(ctx)
    actor = _get_member_id(ctx)

    # #1656 E bucket defense-in-depth: invalid account_id(`default`/패턴
    # 위반/`""`)를 `ipc_send`(→`_handle_treasury_allocate`) 이전에 거부한다.
    # IPC handler가 1차 보증(handler-first require_account_id)하지만, CLI
    # ingress 거부는 clean early exit(traceback 부재) + #1634/#1635 동형
    # 방어선이다. `--account` required arg라 전 입력을 검증한다. 에러코드는
    # #1633 SSOT `VALIDATION_ERROR`(helper가 `e.code` 재사용).
    account_id = reject_invalid_account_id(
        account_id, fmt, context="cli.treasury.allocate"
    )

    async def _run_allocate() -> dict:
        from ante.cli.commands.ipc_helpers import ipc_send

        return await ipc_send(
            "treasury.allocate",
            {"account_id": account_id, "bot_id": bot_id, "amount": amount},
            actor=actor,
        )

    # #1809 (oracle A7 @ a5d8edf): ``Treasury.allocate`` 가 reject 시 typed
    # exception 을 raise 하고 IPC server 가 stable ``code``
    # (``TREASURY_INSUFFICIENT_BALANCE`` / ``TREASURY_INVALID_AMOUNT``) 로
    # envelope ``error`` 를 만들어 보낸다. ``ipc_send`` 는 그 envelope 을
    # ``ClickException.ipc_error_code`` / ``ipc_error_message`` 로 부착하여
    # raise 한다. 이전 ``except ClickException: raise`` 흐름은 middleware
    # fallback 에서 ``IPC_ERROR`` 로 표준화되어 stable code 가 surface 되지
    # 않았다. ``set_balance``/``snapshot``/``status`` (#1758/#1725) 와 동형
    # ``ipc_error_code`` 직접 매핑 패턴으로 일치시킨다.
    try:
        result = _run(_run_allocate())
    except click.ClickException as e:
        code = getattr(e, "ipc_error_code", "") or "IPC_ERROR"
        message = getattr(e, "ipc_error_message", None) or e.message
        fmt.error(message, code=code)
        raise SystemExit(1) from e
    except AccountNotFoundError as e:
        fmt.error(str(e), code="ACCOUNT_NOT_FOUND")
        raise SystemExit(1) from e
    except Exception as e:
        fmt.error(str(e), code=getattr(e, "code", "TREASURY_ERROR"))
        raise SystemExit(1) from e

    # #1809: ``_handle_treasury_allocate`` 가 reject 시 typed exception 으로
    # raise 하므로 정상 응답은 항상 ``success=True``. 잔존 false 경로는
    # 방어적 invariant 로 유지하되 stable ``code`` 를 부착한다.
    if result.get("success"):
        fmt.success(
            f"예산 할당 완료: {bot_id} <- {amount:,.0f}원",
            {"bot_id": bot_id, "amount": amount, "account_id": account_id},
        )
    else:
        fmt.error(
            f"예산 할당 실패: 미할당 자금 부족 또는 금액 오류 (요청: {amount:,.0f}원)",
            code="TREASURY_ALLOCATE_FAILED",
        )
        raise SystemExit(1)


@treasury.command()
@click.argument("bot_id")
@click.argument("amount", type=float, callback=validate_positive_finite_amount)
@click.option("--account", "account_id", required=True, help="계좌 ID")
@click.pass_context
@require_auth
@require_scope("treasury:admin")
def deallocate(ctx: click.Context, bot_id: str, amount: float, account_id: str) -> None:
    """봇 예산 회수."""
    fmt = get_formatter(ctx)
    actor = _get_member_id(ctx)

    # #1656 E bucket defense-in-depth: `allocate`와 동형 — invalid account_id를
    # `ipc_send`(→`_handle_treasury_deallocate`) 이전에 거부한다(required arg
    # 전검증, clean early exit). 에러코드는 #1633 SSOT `VALIDATION_ERROR`.
    account_id = reject_invalid_account_id(
        account_id, fmt, context="cli.treasury.deallocate"
    )

    async def _run_deallocate() -> dict:
        from ante.cli.commands.ipc_helpers import ipc_send

        return await ipc_send(
            "treasury.deallocate",
            {"account_id": account_id, "bot_id": bot_id, "amount": amount},
            actor=actor,
        )

    # #1809: allocate 와 동형 — typed exception envelope ``code``
    # (``TREASURY_INVALID_AMOUNT`` / ``TREASURY_BUDGET_NOT_FOUND`` /
    # ``TREASURY_DEALLOCATE_EXCEEDS_AVAILABLE``) 를 surface 한다.
    try:
        result = _run(_run_deallocate())
    except click.ClickException as e:
        code = getattr(e, "ipc_error_code", "") or "IPC_ERROR"
        message = getattr(e, "ipc_error_message", None) or e.message
        fmt.error(message, code=code)
        raise SystemExit(1) from e
    except AccountNotFoundError as e:
        fmt.error(str(e), code="ACCOUNT_NOT_FOUND")
        raise SystemExit(1) from e
    except Exception as e:
        fmt.error(str(e), code=getattr(e, "code", "TREASURY_ERROR"))
        raise SystemExit(1) from e

    if result.get("success"):
        fmt.success(
            f"예산 회수 완료: {bot_id} -> {amount:,.0f}원",
            {"bot_id": bot_id, "amount": amount, "account_id": account_id},
        )
    else:
        fmt.error(
            f"예산 회수 실패: 가용 예산 부족 (요청: {amount:,.0f}원)",
            code="TREASURY_DEALLOCATE_FAILED",
        )
        raise SystemExit(1)


@treasury.command()
@click.option(
    "--date",
    "date_str",
    default=None,
    callback=validate_iso_date,
    help="특정 날짜 조회 (YYYY-MM-DD)",
)
@click.option(
    "--from",
    "from_date",
    default=None,
    callback=validate_iso_date,
    help="기간 조회 시작일 (YYYY-MM-DD)",
)
@click.option(
    "--to",
    "to_date",
    default=None,
    callback=validate_iso_date,
    help="기간 조회 종료일 (YYYY-MM-DD)",
)
@click.option("--account", "account_id", required=True, help="계좌 ID")
@format_option
@click.pass_context
@require_auth
@require_scope("treasury:read")
def snapshot(
    ctx: click.Context,
    date_str: str | None,
    from_date: str | None,
    to_date: str | None,
    account_id: str,
) -> None:
    """일별 자산 스냅샷 조회."""
    from datetime import UTC, datetime

    fmt = get_formatter(ctx)

    # invalid account_id(`default`/패턴 위반/`""`)를 resource acquisition
    # 이전에 거부한다(#1635 Split B Layer 1). `status`와 동일 `_create_treasury`
    # construction-lifecycle 경계를 공유하므로 동형으로 ingress에서 차단한다.
    # 에러코드는 #1633 SSOT `VALIDATION_ERROR`(helper가 `e.code` 재사용).
    reject_invalid_account_id(account_id, fmt, context="cli.treasury")

    # 옵션 검증: --date 와 --from/--to 는 동시 사용 불가
    if date_str and (from_date or to_date):
        fmt.error(
            "--date와 --from/--to 옵션은 동시에 사용할 수 없습니다.",
            code="CLI_OPTION_CONFLICT",
        )
        raise SystemExit(1)

    # inverted date range(시작일 > 종료일) 거부: CLI_OPTION_CONFLICT 검증
    # 직후, _run_snapshot/서비스 호출 이전에 차단한다 (backtest.py:72-77
    # 동형, INVALID_DATE_RANGE + exit 1).
    reject_inverted_date_range(
        from_date,
        to_date,
        fmt,
        from_label="시작일",
        to_label="종료일",
    )

    async def _run_snapshot() -> dict | list[dict] | None:
        t, db = await _create_treasury(account_id)
        try:
            if date_str:
                return await t.get_daily_snapshot(date_str)
            if from_date or to_date:
                today = datetime.now(UTC).strftime("%Y-%m-%d")
                start = from_date or "2000-01-01"
                end = to_date or today
                return await t.get_snapshots(start, end)
            # 기본: 오늘 스냅샷
            today = datetime.now(UTC).strftime("%Y-%m-%d")
            return await t.get_daily_snapshot(today)
        finally:
            await db.close()

    # valid-but-missing account_id 매핑은 status와 동형이다 (#1725).
    try:
        result = _run(_run_snapshot())
    except AccountNotFoundError as e:
        fmt.error(str(e), code="ACCOUNT_NOT_FOUND")
        raise SystemExit(1) from e

    if result is None:
        target = date_str or datetime.now(UTC).strftime("%Y-%m-%d")
        fmt.error(f"{target} 날짜의 스냅샷이 없습니다.", code="SNAPSHOT_NOT_FOUND")
        raise SystemExit(1)

    if fmt.is_json:
        fmt.output(result)
        return

    # text 모드 출력
    if isinstance(result, list):
        _print_snapshot_list(result)
    else:
        _print_snapshot(result)


@treasury.group("portfolio")
def portfolio() -> None:
    """포트폴리오 가치와 추이 조회."""


def _portfolio_value_from_snapshot_or_summary(treasury_obj) -> dict:  # noqa: ANN001
    async def _inner() -> dict:
        snapshot = await treasury_obj.get_latest_snapshot()
        if snapshot is not None:
            return {
                "account_id": treasury_obj.account_id,
                "total_value": snapshot["total_asset"],
                "daily_pnl": snapshot["daily_pnl"],
                "daily_return": snapshot["daily_return"],
                "unrealized_pnl": snapshot["unrealized_pnl"],
                "snapshot_date": snapshot["snapshot_date"],
                "updated_at": snapshot["created_at"],
            }
        summary = treasury_obj.get_summary()
        return {
            "account_id": treasury_obj.account_id,
            "total_value": summary.get("total_evaluation", 0.0),
            "daily_pnl": 0.0,
            "daily_return": 0.0,
            "unrealized_pnl": 0.0,
            "updated_at": datetime.now(UTC).isoformat(),
        }

    return _run(_inner())


@portfolio.command("value")
@click.option("--account", "account_id", default=None, help="계좌 ID")
@format_option
@click.pass_context
@require_auth
@require_scope("treasury:read")
def portfolio_value(ctx: click.Context, account_id: str | None) -> None:
    """총 자산 가치 조회."""
    fmt = get_formatter(ctx)
    if account_id is not None:
        account_id = reject_invalid_account_id(
            account_id, fmt, context="cli.treasury.portfolio.value"
        )

    async def _run_value() -> dict:
        if account_id is not None:
            t, db = await _create_treasury(account_id)
            treasuries = [t]
        else:
            manager, db = await _create_treasury_manager()
            treasuries = manager.list_all()
        try:
            values = []
            for treasury_obj in treasuries:
                snapshot = await treasury_obj.get_latest_snapshot()
                if snapshot is not None:
                    values.append(
                        {
                            "account_id": treasury_obj.account_id,
                            "total_value": snapshot["total_asset"],
                            "daily_pnl": snapshot["daily_pnl"],
                            "daily_return": snapshot["daily_return"],
                            "unrealized_pnl": snapshot["unrealized_pnl"],
                            "snapshot_date": snapshot["snapshot_date"],
                            "updated_at": snapshot["created_at"],
                        }
                    )
                else:
                    summary = treasury_obj.get_summary()
                    values.append(
                        {
                            "account_id": treasury_obj.account_id,
                            "total_value": summary.get("total_evaluation", 0.0),
                            "daily_pnl": 0.0,
                            "daily_return": 0.0,
                            "unrealized_pnl": 0.0,
                            "updated_at": datetime.now(UTC).isoformat(),
                        }
                    )
            total_value = sum(float(v["total_value"]) for v in values)
            daily_pnl = sum(float(v["daily_pnl"]) for v in values)
            unrealized_pnl = sum(float(v["unrealized_pnl"]) for v in values)
            daily_return = daily_pnl / total_value if total_value else 0.0
            return {
                "total_value": total_value,
                "daily_pnl": daily_pnl,
                "daily_return": daily_return,
                "unrealized_pnl": unrealized_pnl,
                "accounts": values,
                "updated_at": datetime.now(UTC).isoformat(),
            }
        finally:
            await db.close()

    # valid-but-missing account_id 매핑은 status/snapshot/budgets와 동형이다
    # (#1758, #1725). outer try는 `_create_treasury`(line ~612)와
    # `_create_treasury_manager`(line ~615) 두 경로의 raise를 모두 cover한다.
    try:
        result = _run(_run_value())
    except AccountNotFoundError as e:
        fmt.error(str(e), code="ACCOUNT_NOT_FOUND")
        raise SystemExit(1) from e
    except Exception as e:
        fmt.error(str(e), code=getattr(e, "code", "TREASURY_ERROR"))
        raise SystemExit(1) from e

    if fmt.is_json:
        fmt.output(result)
    else:
        click.echo(f"  총 자산        : {result['total_value']:>15,.0f}")
        click.echo(f"  당일 손익      : {result['daily_pnl']:>15,.0f}")
        click.echo(f"  수익률         : {result['daily_return']:>15.4f}")
        click.echo(f"  미실현 손익    : {result['unrealized_pnl']:>15,.0f}")


@portfolio.command("history")
@click.option("--account", "account_id", default=None, help="계좌 ID")
@click.option("--from", "from_date", default=None, callback=validate_iso_date)
@click.option("--to", "to_date", default=None, callback=validate_iso_date)
@format_option
@click.pass_context
@require_auth
@require_scope("treasury:read")
def portfolio_history(
    ctx: click.Context,
    account_id: str | None,
    from_date: str | None,
    to_date: str | None,
) -> None:
    """기간별 자산 추이 조회."""
    fmt = get_formatter(ctx)
    if account_id is not None:
        account_id = reject_invalid_account_id(
            account_id, fmt, context="cli.treasury.portfolio.history"
        )
    reject_inverted_date_range(from_date, to_date, fmt)

    end_date = to_date or datetime.now(UTC).strftime("%Y-%m-%d")
    start_date = from_date or (datetime.now(UTC) - timedelta(days=30)).strftime(
        "%Y-%m-%d"
    )

    async def _run_history() -> dict:
        if account_id is not None:
            t, db = await _create_treasury(account_id)
            treasuries = [t]
        else:
            manager, db = await _create_treasury_manager()
            treasuries = manager.list_all()
        try:
            by_date: dict[str, dict[str, float | str]] = {}
            for treasury_obj in treasuries:
                for snapshot in await treasury_obj.get_snapshots(start_date, end_date):
                    row = by_date.setdefault(
                        snapshot["snapshot_date"],
                        {
                            "date": snapshot["snapshot_date"],
                            "total_asset": 0.0,
                            "daily_pnl": 0.0,
                            "daily_return": 0.0,
                            "unrealized_pnl": 0.0,
                        },
                    )
                    row["total_asset"] = float(row["total_asset"]) + float(
                        snapshot["total_asset"]
                    )
                    row["daily_pnl"] = float(row["daily_pnl"]) + float(
                        snapshot["daily_pnl"]
                    )
                    row["unrealized_pnl"] = float(row["unrealized_pnl"]) + float(
                        snapshot["unrealized_pnl"]
                    )
            data = []
            for row in sorted(by_date.values(), key=lambda x: str(x["date"])):
                total_asset = float(row["total_asset"])
                daily_pnl = float(row["daily_pnl"])
                row["daily_return"] = daily_pnl / total_asset if total_asset else 0.0
                data.append(row)
            return {"data": data, "start_date": start_date, "end_date": end_date}
        finally:
            await db.close()

    # valid-but-missing account_id 매핑은 status/snapshot/budgets와 동형이다
    # (#1758, #1725). outer try는 `_create_treasury`(line ~699)와
    # `_create_treasury_manager`(line ~702) 두 경로의 raise를 모두 cover한다.
    try:
        result = _run(_run_history())
    except AccountNotFoundError as e:
        fmt.error(str(e), code="ACCOUNT_NOT_FOUND")
        raise SystemExit(1) from e
    except Exception as e:
        fmt.error(str(e), code=getattr(e, "code", "TREASURY_ERROR"))
        raise SystemExit(1) from e

    if fmt.is_json:
        fmt.output(result)
    else:
        fmt.table(result["data"], ["date", "total_asset", "daily_pnl", "daily_return"])


def _print_snapshot(s: dict) -> None:
    """단일 스냅샷을 텍스트로 출력."""
    daily_pnl = s.get("daily_pnl", 0.0)
    daily_return = s.get("daily_return", 0.0)
    sign = "+" if daily_pnl >= 0 else ""

    click.echo(f"일별 자산 스냅샷 ({s['snapshot_date']})")
    click.echo(f"  총 자산:      {s['total_asset']:>15,.0f}원")
    purchase = s["ante_purchase_amount"]
    click.echo(
        f"  Ante 관리:    {s['ante_eval_amount']:>15,.0f}원 (매입: {purchase:,.0f}원)"
    )
    click.echo(f"  미할당:       {s['unallocated']:>15,.0f}원")
    click.echo(
        f"  당일 손익:    {sign}{daily_pnl:>14,.0f}원 ({sign}{daily_return:.2f}%)"
    )
    click.echo(f"  미실현 손익:  {s.get('unrealized_pnl', 0.0):>+15,.0f}원")
    click.echo(f"  보유 종목:    {s.get('bot_count', 0)}개 봇")


def _print_snapshot_list(snapshots: list[dict]) -> None:
    """스냅샷 목록을 테이블로 출력."""
    if not snapshots:
        click.echo("(스냅샷 없음)")
        return

    first = snapshots[0]["snapshot_date"]
    last = snapshots[-1]["snapshot_date"]
    click.echo(f"일별 자산 스냅샷 ({first} ~ {last})")
    header = f"  {'날짜':>12} {'총 자산':>15} {'당일 손익':>15} {'수익률':>10}"
    click.echo(header)
    click.echo("  " + "-" * 56)
    for s in snapshots:
        pnl = s.get("daily_pnl", 0.0)
        ret = s.get("daily_return", 0.0)
        sign = "+" if pnl >= 0 else ""
        click.echo(
            f"  {s['snapshot_date']:>12}"
            f" {s['total_asset']:>15,.0f}"
            f" {sign}{pnl:>14,.0f}"
            f" {sign}{ret:>9.2f}%"
        )
