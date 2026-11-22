"""DARTCollector — DART 재무제표 분기별 수집."""

from __future__ import annotations

import json
import logging
from calendar import monthrange
from datetime import date, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, cast

import polars as pl

from ante.core import clock
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

REPRT_CODES = ["11013", "11012", "11014", "11011"]

REPRT_TO_QUARTER: dict[str, str] = {
    "11013": "Q1",
    "11012": "Q2",
    "11014": "Q3",
    "11011": "Q4",
}

DEFAULT_BACKFILL_SINCE = "2015-01-01"


class QuarterStatus(Enum):
    """단일 분기 수집 결과의 3-상태.

    - ``HALT``: transient 예외 / raw-present no-storable(written==0). 데이터
      손실 가능성을 surface하고 이 run의 checkpoint 전진을 동결한다.
    - ``SKIP_EMPTY``: ``not raw_items``(분기종료 직후·공시 전 빈 응답 등 미공시
      가능). checkpoint를 전진시키지 않으면서 halt도 세우지 않아, 오름차순
      순회에서 후속 분기 처리를 계속한다.
    """

    OK = "ok"
    HALT = "halt"
    SKIP_EMPTY = "skip_empty"


QUARTER_STATUS_TRANSITIONS: dict[QuarterStatus, set[QuarterStatus]] = {
    QuarterStatus.OK: set(),
    QuarterStatus.HALT: set(),
    QuarterStatus.SKIP_EMPTY: set(),
}


_KST = timezone(timedelta(hours=9))


def _today_kst() -> date:
    """오늘 날짜(KST 캘린더)를 반환한다."""
    return clock.now(_KST).date()


def _quarter_period_end(year: int, reprt_code: str) -> date | None:
    """(year, reprt_code)가 가리키는 분기의 period-END 날짜를 반환한다."""
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
    ) -> tuple[int, bool, set[str], list[dict[str, Any]]]:
        """DART 재무제표를 분기별로 수집한다.

        Args:
            daily: ``True``면 daily-incremental 모드로, ``backfill_since`` 범위를
                순회하지 않고 **최신 collectable 분기 1개만** 수집한다.
                spec 07-execution-modes의 Daily Incremental("날짜 1개")에 대응하는
                DART daily-equivalent다. DART는 분기 단위 공시이므로 daily 실행은
                "오늘 기준 가장 최근에 공시 가능한 분기"만 확인한다. ``False``(기본,
                backfill 모드)면 ``_resolve_year_range``의 전 분기를 순회한다.
        """
        corp_code_map = await self._load_corp_codes(feed_dir)
        if not corp_code_map:
            logger.warning("DART: 고유번호 매핑이 비어있음")
            warns: list[dict[str, Any]] = [
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
        return cast(
            "dict[str, str]",
            await self._source.fetch_corp_codes(save_path=corp_codes_path),
        )

    @staticmethod
    def _resolve_year_range(
        config: dict[str, Any],
    ) -> tuple[int, int]:
        """설정에서 수집 연도 범위를 결정한다."""
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
    ) -> tuple[int, bool, set[str], list[dict[str, Any]]]:
        """연도/분기를 순회하며 재무제표를 수집한다."""
        corp_codes_list = list(corp_code_map.keys())
        rows_written = 0
        symbols: set[str] = set()
        warns: list[dict[str, Any]] = []
        stored_ok = False

        today = _today_kst()

        halt = False

        for year in range(start_year, end_year + 1):
            for reprt_code in REPRT_CODES:
                quarter_key = f"{year}-{REPRT_TO_QUARTER[reprt_code]}"
                if last_checkpoint and quarter_key <= last_checkpoint:
                    continue

                period_end = _quarter_period_end(year, reprt_code)
                if period_end is not None and period_end > today:
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
                    stored_ok = True
                    if not halt and not store_merge_failed:
                        checkpoint.save(quarter_key)

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
        """today(KST) 기준 가장 최근에 공시 가능한 (year, reprt_code)를 반환한다."""
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
    ) -> tuple[int, bool, set[str], list[dict[str, Any]]]:
        """daily 모드: 최신 collectable 분기 1개만 수집한다."""
        corp_codes_list = list(corp_code_map.keys())
        warns: list[dict[str, Any]] = []

        today = _today_kst()
        latest = self._latest_collectable_quarter(today)
        if latest is None:
            logger.info("DART daily: collectable 분기 없음")
            return 0, False, set(), warns

        year, reprt_code = latest
        quarter_key = f"{year}-{REPRT_TO_QUARTER[reprt_code]}"

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
        warns: list[dict[str, Any]],
    ) -> tuple[int, set[str], QuarterStatus, bool]:
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
            return 0, set(), QuarterStatus.HALT, False

        if not raw_items:
            return 0, set(), QuarterStatus.SKIP_EMPTY, False

        merge_failures_before = store.pending_merge_failure_count()

        storable_rows, net_delta, syms = self._normalize_and_store(
            raw_items,
            corp_code_map,
            store,
        )

        merge_failures_after = store.pending_merge_failure_count()
        store_merge_failed = merge_failures_after > merge_failures_before

        if storable_rows == 0:
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

        return net_delta, syms, QuarterStatus.OK, store_merge_failed

    def _normalize_and_store(
        self,
        raw_items: list[dict[str, Any]],
        corp_code_map: dict[str, str],
        store: ParquetStore,
    ) -> tuple[int, int, set[str]]:
        """raw 데이터를 정규화하고 심볼별로 저장한다."""
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
