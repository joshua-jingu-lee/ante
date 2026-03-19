"""BackfillRunner — 과거 데이터 대량 수집 (backfill 모드)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ante.data.store import ParquetStore
from ante.feed.models.result import CollectionResult
from ante.feed.pipeline.checkpoint import Checkpoint
from ante.feed.pipeline.dart_collector import DARTCollector
from ante.feed.pipeline.data_go_kr_collector import DataGoKrCollector
from ante.feed.pipeline.indicator_calculator import IndicatorCalculator
from ante.feed.pipeline.scheduler import generate_backfill_dates
from ante.feed.sources.dart import (
    CriticalApiError as DARTCriticalError,
)
from ante.feed.sources.dart import (
    DailyLimitExceededError as DARTDailyLimitError,
)
from ante.feed.sources.data_go_kr import (
    CriticalApiError as DataGoKrCriticalError,
)
from ante.feed.sources.data_go_kr import (
    DailyLimitExceededError as DataGoKrDailyLimitError,
)

logger = logging.getLogger(__name__)

DEFAULT_BACKFILL_SINCE = "2015-01-01"


class BackfillRunner:
    """Backfill 모드 ETL 실행기.

    체크포인트 기반으로 날짜 범위를 생성하고,
    DataGoKrCollector + DARTCollector + IndicatorCalculator를 순서대로 실행한다.
    """

    def __init__(
        self,
        data_go_kr_collector: DataGoKrCollector | None = None,
        dart_collector: DARTCollector | None = None,
        indicator_calculator: IndicatorCalculator | None = None,
        store: ParquetStore | None = None,
    ) -> None:
        self._data_go_kr = data_go_kr_collector
        self._dart = dart_collector
        self._indicator = indicator_calculator or IndicatorCalculator()
        self._store = store

    async def run(
        self,
        data_path: Path,
        config: dict[str, Any],
        feed_dir: Path,
        started_at: datetime,
        is_blocked: Any,
    ) -> CollectionResult:
        """Backfill 내부 구현.

        Args:
            data_path: Ante 데이터 저장소 루트 경로.
            config: 설정 딕셔너리.
            feed_dir: .feed 디렉토리.
            started_at: 실행 시작 시각.
            is_blocked: 방어 가드 함수.

        Returns:
            수집 결과 CollectionResult.
        """
        ctx = _RunContext()
        store = self._store or ParquetStore(base_path=data_path)

        dates = self._resolve_dates(config, feed_dir)
        if not dates:
            logger.info("Backfill: 수집할 날짜 없음 (이미 완료)")
            return _make_result("backfill", started_at)

        self._check_sources(ctx)

        ohlcv_checkpoint = Checkpoint(feed_dir, "data_go_kr", "ohlcv")
        dart_checkpoint = Checkpoint(feed_dir, "dart", "fundamental")

        await self._collect_data_go_kr(
            dates,
            config,
            store,
            ohlcv_checkpoint,
            ctx,
            is_blocked,
        )
        await self._collect_dart(
            data_path,
            feed_dir,
            dart_checkpoint,
            config,
            store,
            ctx,
        )
        await self._compute_indicators(store, ctx)

        return ctx.to_result("backfill", started_at)

    @staticmethod
    def _resolve_dates(
        config: dict[str, Any],
        feed_dir: Path,
    ) -> list[str]:
        """체크포인트 기반으로 backfill 날짜 목록을 생성한다."""
        schedule = config.get("schedule", {})
        backfill_since = schedule.get("backfill_since", DEFAULT_BACKFILL_SINCE)
        ohlcv_checkpoint = Checkpoint(feed_dir, "data_go_kr", "ohlcv")
        last_date = ohlcv_checkpoint.get_last_date()

        return list(
            generate_backfill_dates(
                start=backfill_since,
                last_checkpoint=last_date,
            )
        )

    def _check_sources(self, ctx: _RunContext) -> None:
        """소스 누락을 확인하여 config_errors에 기록한다."""
        if self._data_go_kr is None:
            ctx.config_errors.append(
                {
                    "error": "data.go.kr API 키 미설정",
                    "source": "data_go_kr",
                }
            )
        if self._dart is None:
            ctx.config_errors.append(
                {
                    "error": "DART API 키 미설정",
                    "source": "dart",
                }
            )

    async def _collect_data_go_kr(
        self,
        dates: list[str],
        config: dict[str, Any],
        store: ParquetStore,
        checkpoint: Checkpoint,
        ctx: _RunContext,
        is_blocked: Any,
    ) -> None:
        """data.go.kr 날짜별 수집을 실행한다."""
        if self._data_go_kr is None:
            return

        for target_date in dates:
            if is_blocked(config, target_date):
                logger.debug("방어 가드: %s 스킵", target_date)
                continue

            try:
                written, syms, warns = await self._data_go_kr.collect(
                    target_date,
                    store,
                )
                ctx.add_success(written, syms, warns)
                if written > 0:
                    ctx.data_types.update(["ohlcv", "fundamental"])
                checkpoint.save(target_date)

            except (DataGoKrDailyLimitError, DataGoKrCriticalError) as exc:
                logger.critical("data.go.kr 수집 중단: %s", exc)
                ctx.config_errors.append(
                    {
                        "error": str(exc),
                        "source": "data_go_kr",
                    }
                )
                break
            except Exception as exc:
                logger.error(
                    "data.go.kr 수집 실패: date=%s, %s",
                    target_date,
                    exc,
                )
                ctx.failures.append(
                    {
                        "date": target_date,
                        "source": "data_go_kr",
                        "reason": str(exc),
                    }
                )

    async def _collect_dart(
        self,
        data_path: Path,
        feed_dir: Path,
        checkpoint: Checkpoint,
        config: dict[str, Any],
        store: ParquetStore,
        ctx: _RunContext,
    ) -> None:
        """DART 분기별 수집을 실행한다."""
        if self._dart is None:
            return

        try:
            written, syms, warns = await self._dart.collect(
                data_path,
                feed_dir,
                checkpoint,
                config,
                store,
            )
            ctx.add_success(written, syms, warns)
            if written > 0:
                ctx.data_types.add("fundamental")
        except (DARTDailyLimitError, DARTCriticalError) as exc:
            logger.critical("DART 수집 중단: %s", exc)
            ctx.config_errors.append(
                {
                    "error": str(exc),
                    "source": "dart",
                }
            )
        except Exception as exc:
            logger.error("DART 수집 실패: %s", exc)
            ctx.failures.append(
                {
                    "source": "dart",
                    "reason": str(exc),
                }
            )

    async def _compute_indicators(
        self,
        store: ParquetStore,
        ctx: _RunContext,
    ) -> None:
        """파생 지표를 계산한다."""
        if "fundamental" not in ctx.data_types:
            return
        if not ctx.success_symbols:
            return

        try:
            written = await self._indicator.compute(
                store,
                list(ctx.success_symbols),
            )
            ctx.rows_written += written
        except Exception as exc:
            logger.error("파생 지표 계산 실패: %s", exc)
            ctx.warnings.append(
                {
                    "type": "derived_indicators",
                    "message": f"파생 지표 계산 실패: {exc}",
                }
            )


class _RunContext:
    """수집 실행 중 결과를 집계하는 컨텍스트."""

    def __init__(self) -> None:
        self.failures: list[dict] = []
        self.warnings: list[dict] = []
        self.config_errors: list[dict] = []
        self.total_symbols: set[str] = set()
        self.success_symbols: set[str] = set()
        self.rows_written: int = 0
        self.data_types: set[str] = set()

    def add_success(
        self,
        written: int,
        syms: set[str],
        warns: list[dict],
    ) -> None:
        """성공 결과를 집계한다."""
        self.rows_written += written
        self.total_symbols.update(syms)
        self.success_symbols.update(syms)
        if warns:
            self.warnings.extend(warns)

    def to_result(
        self,
        mode: str,
        started_at: datetime,
        target_date: str | None = None,
    ) -> CollectionResult:
        """집계 결과를 CollectionResult로 변환한다."""
        failed = self.total_symbols - self.success_symbols
        return _make_result(
            mode=mode,
            started_at=started_at,
            target_date=target_date,
            symbols_total=len(self.total_symbols),
            symbols_success=len(self.success_symbols),
            symbols_failed=len(failed),
            rows_written=self.rows_written,
            data_types=sorted(self.data_types),
            failures=self.failures,
            warnings=self.warnings,
            config_errors=self.config_errors,
        )


def _make_result(
    mode: str,
    started_at: datetime,
    target_date: str | None = None,
    symbols_total: int = 0,
    symbols_success: int = 0,
    symbols_failed: int = 0,
    rows_written: int = 0,
    data_types: list[str] | None = None,
    failures: list[dict] | None = None,
    warnings: list[dict] | None = None,
    config_errors: list[dict] | None = None,
) -> CollectionResult:
    """CollectionResult를 생성한다."""
    finished_at = datetime.now(tz=UTC)
    duration = (finished_at - started_at).total_seconds()

    return CollectionResult(
        mode=mode,
        started_at=started_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        finished_at=finished_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        duration_seconds=duration,
        target_date=target_date,
        symbols_total=symbols_total,
        symbols_success=symbols_success,
        symbols_failed=symbols_failed,
        rows_written=rows_written,
        data_types=data_types or [],
        failures=failures or [],
        warnings=warnings or [],
        config_errors=config_errors or [],
    )
