"""CommandRegistry — IPC 커맨드 핸들러 등록 및 조회."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date
from typing import TYPE_CHECKING, Any, Literal, cast

from ante.account.errors import (
    AccountActivateAllFailedError,
    AccountSuspendAllFailedError,
)
from ante.account.models import missing_required_credentials
from ante.account.presets import BROKER_PRESETS
from ante.contracts.cli_errors import ConfigUnsupportedKeyError, InvalidDateRangeError
from ante.core import clock
from ante.ipc.requests import (
    AccountActivateRequest,
    AccountSuspendRequest,
    ApprovalApproveRequest,
    ApprovalCancelInvalidRequest,
    ApprovalCancelRequest,
    ApprovalRejectRequest,
    ApprovalReopenRequest,
    ApprovalRequestRequest,
    BotCreateRequest,
    BotInfoRequest,
    BotListRequest,
    BotPositionsRequest,
    BotRemoveRequest,
    BotSignalKeyRequest,
    BotSignalKeyRotateRequest,
    BotStartRequest,
    BotStatusRequest,
    BotStopRequest,
    BotUpdateRequest,
    BrokerBalanceRequest,
    BrokerOrderHistoryRequest,
    BrokerPositionsRequest,
    BrokerReconcileRequest,
    BrokerStatusRequest,
    ConfigSetRequest,
    IPCRequest,
    MemberReactivateRequest,
    MemberRegenerateRecoveryKeyRequest,
    MemberRegisterRequest,
    MemberResetPasswordRequest,
    MemberRevokeRequest,
    MemberRotateTokenRequest,
    MemberSetEmojiRequest,
    MemberSuspendRequest,
    MemberUpdateScopesRequest,
    RuleUpdateRequest,
    SignalConnectRequest,
    StrategySetStatusRequest,
    SystemClearHaltRequest,
    SystemHaltRequest,
    TreasuryAllocateRequest,
    TreasuryDeallocateRequest,
    TreasurySetBalanceRequest,
)
from ante.rule.config_update import is_account_rules_config_key

if TYPE_CHECKING:
    from ante.core.registry import ServiceRegistry

CommandHandler = Callable[["ServiceRegistry", Any, str], Awaitable[dict[str, Any]]]

ShutdownBehavior = Literal["block_on_mutating", "block_all", "allow_all"]

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CommandSpec:
    """IPC 커맨드의 메타데이터."""

    name: str
    handler: CommandHandler
    is_mutating: bool
    request_model: type[IPCRequest]
    required_services: frozenset[str] = field(default_factory=frozenset)
    audit_action: str | None = None
    shutdown_behavior: ShutdownBehavior | None = None


class CommandRegistry:
    """커맨드 이름 -> CommandSpec 매핑.

    외부 호출자는 ``register(name, handler, *, is_mutating=...,
    request_model=...)`` keyword-only 인자를 명시해야 한다.

    ``request_model``이 없는 등록은 ``TypeError``다. 나머지 contract
    metadata 3 필드는 kwargs로 받고 생략하면 기본값이다.
    """

    def __init__(self) -> None:
        self._specs: dict[str, CommandSpec] = {}

    def register(
        self,
        command: str,
        handler: CommandHandler,
        *,
        is_mutating: bool,
        request_model: type[IPCRequest],
        required_services: frozenset[str] | None = None,
        audit_action: str | None = None,
        shutdown_behavior: ShutdownBehavior | None = None,
    ) -> None:
        """핸들러 등록.

        Args:
            is_mutating: 변경 명령 여부. shutdown 중 reject 분기에서 사용.
        """
        if request_model is None:
            raise TypeError(f"{command}: request_model is required")
        self._specs[command] = CommandSpec(
            name=command,
            handler=handler,
            is_mutating=is_mutating,
            request_model=request_model,
            required_services=(
                required_services if required_services is not None else frozenset()
            ),
            audit_action=audit_action,
            shutdown_behavior=shutdown_behavior,
        )

    def get(self, command: str) -> CommandSpec | None:
        """CommandSpec 조회. 미등록이면 None."""
        return self._specs.get(command)

    def iter_specs(self) -> list[CommandSpec]:
        """등록된 모든 ``CommandSpec`` 목록.

        registry metadata 완전성 단언/감사 시 사용. 반환 순서는
        등록 순서를 따른다(Python 3.7+ dict insertion order).
        """
        return list(self._specs.values())

    @property
    def commands(self) -> list[str]:
        """등록된 커맨드 목록 (이름만)."""
        return list(self._specs.keys())


def _kill_switch_payload(status: str, accounts: list[dict[str, Any]]) -> dict[str, Any]:
    """Kill Switch IPC 응답 envelope."""
    from datetime import UTC

    from ante.core.time import format_utc

    return {
        "status": status,
        "accounts_changed": sum(1 for a in accounts if a.get("changed")),
        "changed_at": format_utc(clock.now(UTC)),
        "accounts": accounts,
    }


async def _audit_incomplete_kill_switch(
    svc: ServiceRegistry,
    action: str,
    actor: str,
    failed: tuple[str, ...],
    changed: int,
    reason: str,
) -> None:
    """킬 스위치의 부분 실패를 감사에 한 건 남긴다(감사 실패는 로그만)."""
    try:
        await svc.audit_logger.log(
            member_id=actor,
            action=action,
            resource="system:kill_switch",
            detail=f"failed={','.join(failed)}; changed={changed}; reason={reason}",
            ip="",
        )
    except Exception:
        logger.exception("킬 스위치 부분 실패의 감사 기록 실패: %s", action)


async def _handle_system_halt(
    svc: ServiceRegistry, request: SystemHaltRequest, actor: str
) -> dict[str, Any]:
    """전역 거래 정지(kill switch) IPC handler."""
    reason = request.reason
    try:
        accounts = await svc.account.suspend_all(reason=reason, suspended_by=actor)
    except AccountSuspendAllFailedError as exc:
        await _audit_incomplete_kill_switch(
            svc,
            "system.halt",
            actor,
            exc.failed_account_ids,
            exc.suspended_count,
            reason,
        )
        raise
    payload = _kill_switch_payload("halted", accounts)
    payload["_audit_detail"] = {
        "resource": "system:kill_switch",
        "detail": f"reason={reason}",
        "ip": "",
    }
    return payload


async def _handle_system_clear_halt(
    svc: ServiceRegistry, request: SystemClearHaltRequest, actor: str
) -> dict[str, Any]:
    """전역 거래 정지 해제 IPC handler."""
    try:
        accounts = await svc.account.activate_all(activated_by=actor)
    except AccountActivateAllFailedError as exc:
        await _audit_incomplete_kill_switch(
            svc,
            "system.clear_halt",
            actor,
            (exc.failed_account_id,),
            exc.activated_count,
            request.reason,
        )
        raise
    payload = _kill_switch_payload("halt_cleared", accounts)
    payload["_audit_detail"] = {
        "resource": "system:kill_switch",
        "detail": f"reason={request.reason}",
        "ip": "",
    }
    return payload


async def _handle_account_suspend(
    svc: ServiceRegistry, request: AccountSuspendRequest, actor: str
) -> dict[str, Any]:
    """계좌 정지 IPC handler."""
    account_id = request.account_id
    reason = request.reason
    await svc.account.suspend(account_id, reason=reason, suspended_by=actor)
    return {
        "account_id": account_id,
        "status": "suspended",
        "_audit_detail": {
            "resource": f"account:{account_id}",
            "detail": f"reason={reason}",
            "ip": "",
        },
    }


async def _handle_account_activate(
    svc: ServiceRegistry, request: AccountActivateRequest, actor: str
) -> dict[str, Any]:
    """계좌 활성화 IPC handler."""
    account_id = request.account_id
    await svc.account.activate(account_id, activated_by=actor)
    return {
        "account_id": account_id,
        "status": "active",
        "_audit_detail": {
            "resource": f"account:{account_id}",
            "detail": "",
            "ip": "",
        },
    }


async def _handle_bot_create(
    svc: ServiceRegistry, request: BotCreateRequest, actor: str
) -> dict[str, Any]:
    from pathlib import Path

    from ante.bot.config import BotConfig
    from ante.strategy.loader import StrategyLoader

    account_id = request.account_id

    strategy_id = request.strategy_id
    record = await svc.strategy_registry.get(strategy_id)
    if record is None:
        msg = f"전략을 찾을 수 없습니다: {strategy_id}"
        raise ValueError(msg)

    strategy_cls = StrategyLoader.load(Path(record.filepath))

    config = BotConfig(
        bot_id=request.bot_id,
        strategy_id=strategy_id,
        name=request.name,
        account_id=account_id,
        interval_seconds=request.interval_seconds,
    )

    bot = await svc.bot_manager.create_bot(
        config=config,
        strategy_cls=strategy_cls,
        source_path=Path(record.filepath),
    )
    return {
        "bot_id": bot.bot_id,
        "_audit_detail": {
            "resource": f"bot:{bot.bot_id}",
            "detail": "",
            "ip": "",
        },
    }


async def _handle_bot_remove(
    svc: ServiceRegistry, request: BotRemoveRequest, actor: str
) -> dict[str, Any]:
    """봇 제거 IPC handler."""
    bot_id = request.bot_id
    await svc.bot_manager.remove_bot(bot_id)
    return {
        "bot_id": bot_id,
        "removed": True,
        "_audit_detail": {
            "resource": f"bot:{bot_id}",
            "detail": "",
            "ip": "",
        },
    }


async def _handle_bot_signal_key_rotate(
    svc: ServiceRegistry, request: BotSignalKeyRotateRequest, actor: str
) -> dict[str, Any]:
    """봇 시그널 키 재발급 IPC handler."""
    bot_id = request.bot_id
    new_key = await svc.bot_manager.rotate_signal_key(bot_id)
    return {
        "bot_id": bot_id,
        "signal_key": new_key,
        "rotated": True,
        "_audit_detail": {
            "resource": f"bot:{bot_id}",
            "detail": "",
            "ip": "",
        },
    }


async def _handle_bot_start(
    svc: ServiceRegistry, request: BotStartRequest, actor: str
) -> dict[str, Any]:
    """봇 시작 IPC handler."""
    from ante.bot.exceptions import (
        BotAccountCredentialsNotConfigured,
        BotError,
        BotNotFoundError,
        BotStateConflict,
    )

    bot_id = request.bot_id
    bot = svc.bot_manager.get_bot(bot_id)
    if bot is None:
        raise BotNotFoundError(bot_id)

    account = await svc.account.get(bot.config.account_id)
    preset = BROKER_PRESETS.get(account.broker_type)
    required = preset.required_credentials if preset is not None else ["app_key"]
    missing = missing_required_credentials(required, account.credentials)
    if missing:
        raise BotAccountCredentialsNotConfigured(
            f"계좌에 인증정보({missing[0]})가 설정되지 않았습니다"
        )

    try:
        await svc.bot_manager.start_bot(bot_id)
    except BotError as e:
        raise BotStateConflict(str(e)) from e

    return {
        "bot": bot.get_info(),
        "_audit_detail": {
            "resource": f"bot:{bot_id}",
            "detail": "",
            "ip": "",
        },
    }


async def _handle_bot_stop(
    svc: ServiceRegistry, request: BotStopRequest, actor: str
) -> dict[str, Any]:
    """봇 중지 IPC handler."""
    from ante.bot.exceptions import (
        BotError,
        BotNotFoundError,
        BotStateConflict,
    )

    bot_id = request.bot_id
    bot = svc.bot_manager.get_bot(bot_id)
    if bot is None:
        raise BotNotFoundError(bot_id)

    try:
        await svc.bot_manager.stop_bot(bot_id)
    except BotError as e:
        raise BotStateConflict(str(e)) from e

    return {
        "bot": bot.get_info(),
        "_audit_detail": {
            "resource": f"bot:{bot_id}",
            "detail": "",
            "ip": "",
        },
    }


async def _handle_bot_status(
    svc: ServiceRegistry, request: BotStatusRequest, actor: str
) -> dict[str, Any]:
    """봇 상태 조회 IPC handler."""
    from ante.bot.exceptions import BotNotFoundError
    from ante.bot.info import enrich_bot_info

    bot_id = request.bot_id
    bot = svc.bot_manager.get_bot(bot_id)
    if bot is None:
        raise BotNotFoundError(bot_id)

    treasury_manager = getattr(svc, "treasury_manager", None)
    treasury_for_bot: Any | None = None
    if treasury_manager is not None:
        try:
            treasury_for_bot = treasury_manager.get(bot.config.account_id)
        except KeyError:
            treasury_for_bot = None

    info = await enrich_bot_info(
        bot,
        strategy_registry=getattr(svc, "strategy_registry", None),
        treasury=treasury_for_bot,
        trade_service=getattr(svc, "trade_service", None),
        account_id=bot.config.account_id,
    )
    return {"bot": info}


_BOT_LIST_KEYS = (
    "bot_id",
    "name",
    "strategy_id",
    "account_id",
    "status",
    "created_at",
)


async def _handle_bot_list(
    svc: ServiceRegistry, request: BotListRequest, actor: str
) -> dict[str, Any]:
    """봇 목록 조회 IPC handler (read-only)."""
    account_id = request.account_id
    bots = svc.bot_manager.list_bots()
    result: list[dict[str, Any]] = []
    for info in bots:
        if account_id is not None and info.get("account_id") != account_id:
            continue
        result.append({key: info.get(key) for key in _BOT_LIST_KEYS})
    return {"bots": result}


async def _handle_bot_info(
    svc: ServiceRegistry, request: BotInfoRequest, actor: str
) -> dict[str, Any]:
    """봇 상세 정보 조회 IPC handler (read-only)."""
    from ante.bot.exceptions import BotNotFoundError

    bot_id = request.bot_id
    bot = svc.bot_manager.get_bot(bot_id)
    if bot is None:
        raise BotNotFoundError(bot_id)
    return {"bot": bot.get_info()}


async def _handle_bot_positions(
    svc: ServiceRegistry, request: BotPositionsRequest, actor: str
) -> dict[str, Any]:
    """봇 보유 포지션 조회 IPC handler (read-only)."""
    from ante.bot.exceptions import BotNotFoundError

    bot_id = request.bot_id
    bot = svc.bot_manager.get_bot(bot_id)
    if bot is None:
        raise BotNotFoundError(bot_id)

    trade_service = getattr(svc, "trade_service", None)
    if trade_service is None:
        return {"positions": []}

    positions = await trade_service.get_positions(
        bot_id, account_id=bot.config.account_id
    )
    return {
        "positions": [
            {
                "symbol": p.symbol,
                "quantity": p.quantity,
                "avg_entry_price": p.avg_entry_price,
                "realized_pnl": p.realized_pnl,
            }
            for p in positions
        ]
    }


async def _handle_bot_signal_key(
    svc: ServiceRegistry, request: BotSignalKeyRequest, actor: str
) -> dict[str, Any]:
    """봇 시그널 키 조회 IPC handler (read-only)."""
    from ante.bot.exceptions import BotNotFoundError

    bot_id = request.bot_id
    bot = svc.bot_manager.get_bot(bot_id)
    if bot is None:
        raise BotNotFoundError(bot_id)

    key = await svc.bot_manager.get_signal_key(bot_id)
    return {"bot_id": bot_id, "signal_key": key}


async def _handle_signal_connect(
    svc: ServiceRegistry, request: SignalConnectRequest, actor: str
) -> dict[str, Any]:
    """``signal.connect`` 핸드셰이크 IPC handler (read-only)."""
    from uuid import uuid4

    from ante.bot.config import BotStatus
    from ante.bot.exceptions import (
        BotNotAcceptingSignals,
        BotNotFoundError,
        BotNotRunning,
        InvalidSignalKey,
    )

    bot_id = await svc.bot_manager.validate_signal_key(request.key.get_secret_value())
    if bot_id is None:
        raise InvalidSignalKey()

    bot = svc.bot_manager.get_bot(bot_id)
    if bot is None:
        raise BotNotFoundError(bot_id)

    if bot.status != BotStatus.RUNNING:
        raise BotNotRunning(bot_id, bot.status.value)

    if not bot.strategy or not bot.strategy.meta.accepts_external_signals:
        raise BotNotAcceptingSignals(f"Bot {bot_id} does not accept external signals")

    audit_logger = getattr(svc, "audit_logger", None)
    if audit_logger is not None:
        await audit_logger.log(
            member_id="ipc",
            action="signal.connect",
            resource=f"bot:{bot_id}",
            detail="",
            ip="",
        )

    session_id = uuid4().hex
    reg = getattr(svc, "signal_channel_registry", None)
    if reg is not None:
        from ante.bot.signal_channel_registry import ChannelHandle

        handle = ChannelHandle(
            session_id=session_id,
            bot_id=bot_id,
            generation=reg.current_generation(bot_id),
        )
        reg.register(handle)

    return {
        "bot_id": bot_id,
        "account_id": bot.config.account_id,
        "session_id": session_id,
        "_stream": "signal.connect",
    }


async def _handle_bot_update(
    svc: ServiceRegistry, request: BotUpdateRequest, actor: str
) -> dict[str, Any]:
    """봇 업데이트 IPC handler."""
    from ante.bot.exceptions import BotError

    bot_id = request.bot_id
    updates = request.updates.model_dump(exclude_unset=True)
    bot = svc.bot_manager.get_bot(bot_id)
    if bot is None:
        from ante.bot.exceptions import BotNotFoundError

        raise BotNotFoundError(bot_id)
    try:
        bot = await svc.bot_manager.update_bot(bot_id, **updates)
    except BotError:
        raise

    return {
        "bot": bot.get_info(),
        "_audit_detail": {
            "resource": f"bot:{bot_id}",
            "detail": f"fields={list(updates.keys())}",
            "ip": "",
        },
    }


async def _handle_treasury_allocate(
    svc: ServiceRegistry, request: TreasuryAllocateRequest, actor: str
) -> dict[str, Any]:
    from ante.account.errors import InvalidAccountIdError
    from ante.bot.exceptions import BotNotFoundError

    account_id = request.account_id
    bot_id = request.bot_id
    amount = request.amount
    bot = svc.bot_manager.get_bot(bot_id)
    if bot is None:
        raise BotNotFoundError(bot_id)
    bot_account_id = getattr(bot.config, "account_id", None)
    if bot_account_id and bot_account_id != account_id:
        raise InvalidAccountIdError(
            f"(ipc.treasury.allocate) bot_id={bot_id!r} 의 account_id는 "
            f"{bot_account_id!r} 인데 요청은 {account_id!r} 입니다. "
            "다른 계좌의 예산을 변경할 수 없습니다."
        )
    treasury = svc.treasury_manager.get(account_id)
    await treasury.allocate(bot_id, amount)
    return {"account_id": account_id, "bot_id": bot_id, "success": True}


async def _handle_treasury_deallocate(
    svc: ServiceRegistry, request: TreasuryDeallocateRequest, actor: str
) -> dict[str, Any]:
    from ante.account.errors import InvalidAccountIdError
    from ante.bot.exceptions import BotNotFoundError

    account_id = request.account_id
    bot_id = request.bot_id
    amount = request.amount
    bot = svc.bot_manager.get_bot(bot_id)
    if bot is None:
        raise BotNotFoundError(bot_id)
    bot_account_id = getattr(bot.config, "account_id", None)
    if bot_account_id and bot_account_id != account_id:
        raise InvalidAccountIdError(
            f"(ipc.treasury.deallocate) bot_id={bot_id!r} 의 account_id는 "
            f"{bot_account_id!r} 인데 요청은 {account_id!r} 입니다. "
            "다른 계좌의 예산을 변경할 수 없습니다."
        )
    treasury = svc.treasury_manager.get(account_id)
    await treasury.deallocate(bot_id, amount)
    return {"account_id": account_id, "bot_id": bot_id, "success": True}


async def _handle_treasury_set_balance(
    svc: ServiceRegistry, request: TreasurySetBalanceRequest, actor: str
) -> dict[str, Any]:
    """Treasury balance 설정 IPC handler."""
    from datetime import UTC

    account_id = request.account_id
    balance = request.balance
    treasury = svc.treasury_manager.get(account_id)
    await treasury.set_account_balance(balance)

    return {
        "account_id": account_id,
        "total_balance": treasury.account_balance,
        "updated_at": clock.now(UTC).isoformat(),
        "_audit_detail": {
            "resource": f"treasury:{account_id}",
            "detail": f"balance={balance:,.0f}",
            "ip": "",
        },
    }


async def _handle_rule_update(
    svc: ServiceRegistry, request: RuleUpdateRequest, actor: str
) -> dict[str, Any]:
    """계좌 룰 업데이트 IPC handler."""
    from ante.rule.config_update import update_account_rule_config

    account_id = request.account_id
    rule_type = request.rule_type
    result = await update_account_rule_config(
        account_service=svc.account,
        dynamic_config=svc.dynamic_config,
        account_id=account_id,
        rule_type=rule_type,
        enabled=request.enabled,
        params=request.params,
        changed_by=actor,
        config=svc.config,
        audit_logger=None,
        eventbus=svc.eventbus,
    )
    result["_audit_detail"] = {
        "resource": f"account:{account_id}:rule:{rule_type}",
        "detail": f"rule update: {rule_type} enabled={result['rule']['enabled']}",
        "ip": "",
    }
    return result


async def _handle_strategy_set_status(
    svc: ServiceRegistry, request: StrategySetStatusRequest, actor: str
) -> dict[str, Any]:
    """전략 상태 변경 IPC handler."""
    from ante.strategy.registry import StrategyStatus

    strategy_id = request.strategy_id
    status = StrategyStatus(request.status)
    await svc.strategy_registry.update_status(strategy_id, status)

    return {
        "strategy_id": strategy_id,
        "status": status.value,
        "_audit_detail": {
            "resource": f"strategy:{strategy_id}",
            "detail": f"status={status.value}",
            "ip": "",
        },
    }


async def _handle_member_update_scopes(
    svc: ServiceRegistry, request: MemberUpdateScopesRequest, actor: str
) -> dict[str, Any]:
    """멤버 scope 업데이트 IPC handler."""
    member_id = request.member_id
    scopes = request.scopes
    member_service = getattr(svc, "member_service", None)
    if member_service is None:
        raise RuntimeError("member service not configured")
    member = await member_service.update_scopes(member_id, scopes, updated_by=actor)

    return {
        "member_id": member.member_id,
        "scopes": member.scopes,
        "status": member.status,
        "_audit_detail": {
            "resource": f"member:{member_id}",
            "detail": f"scopes={scopes}",
            "ip": "",
        },
    }


async def _handle_member_register(
    svc: ServiceRegistry, request: MemberRegisterRequest, actor: str
) -> dict[str, Any]:
    """멤버 등록 IPC handler."""
    member_id = request.member_id
    member = getattr(svc, "member_service", None)
    if member is None:
        raise RuntimeError("member service not configured")
    created, token = await member.register(
        member_id=member_id,
        member_type=request.member_type,
        org=request.org,
        name=request.name,
        scopes=request.scopes,
        registered_by=actor,
    )
    return {
        "member_id": created.member_id,
        "type": created.type,
        "role": created.role,
        "org": created.org,
        "name": created.name,
        "token": token,
        "_audit_detail": {
            "resource": f"member:{created.member_id}",
            "detail": "",
            "ip": "",
        },
    }


async def _handle_member_set_emoji(
    svc: ServiceRegistry, request: MemberSetEmojiRequest, actor: str
) -> dict[str, Any]:
    """멤버 emoji 설정 IPC handler."""
    member_id = request.member_id
    emoji = request.emoji
    member = getattr(svc, "member_service", None)
    if member is None:
        raise RuntimeError("member service not configured")
    updated = await member.update_emoji(member_id, emoji, updated_by=actor)
    return {
        "member_id": updated.member_id,
        "emoji": updated.emoji,
        "_audit_detail": {
            "resource": f"member:{member_id}",
            "detail": "",
            "ip": "",
        },
    }


async def _handle_member_suspend(
    svc: ServiceRegistry, request: MemberSuspendRequest, actor: str
) -> dict[str, Any]:
    """멤버 일시 정지 IPC handler."""
    member_id = request.member_id
    member = getattr(svc, "member_service", None)
    if member is None:
        raise RuntimeError("member service not configured")
    updated = await member.suspend(member_id, suspended_by=actor)
    return {
        "member_id": updated.member_id,
        "status": updated.status,
        "_audit_detail": {
            "resource": f"member:{member_id}",
            "detail": "",
            "ip": "",
        },
    }


async def _handle_member_reactivate(
    svc: ServiceRegistry, request: MemberReactivateRequest, actor: str
) -> dict[str, Any]:
    """멤버 재활성화 IPC handler."""
    member_id = request.member_id
    member = getattr(svc, "member_service", None)
    if member is None:
        raise RuntimeError("member service not configured")
    updated = await member.reactivate(member_id, reactivated_by=actor)
    return {
        "member_id": updated.member_id,
        "status": updated.status,
        "_audit_detail": {
            "resource": f"member:{member_id}",
            "detail": "",
            "ip": "",
        },
    }


async def _handle_member_revoke(
    svc: ServiceRegistry, request: MemberRevokeRequest, actor: str
) -> dict[str, Any]:
    """멤버 영구 폐기 IPC handler."""
    member_id = request.member_id
    member = getattr(svc, "member_service", None)
    if member is None:
        raise RuntimeError("member service not configured")
    updated = await member.revoke(member_id, revoked_by=actor)
    return {
        "member_id": updated.member_id,
        "status": updated.status,
        "_audit_detail": {
            "resource": f"member:{member_id}",
            "detail": "",
            "ip": "",
        },
    }


async def _handle_member_rotate_token(
    svc: ServiceRegistry, request: MemberRotateTokenRequest, actor: str
) -> dict[str, Any]:
    """토큰 재발급 IPC handler."""
    member_id = request.member_id
    member = getattr(svc, "member_service", None)
    if member is None:
        raise RuntimeError("member service not configured")
    updated, token = await member.rotate_token(member_id, rotated_by=actor)
    return {
        "member_id": updated.member_id,
        "token": token,
        "_audit_detail": {
            "resource": f"member:{member_id}",
            "detail": "",
            "ip": "",
        },
    }


_RECOVERY_AUDIT_MEMBER_ID = "system:recovery"


async def _resolve_master_member_id(member: Any) -> str:
    """master(human) 멤버 ID 를 서버 측에서 해석한다."""
    members = await member.list_members(member_type="human")
    master = next((m for m in members if m.role == "master"), None)
    if master is None:
        msg = "master 멤버가 존재하지 않습니다"
        raise ValueError(msg)
    return cast("str", master.member_id)


async def _handle_member_reset_password(
    svc: ServiceRegistry, request: MemberResetPasswordRequest, actor: str
) -> dict[str, Any]:
    """recovery key 로 패스워드 리셋 IPC handler (auth-exempt)."""
    member = getattr(svc, "member_service", None)
    if member is None:
        raise RuntimeError("member service not configured")
    recovery_key = request.recovery_key.get_secret_value()
    new_password = request.new_password.get_secret_value()
    master_id = await _resolve_master_member_id(member)
    await member.reset_password(master_id, recovery_key, new_password)
    return {
        "_audit_detail": {
            "resource": f"member:{master_id}",
            "detail": "password reset via recovery key",
            "ip": "",
            "member_id": _RECOVERY_AUDIT_MEMBER_ID,
        },
    }


async def _handle_member_regenerate_recovery_key(
    svc: ServiceRegistry, request: MemberRegenerateRecoveryKeyRequest, actor: str
) -> dict[str, Any]:
    """recovery key 재발급 IPC handler (auth-exempt)."""
    member = getattr(svc, "member_service", None)
    if member is None:
        raise RuntimeError("member service not configured")
    password = request.password.get_secret_value()
    master_id = await _resolve_master_member_id(member)
    new_key = await member.regenerate_recovery_key(master_id, password)
    return {
        "recovery_key": new_key,
        "_audit_detail": {
            "resource": f"member:{master_id}",
            "detail": "recovery key regenerated",
            "ip": "",
            "member_id": _RECOVERY_AUDIT_MEMBER_ID,
        },
    }


async def _handle_config_set(
    svc: ServiceRegistry, request: ConfigSetRequest, actor: str
) -> dict[str, Any]:
    if is_account_rules_config_key(request.key):
        raise ConfigUnsupportedKeyError(
            "계좌 규칙 key(accounts.<account_id>.rules)는 config set으로 바꿀 수 "
            "없습니다. ante rule update <rule_type> --account <account_id>를 "
            "사용하세요."
        )
    key = request.key
    value = request.value
    category = request.category
    await svc.dynamic_config.set(key, value, category=category, changed_by=actor)
    return {"key": key, "value": value}


async def _handle_approval_request(
    svc: ServiceRegistry, request: ApprovalRequestRequest, actor: str
) -> dict[str, Any]:
    created = await svc.approval.create(
        type=request.type,
        requester=actor,
        title=request.title,
        body=request.body,
        params=request.params,
        reference_id=request.reference_id,
        expires_at=request.expires_at,
    )
    return {"id": created.id, "status": str(created.status)}


async def _handle_approval_approve(
    svc: ServiceRegistry, request: ApprovalApproveRequest, actor: str
) -> dict[str, Any]:
    """승인 요청 승인 IPC handler."""
    approval_id = request.id
    approval = await svc.approval.approve(approval_id, resolved_by=actor)
    return {
        "id": approval.id,
        "status": str(approval.status),
        "_audit_detail": {
            "resource": f"approval:{approval_id}",
            "detail": "",
            "ip": "",
        },
    }


async def _handle_approval_reject(
    svc: ServiceRegistry, request: ApprovalRejectRequest, actor: str
) -> dict[str, Any]:
    """승인 요청 거부 IPC handler."""
    approval_id = request.id
    reason = request.reason
    approval = await svc.approval.reject(
        approval_id,
        resolved_by=actor,
        reject_reason=reason,
    )
    return {
        "id": approval.id,
        "status": str(approval.status),
        "_audit_detail": {
            "resource": f"approval:{approval_id}",
            "detail": f"reason={reason}",
            "ip": "",
        },
    }


async def _handle_approval_cancel(
    svc: ServiceRegistry, request: ApprovalCancelRequest, actor: str
) -> dict[str, Any]:
    """승인 요청 취소 IPC handler."""
    approval_id = request.id
    approval = await svc.approval.cancel(approval_id, requester=actor)
    return {
        "id": approval.id,
        "status": str(approval.status),
        "_audit_detail": {
            "resource": f"approval:{approval_id}",
            "detail": "",
            "ip": "",
        },
    }


async def _handle_approval_cancel_invalid(
    svc: ServiceRegistry, request: ApprovalCancelInvalidRequest, actor: str
) -> dict[str, Any]:
    """Administrative cancellation of a legacy invalid-type approval."""
    approval_id = request.approval_id
    approval = await svc.approval.cancel_invalid_type_request(
        approval_id,
        resolved_by=actor,
    )

    return {
        "id": approval.id,
        "status": str(approval.status),
        "type": approval.type,
        "_audit_detail": {
            "resource": f"approval:{approval_id}",
            "detail": approval.type,
            "ip": "",
        },
    }


async def _handle_approval_reopen(
    svc: ServiceRegistry, request: ApprovalReopenRequest, actor: str
) -> dict[str, Any]:
    reopened = await svc.approval.reopen(
        request.id,
        requester=actor,
        body=request.body,
        params=request.params,
    )
    return {"id": reopened.id, "status": str(reopened.status)}


async def _handle_broker_status(
    svc: ServiceRegistry, request: BrokerStatusRequest, actor: str
) -> dict[str, Any]:
    broker = await svc.account.get_broker(request.account_id)
    healthy = await broker.health_check()
    return {
        "connected": broker.is_connected,
        "healthy": healthy,
        "exchange": broker.exchange,
    }


async def _handle_broker_balance(
    svc: ServiceRegistry, request: BrokerBalanceRequest, actor: str
) -> dict[str, Any]:
    broker = await svc.account.get_broker(request.account_id)
    return await broker.get_account_balance()


async def _handle_broker_positions(
    svc: ServiceRegistry, request: BrokerPositionsRequest, actor: str
) -> dict[str, Any]:
    broker = await svc.account.get_broker(request.account_id)
    return {"positions": await broker.get_positions()}


async def _handle_broker_order_history(
    svc: ServiceRegistry, request: BrokerOrderHistoryRequest, actor: str
) -> dict[str, Any]:
    """``broker.order_history`` — 주문/체결 이력 read-only 조회."""
    from ante.core.time import iso_to_kis_date

    if (
        request.from_date is not None
        and request.to_date is not None
        and date.fromisoformat(request.from_date) > date.fromisoformat(request.to_date)
    ):
        raise InvalidDateRangeError(
            f"조회 시작일({request.from_date})이(가) "
            f"조회 종료일({request.to_date}) 이후입니다."
        )
    from_date = iso_to_kis_date(request.from_date)
    to_date = iso_to_kis_date(request.to_date)
    broker = await svc.account.get_broker(request.account_id)
    return {"orders": await broker.get_order_history(from_date, to_date)}


def _broker_reconcile_envelope(
    *,
    account_id: str,
    fix: bool,
    fix_applied: bool,
    bot_count: int,
    adjustments: list[dict[str, Any]],
    mismatches: list[dict[str, Any]],
) -> dict[str, Any]:
    """``broker.reconcile`` 통일 응답 envelope 을 만든다."""
    return {
        "account_id": account_id,
        "fix": fix,
        "bot_count": bot_count,
        "adjustments": adjustments,
        "mismatches": mismatches,
        "total_symbols": len(mismatches),
        "discrepancies": mismatches,
        "match": len(mismatches) == 0,
        "fix_applied": fix_applied,
        "corrections": len(adjustments),
    }


async def _handle_broker_reconcile(
    svc: ServiceRegistry, request: BrokerReconcileRequest, actor: str
) -> dict[str, Any]:
    """``broker.reconcile`` account-level 대사(보정은 봇이 정확히 1개인 계좌만)."""
    account_id = request.account_id
    fix = request.fix

    await svc.account.ensure_reconcile_applicable(account_id)
    broker = await svc.account.get_broker(account_id)
    broker_positions = await broker.get_account_positions()

    bot_manager = getattr(svc, "bot_manager", None)
    account_bots: list[str] = []
    if bot_manager is not None:
        for info in bot_manager.list_bots():
            if info.get("account_id") == account_id:
                account_bots.append(info["bot_id"])
    bot_count = len(account_bots)

    if bot_count == 1:
        adjustments = await svc.reconciler.reconcile(
            account_bots[0],
            broker_positions,
            account_id=account_id,
            dry_run=not fix,
        )
        if fix and adjustments:
            await svc.audit_logger.log(
                member_id=actor,
                action="broker.reconcile",
                resource=f"account:{account_id}",
            )
        mismatches = await svc.reconciler.compute_account_diff(
            broker_positions, account_id=account_id
        )
        return _broker_reconcile_envelope(
            account_id=account_id,
            fix=fix,
            fix_applied=fix,
            bot_count=bot_count,
            adjustments=adjustments,
            mismatches=mismatches,
        )

    mismatches = await svc.reconciler.detect_account_level(
        broker_positions, account_id=account_id
    )
    return _broker_reconcile_envelope(
        account_id=account_id,
        fix=fix,
        fix_applied=False,
        bot_count=bot_count,
        adjustments=[],
        mismatches=mismatches,
    )


def register_all_handlers(registry: CommandRegistry) -> None:
    """런타임 커맨드 핸들러를 일괄 등록.

    각 핸들러는 mutating 또는 read-only로 분류된다. 등록 값은 생성기가
    ``docs/architecture/generated/ipc-commands.md``로 만든다. mutating 명령은
    ``IPCServer``가 ``SHUTTING_DOWN`` 상태일 때 ``SERVICE_UNAVAILABLE``로
    거부된다.

    `account.delete`는 1.0 IPC 계약에서 제외되었다. cold-path CLI에서
    AccountService.delete()를 직접 호출하므로 IPC 라우팅 대상이 아니다.
    """
    registry.register(
        "system.halt",
        _handle_system_halt,
        is_mutating=True,
        required_services=frozenset({"account", "audit_logger"}),
        audit_action="system.halt",
        request_model=SystemHaltRequest,
    )
    registry.register(
        "system.clear_halt",
        _handle_system_clear_halt,
        is_mutating=True,
        required_services=frozenset({"account", "audit_logger"}),
        audit_action="system.clear_halt",
        request_model=SystemClearHaltRequest,
    )
    registry.register(
        "account.suspend",
        _handle_account_suspend,
        is_mutating=True,
        required_services=frozenset({"account", "audit_logger"}),
        audit_action="account.suspend",
        request_model=AccountSuspendRequest,
    )
    registry.register(
        "account.activate",
        _handle_account_activate,
        is_mutating=True,
        required_services=frozenset({"account", "audit_logger"}),
        audit_action="account.activate",
        request_model=AccountActivateRequest,
    )
    registry.register(
        "bot.create",
        _handle_bot_create,
        is_mutating=True,
        required_services=frozenset(
            {"strategy_registry", "bot_manager", "audit_logger"}
        ),
        audit_action="bot.create",
        request_model=BotCreateRequest,
    )
    registry.register(
        "bot.remove",
        _handle_bot_remove,
        is_mutating=True,
        required_services=frozenset({"bot_manager", "audit_logger"}),
        audit_action="bot.delete",
        request_model=BotRemoveRequest,
    )
    registry.register(
        "bot.signal_key.rotate",
        _handle_bot_signal_key_rotate,
        is_mutating=True,
        required_services=frozenset({"bot_manager", "audit_logger"}),
        audit_action="bot.signal_key.rotate",
        request_model=BotSignalKeyRotateRequest,
    )
    registry.register(
        "bot.start",
        _handle_bot_start,
        is_mutating=True,
        required_services=frozenset({"bot_manager", "account", "audit_logger"}),
        audit_action="bot.start",
        request_model=BotStartRequest,
    )
    registry.register(
        "bot.stop",
        _handle_bot_stop,
        is_mutating=True,
        required_services=frozenset({"bot_manager", "audit_logger"}),
        audit_action="bot.stop",
        request_model=BotStopRequest,
    )
    registry.register(
        "bot.update",
        _handle_bot_update,
        is_mutating=True,
        required_services=frozenset({"bot_manager", "audit_logger"}),
        audit_action="bot.update",
        request_model=BotUpdateRequest,
    )
    registry.register(
        "treasury.allocate",
        _handle_treasury_allocate,
        is_mutating=True,
        required_services=frozenset({"bot_manager", "treasury_manager"}),
        request_model=TreasuryAllocateRequest,
    )
    registry.register(
        "treasury.deallocate",
        _handle_treasury_deallocate,
        is_mutating=True,
        required_services=frozenset({"bot_manager", "treasury_manager"}),
        request_model=TreasuryDeallocateRequest,
    )
    registry.register(
        "treasury.set_balance",
        _handle_treasury_set_balance,
        is_mutating=True,
        required_services=frozenset({"treasury_manager", "audit_logger"}),
        audit_action="treasury.set_balance",
        request_model=TreasurySetBalanceRequest,
    )
    registry.register(
        "rule.update",
        _handle_rule_update,
        is_mutating=True,
        required_services=frozenset({"account", "dynamic_config", "audit_logger"}),
        audit_action="account.rule.update",
        request_model=RuleUpdateRequest,
    )
    registry.register(
        "strategy.set_status",
        _handle_strategy_set_status,
        is_mutating=True,
        required_services=frozenset({"strategy_registry", "audit_logger"}),
        audit_action="strategy.set_status",
        request_model=StrategySetStatusRequest,
    )
    registry.register(
        "member.update_scopes",
        _handle_member_update_scopes,
        is_mutating=True,
        required_services=frozenset({"member_service", "audit_logger"}),
        audit_action="member.update_scopes",
        request_model=MemberUpdateScopesRequest,
    )
    registry.register(
        "member.register",
        _handle_member_register,
        is_mutating=True,
        required_services=frozenset({"member_service", "audit_logger"}),
        audit_action="member.register",
        request_model=MemberRegisterRequest,
    )
    registry.register(
        "member.set_emoji",
        _handle_member_set_emoji,
        is_mutating=True,
        required_services=frozenset({"member_service", "audit_logger"}),
        audit_action="member.set_emoji",
        request_model=MemberSetEmojiRequest,
    )
    registry.register(
        "member.suspend",
        _handle_member_suspend,
        is_mutating=True,
        required_services=frozenset({"member_service", "audit_logger"}),
        audit_action="member.suspend",
        request_model=MemberSuspendRequest,
    )
    registry.register(
        "member.reactivate",
        _handle_member_reactivate,
        is_mutating=True,
        required_services=frozenset({"member_service", "audit_logger"}),
        audit_action="member.reactivate",
        request_model=MemberReactivateRequest,
    )
    registry.register(
        "member.revoke",
        _handle_member_revoke,
        is_mutating=True,
        required_services=frozenset({"member_service", "audit_logger"}),
        audit_action="member.revoke",
        request_model=MemberRevokeRequest,
    )
    registry.register(
        "member.rotate_token",
        _handle_member_rotate_token,
        is_mutating=True,
        required_services=frozenset({"member_service", "audit_logger"}),
        audit_action="member.rotate_token",
        request_model=MemberRotateTokenRequest,
    )
    registry.register(
        "member.reset_password",
        _handle_member_reset_password,
        is_mutating=True,
        required_services=frozenset({"member_service", "audit_logger"}),
        audit_action="member.reset_password",
        request_model=MemberResetPasswordRequest,
    )
    registry.register(
        "member.regenerate_recovery_key",
        _handle_member_regenerate_recovery_key,
        is_mutating=True,
        required_services=frozenset({"member_service", "audit_logger"}),
        audit_action="member.regenerate_recovery_key",
        request_model=MemberRegenerateRecoveryKeyRequest,
    )
    registry.register(
        "config.set",
        _handle_config_set,
        is_mutating=True,
        required_services=frozenset({"dynamic_config"}),
        request_model=ConfigSetRequest,
    )
    registry.register(
        "approval.request",
        _handle_approval_request,
        is_mutating=True,
        required_services=frozenset({"approval"}),
        request_model=ApprovalRequestRequest,
    )
    registry.register(
        "approval.approve",
        _handle_approval_approve,
        is_mutating=True,
        required_services=frozenset({"approval", "audit_logger"}),
        audit_action="approval.approve",
        request_model=ApprovalApproveRequest,
    )
    registry.register(
        "approval.reject",
        _handle_approval_reject,
        is_mutating=True,
        required_services=frozenset({"approval", "audit_logger"}),
        audit_action="approval.reject",
        request_model=ApprovalRejectRequest,
    )
    registry.register(
        "approval.cancel",
        _handle_approval_cancel,
        is_mutating=True,
        required_services=frozenset({"approval", "audit_logger"}),
        audit_action="approval.cancel",
        request_model=ApprovalCancelRequest,
    )
    registry.register(
        "approval.cancel_invalid",
        _handle_approval_cancel_invalid,
        is_mutating=True,
        required_services=frozenset({"approval", "audit_logger"}),
        audit_action="approval.cancel_invalid",
        request_model=ApprovalCancelInvalidRequest,
    )
    registry.register(
        "approval.reopen",
        _handle_approval_reopen,
        is_mutating=True,
        required_services=frozenset({"approval"}),
        request_model=ApprovalReopenRequest,
    )
    registry.register(
        "broker.reconcile",
        _handle_broker_reconcile,
        is_mutating=True,
        required_services=frozenset(
            {"account", "reconciler", "bot_manager", "audit_logger"}
        ),
        request_model=BrokerReconcileRequest,
    )

    registry.register(
        "broker.status",
        _handle_broker_status,
        is_mutating=False,
        required_services=frozenset({"account"}),
        request_model=BrokerStatusRequest,
    )
    registry.register(
        "broker.balance",
        _handle_broker_balance,
        is_mutating=False,
        required_services=frozenset({"account"}),
        request_model=BrokerBalanceRequest,
    )
    registry.register(
        "broker.positions",
        _handle_broker_positions,
        is_mutating=False,
        required_services=frozenset({"account"}),
        request_model=BrokerPositionsRequest,
    )
    registry.register(
        "broker.order_history",
        _handle_broker_order_history,
        is_mutating=False,
        required_services=frozenset({"account"}),
        request_model=BrokerOrderHistoryRequest,
    )
    registry.register(
        "bot.status",
        _handle_bot_status,
        is_mutating=False,
        required_services=frozenset({"bot_manager"}),
        request_model=BotStatusRequest,
    )
    registry.register(
        "bot.list",
        _handle_bot_list,
        is_mutating=False,
        required_services=frozenset({"bot_manager"}),
        request_model=BotListRequest,
    )
    registry.register(
        "bot.info",
        _handle_bot_info,
        is_mutating=False,
        required_services=frozenset({"bot_manager"}),
        request_model=BotInfoRequest,
    )
    registry.register(
        "bot.positions",
        _handle_bot_positions,
        is_mutating=False,
        required_services=frozenset({"bot_manager"}),
        request_model=BotPositionsRequest,
    )
    registry.register(
        "bot.signal_key",
        _handle_bot_signal_key,
        is_mutating=False,
        required_services=frozenset({"bot_manager"}),
        request_model=BotSignalKeyRequest,
    )
    registry.register(
        "signal.connect",
        _handle_signal_connect,
        is_mutating=False,
        required_services=frozenset({"bot_manager"}),
        request_model=SignalConnectRequest,
    )
