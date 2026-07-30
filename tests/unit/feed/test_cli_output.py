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


# ── 경고 유계화 envelope (#2414) ─────────────────────────────────────────────


def _truncated_result(**overrides: object) -> CollectionResult:
    """절단 리포트를 모사하는 CollectionResult.

    ``warnings`` 샘플 1건 + 총계 99,691건이라 ``len(result.warnings)`` 로
    파생한 오구현은 값 단정에서 즉시 드러난다.
    """
    base: dict[str, object] = {
        "warnings": [{"type": "business_rule", "message": "low > close"}],
        "warnings_total": 99691,
        "warnings_by_type": {"business_rule": 99690, "untyped": 1},
        "warnings_truncated": True,
    }
    base.update(overrides)
    return _result(**base)


class TestWarningsEnvelopeIsBounded:
    """`ante feed run --json` envelope가 전수 정확 경고 집계를 flat으로 싣는지 검증.

    키 존재만 단정하면 `len(result.warnings)` 오구현(=고치려던 축소 보고
    버그의 재도입)이 게이트를 통과하므로 **절단 케이스의 값**을 단정한다.
    """

    def test_backfill_envelope_reports_total_not_sample_length(self) -> None:
        d = _backfill_result_dict(_truncated_result())

        assert d["warnings_total"] == 99691
        assert d["warnings_by_type"] == {"business_rule": 99690, "untyped": 1}
        assert d["warnings_truncated"] is True
        # 샘플 배열 자체는 유계 절단된 상태로 전달된다.
        assert len(d["warnings"]) == 1
        assert d["warnings_total"] != len(d["warnings"])

    def test_daily_envelope_reports_total_not_sample_length(self) -> None:
        d = _daily_result_dict(
            _truncated_result(mode="daily", target_date="2026-03-17")
        )

        assert d["warnings_total"] == 99691
        assert d["warnings_by_type"] == {"business_rule": 99690, "untyped": 1}
        assert d["warnings_truncated"] is True
        assert len(d["warnings"]) == 1
        assert d["warnings_total"] != len(d["warnings"])

    def test_defaults_are_consistent_when_no_warnings(self) -> None:
        """경고가 없으면 총계 0 / 빈 집계 / 절단 False."""
        for d in (
            _backfill_result_dict(_result()),
            _daily_result_dict(_result(mode="daily", target_date="2026-03-17")),
        ):
            assert d["warnings_total"] == 0
            assert d["warnings_by_type"] == {}
            assert d["warnings_truncated"] is False
