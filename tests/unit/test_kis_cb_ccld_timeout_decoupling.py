"""KIS CircuitBreaker 광역 결합 해소 회귀 테스트 (#2350).

late-ccld(``get_order_history``) 조회 타임아웃이 어댑터 전역 단일 차단기를 OPEN
시켜, 같은 어댑터를 공유하는 treasury 잔고/포지션 동기화·주문 경로까지 broker-wide
로 차단하던 cross-concern blast radius 를 끊는다(정책 (a): late-ccld TimeoutError
차단기 회계 제외 — 호출측 opt-out).

검증 축:
    (결합 재현→해소) get_order_history raw TimeoutError 6회(임계 5 초과) 누적 후에도
      차단기 CLOSED 유지 + get_account_balance/get_positions 정상 호출 가능.
    (주문 경로 보호 불변식) order-cash 타임아웃은 기존대로 record_failure 누적 →
      임계 도달 시 OPEN(무회귀).
    (회계 범위) ccld 경로의 비-Timeout 실패(retryable APIError/5xx)는 기존대로 기록.
"""

from __future__ import annotations

from typing import Any

import pytest

from ante.broker.circuit_breaker import CircuitState
from ante.broker.exceptions import APIError, CircuitOpenError
from ante.broker.kis import KISDomesticAdapter

_CONFIG = {
    "app_key": "test-key",
    "app_secret": "test-secret",
    "account_no": "1234567890",
    "is_paper": True,
    # 임계는 기본 5. 6회 누적이 임계 초과임을 명시하기 위해 기본값을 그대로 둔다.
}


def _make_adapter() -> KISDomesticAdapter:
    """네트워크/인증/rate-limit 없이 차단기 회계만 검증하는 어댑터.

    ``_send_http`` 만 주입해 tr_id/url 별 성공/타임아웃/에러를 제어한다. 실제
    ``_request_with_cont`` 의 차단기 check/record_success/record_failure 회계 경로는
    그대로 돈다(opt-out 판정 포함).
    """
    adapter = KISDomesticAdapter(config=dict(_CONFIG))

    async def _no_auth() -> None:
        return None

    async def _no_rate_limit() -> None:
        return None

    # 재시도 backoff 대기를 0 으로 만들어 테스트를 빠르게 수렴시킨다.
    adapter._ensure_authenticated = _no_auth  # type: ignore[method-assign]
    adapter._rate_limit_wait = _no_rate_limit  # type: ignore[method-assign]
    adapter._backoff_base = 0.0
    adapter._retry_handler._backoff_base = 0.0
    return adapter


def _balance_page() -> dict[str, Any]:
    """잔고/포지션 조회 정상 응답(1페이지, 다음 없음)."""
    return {
        "rt_cd": "0",
        "output1": [
            {
                "pdno": "005930",
                "hldg_qty": "10",
                "pchs_avg_pric": "70000",
                "prpr": "71000",
                "evlu_amt": "710000",
                "evlu_pfls_amt": "10000",
                "evlu_erng_rt": "1.4",
            }
        ],
        "output2": [
            {
                "dnca_tot_amt": "1000000",
                "tot_evlu_amt": "1710000",
            }
        ],
        "ctx_area_fk100": "",
        "ctx_area_nk100": "",
    }


def _order_ok_page() -> dict[str, Any]:
    return {
        "rt_cd": "0",
        "output": {"ODNO": "0000123456", "KRX_FWDG_ORD_ORGNO": "06010"},
    }


# ── 결합 재현 → 해소 (failing check) ─────────────────────────


async def test_ccld_timeout_does_not_open_cb_and_balance_positions_stay_callable() -> (
    None
):
    """late-ccld TimeoutError 6회(임계 초과) 후에도 차단기 CLOSED + 잔고/포지션 정상.

    수정 전(현행)에는 ccld 타임아웃이 record_failure 로 누적돼 임계 5에 도달, 차단기
    OPEN → get_account_balance/get_positions 가 CircuitOpenError 로 차단됐다(결합
    재현). #2350 opt-out 으로 ccld TimeoutError 가 회계에서 제외되면 차단기는 CLOSED
    를 유지하고 두 조회는 정상 호출된다.
    """
    adapter = _make_adapter()
    ccld_path = "inquire-daily-ccld"
    balance_path = "inquire-balance"

    async def fake_send_http(
        method: str,
        url: str,
        headers: dict[str, str],
        params: dict[str, str] | None,
        json_data: dict[str, Any] | None,
        timeout: float,
    ) -> tuple[dict[str, Any], str]:
        if ccld_path in url:
            # raw TimeoutError (to_api_error 변환 **전** 기준 — Codex R1 ③).
            raise TimeoutError("ccld 조회 타임아웃")
        if balance_path in url:
            return _balance_page(), "D"
        raise AssertionError(f"예상치 못한 url: {url}")

    adapter._send_http = fake_send_http  # type: ignore[method-assign]

    # get_order_history 6회 — 각 호출이 최초+재시도 2회=최대 3회 raw TimeoutError 를
    # 던지므로, 회계가 됐다면 누적 record_failure 가 임계 5를 한참 초과한다.
    for _ in range(6):
        with pytest.raises(APIError):
            await adapter.get_order_history(from_date="20260601", to_date="20260601")

    # opt-out 으로 ccld TimeoutError 는 회계에서 제외 — 차단기 CLOSED 유지.
    assert adapter.circuit_breaker.state == CircuitState.CLOSED
    assert adapter.circuit_breaker.failure_count == 0

    # 같은 어댑터의 무관 concern(treasury 잔고/포지션)은 차단되지 않고 정상 호출.
    balance = await adapter.get_account_balance()
    assert balance["cash"] == 1000000.0
    positions = await adapter.get_positions()
    assert positions[0]["symbol"] == "005930"
    assert positions[0]["quantity"] == 10.0


# ── 주문 경로 보호 불변식 (무회귀) ────────────────────────────


async def test_order_timeout_still_records_failure_and_opens_cb() -> None:
    """order-cash 타임아웃은 기존대로 record_failure 누적 → 임계 도달 시 OPEN.

    주문 경로는 기본값 cb_exempt_timeout=False 라 회계 무변경이다. 주문 타임아웃이
    반복되면 차단기가 OPEN 되어 연쇄 호출을 막는 본래 보호가 유지된다.
    """
    adapter = _make_adapter()

    async def fake_send_http(
        method: str,
        url: str,
        headers: dict[str, str],
        params: dict[str, str] | None,
        json_data: dict[str, Any] | None,
        timeout: float,
    ) -> tuple[dict[str, Any], str]:
        if "order-cash" in url:
            raise TimeoutError("주문 타임아웃")
        raise AssertionError(f"예상치 못한 url: {url}")

    adapter._send_http = fake_send_http  # type: ignore[method-assign]

    # 주문 1회 = 최초+재시도 3회 = 최대 4회 record_failure. 임계 5 에 도달하려면
    # 2회 주문이면 충분하다. OPEN 전환 후 check() 가 CircuitOpenError 를 던진다.
    opened = False
    for _ in range(3):
        try:
            await adapter.place_order("005930", "buy", 1.0)
        except CircuitOpenError:
            opened = True
            break
        except APIError:
            continue
    assert opened, "주문 타임아웃 누적으로 차단기가 OPEN 되어야 한다"
    assert adapter.circuit_breaker.state == CircuitState.OPEN


# ── 회계 범위: ccld 비-Timeout 실패는 기존대로 기록 ───────────────


async def test_ccld_non_timeout_retryable_failure_still_records() -> None:
    """ccld 경로의 비-Timeout 실패(retryable APIError/5xx)는 기존대로 회계에 기록.

    opt-out 은 TimeoutError 에 한정된다. retryable APIError(예: 5xx/server busy)는
    cb_exempt_timeout=True 여도 record_failure 가 누적돼 임계 도달 시 OPEN 된다
    (실제 KIS 서버 장애 보호 유지).
    """
    adapter = _make_adapter()

    async def fake_send_http(
        method: str,
        url: str,
        headers: dict[str, str],
        params: dict[str, str] | None,
        json_data: dict[str, Any] | None,
        timeout: float,
    ) -> tuple[dict[str, Any], str]:
        if "inquire-daily-ccld" in url:
            raise APIError("server busy", retryable=True, status_code=503)
        raise AssertionError(f"예상치 못한 url: {url}")

    adapter._send_http = fake_send_http  # type: ignore[method-assign]

    # ccld 1회 = 최초+재시도 2회 = 최대 3회 record_failure. 2회면 임계 5 도달.
    opened = False
    for _ in range(3):
        try:
            await adapter.get_order_history(from_date="20260601", to_date="20260601")
        except CircuitOpenError:
            opened = True
            break
        except APIError:
            continue
    assert opened, "ccld 비-Timeout retryable 실패는 회계에 기록되어 OPEN 되어야 한다"
    assert adapter.circuit_breaker.state == CircuitState.OPEN
