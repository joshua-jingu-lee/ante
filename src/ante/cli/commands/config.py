"""ante config — 설정 조회/변경 커맨드."""

from __future__ import annotations

import asyncio
import json

import click

from ante.cli.formatter import format_option
from ante.cli.main import get_formatter
from ante.cli.middleware import get_member_id, require_auth, require_scope


@click.group()
def config() -> None:
    """설정 조회·변경."""


def _run(coro):  # noqa: ANN001, ANN202
    return asyncio.run(coro)


async def _create_services():  # noqa: ANN202
    from ante.cli.main import get_config_dir, get_db_path
    from ante.config.config import Config
    from ante.config.dynamic import DynamicConfigService
    from ante.core.database import Database
    from ante.eventbus.bus import EventBus

    db = Database(get_db_path())
    await db.connect()
    eventbus = EventBus()
    static_config = Config.load(config_dir=get_config_dir())
    dynamic = DynamicConfigService(db, eventbus)
    await dynamic.initialize()
    return static_config, dynamic, db


async def _resolve_single(key, static_config, dynamic) -> dict:  # noqa: ANN001
    """단일 키 설정값 조회."""
    if await dynamic.exists(key):
        value = await dynamic.get(key)
        return {"key": key, "value": value, "source": "dynamic"}
    static_value = static_config.get(key)
    if static_value is not None:
        return {"key": key, "value": static_value, "source": "static"}
    return {"key": key, "value": None, "source": "not_found"}


async def _resolve_all(static_config, db) -> list[dict]:  # noqa: ANN001
    """전체 설정 목록 조회."""
    from ante.config.defaults import DEFAULTS

    results: list[dict] = []
    for k, v in sorted(DEFAULTS.items()):
        static_val = static_config.get(k, v)
        results.append({"key": k, "value": static_val, "source": "static"})

    rows = await db.fetch_all(
        "SELECT key, value, category FROM dynamic_config ORDER BY key"
    )
    for row in rows:
        results.append(
            {
                "key": row["key"],
                "value": json.loads(row["value"]),
                "source": "dynamic",
            }
        )
    return results


def _render_single(result: dict, fmt) -> None:  # noqa: ANN001
    """단일 설정 결과 출력 (missing은 caller에서 처리).

    note: missing-resource (`source == "not_found"`) 분기는 caller(`config_get`)가
    `ctx.exit(1)`로 처리한다. helper는 pure rendering만 담당한다 (#1515).
    """
    if fmt.is_json:
        fmt.output(result)
    else:
        click.echo(
            f"  {result['key']} = {result['value']} (source: {result['source']})"
        )


def _render_list(result: list[dict], fmt) -> None:  # noqa: ANN001
    """설정 목록 출력."""
    if fmt.is_json:
        fmt.output({"configs": result})
        return
    if not result:
        click.echo("  (설정 없음)")
        return
    for item in result:
        click.echo(f"  {item['key']:40s} = {str(item['value']):20s} ({item['source']})")


@config.command("get")
@click.argument("key", required=False, default=None)
@format_option
@click.pass_context
@require_auth
@require_scope("config:read")
def config_get(ctx: click.Context, key: str | None) -> None:
    """설정 조회. 키 없이 호출하면 전체 목록."""
    fmt = get_formatter(ctx)

    async def _run_get() -> dict | list[dict]:
        static_config, dynamic, db = await _create_services()
        try:
            if key is not None:
                return await _resolve_single(key, static_config, dynamic)
            return await _resolve_all(static_config, db)
        finally:
            await db.close()

    result = _run(_run_get())

    if isinstance(result, dict):
        if result["source"] == "not_found":
            fmt.error(f"설정을 찾을 수 없습니다: {result['key']}")
            ctx.exit(1)
        _render_single(result, fmt)
    else:
        _render_list(result, fmt)


@config.command("set")
@click.argument("key")
@click.argument("value")
@format_option
@click.pass_context
@require_auth
@require_scope("config:write")
def config_set(ctx: click.Context, key: str, value: str) -> None:
    """동적 설정 변경. 정적 설정은 변경 불가."""
    fmt = get_formatter(ctx)
    actor = get_member_id(ctx)

    async def _run_set() -> dict:
        from ante.cli.commands.ipc_helpers import ipc_send

        return await ipc_send("config.set", {"key": key, "value": value}, actor=actor)

    try:
        result = _run(_run_set())
    except click.ClickException as e:
        # #1673 oracle A7: invalid log_level 같은 서비스 경계 입력 오류는
        # ipc_send 가 error envelope를 ClickException 으로 변환한다. bare
        # 재raise 하면 Click 기본 처리가 ``Error: ...`` 를 stderr 로 출력하고
        # exit 1 로 종료해 JSON 모드 stdout 이 비어 envelope 계약이 깨진다
        # (probe stdout_status=None). #1655-1657 envelope discipline 미러:
        # ipc_send 가 부착한 원본 code/message 를 split 없이 복원해
        # text/JSON 공용으로 구조화된 에러를 출력하고 SystemExit(1) 한다
        # (_validators.reject_invalid_account_id 패턴).
        code = getattr(e, "ipc_error_code", "")
        message = getattr(e, "ipc_error_message", None)
        if message is None:
            # 비-IPC ClickException(서버 미기동/타임아웃 등): code 속성이
            # 없으면 ``str(e)`` 가 사람용 메시지 그대로다.
            message = str(e)
        if fmt.is_json:
            # probe 계약: stdout 으로 {status,code,message} 분리 필드.
            fmt.error(message, code=code)
        else:
            # 텍스트 모드는 ``OutputFormatter.error`` 가 code 를 출력하지
            # 않으므로, 기존 Click 기본 처리(``Error: {code}: {message}``)
            # 와 동치가 되도록 code 를 message 에 prefix 한다
            # (test_config_set_server_error 톤 보존).
            text = f"{code}: {message}" if code else message
            fmt.error(text)
        raise SystemExit(1) from e
    except Exception as e:
        fmt.error(str(e))
        return

    if fmt.is_json:
        output = {"status": "success", **result}
        fmt.output(output)
    else:
        fmt.success(
            f"설정 변경 완료: {result.get('key', key)} = {result.get('value', value)}",
            result,
        )


@config.command("history")
@click.argument("key")
@click.option(
    "--limit",
    "-n",
    default=20,
    type=click.IntRange(min=1),
    help="조회 건수 (기본 20)",
)
@format_option
@click.pass_context
@require_auth
@require_scope("config:read")
def config_history(ctx: click.Context, key: str, limit: int) -> None:
    """설정 변경 이력 조회."""
    fmt = get_formatter(ctx)

    async def _run_history() -> list[dict]:
        _, dynamic, db = await _create_services()
        try:
            return await dynamic.get_history(key, limit=limit)
        finally:
            await db.close()

    rows = _run(_run_history())

    if fmt.is_json:
        fmt.output({"key": key, "history": rows})
    else:
        if not rows:
            click.echo(f"  '{key}'에 대한 변경 이력이 없습니다.")
            return
        click.echo(f"  변경 이력: {key} (최근 {limit}건)")
        click.echo(f"  {'시각':24s} {'변경자':16s} {'이전값':20s} → {'새값':20s}")
        click.echo("  " + "-" * 84)
        for row in rows:
            old = row.get("old_value") or "(없음)"
            new = row.get("new_value", "")
            at = row["changed_at"]
            by = row["changed_by"]
            click.echo(f"  {at:24s} {by:16s} {old:20s} → {new:20s}")
