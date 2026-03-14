"""소스별 Normalizer 클래스 패턴 테스트."""

import polars as pl
import pytest

from ante.data.normalizer import (
    BaseNormalizer,
    DefaultNormalizer,
    KISNormalizer,
    YahooNormalizer,
    get_normalizer,
    register_normalizer,
)

# ── BaseNormalizer ABC ──


def test_base_normalizer_is_abstract():
    """BaseNormalizer는 직접 인스턴스화할 수 없다."""
    with pytest.raises(TypeError):
        BaseNormalizer()  # type: ignore[abstract]


# ── KISNormalizer ──


class TestKISNormalizer:
    @pytest.fixture
    def normalizer(self):
        return KISNormalizer()

    def test_source_name(self, normalizer):
        assert normalizer.source_name == "kis"

    def test_column_mapping_keys(self, normalizer):
        mapping = normalizer.column_mapping
        assert "stck_oprc" in mapping
        assert "stck_hgpr" in mapping
        assert "stck_lwpr" in mapping
        assert "stck_clpr" in mapping
        assert "acml_vol" in mapping

    def test_normalize_kis_format(self, normalizer):
        """KIS API 응답 형식이 OHLCV 스키마로 정규화된다."""
        df = pl.DataFrame(
            {
                "stck_bsop_date": ["2026-03-01T09:00:00"],
                "stck_oprc": [50000],
                "stck_hgpr": [50100],
                "stck_lwpr": [49900],
                "stck_clpr": [50050],
                "acml_vol": [1000],
            }
        )
        result = normalizer.normalize(df)
        assert "timestamp" in result.columns
        assert "open" in result.columns
        assert "high" in result.columns
        assert "low" in result.columns
        assert "close" in result.columns
        assert "volume" in result.columns
        assert result["source"][0] == "kis"

    def test_normalize_kis_numeric_types(self, normalizer):
        """KIS 데이터의 가격은 Float64, 거래량은 Int64로 변환된다."""
        df = pl.DataFrame(
            {
                "stck_bsop_date": ["2026-03-01T09:00:00"],
                "stck_oprc": [50000],
                "stck_hgpr": [50100],
                "stck_lwpr": [49900],
                "stck_clpr": [50050],
                "acml_vol": [1000],
            }
        )
        result = normalizer.normalize(df)
        assert result["open"].dtype == pl.Float64
        assert result["volume"].dtype == pl.Int64


# ── YahooNormalizer ──


class TestYahooNormalizer:
    @pytest.fixture
    def normalizer(self):
        return YahooNormalizer()

    def test_source_name(self, normalizer):
        assert normalizer.source_name == "yahoo"

    def test_normalize_yahoo_format(self, normalizer):
        """Yahoo Finance 형식이 정규화된다."""
        df = pl.DataFrame(
            {
                "Date": ["2026-03-01T09:00:00", "2026-03-02T09:00:00"],
                "Open": [50000, 50100],
                "High": [50100, 50200],
                "Low": [49900, 50000],
                "Close": [50050, 50150],
                "Volume": [1000, 1100],
            }
        )
        result = normalizer.normalize(df)
        assert len(result) == 2
        assert "timestamp" in result.columns
        assert result["source"][0] == "yahoo"


# ── DefaultNormalizer ──


class TestDefaultNormalizer:
    @pytest.fixture
    def normalizer(self):
        return DefaultNormalizer()

    def test_source_name(self, normalizer):
        assert normalizer.source_name == "external"

    def test_normalize_with_date_column(self, normalizer):
        """'date' 컬럼이 'timestamp'로 매핑된다."""
        df = pl.DataFrame(
            {
                "date": ["2026-03-01T09:00:00"],
                "open": [50000.0],
                "high": [50100.0],
                "low": [49900.0],
                "close": [50050.0],
                "volume": [1000],
            }
        )
        result = normalizer.normalize(df)
        assert "timestamp" in result.columns

    def test_normalize_with_vol_column(self, normalizer):
        """'vol' 컬럼이 'volume'으로 매핑된다."""
        df = pl.DataFrame(
            {
                "timestamp": ["2026-03-01T09:00:00"],
                "open": [50000.0],
                "high": [50100.0],
                "low": [49900.0],
                "close": [50050.0],
                "vol": [1000],
            }
        )
        result = normalizer.normalize(df)
        assert "volume" in result.columns


# ── 레지스트리 ──


def test_get_normalizer_kis():
    """get_normalizer('kis')가 KISNormalizer를 반환한다."""
    n = get_normalizer("kis")
    assert isinstance(n, KISNormalizer)


def test_get_normalizer_yahoo():
    n = get_normalizer("yahoo")
    assert isinstance(n, YahooNormalizer)


def test_get_normalizer_default():
    n = get_normalizer("external")
    assert isinstance(n, DefaultNormalizer)


def test_get_normalizer_unknown_returns_default():
    """미등록 소스는 DefaultNormalizer로 폴백한다."""
    n = get_normalizer("unknown_source")
    assert isinstance(n, DefaultNormalizer)


def test_register_custom_normalizer():
    """커스텀 Normalizer를 레지스트리에 등록할 수 있다."""

    class CustomNormalizer(BaseNormalizer):
        @property
        def source_name(self) -> str:
            return "custom"

        @property
        def column_mapping(self) -> dict[str, str]:
            return {"price": "close"}

    register_normalizer("custom", CustomNormalizer)
    n = get_normalizer("custom")
    assert isinstance(n, CustomNormalizer)
    assert n.source_name == "custom"


def test_no_timestamp_raises():
    """timestamp 컬럼 없이 정규화하면 ValueError."""
    n = DefaultNormalizer()
    df = pl.DataFrame({"open": [50000.0], "close": [50050.0]})
    with pytest.raises(ValueError, match="timestamp"):
        n.normalize(df)
