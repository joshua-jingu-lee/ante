"""KIS adapter ``_handle_response`` business error 승격 검증 (#1338).

KIS API가 HTTP 5xx + body에 ``rt_cd`` / ``msg_cd``를 포함해 응답하는
경우, ante broker layer는 이를 broker business error로 승격해
``APIError.error_code``에 ``msg_cd``를 보존해야 한다. 그렇지 않으면
``OrderCancelFailedEvent.error_message``가 ``HTTP 500: {...}`` 문자열로만
노출되어 downstream order action 처리와 리포팅이 generic HTTP failure로
오분류된다 (oracle A7 회귀).

retryable 우선순위 (Codex Plan Review v2):
    1. ``msg_cd`` ∈ ``PERMANENT_MSG_CODES`` → ``False`` 강제.
    2. HTTP non-retryable (401/403/404/422 등) → ``False`` 강제.
    3. ``msg_cd`` ∈ ``TRANSIENT_MSG_CODES`` → ``True``.
    4. 그 외 unknown msg_cd는 HTTP retryable에 따른다.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from ante.broker.exceptions import APIError
from ante.broker.kis import KISAdapter


class _FakeResponse:
    """``aiohttp.ClientResponse`` 호환 minimal mock.

    ``_handle_response``는 ``response.status``와
    ``await response.text()`` / ``await response.json()``만 사용한다.
    """

    def __init__(
        self,
        status: int,
        text_body: str | bytes | None = "",
        json_body: Any = None,
    ) -> None:
        self.status = status
        self._text_body = text_body
        self._json_body = json_body

    async def text(self) -> str | bytes:
        # aiohttp는 통상 str을 반환하지만 일부 mock 환경에서 bytes가
        # 흘러올 수 있다. ``_handle_response``는 둘 다 안전 처리해야 한다.
        return self._text_body  # type: ignore[return-value]

    async def json(self) -> Any:
        if self._json_body is None:
            raise ValueError("no json body configured")
        return self._json_body


def _make_adapter() -> KISAdapter:
    """``_handle_response``만 단독으로 호출하기 위한 bare adapter.

    ``__new__``로 ``__init__`` 부수효과(세션 생성 등)를 우회한다.
    """
    return KISAdapter.__new__(KISAdapter)  # type: ignore[arg-type]


def _run(coro: Any) -> Any:
    return asyncio.get_event_loop().run_until_complete(coro)


# ── HTTP 500 + KIS business payload ───────────────────────────────


def test_handle_response_http_500_with_kis_business_error_preserves_msg_cd() -> None:
    """HTTP 500 + IGW00022 → APIError(error_code=IGW00022, retryable=False).

    PERMANENT_MSG_CODES이므로 HTTP retryable이라도 retryable=False가 강제되며,
    ``status_code``는 500으로 보존된다.
    """
    adapter = _make_adapter()
    body = json.dumps(
        {
            "rt_cd": "1",
            "msg_cd": "IGW00022",
            "msg1": "원주문번호 오류",
        }
    )
    resp = _FakeResponse(status=500, text_body=body)

    with pytest.raises(APIError) as exc_info:
        _run(adapter._handle_response(resp))

    err = exc_info.value
    assert err.error_code == "IGW00022"
    assert err.status_code == 500
    assert err.retryable is False
    assert "IGW00022" in str(err)
    assert "원주문번호 오류" in str(err)


def test_handle_response_http_500_with_unknown_msg_cd_inherits_http_retryable() -> None:
    """HTTP 500 + unknown msg_cd → retryable=True (HTTP 500이 retryable).

    PERMANENT/TRANSIENT 어느 쪽에도 등록되지 않은 코드는 HTTP 기준을 따른다.
    """
    adapter = _make_adapter()
    body = json.dumps(
        {
            "rt_cd": "1",
            "msg_cd": "XYZ99999",  # unknown
            "msg1": "Mystery error",
        }
    )
    resp = _FakeResponse(status=500, text_body=body)

    with pytest.raises(APIError) as exc_info:
        _run(adapter._handle_response(resp))

    err = exc_info.value
    assert err.error_code == "XYZ99999"
    assert err.status_code == 500
    assert err.retryable is True


def test_handle_response_http_401_with_transient_msg_cd_overrides_to_false() -> None:
    """HTTP 401 + APBK0600 (transient) → retryable=False.

    HTTP non-retryable(auth/client error)이 transient msg_cd를 override한다.
    """
    adapter = _make_adapter()
    body = json.dumps(
        {
            "rt_cd": "1",
            "msg_cd": "APBK0600",
            "msg1": "서버 과부하",
        }
    )
    resp = _FakeResponse(status=401, text_body=body)

    with pytest.raises(APIError) as exc_info:
        _run(adapter._handle_response(resp))

    err = exc_info.value
    assert err.error_code == "APBK0600"
    assert err.status_code == 401
    assert err.retryable is False


def test_handle_response_http_500_with_transient_msg_cd_retryable() -> None:
    """HTTP 500 + APBK0600 (transient) → retryable=True."""
    adapter = _make_adapter()
    body = json.dumps(
        {
            "rt_cd": "1",
            "msg_cd": "APBK0600",
            "msg1": "서버 과부하",
        }
    )
    resp = _FakeResponse(status=500, text_body=body)

    with pytest.raises(APIError) as exc_info:
        _run(adapter._handle_response(resp))

    err = exc_info.value
    assert err.error_code == "APBK0600"
    assert err.status_code == 500
    assert err.retryable is True


def test_handle_response_http_500_with_permanent_msg_cd_overrides_http() -> None:
    """HTTP 500 + APBK0013 (permanent) → retryable=False.

    PERMANENT가 HTTP retryable을 override해야 한다.
    """
    adapter = _make_adapter()
    body = json.dumps(
        {
            "rt_cd": "1",
            "msg_cd": "APBK0013",
            "msg1": "잘못된 종목코드",
        }
    )
    resp = _FakeResponse(status=500, text_body=body)

    with pytest.raises(APIError) as exc_info:
        _run(adapter._handle_response(resp))

    err = exc_info.value
    assert err.error_code == "APBK0013"
    assert err.status_code == 500
    assert err.retryable is False


# ── HTTP 500 + non-KIS body → generic fallback ────────────────────


def test_handle_response_http_500_without_json_body_falls_back_to_generic() -> None:
    """HTTP 500 + plain text body → generic APIError, retryable=True."""
    adapter = _make_adapter()
    resp = _FakeResponse(status=500, text_body="Internal Server Error")

    with pytest.raises(APIError) as exc_info:
        _run(adapter._handle_response(resp))

    err = exc_info.value
    assert err.error_code == ""  # business code 미보존
    assert err.status_code == 500
    assert err.retryable is True
    assert "HTTP 500" in str(err)


def test_handle_response_http_500_with_invalid_json_falls_back() -> None:
    """HTTP 500 + invalid JSON → generic fallback."""
    adapter = _make_adapter()
    resp = _FakeResponse(status=500, text_body='{"rt_cd": "1", "msg_cd"')  # truncated

    with pytest.raises(APIError) as exc_info:
        _run(adapter._handle_response(resp))

    err = exc_info.value
    assert err.error_code == ""
    assert err.status_code == 500
    assert err.retryable is True
    assert "HTTP 500" in str(err)


def test_handle_response_http_500_with_empty_body_falls_back() -> None:
    """HTTP 500 + empty body → generic fallback."""
    adapter = _make_adapter()
    resp = _FakeResponse(status=500, text_body="")

    with pytest.raises(APIError) as exc_info:
        _run(adapter._handle_response(resp))

    err = exc_info.value
    assert err.error_code == ""
    assert err.status_code == 500
    assert err.retryable is True


def test_handle_response_http_500_with_bytes_body_decoded() -> None:
    """HTTP 500 + bytes body → utf-8 decode 후 KIS payload 정상 인식."""
    adapter = _make_adapter()
    body_bytes = json.dumps(
        {
            "rt_cd": "1",
            "msg_cd": "IGW00022",
            "msg1": "원주문번호 오류",
        }
    ).encode("utf-8")
    resp = _FakeResponse(status=500, text_body=body_bytes)

    with pytest.raises(APIError) as exc_info:
        _run(adapter._handle_response(resp))

    err = exc_info.value
    assert err.error_code == "IGW00022"
    assert err.status_code == 500
    assert err.retryable is False


def test_handle_response_http_500_with_rt_cd_zero_falls_back() -> None:
    """HTTP 500 + rt_cd="0" → generic fallback.

    KIS는 success(rt_cd=0)인데 HTTP는 5xx인 비정상 케이스. business
    error로 승격하지 않는다.
    """
    adapter = _make_adapter()
    body = json.dumps({"rt_cd": "0", "msg_cd": "APBK1234", "msg1": "ok"})
    resp = _FakeResponse(status=500, text_body=body)

    with pytest.raises(APIError) as exc_info:
        _run(adapter._handle_response(resp))

    err = exc_info.value
    # rt_cd == "0"이면 KIS business error로 승격하지 않음
    assert err.error_code == ""
    assert err.status_code == 500
    assert err.retryable is True
    assert "HTTP 500" in str(err)


# ── HTTP 200 경로는 기존 동작 유지 ────────────────────────────────


def test_handle_response_http_200_with_rt_cd_nonzero_unchanged() -> None:
    """HTTP 200 + rt_cd != "0" → 기존 동작 유지 (status_code=0, error_code=msg_cd).

    이 경로는 #1338에서 변경하지 않는다.
    """
    adapter = _make_adapter()
    payload = {"rt_cd": "1", "msg_cd": "APBK0013", "msg1": "잘못된 종목코드"}
    resp = _FakeResponse(status=200, text_body="", json_body=payload)

    with pytest.raises(APIError) as exc_info:
        _run(adapter._handle_response(resp))

    err = exc_info.value
    assert err.error_code == "APBK0013"
    # 기존 경로는 status_code를 명시적으로 설정하지 않는다 (default 0).
    assert err.status_code == 0
    # APBK0013은 PERMANENT이므로 is_retryable_msg_code → False.
    assert err.retryable is False


def test_handle_response_http_200_success_returns_payload() -> None:
    """HTTP 200 + rt_cd="0" → 정상 payload 반환 (회귀 가드)."""
    adapter = _make_adapter()
    payload = {"rt_cd": "0", "output": {"foo": "bar"}}
    resp = _FakeResponse(status=200, text_body="", json_body=payload)

    result = _run(adapter._handle_response(resp))
    assert result == payload
