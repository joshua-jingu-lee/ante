"""업데이트 실행기 — pip 업그레이드, 마이그레이션, 롤백.

DB 경로는 상위 레이어(`ante.cli.commands.update`)가 `get_db_path(ctx)`로
계산해 전달한다. 이 모듈은 더 이상 `db/ante.db` 같은 CWD 기준 하드코딩을
사용하지 않는다. 관련 배경: #1125 Codex 10차 review Finding 2.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def snapshot_dependencies(version: str, db_dir: Path | None = None) -> Path | None:
    """현재 pip freeze 결과를 파일로 저장한다.

    저장 경로: ``{db_dir}/pip_freeze_v{version}.txt``

    Args:
        version: 스냅샷 파일명에 박힐 현재 버전 문자열.
        db_dir: 스냅샷을 저장할 디렉터리. 호출자가 ``get_db_path(ctx)``로
            계산한 DB 파일 경로의 부모 디렉터리를 전달해야 한다. 과거
            기본값 ``Path("db")`` 는 CWD 의존이라 제거됐다. 하위 호환을
            위해 None 이 들어오면 ``Path("db")`` 폴백을 유지한다.

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


def run_post_update_migrations(
    db_path: str | None = None,
    *,
    data_path: str | None = None,
) -> bool:
    """신 코드로 DB 마이그레이션을 실행한다. 성공 시 True.

    Args:
        db_path: 마이그레이션을 적용할 DB 파일 경로. ``get_db_path(ctx)``
            결과를 넘기면 서브프로세스가 ANTE_DB_PATH 환경변수로 이를 읽고
            해당 DB 를 연다. None 이면 서브프로세스 쪽 fallback
            (`db/ante.db`)을 그대로 사용한다 (하위 호환).
        data_path: Parquet 데이터 트리 루트 경로. ``get_data_path(ctx)``
            결과를 넘기면 서브프로세스가 ANTE_DATA_PATH 환경변수로 이를
            읽고 v002 Parquet 마이그레이션을 해당 트리에 적용한다. None
            이면 서브프로세스 쪽 fallback(`data/`)을 그대로 사용한다 —
            custom config_dir / 사용자 지정 데이터 루트에서는 반드시
            전달해야 마이그레이션이 런타임과 동일한 트리를 본다
            (Refs #1125 Codex 13차 review Finding 1).
    """
    env = os.environ.copy()
    if db_path:
        env["ANTE_DB_PATH"] = db_path
    if data_path:
        env["ANTE_DATA_PATH"] = data_path
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "ante.db.migrations"],
        capture_output=True,
        text=True,
        env=env,
    )
    if result.returncode != 0:
        logger.error("마이그레이션 실패: %s", result.stderr)
        return False
    return True


def rollback_update(
    previous_version: str,
    backup_path: Path | None = None,
    db_path: str | None = None,
) -> bool:
    """업데이트 실패 시 롤백. pip 다운그레이드 + DB 복원.

    Args:
        previous_version: 이전 버전 문자열. pip install ante==<version> 으로 복귀.
        backup_path: 복원할 백업 파일 경로. None 이면 DB 복원은 스킵한다.
        db_path: 백업을 복사해 덮어쓸 실제 DB 파일 경로. ``get_db_path(ctx)``
            결과를 그대로 전달해야 한다. None 이면 과거 동작과 동일한
            ``db/ante.db`` 폴백을 사용한다 (하위 호환).
    """
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
        target = Path(db_path) if db_path else Path("db/ante.db")
        shutil.copy2(str(backup_path), str(target))
        logger.info("DB 복원 완료: %s → %s", backup_path, target)
    elif backup_path:
        logger.warning("백업 파일 없음: %s", backup_path)
        success = False

    return success
