"""ante report submit CLI invariant 회귀 테스트 (#1415).

Web API ``POST /api/reports``는 ``ReportSubmitRequest`` (SSOT)로 invalid
metric을 422로 거부하지만, 이전까지 ``ante report submit`` CLI는 동일 invariant를
적용하지 않고 exit 0으로 통과시켜 ReportStore에 invalid 값을 저장했다.

본 모듈은 CLI도 Web API와 동일한 invariants를 통과해야 함을 회귀 검증한다:
- ``total_trades >= 0``
- ``win_rate ∈ [0.0, 100.0]`` (percent 단위, ``None`` 허용)
- 4개 metric (``total_return_pct``, ``sharpe_ratio``, ``max_drawdown_pct``,
  ``win_rate``)은 finite (NaN/Inf 거부)
- ``extra='forbid'`` — 미지정 키 거부

SSOT:
- ``docs/specs/report-store/report-store.md``
- ``src/ante/web/schemas.py::ReportSubmitRequest``
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from ante.cli.main import cli
from ante.member.models import Member, MemberRole, MemberType

_MOCK_MASTER = Member(
    member_id="test-master",
    type=MemberType.HUMAN,
    role=MemberRole.MASTER,
    org="default",
    name="Test Master",
    status="active",
    scopes=[],
)


@pytest.fixture
def runner() -> CliRunner:
    """auth bypass가 적용된 CliRunner.

    ``ante.cli.main.authenticate_member`` 패치로 root group의 인증 검사를
    우회한다 (테스트 픽스처 표준 패턴).
    """
    r = CliRunner()
    original_invoke = r.invoke

    def _invoke_with_auth(cli_cmd, args=None, **kwargs):
        with patch("ante.cli.main.authenticate_member") as mock_auth:

            def _set_member(ctx):
                ctx.obj = ctx.obj or {}
                ctx.obj["member"] = _MOCK_MASTER

            mock_auth.side_effect = _set_member
            return original_invoke(cli_cmd, args, **kwargs)

    r.invoke = _invoke_with_auth
    return r


def _base_payload(**overrides: Any) -> dict[str, Any]:
    """``ReportSubmitRequest`` 통과 가능한 최소 payload."""
    payload: dict[str, Any] = {
        "strategy_name": "cli_probe",
        "strategy_version": "0.1.0",
        "strategy_path": "strategies/cli_probe.py",
        "backtest_period": "2024-01 ~ 2026-03",
        "total_return_pct": 0.0,
        "total_trades": 0,
        "summary": "cli invariant probe",
        "rationale": "CLI invariant 검증",
        "detail_json": "{}",
    }
    payload.update(overrides)
    return payload


def _write_payload(tmp_path, payload: dict[str, Any]) -> str:
    """payload를 JSON 파일로 직렬화하여 경로를 반환."""
    p = tmp_path / "report.json"
    p.write_text(json.dumps(payload))
    return str(p)


def _invoke_submit(runner: CliRunner, tmp_path, json_path: str) -> Any:
    """``ante --format json report submit`` 호출."""
    db_path = str(tmp_path / "test.db")
    return runner.invoke(
        cli,
        ["--format", "json", "report", "submit", json_path, "--db-path", db_path],
    )


# ── total_trades invariant ──────────────────────────────────


class TestTotalTradesInvariant:
    def test_negative_total_trades_rejected(self, runner, tmp_path) -> None:
        """``total_trades=-1`` → exit 1 + structured JSON error."""
        path = _write_payload(tmp_path, _base_payload(total_trades=-1))
        result = _invoke_submit(runner, tmp_path, path)

        assert result.exit_code == 1, result.output
        body = json.loads(result.output)
        assert body["status"] == "error"
        assert body["code"] == "REPORT_VALIDATION_ERROR"
        assert "total_trades" in body["message"]

    def test_zero_total_trades_accepted(self, runner, tmp_path) -> None:
        """``total_trades=0`` (default)는 정상 처리."""
        path = _write_payload(tmp_path, _base_payload(total_trades=0))
        result = _invoke_submit(runner, tmp_path, path)
        assert result.exit_code == 0, result.output


# ── win_rate invariant ──────────────────────────────────────


class TestWinRateInvariant:
    def test_win_rate_above_100_rejected(self, runner, tmp_path) -> None:
        """``win_rate=101.0`` → exit 1."""
        path = _write_payload(tmp_path, _base_payload(win_rate=101.0))
        result = _invoke_submit(runner, tmp_path, path)

        assert result.exit_code == 1, result.output
        body = json.loads(result.output)
        assert body["status"] == "error"
        assert body["code"] == "REPORT_VALIDATION_ERROR"
        assert "win_rate" in body["message"]

    def test_win_rate_negative_rejected(self, runner, tmp_path) -> None:
        """``win_rate=-0.1`` → exit 1."""
        path = _write_payload(tmp_path, _base_payload(win_rate=-0.1))
        result = _invoke_submit(runner, tmp_path, path)
        assert result.exit_code == 1, result.output
        body = json.loads(result.output)
        assert body["code"] == "REPORT_VALIDATION_ERROR"

    @pytest.mark.parametrize("value", [0.0, 1.5, 50.0, 58.0, 100.0])
    def test_win_rate_in_range_accepted(self, runner, tmp_path, value: float) -> None:
        """percent 단위 [0.0, 100.0] 범위 내 값은 정상."""
        path = _write_payload(tmp_path, _base_payload(win_rate=value))
        result = _invoke_submit(runner, tmp_path, path)
        assert result.exit_code == 0, result.output

    def test_win_rate_null_accepted(self, runner, tmp_path) -> None:
        """``win_rate=null``은 옵션 필드."""
        path = _write_payload(tmp_path, _base_payload(win_rate=None))
        result = _invoke_submit(runner, tmp_path, path)
        assert result.exit_code == 0, result.output


# ── finite invariant (NaN/Inf 거부) ────────────────────────


class TestFiniteInvariant:
    """4개 metric 필드 NaN/Inf 거부.

    Python json 모듈은 ``allow_nan=True`` 기본으로 ``NaN``/``Infinity`` 토큰을
    출력한다. CLI는 file을 ``json.load``로 읽으므로 file에 NaN/Infinity 토큰을
    그대로 써두면 Python이 ``float('nan')``/``float('inf')``로 파싱하고
    ``ReportSubmitRequest`` (``allow_inf_nan=False``)에서 거부된다.
    """

    @pytest.mark.parametrize(
        "field",
        ["total_return_pct", "sharpe_ratio", "max_drawdown_pct", "win_rate"],
    )
    @pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity"])
    def test_non_finite_rejected(
        self, runner, tmp_path, field: str, token: str
    ) -> None:
        # JSON file에 비표준 NaN/Inf 토큰을 raw하게 주입한다.
        payload = _base_payload()
        payload[field] = 0.0  # placeholder
        body = json.dumps(payload)
        body = body.replace(f'"{field}": 0.0', f'"{field}": {token}', 1)
        p = tmp_path / "report.json"
        p.write_text(body)

        result = _invoke_submit(runner, tmp_path, str(p))
        assert result.exit_code == 1, (
            f"{field}={token} 은 exit 1로 거부되어야 함: {result.output}"
        )
        parsed = json.loads(result.output)
        assert parsed["code"] == "REPORT_VALIDATION_ERROR"


# ── extra='forbid' ──────────────────────────────────────────


class TestExtraForbid:
    def test_unknown_key_rejected(self, runner, tmp_path) -> None:
        """미지정 키(``foo``)는 ``extra='forbid'``로 거부."""
        path = _write_payload(tmp_path, _base_payload(foo="bar"))
        result = _invoke_submit(runner, tmp_path, path)
        assert result.exit_code == 1, result.output
        body = json.loads(result.output)
        assert body["code"] == "REPORT_VALIDATION_ERROR"


# ── CLI extras (submitted_by, backtest_run_id) ──────────────


class TestCliExtras:
    def test_submitted_by_extracted_before_validation(self, runner, tmp_path) -> None:
        """``submitted_by``는 모델 외부 필드 — extra='forbid'에 걸리지 않는다."""
        payload = _base_payload(submitted_by="cli-user-1")
        path = _write_payload(tmp_path, payload)
        result = _invoke_submit(runner, tmp_path, path)
        assert result.exit_code == 0, result.output
        body = json.loads(result.output)
        assert body["status"] == "ok"

    def test_detail_json_dict_normalized(self, runner, tmp_path) -> None:
        """``detail_json``이 dict로 들어오면 직렬화 후 검증 통과."""
        payload = _base_payload()
        payload["detail_json"] = {
            "equity_curve": [{"date": "2025-01-01", "value": 100}]
        }
        path = _write_payload(tmp_path, payload)
        result = _invoke_submit(runner, tmp_path, path)
        assert result.exit_code == 0, result.output


# ── 정상 케이스 회귀 ───────────────────────────────────────


class TestHappyPath:
    def test_full_valid_payload(self, runner, tmp_path) -> None:
        """정상 케이스 회귀: total_trades=10, win_rate=58.0, dict detail_json."""
        payload = _base_payload(
            total_trades=10,
            win_rate=58.0,
            total_return_pct=12.5,
            sharpe_ratio=1.4,
            max_drawdown_pct=-5.2,
        )
        # dict 입력 후 normalize 경로
        payload["detail_json"] = {"k": 1}
        path = _write_payload(tmp_path, payload)
        result = _invoke_submit(runner, tmp_path, path)
        assert result.exit_code == 0, result.output
        body = json.loads(result.output)
        assert body["status"] == "ok"
        assert body["data"]["strategy"] == "cli_probe"


# ── non-object JSON shape (codex r1 P3) ─────────────────────


class TestNonObjectJsonReturnsValidationError:
    """codex r1 P3: 파일이 JSON object가 아니면 구조화된 REPORT_VALIDATION_ERROR로 거부.

    이전 구현은 ``report_data.pop(...)``/``report_data.get(...)`` 호출이
    ``AttributeError``/``TypeError``로 raise되어 의도한 구조화 응답을 우회했다.
    """

    def test_json_array_rejected(self, runner, tmp_path) -> None:
        """JSON 배열은 dict가 아니므로 거부."""
        p = tmp_path / "report.json"
        p.write_text("[1, 2, 3]")
        db_path = str(tmp_path / "test.db")
        result = runner.invoke(
            cli,
            ["--format", "json", "report", "submit", str(p), "--db-path", db_path],
        )
        assert result.exit_code == 1, result.output
        body = json.loads(result.output)
        assert body["status"] == "error"
        assert body["code"] == "REPORT_VALIDATION_ERROR"
        assert "JSON object" in body["message"] or "object" in body["message"]

    def test_json_string_rejected(self, runner, tmp_path) -> None:
        """JSON string은 dict가 아니므로 거부."""
        p = tmp_path / "report.json"
        p.write_text('"just a string"')
        db_path = str(tmp_path / "test.db")
        result = runner.invoke(
            cli,
            ["--format", "json", "report", "submit", str(p), "--db-path", db_path],
        )
        assert result.exit_code == 1, result.output
        body = json.loads(result.output)
        assert body["status"] == "error"
        assert body["code"] == "REPORT_VALIDATION_ERROR"

    def test_json_number_rejected(self, runner, tmp_path) -> None:
        """JSON number는 dict가 아니므로 거부."""
        p = tmp_path / "report.json"
        p.write_text("42")
        db_path = str(tmp_path / "test.db")
        result = runner.invoke(
            cli,
            ["--format", "json", "report", "submit", str(p), "--db-path", db_path],
        )
        assert result.exit_code == 1, result.output
        body = json.loads(result.output)
        assert body["code"] == "REPORT_VALIDATION_ERROR"

    def test_json_null_rejected(self, runner, tmp_path) -> None:
        """JSON null은 dict가 아니므로 거부."""
        p = tmp_path / "report.json"
        p.write_text("null")
        db_path = str(tmp_path / "test.db")
        result = runner.invoke(
            cli,
            ["--format", "json", "report", "submit", str(p), "--db-path", db_path],
        )
        assert result.exit_code == 1, result.output
        body = json.loads(result.output)
        assert body["code"] == "REPORT_VALIDATION_ERROR"

    def test_malformed_json_rejected(self, runner, tmp_path) -> None:
        """파싱 불가능한 JSON 텍스트도 REPORT_VALIDATION_ERROR로 거부."""
        p = tmp_path / "report.json"
        p.write_text("{not valid json,,")
        db_path = str(tmp_path / "test.db")
        result = runner.invoke(
            cli,
            ["--format", "json", "report", "submit", str(p), "--db-path", db_path],
        )
        assert result.exit_code == 1, result.output
        body = json.loads(result.output)
        assert body["code"] == "REPORT_VALIDATION_ERROR"
        assert "Invalid JSON" in body["message"]
