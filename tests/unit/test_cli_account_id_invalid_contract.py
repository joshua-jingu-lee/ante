"""제공된 runtime-invalid ``account_id`` read-only CLI ingress 거부 회귀.

(#1634, Split A — #1623 oracle probe ``account_info_default``/
``account_info_bad_pattern``/``bot_list_default`` 축)

account-scoped **read-only** CLI 표면 — ``account info <account_id>``(positional),
``account credentials <account_id>``(positional),
``bot list --account <account_id>``(option) — 이 제공된 runtime-invalid
``account_id``(``"default"``/패턴 위반/``""``)를
``docs/specs/account/14-account-id-contract.md`` "Runtime invalid (어떤 시점에도
거부)" 계약(``require_account_id``)대로 ``svc.get`` lookup / SQL filter **이전**
ingress에서 거부하지 않고 not-found 메시지(exit 1, code 없음)나 exit 0 + empty
success로 흘리던 contract-drift를
``ante.cli._validators.reject_invalid_account_id`` 공유 가드로 차단한다.

에러 코드 SSOT는 #1633 선결정으로 고정된
``InvalidAccountIdError.code == "VALIDATION_ERROR"``를 재사용한다(신 코드 0).

검증축 (이슈 #1634 Verification SSOT):

1. 3 표면 × {``default``, ``bad_id``(패턴 위반), ``""``} → exit ≠ 0 + JSON
   ``code="VALIDATION_ERROR"`` + not-found 메시지/exit0-empty/traceback **부재**
2. valid-pattern but absent(``acc-9999``, 패턴 일치·미존재) → VALIDATION_ERROR
   오분류 **아님**: ``account info``/``credentials``는 기존 not-found 동작 유지,
   ``bot list``는 기존 empty 동작 유지 (invalid-format ↔ valid-absent 분리)
3. ``bot list`` omitted-vs-provided 경계: ``--account`` 미지정(``None``) →
   전체 봇 반환(회귀 0) / ``--account ""``(provided) → VALIDATION_ERROR 거부
4. 정상 account_id → 3 표면 기존 동작 유지 (회귀 0)
"""

from __future__ import annotations

import json
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from ante.account.models import Account, AccountStatus, TradingMode
from ante.cli.main import cli
from ante.member.models import Member, MemberRole, MemberType

# 제공된 runtime-invalid account_id 입력 — 14-account-id-contract.md
# "Runtime invalid (어떤 시점에도 거부)" 계약 + scoping.is_invalid_account_id
# (None/""/"default"/패턴 위반). positional 표면은 omitted가 없으므로 3종 전부
# provided. bot list omitted(None)는 별도 경계 케이스로 분리 검증한다.
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


def _mock_account(account_id: str = "domestic") -> Account:
    return Account(
        account_id=account_id,
        name="국내 주식",
        exchange="KRX",
        currency="KRW",
        timezone="Asia/Seoul",
        trading_mode=TradingMode.VIRTUAL,
        broker_type="test",
        buy_commission_rate=Decimal("0.00015"),
        sell_commission_rate=Decimal("0.00195"),
        status=AccountStatus.ACTIVE,
        credentials={"app_key": "PSxxxxxxxx"},
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
    db = AsyncMock()
    db.connect = AsyncMock()
    db.close = AsyncMock()
    db.execute = AsyncMock()
    db.fetch_all = AsyncMock(return_value=rows if rows is not None else [])
    db.fetch_one = AsyncMock(return_value=None)
    return db


# ── account info / credentials helper ───────────────────────────────


def _patch_account_service(svc: AsyncMock, db: AsyncMock):
    """#1856: ``_create_account_service`` 가 async context manager 로
    전환됐다. fake factory 는 ``ctx`` 인자를 받아 ``svc`` 만 yield 한다.
    """
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _create_service(ctx=None):  # noqa: ANN001, ANN202
        yield svc

    return patch(
        "ante.cli.commands.account._create_account_service",
        new=_create_service,
    )


def _patch_bot_services(db: AsyncMock):
    async def _create_services():
        return db, MagicMock(), MagicMock(), AsyncMock()

    return patch(
        "ante.cli.commands.bot._create_services",
        new=_create_services,
    )


def _assert_validation_error_envelope(result, invalid_value: str) -> None:
    """invalid account_id 거부 공통 단언.

    - exit ≠ 0
    - JSON envelope ``status=error`` + ``code="VALIDATION_ERROR"``
    - not-found 어휘(not found/찾을 수 없 등) 부재 (오분류 차단)
    - traceback 부재
    """
    assert result.exit_code != 0, result.output
    payload = json.loads(result.output.strip())
    assert payload["status"] == "error", payload
    assert payload["code"] == "VALIDATION_ERROR", payload
    assert "유효한 account_id" in payload["message"], payload
    # not-found 오분류 차단 — invalid-format을 not-found로 분류하면 안 된다.
    lowered = result.output.lower()
    assert "not found" not in lowered, result.output
    assert "찾을 수 없" not in result.output, result.output
    assert "Traceback" not in result.output, result.output


# ── 축 1: 3 표면 × {default, bad_id, ""} → VALIDATION_ERROR ──────────


class TestAccountInfoInvalidRejected:
    """``account info <account_id>`` (positional) invalid ingress 거부."""

    @pytest.mark.parametrize("invalid", _INVALID_INPUTS)
    def test_invalid_account_id_rejected_before_lookup(
        self, runner, invalid: str
    ) -> None:
        svc = AsyncMock()
        svc.get = AsyncMock(side_effect=AssertionError("svc.get 호출되면 안 됨"))
        db = _make_mock_db()
        with _patch_account_service(svc, db):
            result = runner.invoke(
                cli, ["--format", "json", "account", "info", invalid]
            )
        _assert_validation_error_envelope(result, invalid)
        # lookup 이전 거부 — svc.get 미호출.
        svc.get.assert_not_called()


class TestAccountCredentialsInvalidRejected:
    """``account credentials <account_id>`` (positional) invalid ingress 거부."""

    @pytest.mark.parametrize("invalid", _INVALID_INPUTS)
    def test_invalid_account_id_rejected_before_lookup(
        self, runner, invalid: str
    ) -> None:
        svc = AsyncMock()
        svc.get = AsyncMock(side_effect=AssertionError("svc.get 호출되면 안 됨"))
        db = _make_mock_db()
        with _patch_account_service(svc, db):
            result = runner.invoke(
                cli, ["--format", "json", "account", "credentials", invalid]
            )
        _assert_validation_error_envelope(result, invalid)
        svc.get.assert_not_called()


class TestBotListInvalidRejected:
    """``bot list --account <account_id>`` (option) invalid ingress 거부."""

    @pytest.mark.parametrize("invalid", _INVALID_INPUTS)
    def test_invalid_account_id_rejected_before_filter(
        self, runner, invalid: str
    ) -> None:
        db = _make_mock_db([])
        with _patch_bot_services(db):
            result = runner.invoke(
                cli,
                ["--format", "json", "bot", "list", "--account", invalid],
            )
        _assert_validation_error_envelope(result, invalid)
        # SQL filter 이전 거부 — fetch_all 미호출 (exit0-empty success 차단).
        db.fetch_all.assert_not_called()


# ── 축 2: valid-pattern but absent → VALIDATION_ERROR 오분류 아님 ────


class TestValidButAbsentNotMisclassified:
    """패턴 유효·미존재 account_id는 invalid-format으로 오분류되지 않는다.

    (Codex next-step: invalid-format ↔ valid-absent 분리, VALIDATION_ERROR
    과적용 0)
    """

    def test_account_info_valid_absent_keeps_not_found(self, runner) -> None:
        """``account info acc-9999`` → 기존 not-found 유지(VALIDATION_ERROR 아님)."""
        from ante.account.errors import AccountNotFoundError

        svc = AsyncMock()
        svc.get = AsyncMock(side_effect=AccountNotFoundError("계좌를 찾을 수 없습니다"))
        db = _make_mock_db()
        with _patch_account_service(svc, db):
            result = runner.invoke(
                cli, ["--format", "json", "account", "info", _VALID_ABSENT]
            )
        assert result.exit_code == 1, result.output
        payload = json.loads(result.output.strip())
        # ingress 통과 → not-found 경로 도달 (VALIDATION_ERROR 아님).
        assert payload.get("code") != "VALIDATION_ERROR", payload
        svc.get.assert_awaited_once_with(_VALID_ABSENT)

    def test_account_credentials_valid_absent_keeps_not_found(self, runner) -> None:
        """``account credentials acc-9999`` → 기존 not-found 동작 유지."""
        from ante.account.errors import AccountNotFoundError

        svc = AsyncMock()
        svc.get = AsyncMock(side_effect=AccountNotFoundError("계좌를 찾을 수 없습니다"))
        db = _make_mock_db()
        with _patch_account_service(svc, db):
            result = runner.invoke(
                cli,
                ["--format", "json", "account", "credentials", _VALID_ABSENT],
            )
        assert result.exit_code == 1, result.output
        payload = json.loads(result.output.strip())
        assert payload.get("code") != "VALIDATION_ERROR", payload
        svc.get.assert_awaited_once_with(_VALID_ABSENT)

    def test_bot_list_valid_absent_keeps_empty(self, runner) -> None:
        """``bot list --account acc-9999`` → 기존 empty 동작 유지(거부 아님)."""
        db = _make_mock_db([])
        with _patch_bot_services(db):
            result = runner.invoke(
                cli,
                ["--format", "json", "bot", "list", "--account", _VALID_ABSENT],
            )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output.strip())
        assert payload.get("code") != "VALIDATION_ERROR", payload
        assert payload["bots"] == []
        # ingress 통과 → SQL filter 도달 (account_id 파라미터 바인딩).
        call_args = db.fetch_all.call_args
        assert _VALID_ABSENT in call_args[0][1], call_args


# ── 축 3: bot list omitted-vs-provided 경계 (별도 케이스 고정) ───────


class TestBotListOmittedVsProvidedBoundary:
    """``bot list`` ``--account`` 미지정(None) vs provided ``""`` 분리 고정.

    (Codex next-step: omitted(None) 전체-반환 보존이 불변; provided-empty는
    거부)
    """

    def test_account_omitted_returns_all_bots(self, runner) -> None:
        """``--account`` 미지정(None) → 전체 봇 반환 (omitted 보존, 회귀 0)."""
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
        db = _make_mock_db(bot_rows)
        with _patch_bot_services(db):
            result = runner.invoke(cli, ["--format", "json", "bot", "list"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output.strip())
        assert payload["bots"][0]["account_id"] == "domestic"
        # 파라미터 없이 SQL만 — 전체 봇 쿼리 (omitted 분기 보존).
        call_args = db.fetch_all.call_args
        assert len(call_args[0]) == 1, call_args

    def test_account_provided_empty_rejected(self, runner) -> None:
        """``--account ""``(provided empty) → VALIDATION_ERROR 거부.

        기존 ``if account_id:`` truthy가 ``""``를 falsy-skip해 전체 봇을
        반환하던 provided-empty drift를 닫는다 (omitted None과 구별).
        """
        db = _make_mock_db([])
        with _patch_bot_services(db):
            result = runner.invoke(
                cli, ["--format", "json", "bot", "list", "--account", ""]
            )
        _assert_validation_error_envelope(result, "")
        db.fetch_all.assert_not_called()


# ── 축 4: 정상 account_id → 기존 동작 유지 (회귀 0) ──────────────────


class TestValidAccountIdRegression:
    """정상 account_id는 3 표면 모두 기존 동작을 유지한다."""

    def test_account_info_valid_ok(self, runner) -> None:
        svc = AsyncMock()
        svc.get = AsyncMock(return_value=_mock_account(_VALID_PRESENT))
        db = _make_mock_db()
        with _patch_account_service(svc, db):
            result = runner.invoke(
                cli, ["--format", "json", "account", "info", _VALID_PRESENT]
            )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output.strip())
        assert payload["account_id"] == _VALID_PRESENT
        svc.get.assert_awaited_once_with(_VALID_PRESENT)

    def test_account_credentials_valid_ok(self, runner) -> None:
        svc = AsyncMock()
        svc.get = AsyncMock(return_value=_mock_account(_VALID_PRESENT))
        db = _make_mock_db()
        with _patch_account_service(svc, db):
            result = runner.invoke(
                cli,
                ["--format", "json", "account", "credentials", _VALID_PRESENT],
            )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output.strip())
        assert payload["account_id"] == _VALID_PRESENT
        assert "app_key" in payload["credentials"]
        svc.get.assert_awaited_once_with(_VALID_PRESENT)

    def test_bot_list_valid_filter_ok(self, runner) -> None:
        bot_rows = [
            {
                "bot_id": "bot-1",
                "name": "테스트봇",
                "strategy_id": "s1",
                "account_id": _VALID_PRESENT,
                "status": "idle",
                "created_at": "2026-01-01",
            },
        ]
        db = _make_mock_db(bot_rows)
        with _patch_bot_services(db):
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "bot",
                    "list",
                    "--account",
                    _VALID_PRESENT,
                ],
            )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output.strip())
        assert payload["bots"][0]["account_id"] == _VALID_PRESENT
        call_args = db.fetch_all.call_args
        assert _VALID_PRESENT in call_args[0][1], call_args
