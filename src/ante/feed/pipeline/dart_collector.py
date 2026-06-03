"""DARTCollector — DART 재무제표 분기별 수집."""

from __future__ import annotations

import json
import logging
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any

import polars as pl

from ante.data.normalizer import _REPRT_CODE_MAP, DARTNormalizer
from ante.data.store import ParquetStore
from ante.feed.pipeline.checkpoint import Checkpoint
from ante.feed.sources.dart import (
    CriticalApiError as DARTCriticalError,
)
from ante.feed.sources.dart import (
    DailyLimitExceededError as DARTDailyLimitError,
)

logger = logging.getLogger(__name__)

# DART 보고서 코드 (시간순: 1Q → 반기 → 3Q → 연간)
REPRT_CODES = ["11013", "11012", "11014", "11011"]

# REPRT_CODE → 분기 매핑
REPRT_TO_QUARTER: dict[str, str] = {
    "11013": "Q1",  # 1분기
    "11012": "Q2",  # 반기
    "11014": "Q3",  # 3분기
    "11011": "Q4",  # 사업보고서(연간)
}

# 기본 설정 상수
DEFAULT_BACKFILL_SINCE = "2015-01-01"


class QuarterStatus(Enum):
    """단일 분기 수집 결과의 3-상태(#2028).

    ``_fetch_quarter``가 반환하며, ``_collect_quarters``의 checkpoint 전진/
    halt 결정을 구동한다. 기존 2-값 bool(ok)을 대체한다.

    - ``OK``: 정상 저장(written>0). checkpoint 전진 자격.
    - ``HALT``: transient 예외 / raw-present no-storable(written==0). 데이터
      손실 가능성을 surface하고 이 run의 checkpoint 전진을 동결한다(#2054).
    - ``SKIP_EMPTY``: ``not raw_items``(분기종료 직후·공시 전 빈 응답 등 미공시
      가능). checkpoint를 전진시키지 않으면서 halt도 세우지 않아, 오름차순
      순회에서 후속 분기 처리를 계속한다(#2028).
    """

    OK = "ok"
    HALT = "halt"
    SKIP_EMPTY = "skip_empty"


# `today`는 KST(UTC+9) 캘린더 기준으로 산출한다. 분기 period-end 비교는
# backfill_runner._today_kst()와 동일 기준이어야 한다(repo 전반 KST 정합).
_KST = timezone(timedelta(hours=9))


def _today_kst() -> date:
    """오늘 날짜(KST 캘린더)를 반환한다."""
    return datetime.now(tz=_KST).date()


def _quarter_period_end(year: int, reprt_code: str) -> date | None:
    """(year, reprt_code)가 가리키는 분기의 period-END 날짜를 반환한다.

    reprt_code → 종료월(3/6/9/12) 매핑은 normalizer `_REPRT_CODE_MAP`를
    SSOT로 재사용하며, 그 월의 말일을 period-end로 본다(DART normalizer의
    `_convert_report_date`와 동일 규칙).

    Returns:
        period-end 날짜. reprt_code가 매핑에 없으면 None.
    """
    mapping = _REPRT_CODE_MAP.get(reprt_code)
    if mapping is None:
        return None
    _, month = mapping
    day = monthrange(year, month)[1]
    return date(year, month, day)


class DARTCollector:
    """DART에서 재무제표를 분기별로 수집한다.

    책임: corp_code 매핑 로드 -> 연도/분기 순회 -> 정규화 -> 저장.
    """

    def __init__(
        self,
        source: Any,
        normalizer: DARTNormalizer | None = None,
    ) -> None:
        self._source = source
        self._normalizer = normalizer or DARTNormalizer()

    async def collect(
        self,
        data_path: Path,
        feed_dir: Path,
        checkpoint: Checkpoint,
        config: dict[str, Any],
        store: ParquetStore,
        daily: bool = False,
    ) -> tuple[int, bool, set[str], list[dict]]:
        """DART 재무제표를 분기별로 수집한다.

        Args:
            daily: ``True``면 daily-incremental 모드로, ``backfill_since`` 범위를
                순회하지 않고 **최신 collectable 분기 1개만** 수집한다(#2101).
                spec 07-execution-modes의 Daily Incremental("날짜 1개")에 대응하는
                DART daily-equivalent다. DART는 분기 단위 공시이므로 daily 실행은
                "오늘 기준 가장 최근에 공시 가능한 분기"만 확인한다. ``False``(기본,
                backfill 모드)면 ``_resolve_year_range``의 전 분기를 순회한다.

                운영 전제: daily 모드는 과거 미충전 분기를 보정하지 않는다(최신
                분기 1개만 본다). checkpoint가 비거나 오래되어 과거 분기가 비어
                있으면 ``feed run backfill``(daily=False, 전 분기 순회)로 채워야
                한다. 과거 이력 backfill 책임은 backfill 모드에 있고, daily는
                최신 분기 증분만 담당한다.

        Returns:
            ``(net_delta, stored_ok, 수집된 심볼 집합, 경고 목록)`` (#1993):

            - ``net_delta``: store에 **실제 새로 저장된 net-new 행 수**(rows_written).
              재수집(dedup)이면 0이다.
            - ``stored_ok``: **유효 분기 데이터가 store에 성공 반영되었는지**
              (한 분기라도 ``QuarterStatus.OK``, 즉 storable_rows>0). net_delta와
              무관하다 — 재수집으로 net_delta=0이어도 OK 분기가 있으면 True다.
              빈 매핑/전 분기 SKIP_EMPTY/no-storable HALT 등 저장 반영이 전무하면
              False다. DART checkpoint 전진은 내부 ``QuarterStatus`` 로직이 분기별로
              자체 관리하므로(#2028/#2054), 이 stored_ok는 runner의
              ``data_types`` 반영용이다(checkpoint 가드 아님).
        """
        corp_code_map = await self._load_corp_codes(feed_dir)
        if not corp_code_map:
            logger.warning("DART: 고유번호 매핑이 비어있음")
            warns: list[dict] = [
                {
                    "source": "dart",
                    "type": "empty_corp_code_map",
                    "message": (
                        "DART 고유번호 매핑이 비어 있어 fundamental 수집을 건너뜀"
                    ),
                }
            ]
            return 0, False, set(), warns

        last_checkpoint = checkpoint.get_last_date()
        last_checkpoint = self._migrate_checkpoint_key(last_checkpoint)

        if daily:
            return await self._collect_latest_quarter(
                corp_code_map,
                store,
                checkpoint,
                last_checkpoint,
            )

        start_year, end_year = self._resolve_year_range(config)
        return await self._collect_quarters(
            corp_code_map,
            store,
            checkpoint,
            start_year,
            end_year,
            last_checkpoint,
        )

    async def _load_corp_codes(
        self,
        feed_dir: Path,
    ) -> dict[str, str]:
        """고유번호 매핑을 캐시에서 로드하거나 다운로드한다."""
        corp_codes_path = feed_dir / "dart_corp_codes.json"
        if corp_codes_path.exists():
            try:
                data = json.loads(corp_codes_path.read_text())
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("DART: 고유번호 캐시 파싱 실패(%s), 재다운로드", e)
            else:
                if isinstance(data, dict) and data:
                    return {str(k): str(v) for k, v in data.items()}
                logger.warning("DART: 고유번호 캐시가 비정상(빈/비-dict), 재다운로드")
        return await self._source.fetch_corp_codes(save_path=corp_codes_path)

    @staticmethod
    def _resolve_year_range(
        config: dict[str, Any],
    ) -> tuple[int, int]:
        """설정에서 수집 연도 범위를 결정한다.

        end_year는 KST 기준 현재 연도이며, 분기 단위 미래 컷오프는
        `_collect_quarters`의 period-end(KST) 비교가 담당한다(#1964).
        """
        schedule = config.get("schedule", {})
        backfill_since = schedule.get("backfill_since", DEFAULT_BACKFILL_SINCE)
        start_year = int(backfill_since[:4])
        end_year = _today_kst().year
        return start_year, end_year

    @staticmethod
    def _migrate_checkpoint_key(last: str | None) -> str | None:
        """기존 'YYYY-REPRT_CODE' -> 'YYYY-QN' 형식 변환."""
        if last and "-" in last:
            parts = last.split("-", 1)
            if len(parts) == 2 and parts[1] in REPRT_TO_QUARTER:
                return f"{parts[0]}-{REPRT_TO_QUARTER[parts[1]]}"
        return last

    async def _collect_quarters(
        self,
        corp_code_map: dict[str, str],
        store: ParquetStore,
        checkpoint: Checkpoint,
        start_year: int,
        end_year: int,
        last_checkpoint: str | None,
    ) -> tuple[int, bool, set[str], list[dict]]:
        """연도/분기를 순회하며 재무제표를 수집한다.

        Returns:
            ``(net_delta, stored_ok, symbols, warns)`` (#1993). net_delta는
            ``_fetch_quarter`` 가 반환한 rows_written(net-new 저장 행 수)의 합이며,
            stored_ok는 한 분기라도 ``QuarterStatus.OK`` (storable 저장)였는지다.
        """
        corp_codes_list = list(corp_code_map.keys())
        rows_written = 0
        symbols: set[str] = set()
        warns: list[dict] = []
        stored_ok = False

        # collectable 상한: period-end가 today(KST)를 지난 분기만 fetch/save.
        # 미래 분기(예: 실행일 2026-05-29 기준 2026-Q2/Q3/Q4)는 데이터가
        # 존재할 수 없으므로 fetch도 checkpoint.save도 수행하지 않는다.
        # 이로써 checkpoint가 미래 분기로 전진하지 않는다(#1964).
        today = _today_kst()

        # 첫 HALT(transient 예외 / raw-present no-storable) 이후에는 이 run에서
        # checkpoint를 더 전진시키지 않는다(#2054). checkpoint는 quarter_key
        # 오름차순 last-write-wins로 monotonic 전진하므로, HALT 분기 이후의 성공
        # 분기를 save하면 checkpoint가 HALT 분기를 넘어 전진해 다음 run에서
        # 재시도되지 않는다. halt 플래그로 HALT 분기 직전에 checkpoint를 고정해
        # 다음 run이 HALT 분기부터 재개한다. HALT 이후 분기 fetch는 best-effort로
        # 계속하며(데이터는 best-effort 저장), 재-fetch는 ParquetStore의
        # natural-key dedup(keep="last")로 overwrite 멱등이라 중복 누적이
        # 발생하지 않는다.
        #
        # SKIP_EMPTY(not raw_items, 미공시 가능)는 halt를 세우지 않고 checkpoint도
        # 전진시키지 않는다(#2028). 오름차순 순회라 내부 빈 분기는 후속 데이터
        # 분기의 checkpoint.save가 jump하여 커버하고, trailing 빈 분기는 미전진
        # 상태로 남아 다음 run에서 재시도된다(분기종료 직후 빈 응답을 "완료"로
        # 오인해 이후 공시를 누락하던 버그 해소).
        #
        # store-merge 실패(#1993 R2)는 분기별로 독립 판정한다. halt와 달리 이후
        # 분기로 전파되지 않으며(halt를 세우지 않음), 해당 분기만 checkpoint를
        # 미전진시켜 다음 run에 재시도되게 한다. data.go.kr는 runner R1이 store
        # 경고 drain으로 가드하지만 DART는 checkpoint.save가 collector 내부라
        # _fetch_quarter의 비파괴적 peek 결과(store_merge_failed)로 게이트한다.
        halt = False

        for year in range(start_year, end_year + 1):
            for reprt_code in REPRT_CODES:
                quarter_key = f"{year}-{REPRT_TO_QUARTER[reprt_code]}"
                if last_checkpoint and quarter_key <= last_checkpoint:
                    continue

                period_end = _quarter_period_end(year, reprt_code)
                if period_end is not None and period_end > today:
                    # 미래 분기: fetch/save 모두 건너뛴다.
                    continue

                written, syms, status, store_merge_failed = await self._fetch_quarter(
                    corp_codes_list,
                    corp_code_map,
                    store,
                    year,
                    reprt_code,
                    warns,
                )
                rows_written += written
                symbols.update(syms)
                if status is QuarterStatus.HALT:
                    halt = True
                elif status is QuarterStatus.OK:
                    # storable 저장이 일어난 분기 — stored_ok 신호 set(net_delta
                    # 무관). checkpoint 전진은 halt 미설정 + store-merge 성공일
                    # 때만(#2054 보존, #1993 R2). store-merge 실패(net_delta=0 +
                    # store_merge 경고)면 QuarterStatus는 OK여도 checkpoint를
                    # 전진시키지 않아 다음 run에 재시도된다(데이터 미반영 분기
                    # 영구 skip 방지). store_merge 경고는 runner가 collect 종료 후
                    # drain해 보고한다(DART는 비파괴적 peek만 함).
                    stored_ok = True
                    if not halt and not store_merge_failed:
                        checkpoint.save(quarter_key)
                # QuarterStatus.SKIP_EMPTY: checkpoint 미전진 + halt 미설정(no-op).

        logger.info(
            "DART 수집 완료: symbols=%d rows=%d stored_ok=%s",
            len(symbols),
            rows_written,
            stored_ok,
        )
        return rows_written, stored_ok, symbols, warns

    @staticmethod
    def _latest_collectable_quarter(
        today: date,
    ) -> tuple[int, str] | None:
        """today(KST) 기준 가장 최근에 공시 가능한 (year, reprt_code)를 반환한다.

        collectable = ``_quarter_period_end(year, reprt_code) <= today``인 분기.
        그중 period_end가 가장 최근(=가장 큰)인 분기 1개를 고른다. period_end가
        같으면 발생하지 않지만(reprt_code→종료월 1:1), 안전하게 결정적으로
        고른다.

        연말/연초 경계: annual(Q4, 12/31)은 익년 초까지 미공시일 수 있으므로
        period_end<=today 기준으로 정확히 판정된다. 예를 들어 2026-01-15에는
        2025-Q4(period_end 2025-12-31)가 collectable이며 2025 annual을 고른다.
        반대로 2026-04-01에는 2026-Q1(3/31)이 가장 최근 collectable이다.

        탐색 범위는 today 연도와 직전 연도(today.year-1)면 충분하다. 직전 연도
        Q4(period_end 전년 12/31)는 today가 연초여도 항상 <=today이므로 후보가
        비는 경우는 없다(따라서 실질적으로 None을 반환하지 않지만, 매핑 부재
        등 방어를 위해 Optional 시그니처를 유지한다).

        Returns:
            (year, reprt_code) 또는 collectable 분기가 없으면 None.
        """
        best: tuple[int, str] | None = None
        best_end: date | None = None
        for year in (today.year - 1, today.year):
            for reprt_code in REPRT_CODES:
                period_end = _quarter_period_end(year, reprt_code)
                if period_end is None or period_end > today:
                    continue
                if best_end is None or period_end > best_end:
                    best_end = period_end
                    best = (year, reprt_code)
        return best

    async def _collect_latest_quarter(
        self,
        corp_code_map: dict[str, str],
        store: ParquetStore,
        checkpoint: Checkpoint,
        last_checkpoint: str | None,
    ) -> tuple[int, bool, set[str], list[dict]]:
        """daily 모드: 최신 collectable 분기 1개만 수집한다(#2101).

        ``backfill_since`` 범위를 순회하지 않고, today(KST) 기준 가장 최근에
        공시 가능한 분기 1개에 대해서만 ``_fetch_quarter``를 수행한다. 단일
        분기지만 checkpoint 전진/halt/SKIP_EMPTY 판정은 backfill 경로와 동일한
        ``_fetch_quarter``/``QuarterStatus`` 로직을 그대로 재사용한다(#2028/#2054).

        운영 전제: 이 경로는 최신 분기만 본다. 과거 미충전 분기는 backfill
        모드로 채워야 하며, daily가 과거 누락을 보정하지 않는다.

        Returns:
            ``(net_delta, stored_ok, symbols, warns)`` (#1993). stored_ok는
            최신 분기가 ``QuarterStatus.OK`` (storable 저장)인지다.
        """
        corp_codes_list = list(corp_code_map.keys())
        warns: list[dict] = []

        today = _today_kst()
        latest = self._latest_collectable_quarter(today)
        if latest is None:
            # collectable 분기 부재(매핑 이상 등): no-op.
            logger.info("DART daily: collectable 분기 없음")
            return 0, False, set(), warns

        year, reprt_code = latest
        quarter_key = f"{year}-{REPRT_TO_QUARTER[reprt_code]}"

        # 최신 분기가 이미 checkpoint done(<=last)이면 재수집하지 않는다(0 fetch).
        if last_checkpoint and quarter_key <= last_checkpoint:
            logger.info(
                "DART daily: 최신 분기 %s 이미 수집됨(checkpoint=%s), skip",
                quarter_key,
                last_checkpoint,
            )
            return 0, False, set(), warns

        written, syms, status, store_merge_failed = await self._fetch_quarter(
            corp_codes_list,
            corp_code_map,
            store,
            year,
            reprt_code,
            warns,
        )
        # SKIP_EMPTY(미공시 가능)/HALT(transient·no-storable)는 backfill과 동일하게
        # checkpoint를 전진시키지 않는다. OK일 때만 save하되, store-merge 실패
        # (net_delta=0 + store_merge 경고)면 QuarterStatus가 OK여도 checkpoint를
        # 전진시키지 않는다(#1993 R2, 다음 run 재시도). store_merge 경고는 runner가
        # collect 종료 후 drain해 보고한다(DART는 비파괴적 peek만 함).
        stored_ok = status is QuarterStatus.OK
        if stored_ok and not store_merge_failed:
            checkpoint.save(quarter_key)

        logger.info(
            "DART daily 수집 완료: quarter=%s symbols=%d rows=%d status=%s",
            quarter_key,
            len(syms),
            written,
            status.value,
        )
        return written, stored_ok, syms, warns

    async def _fetch_quarter(
        self,
        corp_codes_list: list[str],
        corp_code_map: dict[str, str],
        store: ParquetStore,
        year: int,
        reprt_code: str,
        warns: list[dict],
    ) -> tuple[int, set[str], QuarterStatus, bool]:
        """단일 분기 재무제표를 수집/정규화/저장한다.

        Returns:
            (기록 행 수, 수집된 심볼 집합, status, store_merge_failed).

            ``status``는 이 분기에 대한 checkpoint 전진/halt 결정을 구동하는
            3-상태다(#2028, #2054). **storable_rows 기준으로만 판정**하며
            store-merge 실패를 절대 섞지 않는다(#2028 의미 보존):

            - transient 예외(warn 추가) → ``QuarterStatus.HALT``
              (미전진 + 이후 분기 동결, 다음 run 재시도)
            - ``not raw_items``(분기종료 직후·공시 전 빈 응답 등 미공시 가능) →
              ``QuarterStatus.SKIP_EMPTY``(미전진하되 halt 미설정; 후속 분기
              처리는 계속). 과거에는 ``ok=True``로 checkpoint를 전진시켜 빈
              분기를 "완료"로 오인하고 이후 공시를 누락했다(#2028 버그).
            - ``raw_items``는 있는데 정규화/저장 결과 0 rows(no-storable) →
              warn 추가 + ``QuarterStatus.HALT``(데이터 손실 surface, 미전진)
            - 정상 저장(written>0) → ``QuarterStatus.OK``(checkpoint 전진 자격)

            ``store_merge_failed``는 이번 분기 ``store.write`` 가 파티션 merge
            실패(기존 파일 보존 + ``store_merge`` 경고 적재, net_delta=0)를
            일으켰는지다(#1993). data.go.kr는 runner R1이 store 경고 drain으로
            checkpoint를 가드하지만 DART는 checkpoint.save를 collector 내부에서
            하므로(``_collect_quarters``/``_collect_latest_quarter``) 호출자가 이
            bool로 checkpoint 전진을 게이트한다. QuarterStatus는 storable 기준
            그대로(OK)이되 store_merge_failed면 checkpoint만 미전진시켜 다음 run에
            재시도되게 한다.

            store_merge 감지는 ``store.pending_merge_failure_count()`` 의
            **비파괴적 peek**로 한다. runner가 DART collect 전체 종료 후 단일
            소유로 drain하므로(backfill_runner) DART가 drain하면 경고가 소실된다.
            누적 카운트라 ``_normalize_and_store`` **직전/직후 증가분**으로 이번
            분기 실패를 판정한다(이전 분기 경고가 아직 drain 안 됐을 수 있음).

            ``DARTDailyLimitError``/``DARTCriticalError``는 기존대로 re-raise.
        """
        try:
            raw_items = await self._source.fetch_financial(
                corp_codes_list,
                str(year),
                reprt_code,
            )
        except (DARTDailyLimitError, DARTCriticalError):
            raise
        except Exception as exc:
            logger.warning(
                "DART 수집 실패: year=%s reprt=%s: %s",
                year,
                reprt_code,
                exc,
            )
            warns.append(
                {
                    "source": "dart",
                    "year": str(year),
                    "reprt_code": reprt_code,
                    "message": str(exc),
                }
            )
            return 0, set(), QuarterStatus.HALT, False

        if not raw_items:
            # 빈 응답: 분기종료 직후 아직 공시되지 않았을 수 있다(미공시 가능).
            # checkpoint를 전진시키면 이후 공시를 영구 누락하므로(분기 완료
            # 오인, #2028) 미전진한다. 단 halt는 세우지 않아 후속 분기 처리는
            # 계속한다(오름차순 순회에서 내부 빈 분기는 후속 데이터 분기의
            # checkpoint.save가 jump 커버, trailing 빈 분기는 다음 run 재시도).
            return 0, set(), QuarterStatus.SKIP_EMPTY, False

        # store-merge 실패 감지(#1993): 비파괴적 peek로 _normalize_and_store
        # 직전/직후 store_merge 경고 누적 카운트를 캡처하고 증가분으로 이번 분기
        # 실패를 판정한다. drain은 runner가 collect 종료 후 단일 소유로 하므로
        # 여기서는 count만 읽는다(drain 소유권 보존).
        merge_failures_before = store.pending_merge_failure_count()

        # storable_rows/net_delta를 분리 수신(#1993). QuarterStatus 판정은
        # storable_rows(정규화/저장 가능 행 수) 기준으로 유지하고(#2028 무변경),
        # 반환하는 written(rows_written)은 net_delta(실제 net-new 저장 행 수)다.
        storable_rows, net_delta, syms = self._normalize_and_store(
            raw_items,
            corp_code_map,
            store,
        )

        merge_failures_after = store.pending_merge_failure_count()
        store_merge_failed = merge_failures_after > merge_failures_before

        if storable_rows == 0:
            # raw_items는 있으나 정규화/저장에서 0 rows(normalized empty,
            # symbol 컬럼 부재 등 no-storable). net-delta가 아니라 storable
            # 기준으로 판정한다 — 재수집(dedup, net_delta=0)은 storable>0이라
            # 여기 걸리지 않고 OK로 처리되어 checkpoint stall을 만들지 않는다.
            # no-storable은 데이터 손실을 surface하고 checkpoint를 전진시키지
            # 않아 다음 run에서 재시도되게 한다.
            logger.warning(
                "DART 정규화/저장 결과 0건: year=%s reprt=%s raw=%d",
                year,
                reprt_code,
                len(raw_items),
            )
            warns.append(
                {
                    "source": "dart",
                    "year": str(year),
                    "reprt_code": reprt_code,
                    "message": (
                        f"raw {len(raw_items)}건이 정규화/저장에서 0건으로 "
                        "처리됨(no-storable)"
                    ),
                }
            )
            return 0, syms, QuarterStatus.HALT, store_merge_failed

        # storable_rows>0 → checkpoint 전진 자격(OK). 재수집이면 net_delta=0이라
        # rows_written은 0이지만 status는 OK로 checkpoint가 정상 전진한다. 단
        # store-merge 실패(net_delta=0 + store_merge 경고)면 호출자가
        # store_merge_failed로 checkpoint를 게이트해 미전진시킨다(다음 run 재시도).
        return net_delta, syms, QuarterStatus.OK, store_merge_failed

    def _normalize_and_store(
        self,
        raw_items: list[dict],
        corp_code_map: dict[str, str],
        store: ParquetStore,
    ) -> tuple[int, int, set[str]]:
        """raw 데이터를 정규화하고 심볼별로 저장한다.

        Returns:
            ``(storable_rows, net_delta, symbols)`` — 두 신호를 **분리** 반환한다
            (#1993, #2028 보존):

            - ``storable_rows``: 정규화/저장 가능한 행 수(정규화 결과 심볼별 행
              수의 합). normalized가 비거나 symbol 컬럼이 없으면 0. 이 값이
              ``_fetch_quarter`` 의 ``written == 0`` no-storable HALT 판정을
              구동한다(QuarterStatus 동작 무변경 — net-delta가 아니라 storable
              기준). 재수집(dedup으로 net_delta=0)이어도 storable_rows>0이라
              빈응답/no-storable과 구분된다.
            - ``net_delta``: ``store.write`` 가 반환한 **실제 net-new 저장 행 수**
              의 합(rows_written, #1993). 재수집/dedup이면 0.
            - ``symbols``: 저장 대상 심볼 집합.
        """
        df = pl.DataFrame(raw_items)
        normalized = self._normalizer.normalize(df, corp_code_map)

        if normalized.is_empty() or "symbol" not in normalized.columns:
            return 0, 0, set()

        storable_rows = 0
        net_delta = 0
        symbols: set[str] = set()
        for sym in normalized["symbol"].unique().to_list():
            sym_df = normalized.filter(pl.col("symbol") == sym)
            net_delta += store.write(sym, "krx", sym_df, data_type="fundamental")
            storable_rows += len(sym_df)
            symbols.add(sym)

        return storable_rows, net_delta, symbols
