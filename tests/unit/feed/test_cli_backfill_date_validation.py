"""ante feed run backfill/daily 날짜 옵션 CLI 검증 테스트.

이슈 #1536: invalid ISO date 입력 시 CLI 경계에서 거부하고
traceback이 stderr에 노출되지 않아야 한다 (`--since`).
이슈 #1562: #1536 follow-up — `run daily --date`도
동일하게 CLI 경계에서 거부하고, 모든 날짜 옵션은 `CLI_INVALID_DATE` 단일 코드로 통일.
"""

from __future__ import annotations

import json
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

_EMPTY_DAILY_RESULT = CollectionResult(
    mode="daily",
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


@pytest.fixture
def runner() -> CliRunner:
    """인증된 상태의 CliRunner. stderr 분리 캡처."""
    r = CliRunner(mix_stderr=False)
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

    (feed_dir / "checkpoints").mkdir()
    (feed_dir / "reports").mkdir()

    return str(data_dir)


class TestBackfillSinceValidation:
    """`--since` 옵션 ISO date 검증 (이슈 #1536)."""

    def test_invalid_since_json_mode_returns_structured_error(
        self, runner: CliRunner, initialized_data_path: str
    ) -> None:
        """JSON 모드에서 invalid --since는 status=error JSON, exit 1, traceback 없음."""
        with patch("ante.feed.cli._build_orchestrator") as mock_build:
            # orchestrator 자체는 호출되어선 안 된다 — CLI 단계에서 차단
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
                    "--since",
                    "not-a-date",
                ],
                catch_exceptions=False,
            )

            assert result.exit_code == 1
            # stderr에 traceback이 노출되지 않아야 한다
            assert "Traceback" not in (result.stderr or "")
            # stdout에 구조화된 JSON 에러
            data = json.loads(result.stdout)
            assert data["status"] == "error"
            assert data["code"] == "CLI_INVALID_DATE"
            assert "not-a-date" in data["message"]
            # orchestrator는 호출되지 않아야 한다
            mock_orch.run_backfill.assert_not_awaited()

    def test_invalid_since_text_mode_writes_error_to_stderr(
        self, runner: CliRunner, initialized_data_path: str
    ) -> None:
        """text 모드에서 invalid --since는 stderr Error, exit 1, traceback 없음."""
        with patch("ante.feed.cli._build_orchestrator") as mock_build:
            mock_orch = AsyncMock()
            mock_orch.run_backfill = AsyncMock(return_value=_EMPTY_RESULT)
            mock_build.return_value = mock_orch

            result = runner.invoke(
                cli,
                [
                    "feed",
                    "run",
                    "backfill",
                    "--data-path",
                    initialized_data_path,
                    "--since",
                    "not-a-date",
                ],
                catch_exceptions=False,
            )

            assert result.exit_code == 1
            stderr = result.stderr or ""
            assert "Traceback" not in stderr
            assert "Error:" in stderr
            assert "잘못된 --since 날짜 형식" in stderr
            assert "not-a-date" in stderr
            mock_orch.run_backfill.assert_not_awaited()

    def test_valid_iso_since_passes_through_to_orchestrator(
        self, runner: CliRunner, initialized_data_path: str
    ) -> None:
        """정상 ISO date(--since 2026-01-01)는 orchestrator.run_backfill로 전달된다."""
        with patch("ante.feed.cli._build_orchestrator") as mock_build:
            mock_orch = AsyncMock()
            mock_orch.run_backfill = AsyncMock(return_value=_EMPTY_RESULT)
            mock_build.return_value = mock_orch

            result = runner.invoke(
                cli,
                [
                    "feed",
                    "run",
                    "backfill",
                    "--data-path",
                    initialized_data_path,
                    "--since",
                    "2026-01-01",
                ],
                catch_exceptions=False,
            )

            assert result.exit_code == 0
            mock_orch.run_backfill.assert_awaited_once()
            call_args = mock_orch.run_backfill.call_args
            config = call_args.kwargs["config"]
            assert config["schedule"]["backfill_since"] == "2026-01-01"

    def test_no_since_option_regression(
        self, runner: CliRunner, initialized_data_path: str
    ) -> None:
        """--since 미지정 시 기존 동작 유지 (검증 분기 우회)."""
        with patch("ante.feed.cli._build_orchestrator") as mock_build:
            mock_orch = AsyncMock()
            mock_orch.run_backfill = AsyncMock(return_value=_EMPTY_RESULT)
            mock_build.return_value = mock_orch

            result = runner.invoke(
                cli,
                [
                    "feed",
                    "run",
                    "backfill",
                    "--data-path",
                    initialized_data_path,
                ],
                catch_exceptions=False,
            )

            assert result.exit_code == 0
            mock_orch.run_backfill.assert_awaited_once()

    @pytest.mark.parametrize(
        "bad_value",
        [
            "20260510",  # basic ISO (no separators)
            "2026-W19-1",  # ISO week date (Codex P2 케이스)
            "2026-1-1",  # non-zero-padded
        ],
    )
    def test_iso_variant_since_rejected_strict(
        self, runner: CliRunner, initialized_data_path: str, bad_value: str
    ) -> None:
        """ISO 변형(basic/week/non-padded) --since는 strict 거부 (#1562 회귀).

        date.fromisoformat()만 쓰던 이전 구현이라면 통과했을 입력을 잠근다.
        """
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
                    "--since",
                    bad_value,
                ],
                catch_exceptions=False,
            )

            assert result.exit_code == 1
            assert "Traceback" not in (result.stderr or "")
            data = json.loads(result.stdout)
            assert data["status"] == "error"
            assert data["code"] == "CLI_INVALID_DATE"
            assert bad_value in data["message"]
            mock_orch.run_backfill.assert_not_awaited()

    def test_invalid_calendar_since_rejected(
        self, runner: CliRunner, initialized_data_path: str
    ) -> None:
        """형태는 맞지만 캘린더상 invalid(2026-13-01) --since는 거부."""
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
                    "--since",
                    "2026-13-01",
                ],
                catch_exceptions=False,
            )

            assert result.exit_code == 1
            data = json.loads(result.stdout)
            assert data["status"] == "error"
            assert data["code"] == "CLI_INVALID_DATE"
            mock_orch.run_backfill.assert_not_awaited()


class TestDailyDateValidation:
    """`run daily --date` 옵션 ISO date 검증 (이슈 #1562)."""

    def test_invalid_date_json_mode_returns_structured_error(
        self, runner: CliRunner, initialized_data_path: str
    ) -> None:
        """JSON 모드에서 invalid --date는 status=error JSON, exit 1, traceback 없음."""
        with patch("ante.feed.cli._build_orchestrator") as mock_build:
            mock_orch = AsyncMock()
            mock_orch.run_daily = AsyncMock(return_value=_EMPTY_DAILY_RESULT)
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
                    "--date",
                    "oracle-not-a-date",
                ],
                catch_exceptions=False,
            )

            assert result.exit_code == 1
            assert "Traceback" not in (result.stderr or "")
            data = json.loads(result.stdout)
            assert data["status"] == "error"
            assert data["code"] == "CLI_INVALID_DATE"
            assert "oracle-not-a-date" in data["message"]
            mock_orch.run_daily.assert_not_awaited()

    def test_invalid_date_text_mode_writes_error_to_stderr(
        self, runner: CliRunner, initialized_data_path: str
    ) -> None:
        """text 모드에서 invalid --date는 stderr Error, exit 1, traceback 없음."""
        with patch("ante.feed.cli._build_orchestrator") as mock_build:
            mock_orch = AsyncMock()
            mock_orch.run_daily = AsyncMock(return_value=_EMPTY_DAILY_RESULT)
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
                    "oracle-not-a-date",
                ],
                catch_exceptions=False,
            )

            assert result.exit_code == 1
            stderr = result.stderr or ""
            assert "Traceback" not in stderr
            assert "Error:" in stderr
            assert "잘못된 --date 날짜 형식" in stderr
            assert "oracle-not-a-date" in stderr
            mock_orch.run_daily.assert_not_awaited()

    def test_valid_iso_date_passes_through_to_orchestrator(
        self, runner: CliRunner, initialized_data_path: str
    ) -> None:
        """정상 ISO date(--date 2025-01-01)는 검증 통과해 orchestrator로 전달된다."""
        with patch("ante.feed.cli._build_orchestrator") as mock_build:
            mock_orch = AsyncMock()
            mock_orch.run_daily = AsyncMock(return_value=_EMPTY_DAILY_RESULT)
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
                    "2025-01-01",
                ],
                catch_exceptions=False,
            )

            assert result.exit_code == 0
            mock_orch.run_daily.assert_awaited_once()

    @pytest.mark.parametrize(
        "bad_value",
        [
            "20260510",  # basic ISO (no separators)
            "2026-W19-1",  # ISO week date — Codex P2 지적 케이스
            "2026-1-1",  # non-zero-padded
        ],
    )
    def test_iso_variant_date_rejected_strict(
        self, runner: CliRunner, initialized_data_path: str, bad_value: str
    ) -> None:
        """ISO 변형(basic/week/non-padded) --date는 strict 거부 (#1562 회귀).

        date.fromisoformat()만 쓰던 이전 구현이라면 `2026-W19-1` 등이
        통과해 원문이 그대로 하위 수집(basDt)으로 전달됐다.
        """
        with patch("ante.feed.cli._build_orchestrator") as mock_build:
            mock_orch = AsyncMock()
            mock_orch.run_daily = AsyncMock(return_value=_EMPTY_DAILY_RESULT)
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
                    "--date",
                    bad_value,
                ],
                catch_exceptions=False,
            )

            assert result.exit_code == 1
            assert "Traceback" not in (result.stderr or "")
            data = json.loads(result.stdout)
            assert data["status"] == "error"
            assert data["code"] == "CLI_INVALID_DATE"
            assert bad_value in data["message"]
            mock_orch.run_daily.assert_not_awaited()

    def test_invalid_calendar_date_rejected(
        self, runner: CliRunner, initialized_data_path: str
    ) -> None:
        """형태는 맞지만 캘린더상 invalid(2026-13-01) --date는 거부."""
        with patch("ante.feed.cli._build_orchestrator") as mock_build:
            mock_orch = AsyncMock()
            mock_orch.run_daily = AsyncMock(return_value=_EMPTY_DAILY_RESULT)
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
                    "--date",
                    "2026-13-01",
                ],
                catch_exceptions=False,
            )

            assert result.exit_code == 1
            data = json.loads(result.stdout)
            assert data["status"] == "error"
            assert data["code"] == "CLI_INVALID_DATE"
            mock_orch.run_daily.assert_not_awaited()

    def test_no_date_option_regression(
        self, runner: CliRunner, initialized_data_path: str
    ) -> None:
        """--date 미지정 시 기존 동작 유지 (검증 분기 우회)."""
        with patch("ante.feed.cli._build_orchestrator") as mock_build:
            mock_orch = AsyncMock()
            mock_orch.run_daily = AsyncMock(return_value=_EMPTY_DAILY_RESULT)
            mock_build.return_value = mock_orch

            result = runner.invoke(
                cli,
                [
                    "feed",
                    "run",
                    "daily",
                    "--data-path",
                    initialized_data_path,
                ],
                catch_exceptions=False,
            )

            assert result.exit_code == 0
            mock_orch.run_daily.assert_awaited_once()
