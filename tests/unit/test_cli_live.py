"""CLI 라이브 커맨드(system/bot/trade/treasury/rule/broker) 단위 테스트."""

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


@pytest.fixture
def runner():
    """인증된 상태의 CliRunner."""
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


# ── system 커맨드 ──────────────────────────────────


class TestSystemCommands:
    def _mock_account_service(self, suspended: bool = False):
        from ante.account.models import AccountStatus

        mock_svc = AsyncMock()
        mock_svc.initialize = AsyncMock()
        if suspended:
            from types import SimpleNamespace

            acct = SimpleNamespace(account_id="test", status=AccountStatus.SUSPENDED)
            mock_svc.list = AsyncMock(return_value=[acct])
        else:
            from types import SimpleNamespace

            acct = SimpleNamespace(account_id="test", status=AccountStatus.ACTIVE)
            mock_svc.list = AsyncMock(return_value=[acct])
        mock_svc.suspend_all = AsyncMock(return_value=1)
        mock_svc.activate_all = AsyncMock(return_value=1)
        return mock_svc

    def test_system_status(self, runner):
        with patch("ante.cli.commands.system._create_services") as mock_svc:
            mock_db = AsyncMock()
            mock_db.fetch_one = AsyncMock(return_value={"cnt": 3})
            mock_db.close = AsyncMock()
            mock_svc.return_value = (mock_db, MagicMock())

            with patch(
                "ante.account.service.AccountService",
                return_value=self._mock_account_service(suspended=False),
            ):
                result = runner.invoke(cli, ["system", "status"])
                assert result.exit_code == 0
                assert "active" in result.output

    def test_system_status_json(self, runner):
        with patch("ante.cli.commands.system._create_services") as mock_svc:
            mock_db = AsyncMock()
            mock_db.fetch_one = AsyncMock(return_value={"cnt": 2})
            mock_db.close = AsyncMock()
            mock_svc.return_value = (mock_db, MagicMock())

            with patch(
                "ante.account.service.AccountService",
                return_value=self._mock_account_service(suspended=False),
            ):
                result = runner.invoke(cli, ["--format", "json", "system", "status"])
                assert result.exit_code == 0
                data = json.loads(result.output)
                assert data["trading_state"] == "active"
                assert data["bot_count"] == 2

    def test_system_halt(self, runner):
        with patch("ante.cli.commands.system._create_services") as mock_svc:
            mock_db = AsyncMock()
            mock_db.close = AsyncMock()
            mock_svc.return_value = (mock_db, MagicMock())

            with patch(
                "ante.account.service.AccountService",
                return_value=self._mock_account_service(suspended=True),
            ):
                result = runner.invoke(cli, ["system", "halt", "--reason", "test halt"])
                assert result.exit_code == 0
                assert "HALTED" in result.output

    def test_system_activate(self, runner):
        with patch("ante.cli.commands.system._create_services") as mock_svc:
            mock_db = AsyncMock()
            mock_db.close = AsyncMock()
            mock_svc.return_value = (mock_db, MagicMock())

            with patch(
                "ante.account.service.AccountService",
                return_value=self._mock_account_service(suspended=False),
            ):
                result = runner.invoke(cli, ["system", "activate"])
                assert result.exit_code == 0
                assert "ACTIVE" in result.output


# ── bot 커맨드 ─────────────────────────────────────


class TestBotCommands:
    def test_bot_list_empty(self, runner):
        with patch("ante.cli.commands.bot._create_services") as mock_svc:
            mock_db = AsyncMock()
            mock_db.fetch_all = AsyncMock(return_value=[])
            mock_db.close = AsyncMock()
            mock_svc.return_value = (mock_db, MagicMock(), MagicMock())

            result = runner.invoke(cli, ["bot", "list"])
            assert result.exit_code == 0

    def test_bot_list_with_data(self, runner):
        with patch("ante.cli.commands.bot._create_services") as mock_svc:
            mock_db = AsyncMock()
            mock_db.fetch_all = AsyncMock(
                return_value=[
                    {
                        "bot_id": "bot-1",
                        "name": "테스트봇",
                        "strategy_id": "stg-1",
                        "account_id": "test",
                        "status": "created",
                        "created_at": "2026-01-01",
                    }
                ]
            )
            mock_db.close = AsyncMock()
            mock_svc.return_value = (mock_db, MagicMock(), MagicMock())

            result = runner.invoke(cli, ["--format", "json", "bot", "list"])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert len(data["bots"]) == 1
            assert data["bots"][0]["bot_id"] == "bot-1"

    def test_bot_info_not_found(self, runner):
        with patch("ante.cli.commands.bot._create_services") as mock_svc:
            mock_db = AsyncMock()
            mock_db.fetch_one = AsyncMock(return_value=None)
            mock_db.close = AsyncMock()
            mock_svc.return_value = (mock_db, MagicMock(), MagicMock())

            result = runner.invoke(cli, ["bot", "info", "nonexistent"])
            assert result.exit_code == 0
            assert "찾을 수 없습니다" in result.output

    def test_bot_info_found(self, runner):
        with patch("ante.cli.commands.bot._create_services") as mock_svc:
            mock_db = AsyncMock()
            mock_db.fetch_one = AsyncMock(
                return_value={
                    "bot_id": "bot-1",
                    "name": "테스트봇",
                    "strategy_id": "stg-1",
                    "account_id": "test",
                    "status": "running",
                    "created_at": "2026-01-01",
                    "config_json": "{}",
                    "auto_start": 0,
                    "updated_at": "2026-01-01",
                }
            )
            mock_db.close = AsyncMock()
            mock_svc.return_value = (mock_db, MagicMock(), MagicMock())

            result = runner.invoke(cli, ["bot", "info", "bot-1"])
            assert result.exit_code == 0
            assert "bot-1" in result.output

    def test_bot_create(self, runner):
        with patch("ante.cli.commands.bot._create_services") as mock_svc:
            mock_db = AsyncMock()
            mock_db.execute = AsyncMock()
            mock_db.close = AsyncMock()
            mock_svc.return_value = (mock_db, MagicMock(), MagicMock())

            result = runner.invoke(
                cli,
                [
                    "bot",
                    "create",
                    "--name",
                    "테스트봇",
                    "--strategy",
                    "stg-1",
                    "--account",
                    "test",
                ],
            )
            assert result.exit_code == 0
            assert "생성 완료" in result.output


# ── trade 커맨드 ────────────────────────────────────


class TestTradeCommands:
    def test_trade_list_empty(self, runner):
        with patch("ante.cli.commands.trade._create_trade_service") as mock_svc:
            mock_service = AsyncMock()
            mock_service.get_trades = AsyncMock(return_value=[])
            mock_db = AsyncMock()
            mock_db.close = AsyncMock()
            mock_svc.return_value = (mock_service, mock_db)

            result = runner.invoke(cli, ["trade", "list"])
            assert result.exit_code == 0

    def test_trade_info_not_found(self, runner):
        with patch("ante.core.database.Database") as mock_db_cls:
            mock_db = AsyncMock()
            mock_db.connect = AsyncMock()
            mock_db.fetch_one = AsyncMock(return_value=None)
            mock_db.close = AsyncMock()
            mock_db_cls.return_value = mock_db

            result = runner.invoke(cli, ["trade", "info", "fake-id"])
            assert result.exit_code == 0
            assert "찾을 수 없습니다" in result.output


# ── treasury 커맨드 ──────────────────────────────────


class TestTreasuryCommands:
    def test_treasury_status(self, runner):
        with patch("ante.cli.commands.treasury._create_treasury") as mock_svc:
            mock_treasury = MagicMock()
            mock_treasury.get_summary.return_value = {
                "account_balance": 10000000.0,
                "purchasable_amount": 8000000.0,
                "total_evaluation": 12000000.0,
                "total_profit_loss": 200000.0,
                "total_allocated": 5000000.0,
                "total_reserved": 100000.0,
                "unallocated": 5000000.0,
                "bot_count": 2,
            }
            mock_db = AsyncMock()
            mock_db.close = AsyncMock()
            mock_svc.return_value = (mock_treasury, mock_db)

            result = runner.invoke(cli, ["treasury", "status"])
            assert result.exit_code == 0
            assert "10,000,000" in result.output

    def test_treasury_status_json(self, runner):
        with patch("ante.cli.commands.treasury._create_treasury") as mock_svc:
            mock_treasury = MagicMock()
            mock_treasury.get_summary.return_value = {
                "account_balance": 10000000.0,
                "purchasable_amount": 8000000.0,
                "total_evaluation": 12000000.0,
                "total_profit_loss": 200000.0,
                "total_allocated": 5000000.0,
                "total_reserved": 100000.0,
                "unallocated": 5000000.0,
                "bot_count": 2,
            }
            mock_db = AsyncMock()
            mock_db.close = AsyncMock()
            mock_svc.return_value = (mock_treasury, mock_db)

            result = runner.invoke(cli, ["--format", "json", "treasury", "status"])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["account_balance"] == 10000000.0

    def test_treasury_allocate_success(self, runner):
        with patch("ante.cli.commands.treasury._create_treasury") as mock_svc:
            mock_treasury = AsyncMock()
            mock_treasury.allocate = AsyncMock(return_value=True)
            mock_db = AsyncMock()
            mock_db.close = AsyncMock()
            mock_svc.return_value = (mock_treasury, mock_db)

            result = runner.invoke(cli, ["treasury", "allocate", "bot-1", "1000000"])
            assert result.exit_code == 0
            assert "할당 완료" in result.output

    def test_treasury_allocate_fail(self, runner):
        with patch("ante.cli.commands.treasury._create_treasury") as mock_svc:
            mock_treasury = AsyncMock()
            mock_treasury.allocate = AsyncMock(return_value=False)
            mock_db = AsyncMock()
            mock_db.close = AsyncMock()
            mock_svc.return_value = (mock_treasury, mock_db)

            result = runner.invoke(cli, ["treasury", "allocate", "bot-1", "999999999"])
            assert result.exit_code == 0
            assert "실패" in result.output

    def test_treasury_deallocate_success(self, runner):
        with patch("ante.cli.commands.treasury._create_treasury") as mock_svc:
            mock_treasury = AsyncMock()
            mock_treasury.deallocate = AsyncMock(return_value=True)
            mock_db = AsyncMock()
            mock_db.close = AsyncMock()
            mock_svc.return_value = (mock_treasury, mock_db)

            result = runner.invoke(cli, ["treasury", "deallocate", "bot-1", "500000"])
            assert result.exit_code == 0
            assert "회수 완료" in result.output


# ── rule 커맨드 ─────────────────────────────────────


class TestRuleCommands:
    def test_rule_list_empty(self, runner):
        with patch("ante.cli.commands.rule._create_rule_engine") as mock_svc:
            mock_engine = MagicMock()
            mock_engine._global_rules = []
            mock_engine._strategy_rules = {}
            mock_db = AsyncMock()
            mock_db.close = AsyncMock()
            mock_svc.return_value = (mock_engine, mock_db)

            with patch("ante.cli.commands.rule._load_rules_from_config"):
                result = runner.invoke(cli, ["rule", "list"])
                assert result.exit_code == 0

    def test_rule_list_with_rules(self, runner):
        with patch("ante.cli.commands.rule._create_rule_engine") as mock_svc:
            mock_rule = MagicMock()
            mock_rule.rule_id = "daily_loss"
            mock_rule.name = "Daily Loss Limit"
            mock_rule.enabled = True
            mock_rule.priority = 0
            mock_rule.description = "Daily loss limit rule"

            mock_engine = MagicMock()
            mock_engine._global_rules = [mock_rule]
            mock_engine._strategy_rules = {}
            mock_db = AsyncMock()
            mock_db.close = AsyncMock()
            mock_svc.return_value = (mock_engine, mock_db)

            with patch("ante.cli.commands.rule._load_rules_from_config"):
                result = runner.invoke(cli, ["--format", "json", "rule", "list"])
                assert result.exit_code == 0
                data = json.loads(result.output)
                assert len(data["rules"]) == 1
                assert data["rules"][0]["rule_id"] == "daily_loss"

    def test_rule_info_not_found(self, runner):
        with patch("ante.cli.commands.rule._create_rule_engine") as mock_svc:
            mock_engine = MagicMock()
            mock_engine._global_rules = []
            mock_engine._strategy_rules = {}
            mock_db = AsyncMock()
            mock_db.close = AsyncMock()
            mock_svc.return_value = (mock_engine, mock_db)

            with patch("ante.cli.commands.rule._load_rules_from_config"):
                result = runner.invoke(cli, ["rule", "info", "nonexistent"])
                assert result.exit_code == 0
                assert "찾을 수 없습니다" in result.output


# ── broker 커맨드 ───────────────────────────────────


class TestBrokerCommands:
    def test_broker_status_connected(self, runner):
        with patch("ante.cli.commands.broker._create_broker") as mock_create:
            mock_adapter = AsyncMock()
            mock_adapter.is_connected = True
            mock_adapter.health_check = AsyncMock(return_value=True)
            mock_adapter.exchange = "KRX"
            mock_create.return_value = mock_adapter

            result = runner.invoke(cli, ["broker", "status"])
            assert result.exit_code == 0
            assert "연결됨" in result.output

    def test_broker_status_error(self, runner):
        with patch("ante.cli.commands.broker._create_broker") as mock_create:
            mock_create.side_effect = Exception("connection failed")

            result = runner.invoke(cli, ["broker", "status"])
            assert result.exit_code == 0
            assert "미연결" in result.output

    def test_broker_balance(self, runner):
        with patch("ante.cli.commands.broker._create_broker") as mock_create:
            mock_adapter = AsyncMock()
            mock_adapter.get_account_balance = AsyncMock(
                return_value={"cash": 10000000.0, "total_assets": 15000000.0}
            )
            mock_adapter.disconnect = AsyncMock()
            mock_create.return_value = mock_adapter

            result = runner.invoke(cli, ["--format", "json", "broker", "balance"])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["cash"] == 10000000.0

    def test_broker_positions_empty(self, runner):
        with patch("ante.cli.commands.broker._create_broker") as mock_create:
            mock_adapter = AsyncMock()
            mock_adapter.get_positions = AsyncMock(return_value=[])
            mock_adapter.disconnect = AsyncMock()
            mock_create.return_value = mock_adapter

            result = runner.invoke(cli, ["broker", "positions"])
            assert result.exit_code == 0
