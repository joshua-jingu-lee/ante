"""ante init — 비대화형 최소 초기 설정."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import click

from ante.account.crypto import _validate_fernet_key
from ante.cli.commands._password import generate_password
from ante.cli.formatter import OutputFormatter
from ante.cli.main import get_formatter


def _fail(fmt: OutputFormatter, message: str, code: str = "") -> None:
    """JSON/text 모두에서 구조화된 에러 출력 후 exit 1."""
    fmt.error(message, code=code)
    sys.exit(1)


_SYSTEM_TOML_FILENAME = "system.toml"
_SECRETS_ENV_FILENAME = "secrets.env"
_DB_FILENAME = "db/ante.db"

SYSTEM_TOML_TEMPLATE = """\
# Ante 시스템 설정

[system]
log_level = "INFO"
timezone = "Asia/Seoul"

[db]
path = "{db_path}"

[runtime]
# `config_dir` 기준 상대 경로. PID/IPC socket 위치
# (docs/specs/config/03-design-decisions.md 200-202).
pid_path = "run/ante.pid"
socket_path = "run/ante.sock"
"""

_ENCRYPTION_KEY_NAME = "ANTE_DB_ENCRYPTION_KEY"

SECRETS_ENV_TEMPLATE = """\
# Ante 비밀값 설정
# 환경변수가 이 파일보다 우선합니다.

# DB credentials Fernet 마스터 키. `ante init`이 자동 생성합니다.
# 수동으로 교체하려면 cryptography.fernet.Fernet.generate_key() 출력만 사용하세요.
{encryption_key_line}

# 텔레그램 알림 (선택) - 사용 시 주석 해제하고 값 채우기
# TELEGRAM_BOT_TOKEN=
# TELEGRAM_CHAT_ID=
"""


def _generate_db_encryption_key() -> str:
    """신규 Fernet 마스터 키를 생성한다."""
    from cryptography.fernet import Fernet

    return Fernet.generate_key().decode()


def _resolve_effective_key(
    env_value: str | None, file_value: str | None
) -> tuple[str, bool, bool]:
    """env/file의 키 분류 결과로부터 effective key와 파일 상태 플래그를 도출한다."""
    env_valid = _validate_fernet_key(env_value)
    file_valid = _validate_fernet_key(file_value)
    file_present_invalid = (file_value is not None) and (not file_valid)

    if env_valid:
        assert env_value is not None
        if file_valid and file_value == env_value:
            return env_value, False, False
        return env_value, file_present_invalid, True

    if file_valid:
        assert file_value is not None
        return file_value, False, False

    new_key = _generate_db_encryption_key()
    return new_key, file_present_invalid, True


def _read_existing_encryption_key_line(secrets_env_path: Path) -> str | None:
    """secrets.env에서 ANTE_DB_ENCRYPTION_KEY 라인의 값만 추출."""
    if not secrets_env_path.exists():
        return None
    last: str | None = None
    for raw_line in secrets_env_path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key.strip() != _ENCRYPTION_KEY_NAME:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        last = value
    return last


def _atomic_backup_secrets_env(secrets_env_path: Path) -> Path:
    """기존 secrets.env 파일을 0600 권한으로 원자적 백업한다."""
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    backup_path = secrets_env_path.parent / f"secrets.env.bak.{ts}"
    content = secrets_env_path.read_bytes()
    fd, tmp_path = tempfile.mkstemp(
        prefix=".secrets.env.bak.", dir=str(secrets_env_path.parent)
    )
    try:
        os.write(fd, content)
        os.fchmod(fd, 0o600)
    finally:
        os.close(fd)
    os.rename(tmp_path, backup_path)
    return backup_path


def _write_encryption_key_into_secrets_env(
    secrets_env_path: Path, effective_key: str
) -> None:
    """secrets.env에 ANTE_DB_ENCRYPTION_KEY 라인을 갱신/추가한다."""
    new_line = f"{_ENCRYPTION_KEY_NAME}={effective_key}"

    if not secrets_env_path.exists():
        secrets_env_path.parent.mkdir(parents=True, exist_ok=True)
        content = SECRETS_ENV_TEMPLATE.format(encryption_key_line=new_line)
        fd, tmp_path = tempfile.mkstemp(
            prefix=".secrets.env.", dir=str(secrets_env_path.parent)
        )
        try:
            os.write(fd, content.encode())
            os.fchmod(fd, 0o600)
        finally:
            os.close(fd)
        os.rename(tmp_path, secrets_env_path)
        return

    existing = secrets_env_path.read_text()
    lines = existing.splitlines()
    last_idx: int | None = None
    for i, raw_line in enumerate(lines):
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped:
            continue
        key, _, _ = stripped.partition("=")
        if key.strip() == _ENCRYPTION_KEY_NAME:
            last_idx = i

    if last_idx is None:
        lines.append(new_line)
    else:
        lines[last_idx] = new_line

    trailing_newline = "\n" if existing.endswith("\n") else ""
    new_content = "\n".join(lines) + trailing_newline

    fd, tmp_path = tempfile.mkstemp(
        prefix=".secrets.env.", dir=str(secrets_env_path.parent)
    )
    try:
        os.write(fd, new_content.encode())
        os.fchmod(fd, 0o600)
    finally:
        os.close(fd)
    os.rename(tmp_path, secrets_env_path)


def _ensure_encryption_key_in_secrets_env(secrets_env_path: Path) -> str:
    """ANTE_DB_ENCRYPTION_KEY 5-state idempotent path."""
    env_value = os.environ.get(_ENCRYPTION_KEY_NAME)
    file_value = _read_existing_encryption_key_line(secrets_env_path)

    effective_key, file_was_invalid_replaced, file_was_synced_from_env = (
        _resolve_effective_key(env_value, file_value)
    )

    needs_backup = file_was_invalid_replaced and bool(file_value)
    needs_write = file_was_synced_from_env or (
        not _validate_fernet_key(file_value)
        and _validate_fernet_key(effective_key)
        and file_value != effective_key
    )

    if needs_backup and secrets_env_path.exists():
        _atomic_backup_secrets_env(secrets_env_path)

    if needs_write:
        _write_encryption_key_into_secrets_env(secrets_env_path, effective_key)

    return effective_key


def _run(coro):
    """동기 CLI에서 async 함수 실행."""
    return asyncio.run(coro)


def _resolve_config_path(ctx: click.Context, target_dir: str | None) -> Path:
    """init 대상 디렉토리 결정."""
    if target_dir:
        return Path(target_dir)

    obj = ctx.obj or {}
    raw_override = obj.get("config_dir")
    if raw_override is not None:
        return raw_override if isinstance(raw_override, Path) else Path(raw_override)

    env_dir = os.environ.get("ANTE_CONFIG_DIR")
    if env_dir:
        return Path(env_dir)

    return Path.home() / ".config" / "ante"


def _expected_artifacts(config_path: Path) -> dict[str, Path]:
    return {
        "system.toml": config_path / _SYSTEM_TOML_FILENAME,
        "secrets.env": config_path / _SECRETS_ENV_FILENAME,
        "db/ante.db": config_path / _DB_FILENAME,
    }


def _all_artifacts_exist(config_path: Path) -> bool:
    return all(p.exists() for p in _expected_artifacts(config_path).values())


def _ensure_file(path: Path, template: str) -> bool:
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(template)
    return True


async def _master_exists_in_db(db_path: str) -> bool:
    """DB에 role='master' member row가 있는지 확인."""
    from ante.core.database import Database

    db = Database(db_path)
    try:
        await db.connect()
    except Exception:
        return False
    try:
        try:
            row = await db.fetch_one(
                "SELECT member_id FROM members WHERE role = ? LIMIT 1",
                ("master",),
            )
        except Exception:
            return False
        return row is not None
    finally:
        await db.close()


async def _test_account_state(
    db_path: str,
) -> Literal["active", "inactive", "missing"]:
    """default test account(account_id='test')의 3-state 판정."""
    from ante.core.database import Database

    db = Database(db_path)
    try:
        await db.connect()
    except Exception:
        return "missing"
    try:
        try:
            row = await db.fetch_one(
                "SELECT status FROM accounts WHERE account_id = ? LIMIT 1",
                ("test",),
            )
        except Exception:
            return "missing"
        if row is None:
            return "missing"
        status = row.get("status")
        return "active" if status == "active" else "inactive"
    finally:
        await db.close()


async def _bootstrap_master(
    db_path: str, member_id: str, name: str, password: str
) -> tuple[dict, str, str]:
    """MemberService를 통해 master 계정을 생성하고 토큰·복구키를 반환한다."""
    from ante.core.database import Database
    from ante.eventbus.bus import EventBus
    from ante.member.service import MemberService

    db = Database(db_path)
    await db.connect()
    try:
        eventbus = EventBus()
        service = MemberService(db, eventbus)
        await service.initialize()
        m, token, recovery_key = await service.bootstrap_master(
            member_id=member_id,
            password=password,
            name=name,
        )
        return (
            {
                "member_id": m.member_id,
                "name": m.name,
                "role": m.role,
                "emoji": m.emoji,
            },
            token,
            recovery_key,
        )
    finally:
        await db.close()


async def _create_test_account(db_path: str) -> dict[str, str]:
    """default test account 한 개를 생성한다."""
    from ante.account.service import AccountService
    from ante.core.database import Database
    from ante.eventbus.bus import EventBus

    db = Database(db_path)
    await db.connect()
    try:
        eventbus = EventBus()
        service = AccountService(db, eventbus)
        await service.initialize()
        account = await service.create_default_test_account()
        return {
            "account_id": account.account_id,
            "broker_type": account.broker_type,
            "exchange": account.exchange,
        }
    finally:
        await db.close()


def _emit_master_credentials_text(
    master_info: dict,
    password: str,
    token: str,
    recovery_key: str,
) -> None:
    """text 모드에서 master bootstrap 직후 비밀값을 stdout에 출력한다."""
    click.echo("\n── Master 계정 생성 완료 ──────────────────────")
    click.echo(f"  Member ID   : {master_info['member_id']}")
    click.echo(f"  이름        : {master_info['name']}")
    click.echo(f"  이모지      : {master_info['emoji']}")
    click.echo(f"\n  패스워드     : {password}")
    click.echo(f"  토큰         : {token}")
    click.echo(f"  Recovery Key : {recovery_key}")
    click.echo("\n  ⚠ 위 3개 값은 이 화면에만 표시됩니다. 안전한 곳에 보관하세요.")


def _emit_master_credentials_json_stderr(
    master_info: dict,
    password: str,
    token: str,
    recovery_key: str,
    config_path: Path,
) -> None:
    """JSON 모드 실패 경로 전용 복구 이벤트 (stderr 한 줄 JSON)."""
    click.echo(
        json.dumps(
            {
                "stage": "master_bootstrap_complete",
                **master_info,
                "password": password,
                "token": token,
                "recovery_key": recovery_key,
                "config_dir": str(config_path),
            },
            ensure_ascii=False,
            default=str,
        ),
        err=True,
    )


@click.command("init")
@click.option("--member-id", default="owner", show_default=True, help="master 멤버 ID")
@click.option("--name", default="Owner", show_default=True, help="master 표시 이름")
@click.option(
    "--dir",
    "target_dir",
    type=click.Path(),
    default=None,
    help="설정 디렉토리 경로 (기본: ~/.config/ante/)",
)
@click.pass_context
def init(
    ctx: click.Context,
    member_id: str,
    name: str,
    target_dir: str | None,
) -> None:
    """비대화형 최소 초기 설정.

    멱등성 (I4 — 파일 + master 레코드 기반 재진입):
    파일(3) + master row + test account row 5-state 가드로 재구성된다.
    모든 상태 완료 시 거부, 그 외 경로에서는 누락된 것만 생성한다.
    """
    fmt = get_formatter(ctx)
    config_path = _resolve_config_path(ctx, target_dir)

    artifacts = _expected_artifacts(config_path)
    all_files_exist = _all_artifacts_exist(config_path)
    db_path = artifacts["db/ante.db"]
    db_file_exists = db_path.exists()

    master_exists = False
    test_account_status: Literal["active", "inactive", "missing"] = "missing"
    if db_file_exists:
        master_exists = _run(_master_exists_in_db(str(db_path)))
        test_account_status = _run(_test_account_state(str(db_path)))
    test_account_exists = test_account_status == "active"

    if test_account_status == "inactive":
        _fail(
            fmt,
            "default test account(account_id='test')가 비활성 상태입니다. "
            "`ante account activate test`로 활성화하거나 해당 row를 정리한 "
            "뒤 재시도하세요.",
            code="ACCOUNT_TEST_INACTIVE",
        )

    if all_files_exist and master_exists and test_account_exists:
        _fail(
            fmt,
            f"init이 이미 완료된 상태입니다: {config_path}\n"
            "  재설치를 원하면 디렉토리를 삭제한 뒤 다시 실행하세요.",
            code="CLI_ALREADY_INITIALIZED",
        )

    config_path.mkdir(parents=True, exist_ok=True)
    system_toml_content = SYSTEM_TOML_TEMPLATE.format(db_path=_DB_FILENAME)
    _ensure_file(artifacts["system.toml"], system_toml_content)
    effective_key = _ensure_encryption_key_in_secrets_env(artifacts["secrets.env"])
    artifacts["secrets.env"].chmod(0o600)
    if not _validate_fernet_key(os.environ.get(_ENCRYPTION_KEY_NAME)):
        os.environ[_ENCRYPTION_KEY_NAME] = effective_key
    db_path.parent.mkdir(parents=True, exist_ok=True)

    token = ""
    recovery_key = ""
    password = ""
    master_info: dict = {}
    test_account: dict = {}
    master_already_existed = master_exists

    if not master_exists:
        password = generate_password()
        try:
            master_info, token, recovery_key = _run(
                _bootstrap_master(str(db_path), member_id, name, password)
            )
        except ValueError as e:
            _fail(fmt, str(e), code="ACCOUNT_MASTER_BOOTSTRAP_FAILED")
        if not fmt.is_json:
            _emit_master_credentials_text(master_info, password, token, recovery_key)

    if not test_account_exists:
        try:
            test_account = _run(_create_test_account(str(db_path)))
        except Exception as e:
            if master_info:
                if fmt.is_json:
                    _emit_master_credentials_json_stderr(
                        master_info, password, token, recovery_key, config_path
                    )
                _fail(
                    fmt,
                    f"테스트 계좌 생성 실패: {e}. "
                    "master는 위에 출력된 비밀값으로 접근 가능. "
                    "원인 해결 후 재실행 시 test account만 생성됨.",
                    code="ACCOUNT_TEST_CREATE_FAILED",
                )
            else:
                _fail(
                    fmt,
                    f"테스트 계좌 생성 실패: {e}",
                    code="ACCOUNT_TEST_CREATE_FAILED",
                )

    if fmt.is_json:
        payload: dict = {"config_dir": str(config_path)}
        if master_info:
            payload.update(master_info)
            payload["token"] = token
            payload["recovery_key"] = recovery_key
            payload["password"] = password
        if test_account:
            payload["test_account"] = test_account
        fmt.output(payload)
        return

    click.echo("\n── 완료 ────────────────────────────────────────")
    click.echo(f"  설정 디렉토리: {config_path}")
    if master_info:
        click.echo(f"  Member ID   : {master_info['member_id']}")
    elif master_already_existed:
        click.echo("  Master 계정 : 이미 존재 (재발급 안 함)")
    if test_account:
        click.echo(
            f"  테스트 계좌 : {test_account['account_id']} ({test_account['exchange']})"
        )
    if master_info:
        click.echo("\n  위에 출력된 토큰을 환경변수로 등록하세요:")
        click.echo("    export ANTE_MEMBER_TOKEN=<위 토큰>")
    click.echo("\n  이제 시스템을 시작할 수 있습니다:")
    click.echo("    ante system start")
