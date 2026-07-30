"""DataFeed 수집 결과 모델."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ValidationResult:
    """4계층 데이터 검증 결과를 담는 데이터클래스.

    각 검증 계층(전송/구문/스키마/비즈니스)이 생성하며,
    경고와 오류를 분리하여 보고한다.
    """

    passed: bool
    """검증 통과 여부. errors가 비어있으면 True."""

    warnings: list[str] = field(default_factory=list)
    """경고 메시지 목록 (비즈니스 규칙 위반 등, 저장은 허용)."""

    errors: list[str] = field(default_factory=list)
    """오류 메시지 목록 (스키마 위반 등, 저장 불가)."""

    def merge(self, other: ValidationResult) -> ValidationResult:
        """다른 ValidationResult를 병합하여 새 결과를 반환한다.

        Args:
            other: 병합할 검증 결과.

        Returns:
            병합된 검증 결과. errors가 하나라도 있으면 passed=False.
        """
        merged_warnings = self.warnings + other.warnings
        merged_errors = self.errors + other.errors
        return ValidationResult(
            passed=len(merged_errors) == 0,
            warnings=merged_warnings,
            errors=merged_errors,
        )


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
    """**net-new 저장 행 수** (#1993).

    store에 실제로 새로 저장된 행 수의 합이다. 입력 len 누적이 아니라 파티션별
    ``max(0, len(merged) - len(existing))`` delta의 합이므로, 재수집/dedup/
    지표 in-place overwrite는 0으로 집계된다(과대계상 제거)."""

    data_types: list[str] = field(default_factory=list)
    """수집된 데이터 유형 목록 (예: ['ohlcv', 'fundamental'])."""

    failures: list[dict] = field(default_factory=list)
    """수집 실패 상세 목록."""

    warnings: list[dict] = field(default_factory=list)
    """데이터 품질 경고 **샘플** (#2414).

    실행 전체 누적이 아니라 경고 ``type`` 버킷별로 유계 절단된 샘플이다
    (다년 backfill이 행 단위 경고를 상한 없이 누적해 메모리를 소진시켰다).
    **총 건수는 반드시 ``warnings_total`` 로 읽는다** — ``len(warnings)`` 는
    절단이 발생하면 총계가 아니라 보존 샘플 수이며 축소 보고가 된다."""

    warnings_total: int = 0
    """**전수 정확** 경고 총 건수 (절단 무관, #2414)."""

    warnings_by_type: dict[str, int] = field(default_factory=dict)
    """경고 ``type`` 버킷별 **전수 정확** 건수 (`{버킷: 건수}`, #2414).

    ``type`` 키가 없는 경고는 ``"untyped"`` 버킷으로 정규화되어 집계된다."""

    warnings_truncated: bool = False
    """``warnings`` 샘플이 버킷 상한으로 절단되었는지 여부 (#2414).

    True이면 절단된 상세는 로그에서 회수한다(경고는 발생 시점에 전건 로깅)."""

    config_errors: list[dict] = field(default_factory=list)
    """설정 오류 목록."""
