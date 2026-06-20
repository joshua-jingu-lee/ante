"""StopOrderManager 단위 테스트."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch  # noqa: F811

import pytest

from ante.eventbus.events import (
    OrderRequestEvent,
    StopOrderExpiredEvent,
    StopOrderRegisteredEvent,
    StopOrderTriggeredEvent,
)
from ante.gateway.stop_order import StopOrderManager


@pytest.fixture
def eventbus() -> MagicMock:
    """EventBus mock."""
    bus = MagicMock()
    bus.publish = AsyncMock()
    return bus


@pytest.fixture
def manager(eventbus: MagicMock) -> StopOrderManager:
    """StopOrderManager 인스턴스."""
    return StopOrderManager(eventbus)


class TestRegister:
    """스탑 주문 등록 테스트."""

    async def test_register_stop_order(
        self, manager: StopOrderManager, eventbus: MagicMock
    ) -> None:
        """스탑 주문 등록."""
        manager.start()
        stop_id = await manager.register(
            order_id="ord-001",
            bot_id="bot-001",
            strategy_id="stg-001",
            symbol="005930",
            side="sell",
            quantity=10.0,
            order_type="stop",
            stop_price=49000.0,
            account_id="acc-test",
        )

        assert stop_id.startswith("stop-")
        assert len(manager.active_orders) == 1
        assert "005930" in manager.monitored_symbols

        # 이벤트 발행 확인
        eventbus.publish.assert_called_once()
        event = eventbus.publish.call_args[0][0]
        assert isinstance(event, StopOrderRegisteredEvent)
        assert event.stop_price == 49000.0

    async def test_register_stop_limit_order(
        self, manager: StopOrderManager, eventbus: MagicMock
    ) -> None:
        """스탑 리밋 주문 등록."""
        manager.start()
        stop_id = await manager.register(
            order_id="ord-002",
            bot_id="bot-001",
            strategy_id="stg-001",
            symbol="005930",
            side="buy",
            quantity=5.0,
            order_type="stop_limit",
            stop_price=51000.0,
            limit_price=51500.0,
            account_id="acc-test",
        )

        order = manager.get_order(stop_id)
        assert order is not None
        assert order.order_type == "stop_limit"
        assert order.limit_price == 51500.0


class TestTrigger:
    """트리거 판단 테스트."""

    @patch.object(StopOrderManager, "_is_in_session", return_value=True)
    async def test_sell_stop_triggered(
        self, _mock_session: MagicMock, manager: StopOrderManager, eventbus: MagicMock
    ) -> None:
        """매도 스탑: 현재가 <= stop_price 시 트리거."""
        manager.start()

        await manager.register(
            order_id="ord-001",
            bot_id="bot-001",
            strategy_id="stg-001",
            symbol="005930",
            side="sell",
            quantity=10.0,
            order_type="stop",
            stop_price=49000.0,
            account_id="acc-test",
        )

        eventbus.publish.reset_mock()

        # 가격이 stop_price 이하로 하락
        await manager.on_price_update("005930", 48500.0, account_id="acc-test")

        # StopOrderTriggeredEvent + OrderRequestEvent 발행
        assert eventbus.publish.call_count == 2

        triggered_event = eventbus.publish.call_args_list[0][0][0]
        assert isinstance(triggered_event, StopOrderTriggeredEvent)
        assert triggered_event.trigger_price == 48500.0
        assert triggered_event.converted_order_type == "market"

        order_event = eventbus.publish.call_args_list[1][0][0]
        assert isinstance(order_event, OrderRequestEvent)
        assert order_event.order_type == "market"
        assert order_event.side == "sell"

    @patch.object(StopOrderManager, "_is_in_session", return_value=True)
    async def test_buy_stop_triggered(
        self, _mock_session: MagicMock, manager: StopOrderManager, eventbus: MagicMock
    ) -> None:
        """매수 스탑: 현재가 >= stop_price 시 트리거."""
        manager.start()

        await manager.register(
            order_id="ord-002",
            bot_id="bot-001",
            strategy_id="stg-001",
            symbol="005930",
            side="buy",
            quantity=5.0,
            order_type="stop",
            stop_price=51000.0,
            account_id="acc-test",
        )

        eventbus.publish.reset_mock()
        await manager.on_price_update("005930", 51500.0, account_id="acc-test")

        assert eventbus.publish.call_count == 2
        triggered_event = eventbus.publish.call_args_list[0][0][0]
        assert isinstance(triggered_event, StopOrderTriggeredEvent)

    @patch.object(StopOrderManager, "_is_in_session", return_value=True)
    async def test_stop_limit_converts_to_limit(
        self, _mock_session: MagicMock, manager: StopOrderManager, eventbus: MagicMock
    ) -> None:
        """stop_limit → limit 변환."""
        manager.start()

        await manager.register(
            order_id="ord-003",
            bot_id="bot-001",
            strategy_id="stg-001",
            symbol="005930",
            side="buy",
            quantity=5.0,
            order_type="stop_limit",
            stop_price=51000.0,
            limit_price=51500.0,
            account_id="acc-test",
        )

        eventbus.publish.reset_mock()
        await manager.on_price_update("005930", 51000.0, account_id="acc-test")

        order_event = eventbus.publish.call_args_list[1][0][0]
        assert isinstance(order_event, OrderRequestEvent)
        assert order_event.order_type == "limit"
        assert order_event.price == 51500.0

    async def test_not_triggered_below_threshold(
        self, manager: StopOrderManager, eventbus: MagicMock
    ) -> None:
        """트리거 조건 미충족 시 주문 유지."""
        manager.start()

        await manager.register(
            order_id="ord-004",
            bot_id="bot-001",
            strategy_id="stg-001",
            symbol="005930",
            side="sell",
            quantity=10.0,
            order_type="stop",
            stop_price=49000.0,
            account_id="acc-test",
        )

        eventbus.publish.reset_mock()
        await manager.on_price_update(
            "005930", 50000.0, account_id="acc-test"
        )  # > stop_price

        # 트리거 안 됨
        assert eventbus.publish.call_count == 0
        assert len(manager.active_orders) == 1

    async def test_different_symbol_ignored(
        self, manager: StopOrderManager, eventbus: MagicMock
    ) -> None:
        """다른 종목 시세는 무시."""
        manager.start()

        await manager.register(
            order_id="ord-005",
            bot_id="bot-001",
            strategy_id="stg-001",
            symbol="005930",
            side="sell",
            quantity=10.0,
            order_type="stop",
            stop_price=49000.0,
            account_id="acc-test",
        )

        eventbus.publish.reset_mock()
        await manager.on_price_update("000660", 48000.0, account_id="acc-test")

        assert eventbus.publish.call_count == 0

    async def test_not_running_ignores_price(
        self, manager: StopOrderManager, eventbus: MagicMock
    ) -> None:
        """매니저 정지 상태(_running=False)에서 시세 무시.

        #2405 (attempt2 P2): register 는 stopped 상태에서 raise 하므로(silent
        loss 제거), 먼저 start→등록 후 _running 을 False 로 내려 on_price_update
        의 정지 가드를 검증한다.
        """
        manager.start()
        stop_id = await manager.register(
            order_id="ord-006",
            bot_id="bot-001",
            strategy_id="stg-001",
            symbol="005930",
            side="sell",
            quantity=10.0,
            order_type="stop",
            stop_price=49000.0,
            account_id="acc-test",
        )

        # 등록 후 정지 상태로 전환(stop() 은 만료 이벤트를 내므로 직접 플래그만 내림).
        manager._running = False
        eventbus.publish.reset_mock()
        await manager.on_price_update("005930", 48000.0, account_id="acc-test")

        # running=False이므로 무시(트리거·세션 멤버십 마킹 모두 없음)
        assert eventbus.publish.call_count == 0
        order = manager.get_order(stop_id)
        assert order is not None
        assert order.entered_session is False


class TestCancel:
    """스탑 주문 취소 테스트."""

    async def test_cancel_active_order(
        self, manager: StopOrderManager, eventbus: MagicMock
    ) -> None:
        """활성 주문 취소."""
        manager.start()
        stop_id = await manager.register(
            order_id="ord-001",
            bot_id="bot-001",
            strategy_id="stg-001",
            symbol="005930",
            side="sell",
            quantity=10.0,
            order_type="stop",
            stop_price=49000.0,
            account_id="acc-test",
        )

        result = manager.cancel(stop_id)
        assert result is True
        assert len(manager.active_orders) == 0

    async def test_cancel_nonexistent(self, manager: StopOrderManager) -> None:
        """존재하지 않는 주문 취소."""
        result = manager.cancel("stop-nonexistent")
        assert result is False


class TestExpiry:
    """세션 종료 만료 테스트."""

    async def test_stop_expires_all_on_stop(
        self, manager: StopOrderManager, eventbus: MagicMock
    ) -> None:
        """매니저 중지 시 모든 주문 만료."""
        manager.start()

        await manager.register(
            order_id="ord-001",
            bot_id="bot-001",
            strategy_id="stg-001",
            symbol="005930",
            side="sell",
            quantity=10.0,
            order_type="stop",
            stop_price=49000.0,
            account_id="acc-test",
        )

        eventbus.publish.reset_mock()
        await manager.stop()

        # StopOrderExpiredEvent 발행
        assert eventbus.publish.call_count == 1
        event = eventbus.publish.call_args[0][0]
        assert isinstance(event, StopOrderExpiredEvent)
        assert event.reason == "manager_stopped"


class TestSessionExpiryA2:
    """#2405 (A2): 자신의 세션에 진입했던 미트리거 주문만 session_ended 로 만료된다.

    #2405 (attempt3 P1/P2): 멤버십을 per-order ``StopOrder.entered_session`` 으로
    추적한다. ``on_price_update`` 가 틱의 종목·계좌와 **무관하게(market-wide)** 그
    시점 in-session 인 **모든** active 주문을 마킹하므로, 거래일에 한 종목이라도
    틱이 흐르면 그 세션의 무틱 종목까지 멤버십을 얻어 함께 만료된다. ``_expire_order``
    가 만료 주문을 ``active_orders`` 에서 소비하므로 별도 reset 이 없다. 휴장일
    (전종목 무틱)에는 어떤 주문도 마킹되지 않아 사전 등록분이 보존된다. 시간
    의존은 ``_is_session_type_active_now`` patch 로 결정화한다(``_is_in_session``
    이 이 헬퍼에 위임하므로 한 번의 patch 로 일관 제어).
    """

    async def test_entered_then_left_session_expires(
        self, manager: StopOrderManager, eventbus: MagicMock
    ) -> None:
        """거래일 정상: in-session 틱으로 멤버십을 얻은 뒤 세션 종료 시 만료된다."""
        manager.start()

        # 세션 안에서 등록 + in-session 틱 → order.entered_session=True.
        with patch.object(
            StopOrderManager, "_is_session_type_active_now", return_value=True
        ):
            stop_id = await manager.register(
                order_id="ord-in",
                bot_id="bot-001",
                strategy_id="stg-001",
                symbol="005930",
                side="sell",
                quantity=10.0,
                order_type="stop",
                stop_price=49000.0,
                account_id="acc-test",
            )

            order = manager.get_order(stop_id)
            assert order is not None
            # register 시점엔 세션 멤버십 미마킹.
            assert order.entered_session is False

            # in-session 틱(트리거 조건 미달 가격) → 세션 멤버십 마킹.
            eventbus.publish.reset_mock()
            await manager.on_price_update("005930", 50000.0, account_id="acc-test")
            assert order.entered_session is True
            # 트리거 조건 미달이라 이벤트 미발행.
            assert eventbus.publish.call_count == 0

        eventbus.publish.reset_mock()

        # 세션 종료 후 sweep → 멤버십이 있었으므로 만료.
        with patch.object(
            StopOrderManager, "_is_session_type_active_now", return_value=False
        ):
            await manager.check_session_expiry()

        assert eventbus.publish.call_count == 1
        event = eventbus.publish.call_args[0][0]
        assert isinstance(event, StopOrderExpiredEvent)
        assert event.reason == "session_ended"
        assert len(manager.active_orders) == 0

    async def test_never_entered_session_not_expired(
        self, manager: StopOrderManager, eventbus: MagicMock
    ) -> None:
        """세션 멤버십 없는(장 전 등록·무틱) 주문은 만료 안 됨(A1 회귀 방지)."""
        manager.start()

        # 세션 밖에서 등록, 틱 없음 → entered_session=False 유지.
        with patch.object(
            StopOrderManager, "_is_session_type_active_now", return_value=False
        ):
            stop_id = await manager.register(
                order_id="ord-pre",
                bot_id="bot-001",
                strategy_id="stg-001",
                symbol="005930",
                side="sell",
                quantity=10.0,
                order_type="stop",
                stop_price=49000.0,
                account_id="acc-test",
            )

            order = manager.get_order(stop_id)
            assert order is not None
            assert order.entered_session is False

            eventbus.publish.reset_mock()
            await manager.check_session_expiry()

        # 세션에 한 번도 진입 안 했으므로 만료 안 됨.
        assert eventbus.publish.call_count == 0
        assert len(manager.active_orders) == 1

    async def test_holiday_no_tick_pre_registered_not_expired(
        self, manager: StopOrderManager, eventbus: MagicMock
    ) -> None:
        """#2405 휴장일 안전: 무틱이면 사전 등록 stop 이 만료되지 않는다.

        시나리오: 사전 등록 후 ``on_price_update`` 를 **호출하지 않고**(무틱),
        out-of-session 시각이 아니라 **in-session 시각**(주말·공휴일의 '시장
        시간대')에 sweep 을 돌린다. 틱이 없었으므로 entered_session=False →
        sweep 비만료. (시각만으로 마킹하던 옛 설계라면 여기서 마킹돼 다음 세션
        종료에 오만료됐다 — 월요일 개장 전 사망.)
        """
        manager.start()

        with patch.object(
            StopOrderManager, "_is_session_type_active_now", return_value=False
        ):
            stop_id = await manager.register(
                order_id="ord-holiday",
                bot_id="bot-001",
                strategy_id="stg-001",
                symbol="005930",
                side="sell",
                quantity=10.0,
                order_type="stop",
                stop_price=49000.0,
                account_id="acc-test",
            )

        order = manager.get_order(stop_id)
        assert order is not None
        assert order.entered_session is False

        eventbus.publish.reset_mock()

        # 휴장일 '시장 시간대' sweep: 시각상 in-session 이지만 무틱 → 미마킹.
        with patch.object(
            StopOrderManager, "_is_session_type_active_now", return_value=True
        ):
            await manager.check_session_expiry()
        assert order.entered_session is False
        assert eventbus.publish.call_count == 0

        # 이후 '세션 종료' sweep 에서도 멤버십 없어 만료 안 됨.
        with patch.object(
            StopOrderManager, "_is_session_type_active_now", return_value=False
        ):
            await manager.check_session_expiry()
        assert eventbus.publish.call_count == 0
        assert len(manager.active_orders) == 1

    async def test_no_tick_symbol_expires_market_wide(
        self, manager: StopOrderManager, eventbus: MagicMock
    ) -> None:
        """#2405 핵심 회귀: 무틱 종목도 market-wide 마킹으로 만료된다.

        종목A 틱이 종목B(무틱) 포함 그 시점 in-session 전 active order 를
        마킹 → 세션 종료 시 **모두** 만료된다. (per-symbol 마킹이라면 종목B 가
        entered_session=False 로 남아 영구 미만료됐다 — 이 회귀 락.)
        """
        manager.start()

        with patch.object(
            StopOrderManager, "_is_session_type_active_now", return_value=True
        ):
            # 종목A — 틱이 들어올 종목.
            stop_a = await manager.register(
                order_id="ord-A",
                bot_id="bot-001",
                strategy_id="stg-001",
                symbol="005930",
                side="sell",
                quantity=10.0,
                order_type="stop",
                stop_price=49000.0,
                account_id="acc-test",
            )
            # 종목B — 세션 내내 무틱 종목.
            stop_b = await manager.register(
                order_id="ord-B",
                bot_id="bot-002",
                strategy_id="stg-002",
                symbol="000660",
                side="sell",
                quantity=5.0,
                order_type="stop",
                stop_price=100000.0,
                account_id="acc-test",
            )

            # 종목A 만 틱(트리거 미달 가격) → market-wide 멤버십 마킹.
            await manager.on_price_update("005930", 50000.0, account_id="acc-test")
            order_a = manager.get_order(stop_a)
            order_b = manager.get_order(stop_b)
            assert order_a is not None and order_b is not None
            # 무틱 종목B 도 market-wide 로 마킹됨.
            assert order_a.entered_session is True
            assert order_b.entered_session is True

        assert len(manager.active_orders) == 2
        eventbus.publish.reset_mock()

        # 세션 종료 sweep → 종목A·종목B 둘 다 만료(무틱 종목 포함).
        with patch.object(
            StopOrderManager, "_is_session_type_active_now", return_value=False
        ):
            await manager.check_session_expiry()

        assert len(manager.active_orders) == 0
        # 두 주문 모두 session_ended 로 만료 이벤트 발행.
        assert eventbus.publish.call_count == 2
        reasons = {call.args[0].reason for call in eventbus.publish.call_args_list}
        assert reasons == {"session_ended"}
        symbols = {call.args[0].symbol for call in eventbus.publish.call_args_list}
        assert symbols == {"005930", "000660"}

    async def test_boundary_race_partial_unexpired_then_next_sweep_expires(
        self, manager: StopOrderManager, eventbus: MagicMock
    ) -> None:
        """#2405 (attempt3 P1) 경계 race 회귀 락.

        sweep 시점 일부 주문이 아직 윈도우 안(``_is_in_session`` True)이라 한
        sweep 에서 미만료돼도, entered_session 은 유지되므로 이후 완전 세션 밖
        sweep 에서 만료된다(누락 없음). (manager-level reset 설계에서는 첫 sweep
        의 reset 이 플래그를 내려 다음 sweep 도 대상에서 제외 → 다음 거래일까지
        생존하는 결함이 있었다.)
        """
        manager.start()

        # in-session 등록 + 틱 → 두 주문 모두 entered_session=True.
        with patch.object(
            StopOrderManager, "_is_session_type_active_now", return_value=True
        ):
            stop_1 = await manager.register(
                order_id="ord-1",
                bot_id="bot-001",
                strategy_id="stg-001",
                symbol="005930",
                side="sell",
                quantity=10.0,
                order_type="stop",
                stop_price=49000.0,
                account_id="acc-test",
            )
            stop_2 = await manager.register(
                order_id="ord-2",
                bot_id="bot-002",
                strategy_id="stg-002",
                symbol="000660",
                side="sell",
                quantity=5.0,
                order_type="stop",
                stop_price=100000.0,
                account_id="acc-test",
            )
            await manager.on_price_update("005930", 50000.0, account_id="acc-test")
            order_1 = manager.get_order(stop_1)
            order_2 = manager.get_order(stop_2)
            assert order_1 is not None and order_2 is not None
            assert order_1.entered_session is True
            assert order_2.entered_session is True

        eventbus.publish.reset_mock()

        # 경계 sweep: 아직 윈도우 안이라 만료 없음(하지만 entered_session 유지).
        with patch.object(
            StopOrderManager, "_is_session_type_active_now", return_value=True
        ):
            await manager.check_session_expiry()
        assert eventbus.publish.call_count == 0
        assert len(manager.active_orders) == 2
        assert order_1.entered_session is True
        assert order_2.entered_session is True

        # 다음 sweep: 완전 세션 밖 → 두 주문 모두 만료(누락 없음).
        with patch.object(
            StopOrderManager, "_is_session_type_active_now", return_value=False
        ):
            await manager.check_session_expiry()
        assert len(manager.active_orders) == 0
        assert eventbus.publish.call_count == 2
        reasons = {call.args[0].reason for call in eventbus.publish.call_args_list}
        assert reasons == {"session_ended"}

    async def test_post_session_register_not_expired(
        self, manager: StopOrderManager, eventbus: MagicMock
    ) -> None:
        """#2405 (attempt3 P2) 종료후 등록 오만료 회귀 락.

        세션 중 다른 주문이 in-session 틱을 받아 entered_session=True 가 된
        상태에서, 세션 종료 후 **새 주문을 register** 한다. 새 주문은 세션 밖이라
        in-session 틱을 받지 못하므로 entered_session=False → check_session_expiry
        에서 만료되지 않는다(A2 사전등록 보존). (manager-level 플래그 설계에서는
        앞 주문이 _session_active[regular]=True 로 올려둔 상태라, 종료 직후 등록한
        주문이 진입한 적 없는데도 즉시 session_ended 로 오만료됐다.)
        """
        manager.start()

        # 세션 중: 주문1 등록 + 틱 → entered_session=True.
        with patch.object(
            StopOrderManager, "_is_session_type_active_now", return_value=True
        ):
            stop_existing = await manager.register(
                order_id="ord-existing",
                bot_id="bot-001",
                strategy_id="stg-001",
                symbol="005930",
                side="sell",
                quantity=10.0,
                order_type="stop",
                stop_price=49000.0,
                account_id="acc-test",
            )
            await manager.on_price_update("005930", 50000.0, account_id="acc-test")
            existing = manager.get_order(stop_existing)
            assert existing is not None
            assert existing.entered_session is True

        # 세션 종료 후: 새 주문2 등록(세션 밖, in-session 틱 못 받음).
        with patch.object(
            StopOrderManager, "_is_session_type_active_now", return_value=False
        ):
            stop_new = await manager.register(
                order_id="ord-new",
                bot_id="bot-002",
                strategy_id="stg-002",
                symbol="000660",
                side="sell",
                quantity=5.0,
                order_type="stop",
                stop_price=100000.0,
                account_id="acc-test",
            )
            new_order = manager.get_order(stop_new)
            assert new_order is not None
            assert new_order.entered_session is False

            # register 이벤트 발행 후 reset → check_session_expiry 만료만 관찰.
            eventbus.publish.reset_mock()
            await manager.check_session_expiry()

        # 주문1(멤버십 O)만 만료, 새 주문2(멤버십 X)는 보존.
        assert eventbus.publish.call_count == 1
        expired_event = eventbus.publish.call_args[0][0]
        assert isinstance(expired_event, StopOrderExpiredEvent)
        assert expired_event.reason == "session_ended"
        assert expired_event.symbol == "005930"
        remaining = manager.active_orders
        assert len(remaining) == 1
        assert remaining[0].order_id == "ord-new"

    async def test_session_reactivate_cycle(
        self, manager: StopOrderManager, eventbus: MagicMock
    ) -> None:
        """#2405: 1일차 만료 후 2일차 신규 주문도 첫 틱으로 멤버십을 얻어 재만료된다.

        per-order 멤버십은 reset 이 없어도 만료가 active_orders 소비로 닫히고,
        다음 거래일 신규 주문은 entered_session=False 로 시작해 그날 첫 틱에
        다시 마킹된다(재만료 사이클).
        """
        manager.start()

        # 1일차: 틱 마킹 → 세션 종료 만료.
        with patch.object(
            StopOrderManager, "_is_session_type_active_now", return_value=True
        ):
            await manager.register(
                order_id="ord-day1",
                bot_id="bot-001",
                strategy_id="stg-001",
                symbol="005930",
                side="sell",
                quantity=10.0,
                order_type="stop",
                stop_price=49000.0,
                account_id="acc-test",
            )
            await manager.on_price_update("005930", 50000.0, account_id="acc-test")

        with patch.object(
            StopOrderManager, "_is_session_type_active_now", return_value=False
        ):
            await manager.check_session_expiry()
        assert len(manager.active_orders) == 0

        # 2일차: 새 주문 등록 → 첫 틱이 다시 마킹 → 재만료.
        eventbus.publish.reset_mock()
        with patch.object(
            StopOrderManager, "_is_session_type_active_now", return_value=True
        ):
            stop_day2 = await manager.register(
                order_id="ord-day2",
                bot_id="bot-001",
                strategy_id="stg-001",
                symbol="005930",
                side="sell",
                quantity=10.0,
                order_type="stop",
                stop_price=49000.0,
                account_id="acc-test",
            )
            await manager.on_price_update("005930", 50000.0, account_id="acc-test")
            order_day2 = manager.get_order(stop_day2)
            assert order_day2 is not None
            assert order_day2.entered_session is True

        with patch.object(
            StopOrderManager, "_is_session_type_active_now", return_value=False
        ):
            await manager.check_session_expiry()
        # 2일차 주문도 만료.
        assert len(manager.active_orders) == 0

    async def test_sweep_in_session_does_not_expire(
        self, manager: StopOrderManager, eventbus: MagicMock
    ) -> None:
        """#2405: 세션이 아직 진행 중이면(윈도우 안) sweep 이 만료하지 않는다.

        entered_session 은 유지되지만 ``not _is_in_session`` 조건이 False 라
        만료되지 않는다(무틱 sweep 호출이어도 안전).
        """
        manager.start()

        with patch.object(
            StopOrderManager, "_is_session_type_active_now", return_value=True
        ):
            stop_id = await manager.register(
                order_id="ord-mid",
                bot_id="bot-001",
                strategy_id="stg-001",
                symbol="005930",
                side="sell",
                quantity=10.0,
                order_type="stop",
                stop_price=49000.0,
                account_id="acc-test",
            )
            await manager.on_price_update("005930", 50000.0, account_id="acc-test")
            order = manager.get_order(stop_id)
            assert order is not None
            assert order.entered_session is True

            # 세션 진행 중 sweep → 윈도우 안이라 만료 없음.
            eventbus.publish.reset_mock()
            await manager.check_session_expiry()

        assert eventbus.publish.call_count == 0
        assert order.entered_session is True
        assert len(manager.active_orders) == 1

    async def test_session_expiry_idempotent(
        self, manager: StopOrderManager, eventbus: MagicMock
    ) -> None:
        """#2405 S4: 만료된 주문은 active_orders 에서 빠져 중복 sweep 무해."""
        manager.start()

        # in-session 틱으로 멤버십 마킹.
        with patch.object(
            StopOrderManager, "_is_session_type_active_now", return_value=True
        ):
            await manager.register(
                order_id="ord-idem",
                bot_id="bot-001",
                strategy_id="stg-001",
                symbol="005930",
                side="sell",
                quantity=10.0,
                order_type="stop",
                stop_price=49000.0,
                account_id="acc-test",
            )
            await manager.on_price_update("005930", 50000.0, account_id="acc-test")

        eventbus.publish.reset_mock()
        with patch.object(
            StopOrderManager, "_is_session_type_active_now", return_value=False
        ):
            await manager.check_session_expiry()
            await manager.check_session_expiry()  # 두 번째 sweep

        # 첫 sweep 만 발행(active_orders not-expired 필터가 소비된 주문 제외).
        assert eventbus.publish.call_count == 1


class TestRegisterStoppedGuard:
    """#2405 (attempt2 P2): stopped(_running=False) 상태에서 register 는
    StopOrderManagerStoppedError 로 거부된다(silent loss 제거)."""

    async def test_register_raises_when_stopped(
        self, manager: StopOrderManager, eventbus: MagicMock
    ) -> None:
        """stop() 후 register() 는 raise(이벤트 미발행, _orders 미추가)."""
        from ante.gateway.stop_order import StopOrderManagerStoppedError

        manager.start()
        await manager.stop()  # _running=False
        assert manager._running is False

        eventbus.publish.reset_mock()

        with pytest.raises(StopOrderManagerStoppedError):
            await manager.register(
                order_id="ord-late",
                bot_id="bot-001",
                strategy_id="stg-001",
                symbol="005930",
                side="sell",
                quantity=10.0,
                order_type="stop",
                stop_price=49000.0,
                account_id="acc-test",
            )

        # 등록 거부 — 주문 미추가, 이벤트 미발행.
        assert len(manager.active_orders) == 0
        assert manager.get_orders_for_account("acc-test") == []
        assert eventbus.publish.call_count == 0

    async def test_register_raises_before_start(
        self, manager: StopOrderManager, eventbus: MagicMock
    ) -> None:
        """start() 호출 전(_running=False)에도 register 는 raise(결정적)."""
        from ante.gateway.stop_order import StopOrderManagerStoppedError

        assert manager._running is False

        with pytest.raises(StopOrderManagerStoppedError):
            await manager.register(
                order_id="ord-pre-start",
                bot_id="bot-001",
                strategy_id="stg-001",
                symbol="005930",
                side="sell",
                quantity=10.0,
                order_type="stop",
                stop_price=49000.0,
                account_id="acc-test",
            )

        assert len(manager._orders) == 0
        assert eventbus.publish.call_count == 0

    async def test_register_stopped_still_rejects_invalid_account(
        self, manager: StopOrderManager
    ) -> None:
        """stopped 상태라도 invalid account_id 는 stopped 가드보다 먼저 거부된다.

        InvalidAccountIdError 가 StopOrderManagerStoppedError 보다 먼저 발생한다
        (account 검증이 가드 앞 — invalid 입력은 stopped 여부와 무관하게 거부).
        """
        from ante.account.errors import InvalidAccountIdError

        manager.start()
        await manager.stop()

        with pytest.raises(InvalidAccountIdError):
            await manager.register(
                order_id="ord-bad",
                bot_id="bot-001",
                strategy_id="stg-001",
                symbol="005930",
                side="sell",
                quantity=10.0,
                order_type="stop",
                stop_price=49000.0,
                account_id="",
            )


class TestBotOrders:
    """봇별 주문 조회 테스트."""

    async def test_get_orders_for_bot(
        self, manager: StopOrderManager, eventbus: MagicMock
    ) -> None:
        """봇별 활성 주문 필터링."""
        manager.start()
        await manager.register(
            order_id="ord-001",
            bot_id="bot-001",
            strategy_id="stg-001",
            symbol="005930",
            side="sell",
            quantity=10.0,
            order_type="stop",
            stop_price=49000.0,
            account_id="acc-test",
        )
        await manager.register(
            order_id="ord-002",
            bot_id="bot-002",
            strategy_id="stg-002",
            symbol="000660",
            side="buy",
            quantity=5.0,
            order_type="stop",
            stop_price=100000.0,
            account_id="acc-test",
        )

        bot1_orders = manager.get_orders_for_bot("bot-001")
        assert len(bot1_orders) == 1
        assert bot1_orders[0].symbol == "005930"


class TestAccountOrders:
    """계좌별 주문 조회 테스트 (#2124, get_orders_for_bot 동형)."""

    def test_get_orders_for_account_exists(self) -> None:
        """#2124 재현 해소: get_orders_for_account 메서드 존재."""
        assert hasattr(StopOrderManager, "get_orders_for_account")

    async def test_get_orders_for_account_isolates_by_account(
        self, manager: StopOrderManager, eventbus: MagicMock
    ) -> None:
        """여러 계좌 등록 시 해당 계좌 활성 주문만 반환 (타 계좌 격리)."""
        manager.start()
        await manager.register(
            order_id="ord-a1",
            bot_id="bot-001",
            strategy_id="stg-001",
            symbol="005930",
            side="sell",
            quantity=10.0,
            order_type="stop",
            stop_price=49000.0,
            account_id="acc-a",
        )
        await manager.register(
            order_id="ord-a2",
            bot_id="bot-002",
            strategy_id="stg-002",
            symbol="000660",
            side="buy",
            quantity=5.0,
            order_type="stop",
            stop_price=100000.0,
            account_id="acc-a",
        )
        await manager.register(
            order_id="ord-b1",
            bot_id="bot-003",
            strategy_id="stg-003",
            symbol="035720",
            side="buy",
            quantity=3.0,
            order_type="stop",
            stop_price=50000.0,
            account_id="acc-b",
        )

        acc_a_orders = manager.get_orders_for_account("acc-a")
        assert len(acc_a_orders) == 2
        assert all(o.account_id == "acc-a" for o in acc_a_orders)
        assert {o.symbol for o in acc_a_orders} == {"005930", "000660"}

        acc_b_orders = manager.get_orders_for_account("acc-b")
        assert len(acc_b_orders) == 1
        assert acc_b_orders[0].account_id == "acc-b"
        assert acc_b_orders[0].symbol == "035720"

    @patch.object(StopOrderManager, "_is_in_session", return_value=True)
    async def test_get_orders_for_account_excludes_triggered_and_expired(
        self,
        _mock_session: MagicMock,
        manager: StopOrderManager,
        eventbus: MagicMock,
    ) -> None:
        """triggered/expired 주문은 제외 (active_orders 기반)."""
        manager.start()

        # 트리거될 주문
        triggered_id = await manager.register(
            order_id="ord-trig",
            bot_id="bot-001",
            strategy_id="stg-001",
            symbol="005930",
            side="sell",
            quantity=10.0,
            order_type="stop",
            stop_price=49000.0,
            account_id="acc-a",
        )
        # 만료시킬 주문
        expired_id = await manager.register(
            order_id="ord-exp",
            bot_id="bot-002",
            strategy_id="stg-002",
            symbol="000660",
            side="buy",
            quantity=5.0,
            order_type="stop",
            stop_price=100000.0,
            account_id="acc-a",
        )
        # 활성으로 유지될 주문
        await manager.register(
            order_id="ord-active",
            bot_id="bot-003",
            strategy_id="stg-003",
            symbol="035720",
            side="buy",
            quantity=3.0,
            order_type="stop",
            stop_price=200000.0,
            account_id="acc-a",
        )

        # triggered 주문 trigger 처리
        await manager.on_price_update("005930", 48500.0, account_id="acc-a")
        # expired 주문 만료 처리
        expired_order = manager.get_order(expired_id)
        assert expired_order is not None
        await manager._expire_order(expired_order, "session_ended")

        triggered_order = manager.get_order(triggered_id)
        assert triggered_order is not None
        assert triggered_order.triggered is True

        acc_a_orders = manager.get_orders_for_account("acc-a")
        assert len(acc_a_orders) == 1
        assert acc_a_orders[0].order_id == "ord-active"

    def test_get_orders_for_account_unknown_returns_empty(
        self, manager: StopOrderManager
    ) -> None:
        """미존재 account_id → 빈 리스트 (데이터 누출 없음)."""
        assert manager.get_orders_for_account("acc-unknown") == []

    async def test_get_orders_for_account_subset_of_active(
        self, manager: StopOrderManager, eventbus: MagicMock
    ) -> None:
        """get_orders_for_bot 과 교차 정합 — 같은 active set 의 부분집합."""
        manager.start()
        await manager.register(
            order_id="ord-1",
            bot_id="bot-001",
            strategy_id="stg-001",
            symbol="005930",
            side="sell",
            quantity=10.0,
            order_type="stop",
            stop_price=49000.0,
            account_id="acc-a",
        )
        await manager.register(
            order_id="ord-2",
            bot_id="bot-001",
            strategy_id="stg-002",
            symbol="000660",
            side="buy",
            quantity=5.0,
            order_type="stop",
            stop_price=100000.0,
            account_id="acc-b",
        )

        active = manager.active_orders
        acc_a_orders = manager.get_orders_for_account("acc-a")
        bot1_orders = manager.get_orders_for_bot("bot-001")

        # 두 조회 모두 active_orders 의 부분집합
        active_ids = {o.stop_order_id for o in active}
        assert {o.stop_order_id for o in acc_a_orders} <= active_ids
        assert {o.stop_order_id for o in bot1_orders} <= active_ids

        # acc-a 활성 주문 = bot-001 의 acc-a 주문 (ord-1) 한 건과 교차 정합
        acc_a_ids = {o.stop_order_id for o in acc_a_orders}
        bot1_ids = {o.stop_order_id for o in bot1_orders}
        assert acc_a_ids & bot1_ids == {
            o.stop_order_id
            for o in active
            if o.account_id == "acc-a" and o.bot_id == "bot-001"
        }


class TestSignalTradingSession:
    """Signal trading_session 필드 테스트."""

    def test_signal_default_session(self) -> None:
        """Signal 기본 trading_session은 regular."""
        from ante.strategy.base import Signal

        sig = Signal(symbol="005930", side="buy", quantity=10)
        assert sig.trading_session == "regular"

    def test_signal_extended_session(self) -> None:
        """Signal extended session 설정."""
        from ante.strategy.base import Signal

        sig = Signal(
            symbol="005930",
            side="buy",
            quantity=10,
            trading_session="extended",
        )
        assert sig.trading_session == "extended"


class TestCrossAccountIsolation:
    """SPLIT-3 (#1242): StopOrderManager는 같은 종목이라도 account_id 가
    다른 stop order 끼리 trigger를 격리한다.

    multi-account 환경에서는 account마다 별도의 KISStreamClient
    인스턴스가 ``account_id`` 명시 호출을 통해 ``on_price_update`` 를
    호출하므로, 시세가 들어온 account 의 stop order만 평가되어야 한다.
    """

    @patch.object(StopOrderManager, "_is_in_session", return_value=True)
    async def test_register_requires_valid_account_id(
        self, _mock_session: MagicMock, manager: StopOrderManager
    ) -> None:
        """register 시 account_id 가 invalid 면 InvalidAccountIdError."""
        from ante.account.errors import InvalidAccountIdError

        with pytest.raises(InvalidAccountIdError):
            await manager.register(
                order_id="ord-bad",
                bot_id="bot-bad",
                strategy_id="stg-bad",
                symbol="005930",
                side="sell",
                quantity=10.0,
                order_type="stop",
                stop_price=49000.0,
                account_id="",
            )

    @patch.object(StopOrderManager, "_is_in_session", return_value=True)
    async def test_on_price_update_requires_account_id(
        self, _mock_session: MagicMock, manager: StopOrderManager
    ) -> None:
        """on_price_update 호출 시 account_id 가 invalid 면 거부."""
        from ante.account.errors import InvalidAccountIdError

        manager.start()

        with pytest.raises(InvalidAccountIdError):
            await manager.on_price_update("005930", 50000.0, account_id="")

    @patch.object(StopOrderManager, "_is_in_session", return_value=True)
    async def test_cross_account_isolation_only_triggers_matching_account(
        self,
        _mock_session: MagicMock,
        manager: StopOrderManager,
        eventbus: MagicMock,
    ) -> None:
        """동일 symbol 이라도 account_id 가 다르면 trigger 되지 않는다."""
        manager.start()

        # acc-1 의 stop sell 주문 등록
        await manager.register(
            order_id="ord-acc1",
            bot_id="bot-acc1",
            strategy_id="stg-1",
            symbol="005930",
            side="sell",
            quantity=10.0,
            order_type="stop",
            stop_price=49000.0,
            account_id="acc-1",
        )
        # acc-2 의 stop sell 주문 등록 (same symbol, same trigger condition)
        await manager.register(
            order_id="ord-acc2",
            bot_id="bot-acc2",
            strategy_id="stg-2",
            symbol="005930",
            side="sell",
            quantity=10.0,
            order_type="stop",
            stop_price=49000.0,
            account_id="acc-2",
        )

        eventbus.publish.reset_mock()

        # acc-1 의 stream 에서 가격이 들어옴 → acc-1 주문만 trigger 되어야 한다
        await manager.on_price_update("005930", 48500.0, account_id="acc-1")

        # 1 trigger × 2 events (StopOrderTriggeredEvent + OrderRequestEvent)
        assert eventbus.publish.call_count == 2

        triggered_event = eventbus.publish.call_args_list[0][0][0]
        order_event = eventbus.publish.call_args_list[1][0][0]
        assert triggered_event.stop_order_id  # 첫 이벤트 stop order id 존재
        # OrderRequestEvent 는 acc-1 의 account_id 를 들고 발행되어야 한다.
        assert order_event.account_id == "acc-1"
        assert order_event.bot_id == "bot-acc1"

        # acc-2 의 주문은 여전히 active 로 남아 있다.
        active_for_acc2 = [o for o in manager.active_orders if o.account_id == "acc-2"]
        assert len(active_for_acc2) == 1

    @patch.object(StopOrderManager, "_is_in_session", return_value=True)
    async def test_cross_account_each_account_triggers_own_orders(
        self,
        _mock_session: MagicMock,
        manager: StopOrderManager,
        eventbus: MagicMock,
    ) -> None:
        """각 계좌 stream 에서 가격이 들어오면 각자의 주문만 trigger 된다."""
        manager.start()

        await manager.register(
            order_id="ord-acc1",
            bot_id="bot-acc1",
            strategy_id="stg-1",
            symbol="005930",
            side="buy",
            quantity=10.0,
            order_type="stop",
            stop_price=51000.0,
            account_id="acc-1",
        )
        await manager.register(
            order_id="ord-acc2",
            bot_id="bot-acc2",
            strategy_id="stg-2",
            symbol="005930",
            side="buy",
            quantity=5.0,
            order_type="stop",
            stop_price=51000.0,
            account_id="acc-2",
        )

        # acc-1 stream 가격
        await manager.on_price_update("005930", 51500.0, account_id="acc-1")
        # acc-2 stream 가격
        await manager.on_price_update("005930", 51500.0, account_id="acc-2")

        # 두 trigger × 2 events 씩 = 4 events
        order_events = [
            call.args[0]
            for call in eventbus.publish.call_args_list
            if call.args and type(call.args[0]).__name__ == "OrderRequestEvent"
        ]
        assert len(order_events) == 2
        accounts = sorted(e.account_id for e in order_events)
        assert accounts == ["acc-1", "acc-2"]


class TestExchangeTickSourceChokepoint:
    """#2405 (attempt5 P2): 거래일 멤버십 마킹은 실 WS 틱(``is_exchange_tick=True``)
    에 한정한다.

    REST fallback poll(``is_exchange_tick=False``)은 KIS ``inquire-price`` 가
    휴장일에도 직전 종가를 성공 반환하므로 거래일을 보증하지 못해 ``entered_session``
    마킹을 유발하지 않는다. 단, 트리거 평가는 출처와 무관하게 항상 수행한다(분리 락).
    """

    async def test_fallback_poll_no_marking_no_expiry(
        self, manager: StopOrderManager, eventbus: MagicMock
    ) -> None:
        """휴장일 fallback → 무마킹 → 무만료.

        in-session 시각에 등록 후 ``is_exchange_tick=False`` 가격을 받아도
        ``entered_session`` 은 False 로 남아, 세션 종료 sweep 에서 보존된다.
        (휴장일/주말의 시계상 세션 시간에 fallback poll 이 성공해 last-close 를
        반환하는 시나리오 — 마킹되면 장종료 sweep 에서 오만료된다.)
        """
        manager.start()

        with patch.object(
            StopOrderManager, "_is_session_type_active_now", return_value=True
        ):
            stop_id = await manager.register(
                order_id="ord-fallback",
                bot_id="bot-001",
                strategy_id="stg-001",
                symbol="005930",
                side="sell",
                quantity=10.0,
                order_type="stop",
                stop_price=49000.0,
                account_id="acc-test",
            )
            order = manager.get_order(stop_id)
            assert order is not None
            assert order.entered_session is False

            # fallback poll 가격(트리거 미달) → is_exchange_tick=False → 무마킹.
            eventbus.publish.reset_mock()
            await manager.on_price_update(
                "005930", 50000.0, account_id="acc-test", is_exchange_tick=False
            )
            assert order.entered_session is False
            assert eventbus.publish.call_count == 0

        # 세션 종료 sweep → 멤버십 없으므로 보존(not expired).
        with patch.object(
            StopOrderManager, "_is_session_type_active_now", return_value=False
        ):
            await manager.check_session_expiry()

        assert eventbus.publish.call_count == 0
        assert len(manager.active_orders) == 1
        assert order.entered_session is False

    async def test_exchange_tick_marks_and_expires(
        self, manager: StopOrderManager, eventbus: MagicMock
    ) -> None:
        """실 WS 틱 → 마킹 → 만료(비회귀).

        ``is_exchange_tick=True``(또는 default) 틱은 거래일 멤버십을 마킹하므로
        세션 종료 시 ``session_ended`` 로 만료된다(기존 동작 유지 회귀 락).
        """
        manager.start()

        with patch.object(
            StopOrderManager, "_is_session_type_active_now", return_value=True
        ):
            stop_id = await manager.register(
                order_id="ord-ws",
                bot_id="bot-001",
                strategy_id="stg-001",
                symbol="005930",
                side="sell",
                quantity=10.0,
                order_type="stop",
                stop_price=49000.0,
                account_id="acc-test",
            )
            order = manager.get_order(stop_id)
            assert order is not None

            # 실 WS 틱(트리거 미달) → 마킹.
            eventbus.publish.reset_mock()
            await manager.on_price_update(
                "005930", 50000.0, account_id="acc-test", is_exchange_tick=True
            )
            assert order.entered_session is True

        eventbus.publish.reset_mock()
        with patch.object(
            StopOrderManager, "_is_session_type_active_now", return_value=False
        ):
            await manager.check_session_expiry()

        assert eventbus.publish.call_count == 1
        event = eventbus.publish.call_args[0][0]
        assert isinstance(event, StopOrderExpiredEvent)
        assert event.reason == "session_ended"
        assert len(manager.active_orders) == 0

    async def test_exchange_tick_default_marks(
        self, manager: StopOrderManager, eventbus: MagicMock
    ) -> None:
        """기본 인자(default ``is_exchange_tick=True``)도 마킹한다(하위호환 락)."""
        manager.start()

        with patch.object(
            StopOrderManager, "_is_session_type_active_now", return_value=True
        ):
            stop_id = await manager.register(
                order_id="ord-default",
                bot_id="bot-001",
                strategy_id="stg-001",
                symbol="005930",
                side="sell",
                quantity=10.0,
                order_type="stop",
                stop_price=49000.0,
                account_id="acc-test",
            )
            order = manager.get_order(stop_id)
            assert order is not None

            # 키워드 미지정 → default True → 마킹.
            await manager.on_price_update("005930", 50000.0, account_id="acc-test")
            assert order.entered_session is True

    async def test_fallback_poll_triggers_without_marking(
        self, manager: StopOrderManager, eventbus: MagicMock
    ) -> None:
        """fallback 트리거 유지 + 무마킹(분리 락).

        ``is_exchange_tick=False`` 라도 stop 조건을 충족하는 가격이면 트리거
        이벤트가 발행돼야 한다(스트림 hiccup 중 실거래일 stop 발동). 동시에
        ``entered_session`` 은 마킹되지 않아야 한다(만료와 트리거의 분리).
        """
        manager.start()

        with patch.object(
            StopOrderManager, "_is_session_type_active_now", return_value=True
        ):
            stop_id = await manager.register(
                order_id="ord-fb-trig",
                bot_id="bot-001",
                strategy_id="stg-001",
                symbol="005930",
                side="sell",
                quantity=10.0,
                order_type="stop",
                stop_price=49000.0,
                account_id="acc-test",
            )
            order = manager.get_order(stop_id)
            assert order is not None

            # 트리거 조건 충족 가격(매도 stop: 현재가 <= stop_price) + fallback 출처.
            eventbus.publish.reset_mock()
            await manager.on_price_update(
                "005930", 48500.0, account_id="acc-test", is_exchange_tick=False
            )

        # 트리거 이벤트 발행(StopOrderTriggeredEvent + OrderRequestEvent).
        published = [call.args[0] for call in eventbus.publish.call_args_list]
        assert any(isinstance(e, StopOrderTriggeredEvent) for e in published)
        assert any(isinstance(e, OrderRequestEvent) for e in published)
        # 트리거됐지만 fallback 출처라 세션 멤버십은 미마킹(분리 락).
        assert order.entered_session is False
