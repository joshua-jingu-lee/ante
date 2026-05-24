"""CLI `backtest run --format json` 회귀 — stdout이 단일 JSON document인지 검증 (#1752).

버그:
- 기존에는 결과 페이로드(`fmt.output(result_dict)`)와 metric 테이블(`fmt.table(...)`)이
  JSON 모드에서도 모두 출력되어 stdout에 두 개의 독립된 JSON document가 붙었다.
- `json.loads`/`jq` 같은 single-document parser가 `Extra data` 오류로 실패했다.

회귀 검증 축:
- R1: `--format json` 호출 → stdout이 `json.loads`로 한 번에 파싱된다.
- R2: 파싱된 payload에 `metrics` 필드가 보존된다 (정보 손실 없음).
- R3: text 모드는 기존대로 metric 테이블을 출력한다 (회귀 보존).
"""

from __future__ import annotations

import json
from unittest.mock import patch

from click.testing import CliRunner

from ante.backtest.result import BacktestResult
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


def _make_runner() -> CliRunner:
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


def _make_result_with_metrics() -> BacktestResult:
    """metrics가 비어있지 않은 BacktestResult를 만든다.

    `if metrics and not fmt.is_json:` 분기를 타려면 metrics가 truthy해야 한다.
    """
    return BacktestResult(
        strategy_name="momentum",
        strategy_version="1.0.0",
        start_date="2026-01-01",
        end_date="2026-01-31",
        initial_balance=10_000_000.0,
        final_balance=11_000_000.0,
        total_return=10.0,
        trades=[],
        equity_curve=[],
        metrics={
            "total_return": 10.0,
            "sharpe_ratio": 1.5,
            "max_drawdown": -3.2,
            "win_rate": 0.6,
            "total_trades": 5,
        },
    )


class _SpyService:
    """BacktestService를 흉내내고 미리 만들어진 BacktestResult를 돌려주는 spy."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    async def run(self, config: dict, progress_callback=None) -> BacktestResult:  # noqa: ARG002
        return _make_result_with_metrics()


def _invoke_run(runner: CliRunner, tmp_path, *extra_args: str):
    """`backtest run`을 호출하되 BacktestService/_save_backtest_run을 stub."""
    strategy = tmp_path / "test_strategy.py"
    strategy.write_text("# dummy")

    with (
        patch("ante.backtest.service.BacktestService", _SpyService),
        patch(
            "ante.cli.commands.backtest._save_backtest_run",
            new=_fake_save_backtest_run,
        ),
    ):
        return runner.invoke(
            cli,
            [
                *extra_args,
                "backtest",
                "run",
                str(strategy),
                "--start",
                "2026-01-01",
                "--end",
                "2026-01-31",
            ],
        )


async def _fake_save_backtest_run(
    db_path: str,  # noqa: ARG001
    result,  # noqa: ARG001
    config: dict,  # noqa: ARG001
    metrics: dict,  # noqa: ARG001
) -> str:
    """DB 접근 없이 결정적 run_id를 반환."""
    return "run-test-1752"


class TestBacktestRunJsonSingleDocument:
    """`backtest run --format json` stdout이 단일 JSON document인지 (R1, R2)."""

    def test_json_mode_stdout_is_single_parseable_document(self, tmp_path):
        """R1: stdout 전체를 `json.loads`로 한 번에 파싱할 수 있어야 한다.

        분기 추가 전에는 metric 테이블이 두 번째 JSON document(배열)로 추가 출력되어
        `json.JSONDecodeError: Extra data`가 발생했다.
        """
        runner = _make_runner()
        result = _invoke_run(runner, tmp_path, "--format", "json")

        assert result.exit_code == 0, result.output
        # 한 번의 json.loads로 stdout 전체가 파싱되어야 한다.
        payload = json.loads(result.stdout)
        assert isinstance(payload, dict)

    def test_json_mode_payload_preserves_metrics(self, tmp_path):
        """R2: JSON payload의 `metrics`가 보존되어 정보 손실이 없다.

        `if metrics and not fmt.is_json:` 분기는 표면 출력을 잘라낼 뿐,
        result_dict["metrics"]는 그대로 노출되어야 한다.
        """
        runner = _make_runner()
        result = _invoke_run(runner, tmp_path, "--format", "json")

        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        assert "metrics" in payload
        # 핵심 지표가 그대로 보존되는지 확인.
        assert payload["metrics"]["sharpe_ratio"] == 1.5
        assert payload["metrics"]["win_rate"] == 0.6
        assert payload["metrics"]["max_drawdown"] == -3.2
        # 결과 페이로드 본문도 함께 보존되는지 확인.
        assert payload["run_id"] == "run-test-1752"
        assert payload["strategy"] == "momentum_v1.0.0"


class TestBacktestRunTextModeMetricTableRegression:
    """R3: text 모드는 기존대로 metric 테이블을 출력해 회귀가 없어야 한다."""

    def test_text_mode_still_renders_metric_table(self, tmp_path):
        """text 모드: `_format_metrics` 라벨(`Sharpe Ratio` 등)이 stdout에 나타난다."""
        runner = _make_runner()
        # --format 미지정 = text 모드 (default).
        result = _invoke_run(runner, tmp_path)

        assert result.exit_code == 0, result.output
        # _format_metrics가 만드는 한국어/영문 라벨 중 대표 토큰이 보여야 한다.
        # (테이블 헤더 "지표 | 값" + 라벨 행 둘 다 검증한다.)
        assert "지표" in result.output
        assert "값" in result.output
        assert "Sharpe Ratio" in result.output
        # 결과 페이로드 텍스트 템플릿도 같이 출력된다 (기존 회귀 보존).
        assert "Run ID: run-test-1752" in result.output
