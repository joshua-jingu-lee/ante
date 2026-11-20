"""CommandRegistry — IPC 커맨드 핸들러 등록 및 조회.

각 커맨드 핸들러는 (ServiceRegistry, args: dict, actor: str) -> dict 시그니처를 따른다.

각 등록 핸들러는 ``CommandSpec``으로 wrap되어 ``is_mutating``
taxonomy를 함께 보유한다. ``IPCServer._dispatch``는 lifecycle state가
``SHUTTING_DOWN``일 때 mutating 핸들러를 ``SERVICE_UNAVAILABLE``로 거부하기
위해 이 정보를 사용한다.

``CommandSpec``의 contract metadata 7 필드(``result_kind``, ``result_key``,
``required_services``, ``audit_action``, ``account_id_policy``, ``cross_validators``,
``shutdown_behavior``)는 default 값으로 backward compatibility를 보장한다.
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

ShutdownBehavior = Literal["block_on_mutating", "block_all", "allow_all"]

AccountIdPolicy = Literal["none", "required", "optional_filter"]

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CommandSpec:
    """IPC 커맨드의 메타데이터.

    lifecycle state machine과 결합하여 shutdown 중
    mutating 명령을 거부하기 위한 taxonomy를 보유한다.

    contract metadata 7 필드를 보유한다.

    Attributes:
        name: 커맨드 식별자 (예: ``"system.halt"``).
        handler: 비동기 핸들러 콜러블.
        is_mutating: 핸들러가 서버 상태/DB를 변경하면 True. 단순 read-only
            (live 조회) 면 False.
        result_kind: handler 반환 result의 shape 종류
            (``entity``/``operation``/``collection``/``raw``/``stream``).
            ``ContractKind`` vocabulary를 그대로 사용한다.
        result_key: handler 반환 dict의 주 키(예: ``"bot"``, ``"positions"``).
            ``None``이면 result가 dict 그 자체이거나 주 키가 없음.
        required_services: handler가 의존하는 ``ServiceRegistry`` attribute
            이름의 frozenset. dispatch wrapper의 service preflight에서
            사용된다.
        audit_action: ``audit_logger.log(action=...)`` 인자. 실제로 audit
            기록을 남기는 명령만 값을 가지고, 그 외에는 ``None``.
            mutating이라는 사실만으로 audit_action을 강제하지 않는다.
        account_id_policy: account_id 검증 정책.
            ``none``/``required``(handler가 ``require_account_id`` 호출)/
            ``optional_filter`` 중 하나.
        cross_validators: 추가 cross-field validator callables. 본 이슈에서는
            skeleton만 도입한다(빈 tuple default).
        shutdown_behavior: shutdown 단계 처리 override. ``None``이면
            ``is_mutating``에서 derive — mutating은 ``block_on_mutating``,
            read-only는 ``allow_all`` 효과(server.py 동작 보존).
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

    외부 호출자는 ``register(name, handler, *, is_mutating=...)``
    keyword-only 인자를 명시해야 한다.

    ``register()``는 contract metadata 7 필드를 kwargs로
    수용한다. ``register(name, handler, is_mutating=...)`` 호출은
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
            result_kind: result shape 종류 (``ContractKind``).
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

        registry metadata 완전성 단언/감사 시 사용. 반환 순서는
        등록 순서를 따른다(Python 3.7+ dict insertion order).
        """
        return list(self._specs.values())

    @property
    def commands(self) -> list[str]:
        """등록된 커맨드 목록 (이름만)."""
        return list(self._specs.keys())


def _kill_switch_payload(status: str, accounts: list[dict[str, Any]]) -> dict:
    """Kill Switch IPC 응답 envelope.

    ``status``, ``accounts_changed``, ``changed_at``, ``accounts[]`` shape를
    사용한다. ``changed_at``은 ISO 8601 UTC ``Z`` suffix를 사용한다.
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
    """전역 거래 정지(kill switch) IPC handler.

    audit.md:115: audit 호출은 ``_dispatch`` wrapper 가
    ``CommandSpec.audit_action="system.halt"`` 기반으로 자동 발화한다. handler
    는 ``_audit_detail`` reserved key 로 ``resource="system:kill_switch"`` 를
    전달하며, wrapper 가 ``pop`` 으로 public envelope 진입 전에 strip 한다.
    """
    reason = args.get("reason", "IPC halt")
    accounts = await svc.account.suspend_all(reason=reason, suspended_by=actor)
    payload = _kill_switch_payload("halted", accounts)
    payload["_audit_detail"] = {
        "resource": "system:kill_switch",
        "detail": f"reason={reason}",
        "ip": "",
    }
    return payload


async def _handle_system_clear_halt(
    svc: ServiceRegistry, args: dict[str, Any], actor: str
) -> dict:
    """전역 거래 정지 해제 IPC handler.

    audit.md:116: audit 호출은 ``_dispatch`` wrapper 가
    ``CommandSpec.audit_action="system.clear_halt"`` 기반으로 자동 발화한다.
    handler 는 ``_audit_detail`` reserved key 로
    ``resource="system:kill_switch"`` 를 전달한다.
    """
    accounts = await svc.account.activate_all(activated_by=actor)
    payload = _kill_switch_payload("halt_cleared", accounts)
    payload["_audit_detail"] = {
        "resource": "system:kill_switch",
        "detail": "",
        "ip": "",
    }
    return payload


async def _handle_account_suspend(
    svc: ServiceRegistry, args: dict[str, Any], actor: str
) -> dict:
    """계좌 정지 IPC handler.

    account_id 검증은 ``_dispatch`` wrapper 가
    ``CommandSpec.account_id_policy="required"`` 기반으로 사전 수행하며,
    audit 호출은 wrapper 가 ``CommandSpec.audit_action="account.suspend"``
    기반으로 자동 발화한다. handler 는 ``_audit_detail`` reserved key 로
    ``resource`` / ``detail`` 만 전달하고, wrapper 가 ``pop`` 으로 public
    envelope 진입 전에 strip 한다.
    """
    account_id = args["account_id"]
    reason = args.get("reason", "IPC suspend")
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
    svc: ServiceRegistry, args: dict[str, Any], actor: str
) -> dict:
    """계좌 활성화 IPC handler.

    account_id 검증은 ``_dispatch`` wrapper 가
    ``CommandSpec.account_id_policy="required"`` 기반으로 사전 수행하며,
    audit 호출은 wrapper 가 ``CommandSpec.audit_action="account.activate"``
    기반으로 자동 발화한다. handler 는 ``_audit_detail`` reserved key 로
    ``resource`` 만 전달하고, wrapper 가 ``pop`` 으로 public envelope 진입
    전에 strip 한다.
    """
    account_id = args["account_id"]
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
    svc: ServiceRegistry, args: dict[str, Any], actor: str
) -> dict:
    from pathlib import Path

    from ante.account.scoping import require_account_id
    from ante.bot.config import BotConfig
    from ante.strategy.loader import StrategyLoader

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
    return {
        "bot_id": bot.bot_id,
        "_audit_detail": {
            "resource": f"bot:{bot.bot_id}",
            "detail": "",
            "ip": "",
        },
    }


async def _handle_bot_remove(
    svc: ServiceRegistry, args: dict[str, Any], actor: str
) -> dict:
    """봇 제거 IPC handler.

    audit.md:120: audit 호출은 ``_dispatch`` wrapper 가
    ``CommandSpec.audit_action="bot.delete"`` 기반으로 자동 발화한다. command
    이름은 ``bot.remove`` 이지만 audit action 은 audit.md SSOT 에 따라
    ``bot.delete`` 다. handler 는 ``_audit_detail`` reserved key 로
    ``resource="bot:{bot_id}"`` 를 전달한다.
    """
    bot_id = args["bot_id"]
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
    svc: ServiceRegistry, args: dict[str, Any], actor: str
) -> dict:
    """봇 시그널 키 재발급 IPC handler.

    ``bot signal-key --rotate`` 의 runtime IPC 경로
    (``bot.signal_key.rotate``). CLI 는
    본 handler 로만 라우팅한다 —
    runtime 경계 / audit / live 상태 정합성을 보존한다.

    ``BotManager.rotate_signal_key`` 는 ``_get_bot`` 존재 확인
    (``BotNotFoundError``) → ``accepts_external_signals`` 게이트
    (``BotNotAcceptingSignals``) → ``SignalKeyManager.rotate`` 위임의 동일
    invariant 를 적용한다. 두 typed exception 은 그대로 propagate 하여
    ``server.py`` 의 ``getattr(e, "code", "EXECUTION_ERROR")`` envelope 이
    ``BOT_NOT_FOUND`` / ``BOT_NOT_ACCEPTING_SIGNALS`` stable code 로
    변환한다. 전략 미발견 등 그 외 ``BotError`` 는 ``EXECUTION_ERROR``
    fallback (서버 경로 SSOT).

    audit.md:121: audit 호출은 ``_dispatch`` wrapper 가
    ``CommandSpec.audit_action = "bot.signal_key.rotate"`` 기반으로 자동
    발화하며, handler 는 ``_audit_detail`` reserved key 로
    ``resource = "bot:{bot_id}"`` 만 전달한다 (wrapper 가 ``pop`` 으로 public
    envelope 진입 전에 strip).
    """
    bot_id = args["bot_id"]
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
    svc: ServiceRegistry, args: dict[str, Any], actor: str
) -> dict:
    """봇 시작 IPC handler.

    bot 부재 / app_key 부재 / BotError를 stable coded exception으로
    raise 한다. IPC
    ``server.py:323`` 의 ``getattr(e, "code", "EXECUTION_ERROR")`` envelope
    이 ``BOT_NOT_FOUND`` / ``BOT_ACCOUNT_CREDENTIALS_NOT_CONFIGURED`` /
    ``BOT_STATE_CONFLICT`` 로 변환한다.

    audit 호출은 ``_dispatch`` wrapper 가 ``CommandSpec.audit_action
    = "bot.start"`` 기반으로 자동 발화한다. handler 는 ``_audit_detail``
    reserved key 로 ``resource`` 만 전달하며, wrapper 가 ``pop`` 으로
    public envelope 진입 전에 strip 한다.
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

    account = await svc.account.get(bot.config.account_id)
    if not account.credentials.get("app_key"):
        raise BotAccountCredentialsNotConfigured(
            "계좌에 인증정보(app_key)가 설정되지 않았습니다"
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
    svc: ServiceRegistry, args: dict[str, Any], actor: str
) -> dict:
    """봇 중지 IPC handler.

    bot 부재 / BotError를 stable coded exception으로 매핑한다.
    ``app_key`` preflight 는 stop 경로에 없다.

    audit 호출은 ``_dispatch`` wrapper 가 ``CommandSpec.audit_action
    = "bot.stop"`` 기반으로 자동 발화한다. handler 는 ``_audit_detail``
    reserved key 로 ``resource`` 만 전달한다.
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

    return {
        "bot": bot.get_info(),
        "_audit_detail": {
            "resource": f"bot:{bot_id}",
            "detail": "",
            "ip": "",
        },
    }


async def _handle_bot_status(
    svc: ServiceRegistry, args: dict[str, Any], actor: str
) -> dict:
    """봇 상태 조회 IPC handler.

    read-only handler. ``enrich_bot_info`` 로 strategy/budget/
    positions 보강 결과를 ``{"bot": info}`` envelope 으로 반환한다.

    의존성은 모두 ``getattr`` safe-access 로 optional 처리한다:
    - ``strategy_registry`` 부재 시 strategy 키 부재.
    - ``treasury_manager`` 부재(또는 해당 계좌 Treasury 미등록) 시 budget 키 부재.
    - ``trade_service`` 부재(legacy ServiceRegistry) 시 positions 키 부재(회귀
      lock — cold-path 호환).

    read-only 분류이므로 audit logger 호출 없음.
    """
    from ante.bot.exceptions import BotNotFoundError
    from ante.bot.info import enrich_bot_info

    bot_id = args["bot_id"]
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
    svc: ServiceRegistry, args: dict[str, Any], actor: str
) -> dict:
    """봇 목록 조회 IPC handler (read-only).

    ``bot status`` (``_handle_bot_status``) 미러 — read-only 분류이므로 audit
    logger 호출 없음. ``svc.bot_manager.list_bots()`` 가 반환하는 live
    ``Bot.get_info()`` dict 들을 CLI ``bot list`` 의 6-key projection
    (``bot_id``/``name``/``strategy_id``/``account_id``/``status``/
    ``created_at``) 으로 좁혀 snapshot fallback 의 ``SELECT ... FROM bots``
    행과 동일 shape 을 surface 한다.

    ``--account`` 필터는 CLI ingress 에서 검증된 뒤 ``account_id`` arg 로
    전달된다. ``None`` 이면 전체, 지정되면 해당 계좌 봇만 반환한다 (CLI SQL
    filter 와 동형). live ``get_info()`` 에 ``created_at`` 이 없으므로 None
    기본값으로 채운다 (snapshot 행과 key parity).
    """
    account_id = args.get("account_id")
    bots = svc.bot_manager.list_bots()
    result: list[dict[str, Any]] = []
    for info in bots:
        if account_id is not None and info.get("account_id") != account_id:
            continue
        result.append({key: info.get(key) for key in _BOT_LIST_KEYS})
    return {"bots": result}


async def _handle_bot_info(
    svc: ServiceRegistry, args: dict[str, Any], actor: str
) -> dict:
    """봇 상세 정보 조회 IPC handler (read-only).

    ``bot status`` 미러 — read-only, audit 없음. ``get_bot(bot_id)`` 가
    ``None`` 이면 ``BotNotFoundError`` (``BOT_NOT_FOUND`` envelope). 존재하면
    ``Bot.get_info()`` 전체를 ``{"bot": info}`` envelope 으로 반환한다. CLI
    fallback 의 ``SELECT * FROM bots`` 행과 공통 핵심키(``bot_id``/``name``/
    ``status``/``account_id``/``strategy_id``) 가 일치한다 (live≠snapshot 의
    완전 통일은 non-goal).
    """
    from ante.bot.exceptions import BotNotFoundError

    bot_id = args["bot_id"]
    bot = svc.bot_manager.get_bot(bot_id)
    if bot is None:
        raise BotNotFoundError(bot_id)
    return {"bot": bot.get_info()}


async def _handle_bot_positions(
    svc: ServiceRegistry, args: dict[str, Any], actor: str
) -> dict:
    """봇 보유 포지션 조회 IPC handler (read-only).

    ``bot status`` 미러 — read-only, audit 없음. ``get_bot(bot_id)`` 존재
    확인(``None`` → ``BotNotFoundError``) 후 ``trade_service`` 로 포지션을
    조회한다.

    ``trade_service`` 는 legacy ``ServiceRegistry`` 에서 ``None`` 일 수 있으므로
    ``getattr`` safe-access 한다 (``_handle_bot_status`` 의 ``trade_service``
    optional 처리 동형). **서비스 미구성(None)과 빈 포지션(0개) 을 혼동하지
    않는다**: ``trade_service`` 가 없으면 빈 list 를
    반환하되, 이는 "조회 불가" 가 아니라 "포지션 보강 미구성" 으로서 봇이
    존재함은 이미 확인되었다(``BotNotFoundError`` 분기와 분리).
    포지션 조회를 봇 계좌(``bot.config.account_id``) 로 스코핑해 타 계좌
    stale/legacy 포지션 누출을 차단한다.
    """
    from ante.bot.exceptions import BotNotFoundError

    bot_id = args["bot_id"]
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
    svc: ServiceRegistry, args: dict[str, Any], actor: str
) -> dict:
    """봇 시그널 키 조회 IPC handler (read-only).

    ``bot status`` 미러 — read-only, audit 없음. ``bot.signal_key.rotate``
    (mutating) 와 별개의 read command 다. ``get_bot(bot_id)`` 존재
    확인(``None`` → ``BotNotFoundError``) 후 ``get_signal_key(bot_id)`` 로
    현재 키를 조회한다. 키 미발급이면 ``signal_key=None`` 을 반환하며, CLI
    후처리(``SIGNAL_KEY_NOT_SET``) 가 None sentinel 을 surface 한다 (IPC·
    fallback 공통).
    """
    from ante.bot.exceptions import BotNotFoundError

    bot_id = args["bot_id"]
    bot = svc.bot_manager.get_bot(bot_id)
    if bot is None:
        raise BotNotFoundError(bot_id)

    key = await svc.bot_manager.get_signal_key(bot_id)
    return {"bot_id": bot_id, "signal_key": key}


async def _handle_signal_connect(
    svc: ServiceRegistry, args: dict[str, Any], actor: str
) -> dict:
    """``signal.connect`` 핸드셰이크 IPC handler (read-only).

    데몬-side·LIVE 상태 4-게이트를 순서대로 검증한 뒤, 통과 시
    ``_stream`` 센티넬이 포함된 dict 를 반환한다. ``IPCServer._handle_connection``
    이 ``response["result"]["_stream"] == "signal.connect"`` 를 감지해 동일 연결을
    long-lived 스트림으로 connection-upgrade 하며, wire 전송 직전 센티넬을 strip
    한다(절대 노출 안 됨 — ipc.md §"1:1 framing 불변").

    4-게이트(ipc.md §"3-Phase 연결"):

    * ① signal key 검증: ``validate_signal_key(key)`` → ``None`` 이면
      ``InvalidSignalKey``. key 부재(``args`` 에 ``key`` 없음)도 ``args.get`` 으로
      ``None`` → 동일 거부(``KeyError`` 아님).
    * ② 봇 존재: ``get_bot(bot_id)`` → ``None`` 이면 ``BotNotFoundError``
      (기존 코드 재사용, 재정의 금지).
    * ③ 봇 RUNNING: ``bot.status != BotStatus.RUNNING`` 이면
      ``BotNotRunning(bot_id, bot.status.value)`` (소문자 ``.value``).
    * ④ 외부 시그널 수용: 전략 부재 또는 ``accepts_external_signals=False`` 면
      ``BotNotAcceptingSignals``.

    ``account_id`` 는 LIVE ``bot.config`` 에서만 취하고 ``args`` 의 spoof 값은
    무시한다. ``audit_action=None`` (자동 audit OFF) — 게이트
    통과 후 단일 manual connect-audit 를 직접 1회 발화한다(actor sentinel
    ``"ipc"``). 키는 로깅/반환에 노출하지 않는다.

    register happen-before ack (F1+F4): gate-4 통과 후 ``_stream``
    반환 **전** ``SignalChannelRegistry.register`` 를 atomic check-and-insert
    로 호출한다(``BotSignalChannelBusy``/``SignalChannelRegistryFrozen`` 둘 다
    ack write **전** raise → Phase-B envelope, stream 미진입). 이 시점의
    ``ChannelHandle`` 은 placeholder(데이터플레인 None) 이며 ``generation`` 을
    스냅샷한다 — ``_run_signal_stream`` 진입 후 adopt 가 데이터플레인을 채우고
    generation re-check 로 rotate-in-window 를 self-close 한다. ``reg`` 가
    ``None`` (headless/legacy)이면 register 를 스킵하고 session_id 만 전달한다.
    """
    from uuid import uuid4

    from ante.bot.config import BotStatus
    from ante.bot.exceptions import (
        BotNotAcceptingSignals,
        BotNotFoundError,
        BotNotRunning,
        InvalidSignalKey,
    )

    key = args.get("key")
    if not isinstance(key, str):
        raise InvalidSignalKey()
    bot_id = await svc.bot_manager.validate_signal_key(key)
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
    svc: ServiceRegistry, args: dict[str, Any], actor: str
) -> dict:
    """봇 업데이트 IPC handler.

    audit 호출은 ``_dispatch`` wrapper 가 ``CommandSpec.audit_action
    = "bot.update"`` 기반으로 자동 발화한다. handler 는 ``_audit_detail``
    reserved key 로 ``resource`` 와 ``detail`` (변경 필드 목록) 을 전달한다.
    """
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

    return {
        "bot": bot.get_info(),
        "_audit_detail": {
            "resource": f"bot:{bot_id}",
            "detail": f"fields={list(updates.keys())}",
            "ip": "",
        },
    }


async def _handle_treasury_allocate(
    svc: ServiceRegistry, args: dict[str, Any], actor: str
) -> dict:
    from ante.account.errors import InvalidAccountIdError
    from ante.account.scoping import require_account_id
    from ante.bot.exceptions import BotNotFoundError

    account_id = require_account_id(
        args.get("account_id"), context="ipc.treasury.allocate"
    )
    bot_id = args["bot_id"]
    amount = args["amount"]
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
    svc: ServiceRegistry, args: dict[str, Any], actor: str
) -> dict:
    from ante.account.errors import InvalidAccountIdError
    from ante.account.scoping import require_account_id
    from ante.bot.exceptions import BotNotFoundError

    account_id = require_account_id(
        args.get("account_id"), context="ipc.treasury.deallocate"
    )
    bot_id = args["bot_id"]
    amount = args["amount"]
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
    svc: ServiceRegistry, args: dict[str, Any], actor: str
) -> dict:
    """Treasury balance 설정 IPC handler.

    audit 호출은 ``_dispatch`` wrapper 가 ``CommandSpec.audit_action
    = "treasury.set_balance"`` 기반으로 자동 발화한다. handler 는
    ``_audit_detail`` reserved key 로 ``resource`` 와 ``detail`` (설정된
    balance) 을 전달한다.
    """
    from datetime import UTC, datetime

    from ante.account.scoping import require_account_id

    account_id = require_account_id(
        args.get("account_id"), context="ipc.treasury.set_balance"
    )
    balance = args["balance"]
    treasury = svc.treasury_manager.get(account_id)
    await treasury.set_account_balance(balance)

    return {
        "account_id": account_id,
        "total_balance": treasury.account_balance,
        "updated_at": datetime.now(UTC).isoformat(),
        "_audit_detail": {
            "resource": f"treasury:{account_id}",
            "detail": f"balance={balance:,.0f}",
            "ip": "",
        },
    }


async def _handle_rule_update(
    svc: ServiceRegistry, args: dict[str, Any], actor: str
) -> dict:
    """계좌 룰 업데이트 IPC handler.

    account_id 검증은 ``_dispatch`` wrapper 가
    ``CommandSpec.account_id_policy="required"`` 기반으로 사전 수행한다. audit
    호출은 wrapper 가 ``CommandSpec.audit_action="account.rule.update"`` 기반
    으로 자동 발화하며, handler 는 helper 에 ``audit_logger=None`` 을 전달하여
    helper 내부 audit 발화를 끈다(CLI offline path 는 ``audit_logger`` 를
    그대로 전달하여 기존 동작 유지). handler 는 helper 결과에
    ``_audit_detail`` reserved key 를 덧붙여 wrapper 가 ``pop`` 으로 strip
    한다.
    """
    from ante.rule.config_update import update_account_rule_config

    account_id = args["account_id"]
    rule_type = args["rule_type"]
    enabled = bool(args.get("enabled", True))
    result = await update_account_rule_config(
        account_service=svc.account,
        dynamic_config=svc.dynamic_config,
        account_id=account_id,
        rule_type=rule_type,
        enabled=enabled,
        params=dict(args.get("params") or {}),
        changed_by=actor,
        audit_logger=None,
    )
    result["_audit_detail"] = {
        "resource": f"account:{account_id}:rule:{rule_type}",
        "detail": f"rule update: {rule_type} enabled={enabled}",
        "ip": "",
    }
    return result


async def _handle_strategy_set_status(
    svc: ServiceRegistry, args: dict[str, Any], actor: str
) -> dict:
    """전략 상태 변경 IPC handler.

    audit 호출은 ``_dispatch`` wrapper 가 ``CommandSpec.audit_action
    = "strategy.set_status"`` 기반으로 자동 발화한다. handler 는
    ``_audit_detail`` reserved key 로 ``resource`` 와 ``detail`` (status) 을
    전달한다.
    """
    from ante.strategy.registry import StrategyStatus

    strategy_id = args["strategy_id"]
    status = StrategyStatus(args["status"])
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
    svc: ServiceRegistry, args: dict[str, Any], actor: str
) -> dict:
    """멤버 scope 업데이트 IPC handler.

    audit 호출은 ``_dispatch`` wrapper 가 ``CommandSpec.audit_action
    = "member.update_scopes"`` 기반으로 자동 발화한다. handler 는
    ``_audit_detail`` reserved key 로 ``resource`` 와 ``detail`` (scopes 목록) 을
    전달한다.
    """
    member_id = args["member_id"]
    scopes = list(args.get("scopes") or [])
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
    svc: ServiceRegistry, args: dict[str, Any], actor: str
) -> dict:
    """멤버 등록 IPC handler.

    ``member.update_scopes`` 미러. ``registered_by=actor`` 로
    서버 측 master 게이트(``MemberService.register`` 내부 검증)를 보존한다.

    secret 비노출: 발급 토큰은 사용자 표시용 result(``token``) 에만 담고,
    ``_audit_detail`` (resource/detail) 이나 server logger / IPC error
    envelope 어디에도 넘기지 않는다. ``_audit_detail`` 에는 resource 만 둔다.
    """
    member_id = args["member_id"]
    member = getattr(svc, "member_service", None)
    if member is None:
        raise RuntimeError("member service not configured")
    created, token = await member.register(
        member_id=member_id,
        member_type=args["member_type"],
        org=args.get("org", "default"),
        name=args.get("name", ""),
        scopes=list(args.get("scopes") or []),
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
    svc: ServiceRegistry, args: dict[str, Any], actor: str
) -> dict:
    """멤버 emoji 설정 IPC handler.

    CLI ``member set-emoji`` → ``MemberService.update_emoji``
    (``set_emoji`` 메서드는 없음). ``updated_by=actor`` 로 호출한다.
    """
    member_id = args["member_id"]
    emoji = args["emoji"]
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
    svc: ServiceRegistry, args: dict[str, Any], actor: str
) -> dict:
    """멤버 일시 정지 IPC handler.

    ``suspended_by=actor`` 로 ``MemberService.suspend`` 내부의
    master 게이트(``_assert_master(actor)``)를 보존한다.
    """
    member_id = args["member_id"]
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
    svc: ServiceRegistry, args: dict[str, Any], actor: str
) -> dict:
    """멤버 재활성화 IPC handler.

    ``reactivated_by=actor`` 로 master 게이트를 보존한다.
    """
    member_id = args["member_id"]
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
    svc: ServiceRegistry, args: dict[str, Any], actor: str
) -> dict:
    """멤버 영구 폐기 IPC handler.

    ``revoked_by=actor`` 로 master 게이트를 보존한다. CLI
    ``--yes`` 게이트는 라우팅 이전 CLI 단에서 검사한다.
    """
    member_id = args["member_id"]
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
    svc: ServiceRegistry, args: dict[str, Any], actor: str
) -> dict:
    """토큰 재발급 IPC handler.

    ``rotated_by=actor`` 로 master 게이트를 보존한다.

    secret 비노출: 새 토큰은 사용자 표시용 result(``token``) 에만 담고
    ``_audit_detail`` / server logger / IPC error envelope 어디에도 넘기지
    않는다.
    """
    member_id = args["member_id"]
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
    """master(human) 멤버 ID 를 서버 측에서 해석한다.

    reset_password / regenerate_recovery_key 는 auth-exempt 라
    client 가 대상 member_id 를 보내지 않는다. master-lookup 을 CLI 가 아니라
    서버 chokepoint(handler)에서 수행해 단일 경로로 일관 적용한다.
    """
    members = await member.list_members(member_type="human")
    master = next((m for m in members if m.role == "master"), None)
    if master is None:
        msg = "master 멤버가 존재하지 않습니다"
        raise ValueError(msg)
    return master.member_id


async def _handle_member_reset_password(
    svc: ServiceRegistry, args: dict[str, Any], actor: str
) -> dict:
    """recovery key 로 패스워드 리셋 IPC handler (auth-exempt).

    args 는 secret(``recovery_key`` / ``new_password``) 만 받는다.
    대상 master member_id 는 서버 chokepoint 에서 ``list_members`` +
    role filter 로 해석한다(client actor 신뢰 금지).

    secret 비노출: ``recovery_key`` / ``new_password`` 는 ``_audit_detail``
    (resource/detail) 이나 server logger / IPC error envelope 어디에도
    넣지 않는다. ``detail`` 은 flow 표식만 둔다.

    audit member_id 는 client actor(스푸핑 가능) 가 아니라 고정 sentinel
    상수(``_RECOVERY_AUDIT_MEMBER_ID``) 로 기록한다 —
    ``_audit_detail["member_id"]`` override 로 wrapper 에 전달한다.
    """
    member = getattr(svc, "member_service", None)
    if member is None:
        raise RuntimeError("member service not configured")
    recovery_key = args["recovery_key"]
    new_password = args["new_password"]
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
    svc: ServiceRegistry, args: dict[str, Any], actor: str
) -> dict:
    """recovery key 재발급 IPC handler (auth-exempt).

    args 는 secret(``password``) 만 받는다. 대상 master member_id 는
    서버 chokepoint 에서 해석한다(client actor 신뢰 금지).

    secret 비노출: 입력 ``password`` 와 재발급된 ``recovery_key`` 는
    ``_audit_detail`` (resource/detail) 이나 server logger / IPC error
    envelope 어디에도 넘기지 않는다. 새 recovery key 는 사용자 표시용
    result(``recovery_key``) 에만 담는다.

    audit member_id 는 client actor 가 아니라 고정 sentinel 상수로 기록한다.
    """
    member = getattr(svc, "member_service", None)
    if member is None:
        raise RuntimeError("member service not configured")
    password = args["password"]
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
    """승인 요청 승인 IPC handler.

    audit.md:112: audit 호출은 ``_dispatch`` wrapper 가
    ``CommandSpec.audit_action="approval.approve"`` 기반으로 자동 발화한다.
    handler 는 ``_audit_detail`` reserved key 로
    ``resource="approval:{id}"`` 를 전달한다.
    """
    approval_id = args["id"]
    request = await svc.approval.approve(approval_id, resolved_by=actor)
    return {
        "id": request.id,
        "status": str(request.status),
        "_audit_detail": {
            "resource": f"approval:{approval_id}",
            "detail": "",
            "ip": "",
        },
    }


async def _handle_approval_reject(
    svc: ServiceRegistry, args: dict[str, Any], actor: str
) -> dict:
    """승인 요청 거부 IPC handler.

    audit.md:113: audit 호출은 ``_dispatch`` wrapper 가
    ``CommandSpec.audit_action="approval.reject"`` 기반으로 자동 발화한다.
    handler 는 ``_audit_detail`` reserved key 로
    ``resource="approval:{id}"`` 를 전달한다.
    """
    approval_id = args["id"]
    reason = args.get("reason", "")
    request = await svc.approval.reject(
        approval_id,
        resolved_by=actor,
        reject_reason=reason,
    )
    return {
        "id": request.id,
        "status": str(request.status),
        "_audit_detail": {
            "resource": f"approval:{approval_id}",
            "detail": f"reason={reason}",
            "ip": "",
        },
    }


async def _handle_approval_cancel(
    svc: ServiceRegistry, args: dict[str, Any], actor: str
) -> dict:
    """승인 요청 취소 IPC handler.

    audit.md:114: audit 호출은 ``_dispatch`` wrapper 가
    ``CommandSpec.audit_action="approval.cancel"`` 기반으로 자동 발화한다.
    handler 는 ``_audit_detail`` reserved key 로
    ``resource="approval:{id}"`` 를 전달한다.
    """
    approval_id = args["id"]
    request = await svc.approval.cancel(approval_id, requester=actor)
    return {
        "id": request.id,
        "status": str(request.status),
        "_audit_detail": {
            "resource": f"approval:{approval_id}",
            "detail": "",
            "ip": "",
        },
    }


async def _handle_approval_cancel_invalid(
    svc: ServiceRegistry, args: dict[str, Any], actor: str
) -> dict:
    """Administrative cancellation of a legacy invalid-type approval.

    CLI ``approval:admin`` scope 를 보유한 운영자가
    ``ante approval cancel-invalid <id>`` 로 호출한다. 성공 후 ``audit_log``
    테이블에 기록을 남기며, 서비스의 ``history`` append 가 fallback 추적
    경로다.

    audit 호출은 ``_dispatch`` wrapper 가 ``CommandSpec.audit_action
    = "approval.cancel_invalid"`` 기반으로 자동 발화한다. handler 는
    ``_audit_detail`` reserved key 로 ``resource`` 와 ``detail`` (request.type)
    을 전달한다.
    """
    approval_id = args["approval_id"]
    request = await svc.approval.cancel_invalid_type_request(
        approval_id,
        resolved_by=actor,
    )

    return {
        "id": request.id,
        "status": str(request.status),
        "type": request.type,
        "_audit_detail": {
            "resource": f"approval:{approval_id}",
            "detail": request.type,
            "ip": "",
        },
    }


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


async def _handle_broker_order_history(
    svc: ServiceRegistry, args: dict[str, Any], actor: str
) -> dict:
    """``broker.order_history`` — 주문/체결 이력 read-only 조회.

    ``_handle_broker_positions`` 동형이며 ``{"orders": [...]}`` envelope 을
    반환한다. 반환 row 는 ``BrokerAdapter.get_order_history`` 의 **정규화 8키**
    (``order_id`` / ``symbol`` / ``side`` / ``quantity`` / ``filled_quantity`` /
    ``price`` / ``status`` / ``timestamp``) 이며, KIS 원시 필드는 어댑터의
    fold 단계에서 이미 버려져 이 경계에 존재하지 않는다.

    **날짜 변환 chokepoint**: ``from_date``/``to_date`` 는 공개 표면 어휘인
    ISO ``YYYY-MM-DD`` 로 받아 :func:`ante.core.time.iso_to_kis_date` 로
    어댑터 경계 압축 ``YYYYMMDD`` 로 바꾼 뒤에만 전달한다. CLI click callback
    (``validate_iso_date``)을 우회하는 직접 IPC 호출도 여기서 fail-closed 로
    거부된다(``InvalidIsoDateError.code = "VALIDATION_ERROR"``).

    검증 순서는 ``account_id`` 우선(broker handlers account_id-first)
    이다 — invalid account_id 는 날짜 파싱보다 먼저 ``VALIDATION_ERROR`` 로
    거부된다.
    """
    from ante.account.scoping import require_account_id
    from ante.core.time import iso_to_kis_date

    account_id = require_account_id(
        args.get("account_id"), context="ipc.broker.order_history"
    )
    from_date = iso_to_kis_date(args.get("from_date"))
    to_date = iso_to_kis_date(args.get("to_date"))
    broker = await svc.account.get_broker(account_id)
    return {"orders": await broker.get_order_history(from_date, to_date)}


def _broker_reconcile_envelope(
    *,
    account_id: str,
    fix: bool,
    bot_count: int,
    adjustments: list[dict[str, Any]],
    mismatches: list[dict[str, Any]],
) -> dict[str, Any]:
    """``broker.reconcile`` 통일 응답 envelope 을 만든다.

    account-level 신규 필드(``account_id``/``fix``/``bot_count``/``adjustments``/
    ``mismatches``)와, CLI/agent display 호환을 위한 legacy 필드
    (``total_symbols``/``discrepancies``/``match``/``fix_applied``/``corrections``)
    를 함께 노출해 IPC·CLI passthrough envelope shape 를 일관 유지한다.
    """
    return {
        "account_id": account_id,
        "fix": fix,
        "bot_count": bot_count,
        "adjustments": adjustments,
        "mismatches": mismatches,
        "total_symbols": len(mismatches),
        "discrepancies": mismatches,
        "match": len(mismatches) == 0,
        "fix_applied": fix,
        "corrections": len(adjustments),
    }


async def _handle_broker_reconcile(
    svc: ServiceRegistry, args: dict[str, Any], actor: str
) -> dict:
    """``broker.reconcile`` — **account-level** 대사.

    account_id 만으로 동작한다(bot_id 불요). 서버 BrokerAdapter 가 계좌
    총합을 직접 조회하며(caller-supplied broker_positions 무시), ``fix``
    플래그를 준수한다. 잘못된 ``correct_position`` 이 실거래 포지션을
    손상시키지 않도록 **correction 은 봇이 정확히 1개인 계좌에서만** 기존
    ``reconcile`` 로직에 위임하고, 그 외(2+봇·0봇)는 detect-only 다.

    봇 count 분기 (status 무관 — 수동 IPC 는 user-initiated 라 봇 상태와
    무관하게 단일봇 귀속이 자명):
        - 정확히 1봇: ``reconciler.reconcile(bot_id, ..., dry_run=not fix)`` —
          기존 self-check/skip_external_buy/external-buy 분류 그대로.
          fix=True 면 보정, fix=False 면 detect-only.
        - 2+봇: ``reconciler.detect_account_level(...)`` (correct_position 미호출).
        - 0봇 + broker_positions 비어있지 않음: account-level detect/alert.
    """
    from ante.account.scoping import require_account_id

    account_id = require_account_id(
        args.get("account_id"), context="ipc.broker.reconcile"
    )
    fix = bool(args.get("fix", False))

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
        bot_count=bot_count,
        adjustments=[],
        mismatches=mismatches,
    )


def register_all_handlers(registry: CommandRegistry) -> None:
    """42개 런타임 커맨드 핸들러를 일괄 등록.

    각 핸들러는 mutating(32개) 또는 read-only(10개)로 분류된다.
    분류는 ``docs/specs/ipc/ipc.md``의 "Handler taxonomy" 섹션과 동기화되어야
    한다. mutating 명령은 ``IPCServer``가 ``SHUTTING_DOWN`` 상태일 때
    ``SERVICE_UNAVAILABLE``로 거부된다.

    `account.delete`는 1.0 IPC 계약에서 제외되었다. cold-path CLI에서
    AccountService.delete()를 직접 호출하므로 IPC 라우팅 대상이 아니다.

    ``approval.cancel_invalid`` (mutating).

    ``bot.start`` / ``bot.stop`` (mutating) / ``bot.status``
    (read-only): ``bot.start`` 는 ``app_key`` preflight + audit
    ``bot.start``, ``bot.stop`` 은 audit ``bot.stop``, ``bot.status`` 는
    ``enrich_bot_info`` 보강 후 ``{"bot": info}`` envelope.

    각 등록에 contract metadata 7 필드 중
    필수값(``result_kind``, ``result_key``, ``required_services``,
    ``audit_action``, ``account_id_policy``)을 명시한다. ``audit_action``은
    실제 ``audit_logger.log`` 호출이 있는 명령만 값을 가진다.
    ``cross_validators``/``shutdown_behavior``는
    default(빈 tuple / None=derive)로 유지한다.

    ``rule.update`` 는 helper 의 ``audit_logger`` 인자를 IPC handler 에서
    ``None`` 으로 전달하고, wrapper 가 ``audit_action="account.rule.update"``
    를 자동 발화한다.

    audit.md:112-120 이 audit 대상으로 정의한 상태변경 명령 가운데 다음 7개에
    ``audit_action`` + ``audit_logger`` required 를 wiring 한다 —
    ``system.halt`` (action ``system.halt``) / ``system.clear_halt`` /
    ``bot.create`` (resource 는 생성 결과 ``bot.bot_id``) / ``bot.remove``
    (action ``bot.delete``) / ``approval.approve`` / ``approval.reject`` /
    ``approval.cancel``. 각각 account.suspend 동형으로 register 에 audit_action
    부여 + required_services union audit_logger, handler 가 ``_audit_detail``
    반환. 현재 ``audit_action`` 부여 commands 는 26개:
    ``account.suspend`` / ``account.activate`` / ``system.halt`` /
    ``system.clear_halt`` / ``bot.create`` / ``bot.remove``(→``bot.delete``) /
    ``bot.start`` / ``bot.stop`` / ``bot.update`` /
    ``bot.signal_key.rotate`` / ``treasury.set_balance`` /
    ``strategy.set_status`` / ``member.update_scopes`` /
    ``member.register`` / ``member.set_emoji`` / ``member.suspend`` /
    ``member.reactivate`` / ``member.revoke`` / ``member.rotate_token`` /
    ``member.reset_password`` / ``member.regenerate_recovery_key`` /
    ``approval.approve`` / ``approval.reject`` / ``approval.cancel`` /
    ``approval.cancel_invalid`` / ``rule.update``.

    ``bot.list`` / ``bot.info`` / ``bot.positions`` /
    ``bot.signal_key`` (read-only): ``bot list/info/positions/signal-key``
    의 runtime IPC 경로. CLI 가 서버 정지 시 snapshot DB fallback 한다. audit
    없음(read-only).

    member admin mutation 8개(``member.register`` /
    ``member.set_emoji`` / ``member.suspend`` / ``member.reactivate`` /
    ``member.revoke`` / ``member.rotate_token`` / ``member.reset_password`` /
    ``member.regenerate_recovery_key``) 를 runtime IPC 로 wiring 한다
    (``member.update_scopes`` 동형, IPC-first + 서버 정지 시 CLI cold-path
    fallback). 발급 토큰/새 recovery key 는 사용자 표시용 result 에만 담고
    audit/log/envelope 에는 노출하지 않는다. ``reset_password`` /
    ``regenerate_recovery_key`` 는 auth-exempt 라 master-lookup 을 handler
    (서버 chokepoint)에서 수행하고 audit member_id 를 고정 sentinel 상수로
    기록한다.

    ``signal.connect`` (read-only): daemon-위임
    signal.connect 핸드셰이크의 4-게이트 LIVE 검증 경로. 통과 시 동일 연결을
    connection-upgrade(``result_kind="stream"``). audit 없음(``audit_action=None``;
    connect-audit 1회는 handler 가 직접 발화).

    ``broker.order_history`` (read-only): ``ante broker
    order-history`` 의 runtime IPC 경로. ``broker.positions`` 1:1 미러
    (``result_kind="collection"``, ``result_key="orders"``,
    ``required_services={"account"}``, ``account_id_policy="required"``).
    audit 없음(read-only).
    """
    registry.register(
        "system.halt",
        _handle_system_halt,
        is_mutating=True,
        result_kind="operation",
        required_services=frozenset({"account", "audit_logger"}),
        audit_action="system.halt",
    )
    registry.register(
        "system.clear_halt",
        _handle_system_clear_halt,
        is_mutating=True,
        result_kind="operation",
        required_services=frozenset({"account", "audit_logger"}),
        audit_action="system.clear_halt",
    )
    registry.register(
        "account.suspend",
        _handle_account_suspend,
        is_mutating=True,
        result_kind="operation",
        required_services=frozenset({"account", "audit_logger"}),
        account_id_policy="required",
        audit_action="account.suspend",
    )
    registry.register(
        "account.activate",
        _handle_account_activate,
        is_mutating=True,
        result_kind="operation",
        required_services=frozenset({"account", "audit_logger"}),
        account_id_policy="required",
        audit_action="account.activate",
    )
    registry.register(
        "bot.create",
        _handle_bot_create,
        is_mutating=True,
        result_kind="entity",
        result_key="bot_id",
        required_services=frozenset(
            {"strategy_registry", "bot_manager", "audit_logger"}
        ),
        account_id_policy="required",
        audit_action="bot.create",
    )
    registry.register(
        "bot.remove",
        _handle_bot_remove,
        is_mutating=True,
        result_kind="operation",
        required_services=frozenset({"bot_manager", "audit_logger"}),
        audit_action="bot.delete",
    )
    registry.register(
        "bot.signal_key.rotate",
        _handle_bot_signal_key_rotate,
        is_mutating=True,
        result_kind="operation",
        required_services=frozenset({"bot_manager", "audit_logger"}),
        audit_action="bot.signal_key.rotate",
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
    registry.register(
        "rule.update",
        _handle_rule_update,
        is_mutating=True,
        result_kind="raw",
        required_services=frozenset({"account", "dynamic_config", "audit_logger"}),
        account_id_policy="required",
        audit_action="account.rule.update",
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
        "member.register",
        _handle_member_register,
        is_mutating=True,
        result_kind="entity",
        required_services=frozenset({"member_service", "audit_logger"}),
        audit_action="member.register",
    )
    registry.register(
        "member.set_emoji",
        _handle_member_set_emoji,
        is_mutating=True,
        result_kind="entity",
        required_services=frozenset({"member_service", "audit_logger"}),
        audit_action="member.set_emoji",
    )
    registry.register(
        "member.suspend",
        _handle_member_suspend,
        is_mutating=True,
        result_kind="operation",
        required_services=frozenset({"member_service", "audit_logger"}),
        audit_action="member.suspend",
    )
    registry.register(
        "member.reactivate",
        _handle_member_reactivate,
        is_mutating=True,
        result_kind="operation",
        required_services=frozenset({"member_service", "audit_logger"}),
        audit_action="member.reactivate",
    )
    registry.register(
        "member.revoke",
        _handle_member_revoke,
        is_mutating=True,
        result_kind="operation",
        required_services=frozenset({"member_service", "audit_logger"}),
        audit_action="member.revoke",
    )
    registry.register(
        "member.rotate_token",
        _handle_member_rotate_token,
        is_mutating=True,
        result_kind="entity",
        required_services=frozenset({"member_service", "audit_logger"}),
        audit_action="member.rotate_token",
    )
    registry.register(
        "member.reset_password",
        _handle_member_reset_password,
        is_mutating=True,
        result_kind="operation",
        required_services=frozenset({"member_service", "audit_logger"}),
        audit_action="member.reset_password",
    )
    registry.register(
        "member.regenerate_recovery_key",
        _handle_member_regenerate_recovery_key,
        is_mutating=True,
        result_kind="entity",
        required_services=frozenset({"member_service", "audit_logger"}),
        audit_action="member.regenerate_recovery_key",
    )
    registry.register(
        "config.set",
        _handle_config_set,
        is_mutating=True,
        result_kind="operation",
        required_services=frozenset({"dynamic_config"}),
    )
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
        required_services=frozenset({"approval", "audit_logger"}),
        audit_action="approval.approve",
    )
    registry.register(
        "approval.reject",
        _handle_approval_reject,
        is_mutating=True,
        result_kind="entity",
        required_services=frozenset({"approval", "audit_logger"}),
        audit_action="approval.reject",
    )
    registry.register(
        "approval.cancel",
        _handle_approval_cancel,
        is_mutating=True,
        result_kind="entity",
        required_services=frozenset({"approval", "audit_logger"}),
        audit_action="approval.cancel",
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
    registry.register(
        "broker.reconcile",
        _handle_broker_reconcile,
        is_mutating=True,
        result_kind="operation",
        required_services=frozenset(
            {"account", "reconciler", "bot_manager", "audit_logger"}
        ),
        account_id_policy="required",
    )

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
        "broker.order_history",
        _handle_broker_order_history,
        is_mutating=False,
        result_kind="collection",
        result_key="orders",
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
    registry.register(
        "bot.list",
        _handle_bot_list,
        is_mutating=False,
        result_kind="collection",
        result_key="bots",
        required_services=frozenset({"bot_manager"}),
        account_id_policy="optional_filter",
    )
    registry.register(
        "bot.info",
        _handle_bot_info,
        is_mutating=False,
        result_kind="entity",
        result_key="bot",
        required_services=frozenset({"bot_manager"}),
    )
    registry.register(
        "bot.positions",
        _handle_bot_positions,
        is_mutating=False,
        result_kind="collection",
        result_key="positions",
        required_services=frozenset({"bot_manager"}),
    )
    registry.register(
        "bot.signal_key",
        _handle_bot_signal_key,
        is_mutating=False,
        result_kind="entity",
        result_key="signal_key",
        required_services=frozenset({"bot_manager"}),
    )
    registry.register(
        "signal.connect",
        _handle_signal_connect,
        is_mutating=False,
        result_kind="stream",
        required_services=frozenset({"bot_manager"}),
        account_id_policy="none",
    )
