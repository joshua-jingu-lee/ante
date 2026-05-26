"""is_paper를 Account.broker_config으로 이관하는 로직 테스트 (Refs #989)."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from ante.account.models import Account

# ── 마이그레이션 로직 단위 테스트 ──────────────────


def _make_account(
    account_id: str = "domestic",
    broker_type: str = "kis-domestic",
    broker_config: dict | None = None,
    credentials: dict | None = None,
) -> Account:
    return Account(
        account_id=account_id,
        name="테스트",
        exchange="KRX",
        currency="KRW",
        broker_type=broker_type,
        broker_config=broker_config or {},
        credentials=credentials or {"app_key": "k", "app_secret": "s"},
        buy_commission_rate=Decimal("0.00015"),
        sell_commission_rate=Decimal("0.00195"),
    )


class TestMigrateIsPaperToBrokerConfig:
    """_migrate_is_paper_to_broker_config 단위 테스트."""

    @pytest.fixture
    def services(self):
        """mock Services 객체."""
        s = MagicMock()
        s.config = MagicMock()
        s.account_service = AsyncMock()
        return s

    async def test_no_legacy_setting_skips(self, services):
        """system.toml에 broker.is_paper가 없으면 아무것도 하지 않는다."""
        from ante.main import _migrate_is_paper_to_broker_config

        services.config.get.return_value = None

        await _migrate_is_paper_to_broker_config(services)

        services.account_service.list.assert_not_called()

    async def test_migrates_kis_accounts(self, services):
        """KIS 계좌에 is_paper를 이관한다."""
        from ante.main import _migrate_is_paper_to_broker_config

        services.config.get.return_value = True
        services.account_service.list.return_value = [
            _make_account("domestic", "kis-domestic"),
        ]

        await _migrate_is_paper_to_broker_config(services)

        services.account_service.update.assert_called_once_with(
            "domestic", broker_config={"is_paper": True}
        )

    async def test_skips_non_kis_accounts(self, services):
        """KIS가 아닌 계좌는 건너뛴다."""
        from ante.main import _migrate_is_paper_to_broker_config

        services.config.get.return_value = True
        services.account_service.list.return_value = [
            _make_account("test", "test"),
        ]

        await _migrate_is_paper_to_broker_config(services)

        services.account_service.update.assert_not_called()

    async def test_skips_already_migrated(self, services):
        """이미 broker_config에 is_paper가 있으면 건너뛴다."""
        from ante.main import _migrate_is_paper_to_broker_config

        services.config.get.return_value = True
        services.account_service.list.return_value = [
            _make_account(
                "domestic", "kis-domestic", broker_config={"is_paper": False}
            ),
        ]

        await _migrate_is_paper_to_broker_config(services)

        services.account_service.update.assert_not_called()

    async def test_migrates_false_value(self, services):
        """is_paper=false도 정상 이관된다."""
        from ante.main import _migrate_is_paper_to_broker_config

        services.config.get.return_value = False
        services.account_service.list.return_value = [
            _make_account("domestic", "kis-domestic"),
        ]

        await _migrate_is_paper_to_broker_config(services)

        services.account_service.update.assert_called_once_with(
            "domestic", broker_config={"is_paper": False}
        )

    async def test_migrates_kis_broker_type(self, services):
        """broker_type='kis'인 계좌도 이관 대상이다."""
        from ante.main import _migrate_is_paper_to_broker_config

        services.config.get.return_value = True
        services.account_service.list.return_value = [
            _make_account("old-kis", "kis"),
        ]

        await _migrate_is_paper_to_broker_config(services)

        services.account_service.update.assert_called_once_with(
            "old-kis", broker_config={"is_paper": True}
        )


# ── main.py broker_config 병합 테스트 ──────────────────


class TestBrokerConfigMerge:
    """main.py에서 stream 초기화 시 broker_config이 credentials에 병합되는지 확인."""

    def test_broker_config_overrides_credentials(self):
        """broker_config의 is_paper가 credentials의 is_paper보다 우선한다."""
        account = _make_account(
            credentials={"app_key": "k", "app_secret": "s", "is_paper": "true"},
            broker_config={"is_paper": False},
        )
        merged = {**account.credentials, **account.broker_config}
        assert merged["is_paper"] is False

    def test_broker_config_adds_is_paper(self):
        """credentials에 is_paper가 없어도 broker_config에서 추가된다."""
        account = _make_account(
            credentials={"app_key": "k", "app_secret": "s"},
            broker_config={"is_paper": True},
        )
        merged = {**account.credentials, **account.broker_config}
        assert merged["is_paper"] is True


# ── CLI account create is_paper 비대화형 테스트 ──────────
#
# 1.0 비대화형 입력 계약(docs/specs/cli/02-design-decisions.md)에 따라
# `ante account create`는 stdin prompt를 사용하지 않는다. ``is_paper``는
# ``--broker-config is_paper=true|false``로 전달한다.


class TestAccountCreateIsPaper:
    """ante account create 비대화형: kis-domestic + ``--broker-config is_paper``."""

    @pytest.fixture(autouse=True)
    def bypass_auth(self):
        from ante.member.models import Member, MemberRole, MemberStatus, MemberType

        mock_member = Member(
            member_id="tester",
            name="테스터",
            type=MemberType.HUMAN,
            role=MemberRole.MASTER,
            status=MemberStatus.ACTIVE,
            scopes=[],
        )
        with patch(
            "ante.cli.main.authenticate_member",
            side_effect=lambda ctx: ctx.obj.update({"member": mock_member}),
        ):
            yield

    @pytest.fixture
    def mock_account_service(self):
        # #1856: async context manager 전환.
        from contextlib import asynccontextmanager

        svc = AsyncMock()

        @asynccontextmanager
        async def _create_service(ctx=None):  # noqa: ANN001, ANN202
            yield svc

        with patch(
            "ante.cli.commands.account._create_account_service", new=_create_service
        ):
            yield svc

    @pytest.fixture
    def offline_runtime(self):
        """active runtime이 없는 cold-path 통과 환경."""
        with (
            patch("ante.main.read_pid_file", return_value=None),
            patch(
                "ante.cli.commands.ipc_helpers.get_socket_path",
                return_value="/tmp/__ante_offline_is_paper_test__.sock",
            ),
        ):
            yield

    def test_kis_domestic_is_paper_true(self, mock_account_service, offline_runtime):
        """--broker-config is_paper=true → broker_config={'is_paper': True}."""
        from ante.cli.main import cli

        created = _make_account("domestic", "kis-domestic")
        mock_account_service.create.return_value = created

        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "account",
                "create",
                "--broker-type",
                "kis-domestic",
                "--account-id",
                "domestic",
                "--name",
                "국내 주식",
                "--trading-mode",
                "virtual",
                "--credential",
                "app_key=test_key",
                "--credential",
                "app_secret=test_secret",
                "--credential",
                "account_no=50123456-01",
                "--broker-config",
                "is_paper=true",
            ],
        )

        assert result.exit_code == 0, result.output
        call_args = mock_account_service.create.call_args
        account_arg = call_args[0][0]
        assert account_arg.broker_config == {"is_paper": True}

    def test_kis_domestic_is_paper_false(self, mock_account_service, offline_runtime):
        """--broker-config is_paper=false → broker_config={'is_paper': False}."""
        from ante.cli.main import cli

        created = _make_account("domestic", "kis-domestic")
        mock_account_service.create.return_value = created

        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "account",
                "create",
                "--broker-type",
                "kis-domestic",
                "--account-id",
                "domestic",
                "--name",
                "국내 주식",
                "--trading-mode",
                "virtual",
                "--credential",
                "app_key=test_key",
                "--credential",
                "app_secret=test_secret",
                "--credential",
                "account_no=50123456-01",
                "--broker-config",
                "is_paper=false",
            ],
        )

        assert result.exit_code == 0, result.output
        call_args = mock_account_service.create.call_args
        account_arg = call_args[0][0]
        assert account_arg.broker_config == {"is_paper": False}

    def test_test_broker_no_broker_config(self, mock_account_service, offline_runtime):
        """test broker는 --broker-config 없이도 broker_config={}로 생성."""
        from ante.cli.main import cli

        created = _make_account("test", "test", broker_config={})
        mock_account_service.create.return_value = created

        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "account",
                "create",
                "--broker-type",
                "test",
                "--account-id",
                "test2",
                "--name",
                "테스트2",
                "--trading-mode",
                "virtual",
                "--credential",
                "app_key=test_key",
                "--credential",
                "app_secret=test_secret",
            ],
        )

        assert result.exit_code == 0, result.output
        call_args = mock_account_service.create.call_args
        account_arg = call_args[0][0]
        assert account_arg.broker_config == {}


# ── CLI init is_paper 프롬프트 테스트 ──────────
#
# `ante init`은 비대화형 재설계(issue #1125)로 계좌 등록 로직이 제거되어
# `ante account create` 경로만 유지된다. 해당 테스트는 `TestAccountCreateIsPaper`
# 클래스에 이미 충분히 커버되어 있으므로 별도 클래스를 두지 않는다.
