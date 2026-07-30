"""수집 리포트 생성 모듈.

CollectionResult를 JSON 파일로 변환하여 .feed/reports/ 에 저장한다.
파일명 형식: {YYYY-MM-DDTHHMMSS}-{mode}.json (started_at의 초까지 포함, 콜론 제거).
동일 started_at(같은 초) rerun으로 파일명이 충돌하면 -1, -2 ... suffix를 붙여
기존 이력을 덮어쓰지 않는다(#2123).
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from ante.feed.models.result import CollectionResult

logger = logging.getLogger(__name__)

REPORTS_DIR = "reports"

# started_at parse 실패 시 정렬 후순위로 밀기 위한 sentinel(UTC aware).
_MIN_STARTED_AT = datetime.min.replace(tzinfo=UTC)


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
                # 총 실패 건수(날짜/소스 단위 비-심볼 실패 포함). symbols_failed는
                # 종목 귀속 실패만 세므로 symbols_failed=0이어도 >0일 수 있다(#2117).
                "failures_total": len(result.failures),
                # 경고는 type 버킷별로 유계 절단되므로(#2414) len(warnings)는
                # 총계가 아니다 — 전수 정확 집계를 result에서 그대로 읽는다.
                "warnings_total": result.warnings_total,
                "warnings_by_type": dict(result.warnings_by_type),
                "warnings_truncated": result.warnings_truncated,
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

        경로: {data_path}/.feed/reports/{YYYY-MM-DDTHHMMSS}-{mode}.json
        파일명의 타임스탬프는 report의 started_at에서 추출한다(초까지 포함,
        콜론은 fs-safe하게 제거). 같은 날 다른 시각의 rerun은 서로 다른 파일명을
        얻어 기존 리포트를 덮어쓰지 않는다(#2123).

        같은 초의 started_at으로 rerun되어 파일명이 이미 존재하면, ``-1``,
        ``-2`` ... 충돌 suffix를 붙여 어떤 기존 이력도 덮어쓰지 않는다(소실 0).

        Args:
            data_path: 데이터 루트 디렉토리.
            report: generate()가 반환한 리포트 dict.
            mode: 수집 모드 ('daily' 또는 'backfill').

        Returns:
            저장된 리포트 파일 경로.
        """
        started_at = report["started_at"]
        # ISO started_at(예: '2026-03-17T16:00:12Z')의 초까지(YYYY-MM-DDTHH:MM:SS)
        # 잘라 콜론을 제거 → '2026-03-17T160012' (fs-safe).
        timestamp = started_at[:19].replace(":", "")

        reports_dir = data_path / ".feed" / REPORTS_DIR
        reports_dir.mkdir(parents=True, exist_ok=True)

        file_path = reports_dir / f"{timestamp}-{mode}.json"
        # 같은 초 rerun으로 파일명이 겹치면 suffix를 붙여 덮어쓰기 방지.
        collision = 0
        while file_path.exists():
            collision += 1
            file_path = reports_dir / f"{timestamp}-{mode}-{collision}.json"

        file_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        logger.info("리포트 저장 완료: %s", file_path)
        return file_path

    def list_reports(self, limit: int = 10) -> list[Path]:
        """최근 리포트 목록을 반환한다.

        각 리포트 JSON의 ``started_at``을 datetime으로 파싱한 값을 기준으로
        내림차순(최신 우선) 정렬한다. 파일명(``{date}-{mode}.json``)은 같은
        날짜의 daily/backfill 순서를 사전식으로 오판하므로 정렬 키로 쓰지
        않는다(#2047).

        ``started_at`` 누락·파싱 실패·파일 읽기 실패 시 해당 파일은 목록에서
        제외하지 않고 정렬 키를 최소값으로 두어 뒤로 보낸다(전체 실패 방지).
        같은 ``started_at``끼리는 파일명 역순을 보조 키로 두어 안정 정렬한다.

        Args:
            limit: 최대 반환 개수 (최신 순).

        Returns:
            리포트 파일 경로 목록 (최신 N개).
        """
        reports_dir = self._feed_dir / REPORTS_DIR
        if not reports_dir.exists():
            return []

        files = list(reports_dir.glob("*.json"))
        # started_at 내림차순, tie는 파일명 역순(둘 다 reverse=True와 정합).
        files.sort(
            key=lambda path: (self._started_at_key(path), path.name),
            reverse=True,
        )
        return files[:limit]

    def _started_at_key(self, path: Path) -> datetime:
        """정렬용 ``started_at`` datetime(UTC aware)을 반환한다.

        읽기/파싱 실패 또는 ``started_at`` 누락 시 ``_MIN_STARTED_AT``을
        반환하여 해당 리포트를 후순위로 밀고, 예외는 삼키되 debug 로그로 남긴다.
        """
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            started_at = raw.get("started_at") if isinstance(raw, dict) else None
            if not isinstance(started_at, str):
                logger.debug("리포트 started_at 누락/비문자열: %s", path)
                return _MIN_STARTED_AT
            parsed = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            return parsed
        except (OSError, json.JSONDecodeError, ValueError, TypeError) as exc:
            logger.debug("리포트 started_at 파싱 실패: %s (%s)", path, exc)
            return _MIN_STARTED_AT
