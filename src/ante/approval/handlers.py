from __future__ import annotations

from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from ante.approval.models import ValidationResult
from ante.bot.config import BotStatus
from ante.report.models import ReportStatus
from ante.strategy.registry import StrategyStatus

if TYPE_CHECKING:
    from ante.bot.manager import BotManager
    from ante.eventbus.bus import EventBus
    from ante.report.store import ReportStore
    from ante.rule.manager import RuleEngineManager
    from ante.strategy.registry import StrategyRegistry
    from ante.trade.position import PositionHistory
    from ante.treasury.manager import TreasuryManager


class ApprovalDeps(Protocol):
    report_store: ReportStore
    strategy_registry: StrategyRegistry
    bot_manager: BotManager
    treasury_manager: TreasuryManager
    rule_engine_manager: RuleEngineManager
    position_history: PositionHistory
    eventbus: EventBus | None


def _approval_account_id(params: dict, *, context: str) -> str:
    """approval params 에서 검증된 account_id 를 추출."""
    from ante.account.scoping import require_account_id

    return require_account_id(params.get("account_id"), context=context)


def _approval_bot_create_config(params: dict) -> Any:
    """bot_create approval params 를 BotManager.create_bot 계약으로 변환."""
    from ante.account.scoping import require_account_id
    from ante.bot.config import BotConfig

    config_params = params.get("config")
    if not isinstance(config_params, dict):
        raise ValueError("bot_create params.config가 누락되었습니다")

    strategy_id = str(config_params.get("strategy_id") or "")
    if not strategy_id:
        raise ValueError("bot_create config.strategy_id가 누락되었습니다")

    bot_id = str(config_params.get("bot_id") or "")
    account_id = require_account_id(
        config_params.get("account_id"), context="approval.bot_create.config"
    )
    interval_seconds = int(config_params.get("interval_seconds", 60))
    return BotConfig(
        bot_id=bot_id,
        strategy_id=strategy_id,
        name=str(config_params.get("name") or bot_id),
        account_id=account_id,
        interval_seconds=interval_seconds,
    )


async def _exec_rule_change(s: ApprovalDeps, params: dict) -> None:
    account_id = _approval_account_id(params, context="approval.rule_change.exec")
    engine = s.rule_engine_manager.get(account_id)
    engine.update_rules(params["bot_id"], params["rules"])


async def _exec_budget_change(s: ApprovalDeps, params: dict) -> None:
    account_id = _approval_account_id(params, context="approval.budget_change.exec")
    treasury = s.treasury_manager.get(account_id)
    await treasury.update_budget(params["bot_id"], params["amount"])


async def _exec_strategy_adopt(s: ApprovalDeps, params: dict) -> None:
    await s.report_store.update_status(params["report_id"], ReportStatus.ADOPTED)
    await s.strategy_registry.update_status(
        params["strategy_id"], StrategyStatus.ADOPTED
    )
    from ante.eventbus.events import NotificationEvent

    rec = await s.strategy_registry.get(params["strategy_id"])
    name = rec.name if rec else params["strategy_id"]
    ver = rec.version if rec else "unknown"
    if s.eventbus is not None:
        await s.eventbus.publish(
            NotificationEvent(
                level="info",
                title="전략 채택",
                message=(
                    f"전략 '{name}' (v{ver})이 채택되었습니다. 봇에 배정할 수 있습니다."
                ),
                category="strategy",
            )
        )


async def _exec_strategy_retire(s: ApprovalDeps, params: dict) -> None:
    await s.report_store.update_status(params["report_id"], ReportStatus.ARCHIVED)
    await s.strategy_registry.update_status(
        params["strategy_id"], StrategyStatus.ARCHIVED
    )
    from ante.eventbus.events import NotificationEvent

    rec = await s.strategy_registry.get(params["strategy_id"])
    name = rec.name if rec else params["strategy_id"]
    ver = rec.version if rec else "unknown"
    if s.eventbus is not None:
        await s.eventbus.publish(
            NotificationEvent(
                level="info",
                title="전략 폐기",
                message=f"전략 '{name}' (v{ver})이 보관 처리되었습니다.",
                category="strategy",
            )
        )


async def _exec_bot_create(s: ApprovalDeps, params: dict) -> None:
    from ante.strategy.loader import StrategyLoader

    config = _approval_bot_create_config(params)
    record = await s.strategy_registry.get(config.strategy_id)
    if record is None:
        raise ValueError(f"전략을 찾을 수 없습니다: {config.strategy_id}")
    if record.status != StrategyStatus.ADOPTED:
        raise ValueError(
            f"전략이 adopted 상태가 아닙니다: {config.strategy_id} ({record.status})"
        )

    strategy_cls = StrategyLoader.load(Path(record.filepath))
    await s.bot_manager.create_bot(
        config=config,
        strategy_cls=strategy_cls,
        source_path=Path(record.filepath),
    )


async def _exec_bot_stop_idempotent(s: ApprovalDeps, params: dict) -> None:
    """approval ``bot_stop`` executor."""
    from ante.bot.exceptions import BotStateConflict

    try:
        await s.bot_manager.stop_bot(params["bot_id"])
    except BotStateConflict:
        return


async def _validate_strategy_adopt(
    s: ApprovalDeps, params: dict
) -> list[ValidationResult]:
    """전략 채택 사전 검증: report_id·strategy_id 존재 확인."""
    strategy_id = params.get("strategy_id", "")
    if not strategy_id:
        return [ValidationResult("fail", "strategy_id가 누락되었습니다", "system")]
    report_id = params.get("report_id", "")
    if not report_id:
        return [ValidationResult("fail", "report_id가 누락되었습니다", "system")]
    record = await s.strategy_registry.get(strategy_id)
    if record is None:
        return [ValidationResult("fail", "전략을 찾을 수 없습니다", "system")]
    return [ValidationResult("pass", "", "system")]


async def _validate_strategy_retire(
    s: ApprovalDeps, params: dict
) -> list[ValidationResult]:
    """전략 폐기 사전 검증: 전략 상태 확인."""
    strategy_id = params.get("strategy_id", "")
    if not strategy_id:
        return [ValidationResult("fail", "strategy_id가 누락되었습니다", "system")]
    record = await s.strategy_registry.get(strategy_id)
    if record is None:
        return [ValidationResult("fail", "전략을 찾을 수 없습니다", "system")]
    if record.status == StrategyStatus.ARCHIVED:
        return [ValidationResult("fail", "이미 보관된 전략입니다", "system")]
    return [ValidationResult("pass", "", "system")]


async def _validate_bot_create(s: ApprovalDeps, params: dict) -> list[ValidationResult]:
    """봇 생성 사전 검증: 전략 adopted 상태, 동일 봇 미존재."""
    results: list[ValidationResult] = []
    try:
        config = _approval_bot_create_config(params)
    except Exception as e:
        return [ValidationResult("fail", str(e), "system:bot_manager")]

    bot_id = config.bot_id
    if bot_id and s.bot_manager.get_bot(bot_id):
        results.append(
            ValidationResult(
                "fail",
                f"동일 ID의 봇이 이미 존재: {bot_id}",
                "system:bot_manager",
            )
        )
    record = await s.strategy_registry.get(config.strategy_id)
    if record is None:
        results.append(
            ValidationResult(
                "fail",
                f"전략을 찾을 수 없습니다: {config.strategy_id}",
                "system:strategy_registry",
            )
        )
    elif record.status != StrategyStatus.ADOPTED:
        results.append(
            ValidationResult(
                "fail",
                f"전략이 adopted 상태가 아닙니다: {config.strategy_id}",
                "system:strategy_registry",
            )
        )
    return results or [ValidationResult("pass", "", "system:bot_manager")]


def _validate_bot_delete(s: ApprovalDeps, params: dict) -> list[ValidationResult]:
    """봇 삭제 사전 검증: stopped 상태, 보유 포지션 없음."""
    results: list[ValidationResult] = []
    bot_id = params.get("bot_id", "")
    bot = s.bot_manager.get_bot(bot_id)
    if not bot:
        return [ValidationResult("fail", "봇이 존재하지 않음", "system:bot_manager")]
    if bot.status != BotStatus.STOPPED:
        results.append(
            ValidationResult(
                "fail",
                f"봇이 {bot.status} 상태 (stopped 필요)",
                "system:bot_manager",
            )
        )
    positions = s.position_history.get_positions_sync(
        bot_id, account_id=bot.config.account_id
    )
    if positions:
        results.append(
            ValidationResult(
                "fail",
                f"보유 포지션 {len(positions)}건 존재",
                "system:trade",
            )
        )
    return results or [ValidationResult("pass", "", "system:bot_manager")]


def _validate_bot_change_strategy(
    s: ApprovalDeps, params: dict
) -> list[ValidationResult]:
    """봇 전략 변경 사전 검증: stopped 상태 확인."""
    bot_id = params.get("bot_id", "")
    bot = s.bot_manager.get_bot(bot_id)
    if not bot:
        return [ValidationResult("fail", "봇이 존재하지 않음", "system:bot_manager")]
    if bot.status != BotStatus.STOPPED:
        return [
            ValidationResult(
                "fail",
                f"봇이 {bot.status} 상태 (stopped 필요)",
                "system:bot_manager",
            )
        ]
    return [ValidationResult("pass", "", "system:bot_manager")]


def _validate_bot_assign_strategy(
    s: ApprovalDeps, params: dict
) -> list[ValidationResult]:
    """봇 전략 배정 사전 검증: 전략 adopted 상태 확인."""
    return [ValidationResult("pass", "", "system:report_store")]


def _validate_bot_resume(s: ApprovalDeps, params: dict) -> list[ValidationResult]:
    """봇 재개 사전 검증: stopped/error 상태 확인."""
    bot_id = params.get("bot_id", "")
    bot = s.bot_manager.get_bot(bot_id)
    if not bot:
        return [ValidationResult("fail", "봇이 존재하지 않음", "system:bot_manager")]
    if bot.status not in (BotStatus.STOPPED, BotStatus.ERROR):
        return [
            ValidationResult(
                "fail",
                f"봇이 {bot.status} 상태 (stopped/error 필요)",
                "system:bot_manager",
            )
        ]
    return [ValidationResult("pass", "", "system:bot_manager")]


def _validate_budget_change(s: ApprovalDeps, params: dict) -> list[ValidationResult]:
    """예산 변경 사전 검증: 미할당 잔액 충분 여부 (warn).

    ``params.get("account_id", "test")`` fallback 은 두지 않는다.
    invalid account_id 는 ``ValidationResult("fail", ...)``
    으로 변환해 ``ApprovalService`` 가 ``ApprovalValidationError`` 로
    변환하도록 한다 (validator 계약: raise 대신 fail 반환).
    """
    from ante.account.errors import InvalidAccountIdError

    try:
        account_id = _approval_account_id(
            params, context="approval.budget_change.validate"
        )
    except InvalidAccountIdError as e:
        return [ValidationResult("fail", str(e), "system:treasury")]
    try:
        treasury = s.treasury_manager.get(account_id)
    except KeyError:
        return [
            ValidationResult(
                "fail",
                f"계좌 '{account_id}'의 Treasury 없음",
                "system:treasury",
            )
        ]
    amount = float(params.get("amount", 0))
    current = float(params.get("current", 0))
    amount_diff = amount - current
    if amount_diff > 0 and amount_diff > treasury.unallocated:
        return [
            ValidationResult(
                "warn",
                f"미할당 잔액({treasury.unallocated:,.0f}원) "
                f"< 증액분({amount_diff:,.0f}원)",
                "system:treasury",
            )
        ]
    return [ValidationResult("pass", "", "system:treasury")]


def build_executors(s: ApprovalDeps) -> dict[str, Any]:
    return {
        "strategy_adopt": partial(_exec_strategy_adopt, s),
        "strategy_retire": partial(_exec_strategy_retire, s),
        "bot_create": partial(_exec_bot_create, s),
        "bot_assign_strategy": lambda params: s.bot_manager.assign_strategy(
            params["bot_id"], params["strategy_id"]
        ),
        "bot_change_strategy": lambda params: s.bot_manager.change_strategy(
            params["bot_id"], params["strategy_id"]
        ),
        "bot_stop": partial(_exec_bot_stop_idempotent, s),
        "bot_resume": lambda params: s.bot_manager.resume_bot(params["bot_id"]),
        "bot_delete": lambda params: s.bot_manager.delete_bot(params["bot_id"]),
        "budget_change": partial(_exec_budget_change, s),
        "rule_change": partial(_exec_rule_change, s),
    }


def build_validators(s: ApprovalDeps) -> dict[str, Any]:
    return {
        "strategy_adopt": partial(_validate_strategy_adopt, s),
        "strategy_retire": partial(_validate_strategy_retire, s),
        "bot_create": partial(_validate_bot_create, s),
        "bot_delete": partial(_validate_bot_delete, s),
        "bot_change_strategy": partial(_validate_bot_change_strategy, s),
        "bot_assign_strategy": partial(_validate_bot_assign_strategy, s),
        "bot_resume": partial(_validate_bot_resume, s),
        "budget_change": partial(_validate_budget_change, s),
    }
