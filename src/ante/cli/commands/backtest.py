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
@click.option("--db-path", default="db/ante.db", help="DB 경로")
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
    db_path: str,
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
        show_progress = not fmt.is_json

        progress_bar = None

        def _progress_callback(current: int, total: int) -> None:
            nonlocal progress_bar
            if not show_progress:
                return
            if progress_bar is None and total > 0:
                progress_bar = click.progressbar(
                    length=total,
                    label="백테스트 진행",
                    show_percent=True,
                    show_pos=True,
                )
                progress_bar.__enter__()
            if progress_bar is not None:
                progress_bar.update(1)

        result = asyncio.run(service.run(config, progress_callback=_progress_callback))

        if progress_bar is not None:
            progress_bar.__exit__(None, None, None)
            click.echo()

        result_dict = result.to_dict()
        metrics = result_dict.get("metrics", {})

        # backtest_runs 이력 저장
        run_id = asyncio.run(_save_backtest_run(db_path, result, config, metrics))
        result_dict["run_id"] = run_id

        fmt.output(
            result_dict,
            "Run ID: {run_id}\n"
            "Strategy: {strategy}\n"
            "Period: {period}\n"
            "Return: {total_return_pct}%\n"
            "Trades: {total_trades}\n"
            "Final Balance: {final_balance:,.0f}",
        )

        if metrics:
            metric_rows = _format_metrics(metrics)
            fmt.table(metric_rows, ["지표", "값"])

    except Exception as e:
        fmt.error(str(e), code="BACKTEST_ERROR")
        raise SystemExit(1) from e


async def _save_backtest_run(
    db_path: str,
    result: object,
    config: dict,
    metrics: dict,
) -> str:
    """backtest_runs 테이블에 이력 저장."""
    from ante.backtest.run_store import BacktestRunStore
    from ante.core.database import Database

    db = Database(db_path)
    await db.connect()
    try:
        store = BacktestRunStore(db)
        await store.initialize()
        return await store.save(
            strategy_name=result.strategy_name,
            strategy_version=result.strategy_version,
            params=config,
            total_return_pct=round(result.total_return, 2),
            sharpe_ratio=metrics.get("sharpe_ratio"),
            max_drawdown_pct=metrics.get("max_drawdown"),
            total_trades=len(result.trades),
            win_rate=metrics.get("win_rate"),
            result_path="",
        )
    finally:
        await db.close()


@backtest.command()
@click.argument("strategy_name")
@click.option("--limit", default=20, type=int, help="조회 건수")
@click.option("--db-path", default="db/ante.db", help="DB 경로")
@click.pass_context
@require_auth
@require_scope("backtest:run")
def history(
    ctx: click.Context,
    strategy_name: str,
    limit: int,
    db_path: str,
) -> None:
    """전략별 백테스트 실행 이력 조회."""
    fmt = get_formatter(ctx)

    async def _list() -> list[dict]:
        from ante.backtest.run_store import BacktestRunStore
        from ante.core.database import Database

        db = Database(db_path)
        await db.connect()
        try:
            store = BacktestRunStore(db)
            await store.initialize()
            runs = await store.list_by_strategy(strategy_name, limit=limit)
            return [r.to_dict() for r in runs]
        finally:
            await db.close()

    try:
        rows = asyncio.run(_list())
        if not rows:
            fmt.output(
                {"message": f"'{strategy_name}' 백테스트 이력이 없습니다.", "runs": []},
                f"'{strategy_name}' 백테스트 이력이 없습니다.",
            )
            return

        if fmt.is_json:
            fmt.output({"strategy_name": strategy_name, "runs": rows})
        else:
            fmt.table(
                rows,
                [
                    "run_id",
                    "strategy_version",
                    "total_return_pct",
                    "sharpe_ratio",
                    "total_trades",
                    "win_rate",
                    "created_at",
                ],
            )
    except Exception as e:
        fmt.error(str(e), code="BACKTEST_ERROR")
        raise SystemExit(1) from e


def _format_metrics(metrics: dict) -> list[dict[str, str]]:
    """metrics dict를 CLI 테이블 행으로 변환."""
    labels = {
        "total_return": ("총 수익률", "%"),
        "annual_return": ("연환산 수익률", "%"),
        "sharpe_ratio": ("Sharpe Ratio", ""),
        "max_drawdown": ("최대 낙폭 (MDD)", "%"),
        "max_drawdown_duration": ("MDD 지속 기간", "일"),
        "total_trades": ("총 거래 횟수", ""),
        "winning_trades": ("승리 거래", ""),
        "losing_trades": ("패배 거래", ""),
        "win_rate": ("승률", "%"),
        "profit_factor": ("Profit Factor", ""),
        "avg_profit": ("평균 수익", "원"),
        "avg_loss": ("평균 손실", "원"),
        "total_commission": ("총 수수료", "원"),
    }
    rows = []
    for key, (label, unit) in labels.items():
        value = metrics.get(key)
        if value is None:
            formatted = "N/A"
        elif isinstance(value, float):
            if value == float("inf"):
                formatted = "∞"
            else:
                formatted = f"{value:,.4f}" if unit == "" else f"{value:,.2f}"
            if unit:
                formatted += unit
        else:
            formatted = str(value)
            if unit:
                formatted += unit
        rows.append({"지표": label, "값": formatted})
    return rows
