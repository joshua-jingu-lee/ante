"""E bucket — non-broker mutating IPC CLI invalid ``account_id`` ingress 거부 회귀.

(#1656, E bucket — #1623 oracle probe ``treasury_allocate_default``/
``treasury_deallocate_default``/``bot_create_default`` 축)

account-scoped **non-broker mutating IPC** CLI 표면 —
``treasury allocate <bot_id> <amount> --account <id>``,
``treasury deallocate <bot_id> <amount> --account <id>``,
``bot create --account <id>`` — 이 제공된 runtime-invalid ``account_id``
(``"default"``/패턴 위반/``""``)를 ``docs/specs/account/14-account-id-contract.md``
E row(L249) "Runtime invalid (어떤 시점에도 거부)" 계약대로
``ipc_send``(→ ``_handle_treasury_allocate``/``_handle_treasury_deallocate``/
``_handle_bot_create``) **이전** ingress 에서 거부하지 않고
``ipc_send``→``InvalidAccountIdError``(non-Click ``AccountError``) 미catch
traceback 으로 종료하던 contract-drift 를
``ante.cli._validators.reject_invalid_account_id`` 공유 가드로 차단한다.

1차 보증은 IPC handler-first ``require_account_id``(별도
``test_ipc_error_code_mapping.py`` direct-IPC 회귀)이며, 본 파일은 CLI
defense-in-depth(clean early exit + ``ipc_send`` 미호출)를 #1634/#1635
구조 미러로 고정한다.

에러 코드 SSOT 는 #1633 선결정으로 고정된
``InvalidAccountIdError.code == "VALIDATION_ERROR"`` 를 재사용한다(신 코드 0).

검증축:

1. 3 표면 × {``default``, ``bad_id!``(패턴 위반), ``""``} → exit ≠ 0 + JSON
   ``code="VALIDATION_ERROR"`` + traceback **부재**
2. invalid 입력에서 ``ipc_send`` / ``IPCClient.send`` **미호출** 단언
3. ``bot create`` omitted-vs-provided 경계: ``--account`` 미지정(``None``) →
   비대화형 resolver 분기 **보존**(omitted 불변, invalid 검증 우회)
4. valid-pattern but absent(``acc-9999``) → ingress 통과(VALIDATION_ERROR
   오분류 아님, invalid-format ↔ valid-absent 분리)
5. 정상 account_id → 3 표면 ``ipc_send`` 도달(회귀 0)
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from ante.cli.main import cli
from ante.member.models import Member, MemberRole, MemberType

# 제공된 runtime-invalid account_id 입력 — 14-account-id-contract.md
# "Runtime invalid (어떤 시점에도 거부)" + scoping.is_invalid_account_id
# (""/"default"/패턴 위반). required `--account` 표면(treasury)은 omitted 가
# 없어 3종 전부 provided. bot create omitted(None)는 별도 경계 케이스.
_INVALID_INPUTS = ["default", "bad_id!", ""]

# 패턴 유효(^[a-zA-Z0-9-]{3,30}$)·미존재 account_id. invalid-format ↔
# valid-absent 분리 — VALIDATION_ERROR 과적용 0 회귀.
_VALID_ABSENT = "acc-9999"

# 정상 account_id (회귀 0 검증).
_VALID_PRESENT = "domestic"


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


def _patch_ipc_send():
    """``ipc_send`` 를 spy AsyncMock 으로 패치.

    invalid 가 ingress 에서 막히면 ``ipc_send`` 가 호출되지 않아야 한다.
    treasury / bot 커맨드는 ``from ante.cli.commands.ipc_helpers import
    ipc_send`` 를 함수 내부에서 import 하므로 원본 심볼을 패치한다.
    """
    spy = AsyncMock(return_value={"success": True, "bot_id": "bot-x"})
    return patch("ante.cli.commands.ipc_helpers.ipc_send", new=spy), spy


def _assert_validation_error_envelope(result) -> None:
    """invalid account_id 거부 공통 단언.

    - exit ≠ 0
    - JSON envelope ``status=error`` + ``code="VALIDATION_ERROR"``
    - traceback 부재 (mutating IPC 미catch traceback drift 차단)
    """
    assert result.exit_code != 0, result.output
    payload = json.loads(result.output.strip())
    assert payload["status"] == "error", payload
    assert payload["code"] == "VALIDATION_ERROR", payload
    assert "유효한 account_id" in payload["message"], payload
    assert "Traceback" not in result.output, result.output


# ── 축 1+2: 3 표면 × invalid → VALIDATION_ERROR + ipc_send 미호출 ────


class TestTreasuryAllocateInvalidRejected:
    """``treasury allocate`` invalid ingress 거부 (traceback/ipc_send 차단)."""

    @pytest.mark.parametrize("invalid", _INVALID_INPUTS)
    def test_invalid_rejected_before_ipc_send(self, runner, invalid: str) -> None:
        ipc_patch, spy = _patch_ipc_send()
        with ipc_patch:
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "treasury",
                    "allocate",
                    "bot-1",
                    "1000",
                    "--account",
                    invalid,
                ],
            )
        _assert_validation_error_envelope(result)
        # ingress 거부 — ipc_send 미호출 (traceback drift 차단).
        spy.assert_not_called()


class TestTreasuryDeallocateInvalidRejected:
    """``treasury deallocate`` invalid ingress 거부."""

    @pytest.mark.parametrize("invalid", _INVALID_INPUTS)
    def test_invalid_rejected_before_ipc_send(self, runner, invalid: str) -> None:
        ipc_patch, spy = _patch_ipc_send()
        with ipc_patch:
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "treasury",
                    "deallocate",
                    "bot-1",
                    "1000",
                    "--account",
                    invalid,
                ],
            )
        _assert_validation_error_envelope(result)
        spy.assert_not_called()


class TestBotCreateInvalidRejected:
    """``bot create --account`` (provided) invalid ingress 거부."""

    @pytest.mark.parametrize("invalid", _INVALID_INPUTS)
    def test_invalid_rejected_before_ipc_send(self, runner, invalid: str) -> None:
        ipc_patch, spy = _patch_ipc_send()
        with ipc_patch:
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "bot",
                    "create",
                    "--name",
                    "Probe",
                    "--strategy",
                    "s1",
                    "--account",
                    invalid,
                ],
            )
        _assert_validation_error_envelope(result)
        spy.assert_not_called()


# ── 축 3: bot create omitted-vs-provided 경계 (resolver 보존 불변) ──


class TestBotCreateOmittedResolverPreserved:
    """``bot create`` ``--account`` 미지정(None) → 비대화형 resolver 분기 보존.

    omitted(None) 는 invalid 검증을 우회하고 ``_resolve_account_non_interactive``
    경로로 흘러야 한다(provided-only 검증, #1634 ``bot_list`` 동형). 본
    테스트는 단일 active 계좌가 없을 때 resolver 가 도달해
    ``BOT_MISSING_REQUIRED_ACCOUNT`` 로 실패함을 확인한다(VALIDATION_ERROR
    아님 — invalid-format 거부가 omitted 를 삼키지 않음).
    """

    def test_account_omitted_reaches_resolver_not_validation_error(
        self, runner
    ) -> None:
        ipc_patch, spy = _patch_ipc_send()

        async def _list_accounts():
            db = AsyncMock()
            account_service = AsyncMock()
            account_service.list = AsyncMock(return_value=[])  # active 0개
            return db, MagicMock(), MagicMock(), account_service

        with (
            ipc_patch,
            patch(
                "ante.cli.commands.bot._create_services",
                new=_list_accounts,
            ),
        ):
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "bot",
                    "create",
                    "--name",
                    "Probe",
                    "--strategy",
                    "s1",
                ],
            )
        # resolver 도달 → BOT_MISSING_REQUIRED_ACCOUNT (omitted 보존).
        assert result.exit_code != 0, result.output
        payload = json.loads(result.output.strip())
        assert payload.get("code") != "VALIDATION_ERROR", payload
        assert payload.get("code") == "BOT_MISSING_REQUIRED_ACCOUNT", payload
        # invalid 검증 우회 → ipc_send 도 미호출(resolver 단계에서 종료).
        spy.assert_not_called()


# ── 축 4: valid-pattern but absent → ingress 통과 (오분류 아님) ──────


class TestValidButAbsentNotMisclassified:
    """패턴 유효·미존재 account_id 는 invalid-format 으로 오분류되지 않는다.

    valid-absent 는 ingress 통과 → ``ipc_send`` 도달(VALIDATION_ERROR 아님,
    invalid-format ↔ valid-absent 분리). server-side 결과는 mock 으로
    고정하고 ingress 통과(ipc_send 호출)만 검증한다.
    """

    def test_treasury_allocate_valid_absent_reaches_ipc_send(self, runner) -> None:
        ipc_patch, spy = _patch_ipc_send()
        spy.return_value = {"success": True}
        with ipc_patch:
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "treasury",
                    "allocate",
                    "bot-1",
                    "1000",
                    "--account",
                    _VALID_ABSENT,
                ],
            )
        assert result.exit_code == 0, result.output
        # ingress 통과 → ipc_send 도달 (account_id 파라미터 바인딩).
        spy.assert_awaited_once()
        sent_args = spy.await_args[0][1]
        assert sent_args["account_id"] == _VALID_ABSENT, sent_args

    def test_bot_create_valid_absent_reaches_ipc_send(self, runner) -> None:
        ipc_patch, spy = _patch_ipc_send()
        spy.return_value = {"bot_id": "bot-x"}
        with ipc_patch:
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "bot",
                    "create",
                    "--name",
                    "Probe",
                    "--strategy",
                    "s1",
                    "--account",
                    _VALID_ABSENT,
                ],
            )
        assert result.exit_code == 0, result.output
        spy.assert_awaited_once()
        sent_args = spy.await_args[0][1]
        assert sent_args["account_id"] == _VALID_ABSENT, sent_args


# ── 축 5: 정상 account_id → ipc_send 도달 (회귀 0) ──────────────────


class TestValidAccountIdRegression:
    """정상 account_id 는 3 표면 모두 ``ipc_send`` 에 도달한다(회귀 0)."""

    def test_treasury_allocate_valid_ok(self, runner) -> None:
        ipc_patch, spy = _patch_ipc_send()
        spy.return_value = {"success": True}
        with ipc_patch:
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "treasury",
                    "allocate",
                    "bot-1",
                    "1000",
                    "--account",
                    _VALID_PRESENT,
                ],
            )
        assert result.exit_code == 0, result.output
        spy.assert_awaited_once()
        assert spy.await_args[0][1]["account_id"] == _VALID_PRESENT

    def test_treasury_deallocate_valid_ok(self, runner) -> None:
        ipc_patch, spy = _patch_ipc_send()
        spy.return_value = {"success": True}
        with ipc_patch:
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "treasury",
                    "deallocate",
                    "bot-1",
                    "1000",
                    "--account",
                    _VALID_PRESENT,
                ],
            )
        assert result.exit_code == 0, result.output
        spy.assert_awaited_once()
        assert spy.await_args[0][1]["account_id"] == _VALID_PRESENT

    def test_bot_create_valid_ok(self, runner) -> None:
        ipc_patch, spy = _patch_ipc_send()
        spy.return_value = {"bot_id": "bot-x"}
        with ipc_patch:
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "bot",
                    "create",
                    "--name",
                    "Probe",
                    "--strategy",
                    "s1",
                    "--account",
                    _VALID_PRESENT,
                ],
            )
        assert result.exit_code == 0, result.output
        spy.assert_awaited_once()
        assert spy.await_args[0][1]["account_id"] == _VALID_PRESENT
