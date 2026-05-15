"""ante rule — 거래 룰 조회/관리 커맨드."""

from __future__ import annotations

import asyncio
import logging
import sqlite3

import click

from ante.account.errors import AccountNotFoundError
from ante.cli.main import get_formatter
from ante.cli.middleware import require_auth, require_scope

logger = logging.getLogger(__name__)


@click.group()
def rule() -> None:
    """거래 룰 조회·관리."""


def _run(coro):  # noqa: ANN001, ANN202
    return asyncio.run(coro)


async def _create_rule_engine(account_id: str):  # noqa: ANN202
    """CLI용 RuleEngine 생성.

    호출자가 ``--account`` 옵션으로 검증된 ``account_id`` 를 반드시 전달
    해야 한다. fallback 정책상 첫 번째 계좌를 임의로 선택해선 안 된다
    (#1217). ``RuleEngine`` 생성자가 내부에서 ``require_account_id`` 로
    재검증한다.
    """
    from ante.cli.main import get_db_path
    from ante.core.database import Database
    from ante.eventbus.bus import EventBus
    from ante.rule.engine import RuleEngine

    db = Database(get_db_path())
    await db.connect()
    eventbus = EventBus()
    engine = RuleEngine(eventbus=eventbus, account_id=account_id)
    return engine, db


def _load_rules_from_config(engine) -> None:  # noqa: ANN001
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
def rule_list(ctx: click.Context, account_id: str, scope_filter: str | None) -> None:
    """룰 목록 조회."""
    fmt = get_formatter(ctx)

    async def _run_list() -> list[dict]:
        engine, db = await _create_rule_engine(account_id)
        try:
            # rule 수집과 독립적으로 account 존재를 검증한다.
            # 미존재 account는 "실재 account의 0 rules"와 구분되어야 하며
            # (#1559) AccountNotFoundError로 분기해 exit 1로 종료한다.
            #
            # AccountService.initialize()는 모든 non-deleted account row를
            # materialize하며 credentials를 복호화하므로, 조회 대상과 무관한
            # 다른 계좌의 credentials 복호화 실패가 rule list를 깨뜨릴 수
            # 있다(정상 사용 회귀). 따라서 credentials 복호화 없이 이미 열린
            # db 핸들로 lightweight 단건 존재 쿼리만 수행한다. 쿼리 의미는
            # AccountService.get(account_id 단건, status 필터 없음)과 일치하며
            # 미존재 시 동일한 AccountNotFoundError 메시지로 분기한다 — 동일
            # ACCOUNT_NOT_FOUND envelope/message 보존. db.close()는 아래
            # finally가 단독 소유한다(lifecycle 불변).
            #
            # ``accounts`` 테이블은 ``AccountService.initialize()`` 의
            # ``_CREATE_TABLE_SQL`` 에서만 생성된다. 이 경로는 raw
            # ``Database`` 핸들만 쓰고 ``AccountService`` 를 초기화하지
            # 않으므로, 부분 초기화/legacy DB(예: ``ante init`` 직후)에서는
            # 테이블 자체가 없어 ``sqlite3.OperationalError: no such table:
            # accounts`` 가 호출자까지 전파되어 ACCOUNT_NOT_FOUND 계약을
            # 우회할 수 있다(#1559). 정의상 accounts 테이블 부재는 해당
            # account 미존재와 동치이므로 동일한 AccountNotFoundError 로
            # 정규화한다. 단, malformed db 같은 다른 ``OperationalError``
            # 까지 삼키지 않도록 "no such table" 메시지일 때로만 좁힌다
            # (#1558 에서 검증된 패턴).
            try:
                account_row = await db.fetch_one(
                    "SELECT 1 FROM accounts WHERE account_id = ?",
                    (account_id,),
                )
            except sqlite3.OperationalError as e:
                if "no such table" in str(e).lower():
                    raise AccountNotFoundError(
                        f"계좌 '{account_id}'를 찾을 수 없습니다."
                    ) from e
                raise
            if account_row is None:
                raise AccountNotFoundError(f"계좌 '{account_id}'를 찾을 수 없습니다.")

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

    try:
        result = _run(_run_list())
    except AccountNotFoundError as e:
        fmt.error(str(e), code="ACCOUNT_NOT_FOUND")
        raise SystemExit(1) from e

    if not result:
        # 실재 account의 0 rules는 정상 계약: exit 0 + 빈 목록 응답을
        # 그대로 유지한다. 미존재 account만 위에서 exit 1로 분기된다(#1559).
        fmt.output({"message": "등록된 룰이 없습니다.", "rules": []})
        return

    if fmt.is_json:
        fmt.output({"rules": result})
    else:
        fmt.table(result, ["rule_id", "name", "scope", "enabled", "priority"])


@rule.command("info")
@click.argument("rule_id")
@click.option("--account", "account_id", required=True, help="계좌 ID")
@click.pass_context
@require_auth
@require_scope("rule:read")
def rule_info(ctx: click.Context, rule_id: str, account_id: str) -> None:
    """룰 상세 정보 조회."""
    fmt = get_formatter(ctx)

    async def _run_info() -> dict | None:
        engine, db = await _create_rule_engine(account_id)
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
