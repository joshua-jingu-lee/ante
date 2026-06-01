"""DARTCollector — DART 재무제표 분기별 수집."""

from __future__ import annotations

import json
import logging
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
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
    ) -> tuple[int, set[str], list[dict]]:
        """DART 재무제표를 분기별로 수집한다.

        Returns:
            (기록 행 수, 수집된 심볼 집합, 경고 목록).
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
            return 0, set(), warns

        start_year, end_year = self._resolve_year_range(config)
        last_checkpoint = checkpoint.get_last_date()
        last_checkpoint = self._migrate_checkpoint_key(last_checkpoint)

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
    ) -> tuple[int, set[str], list[dict]]:
        """연도/분기를 순회하며 재무제표를 수집한다."""
        corp_codes_list = list(corp_code_map.keys())
        rows_written = 0
        symbols: set[str] = set()
        warns: list[dict] = []

        # collectable 상한: period-end가 today(KST)를 지난 분기만 fetch/save.
        # 미래 분기(예: 실행일 2026-05-29 기준 2026-Q2/Q3/Q4)는 데이터가
        # 존재할 수 없으므로 fetch도 checkpoint.save도 수행하지 않는다.
        # 이로써 checkpoint가 미래 분기로 전진하지 않는다(#1964).
        today = _today_kst()

        # 첫 실패(ok=False) 이후에는 이 run에서 checkpoint를 더 전진시키지
        # 않는다(#2054). checkpoint는 quarter_key 오름차순 last-write-wins로
        # monotonic 전진하므로, 실패 분기 이후의 성공 분기를 save하면 checkpoint가
        # 실패 분기를 넘어 전진해 다음 run에서 재시도되지 않는다. halt 플래그로
        # 실패 분기 직전에 checkpoint를 고정해 다음 run이 실패 분기부터 재개한다.
        # 실패 이후 분기 fetch는 best-effort로 계속하며(데이터는 best-effort
        # 저장), 재-fetch는 ParquetStore의 natural-key dedup(keep="last")로
        # overwrite 멱등이라 중복 누적이 발생하지 않는다.
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

                written, syms, ok = await self._fetch_quarter(
                    corp_codes_list,
                    corp_code_map,
                    store,
                    year,
                    reprt_code,
                    warns,
                )
                rows_written += written
                symbols.update(syms)
                if not ok:
                    halt = True
                if ok and not halt:
                    checkpoint.save(quarter_key)

        logger.info(
            "DART 수집 완료: symbols=%d rows=%d",
            len(symbols),
            rows_written,
        )
        return rows_written, symbols, warns

    async def _fetch_quarter(
        self,
        corp_codes_list: list[str],
        corp_code_map: dict[str, str],
        store: ParquetStore,
        year: int,
        reprt_code: str,
        warns: list[dict],
    ) -> tuple[int, set[str], bool]:
        """단일 분기 재무제표를 수집/정규화/저장한다.

        Returns:
            (기록 행 수, 수집된 심볼 집합, ok). ``ok``는 이 분기가 checkpoint
            전진 자격을 갖는지를 나타낸다(#2054):

            - transient 예외(warn 추가) → ``ok=False``(미전진, 다음 run 재시도)
            - ``not raw_items``(upstream terminal no-data) → ``ok=True``
              (정당한 빈-성공; checkpoint 전진하여 무한 재시도 방지)
            - ``raw_items``는 있는데 정규화/저장 결과 0 rows(no-storable) →
              warn 추가 + ``ok=False``(데이터 손실 surface, 미전진)
            - 정상 저장(written>0) → ``ok=True``

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
            return 0, set(), False

        if not raw_items:
            # upstream terminal no-data: 정당한 빈-성공. checkpoint를 전진시켜
            # 데이터 없는 분기를 무한 재시도하지 않는다.
            return 0, set(), True

        written, syms = self._normalize_and_store(
            raw_items,
            corp_code_map,
            store,
        )
        if written == 0:
            # raw_items는 있으나 정규화/저장에서 0 rows(normalized empty,
            # symbol 컬럼 부재 등 no-storable). 데이터 손실을 surface하고
            # checkpoint를 전진시키지 않아 다음 run에서 재시도되게 한다.
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
            return 0, syms, False

        return written, syms, True

    def _normalize_and_store(
        self,
        raw_items: list[dict],
        corp_code_map: dict[str, str],
        store: ParquetStore,
    ) -> tuple[int, set[str]]:
        """raw 데이터를 정규화하고 심볼별로 저장한다."""
        df = pl.DataFrame(raw_items)
        normalized = self._normalizer.normalize(df, corp_code_map)

        if normalized.is_empty() or "symbol" not in normalized.columns:
            return 0, set()

        rows = 0
        symbols: set[str] = set()
        for sym in normalized["symbol"].unique().to_list():
            sym_df = normalized.filter(pl.col("symbol") == sym)
            store.write(sym, "krx", sym_df, data_type="fundamental")
            rows += len(sym_df)
            symbols.add(sym)

        return rows, symbols
