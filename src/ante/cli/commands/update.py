"""업데이트 관련 CLI 명령 및 유틸리티."""

from __future__ import annotations

import os

import click

from ante.cli.formatter import format_option
from ante.cli.main import get_formatter


def check_server_running() -> bool:
    """서버가 실행 중인지 PID 파일로 확인. stale PID는 무시."""
    from ante.main import read_pid_file

    pid = read_pid_file()
    if pid is None:
        return False
    try:
        os.kill(pid, 0)  # 프로세스 존재 확인
        return True
    except (ProcessLookupError, PermissionError):
        return False


@click.command()
@click.option("--check", is_flag=True, help="업데이트 가능 여부만 확인")
@click.option(
    "--version", "target_version", default=None, help="특정 버전으로 업데이트"
)
@click.option("--yes", "-y", is_flag=True, help="확인 프롬프트 건너뛰기")
@click.option("--force", is_flag=True, help="서버 실행 중이면 자동 중지")
@format_option
@click.pass_context
def update(
    ctx: click.Context,
    check: bool,
    target_version: str | None,
    yes: bool,
    force: bool,
) -> None:
    """ante를 최신 버전으로 업데이트합니다."""
    from ante.update.checker import (
        get_current_version,
        get_latest_version,
        is_update_available,
    )

    fmt = get_formatter(ctx)

    # 서버 실행 중 확인
    if check_server_running():
        if force:
            if fmt.is_json:
                pass  # JSON 모드에서는 중간 메시지 생략
            else:
                click.echo("서버를 중지합니다...")
            # TODO: graceful shutdown
        else:
            fmt.error(
                "서버가 실행 중입니다. "
                "먼저 서버를 중지하거나 --force 옵션을 사용하세요."
            )
            raise SystemExit(1)

    current = get_current_version()
    if not fmt.is_json:
        click.echo(f"현재 버전: {current}")

    if check:
        latest = get_latest_version()
        if latest is None:
            fmt.error("PyPI 버전 확인 실패")
            raise SystemExit(1)
        available = is_update_available(current, latest)
        if fmt.is_json:
            fmt.output(
                {
                    "current_version": current,
                    "latest_version": latest,
                    "update_available": available,
                }
            )
        elif available:
            click.echo(f"업데이트 가능: {current} → {latest}")
        else:
            click.echo("이미 최신 버전입니다")
        return

    # 업데이트 실행
    latest = target_version or get_latest_version()
    if latest is None:
        fmt.error("PyPI 버전 확인 실패")
        raise SystemExit(1)

    if not target_version and not is_update_available(current, latest):
        if fmt.is_json:
            fmt.output(
                {
                    "current_version": current,
                    "latest_version": latest,
                    "update_available": False,
                }
            )
        else:
            click.echo("이미 최신 버전입니다")
        return

    if not yes:
        if not click.confirm(f"{current} → {latest}로 업데이트하시겠습니까?"):
            click.echo("업데이트를 취소했습니다")
            return

    # Phase A: 백업 + pip upgrade
    from pathlib import Path

    from ante.db.backup import backup_db
    from ante.update.executor import (
        pip_upgrade,
        rollback_update,
        run_post_update_migrations,
    )

    db_path = Path("db/ante.db")
    if db_path.exists():
        if not fmt.is_json:
            click.echo("DB 백업 중...")
        backup_db(db_path, current)

    if not fmt.is_json:
        click.echo(f"업데이트 중: {current} → {latest}...")
    if not pip_upgrade(target_version):
        fmt.error("업데이트 실패")
        raise SystemExit(1)

    # Phase B: 마이그레이션
    if not fmt.is_json:
        click.echo("DB 마이그레이션 실행 중...")
    if not run_post_update_migrations():
        if not fmt.is_json:
            click.echo("마이그레이션 실패. 자동 롤백 시도 중...", err=True)
        backup_path = db_path.parent / f"{db_path.name}.bak.v{current}"
        if rollback_update(current, backup_path):
            if fmt.is_json:
                fmt.error("마이그레이션 실패. 롤백 완료.", code="migration_failed")
            else:
                click.echo(f"롤백 완료: {current}으로 복원됨")
        else:
            if fmt.is_json:
                fmt.error("마이그레이션 실패. 자동 롤백 실패.", code="rollback_failed")
            else:
                click.echo(
                    f"자동 롤백 실패. 수동 복구 필요:\n"
                    f"  pip install ante=={current}\n"
                    f"  cp {backup_path} db/ante.db",
                    err=True,
                )
        raise SystemExit(1)

    if fmt.is_json:
        fmt.success(
            "업데이트 완료",
            {
                "previous_version": current,
                "current_version": latest,
            },
        )
    else:
        click.echo(f"업데이트 완료: {latest}")
