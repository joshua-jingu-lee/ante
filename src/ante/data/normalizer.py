"""Data Pipeline — 다양한 소스의 데이터를 통일된 스키마로 정규화.

소스별 Normalizer 클래스 패턴: BaseNormalizer ABC를 상속하여
각 데이터 소스(KIS, Yahoo 등)마다 정규화 로직을 캡슐화한다.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

import polars as pl

from ante.data.schemas import FUNDAMENTAL_COLUMNS, OHLCV_COLUMNS

logger = logging.getLogger(__name__)


class BaseNormalizer(ABC):
    """데이터 정규화 인터페이스.

    모든 소스별 Normalizer가 구현해야 하는 ABC.
    """

    @property
    @abstractmethod
    def source_name(self) -> str:
        """데이터 소스 식별자 (예: 'kis', 'yahoo')."""
        ...

    @property
    @abstractmethod
    def column_mapping(self) -> dict[str, str]:
        """소스 컬럼명 → OHLCV 표준 컬럼명 매핑."""
        ...

    def normalize(self, df: pl.DataFrame) -> pl.DataFrame:
        """DataFrame을 OHLCV 스키마로 정규화.

        Args:
            df: 원본 DataFrame.

        Returns:
            OHLCV 스키마에 맞춰 정규화된 DataFrame.
        """
        # 컬럼 이름 매핑
        rename_map = {
            src: dst for src, dst in self.column_mapping.items() if src in df.columns
        }
        if rename_map:
            df = df.rename(rename_map)

        # 소스별 추가 변환 (서브클래스 오버라이드 가능)
        df = self.transform(df)

        # timestamp 정규화
        df = _normalize_timestamp(df)

        # 숫자 컬럼 타입 변환
        for col in ("open", "high", "low", "close"):
            if col in df.columns:
                df = df.with_columns(pl.col(col).cast(pl.Float64))
        if "volume" in df.columns:
            df = df.with_columns(pl.col("volume").cast(pl.Int64))
        if "amount" in df.columns:
            df = df.with_columns(pl.col("amount").cast(pl.Int64))

        # amount 컬럼 (없으면 null로 채움)
        if "amount" not in df.columns:
            df = df.with_columns(pl.lit(None).cast(pl.Int64).alias("amount"))

        # source 컬럼
        if "source" not in df.columns:
            df = df.with_columns(pl.lit(self.source_name).alias("source"))

        # symbol 컬럼 (호출자가 채움)
        if "symbol" not in df.columns:
            df = df.with_columns(pl.lit("").alias("symbol"))

        # 스키마 컬럼만 선택
        available = [c for c in OHLCV_COLUMNS if c in df.columns]
        return df.select(available).sort("timestamp")

    def transform(self, df: pl.DataFrame) -> pl.DataFrame:
        """소스별 추가 변환 훅. 기본은 무변환."""
        return df


class KISNormalizer(BaseNormalizer):
    """한국투자증권(KIS) API 응답 정규화."""

    @property
    def source_name(self) -> str:
        return "kis"

    @property
    def column_mapping(self) -> dict[str, str]:
        return {
            "stck_bsop_date": "date",
            "stck_clpr": "close",
            "stck_oprc": "open",
            "stck_hgpr": "high",
            "stck_lwpr": "low",
            "acml_vol": "volume",
        }

    def transform(self, df: pl.DataFrame) -> pl.DataFrame:
        """KIS date 컬럼을 timestamp로 변환."""
        if "date" in df.columns and "timestamp" not in df.columns:
            df = df.rename({"date": "timestamp"})
        return df


class YahooNormalizer(BaseNormalizer):
    """Yahoo Finance 데이터 정규화."""

    @property
    def source_name(self) -> str:
        return "yahoo"

    @property
    def column_mapping(self) -> dict[str, str]:
        return {
            "Date": "timestamp",
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume",
        }


class DefaultNormalizer(BaseNormalizer):
    """범용 정규화. 일반적인 컬럼명(date, datetime 등)을 매핑."""

    @property
    def source_name(self) -> str:
        return "external"

    @property
    def column_mapping(self) -> dict[str, str]:
        return {
            "date": "timestamp",
            "datetime": "timestamp",
            "time": "timestamp",
            "open": "open",
            "high": "high",
            "low": "low",
            "close": "close",
            "volume": "volume",
            "vol": "volume",
        }


class DataGoKrNormalizer(BaseNormalizer):
    """data.go.kr 주식시세 API 응답 정규화.

    동일한 API 응답에서 OHLCV와 FUNDAMENTAL 두 스키마를 각각 추출한다.
    모든 API 응답 값이 문자열이므로 숫자 타입 변환을 수행한다.
    """

    # OHLCV 컬럼 매핑
    _OHLCV_MAPPING: dict[str, str] = {
        "basDt": "timestamp",
        "srtnCd": "symbol",
        "mkp": "open",
        "hipr": "high",
        "lopr": "low",
        "clpr": "close",
        "trqu": "volume",
        "trPrc": "amount",
    }

    # FUNDAMENTAL 컬럼 매핑
    _FUNDAMENTAL_MAPPING: dict[str, str] = {
        "basDt": "date",
        "srtnCd": "symbol",
        "mrktTotAmt": "market_cap",
        "lstgStCnt": "shares_listed",
    }

    @property
    def source_name(self) -> str:
        return "data_go_kr"

    @property
    def column_mapping(self) -> dict[str, str]:
        return self._OHLCV_MAPPING

    def transform(self, df: pl.DataFrame) -> pl.DataFrame:
        """data.go.kr 문자열 값을 숫자로 변환."""
        # 숫자 컬럼: 문자열 → 숫자 변환
        for col in ("open", "high", "low", "close"):
            if col in df.columns and df[col].dtype == pl.Utf8:
                df = df.with_columns(pl.col(col).cast(pl.Float64))
        for col in ("volume", "amount"):
            if col in df.columns and df[col].dtype == pl.Utf8:
                df = df.with_columns(pl.col(col).cast(pl.Int64))

        # timestamp: YYYYMMDD 문자열 → Date → Datetime 변환
        if "timestamp" in df.columns and df["timestamp"].dtype == pl.Utf8:
            df = df.with_columns(
                pl.col("timestamp").str.to_date("%Y%m%d").cast(pl.Datetime("ns"))
            )
        return df

    def normalize_ohlcv(self, df: pl.DataFrame) -> pl.DataFrame:
        """data.go.kr 응답을 OHLCV_SCHEMA DataFrame으로 정규화.

        Args:
            df: data.go.kr API 원본 응답 DataFrame (모든 값이 문자열).

        Returns:
            OHLCV_SCHEMA에 맞춘 DataFrame.
        """
        return self.normalize(df)

    def normalize_fundamental(self, df: pl.DataFrame) -> pl.DataFrame:
        """data.go.kr 응답을 FUNDAMENTAL_SCHEMA 부분 DataFrame으로 정규화.

        Args:
            df: data.go.kr API 원본 응답 DataFrame (모든 값이 문자열).

        Returns:
            FUNDAMENTAL_SCHEMA 부분 필드
            (date, symbol, market_cap, shares_listed, source).
        """
        # 컬럼 매핑
        rename_map = {
            src: dst
            for src, dst in self._FUNDAMENTAL_MAPPING.items()
            if src in df.columns
        }
        if rename_map:
            df = df.rename(rename_map)

        # date: YYYYMMDD 문자열 → Date 변환
        if "date" in df.columns and df["date"].dtype == pl.Utf8:
            df = df.with_columns(pl.col("date").str.to_date("%Y%m%d"))

        # 숫자 컬럼 변환
        if "market_cap" in df.columns and df["market_cap"].dtype == pl.Utf8:
            df = df.with_columns(pl.col("market_cap").cast(pl.Int64))
        if "shares_listed" in df.columns and df["shares_listed"].dtype == pl.Utf8:
            df = df.with_columns(pl.col("shares_listed").cast(pl.Int64))

        # source 컬럼
        if "source" not in df.columns:
            df = df.with_columns(pl.lit(self.source_name).alias("source"))

        # FUNDAMENTAL_SCHEMA 컬럼만 선택
        available = [c for c in FUNDAMENTAL_COLUMNS if c in df.columns]
        return df.select(available)


# ── DART 재무제표 Normalizer ─────────────────────────

# DART 계정과목명 → FUNDAMENTAL_SCHEMA 필드 매핑
_DART_ACCOUNT_MAP: dict[str, str] = {
    "매출액": "revenue",
    "수익(매출액)": "revenue",
    "당기순이익": "net_income",
    "당기순이익(손실)": "net_income",
    "자본총계": "total_equity",
    "부채총계": "total_debt",
    "자산총계": "total_assets",
}

# DART reprt_code → (분기, 월) 매핑
_REPRT_CODE_MAP: dict[str, tuple[str, int]] = {
    "11013": ("1Q", 3),
    "11012": ("semi", 6),
    "11014": ("3Q", 9),
    "11011": ("annual", 12),
}


class DARTNormalizer:
    """DART API 재무제표 응답을 FUNDAMENTAL_SCHEMA로 정규화.

    DART 응답은 계정과목별 행(row-per-account) 구조이므로
    종목별 컬럼 구조로 피벗 변환한다.

    파생 지표(PER/PBR/EPS/BPS/ROE/부채비율)는 계산하지 않는다.
    이들은 orchestrator가 data.go.kr 데이터와 결합하여 계산한다.
    """

    @property
    def source_name(self) -> str:
        """데이터 소스 식별자."""
        return "dart"

    def normalize(
        self,
        df: pl.DataFrame,
        corp_code_map: dict[str, str],
    ) -> pl.DataFrame:
        """DART 재무제표 DataFrame을 정규화.

        Args:
            df: DART API 원본 응답 DataFrame.
                필수 컬럼: corp_code, account_nm,
                thstrm_amount, fs_div, reprt_code, bsns_year
            corp_code_map: corp_code -> symbol 매핑
                (예: {"00126380": "005930"}).

        Returns:
            FUNDAMENTAL_SCHEMA 부분 컬럼을 가진 DataFrame.
            포함: date, symbol, revenue, net_income,
            total_equity, total_debt, total_assets, source.
        """
        from ante.data.schemas import FUNDAMENTAL_COLUMNS

        empty_schema = {
            "date": pl.Date,
            "symbol": pl.Utf8,
            "source": pl.Utf8,
        }

        if df.is_empty():
            return pl.DataFrame(schema=empty_schema)

        required_cols = {
            "corp_code",
            "account_nm",
            "thstrm_amount",
            "fs_div",
            "reprt_code",
            "bsns_year",
        }
        missing = required_cols - set(df.columns)
        if missing:
            msg = f"DART DataFrame에 필수 컬럼이 없습니다: {missing}"
            raise ValueError(msg)

        # 매핑 대상 계정과목만 필터링
        target_accounts = list(_DART_ACCOUNT_MAP.keys())
        df = df.filter(pl.col("account_nm").is_in(target_accounts))

        if df.is_empty():
            return pl.DataFrame(schema=empty_schema)

        # CFS(연결재무제표) 우선, OFS(개별재무제표) 폴백
        df = self._select_fs_div(df)

        # corp_code → symbol 매핑
        df = df.with_columns(
            pl.col("corp_code")
            .replace_strict(corp_code_map, default=None)
            .alias("symbol")
        )
        # 매핑 실패 행 제거
        df = df.filter(pl.col("symbol").is_not_null())

        if df.is_empty():
            return pl.DataFrame(schema=empty_schema)

        # reprt_code + bsns_year → date 변환
        df = self._convert_report_date(df)

        # thstrm_amount 콤마 제거 + 숫자 변환
        df = df.with_columns(
            pl.col("thstrm_amount")
            .cast(pl.Utf8)
            .str.replace_all(",", "")
            .cast(pl.Int64, strict=False)
            .alias("amount_value")
        )

        # 계정과목명 → 필드명 매핑
        df = df.with_columns(
            pl.col("account_nm")
            .replace_strict(_DART_ACCOUNT_MAP, default=None)
            .alias("field_name")
        )
        df = df.filter(pl.col("field_name").is_not_null())

        if df.is_empty():
            return pl.DataFrame(schema=empty_schema)

        # 피벗: 행(계정과목별) → 열(종목별 필드)
        pivoted = df.pivot(
            on="field_name",
            index=["symbol", "date"],
            values="amount_value",
            aggregate_function="first",
        )

        # source 컬럼 추가
        pivoted = pivoted.with_columns(pl.lit("dart").alias("source"))

        # 출력 컬럼 선택
        fundamental_cols = set(FUNDAMENTAL_COLUMNS)
        extra_cols = {
            "total_equity",
            "total_debt",
            "total_assets",
        }
        select_cols: list[str] = [
            col
            for col in pivoted.columns
            if col in fundamental_cols or col in extra_cols
        ]

        result = pivoted.select(select_cols)

        # 숫자 컬럼 타입 강제
        int_fields = {
            "revenue",
            "net_income",
            "total_equity",
            "total_debt",
            "total_assets",
        }
        for col in int_fields:
            if col in result.columns:
                result = result.with_columns(pl.col(col).cast(pl.Int64, strict=False))

        return result.sort("symbol", "date")

    def _select_fs_div(self, df: pl.DataFrame) -> pl.DataFrame:
        """CFS(연결) 우선, 없으면 OFS(개별) 폴백.

        corp_code + reprt_code 기준으로 CFS 데이터가 있으면
        CFS만, CFS가 없는 조합은 OFS를 사용한다.
        """
        cfs = df.filter(pl.col("fs_div") == "CFS")
        ofs = df.filter(pl.col("fs_div") == "OFS")

        if cfs.is_empty():
            return ofs
        if ofs.is_empty():
            return cfs

        # CFS가 있는 (corp_code, reprt_code) 조합
        cfs_keys = cfs.select("corp_code", "reprt_code").unique()

        # OFS 중 CFS가 없는 조합만 추출
        ofs_fallback = ofs.join(
            cfs_keys,
            on=["corp_code", "reprt_code"],
            how="anti",
        )

        return pl.concat([cfs, ofs_fallback])

    def _convert_report_date(self, df: pl.DataFrame) -> pl.DataFrame:
        """reprt_code + bsns_year → date 컬럼 변환.

        reprt_code 매핑:
        - 11013 → 1Q (3월 말)
        - 11012 → semi (6월 말)
        - 11014 → 3Q (9월 말)
        - 11011 → annual (12월 말)
        """
        from calendar import monthrange
        from datetime import date as date_cls

        def _to_date(reprt_code: str, bsns_year: str) -> date_cls | None:
            mapping = _REPRT_CODE_MAP.get(reprt_code)
            if mapping is None:
                return None
            _, month = mapping
            year = int(bsns_year)
            day = monthrange(year, month)[1]
            return date_cls(year, month, day)

        dates: list[date_cls | None] = []
        for rc, by in zip(
            df["reprt_code"].to_list(),
            df["bsns_year"].to_list(),
        ):
            dates.append(_to_date(str(rc), str(by)))

        df = df.with_columns(pl.Series("date", dates, dtype=pl.Date))
        return df.filter(pl.col("date").is_not_null())


# ── Normalizer 레지스트리 ────────────────────────────

NORMALIZER_REGISTRY: dict[str, type[BaseNormalizer]] = {
    "kis": KISNormalizer,
    "yahoo": YahooNormalizer,
    "default": DefaultNormalizer,
    "external": DefaultNormalizer,
    "data_go_kr": DataGoKrNormalizer,
}

# DARTNormalizer는 BaseNormalizer(OHLCV)와 다른 스키마이므로 별도 등록
DART_NORMALIZER_REGISTRY: dict[str, type[DARTNormalizer]] = {
    "dart": DARTNormalizer,
}


def get_normalizer(source: str) -> BaseNormalizer:
    """소스명으로 Normalizer 인스턴스를 조회.

    Args:
        source: 데이터 소스 식별자 (예: "kis", "yahoo", "external").

    Returns:
        해당 소스의 Normalizer 인스턴스. 미등록 시 DefaultNormalizer.
    """
    cls = NORMALIZER_REGISTRY.get(source, DefaultNormalizer)
    return cls()


def register_normalizer(source: str, cls: type[BaseNormalizer]) -> None:
    """커스텀 Normalizer를 레지스트리에 등록.

    새 거래소 추가 시 이 함수로 등록하면 DataNormalizer가 자동 인식.
    """
    NORMALIZER_REGISTRY[source] = cls


# ── 하위 호환 DataNormalizer 파사드 ──────────────────

# 기존 COLUMN_MAPPINGS 유지 (하위 호환)
COLUMN_MAPPINGS: dict[str, dict[str, str]] = {
    "kis": KISNormalizer().column_mapping,
    "yahoo": YahooNormalizer().column_mapping,
    "default": DefaultNormalizer().column_mapping,
}


class DataNormalizer:
    """하위 호환 파사드. 내부적으로 소스별 Normalizer에 위임."""

    def normalize(
        self,
        df: pl.DataFrame,
        source: str = "external",
        format_hint: str | None = None,
    ) -> pl.DataFrame:
        """DataFrame을 OHLCV 스키마로 정규화.

        Args:
            df: 원본 DataFrame.
            source: 데이터 소스 식별자.
            format_hint: 소스별 컬럼 매핑 힌트. None이면 source 사용.

        Returns:
            OHLCV 스키마에 맞춰 정규화된 DataFrame.
        """
        has_source = "source" in df.columns
        key = format_hint or source
        normalizer = get_normalizer(key)
        result = normalizer.normalize(df)
        # source 값: 원본에 없었을 때만 source 파라미터로 덮어쓰기
        if not has_source and "source" in result.columns:
            result = result.with_columns(pl.lit(source).alias("source"))
        return result

    @staticmethod
    def _normalize_timestamp(df: pl.DataFrame) -> pl.DataFrame:
        """timestamp 컬럼을 Datetime[ns]로 정규화."""
        return _normalize_timestamp(df)


# ── 공통 유틸 ────────────────────────────────────────


def _normalize_timestamp(df: pl.DataFrame) -> pl.DataFrame:
    """timestamp 컬럼을 Datetime[ns, UTC]로 정규화."""
    if "timestamp" not in df.columns:
        raise ValueError("DataFrame에 timestamp 컬럼이 없습니다.")

    ts_dtype = df["timestamp"].dtype
    if ts_dtype == pl.Utf8:
        df = df.with_columns(pl.col("timestamp").str.to_datetime(time_zone="UTC"))
    elif ts_dtype == pl.Date:
        df = df.with_columns(
            pl.col("timestamp").cast(pl.Datetime("ns")).dt.replace_time_zone("UTC")
        )
    elif isinstance(ts_dtype, pl.Datetime):
        if ts_dtype.time_zone is None:
            df = df.with_columns(pl.col("timestamp").dt.replace_time_zone("UTC"))
    else:
        raise ValueError(f"지원하지 않는 timestamp 타입: {ts_dtype}")

    return df
