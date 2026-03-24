"""업데이트 실행기 — pip 업그레이드, 마이그레이션, 롤백."""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def snapshot_dependencies(version: str, db_dir: Path | None = None) -> Path | None:
    """현재 pip freeze 결과를 파일로 저장한다.

    저장 경로: ``{db_dir}/pip_freeze_v{version}.txt``

    Returns:
        저장된 파일의 Path. 실패 시 None.
    """
    if db_dir is None:
        db_dir = Path("db")
    db_dir.mkdir(parents=True, exist_ok=True)

    result = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "pip", "freeze"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        logger.error("pip freeze 실패: %s", result.stderr)
        return None

    snapshot_path = db_dir / f"pip_freeze_v{version}.txt"
    snapshot_path.write_text(result.stdout, encoding="utf-8")
    logger.info("의존성 스냅샷 저장: %s", snapshot_path)
    return snapshot_path


def pip_upgrade(version: str | None = None) -> bool:
    """pip으로 ante 패키지를 업그레이드한다. 성공 시 True."""
    cmd = [sys.executable, "-m", "pip", "install", "--upgrade"]
    if version:
        cmd.append(f"ante=={version}")
    else:
        cmd.append("ante")
    result = subprocess.run(cmd, capture_output=True, text=True)  # noqa: S603
    if result.returncode != 0:
        logger.error("pip upgrade 실패: %s", result.stderr)
        return False
    return True


def run_post_update_migrations() -> bool:
    """신 코드로 DB 마이그레이션을 실행한다. 성공 시 True."""
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "ante.db.migrations"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        logger.error("마이그레이션 실패: %s", result.stderr)
        return False
    return True


def rollback_update(previous_version: str, backup_path: Path | None = None) -> bool:
    """업데이트 실패 시 롤백. pip 다운그레이드 + DB 복원."""
    success = True

    # pip 다운그레이드
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "pip", "install", f"ante=={previous_version}"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        logger.error("pip 롤백 실패: %s", result.stderr)
        success = False

    # DB 복원
    if backup_path and backup_path.exists():
        db_path = Path("db/ante.db")
        shutil.copy2(str(backup_path), str(db_path))
        logger.info("DB 복원 완료: %s → %s", backup_path, db_path)
    elif backup_path:
        logger.warning("백업 파일 없음: %s", backup_path)
        success = False

    return success
