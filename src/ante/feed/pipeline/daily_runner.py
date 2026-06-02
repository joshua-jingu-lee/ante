"""DailyRunner — 일별 증분 수집 (daily 모드)."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from ante.data.store import ParquetStore
from ante.feed.models.result import CollectionResult
from ante.feed.pipeline.backfill_runner import _make_result, _RunContext
from ante.feed.pipeline.checkpoint import Checkpoint
from ante.feed.pipeline.dart_collector import DARTCollector
from ante.feed.pipeline.data_go_kr_collector import DataGoKrCollector
from ante.feed.pipeline.indicator_calculator import IndicatorCalculator
from ante.feed.pipeline.scheduler import generate_daily_date
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


class DailyRunner:
    """Daily 모드 ETL 실행기.

    어제 1일치 데이터를 수집한다. backfill과 동일한 ETL 흐름.
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
        target_date: str | None = None,
    ) -> CollectionResult:
        """Daily 내부 구현.

        ``target_date`` 가 ``None`` 이면 ``generate_daily_date()`` (어제)로
        fallback 한다. 명시 값(예: CLI ``--date`` 또는 스케줄러가 직접
        지정한 날짜)을 받으면 그 값을 그대로 수집 대상일로 사용한다.
        #1943: 기존에는 cli 에서 ``scheduler.generate_daily_date`` 모듈
        속성을 monkey-patch 했으나, 이 모듈이 import 시점에
        ``from ... import generate_daily_date`` 로 함수 객체를 local
        namespace 에 바인딩하기 때문에 패치가 무효였다. 명시 파라미터
        chain 으로 대체한다.
        """
        if target_date is None:
            target_date = generate_daily_date()

        if is_blocked(config, target_date):
            logger.info("Daily: 방어 가드에 의해 스킵 (date=%s)", target_date)
            return _make_result("daily", started_at, target_date=target_date)

        ctx = _RunContext()
        store = self._store or ParquetStore(base_path=data_path)

        # 각 store 쓰기 단계 직후 store의 merge 이상 경고를 drain하여
        # CollectionResult.warnings(→ daily report `warnings`)로 표면화한다.
        # backfill_runner.run()의 drain 지점(data.go.kr/DART/지표 후)을
        # 정확히 미러한다(#2002). collector 미주입(None) skip 경로에서도
        # drain은 빈 경고를 반환해 안전하다.
        await self._collect_data_go_kr(target_date, store, ctx)
        ctx.warnings.extend(store.drain_warnings())
        await self._collect_dart(
            data_path,
            feed_dir,
            config,
            store,
            ctx,
        )
        ctx.warnings.extend(store.drain_warnings())
        self._compute_indicators(store, ctx)
        ctx.warnings.extend(store.drain_warnings())

        return ctx.to_result("daily", started_at, target_date=target_date)

    async def _collect_data_go_kr(
        self,
        target_date: str,
        store: ParquetStore,
        ctx: _RunContext,
    ) -> None:
        """data.go.kr 일별 수집을 실행한다."""
        if self._data_go_kr is None:
            ctx.config_errors.append(
                {
                    "error": "data.go.kr API 키 미설정",
                    "source": "data_go_kr",
                }
            )
            return

        try:
            written, syms, warns = await self._data_go_kr.collect(
                target_date,
                store,
            )
            ctx.add_success(written, syms, warns)
            if written > 0:
                ctx.data_types.update(["ohlcv", "fundamental"])
        except (DataGoKrDailyLimitError, DataGoKrCriticalError) as exc:
            ctx.config_errors.append(
                {
                    "error": str(exc),
                    "source": "data_go_kr",
                }
            )
        except Exception as exc:
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
        config: dict[str, Any],
        store: ParquetStore,
        ctx: _RunContext,
    ) -> None:
        """DART 일별 수집을 실행한다."""
        if self._dart is None:
            ctx.config_errors.append(
                {
                    "error": "DART API 키 미설정",
                    "source": "dart",
                }
            )
            return

        checkpoint = Checkpoint(feed_dir, "dart", "fundamental")
        try:
            # daily=True: DART는 분기 공시이므로 daily-equivalent은 "최신
            # collectable 분기 1개"만 수집한다(#2101). backfill_since 전 분기를
            # 순회하지 않는다. 과거 미충전 분기 보정은 backfill 모드 책임이며,
            # daily는 최신 분기 증분만 담당한다.
            written, syms, warns = await self._dart.collect(
                data_path,
                feed_dir,
                checkpoint,
                config,
                store,
                daily=True,
            )
            ctx.add_success(written, syms, warns)
            if written > 0:
                ctx.data_types.add("fundamental")
        except (DARTDailyLimitError, DARTCriticalError) as exc:
            ctx.config_errors.append(
                {
                    "error": str(exc),
                    "source": "dart",
                }
            )
        except Exception as exc:
            ctx.failures.append(
                {
                    "source": "dart",
                    "reason": str(exc),
                }
            )

    def _compute_indicators(
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
            written = self._indicator.compute(
                store,
                list(ctx.success_symbols),
            )
            ctx.rows_written += written
        except Exception as exc:
            ctx.warnings.append(
                {
                    "type": "derived_indicators",
                    "message": f"파생 지표 계산 실패: {exc}",
                }
            )
