"""DataFeed 수집 결과 모델."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CollectionResult:
    """수집 작업의 집계 결과를 담는 데이터클래스.

    orchestrator가 ETL 루프 완료 후 생성하며,
    report/generator.py가 JSON 리포트로 변환한다.
    """

    mode: str
    """수집 모드 ('backfill' 또는 'daily')."""

    started_at: str
    """수집 시작 시각 (ISO 8601 UTC)."""

    finished_at: str
    """수집 완료 시각 (ISO 8601 UTC)."""

    duration_seconds: float
    """수집 소요 시간 (초)."""

    target_date: str | None = None
    """수집 대상 날짜 (daily 모드 시 사용, YYYY-MM-DD)."""

    symbols_total: int = 0
    """전체 처리 시도 종목 수."""

    symbols_success: int = 0
    """수집 성공 종목 수."""

    symbols_failed: int = 0
    """수집 실패 종목 수."""

    rows_written: int = 0
    """저장된 총 행 수."""

    data_types: list[str] = field(default_factory=list)
    """수집된 데이터 유형 목록 (예: ['ohlcv', 'fundamental'])."""

    failures: list[dict] = field(default_factory=list)
    """수집 실패 상세 목록."""

    warnings: list[dict] = field(default_factory=list)
    """데이터 품질 경고 목록."""

    config_errors: list[dict] = field(default_factory=list)
    """설정 오류 목록."""
