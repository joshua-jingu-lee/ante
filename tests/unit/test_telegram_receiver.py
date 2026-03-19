"""TelegramCommandReceiver 테스트."""

from __future__ import annotations

import time as time_mod
from unittest.mock import AsyncMock, MagicMock

import pytest

from ante.notification.telegram_receiver import TelegramCommandReceiver

# ── Fixtures ──────────────────────────────────────


@pytest.fixture
def adapter():
    """TelegramAdapter mock."""
    mock = MagicMock()
    mock._api_base = "https://api.telegram.org/botTEST"
    return mock


@pytest.fixture
def bot_manager():
    mock = MagicMock()
    mock.list_bots.return_value = [
        {"bot_id": "bot-1", "status": "running", "strategy_id": "s1"},
        {"bot_id": "bot-2", "status": "stopped", "strategy_id": "s2"},
    ]
    mock.get_bot.return_value = MagicMock()
    mock.stop_bot = AsyncMock()
    return mock


@pytest.fixture
def treasury():
    mock = MagicMock()
    mock.get_summary.return_value = {
        "account_balance": 10_000_000,
        "purchasable_amount": 7_000_000,
        "ante_purchase_amount": 2_500_000,
        "ante_eval_amount": 2_650_000,
        "ante_profit_loss": 150_000,
        "total_allocated": 5_000_000,
        "unallocated": 5_000_000,
        "bot_count": 2,
    }
    return mock


@pytest.fixture
def system_state():
    from ante.config.system_state import TradingState

    mock = MagicMock()
    mock.trading_state = TradingState.HALTED
    mock.set_state = AsyncMock()
    return mock


@pytest.fixture
def receiver(adapter, bot_manager, treasury, system_state):
    return TelegramCommandReceiver(
        adapter=adapter,
        allowed_user_ids=[12345],
        polling_interval=1.0,
        confirm_timeout=30.0,
        bot_manager=bot_manager,
        treasury=treasury,
        system_state=system_state,
    )


# ── US-2: 인증 ───────────────────────────────────


class TestAuthorization:
    """화이트리스트 인증 테스트."""

    def test_authorized_user(self, receiver):
        assert receiver._is_authorized(12345) is True

    def test_unauthorized_user(self, receiver):
        assert receiver._is_authorized(99999) is False

    def test_empty_whitelist(self, adapter):
        r = TelegramCommandReceiver(adapter=adapter, allowed_user_ids=[])
        assert r._is_authorized(12345) is False

    async def test_unauthorized_message_ignored(self, receiver):
        """미인가 사용자의 메시지는 무시된다."""
        update = {
            "message": {
                "text": "/status",
                "from": {"id": 99999},
                "chat": {"id": 100},
            }
        }
        # _reply를 mock하여 호출되지 않는지 확인
        receiver._reply = AsyncMock()
        await receiver._handle_update(update)
        receiver._reply.assert_not_called()

    async def test_authorized_message_processed(self, receiver):
        """인가된 사용자의 메시지는 처리된다."""
        update = {
            "message": {
                "text": "/help",
                "from": {"id": 12345},
                "chat": {"id": 100},
            }
        }
        receiver._reply = AsyncMock()
        await receiver._handle_update(update)
        receiver._reply.assert_called_once()


# ── US-3: 명령 핸들러 ────────────────────────────


class TestCommands:
    """명령 핸들러 테스트."""

    async def test_help(self, receiver):
        result = receiver._cmd_help([])
        assert "/status" in result
        assert "/halt" in result
        assert "/help" in result

    async def test_status(self, receiver):
        result = receiver._cmd_status([])
        assert "거래 상태" in result
        assert "halted" in result
        assert "봇" in result

    async def test_status_no_manager(self, receiver):
        receiver._bot_manager = None
        result = receiver._cmd_status([])
        assert "거래 상태" in result

    async def test_status_no_state(self, receiver):
        receiver._system_state = None
        receiver._bot_manager = None
        result = receiver._cmd_status([])
        assert "조회할 수 없습니다" in result

    async def test_bots(self, receiver):
        result = receiver._cmd_bots([])
        assert "봇 목록" in result
        assert "bot-1" in result
        assert "bot-2" in result

    async def test_bots_no_manager(self, receiver):
        receiver._bot_manager = None
        result = receiver._cmd_bots([])
        assert "연결되지 않았습니다" in result

    async def test_bots_empty(self, receiver):
        receiver._bot_manager.list_bots.return_value = []
        result = receiver._cmd_bots([])
        assert "없습니다" in result

    async def test_balance(self, receiver):
        result = receiver._cmd_balance([])
        assert "자금 현황" in result
        assert "계좌 예수금: 10,000,000원" in result
        assert "매수 가능: 7,000,000원" in result
        assert "매입: 2,500,000원" in result
        assert "평가: 2,650,000원" in result
        assert "+150,000원" in result
        assert "봇 할당: 5,000,000원 (2개)" in result
        assert "미할당: 5,000,000원" in result

    async def test_balance_no_positions(self, receiver, treasury):
        """Ante 관리 종목이 없으면 해당 섹션 미표시."""
        treasury.get_summary.return_value = {
            "account_balance": 10_000_000,
            "purchasable_amount": 10_000_000,
            "ante_purchase_amount": 0,
            "ante_eval_amount": 0,
            "ante_profit_loss": 0,
            "total_allocated": 0,
            "unallocated": 10_000_000,
            "bot_count": 0,
        }
        result = receiver._cmd_balance([])
        assert "자금 현황" in result
        assert "Ante 관리 종목" not in result
        assert "봇 할당: 0원 (0개)" in result

    async def test_balance_negative_pl(self, receiver, treasury):
        """손실 시 음수 부호 및 📉 이모지."""
        treasury.get_summary.return_value = {
            "account_balance": 10_000_000,
            "purchasable_amount": 7_000_000,
            "ante_purchase_amount": 2_500_000,
            "ante_eval_amount": 2_300_000,
            "ante_profit_loss": -200_000,
            "total_allocated": 5_000_000,
            "unallocated": 5_000_000,
            "bot_count": 2,
        }
        result = receiver._cmd_balance([])
        assert "📉" in result
        assert "-200,000원" in result

    async def test_balance_no_treasury(self, receiver):
        receiver._treasury = None
        result = receiver._cmd_balance([])
        assert "연결되지 않았습니다" in result

    async def test_unknown_command(self, receiver):
        result = await receiver._execute("unknown", [], 12345, 100)
        assert "알 수 없는 명령" in result

    async def test_activate(self, receiver, system_state):
        result = await receiver._cmd_activate([])
        assert "거래가 재개되었습니다" in result
        system_state.set_state.assert_called_once()

    async def test_activate_already_active(self, receiver, system_state):
        from ante.config.system_state import TradingState

        system_state.trading_state = TradingState.ACTIVE
        result = await receiver._cmd_activate([])
        assert "이미 거래가 활성 상태입니다" in result
        system_state.set_state.assert_not_called()

    async def test_activate_no_state(self, receiver):
        receiver._system_state = None
        result = await receiver._cmd_activate([])
        assert "연결되지 않았습니다" in result

    async def test_stop_bot(self, receiver, bot_manager):
        result = await receiver._cmd_stop(["bot-1"])
        assert "중지" in result
        assert "bot-1" in result
        bot_manager.stop_bot.assert_called_once_with("bot-1")

    async def test_stop_bot_no_args(self, receiver):
        result = await receiver._cmd_stop([])
        assert "봇 ID를 지정" in result

    async def test_stop_bot_not_found(self, receiver, bot_manager):
        bot_manager.get_bot.return_value = None
        result = await receiver._cmd_stop(["bot-999"])
        assert "찾을 수 없습니다" in result

    async def test_stop_no_manager(self, receiver):
        receiver._bot_manager = None
        result = await receiver._cmd_stop(["bot-1"])
        assert "연결되지 않았습니다" in result


# ── US-4: 2단계 확인 ─────────────────────────────


class TestConfirmation:
    """위험 명령 확인 절차 테스트."""

    async def test_halt_requires_confirm(self, receiver):
        """halt 명령은 확인을 요구한다."""
        result = await receiver._execute("halt", ["긴급"], 12345, 100)
        assert "/confirm" in result
        assert "긴급" in result
        assert 12345 in receiver._pending_confirm

    async def test_stop_requires_confirm(self, receiver):
        """stop 명령은 확인을 요구한다."""
        result = await receiver._execute("stop", ["bot-1"], 12345, 100)
        assert "/confirm" in result
        assert "bot-1" in result

    async def test_confirm_executes_halt(self, receiver, system_state):
        """confirm으로 halt가 실행된다."""
        # 먼저 halt 요청
        await receiver._execute("halt", ["점검"], 12345, 100)
        # confirm 실행
        result = await receiver._handle_confirm(12345)
        assert "중지되었습니다" in result
        system_state.set_state.assert_called_once()

    async def test_confirm_executes_stop(self, receiver, bot_manager):
        """confirm으로 stop이 실행된다."""
        await receiver._execute("stop", ["bot-1"], 12345, 100)
        result = await receiver._handle_confirm(12345)
        assert "중지" in result
        bot_manager.stop_bot.assert_called_once_with("bot-1")

    async def test_confirm_no_pending(self, receiver):
        """대기 중인 명령이 없으면 안내 메시지."""
        result = await receiver._handle_confirm(12345)
        assert "대기 중인 명령이 없습니다" in result

    async def test_confirm_timeout(self, receiver):
        """확인 시간이 초과되면 실행 거부."""
        receiver._pending_confirm[12345] = ("halt", [], time_mod.time() - 60)
        result = await receiver._handle_confirm(12345)
        assert "시간이 초과" in result

    async def test_confirm_within_timeout(self, receiver, system_state):
        """타임아웃 내에 확인하면 실행."""
        receiver._pending_confirm[12345] = ("halt", [], time_mod.time() - 5)
        result = await receiver._handle_confirm(12345)
        assert "중지되었습니다" in result

    async def test_confirm_clears_pending(self, receiver):
        """확인 후 대기 상태가 정리된다."""
        await receiver._execute("halt", [], 12345, 100)
        await receiver._handle_confirm(12345)
        assert 12345 not in receiver._pending_confirm

    async def test_different_users_independent(self, receiver):
        """서로 다른 사용자의 확인 대기는 독립적이다."""
        receiver._allowed_user_ids.add(67890)
        receiver._pending_confirm[12345] = ("halt", [], time_mod.time())
        receiver._pending_confirm[67890] = ("stop", ["bot-1"], time_mod.time())

        result = await receiver._handle_confirm(12345)
        assert "중지되었습니다" in result
        assert 67890 in receiver._pending_confirm


# ── US-1: 폴링 루프 ─────────────────────────────


class TestPollingLoop:
    """폴링 루프 및 생명주기 테스트."""

    def test_start_without_users_does_nothing(self, adapter):
        """allowed_user_ids가 비면 시작하지 않는다."""
        r = TelegramCommandReceiver(adapter=adapter)
        r.start()
        assert r._task is None

    async def test_start_creates_task(self, receiver):
        """start()가 asyncio.Task를 생성한다."""
        receiver.start()
        assert receiver._task is not None
        assert not receiver._task.done()
        # 정리
        receiver._running = False
        receiver._task.cancel()

    async def test_stop_cancels_task(self, receiver):
        """stop()이 task를 취소한다."""
        receiver.start()
        assert receiver._task is not None
        await receiver.stop()
        assert receiver._task is None
        assert receiver._running is False

    async def test_start_idempotent(self, receiver):
        """중복 start 호출은 무시된다."""
        receiver.start()
        task1 = receiver._task
        receiver.start()
        assert receiver._task is task1
        receiver._running = False
        receiver._task.cancel()

    async def test_handle_update_non_message(self, receiver):
        """message가 없는 update는 무시."""
        receiver._reply = AsyncMock()
        await receiver._handle_update({"update_id": 1})
        receiver._reply.assert_not_called()

    async def test_handle_update_non_command(self, receiver):
        """/ 로 시작하지 않는 텍스트는 무시."""
        receiver._reply = AsyncMock()
        update = {
            "message": {
                "text": "hello",
                "from": {"id": 12345},
                "chat": {"id": 100},
            }
        }
        await receiver._handle_update(update)
        receiver._reply.assert_not_called()

    async def test_handle_update_empty_text(self, receiver):
        """빈 텍스트는 무시."""
        receiver._reply = AsyncMock()
        update = {
            "message": {
                "text": "",
                "from": {"id": 12345},
                "chat": {"id": 100},
            }
        }
        await receiver._handle_update(update)
        receiver._reply.assert_not_called()


# ── 통합 흐름 ─────────────────────────────────────


class TestIntegrationFlow:
    """명령 수신 → 실행 → 회신 통합 흐름."""

    async def test_full_status_flow(self, receiver):
        """인가 사용자 /status → 상태 회신."""
        receiver._reply = AsyncMock()
        update = {
            "message": {
                "text": "/status",
                "from": {"id": 12345},
                "chat": {"id": 100},
            }
        }
        await receiver._handle_update(update)
        receiver._reply.assert_called_once()
        reply_text = receiver._reply.call_args[0][1]
        assert "거래 상태" in reply_text

    async def test_full_halt_confirm_flow(self, receiver, system_state):
        """halt → confirm → 실제 실행 흐름."""
        receiver._reply = AsyncMock()

        # 1. /halt 요청
        halt_update = {
            "message": {
                "text": "/halt 긴급 점검",
                "from": {"id": 12345},
                "chat": {"id": 100},
            }
        }
        await receiver._handle_update(halt_update)
        assert receiver._reply.call_count == 1
        assert "/confirm" in receiver._reply.call_args[0][1]

        # 2. /confirm
        confirm_update = {
            "message": {
                "text": "/confirm",
                "from": {"id": 12345},
                "chat": {"id": 100},
            }
        }
        await receiver._handle_update(confirm_update)
        assert receiver._reply.call_count == 2
        assert "중지되었습니다" in receiver._reply.call_args[0][1]
        system_state.set_state.assert_called_once()

    async def test_reply_with_no_chat_id(self, receiver):
        """chat_id가 없어도 에러 없이 처리."""
        update = {
            "message": {
                "text": "/help",
                "from": {"id": 12345},
                "chat": {},
            }
        }
        # chat_id가 None이면 _reply는 early return
        receiver._reply = AsyncMock()
        await receiver._handle_update(update)
        # chat_id가 None이므로 _reply가 호출되지만 내부에서 early return
