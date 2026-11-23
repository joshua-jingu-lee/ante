"""ante backtest — 백테스트 커맨드."""

from __future__ import annotations

import asyncio
import re
from typing import Any

import click

from ante.cli._data_path import resolve_data_path
from ante.cli._validators import validate_positive_finite_amount
from ante.cli.db_context import open_cli_db
from ante.cli.formatter import CommandResult, table_lines
from ante.cli.middleware import require_auth, require_scope
from ante.contracts.cli_errors import (
    CLI_ERRORS,
    BacktestDataNotFoundError,
    BacktestError,
    BacktestInvalidExchangeError,
    BacktestInvalidSymbolError,
    BacktestInvalidTimeframeError,
    InvalidDateError,
    InvalidDateRangeError,
)
from ante.core.database import OperationalError

_ISO_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


@click.group()
def backtest() -> None:
    """백테스트."""


@backtest.command()
@click.argument("strategy_path", type=click.Path(exists=True))
@click.option("--start", required=True, help="시작일 (YYYY-MM-DD)")
@click.option("--end", required=True, help="종료일 (YYYY-MM-DD)")
@click.option("--symbols", help="종목 코드 (콤마 구분)")
@click.option(
    "--balance",
    default=10_000_000,
    type=float,
    callback=validate_positive_finite_amount,
    help="초기 자금",
)
@click.option(
    "--timeframe",
    default=None,
    help="타임프레임 (미지정 시 전략 meta)",
)
@click.option("--exchange", default="KRX", help="거래소 (기본: KRX)")
@click.option(
    "--data-path",
    default=None,
    help="데이터 디렉토리 경로 (미지정 시 config_dir 기반)",
)
@click.option("--db-path", default=None, help="DB 경로 (미지정 시 config_dir 기반)")
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
    timeframe: str | None,
    exchange: str,
    data_path: str | None,
    db_path: str | None,
) -> CommandResult:
    """백테스트 실행."""
    import datetime

    from ante.backtest.service import BacktestService
    from ante.cli.main import get_db_path
    from ante.core.exchange import CANONICAL_EXCHANGES, is_canonical
    from ante.core.market_data_vocab import (
        CANONICAL_TIMEFRAMES,
        is_krx_symbol,
        is_valid_timeframe,
    )

    data_path = resolve_data_path(ctx, data_path)
    resolved_db_path = db_path or get_db_path(ctx)

    for label, value in (("시작일", start), ("종료일", end)):
        if _ISO_DATE_RE.fullmatch(value) is None:
            raise InvalidDateError(
                f"{label} 형식이 올바르지 않습니다: '{value}' (YYYY-MM-DD 형식 필요)"
            )
    try:
        start_date = datetime.date.fromisoformat(start)
        end_date = datetime.date.fromisoformat(end)
    except ValueError as e:
        raise InvalidDateError(f"날짜 형식이 올바르지 않습니다: {e}") from e

    if start_date > end_date:
        raise InvalidDateRangeError(f"시작일({start})이 종료일({end}) 이후입니다.")

    if not is_canonical(exchange):
        raise BacktestInvalidExchangeError(
            f"유효하지 않은 거래소: {exchange!r}. "
            f"허용 값: {', '.join(sorted(CANONICAL_EXCHANGES))}"
        )

    if timeframe is not None and not is_valid_timeframe(timeframe):
        raise BacktestInvalidTimeframeError(
            f"유효하지 않은 타임프레임: {timeframe!r}. "
            f"허용 값: {', '.join(CANONICAL_TIMEFRAMES)}"
        )

    if symbols is not None:
        parsed = symbols.split(",")
        if any(not s.strip() for s in parsed):
            raise BacktestInvalidSymbolError(
                f"유효하지 않은 종목 코드: {symbols!r}. "
                "빈 종목 코드를 포함할 수 없습니다."
            )
        if exchange == "KRX":
            for seg in parsed:
                if not is_krx_symbol(seg):
                    raise BacktestInvalidSymbolError(
                        f"유효하지 않은 종목 코드: {seg!r}. "
                        "KRX 종목 코드는 6자리 숫자여야 합니다."
                    )

    config = {
        "strategy_path": strategy_path,
        "start_date": start,
        "end_date": end,
        "symbols": symbols.split(",") if symbols else [],
        "initial_balance": balance,
        "timeframe": timeframe,
        "exchange": exchange,
        "data_path": data_path,
    }

    try:
        service = BacktestService(data_path=data_path)

        result_dict = asyncio.run(service.run_subprocess(config))
        metrics = result_dict.get("metrics", {})

        explicit_symbols = config["symbols"]
        datasets = result_dict.get("datasets", [])
        if (
            explicit_symbols
            and datasets
            and all(d.get("row_count", 0) == 0 for d in datasets)
        ):
            raise BacktestDataNotFoundError(
                f"명시한 종목의 데이터가 없습니다(row_count=0): {explicit_symbols}"
            )

        run_id = asyncio.run(
            _save_backtest_run(resolved_db_path, result_dict, config, metrics)
        )
        result_dict["run_id"] = run_id

        return CommandResult(
            data=result_dict, text=lambda: _run_text_lines(result_dict, metrics)
        )

    except CLI_ERRORS:
        raise
    except Exception as e:
        raise BacktestError(str(e)) from e


def _run_text_lines(
    result_dict: dict[str, Any], metrics: dict[str, Any]
) -> tuple[str, ...]:
    try:
        lines = [
            "Run ID: {run_id}\n"
            "Strategy: {strategy}\n"
            "Period: {period}\n"
            "Return: {total_return_pct}%\n"
            "Trades: {total_trades}\n"
            "Final Balance: {final_balance:,.0f}".format(**result_dict)
        ]
        if metrics:
            lines += table_lines(_format_metrics(metrics), ["지표", "값"])
    except Exception as e:
        raise BacktestError(str(e)) from e
    return tuple(lines)


async def _save_backtest_run(
    db_path: str,
    result_dict: dict[str, Any],
    config: dict[str, Any],
    metrics: dict[str, Any],
) -> str:
    """backtest_runs 테이블에 이력 저장 (envelope dict 기반)."""
    from ante.backtest.run_store import BacktestRunStore
    from ante.core.database import Database

    db = Database(db_path)
    await db.connect()
    try:
        store = BacktestRunStore(db)
        await store.initialize()
        return await store.save(
            strategy_name=result_dict["strategy_name"],
            strategy_version=result_dict["strategy_version"],
            params=config,
            total_return_pct=result_dict["total_return_pct"],
            sharpe_ratio=metrics.get("sharpe_ratio"),
            max_drawdown_pct=metrics.get("max_drawdown"),
            total_trades=result_dict["total_trades"],
            win_rate=metrics.get("win_rate"),
            result_path=result_dict["result_path"],
        )
    finally:
        await db.close()


@backtest.command()
@click.argument("strategy_name")
@click.option("--limit", default=20, type=click.IntRange(min=1), help="조회 건수")
@click.option("--db-path", default=None, help="DB 경로 (미지정 시 config_dir 기반)")
@click.pass_context
@require_auth
@require_scope("backtest:run")
def history(
    ctx: click.Context,
    strategy_name: str,
    limit: int,
    db_path: str | None,
) -> CommandResult:
    """전략별 백테스트 실행 이력 조회."""

    async def _list() -> list[dict[str, Any]]:
        from ante.backtest.run_store import BacktestRunStore

        async with open_cli_db(ctx, read_only=True, db_path_override=db_path) as db:
            store = BacktestRunStore(db)
            try:
                runs = await store.list_by_strategy(strategy_name, limit=limit)
            except OperationalError as e:
                if "no such table" in str(e).lower():
                    return []
                raise
            return [r.to_dict() for r in runs]

    try:
        rows = asyncio.run(_list())
        if not rows:
            message = f"'{strategy_name}' 백테스트 이력이 없습니다."
            empty: dict[str, Any] = {"message": message, "runs": []}
            return CommandResult(data=empty, text=lambda: _history_empty_text(empty))

        columns = [
            "run_id",
            "strategy_version",
            "total_return_pct",
            "sharpe_ratio",
            "total_trades",
            "win_rate",
            "created_at",
        ]
        return CommandResult(
            data={"strategy_name": strategy_name, "runs": rows},
            text=lambda: _history_rows_text(rows, columns),
        )
    except Exception as e:
        raise BacktestError(str(e)) from e


def _history_rows_text(
    rows: list[dict[str, Any]], columns: list[str]
) -> tuple[str, ...]:
    try:
        return tuple(table_lines(rows, columns))
    except Exception as e:
        raise BacktestError(str(e)) from e


def _history_empty_text(empty: dict[str, Any]) -> tuple[str, ...]:
    try:
        return (empty["message"].format(**empty),)
    except Exception as e:
        raise BacktestError(str(e)) from e


def _format_metrics(metrics: dict[str, Any]) -> list[dict[str, str]]:
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
