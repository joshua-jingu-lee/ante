"""FeedOrchestrator — backfill/daily ETL 파이프라인 오케스트레이션."""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import UTC, date, timedelta, timezone
from pathlib import Path
from typing import Any

from ante.core import clock
from ante.data.normalizer import DARTNormalizer, DataGoKrNormalizer
from ante.data.store import ParquetStore
from ante.feed.models.result import CollectionResult
from ante.feed.pipeline.backfill_runner import (
    BackfillRunner,
    _make_result,
)
from ante.feed.pipeline.daily_runner import DailyRunner
from ante.feed.pipeline.dart_collector import DARTCollector
from ante.feed.pipeline.data_go_kr_collector import DataGoKrCollector
from ante.feed.pipeline.indicator_calculator import IndicatorCalculator
from ante.feed.report.generator import ReportGenerator
from ante.feed.sources.dart import DARTSource
from ante.feed.sources.data_go_kr import DataGoKrSource

logger = logging.getLogger(__name__)

LOCK_FILE = "lock"


class FeedOrchestrator:
    """DataFeed ETL 오케스트레이터 (lock/가드/리포트만 담당)."""

    def __init__(
        self,
        data_go_kr_source: DataGoKrSource | None = None,
        dart_source: DARTSource | None = None,
        store: ParquetStore | None = None,
        data_go_kr_normalizer: DataGoKrNormalizer | None = None,
        dart_normalizer: DARTNormalizer | None = None,
        report_generator: ReportGenerator | None = None,
    ) -> None:
        self._store = store
        self._report_generator = report_generator

        data_go_kr_collector = (
            DataGoKrCollector(data_go_kr_source, data_go_kr_normalizer)
            if data_go_kr_source
            else None
        )
        dart_collector = (
            DARTCollector(dart_source, dart_normalizer) if dart_source else None
        )
        indicator = IndicatorCalculator()

        self._backfill_runner = BackfillRunner(
            data_go_kr_collector=data_go_kr_collector,
            dart_collector=dart_collector,
            indicator_calculator=indicator,
            store=store,
        )
        self._daily_runner = DailyRunner(
            data_go_kr_collector=data_go_kr_collector,
            dart_collector=dart_collector,
            indicator_calculator=indicator,
            store=store,
        )

    async def run_backfill(
        self,
        data_path: Path,
        config: dict[str, Any],
        stop_event: asyncio.Event | None = None,
    ) -> CollectionResult:
        """과거 데이터 대량 수집 (backfill 모드).

        ``[schedule].backfill_since`` strict 검증은 lock acquire 이전에
        수행한다. malformed/future일 때는 lock 파일을 만들지 않고
        coded config_error만 담은 결과를 즉시 반환한다(체크포인트·소스
        진입 차단).
        """
        feed_dir = data_path / ".feed"
        started_at = clock.now(UTC)

        coded_date_error = BackfillRunner._validate_backfill_since(config)
        if coded_date_error is not None:
            logger.warning(
                "Backfill 차단(orchestrator): code=%s, error=%s",
                coded_date_error.get("code"),
                coded_date_error.get("error"),
            )
            return _make_result(
                "backfill",
                started_at,
                config_errors=[coded_date_error],
            )

        if not self._acquire_lock(feed_dir):
            return _make_result(
                "backfill",
                started_at,
                config_errors=[{"error": "다른 수집 프로세스가 이미 실행 중"}],
            )

        try:
            result = await self._backfill_runner.run(
                data_path,
                config,
                feed_dir,
                started_at,
                self._is_blocked_day,
                self._is_trading_paused,
                stop_event=stop_event,
            )
            self._save_report(data_path, feed_dir, result, "backfill")
            return result
        finally:
            self._release_lock(feed_dir)

    async def run_daily(
        self,
        data_path: Path,
        config: dict[str, Any],
        target_date: str | None = None,
    ) -> CollectionResult:
        """일별 증분 수집 (daily 모드).

        ``target_date`` 가 ``None`` 이면 ``DailyRunner.run`` 내부에서
        ``generate_daily_date()`` (어제)로 fallback 한다. CLI ``--date``
        같이 명시 지정된 값은 그대로 forward 된다.
        """
        feed_dir = data_path / ".feed"
        started_at = clock.now(UTC)

        if not self._acquire_lock(feed_dir):
            return _make_result(
                "daily",
                started_at,
                config_errors=[{"error": "다른 수집 프로세스가 이미 실행 중"}],
            )

        try:
            result = await self._daily_runner.run(
                data_path,
                config,
                feed_dir,
                started_at,
                self._is_blocked,
                target_date=target_date,
            )
            self._save_report(data_path, feed_dir, result, "daily")
            return result
        finally:
            self._release_lock(feed_dir)

    @staticmethod
    def _is_blocked_day(config: dict[str, Any], target_date: str) -> bool:
        """``blocked_days`` 가드 — target_date의 요일 기반."""
        guard = config.get("guard", {})
        blocked_days = guard.get("blocked_days", [])
        if not blocked_days:
            return False

        d = date.fromisoformat(target_date)
        day_names = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
        current_day = day_names[d.weekday()]
        return current_day in [bd.lower() for bd in blocked_days]

    @staticmethod
    def _is_trading_paused(config: dict[str, Any]) -> bool:
        """``pause_during_trading`` + ``blocked_hours`` 가드 — 현재 시각 기반."""
        guard = config.get("guard", {})
        pause_during_trading = guard.get("pause_during_trading", False)
        blocked_hours = guard.get("blocked_hours", [])

        if not (pause_during_trading and blocked_hours):
            return False

        kst = timezone(timedelta(hours=9))
        now_kst = clock.now(kst)
        current_hour_min = now_kst.strftime("%H:%M")

        for window in blocked_hours:
            if "-" in window:
                start_time, end_time = window.split("-")
                if start_time.strip() <= current_hour_min <= end_time.strip():
                    return True

        return False

    @classmethod
    def _is_blocked(cls, config: dict[str, Any], target_date: str) -> bool:
        """방어 가드 조건을 확인한다(두 축의 합성)."""
        return cls._is_blocked_day(config, target_date) or cls._is_trading_paused(
            config
        )

    @staticmethod
    def _acquire_lock(feed_dir: Path) -> bool:
        """Lock 파일을 원자적으로 생성하여 동시 실행을 방지한다."""
        lock_path = feed_dir / LOCK_FILE
        feed_dir.mkdir(parents=True, exist_ok=True)

        for _ in range(3):
            try:
                fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            except FileExistsError:
                try:
                    pid = int(lock_path.read_text().strip())
                except (ValueError, OSError):
                    logger.warning("비정상 lock 파일(PID 파싱 불가), 제거 후 재시도")
                    lock_path.unlink(missing_ok=True)
                    continue

                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    logger.warning("stale lock 감지(PID=%d 없음), 제거 후 재시도", pid)
                    lock_path.unlink(missing_ok=True)
                    continue
                except PermissionError:
                    logger.error(
                        "다른 수집 프로세스가 실행 중 (PID=%d, signal 권한 없음)", pid
                    )
                    return False
                else:
                    logger.error("다른 수집 프로세스가 실행 중 (PID=%d)", pid)
                    return False
            else:
                try:
                    os.write(fd, str(os.getpid()).encode())
                finally:
                    os.close(fd)
                return True

        logger.error("lock 획득 실패(반복 race)")
        return False

    @staticmethod
    def _release_lock(feed_dir: Path) -> None:
        """Lock 파일을 제거한다."""
        lock_path = feed_dir / LOCK_FILE
        lock_path.unlink(missing_ok=True)

    def _save_report(
        self,
        data_path: Path,
        feed_dir: Path,
        result: CollectionResult,
        mode: str,
    ) -> None:
        """리포트를 생성하고 저장한다."""
        generator = self._report_generator or ReportGenerator(feed_dir)
        report = generator.generate(result)
        generator.save(data_path, report, mode)
