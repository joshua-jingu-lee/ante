"""CommandRegistry — IPC 커맨드 핸들러 등록 및 조회.

각 커맨드 핸들러는 (ServiceRegistry, args: dict, actor: str) -> dict 시그니처를 따른다.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ante.core.registry import ServiceRegistry

CommandHandler = Callable[["ServiceRegistry", dict, str], Awaitable[dict]]

logger = logging.getLogger(__name__)


class CommandRegistry:
    """커맨드 이름 -> 핸들러 매핑."""

    def __init__(self) -> None:
        self._handlers: dict[str, CommandHandler] = {}

    def register(self, command: str, handler: CommandHandler) -> None:
        """핸들러 등록."""
        self._handlers[command] = handler

    def get(self, command: str) -> CommandHandler | None:
        """핸들러 조회. 미등록이면 None."""
        return self._handlers.get(command)

    @property
    def commands(self) -> list[str]:
        """등록된 커맨드 목록."""
        return list(self._handlers.keys())


# ── 핸들러 구현 ──────────────────────────────────────


async def _handle_system_halt(
    svc: ServiceRegistry, args: dict[str, Any], actor: str
) -> dict:
    reason = args.get("reason", "IPC halt")
    count = await svc.account.suspend_all(reason=reason, suspended_by=actor)
    return {"suspended_count": count}


async def _handle_system_activate(
    svc: ServiceRegistry, args: dict[str, Any], actor: str
) -> dict:
    count = await svc.account.activate_all(activated_by=actor)
    return {"activated_count": count}


async def _handle_account_suspend(
    svc: ServiceRegistry, args: dict[str, Any], actor: str
) -> dict:
    account_id = args["account_id"]
    reason = args.get("reason", "IPC suspend")
    await svc.account.suspend(account_id, reason=reason, suspended_by=actor)
    return {"account_id": account_id, "status": "suspended"}


async def _handle_account_activate(
    svc: ServiceRegistry, args: dict[str, Any], actor: str
) -> dict:
    account_id = args["account_id"]
    await svc.account.activate(account_id, activated_by=actor)
    return {"account_id": account_id, "status": "active"}


async def _handle_account_delete(
    svc: ServiceRegistry, args: dict[str, Any], actor: str
) -> dict:
    account_id = args["account_id"]
    await svc.account.delete(account_id, deleted_by=actor)
    return {"account_id": account_id, "status": "deleted"}


async def _handle_bot_create(
    svc: ServiceRegistry, args: dict[str, Any], actor: str
) -> dict:
    bot = await svc.bot_manager.create_bot(**args)
    return {"bot_id": bot.bot_id}


async def _handle_bot_remove(
    svc: ServiceRegistry, args: dict[str, Any], actor: str
) -> dict:
    bot_id = args["bot_id"]
    await svc.bot_manager.remove_bot(bot_id)
    return {"bot_id": bot_id, "removed": True}


async def _handle_treasury_allocate(
    svc: ServiceRegistry, args: dict[str, Any], actor: str
) -> dict:
    account_id = args["account_id"]
    bot_id = args["bot_id"]
    amount = args["amount"]
    treasury = svc.treasury_manager.get(account_id)
    result = await treasury.allocate(bot_id, amount)
    return {"account_id": account_id, "bot_id": bot_id, "success": result}


async def _handle_treasury_deallocate(
    svc: ServiceRegistry, args: dict[str, Any], actor: str
) -> dict:
    account_id = args["account_id"]
    bot_id = args["bot_id"]
    amount = args["amount"]
    treasury = svc.treasury_manager.get(account_id)
    result = await treasury.deallocate(bot_id, amount)
    return {"account_id": account_id, "bot_id": bot_id, "success": result}


async def _handle_config_set(
    svc: ServiceRegistry, args: dict[str, Any], actor: str
) -> dict:
    key = args["key"]
    value = args["value"]
    category = args.get("category", "user")
    await svc.dynamic_config.set(key, value, category=category, changed_by=actor)
    return {"key": key, "value": value}


async def _handle_approval_request(
    svc: ServiceRegistry, args: dict[str, Any], actor: str
) -> dict:
    request = await svc.approval.create(
        type=args["type"],
        requester=actor,
        title=args["title"],
        body=args.get("body", ""),
        params=args.get("params"),
        reference_id=args.get("reference_id", ""),
        expires_at=args.get("expires_at", ""),
    )
    return {"id": request.id, "status": str(request.status)}


async def _handle_approval_approve(
    svc: ServiceRegistry, args: dict[str, Any], actor: str
) -> dict:
    request = await svc.approval.approve(args["id"], resolved_by=actor)
    return {"id": request.id, "status": str(request.status)}


async def _handle_approval_reject(
    svc: ServiceRegistry, args: dict[str, Any], actor: str
) -> dict:
    request = await svc.approval.reject(
        args["id"],
        resolved_by=actor,
        reject_reason=args.get("reason", ""),
    )
    return {"id": request.id, "status": str(request.status)}


async def _handle_approval_cancel(
    svc: ServiceRegistry, args: dict[str, Any], actor: str
) -> dict:
    request = await svc.approval.cancel(args["id"], requester=actor)
    return {"id": request.id, "status": str(request.status)}


async def _handle_approval_reopen(
    svc: ServiceRegistry, args: dict[str, Any], actor: str
) -> dict:
    request = await svc.approval.reopen(
        args["id"],
        requester=actor,
        body=args.get("body"),
        params=args.get("params"),
    )
    return {"id": request.id, "status": str(request.status)}


async def _handle_broker_status(
    svc: ServiceRegistry, args: dict[str, Any], actor: str
) -> dict:
    account_id = args.get("account_id", "")
    broker = await svc.account.get_broker(account_id)
    healthy = await broker.health_check()
    return {
        "connected": broker.is_connected,
        "healthy": healthy,
        "exchange": broker.exchange,
    }


async def _handle_broker_balance(
    svc: ServiceRegistry, args: dict[str, Any], actor: str
) -> dict:
    account_id = args.get("account_id", "")
    broker = await svc.account.get_broker(account_id)
    return await broker.get_account_balance()


async def _handle_broker_positions(
    svc: ServiceRegistry, args: dict[str, Any], actor: str
) -> dict:
    account_id = args.get("account_id", "")
    broker = await svc.account.get_broker(account_id)
    return {"positions": await broker.get_positions()}


async def _handle_broker_reconcile(
    svc: ServiceRegistry, args: dict[str, Any], actor: str
) -> dict:
    bot_id = args["bot_id"]
    broker_positions = args.get("broker_positions", [])
    adjustments = await svc.reconciler.reconcile(bot_id, broker_positions)
    return {"bot_id": bot_id, "adjustments": adjustments}


def register_all_handlers(registry: CommandRegistry) -> None:
    """18개 런타임 커맨드 핸들러를 일괄 등록."""
    registry.register("system.halt", _handle_system_halt)
    registry.register("system.activate", _handle_system_activate)
    registry.register("account.suspend", _handle_account_suspend)
    registry.register("account.activate", _handle_account_activate)
    registry.register("account.delete", _handle_account_delete)
    registry.register("bot.create", _handle_bot_create)
    registry.register("bot.remove", _handle_bot_remove)
    registry.register("treasury.allocate", _handle_treasury_allocate)
    registry.register("treasury.deallocate", _handle_treasury_deallocate)
    registry.register("config.set", _handle_config_set)
    registry.register("approval.request", _handle_approval_request)
    registry.register("approval.approve", _handle_approval_approve)
    registry.register("approval.reject", _handle_approval_reject)
    registry.register("approval.cancel", _handle_approval_cancel)
    registry.register("approval.reopen", _handle_approval_reopen)
    registry.register("broker.status", _handle_broker_status)
    registry.register("broker.balance", _handle_broker_balance)
    registry.register("broker.positions", _handle_broker_positions)
    registry.register("broker.reconcile", _handle_broker_reconcile)
