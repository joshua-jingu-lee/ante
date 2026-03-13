"""ante system — 시스템 제어 커맨드."""

from __future__ import annotations

import asyncio

import click

from ante.cli.main import get_formatter
from ante.cli.middleware import get_member_id, require_auth, require_scope


@click.group()
def system() -> None:
    """시스템 시작·중지·상태 확인."""


def _run(coro):  # noqa: ANN001, ANN202
    return asyncio.run(coro)


async def _create_services():  # noqa: ANN202
    from ante.core.database import Database
    from ante.eventbus.bus import EventBus

    db = Database("db/ante.db")
    await db.connect()
    eventbus = EventBus()
    return db, eventbus


@system.command()
@click.pass_context
@require_auth
@require_scope("system:read")
def status(ctx: click.Context) -> None:
    """시스템 상태 표시."""
    fmt = get_formatter(ctx)

    async def _run_status() -> dict:
        from ante.config.system_state import SystemState

        db, eventbus = await _create_services()
        try:
            state = SystemState(db, eventbus)
            await state.initialize()

            # 봇 수 조회
            row = await db.fetch_one("SELECT count(*) as cnt FROM bots")
            bot_count = row["cnt"] if row else 0

            return {
                "trading_state": state.trading_state.value,
                "bot_count": bot_count,
            }
        finally:
            await db.close()

    result = _run(_run_status())

    if fmt.is_json:
        fmt.output(result)
    else:
        click.echo(f"  거래 상태  : {result['trading_state']}")
        click.echo(f"  봇 수     : {result['bot_count']}")


@system.command()
@click.option("--reason", default="", help="사유")
@click.pass_context
@require_auth
@require_scope("system:admin")
def halt(ctx: click.Context, reason: str) -> None:
    """킬 스위치 발동 (전체 거래 중지)."""
    fmt = get_formatter(ctx)
    actor = get_member_id(ctx)

    async def _run_halt() -> dict:
        from ante.config.system_state import SystemState, TradingState

        db, eventbus = await _create_services()
        try:
            state = SystemState(db, eventbus)
            await state.initialize()
            await state.set_state(TradingState.HALTED, reason=reason, changed_by=actor)
            return {"trading_state": state.trading_state.value}
        finally:
            await db.close()

    result = _run(_run_halt())
    fmt.success("시스템 HALTED — 전체 거래 중지", result)


@system.command()
@click.option("--reason", default="", help="사유")
@click.pass_context
@require_auth
@require_scope("system:admin")
def activate(ctx: click.Context, reason: str) -> None:
    """킬 스위치 해제 (거래 재개)."""
    fmt = get_formatter(ctx)
    actor = get_member_id(ctx)

    async def _run_activate() -> dict:
        from ante.config.system_state import SystemState, TradingState

        db, eventbus = await _create_services()
        try:
            state = SystemState(db, eventbus)
            await state.initialize()
            await state.set_state(TradingState.ACTIVE, reason=reason, changed_by=actor)
            return {"trading_state": state.trading_state.value}
        finally:
            await db.close()

    result = _run(_run_activate())
    fmt.success("시스템 ACTIVE — 거래 재개", result)
