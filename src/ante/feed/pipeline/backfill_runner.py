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

# 경고 `type` 버킷별 인메모리 보존 상한 (#2414).
#
# 리포트 `warnings` 배열은 버킷당 이 건수까지만 보존하고 초과분은 **적재
# 시점에** 절단한다(리포트 생성 시점에 자르면 인메모리 누적이 그대로 남아
# OOM이 해소되지 않는다). 총계·타입별 집계는 절단과 무관하게 전수 정확하며,
# 절단분 상세는 로그에서 회수한다(경고는 발생 시점에 전건 로깅) —
# "규모는 리포트, 상세는 로그".
#
# 산출 근거: #2414 실측이 약 8개월(165 거래일) backfill에서 99,691건
# → 거래일당 약 600건(99,691/165)이다. 1000이면 통상 단일 일자 물량을
# 무손실 수용한다(daily 리포트 동작 불변 — 단, 전 종목 이상치 일자처럼
# 통상 물량을 크게 넘는 날은 daily도 절단되며 warnings_truncated로 표면화).
# 상한 = 버킷 8종 × 1000 × 약 302 B ≈ 2.4 MB로 **날짜 범위와 무관**하다
# (11.6년 약 1.67M건 → 최대 8,000건 보존, 상주 약 500 MB → 약 2.4 MB).
# config 노출은 YAGNI — 모듈 상수로 고정한다.
MAX_WARNINGS_PER_TYPE = 1000

# `type` 키가 없는 경고(DART 수집 경고 2종)를 담는 정적 fallback 버킷.
# `w.get("type")`(=None)을 그대로 버킷 키로 쓰면 json 직렬화에서
# `{"null": N}` 이 리포트로 새므로 반드시 이 값으로 정규화한다.
# 경고 `type`이 유계 정적 집합이라는 규범은
# docs/specs/data-feed/10-checkpoints-and-reports.md가 SSOT다.
UNTYPED_WARNING_BUCKET = "untyped"

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


# data.go.kr OHLCV는 영업일 D의 데이터가 다음 영업일 13:00 KST 이후에
# 공개된다(스펙 docs/specs/data-feed/05-data-sources.md: "영업일 D+1,
# 오후 1시 이후"). backfill 상한을 이 deadline이 지난 마지막 영업일로
# capping해 미공개 날짜를 애초에 시도하지 않는다(quota 보호).
_DATA_GO_KR_PUBLISH_HOUR_KST = 13


def _next_business_day(d: date) -> date:
    """``d`` 다음의 첫 영업일(주말 skip)을 반환한다.

    ``is_business_day``(scheduler.py)는 weekday만 본다(KR 공휴일 미인식).
    cap은 보조(quota 보호)일 뿐이며 데이터 무결성은 ``written > 0`` guard가
    보장하므로, 공휴일 미인식으로 cap이 다소 낙관적이어도 데이터 손실은
    없다(빈 응답 → checkpoint 미전진 → 재시도).
    """
    nxt = d + timedelta(days=1)
    while not is_business_day(nxt.isoformat()):
        nxt += timedelta(days=1)
    return nxt


def _last_published_date(now_kst: datetime) -> date:
    """``now_kst`` 시점에 확실히 공개된 마지막 OHLCV 날짜를 반환한다.

    어제부터 거꾸로 영업일 ``D`` 를 훑으며, ``D`` 의 데이터 공개 deadline
    (``next_business_day(D)`` 의 13:00 KST)이 ``now_kst`` 이하인 첫 ``D`` 를
    반환한다. 무한 루프 방지를 위해 최대 14일까지만 거슬러 올라간다(주말 +
    연속 비영업 구간을 충분히 덮는 보수적 bound). 그 안에 없으면 가장 오래
    거슬러 올라간 영업일을 반환한다(cap이 과도하게 좁아져도 무결성은 guard가
    보장).

    Args:
        now_kst: 기준 시각(KST aware datetime). 테스트는 이 인자를 주입해
            결정적으로 검증한다.

    Returns:
        확실히 공개된 마지막 영업일 ``date``.
    """
    today = now_kst.date()
    candidate = today - timedelta(days=1)
    # 14일 bound: 주말 + 비영업 구간을 덮는 안전 상한(무한 루프 방지).
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

        # 상한을 KST today 대신 "확실히 공개된 마지막 날짜"로 cap한다(#2015).
        # 미공개 최근일(D+1 13:00 KST 미도래)을 빈 응답으로 시도해 quota를
        # 낭비하는 것을 막는다. 데이터 무결성은 written>0 checkpoint guard가
        # 보장하므로 cap은 보조적이다.
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

        checkpoint 가드 = stored_ok 3-state (#1993, #2015 무회귀):
            checkpoint 전진은 더 이상 ``written > 0``(net-delta)가 아니라
            collector가 보고하는 ``stored_ok``(유효 데이터 store 성공 반영) 신호로
            구동한다. rows_written을 net-new delta로 바꾸면 재수집 날짜는
            net_delta=0이 되는데, ``written > 0`` 가드라면 그 날짜가 미전진해
            checkpoint stall이 생긴다. 3-state로 분리:
              - 빈 응답(stored_ok=False) → 미전진(#2015 보존)
              - 유효 재수집(stored_ok=True, net_delta=0) → 전진(stall 해소)
              - store-merge 실패 → 미전진. ``_persist_partition`` 은 merge 실패
                시 raise하지 않고(R1) 기존 파일 보존 + ``store_merge`` 경고만
                적재하므로, runner가 checkpoint save **직전** 이번 날짜 write 직후
                store 경고를 drain해 ``store_merge`` 존재를 확인하는 가드로 미전진
                시킨다. drain은 반드시 collect/write 직후·checkpoint save 직전에
                수행한다(지연 drain이면 실패 날짜가 이미 전진).
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
                net_delta, stored_ok, syms, warns = await self._data_go_kr.collect(
                    target_date,
                    store,
                )
                ctx.add_success(net_delta, syms, warns)
                if stored_ok:
                    ctx.data_types.update(["ohlcv", "fundamental"])

                # R1: store 경고를 checkpoint save 직전·이번 날짜 write 직후
                # drain한다. store-merge 실패(기존 파일 보존)는 raise하지 않고
                # 경고만 남기므로, 이번 날짜에 발생한 store_merge가 있으면
                # checkpoint를 전진시키지 않는다(데이터 미반영 날짜 영구 skip 방지).
                store_merge_failed = self._drain_store_warnings(store, ctx)

                # checkpoint는 유효 데이터가 store에 반영된 날짜(stored_ok)에만
                # 전진시킨다(#1993/#2015). 빈 응답/전 drop/validation 차단
                # (stored_ok=False: 미공개/지연공개/캘린더 미인식 공휴일)에
                # 전진하면 그 날짜가 다음 run에서 last_checkpoint 이전으로 간주되어
                # 영구 skip된다(데이터 손실). 유효 재수집(net_delta=0)은 stored_ok로
                # 정상 전진해 stall을 만들지 않는다.
                # dates는 오름차순이므로 checkpoint = 마지막 stored_ok 날짜이며,
                # 내부 빈 날짜는 다음 데이터 날짜에서 jump해 자연 커버(stall 없음),
                # trailing 빈 날짜는 미전진 → 다음 실행에서 재시도(손실 없음).
                #
                # halt(#2078) 이후 또는 store-merge 실패 시에는 stored_ok여도
                # 전진시키지 않는다(실패 날짜 너머 전진 → 영구 skip 방지).
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
                # 이후 날짜 성공이 checkpoint를 실패 날짜 너머로 전진시키지
                # 못하도록 halt한다(#2078). break는 도입하지 않고(best-effort
                # 수집 계속) checkpoint.save만 위 success 경로에서 가드한다.
                halt = True

    @staticmethod
    def _drain_store_warnings(store: ParquetStore, ctx: _RunContext) -> bool:
        """store의 pending 경고를 즉시 drain해 ctx.warnings로 옮기고,

        이번 drain에 ``store_merge`` (파티션 merge 실패 → 기존 파일 보존, 데이터
        미반영) 경고가 있었는지 반환한다(#1993 R1).

        checkpoint save 직전에 호출해야 한다 — collect/write 직후 drain해야 이번
        날짜에서 발생한 store-merge 실패를 정확히 귀속할 수 있다(지연 drain이면
        실패 날짜가 이미 checkpoint를 전진시킨 뒤가 된다).

        반환값은 ctx 측 경고 절단(#2414)과 **무관**하다 — ``drained`` 전수를
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
            net_delta, stored_ok, syms, warns = await self._dart.collect(
                data_path,
                feed_dir,
                checkpoint,
                config,
                store,
            )
            ctx.add_success(net_delta, syms, warns)
            # data_types는 유효 분기 저장 여부(stored_ok)로 표시한다 — 재수집
            # (net_delta=0)이어도 fundamental 데이터가 store에 있으므로 True(#1993).
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

    경고는 실행 시작~종료까지 상주하므로 날짜 범위에 비례해 무제한 증가했다
    (#2414 — 다년 backfill에서 약 1.67M건 ≈ 500 MB). 내부 리스트를
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
        차단한다(#2414 결정 5).

        **총 건수를 세는 용도로 쓰지 말 것** — 절단 시 ``len()`` 은 총계가
        아니다. ``warnings_total`` 을 쓴다.
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
        """경고를 유계로 적재하는 **단일 chokepoint** (#2414).

        동작:
            1. 버킷을 ``w.get("type") or UNTYPED_WARNING_BUCKET`` 으로
               정규화한다. DART 수집 경고 2종에는 ``type`` 키가 없어 대괄호
               직접 인덱싱은 KeyError이고, ``w.get("type")`` 결과를 그대로
               버킷 키로 쓰면 ``json.dumps({None: 3})`` = ``{"null": 3}`` 이
               리포트로 샌다.
            2. 카운터를 **절단 여부와 무관하게 먼저 전수 증가**시킨다
               (``warnings_total``/``warnings_by_type`` 은 항상 정확).
            3. 해당 버킷 보유량이 상한 미만일 때만 샘플에 보존하고, 한 건이라도
               스킵하면 절단 플래그를 세운다.

        **입력 리스트를 변형하지 않는다**(non-mutating, 결정 6).
        ``_drain_store_warnings`` 호출자가 같은 리스트로 checkpoint 전진을
        판단하므로 in-place clear/pop은 그 계약을 깬다.
        """
        for warn in warns:
            bucket = warn.get("type") or UNTYPED_WARNING_BUCKET
            # 절단 전 보유량 == min(누계, 상한)이므로 증가 전 누계로 판정한다.
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
        (rows_written, #1993)다. 입력 len 누적이 아니라 store가 실제 새로 저장한
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
            # Sequence[dict] → list[dict] 경계 변환(사유화한 내부 리스트를
            # 그대로 넘기지 않는다).
            warnings=list(self._warnings),
            warnings_total=self.warnings_total,
            # 버킷명 정렬 — dict 삽입 순서 = 경고 도착 순서라 실행마다 달라진다
            # (바로 위 data_types=sorted(...)와 동일 지점에서 한 번만 정렬).
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
    """CollectionResult를 생성한다.

    ``warnings_total`` 기본값이 ``0`` 이 아니라 ``None`` 인 것은 의도적이다
    (#2414). ``0`` 으로 두면 ``warnings`` 를 넘기고 총계를 생략한 호출이
    "경고 N건 + 총계 0"이라는 **자기모순 리포트**를 만든다. ``None`` 이면
    ``len(warnings)`` 로 파생해 절단이 없는 호출에서 항상 정합한다.
    """
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
