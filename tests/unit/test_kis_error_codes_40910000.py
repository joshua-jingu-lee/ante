"""KIS error code 분류: ``40910000`` permanent 등록 검증 (#2361).

``40910000``("모의투자 주문이 불가한 계좌입니다" = 계좌 자격/모의 신청 상태
거절)은 KIS 모의투자 주문 응답에서 반환되는 numeric business code다. 계좌
자격/모의 신청 상태에 기인하므로 재시도해도 동일 결과가 반복되는 permanent
rejection이다(``40240000`` 모의투자 잔고내역 없음과 동류). 따라서
``PERMANENT_MSG_CODES``/``KIS_ERROR_MESSAGES``에 등록되어야 한다.

회귀(#2361): 미등록 상태에서는 unknown 기본값(retryable=True)으로 분류되어
주문당 최대 3회 무익 재시도가 발생한다(3세션 일관 관측, 조사 #2360).

분류 경로 정밀(#1951 미러): ``KISErrorClassifier.classify``는 ``error_code``가
아니라 ``APIError.retryable``을 본다. 따라서 (a) SSOT ``is_retryable_msg_code``가
False를 반환하고, (b) ``_handle_response``가 ``40910000`` 응답을
``APIError(retryable=False)``로 승격하며, 그 APIError를 ``classify``에 넣으면
``(retryable=False, record_cb_failure=False)``가 되는지를 검증한다.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from ante.broker.error_codes import (
    KIS_ERROR_MESSAGES,
    PERMANENT_MSG_CODES,
    get_error_message,
    is_retryable_msg_code,
)
from ante.broker.exceptions import APIError
from ante.broker.kis import KISAdapter, KISErrorClassifier


def test_is_retryable_msg_code_40910000_is_permanent() -> None:
    """40910000은 permanent로 분류되어 재시도 불가."""
    assert is_retryable_msg_code("40910000") is False


def test_40910000_in_permanent_msg_codes() -> None:
    """40910000은 PERMANENT_MSG_CODES set에 포함된다."""
    assert "40910000" in PERMANENT_MSG_CODES


def test_kis_error_messages_40910000_present() -> None:
    """40910000은 한글 메시지 매핑에 등록되어 있다."""
    assert "40910000" in KIS_ERROR_MESSAGES
    assert (
        get_error_message("40910000")
        == "모의투자 주문 불가 계좌 (모의 자격/신청 상태 확인 필요)"
    )


# ── _handle_response → classify 통합 (retry/CB 오염 차단) ──────────


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
        return self._text_body  # type: ignore[return-value]

    async def json(self) -> Any:
        if self._json_body is None:
            raise ValueError("no json body configured")
        return self._json_body


def _make_adapter() -> KISAdapter:
    """``_handle_response``만 단독 호출하기 위한 bare adapter."""
    return KISAdapter.__new__(KISAdapter)  # type: ignore[arg-type]


def _run(coro: Any) -> Any:
    return asyncio.get_event_loop().run_until_complete(coro)


def test_handle_response_http_200_40910000_promoted_to_non_retryable() -> None:
    """HTTP 200 + rt_cd!=0 + 40910000 → APIError(retryable=False).

    KIS 정상 경로(HTTP 200, rt_cd="1")에서 ``is_retryable_msg_code``가 False를
    반환하므로 APIError가 retryable=False로 승격된다.
    """
    adapter = _make_adapter()
    payload = {
        "rt_cd": "1",
        "msg_cd": "40910000",
        "msg1": "모의투자 주문이 불가한 계좌입니다.",
    }
    resp = _FakeResponse(status=200, text_body="", json_body=payload)

    with pytest.raises(APIError) as exc_info:
        _run(adapter._handle_response(resp))

    err = exc_info.value
    assert err.error_code == "40910000"
    assert err.retryable is False


def test_handle_response_http_500_40910000_overrides_http_retryable() -> None:
    """HTTP 500 + 40910000(permanent) → retryable=False.

    PERMANENT_MSG_CODES이므로 HTTP 500(retryable)이라도 retryable=False가
    강제되고 status_code는 500으로 보존된다.
    """
    adapter = _make_adapter()
    body = json.dumps(
        {
            "rt_cd": "1",
            "msg_cd": "40910000",
            "msg1": "모의투자 주문이 불가한 계좌입니다.",
        }
    )
    resp = _FakeResponse(status=500, text_body=body)

    with pytest.raises(APIError) as exc_info:
        _run(adapter._handle_response(resp))

    err = exc_info.value
    assert err.error_code == "40910000"
    assert err.status_code == 500
    assert err.retryable is False


def test_classify_40910000_no_retry_no_cb_failure() -> None:
    """40910000 응답으로 승격된 APIError는 retry/CB 오염을 일으키지 않는다.

    ``classify``는 ``APIError.retryable``을 보므로, ``_handle_response``가
    retryable=False로 만든 APIError를 넣으면 ``(False, False)``가 되어야 한다.
    """
    adapter = _make_adapter()
    payload = {
        "rt_cd": "1",
        "msg_cd": "40910000",
        "msg1": "모의투자 주문이 불가한 계좌입니다.",
    }
    resp = _FakeResponse(status=200, text_body="", json_body=payload)

    with pytest.raises(APIError) as exc_info:
        _run(adapter._handle_response(resp))

    retryable, record_cb_failure = KISErrorClassifier.classify(exc_info.value)
    assert retryable is False
    assert record_cb_failure is False
