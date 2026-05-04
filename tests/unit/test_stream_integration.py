"""StreamIntegration 단위 테스트."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ante.eventbus.bus import EventBus
from ante.eventbus.events import (
    BotStartedEvent,
    BotStoppedEvent,
    OrderFilledEvent,
    StreamConnectedEvent,
    StreamDisconnectedEvent,
)
from ante.gateway.cache import ResponseCache
from ante.gateway.stop_order import StopOrderManager
from ante.gateway.stream_integration import StreamIntegration

# ── Fixtures ──────────────────────────────────────


class FakeStreamClient:
    """테스트용 KISStreamClient 대체."""

    def __init__(self) -> None:
        self._connected = False
        self._subscribed: set[str] = set()
        self._price_callbacks: list = []
        self._execution_callbacks: list = []

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def subscribed_symbols(self) -> set[str]:
        return set(self._subscribed)

    def on_price(self, callback: Any) -> None:
        self._price_callbacks.append(callback)

    def on_execution(self, callback: Any) -> None:
        self._execution_callbacks.append(callback)

    async def connect(self) -> None:
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False
        self._subscribed.clear()

    async def subscribe(self, symbol: str) -> bool:
        self._subscribed.add(symbol)
        return True

    async def unsubscribe(self, symbol: str) -> None:
        self._subscribed.discard(symbol)

    async def subscribe_execution(self) -> None:
        pass

    async def fire_price(self, symbol: str, price: float) -> None:
        """테스트에서 시세 콜백 수동 호출."""
        for cb in self._price_callbacks:
            await cb(symbol, price)

    async def fire_execution(self, execution: dict) -> None:
        """테스트에서 체결 콜백 수동 호출."""
        for cb in self._execution_callbacks:
            await cb(execution)


@pytest.fixture
def eventbus() -> EventBus:
    return EventBus()


@pytest.fixture
def cache() -> ResponseCache:
    return ResponseCache()


@pytest.fixture
def stop_order_manager(eventbus: EventBus) -> StopOrderManager:
    mgr = StopOrderManager(eventbus=eventbus)
    mgr.start()
    return mgr


@pytest.fixture
def stream_client() -> FakeStreamClient:
    return FakeStreamClient()


@pytest.fixture
def gateway_mock() -> MagicMock:
    gw = MagicMock()
    gw.get_current_price = AsyncMock(return_value=50000.0)
    return gw


@pytest.fixture
def bot_manager_mock() -> MagicMock:
    bm = MagicMock()
    bm.list_bots.return_value = []
    bm.get_bot.return_value = None
    return bm


@pytest.fixture
def integration(
    stream_client: FakeStreamClient,
    cache: ResponseCache,
    eventbus: EventBus,
    stop_order_manager: StopOrderManager,
    gateway_mock: MagicMock,
    bot_manager_mock: MagicMock,
) -> StreamIntegration:
    return StreamIntegration(
        stream_client=stream_client,
        cache=cache,
        eventbus=eventbus,
        account_id="acc-001",
        stop_order_manager=stop_order_manager,
        gateway=gateway_mock,
        bot_manager=bot_manager_mock,
        fallback_poll_interval=0.1,
        sync_interval=0.1,
    )


# ── 시세 콜백 테스트 ──────────────────────────────


@pytest.mark.asyncio
async def test_price_callback_updates_cache(
    integration: StreamIntegration,
    stream_client: FakeStreamClient,
    cache: ResponseCache,
) -> None:
    """시세 수신 시 ResponseCache에 가격이 적재된다."""
    await integration.start()
    try:
        await stream_client.fire_price("005930", 72000.0)

        cached = cache.get("acc-001:price:005930")
        assert cached == 72000.0
    finally:
        await integration.stop()


@pytest.mark.asyncio
async def test_price_callback_calls_stop_order_manager(
    integration: StreamIntegration,
    stream_client: FakeStreamClient,
    stop_order_manager: StopOrderManager,
    eventbus: EventBus,
) -> None:
    """시세 수신 시 StopOrderManager.on_price_update가 호출된다.

    SPLIT-3 (#1242): StreamIntegration 의 account_id 와 StopOrder 의
    account_id 가 일치할 때만 trigger 된다.
    """
    await integration.start()
    try:
        # 스탑 주문 등록 — integration._account_id="acc-001" 와 동일하게 설정
        await stop_order_manager.register(
            order_id="ord-1",
            bot_id="bot-1",
            strategy_id="stg-1",
            symbol="005930",
            side="buy",
            quantity=10.0,
            order_type="stop",
            stop_price=72000.0,
            account_id="acc-001",
        )

        # 세션 시간을 항상 True로 패치 (테스트 시간에 무관하게 동작)
        with patch.object(StopOrderManager, "_is_in_session", return_value=True):
            # 시세 수신 — 트리거 조건 미충족
            await stream_client.fire_price("005930", 71000.0)
            assert len(stop_order_manager.active_orders) == 1

            # 시세 수신 — 트리거 조건 충족
            await stream_client.fire_price("005930", 72000.0)
            assert len(stop_order_manager.active_orders) == 0
    finally:
        await integration.stop()


# ── 체결 콜백 테스트 ──────────────────────────────


@pytest.mark.asyncio
async def test_execution_callback_invalidates_cache(
    integration: StreamIntegration,
    stream_client: FakeStreamClient,
    cache: ResponseCache,
) -> None:
    """체결 통보 시 balance, positions, 해당 종목 시세 캐시가 무효화된다."""
    await integration.start()
    try:
        # 캐시 사전 적재 (account_id 기반 네임스페이스)
        cache.set("acc-001:balance", {"total": 1000000}, ttl=30)
        cache.set("acc-001:positions", [{"symbol": "005930"}], ttl=30)
        cache.set("acc-001:price:005930", 70000.0, ttl=5)

        execution = {
            "symbol": "005930",
            "order_id": "ord-1",
            "side": "buy",
            "quantity": 10.0,
            "price": 70000.0,
        }
        await stream_client.fire_execution(execution)

        assert cache.get("acc-001:balance") is None
        assert cache.get("acc-001:positions") is None
        assert cache.get("acc-001:price:005930") is None
    finally:
        await integration.stop()


@pytest.mark.asyncio
async def test_execution_callback_publishes_event(
    integration: StreamIntegration,
    stream_client: FakeStreamClient,
    eventbus: EventBus,
) -> None:
    """체결 통보 시 OrderFilledEvent가 발행된다."""
    await integration.start()
    try:
        received: list[OrderFilledEvent] = []

        async def handler(event: OrderFilledEvent) -> None:
            received.append(event)

        eventbus.subscribe(OrderFilledEvent, handler)

        execution = {
            "symbol": "005930",
            "order_id": "ord-1",
            "side": "buy",
            "quantity": 10.0,
            "price": 70000.0,
        }
        await stream_client.fire_execution(execution)

        assert len(received) == 1
        assert received[0].symbol == "005930"
        assert received[0].price == 70000.0
    finally:
        await integration.stop()


# ── 스트림 연결/해제 + 폴백 테스트 ──────────────────


@pytest.mark.asyncio
async def test_fallback_starts_on_stream_disconnect(
    integration: StreamIntegration,
    eventbus: EventBus,
) -> None:
    """스트림 연결 해제 시 REST 폴링 폴백이 시작된다."""
    await integration.start()
    try:
        assert not integration.is_fallback_active

        await eventbus.publish(
            StreamDisconnectedEvent(account_id="acc-001", broker="kis", reason="test")
        )
        # 이벤트 처리 후 폴백 태스크 생성 대기
        await asyncio.sleep(0.05)

        assert integration.is_fallback_active
    finally:
        await integration.stop()


@pytest.mark.asyncio
async def test_fallback_stops_on_stream_reconnect(
    integration: StreamIntegration,
    eventbus: EventBus,
) -> None:
    """스트림 재연결 시 REST 폴링 폴백이 중지된다."""
    await integration.start()
    try:
        # 먼저 폴백 시작
        await eventbus.publish(
            StreamDisconnectedEvent(account_id="acc-001", broker="kis", reason="test")
        )
        await asyncio.sleep(0.05)
        assert integration.is_fallback_active

        # 재연결 시 폴백 중지
        await eventbus.publish(
            StreamConnectedEvent(account_id="acc-001", broker="kis", url="ws://test")
        )
        await asyncio.sleep(0.05)

        assert not integration.is_fallback_active
    finally:
        await integration.stop()


@pytest.mark.asyncio
async def test_fallback_polls_prices(
    integration: StreamIntegration,
    eventbus: EventBus,
    gateway_mock: MagicMock,
    cache: ResponseCache,
    stop_order_manager: StopOrderManager,
) -> None:
    """REST 폴링 폴백 시 모니터링 종목의 시세를 REST로 조회한다."""
    # 스탑 주문 등록 (모니터링 종목 생성)
    # SPLIT-3 (#1242): integration._account_id="acc-001" 와 동일하게 설정해야
    # cross-account isolation 게이트 통과.
    await stop_order_manager.register(
        order_id="ord-1",
        bot_id="bot-1",
        strategy_id="stg-1",
        symbol="005930",
        side="sell",
        quantity=10.0,
        order_type="stop",
        stop_price=60000.0,
        account_id="acc-001",
    )

    await integration.start()
    try:
        # 스트림 해제 → 폴백 시작
        await eventbus.publish(
            StreamDisconnectedEvent(account_id="acc-001", broker="kis", reason="test")
        )
        await asyncio.sleep(0.3)

        # REST API가 호출되었는지 확인
        gateway_mock.get_current_price.assert_called()
        call_args = [
            call.args[0] for call in gateway_mock.get_current_price.call_args_list
        ]
        assert "005930" in call_args

        # 캐시에 가격 적재 확인 (account_id 기반 네임스페이스)
        cached = cache.get("acc-001:price:005930")
        assert cached == 50000.0
    finally:
        await integration.stop()


# ── 종목 구독 동기화 테스트 ──────────────────────────


@pytest.mark.asyncio
async def test_subscription_sync_adds_stop_order_symbols(
    integration: StreamIntegration,
    stream_client: FakeStreamClient,
    stop_order_manager: StopOrderManager,
    eventbus: EventBus,
) -> None:
    """StopOrderManager 종목이 스트림에 구독된다.

    SPLIT-3 (#1242): integration._account_id="acc-001" 와 동일한 account_id
    의 stop order 만 모니터링 대상에 포함된다.
    """
    await stop_order_manager.register(
        order_id="ord-1",
        bot_id="bot-1",
        strategy_id="stg-1",
        symbol="035720",
        side="buy",
        quantity=5.0,
        order_type="stop",
        stop_price=100000.0,
        account_id="acc-001",
    )

    await integration.start()
    try:
        # 동기화 주기 대기
        await asyncio.sleep(0.2)

        assert "035720" in stream_client.subscribed_symbols
    finally:
        await integration.stop()


@pytest.mark.asyncio
async def test_subscription_sync_on_bot_event(
    integration: StreamIntegration,
    stream_client: FakeStreamClient,
    eventbus: EventBus,
    bot_manager_mock: MagicMock,
) -> None:
    """봇 시작/종료 이벤트 시 종목 구독이 즉시 동기화된다.

    SPLIT-3 (#1242): bot.config.account_id 가 integration._account_id 와
    동일한 봇만 모니터링 대상에 포함된다.
    """
    # 봇이 모니터링 종목을 가지도록 설정 — integration._account_id="acc-001" 와 동일
    mock_bot = MagicMock()
    mock_bot.monitored_symbols = {"005930", "035720"}
    mock_bot.config.account_id = "acc-001"
    bot_manager_mock.list_bots.return_value = [{"bot_id": "bot-1", "status": "running"}]
    bot_manager_mock.get_bot.return_value = mock_bot

    await integration.start()
    try:
        # 봇 시작 이벤트 발행
        await eventbus.publish(BotStartedEvent(bot_id="bot-1", account_id="acc-001"))
        await asyncio.sleep(0.05)

        assert "005930" in stream_client.subscribed_symbols
        assert "035720" in stream_client.subscribed_symbols
    finally:
        await integration.stop()


@pytest.mark.asyncio
async def test_subscription_sync_removes_symbols(
    integration: StreamIntegration,
    stream_client: FakeStreamClient,
    eventbus: EventBus,
    bot_manager_mock: MagicMock,
) -> None:
    """봇 종료 후 해당 종목이 스트림에서 구독 해제된다."""
    # 먼저 봇이 있는 상태
    mock_bot = MagicMock()
    mock_bot.monitored_symbols = {"005930"}
    mock_bot.config.account_id = "acc-001"
    bot_manager_mock.list_bots.return_value = [{"bot_id": "bot-1", "status": "running"}]
    bot_manager_mock.get_bot.return_value = mock_bot

    await integration.start()
    try:
        await eventbus.publish(BotStartedEvent(bot_id="bot-1", account_id="acc-001"))
        await asyncio.sleep(0.05)
        assert "005930" in stream_client.subscribed_symbols

        # 봇이 없어진 상태로 변경
        bot_manager_mock.list_bots.return_value = []
        bot_manager_mock.get_bot.return_value = None

        await eventbus.publish(BotStoppedEvent(bot_id="bot-1", account_id="acc-001"))
        await asyncio.sleep(0.05)

        assert "005930" not in stream_client.subscribed_symbols
    finally:
        await integration.stop()


# ── 시작/종료 라이프사이클 테스트 ──────────────────────


@pytest.mark.asyncio
async def test_start_connects_stream(
    integration: StreamIntegration,
    stream_client: FakeStreamClient,
) -> None:
    """start 시 스트림 클라이언트가 연결된다."""
    assert not stream_client.is_connected

    await integration.start()
    try:
        assert stream_client.is_connected
    finally:
        await integration.stop()


@pytest.mark.asyncio
async def test_stop_disconnects_stream(
    integration: StreamIntegration,
    stream_client: FakeStreamClient,
) -> None:
    """stop 시 스트림 클라이언트가 해제된다."""
    await integration.start()
    assert stream_client.is_connected

    await integration.stop()
    assert not stream_client.is_connected


@pytest.mark.asyncio
async def test_double_start_is_idempotent(
    integration: StreamIntegration,
    stream_client: FakeStreamClient,
) -> None:
    """중복 start 호출은 무해하다."""
    await integration.start()
    try:
        await integration.start()  # 두 번째 호출 — 에러 없이 무시
        assert stream_client.is_connected
    finally:
        await integration.stop()


@pytest.mark.asyncio
async def test_stop_without_start_is_safe(
    integration: StreamIntegration,
) -> None:
    """start 없이 stop 호출은 안전하다."""
    await integration.stop()  # 에러 없이 완료


@pytest.mark.asyncio
async def test_fallback_not_started_without_gateway(
    stream_client: FakeStreamClient,
    cache: ResponseCache,
    eventbus: EventBus,
) -> None:
    """APIGateway 없이 생성된 경우 폴백이 시작되지 않는다."""
    integration = StreamIntegration(
        stream_client=stream_client,
        cache=cache,
        eventbus=eventbus,
        account_id="acc-001",
        gateway=None,
    )
    await integration.start()
    try:
        await eventbus.publish(
            StreamDisconnectedEvent(account_id="acc-001", broker="kis", reason="test")
        )
        await asyncio.sleep(0.05)

        assert not integration.is_fallback_active
    finally:
        await integration.stop()


# ── account_id 보강 / strict OrderFilledEvent 회귀 (#1240 review) ──


@pytest.mark.asyncio
async def test_construction_without_account_id_raises(
    stream_client: FakeStreamClient,
    cache: ResponseCache,
    eventbus: EventBus,
) -> None:
    """SPLIT-3 (#1242): StreamIntegration 은 account_id 가 required 이며,
    빈 문자열로 생성하려 하면 InvalidAccountIdError 가 raise 된다.

    SPLIT-1 의 ``test_execution_without_account_id_skips_event`` 는 lifecycle
    account_id 가 없는 상태로 인스턴스를 만들 수 있다는 가정에 의존했으나,
    SPLIT-3 에서 ctor 가 require_account_id 로 fallback 을 차단했다. broker
    payload 만 없을 때 lifecycle account_id 로 fallback 하는 흐름은
    ``test_execution_uses_lifecycle_account_id_when_payload_missing`` 가 검증
    한다.
    """
    from ante.account.errors import InvalidAccountIdError

    with pytest.raises(InvalidAccountIdError):
        StreamIntegration(
            stream_client=stream_client,
            cache=cache,
            eventbus=eventbus,
            account_id="",
        )


@pytest.mark.asyncio
async def test_execution_uses_lifecycle_account_id_when_payload_missing(
    integration: StreamIntegration,
    stream_client: FakeStreamClient,
    eventbus: EventBus,
) -> None:
    """broker payload에 account_id가 없으면 lifecycle account_id로 fallback
    하여 OrderFilledEvent가 정상 발행된다."""
    await integration.start()
    try:
        received: list[OrderFilledEvent] = []

        async def handler(event: OrderFilledEvent) -> None:
            received.append(event)

        eventbus.subscribe(OrderFilledEvent, handler)

        # broker payload에 account_id 없음 → integration._account_id="acc-001" 사용
        await stream_client.fire_execution(
            {
                "symbol": "005930",
                "order_id": "ord-1",
                "side": "buy",
                "quantity": 10.0,
                "price": 70000.0,
            }
        )

        assert len(received) == 1
        assert received[0].account_id == "acc-001"
        assert received[0].order_id == "ord-1"
    finally:
        await integration.stop()


@pytest.mark.asyncio
async def test_execution_payload_account_id_overrides_lifecycle(
    integration: StreamIntegration,
    stream_client: FakeStreamClient,
    eventbus: EventBus,
) -> None:
    """broker payload의 account_id가 lifecycle account_id를 오버라이드한다."""
    await integration.start()
    try:
        received: list[OrderFilledEvent] = []

        async def handler(event: OrderFilledEvent) -> None:
            received.append(event)

        eventbus.subscribe(OrderFilledEvent, handler)

        await stream_client.fire_execution(
            {
                "symbol": "005930",
                "order_id": "ord-2",
                "side": "buy",
                "quantity": 10.0,
                "price": 70000.0,
                "account_id": "acc-other",
            }
        )

        assert len(received) == 1
        assert received[0].account_id == "acc-other"
    finally:
        await integration.stop()


# ── multi_account_pool 회귀 (#1242 SPLIT-3) ────────────────────────


@pytest.mark.asyncio
async def test_multi_account_pool_disconnect_does_not_cross_fallback(
    cache: ResponseCache,
    eventbus: EventBus,
    stop_order_manager: StopOrderManager,
    bot_manager_mock: MagicMock,
    gateway_mock: MagicMock,
) -> None:
    """SPLIT-3 (#1242): multi-account StreamIntegration pool 에서 한 계좌의
    StreamDisconnectedEvent 가 다른 계좌의 fallback 을 켜지 않는다.
    """
    client_a = FakeStreamClient()
    client_b = FakeStreamClient()

    integration_a = StreamIntegration(
        stream_client=client_a,
        cache=cache,
        eventbus=eventbus,
        account_id="acc-a",
        stop_order_manager=stop_order_manager,
        gateway=gateway_mock,
        bot_manager=bot_manager_mock,
        fallback_poll_interval=0.1,
        sync_interval=0.1,
    )
    integration_b = StreamIntegration(
        stream_client=client_b,
        cache=cache,
        eventbus=eventbus,
        account_id="acc-b",
        stop_order_manager=stop_order_manager,
        gateway=gateway_mock,
        bot_manager=bot_manager_mock,
        fallback_poll_interval=0.1,
        sync_interval=0.1,
    )

    await integration_a.start()
    await integration_b.start()

    try:
        assert not integration_a.is_fallback_active
        assert not integration_b.is_fallback_active

        # acc-a 의 stream 만 disconnect 발생
        await eventbus.publish(
            StreamDisconnectedEvent(account_id="acc-a", broker="kis", reason="test")
        )
        await asyncio.sleep(0.05)

        # acc-a 만 fallback 활성, acc-b 는 영향 없음
        assert integration_a.is_fallback_active
        assert not integration_b.is_fallback_active

        # acc-a reconnect 시 acc-a 만 fallback 종료
        await eventbus.publish(
            StreamConnectedEvent(account_id="acc-a", broker="kis", url="ws://a")
        )
        await asyncio.sleep(0.05)

        assert not integration_a.is_fallback_active
        assert not integration_b.is_fallback_active
    finally:
        await integration_a.stop()
        await integration_b.stop()


@pytest.mark.asyncio
async def test_multi_account_pool_monitored_symbols_are_isolated(
    cache: ResponseCache,
    eventbus: EventBus,
    stop_order_manager: StopOrderManager,
    bot_manager_mock: MagicMock,
    gateway_mock: MagicMock,
) -> None:
    """SPLIT-3 (#1242): 각 StreamIntegration 은 자기 account 의 봇 +
    StopOrder 만 모니터링 종목으로 수집한다."""
    client_a = FakeStreamClient()
    client_b = FakeStreamClient()

    bot_a = MagicMock()
    bot_a.monitored_symbols = {"005930"}
    bot_a.config.account_id = "acc-a"
    bot_b = MagicMock()
    bot_b.monitored_symbols = {"000660"}
    bot_b.config.account_id = "acc-b"

    bot_manager_mock.list_bots.return_value = [
        {"bot_id": "bot-a", "status": "running"},
        {"bot_id": "bot-b", "status": "running"},
    ]
    bot_manager_mock.get_bot.side_effect = lambda bot_id: {
        "bot-a": bot_a,
        "bot-b": bot_b,
    }.get(bot_id)

    integration_a = StreamIntegration(
        stream_client=client_a,
        cache=cache,
        eventbus=eventbus,
        account_id="acc-a",
        stop_order_manager=stop_order_manager,
        gateway=gateway_mock,
        bot_manager=bot_manager_mock,
        fallback_poll_interval=0.1,
        sync_interval=0.1,
    )
    integration_b = StreamIntegration(
        stream_client=client_b,
        cache=cache,
        eventbus=eventbus,
        account_id="acc-b",
        stop_order_manager=stop_order_manager,
        gateway=gateway_mock,
        bot_manager=bot_manager_mock,
        fallback_poll_interval=0.1,
        sync_interval=0.1,
    )

    # 각 instance 가 자기 account 의 봇 종목만 수집해야 한다.
    symbols_a = integration_a._get_monitored_symbols()
    symbols_b = integration_b._get_monitored_symbols()

    assert symbols_a == {"005930"}
    assert symbols_b == {"000660"}
