"""체크포인트 저장 및 복원 모듈.

수집 중단/재개를 위한 내부 상태를 JSON으로 원자적으로 기록한다.
원자성 보장: 임시 파일에 쓴 후 rename (write-then-rename).
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

CHECKPOINT_DIR = "checkpoints"


class Checkpoint:
    """소스별 체크포인트를 관리한다.

    체크포인트 파일 형식:
    {
        "source": "data_go_kr",
        "data_type": "ohlcv",
        "last_date": "2024-06-15",
        "updated_at": "2026-03-17T01:23:45Z"
    }
    """

    def __init__(self, feed_dir: Path, source: str, data_type: str) -> None:
        """Checkpoint를 초기화한다.

        Args:
            feed_dir: .feed 디렉토리 경로.
            source: 소스 이름 (예: 'data_go_kr', 'dart').
            data_type: 데이터 유형 (예: 'ohlcv', 'fundamental').
        """
        ...

    def load(self) -> dict | None:
        """체크포인트를 로드한다.

        Returns:
            체크포인트 딕셔너리. 파일이 없으면 None.
        """
        ...

    def save(self, last_date: str) -> None:
        """체크포인트를 원자적으로 저장한다.

        임시 파일에 쓴 후 rename하여 원자성을 보장한다.

        Args:
            last_date: 마지막으로 성공한 날짜 (YYYY-MM-DD).
        """
        ...

    def get_last_date(self) -> str | None:
        """마지막 수집 날짜를 반환한다.

        Returns:
            마지막 수집 날짜 (YYYY-MM-DD). 체크포인트가 없으면 None.
        """
        ...
