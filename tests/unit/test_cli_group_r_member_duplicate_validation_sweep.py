"""Group R member duplicate+validation typed code sweep (#1806 / #1807).

2 oracle A7 issue sweep — member 도메인의 duplicate / recovery credential
validation 거부가 안정 typed code envelope 을 surface 함을 verify 한다
(Group P #1805 missing-resource / Group Q #1814 state-conflict sweep 동형
패턴).

R-case 매트릭스:
  R1 #1807 ``ante member register --id <existing-id> --type human --format json``
         → exit 1, code=``MEMBER_ALREADY_EXISTS``
         (subprocess E2E — ``ante init`` 으로 master 생성 후 동일 ``member_id``
         재등록을 시도)
  R2a #1806 ``ante member reset-password --recovery-key <wrong> ...
         --format json`` → exit 1, code=``MEMBER_INVALID_RECOVERY_CREDENTIAL``
         (subprocess E2E — ``ante init`` 후 잘못된 recovery key 전달)
  R2b #1806 ``ante member regenerate-recovery-key --password-env <wrong> ...
         --format json`` → exit 1, code=``MEMBER_INVALID_RECOVERY_CREDENTIAL``
         (subprocess E2E — ``ante init`` 후 잘못된 현재 패스워드 전달)

이전 (#1806/#1807 이전): 3 표면 모두 generic exception (``ValueError`` /
``PermissionError``) 으로 raise 되어 CLI envelope ``code`` 가 빈 문자열로
떨어졌다. Group R sweep 은 typed exception class
(``MemberAlreadyExistsError`` / ``MemberInvalidRecoveryCredentialError``,
``.code`` 클래스 속성) 를 도입하고 service-layer raise 를 typed 로 좁혀,
CLI ``except <Typed>`` 분기가 ``fmt.error(..., code=<Typed>.code)`` 로
안정 코드를 surface 한다.

회귀 보호 매트릭스:
- ``ValueError`` 다중상속 보존: ``MemberAlreadyExistsError`` /
  ``MemberInvalidRecoveryCredentialError`` 가 ``ValueError`` 다중상속을
  유지해 기존 ``except (ValueError, PermissionError)`` caller (CLI
  ``register`` / ``reset-password`` / ``regenerate-recovery-key`` generic
  fallback) 회귀 없음. ``test_cli_member_non_interactive.py`` 의
  PermissionError mock 시나리오는 service 가 mock 되므로 영향 없음.
- ``.code`` 누락 폴백 lock: typed exception class 가 인스턴스에서도
  ``getattr(exc, "code", None)`` 이 안정 코드를 반환해야 한다.
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
_SUBPROCESS_TIMEOUT_S = 30.0


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _clean_env(
    config_dir: Path,
    *,
    encryption_key: str | None = None,
    token: str | None = None,
    extra: dict[str, str] | None = None,
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
    if extra:
        env.update(extra)
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
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """``ante --format json <args>`` 를 subprocess 로 실행."""
    env = _clean_env(
        config_dir,
        encryption_key=encryption_key,
        token=token,
        extra=extra_env,
    )
    return subprocess.run(
        [sys.executable, "-m", "ante", "--format", "json", *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=_SUBPROCESS_TIMEOUT_S,
    )


def _run_init(config_dir: Path, encryption_key: str) -> tuple[str, str, str, str]:
    """``ante init`` 후 (member_id, token, recovery_key, encryption_key) 반환."""
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
            "GroupR",
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
    member_id = payload.get("member_id")
    recovery_key = payload.get("recovery_key")
    assert token, f"init 출력에 token 없음: {payload}"
    assert member_id, f"init 출력에 member_id 없음: {payload}"
    assert recovery_key, f"init 출력에 recovery_key 없음: {payload}"
    return member_id, token, recovery_key, encryption_key


@pytest.fixture
def initialized_config(tmp_path: Path) -> tuple[Path, str, str, str]:
    """``ante init`` 을 완료한 (config_dir, member_id, token, encryption_key)."""
    config_dir = tmp_path / "config"
    key = Fernet.generate_key().decode()
    member_id, token, _recovery_key, _key = _run_init(config_dir, key)
    return config_dir, member_id, token, key


@pytest.fixture
def initialized_config_with_recovery_key(
    tmp_path: Path,
) -> tuple[Path, str, str, str, str]:
    """``ante init`` 완료 + recovery_key 까지 노출 — R2 시나리오용."""
    config_dir = tmp_path / "config"
    key = Fernet.generate_key().decode()
    member_id, token, recovery_key, _key = _run_init(config_dir, key)
    return config_dir, member_id, token, recovery_key, key


# ════════════════════════════════════════════════════════════════════
# 카테고리 1 — typed exception class ``code`` 속성 lock. CLI 가 typed
# 코드를 surface 하려면 typed exception 이 SCREAMING_SNAKE_CASE 안정
# 코드를 ``.code`` 클래스 속성으로 보유해야 한다 (Group Q #1812-#1814
# ``TestTypedExceptionCodeAttributes`` 동형 패턴).
# ════════════════════════════════════════════════════════════════════


class TestTypedExceptionCodeAttributes:
    """R1-R2 lock: typed exception class ``code`` 속성 매핑."""

    def test_r1_member_already_exists_error_code(self) -> None:
        """#1807: ``MemberAlreadyExistsError.code == "MEMBER_ALREADY_EXISTS"``.

        ``MemberError`` + ``ValueError`` 다중상속 보존 — #1805
        ``MemberNotFoundError`` 패턴 1:1 미러. 기존 ``except ValueError``
        caller (CLI ``register`` line 521 generic fallback) 회귀 없음.
        """
        from ante.member.errors import MemberAlreadyExistsError, MemberError

        assert MemberAlreadyExistsError.code == "MEMBER_ALREADY_EXISTS"
        assert issubclass(MemberAlreadyExistsError, MemberError)
        assert issubclass(MemberAlreadyExistsError, ValueError)
        exc = MemberAlreadyExistsError("agent-dup")
        assert getattr(exc, "code", None) == "MEMBER_ALREADY_EXISTS"
        assert exc.member_id == "agent-dup"
        # 메시지 호환성 — 기존 ``"이미 존재하는"`` 부분 문자열 유지.
        assert "이미 존재하는" in str(exc)
        assert "agent-dup" in str(exc)
        # ``ValueError`` 다중상속 회귀 보호.
        assert isinstance(exc, ValueError)

    def test_r2_member_invalid_recovery_credential_error_code(self) -> None:
        """#1806: ``MemberInvalidRecoveryCredentialError.code ==
        "MEMBER_INVALID_RECOVERY_CREDENTIAL"``.

        ``MemberError`` + ``ValueError`` 다중상속 보존 — 기존
        ``except (ValueError, PermissionError)`` caller (CLI
        ``reset-password`` / ``regenerate-recovery-key`` generic fallback)
        가 ValueError 분기로 회귀 없이 동일하게 잡힌다.
        """
        from ante.member.errors import (
            MemberError,
            MemberInvalidRecoveryCredentialError,
        )

        assert (
            MemberInvalidRecoveryCredentialError.code
            == "MEMBER_INVALID_RECOVERY_CREDENTIAL"
        )
        assert issubclass(MemberInvalidRecoveryCredentialError, MemberError)
        assert issubclass(MemberInvalidRecoveryCredentialError, ValueError)
        exc = MemberInvalidRecoveryCredentialError("유효하지 않은 recovery key")
        assert getattr(exc, "code", None) == "MEMBER_INVALID_RECOVERY_CREDENTIAL"
        assert "유효하지 않은 recovery key" in str(exc)
        # ``ValueError`` 다중상속 회귀 보호.
        assert isinstance(exc, ValueError)


# ════════════════════════════════════════════════════════════════════
# 카테고리 2 — service-layer typed raise 검증. CLI 표면이 typed 코드를
# surface 하려면 service 가 typed exception 을 raise 해야 한다 (Group Q
# ``TestServiceLayerTypedRaise`` 동형 패턴).
# ════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
class TestServiceLayerTypedRaise:
    """service-layer 가 duplicate / invalid credential 을 typed raise."""

    async def test_r1_register_duplicate_raises_typed(self, tmp_path: Path) -> None:
        """#1807: ``MemberService.register(<existing>)`` →
        ``MemberAlreadyExistsError`` (code ``"MEMBER_ALREADY_EXISTS"``).

        ValueError 다중상속이라 기존 ``except ValueError`` caller (CLI
        ``register`` line 521 generic fallback) 가 동일하게 잡힌다.
        """
        from ante.core.database import Database
        from ante.eventbus import EventBus
        from ante.member.errors import MemberAlreadyExistsError
        from ante.member.models import MemberType
        from ante.member.service import MemberService

        db_path = tmp_path / "test.db"
        db = Database(str(db_path))
        await db.connect()
        try:
            eventbus = EventBus()
            service = MemberService(db, eventbus=eventbus)
            await service.initialize()

            # #2294: register 는 무조건 master actor 를 요구한다.
            await service.bootstrap_master("owner", "pass1234")
            await service.register(
                "agent-grp-r", MemberType.AGENT, registered_by="owner"
            )

            with pytest.raises(MemberAlreadyExistsError) as excinfo:
                await service.register(
                    "agent-grp-r", MemberType.AGENT, registered_by="owner"
                )
            assert getattr(excinfo.value, "code", None) == "MEMBER_ALREADY_EXISTS"
            assert excinfo.value.member_id == "agent-grp-r"
            # ``ValueError`` 다중상속 회귀 보호 — 기존 ``except ValueError``
            # caller 가 동일하게 잡을 수 있어야 한다.
            assert isinstance(excinfo.value, ValueError)
        finally:
            await db.close()

    async def test_r2a_reset_password_invalid_recovery_key_raises_typed(
        self, tmp_path: Path
    ) -> None:
        """#1806: ``MemberService.reset_password(<wrong-recovery-key>)`` →
        ``MemberInvalidRecoveryCredentialError`` (code
        ``"MEMBER_INVALID_RECOVERY_CREDENTIAL"``).
        """
        from ante.core.database import Database
        from ante.eventbus import EventBus
        from ante.member.errors import MemberInvalidRecoveryCredentialError
        from ante.member.service import MemberService

        db_path = tmp_path / "test.db"
        db = Database(str(db_path))
        await db.connect()
        try:
            eventbus = EventBus()
            service = MemberService(db, eventbus=eventbus)
            await service.initialize()

            # master 생성 (human + recovery_key 보유).
            await service.bootstrap_master("owner", "pass1234")

            with pytest.raises(MemberInvalidRecoveryCredentialError) as excinfo:
                await service.reset_password(
                    "owner",
                    "ANTE-RK-WRONG-WRONG-WRONG",
                    "new-pass-1234",
                )
            assert (
                getattr(excinfo.value, "code", None)
                == "MEMBER_INVALID_RECOVERY_CREDENTIAL"
            )
            assert "유효하지 않은 recovery key" in str(excinfo.value)
            # ``ValueError`` 다중상속 회귀 보호.
            assert isinstance(excinfo.value, ValueError)
        finally:
            await db.close()

    async def test_r2b_regenerate_recovery_key_invalid_password_raises_typed(
        self, tmp_path: Path
    ) -> None:
        """#1806: ``MemberService.regenerate_recovery_key(<wrong-password>)`` →
        ``MemberInvalidRecoveryCredentialError`` (대칭 분기 — ``reset_password``
        1:1 미러).
        """
        from ante.core.database import Database
        from ante.eventbus import EventBus
        from ante.member.errors import MemberInvalidRecoveryCredentialError
        from ante.member.service import MemberService

        db_path = tmp_path / "test.db"
        db = Database(str(db_path))
        await db.connect()
        try:
            eventbus = EventBus()
            service = MemberService(db, eventbus=eventbus)
            await service.initialize()

            await service.bootstrap_master("owner", "pass1234")

            with pytest.raises(MemberInvalidRecoveryCredentialError) as excinfo:
                await service.regenerate_recovery_key("owner", "wrong-password")
            assert (
                getattr(excinfo.value, "code", None)
                == "MEMBER_INVALID_RECOVERY_CREDENTIAL"
            )
            assert "현재 패스워드가 일치하지 않습니다" in str(excinfo.value)
            assert isinstance(excinfo.value, ValueError)
        finally:
            await db.close()


# ════════════════════════════════════════════════════════════════════
# 카테고리 3 — subprocess CLI E2E. ``ante init`` → R1/R2 표면 호출 →
# envelope code 직접 검증 (Group Q ``TestMemberSuspendStateConflictTypedCode``
# 동형 패턴).
# ════════════════════════════════════════════════════════════════════


class TestMemberRegisterDuplicateTypedCode:
    """R1 subprocess E2E — ``ante member register --id <existing> --type
    human --format json`` → exit 1, code=``MEMBER_ALREADY_EXISTS``.

    ``ante init`` 으로 master ``GroupR`` 가 생성된 뒤 동일 member_id 를
    재등록하면 service ``register`` 가 ``MemberAlreadyExistsError`` 를
    raise 하고 CLI ``register`` 의 typed catch 분기가 안정 코드 envelope
    으로 surface 한다.
    """

    def test_register_duplicate_emits_typed_already_exists(
        self, initialized_config: tuple[Path, str, str, str]
    ) -> None:
        config_dir, master_id, token, key = initialized_config

        # master 와 동일 ``member_id`` 로 재등록 시도.
        result = _run_cli(
            config_dir,
            ["member", "register", "--id", master_id, "--type", "human"],
            token=token,
            encryption_key=key,
        )
        assert result.returncode == 1, (
            f"exit={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
        )
        assert "Traceback" not in result.stderr, (
            f"stderr 에 traceback 노출: {result.stderr!r}"
        )
        payload = _parse_json_last(result.stdout)
        assert payload.get("status") == "error", payload
        assert payload.get("code") == "MEMBER_ALREADY_EXISTS", payload
        # 메시지에 충돌 member_id 가 포함되어 자동화 호출자가 사유를 확인
        # 할 수 있어야 한다.
        assert master_id in payload.get("message", ""), payload


class TestMemberResetPasswordInvalidRecoveryKeyTypedCode:
    """R2a subprocess E2E — ``ante member reset-password --recovery-key
    <wrong> --format json`` → exit 1, code=``MEMBER_INVALID_RECOVERY_CREDENTIAL``.

    ``ante init`` 후 잘못된 recovery key 를 전달하면 ``RecoveryKeyManager.
    reset_password`` 가 ``MemberInvalidRecoveryCredentialError`` 를 raise
    하고 CLI typed catch 분기가 안정 코드 envelope 으로 surface 한다.
    """

    def test_reset_password_wrong_recovery_key_emits_typed_invalid_credential(
        self, initialized_config: tuple[Path, str, str, str]
    ) -> None:
        config_dir, _master_id, _token, key = initialized_config

        # --new-password-env 채널 — env 에 새 패스워드 노출.
        result = _run_cli(
            config_dir,
            [
                "member",
                "reset-password",
                "--recovery-key",
                "ANTE-RK-WRONG-WRONG-WRONG",
                "--new-password-env",
                "ANTE_GRP_R_NEW_PWD",
            ],
            encryption_key=key,
            extra_env={"ANTE_GRP_R_NEW_PWD": "brand-new-pass-1234"},
        )
        assert result.returncode == 1, (
            f"exit={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
        )
        assert "Traceback" not in result.stderr, (
            f"stderr 에 traceback 노출: {result.stderr!r}"
        )
        payload = _parse_json_last(result.stdout)
        assert payload.get("status") == "error", payload
        assert payload.get("code") == "MEMBER_INVALID_RECOVERY_CREDENTIAL", payload


class TestMemberRegenerateRecoveryKeyInvalidPasswordTypedCode:
    """R2b subprocess E2E — ``ante member regenerate-recovery-key
    --password-env <wrong> --format json`` → exit 1,
    code=``MEMBER_INVALID_RECOVERY_CREDENTIAL`` (대칭 분기, ``reset-password``
    1:1 미러).
    """

    def test_regenerate_recovery_key_wrong_password_emits_typed_invalid_credential(
        self, initialized_config: tuple[Path, str, str, str]
    ) -> None:
        config_dir, _master_id, _token, key = initialized_config

        result = _run_cli(
            config_dir,
            [
                "member",
                "regenerate-recovery-key",
                "--password-env",
                "ANTE_GRP_R_CURR_PWD",
            ],
            encryption_key=key,
            extra_env={"ANTE_GRP_R_CURR_PWD": "absolutely-wrong-password"},
        )
        assert result.returncode == 1, (
            f"exit={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
        )
        assert "Traceback" not in result.stderr, (
            f"stderr 에 traceback 노출: {result.stderr!r}"
        )
        payload = _parse_json_last(result.stdout)
        assert payload.get("status") == "error", payload
        assert payload.get("code") == "MEMBER_INVALID_RECOVERY_CREDENTIAL", payload


class TestMemberResetPasswordValidRecoveryKeyHappyPath:
    """R2 happy-path 회귀 보호 — 올바른 recovery key 를 전달하면 reset
    이 성공해야 한다 (typed raise 가 정상 경로를 회귀시키지 않음을 보장).
    """

    def test_reset_password_valid_recovery_key_succeeds(
        self,
        initialized_config_with_recovery_key: tuple[Path, str, str, str, str],
    ) -> None:
        config_dir, _master_id, _token, recovery_key, key = (
            initialized_config_with_recovery_key
        )

        result = _run_cli(
            config_dir,
            [
                "member",
                "reset-password",
                "--recovery-key",
                recovery_key,
                "--new-password-env",
                "ANTE_GRP_R_NEW_PWD_OK",
            ],
            encryption_key=key,
            extra_env={"ANTE_GRP_R_NEW_PWD_OK": "brand-new-pass-1234"},
        )
        assert result.returncode == 0, (
            f"happy-path 실패: exit={result.returncode}\n"
            f"stdout={result.stdout}\nstderr={result.stderr}"
        )
