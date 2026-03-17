"""수집 리포트 생성 모듈.

CollectionResult를 JSON 파일로 변환하여 .feed/reports/ 에 저장한다.
파일명 형식: {YYYY-MM-DD}-{mode}.json
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

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
        self._feed_dir = feed_dir

    def generate(self, result: CollectionResult) -> dict:
        """CollectionResult를 리포트 dict로 변환한다.

        Args:
            result: 수집 결과 객체.

        Returns:
            리포트 JSON 구조를 담은 dict.
        """
        report: dict = {
            "mode": result.mode,
            "started_at": result.started_at,
            "finished_at": result.finished_at,
            "duration_seconds": result.duration_seconds,
            "target_date": result.target_date,
            "summary": {
                "symbols_total": result.symbols_total,
                "symbols_success": result.symbols_success,
                "symbols_failed": result.symbols_failed,
                "rows_written": result.rows_written,
                "data_types": list(result.data_types),
            },
            "failures": list(result.failures),
            "warnings": list(result.warnings),
            "config_errors": list(result.config_errors),
        }
        return report

    def save(self, data_path: Path, report: dict, mode: str) -> Path:
        """리포트를 JSON 파일로 저장한다.

        경로: {data_path}/.feed/reports/{YYYY-MM-DD}-{mode}.json
        날짜는 report의 started_at에서 추출한다.

        Args:
            data_path: 데이터 루트 디렉토리.
            report: generate()가 반환한 리포트 dict.
            mode: 수집 모드 ('daily' 또는 'backfill').

        Returns:
            저장된 리포트 파일 경로.
        """
        started_at = report["started_at"]
        date_str = started_at[:10]

        reports_dir = data_path / ".feed" / REPORTS_DIR
        reports_dir.mkdir(parents=True, exist_ok=True)

        filename = f"{date_str}-{mode}.json"
        file_path = reports_dir / filename

        file_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        logger.info("리포트 저장 완료: %s", file_path)
        return file_path

    def list_reports(self, limit: int = 10) -> list[Path]:
        """최근 리포트 목록을 반환한다.

        Args:
            limit: 최대 반환 개수 (최신 순).

        Returns:
            리포트 파일 경로 목록.
        """
        reports_dir = self._feed_dir / REPORTS_DIR
        if not reports_dir.exists():
            return []

        files = sorted(reports_dir.glob("*.json"), reverse=True)
        return files[:limit]
