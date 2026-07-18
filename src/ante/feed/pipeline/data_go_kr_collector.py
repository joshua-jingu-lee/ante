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
    ) -> tuple[int, bool, set[str], list[dict]]:
        """특정 날짜의 전종목 데이터를 수집한다.

        Returns:
            ``(net_delta, stored_ok, 수집된 심볼 집합, 경고 목록)`` (#1993):

            - ``net_delta``: store에 **실제 새로 저장된 net-new 행 수**
              (= ``store.write`` 반환 합, rows_written). 재수집(dedup)이면 0이며,
              이는 정상이다(과대계상 제거).
            - ``stored_ok``: **유효 데이터가 store에 성공적으로 반영되었는지**.
              net_delta와 무관하며 ``bool(symbols)`` (실제 ``store.write`` 가
              호출된 심볼 존재)에서 유도한다 — 재수집으로 net_delta=0이어도 유효
              데이터를 정규화·저장 완료했으면 symbols가 비어있지 않아 ``True`` 다
              (checkpoint 전진 자격). 빈 응답/전 row drop/validation 차단처럼 저장
              자체를 못한 경우는 조기 ``False`` 반환하고, survivor가 validation을
              통과했어도 정규화 단계에서 추가 drop돼 ohlcv/fundamental 둘 다
              no-symbol이면 symbols가 비어 ``False`` 다(저장 0건 → 미전진).
              store-merge 실패(기존 파일 보존)는 ``store.write`` 호출은 완료했으므로
              해당 심볼이 symbols에 남아 여기서는 ``True`` 이며, checkpoint 미전진은
              runner가 store_merge 경고 존재로 별도 가드한다(R1:
              ``_persist_partition`` 은 merge 실패 시 raise하지 않는다).
        """
        raw_items = await self._source.fetch(target_date)
        if not raw_items:
            logger.debug("data.go.kr: date=%s 데이터 없음", target_date)
            return 0, False, set(), []

        raw_items, symbol_warns = self._filter_invalid_symbols(raw_items, target_date)

        # (a) schema 선필터: 필수 raw 필드 누락/null 레코드를 drop & 에러 로그.
        survivors, schema_warns = self._filter_schema_invalid(raw_items, target_date)
        # (b) survivor 검증: business 경고 수집 + passed 게이트 판정.
        validation_passed, validation_warns = self._validate(survivors, target_date)

        warns = symbol_warns + schema_warns + validation_warns
        if not survivors:
            logger.warning(
                "data.go.kr: date=%s 유효 레코드 없음(전 row drop)", target_date
            )
            return 0, False, set(), warns

        # (c) 검증 게이트: survivor batch가 validate_all에서 passed=False면
        # (transport status≠200, syntax, 또는 향후 schema 검사) 저장하지 않는다.
        # spec(09-failure-recovery.md): schema 실패 레코드는 스킵(저장 금지).
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

        # business 계층은 정규화 후 OHLCV(open/high/low/close/volume)에 적용해야
        # 의미가 있다(#2222). raw `_validate`/validate_all의 business는 raw 컬럼명
        # (mkp/hipr/...)이라 no-op이므로, 정규화 후 별도 검증 경고를 warns에 surface
        # 한다. business는 비차단(경고)이므로 store는 진행한다(spec 09).
        net_delta, symbols = self._normalize_and_store(
            df,
            store,
            target_date,
            warns,
        )

        # stored_ok는 하드코딩 True가 아니라 **실제 저장 심볼 존재(bool(symbols))**
        # 에서 유도한다. `symbols`는 `_store_ohlcv`/`_store_fundamental`에서
        # 실제 `store.write`가 호출된 심볼만 add되므로:
        #   - 빈 응답/전 drop/validation 차단 → 위에서 stored_ok=False 조기 반환.
        #   - survivor가 validation을 통과했더라도 정규화 단계에서 추가 drop돼
        #     normalize_ohlcv·normalize_fundamental이 **둘 다** empty/no-symbol이면
        #     symbols가 빈 set → stored_ok=False(미전진). 저장 0건인데 checkpoint를
        #     전진시켜 데이터를 영구 skip하는 회귀를 막는다.
        #   - 재수집(net_delta=0이지만 정규화 정상)은 symbols가 비어있지 않아
        #     stored_ok=True(전진 유지). net_delta와 무관하게 저장 반영 여부만 본다.
        return net_delta, bool(symbols), symbols, warns

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
    ) -> tuple[bool, list[dict]]:
        """선필터를 통과한 레코드를 검증하고 (passed, 경고 목록)을 반환한다.

        schema 계층은 선필터(_filter_schema_invalid)에서 이미 통과했으므로
        실무상 survivor 검증은 거의 항상 passed=True다. 다만 transport
        (status≠200)/syntax 또는 향후 schema 검사가 잔여 실패를 surface할 수
        있으므로 batch 단위 게이트로 전달한다. passed=False면 호출자가 batch
        저장을 차단한다(spec 09-failure-recovery.md: schema 실패 skip).

        raw_items가 비어있으면 validate_all이 schema 빈-레코드로 passed=True를
        반환하므로 게이트를 막지 않는다(선필터로 전 row drop된 정상 케이스).

        Returns:
            (validation.passed, 구조화 경고 목록).
        """
        warns: list[dict] = []
        if not raw_items:
            return True, warns

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
        # passed=False면 호출자가 batch 저장을 차단한다(저장 금지).
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
        warns: list[dict],
    ) -> tuple[int, set[str]]:
        """OHLCV와 fundamental을 정규화하고 저장한다.

        Args:
            df: survivor raw DataFrame.
            store: 저장소.
            target_date: 수집 대상 날짜(경고 구조화용).
            warns: business 경고를 누적할 목록(collect의 warns로 surface, #2222).
                정규화 후 OHLCV business 위반은 비차단 경고로 여기 추가된다.

        Returns:
            ``(net_delta, symbols)``. net_delta는 ohlcv/fundamental ``store.write``
            반환(실제 net-new 저장 행 수)의 합이다(#1993). 재수집/dedup이면 0.
        """
        rows_written = 0
        symbols: set[str] = set()

        rows_written += self._store_ohlcv(df, store, symbols, target_date, warns)
        rows_written += self._store_fundamental(df, store, symbols)

        # 종목 메타데이터(symbol/exchange/name/market)를 `.feed/instruments.parquet`에
        # upsert한다(spec data-feed/04-schema.md INSTRUMENTS). ohlcv/fundamental과
        # 의미가 다른(심볼 1행 마스터) 산출이라 rows_written에 합산하지 않고 별도
        # 로그만 남긴다. 저장 실패가 ohlcv/fundamental 결과를 회귀시키지 않도록
        # 호출은 ohlcv/fundamental 저장 뒤에 둔다.
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
        warns: list[dict],
    ) -> int:
        """OHLCV 데이터를 정규화하여 심볼별로 저장한다.

        정규화 직후 business 계층 검증(`validate_business`)을 정규화 OHLCV
        (open/high/low/close/volume) 값에 적용한다(#2222). raw `_validate`의
        business는 raw 컬럼명(mkp/hipr/...)이라 no-op이므로, 의미 있는 OHLC 정합성
        (`low<=open/close<=high`)·price>0·volume>=0 anomaly 경고를 여기서 발행한다.
        business는 비차단(경고)이므로 위반이 있어도 저장은 진행한다(spec 09:
        business='경고 로그, 저장'). 시계열 갭(`_validate_time_series`)은 단일 날짜
        collect + dedup 후 사실상 no-op이라 강한 보장 대상은 아니다.

        Args:
            df: survivor raw DataFrame.
            store: 저장소.
            symbols: 저장 심볼을 누적할 집합.
            target_date: 수집 대상 날짜(경고 구조화용).
            warns: business 경고를 누적할 목록(collect의 warns로 surface).

        Returns:
            ``store.write`` 반환(net-new 저장 행 수)의 합(#1993). 입력 len이
            아니라 실제 저장 delta다(재수집/dedup이면 0).
        """
        ohlcv_df = self._normalizer.normalize_ohlcv(df)
        if ohlcv_df.is_empty() or "symbol" not in ohlcv_df.columns:
            return 0

        # 정규화 후 OHLCV에 business 검증(비차단 경고). 기존 구조화 컨벤션
        # (source=data_go_kr / type=business_rule, line 216의 raw business_rule
        # 채널과 동일)으로 wrap하여 collect warns에 surface한다(신규 타입 금지).
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
        """fundamental 데이터를 정규화하여 심볼별로 저장한다.

        Returns:
            ``store.write`` 반환(net-new 저장 행 수)의 합(#1993). 입력 len이
            아니라 실제 저장 delta다(재수집/dedup이면 0).
        """
        fund_df = self._normalizer.normalize_fundamental(df)
        if fund_df.is_empty() or "symbol" not in fund_df.columns:
            return 0

        rows = 0
        for sym in fund_df["symbol"].unique().to_list():
            sym_df = fund_df.filter(pl.col("symbol") == sym)
            rows += store.write(sym, "krx", sym_df, data_type="fundamental")
            symbols.add(sym)
        return rows

    # INSTRUMENTS 스키마 컬럼 순서(spec data-feed/04-schema.md).
    _INSTRUMENTS_COLUMNS = ("symbol", "exchange", "name", "market")

    @classmethod
    def _store_instruments(cls, df: pl.DataFrame, store: ParquetStore) -> int:
        """종목 메타데이터를 `.feed/instruments.parquet`에 upsert한다.

        매핑(spec data-feed/04-schema.md INSTRUMENTS, 05-data-sources.md):
        `srtnCd`→symbol, `itmsNm`→name, `mrktCtg`→market, exchange="KRX".
        itmsNm/mrktCtg 컬럼이 둘 다 없으면(메타데이터 전무) 무가치한 파일을
        만들지 않도록 저장을 건너뛴다. 적어도 하나의 메타 컬럼이 있으면 누락 셀은
        빈 문자열로 안전 처리한다.

        upsert 정책:
        - 신규 batch는 symbol 기준 1행으로 dedup한다.
        - 기존 `.feed/instruments.parquet`가 있으면 symbol을 키로 merge한다.
          단 신규 행의 name/market가 비어있으면(누락/빈 문자열) 기존 non-empty
          값을 덮어쓰지 않고 보존한다(Codex refinement). 신규 값이 non-empty면
          갱신한다.
        - 파일이 없으면 신규 생성한다.

        symbol 컬럼이 없거나 결과가 비어있으면 파일을 생성/변경하지 않는다.

        Returns:
            파일에 기록된 instrument 행 수. 미기록(빈 입력)이면 0.
        """
        # df는 survivors raw DataFrame이므로 종목코드 컬럼은 `srtnCd`다.
        if "srtnCd" not in df.columns:
            return 0

        # itmsNm/mrktCtg가 둘 다 없으면 메타데이터 전무 → 무가치 파일 생성 방지.
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
        # null(누락 셀)은 빈 문자열로 정규화하여 보존 로직이 일관되게 동작하게 한다.
        new_df = new_df.with_columns(
            pl.col("name").fill_null(""),
            pl.col("market").fill_null(""),
        )
        # 유효한 symbol만 유지(빈/null symbol drop) 후 symbol 기준 dedup(1행/심볼).
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
        if path.exists():
            # Check for zero-byte file
            try:
                if path.stat().st_size == 0:
                    logger.warning(
                        "data.go.kr instruments: zero-byte file detected, removing for auto-recovery: %s",
                        path,
                    )
                    try:
                        path.unlink(missing_ok=True)
                    except OSError as exc:
                        logger.warning(
                            "data.go.kr instruments: zero-byte file unlink failed — preserving: %s (%s)",
                            path,
                            exc,
                        )
                        return 0
                    # Treat as missing: merged = new_df
                    merged = new_df
                else:
                    try:
                        existing = pl.read_parquet(path)
                    except Exception as exc:
                        # 기존 파일 손상 시 신규 데이터로 덮어쓰지 않고 보존(데이터 손실 방지).
                        logger.warning(
                            "data.go.kr instruments: 기존 파일 읽기 실패 — 보존, "
                            "write 건너뜀 (%s)",
                            exc,
                        )
                        return 0
                    merged = cls._merge_instruments(existing, new_df)
            except OSError as exc:
                logger.warning(
                    "data.go.kr instruments: failed to check file size — preserving: %s (%s)",
                    path,
                    exc,
                )
                return 0
        else:
            merged = new_df

        merged = merged.select(list(cls._INSTRUMENTS_COLUMNS))
        path.parent.mkdir(parents=True, exist_ok=True)
        # Use atomic write
        store._atomic_write_parquet(merged, path)
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
        """기존 instruments와 신규 행을 symbol 기준으로 merge한다.

        - 신규 symbol은 그대로 추가한다.
        - 기존 symbol은 갱신하되, 신규 name/market가 빈 문자열이면 기존
          non-empty 값을 보존한다(빈 신규값이 기존 값을 덮어쓰지 않게).
        - exchange는 항상 "KRX"로 유지한다.
        """
        # 기존 프레임을 INSTRUMENTS 컬럼으로 정규화(누락 컬럼은 빈 문자열).
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
        merged_rows: list[dict] = []

        for row in existing.iter_rows(named=True):
            sym = row["symbol"]
            existing_symbols.add(sym)
            incoming = new_idx.get(sym)
            if incoming is None:
                merged_rows.append(row)
                continue
            # 신규값이 non-empty면 갱신, 빈 값이면 기존 보존.
            merged_rows.append(
                {
                    "symbol": sym,
                    "exchange": "KRX",
                    "name": incoming["name"] or row["name"],
                    "market": incoming["market"] or row["market"],
                }
            )

        # 기존에 없던 신규 symbol 추가.
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
