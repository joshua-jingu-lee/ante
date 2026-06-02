"""ante feed CLI 결과 출력 포매터 단위 테스트.

`_backfill_result_dict` / `_daily_result_dict`가 CollectionResult의
failures / warnings / config_errors를 JSON 직렬화 dict에 모두 포함하는지
회귀 검증한다 (issue #2068).
"""

from __future__ import annotations

from ante.feed.cli_output import _backfill_result_dict, _daily_result_dict
from ante.feed.models.result import CollectionResult


def _result(**overrides: object) -> CollectionResult:
    """공통 CollectionResult 팩토리."""
    base: dict[str, object] = {
        "mode": "backfill",
        "started_at": "2026-03-18T00:00:00Z",
        "finished_at": "2026-03-18T00:00:01Z",
        "duration_seconds": 1.0,
        "symbols_total": 0,
        "symbols_success": 0,
        "symbols_failed": 0,
        "rows_written": 0,
        "data_types": [],
        "failures": [],
        "warnings": [],
        "config_errors": [],
    }
    base.update(overrides)
    return CollectionResult(**base)  # type: ignore[arg-type]


# ── _backfill_result_dict ────────────────────────────────────────────────


class TestBackfillResultDict:
    def test_includes_failures_warnings_config_errors_keys(self) -> None:
        """세 키(failures/warnings/config_errors)가 모두 포함된다."""
        d = _backfill_result_dict(_result())

        assert "failures" in d
        assert "warnings" in d
        assert "config_errors" in d

    def test_includes_failures_total_key(self) -> None:
        """failures_total 키가 포함된다(#2117)."""
        d = _backfill_result_dict(_result())

        assert "failures_total" in d

    def test_empty_lists_when_result_empty(self) -> None:
        """비어 있는 경우 빈 리스트로 직렬화된다."""
        d = _backfill_result_dict(_result())

        assert d["failures"] == []
        assert d["warnings"] == []
        assert d["config_errors"] == []
        assert d["failures_total"] == 0

    def test_date_level_failure_surfaces_with_symbols_failed_zero(self) -> None:
        """날짜/소스 단위 실패는 symbols_failed=0이어도 failures_total>0(#2117)."""
        result = _result(
            symbols_total=0,
            symbols_success=0,
            symbols_failed=0,
            failures=[
                {"date": "2026-03-16", "source": "data_go_kr", "reason": "HTTP 500"},
                {"source": "dart", "reason": "연결 실패"},
            ],
        )

        d = _backfill_result_dict(result)

        assert d["symbols_failed"] == 0
        assert d["failures_total"] == 2

    def test_values_match_collection_result(self) -> None:
        """항목이 있을 때 값이 CollectionResult와 일치한다."""
        failures = [{"symbol": "005930", "error": "timeout"}]
        warnings = [{"symbol": "000660", "warning": "gap"}]
        config_errors = [{"error": "missing_api_key"}]
        result = _result(
            mode="backfill",
            symbols_total=2,
            symbols_success=1,
            symbols_failed=1,
            failures=failures,
            warnings=warnings,
            config_errors=config_errors,
        )

        d = _backfill_result_dict(result)

        assert d["failures"] == failures
        assert d["warnings"] == warnings
        assert d["config_errors"] == config_errors


# ── _daily_result_dict ───────────────────────────────────────────────────


class TestDailyResultDict:
    def test_includes_failures_warnings_config_errors_keys(self) -> None:
        """세 키(failures/warnings/config_errors)가 모두 포함된다."""
        d = _daily_result_dict(_result(mode="daily", target_date="2026-03-17"))

        assert "failures" in d
        assert "warnings" in d
        assert "config_errors" in d

    def test_includes_failures_total_key(self) -> None:
        """failures_total 키가 포함된다(#2117)."""
        d = _daily_result_dict(_result(mode="daily", target_date="2026-03-17"))

        assert "failures_total" in d

    def test_empty_lists_when_result_empty(self) -> None:
        """비어 있는 경우 빈 리스트로 직렬화된다."""
        d = _daily_result_dict(_result(mode="daily", target_date="2026-03-17"))

        assert d["failures"] == []
        assert d["warnings"] == []
        assert d["config_errors"] == []
        assert d["failures_total"] == 0

    def test_date_level_failure_surfaces_with_symbols_failed_zero(self) -> None:
        """날짜/소스 단위 실패는 symbols_failed=0이어도 failures_total>0(#2117)."""
        result = _result(
            mode="daily",
            target_date="2026-03-17",
            symbols_total=0,
            symbols_success=0,
            symbols_failed=0,
            failures=[
                {"date": "2026-03-16", "source": "data_go_kr", "reason": "HTTP 500"},
            ],
        )

        d = _daily_result_dict(result)

        assert d["symbols_failed"] == 0
        assert d["failures_total"] == 1

    def test_values_match_collection_result(self) -> None:
        """항목이 있을 때 값이 CollectionResult와 일치한다."""
        failures = [{"symbol": "005930", "error": "timeout"}]
        warnings = [{"symbol": "000660", "warning": "gap"}]
        config_errors = [{"error": "missing_api_key"}]
        result = _result(
            mode="daily",
            target_date="2026-03-17",
            symbols_total=2,
            symbols_success=1,
            symbols_failed=1,
            failures=failures,
            warnings=warnings,
            config_errors=config_errors,
        )

        d = _daily_result_dict(result)

        assert d["failures"] == failures
        assert d["warnings"] == warnings
        assert d["config_errors"] == config_errors
