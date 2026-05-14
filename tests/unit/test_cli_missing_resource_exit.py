"""CLI missing-resource 경로의 nonzero exit code 보장 테스트 (#1515).

이슈 #1515 (oracle A7 cli_lookup_errors_exit_zero):
``trade info``, ``config get``, ``bot info``, ``bot signal-key``, ``member info``
5개 조회 명령이 missing-resource를 JSON error로 출력하면서도 exit code 0으로
종료되던 ingress drift를 닫는다. 각 호출자가 ``fmt.error(...)`` 출력 후
``ctx.exit(1)``을 호출해 nonzero exit를 강제한다.

분류 메모:
- ``trade info``, ``config get``, ``member info``는 offline CLI (IPC route 없음).
- ``bot info`` / ``bot signal-key``는 spec ``docs/specs/cli/03-commands.md``상
  ``runtime IPC + snapshot fallback`` 분류이지만, 본 PR의 target 경로(missing case)는
  DB 직접 조회 경로 — IPC 동작 변경 없음.
- ``report view``, ``treasury snapshot``도 같은 ``fmt.error(...) ; return`` 패턴이
  잔존하지만 oracle probe signature에 미포함되어 본 PR Non-Goals (follow-up 후보).
- ``Formatter.error()`` 자체는 미변경 — ``strategy validate`` 등 ``fmt.error`` 후
  추가 errors/warnings를 계속 출력하는 호출자 회귀 회피.
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
    """인증을 mock으로 우회한 CliRunner.

    stderr/stdout 분리(``mix_stderr=False``)로 text 모드 ``Error:`` 메시지가
    stderr로 가는지 확인 가능하게 한다.
    """
    r = CliRunner(mix_stderr=False)
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
    return db


# ── trade info ───────────────────────────────────────────


class TestTradeInfoMissingExit:
    """``ante trade info <missing>`` 은 exit 1 + JSON error envelope."""

    def test_missing_exits_nonzero_json(self, runner: CliRunner) -> None:
        mock_db = MagicMock()
        mock_db.connect = AsyncMock()
        mock_db.close = AsyncMock()
        mock_db.fetch_one = AsyncMock(return_value=None)

        with patch(
            "ante.core.database.Database",
            return_value=mock_db,
        ):
            result = runner.invoke(
                cli, ["trade", "info", "nonexistent-trade", "--format", "json"]
            )

        assert result.exit_code == 1, result.output
        payload = json.loads(result.stdout)
        assert payload["status"] == "error"
        assert "nonexistent-trade" in payload["message"]

    def test_missing_exits_nonzero_text(self, runner: CliRunner) -> None:
        mock_db = AsyncMock()
        mock_db.connect = AsyncMock()
        mock_db.close = AsyncMock()
        mock_db.fetch_one = AsyncMock(return_value=None)

        with patch(
            "ante.core.database.Database",
            return_value=mock_db,
        ):
            result = runner.invoke(cli, ["trade", "info", "nonexistent-trade"])

        assert result.exit_code == 1
        assert "Error:" in result.stderr

    def test_valid_exits_zero(self, runner: CliRunner) -> None:
        """존재하는 trade는 exit 0으로 회귀 보존."""
        mock_db = AsyncMock()
        mock_db.connect = AsyncMock()
        mock_db.close = AsyncMock()
        mock_db.fetch_one = AsyncMock(
            return_value={
                "trade_id": "t-1",
                "bot_id": "b-1",
                "symbol": "AAPL",
                "side": "BUY",
                "quantity": 10,
                "price": 150.0,
                "status": "filled",
            }
        )

        with patch(
            "ante.core.database.Database",
            return_value=mock_db,
        ):
            result = runner.invoke(cli, ["trade", "info", "t-1", "--format", "json"])

        assert result.exit_code == 0, result.stdout + result.stderr
        payload = json.loads(result.stdout)
        assert payload["trade_id"] == "t-1"


# ── config get ───────────────────────────────────────────


class TestConfigGetMissingExit:
    """``ante config get <missing.key>`` 은 exit 1 (caller-level exit)."""

    def test_missing_exits_nonzero_json(self, runner: CliRunner) -> None:
        mock_config = MagicMock()
        mock_config.get.return_value = None  # static 조회 실패
        mock_dynamic = AsyncMock()
        mock_dynamic.exists = AsyncMock(return_value=False)
        mock_db = AsyncMock()
        mock_db.close = AsyncMock()

        with patch(
            "ante.cli.commands.config._create_services",
            new_callable=AsyncMock,
            return_value=(mock_config, mock_dynamic, mock_db),
        ):
            result = runner.invoke(
                cli, ["config", "get", "nonexistent.key", "--format", "json"]
            )

        assert result.exit_code == 1, result.output
        payload = json.loads(result.stdout)
        assert payload["status"] == "error"
        assert "nonexistent.key" in payload["message"]

    def test_missing_exits_nonzero_text(self, runner: CliRunner) -> None:
        mock_config = MagicMock()
        mock_config.get.return_value = None
        mock_dynamic = AsyncMock()
        mock_dynamic.exists = AsyncMock(return_value=False)
        mock_db = AsyncMock()
        mock_db.close = AsyncMock()

        with patch(
            "ante.cli.commands.config._create_services",
            new_callable=AsyncMock,
            return_value=(mock_config, mock_dynamic, mock_db),
        ):
            result = runner.invoke(cli, ["config", "get", "nonexistent.key"])

        assert result.exit_code == 1
        assert "Error:" in result.stderr

    def test_valid_exits_zero(self, runner: CliRunner) -> None:
        """존재하는 static config 키는 exit 0으로 회귀 보존."""
        mock_config = MagicMock()
        mock_config.get.return_value = "hello"
        mock_dynamic = AsyncMock()
        mock_dynamic.exists = AsyncMock(return_value=False)
        mock_db = AsyncMock()
        mock_db.close = AsyncMock()

        with patch(
            "ante.cli.commands.config._create_services",
            new_callable=AsyncMock,
            return_value=(mock_config, mock_dynamic, mock_db),
        ):
            result = runner.invoke(
                cli, ["config", "get", "some.key", "--format", "json"]
            )

        assert result.exit_code == 0, result.stdout + result.stderr
        payload = json.loads(result.stdout)
        assert payload["key"] == "some.key"
        assert payload["value"] == "hello"
        assert payload["source"] == "static"


# ── bot info ─────────────────────────────────────────────


class TestBotInfoMissingExit:
    """``ante bot info <missing>`` 은 exit 1.

    target 경로는 DB 직접 조회 (`bot.py:128`) — IPC 분기 미경유.
    """

    def test_missing_exits_nonzero_json(self, runner: CliRunner) -> None:
        mock_db = AsyncMock()
        mock_db.close = AsyncMock()
        mock_db.fetch_one = AsyncMock(return_value=None)

        with patch(
            "ante.cli.commands.bot._create_services",
            new_callable=AsyncMock,
            return_value=(mock_db, None, None, None),
        ):
            result = runner.invoke(
                cli, ["--format", "json", "bot", "info", "nonexistent-bot"]
            )

        assert result.exit_code == 1, result.output
        payload = json.loads(result.stdout)
        assert payload["status"] == "error"
        assert "nonexistent-bot" in payload["message"]

    def test_missing_exits_nonzero_text(self, runner: CliRunner) -> None:
        mock_db = AsyncMock()
        mock_db.close = AsyncMock()
        mock_db.fetch_one = AsyncMock(return_value=None)

        with patch(
            "ante.cli.commands.bot._create_services",
            new_callable=AsyncMock,
            return_value=(mock_db, None, None, None),
        ):
            result = runner.invoke(cli, ["bot", "info", "nonexistent-bot"])

        assert result.exit_code == 1
        assert "Error:" in result.stderr

    def test_valid_exits_zero(self, runner: CliRunner) -> None:
        """존재하는 봇은 exit 0으로 회귀 보존."""
        mock_db = AsyncMock()
        mock_db.close = AsyncMock()
        mock_db.fetch_one = AsyncMock(
            return_value={
                "bot_id": "b-1",
                "name": "test-bot",
                "strategy_id": "s-1",
                "account_id": "a-1",
                "status": "active",
                "created_at": "2026-01-01T00:00:00",
            }
        )

        with patch(
            "ante.cli.commands.bot._create_services",
            new_callable=AsyncMock,
            return_value=(mock_db, None, None, None),
        ):
            result = runner.invoke(cli, ["bot", "info", "b-1"])

        assert result.exit_code == 0, result.stdout + result.stderr
        assert "b-1" in result.stdout


# ── bot signal-key ───────────────────────────────────────


class TestBotSignalKeyMissingExit:
    """``ante bot signal-key <bot-without-key>`` 은 exit 1."""

    def test_missing_exits_nonzero_json(self, runner: CliRunner) -> None:
        mock_db = AsyncMock()
        mock_db.close = AsyncMock()
        mock_skm = AsyncMock()
        mock_skm.initialize = AsyncMock()
        mock_skm.get_key = AsyncMock(return_value=None)

        with (
            patch(
                "ante.cli.commands.bot._create_services",
                new_callable=AsyncMock,
                return_value=(mock_db, None, None, None),
            ),
            patch(
                "ante.bot.signal_key.SignalKeyManager",
                return_value=mock_skm,
            ),
        ):
            result = runner.invoke(
                cli,
                ["--format", "json", "bot", "signal-key", "bot-without-key"],
            )

        assert result.exit_code == 1, result.output
        payload = json.loads(result.stdout)
        assert payload["status"] == "error"
        assert "bot-without-key" in payload["message"]

    def test_missing_exits_nonzero_text(self, runner: CliRunner) -> None:
        mock_db = AsyncMock()
        mock_db.close = AsyncMock()
        mock_skm = AsyncMock()
        mock_skm.initialize = AsyncMock()
        mock_skm.get_key = AsyncMock(return_value=None)

        with (
            patch(
                "ante.cli.commands.bot._create_services",
                new_callable=AsyncMock,
                return_value=(mock_db, None, None, None),
            ),
            patch(
                "ante.bot.signal_key.SignalKeyManager",
                return_value=mock_skm,
            ),
        ):
            result = runner.invoke(cli, ["bot", "signal-key", "bot-without-key"])

        assert result.exit_code == 1
        assert "Error:" in result.stderr

    def test_valid_exits_zero(self, runner: CliRunner) -> None:
        """signal_key 존재 시 exit 0 회귀 보존."""
        mock_db = AsyncMock()
        mock_db.close = AsyncMock()
        mock_skm = AsyncMock()
        mock_skm.initialize = AsyncMock()
        mock_skm.get_key = AsyncMock(return_value="sk_test123")

        with (
            patch(
                "ante.cli.commands.bot._create_services",
                new_callable=AsyncMock,
                return_value=(mock_db, None, None, None),
            ),
            patch(
                "ante.bot.signal_key.SignalKeyManager",
                return_value=mock_skm,
            ),
        ):
            result = runner.invoke(
                cli, ["--format", "json", "bot", "signal-key", "b-1"]
            )

        assert result.exit_code == 0, result.stdout + result.stderr
        payload = json.loads(result.stdout)
        assert payload["signal_key"] == "sk_test123"


# ── member info ──────────────────────────────────────────


class TestMemberInfoMissingExit:
    """``ante member info <missing>`` 은 exit 1."""

    def test_missing_exits_nonzero_json(self, runner: CliRunner) -> None:
        svc = MagicMock()
        svc.get = AsyncMock(return_value=None)
        db = _mock_db()

        with patch(
            "ante.cli.commands.member._create_service",
            new_callable=AsyncMock,
            return_value=(svc, db),
        ):
            result = runner.invoke(
                cli,
                ["--format", "json", "member", "info", "nonexistent-member"],
            )

        assert result.exit_code == 1, result.output
        payload = json.loads(result.stdout)
        assert payload["status"] == "error"
        assert "nonexistent-member" in payload["message"]

    def test_missing_exits_nonzero_text(self, runner: CliRunner) -> None:
        svc = MagicMock()
        svc.get = AsyncMock(return_value=None)
        db = _mock_db()

        with patch(
            "ante.cli.commands.member._create_service",
            new_callable=AsyncMock,
            return_value=(svc, db),
        ):
            result = runner.invoke(cli, ["member", "info", "nonexistent-member"])

        assert result.exit_code == 1
        assert "Error:" in result.stderr

    def test_valid_exits_zero(self, runner: CliRunner) -> None:
        """존재하는 member는 exit 0 회귀 보존."""
        existing = Member(
            member_id="m-1",
            type=MemberType.HUMAN,
            role=MemberRole.DEFAULT,
            org="default",
            name="Existing",
            status="active",
            scopes=[],
        )
        svc = MagicMock()
        svc.get = AsyncMock(return_value=existing)
        db = _mock_db()

        with patch(
            "ante.cli.commands.member._create_service",
            new_callable=AsyncMock,
            return_value=(svc, db),
        ):
            result = runner.invoke(cli, ["--format", "json", "member", "info", "m-1"])

        assert result.exit_code == 0, result.stdout + result.stderr
        payload = json.loads(result.stdout)
        assert payload["member_id"] == "m-1"
