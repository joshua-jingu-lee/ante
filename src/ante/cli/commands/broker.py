"""ante broker — 증권사 계좌 조회 커맨드."""

from __future__ import annotations

import asyncio

import click

from ante.cli.main import get_formatter
from ante.cli.middleware import require_auth, require_scope


@click.group()
def broker() -> None:
    """증권사 계좌 정보 조회."""


def _run(coro):  # noqa: ANN001, ANN202
    return asyncio.run(coro)


async def _create_broker():  # noqa: ANN202
    from ante.config.config import Config

    config = Config.load()
    broker_config = config.get("broker") or {}
    if not isinstance(broker_config, dict):
        broker_config = {}
    broker_type = broker_config.get("type", "kis")

    if broker_type == "kis":
        from ante.broker.kis import KISAdapter

        adapter = KISAdapter(broker_config)
        await adapter.connect()
        return adapter
    else:
        msg = f"지원하지 않는 브로커: {broker_type}"
        raise ValueError(msg)


@broker.command()
@click.pass_context
@require_auth
@require_scope("broker:read")
def status(ctx: click.Context) -> None:
    """증권사 연결 상태 조회."""
    fmt = get_formatter(ctx)

    async def _run_status() -> dict:
        try:
            adapter = await _create_broker()
            healthy = await adapter.health_check()
            return {
                "connected": adapter.is_connected,
                "healthy": healthy,
                "exchange": adapter.exchange,
            }
        except Exception as e:
            return {
                "connected": False,
                "healthy": False,
                "error": str(e),
            }

    result = _run(_run_status())

    if fmt.is_json:
        fmt.output(result)
    else:
        click.echo(
            f"  연결 상태  : {'연결됨' if result.get('connected') else '미연결'}"
        )
        click.echo(f"  건강 상태  : {'정상' if result.get('healthy') else '이상'}")
        if result.get("exchange"):
            click.echo(f"  거래소     : {result['exchange']}")
        if result.get("error"):
            click.echo(f"  오류       : {result['error']}")


@broker.command()
@click.pass_context
@require_auth
@require_scope("broker:read")
def balance(ctx: click.Context) -> None:
    """증권사 계좌 잔고 조회."""
    fmt = get_formatter(ctx)

    async def _run_balance() -> dict:
        adapter = await _create_broker()
        try:
            return await adapter.get_account_balance()
        finally:
            await adapter.disconnect()

    try:
        result = _run(_run_balance())
    except Exception as e:
        fmt.error(str(e))
        return

    if fmt.is_json:
        fmt.output(result)
    else:
        for key, value in result.items():
            if isinstance(value, float):
                click.echo(f"  {key:20s}: {value:>15,.0f}")
            else:
                click.echo(f"  {key:20s}: {value}")


@broker.command()
@click.pass_context
@require_auth
@require_scope("broker:read")
def positions(ctx: click.Context) -> None:
    """증권사 보유 종목 조회."""
    fmt = get_formatter(ctx)

    async def _run_positions() -> list[dict]:
        adapter = await _create_broker()
        try:
            return await adapter.get_positions()
        finally:
            await adapter.disconnect()

    try:
        result = _run(_run_positions())
    except Exception as e:
        fmt.error(str(e))
        return

    if not result:
        fmt.output({"message": "보유 종목 없음", "positions": []})
        return

    if fmt.is_json:
        fmt.output({"positions": result})
    else:
        columns = ["symbol", "quantity", "avg_price", "eval_amount"]
        fmt.table(result, columns)


@broker.command()
@click.pass_context
@require_auth
@require_scope("broker:read")
def reconcile(ctx: click.Context) -> None:
    """내부 데이터와 증권사 데이터 대사."""
    fmt = get_formatter(ctx)

    async def _run_reconcile() -> dict:
        from ante.core.database import Database
        from ante.eventbus.bus import EventBus
        from ante.trade.performance import PerformanceTracker
        from ante.trade.position import PositionHistory
        from ante.trade.recorder import TradeRecorder
        from ante.trade.service import TradeService

        adapter = await _create_broker()
        db = Database("db/ante.db")
        await db.connect()
        try:
            eventbus = EventBus()
            recorder = TradeRecorder(db, eventbus)
            await recorder.initialize()
            position_history = PositionHistory(db, eventbus)
            await position_history.initialize()
            performance = PerformanceTracker(db)
            await performance.initialize()
            trade_service = TradeService(recorder, position_history, performance)

            broker_positions = await adapter.get_account_positions()
            internal_positions = await trade_service.get_all_positions()

            broker_map = {p["symbol"]: p for p in broker_positions}
            internal_map = {p.symbol: p for p in internal_positions}

            all_symbols = set(broker_map.keys()) | set(internal_map.keys())
            discrepancies = []
            for symbol in sorted(all_symbols):
                bp = broker_map.get(symbol)
                ip = internal_map.get(symbol)
                broker_qty = float(bp.get("quantity", 0)) if bp else 0.0
                internal_qty = ip.quantity if ip else 0.0
                if broker_qty != internal_qty:
                    discrepancies.append(
                        {
                            "symbol": symbol,
                            "broker_qty": broker_qty,
                            "internal_qty": internal_qty,
                            "diff": broker_qty - internal_qty,
                        }
                    )

            return {
                "total_symbols": len(all_symbols),
                "discrepancies": discrepancies,
                "match": len(discrepancies) == 0,
            }
        finally:
            await adapter.disconnect()
            await db.close()

    try:
        result = _run(_run_reconcile())
    except Exception as e:
        fmt.error(str(e))
        return

    if fmt.is_json:
        fmt.output(result)
    else:
        click.echo(f"  총 종목 수     : {result['total_symbols']}")
        click.echo(f"  대사 결과      : {'일치' if result['match'] else '불일치'}")
        if result["discrepancies"]:
            click.echo("  불일치 종목:")
            fmt.table(
                result["discrepancies"],
                ["symbol", "broker_qty", "internal_qty", "diff"],
            )
