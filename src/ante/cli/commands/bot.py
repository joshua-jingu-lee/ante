"""ante bot — 봇 생명주기 관리 커맨드."""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import TYPE_CHECKING

import click

from ante.account.scoping import is_invalid_account_id
from ante.cli._validators import (
    reject_invalid_account_id,
    validate_positive_finite_amount,
)
from ante.cli.cold_path import is_active_runtime
from ante.cli.db_context import open_cli_db
from ante.cli.formatter import format_option
from ante.cli.main import get_formatter
from ante.cli.middleware import get_member_id, require_auth, require_scope
from ante.contracts import emit_cli_error

if TYPE_CHECKING:
    from ante.account.service import AccountService
    from ante.bot.manager import BotManager
    from ante.core.database import Database
    from ante.eventbus.bus import EventBus

logger = logging.getLogger(__name__)


@click.group()
def bot() -> None:
    """봇 생성·시작·중지·조회."""


def _run(coro):  # noqa: ANN001, ANN202
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


async def _audit_log(db, **kwargs) -> None:  # noqa: ANN001
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
) -> dict:
    """서버 정지 상태에서 BotManager 없이 봇을 soft-delete한다.

    ``open_cli_db`` 기반 lifecycle. ``ctx`` 가 ``None`` 이면
    ``click.get_current_context`` 로 fallback 한다 (callsite 하위 호환).
    """
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

    # SQL filter **이전** ingress 검증.
    #
    # omitted-vs-provided 계약:
    #   - `--account` 미지정(`account_id is None`) → 전체 봇 반환 동작 **보존**
    #     (omitted 분기는 검증하지 않는다; 이게 불변이다).
    #   - `--account` provided(`default`/패턴 위반/`""` 포함) → invalid면
    #     SQL filter 이전에 `VALIDATION_ERROR` + exit 1로 거부. 기존
    #     `if account_id:` truthy 분기는 `""`를 falsy-skip해 전체 봇을
    #     반환했으나(provided-empty drift), provided-empty도 invalid로 거부한다.
    if account_id is not None:
        account_id = reject_invalid_account_id(account_id, fmt, context="cli.bot.list")

    async def _run_list() -> list[dict]:
        # ``_create_services`` async context manager lifecycle.
        # ``open_cli_db`` 가 normal/exception/cancellation 모든 경로에서
        # ``Database.close()`` 를 보장한다.
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
        # ``_create_services`` async context manager lifecycle.
        async with _create_services(ctx=ctx) as (db, _, _, _):
            row = await db.fetch_one("SELECT * FROM bots WHERE bot_id = ?", (bot_id,))
            return dict(row) if row else None

    result = _run(_run_info())

    if not result:
        # missing bot 은 안정 코드 ``BOT_NOT_FOUND`` 로 surface 해 자동화가
        # 메시지 파싱 없이 분류할 수 있도록 한다 (CLI/IPC 일관성:
        # ``BotNotFoundError.code = "BOT_NOT_FOUND"`` 와 동형).
        fmt.error(f"봇을 찾을 수 없습니다: {bot_id}", code="BOT_NOT_FOUND")
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
            # invalid --param 입력은 안정 코드
            # ``BOT_INVALID_PARAM`` 으로 surface 한다. 자동화/오라클이
            # 메시지 텍스트 파싱 없이 invalid-input 분류를 할 수 있게 한다.
            fmt.error(str(e), code="BOT_INVALID_PARAM")
            raise SystemExit(1) from e

    # defense-in-depth: provided invalid account_id (`default`/패턴 위반/`""`)
    # 를 omitted resolver / `ipc_send` (→`_handle_bot_create`) 이전에 거부한다.
    # IPC handler가 1차 보증(handler-first require_account_id)하지만, CLI
    # ingress 거부는 clean
    # early exit(traceback 부재)이다. **provided-only**(`account_id is not
    # None`)로만 검증해 `--account` 미지정(None) → 비대화형 resolver 분기를
    # **보존**한다(omitted 불변, `bot_list` 동형, invalid-format ↔
    # valid-absent/omitted 분리). 에러코드는 SSOT `VALIDATION_ERROR`.
    if account_id is not None:
        account_id = reject_invalid_account_id(
            account_id, fmt, context="cli.bot.create"
        )

    # 계좌 미지정 시 비대화형 resolver — 단일 active 계좌면 자동 선택,
    # 그 외(0개/2개 이상)에는 BOT_MISSING_REQUIRED_ACCOUNT로 실패한다.
    if account_id is None:
        from ante.account.models import AccountStatus

        # ``_create_services()`` 가 연 aiosqlite db 연결을 명시적으로
        # close 하지 않으면 ``_resolve_account_non_interactive`` 가 SystemExit
        # 을 raise 한 뒤 (active account 0 / 2+) leaked connection 이 asyncio
        # event loop 를 dangling 상태로 만들어 CLI 프로세스가 종료되지 않고
        # 외부 timeout (probe exit 124) 으로만 죽던 hang 회귀를 차단한다.
        # ``bot_list`` (L107-122) / ``bot_info`` (L149-154) 와 동형의 try/
        # finally + ``db.close()`` cleanup 을 적용한다. resolver 의 SystemExit
        # 은 ``_run(_list_accounts())`` 완료 후 (close 이후) 발생하므로 close
        # 가 항상 보장된다. JSON envelope code (``BOT_MISSING_REQUIRED_ACCOUNT``)
        # 는 종전 동작 그대로다 (이슈 본질은 process termination 보장).
        async def _list_accounts() -> list:
            # ``_create_services`` async context manager lifecycle.
            # cleanup invariant (resolver SystemExit 이후에도 db 가 close 되어
            # process termination 보장) 는 ``open_cli_db`` body close 가 그대로
            # 유지한다.
            async with _create_services(ctx=ctx) as (_, _, _, account_service):
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
        # emit_cli_error 가 registry-first (BotAlreadyExistsError /
        # BotStrategyAlreadyRunningError 등) → ``.code`` fallback →
        # ``EXECUTION_ERROR`` 순서로 public code 를 resolve 한다. IPC envelope
        # 와 동일 코드 surface — ``BotAlreadyExistsError.code = "BOT_ALREADY_EXISTS"``
        # 등 typed 동작은 그대로 유지된다.
        emit_cli_error(fmt, e)

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
        return await _run_bot_remove_cold_path(bot_id, ctx=ctx)

    try:
        result = _run(_run_remove())
    except click.ClickException:
        raise
    except Exception as e:
        # emit_cli_error 가 ``BotNotFoundError`` (cold-path 미존재 봇 거부)
        # 의 등록 spec ``BOT_NOT_FOUND`` 를 우선 surface 한다. registry miss
        # + ``.code`` 부재 시 ``EXECUTION_ERROR`` fallback.
        emit_cli_error(fmt, e)

    if result.get("removed"):
        suffix = "(cold-path)" if result.get("cold_path") else ""
        fmt.success(f"봇 삭제 완료{suffix}: {bot_id}", result)
    else:
        # removed=False sentinel 도 미존재 봇 의미이므로 ``BOT_NOT_FOUND``
        # 안정 코드를 명시 부여한다 (``bot info`` 형제 패턴 미러, IPC envelope
        # 와 동일 public code surface).
        fmt.error(f"봇을 찾을 수 없습니다: {bot_id}", code="BOT_NOT_FOUND")
        raise SystemExit(1)


@bot.command("signal-key")
@click.argument("bot_id")
@click.option("--rotate", is_flag=True, help="기존 키 폐기 + 새 키 발급")
@click.pass_context
@require_auth
@require_scope("bot:admin")
def bot_signal_key(ctx: click.Context, bot_id: str, rotate: bool) -> None:
    """봇 시그널 키 조회 또는 재발급.

    ``--rotate`` 는 runtime IPC (``bot.signal_key.rotate``) 전용이다 (#2111).
    서버가 정지되어 있으면 ``IPC_SERVER_NOT_RUNNING`` 으로 거부하며, cold-path
    DB mutation 으로 대체하지 않는다 (runtime 경계 / audit / live 상태 정합성
    보존). 조회(rotate 미지정)는 기존 cold-path 를 유지한다 (#2112 가 read IPC
    라우팅 소유).
    """
    fmt = get_formatter(ctx)

    if rotate:
        # ``--rotate`` 는 runtime IPC 전용 (#2111). ``BotManager.rotate_signal_key``
        # 가 존재 확인 (``BotNotFoundError`` → ``BOT_NOT_FOUND``) +
        # accepts_external_signals 게이트 (``BotNotAcceptingSignals`` →
        # ``BOT_NOT_ACCEPTING_SIGNALS``) + ``SignalKeyManager.rotate`` 위임을
        # 단일 chokepoint 로 수행한다. 서버 정지 시 ``ipc_send`` 가
        # ``IPC_SERVER_NOT_RUNNING`` ClickException 으로 surface 하며, cold-path
        # DB mutation 으로 fallback 하지 않는다.
        actor = get_member_id(ctx)

        async def _run_rotate() -> dict:
            from ante.cli.commands.ipc_helpers import ipc_send

            return await ipc_send(
                "bot.signal_key.rotate", {"bot_id": bot_id}, actor=actor
            )

        try:
            result = _run(_run_rotate())
        except click.ClickException as e:
            # ``bot start`` 형제 패턴 1:1 미러: ipc_send 가 부착한 원본
            # code/message 를 split 없이 복원해 text/JSON 공용 envelope
            # 안정성을 보존한다. 서버 정지(``IPC_SERVER_NOT_RUNNING``) /
            # 타임아웃(``IPC_TIMEOUT``) / server error envelope 모두 동일
            # 경로로 surface 되며, 직접 DB rotate 로 fallback 하지 않는다.
            code = getattr(e, "ipc_error_code", "") or "IPC_ERROR"
            message = getattr(e, "ipc_error_message", None) or e.message
            if fmt.is_json:
                fmt.error(message, code=code)
            else:
                text = f"{code}: {message}" if code else message
                fmt.error(text)
            raise SystemExit(1) from e

        # 출력 계약 보존 (#2111): rotate 성공은 IPC 라우팅으로 옮겼더라도
        # 기존 standard envelope (``{status, message, data}``, json/text 공통)
        # 을 그대로 유지한다. cli_registry signal-key 계약이 "``--rotate``
        # 경로는 ``fmt.success`` (standard)" 로 의도적·문서화·drift-test 된
        # mixed-branch 결정을 갖고 있으므로 raw passthrough 로 바꾸지 않는다.
        # passthrough 일관성 개선은 별도 명시적 follow-up 범위다.
        fmt.success(f"시그널 키 재발급 완료: {bot_id}", result)
        return

    async def _run_signal_key() -> dict:
        # ``_create_services`` async context manager lifecycle.
        from ante.bot.signal_key import SignalKeyManager

        async with _create_services(ctx=ctx) as (db, _, _, _):
            skm = SignalKeyManager(db)
            await skm.initialize()

            # 미존재 bot 에 대한 signal key 조회를 막기 위해 get_key 호출 전에
            # bot 존재를 먼저 확인한다. 미존재면 sentinel(``missing=True``)을
            # 반환한다. 형제 명령(`bot info`/`bot remove`/`bot positions`)과
            # 동일하게 code 없는 에러 + exit 1 로 거부한다.
            #
            # ``status != 'deleted'`` 조건은 ``BotManager.load_from_db``
            # (manager.py:212 ``FROM bots WHERE status != 'deleted'``)의
            # 운영 bot 정의와 정렬한다. ``bot remove`` 는 키 폐기 후
            # soft-delete (manager.py:826 ``UPDATE bots SET status =
            # 'deleted'``) 하므로 row 가 남는다 — 이를 운영상 미존재로
            # 취급한다.
            #
            # ``bots`` 테이블은 ``BotManager.initialize()`` 에서 생성되며
            # 위 ``_create_services()`` 가 이를 보장하지만, 방어적으로
            # malformed db 외의 "no such table" 은 미존재 bot 으로 정규화
            # 한다 (malformed db 같은 다른 ``OperationalError`` 까지
            # 삼키지 않도록 메시지로 좁힌다, 형제 패턴 동형).
            try:
                bot_row = await db.fetch_one(
                    "SELECT strategy_id FROM bots "
                    "WHERE bot_id = ? AND status != 'deleted'",
                    (bot_id,),
                )
            except sqlite3.OperationalError as e:
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

    try:
        result = _run(_run_signal_key())
    except Exception as e:
        # bot 존재확인 중 non-"no such table" ``OperationalError``
        # (malformed/locked DB 등)가 재던져지면 여기로 떨어진다. JSON error를
        # 출력하면서도 exit 0 으로 끝나면 자동화 호출자가 실패를 감지하지
        # 못하므로, 형제 ``bot remove`` (raise SystemExit(1) from e)와 동일하게
        # non-zero exit 로 종료한다.
        # emit_cli_error 가 ``EXECUTION_ERROR`` 안정 코드를 surface (registry
        # miss + ``.code`` 부재 fallback). 신규 도메인 에러코드 신설 없이
        # taxonomy 기본 fallback 으로 정렬.
        emit_cli_error(fmt, e)

    if result.get("missing"):
        # 미존재 bot 은 안정 코드 ``BOT_NOT_FOUND`` 로 surface 한다
        # (CLI/IPC 일관성: ``BotNotFoundError.code = "BOT_NOT_FOUND"`` 와
        # 동형). signal_key None 분기보다 먼저 처리하여 미존재 bot 이 "키
        # 없음" 으로 잘못 빠지지 않도록 한다.
        fmt.error(f"봇을 찾을 수 없습니다: {bot_id}", code="BOT_NOT_FOUND")
        ctx.exit(1)

    if result.get("signal_key") is None:
        # 시그널 키 미발급은 안정 코드 ``SIGNAL_KEY_NOT_SET`` 로 surface 한다.
        # 미존재 bot (``BOT_NOT_FOUND``) 분기보다 뒤에 둬서 두 의미를 envelope
        # 코드로 분리한다. typed exception 신설 대신 None gate + code 라벨로
        # 단순화한다 (BOT_NOT_FOUND 동형 — 본
        # surface 는 service exception 을 거치지 않는다).
        fmt.error(
            f"signal key가 설정되지 않았습니다: {bot_id}",
            code="SIGNAL_KEY_NOT_SET",
        )
        ctx.exit(1)

    # read (조회) 경로 출력. ``--rotate`` 는 위 IPC 전용 분기에서 이미 return
    # 되므로 여기 도달하는 result 는 항상 조회 결과다 (#2111: rotated 분기 제거).
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
        # ``open_cli_db`` 헬퍼가 service ``initialize()`` /
        # ``get_positions()`` 예외 / cancellation 모든 경로에서
        # ``Database.close()`` 1회 호출을 보장한다 (cleanup invariant).
        # ``--db-path`` override 는 ctx 의 ``get_db_path(ctx)`` resolution 으로
        # 흡수된다.
        from ante.trade.performance import PerformanceTracker
        from ante.trade.position import PositionHistory
        from ante.trade.recorder import TradeRecorder
        from ante.trade.service import TradeService

        async with open_cli_db(ctx) as db:
            # 미존재 bot 을 "실재 bot 의 0 포지션" 과 구분하기 위해 포지션 조회
            # 전에 bot 존재를 먼저 확인한다. 미존재면 sentinel ``None`` 을
            # 반환하고, 실재 bot 이면 (0개 포함) list 를 반환한다.
            #
            # ``bots`` 테이블은 ``BotManager.initialize()`` 에서만 생성되는데,
            # 이 경로는 raw ``Database`` 만 쓰고 ``BotManager`` 를 초기화하지
            # 않는다(예: ``ante init`` 직후). 테이블 자체가 없으면 정의상
            # 해당 bot_id 는 존재할 수 없으므로 미존재 bot 과 동일하게
            # 정규화한다(=sentinel ``None``). 단, malformed db 같은 다른
            # ``OperationalError`` 까지 삼키지 않도록 "no such table" 메시지
            # 일 때로만 좁힌다.
            try:
                bot_row = await db.fetch_one(
                    "SELECT account_id FROM bots WHERE bot_id = ?", (bot_id,)
                )
            except sqlite3.OperationalError as e:
                if "no such table" in str(e).lower():
                    return None
                raise
            if bot_row is None:
                return None

            # #2137: 봇 row 의 account_id 로 포지션 조회를 스코핑한다.
            # ``TradeService.get_positions(bot_id)`` 는 account_id 생략 시
            # all-account 조회로 동작해 같은 bot_id 의 타 계좌 stale/legacy
            # 포지션이 섞일 수 있다. invalid (None/""/"default"/형식 위반) 면
            # fail-closed 로 ``VALIDATION_ERROR`` (``raise SystemExit(1)``) 해
            # 빈 성공 응답(0 포지션과 구분 불가) 을 차단한다.
            account_id = bot_row["account_id"]
            if is_invalid_account_id(account_id):
                fmt.error(
                    f"봇의 account_id 가 유효하지 않아 포지션을 조회할 수 없습니다:"
                    f" {bot_id} (account_id={account_id!r})",
                    code="VALIDATION_ERROR",
                )
                raise SystemExit(1)

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

    result = _run(_run_positions())

    if result is None:
        # 미존재 bot 은 안정 코드 ``BOT_NOT_FOUND`` 로 surface 한다
        # (CLI/IPC 일관성: ``BotNotFoundError.code = "BOT_NOT_FOUND"`` 와
        # 동형, ``bot info`` / ``bot remove`` 형제 패턴 1:1 미러).
        fmt.error(f"봇을 찾을 수 없습니다: {bot_id}", code="BOT_NOT_FOUND")
        ctx.exit(1)

    if not result:
        # 실재 bot, 0 포지션: 기존 계약(exit 0 + "보유 포지션 없음") 유지.
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
        fmt.error(
            "변경할 필드를 하나 이상 지정하세요.",
            code="CLI_MISSING_REQUIRED_INPUT",
        )
        raise SystemExit(1)

    async def _run_update() -> dict:
        from ante.cli.commands.ipc_helpers import ipc_send

        return await ipc_send(
            "bot.update",
            {"bot_id": bot_id, "updates": updates},
            actor=actor,
        )

    try:
        result = _run(_run_update())
    except click.ClickException as e:
        code = getattr(e, "ipc_error_code", "") or "IPC_ERROR"
        message = getattr(e, "ipc_error_message", None) or e.message
        fmt.error(message, code=code)
        raise SystemExit(1) from e

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
        fmt.error(str(e), code="VALIDATION_ERROR")
        raise SystemExit(1) from e
    if since is not None and until is not None and since > until:
        fmt.error(
            f"시작일({from_date})이(가) 종료일({to_date}) 이후입니다.",
            code="INVALID_DATE_RANGE",
        )
        raise SystemExit(1)

    async def _run_logs() -> dict:
        # ``open_cli_db`` 헬퍼 lifecycle (cleanup invariant). ``--config-dir``
        # / ``ANTE_CONFIG_DIR`` 를 통한 ``get_db_path(ctx)`` resolution 동일.
        from ante.eventbus.history import EventHistoryStore

        async with open_cli_db(ctx) as db:
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
        fmt.error(f"봇을 찾을 수 없습니다: {bot_id}", code="BOT_NOT_FOUND")
        raise SystemExit(1)
    if fmt.is_json:
        fmt.output(result)
    elif not result["logs"]:
        click.echo("(logs 없음)")
    else:
        fmt.table(result["logs"], ["timestamp", "result", "message"])


# ── 봇 생명주기 leaf ─────────────────────────────────────────────────────
#
# ``bot.start``/``bot.stop``/``bot.status`` IPC handler가 ``BOT_NOT_FOUND`` /
# ``BOT_ACCOUNT_CREDENTIALS_NOT_CONFIGURED`` / ``BOT_STATE_CONFLICT`` coded
# exception을 raise한다. CLI ingress는 IPC 단일-chokepoint를 그대로 사용하며
# 별도 cold-path fallback을 제공하지 않는다. 에러 envelope 안정성은
# ``config set`` 패턴 (``ipc_send``가 ``ClickException``에 부착한
# ``ipc_error_code``/``ipc_error_message``를 split 없이 복원) 1:1 미러로
# 보존한다.


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

    async def _run_start() -> dict:
        from ante.cli.commands.ipc_helpers import ipc_send

        return await ipc_send("bot.start", {"bot_id": bot_id}, actor=actor)

    try:
        result = _run(_run_start())
    except click.ClickException as e:
        # ipc_send가 부착한 원본 code/message를 split 없이 복원해 text/JSON
        # 공용 envelope 안정성을 보존한다.
        code = getattr(e, "ipc_error_code", "") or "IPC_ERROR"
        message = getattr(e, "ipc_error_message", None) or e.message
        if fmt.is_json:
            fmt.error(message, code=code)
        else:
            text = f"{code}: {message}" if code else message
            fmt.error(text)
        raise SystemExit(1) from e

    # JSON 모드는 IPC `{bot: ...}` envelope 그대로 유지해 `bot status`와
    # 동일 shape를 제공한다. text 모드만 사용자 친화적 성공 메시지.
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
    """봇 live 상태 조회."""
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
    #   해당 section을 생략한다(read-only 정렬).
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
