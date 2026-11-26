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


class TestRegistryWebSocketURL:
    """레지스트리의 모든 어댑터가 스트림 조립 조건을 websocket_url로 낸다 (#2804)."""

    def test_registry_adapters_expose_websocket_url_by_kis_lineage(self) -> None:
        """KISBaseAdapter 하위는 모의 :31000·실전 :21000, 나머지는 None이다."""
        from ante.broker.kis import KISBaseAdapter
        from ante.broker.registry import BROKER_REGISTRY

        kis_classes = 0
        for broker_type, cls in BROKER_REGISTRY.items():
            if issubclass(cls, KISBaseAdapter):
                kis_classes += 1
                paper = cls({**_BASE_CONFIG, "is_paper": True})
                live = cls({**_BASE_CONFIG, "is_paper": False})
                assert paper.websocket_url == "ws://ops.koreainvestment.com:31000"
                assert live.websocket_url == "ws://ops.koreainvestment.com:21000"
            else:
                assert cls.websocket_url is None, broker_type
                assert cls({}).websocket_url is None, broker_type
        assert kis_classes >= 1
        assert len(BROKER_REGISTRY) > kis_classes
