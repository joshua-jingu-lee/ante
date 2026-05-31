"""FeedOrchestrator — backfill/daily ETL 파이프라인 오케스트레이션.

수집/정규화/지표 계산은 전담 클래스에 위임하고,
lock 관리, 방어 가드, 리포트 생성만 담당한다.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

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
        stop_event: asyncio.Event | None = None,
    ) -> CollectionResult:
        """과거 데이터 대량 수집 (backfill 모드).

        ``[schedule].backfill_since`` strict 검증은 lock acquire 이전에
        수행한다. malformed/future일 때는 lock 파일을 만들지 않고
        coded config_error만 담은 결과를 즉시 반환한다(체크포인트·소스
        진입 차단).

        ``stop_event`` 는 상주 스케줄러(``feed start``)가 SIGTERM/SIGINT
        수신 시 거래시간 대기 중인 backfill 루프를 깨워 안전 종료시키기
        위해 전달한다. one-shot(``feed run backfill``)은 ``None`` 이며,
        이 경우 대기는 ``asyncio.sleep`` 로 동작해 ``asyncio.run`` 의
        SIGINT 취소로 중단된다.
        """
        feed_dir = data_path / ".feed"
        started_at = datetime.now(tz=UTC)

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
        같이 명시 지정된 값은 그대로 forward 된다. #1943.
        """
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
                target_date=target_date,
            )
            self._save_report(data_path, feed_dir, result, "daily")
            return result
        finally:
            self._release_lock(feed_dir)

    # ── 방어 가드 ─────────────────────────────────────────
    #
    # 가드는 의미가 다른 두 축으로 분리한다 (#1972):
    #   - ``_is_blocked_day``  : ``blocked_days``. **target_date 기반**.
    #     과거 특정 요일(예: 주말)은 데이터가 없어 영원히 채워지지 않으므로
    #     backfill 루프는 해당 날짜를 **skip** 해야 한다(대기하면 그 날짜의
    #     요일은 절대 안 바뀌어 무한 hang).
    #   - ``_is_trading_paused`` : ``pause_during_trading`` + ``blocked_hours``.
    #     **현재 시각(KST) 기반**. 거래시간 동안 API 부하를 피하려는 의도이며
    #     window가 지나면 데이터는 존재하므로 backfill 루프는 **대기 후
    #     resume** 해야 한다.
    # ``_is_blocked`` 는 두 축의 OR 합성으로 동작을 보존한다 — daily_runner는
    # 이 결합 술어를 그대로 사용한다(무변경).

    @staticmethod
    def _is_blocked_day(config: dict[str, Any], target_date: str) -> bool:
        """``blocked_days`` 가드 — target_date의 요일 기반.

        해당 요일이면 ``True`` (그 과거 날짜는 데이터가 없어 skip 대상).
        """
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
        """``pause_during_trading`` + ``blocked_hours`` 가드 — 현재 시각 기반.

        현재 KST 시각이 거래시간 window 안에 있으면 ``True`` (대기 대상).
        midnight-spanning window(예: "23:00-02:00")는 현 문자열 비교가
        다루지 못한다(pre-existing known-limitation, 본 이슈 범위 밖).
        """
        guard = config.get("guard", {})
        pause_during_trading = guard.get("pause_during_trading", False)
        blocked_hours = guard.get("blocked_hours", [])

        if not (pause_during_trading and blocked_hours):
            return False

        kst = timezone(timedelta(hours=9))
        now_kst = datetime.now(tz=kst)
        current_hour_min = now_kst.strftime("%H:%M")

        for window in blocked_hours:
            if "-" in window:
                start_time, end_time = window.split("-")
                if start_time.strip() <= current_hour_min <= end_time.strip():
                    return True

        return False

    @classmethod
    def _is_blocked(cls, config: dict[str, Any], target_date: str) -> bool:
        """방어 가드 조건을 확인한다(두 축의 합성).

        daily 모드 등 "차단 시 skip(다음 run 재시도)" 의미가 필요한 호출자가
        사용한다. 동작은 분리 이전과 동일하다(behavior-preserving).
        """
        return cls._is_blocked_day(config, target_date) or cls._is_trading_paused(
            config
        )

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
