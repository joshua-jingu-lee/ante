"""``ReportSubmitRequest.detail_json`` 표준 JSON 검증 회귀 테스트 (#2025).

이전까지 ``detail_json``은 ``str`` 타입만 검증하고 JSON 표준성을 검증하지
않아, 비표준 JSON 토큰(``Infinity``/``-Infinity``/``NaN``)을 포함한 문자열도
검증을 통과해 ReportStore에 저장되었다. Python ``json.dumps``는 기본적으로
``float('inf')`` 등을 이 비표준 토큰으로 직렬화하므로, CLI dict 입력 경로를
통해서도 비표준 토큰이 흘러들 수 있었다.

본 모듈은 ``detail_json``이 표준 JSON 문자열이어야 하며, 비표준 토큰(중첩
포함)과 파싱 불가능한 비-JSON 문자열을 거부함을 모델 레벨에서 회귀 검증한다.

SSOT:
- ``docs/specs/report-store/report-store.md``
- ``src/ante/report/validation.py::ReportSubmitRequest``
"""

from __future__ import annotations

import json
import math
from typing import Any

import pytest
from pydantic import ValidationError

from ante.report.validation import ReportSubmitRequest


def _base_kwargs(**overrides: Any) -> dict[str, Any]:
    """``ReportSubmitRequest`` 통과 가능한 최소 kwargs."""
    kwargs: dict[str, Any] = {
        "strategy_name": "probe",
        "strategy_version": "0.1.0",
        "strategy_path": "strategies/probe.py",
        "backtest_period": "2024-01 ~ 2026-03",
        "total_return_pct": 0.0,
        "total_trades": 0,
        "summary": "probe",
        "rationale": "검증",
    }
    kwargs.update(overrides)
    return kwargs


# ── 비표준 JSON 토큰 거부 (NaN/Infinity/-Infinity) ─────────────


class TestNonStandardJsonRejected:
    def test_top_level_infinity_rejected(self) -> None:
        """top-level ``Infinity`` 토큰 거부."""
        with pytest.raises(ValidationError):
            ReportSubmitRequest(**_base_kwargs(detail_json="Infinity"))

    def test_top_level_negative_infinity_rejected(self) -> None:
        """top-level ``-Infinity`` 토큰 거부."""
        with pytest.raises(ValidationError):
            ReportSubmitRequest(**_base_kwargs(detail_json="-Infinity"))

    def test_top_level_nan_rejected(self) -> None:
        """top-level ``NaN`` 토큰 거부."""
        with pytest.raises(ValidationError):
            ReportSubmitRequest(**_base_kwargs(detail_json="NaN"))

    def test_nested_infinity_via_json_dumps_rejected(self) -> None:
        """중첩 위치의 ``Infinity`` 토큰 거부 (``json.dumps``가 ``float('inf')``
        를 ``Infinity``로 직렬화하는 dict 입력 경로 시뮬레이션)."""
        bad = json.dumps({"metrics": {"profit_factor": math.inf}})
        assert "Infinity" in bad
        with pytest.raises(ValidationError):
            ReportSubmitRequest(**_base_kwargs(detail_json=bad))

    def test_nested_negative_infinity_rejected(self) -> None:
        """중첩 위치의 ``-Infinity`` 토큰 거부."""
        bad = json.dumps({"metrics": {"drawdown": -math.inf}})
        assert "-Infinity" in bad
        with pytest.raises(ValidationError):
            ReportSubmitRequest(**_base_kwargs(detail_json=bad))

    def test_nested_nan_rejected(self) -> None:
        """중첩 위치의 ``NaN`` 토큰 거부."""
        bad = json.dumps({"metrics": {"sharpe": math.nan}})
        assert "NaN" in bad
        with pytest.raises(ValidationError):
            ReportSubmitRequest(**_base_kwargs(detail_json=bad))


# ── 비-JSON 문자열 거부 ────────────────────────────────────────


class TestNonJsonRejected:
    def test_plain_text_rejected(self) -> None:
        """파싱 불가능한 비-JSON 문자열 거부."""
        with pytest.raises(ValidationError):
            ReportSubmitRequest(**_base_kwargs(detail_json="not json"))

    def test_malformed_json_rejected(self) -> None:
        """깨진 JSON 문자열 거부."""
        with pytest.raises(ValidationError):
            ReportSubmitRequest(**_base_kwargs(detail_json="{not valid,,"))

    def test_empty_string_rejected(self) -> None:
        """빈 문자열은 유효한 JSON이 아니므로 거부."""
        with pytest.raises(ValidationError):
            ReportSubmitRequest(**_base_kwargs(detail_json=""))


# ── 정상 케이스 통과 ──────────────────────────────────────────


class TestValidDetailJsonAccepted:
    def test_default_empty_object_accepted(self) -> None:
        """기본값 ``"{}"``는 통과하며 원본을 보존한다."""
        req = ReportSubmitRequest(**_base_kwargs())
        assert req.detail_json == "{}"

    def test_explicit_empty_object_accepted(self) -> None:
        """명시적 ``"{}"``는 통과."""
        req = ReportSubmitRequest(**_base_kwargs(detail_json="{}"))
        assert req.detail_json == "{}"

    def test_finite_metric_object_accepted(self) -> None:
        """finite 값으로 구성된 표준 JSON object는 통과하며 원본 보존."""
        good = json.dumps({"metrics": {"profit_factor": 1.5}})
        req = ReportSubmitRequest(**_base_kwargs(detail_json=good))
        assert req.detail_json == good

    def test_nested_array_accepted(self) -> None:
        """중첩 배열을 포함한 표준 JSON object는 통과."""
        good = '{"equity_curve": [100, 105, 110]}'
        req = ReportSubmitRequest(**_base_kwargs(detail_json=good))
        assert req.detail_json == good
