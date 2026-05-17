"""CommandRegistry — IPC 커맨드 핸들러 등록 및 조회.

각 커맨드 핸들러는 (ServiceRegistry, args: dict, actor: str) -> dict 시그니처를 따른다.

Refs #1184: 각 등록 핸들러는 ``CommandSpec``으로 wrap되어 ``is_mutating``
taxonomy를 함께 보유한다. ``IPCServer._dispatch``는 lifecycle state가
``SHUTTING_DOWN``일 때 mutating 핸들러를 ``SERVICE_UNAVAILABLE``로 거부하기
위해 이 정보를 사용한다.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ante.core.registry import ServiceRegistry

CommandHandler = Callable[["ServiceRegistry", dict, str], Awaitable[dict]]

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CommandSpec:
    """IPC 커맨드의 메타데이터.

    Refs #1184: lifecycle state machine과 결합하여 shutdown 중
    mutating 명령을 거부하기 위한 taxonomy를 보유한다.

    Attributes:
        name: 커맨드 식별자 (예: ``"system.halt"``).
        handler: 비동기 핸들러 콜러블.
        is_mutating: 핸들러가 서버 상태/DB를 변경하면 True. 단순 read-only
            (live 조회) 면 False.
    """

    name: str
    handler: CommandHandler
    is_mutating: bool


class CommandRegistry:
    """커맨드 이름 -> CommandSpec 매핑.

    Refs #1184: 단순 dict[str, handler]에서 dict[str, CommandSpec]으로
    전환되었다. 외부 호출자는 ``register(name, handler, *, is_mutating=...)``
    keyword-only 인자를 명시해야 한다.
    """

    def __init__(self) -> None:
        self._specs: dict[str, CommandSpec] = {}

    def register(
        self,
        command: str,
        handler: CommandHandler,
        *,
        is_mutating: bool,
    ) -> None:
        """핸들러 등록.

        Args:
            command: 커맨드 이름.
            handler: 비동기 핸들러.
            is_mutating: 변경 명령 여부. shutdown 중 reject 분기에서 사용.
        """
        self._specs[command] = CommandSpec(
            name=command, handler=handler, is_mutating=is_mutating
        )

    def get(self, command: str) -> CommandSpec | None:
        """CommandSpec 조회. 미등록이면 None."""
        return self._specs.get(command)

    @property
    def commands(self) -> list[str]:
        """등록된 커맨드 목록 (이름만)."""
        return list(self._specs.keys())


# ── 핸들러 구현 ──────────────────────────────────────


def _kill_switch_payload(status: str, accounts: list[dict[str, Any]]) -> dict:
    """Kill Switch IPC 응답 envelope.

    SSOT: ``docs/specs/web-api/04-system-endpoints.md`` Kill Switch 응답 SSOT.
    Web API와 IPC가 동일한 shape(``status``, ``accounts_changed``, ``changed_at``,
    ``accounts[]``)을 사용한다. ``changed_at``은 ISO 8601 UTC ``Z`` suffix를
    사용한다 (Refs #1360).
    """
    from datetime import UTC, datetime

    from ante.core.time import format_utc

    return {
        "status": status,
        "accounts_changed": sum(1 for a in accounts if a.get("changed")),
        "changed_at": format_utc(datetime.now(UTC)),
        "accounts": accounts,
    }


async def _handle_system_halt(
    svc: ServiceRegistry, args: dict[str, Any], actor: str
) -> dict:
    reason = args.get("reason", "IPC halt")
    accounts = await svc.account.suspend_all(reason=reason, suspended_by=actor)
    return _kill_switch_payload("halted", accounts)


async def _handle_system_clear_halt(
    svc: ServiceRegistry, args: dict[str, Any], actor: str
) -> dict:
    accounts = await svc.account.activate_all(activated_by=actor)
    return _kill_switch_payload("halt_cleared", accounts)


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


async def _handle_bot_create(
    svc: ServiceRegistry, args: dict[str, Any], actor: str
) -> dict:
    from pathlib import Path

    from ante.account.scoping import require_account_id
    from ante.bot.config import BotConfig
    from ante.strategy.loader import StrategyLoader

    strategy_id = args["strategy_id"]
    record = await svc.strategy_registry.get(strategy_id)
    if record is None:
        msg = f"전략을 찾을 수 없습니다: {strategy_id}"
        raise ValueError(msg)

    strategy_cls = StrategyLoader.load(Path(record.filepath))

    # Refs #1217 → #1241 SPLIT-2: account_id fallback 제거.
    # ``BotConfig.__post_init__`` 의 require_account_id 와 중복되지만
    # IPC routing 진입점에서 한 번 더 명시 검증해 ``InvalidAccountIdError`` 의
    # context 를 ``ipc.bot.create`` 로 표시한다.
    account_id = require_account_id(args.get("account_id"), context="ipc.bot.create")
    config = BotConfig(
        bot_id=args.get("bot_id", ""),
        strategy_id=strategy_id,
        name=args.get("name", ""),
        account_id=account_id,
        interval_seconds=args.get("interval_seconds", 60),
    )

    bot = await svc.bot_manager.create_bot(
        config=config,
        strategy_cls=strategy_cls,
        source_path=Path(record.filepath),
    )
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


async def _handle_approval_cancel_invalid(
    svc: ServiceRegistry, args: dict[str, Any], actor: str
) -> dict:
    """Administrative cancellation of a legacy invalid-type approval.

    Refs #1418 → #1472 SPLIT-D. CLI ``approval:admin`` scope 를 보유한 운영자가
    ``ante approval cancel-invalid <id>`` 로 호출한다. 성공 후 ``audit_logger``
    가 주입된 환경(production)에서는 ``audit_log`` 테이블에 기록을 남긴다.
    테스트/legacy 환경에서 ``audit_logger`` 가 ``None`` 이면 audit 호출을 건너
    뛰며, 서비스의 ``history`` append 가 fallback 추적 경로다.
    """
    approval_id = args["approval_id"]
    request = await svc.approval.cancel_invalid_type_request(
        approval_id,
        resolved_by=actor,
    )

    audit_logger = getattr(svc, "audit_logger", None)
    if audit_logger is not None:
        await audit_logger.log(
            member_id=actor,
            action="approval.cancel_invalid",
            resource=f"approval:{approval_id}",
            detail=request.type,
        )

    return {"id": request.id, "status": str(request.status), "type": request.type}


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
    from ante.account.scoping import require_account_id

    account_id = require_account_id(args.get("account_id"), context="ipc.broker.status")
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
    from ante.account.scoping import require_account_id

    account_id = require_account_id(
        args.get("account_id"), context="ipc.broker.balance"
    )
    broker = await svc.account.get_broker(account_id)
    return await broker.get_account_balance()


async def _handle_broker_positions(
    svc: ServiceRegistry, args: dict[str, Any], actor: str
) -> dict:
    from ante.account.scoping import require_account_id

    account_id = require_account_id(
        args.get("account_id"), context="ipc.broker.positions"
    )
    broker = await svc.account.get_broker(account_id)
    return {"positions": await broker.get_positions()}


async def _handle_broker_reconcile(
    svc: ServiceRegistry, args: dict[str, Any], actor: str
) -> dict:
    from ante.account.errors import InvalidAccountIdError
    from ante.account.scoping import require_account_id

    # #1623 Split C / #1633 finding: ``require_account_id``를
    # ``args["bot_id"]`` **이전**으로 둔다. 그래야 bot_id 없는
    # invalid-account-only direct-IPC probe도 ``InvalidAccountIdError``
    # (code="VALIDATION_ERROR", #1633 SSOT)로 raise되어 server.py:323
    # ``getattr(e, "code", ...)``를 거쳐 VALIDATION_ERROR envelope이 된다.
    # bot_id를 먼저 읽으면 ``KeyError``가 먼저 터져 EXECUTION_ERROR로
    # 오분류된다. status/balance/positions handler는 이미 require_account_id
    # 최우선이라 무변경 — reconcile만 ordering 대상.
    account_id = require_account_id(
        args.get("account_id"), context="ipc.broker.reconcile"
    )
    bot_id = args["bot_id"]

    # Refs #1240 review (P2-1): BotManager로부터 봇의 실제 account_id를 조회해
    # 요청 payload의 account_id와 일치하지 않으면 거부한다. 잘못된 account_id가
    # ``correct_position(...)`` 까지 흘러가 다른 계좌의 positions / adjustment
    # trade가 손상되는 cross-account corruption을 차단하기 위함이다.
    bot_manager = getattr(svc, "bot_manager", None)
    if bot_manager is not None:
        bot = bot_manager.get_bot(bot_id)
        if bot is not None:
            bot_account_id = getattr(bot.config, "account_id", None)
            if bot_account_id and bot_account_id != account_id:
                raise InvalidAccountIdError(
                    f"(ipc.broker.reconcile) bot_id={bot_id!r} 의 account_id는 "
                    f"{bot_account_id!r} 인데 요청은 {account_id!r} 입니다. "
                    "다른 계좌의 포지션을 조작할 수 없습니다."
                )

    broker_positions = args.get("broker_positions", [])
    adjustments = await svc.reconciler.reconcile(
        bot_id, broker_positions, account_id=account_id
    )
    return {"bot_id": bot_id, "adjustments": adjustments}


def register_all_handlers(registry: CommandRegistry) -> None:
    """19개 런타임 커맨드 핸들러를 일괄 등록.

    Refs #1184: 각 핸들러는 mutating(16개) 또는 read-only(3개)로 분류된다.
    분류는 ``docs/specs/ipc/ipc.md``의 "Handler taxonomy" 섹션과 동기화되어야
    한다. mutating 명령은 ``IPCServer``가 ``SHUTTING_DOWN`` 상태일 때
    ``SERVICE_UNAVAILABLE``로 거부된다.

    `account.delete`는 1.0 IPC 계약에서 제외되었다 (#1139). cold-path CLI에서
    AccountService.delete()를 직접 호출하므로 IPC 라우팅 대상이 아니다.

    Refs #1418 → #1472 SPLIT-D: ``approval.cancel_invalid`` (mutating) 추가.
    """
    # ── mutating (16개): 서버 상태/DB를 변경 ──────────
    registry.register("system.halt", _handle_system_halt, is_mutating=True)
    registry.register("system.clear_halt", _handle_system_clear_halt, is_mutating=True)
    registry.register("account.suspend", _handle_account_suspend, is_mutating=True)
    registry.register("account.activate", _handle_account_activate, is_mutating=True)
    registry.register("bot.create", _handle_bot_create, is_mutating=True)
    registry.register("bot.remove", _handle_bot_remove, is_mutating=True)
    registry.register("treasury.allocate", _handle_treasury_allocate, is_mutating=True)
    registry.register(
        "treasury.deallocate", _handle_treasury_deallocate, is_mutating=True
    )
    registry.register("config.set", _handle_config_set, is_mutating=True)
    registry.register("approval.request", _handle_approval_request, is_mutating=True)
    registry.register("approval.approve", _handle_approval_approve, is_mutating=True)
    registry.register("approval.reject", _handle_approval_reject, is_mutating=True)
    registry.register("approval.cancel", _handle_approval_cancel, is_mutating=True)
    registry.register(
        "approval.cancel_invalid",
        _handle_approval_cancel_invalid,
        is_mutating=True,
    )
    registry.register("approval.reopen", _handle_approval_reopen, is_mutating=True)
    # broker.reconcile은 reconciler.reconcile()이 correct_position/이벤트
    # publish를 수행하므로 일괄 mutating으로 분류한다. CLI ``--fix=False``
    # dryrun 분리는 후속 이슈.
    registry.register("broker.reconcile", _handle_broker_reconcile, is_mutating=True)

    # ── read-only (3개): BrokerAdapter live 조회만 ────
    registry.register("broker.status", _handle_broker_status, is_mutating=False)
    registry.register("broker.balance", _handle_broker_balance, is_mutating=False)
    registry.register("broker.positions", _handle_broker_positions, is_mutating=False)
