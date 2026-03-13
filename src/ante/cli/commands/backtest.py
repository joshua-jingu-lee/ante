"""ante backtest — 백테스트 커맨드."""

from __future__ import annotations

import asyncio

import click

from ante.cli.main import get_formatter
from ante.cli.middleware import require_auth, require_scope


@click.group()
def backtest() -> None:
    """백테스트."""


@backtest.command()
@click.argument("strategy_path", type=click.Path(exists=True))
@click.option("--start", required=True, help="시작일 (YYYY-MM-DD)")
@click.option("--end", required=True, help="종료일 (YYYY-MM-DD)")
@click.option("--symbols", help="종목 코드 (콤마 구분)")
@click.option("--balance", default=10_000_000, type=float, help="초기 자금")
@click.option("--timeframe", default="1d", help="타임프레임")
@click.option("--data-path", default="data/", help="데이터 디렉토리 경로")
@click.pass_context
@require_auth
@require_scope("backtest:run")
def run(
    ctx: click.Context,
    strategy_path: str,
    start: str,
    end: str,
    symbols: str | None,
    balance: float,
    timeframe: str,
    data_path: str,
) -> None:
    """백테스트 실행."""
    from ante.backtest.service import BacktestService

    fmt = get_formatter(ctx)
    config = {
        "strategy_path": strategy_path,
        "start_date": start,
        "end_date": end,
        "symbols": symbols.split(",") if symbols else [],
        "initial_balance": balance,
        "timeframe": timeframe,
        "data_path": data_path,
    }

    try:
        service = BacktestService(data_path=data_path)
        result = asyncio.run(service.run(config))
        result_dict = result.to_dict()
        fmt.output(
            result_dict,
            "Strategy: {strategy}\n"
            "Period: {period}\n"
            "Return: {total_return_pct}%\n"
            "Trades: {total_trades}\n"
            "Final Balance: {final_balance:,.0f}",
        )
    except Exception as e:
        fmt.error(str(e), code="BACKTEST_ERROR")
        raise SystemExit(1) from e
