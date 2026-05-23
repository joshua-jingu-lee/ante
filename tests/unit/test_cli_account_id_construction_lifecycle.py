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

------------------------------------------------------------------------------
(#1655, D follow-up — #1623 oracle probe ``account_suspend_default``/
``account_activate_default`` 축)

account-scoped **account-lifecycle** CLI 표면 — ``account suspend <account_id>``,
``account activate <account_id>``(둘 다 ``@click.argument`` positional required,
IPC ``account.suspend``/``account.activate`` dispatch) — 이 제공된 runtime-invalid
``account_id``(``"default"``/패턴 위반/``""``)를 IPC dispatch **이전** ingress에서
거부하지 않아 ``ipc_send``→``InvalidAccountIdError``(non-Click ``AccountError``,
``except click.ClickException`` fallback 미포착)가 **traceback**으로 누출되던
contract-drift(#1623 ``cli_account_lifecycle_invalid_account_id``)를 같은
``account.py`` ``account_info``(#1634 Split A)와 1:1 동형인
``reject_invalid_account_id`` ingress 가드로 닫는다.

``docs/specs/account/14-account-id-contract.md`` 결정표 **D bucket =
account-lifecycle / cold-path / AccountService mutation → follow-up**의 목표 상태
(invalid → ``VALIDATION_ERROR``)로 ``account suspend``/``account activate`` 2표면을
정렬한다(D bucket의 ``account delete`` 등 다른 표면·E bucket·read-family는 범위 밖).

검증축 (이슈 #1655 Verification SSOT):

5. 2 표면 × {``default``, ``bad_id``(패턴 위반), ``""``} × {json, text} →
   exit ≠ 0 + JSON ``code="VALIDATION_ERROR"`` + traceback **부재**
6. invalid 입력에서 ``ipc_send`` / ``IPCClient.send`` **미호출** 단언
   (ingress가 IPC dispatch 이전 차단 — Codex Plan Review 보강)
7. valid-format **absent** account_id(``acc-9999``)는 ingress helper를 통과해
   기존 IPC 에러 경로로 흐른다(invalid-format ↔ valid-absent 분리 불변 —
   Codex Plan Review 보강): VALIDATION_ERROR 오분류 아님 + ``IPCClient.send``
   도달
8. 정상 account_id → 2 표면 IPC dispatch 도달·기존 동작 유지 (회귀 0)
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

        #1726 SSOT consolidation 후: account 존재 SELECT/raise는
        ``_create_rule_engine`` 내부에서 일어난다. mock helper가
        ``AccountNotFoundError`` 를 raise해 호출 표면의 ``except`` 매핑이
        ``ACCOUNT_NOT_FOUND`` 로 분기함을 보존한다.
        """
        from ante.account.errors import AccountNotFoundError

        ctx_patch = patch(
            "ante.cli.commands.rule._create_rule_engine",
            side_effect=AccountNotFoundError(
                f"계좌 '{_VALID_ABSENT}'를 찾을 수 없습니다."
            ),
        )
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


# ════════════════════════════════════════════════════════════════════════════
# #1655, D follow-up — account-lifecycle IPC ingress
# (oracle probe ``account_suspend_default``/``account_activate_default``)
#
# ``account suspend``/``account activate``는 IPC ``account.suspend``/
# ``account.activate`` dispatch라 ``_create_*`` resource 모킹이 아니라
# ``ipc_send``/``IPCClient`` spy로 검증한다(#1636 Split C 동형). 두 함수는
# ``from ante.cli.commands.ipc_helpers import ipc_send`` local import이므로
# ``ante.cli.commands.ipc_helpers.ipc_send`` 패치가 호출 경로를 가린다.
# ════════════════════════════════════════════════════════════════════════════


# account suspend/activate는 positional required arg(omitted 없음). 3종 전부
# provided로 검증한다 (#1634/#1635 _INVALID_INPUTS 동형: default/패턴위반/"").
_LIFECYCLE_SURFACES = [
    ("suspend", ["account", "suspend"], "account.suspend", "정지 완료"),
    ("activate", ["account", "activate"], "account.activate", "활성화 완료"),
]


def _make_ipc_spy() -> tuple[object, AsyncMock, AsyncMock]:
    """``ipc_send``/``IPCClient.send`` 이중 spy.

    invalid account_id가 ingress(``reject_invalid_account_id``)에서 막히면
    ``ipc_send``도 ``IPCClient.send``도 호출되면 안 된다(IPC dispatch 이전
    차단 — Codex Plan Review 보강). ``ipc_send``는 함수 본문 local import라
    ``ipc_helpers.ipc_send``를 패치하고, 그 내부에서 도달했을 경우를 대비해
    ``IPCClient`` 자체도 spy로 둔다(이중 방어).
    """
    ipc_send_mock = AsyncMock(
        side_effect=AssertionError(
            "invalid account_id가 ipc_send까지 도달했다 (ingress 차단 실패)"
        )
    )
    client_send_mock = AsyncMock(
        side_effect=AssertionError(
            "invalid account_id가 IPCClient.send까지 도달했다 (ingress 차단 실패)"
        )
    )
    mock_client = AsyncMock()
    mock_client.send = client_send_mock
    client_cls = MagicMock(return_value=mock_client)
    return client_cls, ipc_send_mock, client_send_mock


# ── 축 5/6: 2 표면 × {default, bad_id, ""} × {json,text} → VALIDATION_ERROR ──


class TestAccountLifecycleInvalidRejected:
    """``account suspend``/``account activate`` invalid ingress 거부.

    IPC dispatch **이전** ``reject_invalid_account_id`` 가드(#1634 ``account_info``
    1:1 동형 미러)가 traceback 누출을 ``VALIDATION_ERROR`` envelope + exit 1로
    변환하고, ``ipc_send``/``IPCClient.send``가 호출되지 않음을 단언한다.
    """

    @pytest.mark.parametrize(
        "name,argv,_ipc_cmd,_success",
        _LIFECYCLE_SURFACES,
        ids=[s[0] for s in _LIFECYCLE_SURFACES],
    )
    @pytest.mark.parametrize("invalid", _INVALID_INPUTS)
    def test_invalid_rejected_before_ipc_dispatch_json(
        self, runner, name, argv, _ipc_cmd, _success, invalid: str
    ) -> None:
        client_cls, ipc_send_mock, client_send_mock = _make_ipc_spy()
        with (
            patch("ante.cli.commands.ipc_helpers.ipc_send", ipc_send_mock),
            patch("ante.cli.commands.ipc_helpers.IPCClient", client_cls),
            patch(
                "ante.cli.commands.ipc_helpers.get_socket_path",
                return_value="/tmp/test.sock",
            ),
        ):
            result = runner.invoke(cli, ["--format", "json", *argv, invalid])
        _assert_validation_error_envelope(result)
        # traceback 부재: 예외가 있다면 SystemExit만 허용.
        if result.exception is not None:
            assert isinstance(result.exception, SystemExit), (
                f"[{name} {invalid!r}] 비-SystemExit 예외/traceback: "
                f"{result.exception!r}"
            )
        # IPC dispatch 이전 차단 — ipc_send / IPCClient.send 미호출.
        ipc_send_mock.assert_not_awaited()
        client_send_mock.assert_not_awaited()

    @pytest.mark.parametrize(
        "name,argv,_ipc_cmd,_success",
        _LIFECYCLE_SURFACES,
        ids=[s[0] for s in _LIFECYCLE_SURFACES],
    )
    @pytest.mark.parametrize("invalid", _INVALID_INPUTS)
    def test_invalid_rejected_before_ipc_dispatch_text(
        self, runner, name, argv, _ipc_cmd, _success, invalid: str
    ) -> None:
        """text 모드: exit≠0 + stdout JSON 누출 없음 + traceback 부재."""
        client_cls, ipc_send_mock, client_send_mock = _make_ipc_spy()
        with (
            patch("ante.cli.commands.ipc_helpers.ipc_send", ipc_send_mock),
            patch("ante.cli.commands.ipc_helpers.IPCClient", client_cls),
            patch(
                "ante.cli.commands.ipc_helpers.get_socket_path",
                return_value="/tmp/test.sock",
            ),
        ):
            result = runner.invoke(cli, [*argv, invalid])
        assert result.exit_code != 0, result.output
        if result.exception is not None:
            assert isinstance(result.exception, SystemExit), (
                f"[{name} {invalid!r}] 비-SystemExit 예외/traceback: "
                f"{result.exception!r}"
            )
        assert "Traceback" not in result.output, result.output
        ipc_send_mock.assert_not_awaited()
        client_send_mock.assert_not_awaited()


# ── 축 7: valid-format absent → ingress 통과해 기존 IPC 에러 경로 ────────────


class TestAccountLifecycleValidAbsentNotMisclassified:
    """패턴 유효·미존재 account_id는 invalid-format으로 오분류되지 않는다.

    valid-but-absent는 ``require_account_id``가 거부하지 않으므로 ingress helper를
    통과해 기존 IPC 에러 경로로 흐른다(invalid-format ↔ valid-absent 분리 불변 —
    Codex Plan Review 보강). 서버측 ``account.suspend``/``account.activate``
    핸들러가 not-found를 내면 ``ipc_send``가 그것을 ``click.ClickException``으로
    변환한다. 본 테스트는 helper가 그 경로에 VALIDATION_ERROR 오분류를
    주입하지 않고 ``IPCClient.send``에 valid account_id가 도달함만 못박는다.
    """

    @pytest.mark.parametrize(
        "name,argv,ipc_cmd,_success",
        _LIFECYCLE_SURFACES,
        ids=[s[0] for s in _LIFECYCLE_SURFACES],
    )
    def test_valid_absent_flows_to_existing_ipc_error_path(
        self, runner, name, argv, ipc_cmd, _success
    ) -> None:
        # 서버측 핸들러가 not-found error envelope를 반환하는 상황을 모킹.
        # ingress helper를 통과하면 IPCClient.send가 valid account_id로
        # 호출되고, ipc_send가 error 응답을 ClickException으로 변환한다.
        client_send_mock = AsyncMock(
            return_value={
                "status": "error",
                "error": {
                    "code": "ACCOUNT_NOT_FOUND",
                    "message": "계좌를 찾을 수 없습니다",
                },
            }
        )
        mock_client = AsyncMock()
        mock_client.send = client_send_mock
        client_cls = MagicMock(return_value=mock_client)
        with (
            patch("ante.cli.commands.ipc_helpers.IPCClient", client_cls),
            patch(
                "ante.cli.commands.ipc_helpers.get_socket_path",
                return_value="/tmp/test.sock",
            ),
        ):
            result = runner.invoke(cli, ["--format", "json", *argv, _VALID_ABSENT])
        # ingress 통과 → IPCClient.send가 valid account_id로 도달.
        client_send_mock.assert_awaited_once()
        sent_args = client_send_mock.await_args[0]
        assert sent_args[0] == ipc_cmd, sent_args
        assert sent_args[1].get("account_id") == _VALID_ABSENT, sent_args
        # VALIDATION_ERROR 오분류 아님(기존 IPC 에러 경로 보존).
        assert result.exit_code != 0, result.output
        if result.output.strip():
            try:
                payload = json.loads(result.output.strip())
                assert payload.get("code") != "VALIDATION_ERROR", payload
            except json.JSONDecodeError:
                pass


# ── 축 8: 정상 account_id → IPC dispatch 도달·회귀 0 ────────────────────────


class TestAccountLifecycleValidRegression:
    """정상 account_id는 2 표면 모두 기존 IPC dispatch 동작을 유지한다."""

    @pytest.mark.parametrize(
        "name,argv,ipc_cmd,success",
        _LIFECYCLE_SURFACES,
        ids=[s[0] for s in _LIFECYCLE_SURFACES],
    )
    def test_valid_account_id_dispatches_ipc(
        self, runner, name, argv, ipc_cmd, success
    ) -> None:
        client_send_mock = AsyncMock(return_value={"status": "ok", "data": {}})
        mock_client = AsyncMock()
        mock_client.send = client_send_mock
        client_cls = MagicMock(return_value=mock_client)
        with (
            patch("ante.cli.commands.ipc_helpers.IPCClient", client_cls),
            patch(
                "ante.cli.commands.ipc_helpers.get_socket_path",
                return_value="/tmp/test.sock",
            ),
        ):
            result = runner.invoke(cli, [*argv, _VALID_PRESENT])
        assert result.exit_code == 0, result.output
        assert success in result.output, result.output
        client_send_mock.assert_awaited_once()
        sent_args = client_send_mock.await_args[0]
        assert sent_args[0] == ipc_cmd, sent_args
        assert sent_args[1].get("account_id") == _VALID_PRESENT, sent_args
