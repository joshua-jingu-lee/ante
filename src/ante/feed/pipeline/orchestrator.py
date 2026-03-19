"""FeedOrchestrator — backfill/daily ETL 파이프라인 오케스트레이션.

수집/정규화/지표 계산은 전담 클래스에 위임하고,
lock 관리, 방어 가드, 리포트 생성만 담당한다.
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ante.data.normalizer import DARTNormalizer, DataGoKrNormalizer
from ante.data.store import ParquetStore
from ante.feed.models.result import CollectionResult
from ante.feed.pipeline.backfill_runner import BackfillRunner, _make_result
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

        # 하위 컬렉터 조립
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
    ) -> CollectionResult:
        """과거 데이터 대량 수집 (backfill 모드)."""
        feed_dir = data_path / ".feed"
        started_at = datetime.now(tz=UTC)

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
                self._is_blocked,
            )
            self._save_report(data_path, feed_dir, result, "backfill")
            return result
        finally:
            self._release_lock(feed_dir)

    async def run_daily(
        self,
        data_path: Path,
        config: dict[str, Any],
    ) -> CollectionResult:
        """일별 증분 수집 (daily 모드)."""
        feed_dir = data_path / ".feed"
        started_at = datetime.now(tz=UTC)

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
            )
            self._save_report(data_path, feed_dir, result, "daily")
            return result
        finally:
            self._release_lock(feed_dir)

    # ── 방어 가드 ─────────────────────────────────────────

    @staticmethod
    def _is_blocked(config: dict[str, Any], target_date: str) -> bool:
        """방어 가드 조건을 확인한다."""
        guard = config.get("guard", {})

        blocked_days = guard.get("blocked_days", [])
        if blocked_days:
            d = date.fromisoformat(target_date)
            day_names = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
            current_day = day_names[d.weekday()]
            if current_day in [bd.lower() for bd in blocked_days]:
                return True

        pause_during_trading = guard.get("pause_during_trading", False)
        blocked_hours = guard.get("blocked_hours", [])

        if pause_during_trading and blocked_hours:
            kst = timezone(timedelta(hours=9))
            now_kst = datetime.now(tz=kst)
            current_hour_min = now_kst.strftime("%H:%M")

            for window in blocked_hours:
                if "-" in window:
                    start_time, end_time = window.split("-")
                    if start_time.strip() <= current_hour_min <= end_time.strip():
                        return True

        return False

    # ── Lock 파일 관리 ────────────────────────────────────

    @staticmethod
    def _acquire_lock(feed_dir: Path) -> bool:
        """Lock 파일을 생성하여 동시 실행을 방지한다."""
        lock_path = feed_dir / LOCK_FILE
        feed_dir.mkdir(parents=True, exist_ok=True)

        if lock_path.exists():
            try:
                pid = int(lock_path.read_text().strip())
                os.kill(pid, 0)
                logger.error("다른 수집 프로세스가 실행 중 (PID=%d)", pid)
                return False
            except (ValueError, ProcessLookupError, PermissionError, OSError):
                logger.warning("비정상 lock 파일 감지, 제거 후 진행")
                lock_path.unlink(missing_ok=True)

        lock_path.write_text(str(os.getpid()))
        return True

    @staticmethod
    def _release_lock(feed_dir: Path) -> None:
        """Lock 파일을 제거한다."""
        lock_path = feed_dir / LOCK_FILE
        lock_path.unlink(missing_ok=True)

    # ── 리포트 ────────────────────────────────────────────

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
