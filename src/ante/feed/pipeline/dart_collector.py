"""DARTCollector — DART 재무제표 분기별 수집."""

from __future__ import annotations

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
            return 0, set(), []

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
        """고유번호 매핑을 로드하거나 다운로드한다."""
        corp_codes_path = feed_dir / "dart_corp_codes.json"
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

        for year in range(start_year, end_year + 1):
            for reprt_code in REPRT_CODES:
                quarter_key = f"{year}-{REPRT_TO_QUARTER[reprt_code]}"
                if last_checkpoint and quarter_key <= last_checkpoint:
                    continue

                period_end = _quarter_period_end(year, reprt_code)
                if period_end is not None and period_end > today:
                    # 미래 분기: fetch/save 모두 건너뛴다.
                    continue

                written, syms = await self._fetch_quarter(
                    corp_codes_list,
                    corp_code_map,
                    store,
                    year,
                    reprt_code,
                    warns,
                )
                rows_written += written
                symbols.update(syms)
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
    ) -> tuple[int, set[str]]:
        """단일 분기 재무제표를 수집/정규화/저장한다."""
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
            return 0, set()

        if not raw_items:
            return 0, set()

        return self._normalize_and_store(
            raw_items,
            corp_code_map,
            store,
        )

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
