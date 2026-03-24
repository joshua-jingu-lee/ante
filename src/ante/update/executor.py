"""업데이트 실행기 — pip 업그레이드 및 마이그레이션."""

from __future__ import annotations

import logging
import subprocess
import sys

logger = logging.getLogger(__name__)


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
