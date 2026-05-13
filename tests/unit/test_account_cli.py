"""ante account CLI 명령어 테스트."""

from __future__ import annotations

import json
from typing import Any
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


def _invoke(args: list[str]):
    """CLI를 실행하고 결과를 반환한다."""
    runner = CliRunner()
    cli = _make_cli()
    env = {"ANTE_MEMBER_TOKEN": ""}
    result = runner.invoke(cli, args, env=env, catch_exceptions=False)
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

    def test_account_list_invalid_status_rejected_before_db(self) -> None:
        """invalid `--status`는 `_create_account_service` 호출 전 차단된다 (#1462).

        AccountStatus enum (SSOT)에 없는 status 값이 들어오면 preflight가
        `ACCOUNT_INVALID_STATUS` 구조화 에러로 종료시키며, DB 접속을 위한
        `_create_account_service`는 호출되지 않아야 한다.
        """
        mock_create = AsyncMock()
        with patch(
            "ante.cli.commands.account._create_account_service",
            new=mock_create,
        ):
            result = _invoke(
                [
                    "--format",
                    "json",
                    "account",
                    "list",
                    "--status",
                    "oracle_invalid_status",
                ]
            )
        assert result.exit_code == 1
        data = json.loads(result.output.strip())
        assert data["status"] == "error"
        assert data["code"] == "ACCOUNT_INVALID_STATUS"
        assert "oracle_invalid_status" in data["message"]
        assert "Traceback" not in result.output
        mock_create.assert_not_called()

    def test_account_list_valid_status_still_works(
        self, mock_account_service: AsyncMock
    ) -> None:
        """valid `--status` 입력은 회귀 없이 정상 동작한다 (#1462).

        ACTIVE / SUSPENDED / DELETED 세 가지 valid 값 모두 preflight를 통과하고
        AccountService.list가 enum 값으로 호출된다.
        """
        from ante.account.models import AccountStatus

        mock_account_service.list.return_value = []
        for valid in ("active", "suspended", "deleted"):
            mock_account_service.list.reset_mock()
            result = _invoke(["account", "list", "--status", valid])
            assert result.exit_code == 0, result.output
            mock_account_service.list.assert_called_once_with(
                status=AccountStatus(valid),
            )


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


# ── account create 비대화형 테스트 ──────────────────

# 비대화형 입력 계약 SSOT: docs/specs/cli/02-design-decisions.md
# (비대화형 입력 계약 — CLI Non-Interactive Input Contract).


def _create_args_test_broker(
    *,
    account_id: str = "test2",
    name: str = "테스트2",
    trading_mode: str = "virtual",
    extra: list[str] | None = None,
) -> list[str]:
    """``broker-type=test``용 표준 비대화형 인자 세트.

    test broker preset은 ``required_credentials=["app_key", "app_secret"]``이므로
    두 credential을 ``--credential``로 직접 제공한다.
    """
    args = [
        "account",
        "create",
        "--broker-type",
        "test",
        "--account-id",
        account_id,
        "--name",
        name,
        "--trading-mode",
        trading_mode,
        "--credential",
        "app_key=K",
        "--credential",
        "app_secret=S",
    ]
    if extra:
        args.extend(extra)
    return args


class TestAccountCreate:
    """ante account create 비대화형 테스트."""

    def test_create_with_options(
        self, mock_account_service: AsyncMock, offline_runtime
    ) -> None:
        """옵션 기반 비대화형 생성이 정상 동작한다."""
        created = _mock_account("test2", "테스트2", "TEST", "KRW", "test")
        mock_account_service.create.return_value = created

        result = _invoke(_create_args_test_broker())
        assert result.exit_code == 0, result.output
        assert "생성 완료" in result.output
        mock_account_service.create.assert_called_once()

    def test_create_market_buffer_default_uses_preset(
        self, mock_account_service: AsyncMock, offline_runtime
    ) -> None:
        """``--market-order-reserve-buffer-rate`` 누락 시 BrokerPreset 기본값을
        그대로 사용한다 (test broker → 0; #1333).
        """
        from decimal import Decimal

        created = _mock_account("test2", "테스트2", "TEST", "KRW", "test")
        mock_account_service.create.return_value = created

        result = _invoke(_create_args_test_broker())
        assert result.exit_code == 0, result.output
        new_account = mock_account_service.create.call_args.args[0]
        assert new_account.market_order_reserve_buffer_rate == Decimal("0")

    def test_create_market_buffer_explicit_decimal_conversion(
        self, mock_account_service: AsyncMock, offline_runtime
    ) -> None:
        """명시한 ``--market-order-reserve-buffer-rate`` 값이 ``Decimal(str(...))``
        로 변환되어 Account 에 전달된다 (#1333).
        """
        from decimal import Decimal

        created = _mock_account("test2", "테스트2", "TEST", "KRW", "test")
        mock_account_service.create.return_value = created

        result = _invoke(
            _create_args_test_broker(
                extra=["--market-order-reserve-buffer-rate", "0.0075"]
            )
        )
        assert result.exit_code == 0, result.output
        new_account = mock_account_service.create.call_args.args[0]
        # ``Decimal(str(0.0075))`` 는 정확히 ``Decimal("0.0075")``.
        assert new_account.market_order_reserve_buffer_rate == Decimal("0.0075")
        assert isinstance(new_account.market_order_reserve_buffer_rate, Decimal)

    def test_create_json_output(
        self, mock_account_service: AsyncMock, offline_runtime
    ) -> None:
        """--format json 출력이 success 페이로드를 포함한다."""
        created = _mock_account("test2", "테스트2", "TEST", "KRW", "test")
        mock_account_service.create.return_value = created

        result = _invoke(_create_args_test_broker(extra=["--format", "json"]))
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["status"] == "ok"
        assert data["data"]["account_id"] == "test2"
        assert data["data"]["broker_type"] == "test"

    def test_create_blocked_when_active_runtime(
        self, mock_account_service: AsyncMock, active_runtime
    ) -> None:
        """active runtime이 있으면 cold-path가 차단된다."""
        result = _invoke(_create_args_test_broker())
        assert result.exit_code == 1
        assert "ACCOUNT_STRUCTURAL_CHANGE_REQUIRES_STOPPED_SERVER" in result.output
        mock_account_service.create.assert_not_called()

    def test_create_offline_succeeds(self, mock_account_service: AsyncMock) -> None:
        """PID 파일 부재(offline) 시 guard 통과."""
        created = _mock_account("test2", "테스트2", "TEST", "KRW", "test")
        mock_account_service.create.return_value = created

        with (
            patch("ante.main.read_pid_file", return_value=None),
            patch(
                "ante.cli.commands.ipc_helpers.get_socket_path",
                return_value="/tmp/__ante_does_not_exist__.sock",
            ),
        ):
            result = _invoke(_create_args_test_broker())
        assert result.exit_code == 0, result.output
        mock_account_service.create.assert_called_once()

    def test_create_offline_when_pid_alive_but_socket_absent(
        self, mock_account_service: AsyncMock
    ) -> None:
        """PID는 alive지만 socket이 부재하면 stale PID로 보고 guard 통과."""
        created = _mock_account("test2", "테스트2", "TEST", "KRW", "test")
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
            result = _invoke(_create_args_test_broker())
        assert result.exit_code == 0, result.output
        mock_account_service.create.assert_called_once()

    def test_create_missing_broker_type(
        self, mock_account_service: AsyncMock, offline_runtime
    ) -> None:
        """필수 옵션 ``--broker-type`` 누락 시 즉시 에러로 종료한다."""
        result = _invoke(
            [
                "account",
                "create",
                "--account-id",
                "x",
                "--name",
                "X",
                "--trading-mode",
                "virtual",
                "--credential",
                "app_key=K",
                "--credential",
                "app_secret=S",
            ]
        )
        assert result.exit_code == 1
        assert "CLI_MISSING_REQUIRED_INPUT" in result.output
        assert "--broker-type" in result.output
        mock_account_service.create.assert_not_called()

    def test_create_missing_required_credential(
        self, mock_account_service: AsyncMock, offline_runtime
    ) -> None:
        """``required_credentials``에 정의된 key 누락 시 명시적 에러."""
        result = _invoke(
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
                "app_key=K",
                # app_secret 누락
            ]
        )
        assert result.exit_code == 1
        assert "ACCOUNT_MISSING_REQUIRED_CREDENTIAL" in result.output
        assert "app_secret" in result.output
        mock_account_service.create.assert_not_called()

    def test_create_unknown_credential_key(
        self, mock_account_service: AsyncMock, offline_runtime
    ) -> None:
        """``required_credentials`` 외 key는 ``ACCOUNT_UNKNOWN_CREDENTIAL_KEY``."""
        result = _invoke(
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
                "app_key=K",
                "--credential",
                "app_secret=S",
                "--credential",
                "extra_key=X",
            ]
        )
        assert result.exit_code == 1
        assert "ACCOUNT_UNKNOWN_CREDENTIAL_KEY" in result.output
        mock_account_service.create.assert_not_called()

    def test_create_duplicate_credential_key_across_channels(
        self, mock_account_service: AsyncMock, offline_runtime, monkeypatch
    ) -> None:
        """같은 key를 두 채널로 입력하면 ``ACCOUNT_DUPLICATE_CREDENTIAL_KEY``."""
        monkeypatch.setenv("TEST_APP_SECRET_ENV", "S")
        result = _invoke(
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
                "app_key=K",
                "--credential",
                "app_secret=S1",
                "--credential-env",
                "app_secret=TEST_APP_SECRET_ENV",
            ]
        )
        assert result.exit_code == 1
        assert "ACCOUNT_DUPLICATE_CREDENTIAL_KEY" in result.output
        mock_account_service.create.assert_not_called()

    def test_create_credential_env_not_set(
        self, mock_account_service: AsyncMock, offline_runtime, monkeypatch
    ) -> None:
        """``--credential-env``이 참조한 환경변수가 없으면 명시적 에러."""
        monkeypatch.delenv("TEST_NO_SUCH_ENV", raising=False)
        result = _invoke(
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
                "app_key=K",
                "--credential-env",
                "app_secret=TEST_NO_SUCH_ENV",
            ]
        )
        assert result.exit_code == 1
        assert "ACCOUNT_CREDENTIAL_ENV_NOT_SET" in result.output
        mock_account_service.create.assert_not_called()

    def test_create_credential_env_blank(
        self, mock_account_service: AsyncMock, offline_runtime, monkeypatch
    ) -> None:
        """``--credential-env`` 환경변수 값이 공란이면 명시적 에러."""
        monkeypatch.setenv("TEST_BLANK_ENV", "")
        result = _invoke(
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
                "app_key=K",
                "--credential-env",
                "app_secret=TEST_BLANK_ENV",
            ]
        )
        assert result.exit_code == 1
        assert "ACCOUNT_CREDENTIAL_ENV_NOT_SET" in result.output
        mock_account_service.create.assert_not_called()

    def test_create_credential_file(
        self, mock_account_service: AsyncMock, offline_runtime, tmp_path
    ) -> None:
        """``--credential-file`` 경로의 파일을 읽어 credential로 사용한다."""
        secret_path = tmp_path / "secret.txt"
        secret_path.write_text("FILE_SECRET\n", encoding="utf-8")

        created = _mock_account("test2", "테스트2", "TEST", "KRW", "test")
        mock_account_service.create.return_value = created

        result = _invoke(
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
                "app_key=K",
                "--credential-file",
                f"app_secret={secret_path}",
            ]
        )
        assert result.exit_code == 0, result.output
        mock_account_service.create.assert_called_once()
        # service.create에 전달된 Account의 credentials 검증
        account_arg = mock_account_service.create.call_args[0][0]
        assert account_arg.credentials == {"app_key": "K", "app_secret": "FILE_SECRET"}

    def test_create_credential_file_not_found(
        self, mock_account_service: AsyncMock, offline_runtime, tmp_path
    ) -> None:
        """credential-file 경로가 부재하면 ACCOUNT_CREDENTIAL_FILE_NOT_FOUND."""
        missing = tmp_path / "nonexistent.txt"
        result = _invoke(
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
                "app_key=K",
                "--credential-file",
                f"app_secret={missing}",
            ]
        )
        assert result.exit_code == 1
        assert "ACCOUNT_CREDENTIAL_FILE_NOT_FOUND" in result.output
        mock_account_service.create.assert_not_called()

    def test_create_kis_with_env_and_broker_config(
        self, mock_account_service: AsyncMock, offline_runtime, monkeypatch
    ) -> None:
        """KIS 계좌: env credential + ``--broker-config is_paper=true``."""
        monkeypatch.setenv("ANTE_KIS_APP_KEY", "K")
        monkeypatch.setenv("ANTE_KIS_APP_SECRET", "S")
        monkeypatch.setenv("ANTE_KIS_ACCOUNT_NO", "5012XXXX-01")

        created = _mock_account("domestic", "국내 주식", "KRX", "KRW", "kis-domestic")
        mock_account_service.create.return_value = created

        result = _invoke(
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
                "--credential-env",
                "app_key=ANTE_KIS_APP_KEY",
                "--credential-env",
                "app_secret=ANTE_KIS_APP_SECRET",
                "--credential-env",
                "account_no=ANTE_KIS_ACCOUNT_NO",
                "--broker-config",
                "is_paper=true",
            ]
        )
        assert result.exit_code == 0, result.output
        account_arg = mock_account_service.create.call_args[0][0]
        assert account_arg.credentials == {
            "app_key": "K",
            "app_secret": "S",
            "account_no": "5012XXXX-01",
        }
        assert account_arg.broker_config == {"is_paper": True}

    def test_create_unknown_broker_type(
        self, mock_account_service: AsyncMock, offline_runtime
    ) -> None:
        """``BROKER_REGISTRY`` 미등록 broker_type은 입력 단계에서 거부한다."""
        result = _invoke(
            [
                "account",
                "create",
                "--broker-type",
                "no-such-broker",
                "--account-id",
                "x",
                "--name",
                "X",
                "--trading-mode",
                "virtual",
                "--credential",
                "app_key=K",
                "--credential",
                "app_secret=S",
            ]
        )
        assert result.exit_code == 1
        assert "no-such-broker" in result.output
        mock_account_service.create.assert_not_called()

    def test_create_rejects_empty_direct_credential(
        self, mock_account_service: AsyncMock, offline_runtime
    ) -> None:
        """직접 채널 ``--credential KEY=`` (빈 값)은 env/file과 일관되게 거부한다.

        Codex P2-2: env 채널은 ``ACCOUNT_CREDENTIAL_ENV_NOT_SET``, file 채널은
        ``ACCOUNT_CREDENTIAL_FILE_NOT_FOUND``로 빈 값을 거부하지만, 직접
        채널은 빈 문자열을 그대로 통과시켜 unusable 계좌가 만들어질 위험이
        있었다. broker adapter 인증에 사용할 수 없는 빈 값은
        ``ACCOUNT_MISSING_REQUIRED_CREDENTIAL``로 즉시 실패한다.
        """
        result = _invoke(
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
                "app_key=",  # 빈 값
                "--credential",
                "app_secret=S",
            ]
        )
        assert result.exit_code == 1
        assert "ACCOUNT_MISSING_REQUIRED_CREDENTIAL" in result.output
        assert "app_key" in result.output
        mock_account_service.create.assert_not_called()

    def test_create_broker_config_decimal_stored_as_float(
        self, mock_account_service: AsyncMock, offline_runtime
    ) -> None:
        """``--broker-config retry_seconds=1.5`` 같은 소수는 ``float``로 저장한다.

        Codex P2-3: 이전 구현은 ``Decimal(text)`` 검증 후 ``str(text)``를 반환하여
        broker_config에 string이 저장됐다. KIS adapter는
        ``config.get("retry.backoff_base_seconds", DEFAULT)``처럼 numeric 값을
        직접 소비하므로(`src/ante/broker/kis.py`), 문자열 저장은 후속 산술
        연산에서 ``TypeError``를 유발한다. 또한 ``Account.broker_config``는
        ``json.dumps(...)``로 직렬화되므로 ``Decimal``은 JSON serializable이
        아니다 — ``float``로 변환해야 한다.
        """
        created = _mock_account("test2", "테스트2", "TEST", "KRW", "test")
        mock_account_service.create.return_value = created

        result = _invoke(
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
                "app_key=K",
                "--credential",
                "app_secret=S",
                "--broker-config",
                "retry_seconds=1.5",
                "--broker-config",
                "commission_rate=0.00015",
            ]
        )
        assert result.exit_code == 0, result.output
        account_arg = mock_account_service.create.call_args[0][0]
        assert account_arg.broker_config == {
            "retry_seconds": 1.5,
            "commission_rate": 0.00015,
        }
        # 값이 float native 타입인지 명시적으로 확인 (str/Decimal 회귀 방지)
        assert isinstance(account_arg.broker_config["retry_seconds"], float)
        assert isinstance(account_arg.broker_config["commission_rate"], float)


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

    def test_delete_without_yes_requires_confirmation(
        self, mock_account_service: AsyncMock, offline_runtime
    ) -> None:
        """``--yes`` 없이 호출하면 prompt 없이 ``CLI_CONFIRMATION_REQUIRED``로 실패한다.

        SSOT: docs/specs/cli/02-design-decisions.md — 위험 명령 확인 방식 표.
        """
        result = _invoke(["account", "delete", "domestic"])
        assert result.exit_code == 1
        assert "CLI_CONFIRMATION_REQUIRED" in result.output
        mock_account_service.delete.assert_not_called()

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


def _kis_account_for_setcred() -> Any:
    """KIS 계좌 mock (set-credentials 테스트용)."""
    from decimal import Decimal

    from ante.account.models import Account, AccountStatus, TradingMode

    return Account(
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
                "--credential",
                "app_key=k",
                "--credential",
                "app_secret=s",
                "--credential",
                "account_no=5012XXXX-01",
            ]
        )
        assert result.exit_code == 1
        assert "ACCOUNT_STRUCTURAL_CHANGE_REQUIRES_STOPPED_SERVER" in result.output
        mock_account_service.update.assert_not_called()

    def test_set_credentials_offline_succeeds(
        self, mock_account_service: AsyncMock
    ) -> None:
        """PID 파일 부재(offline) 시 guard 통과 후 update 호출."""
        mock_account_service.get.return_value = _kis_account_for_setcred()
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
                    "--credential",
                    "app_key=k",
                    "--credential",
                    "app_secret=s",
                    "--credential",
                    "account_no=5012XXXX-01",
                ]
            )
        assert result.exit_code == 0, result.output
        mock_account_service.update.assert_called_once()
        creds = mock_account_service.update.call_args.kwargs["credentials"]
        assert creds == {
            "app_key": "k",
            "app_secret": "s",
            "account_no": "5012XXXX-01",
        }

    def test_set_credentials_offline_when_pid_alive_but_socket_absent(
        self, mock_account_service: AsyncMock
    ) -> None:
        """PID alive지만 socket 부재면 stale PID로 보고 guard 통과."""
        mock_account_service.get.return_value = _kis_account_for_setcred()
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
                    "--credential",
                    "app_key=k",
                    "--credential",
                    "app_secret=s",
                    "--credential",
                    "account_no=5012XXXX-01",
                ]
            )
        assert result.exit_code == 0, result.output
        mock_account_service.update.assert_called_once()


class TestAccountSetCredentialsContract:
    """``account set-credentials`` 비대화형 입력 계약 검증."""

    def test_no_options_fails_without_prompt(
        self, mock_account_service: AsyncMock, offline_runtime
    ) -> None:
        """credential 옵션이 하나도 없으면 prompt 없이 즉시 실패."""
        mock_account_service.get.return_value = _kis_account_for_setcred()

        result = _invoke(["account", "set-credentials", "domestic"])
        assert result.exit_code == 1
        assert "ACCOUNT_MISSING_REQUIRED_CREDENTIAL" in result.output
        mock_account_service.update.assert_not_called()

    def test_partial_credentials_rejected(
        self, mock_account_service: AsyncMock, offline_runtime
    ) -> None:
        """KIS preset의 required_credentials 일부만 제공하면 실패."""
        mock_account_service.get.return_value = _kis_account_for_setcred()

        result = _invoke(
            [
                "account",
                "set-credentials",
                "domestic",
                "--credential",
                "app_key=k",
                "--credential",
                "app_secret=s",
                # account_no 누락
            ]
        )
        assert result.exit_code == 1
        assert "ACCOUNT_MISSING_REQUIRED_CREDENTIAL" in result.output
        assert "account_no" in result.output
        mock_account_service.update.assert_not_called()

    def test_unknown_credential_key_rejected(
        self, mock_account_service: AsyncMock, offline_runtime
    ) -> None:
        """required_credentials 외 key는 ``ACCOUNT_UNKNOWN_CREDENTIAL_KEY``."""
        mock_account_service.get.return_value = _kis_account_for_setcred()

        result = _invoke(
            [
                "account",
                "set-credentials",
                "domestic",
                "--credential",
                "app_key=k",
                "--credential",
                "app_secret=s",
                "--credential",
                "account_no=5012XXXX-01",
                "--credential",
                "extra=X",
            ]
        )
        assert result.exit_code == 1
        assert "ACCOUNT_UNKNOWN_CREDENTIAL_KEY" in result.output
        mock_account_service.update.assert_not_called()

    def test_duplicate_key_across_channels_rejected(
        self,
        mock_account_service: AsyncMock,
        offline_runtime,
        monkeypatch,
    ) -> None:
        """같은 key가 둘 이상 채널로 들어오면 ``ACCOUNT_DUPLICATE_CREDENTIAL_KEY``."""
        mock_account_service.get.return_value = _kis_account_for_setcred()

        monkeypatch.setenv("KIS_APP_SECRET", "S")
        result = _invoke(
            [
                "account",
                "set-credentials",
                "domestic",
                "--credential",
                "app_key=k",
                "--credential",
                "app_secret=s1",
                "--credential-env",
                "app_secret=KIS_APP_SECRET",
                "--credential",
                "account_no=5012XXXX-01",
            ]
        )
        assert result.exit_code == 1
        assert "ACCOUNT_DUPLICATE_CREDENTIAL_KEY" in result.output
        mock_account_service.update.assert_not_called()

    def test_env_and_file_resolution(
        self,
        mock_account_service: AsyncMock,
        offline_runtime,
        monkeypatch,
        tmp_path,
    ) -> None:
        """env + file + direct 채널을 합쳐 update에 그대로 전달한다."""
        mock_account_service.get.return_value = _kis_account_for_setcred()
        mock_account_service.update.return_value = None

        monkeypatch.setenv("KIS_APP_KEY", "ENV_KEY")
        secret_path = tmp_path / "kis_secret.txt"
        secret_path.write_text("FILE_SECRET\n", encoding="utf-8")

        result = _invoke(
            [
                "account",
                "set-credentials",
                "domestic",
                "--credential-env",
                "app_key=KIS_APP_KEY",
                "--credential-file",
                f"app_secret={secret_path}",
                "--credential",
                "account_no=5012XXXX-01",
            ]
        )
        assert result.exit_code == 0, result.output
        creds = mock_account_service.update.call_args.kwargs["credentials"]
        assert creds == {
            "app_key": "ENV_KEY",
            "app_secret": "FILE_SECRET",
            "account_no": "5012XXXX-01",
        }
