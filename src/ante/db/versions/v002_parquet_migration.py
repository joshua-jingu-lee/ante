"""Parquet 데이터 파일 경로 마이그레이션.

기존 exchange 없는 Parquet 경로를 KRX/ 하위로 이동한다.
DB 마이그레이션은 no-op이며, data_path가 전달되면 Parquet 경로 마이그레이션을 수행한다.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ante.core.database import Database

logger = logging.getLogger(__name__)


async def migrate(db: Database, *, data_path: Path | None = None) -> None:
    """Parquet 경로 마이그레이션.

    Args:
        db: Database 인스턴스 (schema_version 기록용).
        data_path: 데이터 저장소 루트 경로. None이면 Parquet 마이그레이션을 건너뛴다.
    """
    if data_path is None:
        logger.info("data_path 미지정 — Parquet 마이그레이션 건너뜀")
        return

    from ante.data.store import migrate_parquet_paths

    moved = migrate_parquet_paths(data_path)
    if moved:
        logger.info("Parquet 경로 마이그레이션 완료: %d개 이동", moved)
    else:
        logger.debug("Parquet 경로 마이그레이션: 변경 없음")
