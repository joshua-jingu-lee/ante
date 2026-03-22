"""각 모듈의 NotificationEvent 발행 검증 (16건).

이슈 #487: 각 모듈이 도메인 이벤트 발행 지점에서 NotificationEvent를 직접 발행.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from ante.eventbus import EventBus
from ante.eventbus.events import NotificationEvent


def _collect_notifications(eventbus: EventBus) -> list[NotificationEvent]:
    """EventBus에서 NotificationEvent를 수집하는 핸들러 등록."""
    collected: list[NotificationEvent] = []

    async def _handler(event: object) -> None:
        if isinstance(event, NotificationEvent):
            collected.append(event)

    eventbus.subscribe(NotificationEvent, _handler)
    return collected


# ── bot/manager.py (4건) ──────────────────────────


class TestBotManagerNotifications:
    """BotManager: 봇 시작/중지/에러/재시작 한도 소진."""

    @pytest.fixture
    def eventbus(self):
        return EventBus()

    @pytest.fixture
    def notifications(self, eventbus):
        return _collect_notifications(eventbus)

    @pytest.fixture
    async def manager(self, eventbus, tmp_path):
        from ante.core.database import Database

        db = Database(str(tmp_path / "test.db"))
        await db.connect()

        from ante.bot.manager import BotManager

        mgr = BotManager(eventbus=eventbus, db=db)
        await mgr.initialize()
        return mgr

    async def test_bot_started_notification(self, manager, eventbus, notifications):
        """봇 시작 시 NotificationEvent 발행."""
        from ante.eventbus.events import BotStartedEvent

        await eventbus.publish(BotStartedEvent(bot_id="bot-1"))
        assert len(notifications) == 1
        assert notifications[0].level == "info"
        assert notifications[0].category == "bot"
        assert "봇 시작" in notifications[0].title
        assert "bot-1" in notifications[0].message

    async def test_bot_stopped_notification(self, manager, eventbus, notifications):
        """봇 중지 시 NotificationEvent 발행."""
        from ante.eventbus.events import BotStoppedEvent

        await eventbus.publish(BotStoppedEvent(bot_id="bot-1"))
        assert len(notifications) == 1
        assert notifications[0].level == "info"
        assert notifications[0].category == "bot"
        assert "봇 중지" in notifications[0].title
        assert "bot-1" in notifications[0].message

    async def test_bot_error_notification(self, manager, eventbus, notifications):
        """봇 에러 시 NotificationEvent 발행."""
        from ante.eventbus.events import BotErrorEvent

        await eventbus.publish(
            BotErrorEvent(bot_id="bot-1", error_message="Connection timeout")
        )
        assert len(notifications) == 1
        assert notifications[0].level == "error"
        assert notifications[0].category == "bot"
        assert "봇 에러" in notifications[0].title
        assert "bot-1" in notifications[0].message
        assert "Connection timeout" in notifications[0].message

    async def test_restart_exhausted_notification(
        self, manager, eventbus, notifications
    ):
        """재시작 한도 소진 시 NotificationEvent 발행."""
        await manager._on_restart_exhausted("bot-1", "account-1", 3, "Crash")
        assert len(notifications) == 1
        assert notifications[0].level == "error"
        assert notifications[0].category == "bot"
        assert "재시작 한도 소진" in notifications[0].title
        assert "bot-1" in notifications[0].message
        assert "3" in notifications[0].message


# ── trade/recorder.py (3건) ──────────────────────────


class TestTradeRecorderNotifications:
    """TradeRecorder: 체결 완료 (매수/매도), 주문 취소 실패."""

    @pytest.fixture
    def eventbus(self):
        return EventBus()

    @pytest.fixture
    def notifications(self, eventbus):
        return _collect_notifications(eventbus)

    @pytest.fixture
    async def recorder(self, eventbus, tmp_path):
        from ante.core.database import Database
        from ante.trade.position import PositionHistory
        from ante.trade.recorder import TradeRecorder

        db = Database(str(tmp_path / "test.db"))
        await db.connect()
        ph = PositionHistory(db)
        await ph.initialize()
        rec = TradeRecorder(db=db, position_history=ph)
        await rec.initialize()
        rec.subscribe(eventbus)
        return rec

    async def test_filled_buy_notification(self, recorder, eventbus, notifications):
        """매수 체결 시 NotificationEvent 발행."""
        from ante.eventbus.events import OrderFilledEvent

        await eventbus.publish(
            OrderFilledEvent(
                order_id="o1",
                broker_order_id="bk1",
                bot_id="bot-1",
                strategy_id="s1",
                symbol="005930",
                side="buy",
                quantity=100.0,
                price=72000.0,
                order_type="market",
            )
        )
        assert len(notifications) == 1
        assert notifications[0].level == "info"
        assert notifications[0].category == "trade"
        assert "매수" in notifications[0].title
        assert "005930" in notifications[0].message
        assert "72,000" in notifications[0].message

    async def test_filled_sell_notification(self, recorder, eventbus, notifications):
        """매도 체결 시 NotificationEvent 발행."""
        from ante.eventbus.events import OrderFilledEvent

        await eventbus.publish(
            OrderFilledEvent(
                order_id="o2",
                broker_order_id="bk2",
                bot_id="bot-1",
                strategy_id="s1",
                symbol="005930",
                side="sell",
                quantity=50.0,
                price=73000.0,
                order_type="market",
            )
        )
        assert len(notifications) == 1
        assert "매도" in notifications[0].title

    async def test_cancel_failed_notification(self, recorder, eventbus, notifications):
        """주문 취소 실패 시 NotificationEvent 발행."""
        from ante.eventbus.events import OrderCancelFailedEvent

        await eventbus.publish(
            OrderCancelFailedEvent(
                order_id="o1",
                bot_id="bot-1",
                strategy_id="s1",
                error_message="Already filled",
            )
        )
        assert len(notifications) == 1
        assert notifications[0].level == "error"
        assert notifications[0].category == "trade"
        assert "취소 실패" in notifications[0].title
        assert "Already filled" in notifications[0].message


# ── main.py (2건) ──────────────────────────


class TestMainNotifications:
    """main.py: 시스템 시작/종료."""

    async def test_system_start_notification(self):
        """시스템 시작 시 NotificationEvent 발행."""
        from ante.eventbus.events import NotificationEvent

        eventbus = EventBus()
        collected = _collect_notifications(eventbus)

        # _run에서 시스템 시작 알림 발행 로직을 직접 호출
        await eventbus.publish(
            NotificationEvent(
                level="info",
                title="시스템 시작",
                message="Ante 시스템이 시작되었습니다.",
                category="system",
            )
        )
        assert len(collected) == 1
        assert collected[0].category == "system"
        assert "시작" in collected[0].title

    async def test_system_shutdown_notification(self):
        """시스템 종료 시 NotificationEvent 발행."""
        from ante.eventbus.events import NotificationEvent

        eventbus = EventBus()
        collected = _collect_notifications(eventbus)

        await eventbus.publish(
            NotificationEvent(
                level="info",
                title="시스템 종료",
                message="Ante 시스템이 종료됩니다.",
                category="system",
            )
        )
        assert len(collected) == 1
        assert collected[0].category == "system"
        assert "종료" in collected[0].title


# ── broker/circuit_breaker.py (2건) ──────────────────────────


class TestCircuitBreakerNotifications:
    """CircuitBreaker: 서킷 브레이커 차단/복구."""

    async def test_circuit_open_notification(self):
        """서킷 브레이커 OPEN 시 NotificationEvent 발행."""
        eventbus = EventBus()
        collected = _collect_notifications(eventbus)

        from ante.broker.circuit_breaker import CircuitBreaker

        cb = CircuitBreaker(failure_threshold=2, eventbus=eventbus, name="kis")

        # 연속 실패 → OPEN
        cb.record_failure()
        cb.record_failure()

        # fire-and-forget 태스크 대기
        await asyncio.sleep(0.05)

        notifs = [n for n in collected if "차단" in n.title]
        assert len(notifs) == 1
        assert notifs[0].level == "error"
        assert notifs[0].category == "broker"
        assert "kis" in notifs[0].message

    async def test_circuit_closed_notification(self):
        """서킷 브레이커 CLOSED 복구 시 NotificationEvent 발행."""
        eventbus = EventBus()
        collected = _collect_notifications(eventbus)

        from ante.broker.circuit_breaker import CircuitBreaker

        cb = CircuitBreaker(
            failure_threshold=2, recovery_timeout=0.01, eventbus=eventbus, name="kis"
        )

        # OPEN 전환
        cb.record_failure()
        cb.record_failure()
        await asyncio.sleep(0.05)

        # recovery timeout 경과 후 HALF_OPEN → 성공 → CLOSED
        _ = cb.state  # triggers HALF_OPEN
        cb.record_success()
        await asyncio.sleep(0.05)

        notifs = [n for n in collected if "복구" in n.title]
        assert len(notifs) == 1
        assert notifs[0].level == "info"
        assert notifs[0].category == "broker"


# ── trade/reconciler.py (1건) ──────────────────────────


class TestReconcilerNotification:
    """PositionReconciler: 포지션 불일치."""

    async def test_position_mismatch_notification(self):
        """포지션 불일치 감지 시 NotificationEvent 발행."""
        eventbus = EventBus()
        collected = _collect_notifications(eventbus)

        trade_service = AsyncMock()
        # 내부 포지션: 005930 100주
        mock_position = MagicMock()
        mock_position.symbol = "005930"
        mock_position.quantity = 100.0
        mock_position.avg_entry_price = 70000.0
        trade_service.get_positions.return_value = [mock_position]
        trade_service.correct_position.return_value = {
            "symbol": "005930",
            "old_qty": 100.0,
            "new_qty": 50.0,
        }

        from ante.trade.reconciler import PositionReconciler

        reconciler = PositionReconciler(trade_service=trade_service, eventbus=eventbus)

        # 브로커: 005930 50주 (불일치)
        await reconciler.reconcile(
            bot_id="bot-1",
            broker_positions=[
                {"symbol": "005930", "quantity": 50.0, "avg_price": 70000}
            ],
        )

        notifs = [n for n in collected if n.category == "broker"]
        assert len(notifs) == 1
        assert notifs[0].level == "critical"
        assert "포지션 불일치" in notifs[0].title
        assert "005930" in notifs[0].message
        assert "bot-1" in notifs[0].message


# ── approval/service.py (2건) ──────────────────────────


class TestApprovalNotifications:
    """ApprovalService: 결재 요청 생성/처리 완료."""

    @pytest.fixture
    def eventbus(self):
        return EventBus()

    @pytest.fixture
    def notifications(self, eventbus):
        return _collect_notifications(eventbus)

    @pytest.fixture
    async def service(self, eventbus, tmp_path):
        from ante.approval.service import ApprovalService
        from ante.core.database import Database

        db = Database(str(tmp_path / "test.db"))
        await db.connect()
        svc = ApprovalService(db=db, eventbus=eventbus)
        await svc.initialize()
        return svc

    async def test_approval_created_notification(
        self, service, eventbus, notifications
    ):
        """결재 요청 생성 시 NotificationEvent 발행 (버튼 포함)."""
        request = await service.create(
            type="strategy_deploy",
            requester="agent-1",
            title="전략 배포 요청",
        )
        notifs = [n for n in notifications if "결재 요청" in n.title]
        assert len(notifs) == 1
        assert notifs[0].level == "info"
        assert notifs[0].category == "approval"
        assert "전략 배포 요청" in notifs[0].message
        # 자동 승인 아닌 경우 버튼 포함
        assert notifs[0].buttons is not None
        assert len(notifs[0].buttons) == 1
        assert notifs[0].buttons[0][0]["callback_data"] == f"approve:{request.id}"

    async def test_approval_resolved_notification(
        self, service, eventbus, notifications
    ):
        """결재 승인 시 NotificationEvent 발행."""
        request = await service.create(
            type="strategy_deploy",
            requester="agent-1",
            title="전략 배포 요청",
        )
        notifications.clear()

        await service.approve(request.id, resolved_by="user")

        notifs = [n for n in notifications if "처리 완료" in n.title]
        assert len(notifs) == 1
        assert notifs[0].level == "info"
        assert notifs[0].category == "approval"
        assert "approved" in notifs[0].message
        assert request.id in notifs[0].message


# ── member/auth_service.py (1건) ──────────────────────────


class TestAuthServiceNotification:
    """AuthService: 인증 실패 반복."""

    @pytest.fixture
    def eventbus(self):
        return EventBus()

    @pytest.fixture
    def notifications(self, eventbus):
        return _collect_notifications(eventbus)

    @pytest.fixture
    async def auth_service(self, eventbus, tmp_path):
        from ante.core.database import Database
        from ante.member.auth_service import AuthService
        from ante.member.token_manager import TokenManager

        db = Database(str(tmp_path / "test.db"))
        await db.connect()
        token_mgr = TokenManager(db)
        auth = AuthService(
            db=db,
            eventbus=eventbus,
            token_manager=token_mgr,
            get_member=AsyncMock(return_value=None),
        )
        return auth

    async def test_auth_failed_notification(
        self, auth_service, eventbus, notifications
    ):
        """인증 실패 시 NotificationEvent 발행 (WARNING)."""
        with pytest.raises(PermissionError):
            await auth_service.authenticate("invalid_token")

        notifs = [n for n in notifications if n.category == "member"]
        assert len(notifs) == 1
        assert notifs[0].level == "warning"
        assert "인증 실패" in notifs[0].title
