"""KIS WebSocket URL 포트 번호 검증 테스트.

모의투자는 31000, 실전투자는 21000 포트를 사용해야 한다.
Refs #942
"""

from __future__ import annotations

from ante.broker.kis import KISDomesticAdapter

_BASE_CONFIG = {
    "app_key": "test_key",
    "app_secret": "test_secret",
    "account_no": "12345678-01",
}


class TestKISWebSocketURL:
    """KISBaseAdapter WebSocket URL 포트 매핑 테스트."""

    def test_paper_websocket_url_uses_port_31000(self) -> None:
        """모의투자 WebSocket URL은 31000 포트를 사용한다."""
        adapter = KISDomesticAdapter({**_BASE_CONFIG, "is_paper": True})
        assert adapter.websocket_url == "ws://ops.koreainvestment.com:31000"

    def test_live_websocket_url_uses_port_21000(self) -> None:
        """실전투자 WebSocket URL은 21000 포트를 사용한다."""
        adapter = KISDomesticAdapter({**_BASE_CONFIG, "is_paper": False})
        assert adapter.websocket_url == "ws://ops.koreainvestment.com:21000"

    def test_default_is_paper_uses_port_31000(self) -> None:
        """is_paper 미지정 시 기본값(True)이므로 31000 포트를 사용한다."""
        adapter = KISDomesticAdapter({**_BASE_CONFIG})
        assert adapter.websocket_url == "ws://ops.koreainvestment.com:31000"
