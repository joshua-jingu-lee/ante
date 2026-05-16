"""CLI backtest run --symbols/--timeframe ingress 검증 테스트 (#1603).

CLI 경계 단일 검증 (#1585 `BACKTEST_INVALID_EXCHANGE` 블록 1:1 미러):
- invalid timeframe → exit 1 + `BACKTEST_INVALID_TIMEFRAME`.
- 빈/공백 symbol segment → exit 1 + `BACKTEST_INVALID_SYMBOL`.
- `--exchange KRX`에서 비-6자리 symbol → exit 1 + `BACKTEST_INVALID_SYMBOL`.
- `--symbols` 미지정 → 기존 동작 유지 (거부 안 함, 정상 진행 경로).
- `--exchange NYSE --symbols AAPL` → KRX symbol 검증 비거부
  (core.md `### KRX symbol shape` resolved exchange == KRX 한정).
- invalid 입력 → `_save_backtest_run` 미도달 (backtest_runs history 미생성).
- JSON/text 양 포맷 error code/메시지 회귀.

검증 precedence: date/exchange 검증 이후 → ① timeframe → ② 빈 segment →
③ KRX symbol shape (이슈 #1603 Implementation Plan 고정).
"""

from __future__ import annotations

import json
from unittest.mock import patch

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


def _run_args(strategy_path, *extra):
    return [
        "backtest",
        "run",
        str(strategy_path),
        "--start",
        "2026-01-01",
        "--end",
        "2026-01-01",
        *extra,
    ]


class TestBacktestTimeframeValidation:
    """backtest run --timeframe canonical 검증 (CLI 경계 단일 지점)."""

    def test_invalid_timeframe_text_mode_exit1_message_only(self, tmp_path):
        """비-canonical timeframe: text 모드 exit 1 + 메시지만(code 미출력)."""
        strategy = tmp_path / "test_strategy.py"
        strategy.write_text("# dummy")
        runner = _make_runner()

        result = runner.invoke(
            cli,
            _run_args(
                strategy,
                "--symbols",
                "005930",
                "--timeframe",
                "oracle-invalid-timeframe",
            ),
        )
        assert result.exit_code == 1
        assert "유효하지 않은 타임프레임" in result.output
        assert "oracle-invalid-timeframe" in result.output
        # text 모드: OutputFormatter.error는 code를 출력하지 않는다.
        assert "BACKTEST_INVALID_TIMEFRAME" not in result.output

    def test_invalid_timeframe_json_mode_exit1_with_code(self, tmp_path):
        """비-canonical timeframe: --format json exit 1 + 구조화 payload."""
        strategy = tmp_path / "test_strategy.py"
        strategy.write_text("# dummy")
        runner = _make_runner()

        result = runner.invoke(
            cli,
            [
                "--format",
                "json",
                *_run_args(
                    strategy,
                    "--symbols",
                    "005930",
                    "--timeframe",
                    "oracle-invalid-timeframe",
                ),
            ],
        )
        assert result.exit_code == 1
        payload = json.loads(result.stdout)
        assert payload["status"] == "error"
        assert payload["code"] == "BACKTEST_INVALID_TIMEFRAME"

    def test_valid_canonical_timeframe_not_rejected(self, tmp_path):
        """canonical timeframe(1d)은 invalid-timeframe 거부 아님."""
        strategy = tmp_path / "test_strategy.py"
        strategy.write_text("# dummy")
        runner = _make_runner()

        with patch("ante.backtest.service.BacktestService") as mock_service:
            mock_service.side_effect = RuntimeError("stop after validation")
            result = runner.invoke(
                cli,
                _run_args(strategy, "--symbols", "005930", "--timeframe", "1d"),
            )

        mock_service.assert_called_once()
        assert "유효하지 않은 타임프레임" not in result.output


class TestBacktestSymbolValidation:
    """backtest run --symbols 빈 segment / KRX shape 검증."""

    def test_krx_non_six_digit_symbol_exit1_invalid_symbol(self, tmp_path):
        """--exchange KRX + 비-6자리 symbol: exit 1 + BACKTEST_INVALID_SYMBOL."""
        strategy = tmp_path / "test_strategy.py"
        strategy.write_text("# dummy")
        runner = _make_runner()

        result = runner.invoke(
            cli,
            _run_args(
                strategy,
                "--symbols",
                "ABCDEF",
                "--timeframe",
                "1d",
                "--exchange",
                "KRX",
            ),
        )
        assert result.exit_code == 1
        assert "유효하지 않은 종목 코드" in result.output

    def test_krx_non_six_digit_symbol_json_mode_with_code(self, tmp_path):
        """--exchange KRX + 비-6자리 symbol: JSON exit 1 + 구조화 code."""
        strategy = tmp_path / "test_strategy.py"
        strategy.write_text("# dummy")
        runner = _make_runner()

        result = runner.invoke(
            cli,
            [
                "--format",
                "json",
                *_run_args(
                    strategy,
                    "--symbols",
                    "ABCDEF",
                    "--timeframe",
                    "1d",
                    "--exchange",
                    "KRX",
                ),
            ],
        )
        assert result.exit_code == 1
        payload = json.loads(result.stdout)
        assert payload["status"] == "error"
        assert payload["code"] == "BACKTEST_INVALID_SYMBOL"

    def test_interior_empty_segment_exit1_invalid_symbol(self, tmp_path):
        """--symbols 005930,,000660 (내부 빈 segment): exit 1 + INVALID_SYMBOL."""
        strategy = tmp_path / "test_strategy.py"
        strategy.write_text("# dummy")
        runner = _make_runner()

        result = runner.invoke(
            cli,
            _run_args(strategy, "--symbols", "005930,,000660", "--timeframe", "1d"),
        )
        assert result.exit_code == 1
        assert "유효하지 않은 종목 코드" in result.output

    def test_interior_empty_segment_json_mode_with_code(self, tmp_path):
        """내부 빈 segment: JSON exit 1 + BACKTEST_INVALID_SYMBOL."""
        strategy = tmp_path / "test_strategy.py"
        strategy.write_text("# dummy")
        runner = _make_runner()

        result = runner.invoke(
            cli,
            [
                "--format",
                "json",
                *_run_args(
                    strategy, "--symbols", "005930,,000660", "--timeframe", "1d"
                ),
            ],
        )
        assert result.exit_code == 1
        payload = json.loads(result.stdout)
        assert payload["status"] == "error"
        assert payload["code"] == "BACKTEST_INVALID_SYMBOL"

    def test_explicit_empty_symbols_rejected(self, tmp_path):
        """--symbols "" (explicit empty): exit 1 + BACKTEST_INVALID_SYMBOL.

        Click은 빈 문자열 인자를 None이 아닌 ""로 전달한다 →
        symbols is not None 분기 진입, split(",") == [""] 빈 segment 거부.
        """
        strategy = tmp_path / "test_strategy.py"
        strategy.write_text("# dummy")
        runner = _make_runner()

        result = runner.invoke(
            cli,
            _run_args(strategy, "--symbols", "", "--timeframe", "1d"),
        )
        assert result.exit_code == 1
        assert "유효하지 않은 종목 코드" in result.output

    def test_leading_comma_rejected(self, tmp_path):
        """--symbols ",005930" (leading comma): exit 1 + INVALID_SYMBOL."""
        strategy = tmp_path / "test_strategy.py"
        strategy.write_text("# dummy")
        runner = _make_runner()

        result = runner.invoke(
            cli,
            _run_args(strategy, "--symbols", ",005930", "--timeframe", "1d"),
        )
        assert result.exit_code == 1
        assert "유효하지 않은 종목 코드" in result.output

    def test_trailing_comma_rejected(self, tmp_path):
        """--symbols "005930," (trailing comma): exit 1 + INVALID_SYMBOL."""
        strategy = tmp_path / "test_strategy.py"
        strategy.write_text("# dummy")
        runner = _make_runner()

        result = runner.invoke(
            cli,
            _run_args(strategy, "--symbols", "005930,", "--timeframe", "1d"),
        )
        assert result.exit_code == 1
        assert "유효하지 않은 종목 코드" in result.output

    def test_whitespace_only_segment_rejected(self, tmp_path):
        """--symbols "005930,  ,000660" (공백 only segment): 거부."""
        strategy = tmp_path / "test_strategy.py"
        strategy.write_text("# dummy")
        runner = _make_runner()

        result = runner.invoke(
            cli,
            _run_args(strategy, "--symbols", "005930,  ,000660", "--timeframe", "1d"),
        )
        assert result.exit_code == 1
        assert "유효하지 않은 종목 코드" in result.output

    def test_valid_krx_symbols_not_rejected(self, tmp_path):
        """유효한 KRX 6자리 symbol(005930,000660): 거부 아님 (정상 진행)."""
        strategy = tmp_path / "test_strategy.py"
        strategy.write_text("# dummy")
        runner = _make_runner()

        with patch("ante.backtest.service.BacktestService") as mock_service:
            mock_service.side_effect = RuntimeError("stop after validation")
            result = runner.invoke(
                cli,
                _run_args(strategy, "--symbols", "005930,000660", "--timeframe", "1d"),
            )

        mock_service.assert_called_once()
        assert "유효하지 않은 종목 코드" not in result.output


class TestBacktestSymbolValidationScope:
    """KRX 한정 / omitted 경계 — core.md `### KRX symbol shape` 정합."""

    def test_omitted_symbols_passes(self, tmp_path):
        """--symbols 미지정: 기존 동작 유지 (거부 안 함, 정상 진행 경로).

        symbols is None → 빈 segment / KRX shape 검증 미진입.
        """
        strategy = tmp_path / "test_strategy.py"
        strategy.write_text("# dummy")
        runner = _make_runner()

        with patch("ante.backtest.service.BacktestService") as mock_service:
            mock_service.side_effect = RuntimeError("stop after validation")
            result = runner.invoke(
                cli,
                _run_args(strategy, "--timeframe", "1d"),
            )

        mock_service.assert_called_once()
        assert "유효하지 않은 종목 코드" not in result.output
        assert "유효하지 않은 타임프레임" not in result.output

    def test_nyse_non_krx_symbol_not_rejected(self, tmp_path):
        """--exchange NYSE --symbols AAPL: KRX symbol shape 검증 비거부.

        core.md `### KRX symbol shape`는 resolved exchange == KRX 신규 입력
        한정 — 비-KRX exchange symbol format은 1.0 비목표.
        """
        strategy = tmp_path / "test_strategy.py"
        strategy.write_text("# dummy")
        runner = _make_runner()

        with patch("ante.backtest.service.BacktestService") as mock_service:
            mock_service.side_effect = RuntimeError("stop after validation")
            result = runner.invoke(
                cli,
                _run_args(
                    strategy,
                    "--symbols",
                    "AAPL",
                    "--timeframe",
                    "1d",
                    "--exchange",
                    "NYSE",
                ),
            )

        # KRX shape 검증을 통과해야만 BacktestService가 호출됨.
        mock_service.assert_called_once()
        assert "유효하지 않은 종목 코드" not in result.output

    def test_nyse_empty_segment_still_rejected(self, tmp_path):
        """--exchange NYSE라도 빈 segment(②)는 거부 (exchange 무관 경계)."""
        strategy = tmp_path / "test_strategy.py"
        strategy.write_text("# dummy")
        runner = _make_runner()

        result = runner.invoke(
            cli,
            _run_args(
                strategy,
                "--symbols",
                "AAPL,,MSFT",
                "--timeframe",
                "1d",
                "--exchange",
                "NYSE",
            ),
        )
        assert result.exit_code == 1
        assert "유효하지 않은 종목 코드" in result.output


class TestBacktestValidationPrecedence:
    """검증 precedence: date/exchange → ① timeframe → ② 빈 segment → ③ KRX."""

    def test_timeframe_checked_before_symbol(self, tmp_path):
        """timeframe·symbol 동시 invalid → timeframe error 우선 (① 먼저)."""
        strategy = tmp_path / "test_strategy.py"
        strategy.write_text("# dummy")
        runner = _make_runner()

        result = runner.invoke(
            cli,
            [
                "--format",
                "json",
                *_run_args(
                    strategy,
                    "--symbols",
                    "ABCDEF",
                    "--timeframe",
                    "oracle-invalid-timeframe",
                    "--exchange",
                    "KRX",
                ),
            ],
        )
        assert result.exit_code == 1
        payload = json.loads(result.stdout)
        assert payload["code"] == "BACKTEST_INVALID_TIMEFRAME"

    def test_exchange_checked_before_timeframe(self, tmp_path):
        """exchange·timeframe 동시 invalid → exchange error 우선 (#1585 먼저)."""
        strategy = tmp_path / "test_strategy.py"
        strategy.write_text("# dummy")
        runner = _make_runner()

        result = runner.invoke(
            cli,
            [
                "--format",
                "json",
                *_run_args(
                    strategy,
                    "--symbols",
                    "005930",
                    "--timeframe",
                    "oracle-invalid-timeframe",
                    "--exchange",
                    "ORACLE_INVALID_EXCHANGE",
                ),
            ],
        )
        assert result.exit_code == 1
        payload = json.loads(result.stdout)
        assert payload["code"] == "BACKTEST_INVALID_EXCHANGE"

    def test_empty_segment_checked_before_krx_shape(self, tmp_path):
        """빈 segment·KRX shape 동시 invalid → 빈 segment 먼저 (②→③).

        둘 다 BACKTEST_INVALID_SYMBOL이나, 빈 segment 메시지가
        먼저 보고됨을 메시지 본문으로 확인.
        """
        strategy = tmp_path / "test_strategy.py"
        strategy.write_text("# dummy")
        runner = _make_runner()

        result = runner.invoke(
            cli,
            _run_args(
                strategy,
                "--symbols",
                "ABCDEF,,GHIJKL",
                "--timeframe",
                "1d",
                "--exchange",
                "KRX",
            ),
        )
        assert result.exit_code == 1
        assert "빈 종목 코드를 포함할 수 없습니다" in result.output


class TestBacktestInvalidInputNoHistory:
    """invalid 입력 시 backtest_runs history 미생성 (_save_backtest_run 미도달)."""

    def test_invalid_timeframe_no_save_backtest_run(self, tmp_path):
        """invalid timeframe → _save_backtest_run 미호출 (history 미생성)."""
        strategy = tmp_path / "test_strategy.py"
        strategy.write_text("# dummy")
        runner = _make_runner()

        with patch("ante.cli.commands.backtest._save_backtest_run") as mock_save:
            result = runner.invoke(
                cli,
                _run_args(
                    strategy,
                    "--symbols",
                    "005930",
                    "--timeframe",
                    "oracle-invalid-timeframe",
                ),
            )

        assert result.exit_code == 1
        mock_save.assert_not_called()

    def test_invalid_symbol_no_save_backtest_run(self, tmp_path):
        """invalid KRX symbol → _save_backtest_run 미호출 (history 미생성)."""
        strategy = tmp_path / "test_strategy.py"
        strategy.write_text("# dummy")
        runner = _make_runner()

        with patch("ante.cli.commands.backtest._save_backtest_run") as mock_save:
            result = runner.invoke(
                cli,
                _run_args(
                    strategy,
                    "--symbols",
                    "ABCDEF",
                    "--timeframe",
                    "1d",
                    "--exchange",
                    "KRX",
                ),
            )

        assert result.exit_code == 1
        mock_save.assert_not_called()

    def test_empty_segment_no_save_backtest_run(self, tmp_path):
        """빈 segment → _save_backtest_run 미호출 (history 미생성)."""
        strategy = tmp_path / "test_strategy.py"
        strategy.write_text("# dummy")
        runner = _make_runner()

        with patch("ante.cli.commands.backtest._save_backtest_run") as mock_save:
            result = runner.invoke(
                cli,
                _run_args(strategy, "--symbols", "005930,,000660", "--timeframe", "1d"),
            )

        assert result.exit_code == 1
        mock_save.assert_not_called()
