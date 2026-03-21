"""ante system — 시스템 제어 커맨드."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import subprocess
import sys

import click

from ante.cli.formatter import format_option
from ante.cli.main import get_formatter
from ante.cli.middleware import get_member_id, require_auth, require_scope

logger = logging.getLogger(__name__)


@click.group()
def system() -> None:
    """시스템 시작·중지·상태 확인."""


def _run(coro):  # noqa: ANN001, ANN202
    return asyncio.run(coro)


async def _create_services():  # noqa: ANN202
    from ante.core.database import Database
    from ante.eventbus.bus import EventBus

    db = Database("db/ante.db")
    await db.connect()
    eventbus = EventBus()
    return db, eventbus


async def _audit_log(db, **kwargs) -> None:  # noqa: ANN001
    """감사 로그 기록 (실패해도 주 동작에 영향 없음)."""
    try:
        from ante.audit import AuditLogger

        al = AuditLogger(db=db)
        await al.initialize()
        await al.log(**kwargs)
    except Exception as e:
        logger.warning("감사 로그 기록 실패: %s", e)


def _is_process_alive(pid: int) -> bool:
    """프로세스가 살아있는지 확인."""
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


@system.command()
@click.option(
    "--config-dir",
    "config_dir",
    type=click.Path(exists=False),
    default=None,
    help="설정 디렉토리 경로",
)
@click.pass_context
@require_auth
@require_scope("system:admin")
def start(ctx: click.Context, config_dir: str | None) -> None:
    """시스템 시작 (포어그라운드)."""
    from ante.main import read_pid_file

    fmt = get_formatter(ctx)

    # 이미 실행 중인지 확인
    existing_pid = read_pid_file()
    if existing_pid is not None and _is_process_alive(existing_pid):
        fmt.error(
            f"시스템이 이미 실행 중입니다 (pid={existing_pid})", code="ALREADY_RUNNING"
        )
        raise SystemExit(1)

    # python -m ante.main 실행
    cmd = [sys.executable, "-m", "ante.main"]

    env = os.environ.copy()
    if config_dir:
        env["ANTE_CONFIG_DIR"] = config_dir
    # 루트 컨텍스트에서 --config-dir이 설정된 경우 전달
    root_config_dir = ctx.obj.get("config_dir")
    if root_config_dir and not config_dir:
        env["ANTE_CONFIG_DIR"] = str(root_config_dir)

    fmt.success("시스템 시작 중...")

    try:
        proc = subprocess.run(cmd, env=env)
        raise SystemExit(proc.returncode)
    except KeyboardInterrupt:
        raise SystemExit(0)


@system.command()
@click.pass_context
@require_auth
@require_scope("system:admin")
def stop(ctx: click.Context) -> None:
    """시스템 정상 종료 (SIGTERM)."""
    from ante.main import PID_FILE, read_pid_file

    fmt = get_formatter(ctx)

    pid = read_pid_file()
    if pid is None:
        fmt.error(
            f"PID 파일이 없습니다 ({PID_FILE})",
            code="PID_NOT_FOUND",
        )
        raise SystemExit(1)

    if not _is_process_alive(pid):
        # 프로세스가 없으면 stale PID 파일 정리
        PID_FILE.unlink(missing_ok=True)
        fmt.error(
            f"프로세스가 존재하지 않습니다 (pid={pid}). PID 파일을 정리했습니다.",
            code="PROCESS_NOT_FOUND",
        )
        raise SystemExit(1)

    os.kill(pid, signal.SIGTERM)
    fmt.success("종료 시그널 전송 완료", {"pid": pid})


@system.command()
@format_option
@click.pass_context
@require_auth
@require_scope("system:read")
def status(ctx: click.Context) -> None:
    """시스템 상태 표시."""
    fmt = get_formatter(ctx)

    async def _run_status() -> dict:
        from ante.account.service import AccountService

        db, eventbus = await _create_services()
        try:
            account_service = AccountService(db=db, eventbus=eventbus)
            await account_service.initialize()

            from ante.account.models import AccountStatus

            accounts = await account_service.list()
            suspended = [a for a in accounts if a.status == AccountStatus.SUSPENDED]

            # 봇 수 조회
            row = await db.fetch_one("SELECT count(*) as cnt FROM bots")
            bot_count = row["cnt"] if row else 0

            return {
                "trading_state": "suspended" if suspended else "active",
                "bot_count": bot_count,
            }
        finally:
            await db.close()

    result = _run(_run_status())

    if fmt.is_json:
        fmt.output(result)
    else:
        click.echo(f"  거래 상태  : {result['trading_state']}")
        click.echo(f"  봇 수     : {result['bot_count']}")


@system.command()
@click.option("--reason", default="", help="사유")
@click.pass_context
@require_auth
@require_scope("system:admin")
def halt(ctx: click.Context, reason: str) -> None:
    """킬 스위치 발동 (전체 거래 중지)."""
    fmt = get_formatter(ctx)
    actor = get_member_id(ctx)

    async def _run_halt() -> dict:
        from ante.account.service import AccountService

        db, eventbus = await _create_services()
        try:
            account_service = AccountService(db=db, eventbus=eventbus)
            await account_service.initialize()
            count = await account_service.suspend_all(reason=reason, suspended_by=actor)

            await _audit_log(
                db,
                member_id=actor,
                action="system.halt",
                resource="system:kill_switch",
                detail=reason,
            )

            return {"suspended_count": count}
        finally:
            await db.close()

    result = _run(_run_halt())
    fmt.success(f"시스템 HALTED — {result['suspended_count']}개 계좌 거래 중지", result)


@system.command()
@click.option("--reason", default="", help="사유")
@click.pass_context
@require_auth
@require_scope("system:admin")
def activate(ctx: click.Context, reason: str) -> None:
    """킬 스위치 해제 (거래 재개)."""
    fmt = get_formatter(ctx)
    actor = get_member_id(ctx)

    async def _run_activate() -> dict:
        from ante.account.service import AccountService

        db, eventbus = await _create_services()
        try:
            account_service = AccountService(db=db, eventbus=eventbus)
            await account_service.initialize()
            count = await account_service.activate_all(activated_by=actor)

            await _audit_log(
                db,
                member_id=actor,
                action="system.activate",
                resource="system:kill_switch",
                detail=reason,
            )

            return {"activated_count": count}
        finally:
            await db.close()

    result = _run(_run_activate())
    fmt.success(f"시스템 ACTIVE — {result['activated_count']}개 계좌 거래 재개", result)
