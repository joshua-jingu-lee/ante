"""ante rule — 거래 룰 조회/관리 커맨드."""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3

import click

from ante.account.errors import AccountNotFoundError
from ante.cli._validators import reject_invalid_account_id
from ante.cli.formatter import format_option
from ante.cli.main import get_formatter
from ante.cli.middleware import get_member_id, require_auth, require_scope

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

    invalid ``account_id`` 검증은 ``db.connect()`` **이전**에 수행한다
    (#1635 Split B Layer 2 — ``treasury.py:37`` ``_create_treasury`` 패턴
    1:1 미러). 기존 구조는 ``db.connect()`` 후 ``RuleEngine(account_id=...)``
    내부 ``require_account_id`` 가 raise하여 ``(engine, db)`` 가 미반환 →
    호출자 ``finally: db.close()`` 미도달 → aiosqlite connection 누수
    (#1623 Codex finding, lifecycle). resource acquisition 이전에 검증·raise
    하면 획득 자원이 0이라 정리 대상도 0 — 누수 구조 자체를 제거한다.
    ``RuleEngine.__init__`` 내부 ``require_account_id``(``engine.py:270``)는
    defense-in-depth로 그대로 유지한다(무변경).

    valid-format이지만 DB에 없는 ``account_id`` (예: ``acc-9999``)는
    ``RuleEngine`` 생성 **이전**에 lightweight ``SELECT 1`` 로 존재를
    검증해 ``AccountNotFoundError`` 로 분기한다(#1726, ``rule list`` 의
    기존 inline 블록을 SSOT consolidation으로 helper로 이동). 이 검증을
    helper에 두면 ``rule list`` 외에도 ``info`` 등 다른 rule 명령에
    동일하게 적용되며, rule lookup 보다 account existence가 먼저 보고된다.
    실패 시 ``except BaseException`` 블록으로 ``db.close()`` 를 보장한다
    (``_create_treasury`` (#1722) 동형 cleanup).
    """
    from ante.account.scoping import require_account_id
    from ante.cli.main import get_db_path
    from ante.core.database import Database
    from ante.eventbus.bus import EventBus
    from ante.rule.engine import RuleEngine

    validated_account_id = require_account_id(account_id, context="cli.rule")

    db = Database(get_db_path())
    try:
        await db.connect()
        # account existence pre-check. ``rule_list`` 의 기존 inline 블록을
        # 그대로 옮긴 형태이며, ``_create_treasury`` 동형 (#1725).
        #
        # ``AccountService.initialize()`` 는 모든 non-deleted account row를
        # materialize하며 credentials를 복호화하므로, 조회 대상과 무관한
        # 다른 계좌의 credentials 복호화 실패가 rule 명령을 깨뜨릴 수 있다
        # (정상 사용 회귀). 따라서 credentials 복호화 없이 이미 열린 db
        # 핸들로 lightweight 단건 존재 쿼리만 수행한다. 쿼리 의미는
        # ``AccountService.get`` (account_id 단건, status 필터 없음)과
        # 일치하며 미존재 시 동일한 ``AccountNotFoundError`` 메시지로
        # 분기한다 — 동일 ACCOUNT_NOT_FOUND envelope/message 보존.
        #
        # ``accounts`` 테이블은 ``AccountService.initialize()`` 의
        # ``_CREATE_TABLE_SQL`` 에서만 생성된다. 이 경로는 raw ``Database``
        # 핸들만 쓰고 ``AccountService`` 를 초기화하지 않으므로, 부분
        # 초기화/legacy DB(예: ``ante init`` 직후)에서는 테이블 자체가 없어
        # ``sqlite3.OperationalError: no such table: accounts`` 가
        # 호출자까지 전파되어 ACCOUNT_NOT_FOUND 계약을 우회할 수 있다
        # (#1559). 정의상 accounts 테이블 부재는 해당 account 미존재와
        # 동치이므로 동일한 ``AccountNotFoundError`` 로 정규화한다. 단,
        # malformed db 같은 다른 ``OperationalError`` 까지 삼키지 않도록
        # "no such table" 메시지일 때로만 좁힌다 (#1558 검증 패턴).
        try:
            account_row = await db.fetch_one(
                "SELECT 1 FROM accounts WHERE account_id = ?",
                (validated_account_id,),
            )
        except sqlite3.OperationalError as e:
            if "no such table" in str(e).lower():
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
    except BaseException:
        try:
            await db.close()
        except Exception:
            logger.debug(
                "db.close() after rule engine init failure raised — ignored",
                exc_info=True,
            )
        raise
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

    # invalid account_id(`default`/패턴 위반/`""`)를 resource acquisition
    # 이전에 거부한다(#1635 Split B Layer 1). invalid-format은 여기서
    # `VALIDATION_ERROR`(#1633 SSOT) + exit 1로 종료된다. valid-but-absent
    # account_id는 `require_account_id`가 거부하지 않으므로 기존 경로로
    # 흘러 아래 `_run_list`의 account 존재 SELECT → `AccountNotFoundError`
    # → `ACCOUNT_NOT_FOUND` 분기를 보존한다(invalid-format ↔ valid-absent
    # 분리 불변, VALIDATION_ERROR 오분류 금지).
    reject_invalid_account_id(account_id, fmt, context="cli.rule")

    async def _run_list() -> list[dict]:
        # account existence는 ``_create_rule_engine`` 이 ``SELECT 1`` 로 선
        # 검증한다(#1726 SSOT consolidation — 기존 여기 inline 블록을 helper
        # 로 이동). 미존재 account는 ``AccountNotFoundError`` 로 raise되며
        # 아래 호출 표면의 ``except AccountNotFoundError`` 분기가 받는다.
        engine, db = await _create_rule_engine(account_id)
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

    # invalid account_id(`default`/패턴 위반/`""`)를 resource acquisition
    # 이전에 거부한다(#1635 Split B Layer 1). invalid-format은 여기서
    # `VALIDATION_ERROR`(#1633 SSOT) + exit 1로 종료한다. valid-but-absent
    # account_id(예: ``acc-9999``)는 ``_create_rule_engine`` 이 ``SELECT 1``
    # 로 검증해 ``AccountNotFoundError`` 를 raise하며, 아래 호출 표면의
    # ``except AccountNotFoundError`` 분기가 ``ACCOUNT_NOT_FOUND`` 로
    # 매핑한다(#1726 — prior #1635 명시 punt "ACCOUNT_NOT_FOUND 강제
    # 금지"의 후속, ``rule_list`` line 196-198 패턴 1:1 동형).
    reject_invalid_account_id(account_id, fmt, context="cli.rule")

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

    try:
        result = _run(_run_info())
    except AccountNotFoundError as e:
        fmt.error(str(e), code="ACCOUNT_NOT_FOUND")
        raise SystemExit(1) from e

    if not result:
        fmt.error(f"룰을 찾을 수 없습니다: {rule_id}", code="RULE_NOT_FOUND")
        raise SystemExit(1)

    if fmt.is_json:
        fmt.output(result)
    else:
        for key, value in result.items():
            click.echo(f"  {key:15s}: {value}")


def _parse_rule_params(param_items: tuple[str, ...], params_json: str | None) -> dict:
    params: dict = {}
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
    default=True,
    show_default=True,
    help="룰 활성화 여부",
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
    enabled: bool,
    params: tuple[str, ...],
    params_json: str | None,
) -> None:
    """계좌 룰 설정 수정."""
    fmt = get_formatter(ctx)
    actor = get_member_id(ctx)
    account_id = reject_invalid_account_id(account_id, fmt, context="cli.rule.update")

    try:
        param_dict = _parse_rule_params(params, params_json)
    except click.BadParameter as e:
        fmt.error(str(e), code="VALIDATION_ERROR")
        raise SystemExit(1) from e

    async def _run_update() -> dict:
        from ante.cli.cold_path import is_active_runtime
        from ante.cli.commands.ipc_helpers import ipc_send

        if is_active_runtime():
            return await ipc_send(
                "rule.update",
                {
                    "account_id": account_id,
                    "rule_type": rule_type,
                    "enabled": enabled,
                    "params": param_dict,
                },
                actor=actor,
            )

        from ante.account.service import AccountService
        from ante.audit import AuditLogger
        from ante.cli.main import get_config_dir, get_db_path
        from ante.config import Config, DynamicConfigService
        from ante.core.database import Database
        from ante.eventbus.bus import EventBus
        from ante.rule.config_update import update_account_rule_config

        db = Database(get_db_path(ctx))
        await db.connect()
        try:
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
        finally:
            await db.close()

    try:
        result = _run(_run_update())
    except click.ClickException as e:
        code = getattr(e, "ipc_error_code", "") or "IPC_ERROR"
        message = getattr(e, "ipc_error_message", None) or e.message
        fmt.error(message, code=code)
        raise SystemExit(1) from e
    except Exception as e:
        fmt.error(str(e), code=getattr(e, "code", "RULE_UPDATE_ERROR"))
        raise SystemExit(1) from e

    if fmt.is_json:
        fmt.output(result)
    else:
        rule_item = result.get("rule", {})
        click.echo(
            f"룰 수정 완료: {result.get('account_id')} "
            f"{rule_item.get('type', rule_type)} enabled={rule_item.get('enabled')}"
        )
