"""KIS 국내주식 order-cash TR ID 매핑 회귀 테스트 (#2342).

``KISDomesticAdapter.place_order`` 가 KIS 공식 현행 order-cash TR ID 를
``is_paper`` × ``side`` 4조합으로 정확히 전송하는지 검증한다.

공식 현행 매핑(KIS open-trading-api examples_llm + Developers 포털 2축 검증):
    - 모의(paper) 매수: VTTC0012U / 모의 매도: VTTC0011U
    - 실전(live)  매수: TTTC0012U / 실전 매도: TTTC0011U

구버전(deprecated) order-cash TR ID(VTTC0802U/TTTC0802U/VTTC0801U/TTTC0311U)
가 더 이상 전송되지 않음을 회귀 lock 한다.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from ante.broker.kis import KISDomesticAdapter

# 구버전(deprecated) order-cash TR ID — 회귀 lock 대상.
_DEPRECATED_ORDER_TR_IDS = frozenset(
    {"VTTC0802U", "TTTC0802U", "VTTC0801U", "TTTC0311U"}
)


def _make_adapter(*, is_paper: bool) -> KISDomesticAdapter:
    """네트워크 없이 place_order TR ID 선택만 검증하기 위한 어댑터."""
    config = {
        "app_key": "test-key",
        "app_secret": "test-secret",
        "account_no": "1234567890",
        "is_paper": is_paper,
    }
    return KISDomesticAdapter(config=config)


@pytest.mark.parametrize(
    ("is_paper", "side", "expected_tr_id"),
    [
        (True, "buy", "VTTC0012U"),
        (True, "sell", "VTTC0011U"),
        (False, "buy", "TTTC0012U"),
        (False, "sell", "TTTC0011U"),
    ],
)
async def test_place_order_sends_official_order_cash_tr_id(
    is_paper: bool, side: str, expected_tr_id: str
) -> None:
    """place_order 가 is_paper × side 별 공식 현행 order-cash TR ID 를 전송한다."""
    adapter = _make_adapter(is_paper=is_paper)
    adapter._ensure_authenticated = AsyncMock()  # type: ignore[method-assign]
    adapter._rate_limit_wait = AsyncMock()  # type: ignore[method-assign]
    request = AsyncMock(return_value={"output": {"ODNO": "123"}})
    adapter._request = request  # type: ignore[method-assign]

    order_id = await adapter.place_order("005930", side, 10, "market")

    assert order_id == "123"
    # _request(method, url, tr_id, ...) — tr_id 는 3번째 positional 인자.
    sent_tr_id = request.call_args.args[2]
    assert sent_tr_id == expected_tr_id
    # 회귀 lock: 구버전 order-cash TR ID 가 전송되지 않음.
    assert sent_tr_id not in _DEPRECATED_ORDER_TR_IDS
