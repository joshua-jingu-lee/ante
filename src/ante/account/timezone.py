"""Account timezone IANA 검증 헬퍼.

SSOT: Python ``zoneinfo.ZoneInfo`` / IANA timezone database.

이 모듈은 ``Account.timezone`` 입력이 유효한 IANA timezone key인지 확인하는
경량 헬퍼만 제공한다. stdlib ``zoneinfo``만 의존하여 :mod:`ante.account.service`
의 crypto/errors/models/presets/scoping 의존성과 격리한다 (#1473).

caller 책임:

- 빈 문자열/None 처리(default 의미 보존 등)는 caller가 결정한다. 본 헬퍼는
  주어진 비어 있지 않은 문자열의 IANA 유효성만 판정한다.

검증 실패 의미론:

- :exc:`zoneinfo.ZoneInfoNotFoundError` 는 ``ValueError`` 로 변환한다 — Pydantic
  ``field_validator`` 가 ``ValidationError`` 로 wrap 해 HTTP 422 로 매핑하고,
  :class:`ante.account.service.AccountService` 의 defense-in-depth 가드는
  ``ValueError`` 그대로 propagate 하여 비-HTTP caller(CLI/IPC) 에서도 동일
  거부 의미론을 갖는다.

Tolerant load (#1474):

- :func:`is_valid_iana_timezone` 은 invalid 여부를 raise 없이 bool 로 판정한다.
  ``_row_to_account`` 가 legacy DB row 의 invalid timezone(예: ``Mars/Olympus``)
  을 만났을 때 warning log 를 남기고 fallback timezone 으로 대체할 때 사용한다.
- caller(:class:`ante.account.service.AccountService`) 는 invalid 감지 시
  fallback (``DEFAULT_FALLBACK_TIMEZONE`` = ``Asia/Seoul``) 으로 대체하고
  ``Account.timezone_invalid=True`` 플래그를 세팅한다. row 자체는 그대로
  남겨두어 ``ante account repair-timezone`` 으로 명시적으로 복구해야 한다.

Non-goals:

- :class:`ante.account.models.Account` ``__post_init__`` hard 검증은 적용하지
  않는다(legacy DB row load 호환 보존 — #1474 별도 이슈).
- :class:`ante.rule.global_rules.TradingHoursRule` 의 runtime invalid timezone
  처리는 #1475 별도 이슈 범위다.
"""

from __future__ import annotations

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# Tolerant load fallback timezone (#1474).
#
# legacy DB row 가 invalid IANA timezone 으로 저장되어 있을 때 ``_row_to_account``
# 가 사용한다. ``Asia/Seoul`` 은 ``Account.timezone`` 의 dataclass default 와
# ``BROKER_PRESETS["test"].timezone`` 의 default 와 동일하므로 fallback 으로
# 대체했을 때 다른 모듈(TradingHoursRule 등)에서 발생하는 second-order failure
# 를 최소화한다.
DEFAULT_FALLBACK_TIMEZONE = "Asia/Seoul"


def validate_iana_timezone(value: str) -> str:
    """``value`` 가 유효한 IANA timezone key 이면 그대로 반환, 아니면 ValueError.

    :class:`zoneinfo.ZoneInfo` 인스턴스화로 IANA timezone database 등록 여부를
    검증한다. 빈 문자열/None 처리는 caller 가 책임진다 — 본 헬퍼는 caller 의
    default 의미 보존을 가로채지 않기 위해 ``ZoneInfo`` 위임 결과를 그대로
    수용한다 (``""`` 는 ZoneInfo 내부의 path normalization 검사에서 ValueError
    로 거부된다).

    Args:
        value: 검증할 timezone 문자열 (예: ``"Asia/Seoul"``).

    Returns:
        검증을 통과한 동일한 ``value``.

    Raises:
        ValueError: ``ZoneInfo(value)`` 가 IANA 등록 누락
            (:exc:`ZoneInfoNotFoundError`) 또는 형식 위반 (:exc:`ValueError`,
            예: 빈 문자열, 절대 경로) 으로 실패한 경우. 둘 다 동일한
            ``invalid IANA timezone: {value!r}`` 메시지로 wrap 한다 — Pydantic
            ``field_validator`` / service boundary 의 caller 가 일관된 메시지로
            422 또는 propagate 한다.
    """
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"invalid IANA timezone: {value!r}") from exc
    return value


def is_valid_iana_timezone(value: str) -> bool:
    """``value`` 가 유효한 IANA timezone key 인지 raise 없이 bool 로 판정한다.

    :func:`validate_iana_timezone` 와 동일한 :class:`zoneinfo.ZoneInfo` 위임을
    사용하지만 예외를 swallow 한다. ``_row_to_account`` 가 legacy DB row 의
    invalid timezone 을 만났을 때 warning log + fallback 대체 분기를 평가하기
    위해 사용된다 (#1474).

    빈 문자열 / 절대 경로 등 :exc:`ValueError` 도 invalid 로 본다 — 즉
    "ZoneInfo 가 받아들이는 값" 과 동치다.

    Args:
        value: 판정할 timezone 문자열.

    Returns:
        ``ZoneInfo(value)`` 가 예외 없이 성공하면 ``True``, 그렇지 않으면
        ``False``.
    """
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError):
        return False
    return True


__all__ = [
    "DEFAULT_FALLBACK_TIMEZONE",
    "is_valid_iana_timezone",
    "validate_iana_timezone",
]
