"""#1809 Group S R-cases — treasury allocate/deallocate typed reject code surface.

oracle A7 @ a5d8edf finding:
    ``ante --format json treasury allocate``/``treasury deallocate`` 가 기존
    bot 의 예산 작업을 정상적으로 거부하지만 JSON envelope ``code`` 가 빈
    문자열로 surface 되어 ``docs/specs/cli/02-design-decisions.md:83-89`` 의
    stable ``SCREAMING_SNAKE_CASE`` 계약을 위반한다.

수정 후 invariant:
    1. ``Treasury.allocate``/``Treasury.deallocate`` 는 reject 시 reject
       reason 별 typed exception 을 raise 한다 (``bool=False`` 폐기).
    2. IPC server.py:322 ``getattr(e, "code", "EXECUTION_ERROR")`` 가 각
       typed exception 의 ``.code`` 클래스 속성을 envelope ``error.code`` 로
       매핑한다 (``TREASURY_INVALID_AMOUNT`` /
       ``TREASURY_INSUFFICIENT_BALANCE`` /
       ``TREASURY_DEALLOCATE_EXCEEDS_AVAILABLE`` /
       ``TREASURY_BUDGET_NOT_FOUND``).
    3. CLI ``treasury allocate``/``deallocate`` 는 ``ipc_send`` envelope 의
       ``ipc_error_code`` 를 set_balance/snapshot/status (#1758/#1725) 와
       동형으로 ``fmt.error(message, code=code)`` 매핑한다.

본 테스트는 CLI runner 로 mock IPC envelope 응답을 받아 stable ``code`` 가
사용자에게 surface 되는지 R-case 별로 검증한다.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner


def _make_member():
    """테스트용 Member mock 객체."""
    member = MagicMock()
    member.member_id = "test-user"
    from ante.member.models import MemberType

    member.type = MemberType.HUMAN
    return member


def _mock_authenticate(ctx):
    """테스트용 인증 우회."""
    ctx.obj["member"] = _make_member()


def _invoke_cli(args: list[str]):
    """CLI 실행 (인증 우회)."""
    from ante.cli.main import cli

    runner = CliRunner()
    with patch("ante.cli.main.authenticate_member", side_effect=_mock_authenticate):
        result = runner.invoke(
            cli,
            args,
            obj={"member": _make_member()},
            env={"ANTE_MEMBER_TOKEN": ""},
            catch_exceptions=False,
        )
    return result


def _ipc_error_envelope(code: str, message: str) -> dict:
    """IPC server.py:322 의 typed exception envelope 응답을 모사한다."""
    return {
        "id": "req-1",
        "status": "error",
        "error": {"code": code, "message": message},
    }


# ----------------------------------------------------------------------------
# R1: allocate insufficient unallocated balance → TREASURY_INSUFFICIENT_BALANCE
# ----------------------------------------------------------------------------


class TestR1AllocateInsufficientBalance:
    """R1: 미할당 잔액 초과 할당 → TREASURY_INSUFFICIENT_BALANCE."""

    @patch(
        "ante.cli.commands.ipc_helpers.get_socket_path", return_value="/tmp/test.sock"
    )
    @patch("ante.cli.commands.ipc_helpers.IPCClient")
    def test_allocate_insufficient_balance_json_envelope_code(
        self, mock_ipc_cls, mock_socket
    ) -> None:
        """JSON envelope ``code`` 가 ``TREASURY_INSUFFICIENT_BALANCE`` 로 surface."""
        mock_client = AsyncMock()
        mock_client.send.return_value = _ipc_error_envelope(
            "TREASURY_INSUFFICIENT_BALANCE",
            "treasury.allocate: 미할당 잔액 부족 (요청=999999999, 가용=0)",
        )
        mock_ipc_cls.return_value = mock_client

        result = _invoke_cli(
            [
                "--format",
                "json",
                "treasury",
                "allocate",
                "bot-1",
                "999999999",
                "--account",
                "acc-1",
            ]
        )

        assert result.exit_code == 1, result.output
        # JSON envelope code 가 typed code 그대로 surface.
        payload = _parse_last_json(result.output)
        assert payload["status"] == "error", payload
        assert payload["code"] == "TREASURY_INSUFFICIENT_BALANCE", payload
        assert "" != payload["code"], "회귀: 빈 code 가 surface 되면 안 됨"

    @patch(
        "ante.cli.commands.ipc_helpers.get_socket_path", return_value="/tmp/test.sock"
    )
    @patch("ante.cli.commands.ipc_helpers.IPCClient")
    def test_allocate_insufficient_balance_text_mode_exits_with_error_message(
        self, mock_ipc_cls, mock_socket
    ) -> None:
        """text 모드: exit 1 + 사용자 메시지 노출 (code 는 JSON 전용 contract).

        ``docs/specs/cli/02-design-decisions.md:83-89`` 의 stable
        SCREAMING_SNAKE_CASE ``code`` 계약은 JSON envelope 전용이다. text
        모드는 ``Error: {message}`` 만 노출한다 (``cli/formatter.py:78-85``).
        """
        mock_client = AsyncMock()
        mock_client.send.return_value = _ipc_error_envelope(
            "TREASURY_INSUFFICIENT_BALANCE",
            "treasury.allocate: 미할당 잔액 부족",
        )
        mock_ipc_cls.return_value = mock_client

        result = _invoke_cli(
            [
                "treasury",
                "allocate",
                "bot-1",
                "999999999",
                "--account",
                "acc-1",
            ]
        )

        assert result.exit_code == 1, result.output


# ----------------------------------------------------------------------------
# R2: allocate negative/invalid amount → TREASURY_INVALID_AMOUNT (service layer)
#
# 주의: CLI ingress validator ``validate_positive_finite_amount`` 가 음수/0/NaN/Inf
# 를 1차 거부(``VALIDATION_ERROR`` 류)할 수 있다. 본 R-case 는 IPC envelope
# 까지 도달하는 경로(예: 정상 CLI parsing 후 service layer 가 reject)를
# 시뮬레이션하여 service-layer typed code 가 envelope 으로 surface 되는지를
# 단정한다.
# ----------------------------------------------------------------------------


class TestR2AllocateInvalidAmount:
    """R2: service-layer ``TREASURY_INVALID_AMOUNT`` envelope surface."""

    @patch(
        "ante.cli.commands.ipc_helpers.get_socket_path", return_value="/tmp/test.sock"
    )
    @patch("ante.cli.commands.ipc_helpers.IPCClient")
    def test_allocate_invalid_amount_json_envelope_code(
        self, mock_ipc_cls, mock_socket
    ) -> None:
        """JSON envelope code = ``TREASURY_INVALID_AMOUNT``."""
        mock_client = AsyncMock()
        mock_client.send.return_value = _ipc_error_envelope(
            "TREASURY_INVALID_AMOUNT",
            "treasury.allocate: amount는 유한한 양수여야 합니다 (요청=-1.0)",
        )
        mock_ipc_cls.return_value = mock_client

        # ingress validator 우회를 위해 양수 amount 로 호출(서버단 reject 가정).
        result = _invoke_cli(
            [
                "--format",
                "json",
                "treasury",
                "allocate",
                "bot-1",
                "100",
                "--account",
                "acc-1",
            ]
        )

        assert result.exit_code == 1, result.output
        payload = _parse_last_json(result.output)
        assert payload["status"] == "error", payload
        assert payload["code"] == "TREASURY_INVALID_AMOUNT", payload


# ----------------------------------------------------------------------------
# R3: deallocate over-deallocate → TREASURY_DEALLOCATE_EXCEEDS_AVAILABLE
# ----------------------------------------------------------------------------


class TestR3DeallocateExceedsAvailable:
    """R3: 가용 예산 초과 회수 → TREASURY_DEALLOCATE_EXCEEDS_AVAILABLE."""

    @patch(
        "ante.cli.commands.ipc_helpers.get_socket_path", return_value="/tmp/test.sock"
    )
    @patch("ante.cli.commands.ipc_helpers.IPCClient")
    def test_deallocate_exceeds_available_json_envelope_code(
        self, mock_ipc_cls, mock_socket
    ) -> None:
        """JSON envelope code = ``TREASURY_DEALLOCATE_EXCEEDS_AVAILABLE``."""
        mock_client = AsyncMock()
        mock_client.send.return_value = _ipc_error_envelope(
            "TREASURY_DEALLOCATE_EXCEEDS_AVAILABLE",
            "treasury.deallocate: 가용 예산 초과",
        )
        mock_ipc_cls.return_value = mock_client

        result = _invoke_cli(
            [
                "--format",
                "json",
                "treasury",
                "deallocate",
                "bot-1",
                "999999",
                "--account",
                "acc-1",
            ]
        )

        assert result.exit_code == 1, result.output
        payload = _parse_last_json(result.output)
        assert payload["status"] == "error", payload
        assert payload["code"] == "TREASURY_DEALLOCATE_EXCEEDS_AVAILABLE", payload
        assert payload["code"] != "", "회귀: 빈 code 가 surface 되면 안 됨"

    @patch(
        "ante.cli.commands.ipc_helpers.get_socket_path", return_value="/tmp/test.sock"
    )
    @patch("ante.cli.commands.ipc_helpers.IPCClient")
    def test_deallocate_budget_not_found_json_envelope_code(
        self, mock_ipc_cls, mock_socket
    ) -> None:
        """budget record 부재 → ``TREASURY_BUDGET_NOT_FOUND`` envelope."""
        mock_client = AsyncMock()
        mock_client.send.return_value = _ipc_error_envelope(
            "TREASURY_BUDGET_NOT_FOUND",
            "treasury.deallocate: bot 'bot-x' 의 budget record 가 없습니다",
        )
        mock_ipc_cls.return_value = mock_client

        result = _invoke_cli(
            [
                "--format",
                "json",
                "treasury",
                "deallocate",
                "bot-x",
                "100",
                "--account",
                "acc-1",
            ]
        )

        assert result.exit_code == 1, result.output
        payload = _parse_last_json(result.output)
        assert payload["status"] == "error", payload
        assert payload["code"] == "TREASURY_BUDGET_NOT_FOUND", payload


# ----------------------------------------------------------------------------
# R4: happy path 회귀 — success envelope 정상 처리
# ----------------------------------------------------------------------------


class TestR4HappyPath:
    """R4: 정상 할당/회수 → 성공 envelope + exit 0."""

    @patch(
        "ante.cli.commands.ipc_helpers.get_socket_path", return_value="/tmp/test.sock"
    )
    @patch("ante.cli.commands.ipc_helpers.IPCClient")
    def test_allocate_success(self, mock_ipc_cls, mock_socket) -> None:
        """정상 할당."""
        mock_client = AsyncMock()
        mock_client.send.return_value = {
            "id": "req-1",
            "status": "ok",
            "result": {
                "account_id": "acc-1",
                "bot_id": "bot-1",
                "success": True,
            },
        }
        mock_ipc_cls.return_value = mock_client

        result = _invoke_cli(
            ["treasury", "allocate", "bot-1", "100", "--account", "acc-1"]
        )
        assert result.exit_code == 0, result.output
        assert "예산 할당 완료" in result.output

    @patch(
        "ante.cli.commands.ipc_helpers.get_socket_path", return_value="/tmp/test.sock"
    )
    @patch("ante.cli.commands.ipc_helpers.IPCClient")
    def test_deallocate_success(self, mock_ipc_cls, mock_socket) -> None:
        """정상 회수."""
        mock_client = AsyncMock()
        mock_client.send.return_value = {
            "id": "req-1",
            "status": "ok",
            "result": {
                "account_id": "acc-1",
                "bot_id": "bot-1",
                "success": True,
            },
        }
        mock_ipc_cls.return_value = mock_client

        result = _invoke_cli(
            ["treasury", "deallocate", "bot-1", "50", "--account", "acc-1"]
        )
        assert result.exit_code == 0, result.output
        assert "예산 회수 완료" in result.output


# ----------------------------------------------------------------------------
# 서비스 레이어 typed exception → IPC envelope 매핑 단위 검증
# ----------------------------------------------------------------------------


class TestServiceLayerTypedExceptionCodes:
    """``Treasury.allocate``/``deallocate`` typed exception .code SSOT."""

    def test_typed_exception_code_attributes(self) -> None:
        """각 typed exception 의 ``.code`` 가 stable SCREAMING_SNAKE_CASE."""
        from ante.treasury.exceptions import (
            TreasuryBudgetNotFoundError,
            TreasuryDeallocateExceedsAvailableError,
            TreasuryInsufficientUnallocatedError,
            TreasuryInvalidAmountError,
        )

        assert TreasuryInvalidAmountError.code == "TREASURY_INVALID_AMOUNT"
        assert (
            TreasuryInsufficientUnallocatedError.code == "TREASURY_INSUFFICIENT_BALANCE"
        )
        assert TreasuryBudgetNotFoundError.code == "TREASURY_BUDGET_NOT_FOUND"
        assert (
            TreasuryDeallocateExceedsAvailableError.code
            == "TREASURY_DEALLOCATE_EXCEEDS_AVAILABLE"
        )

    def test_typed_exceptions_inherit_treasury_error(self) -> None:
        """모든 reject typed exception 은 ``TreasuryError`` 하위."""
        from ante.treasury.exceptions import (
            TreasuryBudgetNotFoundError,
            TreasuryDeallocateExceedsAvailableError,
            TreasuryError,
            TreasuryInsufficientUnallocatedError,
            TreasuryInvalidAmountError,
        )

        for cls in (
            TreasuryInvalidAmountError,
            TreasuryInsufficientUnallocatedError,
            TreasuryBudgetNotFoundError,
            TreasuryDeallocateExceedsAvailableError,
        ):
            assert issubclass(cls, TreasuryError), cls

    @pytest.mark.asyncio
    async def test_allocate_raises_typed_exception_with_code(self, tmp_path) -> None:
        """``Treasury.allocate`` 가 reject 시 typed exception 을 raise + .code 노출."""
        from ante.core.database import Database
        from ante.eventbus import EventBus
        from ante.treasury.exceptions import (
            TreasuryInsufficientUnallocatedError,
            TreasuryInvalidAmountError,
        )
        from ante.treasury.treasury import Treasury

        db = Database(str(tmp_path / "test.db"))
        await db.connect()
        try:
            t = Treasury(db=db, eventbus=EventBus(), account_id="acc-1")
            await t.initialize()
            await t.set_account_balance(1_000_000.0)

            # 음수 amount
            with pytest.raises(TreasuryInvalidAmountError) as exc_neg:
                await t.allocate("bot-1", -1.0)
            assert exc_neg.value.code == "TREASURY_INVALID_AMOUNT"

            # 미할당 잔액 부족
            with pytest.raises(TreasuryInsufficientUnallocatedError) as exc_ins:
                await t.allocate("bot-1", 999_999_999.0)
            assert exc_ins.value.code == "TREASURY_INSUFFICIENT_BALANCE"
            assert exc_ins.value.bot_id == "bot-1"

            # 정상 호출은 None 반환 (raise 없음)
            result = await t.allocate("bot-1", 100.0)
            assert result is None
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_deallocate_raises_typed_exception_with_code(self, tmp_path) -> None:
        """``Treasury.deallocate`` 가 reject 시 typed exception + .code."""
        from ante.core.database import Database
        from ante.eventbus import EventBus
        from ante.treasury.exceptions import (
            TreasuryBudgetNotFoundError,
            TreasuryDeallocateExceedsAvailableError,
            TreasuryInvalidAmountError,
        )
        from ante.treasury.treasury import Treasury

        db = Database(str(tmp_path / "test.db"))
        await db.connect()
        try:
            t = Treasury(db=db, eventbus=EventBus(), account_id="acc-1")
            await t.initialize()
            await t.set_account_balance(1_000_000.0)

            # budget record 부재
            with pytest.raises(TreasuryBudgetNotFoundError) as exc_nf:
                await t.deallocate("no-bot", 100.0)
            assert exc_nf.value.code == "TREASURY_BUDGET_NOT_FOUND"

            # 음수 amount
            with pytest.raises(TreasuryInvalidAmountError):
                await t.deallocate("any-bot", -1.0)

            # over-deallocate
            await t.allocate("bot-1", 100.0)
            with pytest.raises(TreasuryDeallocateExceedsAvailableError) as exc_ex:
                await t.deallocate("bot-1", 500.0)
            assert exc_ex.value.code == "TREASURY_DEALLOCATE_EXCEEDS_AVAILABLE"
            assert exc_ex.value.amount == 500.0
        finally:
            await db.close()


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------


def _parse_last_json(output: str) -> dict:
    """CLI stdout 에서 마지막 JSON object 를 파싱한다.

    ``fmt.error(message, code=code)`` 가 JSON 모드에서 ``{"status":"error",
    "code":..., "message":...}`` envelope 을 stdout 으로 emit 한다. CLI runner
    출력에는 stderr/stdout 이 섞일 수 있으므로 마지막 ``{...}`` block 을 찾는다.
    """
    # 단순 strategy: 출력에서 ``{`` 시작하는 라인부터 ``}`` 까지의 JSON 을 탐색.
    lines = output.strip().splitlines()
    # 뒤에서부터 ``{`` 로 시작하는 라인을 찾아 JSON decoder 로 시도.
    for idx in range(len(lines) - 1, -1, -1):
        line = lines[idx].strip()
        if line.startswith("{"):
            # 단일 라인 JSON 가정. 멀티라인이면 join.
            for end in range(len(lines), idx, -1):
                candidate = "\n".join(lines[idx:end]).strip()
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    continue
    raise AssertionError(f"JSON envelope 을 찾을 수 없음: output={output!r}")
