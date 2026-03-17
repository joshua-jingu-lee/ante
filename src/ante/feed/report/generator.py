"""수집 리포트 생성 모듈.

CollectionResult를 JSON 파일로 변환하여 .feed/reports/ 에 저장한다.
파일명 형식: {YYYY-MM-DD}-{mode}.json
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ante.feed.models.result import CollectionResult

logger = logging.getLogger(__name__)

REPORTS_DIR = "reports"


class ReportGenerator:
    """CollectionResult를 JSON 리포트 파일로 저장한다."""

    def __init__(self, feed_dir: Path) -> None:
        """ReportGenerator를 초기화한다.

        Args:
            feed_dir: .feed 디렉토리 경로.
        """
        ...

    def generate(self, result: CollectionResult) -> Path:
        """CollectionResult를 JSON 파일로 저장한다.

        파일명: {YYYY-MM-DD}-{mode}.json (started_at 기준)

        Args:
            result: 수집 결과 객체.

        Returns:
            저장된 리포트 파일 경로.
        """
        ...

    def list_reports(self, limit: int = 10) -> list[Path]:
        """최근 리포트 목록을 반환한다.

        Args:
            limit: 최대 반환 개수 (최신 순).

        Returns:
            리포트 파일 경로 목록.
        """
        ...
