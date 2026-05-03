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
    """register_all_handlers가 18개 핸들러를 등록 (account.delete 제외).

    `account.delete`는 1.0 IPC 계약에서 제거되어 cold-path CLI에서 직접
    AccountService를 호출한다.
    """
    registry = CommandRegistry()
    register_all_handlers(registry)
    assert len(registry.commands) == 18

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
    """등록된 18개 핸들러의 mutating/read-only taxonomy가 스펙과 일치한다."""
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
        "approval.reopen",
        "broker.reconcile",
    }
    read_only = {"broker.status", "broker.balance", "broker.positions"}

    assert len(mutating) == 15
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
