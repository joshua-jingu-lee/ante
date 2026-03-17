"""4계층 데이터 검증 모듈 테스트.

각 검증 계층별 테스트와 통합 검증(validate_all) 테스트를 포함한다.
"""

from __future__ import annotations

import json

from ante.feed.models.result import ValidationResult
from ante.feed.transform.validate import (
    validate_all,
    validate_business,
    validate_schema,
    validate_syntax,
    validate_transport,
)

# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------


def _make_ohlcv_record(
    symbol: str = "005930",
    timestamp: str = "2024-01-02",
    open_: float = 100.0,
    high: float = 110.0,
    low: float = 90.0,
    close: float = 105.0,
    volume: int = 1000,
    amount: int = 100000,
    source: str = "data_go_kr",
) -> dict:
    """OHLCV 테스트 레코드를 생성한다."""
    return {
        "timestamp": timestamp,
        "symbol": symbol,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "amount": amount,
        "source": source,
    }


OHLCV_REQUIRED_FIELDS = [
    "timestamp",
    "symbol",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "source",
]


# ===========================================================================
# 1. 전송 계층 (validate_transport)
# ===========================================================================


class TestValidateTransport:
    """전송 계층 검증 테스트."""

    def test_success_200(self) -> None:
        result = validate_transport(200)
        assert result.passed is True
        assert result.errors == []

    def test_success_with_content_length(self) -> None:
        result = validate_transport(200, content_length=1024)
        assert result.passed is True

    def test_fail_4xx(self) -> None:
        result = validate_transport(404)
        assert result.passed is False
        assert len(result.errors) == 1
        assert "404" in result.errors[0]

    def test_fail_5xx(self) -> None:
        result = validate_transport(500)
        assert result.passed is False

    def test_fail_empty_content(self) -> None:
        result = validate_transport(200, content_length=0)
        assert result.passed is False
        assert "비어있음" in result.errors[0]

    def test_none_content_length_skipped(self) -> None:
        result = validate_transport(200, content_length=None)
        assert result.passed is True


# ===========================================================================
# 2. 구문 계층 (validate_syntax)
# ===========================================================================


class TestValidateSyntax:
    """구문 계층 검증 테스트."""

    def test_valid_json_string(self) -> None:
        raw = json.dumps([{"key": "value"}])
        result = validate_syntax(raw)
        assert result.passed is True

    def test_valid_dict(self) -> None:
        result = validate_syntax({"key": "value"})
        assert result.passed is True

    def test_valid_list(self) -> None:
        result = validate_syntax([{"key": "value"}])
        assert result.passed is True

    def test_none_input(self) -> None:
        result = validate_syntax(None)
        assert result.passed is False
        assert "None" in result.errors[0]

    def test_invalid_json(self) -> None:
        result = validate_syntax("{not valid json")
        assert result.passed is False
        assert "JSON" in result.errors[0]

    def test_invalid_bytes_encoding(self) -> None:
        result = validate_syntax(b"\x80\x81\x82")
        assert result.passed is False
        assert "인코딩" in result.errors[0]

    def test_valid_bytes(self) -> None:
        raw = json.dumps({"key": "value"}).encode("utf-8")
        result = validate_syntax(raw)
        assert result.passed is True

    def test_unsupported_type(self) -> None:
        result = validate_syntax(12345)
        assert result.passed is False
        assert "타입" in result.errors[0]

    def test_json_primitive_not_dict_or_list(self) -> None:
        result = validate_syntax('"just a string"')
        assert result.passed is False
        assert "타입" in result.errors[0]


# ===========================================================================
# 3. 스키마 계층 (validate_schema)
# ===========================================================================


class TestValidateSchema:
    """스키마 계층 검증 테스트."""

    def test_valid_records(self) -> None:
        records = [_make_ohlcv_record()]
        result = validate_schema(records, OHLCV_REQUIRED_FIELDS)
        assert result.passed is True
        assert result.errors == []

    def test_empty_records(self) -> None:
        result = validate_schema([], OHLCV_REQUIRED_FIELDS)
        assert result.passed is True
        assert "비어있음" in result.warnings[0]

    def test_missing_required_field(self) -> None:
        record = _make_ohlcv_record()
        del record["close"]
        result = validate_schema([record], OHLCV_REQUIRED_FIELDS)
        assert result.passed is False
        assert "close" in result.errors[0]

    def test_multiple_missing_fields(self) -> None:
        record = {"symbol": "005930", "source": "test"}
        result = validate_schema([record], OHLCV_REQUIRED_FIELDS)
        assert result.passed is False

    def test_numeric_conversion_failure(self) -> None:
        record = _make_ohlcv_record()
        record["open"] = "not_a_number"
        result = validate_schema([record], OHLCV_REQUIRED_FIELDS)
        assert result.passed is False
        assert "변환 불가" in result.errors[0]

    def test_string_numeric_values_ok(self) -> None:
        """문자열 숫자 (API 원시 응답 형태)도 통과해야 한다."""
        record = _make_ohlcv_record()
        record["open"] = "100.0"
        record["volume"] = "5000"
        result = validate_schema([record], OHLCV_REQUIRED_FIELDS)
        assert result.passed is True

    def test_none_numeric_values_ok(self) -> None:
        """None 값은 검사를 건너뛴다."""
        record = _make_ohlcv_record()
        record["amount"] = None
        result = validate_schema([record], OHLCV_REQUIRED_FIELDS)
        assert result.passed is True


# ===========================================================================
# 4. 비즈니스 계층 (validate_business)
# ===========================================================================


class TestValidateBusiness:
    """비즈니스 계층 검증 테스트."""

    def test_valid_ohlcv(self) -> None:
        records = [_make_ohlcv_record()]
        result = validate_business(records)
        assert result.passed is True
        assert result.warnings == []

    def test_empty_records(self) -> None:
        result = validate_business([])
        assert result.passed is True

    def test_negative_price(self) -> None:
        record = _make_ohlcv_record(open_=-10.0)
        result = validate_business([record])
        assert result.passed is True  # 비즈니스 규칙 위반은 경고
        assert any("open <= 0" in w for w in result.warnings)

    def test_zero_price(self) -> None:
        record = _make_ohlcv_record(close=0.0)
        result = validate_business([record])
        assert any("close <= 0" in w for w in result.warnings)

    def test_negative_volume(self) -> None:
        record = _make_ohlcv_record(volume=-100)
        result = validate_business([record])
        assert any("volume < 0" in w for w in result.warnings)

    def test_low_greater_than_close(self) -> None:
        record = _make_ohlcv_record(low=110.0, close=100.0, high=120.0, open_=115.0)
        result = validate_business([record])
        assert any("low > close" in w for w in result.warnings)

    def test_close_greater_than_high(self) -> None:
        record = _make_ohlcv_record(close=130.0, high=120.0, low=90.0)
        result = validate_business([record])
        assert any("close > high" in w for w in result.warnings)

    def test_open_greater_than_high(self) -> None:
        record = _make_ohlcv_record(open_=130.0, high=120.0, low=90.0)
        result = validate_business([record])
        assert any("open > high" in w for w in result.warnings)

    def test_low_greater_than_open(self) -> None:
        record = _make_ohlcv_record(low=110.0, open_=100.0, high=120.0, close=115.0)
        result = validate_business([record])
        assert any("low > open" in w for w in result.warnings)

    def test_duplicate_dates(self) -> None:
        records = [
            _make_ohlcv_record(timestamp="2024-01-02"),
            _make_ohlcv_record(timestamp="2024-01-02"),
        ]
        result = validate_business(records)
        assert any("중복" in w for w in result.warnings)

    def test_date_order_reversal(self) -> None:
        records = [
            _make_ohlcv_record(timestamp="2024-01-03"),
            _make_ohlcv_record(timestamp="2024-01-02"),
        ]
        result = validate_business(records)
        assert any("역전" in w for w in result.warnings)

    def test_multiple_symbols_independent(self) -> None:
        """심볼이 다르면 시계열 검증이 독립적으로 수행된다."""
        records = [
            _make_ohlcv_record(symbol="005930", timestamp="2024-01-03"),
            _make_ohlcv_record(symbol="000660", timestamp="2024-01-02"),
        ]
        result = validate_business(records)
        # 다른 심볼이므로 역전 경고가 없어야 함
        assert not any("역전" in w for w in result.warnings)

    def test_business_violations_are_warnings_not_errors(self) -> None:
        """비즈니스 규칙 위반은 경고이며 passed=True이다."""
        record = _make_ohlcv_record(
            low=200.0,
            close=100.0,
            high=90.0,
            open_=-5.0,
            volume=-1,
        )
        result = validate_business([record])
        assert result.passed is True
        assert len(result.warnings) > 0
        assert result.errors == []


# ===========================================================================
# 5. 통합 검증 (validate_all)
# ===========================================================================


class TestValidateAll:
    """통합 검증 테스트."""

    def test_all_pass(self) -> None:
        records = [_make_ohlcv_record()]
        result = validate_all(records, OHLCV_REQUIRED_FIELDS, status_code=200)
        assert result.passed is True
        assert result.errors == []

    def test_transport_failure_stops_pipeline(self) -> None:
        records = [_make_ohlcv_record()]
        result = validate_all(records, OHLCV_REQUIRED_FIELDS, status_code=500)
        assert result.passed is False

    def test_schema_failure_stops_pipeline(self) -> None:
        record = _make_ohlcv_record()
        del record["close"]
        result = validate_all([record], OHLCV_REQUIRED_FIELDS, status_code=200)
        assert result.passed is False
        assert any("close" in e for e in result.errors)

    def test_business_warnings_propagate(self) -> None:
        record = _make_ohlcv_record(low=200.0, close=100.0, high=300.0, open_=150.0)
        result = validate_all([record], OHLCV_REQUIRED_FIELDS, status_code=200)
        assert result.passed is True
        assert len(result.warnings) > 0

    def test_default_status_code(self) -> None:
        records = [_make_ohlcv_record()]
        result = validate_all(records, OHLCV_REQUIRED_FIELDS)
        assert result.passed is True


# ===========================================================================
# 6. ValidationResult 모델
# ===========================================================================


class TestValidationResult:
    """ValidationResult 데이터클래스 테스트."""

    def test_creation(self) -> None:
        result = ValidationResult(passed=True, warnings=[], errors=[])
        assert result.passed is True

    def test_merge_both_passed(self) -> None:
        a = ValidationResult(passed=True, warnings=["w1"], errors=[])
        b = ValidationResult(passed=True, warnings=["w2"], errors=[])
        merged = a.merge(b)
        assert merged.passed is True
        assert merged.warnings == ["w1", "w2"]
        assert merged.errors == []

    def test_merge_one_failed(self) -> None:
        a = ValidationResult(passed=True, warnings=[], errors=[])
        b = ValidationResult(passed=False, warnings=[], errors=["e1"])
        merged = a.merge(b)
        assert merged.passed is False
        assert merged.errors == ["e1"]

    def test_merge_both_failed(self) -> None:
        a = ValidationResult(passed=False, warnings=[], errors=["e1"])
        b = ValidationResult(passed=False, warnings=[], errors=["e2"])
        merged = a.merge(b)
        assert merged.passed is False
        assert merged.errors == ["e1", "e2"]

    def test_default_factory(self) -> None:
        result = ValidationResult(passed=True)
        assert result.warnings == []
        assert result.errors == []
