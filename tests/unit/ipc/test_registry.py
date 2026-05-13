"""CommandRegistry 테스트."""

import pytest

from ante.ipc.registry import CommandRegistry, CommandSpec, register_all_handlers


@pytest.fixture
def registry() -> CommandRegistry:
    return CommandRegistry()


def test_register_and_get(registry: CommandRegistry) -> None:
    """핸들러 등록 후 조회."""

    async def dummy_handler(svc, args, actor):  # type: ignore[no-untyped-def]
        return {"ok": True}

    registry.register("test.command", dummy_handler, is_mutating=True)
    spec = registry.get("test.command")
    assert spec == CommandSpec(
        name="test.command",
        handler=dummy_handler,
        is_mutating=True,
    )


def test_get_unregistered_returns_none(registry: CommandRegistry) -> None:
    """미등록 커맨드 조회 시 None 반환."""
    assert registry.get("nonexistent.command") is None


def test_commands_property(registry: CommandRegistry) -> None:
    """commands 프로퍼티가 등록된 커맨드 목록을 반환."""

    async def handler(svc, args, actor):  # type: ignore[no-untyped-def]
        return {}

    registry.register("a.command", handler, is_mutating=True)
    registry.register("b.command", handler, is_mutating=False)
    assert set(registry.commands) == {"a.command", "b.command"}


def test_register_all_handlers() -> None:
    """register_all_handlers가 19개 핸들러를 등록 (account.delete 제외).

    `account.delete`는 1.0 IPC 계약에서 제거되어 cold-path CLI에서 직접
    AccountService를 호출한다.

    Refs #1418 → #1472 SPLIT-D: ``approval.cancel_invalid`` 추가 (16번째
    mutating).
    """
    registry = CommandRegistry()
    register_all_handlers(registry)
    assert len(registry.commands) == 19

    expected = {
        "system.halt",
        "system.clear_halt",
        "account.suspend",
        "account.activate",
        "bot.create",
        "bot.remove",
        "treasury.allocate",
        "treasury.deallocate",
        "config.set",
        "approval.request",
        "approval.approve",
        "approval.reject",
        "approval.cancel",
        "approval.cancel_invalid",
        "approval.reopen",
        "broker.status",
        "broker.balance",
        "broker.positions",
        "broker.reconcile",
    }
    assert set(registry.commands) == expected
    # account.delete는 cold-path 전용이므로 IPC 등록 대상이 아니다.
    assert "account.delete" not in registry.commands
    # legacy system.activate는 system.clear_halt로 교체됨 (Refs #1213, #1212 SSOT)
    assert "system.activate" not in registry.commands


def test_register_all_handlers_taxonomy() -> None:
    """등록된 19개 핸들러의 mutating/read-only taxonomy가 스펙과 일치한다."""
    registry = CommandRegistry()
    register_all_handlers(registry)

    mutating = {
        "system.halt",
        "system.clear_halt",
        "account.suspend",
        "account.activate",
        "bot.create",
        "bot.remove",
        "treasury.allocate",
        "treasury.deallocate",
        "config.set",
        "approval.request",
        "approval.approve",
        "approval.reject",
        "approval.cancel",
        "approval.cancel_invalid",
        "approval.reopen",
        "broker.reconcile",
    }
    read_only = {"broker.status", "broker.balance", "broker.positions"}

    assert len(mutating) == 16
    assert len(read_only) == 3
    assert mutating | read_only == set(registry.commands)

    for command in mutating:
        spec = registry.get(command)
        assert spec is not None
        assert spec.is_mutating is True

    for command in read_only:
        spec = registry.get(command)
        assert spec is not None
        assert spec.is_mutating is False


# ── _handle_bot_create 변환 로직 테스트 ──────────────


class TestHandleBotCreate:
    async def test_creates_bot_with_config_and_strategy(self):
        """strategy_id → StrategyLoader → BotConfig → create_bot 변환."""
        from dataclasses import dataclass
        from unittest.mock import AsyncMock, MagicMock

        from ante.ipc.registry import _handle_bot_create

        @dataclass
        class FakeRecord:
            filepath: str = "/tmp/strategy.py"

        fake_registry = AsyncMock()
        fake_registry.get.return_value = FakeRecord()

        fake_bot = MagicMock()
        fake_bot.bot_id = "new-bot"

        fake_bot_manager = AsyncMock()
        fake_bot_manager.create_bot.return_value = fake_bot

        svc = MagicMock()
        svc.strategy_registry = fake_registry
        svc.bot_manager = fake_bot_manager

        # StrategyLoader.load를 모킹
        import ante.strategy.loader

        original_load = ante.strategy.loader.StrategyLoader.load
        ante.strategy.loader.StrategyLoader.load = MagicMock(
            return_value=type("FakeStrategy", (), {})
        )
        try:
            result = await _handle_bot_create(
                svc,
                {
                    "strategy_id": "strat-1",
                    "name": "테스트봇",
                    "account_id": "acct-1",
                    "interval_seconds": 30,
                },
                "cli-user",
            )
        finally:
            ante.strategy.loader.StrategyLoader.load = original_load

        assert result == {"bot_id": "new-bot"}
        fake_registry.get.assert_awaited_once_with("strat-1")
        fake_bot_manager.create_bot.assert_awaited_once()
        call_kwargs = fake_bot_manager.create_bot.call_args.kwargs
        assert call_kwargs["config"].strategy_id == "strat-1"
        assert call_kwargs["config"].name == "테스트봇"
        assert call_kwargs["config"].account_id == "acct-1"
        assert call_kwargs["config"].interval_seconds == 30

    async def test_raises_when_strategy_not_found(self):
        """미등록 strategy_id → ValueError."""
        from unittest.mock import AsyncMock, MagicMock

        from ante.ipc.registry import _handle_bot_create

        fake_registry = AsyncMock()
        fake_registry.get.return_value = None

        svc = MagicMock()
        svc.strategy_registry = fake_registry

        with pytest.raises(ValueError, match="전략을 찾을 수 없습니다"):
            await _handle_bot_create(
                svc,
                {"strategy_id": "nonexistent"},
                "cli-user",
            )

    async def test_ipc_bot_create_account_scoped_required(self):
        """Refs #1217 → #1241 SPLIT-2: ``args["account_id"]`` 누락/invalid 시
        ``InvalidAccountIdError`` 로 거부한다.

        ``args.get("account_id", "")`` fallback 이 제거되어 IPC routing
        진입점에서 즉시 거부된다. ``BotConfig.__post_init__`` 까지 도달하기
        전에 ``ipc.bot.create`` context 로 실패한다.
        """
        from dataclasses import dataclass
        from unittest.mock import AsyncMock, MagicMock

        from ante.account.errors import InvalidAccountIdError
        from ante.ipc.registry import _handle_bot_create

        @dataclass
        class FakeRecord:
            filepath: str = "/tmp/strategy.py"

        fake_registry = AsyncMock()
        fake_registry.get.return_value = FakeRecord()

        fake_bot_manager = AsyncMock()

        svc = MagicMock()
        svc.strategy_registry = fake_registry
        svc.bot_manager = fake_bot_manager

        import ante.strategy.loader

        original_load = ante.strategy.loader.StrategyLoader.load
        ante.strategy.loader.StrategyLoader.load = MagicMock(
            return_value=type("FakeStrategy", (), {})
        )
        try:
            # 누락 → 거부
            with pytest.raises(InvalidAccountIdError, match="ipc.bot.create"):
                await _handle_bot_create(
                    svc,
                    {"strategy_id": "strat-1"},
                    "cli-user",
                )

            # 빈 문자열 → 거부
            with pytest.raises(InvalidAccountIdError):
                await _handle_bot_create(
                    svc,
                    {"strategy_id": "strat-1", "account_id": ""},
                    "cli-user",
                )

            # 'default' 예약어 → 거부
            with pytest.raises(InvalidAccountIdError):
                await _handle_bot_create(
                    svc,
                    {"strategy_id": "strat-1", "account_id": "default"},
                    "cli-user",
                )

            # bot_manager.create_bot 까지 절대 도달하지 않아야 한다
            fake_bot_manager.create_bot.assert_not_called()
        finally:
            ante.strategy.loader.StrategyLoader.load = original_load


# ── system.halt / system.clear_halt 응답 shape (Refs #1213) ──


class TestSystemKillSwitchHandlers:
    """system.halt / system.clear_halt IPC 응답 shape 회귀 가드.

    SSOT: ``docs/specs/web-api/04-system-endpoints.md`` Kill Switch 응답.
    Web API와 IPC가 동일한 shape (status, accounts_changed, changed_at, accounts[])을
    사용한다.
    """

    @pytest.mark.asyncio
    async def test_handle_system_halt_response_shape(self):
        from unittest.mock import AsyncMock, MagicMock

        from ante.ipc.registry import _handle_system_halt

        accounts = [
            {
                "account_id": "acc1",
                "previous_status": "active",
                "status": "suspended",
                "changed": True,
            },
            {
                "account_id": "acc2",
                "previous_status": "suspended",
                "status": "suspended",
                "changed": False,
            },
        ]

        svc = MagicMock()
        svc.account = MagicMock()
        svc.account.suspend_all = AsyncMock(return_value=accounts)

        result = await _handle_system_halt(svc, {"reason": "test"}, "cli-user")

        assert result["status"] == "halted"
        assert result["accounts_changed"] == 1
        assert result["accounts"] == accounts
        assert isinstance(result["changed_at"], str) and result["changed_at"]
        svc.account.suspend_all.assert_awaited_once_with(
            reason="test", suspended_by="cli-user"
        )

    @pytest.mark.asyncio
    async def test_handle_system_clear_halt_response_shape(self):
        from unittest.mock import AsyncMock, MagicMock

        from ante.ipc.registry import _handle_system_clear_halt

        accounts = [
            {
                "account_id": "acc1",
                "previous_status": "suspended",
                "status": "active",
                "changed": True,
            },
        ]

        svc = MagicMock()
        svc.account = MagicMock()
        svc.account.activate_all = AsyncMock(return_value=accounts)

        # bot_manager.start*/restart* 같은 메서드가 호출되지 않음을 보장하려면
        # bot_manager 자체가 호출되지 않아야 한다 (clear_halt 핸들러는 BotManager
        # 의존성을 직접 보유하지 않는다 — Refs #1213 회귀 가드).
        svc.bot_manager = MagicMock()

        result = await _handle_system_clear_halt(svc, {}, "cli-user")

        assert result["status"] == "halt_cleared"
        assert result["accounts_changed"] == 1
        assert result["accounts"] == accounts
        assert isinstance(result["changed_at"], str) and result["changed_at"]
        svc.account.activate_all.assert_awaited_once_with(activated_by="cli-user")
        # 봇 자동 재시작 회귀 가드: BotManager 메서드가 호출되지 않아야 한다.
        svc.bot_manager.start_bot.assert_not_called()
        svc.bot_manager.restart_bot.assert_not_called()
        svc.bot_manager.start_all.assert_not_called()


# ── broker.reconcile cross-account guard (Refs #1240 review P2-1) ──


class TestHandleBrokerReconcile:
    """broker.reconcile IPC 핸들러의 account 일치 가드.

    Refs #1240 review (P2-1): 요청자가 ``bot_id`` 와 다른 ``account_id`` 를
    보내면 잘못된 account_id 가 ``reconciler.reconcile(...)`` 으로 흘러
    다른 계좌의 positions / adjustment trade 가 손상된다. BotManager 로
    봇의 실제 account_id 를 조회하여 일치하지 않으면 거부한다.
    """

    @pytest.mark.asyncio
    async def test_broker_reconcile_rejects_account_mismatch(self):
        from unittest.mock import AsyncMock, MagicMock

        from ante.account.errors import InvalidAccountIdError
        from ante.ipc.registry import _handle_broker_reconcile

        # 봇은 acc-a 소속인데 요청은 acc-b 로 들어옴.
        fake_bot = MagicMock()
        fake_bot.config = MagicMock()
        fake_bot.config.account_id = "acc-a"

        fake_bot_manager = MagicMock()
        fake_bot_manager.get_bot.return_value = fake_bot

        fake_reconciler = AsyncMock()

        svc = MagicMock()
        svc.bot_manager = fake_bot_manager
        svc.reconciler = fake_reconciler

        with pytest.raises(InvalidAccountIdError, match="acc-a"):
            await _handle_broker_reconcile(
                svc,
                {
                    "bot_id": "bot-1",
                    "account_id": "acc-b",
                    "broker_positions": [],
                },
                "cli-user",
            )

        # reconcile 까지 절대 도달하지 않아야 한다.
        fake_reconciler.reconcile.assert_not_called()

    @pytest.mark.asyncio
    async def test_broker_reconcile_passes_when_account_matches(self):
        from unittest.mock import AsyncMock, MagicMock

        from ante.ipc.registry import _handle_broker_reconcile

        fake_bot = MagicMock()
        fake_bot.config = MagicMock()
        fake_bot.config.account_id = "acc-a"

        fake_bot_manager = MagicMock()
        fake_bot_manager.get_bot.return_value = fake_bot

        fake_reconciler = AsyncMock()
        fake_reconciler.reconcile.return_value = []

        svc = MagicMock()
        svc.bot_manager = fake_bot_manager
        svc.reconciler = fake_reconciler

        result = await _handle_broker_reconcile(
            svc,
            {
                "bot_id": "bot-1",
                "account_id": "acc-a",
                "broker_positions": [],
            },
            "cli-user",
        )

        assert result == {"bot_id": "bot-1", "adjustments": []}
        fake_reconciler.reconcile.assert_awaited_once_with(
            "bot-1", [], account_id="acc-a"
        )

    @pytest.mark.asyncio
    async def test_broker_reconcile_passes_when_bot_not_found(self):
        """알 수 없는 ``bot_id`` 는 reconcile 단계에서 처리되도록 통과시킨다.

        BotManager 에 없는 봇이라도 mismatch 검증 단계에서 false negative 로
        막아버리면 cold-path / migration 시나리오가 깨진다. account_id 형식
        검증은 ``require_account_id`` 가 이미 수행하므로 이 단계는 mismatch
        만 책임진다.
        """
        from unittest.mock import AsyncMock, MagicMock

        from ante.ipc.registry import _handle_broker_reconcile

        fake_bot_manager = MagicMock()
        fake_bot_manager.get_bot.return_value = None

        fake_reconciler = AsyncMock()
        fake_reconciler.reconcile.return_value = []

        svc = MagicMock()
        svc.bot_manager = fake_bot_manager
        svc.reconciler = fake_reconciler

        result = await _handle_broker_reconcile(
            svc,
            {
                "bot_id": "unknown-bot",
                "account_id": "acc-a",
                "broker_positions": [],
            },
            "cli-user",
        )

        assert result == {"bot_id": "unknown-bot", "adjustments": []}
        fake_reconciler.reconcile.assert_awaited_once()


# ── #1379 oracle A7: IPC config.set 핸들러도 서비스 경계 ValueError 전파 ──


class TestHandleConfigSetValidation:
    """``_handle_config_set`` 이 ``DynamicConfigService.set`` 의 ValueError 를
    그대로 전파하는지 검증한다(IPC 우회 차단, #1379).
    """

    async def test_invalid_log_level_propagates_value_error(self):
        """invalid system.log_level → ValueError (IPC 단계 차단)."""
        from unittest.mock import AsyncMock, MagicMock

        from ante.ipc.registry import _handle_config_set

        async def _set(key, value, category, changed_by):  # noqa: ANN001, ANN202
            from ante.config.dynamic import validate_value

            validate_value(key, value)

        fake_dynamic = MagicMock()
        fake_dynamic.set = AsyncMock(side_effect=_set)

        svc = MagicMock()
        svc.dynamic_config = fake_dynamic

        with pytest.raises(ValueError, match="system.log_level"):
            await _handle_config_set(
                svc,
                {
                    "key": "system.log_level",
                    "value": "ORACLE_INVALID_LEVEL",
                    "category": "system",
                },
                "cli-user",
            )

    async def test_valid_log_level_succeeds(self):
        """``DEBUG`` 같은 정상 값은 통과."""
        from unittest.mock import AsyncMock, MagicMock

        from ante.ipc.registry import _handle_config_set

        fake_dynamic = MagicMock()
        fake_dynamic.set = AsyncMock(return_value=None)

        svc = MagicMock()
        svc.dynamic_config = fake_dynamic

        result = await _handle_config_set(
            svc,
            {
                "key": "system.log_level",
                "value": "DEBUG",
                "category": "system",
            },
            "cli-user",
        )
        assert result == {"key": "system.log_level", "value": "DEBUG"}
        fake_dynamic.set.assert_awaited_once()
