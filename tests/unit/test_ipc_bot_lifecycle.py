"""IPC handlers ``bot.start`` / ``bot.stop`` / ``bot.status`` 검증 (#1712).

검증 대상:
- 정상 경로: ``{bot: info}`` envelope 반환.
- 거부 경로 coded exception:
  - ``BotNotFoundError`` (code=BOT_NOT_FOUND).
  - ``BotAccountCredentialsNotConfigured``
    (code=BOT_ACCOUNT_CREDENTIALS_NOT_CONFIGURED).
  - ``BotStateConflict`` (code=BOT_STATE_CONFLICT).
- audit detail handover (#1851):
  - ``bot.start`` / ``bot.stop`` 성공 시 handler 반환 dict 안의 reserved key
    ``_audit_detail`` 에 ``resource=f"bot:{bot_id}"`` 가 채워져 있다 — 실제
    audit 호출은 ``_dispatch`` wrapper 가 ``CommandSpec.audit_action`` 기반으로
    수행한다.
  - ``bot.status`` 는 read-only — ``_audit_detail`` 자체가 없다.
- ``trade_service`` optional:
  - 주입 시 positions 보강.
  - 부재 시 ``positions`` 키 부재(회귀 lock, #1712 cold-path 호환).
- ``CommandRegistry`` 등록 invariant: taxonomy(start/stop=mutating,
  status=read-only), 27 count.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from ante.bot.exceptions import (
    BOT_ACCOUNT_CREDENTIALS_NOT_CONFIGURED_CODE,
    BOT_NOT_FOUND_CODE,
    BOT_STATE_CONFLICT_CODE,
    BotAccountCredentialsNotConfigured,
    BotError,
    BotNotFoundError,
    BotStateConflict,
)
from ante.ipc.registry import (
    CommandRegistry,
    _handle_bot_start,
    _handle_bot_status,
    _handle_bot_stop,
    register_all_handlers,
)


def _make_bot(
    *,
    bot_id: str = "bot-1",
    account_id: str = "acc-1",
    info: dict | None = None,
) -> SimpleNamespace:
    """Bot stub — ``get_info()`` / ``config.account_id`` / ``bot_id`` 노출."""
    bot_info = info if info is not None else {"bot_id": bot_id, "status": "stopped"}
    return SimpleNamespace(
        bot_id=bot_id,
        config=SimpleNamespace(account_id=account_id),
        get_info=MagicMock(return_value=bot_info),
    )


def _make_svc(
    *,
    bot: SimpleNamespace | None,
    account: SimpleNamespace | None = None,
    start_side_effect: Exception | None = None,
    stop_side_effect: Exception | None = None,
    with_audit_logger: bool = True,
    strategy_registry: object | None = None,
    treasury_manager: object | None = None,
    trade_service: object | None = None,
) -> tuple[SimpleNamespace, AsyncMock | None]:
    """ServiceRegistry-shaped stub.

    ``svc.bot_manager.get_bot(bot_id)`` 는 주어진 ``bot`` 을 반환한다(None 가능).
    """
    bot_manager = MagicMock()
    bot_manager.get_bot = MagicMock(return_value=bot)
    bot_manager.start_bot = AsyncMock(side_effect=start_side_effect)
    bot_manager.stop_bot = AsyncMock(side_effect=stop_side_effect)

    account_service = MagicMock()
    if account is not None:
        account_service.get = AsyncMock(return_value=account)
    else:
        account_service.get = AsyncMock(return_value=None)

    audit_log: AsyncMock | None
    if with_audit_logger:
        audit_logger = MagicMock()
        audit_logger.log = AsyncMock()
        audit_log = audit_logger.log
    else:
        audit_logger = None
        audit_log = None

    svc = SimpleNamespace(
        bot_manager=bot_manager,
        account=account_service,
        audit_logger=audit_logger,
        strategy_registry=strategy_registry,
        treasury_manager=treasury_manager,
        trade_service=trade_service,
    )
    return svc, audit_log


# ── bot.start ────────────────────────────────────────


class TestHandleBotStart:
    """``_handle_bot_start`` 정상 + 거부 경로."""

    async def test_success_returns_bot_envelope(self) -> None:
        """성공 시 ``{"bot": info, "_audit_detail": {...}}`` envelope.

        Refs #1851: handler 본문은 더 이상 ``audit_logger.log`` 를 직접
        호출하지 않는다 — ``_audit_detail`` reserved key 로 wrapper 에 audit
        detail 만 넘긴다. 실제 audit 발화 + reserved key strip 은 ``_dispatch``
        wrapper 가 envelope 생성 전에 수행한다(통합 검증은
        ``test_dispatch_wrapper_audit.py``).
        """
        bot = _make_bot(bot_id="bot-1", account_id="acc-1")
        account = SimpleNamespace(credentials={"app_key": "AK-XYZ"})
        svc, audit_log = _make_svc(bot=bot, account=account)

        result = await _handle_bot_start(svc, {"bot_id": "bot-1"}, "admin-master")

        assert result == {
            "bot": {"bot_id": "bot-1", "status": "stopped"},
            "_audit_detail": {
                "resource": "bot:bot-1",
                "detail": "",
                "ip": "",
            },
        }
        svc.bot_manager.start_bot.assert_awaited_once_with("bot-1")
        # handler 본문은 audit 호출을 더 이상 직접 수행하지 않는다(#1851).
        assert audit_log is not None
        audit_log.assert_not_awaited()

    async def test_missing_bot_raises_bot_not_found(self) -> None:
        """봇 부재 → ``BotNotFoundError`` (code=BOT_NOT_FOUND)."""
        svc, _ = _make_svc(bot=None)

        with pytest.raises(BotNotFoundError) as exc:
            await _handle_bot_start(svc, {"bot_id": "missing"}, "admin-master")

        assert exc.value.code == BOT_NOT_FOUND_CODE
        svc.bot_manager.start_bot.assert_not_awaited()

    async def test_missing_app_key_raises_credentials_error(self) -> None:
        """app_key 부재 → ``BotAccountCredentialsNotConfigured``."""
        bot = _make_bot()
        account = SimpleNamespace(credentials={})  # app_key 누락
        svc, audit_log = _make_svc(bot=bot, account=account)

        with pytest.raises(BotAccountCredentialsNotConfigured) as exc:
            await _handle_bot_start(svc, {"bot_id": "bot-1"}, "admin-master")

        assert exc.value.code == BOT_ACCOUNT_CREDENTIALS_NOT_CONFIGURED_CODE
        svc.bot_manager.start_bot.assert_not_awaited()
        # 거부된 경우 audit 호출 없음
        assert audit_log is not None
        audit_log.assert_not_awaited()

    async def test_bot_error_raises_state_conflict(self) -> None:
        """``BotManager.start_bot`` 의 ``BotError`` → ``BotStateConflict``."""
        bot = _make_bot()
        account = SimpleNamespace(credentials={"app_key": "AK"})
        svc, audit_log = _make_svc(
            bot=bot,
            account=account,
            start_side_effect=BotError("이미 실행 중인 봇입니다: bot-1"),
        )

        with pytest.raises(BotStateConflict) as exc:
            await _handle_bot_start(svc, {"bot_id": "bot-1"}, "admin-master")

        assert exc.value.code == BOT_STATE_CONFLICT_CODE
        # raised from BotError
        assert isinstance(exc.value.__cause__, BotError)
        assert audit_log is not None
        audit_log.assert_not_awaited()

    async def test_succeeds_when_audit_logger_is_none(self) -> None:
        """``audit_logger=None`` 환경에서도 핸들러는 정상 성공.

        Refs #1851: handler 가 audit 를 직접 호출하지 않으므로 ``audit_logger``
        부재가 handler 정상 경로에 영향을 주지 않는다. ``_audit_detail`` 만
        envelope 에 담겨 반환되며, wrapper 가 ``audit_logger`` 부재를 감지하면
        skip 한다(``test_audit_action_without_audit_logger_no_crash``).
        """
        bot = _make_bot()
        account = SimpleNamespace(credentials={"app_key": "AK"})
        svc, _ = _make_svc(bot=bot, account=account, with_audit_logger=False)

        result = await _handle_bot_start(svc, {"bot_id": "bot-1"}, "admin-master")

        assert result == {
            "bot": {"bot_id": "bot-1", "status": "stopped"},
            "_audit_detail": {
                "resource": "bot:bot-1",
                "detail": "",
                "ip": "",
            },
        }
        svc.bot_manager.start_bot.assert_awaited_once_with("bot-1")


# ── bot.stop ─────────────────────────────────────────


class TestHandleBotStop:
    """``_handle_bot_stop`` 정상 + 거부 경로."""

    async def test_success_returns_bot_envelope(self) -> None:
        """성공 시 ``{"bot": info, "_audit_detail": {...}}`` envelope.

        Refs #1851: ``bot.start`` 와 동형 — handler 는 ``_audit_detail`` 만
        반환하고, 실제 audit 발화는 ``_dispatch`` wrapper 가 수행한다.
        """
        bot = _make_bot(bot_id="bot-1")
        svc, audit_log = _make_svc(bot=bot)

        result = await _handle_bot_stop(svc, {"bot_id": "bot-1"}, "admin-master")

        assert result == {
            "bot": {"bot_id": "bot-1", "status": "stopped"},
            "_audit_detail": {
                "resource": "bot:bot-1",
                "detail": "",
                "ip": "",
            },
        }
        svc.bot_manager.stop_bot.assert_awaited_once_with("bot-1")
        # ``bot.stop`` 은 app_key preflight 가 없다 — account_service.get 미호출.
        svc.account.get.assert_not_awaited()
        # handler 본문에서 audit 직접 호출 제거(#1851).
        assert audit_log is not None
        audit_log.assert_not_awaited()

    async def test_missing_bot_raises_bot_not_found(self) -> None:
        """봇 부재 → ``BotNotFoundError`` (code=BOT_NOT_FOUND)."""
        svc, _ = _make_svc(bot=None)

        with pytest.raises(BotNotFoundError) as exc:
            await _handle_bot_stop(svc, {"bot_id": "missing"}, "admin-master")

        assert exc.value.code == BOT_NOT_FOUND_CODE
        svc.bot_manager.stop_bot.assert_not_awaited()

    async def test_bot_error_raises_state_conflict(self) -> None:
        """``BotManager.stop_bot`` 의 ``BotError`` → ``BotStateConflict``."""
        bot = _make_bot()
        svc, audit_log = _make_svc(
            bot=bot,
            stop_side_effect=BotError("실행 중이 아닙니다"),
        )

        with pytest.raises(BotStateConflict) as exc:
            await _handle_bot_stop(svc, {"bot_id": "bot-1"}, "admin-master")

        assert exc.value.code == BOT_STATE_CONFLICT_CODE
        assert isinstance(exc.value.__cause__, BotError)
        assert audit_log is not None
        audit_log.assert_not_awaited()

    async def test_succeeds_when_audit_logger_is_none(self) -> None:
        """``audit_logger=None`` 환경에서도 핸들러는 정상 성공 (#1851)."""
        bot = _make_bot()
        svc, _ = _make_svc(bot=bot, with_audit_logger=False)

        result = await _handle_bot_stop(svc, {"bot_id": "bot-1"}, "admin-master")

        assert result == {
            "bot": {"bot_id": "bot-1", "status": "stopped"},
            "_audit_detail": {
                "resource": "bot:bot-1",
                "detail": "",
                "ip": "",
            },
        }
        svc.bot_manager.stop_bot.assert_awaited_once_with("bot-1")


# ── bot.status ───────────────────────────────────────


class TestHandleBotStatus:
    """``_handle_bot_status`` read-only handler + ``enrich_bot_info`` 보강."""

    async def test_success_with_trade_service_enriches_positions(self) -> None:
        """``trade_service`` 주입 시 positions 보강."""
        bot = _make_bot(
            bot_id="bot-1",
            account_id="acc-1",
            info={"bot_id": "bot-1", "status": "running", "strategy_id": ""},
        )

        position = SimpleNamespace(
            symbol="005930",
            quantity=10,
            avg_entry_price=70000.0,
            realized_pnl=1500.0,
        )
        trade_service = MagicMock()
        trade_service.get_positions = AsyncMock(return_value=[position])

        svc, audit_log = _make_svc(bot=bot, trade_service=trade_service)

        result = await _handle_bot_status(svc, {"bot_id": "bot-1"}, "admin-master")

        assert "positions" in result["bot"]
        assert result["bot"]["positions"] == [
            {
                "symbol": "005930",
                "quantity": 10,
                "avg_entry_price": 70000.0,
                "realized_pnl": 1500.0,
            }
        ]
        trade_service.get_positions.assert_awaited_once_with(
            bot_id="bot-1", include_closed=True
        )
        # read-only — audit 호출 없음
        assert audit_log is not None
        audit_log.assert_not_awaited()

    async def test_success_without_trade_service_omits_positions(self) -> None:
        """``trade_service=None`` 시 positions 키 부재 (회귀 lock)."""
        bot = _make_bot(
            bot_id="bot-1",
            info={"bot_id": "bot-1", "status": "running", "strategy_id": ""},
        )
        svc, _ = _make_svc(bot=bot, trade_service=None)

        result = await _handle_bot_status(svc, {"bot_id": "bot-1"}, "admin-master")

        # ``positions`` 키 자체가 부재 — 빈 리스트로 흡수되는 contract drift 차단.
        assert "positions" not in result["bot"]

    async def test_missing_bot_raises_bot_not_found(self) -> None:
        """봇 부재 → ``BotNotFoundError`` (code=BOT_NOT_FOUND)."""
        svc, _ = _make_svc(bot=None)

        with pytest.raises(BotNotFoundError) as exc:
            await _handle_bot_status(svc, {"bot_id": "missing"}, "admin-master")

        assert exc.value.code == BOT_NOT_FOUND_CODE

    async def test_read_only_does_not_call_audit(self) -> None:
        """read-only handler 는 audit logger 가 주입돼도 호출하지 않는다."""
        bot = _make_bot(info={"bot_id": "bot-1", "strategy_id": ""})
        svc, audit_log = _make_svc(bot=bot)

        await _handle_bot_status(svc, {"bot_id": "bot-1"}, "admin-master")

        assert audit_log is not None
        audit_log.assert_not_awaited()

    async def test_succeeds_when_audit_logger_is_none(self) -> None:
        """``audit_logger=None`` 환경에서도 정상 성공 (read-only 일관성)."""
        bot = _make_bot(info={"bot_id": "bot-1", "strategy_id": ""})
        svc, _ = _make_svc(bot=bot, with_audit_logger=False)

        result = await _handle_bot_status(svc, {"bot_id": "bot-1"}, "admin-master")

        assert result == {"bot": {"bot_id": "bot-1", "strategy_id": ""}}

    async def test_strategy_registry_enriches_strategy_info(self) -> None:
        """``strategy_registry`` 주입 시 strategy 필드 보강."""
        bot = _make_bot(info={"bot_id": "bot-1", "strategy_id": "strat-1"})

        record = SimpleNamespace(
            name="MyStrategy",
            version="1.0",
            author_name="alice",
            author_id="ag-alice",
            description="desc",
        )
        strategy_registry = MagicMock()
        strategy_registry.get = AsyncMock(return_value=record)

        svc, _ = _make_svc(bot=bot, strategy_registry=strategy_registry)

        result = await _handle_bot_status(svc, {"bot_id": "bot-1"}, "admin-master")

        assert result["bot"]["strategy_name"] == "MyStrategy"
        assert result["bot"]["strategy_author_name"] == "alice"
        assert result["bot"]["strategy_author_id"] == "ag-alice"
        assert result["bot"]["strategy"]["version"] == "1.0"
        strategy_registry.get.assert_awaited_once_with("strat-1")

    async def test_treasury_manager_enriches_budget(self) -> None:
        """``treasury_manager`` 가 해당 계좌 Treasury 를 반환하면 budget 보강."""
        bot = _make_bot(account_id="acc-1", info={"bot_id": "bot-1", "strategy_id": ""})

        budget = SimpleNamespace(
            allocated=10000.0,
            spent=2000.0,
            reserved=500.0,
            available=7500.0,
        )
        treasury = MagicMock()
        treasury.get_budget = MagicMock(return_value=budget)

        treasury_manager = MagicMock()
        treasury_manager.get = MagicMock(return_value=treasury)

        svc, _ = _make_svc(bot=bot, treasury_manager=treasury_manager)

        result = await _handle_bot_status(svc, {"bot_id": "bot-1"}, "admin-master")

        assert result["bot"]["budget"] == {
            "allocated": 10000.0,
            "spent": 2000.0,
            "reserved": 500.0,
            "available": 7500.0,
        }
        treasury_manager.get.assert_called_once_with("acc-1")
        treasury.get_budget.assert_called_once_with("bot-1")

    async def test_treasury_manager_missing_account_omits_budget(self) -> None:
        """``treasury_manager.get`` 가 ``KeyError`` 시 budget 키 부재."""
        bot = _make_bot(account_id="acc-1", info={"bot_id": "bot-1", "strategy_id": ""})

        treasury_manager = MagicMock()
        treasury_manager.get = MagicMock(side_effect=KeyError("acc-1"))

        svc, _ = _make_svc(bot=bot, treasury_manager=treasury_manager)

        result = await _handle_bot_status(svc, {"bot_id": "bot-1"}, "admin-master")

        assert "budget" not in result["bot"]


# ── CommandRegistry 등록 invariant ───────────────────


class TestRegistryRegistration:
    """``bot.start`` / ``bot.stop`` / ``bot.status`` 등록 invariant (#1712)."""

    def test_bot_start_registered_as_mutating(self) -> None:
        registry = CommandRegistry()
        register_all_handlers(registry)

        spec = registry.get("bot.start")
        assert spec is not None
        assert spec.is_mutating is True
        assert spec.handler is _handle_bot_start

    def test_bot_stop_registered_as_mutating(self) -> None:
        registry = CommandRegistry()
        register_all_handlers(registry)

        spec = registry.get("bot.stop")
        assert spec is not None
        assert spec.is_mutating is True
        assert spec.handler is _handle_bot_stop

    def test_bot_status_registered_as_read_only(self) -> None:
        registry = CommandRegistry()
        register_all_handlers(registry)

        spec = registry.get("bot.status")
        assert spec is not None
        assert spec.is_mutating is False
        assert spec.handler is _handle_bot_status

    def test_total_command_count_is_27(self) -> None:
        """#1712 이후 CLI/IPC parity mutation 5개를 포함한다."""
        registry = CommandRegistry()
        register_all_handlers(registry)
        assert len(registry.commands) == 27
