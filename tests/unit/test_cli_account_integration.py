"""CLI 명령어 account_id 연동 테스트 (#573)."""

from __future__ import annotations

import json
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from ante.account.models import Account, AccountStatus, TradingMode
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

_MOCK_ACCOUNT_1 = Account(
    account_id="domestic",
    name="국내 주식",
    exchange="KRX",
    currency="KRW",
    timezone="Asia/Seoul",
    trading_mode=TradingMode.VIRTUAL,
    broker_type="test",
    buy_commission_rate=Decimal("0.00015"),
    sell_commission_rate=Decimal("0.00195"),
    status=AccountStatus.ACTIVE,
)

_MOCK_ACCOUNT_2 = Account(
    account_id="overseas",
    name="해외 주식",
    exchange="NYSE",
    currency="USD",
    timezone="America/New_York",
    trading_mode=TradingMode.VIRTUAL,
    broker_type="test",
    buy_commission_rate=Decimal("0"),
    sell_commission_rate=Decimal("0"),
    status=AccountStatus.ACTIVE,
)


@pytest.fixture
def runner():
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


def _make_mock_db(rows=None):
    """모의 Database 객체 생성."""
    db = AsyncMock()
    db.connect = AsyncMock()
    db.close = AsyncMock()
    db.execute = AsyncMock()
    db.execute_script = AsyncMock()
    if rows is not None:
        db.fetch_all = AsyncMock(return_value=rows)
        db.fetch_one = AsyncMock(return_value=rows[0] if rows else None)
    else:
        db.fetch_all = AsyncMock(return_value=[])
        db.fetch_one = AsyncMock(return_value=None)
    return db


def _make_mock_account_service(accounts=None):
    """모의 AccountService 객체 생성."""
    svc = AsyncMock()
    svc.initialize = AsyncMock()
    svc.list = AsyncMock(return_value=accounts or [])
    svc.get = AsyncMock()
    svc.suspend_all = AsyncMock(return_value=2)
    svc.activate_all = AsyncMock(return_value=2)
    return svc


# ── bot list --account ──────────────────────────────────


class TestBotListAccountFilter:
    def test_bot_list_with_account_filter(self, runner):
        """--account 옵션으로 특정 계좌의 봇만 필터링."""
        bot_rows = [
            {
                "bot_id": "bot-1",
                "name": "테스트봇",
                "strategy_id": "s1",
                "account_id": "domestic",
                "status": "idle",
                "created_at": "2026-01-01",
            },
        ]
        mock_db = _make_mock_db(bot_rows)
        mock_account_svc = _make_mock_account_service()

        with patch("ante.cli.commands.bot._create_services") as mock_cs:
            mock_cs.return_value = (
                mock_db,
                MagicMock(),
                MagicMock(),
                mock_account_svc,
            )
            result = runner.invoke(cli, ["bot", "list", "--account", "domestic"])

        assert result.exit_code == 0
        # fetch_all 호출 시 account_id 파라미터가 전달됨
        call_args = mock_db.fetch_all.call_args
        assert "domestic" in call_args[0][1]

    def test_bot_list_without_account_filter(self, runner):
        """--account 미지정 시 전체 봇 목록."""
        mock_db = _make_mock_db([])
        mock_account_svc = _make_mock_account_service()

        with patch("ante.cli.commands.bot._create_services") as mock_cs:
            mock_cs.return_value = (
                mock_db,
                MagicMock(),
                MagicMock(),
                mock_account_svc,
            )
            result = runner.invoke(cli, ["bot", "list"])

        assert result.exit_code == 0
        call_args = mock_db.fetch_all.call_args
        # 파라미터 없이 호출
        assert len(call_args[0]) == 1  # SQL만 전달

    def test_bot_list_with_account_json(self, runner):
        """JSON 모드에서 --account 필터."""
        bot_rows = [
            {
                "bot_id": "bot-1",
                "name": "테스트봇",
                "strategy_id": "s1",
                "account_id": "domestic",
                "status": "idle",
                "created_at": "2026-01-01",
            },
        ]
        mock_db = _make_mock_db(bot_rows)
        mock_account_svc = _make_mock_account_service()

        with patch("ante.cli.commands.bot._create_services") as mock_cs:
            mock_cs.return_value = (
                mock_db,
                MagicMock(),
                MagicMock(),
                mock_account_svc,
            )
            result = runner.invoke(
                cli, ["--format", "json", "bot", "list", "--account", "domestic"]
            )

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "bots" in data
        assert data["bots"][0]["account_id"] == "domestic"


# ── bot create --account (대화형 선택) ──────────────────


class TestBotCreateAccountOption:
    def test_bot_create_with_account_option(self, runner):
        """--account 옵션으로 계좌 지정."""
        mock_client = AsyncMock()
        mock_client.send.return_value = {
            "id": "req-1",
            "status": "ok",
            "result": {"bot_id": "bot-abc123"},
        }

        with (
            patch(
                "ante.cli.commands._ipc._get_socket_path",
                return_value="/tmp/test.sock",
            ),
            patch("ante.cli.commands._ipc.IPCClient", return_value=mock_client),
        ):
            result = runner.invoke(
                cli,
                [
                    "bot",
                    "create",
                    "--name",
                    "테스트봇",
                    "--strategy",
                    "s1",
                    "--account",
                    "domestic",
                ],
            )

        assert result.exit_code == 0
        assert "봇 생성 완료" in result.output
        # IPC로 전달된 account_id 확인
        sent_args = mock_client.send.call_args[0][1]
        assert sent_args["account_id"] == "domestic"

    def test_bot_create_interactive_single_account(self, runner):
        """계좌 미지정 + 활성 계좌 1개 → 자동 선택."""
        mock_account_svc = _make_mock_account_service([_MOCK_ACCOUNT_1])
        mock_client = AsyncMock()
        mock_client.send.return_value = {
            "id": "req-1",
            "status": "ok",
            "result": {"bot_id": "bot-abc123"},
        }

        with (
            patch("ante.cli.commands.bot._create_services") as mock_cs,
            patch(
                "ante.cli.commands._ipc._get_socket_path",
                return_value="/tmp/test.sock",
            ),
            patch("ante.cli.commands._ipc.IPCClient", return_value=mock_client),
        ):
            mock_cs.return_value = (
                _make_mock_db(),
                MagicMock(),
                MagicMock(),
                mock_account_svc,
            )
            result = runner.invoke(
                cli,
                ["bot", "create", "--name", "테스트봇", "--strategy", "s1"],
            )

        assert result.exit_code == 0
        assert "계좌 자동 선택" in result.output
        assert "domestic" in result.output

    def test_bot_create_interactive_multiple_accounts(self, runner):
        """계좌 미지정 + 활성 계좌 여러 개 → 대화형 선택."""
        mock_account_svc = _make_mock_account_service(
            [_MOCK_ACCOUNT_1, _MOCK_ACCOUNT_2]
        )
        mock_client = AsyncMock()
        mock_client.send.return_value = {
            "id": "req-1",
            "status": "ok",
            "result": {"bot_id": "bot-abc123"},
        }

        with (
            patch("ante.cli.commands.bot._create_services") as mock_cs,
            patch(
                "ante.cli.commands._ipc._get_socket_path",
                return_value="/tmp/test.sock",
            ),
            patch("ante.cli.commands._ipc.IPCClient", return_value=mock_client),
        ):
            mock_cs.return_value = (
                _make_mock_db(),
                MagicMock(),
                MagicMock(),
                mock_account_svc,
            )
            result = runner.invoke(
                cli,
                ["bot", "create", "--name", "테스트봇", "--strategy", "s1"],
                input="1\n",
            )

        assert result.exit_code == 0
        assert "계좌를 선택하세요" in result.output
        assert "domestic" in result.output
        assert "overseas" in result.output

    def test_bot_create_interactive_no_accounts(self, runner):
        """계좌 미지정 + 활성 계좌 0개 → 에러."""
        mock_account_svc = _make_mock_account_service([])

        with patch("ante.cli.commands.bot._create_services") as mock_cs:
            mock_cs.return_value = (
                _make_mock_db(),
                MagicMock(),
                MagicMock(),
                mock_account_svc,
            )
            result = runner.invoke(
                cli,
                ["bot", "create", "--name", "테스트봇", "--strategy", "s1"],
            )

        assert result.exit_code == 1
        assert "활성 계좌가 없습니다" in result.output


# ── system halt/activate (IPC) ──────────────────────────


class TestSystemHaltActivate:
    def test_system_halt_sends_ipc(self, runner):
        """system halt가 IPC system.halt 커맨드 전송."""
        mock_response = {"status": "ok", "data": {"suspended_count": 2}}

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
                result = runner.invoke(cli, ["system", "halt"])

        assert result.exit_code == 0
        assert "HALTED" in result.output
        mock_client.send.assert_called_once()

    def test_system_activate_sends_ipc(self, runner):
        """system activate가 IPC system.activate 커맨드 전송."""
        mock_response = {"status": "ok", "data": {"activated_count": 2}}

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
                result = runner.invoke(cli, ["system", "activate"])

        assert result.exit_code == 0
        assert "ACTIVE" in result.output
        mock_client.send.assert_called_once()


# ── treasury status --account ───────────────────────────


class TestTreasuryStatusAccount:
    def test_treasury_status_with_account(self, runner):
        """--account 옵션으로 계좌별 자금 현황 조회."""
        mock_treasury = MagicMock()
        mock_treasury.get_summary.return_value = {
            "account_balance": 10000000,
            "purchasable_amount": 8000000,
            "total_evaluation": 12000000,
            "total_profit_loss": 200000,
            "total_allocated": 5000000,
            "total_reserved": 1000000,
            "unallocated": 3000000,
            "bot_count": 2,
        }
        mock_treasury.initialize = AsyncMock()
        mock_db = _make_mock_db()

        with patch("ante.cli.commands.treasury._create_treasury") as mock_ct:
            mock_ct.return_value = (mock_treasury, mock_db)
            result = runner.invoke(cli, ["treasury", "status", "--account", "domestic"])

        assert result.exit_code == 0
        assert "10,000,000" in result.output
        # _create_treasury가 account_id와 함께 호출됨
        mock_ct.assert_called_once_with("domestic")

    def test_treasury_status_without_account(self, runner):
        """--account 미지정 시 기본 자금 현황."""
        mock_treasury = MagicMock()
        mock_treasury.get_summary.return_value = {
            "account_balance": 10000000,
            "purchasable_amount": 8000000,
            "total_evaluation": 12000000,
            "total_profit_loss": 200000,
            "total_allocated": 5000000,
            "total_reserved": 1000000,
            "unallocated": 3000000,
            "bot_count": 2,
        }
        mock_treasury.initialize = AsyncMock()
        mock_db = _make_mock_db()

        with patch("ante.cli.commands.treasury._create_treasury") as mock_ct:
            mock_ct.return_value = (mock_treasury, mock_db)
            result = runner.invoke(cli, ["treasury", "status"])

        assert result.exit_code == 0
        mock_ct.assert_called_once_with(None)

    def test_treasury_status_with_account_json(self, runner):
        """JSON 모드에서 --account 필터."""
        mock_treasury = MagicMock()
        mock_treasury.get_summary.return_value = {
            "account_balance": 10000000,
            "purchasable_amount": 8000000,
            "total_evaluation": 12000000,
            "total_profit_loss": 200000,
            "total_allocated": 5000000,
            "total_reserved": 1000000,
            "unallocated": 3000000,
            "bot_count": 2,
        }
        mock_treasury.initialize = AsyncMock()
        mock_db = _make_mock_db()

        with patch("ante.cli.commands.treasury._create_treasury") as mock_ct:
            mock_ct.return_value = (mock_treasury, mock_db)
            result = runner.invoke(
                cli,
                ["--format", "json", "treasury", "status", "--account", "domestic"],
            )

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["account_balance"] == 10000000


# ── broker balance/positions --account ──────────────────


class TestBrokerAccountOption:
    def test_broker_balance_with_account(self, runner):
        """--account 옵션으로 계좌별 잔고 조회."""
        mock_adapter = AsyncMock()
        mock_adapter.get_account_balance = AsyncMock(
            return_value={"cash": 5000000.0, "total": 8000000.0}
        )
        mock_adapter.disconnect = AsyncMock()
        mock_db = _make_mock_db()

        with patch("ante.cli.commands.broker._get_broker") as mock_gb:
            mock_gb.return_value = (mock_adapter, mock_db)
            result = runner.invoke(cli, ["broker", "balance", "--account", "domestic"])

        assert result.exit_code == 0
        mock_gb.assert_called_once_with("domestic")

    def test_broker_balance_without_account(self, runner):
        """--account 미지정 시 기존 Config 기반 폴백."""
        mock_adapter = AsyncMock()
        mock_adapter.get_account_balance = AsyncMock(return_value={"cash": 5000000.0})
        mock_adapter.disconnect = AsyncMock()

        with patch("ante.cli.commands.broker._get_broker") as mock_gb:
            mock_gb.return_value = (mock_adapter, None)
            result = runner.invoke(cli, ["broker", "balance"])

        assert result.exit_code == 0
        mock_gb.assert_called_once_with(None)

    def test_broker_positions_with_account(self, runner):
        """--account 옵션으로 계좌별 포지션 조회."""
        mock_adapter = AsyncMock()
        mock_adapter.get_positions = AsyncMock(
            return_value=[
                {
                    "symbol": "005930",
                    "quantity": 10,
                    "avg_price": 70000.0,
                    "eval_amount": 700000.0,
                },
            ]
        )
        mock_adapter.disconnect = AsyncMock()
        mock_db = _make_mock_db()

        with patch("ante.cli.commands.broker._get_broker") as mock_gb:
            mock_gb.return_value = (mock_adapter, mock_db)
            result = runner.invoke(
                cli, ["broker", "positions", "--account", "domestic"]
            )

        assert result.exit_code == 0
        mock_gb.assert_called_once_with("domestic")

    def test_broker_positions_with_account_json(self, runner):
        """JSON 모드에서 --account로 포지션 조회."""
        mock_adapter = AsyncMock()
        mock_adapter.get_positions = AsyncMock(
            return_value=[
                {
                    "symbol": "005930",
                    "quantity": 10,
                    "avg_price": 70000.0,
                    "eval_amount": 700000.0,
                },
            ]
        )
        mock_adapter.disconnect = AsyncMock()
        mock_db = _make_mock_db()

        with patch("ante.cli.commands.broker._get_broker") as mock_gb:
            mock_gb.return_value = (mock_adapter, mock_db)
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "broker",
                    "positions",
                    "--account",
                    "domestic",
                ],
            )

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data["positions"]) == 1
        assert data["positions"][0]["symbol"] == "005930"
