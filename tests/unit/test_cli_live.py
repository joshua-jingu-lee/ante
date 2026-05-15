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
        # Refs #1213: suspend_all/activate_all 반환 타입은 list[dict].
        mock_svc.suspend_all = AsyncMock(
            return_value=[
                {
                    "account_id": "test",
                    "previous_status": "active",
                    "status": "suspended",
                    "changed": True,
                }
            ]
        )
        mock_svc.activate_all = AsyncMock(
            return_value=[
                {
                    "account_id": "test",
                    "previous_status": "suspended",
                    "status": "active",
                    "changed": True,
                }
            ]
        )
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
        mock_response = {
            "status": "ok",
            "data": {
                "status": "halted",
                "accounts_changed": 2,
                "changed_at": "2026-05-03T05:21:33+00:00",
                "accounts": [],
            },
        }

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
                result = runner.invoke(cli, ["system", "halt", "--reason", "test halt"])
                assert result.exit_code == 0
                assert "HALTED" in result.output

    def test_system_clear_halt(self, runner):
        mock_response = {
            "status": "ok",
            "data": {
                "status": "halt_cleared",
                "accounts_changed": 2,
                "changed_at": "2026-05-03T05:21:33+00:00",
                "accounts": [],
            },
        }

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
                result = runner.invoke(cli, ["system", "clear-halt"])
                assert result.exit_code == 0
                assert "정지 해제" in result.output


# ── bot 커맨드 ─────────────────────────────────────


class TestBotCommands:
    def test_bot_list_empty(self, runner):
        with patch("ante.cli.commands.bot._create_services") as mock_svc:
            mock_db = AsyncMock()
            mock_db.fetch_all = AsyncMock(return_value=[])
            mock_db.close = AsyncMock()
            mock_svc.return_value = (mock_db, MagicMock(), MagicMock(), MagicMock())

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
            mock_svc.return_value = (mock_db, MagicMock(), MagicMock(), MagicMock())

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
            mock_svc.return_value = (mock_db, MagicMock(), MagicMock(), MagicMock())

            result = runner.invoke(cli, ["bot", "info", "nonexistent"])
            # #1515: missing-resource는 ctx.exit(1)로 non-zero exit
            assert result.exit_code == 1
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
            mock_svc.return_value = (mock_db, MagicMock(), MagicMock(), MagicMock())

            result = runner.invoke(cli, ["bot", "info", "bot-1"])
            assert result.exit_code == 0
            assert "bot-1" in result.output

    def test_bot_create(self, runner):
        mock_client = AsyncMock()
        mock_client.send.return_value = {
            "id": "req-1",
            "status": "ok",
            "result": {"bot_id": "bot-abc123"},
        }

        with (
            patch(
                "ante.cli.commands.ipc_helpers.get_socket_path",
                return_value="/tmp/test.sock",
            ),
            patch("ante.cli.commands.ipc_helpers.IPCClient", return_value=mock_client),
        ):
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

    def test_create_trade_service_constructor_args(self):
        """_create_trade_service가 올바른 생성자 시그니처로 호출되는지 검증.

        이전 버전에서는 EventBus를 잘못된 인자로 전달하여 hang이 발생했다.
        Refs #642.
        """
        import asyncio

        with (
            patch("ante.core.database.Database") as mock_db_cls,
            patch("ante.trade.position.PositionHistory") as mock_ph_cls,
            patch("ante.trade.recorder.TradeRecorder") as mock_rec_cls,
            patch("ante.trade.performance.PerformanceTracker") as mock_perf_cls,
            patch("ante.trade.service.TradeService") as mock_svc_cls,
        ):
            mock_db = AsyncMock()
            mock_db.connect = AsyncMock()
            mock_db_cls.return_value = mock_db

            mock_ph = AsyncMock()
            mock_ph.initialize = AsyncMock()
            mock_ph_cls.return_value = mock_ph

            mock_rec = AsyncMock()
            mock_rec.initialize = AsyncMock()
            mock_rec_cls.return_value = mock_rec

            mock_perf = MagicMock()
            mock_perf_cls.return_value = mock_perf

            mock_service = MagicMock()
            mock_svc_cls.return_value = mock_service

            from ante.cli.commands.trade import _create_trade_service

            service, db = asyncio.run(_create_trade_service())

            # PositionHistory는 db만 받아야 한다
            mock_ph_cls.assert_called_once_with(db=mock_db)
            # TradeRecorder는 db + position_history를 받아야 한다
            mock_rec_cls.assert_called_once_with(db=mock_db, position_history=mock_ph)
            # PerformanceTracker는 db만 받아야 한다
            mock_perf_cls.assert_called_once_with(db=mock_db)

    def test_trade_info_not_found(self, runner):
        with patch("ante.core.database.Database") as mock_db_cls:
            mock_db = AsyncMock()
            mock_db.connect = AsyncMock()
            mock_db.fetch_one = AsyncMock(return_value=None)
            mock_db.close = AsyncMock()
            mock_db_cls.return_value = mock_db

            result = runner.invoke(cli, ["trade", "info", "fake-id"])
            # #1515: missing-resource는 ctx.exit(1)로 non-zero exit
            assert result.exit_code == 1
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

            result = runner.invoke(cli, ["treasury", "status", "--account", "domestic"])
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

            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "treasury",
                    "status",
                    "--account",
                    "domestic",
                ],
            )
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["account_balance"] == 10000000.0

    def test_treasury_allocate_success(self, runner):
        mock_client = AsyncMock()
        mock_client.send.return_value = {
            "id": "req-1",
            "status": "ok",
            "result": {"account_id": "acc-1", "bot_id": "bot-1", "success": True},
        }

        with (
            patch(
                "ante.cli.commands.ipc_helpers.get_socket_path",
                return_value="/tmp/test.sock",
            ),
            patch("ante.cli.commands.ipc_helpers.IPCClient", return_value=mock_client),
        ):
            result = runner.invoke(
                cli, ["treasury", "allocate", "bot-1", "1000000", "--account", "acc-1"]
            )
            assert result.exit_code == 0
            assert "할당 완료" in result.output

    def test_treasury_allocate_fail(self, runner):
        mock_client = AsyncMock()
        mock_client.send.return_value = {
            "id": "req-1",
            "status": "ok",
            "result": {"account_id": "acc-1", "bot_id": "bot-1", "success": False},
        }

        with (
            patch(
                "ante.cli.commands.ipc_helpers.get_socket_path",
                return_value="/tmp/test.sock",
            ),
            patch("ante.cli.commands.ipc_helpers.IPCClient", return_value=mock_client),
        ):
            result = runner.invoke(
                cli,
                ["treasury", "allocate", "bot-1", "999999999", "--account", "acc-1"],
            )
            # #1517: IPC success=False는 ctx.exit(1)로 non-zero exit
            assert result.exit_code == 1
            assert "실패" in result.output

    def test_treasury_deallocate_success(self, runner):
        mock_client = AsyncMock()
        mock_client.send.return_value = {
            "id": "req-1",
            "status": "ok",
            "result": {"account_id": "acc-1", "bot_id": "bot-1", "success": True},
        }

        with (
            patch(
                "ante.cli.commands.ipc_helpers.get_socket_path",
                return_value="/tmp/test.sock",
            ),
            patch("ante.cli.commands.ipc_helpers.IPCClient", return_value=mock_client),
        ):
            result = runner.invoke(
                cli,
                ["treasury", "deallocate", "bot-1", "500000", "--account", "acc-1"],
            )
            assert result.exit_code == 0
            assert "회수 완료" in result.output


# ── rule 커맨드 ─────────────────────────────────────


class TestRuleCommands:
    @staticmethod
    def _patch_account_service(*, exists: bool):
        """`rule list`가 내부에서 생성하는 AccountService를 mock한다.

        `exists=True`면 `get`이 정상 반환(실재 account),
        `exists=False`면 `AccountNotFoundError`를 raise(미존재 account, #1559).
        """
        from ante.account.errors import AccountNotFoundError

        mock_service = AsyncMock()
        mock_service.initialize = AsyncMock()
        if exists:
            mock_service.get = AsyncMock(return_value=MagicMock())
        else:
            mock_service.get = AsyncMock(
                side_effect=AccountNotFoundError(
                    "계좌 'oracle-missing-account'를 찾을 수 없습니다."
                )
            )
        return patch(
            "ante.account.service.AccountService",
            return_value=mock_service,
        )

    def test_rule_list_empty(self, runner):
        with patch("ante.cli.commands.rule._create_rule_engine") as mock_svc:
            mock_engine = MagicMock()
            mock_engine._global_rules = []
            mock_engine._strategy_rules = {}
            mock_db = AsyncMock()
            mock_db.close = AsyncMock()
            mock_svc.return_value = (mock_engine, mock_db)

            with (
                patch("ante.cli.commands.rule._load_rules_from_config"),
                self._patch_account_service(exists=True),
            ):
                result = runner.invoke(cli, ["rule", "list", "--account", "acc-1"])
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

            with (
                patch("ante.cli.commands.rule._load_rules_from_config"),
                self._patch_account_service(exists=True),
            ):
                result = runner.invoke(
                    cli,
                    [
                        "--format",
                        "json",
                        "rule",
                        "list",
                        "--account",
                        "acc-1",
                    ],
                )
                assert result.exit_code == 0
                data = json.loads(result.output)
                assert len(data["rules"]) == 1
                assert data["rules"][0]["rule_id"] == "daily_loss"

    def test_rule_list_missing_account_json_exit_1(self, runner):
        """미존재 account: JSON envelope + ACCOUNT_NOT_FOUND + exit 1 (#1559)."""
        with patch("ante.cli.commands.rule._create_rule_engine") as mock_svc:
            mock_engine = MagicMock()
            mock_engine._global_rules = []
            mock_engine._strategy_rules = {}
            mock_db = AsyncMock()
            mock_db.close = AsyncMock()
            mock_svc.return_value = (mock_engine, mock_db)

            with (
                patch("ante.cli.commands.rule._load_rules_from_config"),
                self._patch_account_service(exists=False),
            ):
                result = runner.invoke(
                    cli,
                    [
                        "--format",
                        "json",
                        "rule",
                        "list",
                        "--account",
                        "oracle-missing-account",
                    ],
                )
                assert result.exit_code == 1
                data = json.loads(result.output)
                assert data["status"] == "error"
                assert data["code"] == "ACCOUNT_NOT_FOUND"
                assert "찾을 수 없습니다" in data["message"]
                # db.close()는 finally가 단독 소유 — lifecycle 불변(#1559).
                mock_db.close.assert_awaited()

    def test_rule_list_missing_account_text_exit_1(self, runner):
        """미존재 account: text 출력도 exit 1로 종료 (#1559)."""
        with patch("ante.cli.commands.rule._create_rule_engine") as mock_svc:
            mock_engine = MagicMock()
            mock_engine._global_rules = []
            mock_engine._strategy_rules = {}
            mock_db = AsyncMock()
            mock_db.close = AsyncMock()
            mock_svc.return_value = (mock_engine, mock_db)

            with (
                patch("ante.cli.commands.rule._load_rules_from_config"),
                self._patch_account_service(exists=False),
            ):
                result = runner.invoke(
                    cli,
                    ["rule", "list", "--account", "oracle-missing-account"],
                )
                assert result.exit_code == 1
                assert "찾을 수 없습니다" in result.output

    def test_rule_list_real_account_zero_rules_exit_0(self, runner):
        """regression guard: 실재 account + 0 rules는 정상 계약 유지 (#1559).

        exit 0 + {"message":"등록된 룰이 없습니다.","rules":[]} 그대로.
        """
        with patch("ante.cli.commands.rule._create_rule_engine") as mock_svc:
            mock_engine = MagicMock()
            mock_engine._global_rules = []
            mock_engine._strategy_rules = {}
            mock_db = AsyncMock()
            mock_db.close = AsyncMock()
            mock_svc.return_value = (mock_engine, mock_db)

            with (
                patch("ante.cli.commands.rule._load_rules_from_config"),
                self._patch_account_service(exists=True),
            ):
                result = runner.invoke(
                    cli,
                    ["--format", "json", "rule", "list", "--account", "acc-1"],
                )
                assert result.exit_code == 0
                data = json.loads(result.output)
                assert data["message"] == "등록된 룰이 없습니다."
                assert data["rules"] == []

    def test_rule_info_not_found(self, runner):
        with patch("ante.cli.commands.rule._create_rule_engine") as mock_svc:
            mock_engine = MagicMock()
            mock_engine._global_rules = []
            mock_engine._strategy_rules = {}
            mock_db = AsyncMock()
            mock_db.close = AsyncMock()
            mock_svc.return_value = (mock_engine, mock_db)

            with patch("ante.cli.commands.rule._load_rules_from_config"):
                result = runner.invoke(
                    cli,
                    ["rule", "info", "nonexistent", "--account", "acc-1"],
                )
                assert result.exit_code == 1
                assert "찾을 수 없습니다" in result.output

    def test_rule_list_requires_account(self, runner):
        """--account 옵션 누락 시 click usage error로 실패."""
        result = runner.invoke(cli, ["rule", "list"])
        assert result.exit_code != 0
        assert "--account" in result.output

    def test_rule_info_requires_account(self, runner):
        """rule info도 --account 옵션 누락 시 실패."""
        result = runner.invoke(cli, ["rule", "info", "some-rule"])
        assert result.exit_code != 0
        assert "--account" in result.output


# ── broker 커맨드 ───────────────────────────────────


class TestBrokerCommands:
    def test_broker_status_connected(self, runner):
        with patch("ante.cli.commands.broker._get_broker") as mock_create:
            mock_adapter = AsyncMock()
            mock_adapter.is_connected = True
            mock_adapter.health_check = AsyncMock(return_value=True)
            mock_adapter.exchange = "KRX"
            mock_create.return_value = (mock_adapter, None)

            result = runner.invoke(cli, ["broker", "status", "--account", "acc-1"])
            assert result.exit_code == 0
            assert "연결됨" in result.output

    def test_broker_status_error(self, runner):
        with patch("ante.cli.commands.broker._get_broker") as mock_create:
            mock_create.side_effect = Exception("connection failed")

            result = runner.invoke(cli, ["broker", "status", "--account", "acc-1"])
            assert result.exit_code == 0
            assert "미연결" in result.output

    def test_broker_balance(self, runner):
        with patch("ante.cli.commands.broker._get_broker") as mock_create:
            mock_adapter = AsyncMock()
            mock_adapter.get_account_balance = AsyncMock(
                return_value={"cash": 10000000.0, "total_assets": 15000000.0}
            )
            mock_adapter.disconnect = AsyncMock()
            mock_create.return_value = (mock_adapter, None)

            result = runner.invoke(
                cli, ["--format", "json", "broker", "balance", "--account", "acc-1"]
            )
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["cash"] == 10000000.0

    def test_broker_positions_empty(self, runner):
        with patch("ante.cli.commands.broker._get_broker") as mock_create:
            mock_adapter = AsyncMock()
            mock_adapter.get_positions = AsyncMock(return_value=[])
            mock_adapter.disconnect = AsyncMock()
            mock_create.return_value = (mock_adapter, None)

            result = runner.invoke(cli, ["broker", "positions", "--account", "acc-1"])
            assert result.exit_code == 0

    def test_broker_status_requires_account(self, runner):
        """broker status도 --account 옵션 누락 시 user-friendly 에러로 거부.

        #1217 SPLIT-1: account_id fallback 금지. CLI 진입 시점에서 차단.
        """
        result = runner.invoke(cli, ["broker", "status"])
        assert result.exit_code != 0
        assert "--account" in result.output

    def test_broker_balance_requires_account(self, runner):
        """broker balance도 --account 옵션 누락 시 거부."""
        result = runner.invoke(cli, ["broker", "balance"])
        assert result.exit_code != 0
        assert "--account" in result.output

    def test_broker_positions_requires_account(self, runner):
        """broker positions도 --account 옵션 누락 시 거부."""
        result = runner.invoke(cli, ["broker", "positions"])
        assert result.exit_code != 0
        assert "--account" in result.output

    def test_broker_reconcile_requires_account(self, runner):
        """broker reconcile (--fix 유무 무관) --account 옵션 누락 시 거부."""
        result = runner.invoke(cli, ["broker", "reconcile"])
        assert result.exit_code != 0
        assert "--account" in result.output

        result_fix = runner.invoke(cli, ["broker", "reconcile", "--fix"])
        assert result_fix.exit_code != 0
        assert "--account" in result_fix.output

    def test_offline_broker_reconcile_filters_other_account(self, runner):
        """오프라인 fallback 도 ``--account`` 의 포지션만 비교한다.

        Refs #1240 review (P2-2): 서버 미기동 fallback 의
        ``position_history.get_all_positions()`` 호출이 모든 계좌를 보면
        다른 계좌의 포지션이 false discrepancy 로 잡힌다. 단일 계좌
        reconcile 은 해당 계좌만 보도록 ``account_id`` 필터를 전달해야 한다.
        """
        with (
            patch("ante.cli.commands.broker._get_broker") as mock_get_broker,
            patch("ante.cli.commands.ipc_helpers.IPCClient") as mock_ipc_cls,
            patch(
                "ante.cli.commands.ipc_helpers.get_socket_path",
                return_value="/tmp/test.sock",
            ),
            patch("ante.core.database.Database") as mock_db_cls,
            patch("ante.trade.position.PositionHistory") as mock_ph_cls,
        ):
            # IPC 는 서버 미기동으로 ClickException → fallback 으로 분기.
            from ante.ipc.exceptions import ServerNotRunningError

            mock_ipc = AsyncMock()
            mock_ipc.send = AsyncMock(side_effect=ServerNotRunningError("no server"))
            mock_ipc_cls.return_value = mock_ipc

            # Broker adapter mock — acc-a 의 포지션만 노출.
            mock_adapter = AsyncMock()
            mock_adapter.get_account_positions = AsyncMock(
                return_value=[{"symbol": "AAA", "quantity": 10.0}]
            )
            mock_adapter.disconnect = AsyncMock()
            mock_db = AsyncMock()
            mock_db.connect = AsyncMock()
            mock_db.close = AsyncMock()
            mock_db_cls.return_value = mock_db
            mock_get_broker.return_value = (mock_adapter, mock_db)

            # PositionHistory.get_all_positions(account_id=...) 의 인자 검증을
            # 위해 spec 을 정확히 맞춘 AsyncMock 사용.
            mock_ph = AsyncMock()
            mock_ph.initialize = AsyncMock()
            mock_ph.get_all_positions = AsyncMock(return_value=[])
            mock_ph_cls.return_value = mock_ph

            result = runner.invoke(cli, ["broker", "reconcile", "--account", "acc-a"])

            assert result.exit_code == 0, result.output
            mock_ph.get_all_positions.assert_awaited_once_with(account_id="acc-a")
