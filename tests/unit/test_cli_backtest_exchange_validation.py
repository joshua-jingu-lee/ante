"""CLI backtest run --exchange canonical 검증 + CLI→config handoff 테스트 (#1585).

CLI 경계 단일 검증:
- 비-canonical / `*` → exit 1 + 구조화 error payload (text: 메시지만, JSON: code).
- canonical(NYSE) → invalid-exchange 거부 아님(축 A — canonical은 invalid 아님).
- 옵션 미지정 → KRX 기본(기존 동작 회귀).
- CLI→config handoff: CLI가 넘기는 config dict에 exchange가 정확히 실린다.
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


class TestBacktestExchangeValidation:
    """backtest run --exchange canonical 검증 (CLI 경계 단일 지점)."""

    def test_non_canonical_exchange_text_mode_exit1_message_only(self, tmp_path):
        """비-canonical 거래소: text 모드 exit 1 + 에러 메시지만(code 미출력)."""
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
                "2026-01-01",
                "--exchange",
                "ORACLE_INVALID_EXCHANGE",
            ],
        )
        assert result.exit_code == 1
        assert "유효하지 않은 거래소" in result.output
        assert "ORACLE_INVALID_EXCHANGE" in result.output
        # text 모드: OutputFormatter.error는 code를 출력하지 않는다.
        assert "BACKTEST_INVALID_EXCHANGE" not in result.output

    def test_non_canonical_exchange_json_mode_exit1_with_code(self, tmp_path):
        """비-canonical 거래소: --format json exit 1 + 구조화 error payload."""
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
                "2026-01-01",
                "--end",
                "2026-01-01",
                "--exchange",
                "ORACLE_INVALID_EXCHANGE",
            ],
        )
        assert result.exit_code == 1
        payload = json.loads(result.stdout)
        assert payload["status"] == "error"
        assert payload["code"] == "BACKTEST_INVALID_EXCHANGE"

    def test_wildcard_exchange_rejected_exit1(self, tmp_path):
        """`*`는 backtest 표면에서 거부 (StrategyMeta 표면 아님)."""
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
                "2026-01-01",
                "--exchange",
                "*",
            ],
        )
        assert result.exit_code == 1
        assert "유효하지 않은 거래소" in result.output

    def test_canonical_exchange_nyse_not_rejected(self, tmp_path):
        """canonical(NYSE)은 invalid-exchange 거부 아님 (축 A)."""
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
                    "--exchange",
                    "NYSE",
                ],
            )

        # canonical 검증을 통과해야만 BacktestService가 호출됨.
        mock_service.assert_called_once()
        assert "유효하지 않은 거래소" not in result.output

    def test_default_exchange_krx_passes(self, tmp_path):
        """--exchange 미지정은 KRX 기본 — 검증 통과 (기존 동작 회귀)."""
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

        mock_service.assert_called_once()
        assert "유효하지 않은 거래소" not in result.output


def _capture_config():
    """BacktestService.run_subprocess 에 넘어온 config dict를 캡처하는 스파이 (#2001).

    CLI가 검증만 통과시키고 config에 exchange를 누락해도 잡아낸다
    (validation/plumbing 테스트만으로는 못 잡는 hop — q2). CLI 가 subprocess
    격리 경로(run_subprocess)로 전환되었으므로 그 hop 을 spy 한다.
    """
    captured: dict = {}

    class _SpyService:
        def __init__(self, *args, **kwargs):
            pass

        async def run_subprocess(self, config):
            captured["config"] = dict(config)
            raise RuntimeError("stop after config handoff")

    return captured, _SpyService


class TestBacktestExchangeConfigHandoff:
    """CLI→config handoff: CLI가 넘기는 config dict에 exchange가 실린다."""

    def test_explicit_exchange_in_config(self, tmp_path):
        """--exchange NYSE → config['exchange'] == 'NYSE'."""
        strategy = tmp_path / "test_strategy.py"
        strategy.write_text("# dummy")
        runner = _make_runner()
        captured, spy = _capture_config()

        with patch("ante.backtest.service.BacktestService", spy):
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
                    "--exchange",
                    "NYSE",
                ],
            )

        assert result.exit_code == 1
        assert captured["config"]["exchange"] == "NYSE"

    def test_default_exchange_in_config(self, tmp_path):
        """--exchange 미지정 → config['exchange'] == 'KRX'."""
        strategy = tmp_path / "test_strategy.py"
        strategy.write_text("# dummy")
        runner = _make_runner()
        captured, spy = _capture_config()

        with patch("ante.backtest.service.BacktestService", spy):
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

        assert result.exit_code == 1
        assert captured["config"]["exchange"] == "KRX"
