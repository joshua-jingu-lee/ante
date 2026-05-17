"""제공된 runtime-invalid ``account_id`` construction-lifecycle CLI 경계 회귀.

(#1635, Split B — #1623 oracle probe ``treasury_status_default``/
``rule_list_default`` 축)

account-scoped **construction-lifecycle** CLI 표면 —
``treasury status --account``, ``treasury snapshot --account``
(``_create_treasury``), ``rule list --account``, ``rule info --account``
(``_create_rule_engine``) — 이 제공된 runtime-invalid ``account_id``
(``"default"``/패턴 위반/``""``)를 resource acquisition **이전** ingress에서
거부하지 않아 다음 두 drift가 있었다 (#1623 Codex finding):

- ``treasury status/snapshot``: ``_create_treasury:37`` ``require_account_id``
  가 ``db.connect()`` 이전에 raise하지만 CLI 콜백이 non-Click
  ``InvalidAccountIdError``를 명시적으로 catch하지 않아 **traceback**으로 누수.
- ``rule list/info``: 기존 ``_create_rule_engine``이 ``db.connect()`` **후**
  ``RuleEngine(account_id=...)`` 내부 ``require_account_id``가 raise하여
  ``(engine, db)``가 미반환 → 호출자 ``finally: db.close()`` 미도달 →
  aiosqlite connection **누수 → hang/timeout** (lifecycle).

#1635는 2계층으로 닫는다:

- Layer 1 (CLI ingress, 4 표면): 각 ``_create_*`` 호출 **이전**
  ``ante.cli._validators.reject_invalid_account_id`` 공유 가드로 거부.
- Layer 2 (``_create_rule_engine`` 누수 구조 제거): ``require_account_id``를
  ``db.connect()`` **이전**으로 이동(``treasury.py:37`` 패턴 1:1 미러) —
  resource 획득 전 raise라 정리 대상 0, 누수 구조 자체를 제거한다.

에러 코드 SSOT는 #1633 선결정으로 고정된
``InvalidAccountIdError.code == "VALIDATION_ERROR"``를 재사용한다(신 코드 0).

검증축 (이슈 #1635 Verification SSOT):

1. 4 표면 × {``default``, ``bad_id``(패턴 위반), ``""``} → exit ≠ 0 + JSON
   ``code="VALIDATION_ERROR"`` + traceback/timeout/hang **부재**
2. rule lifecycle regression: ``_create_rule_engine`` invalid 시 ``db.connect``
   미수행 — 자원 미획득(connection 누수 0) 단언
3. valid-pattern but absent(``acc-9999``, 패턴 일치·미존재) → VALIDATION_ERROR
   오분류 **아님**: ``rule list``는 기존 ``ACCOUNT_NOT_FOUND`` 유지,
   ``rule info``/``treasury``는 각 기존 동작 불변(ACCOUNT_NOT_FOUND 강제 안 함)
4. 정상 account_id → 4 표면 기존 동작 유지 (회귀 0)
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
# (None/""/"default"/패턴 위반). 4 표면 모두 ``--account`` required option
# 이므로 omitted가 없어 3종 전부 provided.
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


# ── treasury _create_treasury 모킹 ──────────────────────────────────


def _make_mock_treasury(summary=None, snapshot=None):
    """``_create_treasury``를 모킹. invalid가 ingress에서 막히면 미호출."""
    mock_t = AsyncMock()
    mock_t.get_summary = MagicMock(
        return_value=summary if summary is not None else _SAMPLE_SUMMARY
    )
    mock_t.get_daily_snapshot = AsyncMock(return_value=snapshot)
    mock_t.get_snapshots = AsyncMock(return_value=[])
    mock_db = AsyncMock()
    mock_db.connect = AsyncMock()
    mock_db.close = AsyncMock()

    create_calls: list[str] = []

    async def _create(account_id=None):
        create_calls.append(account_id)
        return mock_t, mock_db

    ctx_patch = patch(
        "ante.cli.commands.treasury._create_treasury",
        side_effect=_create,
    )
    return ctx_patch, mock_t, mock_db, create_calls


_SAMPLE_SUMMARY = {
    "account_balance": 1_000_000.0,
    "purchasable_amount": 800_000.0,
    "total_evaluation": 1_200_000.0,
    "total_profit_loss": 50_000.0,
    "total_allocated": 300_000.0,
    "total_reserved": 0.0,
    "unallocated": 700_000.0,
    "bot_count": 2,
}


# ── rule _create_rule_engine 모킹 (Layer 1 ingress 표면용) ──────────


def _make_mock_rule_engine():
    """``_create_rule_engine``를 모킹. invalid가 ingress에서 막히면 미호출."""
    mock_engine = MagicMock()
    mock_engine._global_rules = []
    mock_engine._strategy_rules = {}
    mock_engine.load_rules_from_config = MagicMock()
    mock_engine.load_strategy_rules_from_config = MagicMock()
    mock_db = AsyncMock()
    mock_db.connect = AsyncMock()
    mock_db.close = AsyncMock()
    mock_db.fetch_one = AsyncMock(return_value={"1": 1})

    create_calls: list[str] = []

    async def _create(account_id):
        create_calls.append(account_id)
        return mock_engine, mock_db

    ctx_patch = patch(
        "ante.cli.commands.rule._create_rule_engine",
        side_effect=_create,
    )
    return ctx_patch, mock_engine, mock_db, create_calls


def _assert_validation_error_envelope(result) -> None:
    """invalid account_id 거부 공통 단언.

    - exit ≠ 0
    - JSON envelope ``status=error`` + ``code="VALIDATION_ERROR"``
    - not-found 어휘 부재 (invalid-format → not-found 오분류 차단)
    - traceback 부재 (treasury 미catch traceback drift 차단)
    """
    assert result.exit_code != 0, result.output
    payload = json.loads(result.output.strip())
    assert payload["status"] == "error", payload
    assert payload["code"] == "VALIDATION_ERROR", payload
    assert "유효한 account_id" in payload["message"], payload
    lowered = result.output.lower()
    assert "not found" not in lowered, result.output
    assert "찾을 수 없" not in result.output, result.output
    assert "Traceback" not in result.output, result.output


# ── 축 1: 4 표면 × {default, bad_id, ""} → VALIDATION_ERROR ──────────


class TestTreasuryStatusInvalidRejected:
    """``treasury status --account`` invalid ingress 거부 (traceback 차단)."""

    @pytest.mark.parametrize("invalid", _INVALID_INPUTS)
    def test_invalid_rejected_before_create_treasury(
        self, runner, invalid: str
    ) -> None:
        ctx_patch, _mock_t, _mock_db, create_calls = _make_mock_treasury()
        with ctx_patch:
            result = runner.invoke(
                cli,
                ["--format", "json", "treasury", "status", "--account", invalid],
            )
        _assert_validation_error_envelope(result)
        # resource acquisition 이전 거부 — _create_treasury 미호출.
        assert create_calls == [], create_calls


class TestTreasurySnapshotInvalidRejected:
    """``treasury snapshot --account`` invalid ingress 거부 (traceback 차단)."""

    @pytest.mark.parametrize("invalid", _INVALID_INPUTS)
    def test_invalid_rejected_before_create_treasury(
        self, runner, invalid: str
    ) -> None:
        ctx_patch, _mock_t, _mock_db, create_calls = _make_mock_treasury()
        with ctx_patch:
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "treasury",
                    "snapshot",
                    "--account",
                    invalid,
                ],
            )
        _assert_validation_error_envelope(result)
        assert create_calls == [], create_calls


class TestRuleListInvalidRejected:
    """``rule list --account`` invalid ingress 거부 (lifecycle leak 차단)."""

    @pytest.mark.parametrize("invalid", _INVALID_INPUTS)
    def test_invalid_rejected_before_create_rule_engine(
        self, runner, invalid: str
    ) -> None:
        ctx_patch, _engine, _mock_db, create_calls = _make_mock_rule_engine()
        with ctx_patch:
            result = runner.invoke(
                cli,
                ["--format", "json", "rule", "list", "--account", invalid],
            )
        _assert_validation_error_envelope(result)
        # resource acquisition 이전 거부 — _create_rule_engine 미호출
        # (db.connect/RuleEngine 도달 안 함 → leak/timeout 차단).
        assert create_calls == [], create_calls


class TestRuleInfoInvalidRejected:
    """``rule info <rule_id> --account`` invalid ingress 거부."""

    @pytest.mark.parametrize("invalid", _INVALID_INPUTS)
    def test_invalid_rejected_before_create_rule_engine(
        self, runner, invalid: str
    ) -> None:
        ctx_patch, _engine, _mock_db, create_calls = _make_mock_rule_engine()
        with ctx_patch:
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "rule",
                    "info",
                    "some-rule",
                    "--account",
                    invalid,
                ],
            )
        _assert_validation_error_envelope(result)
        assert create_calls == [], create_calls


# ── 축 2: rule _create_rule_engine lifecycle regression ─────────────


class TestCreateRuleEngineLifecycleRegression:
    """Layer 2 — ``_create_rule_engine`` invalid 시 자원 미획득 (누수 0).

    기존 구조는 ``db.connect()`` **후** ``RuleEngine`` 내부
    ``require_account_id``가 raise하여 ``(engine, db)`` 미반환 → 호출자
    ``finally: db.close()`` 미도달 → connection 누수. Layer 2는
    ``require_account_id``를 ``db.connect()`` **이전**으로 이동해
    invalid 시 ``Database``/``db.connect``가 애초에 호출되지 않음을 보장한다.
    """

    @pytest.mark.parametrize("invalid", _INVALID_INPUTS)
    def test_invalid_raises_before_db_connect_no_resource(self, invalid: str) -> None:
        import asyncio

        from ante.account.errors import InvalidAccountIdError
        from ante.cli.commands.rule import _create_rule_engine

        mock_db_instance = AsyncMock()
        mock_db_instance.connect = AsyncMock()
        mock_db_instance.close = AsyncMock()

        with (
            patch(
                "ante.core.database.Database",
                return_value=mock_db_instance,
            ) as mock_db_cls,
            patch("ante.cli.main.get_db_path", return_value=":memory:"),
        ):
            with pytest.raises(InvalidAccountIdError) as exc_info:
                asyncio.run(_create_rule_engine(invalid))

        # #1633 SSOT 코드 보존.
        assert exc_info.value.code == "VALIDATION_ERROR"
        # 자원 미획득 — Database 인스턴스화/connect 자체가 일어나지 않음
        # (validate-before-connect: 정리 대상 0이므로 누수 구조 제거).
        mock_db_cls.assert_not_called()
        mock_db_instance.connect.assert_not_called()
        mock_db_instance.close.assert_not_called()

    def test_valid_account_id_acquires_resources(self) -> None:
        """정상 account_id → 기존대로 db.connect 수행·(engine, db) 반환."""
        import asyncio

        from ante.cli.commands.rule import _create_rule_engine

        mock_db_instance = AsyncMock()
        mock_db_instance.connect = AsyncMock()
        mock_db_instance.close = AsyncMock()

        with (
            patch(
                "ante.core.database.Database",
                return_value=mock_db_instance,
            ),
            patch("ante.cli.main.get_db_path", return_value=":memory:"),
        ):
            engine, db = asyncio.run(_create_rule_engine(_VALID_PRESENT))

        assert db is mock_db_instance
        mock_db_instance.connect.assert_awaited_once()
        # account_id 바인딩 보존.
        assert engine._account_id == _VALID_PRESENT


# ── 축 3: valid-pattern but absent → VALIDATION_ERROR 오분류 아님 ────


class TestValidButAbsentNotMisclassified:
    """패턴 유효·미존재 account_id는 invalid-format으로 오분류되지 않는다.

    valid-but-absent는 ``require_account_id``가 거부하지 않으므로 기존 경로로
    흐른다(invalid-format ↔ valid-absent 분리 불변).
    """

    def test_rule_list_valid_absent_keeps_account_not_found(self, runner) -> None:
        """``rule list --account acc-9999`` → 기존 ACCOUNT_NOT_FOUND 유지.

        narrow scope: rule_list의 기존 ``AccountNotFoundError`` →
        ``ACCOUNT_NOT_FOUND`` 분기 보존(무변경, VALIDATION_ERROR 오분류 아님).
        """
        ctx_patch, _engine, mock_db, _calls = _make_mock_rule_engine()
        # account 존재 SELECT가 미존재(None)를 반환 → AccountNotFoundError.
        mock_db.fetch_one = AsyncMock(return_value=None)
        with ctx_patch:
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "rule",
                    "list",
                    "--account",
                    _VALID_ABSENT,
                ],
            )
        assert result.exit_code == 1, result.output
        payload = json.loads(result.output.strip())
        # ingress 통과 → 기존 not-found 경로 도달 (VALIDATION_ERROR 아님).
        assert payload["code"] == "ACCOUNT_NOT_FOUND", payload
        assert payload["code"] != "VALIDATION_ERROR", payload

    def test_rule_info_valid_absent_keeps_existing_behavior(self, runner) -> None:
        """``rule info ... --account acc-9999`` → 기존 동작 불변.

        rule_info는 account 존재 SELECT/AccountNotFoundError catch가 없다
        (#1635 범위 밖). valid-absent는 ingress 통과 후 기존 경로대로
        "룰을 찾을 수 없습니다"(rule 미발견)로 흐른다 — VALIDATION_ERROR
        오분류만 아니면 되고 ACCOUNT_NOT_FOUND를 강제하지 않는다.
        """
        ctx_patch, _engine, _mock_db, create_calls = _make_mock_rule_engine()
        with ctx_patch:
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "rule",
                    "info",
                    "missing-rule",
                    "--account",
                    _VALID_ABSENT,
                ],
            )
        # ingress 통과 → _create_rule_engine 도달 (기존 동작 보존).
        assert create_calls == [_VALID_ABSENT], create_calls
        payload = json.loads(result.output.strip())
        assert payload.get("code") != "VALIDATION_ERROR", payload

    def test_treasury_status_valid_absent_keeps_existing_behavior(self, runner) -> None:
        """``treasury status --account acc-9999`` → 기존 동작 불변.

        valid-absent는 ingress 통과 → _create_treasury 도달. 기존 동작
        (AccountService.get의 not-found 등)을 강제하지 않고 VALIDATION_ERROR
        오분류만 아니면 된다.
        """
        from ante.account.errors import AccountNotFoundError

        mock_db = AsyncMock()
        mock_db.connect = AsyncMock()
        mock_db.close = AsyncMock()

        create_calls: list[str] = []

        async def _create(account_id=None):
            create_calls.append(account_id)
            raise AccountNotFoundError("계좌를 찾을 수 없습니다")

        with patch(
            "ante.cli.commands.treasury._create_treasury",
            side_effect=_create,
        ):
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "treasury",
                    "status",
                    "--account",
                    _VALID_ABSENT,
                ],
            )
        # ingress 통과 → _create_treasury 도달 (VALIDATION_ERROR 아님).
        assert create_calls == [_VALID_ABSENT], create_calls
        if result.output.strip():
            try:
                payload = json.loads(result.output.strip())
                assert payload.get("code") != "VALIDATION_ERROR", payload
            except json.JSONDecodeError:
                pass


# ── 축 4: 정상 account_id → 기존 동작 유지 (회귀 0) ──────────────────


class TestValidAccountIdRegression:
    """정상 account_id는 4 표면 모두 기존 동작을 유지한다."""

    def test_treasury_status_valid_ok(self, runner) -> None:
        ctx_patch, _mock_t, _mock_db, create_calls = _make_mock_treasury()
        with ctx_patch:
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "treasury",
                    "status",
                    "--account",
                    _VALID_PRESENT,
                ],
            )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output.strip())
        assert payload["account_balance"] == 1_000_000.0
        assert create_calls == [_VALID_PRESENT], create_calls

    def test_treasury_snapshot_valid_ok(self, runner) -> None:
        snap = {
            "snapshot_date": "2026-05-17",
            "total_asset": 1_000_000.0,
            "ante_eval_amount": 500_000.0,
            "ante_purchase_amount": 480_000.0,
            "unallocated": 500_000.0,
            "daily_pnl": 1_000.0,
            "daily_return": 0.1,
            "unrealized_pnl": 0.0,
            "bot_count": 1,
        }
        ctx_patch, _mock_t, _mock_db, create_calls = _make_mock_treasury(snapshot=snap)
        with ctx_patch:
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "treasury",
                    "snapshot",
                    "--account",
                    _VALID_PRESENT,
                ],
            )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output.strip())
        assert payload["snapshot_date"] == "2026-05-17"
        assert create_calls == [_VALID_PRESENT], create_calls

    def test_rule_list_valid_ok(self, runner) -> None:
        ctx_patch, _engine, mock_db, create_calls = _make_mock_rule_engine()
        # account 존재 SELECT가 row 반환 → not-found 분기 안 탐.
        mock_db.fetch_one = AsyncMock(return_value={"1": 1})
        with ctx_patch:
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "rule",
                    "list",
                    "--account",
                    _VALID_PRESENT,
                ],
            )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output.strip())
        # 등록된 룰 없음 → 정상 빈 목록 (실재 account의 0 rules 계약).
        assert payload["rules"] == []
        assert create_calls == [_VALID_PRESENT], create_calls

    def test_rule_info_valid_ok(self, runner) -> None:
        ctx_patch, _engine, _mock_db, create_calls = _make_mock_rule_engine()
        with ctx_patch:
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "rule",
                    "info",
                    "missing-rule",
                    "--account",
                    _VALID_PRESENT,
                ],
            )
        # ingress 통과 → _create_rule_engine 도달. rule 미발견은 기존 동작.
        assert create_calls == [_VALID_PRESENT], create_calls
        assert result.exit_code == 1, result.output
        payload = json.loads(result.output.strip())
        assert payload.get("code") != "VALIDATION_ERROR", payload
