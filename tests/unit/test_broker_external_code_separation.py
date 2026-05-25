"""Broker 원천 external code (KIS ``msg_cd``) log-only 분리 round-trip lock.

#1843 sub-PR 5 Codex Plan Review v1 condition — broker ``APIError`` 가
보존하는 원천 외부 broker code (KIS ``msg_cd``, 예: ``APBK0501``) 는
**log/디버깅 보조** 채널에만 보존되며, public envelope (CLI ``OutputFormatter.
error`` / IPC envelope ``{code, message}``) 의 ``code`` 필드에는 ante
taxonomy 의 안정 코드 ``BROKER_API_ERROR`` 만 노출된다.

본 모듈이 lock 하는 contract:

- ``APIError(msg, status_code=..., error_code="<msg_cd>")`` 인스턴스의
  ``.error_code`` 필드 보존 — log/EventBus 직접 소비자가 원천 코드를 사용
  가능해야 한다.
- 동일 인스턴스를 ``ipc_error_payload`` 로 직렬화한 결과의 ``code`` 는
  ``BROKER_API_ERROR`` 만 노출 — 원천 ``msg_cd`` 가 envelope 상위 필드로
  새지 않는다.
- helper ``error_spec_for_exception`` 도 ``BROKER_API_ERROR`` 안정 코드
  만 resolve — 원천 ``msg_cd`` 가 helper 경로로 외부에 노출되지 않는다.

envelope SSOT 갱신 필요한 ``details.broker_code`` 필드 도입은 본 PR 범위
밖이며, 후속 spec PR 이 책임진다. 본 모듈은 그 추가 도입 시점까지 원천
``msg_cd`` 가 envelope 의 어떤 top-level 필드로도 누출되지 않음을 lock
한다 (negative contract).

NOTE: ``APIError`` 의 ``str(exc)`` (즉 envelope ``message`` 필드 후보) 는
실측 KIS error format ``"KIS API Error [{msg_cd}]: {msg1}"`` 을 그대로
포함할 수 있다 — 이는 사용자/로그 표시용 자연어 메시지이며 구조화된
원천 코드 surface 가 아니다. 본 round-trip lock 은 envelope 의 구조화된
``code`` 필드만을 단언한다.
"""

from __future__ import annotations

from ante.broker.exceptions import APIError
from ante.contracts import error_spec_for_exception, ipc_error_payload

# ── (1) APIError 인스턴스가 원천 ``msg_cd`` 를 내부 필드로 보존한다 ──────────


def test_api_error_preserves_origin_msg_cd_internally() -> None:
    """``APIError.error_code`` 필드는 KIS 원천 ``msg_cd`` 를 그대로 보존한다.

    이 필드는 log message / EventBus ``OrderFailedEvent.error_code`` payload
    같은 내부 소비자가 디버깅/감사용으로 사용한다. public envelope 으로는
    이후 단언처럼 노출되지 않는다.
    """

    exc = APIError(
        "KIS API Error [APBK0501]: 주문 가능 금액 부족",
        status_code=400,
        error_code="APBK0501",
        retryable=False,
    )

    assert exc.error_code == "APBK0501"
    assert exc.status_code == 400
    assert exc.retryable is False


# ── (2) Public envelope 는 ante taxonomy 안정 코드만 노출한다 ────────────────


def test_api_error_envelope_exposes_only_public_code() -> None:
    """``ipc_error_payload(APIError(...))`` 는 ``BROKER_API_ERROR`` 만 노출.

    envelope 의 top-level 필드는 ``{"code", "message"}`` 두 개로 고정되어
    있다 (#1820 envelope SSOT). ``code`` 는 ante taxonomy 안정 코드여야 하며,
    원천 KIS ``msg_cd`` (``APBK0501``) 가 ``code`` 필드로 새는 것을 금지한다.

    ``details.broker_code`` 같은 별도 구조화 필드는 envelope SSOT 갱신
    이후 후속 spec PR 에서 도입한다 (Codex Plan Review v1 condition) —
    본 round-trip lock 은 그 도입 이전까지 envelope top-level 어디에도
    원천 ``msg_cd`` 가 노출되지 않음을 단언한다.
    """

    exc = APIError(
        "KIS API Error [APBK0501]: 주문 가능 금액 부족",
        status_code=400,
        error_code="APBK0501",
    )

    payload = ipc_error_payload(exc)

    # 구조화 envelope 의 ``code`` 는 안정 ante 코드 — 원천 msg_cd 아님.
    assert payload["code"] == "BROKER_API_ERROR"
    assert payload["code"] != "APBK0501"

    # ``message`` 는 사용자/로그 표시용 자연어 메시지 — 본 round-trip 은
    # 구조화 필드만 단언한다 (str 메시지에 KIS 표기가 포함되는 것은 의도).
    assert isinstance(payload["message"], str)

    # envelope 은 top-level 에 추가 구조화 필드를 갖지 않는다 (현재 SSOT 기준).
    # ``details.broker_code`` 등 후속 spec 도입 전까지 다른 키가 새지 않음.
    assert set(payload.keys()) == {"code", "message"}


def test_api_error_helper_resolves_only_public_spec() -> None:
    """``error_spec_for_exception(APIError(...))`` 도 안정 코드만 resolve.

    helper 경로의 ``ErrorSpec`` 도 동일하게 ``BROKER_API_ERROR`` /
    ``external`` 만 노출한다. 원천 ``msg_cd`` 가 helper 의 ``ErrorSpec.code``
    필드로 새는 것을 금지한다.
    """

    exc = APIError(
        "KIS API Error [APBK0501]: 주문 가능 금액 부족",
        status_code=400,
        error_code="APBK0501",
    )

    spec = error_spec_for_exception(exc)

    assert spec.code == "BROKER_API_ERROR"
    assert spec.category == "external"
    assert spec.code != "APBK0501"


# ── (3) ``.error_code`` 빈 문자열 default 도 envelope 에 새지 않는다 ─────────


def test_api_error_without_origin_code_envelope_stable() -> None:
    """원천 코드 미설정 (예: 네트워크 timeout wrap APIError) 시에도 envelope
    은 안정 ``BROKER_API_ERROR`` 만 노출 — ``""`` 가 ``code`` 로 새지 않는다.
    """

    exc = APIError("타임아웃 (5초 초과)", retryable=True)

    assert exc.error_code == ""

    payload = ipc_error_payload(exc)

    assert payload["code"] == "BROKER_API_ERROR"
    assert payload["code"] != ""


# ── (4) ``APIError`` 와 분리된 typed exception 도 원천 코드와 무관 ───────────


def test_api_error_origin_code_does_not_leak_to_other_typed_exceptions() -> None:
    """``APIError`` 인스턴스의 원천 ``msg_cd`` 는 같은 typed 패밀리 다른
    인스턴스로 leak 되지 않는다 — instance state 격리 sanity check.

    (회귀 시연: 이전 helper 가 class-level state 로 원천 코드를 캐싱하면
    instance 간 leak 가능. helper 는 instance attribute 만 본다.)
    """

    exc_a = APIError(
        "KIS API Error [APBK0501]: 주문 가능 금액 부족",
        error_code="APBK0501",
    )
    exc_b = APIError(
        "KIS API Error [APBK0502]: 종목 코드 오류",
        error_code="APBK0502",
    )

    # 인스턴스 별 원천 코드 격리.
    assert exc_a.error_code == "APBK0501"
    assert exc_b.error_code == "APBK0502"

    # envelope 은 둘 다 동일 안정 코드만 노출.
    assert ipc_error_payload(exc_a)["code"] == "BROKER_API_ERROR"
    assert ipc_error_payload(exc_b)["code"] == "BROKER_API_ERROR"
