"""UTC ISO 8601 직렬화 / 압축 날짜 변환 helper."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta, timezone


def format_utc(dt: datetime) -> str:
    """UTC ``datetime``을 ISO 8601 + ``Z`` suffix 문자열로 직렬화한다.

    Args:
        dt: tzinfo가 UTC인 ``datetime``. naive 또는 다른 timezone은 reject한다.

    Raises:
        ValueError: ``dt``가 naive이거나 UTC가 아닌 경우.
    """
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) != UTC.utcoffset(dt):
        msg = (
            "format_utc는 UTC tzinfo가 명시된 datetime만 받는다. "
            f"got tzinfo={dt.tzinfo!r}"
        )
        raise ValueError(msg)
    return dt.isoformat().replace("+00:00", "Z")


class InvalidIsoDateError(ValueError):
    """ISO ``YYYY-MM-DD`` 형식/캘린더 위반.

    ``code`` class attribute 로 안정 코드를 보유한다. IPC server 의
    ``ipc_error_payload`` 와 CLI 진입점 훅이 이 값을 그대로 surface 하므로,
    invalid 날짜가 ``EXECUTION_ERROR`` 로 접히지 않는다.
    코드 값은 SSOT(``InvalidAccountIdError.code``)와 동일한
    ``VALIDATION_ERROR`` 를 재사용하며 신규 코드를 도입하지 않는다.
    """

    code = "VALIDATION_ERROR"


_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def iso_to_kis_date(value: str | None) -> str | None:
    """공개 표면 ISO ``YYYY-MM-DD`` → broker 경계 압축 ``YYYYMMDD``.

    Raises:
        InvalidIsoDateError: regex mismatch 또는 존재하지 않는 캘린더 날짜.
            이미 ``YYYYMMDD`` 인 값(``"20260701"``)도 거부한다 — 공개 표면의
            날짜 어휘는 ISO 단일이며, 압축형 우회 입력을 통과시키면 표면
            어휘가 조용히 이중화된다.
    """
    if value is None:
        return None
    if not isinstance(value, str) or not _ISO_DATE_RE.fullmatch(value):
        msg = f"{value!r}은(는) YYYY-MM-DD 형식이어야 합니다 (zero-padded)."
        raise InvalidIsoDateError(msg)
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        msg = f"{value!r}은(는) 유효한 달력 날짜가 아닙니다."
        raise InvalidIsoDateError(msg) from exc
    return value.replace("-", "")


_KST = timezone(timedelta(hours=9))


def default_order_history_range(now: datetime) -> tuple[date, date]:
    """``now``의 KST 날짜 기준 주문 이력 기본 구간 ``(오늘 - 7일, 오늘)``.

    시계를 읽지 않는다. ``now``는 tz-aware여야 하며 naive이면 ``ValueError``.
    """
    if now.tzinfo is None or now.tzinfo.utcoffset(now) is None:
        msg = f"default_order_history_range는 tz-aware datetime만 받는다. got {now!r}"
        raise ValueError(msg)
    today = now.astimezone(_KST).date()
    return today - timedelta(days=7), today


__all__ = [
    "InvalidIsoDateError",
    "default_order_history_range",
    "format_utc",
    "iso_to_kis_date",
]
