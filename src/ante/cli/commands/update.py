"""업데이트 관련 CLI 명령 및 유틸리티."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import click

from ante.cli.formatter import format_option
from ante.cli.main import get_formatter

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
    """서버가 실행 중인지 PID 파일로 확인. stale PID는 무시.

    Refs #1157: ``--config-dir``로 가리킨 디렉토리의 canonical PID 파일만 본다.
    명시적으로 ``Config.load(config_dir=get_config_dir())``로 인스턴스를 만들어
    ``read_pid_file(config)``에 전달한다 — 0-arg ``read_pid_file()``은
    ``ANTE_CONFIG_DIR`` env/default 폴백을 보므로, 다른 ``config_dir``로 실행 중인
    server runtime을 누락해 update를 server 실행 중에 진행하는 위험이 있다.
    """
    from ante.cli.main import get_config_dir
    from ante.config import Config
    from ante.main import read_pid_file

    config = Config.load(config_dir=get_config_dir())
    pid = read_pid_file(config)
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
@click.option(
    "--yes",
    "-y",
    is_flag=True,
    help="실제 업데이트 실행 확인 (위험 명령). 누락 시 prompt 없이 에러로 실패",
)
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
    """ante를 최신 버전으로 업데이트합니다.

    `--check`은 PyPI 버전 조회만 수행한다 (`--yes` 불필요).
    `--check`이 아닌 실제 업데이트 실행은 `--yes`가 반드시 필요하며,
    누락 시 prompt 없이 ``CLI_CONFIRMATION_REQUIRED`` 에러로 종료한다.
    `--yes` 게이트는 PyPI 조회 **앞에** 평가하므로, 네트워크 느림/실패
    환경에서도 `--yes` 누락 호출은 PyPI 실패가 아닌 동일한 구조화 에러
    코드로 거절된다.
    """
    from ante.update.checker import (
        get_current_version,
        get_latest_version,
        is_update_available,
    )

    fmt = get_formatter(ctx)

    # 서버 실행 중 확인
    if check_server_running():
        if force:
            if not fmt.is_json:
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

    # 비대화형 입력 계약 (#1170, #1171 SSOT): `--check`이 아닌 실제 업데이트
    # 실행 호출에는 `--yes`가 반드시 필요하다. 이 게이트는 PyPI 조회
    # (`get_latest_version()`) **앞에** 위치해야 한다 — 그래야 네트워크
    # 느림/실패 환경에서도 `--yes` 누락 호출이 PyPI 실패가 아닌
    # ``CLI_CONFIRMATION_REQUIRED``로 거절된다 (Codex P2 finding 2차).
    # 자동화는 네트워크 상태와 무관하게 동일한 구조화 에러 코드를 받는다.
    # 게이트 통과 전이므로 PyPI 조회/backup/pip upgrade/migration 등
    # 부수 효과는 일체 발생하지 않는다.
    if not yes:
        fmt.error(
            f"업데이트 실행에는 --yes가 필요합니다 (현재 {current}). "
            "재실행: ante update --yes",
            code="CLI_CONFIRMATION_REQUIRED",
        )
        raise SystemExit(1)

    # 업데이트 실행 — `--yes` 게이트 통과 후에만 PyPI를 조회한다.
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

    # 디스크 공간 사전 검사
    from ante.cli.main import get_data_path, get_db_path

    db_path = Path(get_db_path(ctx))
    # 마이그레이션 서브프로세스에 넘길 데이터 루트.
    # 런타임이 `data.path` 로 보는 경로와 동일해야 v002 Parquet 마이그레이션이
    # 실제 데이터 트리에 적용된다 (Refs #1125 Codex 13차 review Finding 1).
    data_path = get_data_path(ctx)
    ok, msg = check_disk_space(db_path)
    if not ok:
        click.echo(msg, err=True)
        raise SystemExit(1)

    # Phase A: 백업 + pip upgrade

    from ante.db.backup import backup_db
    from ante.update.executor import (
        pip_upgrade,
        rollback_update,
        run_post_update_migrations,
        snapshot_dependencies,
    )

    if db_path.exists():
        if not fmt.is_json:
            click.echo("DB 백업 중...")
        backup_db(db_path, current)

    # 의존성 스냅샷 저장 — 스냅샷은 DB 디렉터리 옆에 저장해 백업과 위치를
    # 통일한다. `get_db_path(ctx)` 결과의 부모 디렉터리를 그대로 전달해
    # 과거 `./db` CWD 폴백이 남기던 유령 파일을 없앤다 (Refs #1125).
    if not fmt.is_json:
        click.echo("의존성 스냅샷 저장 중...")
    snapshot_path = snapshot_dependencies(current, db_dir=db_path.parent)
    if snapshot_path:
        if not fmt.is_json:
            click.echo(f"스냅샷 저장 완료: {snapshot_path}")
    else:
        if not fmt.is_json:
            click.echo("의존성 스냅샷 저장 실패 (계속 진행)", err=True)

    if not fmt.is_json:
        click.echo(f"업데이트 중: {current} → {latest}...")
    if not pip_upgrade(target_version):
        fmt.error("업데이트 실패")
        raise SystemExit(1)

    # Phase B: 마이그레이션 — executor 가 서브프로세스로 `python -m
    # ante.db.migrations` 를 호출한다. config_dir 로 계산한 DB 경로와
    # `data.path` 로 계산한 데이터 루트를 환경변수로 함께 전달해, 서브프로세스가
    # 런타임과 동일한 DB·데이터 트리에 마이그레이션을 적용한다.
    if not fmt.is_json:
        click.echo("DB 마이그레이션 실행 중...")
    if not run_post_update_migrations(str(db_path), data_path=data_path):
        if not fmt.is_json:
            click.echo("마이그레이션 실패. 자동 롤백 시도 중...", err=True)
        backup_path = db_path.parent / f"{db_path.name}.bak.v{current}"
        if rollback_update(current, backup_path, str(db_path)):
            if fmt.is_json:
                fmt.error("마이그레이션 실패. 롤백 완료.", code="migration_failed")
            else:
                click.echo(f"롤백 완료: {current}으로 복원됨")
                if snapshot_path:
                    click.echo(f"의존성 복원: pip install -r {snapshot_path}")
        else:
            restore_hint = f"  pip install ante=={current}"
            if snapshot_path:
                restore_hint += f"\n  pip install -r {snapshot_path}"
            if fmt.is_json:
                fmt.error("마이그레이션 실패. 자동 롤백 실패.", code="rollback_failed")
            else:
                click.echo(
                    f"자동 롤백 실패. 수동 복구 필요:\n"
                    f"{restore_hint}\n"
                    f"  cp {backup_path} {db_path}",
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
