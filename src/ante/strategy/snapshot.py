"""StrategySnapshot — 전략 파일 스냅샷 생성/정리."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

# strategies/.running/{bot_id}/ 하위에 스냅샷 저장
_RUNNING_DIR_NAME = ".running"


class StrategySnapshot:
    """전략 파일 스냅샷 관리.

    봇 시작 시 원본 전략 파일을 .running/{bot_id}/ 디렉토리에 복사하고,
    봇 종료 시 정리한다. 원본 파일 수정으로부터 실행 중 코드를 보호한다.
    """

    def __init__(self, strategies_dir: Path) -> None:
        self._strategies_dir = strategies_dir
        self._running_dir = strategies_dir / _RUNNING_DIR_NAME

    def create(self, bot_id: str, source_path: Path) -> Path:
        """전략 파일을 스냅샷 디렉토리에 복사.

        Args:
            bot_id: 봇 식별자
            source_path: 원본 전략 파일 경로

        Returns:
            스냅샷 파일 경로
        """
        bot_dir = self._running_dir / bot_id
        bot_dir.mkdir(parents=True, exist_ok=True)

        snapshot_path = bot_dir / source_path.name
        shutil.copy2(source_path, snapshot_path)

        logger.info("전략 스냅샷 생성: %s → %s", source_path, snapshot_path)
        return snapshot_path

    def cleanup(self, bot_id: str) -> None:
        """봇의 스냅샷 디렉토리 삭제."""
        bot_dir = self._running_dir / bot_id
        if bot_dir.exists():
            shutil.rmtree(bot_dir)
            logger.info("전략 스냅샷 정리: %s", bot_dir)

    def cleanup_all(self) -> int:
        """잔존 스냅샷 전체 정리. 시스템 시작 시 호출.

        Returns:
            정리된 봇 디렉토리 수
        """
        if not self._running_dir.exists():
            return 0

        count = 0
        for bot_dir in self._running_dir.iterdir():
            if bot_dir.is_dir():
                shutil.rmtree(bot_dir)
                logger.info("잔존 스냅샷 정리: %s", bot_dir)
                count += 1

        return count

    def get_snapshot_path(self, bot_id: str) -> Path | None:
        """봇의 스냅샷 파일 경로 반환. 없으면 None."""
        bot_dir = self._running_dir / bot_id
        if not bot_dir.exists():
            return None

        py_files = list(bot_dir.glob("*.py"))
        return py_files[0] if py_files else None
