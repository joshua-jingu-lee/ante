"""ante feed run/start CLI 커맨드 테스트.

mock orchestrator로 CLI invocation을 검증한다.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner

from ante.cli.main import cli
from ante.feed.models.result import CollectionResult
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

_EMPTY_RESULT = CollectionResult(
    mode="backfill",
    started_at="2026-03-18T00:00:00Z",
    finished_at="2026-03-18T00:00:01Z",
    duration_seconds=1.0,
    symbols_total=0,
    symbols_success=0,
    symbols_failed=0,
    rows_written=0,
    data_types=[],
    failures=[],
    warnings=[],
    config_errors=[],
)

_DAILY_RESULT = CollectionResult(
    mode="daily",
    started_at="2026-03-18T00:00:00Z",
    finished_at="2026-03-18T00:00:02Z",
    duration_seconds=2.0,
    target_date="2026-03-17",
    symbols_total=100,
    symbols_success=98,
    symbols_failed=2,
    rows_written=500,
    data_types=["ohlcv", "fundamental"],
    failures=[],
    warnings=[],
    config_errors=[],
)


@pytest.fixture
def runner() -> CliRunner:
    """인증된 상태의 CliRunner."""
    r = CliRunner()
    original_invoke = r.invoke

    def _invoke_with_auth(cli_cmd, args=None, **kwargs):  # type: ignore[no-untyped-def]
        with patch("ante.cli.main.authenticate_member") as mock_auth:

            def _set_member(ctx: object) -> None:
                import click

                ctx = click.get_current_context()
                ctx.obj = ctx.obj or {}
                ctx.obj["member"] = _MOCK_MASTER

            mock_auth.side_effect = _set_member
            return original_invoke(cli_cmd, args, **kwargs)

    r.invoke = _invoke_with_auth  # type: ignore[method-assign]
    return r


@pytest.fixture
def initialized_data_path(tmp_path: Path) -> str:
    """초기화된 데이터 디렉토리 경로."""
    data_dir = tmp_path / "data"
    feed_dir = data_dir / ".feed"
    feed_dir.mkdir(parents=True)

    # config.toml 생성
    config_toml = feed_dir / "config.toml"
    config_toml.write_text(
        "[schedule]\n"
        'daily_at = "16:00"\n'
        'backfill_at = "01:00"\n'
        'backfill_since = "2024-01-01"\n'
        "\n"
        "[guard]\n"
        "blocked_days = []\n"
        'blocked_hours = ["09:00-15:30"]\n'
        "pause_during_trading = true\n"
    )

    # checkpoints, reports 디렉토리 생성
    (feed_dir / "checkpoints").mkdir()
    (feed_dir / "reports").mkdir()

    return str(data_dir)


@pytest.fixture
def uninitialized_data_path(tmp_path: Path) -> str:
    """초기화되지 않은 데이터 디렉토리 경로."""
    return str(tmp_path / "data")


# ── ante feed run backfill ───────────────────────────────────────────────


class TestRunBackfill:
    def test_exit_code_zero(
        self, runner: CliRunner, initialized_data_path: str
    ) -> None:
        """backfill이 정상 실행되면 exit code 0."""
        with patch("ante.feed.cli._build_orchestrator") as mock_build:
            mock_orch = AsyncMock()
            mock_orch.run_backfill = AsyncMock(return_value=_EMPTY_RESULT)
            mock_build.return_value = mock_orch

            result = runner.invoke(
                cli,
                ["feed", "run", "backfill", "--data-path", initialized_data_path],
                catch_exceptions=False,
            )
            assert result.exit_code == 0

    def test_calls_orchestrator_run_backfill(
        self, runner: CliRunner, initialized_data_path: str
    ) -> None:
        """FeedOrchestrator.run_backfill이 호출된다."""
        with patch("ante.feed.cli._build_orchestrator") as mock_build:
            mock_orch = AsyncMock()
            mock_orch.run_backfill = AsyncMock(return_value=_EMPTY_RESULT)
            mock_build.return_value = mock_orch

            runner.invoke(
                cli,
                ["feed", "run", "backfill", "--data-path", initialized_data_path],
                catch_exceptions=False,
            )

            mock_orch.run_backfill.assert_awaited_once()

    def test_output_contains_result_summary(
        self, runner: CliRunner, initialized_data_path: str
    ) -> None:
        """출력에 결과 요약이 포함된다."""
        with patch("ante.feed.cli._build_orchestrator") as mock_build:
            mock_orch = AsyncMock()
            mock_orch.run_backfill = AsyncMock(return_value=_EMPTY_RESULT)
            mock_build.return_value = mock_orch

            result = runner.invoke(
                cli,
                ["feed", "run", "backfill", "--data-path", initialized_data_path],
                catch_exceptions=False,
            )

            assert "Backfill" in result.output

    def test_since_option_overrides_config(
        self, runner: CliRunner, initialized_data_path: str
    ) -> None:
        """--since 옵션이 config의 backfill_since를 오버라이드한다."""
        with patch("ante.feed.cli._build_orchestrator") as mock_build:
            mock_orch = AsyncMock()
            mock_orch.run_backfill = AsyncMock(return_value=_EMPTY_RESULT)
            mock_build.return_value = mock_orch

            runner.invoke(
                cli,
                [
                    "feed",
                    "run",
                    "backfill",
                    "--data-path",
                    initialized_data_path,
                    "--since",
                    "2020-01-01",
                ],
                catch_exceptions=False,
            )

            call_args = mock_orch.run_backfill.call_args
            config = call_args.kwargs["config"]
            assert config["schedule"]["backfill_since"] == "2020-01-01"

    def test_not_initialized_error(
        self, runner: CliRunner, uninitialized_data_path: str
    ) -> None:
        """초기화되지 않은 상태에서 실행하면 에러."""
        result = runner.invoke(
            cli,
            ["feed", "run", "backfill", "--data-path", uninitialized_data_path],
        )
        assert result.exit_code != 0

    def test_json_output(self, runner: CliRunner, initialized_data_path: str) -> None:
        """--format json 출력이 올바르다."""
        import json

        with patch("ante.feed.cli._build_orchestrator") as mock_build:
            mock_orch = AsyncMock()
            mock_orch.run_backfill = AsyncMock(return_value=_EMPTY_RESULT)
            mock_build.return_value = mock_orch

            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "feed",
                    "run",
                    "backfill",
                    "--data-path",
                    initialized_data_path,
                ],
                catch_exceptions=False,
            )

            data = json.loads(result.output)
            assert data["mode"] == "backfill"
            assert "rows_written" in data


# ── ante feed run daily ──────────────────────────────────────────────────


class TestRunDaily:
    def test_exit_code_zero(
        self, runner: CliRunner, initialized_data_path: str
    ) -> None:
        """daily가 정상 실행되면 exit code 0."""
        with patch("ante.feed.cli._build_orchestrator") as mock_build:
            mock_orch = AsyncMock()
            mock_orch.run_daily = AsyncMock(return_value=_DAILY_RESULT)
            mock_build.return_value = mock_orch

            result = runner.invoke(
                cli,
                ["feed", "run", "daily", "--data-path", initialized_data_path],
                catch_exceptions=False,
            )
            assert result.exit_code == 0

    def test_calls_orchestrator_run_daily(
        self, runner: CliRunner, initialized_data_path: str
    ) -> None:
        """FeedOrchestrator.run_daily가 호출된다."""
        with patch("ante.feed.cli._build_orchestrator") as mock_build:
            mock_orch = AsyncMock()
            mock_orch.run_daily = AsyncMock(return_value=_DAILY_RESULT)
            mock_build.return_value = mock_orch

            runner.invoke(
                cli,
                ["feed", "run", "daily", "--data-path", initialized_data_path],
                catch_exceptions=False,
            )

            mock_orch.run_daily.assert_awaited_once()

    def test_output_contains_daily_summary(
        self, runner: CliRunner, initialized_data_path: str
    ) -> None:
        """출력에 Daily 수집 결과가 포함된다."""
        with patch("ante.feed.cli._build_orchestrator") as mock_build:
            mock_orch = AsyncMock()
            mock_orch.run_daily = AsyncMock(return_value=_DAILY_RESULT)
            mock_build.return_value = mock_orch

            result = runner.invoke(
                cli,
                ["feed", "run", "daily", "--data-path", initialized_data_path],
                catch_exceptions=False,
            )

            assert "Daily" in result.output
            assert "98/100" in result.output

    def test_date_option(self, runner: CliRunner, initialized_data_path: str) -> None:
        """--date 옵션으로 수집 대상일을 지정할 수 있다."""
        custom_result = CollectionResult(
            mode="daily",
            started_at="2026-03-18T00:00:00Z",
            finished_at="2026-03-18T00:00:01Z",
            duration_seconds=1.0,
            target_date="2026-01-15",
        )

        with patch("ante.feed.cli._build_orchestrator") as mock_build:
            mock_orch = AsyncMock()
            mock_orch.run_daily = AsyncMock(return_value=custom_result)
            mock_build.return_value = mock_orch

            result = runner.invoke(
                cli,
                [
                    "feed",
                    "run",
                    "daily",
                    "--data-path",
                    initialized_data_path,
                    "--date",
                    "2026-01-15",
                ],
                catch_exceptions=False,
            )

            assert result.exit_code == 0

    def test_not_initialized_error(
        self, runner: CliRunner, uninitialized_data_path: str
    ) -> None:
        """초기화되지 않은 상태에서 실행하면 에러."""
        result = runner.invoke(
            cli,
            ["feed", "run", "daily", "--data-path", uninitialized_data_path],
        )
        assert result.exit_code != 0

    def test_json_output(self, runner: CliRunner, initialized_data_path: str) -> None:
        """--format json 출력이 올바르다."""
        import json

        with patch("ante.feed.cli._build_orchestrator") as mock_build:
            mock_orch = AsyncMock()
            mock_orch.run_daily = AsyncMock(return_value=_DAILY_RESULT)
            mock_build.return_value = mock_orch

            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "feed",
                    "run",
                    "daily",
                    "--data-path",
                    initialized_data_path,
                ],
                catch_exceptions=False,
            )

            data = json.loads(result.output)
            assert data["mode"] == "daily"
            assert data["target_date"] == "2026-03-17"
            assert data["symbols_success"] == 98


# ── ante feed start ──────────────────────────────────────────────────────


class TestFeedStart:
    def test_not_initialized_error(
        self, runner: CliRunner, uninitialized_data_path: str
    ) -> None:
        """초기화되지 않은 상태에서 실행하면 에러."""
        result = runner.invoke(
            cli,
            ["feed", "start", "--data-path", uninitialized_data_path],
        )
        assert result.exit_code != 0

    def test_help_shows_description(self, runner: CliRunner) -> None:
        """--help에 상주 프로세스 설명이 포함된다."""
        result = runner.invoke(
            cli,
            ["feed", "start", "--help"],
        )
        assert result.exit_code == 0
        assert "스케줄러" in result.output


# ── ante feed run --help ─────────────────────────────────────────────────


class TestRunHelp:
    def test_run_group_help(self, runner: CliRunner) -> None:
        """feed run --help에 backfill/daily 서브커맨드가 표시된다."""
        result = runner.invoke(
            cli,
            ["feed", "run", "--help"],
        )
        assert result.exit_code == 0
        assert "backfill" in result.output
        assert "daily" in result.output

    def test_backfill_help(self, runner: CliRunner) -> None:
        """feed run backfill --help에 옵션이 표시된다."""
        result = runner.invoke(
            cli,
            ["feed", "run", "backfill", "--help"],
        )
        assert result.exit_code == 0
        assert "--since" in result.output
        assert "--data-path" in result.output

    def test_daily_help(self, runner: CliRunner) -> None:
        """feed run daily --help에 옵션이 표시된다."""
        result = runner.invoke(
            cli,
            ["feed", "run", "daily", "--help"],
        )
        assert result.exit_code == 0
        assert "--date" in result.output
        assert "--data-path" in result.output
