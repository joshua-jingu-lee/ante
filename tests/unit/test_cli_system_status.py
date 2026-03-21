"""ante system status --format json 테스트.

이슈 #663: system status 커맨드에 --format json 옵션 추가 검증.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

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


@pytest.fixture()
def runner() -> CliRunner:
    """인증된 상태의 CliRunner."""
    r = CliRunner()
    original_invoke = r.invoke

    def _invoke_with_auth(cli_cmd, args=None, **kwargs):  # noqa: ANN001, ANN202
        with patch("ante.cli.main.authenticate_member") as mock_auth:

            def _set_member(ctx):  # noqa: ANN001
                ctx.obj = ctx.obj or {}
                ctx.obj["member"] = _MOCK_MASTER

            mock_auth.side_effect = _set_member
            return original_invoke(cli_cmd, args, **kwargs)

    r.invoke = _invoke_with_auth
    return r


def _mock_db() -> MagicMock:
    db = MagicMock()
    db.connect = AsyncMock()
    db.close = AsyncMock()
    db.fetch_one = AsyncMock(return_value={"cnt": 3})
    return db


class TestSystemStatusFormatJson:
    """ante system status --format json."""

    def test_format_after_subcommand(self, runner: CliRunner) -> None:
        """system status --format json 이 올바르게 JSON 출력."""
        from ante.account.models import AccountStatus

        db = _mock_db()
        eventbus = MagicMock()

        mock_account = MagicMock()
        mock_account.status = AccountStatus.ACTIVE

        svc = MagicMock()
        svc.initialize = AsyncMock()
        svc.list = AsyncMock(return_value=[mock_account])

        with (
            patch(
                "ante.cli.commands.system._create_services",
                new_callable=AsyncMock,
                return_value=(db, eventbus),
            ),
            patch(
                "ante.account.service.AccountService",
                return_value=svc,
            ),
        ):
            result = runner.invoke(cli, ["system", "status", "--format", "json"])
            assert result.exit_code == 0, result.output
            data = json.loads(result.output)
            assert "trading_state" in data
            assert "bot_count" in data
            assert data["trading_state"] == "active"
            assert data["bot_count"] == 3

    def test_format_before_subcommand(self, runner: CliRunner) -> None:
        """--format json system status (루트 옵션) 도 동작."""
        from ante.account.models import AccountStatus

        db = _mock_db()
        eventbus = MagicMock()

        mock_account = MagicMock()
        mock_account.status = AccountStatus.SUSPENDED

        svc = MagicMock()
        svc.initialize = AsyncMock()
        svc.list = AsyncMock(return_value=[mock_account])

        with (
            patch(
                "ante.cli.commands.system._create_services",
                new_callable=AsyncMock,
                return_value=(db, eventbus),
            ),
            patch(
                "ante.account.service.AccountService",
                return_value=svc,
            ),
        ):
            result = runner.invoke(cli, ["--format", "json", "system", "status"])
            assert result.exit_code == 0, result.output
            data = json.loads(result.output)
            assert data["trading_state"] == "suspended"

    def test_text_format_default(self, runner: CliRunner) -> None:
        """기본(text) 형식 출력 확인."""
        from ante.account.models import AccountStatus

        db = _mock_db()
        eventbus = MagicMock()

        mock_account = MagicMock()
        mock_account.status = AccountStatus.ACTIVE

        svc = MagicMock()
        svc.initialize = AsyncMock()
        svc.list = AsyncMock(return_value=[mock_account])

        with (
            patch(
                "ante.cli.commands.system._create_services",
                new_callable=AsyncMock,
                return_value=(db, eventbus),
            ),
            patch(
                "ante.account.service.AccountService",
                return_value=svc,
            ),
        ):
            result = runner.invoke(cli, ["system", "status"])
            assert result.exit_code == 0, result.output
            assert "거래 상태" in result.output
            assert "봇 수" in result.output
