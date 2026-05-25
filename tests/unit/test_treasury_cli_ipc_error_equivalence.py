"""Treasury CLI direct path ↔ IPC path error code equivalence lock (#1843 sub-PR 4).

본 모듈은 #1816 의 5차 migration domain (treasury) 의 대표 fault 6 건이
CLI path 와 IPC envelope path 양쪽에서 **동일한 public code** 를 노출함을
lock 한다. #1842 (account) / #1843 sub-PR 1 (member) / sub-PR 2 (approval) /
sub-PR 3 (bot) 의 1:1 동형 패턴.

검증 대상 fault:

- ``TreasuryInvalidAmountError`` → ``TREASURY_INVALID_AMOUNT`` (validation;
  ``allocate``/``deallocate`` 의 finite-positive 가드 위반)
- ``TreasuryInsufficientUnallocatedError`` → ``TREASURY_INSUFFICIENT_BALANCE``
  (validation; ``allocate`` 시 ``self._unallocated < amount``)
- ``TreasuryBudgetNotFoundError`` → ``TREASURY_BUDGET_NOT_FOUND`` (not_found;
  ``deallocate`` 시 budget record 부재)
- ``TreasuryDeallocateExceedsAvailableError`` →
  ``TREASURY_DEALLOCATE_EXCEEDS_AVAILABLE`` (validation; over-deallocate)
- ``BotNotStoppedError`` → ``TREASURY_BOT_NOT_STOPPED`` (state_conflict;
  ``update_budget`` 시 running 봇 거부)
- ``TreasuryNotConfiguredError`` → ``TREASURY_NOT_CONFIGURED``
  (service_unavailable; ``TreasuryManager`` 미주입 / 등록된 Treasury 부재)

treasury CLI 의 mutating 표면 (``allocate``/``deallocate``/``set-balance``)
은 모두 ``ipc_send`` 경유이므로 CLI direct path equivalence 는 ``ipc_send``
mock 으로 server-side envelope (``ipc_error_code``/``ipc_error_message``) 을
주입한 뒤 CLI middleware ClickException 분기가 동일 코드를 surface 함을
확인한다 (#1843 sub-PR 3 bot 1:1 동형).

IPC path 는 ``ante.contracts.ipc_error_payload`` helper (server.py:322 의
``getattr(e, "code", "EXECUTION_ERROR")`` 와 동일 코드를 생성 — 실측 ``.code``
가 일치하는 한 contract 동등성, #1842 plan v2 #6) 로 직접 직렬화한다.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import click
import pytest
from click.testing import CliRunner

from ante.cli.main import cli
from ante.contracts import ipc_error_payload
from ante.member.models import Member, MemberRole, MemberType
from ante.treasury.exceptions import (
    BotNotStoppedError,
    TreasuryBudgetNotFoundError,
    TreasuryDeallocateExceedsAvailableError,
    TreasuryInsufficientUnallocatedError,
    TreasuryInvalidAmountError,
    TreasuryNotConfiguredError,
)

_MOCK_MASTER = Member(
    member_id="test-master",
    type=MemberType.HUMAN,
    role=MemberRole.MASTER,
    org="default",
    name="Test Master",
    status="active",
    scopes=["treasury:read", "treasury:write", "treasury:admin"],
)


@pytest.fixture
def runner() -> CliRunner:
    """``ante --format json treasury ...`` 호출용 ``CliRunner`` fixture.

    auth middleware 를 master member 로 우회한다 (#1843 sub-PR 1/2/3
    fixture 1:1 동형). ``require_scope`` decorator 는 그대로 동작하므로
    모든 treasury scope 를 부여한다.
    """
    r = CliRunner()
    original_invoke = r.invoke

    def _invoke_with_auth(cli_cmd, args=None, **kwargs):  # noqa: ANN001, ANN202
        with patch("ante.cli.main.authenticate_member") as mock_auth:

            def _set_member(ctx) -> None:  # noqa: ANN001
                ctx.obj = ctx.obj or {}
                ctx.obj["member"] = _MOCK_MASTER

            mock_auth.side_effect = _set_member
            return original_invoke(cli_cmd, args, **kwargs)

    r.invoke = _invoke_with_auth  # type: ignore[method-assign]
    return r


def _ipc_envelope_code(exc: BaseException) -> str:
    """주어진 exception 을 IPC envelope 으로 직렬화했을 때의 ``code``.

    IPC server.py:322 가 적용하는 ``getattr(e, "code", "EXECUTION_ERROR")``
    fallback 과 helper(``ipc_error_payload``)의 registry-first resolution 은
    실측 ``.code`` 가 일치하는 한 동일 코드를 생성한다 (#1842 plan v2 #6).
    본 helper 는 helper 경로를 그대로 사용해 contract 동등성을 단언한다.
    """

    payload = ipc_error_payload(exc)
    return payload["code"]


def _cli_envelope_payload(result_output: str) -> dict:
    """``CliRunner.result.output`` 에서 JSON envelope 첫 객체를 추출."""
    payload_line = next(
        (line for line in result_output.splitlines() if line.startswith("{")),
        None,
    )
    assert payload_line is not None, f"JSON envelope 발견 실패: {result_output!r}"
    return json.loads(payload_line)


def _make_click_exc(code: str, message: str) -> click.ClickException:
    """``ipc_send`` 가 server error envelope 을 변환할 때 부착하는
    ``ipc_error_code``/``ipc_error_message`` 속성을 가진 ClickException 을
    구성한다. CLI command 의 ``except click.ClickException`` 분기에서 동일한
    형태로 message/code 를 복원한다 (#1843 sub-PR 3 ``_make_click_exc`` 동형).
    """

    exc = click.ClickException(f"{code}: {message}")
    exc.ipc_error_code = code  # type: ignore[attr-defined]
    exc.ipc_error_message = message  # type: ignore[attr-defined]
    return exc


# ── (1) TreasuryInvalidAmountError ↔ TREASURY_INVALID_AMOUNT ────────────────


class TestTreasuryInvalidAmountEquivalence:
    """``TreasuryInvalidAmountError`` 는 양쪽에서 ``TREASURY_INVALID_AMOUNT``.

    CLI direct path: ``treasury allocate`` 표면 — ``ipc_send`` 가 server
    typed envelope (code=``TREASURY_INVALID_AMOUNT``) 을 ClickException 으로
    변환하고, ``except click.ClickException`` 분기가 JSON 모드에서 동일
    코드로 CLI envelope 을 surface 한다.

    NB: CLI ingress(``validate_positive_finite_amount``) 가 amount <= 0/NaN/
    Inf 를 ``VALIDATION_ERROR`` 로 1차 거부하므로, 본 test 는 service-layer
    invariant 가 IPC envelope 까지 통과한 경로 (server-side raise) 의 코드
    surface 동등성만 검증한다. CLI ingress validation 거부 회귀는 별도
    ``test_treasury_*_ingress`` 테스트가 책임진다.
    """

    def test_cli_direct_invalid_amount_via_allocate(self, runner: CliRunner) -> None:
        click_exc = _make_click_exc(
            "TREASURY_INVALID_AMOUNT",
            "treasury.allocate: amount는 유한한 양수여야 합니다",
        )

        async def _raise(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
            raise click_exc

        with patch("ante.cli.commands.ipc_helpers.ipc_send", new=_raise):
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "treasury",
                    "allocate",
                    "bot-1",
                    "100",
                    "--account",
                    "acc-1",
                ],
            )

        assert result.exit_code != 0, result.output
        payload = _cli_envelope_payload(result.output)
        assert payload["status"] == "error"
        assert payload["code"] == "TREASURY_INVALID_AMOUNT"

    def test_ipc_envelope_invalid_amount(self) -> None:
        exc = TreasuryInvalidAmountError(0.0, operation="allocate")
        assert _ipc_envelope_code(exc) == "TREASURY_INVALID_AMOUNT"


# ── (2) TreasuryInsufficientUnallocatedError ↔ TREASURY_INSUFFICIENT_BALANCE


class TestTreasuryInsufficientBalanceEquivalence:
    """``TreasuryInsufficientUnallocatedError`` 는 양쪽에서
    ``TREASURY_INSUFFICIENT_BALANCE``.

    CLI direct path: ``treasury allocate`` 표면 — ``ipc_send`` 가 server
    typed envelope (code=``TREASURY_INSUFFICIENT_BALANCE``) 을 ClickException
    으로 변환하고, ``except click.ClickException`` 분기가 동일 코드를
    surface 한다.
    """

    def test_cli_direct_insufficient_balance_via_allocate(
        self, runner: CliRunner
    ) -> None:
        click_exc = _make_click_exc(
            "TREASURY_INSUFFICIENT_BALANCE",
            "treasury.allocate: 미할당 잔액 부족",
        )

        async def _raise(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
            raise click_exc

        with patch("ante.cli.commands.ipc_helpers.ipc_send", new=_raise):
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "treasury",
                    "allocate",
                    "bot-1",
                    "1000000",
                    "--account",
                    "acc-1",
                ],
            )

        assert result.exit_code != 0, result.output
        payload = _cli_envelope_payload(result.output)
        assert payload["status"] == "error"
        assert payload["code"] == "TREASURY_INSUFFICIENT_BALANCE"

    def test_ipc_envelope_insufficient_balance(self) -> None:
        exc = TreasuryInsufficientUnallocatedError(
            bot_id="bot-1", amount=1_000_000.0, unallocated=500_000.0
        )
        assert _ipc_envelope_code(exc) == "TREASURY_INSUFFICIENT_BALANCE"


# ── (3) TreasuryBudgetNotFoundError ↔ TREASURY_BUDGET_NOT_FOUND ─────────────


class TestTreasuryBudgetNotFoundEquivalence:
    """``TreasuryBudgetNotFoundError`` 는 양쪽에서 ``TREASURY_BUDGET_NOT_FOUND``.

    CLI direct path: ``treasury deallocate`` 표면 — ``ipc_send`` 가 server
    typed envelope (code=``TREASURY_BUDGET_NOT_FOUND``) 을 ClickException
    으로 변환하고, ``except click.ClickException`` 분기가 동일 코드를
    surface 한다.
    """

    def test_cli_direct_budget_not_found_via_deallocate(
        self, runner: CliRunner
    ) -> None:
        click_exc = _make_click_exc(
            "TREASURY_BUDGET_NOT_FOUND",
            "treasury.deallocate: bot 'bot-1' 의 budget record 가 없습니다",
        )

        async def _raise(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
            raise click_exc

        with patch("ante.cli.commands.ipc_helpers.ipc_send", new=_raise):
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "treasury",
                    "deallocate",
                    "bot-1",
                    "100",
                    "--account",
                    "acc-1",
                ],
            )

        assert result.exit_code != 0, result.output
        payload = _cli_envelope_payload(result.output)
        assert payload["status"] == "error"
        assert payload["code"] == "TREASURY_BUDGET_NOT_FOUND"

    def test_ipc_envelope_budget_not_found(self) -> None:
        exc = TreasuryBudgetNotFoundError(bot_id="bot-1")
        assert _ipc_envelope_code(exc) == "TREASURY_BUDGET_NOT_FOUND"


# ── (4) TreasuryDeallocateExceedsAvailableError ↔
#       TREASURY_DEALLOCATE_EXCEEDS_AVAILABLE ─────────────────────────────────


class TestTreasuryDeallocateExceedsAvailableEquivalence:
    """``TreasuryDeallocateExceedsAvailableError`` 는 양쪽에서
    ``TREASURY_DEALLOCATE_EXCEEDS_AVAILABLE``.

    CLI direct path: ``treasury deallocate`` 표면 — ``ipc_send`` 가 server
    typed envelope (code=``TREASURY_DEALLOCATE_EXCEEDS_AVAILABLE``) 을
    ClickException 으로 변환하고, ``except click.ClickException`` 분기가
    동일 코드를 surface 한다.
    """

    def test_cli_direct_deallocate_exceeds_available_via_deallocate(
        self, runner: CliRunner
    ) -> None:
        click_exc = _make_click_exc(
            "TREASURY_DEALLOCATE_EXCEEDS_AVAILABLE",
            "treasury.deallocate: 가용 예산 초과",
        )

        async def _raise(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
            raise click_exc

        with patch("ante.cli.commands.ipc_helpers.ipc_send", new=_raise):
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "treasury",
                    "deallocate",
                    "bot-1",
                    "1000000",
                    "--account",
                    "acc-1",
                ],
            )

        assert result.exit_code != 0, result.output
        payload = _cli_envelope_payload(result.output)
        assert payload["status"] == "error"
        assert payload["code"] == "TREASURY_DEALLOCATE_EXCEEDS_AVAILABLE"

    def test_ipc_envelope_deallocate_exceeds_available(self) -> None:
        exc = TreasuryDeallocateExceedsAvailableError(
            bot_id="bot-1", amount=1_000_000.0, available=500_000.0
        )
        assert _ipc_envelope_code(exc) == "TREASURY_DEALLOCATE_EXCEEDS_AVAILABLE"


# ── (5) BotNotStoppedError ↔ TREASURY_BOT_NOT_STOPPED ───────────────────────


class TestTreasuryBotNotStoppedEquivalence:
    """``BotNotStoppedError`` 는 양쪽에서 ``TREASURY_BOT_NOT_STOPPED``
    (state_conflict; running 봇의 예산 변경 거부).

    본 PR 에서 신규 부여한 ``.code = "TREASURY_BOT_NOT_STOPPED"`` 가
    IPC envelope helper-direct path 와 registry MRO lookup 양쪽에서 동일
    코드를 surface 한다는 contract 동등성을 lock 한다. CLI 표면은
    ``update_budget`` 호출 경로 (예: ``bot update --budget``) 에서 raise
    되며, ``treasury`` CLI 자체는 ``update_budget`` 직접 표면이 없으므로
    IPC envelope path 단독 단언한다 (#1843 sub-PR 3 ``BotNotAcceptingSignals``
    동형 — contract-level equivalence).
    """

    def test_ipc_envelope_bot_not_stopped(self) -> None:
        exc = BotNotStoppedError("봇이 운용 중이라 예산 변경 불가: bot-1")
        assert _ipc_envelope_code(exc) == "TREASURY_BOT_NOT_STOPPED"


# ── (6) TreasuryNotConfiguredError ↔ TREASURY_NOT_CONFIGURED ────────────────


class TestTreasuryNotConfiguredEquivalence:
    """``TreasuryNotConfiguredError`` 는 양쪽에서ApprovalStatusConflict
    안정 코드 ``TREASURY_NOT_CONFIGURED`` (service_unavailable; #1335
    ``TreasuryManager`` 미주입 / 등록된 Treasury 부재).

    본 PR 에서 신규 부여한 ``.code = "TREASURY_NOT_CONFIGURED"`` 가
    IPC envelope helper-direct path 와 registry MRO lookup 양쪽에서 동일
    코드를 surface 한다는 contract 동등성을 lock 한다. CLI 표면은
    ``BotManager`` 가 budget 작업 시 raise 하므로 ``bot create
    --budget``/``bot update --budget`` 경로에서 surface 되며, ``treasury``
    CLI 자체는 직접 표면이 없으므로 IPC envelope path 단독 단언한다.
    """

    def test_ipc_envelope_not_configured(self) -> None:
        exc = TreasuryNotConfiguredError(
            "account 'acc-1' 에 Treasury 가 구성되지 않았습니다"
        )
        assert _ipc_envelope_code(exc) == "TREASURY_NOT_CONFIGURED"
