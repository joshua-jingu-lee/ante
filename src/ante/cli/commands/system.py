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
    from pathlib import Path

    from ante.config import Config
    from ante.main import read_pid_file

    fmt = get_formatter(ctx)

    # Refs #1157: PID 조회는 명시적 ``Config`` 인스턴스로 한다. ``--config-dir``
    # (서브커맨드 또는 루트 ``ctx.obj["config_dir"]``)이 가리키는 디렉토리의
    # canonical PID 파일만 본다. 0-arg ``read_pid_file()``은 ``ANTE_CONFIG_DIR``
    # env 또는 default 폴백을 보므로, 다른 ``config_dir``로 실행 중인 server를
    # 누락해 중복 실행/IPC socket race를 일으킬 수 있다.
    if config_dir:
        resolver_config_dir: Path | None = Path(config_dir)
    else:
        root_config_dir = ctx.obj.get("config_dir") if ctx.obj else None
        resolver_config_dir = (
            root_config_dir if isinstance(root_config_dir, Path) else None
        )
        if resolver_config_dir is None and root_config_dir:
            resolver_config_dir = Path(root_config_dir)
    config = Config.load(config_dir=resolver_config_dir)

    # 이미 실행 중인지 확인
    existing_pid = read_pid_file(config)
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
        if fmt.is_json:
            # #1757: JSON 모드 — 부모 stdout 에는 ``fmt.success`` 가 출력한
            # 단일 JSON document 하나만 남아야 한다. 자식 프로세스
            # (``python -m ante.main``) 의 runtime logger 가 inherit 된 stdout
            # 으로 흘러 들면 자동화 호출자(ante-oracle host probe 등)가
            # ``json.loads`` 로 응답을 파싱하지 못한다 (A7
            # ``cli_system_start_json_stdout_contract`` probe). 자식 stdout/
            # stderr 를 부모 stderr 로 redirect 해 stdout 격리를 보존한다.
            proc = subprocess.run(cmd, env=env, stdout=sys.stderr, stderr=sys.stderr)
        else:
            # text 모드: 자식 stdout/stderr inherit (기존 동작 보존).
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
    from ante.config import Config
    from ante.main import _remove_pid_file, read_pid_file

    fmt = get_formatter(ctx)

    # Refs #1157: PID 경로는 `runtime.pid_path` resolver로 결정한다.
    # 같은 `config_dir`을 쓰는 server runtime/IPC client/cold-path guard와
    # 동일한 canonical 위치(`<config_dir>/run/ante.pid`)를 본다.
    config_dir = ctx.obj.get("config_dir") if ctx.obj else None
    config = Config.load(config_dir=config_dir)
    pid_path = config.runtime_pid_path()

    pid = read_pid_file(config)
    if pid is None:
        fmt.error(
            f"PID 파일이 없습니다 ({pid_path})",
            code="PID_NOT_FOUND",
        )
        raise SystemExit(1)

    if not _is_process_alive(pid):
        # 프로세스가 없으면 canonical + legacy ``db/ante.pid`` 양쪽 stale PID
        # 정리 (Refs #1157). ``read_pid_file``은 canonical만 보지만, cleanup은
        # transitional 환경의 legacy 잔여까지 best-effort로 unlink한다.
        _remove_pid_file(config)
        fmt.error(
            f"프로세스가 존재하지 않습니다 (pid={pid}). PID 파일을 정리했습니다.",
            code="PROCESS_NOT_FOUND",
        )
        raise SystemExit(1)

    os.kill(pid, signal.SIGTERM)
    fmt.success("종료 시그널 전송 완료", {"pid": pid})


async def _create_services():  # noqa: ANN202
    """오프라인 커맨드용 DB/EventBus 생성 헬퍼."""
    from ante.cli.main import get_db_path
    from ante.core.database import Database
    from ante.eventbus.bus import EventBus

    db = Database(get_db_path())
    await db.connect()
    eventbus = EventBus()
    return db, eventbus


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
    from ante.cli.commands.ipc_helpers import ipc_send

    fmt = get_formatter(ctx)
    actor = get_member_id(ctx)

    result = _run(ipc_send("system.halt", {"reason": reason}, actor=actor))
    data = result.get("data", result)
    count = data.get("accounts_changed", 0)
    fmt.success(f"시스템 HALTED — {count}개 계좌 거래 중지", data)


@system.command(name="clear-halt")
@click.option("--reason", default="", help="사유")
@click.pass_context
@require_auth
@require_scope("system:admin")
def clear_halt(ctx: click.Context, reason: str) -> None:
    """킬 스위치 해제 (전역 정지 해제 — 봇은 자동 재시작되지 않음)."""
    from ante.cli.commands.ipc_helpers import ipc_send

    fmt = get_formatter(ctx)
    actor = get_member_id(ctx)

    result = _run(ipc_send("system.clear_halt", {"reason": reason}, actor=actor))
    data = result.get("data", result)
    count = data.get("accounts_changed", 0)
    fmt.success(
        f"시스템 정지 해제 — {count}개 계좌 ACTIVE 복구 (봇은 자동 재시작되지 않음)",
        data,
    )
