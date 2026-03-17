"""체크포인트 저장 및 복원 모듈.

수집 중단/재개를 위한 내부 상태를 JSON으로 원자적으로 기록한다.
원자성 보장: 임시 파일에 쓴 후 rename (write-then-rename).
"""

from __future__ import annotations

import json
import logging
import tempfile
from datetime import UTC, datetime
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
        self._feed_dir = feed_dir
        self._source = source
        self._data_type = data_type
        self._checkpoint_dir = feed_dir / CHECKPOINT_DIR
        self._file_path = self._checkpoint_dir / f"{source}_{data_type}.json"

    @property
    def file_path(self) -> Path:
        """체크포인트 파일 경로를 반환한다."""
        return self._file_path

    def load(self) -> dict | None:
        """체크포인트를 로드한다.

        Returns:
            체크포인트 딕셔너리. 파일이 없으면 None.
        """
        if not self._file_path.exists():
            logger.debug(
                "체크포인트 파일 없음: %s",
                self._file_path,
            )
            return None

        try:
            data: dict = json.loads(self._file_path.read_text(encoding="utf-8"))
            logger.debug(
                "체크포인트 로드: source=%s, data_type=%s, last_date=%s",
                data.get("source"),
                data.get("data_type"),
                data.get("last_date"),
            )
            return data
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning(
                "체크포인트 파일 읽기 실패: %s (%s)",
                self._file_path,
                exc,
            )
            return None

    def save(self, last_date: str) -> None:
        """체크포인트를 원자적으로 저장한다.

        임시 파일에 쓴 후 rename하여 원자성을 보장한다.

        Args:
            last_date: 마지막으로 성공한 날짜 (YYYY-MM-DD).
        """
        self._checkpoint_dir.mkdir(parents=True, exist_ok=True)

        data = {
            "source": self._source,
            "data_type": self._data_type,
            "last_date": last_date,
            "updated_at": datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

        # write-then-rename 패턴으로 원자성 보장
        fd, tmp_path = tempfile.mkstemp(
            dir=self._checkpoint_dir,
            suffix=".tmp",
        )
        try:
            with open(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            Path(tmp_path).replace(self._file_path)
        except BaseException:
            # 실패 시 임시 파일 정리
            Path(tmp_path).unlink(missing_ok=True)
            raise

        logger.info(
            "체크포인트 저장: source=%s, data_type=%s, last_date=%s",
            self._source,
            self._data_type,
            last_date,
        )

    def get_last_date(self) -> str | None:
        """마지막 수집 날짜를 반환한다.

        Returns:
            마지막 수집 날짜 (YYYY-MM-DD). 체크포인트가 없으면 None.
        """
        checkpoint = self.load()
        if checkpoint is None:
            return None
        return checkpoint.get("last_date")
