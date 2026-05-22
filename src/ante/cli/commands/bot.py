"""ante bot — 봇 생명주기 관리 커맨드."""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from pathlib import Path

import click

from ante.cli._validators import reject_invalid_account_id
from ante.cli.cold_path import is_active_runtime
from ante.cli.formatter import format_option
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
    from ante.cli.main import get_db_path
    from ante.core.database import Database
    from ante.eventbus.bus import EventBus

    db = Database(get_db_path())
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


async def _run_bot_remove_cold_path(bot_id: str) -> dict:
    """서버 정지 상태에서 BotManager 없이 봇을 soft-delete한다."""
    from ante.bot.cold_path import cold_path_remove_bot
    from ante.cli.main import get_config_dir, get_db_path
    from ante.config import Config
    from ante.core.database import Database

    db = Database(get_db_path())
    await db.connect()
    try:
        config = Config.load(config_dir=get_config_dir())
        strategies_dir = Path(str(config.get("strategy.dir", "strategies")))
        return await cold_path_remove_bot(
            db,
            bot_id,
            strategies_dir=strategies_dir,
        )
    finally:
        await db.close()


@bot.command("list")
@click.option("--account", "account_id", default=None, help="계좌 ID로 필터링")
@format_option
@click.pass_context
@require_auth
@require_scope("bot:read")
def bot_list(ctx: click.Context, account_id: str | None) -> None:
    """봇 목록 조회."""
    fmt = get_formatter(ctx)

    # SQL filter **이전** ingress 검증 (#1634, Split A).
    #
    # omitted-vs-provided 계약 (#1624 동형):
    #   - `--account` 미지정(`account_id is None`) → 전체 봇 반환 동작 **보존**
    #     (omitted 분기는 검증하지 않는다; 이게 불변이다).
    #   - `--account` provided(`default`/패턴 위반/`""` 포함) → invalid면
    #     SQL filter 이전에 `VALIDATION_ERROR` + exit 1로 거부. 기존
    #     `if account_id:` truthy 분기는 `""`를 falsy-skip해 전체 봇을
    #     반환했으나(provided-empty drift), provided-empty도 invalid로 거부한다.
    if account_id is not None:
        account_id = reject_invalid_account_id(account_id, fmt, context="cli.bot.list")

    async def _run_list() -> list[dict]:
        db, _, _, _ = await _create_services()
        try:
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
        ctx.exit(1)

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


def _resolve_account_non_interactive(accounts: list, fmt) -> str:  # noqa: ANN001
    """활성 계좌 목록에서 비대화형으로 계좌를 선택한다.

    - 활성 계좌가 정확히 1개면 자동 선택한다.
    - 활성 계좌가 0개 또는 2개 이상이면 prompt 없이
      `BOT_MISSING_REQUIRED_ACCOUNT` 에러로 실패한다.
    """
    if len(accounts) == 1:
        return accounts[0].account_id

    if not accounts:
        fmt.error(
            "활성 계좌가 없습니다. 먼저 계좌를 등록한 뒤 --account <id>로 지정하세요.",
            code="BOT_MISSING_REQUIRED_ACCOUNT",
        )
    else:
        ids = ", ".join(acc.account_id for acc in accounts)
        fmt.error(
            "활성 계좌가 여러 개입니다. --account <id>로 명시하세요."
            f" (가능한 계좌: {ids})",
            code="BOT_MISSING_REQUIRED_ACCOUNT",
        )
    raise SystemExit(1)


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
            raise SystemExit(1) from e

    # #1656 E bucket defense-in-depth: provided invalid account_id
    # (`default`/패턴 위반/`""`)를 omitted resolver / `ipc_send`
    # (→`_handle_bot_create`) 이전에 거부한다. IPC handler가 1차
    # 보증(handler-first require_account_id)하지만, CLI ingress 거부는 clean
    # early exit(traceback 부재)이다. **provided-only**(`account_id is not
    # None`)로만 검증해 `--account` 미지정(None) → 비대화형 resolver 분기를
    # **보존**한다(omitted 불변, #1634 `bot_list`(L97) 동형, invalid-format ↔
    # valid-absent/omitted 분리). 에러코드는 #1633 SSOT `VALIDATION_ERROR`.
    if account_id is not None:
        account_id = reject_invalid_account_id(
            account_id, fmt, context="cli.bot.create"
        )

    # 계좌 미지정 시 비대화형 resolver — 단일 active 계좌면 자동 선택,
    # 그 외(0개/2개 이상)에는 BOT_MISSING_REQUIRED_ACCOUNT로 실패한다.
    if account_id is None:
        from ante.account.models import AccountStatus

        async def _list_accounts() -> list:
            _, _, _, account_service = await _create_services()
            return await account_service.list(status=AccountStatus.ACTIVE)

        accounts = _run(_list_accounts())
        account_id = _resolve_account_non_interactive(accounts, fmt)

    resolved_account_id = account_id

    async def _run_create() -> dict:
        from ante.cli.commands.ipc_helpers import ipc_send

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
        raise SystemExit(1) from e

    fmt.success(f"봇 생성 완료: {result.get('bot_id', '')}", result)


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
def bot_remove(ctx: click.Context, bot_id: str, yes: bool) -> None:
    """봇 삭제.

    서버가 실행 중이면 기존 IPC 경로를 사용하고, 서버가 정지되어 있으면
    cold-path service가 persisted DB/signal key/snapshot/treasury state를 정리한다.
    `--yes` 누락 시 prompt 없이 `CLI_CONFIRMATION_REQUIRED` 에러로 종료한다.
    """
    fmt = get_formatter(ctx)
    actor = get_member_id(ctx)

    if not yes:
        fmt.error(
            "위험 명령입니다. --yes를 명시해야 봇을 삭제합니다.",
            code="CLI_CONFIRMATION_REQUIRED",
        )
        raise SystemExit(1)

    async def _run_remove() -> dict:
        from ante.cli.commands.ipc_helpers import ipc_send

        if is_active_runtime():
            return await ipc_send("bot.remove", {"bot_id": bot_id}, actor=actor)
        return await _run_bot_remove_cold_path(bot_id)

    try:
        result = _run(_run_remove())
    except click.ClickException:
        raise
    except Exception as e:
        fmt.error(str(e), code=getattr(e, "code", ""))
        raise SystemExit(1) from e

    if result.get("removed"):
        suffix = "(cold-path)" if result.get("cold_path") else ""
        fmt.success(f"봇 삭제 완료{suffix}: {bot_id}", result)
    else:
        fmt.error(f"봇을 찾을 수 없습니다: {bot_id}")
        raise SystemExit(1)


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

            # 미존재 bot 에 대한 signal key 발급/조회를 막기 위해
            # rotate/get_key 호출 전에 bot 존재를 먼저 확인한다. 미존재면
            # sentinel(``missing=True``)을 반환하여 orphan credential 발급을
            # 차단한다. 형제 명령(`bot info`/`bot remove`/`bot positions`,
            # #1558)과 동일하게 code 없는 에러 + exit 1 로 거부한다.
            #
            # ``status != 'deleted'`` 조건은 ``BotManager.load_from_db``
            # (manager.py:212 ``FROM bots WHERE status != 'deleted'``)의
            # 운영 bot 정의와 정렬한다. ``bot remove`` 는 키 폐기 후
            # soft-delete (manager.py:826 ``UPDATE bots SET status =
            # 'deleted'``) 하므로 row 가 남는다 — 이를 운영상 미존재로
            # 취급하지 않으면 soft-deleted bot 에 ``--rotate`` 가
            # orphan credential 을 재발급한다 (#1596가 막으려는 버그류).
            #
            # ``bots`` 테이블은 ``BotManager.initialize()`` 에서 생성되며
            # 위 ``_create_services()`` 가 이를 보장하지만, 방어적으로
            # malformed db 외의 "no such table" 은 미존재 bot 으로 정규화
            # 한다 (malformed db 같은 다른 ``OperationalError`` 까지
            # 삼키지 않도록 메시지로 좁힌다, #1558 동형).
            try:
                bot_row = await db.fetch_one(
                    "SELECT 1 FROM bots WHERE bot_id = ? AND status != 'deleted'",
                    (bot_id,),
                )
            except sqlite3.OperationalError as e:
                if "no such table" in str(e).lower():
                    bot_row = None
                else:
                    raise
            if bot_row is None:
                return {"bot_id": bot_id, "missing": True}

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
        # bot 존재확인 중 non-"no such table" ``OperationalError``
        # (malformed/locked DB 등)가 재던져지면 여기로 떨어진다. JSON error를
        # 출력하면서도 exit 0 으로 끝나면 자동화 호출자가 실패를 감지하지
        # 못하므로, 형제 ``bot remove`` (raise SystemExit(1) from e)와 동일하게
        # non-zero exit 로 종료한다 (#1596). 메시지 톤은 기존 bot_signal_key
        # 그대로 유지한다 (code 미부착 — Non-Goal: 신규 에러코드 신설 금지).
        fmt.error(str(e))
        raise SystemExit(1) from e

    if result.get("missing"):
        # 미존재 bot: 형제 명령(`bot info`/`bot remove`/`bot positions`)과
        # 동일하게 code 없는 에러 메시지 + exit 1 (#1596). signal_key None
        # 분기보다 먼저 처리하여 미존재 bot 이 "키 없음" 으로 잘못 빠지지
        # 않도록 한다.
        fmt.error(f"봇을 찾을 수 없습니다: {bot_id}")
        ctx.exit(1)

    if result.get("signal_key") is None:
        fmt.error(f"시그널 키가 없습니다: {bot_id}")
        ctx.exit(1)

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

    async def _run_positions() -> list[dict] | None:
        from ante.cli.main import get_db_path
        from ante.core.database import Database
        from ante.trade.performance import PerformanceTracker
        from ante.trade.position import PositionHistory
        from ante.trade.recorder import TradeRecorder
        from ante.trade.service import TradeService

        db = Database(get_db_path())
        await db.connect()
        try:
            # 미존재 bot 을 "실재 bot 의 0 포지션" 과 구분하기 위해 포지션 조회
            # 전에 bot 존재를 먼저 확인한다. 미존재면 sentinel ``None`` 을
            # 반환하고, 실재 bot 이면 (0개 포함) list 를 반환한다 (#1558).
            #
            # ``bots`` 테이블은 ``BotManager.initialize()`` 에서만 생성되는데,
            # 이 경로는 raw ``Database`` 만 쓰고 ``BotManager`` 를 초기화하지
            # 않는다(예: ``ante init`` 직후). 테이블 자체가 없으면 정의상
            # 해당 bot_id 는 존재할 수 없으므로 미존재 bot 과 동일하게
            # 정규화한다(=sentinel ``None``). 단, malformed db 같은 다른
            # ``OperationalError`` 까지 삼키지 않도록 "no such table" 메시지
            # 일 때로만 좁힌다 (#1558).
            try:
                bot_row = await db.fetch_one(
                    "SELECT 1 FROM bots WHERE bot_id = ?", (bot_id,)
                )
            except sqlite3.OperationalError as e:
                if "no such table" in str(e).lower():
                    return None
                raise
            if bot_row is None:
                return None

            position_history = PositionHistory(db)
            await position_history.initialize()
            recorder = TradeRecorder(db, position_history)
            await recorder.initialize()
            performance = PerformanceTracker(db)

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

    if result is None:
        # 미존재 bot: 형제 명령(`bot info`/`bot remove`)과 동일하게
        # code 없는 에러 메시지 + exit 1 (#1558).
        fmt.error(f"봇을 찾을 수 없습니다: {bot_id}")
        ctx.exit(1)

    if not result:
        # 실재 bot, 0 포지션: 기존 계약(exit 0 + "보유 포지션 없음") 유지.
        fmt.output({"message": "보유 포지션 없음", "positions": []})
        return

    if fmt.is_json:
        fmt.output({"positions": result})
    else:
        fmt.table(result, ["symbol", "quantity", "avg_entry_price", "realized_pnl"])


# ── 봇 생명주기 leaf (#1713) ─────────────────────────────────────────────
#
# Refs #1713/#1712: ``bot.start``/``bot.stop``/``bot.status`` IPC handler가
# Web API ``POST/GET /api/bots/{bot_id}/...``와 정렬된 거부 경로
# (``BOT_NOT_FOUND`` / ``BOT_ACCOUNT_CREDENTIALS_NOT_CONFIGURED`` /
# ``BOT_STATE_CONFLICT``) coded exception을 raise한다. CLI ingress는 IPC
# 단일-chokepoint를 그대로 사용하며 별도 cold-path fallback을 제공하지
# 않는다(Non-Goal). 에러 envelope 안정성은 #1673 ``config set`` 패턴
# (``ipc_send``가 ``ClickException``에 부착한 ``ipc_error_code``/
# ``ipc_error_message``를 split 없이 복원) 1:1 미러로 보존한다.


@bot.command("start")
@click.argument("bot_id")
@format_option
@click.pass_context
@require_auth
@require_scope("bot:admin")
def bot_start(ctx: click.Context, bot_id: str) -> None:
    """봇 시작 (Web API ``POST /api/bots/{bot_id}/start``와 같은 동작)."""
    fmt = get_formatter(ctx)
    actor = get_member_id(ctx)

    async def _run_start() -> dict:
        from ante.cli.commands.ipc_helpers import ipc_send

        return await ipc_send("bot.start", {"bot_id": bot_id}, actor=actor)

    try:
        result = _run(_run_start())
    except click.ClickException as e:
        # #1673 미러: ipc_send가 부착한 원본 code/message를 split 없이
        # 복원해 text/JSON 공용 envelope 안정성을 보존한다.
        code = getattr(e, "ipc_error_code", "") or "IPC_ERROR"
        message = getattr(e, "ipc_error_message", None) or e.message
        if fmt.is_json:
            fmt.error(message, code=code)
        else:
            text = f"{code}: {message}" if code else message
            fmt.error(text)
        raise SystemExit(1) from e

    # JSON 모드는 IPC `{bot: ...}` envelope 그대로 (BotDetailResponse 정합 —
    # `bot status`와 동일 shape, agent 파싱 일관). text 모드만 사용자 친화적
    # 성공 메시지.
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
    """봇 중지 (Web API ``POST /api/bots/{bot_id}/stop``과 같은 동작)."""
    fmt = get_formatter(ctx)
    actor = get_member_id(ctx)

    async def _run_stop() -> dict:
        from ante.cli.commands.ipc_helpers import ipc_send

        return await ipc_send("bot.stop", {"bot_id": bot_id}, actor=actor)

    try:
        result = _run(_run_stop())
    except click.ClickException as e:
        code = getattr(e, "ipc_error_code", "") or "IPC_ERROR"
        message = getattr(e, "ipc_error_message", None) or e.message
        if fmt.is_json:
            fmt.error(message, code=code)
        else:
            text = f"{code}: {message}" if code else message
            fmt.error(text)
        raise SystemExit(1) from e

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
    """봇 live 상태 조회 (Web API ``GET /api/bots/{bot_id}``와 같은 동작)."""
    fmt = get_formatter(ctx)
    actor = get_member_id(ctx)

    async def _run_status() -> dict:
        from ante.cli.commands.ipc_helpers import ipc_send

        return await ipc_send("bot.status", {"bot_id": bot_id}, actor=actor)

    try:
        result = _run(_run_status())
    except click.ClickException as e:
        code = getattr(e, "ipc_error_code", "") or "IPC_ERROR"
        message = getattr(e, "ipc_error_message", None) or e.message
        if fmt.is_json:
            fmt.error(message, code=code)
        else:
            text = f"{code}: {message}" if code else message
            fmt.error(text)
        raise SystemExit(1) from e

    # status 출력 계약:
    # - JSON 모드: IPC result 그대로 (``BotDetailResponse``-equivalent
    #   ``{"bot": info}`` envelope). 보강된 strategy/budget/positions까지
    #   포함된다.
    # - text 모드: ``bot info`` 스타일 detail + optional sections
    #   (strategy_name/budget/positions). 의존성 부재로 키가 없으면
    #   해당 section을 생략한다(#1712 read-only 정렬).
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
