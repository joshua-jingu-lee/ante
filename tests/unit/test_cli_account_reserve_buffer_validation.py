"""``account create --market-order-reserve-buffer-rate`` ingress 회귀 (#1723).

오라클 A7 finding(``cli_account_reserve_buffer_contract``):
``--market-order-reserve-buffer-rate``가 ``inf``/음수를 exit 0 status=ok로 통과
시키고, ``nan``은 SQLite ``NOT NULL constraint`` raw 메시지 + 빈 code로 떨어졌다.
본 PR은 ``validate_nonnegative_finite_amount`` callback을 부착해 그 ingress
drift를 닫는다.

본 테스트는 e2e Click runner 회귀 R1~R6을 단정한다:

- R1: ``inf`` → exit 1, JSON ``code="CLI_USAGE_ERROR"``, "finite" 포함.
- R2: ``nan`` → exit 1, JSON ``code="CLI_USAGE_ERROR"``.
- R3: ``-0.1`` → exit 1, JSON ``code="CLI_USAGE_ERROR"``, "0 이상" 포함.
- R4: ``0`` → exit 0, account 정상 생성 (boundary; ``Decimal("0")`` 기본값 SSOT).
- R5: ``0.005`` → exit 0, account 정상 생성.
- R6: ``1e-300`` → exit 0, account 정상 생성 (positive-near-zero boundary —
  finite invariant 강조; subnormal float이지만 ``math.isfinite`` 통과).

invalid 케이스는 click ``BadParameter`` 경로를 타고 ``AuthenticatedGroup.main``
middleware(``src/ante/cli/middleware.py:561-581``)가 ``CLI_USAGE_ERROR`` JSON
envelope + exit 1로 변환한다. R1~R3은 그 envelope을 단정한다. 정상 케이스
R4~R6은 ``_create_account_service`` mock으로 DB 접근을 차단하고 ``Account.
market_order_reserve_buffer_rate``가 정확한 ``Decimal``로 전달되는지를 단정한다.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner

from ante.cli.main import cli


def _invoke(args: list[str]) -> Any:
    """``ANTE_MEMBER_TOKEN``을 빈 문자열로 두고 ``CliRunner``로 실행한다.

    인증은 ``bypass_auth`` fixture가 ``authenticate_member``를 patch해 우회한다
    (``test_account_cli.py`` 패턴과 동형).
    """
    runner = CliRunner()
    env = {"ANTE_MEMBER_TOKEN": ""}
    return runner.invoke(cli, args, env=env, catch_exceptions=False)


def _mock_account_obj(account_id: str = "oracle-buf") -> Any:
    """정상 케이스(R4~R6)에서 ``svc.create`` 반환값으로 사용할 Account stub."""
    from ante.account.models import Account, AccountStatus, TradingMode

    return Account(
        account_id=account_id,
        name="OracleBuf",
        exchange="TEST",
        currency="KRW",
        broker_type="test",
        status=AccountStatus("active"),
        trading_mode=TradingMode("virtual"),
        credentials={},
        buy_commission_rate=Decimal("0.00015"),
        sell_commission_rate=Decimal("0.00195"),
    )


@pytest.fixture(autouse=True)
def bypass_auth():
    """인증 우회 — ``test_account_cli.py`` 패턴 동형."""
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
    """cold-path active runtime guard 통과 — ``test_account_cli.py`` 패턴 동형."""
    with (
        patch("ante.main.read_pid_file", return_value=None),
        patch(
            "ante.cli.commands.ipc_helpers.get_socket_path",
            return_value="/tmp/__ante_offline_runtime_buffer_test__.sock",
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


def _argv(value: str) -> list[str]:
    """``account create`` argv (JSON 모드).

    음수 토큰(``-0.1``)이 option 후보로 처리되어 "No such option"으로 reject되지
    않도록 ``=`` 형태로 옵션-값을 결합한다. click은 ``--opt=-0.1`` 형태에서는
    토큰 분리 없이 value로 직접 파싱한다.
    """
    return [
        "--format",
        "json",
        "account",
        "create",
        "--broker-type",
        "test",
        "--account-id",
        "oracle-buf",
        "--name",
        "OracleBuf",
        "--trading-mode",
        "virtual",
        "--credential",
        "app_key=K",
        "--credential",
        "app_secret=S",
        f"--market-order-reserve-buffer-rate={value}",
    ]


def _assert_cli_usage_error(result: Any, *, expect_substr: str | None = None) -> None:
    """invalid 입력에 대해 ``CLI_USAGE_ERROR`` envelope + exit 1을 단정."""
    assert result.exit_code == 1, (
        f"expected exit=1, got exit={result.exit_code} output={result.output!r}"
    )
    payload = json.loads(result.output.strip())
    assert payload["status"] == "error"
    assert payload["code"] == "CLI_USAGE_ERROR", (
        f"expected code=CLI_USAGE_ERROR, got code={payload.get('code')!r}"
    )
    if expect_substr is not None:
        assert expect_substr in payload["message"], (
            f"expected substring {expect_substr!r} in message, "
            f"got message={payload['message']!r}"
        )
    # raw SQLite 메시지 누출 회귀 차단 (#1723 root cause).
    assert "NOT NULL constraint" not in payload["message"]


class TestInvalidValuesRejected:
    """R1~R3: invalid ingress가 ``CLI_USAGE_ERROR`` JSON envelope + exit 1로 거부."""

    def test_r1_infinity_rejected(
        self, mock_account_service: AsyncMock, offline_runtime
    ) -> None:
        """R1: ``inf`` → exit 1, ``CLI_USAGE_ERROR``, message에 ``finite`` 포함."""
        result = _invoke(_argv("inf"))
        _assert_cli_usage_error(result, expect_substr="finite")
        # ingress에서 차단되므로 service.create는 호출되지 않아야 한다.
        mock_account_service.create.assert_not_called()

    def test_r2_nan_rejected(
        self, mock_account_service: AsyncMock, offline_runtime
    ) -> None:
        """R2: ``nan`` → exit 1, ``CLI_USAGE_ERROR``.

        기존 버그: SQLite ``NOT NULL constraint`` raw 메시지 + 빈 code로 누출.
        callback 부착 후에는 ingress에서 차단되어야 한다.
        """
        result = _invoke(_argv("nan"))
        _assert_cli_usage_error(result, expect_substr="finite")
        mock_account_service.create.assert_not_called()

    def test_r3_negative_rejected(
        self, mock_account_service: AsyncMock, offline_runtime
    ) -> None:
        """R3: ``-0.1`` → exit 1, ``CLI_USAGE_ERROR``, message에 ``0 이상`` 포함."""
        result = _invoke(_argv("-0.1"))
        _assert_cli_usage_error(result, expect_substr="0 이상")
        mock_account_service.create.assert_not_called()


class TestValidValuesAccepted:
    """R4~R6: valid ingress가 정상 통과해 account가 생성."""

    def test_r4_zero_accepted_boundary(
        self, mock_account_service: AsyncMock, offline_runtime
    ) -> None:
        """R4: ``0`` → exit 0 (boundary; ``Decimal("0")`` 기본값 SSOT, #1333).

        ``validate_positive_finite_amount``와 달리 본 callback은 0을 허용한다.
        """
        mock_account_service.create.return_value = _mock_account_obj()
        result = _invoke(_argv("0"))
        assert result.exit_code == 0, result.output
        new_account = mock_account_service.create.call_args.args[0]
        assert new_account.market_order_reserve_buffer_rate == Decimal("0")

    def test_r5_small_positive_accepted(
        self, mock_account_service: AsyncMock, offline_runtime
    ) -> None:
        """R5: ``0.005`` → exit 0, account 정상 생성."""
        mock_account_service.create.return_value = _mock_account_obj()
        result = _invoke(_argv("0.005"))
        assert result.exit_code == 0, result.output
        new_account = mock_account_service.create.call_args.args[0]
        assert new_account.market_order_reserve_buffer_rate == Decimal("0.005")

    def test_r6_subnormal_finite_accepted(
        self, mock_account_service: AsyncMock, offline_runtime
    ) -> None:
        """R6: ``1e-300`` → exit 0 (positive-near-zero boundary, finite invariant).

        ``1e-300``은 IEEE-754 double subnormal이지만 ``math.isfinite``로 finite
        판정된다. callback은 finite + 0 이상만 보장하므로 통과해야 한다.
        ``Decimal(str(1e-300))``은 ``Decimal("1e-300")``으로 정확히 매핑된다.
        """
        mock_account_service.create.return_value = _mock_account_obj()
        result = _invoke(_argv("1e-300"))
        assert result.exit_code == 0, result.output
        new_account = mock_account_service.create.call_args.args[0]
        # ``Decimal(str(1e-300))`` == ``Decimal("1e-300")``.
        assert new_account.market_order_reserve_buffer_rate == Decimal("1e-300")
        assert isinstance(new_account.market_order_reserve_buffer_rate, Decimal)
