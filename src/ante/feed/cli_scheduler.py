"""ante feed start — 상주 스케줄러 루프.

feed_start CLI 커맨드에서 사용하는 스케줄러 루프를 분리한 모듈이다.
"""

from __future__ import annotations

import asyncio
import logging
import signal
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import click

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))


async def run_scheduler_loop(
    orchestrator: Any,  # FeedOrchestrator  # noqa: ANN401
    data_path: str,
    config: dict[str, Any],
    daily_at: str,
    backfill_at: str,
) -> None:
    """스케줄 루프: daily_at / backfill_at 시각에 수집을 실행한다."""
    stop_event = _setup_signal_handlers()

    logger.info(
        "DataFeed 스케줄러 시작 (daily_at=%s, backfill_at=%s)",
        daily_at,
        backfill_at,
    )
    click.echo(
        f"DataFeed 스케줄러 시작 (daily_at={daily_at}, backfill_at={backfill_at})"
    )
    click.echo("종료하려면 Ctrl+C 또는 SIGTERM을 보내세요.")

    daily_ran_today = False
    backfill_ran_today = False
    last_date = ""

    while not stop_event.is_set():
        now = datetime.now(tz=KST)
        current_time = now.strftime("%H:%M")
        current_date = now.strftime("%Y-%m-%d")

        if last_date and last_date != current_date:
            daily_ran_today = False
            backfill_ran_today = False
        last_date = current_date

        if not daily_ran_today and current_time >= str(daily_at):
            await _run_daily_job(orchestrator, data_path, config, current_date)
            daily_ran_today = True

        if not backfill_ran_today and current_time >= str(backfill_at):
            await _run_backfill_job(orchestrator, data_path, config, current_date)
            backfill_ran_today = True

        await _wait_or_stop(stop_event, timeout=60.0)

    logger.info("DataFeed 스케줄러 종료")
    click.echo("DataFeed 스케줄러 종료")


def _setup_signal_handlers() -> asyncio.Event:
    """SIGTERM/SIGINT 시그널 핸들러를 등록하고 stop_event를 반환한다."""
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    def _handle_signal() -> None:
        logger.info("종료 시그널 수신, 스케줄러 중지...")
        stop_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _handle_signal)

    return stop_event


async def _run_daily_job(
    orchestrator: Any,  # noqa: ANN401
    data_path: str,
    config: dict[str, Any],
    current_date: str,
) -> None:
    """Daily 수집 작업을 1회 실행한다."""
    logger.info("Daily 수집 시작 (%s)", current_date)
    try:
        result = await orchestrator.run_daily(
            data_path=Path(data_path),
            config=config,
        )
        click.echo(
            f"[{current_date}] Daily 완료: "
            f"{result.symbols_success}/{result.symbols_total} 종목, "
            f"{result.rows_written} rows"
        )
    except Exception as exc:
        logger.error("Daily 수집 실패: %s", exc)


async def _run_backfill_job(
    orchestrator: Any,  # noqa: ANN401
    data_path: str,
    config: dict[str, Any],
    current_date: str,
) -> None:
    """Backfill 수집 작업을 1회 실행한다."""
    logger.info("Backfill 수집 시작 (%s)", current_date)
    try:
        result = await orchestrator.run_backfill(
            data_path=Path(data_path),
            config=config,
        )
        click.echo(
            f"[{current_date}] Backfill 완료: "
            f"{result.symbols_success}/{result.symbols_total} 종목, "
            f"{result.rows_written} rows"
        )
    except Exception as exc:
        logger.error("Backfill 수집 실패: %s", exc)


async def _wait_or_stop(stop_event: asyncio.Event, *, timeout: float) -> None:
    """stop_event 또는 timeout까지 대기한다."""
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=timeout)
    except TimeoutError:
        pass
