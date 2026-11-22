"""ante config — 설정 조회/변경 커맨드."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Coroutine
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

import click

from ante.cli.db_context import open_cli_db
from ante.cli.formatter import format_option
from ante.cli.main import get_formatter
from ante.cli.middleware import get_member_id, require_auth, require_scope
from ante.contracts.cli_errors import ConfigKeyNotFoundError

if TYPE_CHECKING:
    from ante.config.config import Config
    from ante.config.dynamic import DynamicConfigService
    from ante.core.database import Database


@click.group()
def config() -> None:
    """설정 조회·변경."""


def _run(coro: Coroutine[Any, Any, Any]) -> Any:
    return asyncio.run(coro)


@asynccontextmanager
async def _create_services(
    ctx: click.Context | None = None,
) -> AsyncIterator[tuple[Config, DynamicConfigService, Database]]:
    """CLI 에서 ``Config`` / ``DynamicConfigService`` / ``Database`` 를 함께
    구성하는 async context manager.

    ``open_cli_db`` 기반 lifecycle (factory composition, account.py 패턴
    1:1 미러). 호출 패턴:

        async with _create_services(ctx=ctx) as (static_config, dynamic, db):
            ...

    Args:
        ctx: Click 컨텍스트. ``None`` 이면 ``click.get_current_context``
            (silent=True) 로 fallback. 신규 호출은 ctx 명시 전달 권장.

    Yields:
        ``DynamicConfigService.initialize()`` 가 완료된 3-tuple.
        ``DynamicConfigService.initialize()`` 는 read-only 명시 예외(schema
        bootstrap) 로 호출을 보존한다.

    Cleanup invariant:
        - ``open_cli_db`` 가 ``BaseException`` 까지 catch — service init 실패
          시에도 ``Database.close()`` 보장.
    """
    from ante.cli.main import get_config_dir
    from ante.config.config import Config
    from ante.config.dynamic import DynamicConfigService
    from ante.eventbus.bus import EventBus

    resolved_ctx = ctx if ctx is not None else click.get_current_context(silent=True)
    if resolved_ctx is None:
        raise ValueError(
            "_create_services requires a Click context "
            "(explicit ctx or active click.get_current_context)"
        )

    async with open_cli_db(resolved_ctx) as db:
        eventbus = EventBus()
        static_config = Config.load(config_dir=get_config_dir())
        dynamic = DynamicConfigService(db, eventbus)
        await dynamic.initialize()
        yield static_config, dynamic, db


async def _resolve_single(
    key: str, static_config: Config, dynamic: DynamicConfigService
) -> dict[str, Any]:
    """단일 키 설정값 조회."""
    if await dynamic.exists(key):
        value = await dynamic.get(key)
        return {"key": key, "value": value, "source": "dynamic"}
    static_value = static_config.get(key)
    if static_value is not None:
        return {"key": key, "value": static_value, "source": "static"}
    return {"key": key, "value": None, "source": "not_found"}


async def _resolve_all(static_config: Config, db: Database) -> list[dict[str, Any]]:
    """전체 설정 목록 조회."""
    from ante.config.defaults import DEFAULTS

    results: list[dict[str, Any]] = []
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


def _render_single(result: dict[str, Any], fmt: Any) -> None:
    """단일 설정 결과 출력 (missing은 caller에서 처리)."""
    if fmt.is_json:
        fmt.output(result)
    else:
        click.echo(
            f"  {result['key']} = {result['value']} (source: {result['source']})"
        )


def _render_list(result: list[dict[str, Any]], fmt: Any) -> None:
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

    async def _run_get() -> dict[str, Any] | list[dict[str, Any]]:
        async with _create_services(ctx=ctx) as (static_config, dynamic, db):
            if key is not None:
                return await _resolve_single(key, static_config, dynamic)
            return await _resolve_all(static_config, db)

    result = _run(_run_get())

    if isinstance(result, dict):
        if result["source"] == "not_found":
            raise ConfigKeyNotFoundError(f"설정을 찾을 수 없습니다: {result['key']}")
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

    async def _run_set() -> dict[str, Any]:
        from ante.cli.commands.ipc_helpers import ipc_send

        return await ipc_send("config.set", {"key": key, "value": value}, actor=actor)

    result = _run(_run_set())

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

    async def _run_history() -> list[dict[str, Any]]:
        async with _create_services(ctx=ctx) as (_, dynamic, _):
            return await dynamic.get_history(key, limit=limit)

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
