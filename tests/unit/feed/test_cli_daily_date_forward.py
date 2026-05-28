"""`ante feed run daily --date` CLI 회귀 테스트.

#1943: monkey-patch 무효로 ``--date`` 가 무시되던 버그를 명시 파라미터
chain으로 고친 변경의 end-to-end 회귀 잠금. orchestrator를 mock 으로 두고
CLI 가 ``target_date`` 를 keyword 인자로 전달하는지만 검증한다.
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


@pytest.fixture
def runner() -> CliRunner:
    """인증된 상태의 CliRunner."""
    r = CliRunner()
    original_invoke = r.invoke

    def _invoke_with_auth(cli_cmd, args=None, **kwargs):  # type: ignore[no-untyped-def]
        with patch("ante.cli.main.authenticate_member") as mock_auth:

            def _set_member(_ctx: object) -> None:
                import click

                cur = click.get_current_context()
                cur.obj = cur.obj or {}
                cur.obj["member"] = _MOCK_MASTER

            mock_auth.side_effect = _set_member
            return original_invoke(cli_cmd, args, **kwargs)

    r.invoke = _invoke_with_auth  # type: ignore[method-assign]
    return r


@pytest.fixture
def initialized_data_path(tmp_path: Path) -> str:
    data_dir = tmp_path / "data"
    feed_dir = data_dir / ".feed"
    feed_dir.mkdir(parents=True)
    (feed_dir / "config.toml").write_text(
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


def _result_for(target_date: str | None) -> CollectionResult:
    return CollectionResult(
        mode="daily",
        started_at="2026-05-28T00:00:00Z",
        finished_at="2026-05-28T00:00:01Z",
        duration_seconds=1.0,
        target_date=target_date,
    )


def test_cli_forwards_explicit_date_to_orchestrator(
    runner: CliRunner, initialized_data_path: str
) -> None:
    """``--date 2024-12-30`` 가 ``run_daily(target_date=...)`` 로 전달된다."""
    with patch("ante.feed.cli._build_orchestrator") as mock_build:
        mock_orch = AsyncMock()
        mock_orch.run_daily = AsyncMock(return_value=_result_for("2024-12-30"))
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
                "2024-12-30",
            ],
            catch_exceptions=False,
        )

    assert result.exit_code == 0
    mock_orch.run_daily.assert_awaited_once()
    kwargs = mock_orch.run_daily.await_args.kwargs
    assert kwargs.get("target_date") == "2024-12-30"


def test_cli_without_date_forwards_none(
    runner: CliRunner, initialized_data_path: str
) -> None:
    """``--date`` 미지정 시 ``target_date=None`` 으로 전달된다."""
    with patch("ante.feed.cli._build_orchestrator") as mock_build:
        mock_orch = AsyncMock()
        mock_orch.run_daily = AsyncMock(return_value=_result_for("2026-05-27"))
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
    kwargs = mock_orch.run_daily.await_args.kwargs
    assert kwargs.get("target_date") is None
