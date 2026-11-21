"""BackfillRunner — 과거 데이터 대량 수집 (backfill 모드)."""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ante.data.store import ParquetStore
from ante.feed.models.result import CollectionResult
from ante.feed.pipeline.checkpoint import Checkpoint
from ante.feed.pipeline.dart_collector import DARTCollector
from ante.feed.pipeline.data_go_kr_collector import DataGoKrCollector
from ante.feed.pipeline.indicator_calculator import IndicatorCalculator
from ante.feed.pipeline.scheduler import generate_backfill_dates, is_business_day
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

MAX_WARNINGS_PER_TYPE = 1000

UNTYPED_WARNING_BUCKET = "untyped"

_BACKFILL_ISO_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")

CONFIG_ERROR_CODE_INVALID_DATE = "CLI_INVALID_DATE"
CONFIG_ERROR_CODE_INVALID_DATE_RANGE = "INVALID_DATE_RANGE"

CONFIG_ERROR_CODE_GUARD_PERMANENTLY_BLOCKED = "GUARD_PERMANENTLY_BLOCKED"
CONFIG_ERROR_CODE_BACKFILL_STOP_REQUESTED = "BACKFILL_STOP_REQUESTED"

BACKFILL_DATE_ERROR_CODES = frozenset(
    {
        CONFIG_ERROR_CODE_INVALID_DATE,
        CONFIG_ERROR_CODE_INVALID_DATE_RANGE,
        CONFIG_ERROR_CODE_GUARD_PERMANENTLY_BLOCKED,
        CONFIG_ERROR_CODE_BACKFILL_STOP_REQUESTED,
    }
)

GUARD_WAIT_POLL_SECONDS = 60.0
MAX_GUARD_WAIT_SECONDS = 26 * 60 * 60.0

_KST = timezone(timedelta(hours=9))


def _parse_strict_backfill_since(value: str) -> date | None:
    """``backfill_since`` 값을 strict ``YYYY-MM-DD``로 파싱한다."""
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


_DATA_GO_KR_PUBLISH_HOUR_KST = 13


def _next_business_day(d: date) -> date:
    """``d`` 다음의 첫 영업일(주말 skip)을 반환한다."""
    nxt = d + timedelta(days=1)
    while not is_business_day(nxt.isoformat()):
        nxt += timedelta(days=1)
    return nxt


def _last_published_date(now_kst: datetime) -> date:
    """``now_kst`` 시점에 확실히 공개된 마지막 OHLCV 날짜를 반환한다."""
    today = now_kst.date()
    candidate = today - timedelta(days=1)
    for _ in range(14):
        if is_business_day(candidate.isoformat()):
            deadline = datetime.combine(
                _next_business_day(candidate),
                datetime.min.time().replace(hour=_DATA_GO_KR_PUBLISH_HOUR_KST),
                tzinfo=_KST,
            )
            if deadline <= now_kst:
                return candidate
        candidate -= timedelta(days=1)
    return candidate


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
        is_blocked_day: Callable[[dict[str, Any], str], bool],
        is_trading_paused: Callable[[dict[str, Any]], bool],
        stop_event: asyncio.Event | None = None,
    ) -> CollectionResult:
        """Backfill 내부 구현. data.go.kr + DART 수집 후 지표 계산.

        backfill_since strict 검증은 수렴점이므로 수집 메서드 진입 전
        가장 먼저 수행한다. malformed/future일 때는 체크포인트·소스
        접근 없이 coded config_error만 담은 result를 즉시 반환한다.

        ``stop_event`` 가 주어지면(상주 스케줄러) 거래시간 대기 중
        SIGTERM/SIGINT로 깨어나 체크포인트를 저장한 partial을 반환하며
        ``BACKFILL_STOP_REQUESTED`` 마커를 적재한다.
        """
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
            is_blocked_day,
            is_trading_paused,
            stop_event,
        )
        ctx.add_warnings(store.drain_warnings())
        await self._collect_dart(
            data_path,
            feed_dir,
            dart_checkpoint,
            config,
            store,
            ctx,
        )
        ctx.add_warnings(store.drain_warnings())
        self._compute_indicators(store, ctx)
        ctx.add_warnings(store.drain_warnings())

        return ctx.to_result("backfill", started_at)

    @staticmethod
    def _validate_backfill_since(
        config: dict[str, Any],
    ) -> dict[str, str] | None:
        """``[schedule].backfill_since``를 strict 검증한다."""
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

        published_end = _last_published_date(datetime.now(tz=_KST))

        return list(
            generate_backfill_dates(
                start=backfill_since,
                end=published_end.isoformat(),
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
        is_blocked_day: Callable[[dict[str, Any], str], bool],
        is_trading_paused: Callable[[dict[str, Any]], bool],
        stop_event: asyncio.Event | None,
    ) -> None:
        """data.go.kr 날짜별 수집을 실행한다."""
        if self._data_go_kr is None:
            return

        halt = False

        for target_date in dates:
            if is_blocked_day(config, target_date):
                logger.debug("방어 가드(blocked_days): %s 스킵", target_date)
                continue

            should_stop = await self._wait_out_trading_pause(
                config,
                is_trading_paused,
                stop_event,
                ctx,
            )
            if should_stop:
                break

            try:
                net_delta, stored_ok, syms, warns = await self._data_go_kr.collect(
                    target_date,
                    store,
                )
                ctx.add_success(net_delta, syms, warns)
                if stored_ok:
                    ctx.data_types.update(["ohlcv", "fundamental"])

                store_merge_failed = self._drain_store_warnings(store, ctx)

                if not halt and stored_ok and not store_merge_failed:
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
                halt = True

    @staticmethod
    def _drain_store_warnings(store: ParquetStore, ctx: _RunContext) -> bool:
        """store의 pending 경고를 즉시 drain해 ctx.warnings로 옮기고,

        이번 drain에 ``store_merge`` (파티션 merge 실패 → 기존 파일 보존, 데이터
        미반영) 경고가 있었는지 반환한다(R1).

        checkpoint save 직전에 호출해야 한다 — collect/write 직후 drain해야 이번
        날짜에서 발생한 store-merge 실패를 정확히 귀속할 수 있다(지연 drain이면
        실패 날짜가 이미 checkpoint를 전진시킨 뒤가 된다).

        반환값은 ctx 측 경고 절단과 **무관**하다 — ``drained`` 전수를
        먼저 검사한 뒤 ctx에 적재하며, ``add_warnings`` 는 입력 리스트를
        변형하지 않는다(결정 6). 절단된 ``store_merge`` 도 checkpoint 미전진을
        정확히 유발한다.

        Returns:
            이번 drain에 ``type == "store_merge"`` 경고가 하나라도 있었으면 True.
        """
        drained = store.drain_warnings()
        store_merge_failed = any(w.get("type") == "store_merge" for w in drained)
        if drained:
            ctx.add_warnings(drained)
        return store_merge_failed

    async def _wait_out_trading_pause(
        self,
        config: dict[str, Any],
        is_trading_paused: Callable[[dict[str, Any]], bool],
        stop_event: asyncio.Event | None,
        ctx: _RunContext,
    ) -> bool:
        """거래시간 가드(``blocked_hours``)가 풀릴 때까지 대기한다."""
        waited = 0.0
        first_log = True

        while is_trading_paused(config):
            if stop_event is not None and stop_event.is_set():
                logger.info("Backfill 중단 요청 수신, 거래시간 대기 종료")
                ctx.config_errors.append(
                    {
                        "code": CONFIG_ERROR_CODE_BACKFILL_STOP_REQUESTED,
                        "error": "중단 요청으로 backfill 거래시간 대기를 종료했습니다",
                        "source": "data_go_kr",
                    }
                )
                return True

            if waited >= MAX_GUARD_WAIT_SECONDS:
                logger.error(
                    "거래시간 가드 대기 상한(%.0fs) 초과 — backfill 중단",
                    MAX_GUARD_WAIT_SECONDS,
                )
                ctx.config_errors.append(
                    {
                        "code": CONFIG_ERROR_CODE_GUARD_PERMANENTLY_BLOCKED,
                        "error": (
                            "거래시간 가드(blocked_hours)가 대기 상한"
                            f"({MAX_GUARD_WAIT_SECONDS:.0f}s)을 초과해 해제되지 "
                            "않았습니다. blocked_hours 설정을 확인하세요"
                        ),
                        "source": "data_go_kr",
                    }
                )
                return True

            if first_log:
                logger.info("방어 가드(blocked_hours): 거래시간 종료까지 대기")
                first_log = False

            if stop_event is not None:
                try:
                    await asyncio.wait_for(
                        stop_event.wait(),
                        timeout=GUARD_WAIT_POLL_SECONDS,
                    )
                except TimeoutError:
                    waited += GUARD_WAIT_POLL_SECONDS
                    continue
                logger.info("Backfill 중단 요청 수신, 거래시간 대기 종료")
                ctx.config_errors.append(
                    {
                        "code": CONFIG_ERROR_CODE_BACKFILL_STOP_REQUESTED,
                        "error": "중단 요청으로 backfill 거래시간 대기를 종료했습니다",
                        "source": "data_go_kr",
                    }
                )
                return True

            await asyncio.sleep(GUARD_WAIT_POLL_SECONDS)
            waited += GUARD_WAIT_POLL_SECONDS

        return False

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
            net_delta, stored_ok, syms, warns = await self._dart.collect(
                data_path,
                feed_dir,
                checkpoint,
                config,
                store,
            )
            ctx.add_success(net_delta, syms, warns)
            if stored_ok:
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
            ctx.add_warnings(
                [
                    {
                        "type": "derived_indicators",
                        "message": f"파생 지표 계산 실패: {exc}",
                    }
                ]
            )


class _RunContext:
    """수집 실행 중 결과를 집계하는 컨텍스트.

    경고는 실행 시작~종료까지 상주하므로 절단하지 않으면 날짜 범위에 비례해
    무제한 증가한다(다년 backfill에서 약 1.67M건 ≈ 500 MB). 내부 리스트를
    ``_warnings`` 로 사유화하고 ``add_warnings()`` **단일 chokepoint**에서만
    적재해 **버킷(``type``)별 ``MAX_WARNINGS_PER_TYPE`` 건**까지만 보존한다.
    총계·타입별 집계는 절단과 무관하게 전수 정확하다.
    """

    def __init__(self) -> None:
        self.failures: list[dict] = []
        self._warnings: list[dict] = []
        self._warnings_by_type: dict[str, int] = {}
        self._warnings_truncated: bool = False
        self.config_errors: list[dict] = []
        self.total_symbols: set[str] = set()
        self.success_symbols: set[str] = set()
        self.rows_written: int = 0
        self.data_types: set[str] = set()

    @property
    def warnings(self) -> Sequence[dict]:
        """보존된 경고 샘플 (버킷별 최대 ``MAX_WARNINGS_PER_TYPE`` 건).

        반환 타입이 ``list[dict]`` 이 아니라 ``Sequence[dict]`` 인 것은
        의도적이다 — ``list`` 로 노출하면 소비자가 반환된 리스트를 직접
        변형(append/extend)해 chokepoint를 우회할 수 있고 mypy도 그것을
        통과시킨다(막히는 것은 속성 재바인딩뿐). ``Sequence`` 로 두면 mypy가
        ``attr-defined`` 로 append/extend/insert/슬라이스 대입을 전부
        차단한다.
        """
        return self._warnings

    @property
    def warnings_total(self) -> int:
        """**전수 정확** 경고 총 건수 (절단 무관)."""
        return sum(self._warnings_by_type.values())

    @property
    def warnings_truncated(self) -> bool:
        """버킷 상한으로 경고 샘플이 한 건이라도 절단되었는지 여부."""
        return self._warnings_truncated

    def add_warnings(self, warns: list[dict]) -> None:
        """경고를 유계로 적재하는 **단일 chokepoint**.

        **입력 리스트를 변형하지 않는다**(non-mutating, 결정 6).
        ``_drain_store_warnings`` 호출자가 같은 리스트로 checkpoint 전진을
        판단하므로 in-place clear/pop은 그 계약을 깬다.
        """
        for warn in warns:
            bucket = warn.get("type") or UNTYPED_WARNING_BUCKET
            seen = self._warnings_by_type.get(bucket, 0)
            self._warnings_by_type[bucket] = seen + 1
            if seen < MAX_WARNINGS_PER_TYPE:
                self._warnings.append(warn)
            else:
                self._warnings_truncated = True

    def add_success(
        self,
        net_delta: int,
        syms: set[str],
        warns: list[dict],
    ) -> None:
        """성공 결과를 집계한다.

        ``net_delta`` 는 collector가 보고한 **실제 net-new 저장 행 수**
        (rows_written)다. 입력 len 누적이 아니라 store가 실제 새로 저장한
        delta를 누적하므로 재수집/dedup이 rows_written을 과대계상하지 않는다.
        """
        self.rows_written += net_delta
        self.total_symbols.update(syms)
        self.success_symbols.update(syms)
        if warns:
            self.add_warnings(warns)

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
            warnings=list(self._warnings),
            warnings_total=self.warnings_total,
            warnings_by_type=dict(sorted(self._warnings_by_type.items())),
            warnings_truncated=self.warnings_truncated,
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
    warnings_total: int | None = None,
    warnings_by_type: dict[str, int] | None = None,
    warnings_truncated: bool = False,
    config_errors: list[dict] | None = None,
) -> CollectionResult:
    """CollectionResult를 생성한다."""
    finished_at = datetime.now(tz=UTC)
    duration = (finished_at - started_at).total_seconds()
    warning_items = warnings or []

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
        warnings=warning_items,
        warnings_total=(
            len(warning_items) if warnings_total is None else warnings_total
        ),
        warnings_by_type=warnings_by_type or {},
        warnings_truncated=warnings_truncated,
        config_errors=config_errors or [],
    )
