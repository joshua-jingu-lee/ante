"""4계층 데이터 검증 모듈.

계층별 검증:
  1. 전송 계층: HTTP 상태 코드, Content-Length 확인
  2. 구문 계층: JSON 파싱, 인코딩 정상 여부 확인
  3. 스키마 계층: 필수 필드 존재, 타입 변환 가능 여부 확인
  4. 비즈니스 계층: low<=open/close<=high, volume>=0, 시계열 갭 확인
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from ante.feed.models.result import ValidationResult

logger = logging.getLogger(__name__)


def validate_transport(
    status_code: int,
    content_length: int | None = None,
) -> ValidationResult:
    """전송 계층 검증.

    HTTP 상태 코드와 Content-Length를 확인한다.

    Args:
        status_code: HTTP 응답 상태 코드.
        content_length: 응답 본문 크기 (바이트). None이면 검사 생략.

    Returns:
        검증 결과.
    """
    errors: list[str] = []
    warnings: list[str] = []

    if not (200 <= status_code < 300):
        errors.append(f"HTTP 상태 코드 오류: {status_code}")

    if content_length is not None and content_length == 0:
        errors.append("응답 본문이 비어있음 (Content-Length: 0)")

    return ValidationResult(
        passed=len(errors) == 0,
        warnings=warnings,
        errors=errors,
    )


def validate_syntax(raw: Any) -> ValidationResult:
    """구문 계층 검증.

    JSON 파싱 가능 여부와 인코딩 정상 여부를 확인한다.

    Args:
        raw: 원시 응답 데이터. str이면 JSON 파싱을 시도하고,
             dict/list면 이미 파싱된 것으로 간주한다.

    Returns:
        검증 결과.
    """
    errors: list[str] = []
    warnings: list[str] = []

    if raw is None:
        errors.append("응답 데이터가 None")
        return ValidationResult(passed=False, warnings=warnings, errors=errors)

    if isinstance(raw, bytes):
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError as e:
            errors.append(f"인코딩 오류: {e}")
            return ValidationResult(passed=False, warnings=warnings, errors=errors)

    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, ValueError) as e:
            errors.append(f"JSON 파싱 오류: {e}")
            return ValidationResult(passed=False, warnings=warnings, errors=errors)
        if not isinstance(parsed, (dict, list)):
            errors.append(f"예상치 못한 JSON 타입: {type(parsed).__name__}")
    elif not isinstance(raw, (dict, list)):
        errors.append(f"지원하지 않는 데이터 타입: {type(raw).__name__}")

    return ValidationResult(
        passed=len(errors) == 0,
        warnings=warnings,
        errors=errors,
    )


def validate_schema(
    records: list[dict[str, Any]],
    required_fields: list[str],
) -> ValidationResult:
    """스키마 계층 검증.

    필수 필드 존재 여부와 타입 변환 가능 여부를 확인한다.

    Args:
        records: 검증할 레코드 목록.
        required_fields: 반드시 존재해야 하는 필드 이름 목록.

    Returns:
        검증 결과.
    """
    errors: list[str] = []
    warnings: list[str] = []

    if not records:
        warnings.append("레코드가 비어있음")
        return ValidationResult(passed=True, warnings=warnings, errors=errors)

    # 첫 레코드 기준으로 필수 필드 존재 여부 확인
    first_record_keys = set(records[0].keys())
    missing_fields = set(required_fields) - first_record_keys
    if missing_fields:
        errors.append(f"필수 필드 누락: {sorted(missing_fields)}")

    # 숫자 필드 타입 변환 가능 여부 확인
    numeric_fields = {"open", "high", "low", "close", "volume", "amount"}
    check_fields = numeric_fields & first_record_keys

    for i, record in enumerate(records):
        for field_name in check_fields:
            value = record.get(field_name)
            if value is None:
                continue
            if isinstance(value, (int, float)):
                continue
            try:
                float(value)
            except (ValueError, TypeError):
                errors.append(
                    f"레코드 {i}: 필드 '{field_name}' 값 '{value}'를 숫자로 변환 불가"
                )

    return ValidationResult(
        passed=len(errors) == 0,
        warnings=warnings,
        errors=errors,
    )


def validate_business(records: list[dict[str, Any]]) -> ValidationResult:
    """비즈니스 계층 검증.

    OHLCV 비즈니스 규칙과 시계열 연속성을 확인한다.
    실패 시 경고 로그를 남기고 저장은 허용한다.

    검증 규칙:
    - price > 0 (open, high, low, close)
    - volume >= 0
    - low <= close <= high
    - low <= open <= high
    - 시계열 갭 감지 (날짜 중복, 순서 역전)

    Args:
        records: 검증할 OHLCV 레코드 목록.

    Returns:
        검증 결과 (경고 포함 가능, 비즈니스 규칙 위반은 경고로 분류).
    """
    warnings: list[str] = []

    if not records:
        return ValidationResult(passed=True, warnings=warnings, errors=[])

    for i, record in enumerate(records):
        symbol = record.get("symbol", f"record_{i}")
        _check_positive_prices(record, symbol, warnings)
        _check_volume_non_negative(record, symbol, warnings)
        _check_ohlc_relationship(record, symbol, warnings)

    _validate_time_series(records, warnings)

    if warnings:
        for w in warnings:
            logger.warning("비즈니스 검증 경고: %s", w)

    return ValidationResult(
        passed=True,  # 비즈니스 규칙 위반은 경고이므로 passed=True
        warnings=warnings,
        errors=[],
    )


def _check_positive_prices(
    record: dict[str, Any],
    symbol: str,
    warnings: list[str],
) -> None:
    """가격 필드가 양수인지 검증한다.

    Args:
        record: 검증할 레코드.
        symbol: 심볼 식별자 (경고 메시지용).
        warnings: 경고를 추가할 목록.
    """
    for price_field in ("open", "high", "low", "close"):
        value = record.get(price_field)
        if value is None:
            continue
        try:
            price = float(value)
        except (ValueError, TypeError):
            continue  # 스키마 검증에서 이미 잡힘
        if price <= 0:
            warnings.append(f"{symbol}: {price_field} <= 0 ({price_field}={price})")


def _check_volume_non_negative(
    record: dict[str, Any],
    symbol: str,
    warnings: list[str],
) -> None:
    """거래량이 0 이상인지 검증한다.

    Args:
        record: 검증할 레코드.
        symbol: 심볼 식별자 (경고 메시지용).
        warnings: 경고를 추가할 목록.
    """
    volume_val = record.get("volume")
    if volume_val is None:
        return
    try:
        vol = int(float(str(volume_val)))
    except (ValueError, TypeError):
        return
    if vol < 0:
        warnings.append(f"{symbol}: volume < 0 (volume={vol})")


def _check_ohlc_relationship(
    record: dict[str, Any],
    symbol: str,
    warnings: list[str],
) -> None:
    """OHLC 관계(low <= open/close <= high)를 검증한다.

    Args:
        record: 검증할 레코드.
        symbol: 심볼 식별자 (경고 메시지용).
        warnings: 경고를 추가할 목록.
    """
    try:
        o = float(record["open"]) if "open" in record else None
        h = float(record["high"]) if "high" in record else None
        low_val = float(record["low"]) if "low" in record else None
        c = float(record["close"]) if "close" in record else None
    except (ValueError, TypeError):
        return  # 숫자 변환 실패는 스키마 계층에서 처리

    if not all(v is not None for v in (o, h, low_val, c)):
        return

    if low_val > c:
        warnings.append(f"{symbol}: low > close (low={low_val}, close={c})")
    if c > h:
        warnings.append(f"{symbol}: close > high (close={c}, high={h})")
    if low_val > o:
        warnings.append(f"{symbol}: low > open (low={low_val}, open={o})")
    if o > h:
        warnings.append(f"{symbol}: open > high (open={o}, high={h})")


def _validate_time_series(records: list[dict[str, Any]], warnings: list[str]) -> None:
    """시계열 연속성을 검증한다.

    날짜 중복과 순서 역전을 감지한다.

    Args:
        records: 검증할 레코드 목록.
        warnings: 경고를 추가할 목록.
    """
    # timestamp 또는 date 필드로 시계열 확인
    date_field = "timestamp" if "timestamp" in records[0] else "date"
    if date_field not in records[0]:
        return

    # 심볼별로 그룹핑하여 검증
    by_symbol: dict[str, list[str]] = {}
    for record in records:
        symbol = record.get("symbol", "unknown")
        date_val = record.get(date_field)
        if date_val is not None:
            by_symbol.setdefault(symbol, []).append(str(date_val))

    for symbol, dates in by_symbol.items():
        _check_duplicate_dates(symbol, dates, warnings)
        _check_date_order(symbol, dates, warnings)


def _check_duplicate_dates(
    symbol: str,
    dates: list[str],
    warnings: list[str],
) -> None:
    """날짜 중복을 검사한다.

    Args:
        symbol: 심볼 식별자.
        dates: 날짜 문자열 목록.
        warnings: 경고를 추가할 목록.
    """
    seen: set[str] = set()
    duplicates: list[str] = []
    for d in dates:
        if d in seen:
            duplicates.append(d)
        seen.add(d)

    if duplicates:
        warnings.append(f"{symbol}: 중복 날짜 감지: {duplicates}")


def _check_date_order(
    symbol: str,
    dates: list[str],
    warnings: list[str],
) -> None:
    """날짜 순서 역전을 검사한다.

    Args:
        symbol: 심볼 식별자.
        dates: 날짜 문자열 목록.
        warnings: 경고를 추가할 목록.
    """
    parsed_dates: list[tuple[datetime, str]] = []
    for d in dates:
        dt = _try_parse_date(d)
        if dt is not None:
            parsed_dates.append((dt, d))

    for j in range(1, len(parsed_dates)):
        if parsed_dates[j][0] < parsed_dates[j - 1][0]:
            warnings.append(
                f"{symbol}: 날짜 순서 역전 감지: "
                f"{parsed_dates[j - 1][1]} -> {parsed_dates[j][1]}"
            )


def _try_parse_date(value: str) -> datetime | None:
    """날짜 문자열을 파싱 시도한다.

    Args:
        value: 날짜 문자열.

    Returns:
        파싱된 datetime 또는 None.
    """
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d",
        "%Y%m%d",
    ):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def validate_all(
    records: list[dict[str, Any]],
    required_fields: list[str],
    status_code: int = 200,
) -> ValidationResult:
    """4계층 검증을 순서대로 실행한다.

    각 계층에서 오류가 발생하면 다음 계층으로 진행하지 않고
    해당 시점까지의 결과를 반환한다.

    Args:
        records: 검증할 레코드 목록.
        required_fields: 스키마 계층 필수 필드 목록.
        status_code: HTTP 상태 코드 (전송 계층 검증용).

    Returns:
        통합 검증 결과.
    """
    # 1. 전송 계층
    transport_result = validate_transport(status_code)
    if not transport_result.passed:
        return transport_result

    # 2. 구문 계층 (records가 이미 파싱된 상태이므로 list 검증)
    syntax_result = validate_syntax(records)
    if not syntax_result.passed:
        return transport_result.merge(syntax_result)

    # 3. 스키마 계층
    schema_result = validate_schema(records, required_fields)
    merged = transport_result.merge(syntax_result).merge(schema_result)
    if not merged.passed:
        return merged

    # 4. 비즈니스 계층
    business_result = validate_business(records)
    return merged.merge(business_result)
