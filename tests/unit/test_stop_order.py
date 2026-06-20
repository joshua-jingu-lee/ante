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
        await manager.register(
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

        # running=False이므로 무시(트리거·세션마킹 모두 없음)
        assert eventbus.publish.call_count == 0
        assert manager._session_active["regular"] is False
        assert manager._session_active["extended"] is False


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
    """#2405 (A2): 세션에 진입했던 미트리거 주문만 session_ended 로 만료된다.

    #2405 (attempt2 P2): 마킹을 per-order ``entered_session`` 에서
    manager-level ``_session_active`` 로 옮겼다. 거래일에 한 종목이라도
    in-session 틱(``on_price_update``)이 흐르면 그 세션이 market-wide 로 active
    표시되고, 세션 종료 시 그 세션의 모든 미트리거 주문(무틱 종목 포함)이
    만료된다. 휴장일(전종목 무틱)에는 플래그가 False 로 남아 사전 등록분이
    보존된다. 시간 의존은 ``_is_session_type_active_now`` patch 로 결정화한다
    (``_is_in_session`` 과 ``_current_session_types`` 가 이 헬퍼에 위임하므로
    한 번의 patch 로 둘 다 일관 제어).
    """

    async def test_entered_then_left_session_expires(
        self, manager: StopOrderManager, eventbus: MagicMock
    ) -> None:
        """거래일 정상: in-session 틱으로 세션이 active 표시된 뒤 종료 시 만료된다."""
        manager.start()

        # 세션 안에서 등록 + in-session 틱 → _session_active[regular]=True.
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
            # register 시점엔 세션활동 미마킹.
            assert manager._session_active["regular"] is False

            # in-session 틱(트리거 조건 미달 가격) → 세션 active 마킹.
            eventbus.publish.reset_mock()
            await manager.on_price_update("005930", 50000.0, account_id="acc-test")
            assert manager._session_active["regular"] is True
            # 트리거 조건 미달이라 이벤트 미발행.
            assert eventbus.publish.call_count == 0

        eventbus.publish.reset_mock()

        # 세션 종료 후 sweep → 세션이 active 였으므로 만료.
        with patch.object(
            StopOrderManager, "_is_session_type_active_now", return_value=False
        ):
            await manager.check_session_expiry()

        assert eventbus.publish.call_count == 1
        event = eventbus.publish.call_args[0][0]
        assert isinstance(event, StopOrderExpiredEvent)
        assert event.reason == "session_ended"
        assert len(manager.active_orders) == 0
        # reset: 윈도우 밖으로 끝난 세션 플래그가 닫힌다.
        assert manager._session_active["regular"] is False

    async def test_never_entered_session_not_expired(
        self, manager: StopOrderManager, eventbus: MagicMock
    ) -> None:
        """세션 미활동(장 전 등록·무틱) 주문은 만료 안 됨(A1 회귀 방지)."""
        manager.start()

        # 세션 밖에서 등록, 틱 없음 → _session_active 전부 False 유지.
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
            assert manager._session_active["regular"] is False

            eventbus.publish.reset_mock()
            await manager.check_session_expiry()

        # 세션이 한 번도 active 안 됐으므로 만료 안 됨.
        assert eventbus.publish.call_count == 0
        assert len(manager.active_orders) == 1

    async def test_holiday_no_tick_pre_registered_not_expired(
        self, manager: StopOrderManager, eventbus: MagicMock
    ) -> None:
        """#2405 (attempt2 P2) 휴장일 안전: 무틱이면 사전 등록 stop 이 만료되지 않는다.

        시나리오: 사전 등록 후 ``on_price_update`` 를 **호출하지 않고**(무틱),
        out-of-session 시각이 아니라 **in-session 시각**(주말·공휴일의 '시장
        시간대')에 sweep 을 돌린다. 틱이 없었으므로 _session_active=False →
        sweep 비만료. 시각만으로 마킹하면(이전 sweep 마킹 설계) 여기서 마킹돼
        다음 세션 종료에 오만료됐다(월요일 개장 전 사망).
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
        assert manager._session_active["regular"] is False

        eventbus.publish.reset_mock()

        # 휴장일 '시장 시간대' sweep: 시각상 in-session 이지만 무틱 → 미마킹.
        with patch.object(
            StopOrderManager, "_is_session_type_active_now", return_value=True
        ):
            await manager.check_session_expiry()
        assert manager._session_active["regular"] is False
        assert eventbus.publish.call_count == 0

        # 이후 '세션 종료' sweep 에서도 세션 미활동이라 만료 안 됨.
        with patch.object(
            StopOrderManager, "_is_session_type_active_now", return_value=False
        ):
            await manager.check_session_expiry()
        assert eventbus.publish.call_count == 0
        assert len(manager.active_orders) == 1

    async def test_no_tick_symbol_expires_market_wide(
        self, manager: StopOrderManager, eventbus: MagicMock
    ) -> None:
        """#2405 (attempt2 P2) 핵심 회귀: 무틱 종목도 market-wide 만료된다.

        종목A 틱으로 _session_active[regular]=True → 종목B(무틱) 포함 active
        order 들이 세션 종료 시 **모두** 만료된다. 이전 per-symbol 마킹에서는
        종목B 가 entered_session=False 로 남아 영구 미만료됐다(이 회귀 락).
        """
        manager.start()

        with patch.object(
            StopOrderManager, "_is_session_type_active_now", return_value=True
        ):
            # 종목A — 틱이 들어올 종목.
            await manager.register(
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
            await manager.register(
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

            # 종목A 만 틱(트리거 미달 가격) → market-wide 세션 active 마킹.
            await manager.on_price_update("005930", 50000.0, account_id="acc-test")
            assert manager._session_active["regular"] is True

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

    async def test_session_reset_then_reactivate_cycle(
        self, manager: StopOrderManager, eventbus: MagicMock
    ) -> None:
        """#2405 (attempt2 P2): 만료 sweep 후 _session_active reset → 다음
        세션 첫 틱 재set → 재만료 사이클."""
        manager.start()

        # 1일차: 틱 마킹 → 세션 종료 만료 → reset.
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
            assert manager._session_active["regular"] is True

        with patch.object(
            StopOrderManager, "_is_session_type_active_now", return_value=False
        ):
            await manager.check_session_expiry()
        # reset 확인.
        assert manager._session_active["regular"] is False

        # 2일차: 새 주문 등록 → 첫 틱이 다시 active set → 재만료.
        eventbus.publish.reset_mock()
        with patch.object(
            StopOrderManager, "_is_session_type_active_now", return_value=True
        ):
            await manager.register(
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
            assert manager._session_active["regular"] is True

        with patch.object(
            StopOrderManager, "_is_session_type_active_now", return_value=False
        ):
            await manager.check_session_expiry()
        # 2일차 주문도 만료.
        assert len(manager.active_orders) == 0
        assert manager._session_active["regular"] is False

    async def test_sweep_in_session_does_not_reset_active_flag(
        self, manager: StopOrderManager, eventbus: MagicMock
    ) -> None:
        """#2405 (attempt2 P2): 세션이 아직 진행 중이면(윈도우 안) sweep 이
        플래그를 reset 하지 않는다(만료도 안 함). 무틱 호출이어도 안전."""
        manager.start()

        with patch.object(
            StopOrderManager, "_is_session_type_active_now", return_value=True
        ):
            await manager.register(
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
            assert manager._session_active["regular"] is True

            # 세션 진행 중 sweep → 윈도우 안이라 만료·reset 모두 없음.
            eventbus.publish.reset_mock()
            await manager.check_session_expiry()

        assert eventbus.publish.call_count == 0
        assert manager._session_active["regular"] is True
        assert len(manager.active_orders) == 1

    async def test_session_expiry_idempotent(
        self, manager: StopOrderManager, eventbus: MagicMock
    ) -> None:
        """#2405 S4: 만료된 주문은 active_orders 에서 빠져 중복 sweep 무해."""
        manager.start()

        # in-session 틱으로 세션 active 마킹.
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

        # 첫 sweep 만 발행(active_orders not-expired 필터 + reset 후 플래그 False)
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
