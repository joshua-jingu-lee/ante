"""ante bot — 봇 생명주기 관리 커맨드."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Coroutine
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import click

from ante.account.scoping import is_invalid_account_id
from ante.cli._validators import (
    reject_invalid_account_id,
    validate_positive_finite_amount,
)
from ante.cli.cold_path import is_active_runtime
from ante.cli.db_context import open_cli_db
from ante.cli.formatter import CommandResult, format_option
from ante.cli.main import get_formatter
from ante.cli.middleware import get_member_id, require_auth, require_scope
from ante.contracts.cli_errors import (
    BotInvalidParamError,
    BotMissingRequiredAccountError,
    CliBotNotFoundError,
    CliConfirmationRequiredError,
    CliMissingRequiredInputError,
    InvalidDateRangeError,
    SignalKeyNotSetError,
)
from ante.contracts.ipc_client_errors import IPCRemoteError, IPCServerNotRunningError
from ante.contracts.request_errors import RequestValidationError
from ante.core.database import OperationalError

if TYPE_CHECKING:
    from ante.account.service import AccountService
    from ante.bot.manager import BotManager
    from ante.core.database import Database
    from ante.eventbus.bus import EventBus

logger = logging.getLogger(__name__)


@click.group()
def bot() -> None:
    """봇 생성·시작·중지·조회."""


def _run(coro: Coroutine[Any, Any, Any]) -> Any:
    return asyncio.run(coro)


@asynccontextmanager
async def _create_services(
    ctx: click.Context | None = None,
) -> AsyncIterator[tuple[Database, EventBus, BotManager, AccountService]]:
    """CLI 에서 ``Database``/``EventBus``/``BotManager``/``AccountService`` 를
    함께 구성하는 async context manager.

    ``open_cli_db`` 기반 lifecycle (factory composition, account.py 패턴
    1:1 미러). 호출 패턴:

        async with _create_services(ctx=ctx) as (db, eventbus, mgr, account_service):
            ...

    ``open_cli_db`` 가 normal/exception/cancellation 모든 경로에서
    ``Database.close()`` 를 보장하므로 (cleanup invariant), callsite 의
    ``try/finally: await db.close()`` 패턴이 제거된다.

    Args:
        ctx: Click 컨텍스트. ``None`` 이면 ``click.get_current_context``
            (silent=True) 로 fallback 해 ctx-less call sites 와의 하위 호환을
            유지한다. 신규 호출은 항상 ctx 명시 전달이 권장된다
            (offline-factory.md §3.1).

    Yields:
        ``initialize()`` 가 완료된 ``(db, eventbus, manager, account_service)``
        4-tuple. ``BotManager``/``AccountService`` 의 ``initialize()`` 호출은
        그대로 보존된다 (read-only 명시 예외는 ``AuditLogger`` /
        ``DynamicConfigService`` 만; 본 helper 는 read-only skip 적용 안 함).

    Cleanup invariant:
        - ``open_cli_db`` 가 ``BaseException`` 까지 catch 하므로 service
          ``initialize()`` 가 raise 해도 ``Database.close()`` 가 1회 호출된다.
    """
    from ante.account.service import AccountService
    from ante.bot.manager import BotManager
    from ante.eventbus.bus import EventBus

    resolved_ctx = ctx if ctx is not None else click.get_current_context(silent=True)
    if resolved_ctx is None:
        raise ValueError(
            "_create_services requires a Click context "
            "(explicit ctx or active click.get_current_context)"
        )

    async with open_cli_db(resolved_ctx) as db:
        eventbus = EventBus()
        account_service = AccountService(db=db, eventbus=eventbus)
        await account_service.initialize()
        manager = BotManager(eventbus=eventbus, db=db)
        await manager.initialize()
        yield db, eventbus, manager, account_service


async def _audit_log(db: Database, **kwargs: Any) -> None:
    """감사 로그 기록 (실패해도 주 동작에 영향 없음)."""
    try:
        from ante.audit import AuditLogger

        al = AuditLogger(db=db)
        await al.initialize()
        await al.log(**kwargs)
    except Exception as e:
        logger.warning("감사 로그 기록 실패: %s", e)


async def _run_bot_remove_cold_path(
    bot_id: str, ctx: click.Context | None = None
) -> dict[str, Any]:
    """서버 정지 상태에서 BotManager 없이 봇을 soft-delete한다."""
    from ante.bot.cold_path import cold_path_remove_bot
    from ante.cli.main import get_config_dir
    from ante.config import Config

    resolved_ctx = ctx if ctx is not None else click.get_current_context(silent=True)
    if resolved_ctx is None:
        raise ValueError(
            "_run_bot_remove_cold_path requires a Click context "
            "(explicit ctx or active click.get_current_context)"
        )

    async with open_cli_db(resolved_ctx) as db:
        config = Config.load(config_dir=get_config_dir())
        strategies_dir = Path(str(config.get("strategy.dir", "strategies")))
        return await cold_path_remove_bot(
            db,
            bot_id,
            strategies_dir=strategies_dir,
        )


@bot.command("list")
@click.option("--account", "account_id", default=None, help="계좌 ID로 필터링")
@format_option
@click.pass_context
@require_auth
@require_scope("bot:read")
def bot_list(ctx: click.Context, account_id: str | None) -> None:
    """봇 목록 조회."""
    fmt = get_formatter(ctx)

    if account_id is not None:
        account_id = reject_invalid_account_id(account_id, fmt, context="cli.bot.list")

    actor = get_member_id(ctx)

    async def _run_list_fallback() -> list[dict[str, Any]]:
        async with _create_services(ctx=ctx) as (db, _, _, _):
            if account_id is not None:
                rows = await db.fetch_all(
                    "SELECT bot_id, name, strategy_id, account_id, status, created_at"
                    " FROM bots WHERE status != 'deleted' AND account_id = ?",
                    (account_id,),
                )
            else:
                rows = await db.fetch_all(
                    "SELECT bot_id, name, strategy_id, account_id, status, created_at"
                    " FROM bots WHERE status != 'deleted'"
                )
            return [dict(r) for r in rows]

    async def _run_list() -> list[dict[str, Any]]:
        from ante.cli.commands.ipc_helpers import ipc_send

        args: dict[str, Any] = {}
        if account_id is not None:
            args["account_id"] = account_id
        try:
            ipc_result = await ipc_send("bot.list", args, actor=actor)
        except IPCServerNotRunningError:
            return await _run_list_fallback()
        return list(ipc_result.get("bots", []))

    result = _run(_run_list())

    if not result:
        fmt.output({"message": "등록된 봇이 없습니다.", "bots": []})
        return

    if fmt.is_json:
        fmt.output({"bots": result})
    else:
        fmt.table(
            result,
            ["bot_id", "name", "strategy_id", "account_id", "status", "created_at"],
        )


@bot.command("info")
@click.argument("bot_id")
@click.pass_context
@require_auth
@require_scope("bot:read")
def bot_info(ctx: click.Context, bot_id: str) -> None:
    """봇 상세 정보 조회."""
    fmt = get_formatter(ctx)
    actor = get_member_id(ctx)

    async def _run_info_fallback() -> dict[str, Any] | None:
        async with _create_services(ctx=ctx) as (db, _, _, _):
            row = await db.fetch_one("SELECT * FROM bots WHERE bot_id = ?", (bot_id,))
            return dict(row) if row else None

    async def _run_info() -> dict[str, Any] | None:
        from ante.cli.commands.ipc_helpers import ipc_send

        try:
            ipc_result = await ipc_send("bot.info", {"bot_id": bot_id}, actor=actor)
        except IPCServerNotRunningError:
            return await _run_info_fallback()
        return ipc_result.get("bot")

    result = _run(_run_info())

    if not result:
        raise CliBotNotFoundError(f"봇을 찾을 수 없습니다: {bot_id}")

    if fmt.is_json:
        fmt.output(result)
    else:
        click.echo(f"  Bot ID    : {result['bot_id']}")
        click.echo(f"  이름      : {result['name']}")
        click.echo(f"  전략      : {result['strategy_id']}")
        click.echo(f"  계좌      : {result.get('account_id', 'test')}")
        click.echo(f"  상태      : {result['status']}")
        click.echo(f"  생성일    : {result.get('created_at')}")


def _parse_param(value: str) -> tuple[str, object]:
    """key=value 형식의 파라미터 파싱. 값은 JSON 파싱 시도."""
    import json as _json

    if "=" not in value:
        msg = f"잘못된 파라미터 형식: '{value}' (key=value 형태로 지정)"
        raise click.BadParameter(msg)
    key, raw = value.split("=", 1)
    try:
        parsed = _json.loads(raw)
    except _json.JSONDecodeError:
        parsed = raw
    return key.strip(), parsed


def _resolve_account_non_interactive(accounts: list[Any]) -> str:
    """활성 계좌 목록에서 비대화형으로 계좌를 선택한다."""
    if len(accounts) == 1:
        return cast("str", accounts[0].account_id)

    if not accounts:
        raise BotMissingRequiredAccountError(
            "활성 계좌가 없습니다. 먼저 계좌를 등록한 뒤 --account <id>로 지정하세요."
        )
    ids = ", ".join(acc.account_id for acc in accounts)
    raise BotMissingRequiredAccountError(
        f"활성 계좌가 여러 개입니다. --account <id>로 명시하세요. (가능한 계좌: {ids})"
    )


@bot.command("create")
@click.option("--name", required=True, help="봇 이름")
@click.option("--strategy", required=True, help="전략 ID")
@click.option(
    "--account",
    "account_id",
    default=None,
    help="계좌 ID (미지정 시 단일 active 계좌 자동 선택, 0개/2개 이상 시 에러)",
)
@click.option(
    "--interval",
    default=60,
    type=click.IntRange(10, 3600),
    help="실행 주기 (초, 10-3600)",
)
@click.option("--id", "bot_id", default="", help="봇 ID (미지정 시 자동 생성)")
@click.option(
    "--param",
    "params",
    multiple=True,
    help="전략 파라미터 오버라이드 (key=value, 복수 지정 가능)",
)
@click.pass_context
@require_auth
@require_scope("bot:admin")
def bot_create(
    ctx: click.Context,
    name: str,
    strategy: str,
    account_id: str | None,
    interval: int,
    bot_id: str,
    params: tuple[str, ...],
) -> CommandResult:
    """봇 생성."""
    fmt = get_formatter(ctx)
    actor = get_member_id(ctx)

    param_dict: dict[str, Any] = {}
    for p in params:
        try:
            key, value = _parse_param(p)
            param_dict[key] = value
        except click.BadParameter as e:
            raise BotInvalidParamError(str(e)) from e

    if account_id is not None:
        account_id = reject_invalid_account_id(
            account_id, fmt, context="cli.bot.create"
        )

    if account_id is None:
        from ante.account.models import AccountStatus

        async def _list_accounts() -> list[Any]:
            async with _create_services(ctx=ctx) as (_, _, _, account_service):
                return await account_service.list(status=AccountStatus.ACTIVE)

        accounts = _run(_list_accounts())
        account_id = _resolve_account_non_interactive(accounts)

    resolved_account_id = account_id

    async def _run_create() -> dict[str, Any]:
        from ante.cli.commands.ipc_helpers import ipc_send

        args: dict[str, Any] = {
            "name": name,
            "strategy_id": strategy,
            "account_id": resolved_account_id,
            "interval_seconds": interval,
        }
        if bot_id:
            args["bot_id"] = bot_id
        return await ipc_send("bot.create", args, actor=actor)

    result = _run(_run_create())

    return CommandResult(
        data=result, message=f"봇 생성 완료: {result.get('bot_id', '')}"
    )


@bot.command("remove")
@click.argument("bot_id")
@click.option(
    "--yes",
    "yes",
    is_flag=True,
    default=False,
    help="삭제를 확인 (위험 명령). 누락 시 prompt 없이 에러로 실패",
)
@click.pass_context
@require_auth
@require_scope("bot:admin")
def bot_remove(ctx: click.Context, bot_id: str, yes: bool) -> CommandResult:
    """봇 삭제.

    서버가 실행 중이면 기존 IPC 경로를 사용하고, 서버가 정지되어 있으면
    cold-path service가 persisted DB/signal key/snapshot/treasury state를 정리한다.
    `--yes` 누락 시 prompt 없이 `CLI_CONFIRMATION_REQUIRED` 에러로 종료한다.
    """
    actor = get_member_id(ctx)

    if not yes:
        raise CliConfirmationRequiredError(
            "위험 명령입니다. --yes를 명시해야 봇을 삭제합니다."
        )

    async def _run_remove() -> dict[str, Any]:
        from ante.cli.commands.ipc_helpers import ipc_send

        if is_active_runtime():
            return await ipc_send("bot.remove", {"bot_id": bot_id}, actor=actor)
        return await _run_bot_remove_cold_path(bot_id, ctx=ctx)

    result = _run(_run_remove())

    if not result.get("removed"):
        raise CliBotNotFoundError(f"봇을 찾을 수 없습니다: {bot_id}")
    suffix = "(cold-path)" if result.get("cold_path") else ""
    return CommandResult(data=result, message=f"봇 삭제 완료{suffix}: {bot_id}")


@bot.command("signal-key")
@click.argument("bot_id")
@click.option("--rotate", is_flag=True, help="기존 키 폐기 + 새 키 발급")
@click.pass_context
@require_auth
@require_scope("bot:admin")
def bot_signal_key(ctx: click.Context, bot_id: str, rotate: bool) -> None:
    """봇 시그널 키 조회 또는 재발급.

    ``--rotate`` 는 runtime IPC (``bot.signal_key.rotate``) 전용이다.
    서버가 정지되어 있으면 ``IPC_SERVER_NOT_RUNNING`` 으로 거부하며, cold-path
    DB mutation 으로 대체하지 않는다 (runtime 경계 / audit / live 상태 정합성
    보존).

    조회(rotate 미지정)는 runtime IPC (``bot.signal_key`` read) 우선 + 서버
    정지 시 snapshot DB fallback 이다 (``--rotate`` 와 정반대로 서버
    정지 시 기존 직접 DB 경로를 보존한다 — 스펙: runtime IPC + snapshot
    fallback).
    """
    fmt = get_formatter(ctx)

    if rotate:
        actor = get_member_id(ctx)

        async def _run_rotate() -> dict[str, Any]:
            from ante.cli.commands.ipc_helpers import ipc_send

            return await ipc_send(
                "bot.signal_key.rotate", {"bot_id": bot_id}, actor=actor
            )

        result = _run(_run_rotate())

        fmt.success(f"시그널 키 재발급 완료: {bot_id}", result)
        return

    actor = get_member_id(ctx)

    async def _run_signal_key_fallback() -> dict[str, Any]:
        from ante.bot.signal_key import SignalKeyManager

        async with _create_services(ctx=ctx) as (db, _, _, _):
            skm = SignalKeyManager(db)
            await skm.initialize()

            try:
                bot_row = await db.fetch_one(
                    "SELECT strategy_id FROM bots "
                    "WHERE bot_id = ? AND status != 'deleted'",
                    (bot_id,),
                )
            except OperationalError as e:
                if "no such table" in str(e).lower():
                    bot_row = None
                else:
                    raise
            if bot_row is None:
                return {"bot_id": bot_id, "missing": True}

            key = await skm.get_key(bot_id)
            if not key:
                return {"bot_id": bot_id, "signal_key": None}
            return {"bot_id": bot_id, "signal_key": key}

    async def _run_signal_key() -> dict[str, Any]:
        from ante.cli.commands.ipc_helpers import ipc_send

        try:
            return await ipc_send("bot.signal_key", {"bot_id": bot_id}, actor=actor)
        except IPCServerNotRunningError:
            return await _run_signal_key_fallback()
        except IPCRemoteError as e:
            if e.code != "BOT_NOT_FOUND":
                raise
            return {"bot_id": bot_id, "missing": True}

    result = _run(_run_signal_key())

    if result.get("missing"):
        raise CliBotNotFoundError(f"봇을 찾을 수 없습니다: {bot_id}")

    if result.get("signal_key") is None:
        raise SignalKeyNotSetError(f"signal key가 설정되지 않았습니다: {bot_id}")

    if fmt.is_json:
        fmt.output(result)
    else:
        click.echo(f"  Bot ID     : {result['bot_id']}")
        click.echo(f"  Signal Key : {result['signal_key']}")


@bot.command("positions")
@click.argument("bot_id")
@click.pass_context
@require_auth
@require_scope("bot:read")
def bot_positions(ctx: click.Context, bot_id: str) -> None:
    """봇 보유 포지션 조회."""
    fmt = get_formatter(ctx)
    actor = get_member_id(ctx)

    async def _run_positions_fallback() -> list[dict[str, Any]] | None:
        from ante.trade.performance import PerformanceTracker
        from ante.trade.position import PositionHistory
        from ante.trade.recorder import TradeRecorder
        from ante.trade.service import TradeService

        async with open_cli_db(ctx) as db:
            try:
                bot_row = await db.fetch_one(
                    "SELECT account_id FROM bots WHERE bot_id = ?", (bot_id,)
                )
            except OperationalError as e:
                if "no such table" in str(e).lower():
                    return None
                raise
            if bot_row is None:
                return None

            account_id = bot_row["account_id"]
            if is_invalid_account_id(account_id):
                raise RequestValidationError(
                    f"봇의 account_id 가 유효하지 않아 포지션을 조회할 수 없습니다:"
                    f" {bot_id} (account_id={account_id!r})"
                )

            position_history = PositionHistory(db)
            await position_history.initialize()
            recorder = TradeRecorder(db, position_history)
            await recorder.initialize()
            performance = PerformanceTracker(db)

            service = TradeService(recorder, position_history, performance)
            positions = await service.get_positions(bot_id, account_id=account_id)
            return [
                {
                    "symbol": p.symbol,
                    "quantity": p.quantity,
                    "avg_entry_price": p.avg_entry_price,
                    "realized_pnl": p.realized_pnl,
                }
                for p in positions
            ]

    async def _run_positions() -> list[dict[str, Any]] | None:
        from ante.cli.commands.ipc_helpers import ipc_send

        try:
            ipc_result = await ipc_send(
                "bot.positions", {"bot_id": bot_id}, actor=actor
            )
        except IPCServerNotRunningError:
            return await _run_positions_fallback()
        return list(ipc_result.get("positions", []))

    result = _run(_run_positions())

    if result is None:
        raise CliBotNotFoundError(f"봇을 찾을 수 없습니다: {bot_id}")

    if not result:
        fmt.output({"message": "보유 포지션 없음", "positions": []})
        return

    if fmt.is_json:
        fmt.output({"positions": result})
    else:
        fmt.table(result, ["symbol", "quantity", "avg_entry_price", "realized_pnl"])


@bot.command("update")
@click.argument("bot_id")
@click.option("--name", default=None, help="봇 이름")
@click.option("--strategy", "strategy_id", default=None, help="전략 ID")
@click.option(
    "--interval",
    "interval_seconds",
    type=click.IntRange(10, 3600),
    default=None,
    help="실행 주기(초)",
)
@click.option(
    "--budget",
    type=float,
    callback=validate_positive_finite_amount,
    default=None,
    help="목표 할당 예산",
)
@click.option(
    "--auto-restart/--no-auto-restart",
    default=None,
    help="오류 시 자동 재시작 여부",
)
@click.option("--max-restart-attempts", type=click.IntRange(1, 10), default=None)
@click.option("--restart-cooldown-seconds", type=click.IntRange(10, 600), default=None)
@click.option("--step-timeout-seconds", type=click.IntRange(5, 120), default=None)
@click.option("--max-signals-per-step", type=click.IntRange(1, 200), default=None)
@format_option
@click.pass_context
@require_auth
@require_scope("bot:admin")
def bot_update(
    ctx: click.Context,
    bot_id: str,
    name: str | None,
    strategy_id: str | None,
    interval_seconds: int | None,
    budget: float | None,
    auto_restart: bool | None,
    max_restart_attempts: int | None,
    restart_cooldown_seconds: int | None,
    step_timeout_seconds: int | None,
    max_signals_per_step: int | None,
) -> None:
    """중지 상태 봇 설정 수정."""
    fmt = get_formatter(ctx)
    actor = get_member_id(ctx)
    updates = {
        "name": name,
        "strategy_id": strategy_id,
        "interval_seconds": interval_seconds,
        "budget": budget,
        "auto_restart": auto_restart,
        "max_restart_attempts": max_restart_attempts,
        "restart_cooldown_seconds": restart_cooldown_seconds,
        "step_timeout_seconds": step_timeout_seconds,
        "max_signals_per_step": max_signals_per_step,
    }
    updates = {k: v for k, v in updates.items() if v is not None}
    if not updates:
        raise CliMissingRequiredInputError("변경할 필드를 하나 이상 지정하세요.")

    async def _run_update() -> dict[str, Any]:
        from ante.cli.commands.ipc_helpers import ipc_send

        return await ipc_send(
            "bot.update",
            {"bot_id": bot_id, "updates": updates},
            actor=actor,
        )

    result = _run(_run_update())

    if fmt.is_json:
        fmt.output(result)
    else:
        click.echo(f"봇 설정 수정 완료: {bot_id}")


def _parse_log_datetime(
    value: str | None,
    field: str,
    *,
    end_of_day: bool = False,
) -> datetime | None:
    if value is None:
        return None
    try:
        parsed_date = date.fromisoformat(value)
    except ValueError:
        parsed_date = None
    if parsed_date is not None:
        t = time.max if end_of_day else time.min
        return datetime.combine(parsed_date, t, tzinfo=UTC)
    try:
        parsed_dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as e:
        raise click.BadParameter(
            f"{field}는 YYYY-MM-DD 또는 ISO 8601 datetime이어야 합니다"
        ) from e
    if parsed_dt.tzinfo is None:
        return parsed_dt.replace(tzinfo=UTC)
    return parsed_dt.astimezone(UTC)


@bot.command("logs")
@click.argument("bot_id")
@click.option("--limit", default=50, type=click.IntRange(1, 100), help="조회 수")
@click.option("--offset", default=0, type=click.IntRange(min=0), help="시작 offset")
@click.option("--from", "from_date", default=None, help="시작일/시각")
@click.option("--to", "to_date", default=None, help="종료일/시각")
@format_option
@click.pass_context
@require_auth
@require_scope("bot:read")
def bot_logs(
    ctx: click.Context,
    bot_id: str,
    limit: int,
    offset: int,
    from_date: str | None,
    to_date: str | None,
) -> None:
    """봇 실행 로그 조회."""
    fmt = get_formatter(ctx)
    try:
        since = _parse_log_datetime(from_date, "--from")
        until = _parse_log_datetime(to_date, "--to", end_of_day=True)
    except click.BadParameter as e:
        raise RequestValidationError(str(e)) from e
    if since is not None and until is not None and since > until:
        raise InvalidDateRangeError(
            f"시작일({from_date})이(가) 종료일({to_date}) 이후입니다."
        )

    async def _run_logs() -> dict[str, Any]:
        from ante.eventbus.history import EventHistoryStore

        async with open_cli_db(ctx) as db:
            try:
                bot_row = await db.fetch_one(
                    "SELECT 1 FROM bots WHERE bot_id = ? AND status != 'deleted'",
                    (bot_id,),
                )
            except OperationalError as e:
                if "no such table" in str(e).lower():
                    bot_row = None
                else:
                    raise
            if bot_row is None:
                return {"bot_id": bot_id, "missing": True, "logs": [], "total": 0}

            store = EventHistoryStore(db)
            await store.initialize()
            payload_filter = {"bot_id": bot_id}
            rows = await store.query(
                event_type="BotStepCompletedEvent",
                since=since,
                limit=limit,
                until=until,
                offset=offset,
                payload_filter=payload_filter,
            )
            total = await store.count(
                event_type="BotStepCompletedEvent",
                since=since,
                until=until,
                payload_filter=payload_filter,
            )
            logs = [
                {
                    "event_id": row.get("event_id", ""),
                    "timestamp": row.get("timestamp", ""),
                    "result": row.get("payload", {}).get("result", ""),
                    "message": row.get("payload", {}).get("message", ""),
                }
                for row in rows
            ]
            return {"bot_id": bot_id, "logs": logs, "total": total}

    result = _run(_run_logs())
    if result.get("missing"):
        raise CliBotNotFoundError(f"봇을 찾을 수 없습니다: {bot_id}")
    if fmt.is_json:
        fmt.output(result)
    elif not result["logs"]:
        click.echo("(logs 없음)")
    else:
        fmt.table(result["logs"], ["timestamp", "result", "message"])


@bot.command("start")
@click.argument("bot_id")
@format_option
@click.pass_context
@require_auth
@require_scope("bot:admin")
def bot_start(ctx: click.Context, bot_id: str) -> None:
    """봇 시작."""
    fmt = get_formatter(ctx)
    actor = get_member_id(ctx)

    async def _run_start() -> dict[str, Any]:
        from ante.cli.commands.ipc_helpers import ipc_send

        return await ipc_send("bot.start", {"bot_id": bot_id}, actor=actor)

    result = _run(_run_start())

    if fmt.is_json:
        fmt.output(result)
    else:
        click.echo(f"봇 시작 완료: {bot_id}")


@bot.command("stop")
@click.argument("bot_id")
@format_option
@click.pass_context
@require_auth
@require_scope("bot:admin")
def bot_stop(ctx: click.Context, bot_id: str) -> None:
    """봇 중지."""
    fmt = get_formatter(ctx)
    actor = get_member_id(ctx)

    async def _run_stop() -> dict[str, Any]:
        from ante.cli.commands.ipc_helpers import ipc_send

        return await ipc_send("bot.stop", {"bot_id": bot_id}, actor=actor)

    result = _run(_run_stop())

    if fmt.is_json:
        fmt.output(result)
    else:
        click.echo(f"봇 중지 완료: {bot_id}")


@bot.command("status")
@click.argument("bot_id")
@format_option
@click.pass_context
@require_auth
@require_scope("bot:read")
def bot_status(ctx: click.Context, bot_id: str) -> None:
    """봇 live 상태 조회."""
    fmt = get_formatter(ctx)
    actor = get_member_id(ctx)

    async def _run_status() -> dict[str, Any]:
        from ante.cli.commands.ipc_helpers import ipc_send

        return await ipc_send("bot.status", {"bot_id": bot_id}, actor=actor)

    result = _run(_run_status())

    if fmt.is_json:
        fmt.output(result)
        return

    info = result.get("bot", {})
    click.echo(f"  Bot ID       : {info.get('bot_id')}")
    click.echo(f"  Name         : {info.get('name')}")
    click.echo(f"  Status       : {info.get('status')}")
    click.echo(f"  Account ID   : {info.get('account_id')}")
    click.echo(f"  Strategy ID  : {info.get('strategy_id')}")
    if info.get("strategy_name"):
        click.echo(f"  Strategy Name: {info.get('strategy_name')}")
    if info.get("interval_seconds") is not None:
        click.echo(f"  Interval     : {info.get('interval_seconds')}s")
    if info.get("started_at"):
        click.echo(f"  Started At   : {info.get('started_at')}")
    if info.get("stopped_at"):
        click.echo(f"  Stopped At   : {info.get('stopped_at')}")
    if info.get("error_message"):
        click.echo(f"  Error        : {info.get('error_message')}")
    budget = info.get("budget")
    if budget:
        click.echo("  Budget:")
        for k, v in budget.items():
            click.echo(f"    {k}: {v}")
    positions = info.get("positions")
    if positions:
        click.echo(f"  Positions ({len(positions)}):")
        for p in positions:
            click.echo(
                f"    {p.get('symbol')}: qty={p.get('quantity')}, "
                f"avg={p.get('avg_entry_price')}"
            )
