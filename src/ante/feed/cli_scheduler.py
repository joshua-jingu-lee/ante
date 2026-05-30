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
            await _run_backfill_job(
                orchestrator, data_path, config, current_date, stop_event
            )
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
        # #1943: 스케줄러 호출은 generate_daily_date() (어제) fallback 유지.
        # ``target_date=None`` 을 명시해 의도를 문서화하고, 추후 시그니처
        # 변경이 있어도 keyword 의미를 명확히 보존한다.
        result = await orchestrator.run_daily(
            data_path=Path(data_path),
            config=config,
            target_date=None,
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
    stop_event: asyncio.Event | None = None,
) -> None:
    """Backfill 수집 작업을 1회 실행한다.

    `result.config_errors`에 coded date error(CLI_INVALID_DATE /
    INVALID_DATE_RANGE / GUARD_PERMANENTLY_BLOCKED /
    BACKFILL_STOP_REQUESTED)가 포함된 경우 "Backfill 완료" 메시지를
    출력하지 않고 명시 오류/중단을 echo/log한다. 기존 비날짜
    config_errors(소스 누락·lock 경합·rate-limit 등)는 현행 완료 메시지
    흐름을 유지한다.

    ``stop_event`` 는 상주 스케줄러 루프가 보유한 종료 이벤트로, 거래시간
    가드 대기 중 SIGTERM/SIGINT 수신 시 backfill 루프를 깨워 안전 종료
    시키기 위해 ``orchestrator.run_backfill`` 로 전파한다(#1972). 직접
    호출(테스트 등)에서는 ``None`` 이며 one-shot 의미로 동작한다.
    """
    from ante.feed.pipeline.backfill_runner import (
        BACKFILL_DATE_ERROR_CODES,
        CONFIG_ERROR_CODE_BACKFILL_STOP_REQUESTED,
    )

    logger.info("Backfill 수집 시작 (%s)", current_date)
    try:
        result = await orchestrator.run_backfill(
            data_path=Path(data_path),
            config=config,
            stop_event=stop_event,
        )
        coded_date_errors = [
            entry
            for entry in result.config_errors
            if isinstance(entry, dict)
            and entry.get("code") in BACKFILL_DATE_ERROR_CODES
        ]
        if coded_date_errors:
            for entry in coded_date_errors:
                code = entry.get("code")
                message = entry.get("error", "")
                # stop_event 중단은 "중단", 그 외 coded error(미래/형식 오류·
                # 가드 영구차단)는 "차단"으로 구분해 echo/log한다.
                label = (
                    "중단"
                    if code == CONFIG_ERROR_CODE_BACKFILL_STOP_REQUESTED
                    else "차단"
                )
                logger.error(
                    "Backfill %s (%s): code=%s, error=%s",
                    label,
                    current_date,
                    code,
                    message,
                )
                click.echo(f"[{current_date}] Backfill {label}: {code} — {message}")
            return
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
