"""Group Q state-conflict typed code sweep (#1812 / #1813 / #1814).

3 oracle A7 state-conflict issue sweep — 각 CLI/IPC 표면이 안정 typed code
envelope 을 surface 함을 verify 한다 (Group P #1805 missing-resource sweep
동형 패턴).

R-case 매트릭스:
  R1 #1812 ``ante account suspend <SUSPENDED-account> --format json``
         → exit 1, code=``ACCOUNT_ALREADY_SUSPENDED``
         (IPC-only — server fixture 없이 subprocess 재현이 불가하므로
         Group A #1795 ``AccountNotFoundError`` 패턴을 따라 typed exception
         class ``code`` 속성 + IPC envelope 매핑 invariant 를 직접 verify
         한다. ``test_ipc_error_code_mapping.py
         ::test_ipc_server_surfaces_typed_code_for_account_already_suspended``
         가 추가 회귀로 envelope 매핑을 lock 한다)
  R2 #1813 ``ante approval reject <REJECTED-approval> --format json``
         → exit 1, code=``APPROVAL_STATUS_CONFLICT``
         (IPC-only — R1 과 동일 분류. 직접 service ``reject(rejected_id)``
         호출이 ``ApprovalStatusConflictError`` 를 raise 함을 verify)
  R3 #1814 ``ante member suspend <SUSPENDED-member> --format json``
         → exit 1, code=``MEMBER_STATE_CONFLICT``
         (member CLI 는 ``_create_service()`` 직접 호출 경로라 subprocess
         E2E 가능. ``ante init`` → ``member register`` → ``member suspend``
         × 2 로 재현)

이전 (#1812 이전): 3 표면 모두 generic exception (``ValueError`` /
``PermissionError``) 으로 raise 되어 IPC envelope 이 ``EXECUTION_ERROR``
또는 미상수 코드로 떨어졌다. Group Q sweep 은 state-conflict 표면에
typed exception class (``.code = "ACCOUNT_ALREADY_SUSPENDED"`` 등) 를
도입하고 service-layer raise 를 typed 로 좁혀, IPC ``getattr(e, "code",
"EXECUTION_ERROR")`` envelope 이 자동으로 안정 코드를 surface 하도록 한다.

회귀 보호 매트릭스:
- ``ValueError`` 다중상속 보존: ``ApprovalStatusConflictError`` /
  ``MemberStateConflictError`` 가 ``ValueError`` 다중상속을 유지해 기존
  ``except ValueError`` caller (#1805 ``MemberNotFoundError`` 패턴 1:1
  미러) 회귀 없음.
- ``.code`` 누락 폴백 lock: typed exception class 가 인스턴스에서도
  ``getattr(exc, "code", None)`` 이 안정 코드를 반환해야 한다 (IPC
  envelope ``getattr(e, "code", "EXECUTION_ERROR")`` 폴백 회귀 차단).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

# subprocess timeout: hang 회귀를 5초 마진으로 차단한다.
_SUBPROCESS_TIMEOUT_S = 10.0


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _clean_env(
    config_dir: Path,
    *,
    encryption_key: str | None = None,
    token: str | None = None,
) -> dict[str, str]:
    """subprocess 환경 격리 — 부모 ANTE_* 변수가 새지 않도록 명시 전달."""
    env: dict[str, str] = {
        "PATH": os.environ["PATH"],
        "HOME": os.environ.get("HOME", str(config_dir)),
        "ANTE_CONFIG_DIR": str(config_dir),
        "PYTHONPATH": str(_repo_root() / "src"),
    }
    if encryption_key is not None:
        env["ANTE_DB_ENCRYPTION_KEY"] = encryption_key
    if token is not None:
        env["ANTE_MEMBER_TOKEN"] = token
    return env


def _parse_json_last(stdout: str) -> dict:
    """stdout 에서 JSON dict payload 를 추출 (error 한 줄 또는 indent 멀티라인)."""
    stripped = stdout.strip()
    if stripped.startswith("{"):
        try:
            obj = json.loads(stripped)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass

    last_obj: dict | None = None
    for raw in stdout.splitlines():
        line = raw.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            last_obj = obj
    assert last_obj is not None, f"JSON dict 라인을 stdout 에서 찾지 못함: {stdout!r}"
    return last_obj


def _run_cli(
    config_dir: Path,
    args: list[str],
    *,
    token: str | None = None,
    encryption_key: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """``ante --format json <args>`` 를 subprocess 로 실행."""
    env = _clean_env(config_dir, encryption_key=encryption_key, token=token)
    return subprocess.run(
        [sys.executable, "-m", "ante", "--format", "json", *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=_SUBPROCESS_TIMEOUT_S,
    )


def _run_init(config_dir: Path, encryption_key: str) -> tuple[str, str]:
    """``ante init`` 후 (token, encryption_key) 반환."""
    init_env = _clean_env(config_dir, encryption_key=encryption_key)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ante",
            "--format",
            "json",
            "init",
            "--name",
            "GroupQ",
        ],
        env=init_env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"init 실패: exit={result.returncode}\n"
        f"stdout={result.stdout}\nstderr={result.stderr}"
    )
    payload = json.loads(result.stdout)
    token = payload.get("token")
    assert token, f"init 출력에 token 없음: {payload}"
    return token, encryption_key


@pytest.fixture
def initialized_config(tmp_path: Path) -> tuple[Path, str, str]:
    """``ante init`` 을 완료한 (config_dir, token, encryption_key) 튜플."""
    config_dir = tmp_path / "config"
    key = Fernet.generate_key().decode()
    token, _ = _run_init(config_dir, key)
    return config_dir, token, key


# ════════════════════════════════════════════════════════════════════
# 카테고리 1 — typed exception class ``code`` 속성 lock (IPC envelope
# 매핑 invariant). #1812 / #1813 / #1814 의 state-conflict typed exception
# 이 SCREAMING_SNAKE_CASE 안정 코드를 ``.code`` 클래스 속성으로 보유함
# 을 직접 verify 한다. IPC ``server.py:_dispatch`` 가 ``getattr(e,
# "code", "EXECUTION_ERROR")`` 로 envelope 코드를 매핑하므로, 핸들러가
# 이 typed exception 을 raise 하기만 하면 envelope 에 자동 surface 된다.
# ════════════════════════════════════════════════════════════════════


class TestTypedExceptionCodeAttributes:
    """R1-R3 lock: typed exception class ``code`` 속성 매핑."""

    # ─── #1812 Account state-conflict typed codes ──────────────────

    def test_r1a_account_already_suspended_error_code(self) -> None:
        """#1812: ``AccountAlreadySuspendedError.code ==
        "ACCOUNT_ALREADY_SUSPENDED"``.
        """
        from ante.account.errors import AccountAlreadySuspendedError, AccountError

        assert AccountAlreadySuspendedError.code == "ACCOUNT_ALREADY_SUSPENDED"
        assert issubclass(AccountAlreadySuspendedError, AccountError)
        # 인스턴스에서도 동일 코드가 surface 되어 IPC envelope 의
        # ``getattr(e, "code", ...)`` 폴백이 안정 코드를 노출한다.
        exc = AccountAlreadySuspendedError("이미 정지됨")
        assert getattr(exc, "code", None) == "ACCOUNT_ALREADY_SUSPENDED"

    def test_r1b_account_suspended_error_code(self) -> None:
        """#1812: ``AccountSuspendedError.code == "ACCOUNT_SUSPENDED"``."""
        from ante.account.errors import AccountError, AccountSuspendedError

        assert AccountSuspendedError.code == "ACCOUNT_SUSPENDED"
        assert issubclass(AccountSuspendedError, AccountError)
        exc = AccountSuspendedError("정지된 계좌")
        assert getattr(exc, "code", None) == "ACCOUNT_SUSPENDED"

    def test_r1c_account_deleted_error_code(self) -> None:
        """#1812: ``AccountDeletedError.code == "ACCOUNT_DELETED"`` (IPC
        envelope 의 fallback 코드. CLI ``account delete`` 의 명시 except 는
        UX 의미 보존을 위해 ``ACCOUNT_ALREADY_DELETED`` 를 override).
        """
        from ante.account.errors import AccountDeletedError, AccountError

        assert AccountDeletedError.code == "ACCOUNT_DELETED"
        assert issubclass(AccountDeletedError, AccountError)
        exc = AccountDeletedError("삭제됨")
        assert getattr(exc, "code", None) == "ACCOUNT_DELETED"

    def test_r1d_account_has_active_bots_error_code(self) -> None:
        """#1812: ``AccountHasActiveBotsError.code == "ACCOUNT_HAS_ACTIVE_BOTS"``."""
        from ante.account.errors import AccountError, AccountHasActiveBotsError

        assert AccountHasActiveBotsError.code == "ACCOUNT_HAS_ACTIVE_BOTS"
        assert issubclass(AccountHasActiveBotsError, AccountError)
        exc = AccountHasActiveBotsError("acc-1", 2)
        assert getattr(exc, "code", None) == "ACCOUNT_HAS_ACTIVE_BOTS"

    def test_r1e_account_already_exists_error_code(self) -> None:
        """#1812: ``AccountAlreadyExistsError.code == "ACCOUNT_ALREADY_EXISTS"``."""
        from ante.account.errors import AccountAlreadyExistsError, AccountError

        assert AccountAlreadyExistsError.code == "ACCOUNT_ALREADY_EXISTS"
        assert issubclass(AccountAlreadyExistsError, AccountError)
        exc = AccountAlreadyExistsError("중복")
        assert getattr(exc, "code", None) == "ACCOUNT_ALREADY_EXISTS"

    def test_r1f_account_immutable_field_error_code(self) -> None:
        """#1812: ``AccountImmutableFieldError.code == "ACCOUNT_IMMUTABLE_FIELD"``."""
        from ante.account.errors import AccountError, AccountImmutableFieldError

        assert AccountImmutableFieldError.code == "ACCOUNT_IMMUTABLE_FIELD"
        assert issubclass(AccountImmutableFieldError, AccountError)
        exc = AccountImmutableFieldError("exchange 변경 불가")
        assert getattr(exc, "code", None) == "ACCOUNT_IMMUTABLE_FIELD"

    def test_r1g_broker_reconnect_failed_error_code(self) -> None:
        """#1812: ``BrokerReconnectFailedError.code == "BROKER_RECONNECT_FAILED"``."""
        from ante.account.errors import AccountError, BrokerReconnectFailedError

        assert BrokerReconnectFailedError.code == "BROKER_RECONNECT_FAILED"
        assert issubclass(BrokerReconnectFailedError, AccountError)
        exc = BrokerReconnectFailedError("connect 실패")
        assert getattr(exc, "code", None) == "BROKER_RECONNECT_FAILED"

    def test_r1h_missing_credentials_error_code(self) -> None:
        """#1812: ``MissingCredentialsError.code == "ACCOUNT_MISSING_CREDENTIALS"``."""
        from ante.account.errors import AccountError, MissingCredentialsError

        assert MissingCredentialsError.code == "ACCOUNT_MISSING_CREDENTIALS"
        assert issubclass(MissingCredentialsError, AccountError)
        exc = MissingCredentialsError("app_key 누락")
        assert getattr(exc, "code", None) == "ACCOUNT_MISSING_CREDENTIALS"

    def test_r1i_invalid_broker_type_error_code(self) -> None:
        """#1812: ``InvalidBrokerTypeError.code == "ACCOUNT_INVALID_BROKER_TYPE"``."""
        from ante.account.errors import AccountError, InvalidBrokerTypeError

        assert InvalidBrokerTypeError.code == "ACCOUNT_INVALID_BROKER_TYPE"
        assert issubclass(InvalidBrokerTypeError, AccountError)
        exc = InvalidBrokerTypeError("unknown broker")
        assert getattr(exc, "code", None) == "ACCOUNT_INVALID_BROKER_TYPE"

    # ─── #1813 Approval status-conflict typed code ─────────────────

    def test_r2_approval_status_conflict_error_code(self) -> None:
        """#1813: ``ApprovalStatusConflictError.code == "APPROVAL_STATUS_CONFLICT"``.

        ``ApprovalError`` + ``ValueError`` 다중상속 보존 — 기존
        ``except ValueError`` caller (CLI ``approval approve`` line 629
        generic fallback) 회귀 없음.
        """
        from ante.approval.errors import ApprovalError, ApprovalStatusConflictError

        assert ApprovalStatusConflictError.code == "APPROVAL_STATUS_CONFLICT"
        assert issubclass(ApprovalStatusConflictError, ApprovalError)
        assert issubclass(ApprovalStatusConflictError, ValueError)
        exc = ApprovalStatusConflictError(
            "appr-1",
            current_status="rejected",
            requested_action="reject",
        )
        assert getattr(exc, "code", None) == "APPROVAL_STATUS_CONFLICT"
        assert exc.approval_id == "appr-1"
        assert exc.current_status == "rejected"
        assert exc.requested_action == "reject"

    # ─── #1814 Member state-conflict typed code ────────────────────

    def test_r3_member_state_conflict_error_code(self) -> None:
        """#1814: ``MemberStateConflictError.code == "MEMBER_STATE_CONFLICT"``.

        ``MemberError`` + ``ValueError`` 다중상속 보존 — #1805
        ``MemberNotFoundError`` 패턴 1:1 미러. 기존 ``except (ValueError,
        PermissionError)`` caller (CLI member suspend/reactivate line
        657/692 generic fallback) 회귀 없음.
        """
        from ante.member.errors import MemberError, MemberStateConflictError

        assert MemberStateConflictError.code == "MEMBER_STATE_CONFLICT"
        assert issubclass(MemberStateConflictError, MemberError)
        assert issubclass(MemberStateConflictError, ValueError)
        exc = MemberStateConflictError(
            "mbr-1",
            current_status="suspended",
            requested_action="suspend",
        )
        assert getattr(exc, "code", None) == "MEMBER_STATE_CONFLICT"
        assert exc.member_id == "mbr-1"
        assert exc.current_status == "suspended"
        assert exc.requested_action == "suspend"


# ════════════════════════════════════════════════════════════════════
# 카테고리 2 — service-layer typed raise 검증. CLI/IPC 표면이 typed
# 코드를 surface 하려면 service 가 typed exception 을 raise 해야 한다.
# fixture-light 단위 테스트로 service 를 직접 호출해 raise type 회귀를
# 막는다 (Group A ``TestServiceLayerTypedRaise`` 동형 패턴).
# ════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
class TestServiceLayerTypedRaise:
    """service-layer 가 state-conflict 를 typed exception 으로 raise."""

    # ─── R1 #1812 account.suspend(SUSPENDED) → AccountAlreadySuspendedError ─

    async def test_r1_account_service_suspend_already_suspended_raises_typed(
        self, tmp_path: Path
    ) -> None:
        """#1812: ``AccountService.suspend(<SUSPENDED-account>)`` →
        ``AccountAlreadySuspendedError`` (code ``"ACCOUNT_ALREADY_SUSPENDED"``).

        IPC envelope 이 ``getattr(e, "code", ...)`` 로 안정 코드를 surface
        하려면 service-layer 가 typed exception 을 raise 해야 한다. 본
        테스트는 service 의 typed raise 자체를 lock 해 #1813 ``approve``
        / #1814 ``suspend`` 와 형제 invariant 를 보장한다.
        """
        from decimal import Decimal

        from ante.account.errors import AccountAlreadySuspendedError
        from ante.account.models import (
            Account,
            AccountStatus,
            TradingMode,
        )
        from ante.account.service import AccountService
        from ante.core.database import Database
        from ante.eventbus import EventBus

        db_path = tmp_path / "test.db"
        db = Database(str(db_path))
        await db.connect()
        try:
            eventbus = EventBus()
            service = AccountService(db, eventbus=eventbus)
            await service.initialize()

            # ACTIVE 계좌 생성 → suspend × 2 시 typed raise.
            acct = Account(
                account_id="acc-grp-q",
                name="Group Q Test",
                exchange="TEST",
                currency="KRW",
                timezone="Asia/Seoul",
                trading_hours_start="00:00",
                trading_hours_end="23:59",
                trading_mode=TradingMode.VIRTUAL,
                broker_type="test",
                credentials={"app_key": "x", "app_secret": "y"},
                broker_config={},
                buy_commission_rate=Decimal("0"),
                sell_commission_rate=Decimal("0"),
                market_order_reserve_buffer_rate=Decimal("0"),
            )
            await service.create(acct)
            await service.suspend(
                "acc-grp-q",
                reason="첫 정지",
                suspended_by="system",
            )
            refreshed = await service.get("acc-grp-q")
            assert refreshed.status == AccountStatus.SUSPENDED

            with pytest.raises(AccountAlreadySuspendedError) as excinfo:
                await service.suspend(
                    "acc-grp-q",
                    reason="재정지 시도",
                    suspended_by="system",
                )
            assert getattr(excinfo.value, "code", None) == "ACCOUNT_ALREADY_SUSPENDED"
        finally:
            await db.close()

    # ─── R2 #1813 approval.reject(REJECTED) → ApprovalStatusConflictError ──

    async def test_r2_approval_service_reject_already_rejected_raises_typed(
        self, tmp_path: Path
    ) -> None:
        """#1813: ``ApprovalService.reject(<REJECTED-approval>)`` →
        ``ApprovalStatusConflictError`` (code ``"APPROVAL_STATUS_CONFLICT"``).

        IPC envelope 이 typed code 를 surface 하려면 service-layer 가 typed
        exception 을 raise 해야 한다. Group A #1798
        ``cancel_invalid_type_request`` 동형 패턴.
        """
        from ante.approval.errors import ApprovalStatusConflictError
        from ante.approval.models import ApprovalType
        from ante.approval.service import ApprovalService
        from ante.core.database import Database
        from ante.eventbus import EventBus

        async def _noop_executor(params: dict) -> None:
            return None

        db_path = tmp_path / "test.db"
        db = Database(str(db_path))
        await db.connect()
        try:
            eventbus = EventBus()
            executors = {t.value: _noop_executor for t in ApprovalType}
            service = ApprovalService(db, eventbus=eventbus, executors=executors)
            await service.initialize()

            req = await service.create(
                type="budget_change",
                requester="agent",
                title="Group Q 테스트",
                params={"account_id": "acc-grp-q"},
            )
            await service.reject(req.id, reject_reason="첫 거절")

            with pytest.raises(ApprovalStatusConflictError) as excinfo:
                await service.reject(req.id, reject_reason="재거절 시도")
            assert getattr(excinfo.value, "code", None) == "APPROVAL_STATUS_CONFLICT"
            assert excinfo.value.approval_id == req.id
            assert excinfo.value.requested_action == "reject"
            # ``ValueError`` 다중상속 회귀 보호 — 기존 ``except ValueError``
            # caller 가 동일하게 잡을 수 있어야 한다.
            assert isinstance(excinfo.value, ValueError)
        finally:
            await db.close()

    async def test_r2b_approval_service_approve_already_approved_raises_typed(
        self, tmp_path: Path
    ) -> None:
        """#1813: ``ApprovalService.approve(<APPROVED-approval>)`` →
        ``ApprovalStatusConflictError`` (대칭 분기 — ``reject`` 1:1 미러).
        """
        from ante.approval.errors import ApprovalStatusConflictError
        from ante.approval.models import ApprovalType
        from ante.approval.service import ApprovalService
        from ante.core.database import Database
        from ante.eventbus import EventBus

        async def _noop_executor(params: dict) -> None:
            return None

        db_path = tmp_path / "test.db"
        db = Database(str(db_path))
        await db.connect()
        try:
            eventbus = EventBus()
            executors = {t.value: _noop_executor for t in ApprovalType}
            service = ApprovalService(db, eventbus=eventbus, executors=executors)
            await service.initialize()

            req = await service.create(
                type="budget_change",
                requester="agent",
                title="Group Q approve 테스트",
                params={"account_id": "acc-grp-q"},
            )
            await service.approve(req.id)

            with pytest.raises(ApprovalStatusConflictError) as excinfo:
                await service.approve(req.id)
            assert getattr(excinfo.value, "code", None) == "APPROVAL_STATUS_CONFLICT"
            assert excinfo.value.requested_action == "approve"
        finally:
            await db.close()

    # ─── R3 #1814 member.suspend(SUSPENDED) → MemberStateConflictError ─────

    async def test_r3_member_service_suspend_already_suspended_raises_typed(
        self, tmp_path: Path
    ) -> None:
        """#1814: ``MemberService.suspend(<SUSPENDED-member>)`` →
        ``MemberStateConflictError`` (code ``"MEMBER_STATE_CONFLICT"``).

        이전 (#1814 이전): ``_assert_status`` 가 ``PermissionError`` 를 raise
        해 IPC envelope 이 ``EXECUTION_ERROR`` 폴백 (or unmapped) 로 떨어졌다.
        Group Q sweep 은 ``suspend``/``reactivate`` state 체크를 typed
        ``MemberStateConflictError`` 로 좁힌다.
        """
        from ante.core.database import Database
        from ante.eventbus import EventBus
        from ante.member.errors import MemberStateConflictError
        from ante.member.models import MemberType
        from ante.member.service import MemberService

        db_path = tmp_path / "test.db"
        db = Database(str(db_path))
        await db.connect()
        try:
            eventbus = EventBus()
            service = MemberService(db, eventbus=eventbus)
            await service.initialize()

            # master + ACTIVE agent 생성 → suspend 1회 후 재정지 시 typed.
            await service.bootstrap_master("owner", "pass1234")
            await service.register(
                "agent-grp-q", MemberType.AGENT, registered_by="owner"
            )
            await service.suspend("agent-grp-q", suspended_by="owner")

            with pytest.raises(MemberStateConflictError) as excinfo:
                await service.suspend("agent-grp-q", suspended_by="owner")
            assert getattr(excinfo.value, "code", None) == "MEMBER_STATE_CONFLICT"
            assert excinfo.value.member_id == "agent-grp-q"
            assert excinfo.value.requested_action == "suspend"
            # ``ValueError`` 다중상속 회귀 보호.
            assert isinstance(excinfo.value, ValueError)
        finally:
            await db.close()


# ════════════════════════════════════════════════════════════════════
# 카테고리 3 — subprocess CLI E2E. member CLI 는 ``_create_service()``
# 직접 호출 경로라 server fixture 없이 ``ante init`` → ``member
# register`` → ``member suspend`` × 2 로 R3 envelope 을 직접 검증할 수
# 있다 (R1/R2 는 IPC-only 라 카테고리 2 service-layer 검증으로 대체).
# ════════════════════════════════════════════════════════════════════


class TestMemberSuspendStateConflictTypedCode:
    """R3 subprocess E2E — ``ante member suspend <SUSPENDED> --format
    json`` → exit 1, code=``MEMBER_STATE_CONFLICT``.

    Group P #1805 ``member suspend <missing>`` → ``MEMBER_NOT_FOUND`` 와
    형제 패턴이지만 envelope code 로 의미를 구분 (missing vs state-conflict).
    """

    def test_suspend_already_suspended_emits_typed_state_conflict(
        self, initialized_config: tuple[Path, str, str]
    ) -> None:
        config_dir, token, key = initialized_config

        # 1) member register — master 가 agent 를 등록 (text 출력 OK).
        register_result = _run_cli(
            config_dir,
            ["member", "register", "--id", "agent-grp-q", "--type", "agent"],
            token=token,
            encryption_key=key,
        )
        assert register_result.returncode == 0, (
            f"register 실패: exit={register_result.returncode}\n"
            f"stdout={register_result.stdout}\nstderr={register_result.stderr}"
        )

        # 2) 첫 suspend — 정상 종료.
        first_suspend = _run_cli(
            config_dir,
            ["member", "suspend", "agent-grp-q"],
            token=token,
            encryption_key=key,
        )
        assert first_suspend.returncode == 0, (
            f"첫 suspend 실패: exit={first_suspend.returncode}\n"
            f"stdout={first_suspend.stdout}\nstderr={first_suspend.stderr}"
        )

        # 3) 재정지 시도 — typed envelope code 검증.
        second_suspend = _run_cli(
            config_dir,
            ["member", "suspend", "agent-grp-q"],
            token=token,
            encryption_key=key,
        )
        assert second_suspend.returncode == 1, (
            f"exit={second_suspend.returncode}\n"
            f"stdout={second_suspend.stdout}\nstderr={second_suspend.stderr}"
        )
        assert "Traceback" not in second_suspend.stderr, (
            f"stderr 에 traceback 노출: {second_suspend.stderr!r}"
        )
        payload = _parse_json_last(second_suspend.stdout)
        assert payload.get("status") == "error", payload
        assert payload.get("code") == "MEMBER_STATE_CONFLICT", payload


class TestMemberReactivateStateConflictTypedCode:
    """R3 보조 — ``ante member reactivate <ACTIVE> --format json`` →
    exit 1, code=``MEMBER_STATE_CONFLICT`` (대칭 분기, ``suspend`` 1:1
    미러).
    """

    def test_reactivate_already_active_emits_typed_state_conflict(
        self, initialized_config: tuple[Path, str, str]
    ) -> None:
        config_dir, token, key = initialized_config

        # 1) member register — ACTIVE 상태로 등록.
        register_result = _run_cli(
            config_dir,
            ["member", "register", "--id", "agent-grp-q-2", "--type", "agent"],
            token=token,
            encryption_key=key,
        )
        assert register_result.returncode == 0, (
            f"register 실패: exit={register_result.returncode}\n"
            f"stdout={register_result.stdout}\nstderr={register_result.stderr}"
        )

        # 2) reactivate 시도 — ACTIVE 상태에서 typed envelope code 검증.
        reactivate_result = _run_cli(
            config_dir,
            ["member", "reactivate", "agent-grp-q-2"],
            token=token,
            encryption_key=key,
        )
        assert reactivate_result.returncode == 1, (
            f"exit={reactivate_result.returncode}\n"
            f"stdout={reactivate_result.stdout}\nstderr={reactivate_result.stderr}"
        )
        assert "Traceback" not in reactivate_result.stderr, (
            f"stderr 에 traceback 노출: {reactivate_result.stderr!r}"
        )
        payload = _parse_json_last(reactivate_result.stdout)
        assert payload.get("status") == "error", payload
        assert payload.get("code") == "MEMBER_STATE_CONFLICT", payload
