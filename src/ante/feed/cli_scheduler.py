"""ante feed start — 상주 스케줄러 루프."""

from __future__ import annotations

import asyncio
import logging
import re
import signal
from datetime import timedelta, timezone
from pathlib import Path
from typing import Any

import click

from ante.core import clock

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))

_HHMM_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _is_valid_hhmm(s: str) -> bool:
    """``s`` 가 zero-padded ``HH:MM`` (00:00–23:59) 형식인지 검증한다."""
    return isinstance(s, str) and _HHMM_RE.fullmatch(s) is not None


def _validate_schedule_times(
    daily_at: str,
    backfill_at: str,
    blocked_hours: list[Any] | None = None,
) -> None:
    """스케줄러 진입 시 시간 설정을 1회 fail-fast 검증한다."""
    errors: list[str] = []

    if not _is_valid_hhmm(daily_at):
        errors.append(
            f"잘못된 daily_at 형식: '{daily_at}' (zero-padded HH:MM 필요, 예: 16:00)"
        )
    if not _is_valid_hhmm(backfill_at):
        errors.append(
            f"잘못된 backfill_at 형식: '{backfill_at}' "
            "(zero-padded HH:MM 필요, 예: 01:00)"
        )

    for window in blocked_hours or []:
        if not isinstance(window, str) or "-" not in window:
            errors.append(
                f"잘못된 blocked_hours 항목: '{window}' "
                "(HH:MM-HH:MM 형식 필요, 예: 09:00-15:30)"
            )
            continue
        start_time, end_time = (part.strip() for part in window.split("-", 1))
        if not _is_valid_hhmm(start_time) or not _is_valid_hhmm(end_time):
            errors.append(
                f"잘못된 blocked_hours 항목: '{window}' "
                "(양 끝점 모두 zero-padded HH:MM 필요, 예: 09:00-15:30)"
            )

    if errors:
        raise ValueError("; ".join(errors))


def validate_schedule(config: dict[str, Any], daily_at: str, backfill_at: str) -> None:
    """스케줄 시각과 ``guard.blocked_hours`` 를 검증한다(실패 시 ValueError)."""
    guard = config.get("guard") if isinstance(config, dict) else None
    blocked_hours = guard.get("blocked_hours") if isinstance(guard, dict) else None
    _validate_schedule_times(daily_at, backfill_at, blocked_hours)


async def run_scheduler_loop(
    orchestrator: Any,
    data_path: str,
    config: dict[str, Any],
    daily_at: str,
    backfill_at: str,
) -> None:
    """스케줄 루프: daily_at / backfill_at 시각에 수집을 실행한다.

    진입 시 ``daily_at`` / ``backfill_at`` (및 config 의 ``blocked_hours``)
    형식을 1회 fail-fast 검증한다. ``feed start`` 는 루프 전에 같은 검증을
    먼저 하고, 이 검증은 직접 호출자를 위한 방어로 남아 non-padded("9:00")
    등으로 인한 조용한 미실행을 진입 시점에 ``ValueError`` 로 차단한다. 루프
    내부에서는 재검증하지 않는다.
    """
    validate_schedule(config, daily_at, backfill_at)

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
        now = clock.now(KST)
        current_time = now.strftime("%H:%M")
        current_date = now.strftime("%Y-%m-%d")

        if last_date and last_date != current_date:
            daily_ran_today = False
            backfill_ran_today = False
        last_date = current_date

        if not backfill_ran_today and current_time >= str(backfill_at):
            await _run_backfill_job(
                orchestrator, data_path, config, current_date, stop_event
            )
            backfill_ran_today = True

        if not daily_ran_today and current_time >= str(daily_at):
            await _run_daily_job(orchestrator, data_path, config, current_date)
            daily_ran_today = True

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
    orchestrator: Any,
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
    orchestrator: Any,
    data_path: str,
    config: dict[str, Any],
    current_date: str,
    stop_event: asyncio.Event | None = None,
) -> None:
    """Backfill 수집 작업을 1회 실행한다."""
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
