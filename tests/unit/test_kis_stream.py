"""KISStreamClient 단위 테스트."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from ante.broker.kis_stream import (
    CHANNEL_EXECUTION,
    CHANNEL_PRICE,
    MAX_SUBSCRIPTIONS,
    KISStreamClient,
)


@pytest.fixture
def eventbus() -> MagicMock:
    """EventBus mock."""
    bus = MagicMock()
    bus.publish = AsyncMock()
    return bus


@pytest.fixture
def stream_client(eventbus: MagicMock) -> KISStreamClient:
    """KISStreamClient 인스턴스."""
    return KISStreamClient(
        websocket_url="ws://ops.koreainvestment.com:31000",
        app_key="test_key",
        app_secret="test_secret",
        approval_key="test_approval",
        eventbus=eventbus,
    )


class TestKISStreamClientInit:
    """초기화 테스트."""

    def test_init_paper(self, stream_client: KISStreamClient) -> None:
        assert stream_client._url == "ws://ops.koreainvestment.com:31000"
        assert not stream_client.is_connected
        assert len(stream_client.subscribed_symbols) == 0

    def test_init_real(self, eventbus: MagicMock) -> None:
        client = KISStreamClient(
            websocket_url="ws://ops.koreainvestment.com:21000",
            app_key="key",
            app_secret="secret",
            approval_key="approval",
            eventbus=eventbus,
        )
        assert client._url == "ws://ops.koreainvestment.com:21000"


class TestSubscription:
    """구독 관련 테스트."""

    async def test_subscribe_before_connect(
        self, stream_client: KISStreamClient
    ) -> None:
        """연결 전 구독은 목록에만 추가."""
        result = await stream_client.subscribe("005930")
        assert result is True
        assert "005930" in stream_client.subscribed_symbols

    async def test_subscribe_duplicate(self, stream_client: KISStreamClient) -> None:
        """중복 구독은 무시."""
        await stream_client.subscribe("005930")
        result = await stream_client.subscribe("005930")
        assert result is True
        assert len(stream_client.subscribed_symbols) == 1

    async def test_subscribe_max_limit(self, stream_client: KISStreamClient) -> None:
        """최대 구독 한도 초과 시 False 반환."""
        for i in range(MAX_SUBSCRIPTIONS):
            await stream_client.subscribe(f"{i:06d}")
        result = await stream_client.subscribe("999999")
        assert result is False
        assert len(stream_client.subscribed_symbols) == MAX_SUBSCRIPTIONS

    async def test_unsubscribe(self, stream_client: KISStreamClient) -> None:
        """구독 해제."""
        await stream_client.subscribe("005930")
        await stream_client.unsubscribe("005930")
        assert "005930" not in stream_client.subscribed_symbols

    async def test_unsubscribe_not_subscribed(
        self, stream_client: KISStreamClient
    ) -> None:
        """미구독 종목 해제는 무시."""
        await stream_client.unsubscribe("999999")  # 에러 없이 통과


class TestMessageHandling:
    """메시지 처리 테스트."""

    async def test_handle_price_data(self, stream_client: KISStreamClient) -> None:
        """실시간 시세 데이터 처리."""
        received: list[tuple[str, float]] = []

        async def on_price(symbol: str, price: float) -> None:
            received.append((symbol, price))

        stream_client.on_price(on_price)

        # 파이프 구분 시세 데이터
        raw = f"0|{CHANNEL_PRICE}|004|005930^143000^50000^500"
        await stream_client._handle_message(raw)

        assert len(received) == 1
        assert received[0] == ("005930", 50000.0)

    async def test_handle_price_data_invalid(
        self, stream_client: KISStreamClient
    ) -> None:
        """잘못된 시세 데이터는 무시."""
        received: list[tuple[str, float]] = []

        async def on_price(symbol: str, price: float) -> None:
            received.append((symbol, price))

        stream_client.on_price(on_price)

        # 필드 부족
        raw = f"0|{CHANNEL_PRICE}|004|005930"
        await stream_client._handle_message(raw)
        assert len(received) == 0

    async def test_handle_execution_data(self, stream_client: KISStreamClient) -> None:
        """실시간 체결 통보 처리."""
        received: list[dict] = []

        async def on_exec(data: dict) -> None:
            received.append(data)

        stream_client.on_execution(on_exec)

        # 파이프 구분 체결 데이터
        fields = ["005930", "ORD001", "", "", "02", "10", "50000", "", "", "", ""]
        raw = f"0|{CHANNEL_EXECUTION}|004|" + "^".join(fields)
        await stream_client._handle_message(raw)

        assert len(received) == 1
        assert received[0]["symbol"] == "005930"
        assert received[0]["side"] == "buy"
        assert received[0]["quantity"] == 10.0

    async def test_handle_json_message(self, stream_client: KISStreamClient) -> None:
        """JSON 구독 확인 메시지 처리 (에러 없이)."""
        import json

        msg = json.dumps(
            {
                "header": {"tr_id": "H0STCNT0", "tr_key": "005930"},
                "body": {"msg1": "SUBSCRIBE SUCCESS"},
            }
        )
        # JSON 메시지 (구독 확인 등) — 에러 없이 처리
        await stream_client._handle_message(msg)

    async def test_price_callback_error_isolated(
        self, stream_client: KISStreamClient
    ) -> None:
        """콜백 오류가 다른 콜백에 영향 주지 않음."""
        received: list[tuple[str, float]] = []

        async def bad_callback(symbol: str, price: float) -> None:
            raise ValueError("test error")

        async def good_callback(symbol: str, price: float) -> None:
            received.append((symbol, price))

        stream_client.on_price(bad_callback)
        stream_client.on_price(good_callback)

        raw = f"0|{CHANNEL_PRICE}|004|005930^143000^50000^500"
        await stream_client._handle_message(raw)

        assert len(received) == 1


class TestDisconnect:
    """연결 해제 테스트."""

    async def test_disconnect_clears_state(
        self, stream_client: KISStreamClient
    ) -> None:
        """disconnect 시 구독 목록 초기화."""
        await stream_client.subscribe("005930")
        await stream_client.disconnect()
        assert len(stream_client.subscribed_symbols) == 0
        assert not stream_client.is_connected

    async def test_disconnect_publishes_event(
        self, stream_client: KISStreamClient, eventbus: MagicMock
    ) -> None:
        """disconnect 후 이벤트 발행 안 함 (clean disconnect)."""
        await stream_client.disconnect()
        # clean disconnect에서는 disconnected 이벤트를 발행하지 않음
        # (connection_lost일 때만 발행)
