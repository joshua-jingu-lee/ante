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
from ante.feed.transform.validate import validate_all, validate_business

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
    ) -> tuple[int, bool, set[str], list[dict[str, Any]]]:
        """특정 날짜의 전종목 데이터를 수집한다.

        Returns:
            ``(net_delta, stored_ok, 수집된 심볼 집합, 경고 목록)``:

            - ``net_delta``: store에 **실제 새로 저장된 net-new 행 수**
              (= ``store.write`` 반환 합, rows_written). 재수집(dedup)이면 0이며,
              이는 정상이다(과대계상 제거).
        """
        raw_items = await self._source.fetch(target_date)
        if not raw_items:
            logger.debug("data.go.kr: date=%s 데이터 없음", target_date)
            return 0, False, set(), []

        raw_items, symbol_warns = self._filter_invalid_symbols(raw_items, target_date)

        survivors, schema_warns = self._filter_schema_invalid(raw_items, target_date)
        validation_passed, validation_warns = self._validate(survivors, target_date)

        warns = symbol_warns + schema_warns + validation_warns
        if not survivors:
            logger.warning(
                "data.go.kr: date=%s 유효 레코드 없음(전 row drop)", target_date
            )
            return 0, False, set(), warns

        if not validation_passed:
            logger.warning(
                "data.go.kr: date=%s survivor 검증 실패(passed=False)로 저장 차단 "
                "(survivors=%d)",
                target_date,
                len(survivors),
            )
            return 0, False, set(), warns

        df = pl.DataFrame(survivors)
        df = self._deduplicate(df)

        net_delta, symbols = self._normalize_and_store(
            df,
            store,
            target_date,
            warns,
        )

        return net_delta, bool(symbols), symbols, warns

    @staticmethod
    def _filter_invalid_symbols(
        raw_items: list[dict[str, Any]],
        target_date: str,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """srtnCd가 KRX 6자리 형식이 아닌 row를 drop하고 구조화 warning을 반환한다."""
        valid: list[dict[str, Any]] = []
        warns: list[dict[str, Any]] = []
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
        raw_items: list[dict[str, Any]],
        target_date: str,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """raw 필수 필드가 누락/null인 레코드를 drop하고 구조화 warning을 반환한다."""
        survivors: list[dict[str, Any]] = []
        warns: list[dict[str, Any]] = []
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
        raw_items: list[dict[str, Any]],
        target_date: str,
    ) -> tuple[bool, list[dict[str, Any]]]:
        """선필터를 통과한 레코드를 검증하고 (passed, 경고 목록)을 반환한다."""
        warns: list[dict[str, Any]] = []
        if not raw_items:
            return True, warns

        validation = validate_all(raw_items, list(DATAGOKR_OHLCV_RAW_REQUIRED_FIELDS))

        for w in validation.warnings:
            warns.append(
                {
                    "date": target_date,
                    "source": "data_go_kr",
                    "type": "business_rule",
                    "message": w,
                }
            )

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
        return validation.passed, warns

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
        warns: list[dict[str, Any]],
    ) -> tuple[int, set[str]]:
        """OHLCV와 fundamental을 정규화하고 저장한다."""
        rows_written = 0
        symbols: set[str] = set()

        rows_written += self._store_ohlcv(df, store, symbols, target_date, warns)
        rows_written += self._store_fundamental(df, store, symbols)

        instruments_written = self._store_instruments(df, store)

        logger.info(
            "data.go.kr 수집 완료: date=%s symbols=%d rows=%d instruments=%d",
            target_date,
            len(symbols),
            rows_written,
            instruments_written,
        )
        return rows_written, symbols

    def _store_ohlcv(
        self,
        df: pl.DataFrame,
        store: ParquetStore,
        symbols: set[str],
        target_date: str,
        warns: list[dict[str, Any]],
    ) -> int:
        """OHLCV 데이터를 정규화하여 심볼별로 저장한다."""
        ohlcv_df = self._normalizer.normalize_ohlcv(df)
        if ohlcv_df.is_empty() or "symbol" not in ohlcv_df.columns:
            return 0

        business_result = validate_business(ohlcv_df.to_dicts())
        for w in business_result.warnings:
            warns.append(
                {
                    "date": target_date,
                    "source": "data_go_kr",
                    "type": "business_rule",
                    "message": w,
                }
            )

        rows = 0
        for sym in ohlcv_df["symbol"].unique().to_list():
            sym_df = ohlcv_df.filter(pl.col("symbol") == sym)
            rows += store.write(sym, "1d", sym_df, data_type="ohlcv")
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
            rows += store.write(sym, "krx", sym_df, data_type="fundamental")
            symbols.add(sym)
        return rows

    _INSTRUMENTS_COLUMNS = ("symbol", "exchange", "name", "market")

    @classmethod
    def _store_instruments(cls, df: pl.DataFrame, store: ParquetStore) -> int:
        """종목 메타데이터를 `.feed/instruments.parquet`에 upsert한다."""
        if "srtnCd" not in df.columns:
            return 0

        if "itmsNm" not in df.columns and "mrktCtg" not in df.columns:
            logger.debug(
                "data.go.kr instruments: 메타 컬럼(itmsNm/mrktCtg) 전무(rows=%d) "
                "— 파일 미생성",
                df.height,
            )
            return 0

        height = df.height
        symbol_expr = pl.col("srtnCd").cast(pl.Utf8)
        name_expr = (
            pl.col("itmsNm").cast(pl.Utf8) if "itmsNm" in df.columns else pl.lit("")
        )
        market_expr = (
            pl.col("mrktCtg").cast(pl.Utf8) if "mrktCtg" in df.columns else pl.lit("")
        )

        new_df = df.select(
            symbol_expr.alias("symbol"),
            pl.lit("KRX").alias("exchange"),
            name_expr.alias("name"),
            market_expr.alias("market"),
        )
        new_df = new_df.with_columns(
            pl.col("name").fill_null(""),
            pl.col("market").fill_null(""),
        )
        new_df = new_df.filter(
            pl.col("symbol").is_not_null() & (pl.col("symbol") != "")
        ).unique(subset=["symbol"], keep="last")

        if new_df.is_empty():
            logger.debug(
                "data.go.kr instruments: 유효 symbol 없음(rows=%d) — 파일 미변경",
                height,
            )
            return 0

        path = store.base_path / ".feed" / "instruments.parquet"
        is_zero_byte_recovery = store._is_zero_byte(path)
        preserve_existing_mode = not is_zero_byte_recovery
        if not is_zero_byte_recovery:
            try:
                existing = pl.read_parquet(path)
            except FileNotFoundError:
                merged = new_df
                preserve_existing_mode = False
            except Exception as exc:
                logger.warning(
                    "data.go.kr instruments: 기존 파일 읽기 실패 — 보존, "
                    "write 건너뜀 (%s)",
                    exc,
                )
                return 0
            else:
                merged = cls._merge_instruments(existing, new_df)
        else:
            merged = new_df

        merged = merged.select(list(cls._INSTRUMENTS_COLUMNS))
        path.parent.mkdir(parents=True, exist_ok=True)
        store._atomic_write_parquet(
            merged,
            path,
            preserve_existing_mode=preserve_existing_mode,
        )
        if is_zero_byte_recovery:
            logger.warning(
                "data.go.kr instruments: 0바이트 파일을 신규 수집분으로 복구: %s",
                path,
            )
        logger.info(
            "data.go.kr instruments 갱신: path=%s rows=%d",
            path,
            merged.height,
        )
        return merged.height

    @staticmethod
    def _merge_instruments(
        existing: pl.DataFrame, new_df: pl.DataFrame
    ) -> pl.DataFrame:
        """기존 instruments와 신규 행을 symbol 기준으로 merge한다."""
        existing = existing.with_columns(
            *[
                pl.lit("").alias(col)
                for col in ("symbol", "exchange", "name", "market")
                if col not in existing.columns
            ]
        )
        existing = existing.select("symbol", "exchange", "name", "market")
        existing = existing.with_columns(
            pl.col("symbol").cast(pl.Utf8),
            pl.col("exchange").cast(pl.Utf8).fill_null(""),
            pl.col("name").cast(pl.Utf8).fill_null(""),
            pl.col("market").cast(pl.Utf8).fill_null(""),
        )

        new_idx = {row["symbol"]: row for row in new_df.iter_rows(named=True)}
        existing_symbols: set[str] = set()
        merged_rows: list[dict[str, Any]] = []

        for row in existing.iter_rows(named=True):
            sym = row["symbol"]
            existing_symbols.add(sym)
            incoming = new_idx.get(sym)
            if incoming is None:
                merged_rows.append(row)
                continue
            merged_rows.append(
                {
                    "symbol": sym,
                    "exchange": "KRX",
                    "name": incoming["name"] or row["name"],
                    "market": incoming["market"] or row["market"],
                }
            )

        for sym, incoming in new_idx.items():
            if sym in existing_symbols:
                continue
            merged_rows.append(
                {
                    "symbol": sym,
                    "exchange": "KRX",
                    "name": incoming["name"],
                    "market": incoming["market"],
                }
            )

        return pl.DataFrame(
            merged_rows,
            schema={
                "symbol": pl.Utf8,
                "exchange": pl.Utf8,
                "name": pl.Utf8,
                "market": pl.Utf8,
            },
        )
