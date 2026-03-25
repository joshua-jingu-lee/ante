"""ante rule — 거래 룰 조회/관리 커맨드."""

from __future__ import annotations

import asyncio
import logging

import click

from ante.cli.main import get_formatter
from ante.cli.middleware import require_auth, require_scope

logger = logging.getLogger(__name__)


@click.group()
def rule() -> None:
    """거래 룰 조회·관리."""


def _run(coro):  # noqa: ANN001, ANN202
    return asyncio.run(coro)


async def _create_rule_engine():  # noqa: ANN202
    from ante.core.database import Database
    from ante.eventbus.bus import EventBus
    from ante.rule.engine import RuleEngine

    db = Database("db/ante.db")
    await db.connect()
    eventbus = EventBus()
    engine = RuleEngine(eventbus=eventbus)
    return engine, db


def _load_rules_from_config(engine) -> None:  # noqa: ANN001
    """설정 파일에서 룰을 로딩."""
    from ante.config.config import Config

    config = Config.load()
    global_rules = config.get("rules.global")
    if isinstance(global_rules, list):
        engine.load_rules_from_config(global_rules)

    strategy_rules = config.get("rules.strategy")
    if isinstance(strategy_rules, dict):
        for strategy_id, rules in strategy_rules.items():
            engine.load_strategy_rules_from_config(strategy_id, rules)


def _collect_rules(engine) -> list[dict]:  # noqa: ANN001
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
def rule_list(ctx: click.Context, scope_filter: str | None) -> None:
    """룰 목록 조회."""
    fmt = get_formatter(ctx)

    async def _run_list() -> list[dict]:
        engine, db = await _create_rule_engine()
        try:
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
        finally:
            await db.close()

    result = _run(_run_list())

    if not result:
        fmt.output({"message": "등록된 룰이 없습니다.", "rules": []})
        return

    if fmt.is_json:
        fmt.output({"rules": result})
    else:
        fmt.table(result, ["rule_id", "name", "scope", "enabled", "priority"])


@rule.command("info")
@click.argument("rule_id")
@click.pass_context
@require_auth
@require_scope("rule:read")
def rule_info(ctx: click.Context, rule_id: str) -> None:
    """룰 상세 정보 조회."""
    fmt = get_formatter(ctx)

    async def _run_info() -> dict | None:
        engine, db = await _create_rule_engine()
        try:
            try:
                _load_rules_from_config(engine)
            except Exception as e:
                logger.warning("룰 설정 로드 실패: %s", e)
            rules = _collect_rules(engine)
            return next((r for r in rules if r["rule_id"] == rule_id), None)
        finally:
            await db.close()

    result = _run(_run_info())

    if not result:
        fmt.error(f"룰을 찾을 수 없습니다: {rule_id}")
        raise SystemExit(1)

    if fmt.is_json:
        fmt.output(result)
    else:
        for key, value in result.items():
            click.echo(f"  {key:15s}: {value}")
