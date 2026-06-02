"""DataGoKrCollector — data.go.kr 전종목 일별 수집."""

from __future__ import annotations

import logging
from typing import Any

import polars as pl

from ante.core.market_data_vocab import is_krx_symbol
from ante.data.normalizer import (
    DATAGOKR_OHLCV_RAW_REQUIRED_FIELDS,
    DataGoKrNormalizer,
)
from ante.data.store import ParquetStore
from ante.feed.transform.validate import validate_all

logger = logging.getLogger(__name__)


class DataGoKrCollector:
    """data.go.kr에서 특정 날짜 전종목 데이터를 수집한다.

    책임: API 호출 -> 검증 -> 정규화 -> 심볼별 저장.
    """

    def __init__(
        self,
        source: Any,
        normalizer: DataGoKrNormalizer | None = None,
    ) -> None:
        self._source = source
        self._normalizer = normalizer or DataGoKrNormalizer()

    async def collect(
        self,
        target_date: str,
        store: ParquetStore,
    ) -> tuple[int, set[str], list[dict]]:
        """특정 날짜의 전종목 데이터를 수집한다.

        Returns:
            (기록 행 수, 수집된 심볼 집합, 경고 목록).
        """
        raw_items = await self._source.fetch(target_date)
        if not raw_items:
            logger.debug("data.go.kr: date=%s 데이터 없음", target_date)
            return 0, set(), []

        raw_items, symbol_warns = self._filter_invalid_symbols(raw_items, target_date)

        # (a) schema 선필터: 필수 raw 필드 누락/null 레코드를 drop & 에러 로그.
        survivors, schema_warns = self._filter_schema_invalid(raw_items, target_date)
        # (b) survivor 검증: business 경고 수집 + 비-schema 실패 surface.
        business_warns = self._validate(survivors, target_date)

        warns = symbol_warns + schema_warns + business_warns
        if not survivors:
            logger.warning(
                "data.go.kr: date=%s 유효 레코드 없음(전 row drop)", target_date
            )
            return 0, set(), warns

        df = pl.DataFrame(survivors)
        df = self._deduplicate(df)

        rows_written, symbols = self._normalize_and_store(
            df,
            store,
            target_date,
        )

        return rows_written, symbols, warns

    @staticmethod
    def _filter_invalid_symbols(
        raw_items: list[dict],
        target_date: str,
    ) -> tuple[list[dict], list[dict]]:
        """srtnCd가 KRX 6자리 형식이 아닌 row를 drop하고 구조화 warning을 반환한다."""
        valid: list[dict] = []
        warns: list[dict] = []
        for item in raw_items:
            srtn: Any = item.get("srtnCd")
            if is_krx_symbol(srtn):
                valid.append(item)
            else:
                warns.append(
                    {
                        "date": target_date,
                        "source": "data_go_kr",
                        "type": "invalid_symbol",
                        "message": f"비KRX 심볼 drop: srtnCd={srtn!r}",
                    }
                )
        return valid, warns

    @staticmethod
    def _filter_schema_invalid(
        raw_items: list[dict],
        target_date: str,
    ) -> tuple[list[dict], list[dict]]:
        """raw 필수 필드가 누락/null인 레코드를 drop하고 구조화 warning을 반환한다.

        판정 기준은 validate_schema와 동일하다: 필수 필드의 키가 없거나(missing
        key) 값이 None(null)이면 schema 실패로 간주한다. drop된 레코드는 에러
        로그를 남기고 type=schema_validation 엔트리로 surface한다(저장 차단).
        """
        survivors: list[dict] = []
        warns: list[dict] = []
        for item in raw_items:
            missing = [f for f in DATAGOKR_OHLCV_RAW_REQUIRED_FIELDS if f not in item]
            null_fields = [
                f
                for f in DATAGOKR_OHLCV_RAW_REQUIRED_FIELDS
                if f in item and item.get(f) is None
            ]
            if missing or null_fields:
                reason = []
                if missing:
                    reason.append(f"누락={missing}")
                if null_fields:
                    reason.append(f"null={null_fields}")
                detail = ", ".join(reason)
                logger.error(
                    "data.go.kr: date=%s 필수 필드 누락/null로 레코드 skip "
                    "(srtnCd=%r, %s)",
                    target_date,
                    item.get("srtnCd"),
                    detail,
                )
                warns.append(
                    {
                        "date": target_date,
                        "source": "data_go_kr",
                        "type": "schema_validation",
                        "message": (
                            f"필수 필드 누락/null로 레코드 skip: "
                            f"srtnCd={item.get('srtnCd')!r}, {detail}"
                        ),
                    }
                )
            else:
                survivors.append(item)
        return survivors, warns

    @staticmethod
    def _validate(
        raw_items: list[dict],
        target_date: str,
    ) -> list[dict]:
        """선필터를 통과한 레코드를 검증하고 경고 목록을 반환한다.

        schema 계층은 선필터(_filter_schema_invalid)에서 이미 통과했으므로
        여기서는 business 경고를 수집한다. transport/syntax 등 비-schema 실패가
        나오면 폐기하지 않고 에러 로그 + schema_validation 엔트리로 surface한다.
        """
        warns: list[dict] = []
        if not raw_items:
            return warns

        validation = validate_all(raw_items, list(DATAGOKR_OHLCV_RAW_REQUIRED_FIELDS))

        # business 계층 경고 (저장 유지)
        for w in validation.warnings:
            warns.append(
                {
                    "date": target_date,
                    "source": "data_go_kr",
                    "type": "business_rule",
                    "message": w,
                }
            )

        # 비-schema(transport/syntax 등) 실패는 무시하지 않고 surface한다.
        for err in validation.errors:
            logger.error("data.go.kr: date=%s survivor 검증 실패: %s", target_date, err)
            warns.append(
                {
                    "date": target_date,
                    "source": "data_go_kr",
                    "type": "schema_validation",
                    "message": err,
                }
            )
        return warns

    @staticmethod
    def _deduplicate(df: pl.DataFrame) -> pl.DataFrame:
        """srtnCd + basDt 기준 중복을 제거한다."""
        if "srtnCd" in df.columns and "basDt" in df.columns:
            return df.unique(subset=["srtnCd", "basDt"])
        return df

    def _normalize_and_store(
        self,
        df: pl.DataFrame,
        store: ParquetStore,
        target_date: str,
    ) -> tuple[int, set[str]]:
        """OHLCV와 fundamental을 정규화하고 저장한다."""
        rows_written = 0
        symbols: set[str] = set()

        rows_written += self._store_ohlcv(df, store, symbols)
        rows_written += self._store_fundamental(df, store, symbols)

        logger.info(
            "data.go.kr 수집 완료: date=%s symbols=%d rows=%d",
            target_date,
            len(symbols),
            rows_written,
        )
        return rows_written, symbols

    def _store_ohlcv(
        self,
        df: pl.DataFrame,
        store: ParquetStore,
        symbols: set[str],
    ) -> int:
        """OHLCV 데이터를 정규화하여 심볼별로 저장한다."""
        ohlcv_df = self._normalizer.normalize_ohlcv(df)
        if ohlcv_df.is_empty() or "symbol" not in ohlcv_df.columns:
            return 0

        rows = 0
        for sym in ohlcv_df["symbol"].unique().to_list():
            sym_df = ohlcv_df.filter(pl.col("symbol") == sym)
            store.write(sym, "1d", sym_df, data_type="ohlcv")
            rows += len(sym_df)
            symbols.add(sym)
        return rows

    def _store_fundamental(
        self,
        df: pl.DataFrame,
        store: ParquetStore,
        symbols: set[str],
    ) -> int:
        """fundamental 데이터를 정규화하여 심볼별로 저장한다."""
        fund_df = self._normalizer.normalize_fundamental(df)
        if fund_df.is_empty() or "symbol" not in fund_df.columns:
            return 0

        rows = 0
        for sym in fund_df["symbol"].unique().to_list():
            sym_df = fund_df.filter(pl.col("symbol") == sym)
            store.write(sym, "krx", sym_df, data_type="fundamental")
            rows += len(sym_df)
            symbols.add(sym)
        return rows
