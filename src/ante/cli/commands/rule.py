"""ante rule — 거래 룰 조회/관리 커맨드."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Coroutine
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

import click

from ante.account.errors import AccountNotFoundError
from ante.cli._validators import reject_invalid_account_id
from ante.cli.db_context import open_cli_db
from ante.cli.formatter import CommandResult, format_option, table_lines
from ante.cli.main import get_formatter
from ante.cli.middleware import get_member_id, require_auth, require_scope
from ante.contracts.cli_errors import RuleNotFoundError, RuleUpdateError
from ante.contracts.error_registry import EXECUTION_ERROR_SPEC
from ante.contracts.helpers import error_spec_for_exception
from ante.contracts.ipc_client_errors import (
    IPCClientTimeoutError,
    IPCRemoteError,
    IPCServerNotRunningError,
)
from ante.contracts.request_errors import RequestValidationError
from ante.core.database import OperationalError, is_missing_table

if TYPE_CHECKING:
    from ante.core.database import Database
    from ante.rule.engine import RuleEngine

logger = logging.getLogger(__name__)


@click.group()
def rule() -> None:
    """거래 룰 조회·관리."""


def _run(coro: Coroutine[Any, Any, Any]) -> Any:
    return asyncio.run(coro)


@asynccontextmanager
async def _create_rule_engine(
    account_id: str, *, ctx: click.Context | None = None
) -> AsyncIterator[tuple[RuleEngine, Database]]:
    """CLI용 RuleEngine async context manager."""
    from ante.account.scoping import require_account_id
    from ante.eventbus.bus import EventBus
    from ante.rule.engine import RuleEngine

    validated_account_id = require_account_id(account_id, context="cli.rule")

    resolved_ctx = ctx if ctx is not None else click.get_current_context(silent=True)
    if resolved_ctx is None:
        raise ValueError(
            "_create_rule_engine requires a Click context "
            "(explicit ctx or active click.get_current_context)"
        )

    async with open_cli_db(resolved_ctx) as db:
        try:
            account_row = await db.fetch_one(
                "SELECT 1 FROM accounts WHERE account_id = ?",
                (validated_account_id,),
            )
        except OperationalError as e:
            if is_missing_table(e):
                raise AccountNotFoundError(
                    f"계좌 '{validated_account_id}'를 찾을 수 없습니다."
                ) from e
            raise
        if account_row is None:
            raise AccountNotFoundError(
                f"계좌 '{validated_account_id}'를 찾을 수 없습니다."
            )
        eventbus = EventBus()
        engine = RuleEngine(eventbus=eventbus, account_id=validated_account_id)
        yield engine, db


def _load_rules_from_config(engine: RuleEngine) -> None:
    """설정 파일에서 룰을 로딩."""
    from ante.cli.main import get_config_dir
    from ante.config.config import Config

    config = Config.load(config_dir=get_config_dir())
    global_rules = config.get("rules.global")
    if isinstance(global_rules, list):
        engine.load_rules_from_config(global_rules)

    strategy_rules = config.get("rules.strategy")
    if isinstance(strategy_rules, dict):
        for strategy_id, rules in strategy_rules.items():
            engine.load_strategy_rules_from_config(strategy_id, rules)


def _collect_rules(engine: RuleEngine) -> list[dict[str, Any]]:
    """엔진에서 전체 룰 목록 수집."""
    rules = []
    for r in engine._global_rules:
        rules.append(
            {
                "rule_id": r.rule_id,
                "name": r.name,
                "scope": "global",
                "enabled": r.enabled,
                "priority": r.priority,
                "description": r.description,
            }
        )
    for strategy_id, strategy_rules in engine._strategy_rules.items():
        for r in strategy_rules:
            rules.append(
                {
                    "rule_id": r.rule_id,
                    "name": r.name,
                    "scope": f"strategy:{strategy_id}",
                    "enabled": r.enabled,
                    "priority": r.priority,
                    "description": r.description,
                }
            )
    return rules


@rule.command("list")
@click.option("--account", "account_id", required=True, help="계좌 ID")
@click.option(
    "--scope",
    "scope_filter",
    type=click.Choice(["global", "strategy"]),
    default=None,
    help="룰 범위 필터",
)
@click.pass_context
@require_auth
@require_scope("rule:read")
def rule_list(
    ctx: click.Context, account_id: str, scope_filter: str | None
) -> CommandResult:
    """룰 목록 조회."""
    fmt = get_formatter(ctx)

    reject_invalid_account_id(account_id, fmt, context="cli.rule")

    async def _run_list() -> list[dict[str, Any]]:
        async with _create_rule_engine(account_id, ctx=ctx) as (engine, _):
            try:
                _load_rules_from_config(engine)
            except Exception as e:
                logger.warning("룰 설정 로드 실패: %s", e)
            rules = _collect_rules(engine)
            if scope_filter:
                rules = [
                    r
                    for r in rules
                    if (scope_filter == "global" and r["scope"] == "global")
                    or (
                        scope_filter == "strategy"
                        and r["scope"].startswith("strategy:")
                    )
                ]
            return rules

    result = _run(_run_list())

    if not result:
        message = "등록된 룰이 없습니다."
        empty: dict[str, Any] = {"message": message, "rules": []}
        return CommandResult(data=empty, text=(message,))

    columns = ["rule_id", "name", "scope", "enabled", "priority"]
    return CommandResult(
        data={"rules": result}, text=lambda: tuple(table_lines(result, columns))
    )


@rule.command("info")
@click.argument("rule_id")
@click.option("--account", "account_id", required=True, help="계좌 ID")
@click.pass_context
@require_auth
@require_scope("rule:read")
def rule_info(ctx: click.Context, rule_id: str, account_id: str) -> CommandResult:
    """룰 상세 정보 조회."""
    fmt = get_formatter(ctx)

    reject_invalid_account_id(account_id, fmt, context="cli.rule")

    async def _run_info() -> dict[str, Any] | None:
        async with _create_rule_engine(account_id, ctx=ctx) as (engine, _):
            try:
                _load_rules_from_config(engine)
            except Exception as e:
                logger.warning("룰 설정 로드 실패: %s", e)
            rules = _collect_rules(engine)
            return next((r for r in rules if r["rule_id"] == rule_id), None)

    result = _run(_run_info())

    if not result:
        raise RuleNotFoundError(f"룰을 찾을 수 없습니다: {rule_id}")

    found = result
    return CommandResult(
        data=found,
        text=lambda: tuple(f"  {key:15s}: {value}" for key, value in found.items()),
    )


def _parse_rule_params(
    param_items: tuple[str, ...], params_json: str | None
) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if params_json:
        try:
            decoded = json.loads(params_json)
        except json.JSONDecodeError as e:
            raise click.BadParameter("--params-json 값은 JSON object여야 합니다") from e
        if not isinstance(decoded, dict):
            raise click.BadParameter("--params-json 값은 JSON object여야 합니다")
        params.update(decoded)
    for item in param_items:
        key, value = _parse_key_value(item)
        params[key] = value
    return params


def _parse_key_value(value: str) -> tuple[str, object]:
    if "=" not in value:
        raise click.BadParameter(f"잘못된 파라미터 형식: {value!r} (key=value)")
    key, raw = value.split("=", 1)
    key = key.strip()
    if not key:
        raise click.BadParameter("파라미터 key는 비어 있을 수 없습니다")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = raw
    return key, parsed


@rule.command("update")
@click.argument("rule_type")
@click.option("--account", "account_id", required=True, help="계좌 ID")
@click.option(
    "--enabled/--disabled",
    default=None,
    help="룰 활성화 여부 (생략하면 저장된 값을 유지)",
)
@click.option(
    "--param",
    "params",
    multiple=True,
    help="룰 파라미터 (key=value, 복수 지정 가능)",
)
@click.option("--params-json", default=None, help="룰 파라미터 JSON object")
@format_option
@click.pass_context
@require_auth
@require_scope("rule:admin")
def rule_update(
    ctx: click.Context,
    rule_type: str,
    account_id: str,
    enabled: bool | None,
    params: tuple[str, ...],
    params_json: str | None,
) -> CommandResult:
    """계좌 룰 설정 수정."""
    fmt = get_formatter(ctx)
    actor = get_member_id(ctx)
    account_id = reject_invalid_account_id(account_id, fmt, context="cli.rule.update")

    try:
        param_dict = _parse_rule_params(params, params_json)
    except click.BadParameter as e:
        raise RequestValidationError(str(e)) from e

    async def _run_update() -> dict[str, Any]:
        from ante.cli.cold_path import is_active_runtime
        from ante.cli.commands.ipc_helpers import ipc_send

        if is_active_runtime():
            payload: dict[str, Any] = {
                "account_id": account_id,
                "rule_type": rule_type,
                "params": param_dict,
            }
            if enabled is not None:
                payload["enabled"] = enabled
            return await ipc_send("rule.update", payload, actor=actor)

        from ante.account.service import AccountService
        from ante.audit import AuditLogger
        from ante.cli.main import get_config_dir
        from ante.config import Config, DynamicConfigService
        from ante.eventbus.bus import EventBus
        from ante.rule.config_update import update_account_rule_config

        async with open_cli_db(ctx) as db:
            eventbus = EventBus()
            account_service = AccountService(db=db, eventbus=eventbus)
            await account_service.initialize()
            dynamic_config = DynamicConfigService(db=db, eventbus=eventbus)
            await dynamic_config.initialize()
            audit_logger = AuditLogger(db=db)
            await audit_logger.initialize()
            config = Config.load(config_dir=get_config_dir(ctx))
            return await update_account_rule_config(
                account_service=account_service,
                dynamic_config=dynamic_config,
                account_id=account_id,
                rule_type=rule_type,
                enabled=enabled,
                params=param_dict,
                changed_by=actor,
                config=config,
                audit_logger=audit_logger,
            )

    try:
        result = _run(_run_update())
    except (
        click.ClickException,
        IPCServerNotRunningError,
        IPCClientTimeoutError,
        IPCRemoteError,
    ):
        raise
    except Exception as e:
        if error_spec_for_exception(e).code != EXECUTION_ERROR_SPEC.code:
            raise
        raise RuleUpdateError(str(e)) from e

    def _lines() -> tuple[str, ...]:
        rule_item = result.get("rule", {})
        lines = (
            f"룰 수정 완료: {result.get('account_id')} "
            f"{rule_item.get('type', rule_type)} enabled={rule_item.get('enabled')}",
        )
        dropped = result.get("dropped_items") or []
        if not dropped:
            return lines
        positions = ", ".join(
            f"stored_index={d.get('stored_index')} rule_type={d.get('rule_type')!r}"
            for d in dropped
        )
        return (
            *lines,
            f"저장값에서 쓸 수 없는 항목 {len(dropped)}건을 버림: {positions} "
            f"(원문은 ante config history accounts.{result.get('account_id')}.rules의 "
            "이전 값, seed에서 읽었으면 설정 파일에 남음)",
        )

    return CommandResult(data=result, text=_lines)
