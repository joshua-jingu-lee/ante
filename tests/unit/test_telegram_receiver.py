"""TelegramCommandReceiver 테스트."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ante.bot.manager import StopCleanup
from ante.core import clock
from ante.notification.telegram_receiver import (
    _UPDATE_FAILURE_REPLY,
    TelegramCommandReceiver,
)
from tests.conftest import DEFAULT_MANUAL_CLOCK_AT, ManualClock

# ── Fixtures ──────────────────────────────────────


@pytest.fixture
def adapter():
    """TelegramAdapter mock."""
    mock = MagicMock()
    mock._api_base = "https://api.telegram.org/botTEST"
    return mock


def _make_running_bot(
    bot_id: str = "bot-1",
    name: str = "테스트봇",
    positions: dict | None = None,
    open_orders: list | None = None,
    account_id: str = "test",
):
    """RUNNING 상태의 Bot mock 생성 헬퍼."""
    from ante.bot.config import BotStatus

    bot = MagicMock()
    bot.bot_id = bot_id
    bot.status = BotStatus.RUNNING
    bot.config.name = name
    bot.config.account_id = account_id
    bot._ctx.get_positions.return_value = positions or {}
    bot._ctx.get_open_orders.return_value = open_orders or []
    return bot


@pytest.fixture
def bot_manager():
    mock = MagicMock()
    mock.list_bots.return_value = [
        {"bot_id": "bot-1", "status": "running", "strategy_id": "s1"},
        {"bot_id": "bot-2", "status": "stopped", "strategy_id": "s2"},
    ]
    mock.get_bot.return_value = _make_running_bot()
    mock.stop_bot = AsyncMock(return_value=None)
    return mock


def _make_treasury(account_id: str = "test", summary: dict | None = None):
    """``account_id`` property + sync ``get_summary()``를 갖는 Treasury mock."""
    mock = MagicMock()
    mock.account_id = account_id
    mock.get_summary.return_value = summary or {
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
def treasury_manager():
    """TreasuryManager mock — ``list_all()`` (sync) 가 단일 Treasury 반환."""
    mock = MagicMock()
    mock.list_all.return_value = [_make_treasury()]
    return mock


@pytest.fixture
def account_service():
    """AccountService mock (모든 계좌 SUSPENDED 상태)."""
    from ante.account.models import AccountStatus

    mock = AsyncMock()
    # 기본: ACTIVE 계좌 1개
    active_account = SimpleNamespace(account_id="test", status=AccountStatus.ACTIVE)
    mock.list.return_value = [active_account]
    mock.has_unpersisted_suspensions = MagicMock(return_value=False)
    # Refs #1213: list[dict] 반환 타입.
    mock.suspend_all = AsyncMock(
        return_value=[
            {
                "account_id": "test",
                "previous_status": "active",
                "status": "suspended",
                "changed": True,
            }
        ]
    )
    mock.activate_all = AsyncMock(
        return_value=[
            {
                "account_id": "test",
                "previous_status": "suspended",
                "status": "active",
                "changed": True,
            }
        ]
    )
    # #2385: /stop exchange 해석용 — account.exchange 기본 KRX.
    mock.get = AsyncMock(
        return_value=SimpleNamespace(account_id="test", exchange="KRX")
    )
    return mock


@pytest.fixture
def instrument_service():
    """InstrumentService mock — format_label SSOT (#2385).

    KRX 캐시에 005930/035720 만 존재. 다른 (symbol, exchange) 는 symbol-only
    폴백을 흉내낸다(실제 ``format_label`` 의 캐시 미스 계약과 동형).
    """
    names = {
        ("005930", "KRX"): "삼성전자",
        ("035720", "KRX"): "카카오",
    }

    def _format_label(symbol: str, exchange: str = "KRX", *, markdown: bool = False):
        base = f"`{symbol}`" if markdown else symbol
        name = names.get((symbol, exchange))
        if not name or name == symbol:
            return base
        return f"{base} ({name})"

    mock = MagicMock()
    mock.format_label.side_effect = _format_label
    return mock


@pytest.fixture
def receiver(
    adapter, bot_manager, treasury_manager, account_service, instrument_service
):
    return TelegramCommandReceiver(
        adapter=adapter,
        allowed_user_ids=[12345],
        polling_interval=1.0,
        confirm_timeout=30.0,
        bot_manager=bot_manager,
        treasury_manager=treasury_manager,
        account_service=account_service,
        instrument_service=instrument_service,
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
        result = await receiver._cmd_status([])
        assert "거래 상태" in result
        assert "active" in result
        assert "봇" in result

    async def test_status_no_manager(self, receiver):
        receiver._bot_manager = None
        result = await receiver._cmd_status([])
        assert "거래 상태" in result

    async def test_status_no_service(self, receiver):
        receiver._account_service = None
        receiver._bot_manager = None
        result = await receiver._cmd_status([])
        assert "조회할 수 없습니다" in result

    async def test_bots(self, receiver):
        result = receiver._cmd_bots([])
        assert "봇 목록 (1/2 실행 중)" in result
        assert "bot-1" in result
        assert "[실행 중]" in result
        assert "bot-2" in result
        assert "[중지됨]" in result

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
        assert "계좌: test" in result
        assert "계좌 예수금: 10,000,000원" in result
        assert "매수 가능: 7,000,000원" in result
        assert "매입: 2,500,000원" in result
        assert "평가: 2,650,000원" in result
        assert "+150,000원" in result
        assert "봇 할당: 5,000,000원 (2개)" in result
        assert "미할당: 5,000,000원" in result

    async def test_balance_no_positions(self, receiver, treasury_manager):
        """Ante 관리 종목이 없으면 해당 섹션 미표시."""
        treasury_manager.list_all.return_value = [
            _make_treasury(
                summary={
                    "account_balance": 10_000_000,
                    "purchasable_amount": 10_000_000,
                    "ante_purchase_amount": 0,
                    "ante_eval_amount": 0,
                    "ante_profit_loss": 0,
                    "total_allocated": 0,
                    "unallocated": 10_000_000,
                    "bot_count": 0,
                }
            )
        ]
        result = receiver._cmd_balance([])
        assert "자금 현황" in result
        assert "Ante 관리 종목" not in result
        assert "봇 할당: 0원 (0개)" in result

    async def test_balance_negative_pl(self, receiver, treasury_manager):
        """손실 시 음수 부호."""
        treasury_manager.list_all.return_value = [
            _make_treasury(
                summary={
                    "account_balance": 10_000_000,
                    "purchasable_amount": 7_000_000,
                    "ante_purchase_amount": 2_500_000,
                    "ante_eval_amount": 2_300_000,
                    "ante_profit_loss": -200_000,
                    "total_allocated": 5_000_000,
                    "unallocated": 5_000_000,
                    "bot_count": 2,
                }
            )
        ]
        result = receiver._cmd_balance([])
        assert "-200,000원" in result

    async def test_balance_multi_account(self, receiver, treasury_manager):
        """다계좌 — 계좌별 섹션이 각각 렌더링된다 (#2378 전 계좌 요약)."""
        treasury_manager.list_all.return_value = [
            _make_treasury(
                account_id="acct-a",
                summary={
                    "account_balance": 10_000_000,
                    "purchasable_amount": 7_000_000,
                    "ante_purchase_amount": 0,
                    "ante_eval_amount": 0,
                    "ante_profit_loss": 0,
                    "total_allocated": 3_000_000,
                    "unallocated": 4_000_000,
                    "bot_count": 1,
                },
            ),
            _make_treasury(
                account_id="acct-b",
                summary={
                    "account_balance": 20_000_000,
                    "purchasable_amount": 15_000_000,
                    "ante_purchase_amount": 0,
                    "ante_eval_amount": 0,
                    "ante_profit_loss": 0,
                    "total_allocated": 5_000_000,
                    "unallocated": 10_000_000,
                    "bot_count": 2,
                },
            ),
        ]
        result = receiver._cmd_balance([])
        # 최상단 타이틀은 1회만 노출
        assert result.count("ℹ️ 자금 현황") == 1
        # 두 계좌 헤더와 각 본문이 모두 노출
        assert "계좌: acct-a" in result
        assert "계좌: acct-b" in result
        assert "계좌 예수금: 10,000,000원" in result
        assert "계좌 예수금: 20,000,000원" in result
        assert "봇 할당: 3,000,000원 (1개)" in result
        assert "봇 할당: 5,000,000원 (2개)" in result

    async def test_balance_no_accounts(self, receiver, treasury_manager):
        """등록된 계좌가 없으면 안내 메시지."""
        treasury_manager.list_all.return_value = []
        result = receiver._cmd_balance([])
        assert "등록된 계좌가 없습니다" in result

    async def test_balance_no_treasury_manager(self, receiver):
        """TreasuryManager 미주입 시 fallback 문구."""
        receiver._treasury_manager = None
        result = receiver._cmd_balance([])
        assert "TreasuryManager가 연결되지 않았습니다" in result

    async def test_unknown_command(self, receiver):
        result = await receiver._execute("unknown", [], 12345, 100)
        assert "알 수 없는 명령" in result

    async def test_clear_halt(self, receiver, account_service):
        """``_cmd_clear_halt``는 ``activate_all``을 호출하고 SSOT 안내 문구를 반환."""
        from ante.account.models import AccountStatus

        suspended_account = SimpleNamespace(
            account_id="test", status=AccountStatus.SUSPENDED
        )
        account_service.list.return_value = [suspended_account]
        result = await receiver._cmd_clear_halt([])
        assert "정지가 해제" in result
        # SSOT 문구: 봇 자동 재시작 없음
        assert "자동 재시작되지 않습니다" in result
        account_service.activate_all.assert_called_once_with(activated_by="telegram")

    async def test_clear_halt_already_active(self, receiver, account_service):
        """이미 ACTIVE면 즉시 안내."""
        result = await receiver._cmd_clear_halt([])
        assert "이미 거래가 활성 상태입니다" in result
        account_service.activate_all.assert_not_called()

    async def test_clear_halt_no_service(self, receiver):
        receiver._account_service = None
        result = await receiver._cmd_clear_halt([])
        assert "연결되지 않았습니다" in result

    async def test_no_legacy_activate_handler(self, receiver):
        """legacy ``_cmd_activate`` 메서드는 제거되었다 (Refs #1213)."""
        assert not hasattr(receiver, "_cmd_activate")

    async def test_stop_bot_no_positions(self, receiver, bot_manager):
        """보유 종목 없이 봇 중지 — 정리 결과를 적고 옛 안내 문장이 없다 (#3049)."""
        bot_manager.stop_bot.return_value = StopCleanup(cancelled=2, failed=1)
        result = await receiver._cmd_stop(["bot-1"])
        assert "봇 중지" in result
        assert "테스트봇 (bot-1)" in result
        assert "실행 중 → 중지됨" in result
        assert "미체결 주문 취소: 2건 (실패 1건)" in result
        assert "스탑 주문 만료: 0건" in result
        assert "자동 취소되지 않습니다" not in result
        bot_manager.stop_bot.assert_called_once_with(
            "bot-1", suppress_notification=True
        )

    async def test_stop_bot_lists_expired_stop_orders(self, receiver, bot_manager):
        """#3049: 만료한 스탑 주문의 종목·방향·스탑 가격을 적는다."""
        stop = SimpleNamespace(symbol="005930", side="sell", stop_price=68000.0)
        bot_manager.stop_bot.return_value = StopCleanup(
            cancelled=0,
            failed=0,
            stop_orders=(stop,),  # type: ignore[arg-type]
        )
        result = await receiver._cmd_stop(["bot-1"])
        assert "스탑 주문 만료: 1건" in result
        assert "- 005930 sell stop 68,000" in result

    async def test_stop_bot_with_positions(self, receiver, bot_manager):
        """보유 종목 있으면 메시지 B — 종목명 및 미체결 주문 건수 표시.

        #1948: 통일 OpenOrder dict 스키마에 amount(예약 금액)가 없으므로
        체결대기는 금액 합이 아닌 **주문 건수**로 표시한다(live amount 부재
        0원 오표시 버그 정정).
        """
        bot = _make_running_bot(
            positions={
                "005930": {
                    "symbol": "005930",
                    "quantity": 10,
                    "avg_entry_price": 70000,
                },
                "035720": {"symbol": "035720", "quantity": 5, "avg_entry_price": 50000},
            },
            open_orders=[
                {
                    "order_id": "o1",
                    "symbol": "005930",
                    "side": "buy",
                    "ordered_qty": 10.0,
                    "recorded_filled_qty": 0.0,
                    "remaining_qty": 10.0,
                    "status": "open",
                    "submitted_at": None,
                },
                {
                    "order_id": "o2",
                    "symbol": "035720",
                    "side": "buy",
                    "ordered_qty": 5.0,
                    "recorded_filled_qty": 0.0,
                    "remaining_qty": 5.0,
                    "status": "open",
                    "submitted_at": None,
                },
            ],
        )
        bot_manager.get_bot.return_value = bot
        result = await receiver._cmd_stop(["bot-1"])
        assert "봇 중지" in result
        assert "보유 종목 2개가 유지됩니다" in result
        assert "포지션을 직접 관리" in result
        # #2385: format_label SSOT 로 종목명 병기 (plain transport).
        assert "005930 (삼성전자)" in result
        assert "035720 (카카오)" in result
        assert "체결대기 주문" not in result

    async def test_stop_bot_label_uses_account_exchange(
        self, receiver, bot_manager, account_service, instrument_service
    ):
        """#2385: exchange 는 bot.config.account_id → account.exchange 로 해석."""
        account_service.get.return_value = SimpleNamespace(
            account_id="sample-paper", exchange="KRX"
        )
        bot = _make_running_bot(
            account_id="sample-paper",
            positions={
                "005930": {"symbol": "005930", "quantity": 1, "avg_entry_price": 70000},
            },
        )
        bot_manager.get_bot.return_value = bot
        result = await receiver._cmd_stop(["bot-1"])
        assert "005930 (삼성전자)" in result
        # bot.config.account_id 로 계좌를 조회해 exchange 를 얻는다.
        account_service.get.assert_awaited_once_with("sample-paper")
        instrument_service.format_label.assert_any_call("005930", "KRX", markdown=False)

    async def test_stop_bot_label_cache_miss_no_name(self, receiver, bot_manager):
        """#2385: TEST/non-KRX(캐시 미스) → 이름 누락·오표기 없이 symbol-only."""
        bot = _make_running_bot(
            positions={
                # 캐시에 없는 TEST 더미 종목 → 종목명 병기 없이 코드만.
                "000001": {"symbol": "000001", "quantity": 1, "avg_entry_price": 1000},
            },
        )
        bot_manager.get_bot.return_value = bot
        result = await receiver._cmd_stop(["bot-1"])
        assert "보유: 000001" in result
        # 괄호 종목명 병기가 붙지 않아야 한다 (오표기 금지).
        assert "000001 (" not in result

    async def test_stop_bot_label_exchange_lookup_failure_falls_back_to_krx(
        self, receiver, bot_manager, account_service, instrument_service
    ):
        """#2385: account 조회 실패 → KRX 폴백, stop 성공이 reply 실패로 번지지 않음."""
        account_service.get.side_effect = RuntimeError("account lookup down")
        bot = _make_running_bot(
            positions={
                "005930": {"symbol": "005930", "quantity": 1, "avg_entry_price": 70000},
            },
        )
        bot_manager.get_bot.return_value = bot
        # 예외 없이 응답을 구성해야 한다.
        result = await receiver._cmd_stop(["bot-1"])
        assert "봇 중지" in result
        # KRX 폴백으로 종목명 병기 성공.
        assert "005930 (삼성전자)" in result
        instrument_service.format_label.assert_any_call("005930", "KRX", markdown=False)

    async def test_stop_bot_label_no_instrument_service_fallback(
        self, receiver, bot_manager
    ):
        """#2385: instrument_service=None → 기존 ', '.join(symbols) fallback 회귀."""
        receiver._instrument_service = None
        bot = _make_running_bot(
            positions={
                "005930": {"symbol": "005930", "quantity": 1, "avg_entry_price": 70000},
                "035720": {"symbol": "035720", "quantity": 5, "avg_entry_price": 50000},
            },
        )
        bot_manager.get_bot.return_value = bot
        result = await receiver._cmd_stop(["bot-1"])
        # 종목명 병기 없이 코드만 콤마 결합.
        assert "보유: 005930, 035720" in result
        assert "(삼성전자)" not in result

    async def test_stop_bot_already_stopped(self, receiver, bot_manager):
        """이미 중지된 봇은 안내 메시지 반환."""
        from ante.bot.config import BotStatus

        bot = MagicMock()
        bot.status = BotStatus.STOPPED
        bot_manager.get_bot.return_value = bot
        result = await receiver._cmd_stop(["bot-1"])
        assert "이미 중지된 봇입니다" in result
        bot_manager.stop_bot.assert_not_called()

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

    async def test_stop_bot_name_fallback(self, receiver, bot_manager):
        """봇 이름이 빈 문자열이면 bot_id로 대체."""
        bot = _make_running_bot(name="")
        bot_manager.get_bot.return_value = bot
        result = await receiver._cmd_stop(["bot-1"])
        assert "bot-1 (bot-1)" in result


# ── US-4: 2단계 확인 ─────────────────────────────


class TestConfirmation:
    """위험 명령 확인 절차 테스트."""

    def test_dangerous_commands_set_includes_clear_halt(self):
        """``_DANGEROUS_COMMANDS``에 ``clear_halt`` 포함 (Refs #1213).

        SSOT: ``docs/specs/notification/notification.md`` 위험 명령 표.
        ``halt``, ``clear_halt``, ``stop`` 모두 2단계 확인 대상이다.
        """
        from ante.notification.telegram_receiver import _DANGEROUS_COMMANDS

        assert _DANGEROUS_COMMANDS == {"halt", "clear_halt", "stop"}

    async def test_halt_requires_confirm(self, receiver):
        """halt 명령은 확인을 요구한다."""
        result = await receiver._execute("halt", ["긴급"], 12345, 100)
        assert "/confirm" in result
        assert "긴급" in result
        assert 12345 in receiver._pending_confirm

    async def test_clear_halt_requires_confirm(self, receiver, account_service):
        """clear_halt 명령은 확인을 요구한다 (Refs #1213, SSOT 위험 명령).

        SSOT: ``docs/specs/notification/notification.md`` 위험 명령 표.
        """
        from ante.account.models import AccountStatus

        # SUSPENDED 상태에서 호출해야 confirmation까지 도달.
        suspended_account = SimpleNamespace(
            account_id="test", status=AccountStatus.SUSPENDED
        )
        account_service.list.return_value = [suspended_account]
        result = await receiver._execute("clear_halt", [], 12345, 100)
        assert "/confirm" in result
        assert "정지" in result
        assert "자동 재시작" in result
        assert 12345 in receiver._pending_confirm
        # confirmation 단계이므로 activate_all은 아직 호출되지 않아야 한다.
        account_service.activate_all.assert_not_called()

    async def test_clear_halt_short_circuits_when_already_active(
        self, receiver, account_service
    ):
        """이미 ACTIVE이면 confirmation 없이 즉시 안내."""
        # fixture default is ACTIVE
        result = await receiver._execute("clear_halt", [], 12345, 100)
        assert "이미 거래가 활성 상태입니다" in result
        assert 12345 not in receiver._pending_confirm
        account_service.activate_all.assert_not_called()

    async def test_halt_with_unpersisted_suspension_requires_confirm(
        self, receiver, account_service
    ):
        """모두 정지여도 DB에 기록되지 않은 정지가 있으면 확인으로 간다 (#2858)."""
        from ante.account.models import AccountStatus

        account_service.list.return_value = [
            SimpleNamespace(account_id="test", status=AccountStatus.SUSPENDED)
        ]
        account_service.has_unpersisted_suspensions.return_value = True

        result = await receiver._execute("halt", ["재시도"], 12345, 100)

        assert "/confirm" in result
        assert 12345 in receiver._pending_confirm
        account_service.suspend_all.assert_not_called()

    async def test_cmd_halt_with_unpersisted_suspension_calls_suspend_all(
        self, receiver, account_service
    ):
        """미기록 정지가 있으면 ``_cmd_halt``가 ``suspend_all``을 부른다 (#2858)."""
        from ante.account.models import AccountStatus

        account_service.list.return_value = [
            SimpleNamespace(account_id="test", status=AccountStatus.SUSPENDED)
        ]
        account_service.has_unpersisted_suspensions.return_value = True

        result = await receiver._cmd_halt(["재시도"])

        assert "중지되었습니다" in result
        account_service.suspend_all.assert_called_once_with(
            reason="재시도", suspended_by="telegram"
        )

    async def test_stop_requires_confirm(self, receiver):
        """stop 명령은 확인을 요구한다."""
        result = await receiver._execute("stop", ["bot-1"], 12345, 100)
        assert "/confirm" in result
        assert "bot-1" in result

    async def test_confirm_executes_halt(self, receiver, account_service):
        """confirm으로 halt가 실행된다."""
        # 먼저 halt 요청
        await receiver._execute("halt", ["점검"], 12345, 100)
        # confirm 실행
        result = await receiver._handle_confirm(12345)
        assert "중지되었습니다" in result
        account_service.suspend_all.assert_called_once_with(
            reason="점검", suspended_by="telegram"
        )

    async def test_confirm_executes_clear_halt(self, receiver, account_service):
        """confirm으로 clear_halt가 실행된다 (Refs #1213).

        clear_halt는 SSOT 위험 명령이므로 ``/confirm`` 분기에서 실행되어야 한다.
        """
        from ante.account.models import AccountStatus

        suspended_account = SimpleNamespace(
            account_id="test", status=AccountStatus.SUSPENDED
        )
        account_service.list.return_value = [suspended_account]

        await receiver._execute("clear_halt", [], 12345, 100)
        result = await receiver._handle_confirm(12345)
        assert "정지가 해제" in result
        # SSOT: 봇 자동 재시작 없음
        assert "자동 재시작되지 않습니다" in result
        account_service.activate_all.assert_called_once_with(activated_by="telegram")

    async def test_confirm_halt_reports_partial_failure(
        self, receiver, account_service
    ):
        """일괄 정지의 부분 실패는 성공 문구 대신 실패한 계좌를 답한다."""
        from ante.account.errors import AccountSuspendAllFailedError

        account_service.suspend_all = AsyncMock(
            side_effect=AccountSuspendAllFailedError(("acc2",), 1)
        )
        await receiver._execute("halt", ["점검"], 12345, 100)
        result = await receiver._handle_confirm(12345)
        assert "일부 계좌에서 실패" in result
        assert "acc2" in result
        assert "사유: 점검" in result
        assert "중지되었습니다" not in result

    async def test_confirm_clear_halt_reports_stopped_midway(
        self, receiver, account_service
    ):
        """일괄 활성화가 멈추면 성공 문구 대신 멈춘 계좌를 답한다."""
        from ante.account.errors import AccountActivateAllFailedError
        from ante.account.models import AccountStatus

        account_service.list.return_value = [
            SimpleNamespace(account_id="test", status=AccountStatus.SUSPENDED)
        ]
        account_service.activate_all = AsyncMock(
            side_effect=AccountActivateAllFailedError("acc2", 1)
        )
        await receiver._execute("clear_halt", [], 12345, 100)
        result = await receiver._handle_confirm(12345)
        assert "중간에 멈췄습니다" in result
        assert "acc2" in result
        assert "정지가 해제되었습니다" not in result

    async def test_confirm_executes_stop(self, receiver, bot_manager):
        """confirm으로 stop이 실행된다."""
        await receiver._execute("stop", ["bot-1"], 12345, 100)
        result = await receiver._handle_confirm(12345)
        assert "봇 중지" in result
        assert "실행 중 → 중지됨" in result
        bot_manager.stop_bot.assert_called_once_with(
            "bot-1", suppress_notification=True
        )

    async def test_confirm_no_pending(self, receiver):
        """대기 중인 명령이 없으면 안내 메시지."""
        result = await receiver._handle_confirm(12345)
        assert "대기 중인 명령이 없습니다" in result

    async def test_confirm_timeout(self, receiver, manual_clock):
        """확인 시간이 초과되면 실행 거부."""
        await receiver._execute("halt", [], 12345, 100)
        manual_clock.advance(60)
        result = await receiver._handle_confirm(12345)
        assert "시간이 초과" in result

    async def test_confirm_within_timeout(
        self, receiver, account_service, manual_clock
    ):
        """타임아웃 내에 확인하면 실행."""
        await receiver._execute("halt", [], 12345, 100)
        manual_clock.advance(5)
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
        receiver._pending_confirm[12345] = ("halt", [], clock.monotonic())
        receiver._pending_confirm[67890] = ("stop", ["bot-1"], clock.monotonic())

        result = await receiver._handle_confirm(12345)
        assert "중지되었습니다" in result
        assert 67890 in receiver._pending_confirm

    async def test_confirm_expires_when_wall_clock_moves_back(
        self, receiver, account_service
    ):
        """벽시계가 뒤로 조정돼도 단조 경과가 기한을 넘으면 거부한다 (#2935)."""
        with clock.use_clock(ManualClock(DEFAULT_MANUAL_CLOCK_AT, monotonic=1000.0)):
            await receiver._execute("halt", [], 12345, 100)
        moved_back = ManualClock(
            DEFAULT_MANUAL_CLOCK_AT - timedelta(hours=1), monotonic=1060.0
        )
        with clock.use_clock(moved_back):
            result = await receiver._handle_confirm(12345)
        assert "시간이 초과" in result
        account_service.suspend_all.assert_not_called()

    async def test_confirm_within_timeout_when_wall_clock_moves_forward(
        self, receiver, account_service
    ):
        """벽시계가 앞으로 조정돼도 단조 경과가 기한 안이면 실행한다 (#2935)."""
        with clock.use_clock(ManualClock(DEFAULT_MANUAL_CLOCK_AT, monotonic=1000.0)):
            await receiver._execute("halt", [], 12345, 100)
        moved_forward = ManualClock(
            DEFAULT_MANUAL_CLOCK_AT + timedelta(hours=1), monotonic=1005.0
        )
        with clock.use_clock(moved_forward):
            result = await receiver._handle_confirm(12345)
        assert "중지되었습니다" in result

    async def test_confirm_at_exact_timeout_executes(
        self, receiver, account_service, manual_clock
    ):
        """경과가 기한과 같으면 실행한다."""
        await receiver._execute("halt", [], 12345, 100)
        manual_clock.advance(30)
        result = await receiver._handle_confirm(12345)
        assert "중지되었습니다" in result

    async def test_confirm_just_past_timeout_rejected(
        self, receiver, account_service, manual_clock
    ):
        """경과가 기한을 조금이라도 넘으면 거부한다."""
        await receiver._execute("halt", [], 12345, 100)
        manual_clock.advance(30.001)
        result = await receiver._handle_confirm(12345)
        assert "시간이 초과" in result
        account_service.suspend_all.assert_not_called()


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


# ── US-1: 묶음 안의 업데이트 단위 격리 (#3012) ──────


_FAILURE_TEXT = "처리 중 오류가 발생했습니다"
_SECRET = "SECRET-CAUSE-3012"


class _FakeResponse:
    def __init__(self, data: dict | None = None) -> None:
        self.status = 200
        self._data = data

    async def json(self) -> dict | None:
        return self._data

    async def __aenter__(self) -> _FakeResponse:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False


class _FakeTelegramSession:
    """첫 getUpdates에 묶음을, 두 번째에 빈 결과를 주고 루프를 멈추는 가짜 세션."""

    def __init__(self, receiver: TelegramCommandReceiver, batch: list) -> None:
        self._receiver = receiver
        self._batch = batch
        self.get_params: list[dict] = []
        self.posts: list[tuple[str, dict]] = []

    async def __aenter__(self) -> _FakeTelegramSession:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    def get(self, url: str, params: dict | None = None, timeout: object = None):
        self.get_params.append(dict(params or {}))
        if len(self.get_params) == 1:
            return _FakeResponse({"ok": True, "result": self._batch})
        self._receiver._running = False
        return _FakeResponse({"ok": True, "result": []})

    def post(self, url: str, json: dict | None = None):
        self.posts.append((url.rsplit("/", 1)[-1], dict(json or {})))
        return _FakeResponse({"ok": True})

    def sent(self, method: str = "sendMessage") -> list[dict]:
        return [payload for name, payload in self.posts if name == method]


def _msg(update_id: int, user_id: int, chat_id: int, text: str) -> dict:
    return {
        "update_id": update_id,
        "message": {"text": text, "from": {"id": user_id}, "chat": {"id": chat_id}},
    }


class TestPollingBatchIsolation:
    """한 업데이트의 예외가 같은 묶음의 뒤 업데이트를 버리지 않는다 (#3012)."""

    @pytest.fixture
    def poll_receiver(self, bot_manager, treasury_manager, account_service):
        from ante.notification.telegram import TelegramAdapter

        return TelegramCommandReceiver(
            adapter=TelegramAdapter(bot_token="TEST", chat_id="0"),
            allowed_user_ids=[12345, 67890],
            polling_interval=0,
            confirm_timeout=30.0,
            bot_manager=bot_manager,
            treasury_manager=treasury_manager,
            account_service=account_service,
        )

    async def _run(self, receiver: TelegramCommandReceiver, batch: list):
        session = _FakeTelegramSession(receiver, batch)
        receiver._running = True
        with patch("aiohttp.ClientSession", return_value=session):
            await asyncio.wait_for(receiver._poll_loop(), timeout=5)
        return session

    async def test_halt_after_failing_command_gets_prompt(
        self, poll_receiver, bot_manager
    ):
        """재현 1: [예외를 내는 /bots, /halt] → /halt의 확인 프롬프트가 간다."""
        bot_manager.list_bots.side_effect = RuntimeError(_SECRET)
        session = await self._run(
            poll_receiver, [_msg(1, 12345, 100, "/bots"), _msg(2, 12345, 100, "/halt")]
        )

        sent = session.sent()
        assert [p["chat_id"] for p in sent] == [100, 100]
        assert sent[0]["text"] == _UPDATE_FAILURE_REPLY
        assert "/confirm" in sent[1]["text"]
        assert poll_receiver._pending_confirm[12345][0] == "halt"
        assert all(_SECRET not in p["text"] for p in sent)
        assert bot_manager.list_bots.call_count == 1

    async def test_other_users_confirm_after_failing_confirm_runs_halt(
        self, poll_receiver, bot_manager, account_service
    ):
        """재현 2: 예외를 내는 /confirm 뒤 다른 사용자의 /confirm이 halt를 실행한다."""
        bot_manager.stop_bot.side_effect = RuntimeError(_SECRET)
        now = clock.monotonic()
        poll_receiver._pending_confirm[12345] = ("stop", ["bot-1"], now)
        poll_receiver._pending_confirm[67890] = ("halt", [], now)

        session = await self._run(
            poll_receiver,
            [_msg(1, 12345, 100, "/confirm"), _msg(2, 67890, 200, "/confirm")],
        )

        assert bot_manager.stop_bot.call_count == 1
        account_service.suspend_all.assert_awaited_once()
        sent = session.sent()
        assert [p["chat_id"] for p in sent] == [100, 200]
        assert _FAILURE_TEXT in sent[0]["text"]
        assert "전체 거래가 중지되었습니다" in sent[1]["text"]
        assert all(_SECRET not in p["text"] for p in sent)
        assert poll_receiver._pending_confirm == {}

    async def test_control_batch_replies_both(self, poll_receiver):
        """대조군: [/help, /halt] → 두 답 모두 정상."""
        session = await self._run(
            poll_receiver, [_msg(1, 12345, 100, "/help"), _msg(2, 12345, 100, "/halt")]
        )

        sent = session.sent()
        assert len(sent) == 2
        assert "사용 가능한 명령어" in sent[0]["text"]
        assert "/confirm" in sent[1]["text"]
        assert session.sent("answerCallbackQuery") == []

    async def test_offset_advances_once_and_nothing_reprocessed(
        self, poll_receiver, bot_manager
    ):
        """offset은 묶음 끝 + 1로 오르고 어떤 업데이트도 두 번 처리되지 않는다."""
        bot_manager.list_bots.side_effect = RuntimeError(_SECRET)
        handled: list[int] = []
        original = poll_receiver._handle_update

        async def _spy(update):
            handled.append(update["update_id"])
            await original(update)

        poll_receiver._handle_update = _spy
        session = await self._run(
            poll_receiver,
            [_msg(7, 12345, 100, "/bots"), _msg(8, 12345, 100, "/help")],
        )

        assert [p["offset"] for p in session.get_params] == [0, 9]
        assert handled == [7, 8]
        assert len(session.sent()) == 2

    async def test_failed_confirm_is_not_rerun_by_next_confirm(
        self, poll_receiver, bot_manager
    ):
        """예외로 끝난 /confirm 뒤 같은 사용자의 /confirm은 대기 항목이 없다."""
        bot_manager.stop_bot.side_effect = RuntimeError(_SECRET)
        poll_receiver._pending_confirm[12345] = ("stop", ["bot-1"], clock.monotonic())

        session = await self._run(
            poll_receiver,
            [_msg(1, 12345, 100, "/confirm"), _msg(2, 12345, 100, "/confirm")],
        )

        assert bot_manager.stop_bot.call_count == 1
        sent = session.sent()
        assert len(sent) == 2
        assert _FAILURE_TEXT in sent[0]["text"]
        assert sent[1]["text"] == "확인 대기 중인 명령이 없습니다."

    async def test_failure_reply_error_does_not_block_next_update(
        self, poll_receiver, bot_manager
    ):
        """실패 답의 전송이 예외를 내도 다음 업데이트는 처리된다."""
        bot_manager.list_bots.side_effect = RuntimeError(_SECRET)
        original_reply = poll_receiver._reply

        async def _reply(chat_id, text):
            if _FAILURE_TEXT in text:
                raise RuntimeError("reply failed")
            await original_reply(chat_id, text)

        poll_receiver._reply = _reply
        session = await self._run(
            poll_receiver, [_msg(1, 12345, 100, "/bots"), _msg(2, 12345, 100, "/halt")]
        )

        sent = session.sent()
        assert len(sent) == 1
        assert "/confirm" in sent[0]["text"]

    async def test_non_dict_update_does_not_drop_rest(self, poll_receiver):
        """dict가 아닌 업데이트가 끼어도 뒤 업데이트는 처리되고 그것엔 답이 없다."""
        session = await self._run(poll_receiver, [42, _msg(2, 12345, 100, "/help")])

        sent = session.sent()
        assert len(sent) == 1
        assert "사용 가능한 명령어" in sent[0]["text"]
        assert session.sent("answerCallbackQuery") == []

    async def test_broken_callback_answers_with_failure(self, poll_receiver):
        """콜백 업데이트의 예외에는 콜백 응답이 실패 문구로 간다."""
        broken = {
            "update_id": 1,
            "callback_query": {
                "id": "cb9",
                "from": {"id": 12345},
                "message": "broken",
                "data": "approve:x",
            },
        }
        session = await self._run(poll_receiver, [broken, _msg(2, 12345, 100, "/help")])

        answers = session.sent("answerCallbackQuery")
        assert len(answers) == 1
        assert answers[0]["callback_query_id"] == "cb9"
        assert _FAILURE_TEXT in answers[0]["text"]
        sent = session.sent()
        assert len(sent) == 1
        assert "사용 가능한 명령어" in sent[0]["text"]

    async def test_unauthorized_failing_updates_get_no_reply(self, poll_receiver):
        """미인가 사용자의 예외로 끝난 업데이트에는 답이 없다."""
        broken_callback = {
            "update_id": 1,
            "callback_query": {
                "id": "cb9",
                "from": {"id": 99999},
                "message": "broken",
                "data": "approve:x",
            },
        }
        broken_message = {
            "update_id": 2,
            "message": {"text": "/bots", "from": {"id": 99999}, "chat": "broken"},
        }
        session = await self._run(
            poll_receiver,
            [broken_callback, broken_message, _msg(3, 12345, 100, "/help")],
        )

        assert session.sent("answerCallbackQuery") == []
        sent = session.sent()
        assert len(sent) == 1
        assert sent[0]["chat_id"] == 100

    async def test_cancelled_error_is_not_isolated(self, poll_receiver):
        """업데이트 처리 중 작업 취소는 가둬지지 않고 루프 밖으로 나간다."""
        poll_receiver._handle_update = AsyncMock(side_effect=asyncio.CancelledError)
        session = _FakeTelegramSession(
            poll_receiver,
            [_msg(1, 12345, 100, "/help"), _msg(2, 12345, 100, "/help")],
        )
        poll_receiver._running = True
        with patch("aiohttp.ClientSession", return_value=session):
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(poll_receiver._poll_loop(), timeout=5)

        assert poll_receiver._handle_update.await_count == 1
        assert session.sent() == []

    async def test_stop_is_not_blocked_while_update_in_flight(self, poll_receiver):
        """업데이트 처리 중 stop()은 남은 업데이트로 넘어가지 않고 끝난다."""
        entered = asyncio.Event()
        calls: list[int] = []

        async def _blocking(update):
            calls.append(update["update_id"])
            entered.set()
            await asyncio.Event().wait()

        poll_receiver._handle_update = _blocking
        session = _FakeTelegramSession(
            poll_receiver,
            [_msg(1, 12345, 100, "/help"), _msg(2, 12345, 100, "/help")],
        )
        with patch("aiohttp.ClientSession", return_value=session):
            poll_receiver.start()
            await asyncio.wait_for(entered.wait(), timeout=5)
            await asyncio.wait_for(poll_receiver.stop(), timeout=5)

        assert poll_receiver._task is None
        assert calls == [1]
        assert session.sent() == []


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

    async def test_full_halt_confirm_flow(self, receiver, account_service):
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
        reply_text = receiver._reply.call_args[0][1]
        assert "중지되었습니다" in reply_text
        # Refs #1213: 안내는 /clear_halt로 정렬 (legacy /activate 제거).
        assert "/clear_halt" in reply_text
        assert "/activate" not in reply_text
        account_service.suspend_all.assert_called_once_with(
            reason="긴급 점검", suspended_by="telegram"
        )

    async def test_halt_already_halted(self, receiver, account_service):
        """이미 모든 계좌가 SUSPENDED 상태이면 중복 메시지를 반환한다."""
        from ante.account.models import AccountStatus

        suspended_account = SimpleNamespace(
            account_id="test", status=AccountStatus.SUSPENDED
        )
        account_service.list.return_value = [suspended_account]

        receiver._reply = AsyncMock()

        halt_update = {
            "message": {
                "text": "/halt",
                "from": {"id": 12345},
                "chat": {"id": 100},
            }
        }
        await receiver._handle_update(halt_update)

        # confirm 없이 즉시 응답
        assert receiver._reply.call_count == 1
        assert "이미 거래가 중지된 상태입니다" in receiver._reply.call_args[0][1]
        account_service.suspend_all.assert_not_called()

    async def test_full_clear_halt_confirm_flow(self, receiver, account_service):
        """clear_halt → confirm → 실제 실행 흐름 (Refs #1213).

        SSOT: ``docs/specs/notification/notification.md`` 위험 명령 표.
        ``/clear_halt``는 2단계 확인 후 ``activate_all``을 호출하며,
        BotManager 자동 재시작은 수행되지 않는다 (회귀 가드).
        """
        from ante.account.models import AccountStatus

        suspended_account = SimpleNamespace(
            account_id="test", status=AccountStatus.SUSPENDED
        )
        account_service.list.return_value = [suspended_account]

        receiver._reply = AsyncMock()

        clear_halt_update = {
            "message": {
                "text": "/clear_halt",
                "from": {"id": 12345},
                "chat": {"id": 100},
            }
        }
        await receiver._handle_update(clear_halt_update)
        assert receiver._reply.call_count == 1
        assert "/confirm" in receiver._reply.call_args[0][1]
        # 확인 단계에서는 activate_all이 호출되지 않는다.
        account_service.activate_all.assert_not_called()

        confirm_update = {
            "message": {
                "text": "/confirm",
                "from": {"id": 12345},
                "chat": {"id": 100},
            }
        }
        await receiver._handle_update(confirm_update)
        assert receiver._reply.call_count == 2
        reply_text = receiver._reply.call_args[0][1]
        assert "정지가 해제" in reply_text
        assert "자동 재시작되지 않습니다" in reply_text
        account_service.activate_all.assert_called_once_with(activated_by="telegram")

    async def test_clear_halt_does_not_restart_bots(
        self, receiver, account_service, bot_manager
    ):
        """clear_halt 실행 후 BotManager 자동 재시작이 호출되지 않음 (Refs #1213).

        Kill Switch 응답은 "계좌 상태만 복구하며 봇 자동 재시작은 수행하지 않는다".
        BotManager는 ``AccountActivatedEvent`` 수신 시 로깅만 수행한다.
        """
        from ante.account.models import AccountStatus

        suspended_account = SimpleNamespace(
            account_id="test", status=AccountStatus.SUSPENDED
        )
        account_service.list.return_value = [suspended_account]

        await receiver._cmd_clear_halt([])

        account_service.activate_all.assert_called_once_with(activated_by="telegram")
        # BotManager 자동 재시작 메서드들이 호출되지 않아야 한다.
        bot_manager.start_bot.assert_not_called()
        bot_manager.restart_bot.assert_not_called()
        bot_manager.start_all.assert_not_called()
        bot_manager.start.assert_not_called()

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


# ── CHAT_ID 기반 초기화 ──────────────────────────


class TestChatIdBasedInit:
    """TELEGRAM_CHAT_ID 환경변수 기반 초기화 테스트 (Refs #997)."""

    def test_chat_id_as_allowed_user(self, adapter):
        """CHAT_ID를 allowed_user_ids로 사용하면 해당 ID가 인가된다."""
        chat_id = 987654321
        r = TelegramCommandReceiver(
            adapter=adapter,
            allowed_user_ids=[chat_id],
            polling_interval=3.0,
            confirm_timeout=30.0,
        )
        assert r._is_authorized(chat_id) is True
        assert r._is_authorized(12345) is False

    async def test_start_with_chat_id(self, adapter, bot_manager, account_service):
        """chat_id가 설정되면 receiver가 정상 시작된다."""
        r = TelegramCommandReceiver(
            adapter=adapter,
            allowed_user_ids=[111222333],
            polling_interval=3.0,
            confirm_timeout=30.0,
            bot_manager=bot_manager,
            account_service=account_service,
        )
        r.start()
        assert r._task is not None
        assert r._running is True
        # 정리
        r._running = False
        r._task.cancel()

    def test_empty_chat_id_no_start(self, adapter):
        """allowed_user_ids가 비면 시작하지 않는다."""
        r = TelegramCommandReceiver(
            adapter=adapter,
            allowed_user_ids=[],
            polling_interval=3.0,
            confirm_timeout=30.0,
        )
        r.start()
        assert r._task is None
