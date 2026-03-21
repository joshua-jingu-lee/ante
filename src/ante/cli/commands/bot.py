"""ante bot — 봇 생명주기 관리 커맨드."""

from __future__ import annotations

import asyncio
import logging

import click

from ante.cli.main import get_formatter
from ante.cli.middleware import get_member_id, require_auth, require_scope

logger = logging.getLogger(__name__)


@click.group()
def bot() -> None:
    """봇 생성·시작·중지·조회."""


def _run(coro):  # noqa: ANN001, ANN202
    return asyncio.run(coro)


async def _create_services():  # noqa: ANN202
    from ante.account.service import AccountService
    from ante.bot.manager import BotManager
    from ante.core.database import Database
    from ante.eventbus.bus import EventBus

    db = Database("db/ante.db")
    await db.connect()
    eventbus = EventBus()
    account_service = AccountService(db=db, eventbus=eventbus)
    await account_service.initialize()
    manager = BotManager(eventbus=eventbus, db=db)
    await manager.initialize()
    return db, eventbus, manager, account_service


async def _audit_log(db, **kwargs) -> None:  # noqa: ANN001
    """감사 로그 기록 (실패해도 주 동작에 영향 없음)."""
    try:
        from ante.audit import AuditLogger

        al = AuditLogger(db=db)
        await al.initialize()
        await al.log(**kwargs)
    except Exception as e:
        logger.warning("감사 로그 기록 실패: %s", e)


@bot.command("list")
@click.option("--account", "account_id", default=None, help="계좌 ID로 필터링")
@click.pass_context
@require_auth
@require_scope("bot:read")
def bot_list(ctx: click.Context, account_id: str | None) -> None:
    """봇 목록 조회."""
    fmt = get_formatter(ctx)

    async def _run_list() -> list[dict]:
        db, _, _, _ = await _create_services()
        try:
            if account_id:
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
        finally:
            await db.close()

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

    async def _run_info() -> dict | None:
        db, _, _, _ = await _create_services()
        try:
            row = await db.fetch_one("SELECT * FROM bots WHERE bot_id = ?", (bot_id,))
            return dict(row) if row else None
        finally:
            await db.close()

    result = _run(_run_info())

    if not result:
        fmt.error(f"봇을 찾을 수 없습니다: {bot_id}")
        return

    if fmt.is_json:
        fmt.output(result)
    else:
        click.echo(f"  Bot ID    : {result['bot_id']}")
        click.echo(f"  이름      : {result['name']}")
        click.echo(f"  전략      : {result['strategy_id']}")
        click.echo(f"  계좌      : {result.get('account_id', 'test')}")
        click.echo(f"  상태      : {result['status']}")
        click.echo(f"  생성일    : {result['created_at']}")


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


def _select_account_interactive(accounts: list) -> str:
    """활성 계좌 목록에서 대화형으로 계좌를 선택한다."""
    if not accounts:
        click.echo("활성 계좌가 없습니다. 먼저 계좌를 등록하세요.")
        raise SystemExit(1)

    if len(accounts) == 1:
        selected = accounts[0]
        msg = f"계좌 자동 선택: {selected.account_id}"
        msg += f" ({selected.exchange} / {selected.currency})"
        click.echo(msg)
        return selected.account_id

    click.echo("계좌를 선택하세요:")
    for i, acc in enumerate(accounts, 1):
        click.echo(f"  {i}) {acc.account_id} ({acc.exchange} / {acc.currency})")
    choice = click.prompt("", type=click.IntRange(1, len(accounts)))
    return accounts[choice - 1].account_id


@bot.command("create")
@click.option("--name", required=True, help="봇 이름")
@click.option("--strategy", required=True, help="전략 ID")
@click.option(
    "--account",
    "account_id",
    default=None,
    help="계좌 ID (미지정 시 대화형 선택)",
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
) -> None:
    """봇 생성."""
    fmt = get_formatter(ctx)
    actor = get_member_id(ctx)

    # 파라미터 파싱
    param_dict: dict = {}
    for p in params:
        try:
            key, value = _parse_param(p)
            param_dict[key] = value
        except click.BadParameter as e:
            fmt.error(str(e))
            return

    # 계좌 미지정 시 대화형 선택
    if account_id is None:
        from ante.account.models import AccountStatus

        async def _list_accounts() -> list:
            _, _, _, account_service = await _create_services()
            return await account_service.list(status=AccountStatus.ACTIVE)

        accounts = _run(_list_accounts())
        account_id = _select_account_interactive(accounts)

    resolved_account_id = account_id

    async def _run_create() -> dict:
        from ante.cli.commands._ipc import ipc_send

        args: dict = {
            "name": name,
            "strategy_id": strategy,
            "account_id": resolved_account_id,
            "interval_seconds": interval,
        }
        if bot_id:
            args["bot_id"] = bot_id
        if param_dict:
            args["params"] = param_dict
        return await ipc_send("bot.create", args, actor=actor)

    try:
        result = _run(_run_create())
    except click.ClickException:
        raise
    except Exception as e:
        fmt.error(str(e))
        return

    fmt.success(f"봇 생성 완료: {result.get('bot_id', '')}", result)


@bot.command("remove")
@click.argument("bot_id")
@click.confirmation_option(prompt="봇을 삭제합니다. 계속하시겠습니까?")
@click.pass_context
@require_auth
@require_scope("bot:admin")
def bot_remove(ctx: click.Context, bot_id: str) -> None:
    """봇 삭제."""
    fmt = get_formatter(ctx)
    actor = get_member_id(ctx)

    async def _run_remove() -> dict:
        from ante.cli.commands._ipc import ipc_send

        return await ipc_send("bot.remove", {"bot_id": bot_id}, actor=actor)

    try:
        result = _run(_run_remove())
    except click.ClickException:
        raise
    except Exception as e:
        fmt.error(str(e))
        return

    if result.get("removed"):
        fmt.success(f"봇 삭제 완료: {bot_id}")
    else:
        fmt.error(f"봇을 찾을 수 없습니다: {bot_id}")


@bot.command("signal-key")
@click.argument("bot_id")
@click.option("--rotate", is_flag=True, help="기존 키 폐기 + 새 키 발급")
@click.pass_context
@require_auth
@require_scope("bot:admin")
def bot_signal_key(ctx: click.Context, bot_id: str, rotate: bool) -> None:
    """봇 시그널 키 조회 또는 재발급."""
    fmt = get_formatter(ctx)

    async def _run_signal_key() -> dict:
        from ante.bot.signal_key import SignalKeyManager

        db, _, _, _ = await _create_services()
        try:
            skm = SignalKeyManager(db)
            await skm.initialize()

            if rotate:
                new_key = await skm.rotate(bot_id)
                return {"bot_id": bot_id, "signal_key": new_key, "rotated": True}

            key = await skm.get_key(bot_id)
            if not key:
                return {"bot_id": bot_id, "signal_key": None}
            return {"bot_id": bot_id, "signal_key": key}
        finally:
            await db.close()

    try:
        result = _run(_run_signal_key())
    except Exception as e:
        fmt.error(str(e))
        return

    if result.get("signal_key") is None:
        fmt.error(f"시그널 키가 없습니다: {bot_id}")
        return

    if result.get("rotated"):
        fmt.success(f"시그널 키 재발급 완료: {bot_id}", result)
    else:
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

    async def _run_positions() -> list[dict]:
        from ante.core.database import Database
        from ante.eventbus.bus import EventBus
        from ante.trade.performance import PerformanceTracker
        from ante.trade.position import PositionHistory
        from ante.trade.recorder import TradeRecorder
        from ante.trade.service import TradeService

        db = Database("db/ante.db")
        await db.connect()
        try:
            eventbus = EventBus()
            recorder = TradeRecorder(db, eventbus)
            await recorder.initialize()
            position_history = PositionHistory(db, eventbus)
            await position_history.initialize()
            performance = PerformanceTracker(db)
            await performance.initialize()
            service = TradeService(recorder, position_history, performance)
            positions = await service.get_positions(bot_id)
            return [
                {
                    "symbol": p.symbol,
                    "quantity": p.quantity,
                    "avg_entry_price": p.avg_entry_price,
                    "realized_pnl": p.realized_pnl,
                }
                for p in positions
            ]
        finally:
            await db.close()

    result = _run(_run_positions())

    if not result:
        fmt.output({"message": "보유 포지션 없음", "positions": []})
        return

    if fmt.is_json:
        fmt.output({"positions": result})
    else:
        fmt.table(result, ["symbol", "quantity", "avg_entry_price", "realized_pnl"])
