"""ante config — 설정 조회/변경 커맨드."""

from __future__ import annotations

import asyncio
import json

import click

from ante.cli.main import get_formatter
from ante.cli.middleware import get_member_id, require_auth, require_scope


@click.group()
def config() -> None:
    """설정 조회·변경."""


def _run(coro):  # noqa: ANN001, ANN202
    return asyncio.run(coro)


async def _create_services():  # noqa: ANN202
    from ante.config.config import Config
    from ante.config.dynamic import DynamicConfigService
    from ante.core.database import Database
    from ante.eventbus.bus import EventBus

    db = Database("db/ante.db")
    await db.connect()
    eventbus = EventBus()
    static_config = Config.load()
    dynamic = DynamicConfigService(db, eventbus)
    await dynamic.initialize()
    return static_config, dynamic, db


@config.command("get")
@click.argument("key", required=False, default=None)
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
                # 동적 설정 먼저 확인
                if await dynamic.exists(key):
                    value = await dynamic.get(key)
                    return {"key": key, "value": value, "source": "dynamic"}
                # 정적 설정 확인
                static_value = static_config.get(key)
                if static_value is not None:
                    return {"key": key, "value": static_value, "source": "static"}
                return {"key": key, "value": None, "source": "not_found"}
            else:
                # 전체 목록
                results: list[dict] = []

                # 정적 설정 (defaults + system.toml)
                from ante.config.defaults import DEFAULTS

                for k, v in sorted(DEFAULTS.items()):
                    static_val = static_config.get(k, v)
                    results.append(
                        {
                            "key": k,
                            "value": static_val,
                            "source": "static",
                        }
                    )

                # 동적 설정
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
        finally:
            await db.close()

    result = _run(_run_get())

    if isinstance(result, dict):
        if result["source"] == "not_found":
            fmt.error(f"설정을 찾을 수 없습니다: {result['key']}")
            return
        if fmt.is_json:
            fmt.output(result)
        else:
            click.echo(
                f"  {result['key']} = {result['value']} (source: {result['source']})"
            )
    else:
        if fmt.is_json:
            fmt.output({"configs": result})
        else:
            if not result:
                click.echo("  (설정 없음)")
                return
            for item in result:
                click.echo(
                    f"  {item['key']:40s} = {str(item['value']):20s} ({item['source']})"
                )


@config.command("set")
@click.argument("key")
@click.argument("value")
@click.pass_context
@require_auth
@require_scope("config:write")
def config_set(ctx: click.Context, key: str, value: str) -> None:
    """동적 설정 변경. 정적 설정은 변경 불가."""
    fmt = get_formatter(ctx)
    actor = get_member_id(ctx)

    async def _run_set() -> dict:
        from ante.config.defaults import DEFAULTS

        static_config, dynamic, db = await _create_services()
        try:
            # 정적 설정 키인지 확인
            if key in DEFAULTS or static_config.get(key) is not None:
                if not await dynamic.exists(key):
                    return {
                        "success": False,
                        "error": (
                            f"'{key}'는 정적 설정입니다. "
                            "config/system.toml을 직접 수정해 주세요."
                        ),
                    }

            # 값 파싱 (JSON 시도, 실패하면 문자열)
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                parsed = value

            # 카테고리 추론
            category = key.split(".")[0] if "." in key else "general"

            await dynamic.set(key, parsed, category, changed_by=f"cli:{actor}")
            return {
                "success": True,
                "key": key,
                "value": parsed,
                "category": category,
                "changed_by": actor,
            }
        finally:
            await db.close()

    result = _run(_run_set())

    if not result["success"]:
        fmt.error(result["error"])
        return

    if fmt.is_json:
        fmt.output(result)
    else:
        fmt.success(
            f"설정 변경 완료: {result['key']} = {result['value']}",
            result,
        )


@config.command("history")
@click.argument("key")
@click.option("--limit", "-n", default=20, help="조회 건수 (기본 20)")
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
