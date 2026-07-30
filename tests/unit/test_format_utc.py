"""``ante.core.time`` 단위 테스트 (Refs #1360, #2412).

- :func:`format_utc` (#1360) — IPC와 이벤트 payload가 공유하는 UTC ISO 8601
  직렬화 helper. Python ``datetime.isoformat()``의 기본 ``+00:00``을 ``Z``로
  치환한다.
- :func:`iso_to_kis_date` (#2412) — 공개 표면 ISO ``YYYY-MM-DD``를 broker
  어댑터 경계의 압축 ``YYYYMMDD``로 바꾸는 **공유 chokepoint**. CLI(직접 연결
  폴백)와 IPC(핸들러) 두 소비자가 같은 함수를 호출한다.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from ante.core.time import InvalidIsoDateError, format_utc, iso_to_kis_date


def test_format_utc_replaces_plus_zero_offset_with_z() -> None:
    dt = datetime(2026, 5, 8, 11, 33, 25, tzinfo=UTC)
    assert format_utc(dt) == "2026-05-08T11:33:25Z"


def test_format_utc_keeps_microseconds() -> None:
    dt = datetime(2026, 5, 8, 11, 33, 25, 123456, tzinfo=UTC)
    assert format_utc(dt) == "2026-05-08T11:33:25.123456Z"


def test_format_utc_does_not_contain_plus_offset() -> None:
    dt = datetime.now(UTC)
    result = format_utc(dt)
    assert "+00:00" not in result
    assert result.endswith("Z")


def test_format_utc_rejects_naive_datetime() -> None:
    """naive datetime은 UTC 보장이 불가능하므로 reject."""
    naive = datetime(2026, 5, 8, 11, 33, 25)
    with pytest.raises(ValueError):
        format_utc(naive)


def test_format_utc_rejects_non_utc_timezone() -> None:
    """다른 timezone offset은 reject (helper 이름이 ``format_utc``)."""
    kst = timezone(timedelta(hours=9))
    dt = datetime(2026, 5, 8, 20, 33, 25, tzinfo=kst)
    with pytest.raises(ValueError):
        format_utc(dt)


# ── iso_to_kis_date (#2412) ────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("iso", "expected"),
    [
        ("2026-07-01", "20260701"),
        ("2026-01-01", "20260101"),
        ("2026-12-31", "20261231"),
        ("2024-02-29", "20240229"),  # 윤년
    ],
)
def test_iso_to_kis_date_converts(iso: str, expected: str) -> None:
    """ISO ``YYYY-MM-DD`` → 압축 ``YYYYMMDD``."""
    assert iso_to_kis_date(iso) == expected


def test_iso_to_kis_date_none_passthrough() -> None:
    """``None``(옵션 미지정)은 그대로 통과 — 어댑터 기본값 산출에 위임."""
    assert iso_to_kis_date(None) is None


@pytest.mark.parametrize(
    "bad",
    [
        "20260701",  # 이미 압축형 — 표면 어휘 이중화 차단
        "2026-7-1",  # non-zero-padded
        "2026-13-01",  # 존재하지 않는 달
        "2026-02-30",  # 존재하지 않는 날
        "2026-02-29",  # 평년 2/29
        "2026/07/01",  # 잘못된 구분자
        "2026-07-01 ",  # trailing whitespace
        " 2026-07-01",
        "not-a-date",
        "",
    ],
)
def test_iso_to_kis_date_rejects_invalid(bad: str) -> None:
    """invalid 입력은 ``InvalidIsoDateError``(``VALIDATION_ERROR``)로 fail-closed."""
    with pytest.raises(InvalidIsoDateError) as exc_info:
        iso_to_kis_date(bad)
    assert exc_info.value.code == "VALIDATION_ERROR"


def test_invalid_iso_date_error_is_value_error() -> None:
    """``ValueError`` 하위 — 기존 ``except ValueError`` 소비자 호환."""
    assert issubclass(InvalidIsoDateError, ValueError)


def test_invalid_iso_date_error_taxonomy_registered() -> None:
    """error taxonomy registry entry lock — category 가 ``validation``.

    class-level ``.code`` 만으로도 안정 코드는 surface 되지만, helper 의
    bare-``.code`` 경로는 category 를 ``internal`` 로 wrap 한다. registry
    entry 가 빠지면 validation 성격이 taxonomy 에서 조용히 소실된다.
    """
    from ante.contracts.helpers import error_spec_for_exception

    spec = error_spec_for_exception(InvalidIsoDateError("x"))
    assert spec.code == "VALIDATION_ERROR"
    assert spec.category == "validation"
    assert spec.exit_code == 1


def test_iso_to_kis_date_output_has_no_separator() -> None:
    """🔴 출력에 ``-`` 가 남으면 어댑터의 사전순 경계 비교가 조용히 어긋난다.

    ``'2026-07-01' >= '20260311'`` 은 ``'-'``(0x2D) < ``'3'``(0x33) 이라
    무조건 False 다 — 3개월 이내 구간인데도 before 분기를 오선택하고
    malformed 값이 KIS 로 전송되지만 예외도 경고도 없다.
    """
    converted = iso_to_kis_date("2026-07-01")
    assert converted is not None
    assert "-" not in converted
    assert len(converted) == 8
    assert converted.isdigit()
    # 사전순 비교가 의도대로 동작함을 직접 확인.
    assert converted >= "20260311"
