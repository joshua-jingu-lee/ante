"""BackfillRunner — 과거 데이터 대량 수집 (backfill 모드)."""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Callable
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

# 거래시간 가드(`blocked_hours`+`pause_during_trading`) 대기 관련 coded
# config_error 코드 (#1972). backfill 날짜별 루프가 거래시간 window 안에서
# 대기하다가, 누적 대기가 상한(MAX_GUARD_WAIT_SECONDS)을 넘으면
# ``GUARD_PERMANENTLY_BLOCKED`` 를, 상주 스케줄러 stop_event로 대기가
# 중단되면 ``BACKFILL_STOP_REQUESTED`` 를 result.config_errors에 적재한다.
# 둘 다 mid-range partial 종료를 관측 가능하게 만드는 마커이며
# (clean-success 차단), BACKFILL_DATE_ERROR_CODES에 포함되어 CLI exit-1 /
# daemon 차단 echo 경로를 그대로 탄다.
CONFIG_ERROR_CODE_GUARD_PERMANENTLY_BLOCKED = "GUARD_PERMANENTLY_BLOCKED"
CONFIG_ERROR_CODE_BACKFILL_STOP_REQUESTED = "BACKFILL_STOP_REQUESTED"

# 신설 coded config_errors의 코드 집합. CLI/scheduler에서 이 집합으로만
# 새 envelope/차단 분기를 trigger한다 (기존 비날짜 entries 보존).
BACKFILL_DATE_ERROR_CODES = frozenset(
    {
        CONFIG_ERROR_CODE_INVALID_DATE,
        CONFIG_ERROR_CODE_INVALID_DATE_RANGE,
        CONFIG_ERROR_CODE_GUARD_PERMANENTLY_BLOCKED,
        CONFIG_ERROR_CODE_BACKFILL_STOP_REQUESTED,
    }
)

# 거래시간 가드 대기 폴링 주기/상한 (초). 모듈 상수 — `[guard]` 스키마
# 확장 없이 고정값으로 둔다(#1972 Non-Goal). 테스트는 이 상수들을
# patch/주입해 시간 비의존(결정적)으로 검증한다.
GUARD_WAIT_POLL_SECONDS = 60.0
# 상한은 하루를 충분히 넘긴다(거래시간 window가 자정 안에 끝나면 그날
# 안에 반드시 해제되므로, 정상 운영에서는 도달하지 않는다). 도달은
# 설정 오류(예: 24시간 전체 차단)를 의미한다.
MAX_GUARD_WAIT_SECONDS = 26 * 60 * 60.0

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
        is_blocked_day: Callable[[dict[str, Any], str], bool],
        is_trading_paused: Callable[[dict[str, Any]], bool],
        stop_event: asyncio.Event | None = None,
    ) -> CollectionResult:
        """Backfill 내부 구현. data.go.kr + DART 수집 후 지표 계산.

        backfill_since strict 검증은 수렴점이므로 수집 메서드 진입 전
        가장 먼저 수행한다. malformed/future일 때는 체크포인트·소스
        접근 없이 coded config_error만 담은 result를 즉시 반환한다.

        가드는 두 술어로 분리되어 주입된다 (#1972):
            ``is_blocked_day(config, target_date)`` — ``blocked_days``
            (target_date 요일). 해당 날짜는 데이터가 없어 **skip**.
            ``is_trading_paused(config)`` — ``blocked_hours`` +
            ``pause_during_trading`` (현재 시각). 해당 시 window가 풀릴
            때까지 **대기 후** 그 날짜를 수집한다.

        ``stop_event`` 가 주어지면(상주 스케줄러) 거래시간 대기 중
        SIGTERM/SIGINT로 깨어나 체크포인트를 저장한 partial을 반환하며
        ``BACKFILL_STOP_REQUESTED`` 마커를 적재한다.
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
            is_blocked_day,
            is_trading_paused,
            stop_event,
        )
        ctx.warnings.extend(store.drain_warnings())
        await self._collect_dart(
            data_path,
            feed_dir,
            dart_checkpoint,
            config,
            store,
            ctx,
        )
        ctx.warnings.extend(store.drain_warnings())
        self._compute_indicators(store, ctx)
        ctx.warnings.extend(store.drain_warnings())

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
        is_blocked_day: Callable[[dict[str, Any], str], bool],
        is_trading_paused: Callable[[dict[str, Any]], bool],
        stop_event: asyncio.Event | None,
    ) -> None:
        """data.go.kr 날짜별 수집을 실행한다.

        가드 분리 (#1972):
            - ``is_blocked_day`` 가 True인 비거래 요일은 **skip**한다
              (그 과거 날짜는 데이터가 없어 대기해도 영원히 안 채워짐).
            - 그 외 날짜는 ``is_trading_paused`` 가 풀릴 때까지 **대기한 뒤**
              수집한다(window가 지나면 데이터는 존재).

        checkpoint 미전진 (#2078, #2054 동형 halt):
            ``dates`` 는 오름차순이고 ``Checkpoint.save`` 는 last-write-wins이므로,
            transient 실패(generic ``except Exception``) 이후의 날짜 성공이
            checkpoint를 실패 날짜 너머로 전진시키면 그 실패 날짜는 다음 run에서
            ``last_checkpoint`` 이전으로 간주되어 영구 skip된다. 첫 transient
            실패 시 ``halt = True`` 를 세워 이후 ``checkpoint.save`` 를 모두
            건너뛴다(실패 직전 날짜에 checkpoint 고정). 수집 자체는 best-effort로
            계속하므로 ``continue``(루프 진행)는 유지한다 — DataGoKr 결과는
            ParquetStore natural-key dedup으로 재-fetch overwrite 멱등.
        """
        if self._data_go_kr is None:
            return

        # 첫 transient 실패 이후 checkpoint 전진을 멈추는 플래그(#2078).
        halt = False

        for target_date in dates:
            if is_blocked_day(config, target_date):
                logger.debug("방어 가드(blocked_days): %s 스킵", target_date)
                continue

            # 거래시간 가드가 활성이면 풀릴 때까지 대기한다. 대기가 stop_event
            # 또는 max-wait 상한으로 중단되면 체크포인트만 저장된 partial로
            # 루프를 빠져나간다(관측 가능한 coded marker 적재).
            should_stop = await self._wait_out_trading_pause(
                config,
                is_trading_paused,
                stop_event,
                ctx,
            )
            if should_stop:
                break

            try:
                written, syms, warns = await self._data_go_kr.collect(
                    target_date,
                    store,
                )
                ctx.add_success(written, syms, warns)
                if written > 0:
                    ctx.data_types.update(["ohlcv", "fundamental"])
                # halt 이후에는 checkpoint를 전진시키지 않는다(#2078). 앞선
                # 실패 날짜 너머로 last_date가 진행되면 그 날짜가 영구 skip된다.
                if not halt:
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
                # 이후 날짜 성공이 checkpoint를 실패 날짜 너머로 전진시키지
                # 못하도록 halt한다(#2078). break는 도입하지 않고(best-effort
                # 수집 계속) checkpoint.save만 위 success 경로에서 가드한다.
                halt = True

    async def _wait_out_trading_pause(
        self,
        config: dict[str, Any],
        is_trading_paused: Callable[[dict[str, Any]], bool],
        stop_event: asyncio.Event | None,
        ctx: _RunContext,
    ) -> bool:
        """거래시간 가드(``blocked_hours``)가 풀릴 때까지 대기한다.

        ``is_trading_paused(config)`` 가 True인 동안 ``GUARD_WAIT_POLL_SECONDS``
        주기로 폴링한다.

        - 상주 스케줄러(``stop_event`` 주어짐): ``asyncio.wait_for`` 로 poll
          만큼 대기하되 stop_event가 set되면 즉시 깨어난다(SIGTERM 안전종료).
        - one-shot(``stop_event=None``): ``asyncio.sleep`` 로 대기하며,
          ``asyncio.run`` 의 SIGINT가 task를 취소해 중단할 수 있다.

        Returns:
            ``True``  — stop_event 또는 max-wait 상한으로 대기가 중단됨.
                루프는 즉시 break하고 체크포인트만 저장된 partial을 반환한다.
                (각각 ``BACKFILL_STOP_REQUESTED`` /
                ``GUARD_PERMANENTLY_BLOCKED`` coded marker가 적재됨.)
            ``False`` — 가드가 풀려 정상적으로 해당 날짜를 수집할 수 있음.
        """
        waited = 0.0
        first_log = True

        while is_trading_paused(config):
            # 대기 진입 직전에 stop이 이미 요청되었으면 즉시 중단한다.
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
                # stop set 시 즉시 깨어난다. 그 외에는 poll만큼 대기 후 재확인.
                try:
                    await asyncio.wait_for(
                        stop_event.wait(),
                        timeout=GUARD_WAIT_POLL_SECONDS,
                    )
                except TimeoutError:
                    # poll 경과(stop 미수신) — window/상한을 루프 top에서 재확인.
                    waited += GUARD_WAIT_POLL_SECONDS
                    continue
                # TimeoutError 아님 ⇒ wait 도중 stop_event가 set됨 ⇒ 즉시 중단.
                # 같은 사이클에 거래시간 window가 동시에 풀려 while 재평가가
                # False가 되더라도 그 race를 통과시키지 않고 stop을 우선한다.
                logger.info("Backfill 중단 요청 수신, 거래시간 대기 종료")
                ctx.config_errors.append(
                    {
                        "code": CONFIG_ERROR_CODE_BACKFILL_STOP_REQUESTED,
                        "error": "중단 요청으로 backfill 거래시간 대기를 종료했습니다",
                        "source": "data_go_kr",
                    }
                )
                return True

            # one-shot: asyncio.run SIGINT가 이 sleep을 취소해 중단 가능.
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
