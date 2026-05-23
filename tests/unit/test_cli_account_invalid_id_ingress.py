"""제공된 invalid ``account_id`` cold-path CLI ingress 거부 회귀 (#1724).

#1634 Split A가 read-only account-scoped CLI(``account info``/``credentials``/
``suspend``/``activate``)에 적용한 ``reject_invalid_account_id`` 패턴을
나머지 cold-path 4 명령(``account create``/``delete``/``set-credentials``/
``repair-timezone``)으로 동형 확장한다.

본 PR 이전 상태(drift):

- ``account create default`` → ``EXECUTION_ERROR`` raw or empty (svc.create
  내부에서 RESTRICTED 차단 실패 메시지 노출).
- ``account delete default`` → ``ACCOUNT_NOT_FOUND`` 오분류 (svc.delete
  lookup이 SQL miss).
- ``account set-credentials default`` → ``ACCOUNT_NOT_FOUND`` 오분류 (svc.get
  lookup이 SQL miss).
- ``account repair-timezone default`` → ``ACCOUNT_NOT_FOUND`` 오분류.

본 PR이 적용된 후:

- create-path는 :func:`reject_invalid_new_account_id` (RESTRICTED-aware)
  helper로 거부 → ``VALIDATION_ERROR`` + exit 1.
- delete/set-credentials/repair-timezone은 :func:`reject_invalid_account_id`
  (lookup-policy) helper로 거부 → ``VALIDATION_ERROR`` + exit 1.

검증축 (이슈 #1724 Verification SSOT, plan R1-R10 압축):

- R1-R8: 4 명령 × {``default``, ``bad_id``} → ``VALIDATION_ERROR``
  (parameterized; service-layer 미호출 단정).
- R9: ``account delete nonexistent-acc-1 --yes`` (valid format, missing) →
  ``ACCOUNT_NOT_FOUND`` 보존 (VALIDATION_ERROR 과적용 0).
- R10: ``account create --account-id valid-acc-1 ...`` → 정상 생성 (회귀 0).

에러 코드 SSOT는 #1633 선결정으로 고정된
``InvalidAccountIdError.code == "VALIDATION_ERROR"``를 재사용한다(신 코드 0).
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner

from ante.cli.main import cli

# 제공된 invalid account_id 입력:
# - ``default``: RESTRICTED_NEW_ACCOUNT_IDS / lookup-invalid 양쪽 모두 거부.
# - ``bad_id``: ``ACCOUNT_ID_PATTERN`` (``^[a-zA-Z0-9-]{3,30}$``) 위반 (underscore).
# 8 명령 × 2 invalid = R1-R8.
_INVALID_IDS = ["default", "bad_id"]

# 패턴 유효(``^[a-zA-Z0-9-]{3,30}$``)·미존재 account_id. invalid-format ↔
# valid-absent 분리 단정용 (R9).
_VALID_ABSENT = "nonexistent-acc-1"

# 정상 account_id (R10 회귀 0 검증).
_VALID_PRESENT = "valid-acc-1"


def _mock_account_obj(account_id: str = _VALID_PRESENT) -> Any:
    """svc.create / svc.repair_timezone 반환값으로 사용할 Account stub."""
    from ante.account.models import Account, AccountStatus, TradingMode

    return Account(
        account_id=account_id,
        name="ValidAcc",
        exchange="TEST",
        currency="KRW",
        broker_type="test",
        status=AccountStatus("active"),
        trading_mode=TradingMode("virtual"),
        credentials={"app_key": "K", "app_secret": "S"},
        buy_commission_rate=Decimal("0.00015"),
        sell_commission_rate=Decimal("0.00195"),
    )


# ── fixtures ─────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def bypass_auth():
    """인증 우회 — ``test_cli_account_reserve_buffer_validation.py`` 패턴 동형."""
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
def offline_runtime():
    """cold-path active runtime guard 통과 — ingress 검증이 차단되어야 함을 단정.

    cold-path 4 명령은 모두 ``_assert_no_active_runtime``을 호출하므로 본 PR의
    ingress 검증이 그 이후에 동작한다. 본 fixture가 guard를 통과시키는 게
    중요하다 (guard에서 미리 차단되면 ingress drift를 단정할 수 없다).
    """
    with (
        patch("ante.main.read_pid_file", return_value=None),
        patch(
            "ante.cli.commands.ipc_helpers.get_socket_path",
            return_value="/tmp/__ante_offline_invalid_id_ingress_test__.sock",
        ),
    ):
        yield


@pytest.fixture
def mock_account_service():
    """``_create_account_service``를 mock해 DB 접근을 차단한다."""
    svc = AsyncMock()
    db = AsyncMock()

    async def _create_service():
        return svc, db

    with patch(
        "ante.cli.commands.account._create_account_service", new=_create_service
    ):
        yield svc


def _runner() -> CliRunner:
    return CliRunner()


def _invoke(args: list[str]) -> Any:
    env = {"ANTE_MEMBER_TOKEN": ""}
    return _runner().invoke(cli, args, env=env, catch_exceptions=False)


def _assert_validation_error(result: Any) -> None:
    """invalid account_id 거부 envelope 단정.

    - exit code 1
    - JSON envelope ``status=error`` + ``code="VALIDATION_ERROR"``
    - not-found 오분류 어휘 부재 (raw traceback / NOT NULL 누출 부재)
    """
    assert result.exit_code == 1, (
        f"expected exit=1, got exit={result.exit_code} output={result.output!r}"
    )
    # JSON envelope는 stdout의 마지막 라인이다 (text mode print 잔재 차단).
    payload = json.loads(result.output.strip().splitlines()[-1])
    assert payload["status"] == "error", payload
    assert payload["code"] == "VALIDATION_ERROR", payload
    # not-found 오분류 차단.
    assert "ACCOUNT_NOT_FOUND" not in result.output, result.output
    # raw traceback 누출 차단.
    assert "Traceback" not in result.output, result.output


# ── argv builders ────────────────────────────────────────────────────


def _argv_create(account_id: str) -> list[str]:
    """``account create --account-id <id> ...`` argv (option 표면)."""
    return [
        "--format",
        "json",
        "account",
        "create",
        "--broker-type",
        "test",
        "--account-id",
        account_id,
        "--name",
        "X",
        "--trading-mode",
        "virtual",
        "--credential",
        "app_key=K",
        "--credential",
        "app_secret=S",
    ]


def _argv_delete(account_id: str) -> list[str]:
    """``account delete <id> --yes`` argv (positional 표면)."""
    return [
        "--format",
        "json",
        "account",
        "delete",
        account_id,
        "--yes",
    ]


def _argv_set_credentials(account_id: str) -> list[str]:
    """``account set-credentials <id> --credential ...`` argv (positional 표면)."""
    return [
        "--format",
        "json",
        "account",
        "set-credentials",
        account_id,
        "--credential",
        "app_key=K",
        "--credential",
        "app_secret=S",
    ]


def _argv_repair_timezone(account_id: str) -> list[str]:
    """``account repair-timezone <id> <new_timezone>`` argv (positional 표면)."""
    return [
        "--format",
        "json",
        "account",
        "repair-timezone",
        account_id,
        "Asia/Seoul",
    ]


_ARGV_BUILDERS = {
    "create": _argv_create,
    "delete": _argv_delete,
    "set-credentials": _argv_set_credentials,
    "repair-timezone": _argv_repair_timezone,
}


# ── 축 1: R1-R8 — 4 cold-path 명령 × {default, bad_id} → VALIDATION_ERROR ──


@pytest.mark.parametrize(
    "subcommand",
    ["create", "delete", "set-credentials", "repair-timezone"],
)
@pytest.mark.parametrize("invalid_id", _INVALID_IDS)
class TestInvalidAccountIdRejected:
    """4 cold-path 명령이 invalid account_id를 service 진입 이전에 거부.

    parametrize 매트릭스 = 4 명령 × 2 invalid = R1-R8.
    """

    def test_invalid_id_returns_validation_error(
        self,
        mock_account_service: AsyncMock,
        offline_runtime: Any,
        subcommand: str,
        invalid_id: str,
    ) -> None:
        """invalid account_id → exit 1, VALIDATION_ERROR, service 미호출."""
        argv = _ARGV_BUILDERS[subcommand](invalid_id)
        result = _invoke(argv)
        _assert_validation_error(result)
        # ingress 거부 → service 메서드는 어느 것도 호출되지 않아야 한다.
        mock_account_service.create.assert_not_called()
        mock_account_service.delete.assert_not_called()
        mock_account_service.get.assert_not_called()
        mock_account_service.update.assert_not_called()
        mock_account_service.repair_timezone.assert_not_called()


# ── 축 2: R9 — valid format / absent → ACCOUNT_NOT_FOUND 보존 ────────


class TestValidButAbsentNotMisclassified:
    """패턴 유효·미존재 account_id는 invalid-format으로 오분류되지 않는다.

    (Codex next-step 동형: invalid-format ↔ valid-absent 분리, VALIDATION_ERROR
    과적용 0)
    """

    def test_account_delete_valid_absent_keeps_not_found(
        self, mock_account_service: AsyncMock, offline_runtime: Any
    ) -> None:
        """``account delete nonexistent-acc-1 --yes`` → ``ACCOUNT_NOT_FOUND`` 보존."""
        from ante.account.errors import AccountNotFoundError

        mock_account_service.delete.side_effect = AccountNotFoundError(
            "계좌를 찾을 수 없습니다"
        )
        result = _invoke(_argv_delete(_VALID_ABSENT))
        assert result.exit_code == 1, result.output
        payload = json.loads(result.output.strip().splitlines()[-1])
        # ingress 통과 → not-found 경로 도달 (VALIDATION_ERROR 아님).
        assert payload.get("code") != "VALIDATION_ERROR", payload
        assert payload.get("code") == "ACCOUNT_NOT_FOUND", payload
        mock_account_service.delete.assert_awaited_once()


# ── 축 3: R10 — 정상 create → 정상 생성 (회귀 0) ──────────────────────


class TestValidAccountIdRegression:
    """정상 account_id ``account create``는 기존 동작을 유지한다."""

    def test_account_create_valid_ok(
        self, mock_account_service: AsyncMock, offline_runtime: Any
    ) -> None:
        """``account create --account-id valid-acc-1 ...`` → 정상 생성."""
        mock_account_service.create.return_value = _mock_account_obj(_VALID_PRESENT)
        result = _invoke(_argv_create(_VALID_PRESENT))
        assert result.exit_code == 0, result.output
        # ingress 통과 → svc.create 호출 + valid id 전달.
        mock_account_service.create.assert_awaited_once()
        new_account = mock_account_service.create.call_args.args[0]
        assert new_account.account_id == _VALID_PRESENT
