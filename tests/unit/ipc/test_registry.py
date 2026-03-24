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
