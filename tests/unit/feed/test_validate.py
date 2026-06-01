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

    def test_later_record_missing_field_detected(self) -> None:
        """첫 레코드 정상 + 이후 레코드 필수 필드 누락 → passed=False (#2087)."""
        first = _make_ohlcv_record(symbol="005930")
        second = _make_ohlcv_record(symbol="000660")
        del second["close"]
        result = validate_schema([first, second], OHLCV_REQUIRED_FIELDS)
        assert result.passed is False
        assert any("레코드 1" in e and "close" in e for e in result.errors)
        # 첫 레코드는 정상이므로 "레코드 0" 누락 에러는 없어야 함
        assert not any("레코드 0: 필수 필드 누락" in e for e in result.errors)

    def test_all_records_valid_multi(self) -> None:
        """모든 레코드가 정상이면 passed=True (회귀)."""
        records = [
            _make_ohlcv_record(symbol="005930", timestamp="2024-01-02"),
            _make_ohlcv_record(symbol="000660", timestamp="2024-01-03"),
            _make_ohlcv_record(symbol="035720", timestamp="2024-01-04"),
        ]
        result = validate_schema(records, OHLCV_REQUIRED_FIELDS)
        assert result.passed is True
        assert result.errors == []

    def test_null_required_timestamp_is_error(self) -> None:
        """present-but-null 필수 필드(timestamp=None)는 schema error (#2103)."""
        record = _make_ohlcv_record()
        record["timestamp"] = None
        result = validate_schema([record], OHLCV_REQUIRED_FIELDS)
        assert result.passed is False
        assert any(
            "레코드 0: 필수 필드 null 값" in e and "timestamp" in e
            for e in result.errors
        )

    def test_null_required_open_is_error(self) -> None:
        """present-but-null 필수 필드(open=None)는 schema error (#2103)."""
        record = _make_ohlcv_record()
        record["open"] = None
        result = validate_schema([record], OHLCV_REQUIRED_FIELDS)
        assert result.passed is False
        assert any(
            "레코드 0: 필수 필드 null 값" in e and "open" in e for e in result.errors
        )

    def test_null_non_required_field_not_error(self) -> None:
        """비필수 필드 null(amount=None)은 null 값 error가 아니다 (#2103)."""
        record = _make_ohlcv_record()
        record["amount"] = None
        result = validate_schema([record], OHLCV_REQUIRED_FIELDS)
        assert result.passed is True
        assert not any("필수 필드 null 값" in e for e in result.errors)

    def test_later_record_only_numeric_field_checked(self) -> None:
        """첫 레코드에 없고 이후 레코드에만 있는 숫자 필드의 비숫자 값도 검출."""
        first = {
            "timestamp": "2024-01-02",
            "symbol": "005930",
            "open": "100.0",
            "high": "110.0",
            "low": "90.0",
            "close": "105.0",
            "volume": "1000",
            "source": "data_go_kr",
            # amount 없음
        }
        second = {
            "timestamp": "2024-01-03",
            "symbol": "000660",
            "open": "100.0",
            "high": "110.0",
            "low": "90.0",
            "close": "105.0",
            "volume": "1000",
            "source": "data_go_kr",
            "amount": "not_a_number",  # 첫 레코드엔 없는 숫자 필드
        }
        required = [
            "timestamp",
            "symbol",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "source",
        ]
        result = validate_schema([first, second], required)
        assert result.passed is False
        assert any(
            "레코드 1" in e and "amount" in e and "변환 불가" in e
            for e in result.errors
        )


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

    def test_duplicate_dates_normalized_temporal_key(self) -> None:
        """이슈 재현: 같은 시점의 다른 형식 timestamp도 중복으로 감지 (#2102).

        "2026-01-01T00:00:00"과 "2026-01-01 00:00:00"은 _try_parse_date()가
        동일 datetime으로 파싱하므로 정규화 키 비교로 중복이 감지되어야 한다.
        """
        records = [
            _make_ohlcv_record(timestamp="2026-01-01T00:00:00"),
            _make_ohlcv_record(timestamp="2026-01-01 00:00:00"),
        ]
        result = validate_business(records)
        assert result.passed is True
        assert any("중복 날짜 감지" in w for w in result.warnings)

    def test_duplicate_dates_same_raw_regression(self) -> None:
        """회귀: 동일 raw 문자열 중복은 그대로 감지된다 (#2102)."""
        records = [
            _make_ohlcv_record(timestamp="2026-01-01"),
            _make_ohlcv_record(timestamp="2026-01-01"),
        ]
        result = validate_business(records)
        assert any("중복 날짜 감지" in w for w in result.warnings)

    def test_distinct_dates_no_duplicate_warning(self) -> None:
        """서로 다른 시점은 중복 경고가 없어야 한다 (#2102)."""
        records = [
            _make_ohlcv_record(timestamp="2026-01-01"),
            _make_ohlcv_record(timestamp="2026-01-02"),
        ]
        result = validate_business(records)
        assert not any("중복 날짜 감지" in w for w in result.warnings)

    def test_unparseable_duplicate_raw_fallback(self) -> None:
        """파싱 불가 동일 값은 raw fallback으로 중복 감지 (#2102)."""
        records = [
            _make_ohlcv_record(timestamp="bad"),
            _make_ohlcv_record(timestamp="bad"),
        ]
        result = validate_business(records)
        assert any("중복 날짜 감지" in w for w in result.warnings)

    def test_unparseable_distinct_no_duplicate(self) -> None:
        """파싱 불가 서로 다른 값은 중복 경고가 없어야 한다 (#2102)."""
        records = [
            _make_ohlcv_record(timestamp="bad1"),
            _make_ohlcv_record(timestamp="bad2"),
        ]
        result = validate_business(records)
        assert not any("중복 날짜 감지" in w for w in result.warnings)

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

    # --- NaN/inf finite 검증 (#2089) ---------------------------------------

    def test_nan_inf_observed_as_warning(self) -> None:
        """이슈 재현: NaN/inf 값은 business 경고로 관측되며 passed=True (#2089)."""
        record = _make_ohlcv_record()
        record["open"] = "NaN"
        record["high"] = "inf"
        record["low"] = float("nan")
        result = validate_business([record])
        assert result.passed is True
        assert result.errors == []
        finite_warnings = [w for w in result.warnings if "비정상 값(NaN/inf)" in w]
        # open/high/low 세 필드 모두 finite 경고가 남아야 함
        assert any("open" in w for w in finite_warnings)
        assert any("high" in w for w in finite_warnings)
        assert any("low" in w for w in finite_warnings)

    def test_finite_warnings_propagate_via_validate_all(self) -> None:
        """schema 통과(필수 필드 충족) 시 business finite 경고가 전파된다 (#2089)."""
        record = _make_ohlcv_record()
        record["open"] = "NaN"
        record["high"] = "inf"
        result = validate_all([record], OHLCV_REQUIRED_FIELDS, status_code=200)
        assert result.passed is True
        assert any("비정상 값(NaN/inf)" in w for w in result.warnings)

    def test_valid_finite_data_no_finite_warning(self) -> None:
        """회귀: 정상 finite 데이터에는 finite 경고가 없다 (#2089)."""
        record = _make_ohlcv_record()
        result = validate_business([record])
        assert result.passed is True
        assert not any("비정상 값(NaN/inf)" in w for w in result.warnings)

    def test_volume_inf_no_crash(self) -> None:
        """volume=inf는 int() OverflowError 없이 finite 경고만 남긴다 (#2089)."""
        record = _make_ohlcv_record()
        record["volume"] = "inf"
        result = validate_business([record])
        assert result.passed is True
        assert any("비정상 값(NaN/inf)" in w and "volume" in w for w in result.warnings)
        # volume<0 오탐 경고는 없어야 함
        assert not any("volume < 0" in w for w in result.warnings)

    def test_none_fields_skipped_by_finite_check(self) -> None:
        """None 필드는 finite 검사에서 건너뛴다 (경고 없음) (#2089)."""
        record = _make_ohlcv_record()
        record["amount"] = None
        result = validate_business([record])
        assert result.passed is True
        assert not any("비정상 값(NaN/inf)" in w for w in result.warnings)

    def test_nonfinite_does_not_trigger_downstream_false_positive(self) -> None:
        """중복/오탐 차단 lock: -inf/inf는 finite 경고만, downstream 오탐 없음 (#2089).

        open=-inf는 _check_positive_prices의 price<=0 오탐 위치,
        low=inf는 _check_ohlc_relationship의 low>close 오탐 위치를 유발한다.
        finite 가드로 이들 downstream 경고가 발생하지 않아야 한다.
        """
        record = _make_ohlcv_record()
        record["open"] = float("-inf")
        record["low"] = float("inf")
        result = validate_business([record])
        assert result.passed is True
        assert result.errors == []

        finite_warnings = [w for w in result.warnings if "비정상 값(NaN/inf)" in w]
        # finite 경고는 open/low 두 필드에 대해 존재
        assert any("open" in w for w in finite_warnings)
        assert any("low" in w for w in finite_warnings)
        # finite 경고 외 downstream 오탐 경고는 전무해야 함
        assert len(result.warnings) == len(finite_warnings)
        for substring in ("<= 0", "low > close", "open > high", "low > open"):
            assert not any(substring in w for w in result.warnings)

    # --- temporal 파싱 가능성 검증 (#2103) ---------------------------------

    def test_unparseable_timestamp_is_warning(self) -> None:
        """파싱 불가 timestamp는 business 경고이며 passed=True (#2103)."""
        record = _make_ohlcv_record(timestamp="not-a-date")
        result = validate_business([record])
        assert result.passed is True
        assert result.errors == []
        assert any("timestamp 파싱 불가" in w for w in result.warnings)

    def test_parseable_timestamp_no_warning(self) -> None:
        """회귀: 파싱 가능한 timestamp는 파싱불가 경고가 없다 (#2103)."""
        record = _make_ohlcv_record(timestamp="2026-01-01")
        result = validate_business([record])
        assert result.passed is True
        assert not any("파싱 불가" in w for w in result.warnings)

    def test_datetime_timestamp_no_false_positive(self) -> None:
        """datetime 객체 timestamp(이미 파싱됨)는 파싱불가 오탐이 없다 (#2103)."""
        from datetime import datetime

        record = _make_ohlcv_record()
        record["timestamp"] = datetime(2026, 1, 1, 0, 0, 0)
        result = validate_business([record])
        assert result.passed is True
        assert not any("파싱 불가" in w for w in result.warnings)

    def test_unparseable_date_field_is_warning(self) -> None:
        """date 필드 파싱 불가도 경고로 관측된다 (#2103)."""
        record = _make_ohlcv_record()
        del record["timestamp"]
        record["date"] = "garbage"
        result = validate_business([record])
        assert result.passed is True
        assert any("date 파싱 불가" in w for w in result.warnings)


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

    def test_null_required_field_blocks_pipeline(self) -> None:
        """null 필수 필드(timestamp=None)는 schema error로 파이프라인 차단 (#2103)."""
        record = _make_ohlcv_record()
        record["timestamp"] = None
        result = validate_all([record], OHLCV_REQUIRED_FIELDS, status_code=200)
        assert result.passed is False
        assert any("필수 필드 null 값" in e and "timestamp" in e for e in result.errors)

    def test_null_required_open_blocks_pipeline(self) -> None:
        """null 필수 필드(open=None)는 schema error로 파이프라인 차단 (#2103)."""
        record = _make_ohlcv_record()
        record["open"] = None
        result = validate_all([record], OHLCV_REQUIRED_FIELDS, status_code=200)
        assert result.passed is False
        assert any("필수 필드 null 값" in e and "open" in e for e in result.errors)

    def test_unparseable_timestamp_passes_schema_warns_business(self) -> None:
        """파싱 불가 timestamp: schema 통과 후 business 경고 전파 (#2103)."""
        record = _make_ohlcv_record(timestamp="not-a-date")
        result = validate_all([record], OHLCV_REQUIRED_FIELDS, status_code=200)
        assert result.passed is True
        assert result.errors == []
        assert any("timestamp 파싱 불가" in w for w in result.warnings)

    def test_valid_record_no_temporal_warning(self) -> None:
        """회귀: 정상 레코드는 errors=[] 이고 temporal 경고도 없다 (#2103)."""
        record = _make_ohlcv_record(timestamp="2026-01-01")
        result = validate_all([record], OHLCV_REQUIRED_FIELDS, status_code=200)
        assert result.passed is True
        assert result.errors == []
        assert not any("파싱 불가" in w for w in result.warnings)


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
