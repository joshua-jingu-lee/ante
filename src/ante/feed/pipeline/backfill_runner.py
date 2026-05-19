"""BackfillRunner — 과거 데이터 대량 수집 (backfill 모드)."""

from __future__ import annotations

import logging
import re
from datetime import UTC, date, datetime, timedelta, timezone
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

# zero-padded YYYY-MM-DD만 허용. date.fromisoformat()은 3.11+에서
# basic ISO(20260510)·ISO week date(2026-W19-1) 등 변형도 수락하므로
# 형태를 정규식으로 먼저 고정한 뒤 캘린더 유효성만 검증한다.
# CLI `--since`(feed/cli.py::_validate_iso_date)와 동일한 strictness를
# 사용해 두 진입 표면을 정합시킨다(이슈 #1674).
_BACKFILL_ISO_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")

# coded config_error 코드. CLI/scheduler가 이 코드를 관측해 분기하므로,
# 기존 비날짜 config_errors(`code` 키 없는 dict)와 명확히 구분된다.
CONFIG_ERROR_CODE_INVALID_DATE = "CLI_INVALID_DATE"
CONFIG_ERROR_CODE_INVALID_DATE_RANGE = "INVALID_DATE_RANGE"

# 신설 coded config_errors의 코드 집합. CLI/scheduler에서 이 집합으로만
# 새 envelope/차단 분기를 trigger한다 (기존 비날짜 entries 보존).
BACKFILL_DATE_ERROR_CODES = frozenset(
    {
        CONFIG_ERROR_CODE_INVALID_DATE,
        CONFIG_ERROR_CODE_INVALID_DATE_RANGE,
    }
)

# `today`는 KST 캘린더 기준으로 산출한다. backfill_since는 거래일 단위
# 날짜이며 cli_scheduler도 KST(UTC+9)로 동작한다(see cli_scheduler.KST).
_KST = timezone(timedelta(hours=9))


def _parse_strict_backfill_since(value: str) -> date | None:
    """``backfill_since`` 값을 strict ``YYYY-MM-DD``로 파싱한다.

    backfill 진입 표면(CLI ``--since`` / config TOML ``backfill_since``)이
    공유하는 helper. 형태가 어긋나거나 캘린더상 유효하지 않으면 ``None`` 을
    반환한다(호출 측이 ``CLI_INVALID_DATE`` config_error로 변환).

    feed-local 사용에 한정한다 — 전역 validators 통합 금지(이슈 #1674
    Stop Condition).
    """
    if not isinstance(value, str):
        return None
    if _BACKFILL_ISO_DATE_RE.fullmatch(value) is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _today_kst() -> date:
    """오늘 날짜(KST 캘린더)를 반환한다."""
    return datetime.now(tz=_KST).date()


def validate_backfill_since(
    value: str,
) -> tuple[date | None, dict[str, str] | None]:
    """``backfill_since`` 값을 strict 검증한다.

    반환값:
        ``(parsed_date, None)`` — strict ``YYYY-MM-DD`` + ``start <= today``
        ``(None, {"code": "CLI_INVALID_DATE", "error": ...})`` — 형태/캘린더 위반
        ``(None, {"code": "INVALID_DATE_RANGE", "error": ...})`` — ``start > today``

    config_error dict는 ``CollectionResult.config_errors`` 에 그대로
    삽입할 수 있는 shape이다(``code`` 키 존재로 비날짜 error와 구분).
    """
    parsed = _parse_strict_backfill_since(value)
    if parsed is None:
        return None, {
            "code": CONFIG_ERROR_CODE_INVALID_DATE,
            "error": (
                f"잘못된 backfill_since 날짜 형식: '{value}' (YYYY-MM-DD 형식 필요)"
            ),
        }

    today = _today_kst()
    if parsed > today:
        return None, {
            "code": CONFIG_ERROR_CODE_INVALID_DATE_RANGE,
            "error": (
                f"backfill_since가 오늘({today.isoformat()})보다 미래입니다: '{value}'"
            ),
        }
    return parsed, None


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
        """Backfill 내부 구현. data.go.kr + DART 수집 후 지표 계산.

        backfill_since strict 검증은 수렴점이므로 수집 메서드 진입 전
        가장 먼저 수행한다. malformed/future일 때는 체크포인트·소스
        접근 없이 coded config_error만 담은 result를 즉시 반환한다.
        """
        # strict 날짜 검증을 가장 먼저 수행해 malformed/future config가
        # checkpoint/소스/지표 어디에도 도달하지 않도록 한다.
        coded_date_error = self._validate_backfill_since(config)
        if coded_date_error is not None:
            logger.warning(
                "Backfill 차단: backfill_since 검증 실패 (code=%s, error=%s)",
                coded_date_error.get("code"),
                coded_date_error.get("error"),
            )
            return _make_result(
                "backfill",
                started_at,
                config_errors=[coded_date_error],
            )

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
        self._compute_indicators(store, ctx)

        return ctx.to_result("backfill", started_at)

    @staticmethod
    def _validate_backfill_since(
        config: dict[str, Any],
    ) -> dict[str, str] | None:
        """``[schedule].backfill_since``를 strict 검증한다.

        config에 ``backfill_since`` 가 명시되어 있을 때만 검증한다.
        키 부재 시에는 ``DEFAULT_BACKFILL_SINCE`` (`2015-01-01`)가
        쓰이며 정의상 strict + past이므로 검증을 건너뛴다.

        Returns:
            None이면 strict 통과 (수집 진입 가능).
            dict이면 coded config_error (``code`` 키 = CLI_INVALID_DATE /
            INVALID_DATE_RANGE).
        """
        schedule = config.get("schedule")
        if not isinstance(schedule, dict):
            return None
        if "backfill_since" not in schedule:
            return None
        raw = schedule.get("backfill_since")
        if not isinstance(raw, str):
            return {
                "code": CONFIG_ERROR_CODE_INVALID_DATE,
                "error": (
                    f"잘못된 backfill_since 날짜 형식: {raw!r} (YYYY-MM-DD 형식 필요)"
                ),
            }
        _parsed, error = validate_backfill_since(raw)
        return error

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
