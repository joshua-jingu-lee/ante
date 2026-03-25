"""CLI --format json 서브커맨드 뒤 배치 테스트.

이슈 #632: QA TC에서 `ante account list --format json` 형태로 호출할 때
서브커맨드 뒤의 --format 옵션이 올바르게 동작하는지 검증한다.
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
    return db


# ── member list --format json ────────────────────────────


class TestMemberListFormatOption:
    """ante member list --format json (서브커맨드 뒤 배치)."""

    def test_format_after_subcommand(self, runner: CliRunner) -> None:
        """member list --format json 이 올바르게 JSON 출력."""
        svc = MagicMock()
        db = _mock_db()
        svc.list = AsyncMock(return_value=[])

        with patch(
            "ante.cli.commands.member._create_service",
            new_callable=AsyncMock,
            return_value=(svc, db),
        ):
            result = runner.invoke(cli, ["member", "list", "--format", "json"])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert "members" in data or "message" in data

    def test_format_before_subcommand_still_works(self, runner: CliRunner) -> None:
        """--format json member list (루트 옵션) 도 여전히 동작."""
        svc = MagicMock()
        db = _mock_db()
        svc.list = AsyncMock(return_value=[])

        with patch(
            "ante.cli.commands.member._create_service",
            new_callable=AsyncMock,
            return_value=(svc, db),
        ):
            result = runner.invoke(cli, ["--format", "json", "member", "list"])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert "members" in data or "message" in data


# ── member register --format json ────────────────────────


class TestMemberRegisterFormatOption:
    """ante member register ... --format json."""

    def test_register_format_after(self, runner: CliRunner) -> None:
        """register --format json 이 JSON 출력."""
        svc = MagicMock()
        db = _mock_db()
        mock_member = MagicMock()
        mock_member.member_id = "new-agent"
        mock_member.type = "agent"
        mock_member.role = "member"
        mock_member.org = "default"
        mock_member.name = "Agent"
        svc.register = AsyncMock(return_value=(mock_member, "token-123"))

        with patch(
            "ante.cli.commands.member._create_service",
            new_callable=AsyncMock,
            return_value=(svc, db),
        ):
            result = runner.invoke(
                cli,
                [
                    "member",
                    "register",
                    "--id",
                    "new-agent",
                    "--type",
                    "agent",
                    "--format",
                    "json",
                ],
            )
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["member_id"] == "new-agent"
            assert data["token"] == "token-123"


# ── account list --format json ────────────────────────────


class TestAccountListFormatOption:
    """ante account list --format json."""

    def test_format_after_subcommand(self, runner: CliRunner) -> None:
        svc = AsyncMock()
        db = _mock_db()
        svc.list.return_value = []

        with patch(
            "ante.cli.commands.account._create_account_service",
            new_callable=AsyncMock,
            return_value=(svc, db),
        ):
            result = runner.invoke(cli, ["account", "list", "--format", "json"])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert "accounts" in data or "message" in data


# ── account info --format json ────────────────────────────


class TestAccountInfoFormatOption:
    """ante account info {id} --format json."""

    def test_format_after_subcommand(self, runner: CliRunner) -> None:
        from decimal import Decimal

        from ante.account.models import Account, AccountStatus, TradingMode

        svc = AsyncMock()
        db = _mock_db()
        svc.get.return_value = Account(
            account_id="test-acct",
            name="테스트",
            exchange="KRX",
            currency="KRW",
            broker_type="mock",
            status=AccountStatus.ACTIVE,
            trading_mode=TradingMode.VIRTUAL,
            credentials={},
            buy_commission_rate=Decimal("0.00015"),
            sell_commission_rate=Decimal("0.00195"),
        )

        with patch(
            "ante.cli.commands.account._create_account_service",
            new_callable=AsyncMock,
            return_value=(svc, db),
        ):
            result = runner.invoke(
                cli, ["account", "info", "test-acct", "--format", "json"]
            )
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["account_id"] == "test-acct"


# ── account delete --yes ──────────────────────────────


class TestAccountDeleteYes:
    """ante account delete {id} --yes."""

    def test_delete_with_yes_skips_confirm(self, runner: CliRunner) -> None:
        mock_response = {"status": "ok", "data": {}}

        with patch(
            "ante.cli.commands.ipc_helpers.IPCClient", autospec=True
        ) as mock_cls:
            mock_client = AsyncMock()
            mock_client.send.return_value = mock_response
            mock_cls.return_value = mock_client

            with patch(
                "ante.cli.commands.ipc_helpers.get_socket_path",
                return_value="/tmp/test.sock",
            ):
                result = runner.invoke(cli, ["account", "delete", "test-acct", "--yes"])

        assert result.exit_code == 0
        assert "삭제 완료" in result.output
        mock_client.send.assert_called_once()

    def test_delete_without_yes_prompts(self, runner: CliRunner) -> None:
        """--yes 없이 호출하면 확인 프롬프트가 나타남."""
        mock_response = {"status": "ok", "data": {}}

        with patch(
            "ante.cli.commands.ipc_helpers.IPCClient", autospec=True
        ) as mock_cls:
            mock_client = AsyncMock()
            mock_client.send.return_value = mock_response
            mock_cls.return_value = mock_client

            with patch(
                "ante.cli.commands.ipc_helpers.get_socket_path",
                return_value="/tmp/test.sock",
            ):
                result = runner.invoke(
                    cli, ["account", "delete", "test-acct"], input="y\n"
                )

        assert result.exit_code == 0
        assert "삭제 완료" in result.output


# ── treasury status --format json ─────────────────────────


class TestTreasuryStatusFormatOption:
    """ante treasury status --format json."""

    def test_format_after_subcommand(self, runner: CliRunner) -> None:
        mock_treasury = MagicMock()
        db = _mock_db()
        mock_treasury.get_summary.return_value = {
            "account_balance": 1000000,
            "purchasable_amount": 800000,
            "total_evaluation": 1200000,
            "total_profit_loss": 200000,
            "total_allocated": 500000,
            "total_reserved": 100000,
            "unallocated": 300000,
            "bot_count": 2,
        }

        with patch(
            "ante.cli.commands.treasury._create_treasury",
            new_callable=AsyncMock,
            return_value=(mock_treasury, db),
        ):
            result = runner.invoke(cli, ["treasury", "status", "--format", "json"])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["account_balance"] == 1000000
            assert data["bot_count"] == 2


# ── strategy list --format json ───────────────────────────


class TestStrategyListFormatOption:
    """ante strategy list --format json."""

    def test_format_after_subcommand(self, runner: CliRunner) -> None:
        db = _mock_db()
        registry = MagicMock()
        registry.list_strategies = AsyncMock(return_value=[])

        with patch(
            "ante.cli.commands.strategy._create_registry",
            new_callable=AsyncMock,
            return_value=(registry, db),
        ):
            result = runner.invoke(cli, ["strategy", "list", "--format", "json"])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert "strategies" in data or "message" in data


# ── strategy info --format json ───────────────────────────


class TestStrategyInfoFormatOption:
    """ante strategy info {name} --format json."""

    def test_format_after_subcommand(self, runner: CliRunner) -> None:
        from datetime import UTC, datetime

        from ante.strategy.registry import StrategyRecord, StrategyStatus

        db = _mock_db()
        record = StrategyRecord(
            strategy_id="test_v1.0",
            name="test",
            version="1.0",
            filepath="/strats/test.py",
            status=StrategyStatus.ACTIVE,
            registered_at=datetime(2026, 1, 1, tzinfo=UTC),
            description="테스트 전략",
            author_name="agent",
            author_id="agent",
            validation_warnings=[],
        )
        registry = MagicMock()
        registry.get_by_name = AsyncMock(return_value=[record])

        with (
            patch(
                "ante.cli.commands.strategy._create_registry",
                new_callable=AsyncMock,
                return_value=(registry, db),
            ),
            patch(
                "ante.cli.commands.strategy._load_strategy_params",
                return_value=None,
            ),
        ):
            result = runner.invoke(
                cli, ["strategy", "info", "test", "--format", "json"]
            )
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["name"] == "test"


# ── config get --format json ──────────────────────────────


class TestConfigGetFormatOption:
    """ante config get --format json."""

    def test_format_after_subcommand(self, runner: CliRunner) -> None:
        mock_config = MagicMock()
        mock_config.get.side_effect = lambda k, d=None: d
        mock_dynamic = AsyncMock()
        mock_db = AsyncMock()
        mock_db.fetch_all = AsyncMock(return_value=[])
        mock_db.close = AsyncMock()

        with patch(
            "ante.cli.commands.config._create_services",
            new_callable=AsyncMock,
            return_value=(mock_config, mock_dynamic, mock_db),
        ):
            result = runner.invoke(cli, ["config", "get", "--format", "json"])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert "configs" in data


# ── config set --format json ──────────────────────────────


class TestConfigSetFormatOption:
    """ante config set KEY VALUE --format json."""

    def test_format_after_subcommand(self, runner: CliRunner) -> None:
        mock_client = AsyncMock()
        mock_client.send.return_value = {
            "id": "req-1",
            "status": "ok",
            "result": {"success": True, "key": "custom.key", "value": "hello"},
        }

        with (
            patch(
                "ante.cli.commands.ipc_helpers.IPCClient",
                return_value=mock_client,
            ),
            patch(
                "ante.cli.commands.ipc_helpers.get_socket_path",
                return_value="/tmp/test.sock",
            ),
        ):
            result = runner.invoke(
                cli, ["config", "set", "custom.key", "hello", "--format", "json"]
            )
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["success"] is True


# ── config history --format json ──────────────────────────


class TestConfigHistoryFormatOption:
    """ante config history KEY --format json."""

    def test_format_after_subcommand(self, runner: CliRunner) -> None:
        mock_config = MagicMock()
        mock_dynamic = AsyncMock()
        mock_dynamic.get_history = AsyncMock(return_value=[])
        mock_db = AsyncMock()
        mock_db.close = AsyncMock()

        with patch(
            "ante.cli.commands.config._create_services",
            new_callable=AsyncMock,
            return_value=(mock_config, mock_dynamic, mock_db),
        ):
            result = runner.invoke(
                cli,
                ["config", "history", "risk.test_qa_key", "--format", "json"],
            )
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["key"] == "risk.test_qa_key"
            assert data["history"] == []


# ── trade list --format json ──────────────────────────────


class TestTradeListFormatOption:
    """ante trade list --format json."""

    def test_format_after_subcommand(self, runner: CliRunner) -> None:
        svc = MagicMock()
        db = _mock_db()
        svc.get_trades = AsyncMock(return_value=[])

        with patch(
            "ante.cli.commands.trade._create_trade_service",
            new_callable=AsyncMock,
            return_value=(svc, db),
        ):
            result = runner.invoke(cli, ["trade", "list", "--format", "json"])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert "trades" in data or "message" in data


# ── trade info --format json ──────────────────────────────


class TestTradeInfoFormatOption:
    """ante trade info {id} --format json."""

    def test_format_after_subcommand(self, runner: CliRunner) -> None:
        mock_db = AsyncMock()
        mock_db.connect = AsyncMock()
        mock_db.close = AsyncMock()
        mock_db.fetch_one = AsyncMock(return_value=None)

        with patch(
            "ante.cli.commands.trade.asyncio.run",
            return_value=None,
        ):
            result = runner.invoke(
                cli, ["trade", "info", "trade-123", "--format", "json"]
            )
            assert result.exit_code == 0
            # Not found case produces JSON error
            data = json.loads(result.output)
            assert "error" in data


# ── account set-credentials 비대화형 테스트 ────────────────


class TestAccountSetCredentialsNonInteractive:
    """ante account set-credentials {id} --app-key KEY --app-secret SECRET."""

    def test_set_credentials_non_interactive(self, runner: CliRunner) -> None:
        from decimal import Decimal

        from ante.account.models import Account, AccountStatus, TradingMode

        svc = AsyncMock()
        db = _mock_db()
        svc.get.return_value = Account(
            account_id="test-acct",
            name="테스트",
            exchange="KRX",
            currency="KRW",
            broker_type="kis-domestic",
            status=AccountStatus.ACTIVE,
            trading_mode=TradingMode.VIRTUAL,
            credentials={},
            buy_commission_rate=Decimal("0.00015"),
            sell_commission_rate=Decimal("0.00195"),
        )

        with patch(
            "ante.cli.commands.account._create_account_service",
            new_callable=AsyncMock,
            return_value=(svc, db),
        ):
            result = runner.invoke(
                cli,
                [
                    "account",
                    "set-credentials",
                    "test-acct",
                    "--app-key",
                    "my-key",
                    "--app-secret",
                    "my-secret",
                    "--format",
                    "json",
                ],
            )
            assert result.exit_code == 0
            assert "재설정 완료" in result.output
            svc.update.assert_called_once()
            # 전달된 credentials 확인
            call_kwargs = svc.update.call_args
            creds = call_kwargs.kwargs.get("credentials") or call_kwargs[1].get(
                "credentials"
            )
            assert creds["app_key"] == "my-key"
            assert creds["app_secret"] == "my-secret"
