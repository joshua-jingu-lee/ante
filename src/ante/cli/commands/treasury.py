"""ante treasury — 자금 현황 조회/관리 커맨드."""

from __future__ import annotations

import asyncio

import click

from ante.cli.formatter import format_option
from ante.cli.main import get_formatter
from ante.cli.middleware import require_auth, require_scope


@click.group()
def treasury() -> None:
    """자금 현황 조회·관리."""


def _run(coro):  # noqa: ANN001, ANN202
    return asyncio.run(coro)


async def _create_treasury(account_id: str | None = None):  # noqa: ANN202
    from ante.account.service import AccountService
    from ante.core.database import Database
    from ante.eventbus.bus import EventBus
    from ante.treasury.treasury import Treasury

    db = Database("db/ante.db")
    await db.connect()
    eventbus = EventBus()
    account_service = AccountService(db=db, eventbus=eventbus)
    await account_service.initialize()

    if account_id:
        account = await account_service.get(account_id)
        t = Treasury(
            db,
            eventbus,
            account_id=account.account_id,
            currency=account.currency,
            buy_commission_rate=float(account.buy_commission_rate),
            sell_commission_rate=float(account.sell_commission_rate),
        )
    else:
        t = Treasury(db, eventbus)

    await t.initialize()
    return t, db


@treasury.command()
@click.option("--account", "account_id", default=None, help="계좌 ID로 필터링")
@format_option
@click.pass_context
@require_auth
@require_scope("treasury:read")
def status(ctx: click.Context, account_id: str | None) -> None:
    """자금 현황 요약."""
    fmt = get_formatter(ctx)

    async def _run_status() -> dict:
        t, db = await _create_treasury(account_id)
        try:
            return t.get_summary()
        finally:
            await db.close()

    result = _run(_run_status())

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


@treasury.command()
@click.argument("bot_id")
@click.argument("amount", type=float)
@click.pass_context
@require_auth
@require_scope("treasury:admin")
def allocate(ctx: click.Context, bot_id: str, amount: float) -> None:
    """봇에 예산 할당."""
    fmt = get_formatter(ctx)

    from ante.treasury.exceptions import BotNotStoppedError

    async def _run_allocate() -> bool:
        t, db = await _create_treasury()
        try:
            return await t.allocate(bot_id, amount)
        finally:
            await db.close()

    try:
        success = _run(_run_allocate())
    except BotNotStoppedError as e:
        fmt.error(str(e))
        return

    if success:
        fmt.success(
            f"예산 할당 완료: {bot_id} ← {amount:,.0f}원",
            {"bot_id": bot_id, "amount": amount},
        )
    else:
        fmt.error(
            f"예산 할당 실패: 미할당 자금 부족 또는 금액 오류 (요청: {amount:,.0f}원)"
        )


@treasury.command()
@click.argument("bot_id")
@click.argument("amount", type=float)
@click.pass_context
@require_auth
@require_scope("treasury:admin")
def deallocate(ctx: click.Context, bot_id: str, amount: float) -> None:
    """봇 예산 회수."""
    fmt = get_formatter(ctx)

    from ante.treasury.exceptions import BotNotStoppedError

    async def _run_deallocate() -> bool:
        t, db = await _create_treasury()
        try:
            return await t.deallocate(bot_id, amount)
        finally:
            await db.close()

    try:
        success = _run(_run_deallocate())
    except BotNotStoppedError as e:
        fmt.error(str(e))
        return

    if success:
        fmt.success(
            f"예산 회수 완료: {bot_id} → {amount:,.0f}원",
            {"bot_id": bot_id, "amount": amount},
        )
    else:
        fmt.error(f"예산 회수 실패: 가용 예산 부족 (요청: {amount:,.0f}원)")
