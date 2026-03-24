"""업데이트 관련 CLI 명령 및 유틸리티."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import click

# pip 다운로드 등 임시 파일을 위한 최소 여유 공간
_MIN_FREE_MB = 100


def check_disk_space(db_path: Path) -> tuple[bool, str]:
    """디스크 여유 공간이 업데이트에 충분한지 확인한다.

    필요 공간 = DB 크기 × 2 (백업 + 임시) + 100 MB (pip 다운로드).
    DB 파일이 없으면 100 MB만 확인한다.

    Returns:
        (통과 여부, 안내 메시지) 튜플.
    """
    if db_path.exists():
        db_size = db_path.stat().st_size
        required = db_size * 2 + _MIN_FREE_MB * 1024 * 1024
    else:
        db_size = 0
        required = _MIN_FREE_MB * 1024 * 1024

    free = shutil.disk_usage(
        db_path.parent if db_path.parent.exists() else Path(".")
    ).free

    if free >= required:
        return True, ""

    required_mb = required / (1024 * 1024)
    free_mb = free / (1024 * 1024)
    return False, (
        f"디스크 공간 부족: 필요 {required_mb:.0f}MB, 여유 {free_mb:.0f}MB. "
        "불필요한 파일을 정리한 후 다시 시도하세요."
    )


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
def update(check: bool, target_version: str | None, yes: bool, force: bool) -> None:
    """ante를 최신 버전으로 업데이트합니다."""
    from ante.update.checker import (
        get_current_version,
        get_latest_version,
        is_update_available,
    )

    # 서버 실행 중 확인
    if check_server_running():
        if force:
            click.echo("서버를 중지합니다...")
            # TODO: graceful shutdown
        else:
            click.echo(
                "서버가 실행 중입니다. "
                "먼저 서버를 중지하거나 --force 옵션을 사용하세요.",
                err=True,
            )
            raise SystemExit(1)

    current = get_current_version()
    click.echo(f"현재 버전: {current}")

    if check:
        latest = get_latest_version()
        if latest is None:
            click.echo("PyPI 버전 확인 실패", err=True)
            raise SystemExit(1)
        if is_update_available(current, latest):
            click.echo(f"업데이트 가능: {current} → {latest}")
        else:
            click.echo("이미 최신 버전입니다")
        return

    # 업데이트 실행
    latest = target_version or get_latest_version()
    if latest is None:
        click.echo("PyPI 버전 확인 실패", err=True)
        raise SystemExit(1)

    if not target_version and not is_update_available(current, latest):
        click.echo("이미 최신 버전입니다")
        return

    # 디스크 공간 사전 검사
    db_path = Path("db/ante.db")
    ok, msg = check_disk_space(db_path)
    if not ok:
        click.echo(msg, err=True)
        raise SystemExit(1)

    if not yes:
        if not click.confirm(f"{current} → {latest}로 업데이트하시겠습니까?"):
            click.echo("업데이트를 취소했습니다")
            return

    # Phase A: 백업 + pip upgrade

    from ante.db.backup import backup_db
    from ante.update.executor import (
        pip_upgrade,
        rollback_update,
        run_post_update_migrations,
    )

    if db_path.exists():
        click.echo("DB 백업 중...")
        backup_db(db_path, current)

    click.echo(f"업데이트 중: {current} → {latest}...")
    if not pip_upgrade(target_version):
        click.echo("업데이트 실패", err=True)
        raise SystemExit(1)

    # Phase B: 마이그레이션
    click.echo("DB 마이그레이션 실행 중...")
    if not run_post_update_migrations():
        click.echo("마이그레이션 실패. 자동 롤백 시도 중...", err=True)
        backup_path = db_path.parent / f"{db_path.name}.bak.v{current}"
        if rollback_update(current, backup_path):
            click.echo(f"롤백 완료: {current}으로 복원됨")
        else:
            click.echo(
                f"자동 롤백 실패. 수동 복구 필요:\n"
                f"  pip install ante=={current}\n"
                f"  cp {backup_path} db/ante.db",
                err=True,
            )
        raise SystemExit(1)

    click.echo(f"업데이트 완료: {latest}")
