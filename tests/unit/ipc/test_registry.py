"""CommandRegistry 테스트."""

import pytest

from ante.ipc.registry import CommandRegistry, register_all_handlers


@pytest.fixture
def registry() -> CommandRegistry:
    return CommandRegistry()


def test_register_and_get(registry: CommandRegistry) -> None:
    """핸들러 등록 후 조회."""

    async def dummy_handler(svc, args, actor):  # type: ignore[no-untyped-def]
        return {"ok": True}

    registry.register("test.command", dummy_handler)
    assert registry.get("test.command") is dummy_handler


def test_get_unregistered_returns_none(registry: CommandRegistry) -> None:
    """미등록 커맨드 조회 시 None 반환."""
    assert registry.get("nonexistent.command") is None


def test_commands_property(registry: CommandRegistry) -> None:
    """commands 프로퍼티가 등록된 커맨드 목록을 반환."""

    async def handler(svc, args, actor):  # type: ignore[no-untyped-def]
        return {}

    registry.register("a.command", handler)
    registry.register("b.command", handler)
    assert set(registry.commands) == {"a.command", "b.command"}


def test_register_all_handlers() -> None:
    """register_all_handlers가 19개 핸들러를 등록."""
    registry = CommandRegistry()
    register_all_handlers(registry)
    assert len(registry.commands) == 19

    expected = {
        "system.halt",
        "system.activate",
        "account.delete",
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
