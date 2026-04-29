"""ante account CLI 명령어 테스트."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner

from ante.cli.commands.account import mask_value

# ── mask_value 단위 테스트 ──────────────────────────────


class TestMaskValue:
    """mask_value 함수 테스트."""

    def test_short_value_masked_fully(self) -> None:
        """6자 이하는 '****'로 마스킹."""
        assert mask_value("key", "abc") == "****"
        assert mask_value("key", "123456") == "****"

    def test_long_value_partial_mask(self) -> None:
        """6자 초과는 앞 4자 + '****' + 뒤 2자."""
        assert mask_value("key", "PSxxxxxxxx") == "PSxx****xx"
        assert mask_value("key", "1234567") == "1234****67"

    def test_exactly_seven_chars(self) -> None:
        """7자(경계값) 테스트."""
        assert mask_value("key", "abcdefg") == "abcd****fg"

    def test_empty_value(self) -> None:
        """빈 문자열은 6자 이하이므로 '****'."""
        assert mask_value("key", "") == "****"


# ── CLI 통합 테스트 헬퍼 ──────────────────────────────


def _make_cli():
    """테스트용 CLI 인스턴스를 생성한다 (인증 우회)."""
    from ante.cli.main import cli

    return cli


def _invoke(args: list[str], input_text: str | None = None):
    """CLI를 실행하고 결과를 반환한다."""
    runner = CliRunner()
    cli = _make_cli()
    env = {"ANTE_MEMBER_TOKEN": ""}
    result = runner.invoke(cli, args, env=env, input=input_text, catch_exceptions=False)
    return result


# ── Account 모듈 Mock ──────────────────────────────


def _mock_account(
    account_id: str = "test",
    name: str = "테스트",
    exchange: str = "TEST",
    currency: str = "KRW",
    broker_type: str = "test",
    status: str = "active",
    trading_mode: str = "virtual",
    credentials: dict | None = None,
):
    """테스트용 Account mock 객체."""
    from decimal import Decimal

    from ante.account.models import Account, AccountStatus, TradingMode

    return Account(
        account_id=account_id,
        name=name,
        exchange=exchange,
        currency=currency,
        broker_type=broker_type,
        status=AccountStatus(status),
        trading_mode=TradingMode(trading_mode),
        credentials=credentials or {},
        buy_commission_rate=Decimal("0.00015"),
        sell_commission_rate=Decimal("0.00195"),
    )


@pytest.fixture
def mock_account_service():
    """AccountService mock을 patch하는 fixture."""
    svc = AsyncMock()
    db = AsyncMock()

    async def _create_service():
        return svc, db

    with patch(
        "ante.cli.commands.account._create_account_service", new=_create_service
    ):
        yield svc


@pytest.fixture(autouse=True)
def bypass_auth():
    """인증을 우회한다."""
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


# ── account list 테스트 ──────────────────────────────


class TestAccountList:
    """ante account list 테스트."""

    def test_list_empty(self, mock_account_service: AsyncMock) -> None:
        """계좌가 없으면 빈 목록 메시지."""
        mock_account_service.list.return_value = []
        result = _invoke(["account", "list"])
        assert result.exit_code == 0
        assert "등록된 계좌가 없습니다" in result.output

    def test_list_text_format(self, mock_account_service: AsyncMock) -> None:
        """텍스트 모드로 계좌 목록 출력."""
        mock_account_service.list.return_value = [
            _mock_account("test", "테스트", "TEST", "KRW", "test"),
            _mock_account("domestic", "국내 주식", "KRX", "KRW", "kis-domestic"),
        ]
        result = _invoke(["account", "list"])
        assert result.exit_code == 0
        assert "test" in result.output
        assert "domestic" in result.output

    def test_list_json_format(self, mock_account_service: AsyncMock) -> None:
        """JSON 모드로 계좌 목록 출력."""
        mock_account_service.list.return_value = [
            _mock_account("test", "테스트", "TEST", "KRW", "test"),
        ]
        result = _invoke(["--format", "json", "account", "list"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "accounts" in data
        assert len(data["accounts"]) == 1
        assert data["accounts"][0]["account_id"] == "test"

    def test_list_with_status_filter(self, mock_account_service: AsyncMock) -> None:
        """--status 필터로 목록 조회."""
        mock_account_service.list.return_value = [
            _mock_account("test", "테스트", status="suspended"),
        ]
        result = _invoke(["account", "list", "--status", "suspended"])
        assert result.exit_code == 0


# ── account info 테스트 ──────────────────────────────


class TestAccountInfo:
    """ante account info 테스트."""

    def test_info_text_format(self, mock_account_service: AsyncMock) -> None:
        """텍스트 모드로 계좌 상세 출력."""
        mock_account_service.get.return_value = _mock_account(
            "domestic", "국내 주식", "KRX", "KRW", "kis-domestic"
        )
        result = _invoke(["account", "info", "domestic"])
        assert result.exit_code == 0
        assert "국내 주식" in result.output
        assert "KRX" in result.output

    def test_info_json_format(self, mock_account_service: AsyncMock) -> None:
        """JSON 모드로 계좌 상세 출력."""
        mock_account_service.get.return_value = _mock_account(
            "domestic", "국내 주식", "KRX", "KRW", "kis-domestic"
        )
        result = _invoke(["--format", "json", "account", "info", "domestic"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["account_id"] == "domestic"
        assert data["exchange"] == "KRX"

    def test_info_not_found(self, mock_account_service: AsyncMock) -> None:
        """존재하지 않는 계좌 조회."""
        from ante.account.errors import AccountNotFoundError

        mock_account_service.get.side_effect = AccountNotFoundError("not found")
        result = _invoke(["account", "info", "nope"])
        assert result.exit_code == 1


# ── account credentials 마스킹 테스트 ──────────────────


class TestAccountCredentials:
    """ante account credentials 테스트."""

    def test_credentials_masking(self, mock_account_service: AsyncMock) -> None:
        """인증 정보가 마스킹되어 출력된다."""
        mock_account_service.get.return_value = _mock_account(
            "domestic",
            credentials={
                "app_key": "PSxxxxxxxx",
                "app_secret": "abcdefghij1234567890abcdefghij12",
                "account_no": "50123456-01",
            },
        )
        result = _invoke(["account", "credentials", "domestic"])
        assert result.exit_code == 0
        assert "PSxx****xx" in result.output
        assert "abcd****12" in result.output
        assert "5012****01" in result.output

    def test_credentials_json_format(self, mock_account_service: AsyncMock) -> None:
        """JSON 모드로 마스킹된 인증 정보 출력."""
        mock_account_service.get.return_value = _mock_account(
            "domestic",
            credentials={"app_key": "PSxxxxxxxx"},
        )
        result = _invoke(["--format", "json", "account", "credentials", "domestic"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["credentials"]["app_key"] == "PSxx****xx"

    def test_credentials_empty(self, mock_account_service: AsyncMock) -> None:
        """인증 정보가 없는 계좌."""
        mock_account_service.get.return_value = _mock_account("test", credentials={})
        result = _invoke(["account", "credentials", "test"])
        assert result.exit_code == 0
        assert "등록된 인증 정보가 없습니다" in result.output


# ── active runtime guard 헬퍼 ──────────────────────────────


@pytest.fixture
def offline_runtime():
    """active runtime이 없는 상태(PID 파일 부재)를 모사한다.

    cold-path 명령이 active runtime guard를 통과하도록 read_pid_file이
    None을 반환하게 하고, 보강 socket guard가 호출되어도 안전하도록
    get_socket_path가 존재하지 않는 임시 경로를 반환하게 한다.
    """
    with (
        patch("ante.main.read_pid_file", return_value=None),
        patch(
            "ante.cli.commands.ipc_helpers.get_socket_path",
            return_value="/tmp/__ante_offline_runtime_test__.sock",
        ),
    ):
        yield


@pytest.fixture
def active_runtime():
    """active runtime(PID alive + socket present)을 모사한다."""
    import tempfile
    from pathlib import Path

    with tempfile.NamedTemporaryFile(
        prefix="ante_active_runtime_", suffix=".sock"
    ) as f:
        socket_path = f.name
        # 파일이 존재하는 상태로 patches 적용
        with (
            patch("ante.main.read_pid_file", return_value=12345),
            patch(
                "ante.cli.commands.account.os.kill",
                return_value=None,
            ),
            patch(
                "ante.cli.commands.ipc_helpers.get_socket_path",
                return_value=socket_path,
            ),
        ):
            assert Path(socket_path).exists()
            yield


# ── account create 대화형 테스트 ──────────────────


class TestAccountCreate:
    """ante account create 테스트."""

    def test_create_interactive(
        self, mock_account_service: AsyncMock, offline_runtime
    ) -> None:
        """대화형 생성 흐름이 정상 동작한다."""
        created = _mock_account("test", "테스트", "TEST", "KRW", "test")
        mock_account_service.create.return_value = created

        # 입력: 브로커 1(test), 계좌ID(기본), 이름(기본), 거래모드 1(virtual),
        # 인증정보: app_key=test, app_secret=test
        input_text = "1\n\n\n1\ntest\ntest\n"
        result = _invoke(["account", "create"], input_text=input_text)
        assert result.exit_code == 0
        assert "생성 완료" in result.output
        mock_account_service.create.assert_called_once()

    def test_create_blocked_when_active_runtime(
        self, mock_account_service: AsyncMock, active_runtime
    ) -> None:
        """active runtime이 있으면 cold-path가 차단된다."""
        input_text = "1\n\n\n1\ntest\ntest\n"
        result = _invoke(["account", "create"], input_text=input_text)
        assert result.exit_code == 1
        assert "ACCOUNT_STRUCTURAL_CHANGE_REQUIRES_STOPPED_SERVER" in result.output
        mock_account_service.create.assert_not_called()

    def test_create_offline_succeeds(self, mock_account_service: AsyncMock) -> None:
        """PID 파일 부재(offline) 시 guard 통과."""
        created = _mock_account("test", "테스트", "TEST", "KRW", "test")
        mock_account_service.create.return_value = created

        with (
            patch("ante.main.read_pid_file", return_value=None),
            patch(
                "ante.cli.commands.ipc_helpers.get_socket_path",
                return_value="/tmp/__ante_does_not_exist__.sock",
            ),
        ):
            input_text = "1\n\n\n1\ntest\ntest\n"
            result = _invoke(["account", "create"], input_text=input_text)
        assert result.exit_code == 0
        mock_account_service.create.assert_called_once()

    def test_create_offline_when_pid_alive_but_socket_absent(
        self, mock_account_service: AsyncMock
    ) -> None:
        """PID는 alive지만 socket이 부재하면 stale PID로 보고 guard 통과."""
        created = _mock_account("test", "테스트", "TEST", "KRW", "test")
        mock_account_service.create.return_value = created

        with (
            patch("ante.main.read_pid_file", return_value=12345),
            patch(
                "ante.cli.commands.account.os.kill",
                return_value=None,
            ),
            patch(
                "ante.cli.commands.ipc_helpers.get_socket_path",
                return_value="/tmp/__ante_no_such_socket_xxx__.sock",
            ),
        ):
            input_text = "1\n\n\n1\ntest\ntest\n"
            result = _invoke(["account", "create"], input_text=input_text)
        assert result.exit_code == 0
        mock_account_service.create.assert_called_once()


# ── account suspend/activate/delete 테스트 ──────────


class TestAccountStateTransitions:
    """계좌 상태 전이 커맨드 테스트."""

    def test_suspend(self) -> None:
        """계좌 정지 (IPC 전환)."""
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
                result = _invoke(["account", "suspend", "domestic"])

        assert result.exit_code == 0
        assert "정지 완료" in result.output
        mock_client.send.assert_called_once()

    def test_activate(self) -> None:
        """계좌 활성화 (IPC 전환)."""
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
                result = _invoke(["account", "activate", "domestic"])

        assert result.exit_code == 0
        assert "활성화 완료" in result.output
        mock_client.send.assert_called_once()

    def test_delete_with_yes(
        self, mock_account_service: AsyncMock, offline_runtime
    ) -> None:
        """계좌 삭제 (--yes 옵션, cold-path direct service 호출)."""
        mock_account_service.delete.return_value = None

        result = _invoke(["account", "delete", "domestic", "--yes"])

        assert result.exit_code == 0
        assert "삭제 완료" in result.output
        mock_account_service.delete.assert_called_once()

    def test_delete_with_confirm(
        self, mock_account_service: AsyncMock, offline_runtime
    ) -> None:
        """계좌 삭제 (확인 프롬프트 y 입력, cold-path direct service 호출)."""
        mock_account_service.delete.return_value = None

        result = _invoke(["account", "delete", "domestic"], input_text="y\n")

        assert result.exit_code == 0
        assert "삭제 완료" in result.output
        mock_account_service.delete.assert_called_once()

    def test_delete_abort(self) -> None:
        """계좌 삭제 취소 (확인 프롬프트 n 입력)."""
        result = _invoke(["account", "delete", "domestic"], input_text="n\n")
        assert result.exit_code == 1

    def test_delete_blocked_when_active_runtime(
        self, mock_account_service: AsyncMock, active_runtime
    ) -> None:
        """active runtime이 있으면 cold-path delete가 차단된다."""
        result = _invoke(["account", "delete", "domestic", "--yes"])
        assert result.exit_code == 1
        assert "ACCOUNT_STRUCTURAL_CHANGE_REQUIRES_STOPPED_SERVER" in result.output
        mock_account_service.delete.assert_not_called()

    def test_delete_offline_succeeds(self, mock_account_service: AsyncMock) -> None:
        """PID 파일 부재(offline) 시 guard 통과 후 delete 호출."""
        mock_account_service.delete.return_value = None
        with (
            patch("ante.main.read_pid_file", return_value=None),
            patch(
                "ante.cli.commands.ipc_helpers.get_socket_path",
                return_value="/tmp/__ante_does_not_exist_del__.sock",
            ),
        ):
            result = _invoke(["account", "delete", "domestic", "--yes"])
        assert result.exit_code == 0
        mock_account_service.delete.assert_called_once()

    def test_delete_offline_when_pid_alive_but_socket_absent(
        self, mock_account_service: AsyncMock
    ) -> None:
        """PID alive지만 socket 부재면 stale PID로 보고 guard 통과."""
        mock_account_service.delete.return_value = None
        with (
            patch("ante.main.read_pid_file", return_value=12345),
            patch("ante.cli.commands.account.os.kill", return_value=None),
            patch(
                "ante.cli.commands.ipc_helpers.get_socket_path",
                return_value="/tmp/__ante_no_socket_del_xxx__.sock",
            ),
        ):
            result = _invoke(["account", "delete", "domestic", "--yes"])
        assert result.exit_code == 0
        mock_account_service.delete.assert_called_once()

    def test_delete_blocks_when_active_bots_present(
        self, mock_account_service: AsyncMock, offline_runtime
    ) -> None:
        """non-deleted 봇이 있는 계좌의 delete는 명확한 메시지로 차단된다."""
        from ante.account.errors import AccountHasActiveBotsError

        mock_account_service.delete.side_effect = AccountHasActiveBotsError(
            account_id="domestic",
            bot_count=2,
        )

        result = _invoke(["account", "delete", "domestic", "--yes"])

        assert result.exit_code == 1
        assert "domestic" in result.output
        # bot_count 또는 명확한 메시지가 사용자에게 노출되어야 한다
        assert "봇" in result.output or "bot" in result.output.lower()
        mock_account_service.delete.assert_called_once()


# ── account set-credentials cold-path guard 테스트 ──────


class TestAccountSetCredentialsRuntimeGuard:
    """ante account set-credentials cold-path active runtime guard."""

    def test_set_credentials_blocked_when_active_runtime(
        self, mock_account_service: AsyncMock, active_runtime
    ) -> None:
        """active runtime이 있으면 cold-path set-credentials가 차단된다."""
        result = _invoke(
            [
                "account",
                "set-credentials",
                "domestic",
                "--app-key",
                "k",
                "--app-secret",
                "s",
            ]
        )
        assert result.exit_code == 1
        assert "ACCOUNT_STRUCTURAL_CHANGE_REQUIRES_STOPPED_SERVER" in result.output
        mock_account_service.update.assert_not_called()

    def test_set_credentials_offline_succeeds(
        self, mock_account_service: AsyncMock
    ) -> None:
        """PID 파일 부재(offline) 시 guard 통과 후 update 호출."""
        from decimal import Decimal

        from ante.account.models import Account, AccountStatus, TradingMode

        mock_account_service.get.return_value = Account(
            account_id="domestic",
            name="국내",
            exchange="KRX",
            currency="KRW",
            broker_type="kis-domestic",
            status=AccountStatus.ACTIVE,
            trading_mode=TradingMode.VIRTUAL,
            credentials={},
            buy_commission_rate=Decimal("0.00015"),
            sell_commission_rate=Decimal("0.00195"),
        )
        mock_account_service.update.return_value = None

        with (
            patch("ante.main.read_pid_file", return_value=None),
            patch(
                "ante.cli.commands.ipc_helpers.get_socket_path",
                return_value="/tmp/__ante_offline_setc__.sock",
            ),
        ):
            result = _invoke(
                [
                    "account",
                    "set-credentials",
                    "domestic",
                    "--app-key",
                    "k",
                    "--app-secret",
                    "s",
                ]
            )
        assert result.exit_code == 0
        mock_account_service.update.assert_called_once()

    def test_set_credentials_offline_when_pid_alive_but_socket_absent(
        self, mock_account_service: AsyncMock
    ) -> None:
        """PID alive지만 socket 부재면 stale PID로 보고 guard 통과."""
        from decimal import Decimal

        from ante.account.models import Account, AccountStatus, TradingMode

        mock_account_service.get.return_value = Account(
            account_id="domestic",
            name="국내",
            exchange="KRX",
            currency="KRW",
            broker_type="kis-domestic",
            status=AccountStatus.ACTIVE,
            trading_mode=TradingMode.VIRTUAL,
            credentials={},
            buy_commission_rate=Decimal("0.00015"),
            sell_commission_rate=Decimal("0.00195"),
        )
        mock_account_service.update.return_value = None

        with (
            patch("ante.main.read_pid_file", return_value=12345),
            patch("ante.cli.commands.account.os.kill", return_value=None),
            patch(
                "ante.cli.commands.ipc_helpers.get_socket_path",
                return_value="/tmp/__ante_no_socket_setc_xxx__.sock",
            ),
        ):
            result = _invoke(
                [
                    "account",
                    "set-credentials",
                    "domestic",
                    "--app-key",
                    "k",
                    "--app-secret",
                    "s",
                ]
            )
        assert result.exit_code == 0
        mock_account_service.update.assert_called_once()
