"""CommandRegistry — IPC 커맨드 핸들러 등록 및 조회.

각 커맨드 핸들러는 (ServiceRegistry, args: dict, actor: str) -> dict 시그니처를 따른다.

Refs #1184: 각 등록 핸들러는 ``CommandSpec``으로 wrap되어 ``is_mutating``
taxonomy를 함께 보유한다. ``IPCServer._dispatch``는 lifecycle state가
``SHUTTING_DOWN``일 때 mutating 핸들러를 ``SERVICE_UNAVAILABLE``로 거부하기
위해 이 정보를 사용한다.

Refs #1849 (#1819 부모 epic): ``CommandSpec``에 contract metadata 7 필드를
추가한다(``result_kind``, ``result_key``, ``required_services``,
``audit_action``, ``account_id_policy``, ``cross_validators``,
``shutdown_behavior``). dispatch wrapper 동작 변경은 본 이슈 범위가 아니다
(#1850 / #1851 책임). default 값으로 backward compatibility를 보장한다.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from ante.contracts.vocab import ContractKind

if TYPE_CHECKING:
    from ante.core.registry import ServiceRegistry

CommandHandler = Callable[["ServiceRegistry", dict, str], Awaitable[dict]]

# Refs #1849 / Codex v2 condition 1: shutdown_behavior 한 타입 lock.
# None인 경우 ``is_mutating``에서 derive(``block_on_mutating``).
ShutdownBehavior = Literal["block_on_mutating", "block_all", "allow_all"]

# Refs #1849: account_id 강제 정책 vocabulary.
AccountIdPolicy = Literal["none", "required", "optional_filter"]

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CommandSpec:
    """IPC 커맨드의 메타데이터.

    Refs #1184: lifecycle state machine과 결합하여 shutdown 중
    mutating 명령을 거부하기 위한 taxonomy를 보유한다.

    Refs #1849 (#1819 부모 epic): contract metadata 7 신규 필드를 보유한다.
    dispatch wrapper의 실제 활용은 #1850(required_services 자동 검증) /
    #1851(audit_action 자동 발화) 책임이며, 본 이슈에서는 metadata 자체와
    27개 등록 명령의 필수값만 채운다.

    Attributes:
        name: 커맨드 식별자 (예: ``"system.halt"``).
        handler: 비동기 핸들러 콜러블.
        is_mutating: 핸들러가 서버 상태/DB를 변경하면 True. 단순 read-only
            (live 조회) 면 False.
        result_kind: handler 반환 result의 shape 종류
            (``entity``/``operation``/``collection``/``raw``/``stream``).
            ``ContractKind`` vocabulary(#1822)를 그대로 사용한다.
        result_key: handler 반환 dict의 주 키(예: ``"bot"``, ``"positions"``).
            ``None``이면 result가 dict 그 자체이거나 주 키가 없음.
        required_services: handler가 의존하는 ``ServiceRegistry`` attribute
            이름의 frozenset. dispatch wrapper의 service preflight(#1850)에서
            사용된다.
        audit_action: ``audit_logger.log(action=...)`` 인자. 실제로 audit
            기록을 남기는 명령만 값을 가지고, 그 외에는 ``None``.
            mutating이라는 사실만으로 audit_action을 강제하지 않는다
            (#1819 본문 / Codex v2 condition 3).
        account_id_policy: account_id 검증 정책.
            ``none``/``required``(handler가 ``require_account_id`` 호출)/
            ``optional_filter`` 중 하나.
        cross_validators: 추가 cross-field validator callables. 본 이슈에서는
            skeleton만 도입한다(빈 tuple default).
        shutdown_behavior: shutdown 단계 처리 override. ``None``이면
            ``is_mutating``에서 derive — mutating은 ``block_on_mutating``,
            read-only는 ``allow_all`` 효과(#1184 server.py 동작 보존).
    """

    name: str
    handler: CommandHandler
    is_mutating: bool
    result_kind: ContractKind = "raw"
    result_key: str | None = None
    required_services: frozenset[str] = field(default_factory=frozenset)
    audit_action: str | None = None
    account_id_policy: AccountIdPolicy = "none"
    cross_validators: tuple[Callable[..., Any], ...] = ()
    shutdown_behavior: ShutdownBehavior | None = None


class CommandRegistry:
    """커맨드 이름 -> CommandSpec 매핑.

    Refs #1184: 단순 dict[str, handler]에서 dict[str, CommandSpec]으로
    전환되었다. 외부 호출자는 ``register(name, handler, *, is_mutating=...)``
    keyword-only 인자를 명시해야 한다.

    Refs #1849: ``register()``는 contract metadata 7 신규 필드를 kwargs로
    추가 수용한다. 기존 ``register(name, handler, is_mutating=...)`` 호출은
    default 값으로 그대로 작동(backward compat).
    """

    def __init__(self) -> None:
        self._specs: dict[str, CommandSpec] = {}

    def register(
        self,
        command: str,
        handler: CommandHandler,
        *,
        is_mutating: bool,
        result_kind: ContractKind = "raw",
        result_key: str | None = None,
        required_services: frozenset[str] | None = None,
        audit_action: str | None = None,
        account_id_policy: AccountIdPolicy = "none",
        cross_validators: tuple[Callable[..., Any], ...] = (),
        shutdown_behavior: ShutdownBehavior | None = None,
    ) -> None:
        """핸들러 등록.

        Args:
            command: 커맨드 이름.
            handler: 비동기 핸들러.
            is_mutating: 변경 명령 여부. shutdown 중 reject 분기에서 사용.
            result_kind: result shape 종류 (#1822 ``ContractKind``).
            result_key: result dict의 주 키.
            required_services: ``ServiceRegistry`` 의존 attribute 이름 집합.
            audit_action: audit 기록 시 action 이름(없으면 ``None``).
            account_id_policy: account_id 검증 정책.
            cross_validators: 추가 validator callables.
            shutdown_behavior: shutdown 처리 override(없으면 derive).
        """
        self._specs[command] = CommandSpec(
            name=command,
            handler=handler,
            is_mutating=is_mutating,
            result_kind=result_kind,
            result_key=result_key,
            required_services=(
                required_services if required_services is not None else frozenset()
            ),
            audit_action=audit_action,
            account_id_policy=account_id_policy,
            cross_validators=cross_validators,
            shutdown_behavior=shutdown_behavior,
        )

    def get(self, command: str) -> CommandSpec | None:
        """CommandSpec 조회. 미등록이면 None."""
        return self._specs.get(command)

    def iter_specs(self) -> list[CommandSpec]:
        """등록된 모든 ``CommandSpec`` 목록.

        Refs #1849: registry metadata 완전성 단언/감사 시 사용. 반환 순서는
        등록 순서를 따른다(Python 3.7+ dict insertion order).
        """
        return list(self._specs.values())

    @property
    def commands(self) -> list[str]:
        """등록된 커맨드 목록 (이름만)."""
        return list(self._specs.keys())


# ── 핸들러 구현 ──────────────────────────────────────


def _kill_switch_payload(status: str, accounts: list[dict[str, Any]]) -> dict:
    """Kill Switch IPC 응답 envelope.

    ``status``, ``accounts_changed``, ``changed_at``, ``accounts[]`` shape를
    사용한다. ``changed_at``은 ISO 8601 UTC ``Z`` suffix를 사용한다
    (Refs #1360).
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

    # #1656 E bucket / #1633 finding: ``require_account_id``를 함수
    # **최상단**(strategy_registry.get / StrategyLoader.load 이전)으로 둔다.
    # 그래야 invalid/missing account_id direct-IPC payload가 strategy
    # lookup/load 오류(ValueError / 파일 IO)나 늦은 검증에 가리지 않고
    # ``InvalidAccountIdError``(code="VALIDATION_ERROR", #1633 SSOT)로 먼저
    # raise되어 server.py:323 ``getattr(e, "code", ...)``를 거쳐
    # VALIDATION_ERROR envelope이 된다. #1636 broker handlers(account_id-first)
    # 1:1 동형. Refs #1217 → #1241 SPLIT-2: account_id fallback 제거 — IPC
    # routing 진입점에서 ``ipc.bot.create`` context로 명시 검증한다.
    account_id = require_account_id(args.get("account_id"), context="ipc.bot.create")

    strategy_id = args["strategy_id"]
    record = await svc.strategy_registry.get(strategy_id)
    if record is None:
        msg = f"전략을 찾을 수 없습니다: {strategy_id}"
        raise ValueError(msg)

    strategy_cls = StrategyLoader.load(Path(record.filepath))

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


async def _handle_bot_start(
    svc: ServiceRegistry, args: dict[str, Any], actor: str
) -> dict:
    """봇 시작 IPC handler.

    Refs #1712: bot 부재 / app_key 부재 / BotError를 stable coded exception으로
    raise 한다. IPC
    ``server.py:323`` 의 ``getattr(e, "code", "EXECUTION_ERROR")`` envelope
    이 ``BOT_NOT_FOUND`` / ``BOT_ACCOUNT_CREDENTIALS_NOT_CONFIGURED`` /
    ``BOT_STATE_CONFLICT`` 로 변환한다.

    audit logger 가 주입된 환경에서는 ``approval.cancel_invalid`` 선례와 동형
    으로 ``bot.start`` action 을 기록한다(``getattr`` safe-access).
    """
    from ante.bot.exceptions import (
        BotAccountCredentialsNotConfigured,
        BotError,
        BotNotFoundError,
        BotStateConflict,
    )

    bot_id = args["bot_id"]
    bot = svc.bot_manager.get_bot(bot_id)
    if bot is None:
        raise BotNotFoundError(bot_id)

    # 계좌 인증정보 검증: app_key 가 없으면 봇 시작 거부.
    account = await svc.account.get(bot.config.account_id)
    if not account.credentials.get("app_key"):
        raise BotAccountCredentialsNotConfigured(
            "계좌에 인증정보(app_key)가 설정되지 않았습니다"
        )

    try:
        await svc.bot_manager.start_bot(bot_id)
    except BotError as e:
        raise BotStateConflict(str(e)) from e

    audit_logger = getattr(svc, "audit_logger", None)
    if audit_logger is not None:
        await audit_logger.log(
            member_id=actor,
            action="bot.start",
            resource=f"bot:{bot_id}",
            ip="",
        )

    return {"bot": bot.get_info()}


async def _handle_bot_stop(
    svc: ServiceRegistry, args: dict[str, Any], actor: str
) -> dict:
    """봇 중지 IPC handler.

    Refs #1712: bot 부재 / BotError를 stable coded exception으로 매핑한다.
    ``app_key`` preflight 는 stop 경로에 없다. audit logger 가 주입된 환경에서는
    ``bot.stop`` action 을 기록한다.
    """
    from ante.bot.exceptions import (
        BotError,
        BotNotFoundError,
        BotStateConflict,
    )

    bot_id = args["bot_id"]
    bot = svc.bot_manager.get_bot(bot_id)
    if bot is None:
        raise BotNotFoundError(bot_id)

    try:
        await svc.bot_manager.stop_bot(bot_id)
    except BotError as e:
        raise BotStateConflict(str(e)) from e

    audit_logger = getattr(svc, "audit_logger", None)
    if audit_logger is not None:
        await audit_logger.log(
            member_id=actor,
            action="bot.stop",
            resource=f"bot:{bot_id}",
            ip="",
        )

    return {"bot": bot.get_info()}


async def _handle_bot_status(
    svc: ServiceRegistry, args: dict[str, Any], actor: str
) -> dict:
    """봇 상태 조회 IPC handler.

    Refs #1712: read-only handler. ``enrich_bot_info`` 로 strategy/budget/
    positions 보강 결과를 ``{"bot": info}`` envelope 으로 반환한다.

    의존성은 모두 ``getattr`` safe-access 로 optional 처리한다:
    - ``strategy_registry`` 부재 시 strategy 키 부재.
    - ``treasury_manager`` 부재(또는 해당 계좌 Treasury 미등록) 시 budget 키 부재.
    - ``trade_service`` 부재(legacy ServiceRegistry) 시 positions 키 부재(회귀
      lock — #1712 cold-path 호환).

    read-only 분류이므로 audit logger 호출 없음.
    """
    from ante.bot.exceptions import BotNotFoundError
    from ante.bot.info import enrich_bot_info

    bot_id = args["bot_id"]
    bot = svc.bot_manager.get_bot(bot_id)
    if bot is None:
        raise BotNotFoundError(bot_id)

    # 계좌별 Treasury resolve. manager 부재 또는 미등록 시 None.
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
    )
    return {"bot": info}


async def _handle_bot_update(
    svc: ServiceRegistry, args: dict[str, Any], actor: str
) -> dict:
    from ante.bot.exceptions import BotError

    bot_id = args["bot_id"]
    updates = dict(args.get("updates") or {})
    bot = svc.bot_manager.get_bot(bot_id)
    if bot is None:
        from ante.bot.exceptions import BotNotFoundError

        raise BotNotFoundError(bot_id)
    try:
        bot = await svc.bot_manager.update_bot(bot_id, **updates)
    except BotError:
        raise

    audit_logger = getattr(svc, "audit_logger", None)
    if audit_logger is not None:
        await audit_logger.log(
            member_id=actor,
            action="bot.update",
            resource=f"bot:{bot_id}",
            detail=f"fields={list(updates.keys())}",
            ip="",
        )
    return {"bot": bot.get_info()}


async def _handle_treasury_allocate(
    svc: ServiceRegistry, args: dict[str, Any], actor: str
) -> dict:
    from ante.account.scoping import require_account_id
    from ante.bot.exceptions import BotNotFoundError

    # #1656 E bucket / #1633 finding: ``require_account_id``를 함수 **첫
    # 문장**으로(``args["bot_id"]``/``args["amount"]`` 이전) 둔다. raw
    # ``args["account_id"]`` 직접 인덱싱은 account_id 키 생략 payload에서
    # ``KeyError``가 먼저 터져 server.py:323 ``getattr(e, "code",
    # "EXECUTION_ERROR")``로 오분류된다. ``args.get`` +
    # ``require_account_id``로 invalid/missing 모두 ``InvalidAccountIdError``
    # (code="VALIDATION_ERROR", #1633 SSOT)로 먼저 raise되어
    # VALIDATION_ERROR envelope이 된다. #1636 broker handlers(args["bot_id"]
    # 이전 require_account_id) 1:1 동형.
    account_id = require_account_id(
        args.get("account_id"), context="ipc.treasury.allocate"
    )
    bot_id = args["bot_id"]
    amount = args["amount"]
    # #1792: missing bot id 로 호출해도 ``Treasury.allocate`` 가 cash 만 검증하고
    # bot 존재 여부를 검사하지 않아 exit 0 + status=ok 가 반환되던 회귀를 차단.
    # ``bot.start``/``bot.stop``/``bot.status``/``bot.update`` (registry.py:212/
    # 256/297/326) 와 동일한 ``svc.bot_manager.get_bot`` + ``BotNotFoundError``
    # (code="BOT_NOT_FOUND") 패턴을 사용한다. ``Treasury`` 서비스 자체는 단일
    # 책임(현금/예산)을 유지하고 IPC handler 가 cross-module 존재 검증을 한다.
    bot = svc.bot_manager.get_bot(bot_id)
    if bot is None:
        raise BotNotFoundError(bot_id)
    treasury = svc.treasury_manager.get(account_id)
    # #1809 (oracle A7 @ a5d8edf): ``Treasury.allocate`` 가 reject 시
    # ``bool=False`` 대신 reject reason 별 typed exception 을 raise 한다
    # (``TreasuryInvalidAmountError`` / ``TreasuryInsufficientUnallocatedError``).
    # IPC server.py:322 의 ``getattr(e, "code", "EXECUTION_ERROR")`` 가 stable
    # ``SCREAMING_SNAKE_CASE`` envelope ``code`` 로 자동 surface 시키므로
    # 명시 try/except 가 불필요하다 (handler 는 정상 경로만 성공 응답으로
    # 마무리). 결과는 항상 성공 (``success=True``) — reject 는 예외 경로.
    await treasury.allocate(bot_id, amount)
    return {"account_id": account_id, "bot_id": bot_id, "success": True}


async def _handle_treasury_deallocate(
    svc: ServiceRegistry, args: dict[str, Any], actor: str
) -> dict:
    from ante.account.scoping import require_account_id
    from ante.bot.exceptions import BotNotFoundError

    # #1656 E bucket / #1633 finding: ``_handle_treasury_allocate``와 동형 —
    # ``require_account_id``를 첫 문장으로(``args["bot_id"]``/``args["amount"]``
    # 이전, ``args.get``). 키 생략 payload의 ``KeyError`` →
    # EXECUTION_ERROR 누수 차단, invalid/missing 모두 VALIDATION_ERROR.
    account_id = require_account_id(
        args.get("account_id"), context="ipc.treasury.deallocate"
    )
    bot_id = args["bot_id"]
    amount = args["amount"]
    # #1792: allocate 와 동형 — bot 존재 검증을 ``Treasury.deallocate`` 호출
    # 이전에 둔다. ``BotNotFoundError`` (code="BOT_NOT_FOUND") 가 raise 되며
    # IPC server.py 의 ``getattr(e, "code", ...)`` envelope 으로 surface 된다.
    bot = svc.bot_manager.get_bot(bot_id)
    if bot is None:
        raise BotNotFoundError(bot_id)
    treasury = svc.treasury_manager.get(account_id)
    # #1809 (oracle A7 @ a5d8edf): allocate 와 동형 — typed exception
    # (``TreasuryInvalidAmountError`` / ``TreasuryBudgetNotFoundError`` /
    # ``TreasuryDeallocateExceedsAvailableError``) 을 server.py:322 envelope
    # 매핑으로 surface. 정상 경로는 항상 ``success=True``.
    await treasury.deallocate(bot_id, amount)
    return {"account_id": account_id, "bot_id": bot_id, "success": True}


async def _handle_treasury_set_balance(
    svc: ServiceRegistry, args: dict[str, Any], actor: str
) -> dict:
    from datetime import UTC, datetime

    from ante.account.scoping import require_account_id

    account_id = require_account_id(
        args.get("account_id"), context="ipc.treasury.set_balance"
    )
    balance = args["balance"]
    treasury = svc.treasury_manager.get(account_id)
    await treasury.set_account_balance(balance)

    audit_logger = getattr(svc, "audit_logger", None)
    if audit_logger is not None:
        await audit_logger.log(
            member_id=actor,
            action="treasury.set_balance",
            resource=f"treasury:{account_id}",
            detail=f"balance={balance:,.0f}",
            ip="",
        )
    return {
        "account_id": account_id,
        "total_balance": treasury.account_balance,
        "updated_at": datetime.now(UTC).isoformat(),
    }


async def _handle_rule_update(
    svc: ServiceRegistry, args: dict[str, Any], actor: str
) -> dict:
    from ante.account.scoping import require_account_id
    from ante.rule.config_update import update_account_rule_config

    account_id = require_account_id(args.get("account_id"), context="ipc.rule.update")
    return await update_account_rule_config(
        account_service=svc.account,
        dynamic_config=svc.dynamic_config,
        account_id=account_id,
        rule_type=args["rule_type"],
        enabled=bool(args.get("enabled", True)),
        params=dict(args.get("params") or {}),
        changed_by=actor,
        audit_logger=getattr(svc, "audit_logger", None),
    )


async def _handle_strategy_set_status(
    svc: ServiceRegistry, args: dict[str, Any], actor: str
) -> dict:
    from ante.strategy.registry import StrategyStatus

    strategy_id = args["strategy_id"]
    status = StrategyStatus(args["status"])
    await svc.strategy_registry.update_status(strategy_id, status)

    audit_logger = getattr(svc, "audit_logger", None)
    if audit_logger is not None:
        await audit_logger.log(
            member_id=actor,
            action="strategy.set_status",
            resource=f"strategy:{strategy_id}",
            detail=f"status={status.value}",
            ip="",
        )
    return {"strategy_id": strategy_id, "status": status.value}


async def _handle_member_update_scopes(
    svc: ServiceRegistry, args: dict[str, Any], actor: str
) -> dict:
    member_id = args["member_id"]
    scopes = list(args.get("scopes") or [])
    member_service = getattr(svc, "member_service", None)
    if member_service is None:
        raise RuntimeError("member service not configured")
    member = await member_service.update_scopes(member_id, scopes, updated_by=actor)

    audit_logger = getattr(svc, "audit_logger", None)
    if audit_logger is not None:
        await audit_logger.log(
            member_id=actor,
            action="member.update_scopes",
            resource=f"member:{member_id}",
            detail=f"scopes={scopes}",
            ip="",
        )
    return {
        "member_id": member.member_id,
        "scopes": member.scopes,
        "status": member.status,
    }


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
    """27개 런타임 커맨드 핸들러를 일괄 등록.

    Refs #1184: 각 핸들러는 mutating(23개) 또는 read-only(4개)로 분류된다.
    분류는 ``docs/specs/ipc/ipc.md``의 "Handler taxonomy" 섹션과 동기화되어야
    한다. mutating 명령은 ``IPCServer``가 ``SHUTTING_DOWN`` 상태일 때
    ``SERVICE_UNAVAILABLE``로 거부된다.

    `account.delete`는 1.0 IPC 계약에서 제외되었다 (#1139). cold-path CLI에서
    AccountService.delete()를 직접 호출하므로 IPC 라우팅 대상이 아니다.

    Refs #1418 → #1472 SPLIT-D: ``approval.cancel_invalid`` (mutating) 추가.

    Refs #1712: ``bot.start`` / ``bot.stop`` (mutating) / ``bot.status``
    (read-only) 추가. ``bot.start`` 는 ``app_key`` preflight + audit
    ``bot.start``, ``bot.stop`` 은 audit ``bot.stop``, ``bot.status`` 는
    ``enrich_bot_info`` 보강 후 ``{"bot": info}`` envelope.

    Refs #1849 (#1819 부모 epic): 각 등록에 contract metadata 7 필드 중
    필수값(``result_kind``, ``result_key``, ``required_services``,
    ``audit_action``, ``account_id_policy``)을 명시한다. ``audit_action``은
    실제 ``audit_logger.log`` 호출이 있는 명령만 값을 가진다(#1819 본문 /
    Codex v2 condition 3). ``cross_validators``/``shutdown_behavior``는 본
    이슈에서 default(빈 tuple / None=derive)로 유지한다.
    """
    # ── mutating (23개): 서버 상태/DB를 변경 ──────────
    # system.* — account_service의 suspend_all/activate_all (collective ops).
    registry.register(
        "system.halt",
        _handle_system_halt,
        is_mutating=True,
        result_kind="operation",
        required_services=frozenset({"account"}),
    )
    registry.register(
        "system.clear_halt",
        _handle_system_clear_halt,
        is_mutating=True,
        result_kind="operation",
        required_services=frozenset({"account"}),
    )
    # account.* — account_id 인자는 require_account_id 미사용(args["account_id"]
    # 직접 인덱싱)이라 policy는 ``none``으로 분류한다. 실제 검증 강제는 #1850
    # 후속에서 정책 정렬 시 재평가한다.
    registry.register(
        "account.suspend",
        _handle_account_suspend,
        is_mutating=True,
        result_kind="operation",
        required_services=frozenset({"account"}),
    )
    registry.register(
        "account.activate",
        _handle_account_activate,
        is_mutating=True,
        result_kind="operation",
        required_services=frozenset({"account"}),
    )
    # bot.* — bot 객체 entity 반환, audit_action은 start/stop/update만.
    registry.register(
        "bot.create",
        _handle_bot_create,
        is_mutating=True,
        result_kind="entity",
        result_key="bot_id",
        required_services=frozenset({"strategy_registry", "bot_manager"}),
        account_id_policy="required",
    )
    registry.register(
        "bot.remove",
        _handle_bot_remove,
        is_mutating=True,
        result_kind="operation",
        required_services=frozenset({"bot_manager"}),
    )
    registry.register(
        "bot.start",
        _handle_bot_start,
        is_mutating=True,
        result_kind="entity",
        result_key="bot",
        required_services=frozenset({"bot_manager", "account", "audit_logger"}),
        audit_action="bot.start",
    )
    registry.register(
        "bot.stop",
        _handle_bot_stop,
        is_mutating=True,
        result_kind="entity",
        result_key="bot",
        required_services=frozenset({"bot_manager", "audit_logger"}),
        audit_action="bot.stop",
    )
    registry.register(
        "bot.update",
        _handle_bot_update,
        is_mutating=True,
        result_kind="entity",
        result_key="bot",
        required_services=frozenset({"bot_manager", "audit_logger"}),
        audit_action="bot.update",
    )
    # treasury.* — allocate/deallocate는 success bool envelope(operation),
    # set_balance는 entity(account_id+total_balance+updated_at).
    registry.register(
        "treasury.allocate",
        _handle_treasury_allocate,
        is_mutating=True,
        result_kind="operation",
        required_services=frozenset({"bot_manager", "treasury_manager"}),
        account_id_policy="required",
    )
    registry.register(
        "treasury.deallocate",
        _handle_treasury_deallocate,
        is_mutating=True,
        result_kind="operation",
        required_services=frozenset({"bot_manager", "treasury_manager"}),
        account_id_policy="required",
    )
    registry.register(
        "treasury.set_balance",
        _handle_treasury_set_balance,
        is_mutating=True,
        result_kind="entity",
        required_services=frozenset({"treasury_manager", "audit_logger"}),
        audit_action="treasury.set_balance",
        account_id_policy="required",
    )
    # rule.update — update_account_rule_config helper 응답을 그대로 통과
    # (envelope shape이 helper 내부 결정이므로 raw).
    registry.register(
        "rule.update",
        _handle_rule_update,
        is_mutating=True,
        result_kind="raw",
        required_services=frozenset({"account", "dynamic_config", "audit_logger"}),
        account_id_policy="required",
    )
    registry.register(
        "strategy.set_status",
        _handle_strategy_set_status,
        is_mutating=True,
        result_kind="entity",
        required_services=frozenset({"strategy_registry", "audit_logger"}),
        audit_action="strategy.set_status",
    )
    registry.register(
        "member.update_scopes",
        _handle_member_update_scopes,
        is_mutating=True,
        result_kind="entity",
        required_services=frozenset({"member_service", "audit_logger"}),
        audit_action="member.update_scopes",
    )
    registry.register(
        "config.set",
        _handle_config_set,
        is_mutating=True,
        result_kind="operation",
        required_services=frozenset({"dynamic_config"}),
    )
    # approval.* — request/approve/reject/cancel/reopen은 audit_logger 호출이
    # 없고(서비스 내부 history append가 fallback), cancel_invalid만 명시
    # ``approval.cancel_invalid`` audit를 남긴다(#1418 → #1472 SPLIT-D).
    registry.register(
        "approval.request",
        _handle_approval_request,
        is_mutating=True,
        result_kind="entity",
        required_services=frozenset({"approval"}),
    )
    registry.register(
        "approval.approve",
        _handle_approval_approve,
        is_mutating=True,
        result_kind="entity",
        required_services=frozenset({"approval"}),
    )
    registry.register(
        "approval.reject",
        _handle_approval_reject,
        is_mutating=True,
        result_kind="entity",
        required_services=frozenset({"approval"}),
    )
    registry.register(
        "approval.cancel",
        _handle_approval_cancel,
        is_mutating=True,
        result_kind="entity",
        required_services=frozenset({"approval"}),
    )
    registry.register(
        "approval.cancel_invalid",
        _handle_approval_cancel_invalid,
        is_mutating=True,
        result_kind="entity",
        required_services=frozenset({"approval", "audit_logger"}),
        audit_action="approval.cancel_invalid",
    )
    registry.register(
        "approval.reopen",
        _handle_approval_reopen,
        is_mutating=True,
        result_kind="entity",
        required_services=frozenset({"approval"}),
    )
    # broker.reconcile은 reconciler.reconcile()이 correct_position/이벤트
    # publish를 수행하므로 일괄 mutating으로 분류한다. CLI ``--fix=False``
    # dryrun 분리는 후속 이슈.
    registry.register(
        "broker.reconcile",
        _handle_broker_reconcile,
        is_mutating=True,
        result_kind="operation",
        required_services=frozenset({"reconciler", "bot_manager"}),
        account_id_policy="required",
    )

    # ── read-only (4개): live 조회만 ──────────────────
    # broker.* read-only — broker 객체 메서드 결과를 그대로 envelope에 surface.
    # status는 connected/healthy/exchange dict(entity), balance는 broker
    # response dict 그대로(raw passthrough), positions는 list collection.
    registry.register(
        "broker.status",
        _handle_broker_status,
        is_mutating=False,
        result_kind="entity",
        required_services=frozenset({"account"}),
        account_id_policy="required",
    )
    registry.register(
        "broker.balance",
        _handle_broker_balance,
        is_mutating=False,
        result_kind="raw",
        required_services=frozenset({"account"}),
        account_id_policy="required",
    )
    registry.register(
        "broker.positions",
        _handle_broker_positions,
        is_mutating=False,
        result_kind="collection",
        result_key="positions",
        required_services=frozenset({"account"}),
        account_id_policy="required",
    )
    registry.register(
        "bot.status",
        _handle_bot_status,
        is_mutating=False,
        result_kind="entity",
        result_key="bot",
        required_services=frozenset({"bot_manager"}),
    )
