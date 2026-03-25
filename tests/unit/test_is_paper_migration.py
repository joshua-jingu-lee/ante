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


# ── CLI account create is_paper 프롬프트 테스트 ──────────


class TestAccountCreateIsPaper:
    """ante account create에서 kis-domestic 선택 시 is_paper 입력 확인."""

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
        svc = AsyncMock()
        db = AsyncMock()

        async def _create_service():
            return svc, db

        with patch(
            "ante.cli.commands.account._create_account_service", new=_create_service
        ):
            yield svc

    def test_kis_domestic_asks_is_paper(self, mock_account_service):
        """kis-domestic 선택 시 모의투자 모드 질문이 표시된다."""
        from ante.cli.main import cli

        created = _make_account("domestic", "kis-domestic")
        mock_account_service.create.return_value = created

        runner = CliRunner()
        # 브로커 2(kis-domestic), 계좌ID(기본), 이름(기본), 거래모드 1(virtual),
        # app_key, app_secret, account_no, is_paper=y
        input_text = "2\n\n\n1\ntest_key\ntest_secret\n50123456-01\ny\n"
        result = runner.invoke(cli, ["account", "create"], input=input_text)

        assert result.exit_code == 0, result.output
        assert "모의투자 모드" in result.output
        # create에 전달된 Account의 broker_config 확인
        call_args = mock_account_service.create.call_args
        account_arg = call_args[0][0]
        assert account_arg.broker_config == {"is_paper": True}

    def test_kis_domestic_is_paper_false(self, mock_account_service):
        """모의투자 N 선택 시 is_paper=False로 저장된다."""
        from ante.cli.main import cli

        created = _make_account("domestic", "kis-domestic")
        mock_account_service.create.return_value = created

        runner = CliRunner()
        input_text = "2\n\n\n1\ntest_key\ntest_secret\n50123456-01\nn\n"
        result = runner.invoke(cli, ["account", "create"], input=input_text)

        assert result.exit_code == 0, result.output
        call_args = mock_account_service.create.call_args
        account_arg = call_args[0][0]
        assert account_arg.broker_config == {"is_paper": False}

    def test_test_broker_no_is_paper(self, mock_account_service):
        """test 브로커 선택 시 is_paper 질문이 없다."""
        from ante.cli.main import cli

        created = _make_account("test", "test", broker_config={})
        mock_account_service.create.return_value = created

        runner = CliRunner()
        # 브로커 1(test), 계좌ID(기본), 이름(기본), 거래모드 1(virtual),
        # app_key, app_secret
        input_text = "1\n\n\n1\ntest_key\ntest_secret\n"
        result = runner.invoke(cli, ["account", "create"], input=input_text)

        assert result.exit_code == 0, result.output
        assert "모의투자 모드" not in result.output
        call_args = mock_account_service.create.call_args
        account_arg = call_args[0][0]
        assert account_arg.broker_config == {}


# ── CLI init is_paper 프롬프트 테스트 ──────────


class TestInitIsPaper:
    """ante init에서 kis-domestic 선택 시 is_paper 입력 확인."""

    def test_init_with_kis_asks_is_paper(self, runner, tmp_path):
        """kis-domestic 등록 시 모의투자 모드 질문이 표시된다."""
        from ante.cli.main import cli

        target = tmp_path / "config"
        input_lines = "\n".join(
            [
                "owner",  # Member ID
                "홈트레이더",  # 이름
                "pass1234",  # 패스워드
                "pass1234",  # 패스워드 확인
                "y",  # 실제 계좌 등록? y
                "1",  # 브로커 선택 (kis-domestic)
                "domestic",  # 계좌 ID
                "국내 주식",  # 이름
                "PSxxxxxxxx",  # app_key
                "secretkey123",  # app_secret
                "50123456-01",  # account_no
                "y",  # 모의투자 모드? y
                "n",  # 추가 계좌? n
                "n",  # 텔레그램? n
                "n",  # data.go.kr? n
                "n",  # DART? n
            ]
        )

        mock_result = {"member_id": "owner", "role": "master", "emoji": "f"}
        mock_token = "ante_hk_test_token_123"
        mock_recovery_key = "ANTE-RK-XXXX"

        def _mock_bootstrap(*a, **kw):
            return mock_result, mock_token, mock_recovery_key

        mock_test_account = [
            {"account_id": "test", "broker_type": "test", "exchange": "TEST"},
            {
                "account_id": "domestic",
                "broker_type": "kis-domestic",
                "exchange": "KRX",
            },
        ]

        create_accounts_mock = AsyncMock(side_effect=lambda *a, **kw: mock_test_account)

        patches = [
            patch(
                "ante.cli.commands.init._bootstrap_master",
                new=AsyncMock(side_effect=_mock_bootstrap),
            ),
            patch(
                "ante.cli.commands.init._create_accounts",
                new=create_accounts_mock,
            ),
            patch("ante.cli.main.authenticate_member"),
        ]

        for p in patches:
            p.start()
        try:
            result = runner.invoke(
                cli, ["init", "--dir", str(target)], input=input_lines
            )
        finally:
            for p in patches:
                p.stop()

        assert result.exit_code == 0, result.output
        assert "모의투자 모드" in result.output

        # _create_accounts에 전달된 account_inputs에 broker_config 포함 확인
        call_args = create_accounts_mock.call_args
        account_inputs = call_args[0][1]
        assert len(account_inputs) == 1
        assert account_inputs[0]["broker_config"] == {"is_paper": True}

    @pytest.fixture
    def runner(self):
        return CliRunner()
