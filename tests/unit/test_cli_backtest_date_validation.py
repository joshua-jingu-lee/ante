"""CLI backtest run 날짜 검증 테스트."""

from __future__ import annotations

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


def _make_runner():
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


class TestBacktestDateValidation:
    """backtest run 시작일/종료일 검증."""

    def test_start_after_end_returns_exit_code_1(self, tmp_path):
        """시작일이 종료일 이후이면 exit code 1."""
        strategy = tmp_path / "test_strategy.py"
        strategy.write_text("# dummy")
        runner = _make_runner()

        result = runner.invoke(
            cli,
            [
                "backtest",
                "run",
                str(strategy),
                "--start",
                "2026-01-01",
                "--end",
                "2025-01-01",
            ],
        )
        assert result.exit_code == 1
        assert "시작일" in result.output

    def test_start_after_end_error_message(self, tmp_path):
        """에러 메시지에 날짜 정보가 포함된다."""
        strategy = tmp_path / "test_strategy.py"
        strategy.write_text("# dummy")
        runner = _make_runner()

        result = runner.invoke(
            cli,
            [
                "backtest",
                "run",
                str(strategy),
                "--start",
                "2026-06-01",
                "--end",
                "2025-06-01",
            ],
        )
        assert result.exit_code == 1
        assert "2026-06-01" in result.output
        assert "2025-06-01" in result.output

    def test_same_date_is_allowed(self, tmp_path):
        """시작일 == 종료일은 허용 (날짜 검증 통과, INVALID_DATE_RANGE 에러 없음)."""
        strategy = tmp_path / "test_strategy.py"
        strategy.write_text("# dummy")
        runner = _make_runner()

        result = runner.invoke(
            cli,
            [
                "backtest",
                "run",
                str(strategy),
                "--start",
                "2025-06-01",
                "--end",
                "2025-06-01",
            ],
        )
        # 날짜 검증 에러가 아닌 것만 확인 (이후 단계에서 다른 에러 발생 가능)
        assert "시작일" not in result.output

    def test_invalid_date_format(self, tmp_path):
        """잘못된 날짜 형식이면 exit code 1."""
        strategy = tmp_path / "test_strategy.py"
        strategy.write_text("# dummy")
        runner = _make_runner()

        result = runner.invoke(
            cli,
            [
                "backtest",
                "run",
                str(strategy),
                "--start",
                "not-a-date",
                "--end",
                "2025-01-01",
            ],
        )
        # 'not-a-date' 는 strict YYYY-MM-DD 가드(#2053)에서 INVALID_DATE 로 거부된다.
        assert result.exit_code == 1
        assert "형식이 올바르지 않습니다" in result.output


class TestBacktestStrictIsoDate:
    """backtest run --start/--end strict YYYY-MM-DD 가드 (이슈 #2053).

    Python 3.11+ ``date.fromisoformat`` 이 수락하는 basic ISO(``20260510``)·
    week date(``2026-W19-1``) 변형은 ParquetStore 의 Polars 파싱이 거부하므로
    CLI preflight 단계에서 INVALID_DATE 로 차단되어야 한다. 정상 확장 형식은
    날짜 검증을 통과해 이후 실행 단계로 진입한다.
    """

    def test_basic_iso_start_rejected(self, tmp_path):
        """(a) 재현: --start 20260510 (basic ISO)는 INVALID_DATE 로 거부."""
        strategy = tmp_path / "test_strategy.py"
        strategy.write_text("# dummy")
        runner = _make_runner()

        result = runner.invoke(
            cli,
            [
                "--format",
                "json",
                "backtest",
                "run",
                str(strategy),
                "--start",
                "20260510",
                "--end",
                "2026-05-20",
            ],
        )
        assert result.exit_code == 1
        assert '"code": "INVALID_DATE"' in result.output

    def test_week_date_start_rejected(self, tmp_path):
        """(b) --start 2026-W19-1 (ISO week date)는 INVALID_DATE 로 거부."""
        strategy = tmp_path / "test_strategy.py"
        strategy.write_text("# dummy")
        runner = _make_runner()

        result = runner.invoke(
            cli,
            [
                "--format",
                "json",
                "backtest",
                "run",
                str(strategy),
                "--start",
                "2026-W19-1",
                "--end",
                "2026-05-20",
            ],
        )
        assert result.exit_code == 1
        assert '"code": "INVALID_DATE"' in result.output

    def test_basic_iso_end_rejected(self, tmp_path):
        """(c) --end 20260510 (basic ISO)도 검증됨 — INVALID_DATE 로 거부."""
        strategy = tmp_path / "test_strategy.py"
        strategy.write_text("# dummy")
        runner = _make_runner()

        result = runner.invoke(
            cli,
            [
                "--format",
                "json",
                "backtest",
                "run",
                str(strategy),
                "--start",
                "2026-05-10",
                "--end",
                "20260510",
            ],
        )
        assert result.exit_code == 1
        assert '"code": "INVALID_DATE"' in result.output

    def test_valid_extended_iso_passes_validation(self, tmp_path):
        """(d) 회귀: 정상 YYYY-MM-DD 는 날짜 검증을 통과해 실행 단계로 진입."""
        strategy = tmp_path / "test_strategy.py"
        strategy.write_text("# dummy")
        runner = _make_runner()

        with patch("ante.backtest.service.BacktestService") as mock_service:
            mock_service.side_effect = RuntimeError("stop after validation")
            result = runner.invoke(
                cli,
                [
                    "backtest",
                    "run",
                    str(strategy),
                    "--start",
                    "2026-05-10",
                    "--end",
                    "2026-05-20",
                ],
            )

        # 날짜 검증 통과 → exchange/timeframe/symbol 검증 후 BacktestService 진입
        mock_service.assert_called_once()
        assert "형식이 올바르지 않습니다" not in result.output

    def test_nonexistent_calendar_date_rejected(self, tmp_path):
        """(e) 회귀: strict 형식이나 비실재 날짜(2026-13-40)는 fromisoformat 거부."""
        strategy = tmp_path / "test_strategy.py"
        strategy.write_text("# dummy")
        runner = _make_runner()

        result = runner.invoke(
            cli,
            [
                "--format",
                "json",
                "backtest",
                "run",
                str(strategy),
                "--start",
                "2026-13-40",
                "--end",
                "2026-05-20",
            ],
        )
        assert result.exit_code == 1
        assert '"code": "INVALID_DATE"' in result.output

    def test_start_after_end_still_invalid_range(self, tmp_path):
        """(f) 회귀: 정상 형식 역전(start > end)은 INVALID_DATE_RANGE 유지."""
        strategy = tmp_path / "test_strategy.py"
        strategy.write_text("# dummy")
        runner = _make_runner()

        result = runner.invoke(
            cli,
            [
                "--format",
                "json",
                "backtest",
                "run",
                str(strategy),
                "--start",
                "2026-05-20",
                "--end",
                "2026-05-10",
            ],
        )
        assert result.exit_code == 1
        assert '"code": "INVALID_DATE_RANGE"' in result.output


class TestBacktestBalanceValidation:
    """backtest run --balance non-finite/non-positive 거부 (이슈 #1565)."""

    @pytest.mark.parametrize("bad_balance", ["nan", "inf", "-inf", "-1", "0"])
    def test_non_finite_or_non_positive_balance_rejected(self, tmp_path, bad_balance):
        """nan/inf/음수/0 balance는 backtest 실행 전 non-zero exit으로 거부."""
        strategy = tmp_path / "test_strategy.py"
        strategy.write_text("# dummy")
        runner = _make_runner()

        with patch("ante.backtest.service.BacktestService") as mock_service:
            result = runner.invoke(
                cli,
                [
                    "backtest",
                    "run",
                    str(strategy),
                    "--start",
                    "2026-01-01",
                    "--end",
                    "2026-01-01",
                    "--balance",
                    bad_balance,
                ],
            )

        # click.BadParameter → click 표준 경로 (exit 2, backtest 미실행)
        assert result.exit_code != 0
        mock_service.assert_not_called()

    def test_nan_balance_rejected_in_json_mode(self, tmp_path):
        """--format json 모드에서도 --balance nan은 non-zero exit (이슈 재현).

        click 표준 경로이므로 stderr는 text다 (JSON envelope 표준화는
        validator의 명시적 Non-Goal — 별도 이슈).
        """
        strategy = tmp_path / "test_strategy.py"
        strategy.write_text("# dummy")
        runner = _make_runner()

        with patch("ante.backtest.service.BacktestService") as mock_service:
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "backtest",
                    "run",
                    str(strategy),
                    "--start",
                    "2026-01-01",
                    "--end",
                    "2026-01-01",
                    "--balance",
                    "nan",
                ],
            )

        assert result.exit_code != 0
        mock_service.assert_not_called()

    def test_valid_balance_passes_validation(self, tmp_path):
        """유효한 양수 finite balance는 검증 통과 (기존 backtest 실행 경로 진입)."""
        strategy = tmp_path / "test_strategy.py"
        strategy.write_text("# dummy")
        runner = _make_runner()

        with patch("ante.backtest.service.BacktestService") as mock_service:
            mock_service.side_effect = RuntimeError("stop after validation")
            result = runner.invoke(
                cli,
                [
                    "backtest",
                    "run",
                    str(strategy),
                    "--start",
                    "2026-01-01",
                    "--end",
                    "2026-01-01",
                    "--balance",
                    "5000000",
                ],
            )

        # balance 검증을 통과해야만 BacktestService가 호출됨 (이후 mock이 차단)
        mock_service.assert_called_once()
        assert "양수" not in result.output
        assert "finite" not in result.output

    def test_default_balance_passes_validation(self, tmp_path):
        """--balance 미지정(default 10_000_000)은 검증 통과 (기존 동작 유지)."""
        strategy = tmp_path / "test_strategy.py"
        strategy.write_text("# dummy")
        runner = _make_runner()

        with patch("ante.backtest.service.BacktestService") as mock_service:
            mock_service.side_effect = RuntimeError("stop after validation")
            result = runner.invoke(
                cli,
                [
                    "backtest",
                    "run",
                    str(strategy),
                    "--start",
                    "2026-01-01",
                    "--end",
                    "2026-01-01",
                ],
            )

        # default balance도 callback 통과 → BacktestService 진입
        mock_service.assert_called_once()
        assert "양수" not in result.output
        assert "finite" not in result.output
