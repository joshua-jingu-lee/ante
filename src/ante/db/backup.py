from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

MAX_BACKUPS = 3


def backup_db(src_path: Path, version: str) -> Path:
    """sqlite3.backup()으로 안전한 DB 백업. 최근 MAX_BACKUPS개만 유지."""
    if not src_path.exists():
        raise FileNotFoundError(f"원본 DB 파일이 존재하지 않습니다: {src_path}")

    dst_path = src_path.parent / f"{src_path.name}.bak.v{version}"

    src_conn = sqlite3.connect(str(src_path))
    dst_conn = sqlite3.connect(str(dst_path))
    try:
        src_conn.backup(dst_conn)
    finally:
        dst_conn.close()
        src_conn.close()

    logger.info("DB 백업 완료: %s", dst_path)
    _cleanup_old_backups(src_path, keep=MAX_BACKUPS)
    return dst_path


def _cleanup_old_backups(src_path: Path, keep: int = MAX_BACKUPS) -> None:
    """오래된 백업 파일 삭제. 최신 keep개만 유지."""
    pattern = f"{src_path.name}.bak.v*"
    backups = sorted(src_path.parent.glob(pattern), key=lambda p: p.stat().st_mtime)
    for old in backups[:-keep]:
        old.unlink()
        logger.info("오래된 백업 삭제: %s", old)
