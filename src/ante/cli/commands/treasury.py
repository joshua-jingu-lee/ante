"""ante treasury — 자금 현황 조회/관리 커맨드."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Coroutine
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import UTC, date, timedelta, timezone
from typing import TYPE_CHECKING, Any

import click

from ante.cli._validators import (
    reject_invalid_account_id,
    reject_inverted_date_range,
    validate_iso_date,
    validate_nonnegative_finite_amount,
    validate_positive_finite_amount,
)
from ante.cli.db_context import open_cli_db
from ante.cli.formatter import CommandResult, format_option, table_lines
from ante.cli.main import get_formatter
from ante.cli.middleware import get_member_id as _get_member_id
from ante.cli.middleware import require_auth, require_scope
from ante.contracts.cli_errors import (
    CliOptionConflictError,
    SnapshotNotFoundError,
    TreasuryAllocateFailedError,
    TreasuryDeallocateFailedError,
)
from ante.core import clock
from ante.core.database import is_missing_table

if TYPE_CHECKING:
    from ante.core.database import Database
    from ante.treasury.manager import TreasuryManager
    from ante.treasury.treasury import Treasury

logger = logging.getLogger(__name__)

_KST = timezone(timedelta(hours=9))


def _today_kst() -> date:
    """스냅샷 키와 같은 기준(KST)의 오늘 날짜."""
    return clock.now(_KST).date()


@click.group()
def treasury() -> None:
    """자금 현황 조회·관리."""


def _run(coro: Coroutine[Any, Any, Any]) -> Any:
    return asyncio.run(coro)


@asynccontextmanager
async def _create_treasury(
    account_id: str | None = None,
    *,
    ctx: click.Context | None = None,
) -> AsyncIterator[tuple[Treasury, Database]]:
    """CLI 에서 ``Treasury`` async context manager."""
    from ante.account.scoping import require_account_id
    from ante.account.service import AccountService
    from ante.eventbus.bus import EventBus
    from ante.treasury.treasury import Treasury

    validated_account_id = require_account_id(account_id, context="cli.treasury")

    resolved_ctx = ctx if ctx is not None else click.get_current_context(silent=True)
    if resolved_ctx is None:
        raise ValueError(
            "_create_treasury requires a Click context "
            "(explicit ctx or active click.get_current_context)"
        )

    async with open_cli_db(resolved_ctx) as db:
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
        yield t, db


@asynccontextmanager
async def _create_treasury_manager(
    ctx: click.Context | None = None,
) -> AsyncIterator[tuple[TreasuryManager, Database]]:
    """CLI 에서 ``TreasuryManager`` async context manager."""
    from ante.account.service import AccountService
    from ante.eventbus.bus import EventBus
    from ante.treasury.manager import TreasuryManager

    resolved_ctx = ctx if ctx is not None else click.get_current_context(silent=True)
    if resolved_ctx is None:
        raise ValueError(
            "_create_treasury_manager requires a Click context "
            "(explicit ctx or active click.get_current_context)"
        )

    async with open_cli_db(resolved_ctx) as db:
        eventbus = EventBus()
        account_service = AccountService(db=db, eventbus=eventbus)
        await account_service.initialize()
        manager = TreasuryManager(db=db, eventbus=eventbus)
        await manager.initialize_all(await account_service.list())
        yield manager, db


@treasury.command()
@click.option("--account", "account_id", required=True, help="계좌 ID")
@format_option
@click.pass_context
@require_auth
@require_scope("treasury:read")
def status(ctx: click.Context, account_id: str) -> CommandResult:
    """자금 현황 요약."""
    fmt = get_formatter(ctx)

    reject_invalid_account_id(account_id, fmt, context="cli.treasury")

    async def _run_status() -> dict[str, Any]:
        async with _create_treasury(account_id, ctx=ctx) as (t, _):
            return t.get_summary()

    result = _run(_run_status())

    return CommandResult(
        data=result,
        text=(
            f"  계좌 잔고      : {result['account_balance']:>15,.0f}",
            f"  매수 가능      : {result['purchasable_amount']:>15,.0f}",
            f"  총 평가액      : {result['total_evaluation']:>15,.0f}",
            f"  총 손익        : {result['total_profit_loss']:>15,.0f}",
            f"  총 할당        : {result['total_allocated']:>15,.0f}",
            f"  총 예약        : {result['total_reserved']:>15,.0f}",
            f"  미할당         : {result['unallocated']:>15,.0f}",
            f"  봇 수          : {result['bot_count']:>15d}",
        ),
    )


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
) -> CommandResult:
    """자금 변동 이력 조회."""
    fmt = get_formatter(ctx)
    if account_id is not None:
        account_id = reject_invalid_account_id(
            account_id, fmt, context="cli.treasury.transactions"
        )
    reject_inverted_date_range(from_date, to_date, fmt)

    async def _run_transactions() -> dict[str, Any]:
        async with open_cli_db(ctx) as db:
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
                    " ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
                    (*params, limit, offset),
                )
            except Exception as e:
                if is_missing_table(e):
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

    result = _run(_run_transactions())
    columns = ["created_at", "account_id", "type", "bot_id", "amount"]
    return CommandResult(data=result, text=tuple(table_lines(result["items"], columns)))


@treasury.command("budgets")
@click.option("--account", "account_id", default=None, help="계좌 ID 필터")
@format_option
@click.pass_context
@require_auth
@require_scope("treasury:read")
def budgets(ctx: click.Context, account_id: str | None) -> CommandResult:
    """봇별 예산 목록 조회."""
    fmt = get_formatter(ctx)
    if account_id is not None:
        account_id = reject_invalid_account_id(
            account_id, fmt, context="cli.treasury.budgets"
        )

    async def _run_budgets() -> dict[str, Any]:
        async def _collect_items(treasuries: list[Treasury]) -> dict[str, Any]:
            items = []
            for treasury_obj in treasuries:
                for budget in treasury_obj.list_budgets():
                    data = asdict(budget)
                    if hasattr(budget.last_updated, "isoformat"):
                        data["last_updated"] = budget.last_updated.isoformat()
                    items.append(data)
            return {"budgets": items}

        if account_id is not None:
            async with _create_treasury(account_id, ctx=ctx) as (t, _):
                return await _collect_items([t])
        async with _create_treasury_manager(ctx=ctx) as (manager, _):
            return await _collect_items(manager.list_all())

    result = _run(_run_budgets())

    columns = ["account_id", "bot_id", "allocated", "available", "reserved"]
    return CommandResult(
        data=result, text=tuple(table_lines(result["budgets"], columns))
    )


@treasury.command("set-balance")
@click.argument("amount", type=float, callback=validate_nonnegative_finite_amount)
@click.option("--account", "account_id", required=True, help="계좌 ID")
@format_option
@click.pass_context
@require_auth
@require_scope("treasury:admin")
def set_balance(ctx: click.Context, amount: float, account_id: str) -> CommandResult:
    """계좌 총 잔고 수동 설정."""
    fmt = get_formatter(ctx)
    actor = _get_member_id(ctx)
    account_id = reject_invalid_account_id(
        account_id, fmt, context="cli.treasury.set_balance"
    )

    async def _run_set_balance() -> dict[str, Any]:
        from ante.cli.cold_path import is_active_runtime
        from ante.cli.commands.ipc_helpers import ipc_send

        if is_active_runtime():
            return await ipc_send(
                "treasury.set_balance",
                {"account_id": account_id, "balance": amount},
                actor=actor,
            )
        async with _create_treasury(account_id, ctx=ctx) as (t, _):
            await t.set_account_balance(amount)
            return {
                "account_id": account_id,
                "total_balance": t.account_balance,
                "updated_at": clock.now(UTC).isoformat(),
            }

    result = _run(_run_set_balance())

    return CommandResult(
        data=result, text=(f"계좌 잔고 설정 완료: {account_id} {amount:,.0f}",)
    )


@treasury.command()
@click.argument("bot_id")
@click.argument("amount", type=float, callback=validate_positive_finite_amount)
@click.option("--account", "account_id", required=True, help="계좌 ID")
@click.pass_context
@require_auth
@require_scope("treasury:admin")
def allocate(
    ctx: click.Context, bot_id: str, amount: float, account_id: str
) -> CommandResult:
    """봇에 예산 할당."""
    fmt = get_formatter(ctx)
    actor = _get_member_id(ctx)

    account_id = reject_invalid_account_id(
        account_id, fmt, context="cli.treasury.allocate"
    )

    async def _run_allocate() -> dict[str, Any]:
        from ante.cli.commands.ipc_helpers import ipc_send

        return await ipc_send(
            "treasury.allocate",
            {"account_id": account_id, "bot_id": bot_id, "amount": amount},
            actor=actor,
        )

    result = _run(_run_allocate())

    if result.get("success"):
        return CommandResult(
            data={"bot_id": bot_id, "amount": amount, "account_id": account_id},
            message=f"예산 할당 완료: {bot_id} <- {amount:,.0f}원",
        )
    raise TreasuryAllocateFailedError(
        f"예산 할당 실패: 미할당 자금 부족 또는 금액 오류 (요청: {amount:,.0f}원)"
    )


@treasury.command()
@click.argument("bot_id")
@click.argument("amount", type=float, callback=validate_positive_finite_amount)
@click.option("--account", "account_id", required=True, help="계좌 ID")
@click.pass_context
@require_auth
@require_scope("treasury:admin")
def deallocate(
    ctx: click.Context, bot_id: str, amount: float, account_id: str
) -> CommandResult:
    """봇 예산 회수."""
    fmt = get_formatter(ctx)
    actor = _get_member_id(ctx)

    account_id = reject_invalid_account_id(
        account_id, fmt, context="cli.treasury.deallocate"
    )

    async def _run_deallocate() -> dict[str, Any]:
        from ante.cli.commands.ipc_helpers import ipc_send

        return await ipc_send(
            "treasury.deallocate",
            {"account_id": account_id, "bot_id": bot_id, "amount": amount},
            actor=actor,
        )

    result = _run(_run_deallocate())

    if result.get("success"):
        return CommandResult(
            data={"bot_id": bot_id, "amount": amount, "account_id": account_id},
            message=f"예산 회수 완료: {bot_id} -> {amount:,.0f}원",
        )
    raise TreasuryDeallocateFailedError(
        f"예산 회수 실패: 가용 예산 부족 (요청: {amount:,.0f}원)"
    )


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
) -> CommandResult:
    """일별 자산 스냅샷 조회."""
    fmt = get_formatter(ctx)

    reject_invalid_account_id(account_id, fmt, context="cli.treasury")

    if date_str and (from_date or to_date):
        raise CliOptionConflictError(
            "--date와 --from/--to 옵션은 동시에 사용할 수 없습니다."
        )

    start: str | None = None
    end: str | None = None
    if from_date or to_date:
        start = from_date or "2000-01-01"
        end = to_date or _today_kst().isoformat()
        reject_inverted_date_range(
            start,
            end,
            fmt,
            from_label="시작일" if from_date else "기본 시작일",
            to_label="종료일" if to_date else "기본 종료일",
        )

    async def _run_snapshot() -> dict[str, Any] | list[dict[str, Any]] | None:
        async with _create_treasury(account_id, ctx=ctx) as (t, _):
            if date_str:
                return await t.get_daily_snapshot(date_str)
            if start is not None and end is not None:
                return await t.get_snapshots(start, end)
            return await t.get_latest_snapshot()

    result = _run(_run_snapshot())

    if result is None:
        if date_str:
            raise SnapshotNotFoundError(f"{date_str} 날짜의 스냅샷이 없습니다.")
        raise SnapshotNotFoundError("저장된 스냅샷이 없습니다.")

    if isinstance(result, list):
        return CommandResult(data=result, text=tuple(_snapshot_list_lines(result)))
    return CommandResult(data=result, text=tuple(_snapshot_lines(result)))


@treasury.group("portfolio")
def portfolio() -> None:
    """포트폴리오 가치와 추이 조회."""


@portfolio.command("value")
@click.option("--account", "account_id", default=None, help="계좌 ID")
@format_option
@click.pass_context
@require_auth
@require_scope("treasury:read")
def portfolio_value(ctx: click.Context, account_id: str | None) -> CommandResult:
    """총 자산 가치 조회."""
    fmt = get_formatter(ctx)
    if account_id is not None:
        account_id = reject_invalid_account_id(
            account_id, fmt, context="cli.treasury.portfolio.value"
        )

    async def _run_value() -> dict[str, Any]:
        async def _collect_values(treasuries: list[Treasury]) -> dict[str, Any]:
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
                            "updated_at": clock.now(UTC).isoformat(),
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
                "updated_at": clock.now(UTC).isoformat(),
            }

        if account_id is not None:
            async with _create_treasury(account_id, ctx=ctx) as (t, _):
                return await _collect_values([t])
        async with _create_treasury_manager(ctx=ctx) as (manager, _):
            return await _collect_values(manager.list_all())

    result = _run(_run_value())

    return CommandResult(
        data=result,
        text=(
            f"  총 자산        : {result['total_value']:>15,.0f}",
            f"  당일 손익      : {result['daily_pnl']:>15,.0f}",
            f"  수익률         : {result['daily_return']:>15.4f}",
            f"  미실현 손익    : {result['unrealized_pnl']:>15,.0f}",
        ),
    )


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
) -> CommandResult:
    """기간별 자산 추이 조회."""
    fmt = get_formatter(ctx)
    if account_id is not None:
        account_id = reject_invalid_account_id(
            account_id, fmt, context="cli.treasury.portfolio.history"
        )
    today = _today_kst()
    end_date = to_date or today.isoformat()
    start_date = from_date or (today - timedelta(days=30)).isoformat()
    reject_inverted_date_range(
        start_date,
        end_date,
        fmt,
        from_label="시작일" if from_date else "기본 시작일",
        to_label="종료일" if to_date else "기본 종료일",
    )

    async def _run_history() -> dict[str, Any]:
        async def _collect_history(treasuries: list[Treasury]) -> dict[str, Any]:
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

        if account_id is not None:
            async with _create_treasury(account_id, ctx=ctx) as (t, _):
                return await _collect_history([t])
        async with _create_treasury_manager(ctx=ctx) as (manager, _):
            return await _collect_history(manager.list_all())

    result = _run(_run_history())

    columns = ["date", "total_asset", "daily_pnl", "daily_return"]
    return CommandResult(data=result, text=tuple(table_lines(result["data"], columns)))


def _snapshot_lines(s: dict[str, Any]) -> list[str]:
    """단일 스냅샷의 텍스트 줄."""
    daily_pnl = s.get("daily_pnl", 0.0)
    daily_return = s.get("daily_return", 0.0)
    sign = "+" if daily_pnl >= 0 else ""
    purchase = s["ante_purchase_amount"]
    return [
        f"일별 자산 스냅샷 ({s['snapshot_date']})",
        f"  총 자산:      {s['total_asset']:>15,.0f}원",
        f"  Ante 관리:    {s['ante_eval_amount']:>15,.0f}원 (매입: {purchase:,.0f}원)",
        f"  미할당:       {s['unallocated']:>15,.0f}원",
        f"  당일 손익:    {sign}{daily_pnl:>14,.0f}원 ({sign}{daily_return:.2f}%)",
        f"  미실현 손익:  {s.get('unrealized_pnl', 0.0):>+15,.0f}원",
        f"  보유 종목:    {s.get('bot_count', 0)}개 봇",
    ]


def _snapshot_list_lines(snapshots: list[dict[str, Any]]) -> list[str]:
    """스냅샷 목록의 표 줄."""
    if not snapshots:
        return ["(스냅샷 없음)"]

    first = snapshots[0]["snapshot_date"]
    last = snapshots[-1]["snapshot_date"]
    lines = [
        f"일별 자산 스냅샷 ({first} ~ {last})",
        f"  {'날짜':>12} {'총 자산':>15} {'당일 손익':>15} {'수익률':>10}",
        "  " + "-" * 56,
    ]
    for s in snapshots:
        pnl = s.get("daily_pnl", 0.0)
        ret = s.get("daily_return", 0.0)
        sign = "+" if pnl >= 0 else ""
        lines.append(
            f"  {s['snapshot_date']:>12}"
            f" {s['total_asset']:>15,.0f}"
            f" {sign}{pnl:>14,.0f}"
            f" {sign}{ret:>9.2f}%"
        )
    return lines
