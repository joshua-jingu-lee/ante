"""Account timezone IANA 검증 헬퍼."""

from __future__ import annotations

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def validate_iana_timezone(value: str) -> str:
    """``value`` 가 유효한 IANA timezone key 이면 그대로 반환, 아니면 ValueError.

    :class:`zoneinfo.ZoneInfo` 인스턴스화로 IANA timezone database 등록 여부를
    검증한다. 빈 문자열/None 처리는 caller 가 책임진다 — 본 헬퍼는 caller 의
    default 의미 보존을 가로채지 않기 위해 ``ZoneInfo`` 위임 결과를 그대로
    수용한다 (``""`` 는 ZoneInfo 내부의 path normalization 검사에서 ValueError
    로 거부된다).
    """
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"invalid IANA timezone: {value!r}") from exc
    return value


__all__ = ["validate_iana_timezone"]
