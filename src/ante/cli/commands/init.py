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
    """JSON/text 모두에서 구조화된 에러 출력 후 exit 1.

    `click.ClickException`은 text 모드에서 "Error: ..." 를 stderr에 쓰지만
    JSON 모드에서도 동일한 텍스트를 내보내 `--format json` 계약을 깨뜨린다.
    이 헬퍼는 `OutputFormatter.error()`를 거쳐 JSON 모드에서는 구조화 에러를,
    text 모드에서는 "Error: ..." 를 stderr에 낸 뒤 exit code 1로 종료한다.
    """
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
# `config_dir` 기준 상대 경로. PID/IPC socket 위치 (Refs #1157,
# docs/specs/config/03-design-decisions.md 200-202).
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
    """신규 Fernet 마스터 키를 생성한다.

    구현은 ``cryptography.fernet.Fernet.generate_key()``를 그대로 호출하고
    base64 문자열로 디코딩해 반환한다. 결과는 항상 ``_validate_fernet_key``
    검증을 통과한다.
    """
    from cryptography.fernet import Fernet

    return Fernet.generate_key().decode()


def _resolve_effective_key(
    env_value: str | None, file_value: str | None
) -> tuple[str, bool, bool]:
    """env/file의 키 분류 결과로부터 effective key와 파일 상태 플래그를 도출한다.

    결정 행렬 (이슈 #1721 Implementation Plan v4):

    - valid env + valid file (동일 값): env 사용, file 보존, 백업 없음.
    - valid env + valid file (다른 값): env-wins. file을 env value로 교체하지만
      이전 라인이 valid였으므로 **백업하지 않는다**.
    - valid env + invalid/없음 file: env value를 file에 기입. invalid이었으면
      ``file_was_invalid_replaced=True`` 로 표시해 호출자가 백업하게 한다.
    - invalid/없음 env + valid file: file value를 effective key로 채택.
    - invalid/없음 env + invalid/없음 file: 신규 Fernet 키 생성. invalid이었으면
      ``file_was_invalid_replaced=True``.

    Args:
        env_value: ``os.environ.get("ANTE_DB_ENCRYPTION_KEY")`` 결과.
        file_value: ``secrets.env`` 의 동일 키 라인 값 (없으면 ``None``).

    Returns:
        ``(effective_key, file_was_invalid_replaced, file_was_synced_from_env)``.

        - ``effective_key``: 실제로 사용할 Fernet 키 문자열.
        - ``file_was_invalid_replaced``: file에 non-empty invalid 값이 있어서
          교체해야 한다는 신호. 호출자는 이 경우에만 백업 파일을 만든다.
        - ``file_was_synced_from_env``: file을 env value로 동기화해야 한다는 신호.
          (env가 valid이고 file이 invalid/없음 또는 다른 valid 값인 경우)
    """
    env_valid = _validate_fernet_key(env_value)
    file_valid = _validate_fernet_key(file_value)
    file_present_invalid = (file_value is not None) and (not file_valid)

    if env_valid:
        assert env_value is not None  # narrow type for mypy
        if file_valid and file_value == env_value:
            # NOP — file already in sync with env.
            return env_value, False, False
        # env-wins: file을 env value로 동기화.
        # 백업은 invalid 라인 교체 시에만(valid→valid 교체는 백업 없음).
        return env_value, file_present_invalid, True

    # env invalid/없음.
    if file_valid:
        assert file_value is not None  # narrow type for mypy
        return file_value, False, False

    # env invalid/없음 + file invalid/없음 → 신규 키 생성.
    new_key = _generate_db_encryption_key()
    return new_key, file_present_invalid, True


def _read_existing_encryption_key_line(secrets_env_path: Path) -> str | None:
    """secrets.env에서 ANTE_DB_ENCRYPTION_KEY 라인의 값만 추출.

    동일 키가 여러 번 있으면 **마지막 라인**의 값을 반환한다(`_load_dotenv`와
    동일한 last-wins 의미). 라인이 전혀 없으면 ``None``. 주석(#)으로 시작하는
    라인은 무시한다.
    """
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
    """기존 secrets.env 파일을 0600 권한으로 원자적 백업한다.

    백업 파일명: ``secrets.env.bak.<UTC iso>`` (같은 디렉토리). tempfile에
    내용을 0600으로 쓴 뒤 ``os.rename``으로 원자 이동한다. 기존 secrets.env는
    그대로 유지된다(이 헬퍼는 백업만 담당).
    """
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
    """secrets.env에 ANTE_DB_ENCRYPTION_KEY 라인을 갱신/추가한다.

    - 파일이 없으면: ``SECRETS_ENV_TEMPLATE``을 채워 신규 생성(0600).
    - 파일이 있는데 라인이 없으면: 파일 끝에 ``ANTE_DB_ENCRYPTION_KEY=…``
      한 줄을 append하고 권한을 0600으로 다시 적용한다.
    - 라인이 있으면: 마지막 발견 라인을 새 값으로 교체(주석 라인은 보존).

    파일 갱신은 tempfile에 내용을 쓰고 0600 chmod 후 ``os.rename``으로
    원자 이동한다. 이렇게 해야 부분 쓰기 상태에서 다른 프로세스가 키를 빈
    상태로 읽지 않는다.
    """
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
    # 마지막 ANTE_DB_ENCRYPTION_KEY 라인 인덱스 탐색 (last-wins 일관).
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
    """ANTE_DB_ENCRYPTION_KEY 5-state idempotent path.

    5개 상태 분기:
      1. secrets.env 파일 자체가 없음 → 신규 키 생성 + 파일 신규 생성(템플릿).
      2. 파일은 있는데 라인이 없음 → 신규 키 생성 + 라인 append.
      3. 라인은 있는데 값이 빈 문자열 → 신규 키 생성 + 라인 교체(백업 없음, 빈
         값은 backup 가치 없음).
      4. 라인이 있고 값이 non-empty이지만 Fernet 검증 실패(invalid) → 신규 키
         생성 또는 valid env value로 교체. **invalid 값 backup 필수**.
      5. 라인이 있고 값이 Fernet valid → env-wins 비교. 동일 값이면 NOP,
         다른 valid env가 있으면 env value로 교체(valid→valid는 backup 없음),
         env가 invalid/없음이면 file value 유지.

    Args:
        secrets_env_path: ``<config_dir>/secrets.env`` 경로.

    Returns:
        이 함수가 effective key로 결정한 Fernet 키 문자열. 호출자는 이 값을
        ``os.environ[_ENCRYPTION_KEY_NAME]`` 에 set한다(이미 valid env가
        있으면 set 생략).
    """
    env_value = os.environ.get(_ENCRYPTION_KEY_NAME)
    file_value = _read_existing_encryption_key_line(secrets_env_path)

    effective_key, file_was_invalid_replaced, file_was_synced_from_env = (
        _resolve_effective_key(env_value, file_value)
    )

    # 빈 문자열은 backup 대상이 아니다 — invalid 분류이지만 보호할 데이터가 없음.
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


def _run(coro):  # noqa: ANN001, ANN202
    """동기 CLI에서 async 함수 실행."""
    return asyncio.run(coro)


def _resolve_config_path(ctx: click.Context, target_dir: str | None) -> Path:
    """init 대상 디렉토리 결정.

    우선순위:
      1. `--dir` 인자 (이 명령 전용 명시적 override) — 다른 모든 입력을 무시한다.
      2. 루트 그룹이 `--config-dir`/`ANTE_CONFIG_DIR`로부터 확정한
         `ctx.obj['config_dir']`.
      3. `ANTE_CONFIG_DIR` 환경변수 (root callback이 이미 처리하지만 ctx가
         비어 있는 직접 호출 경로를 위해 폴백으로도 검사한다).
      4. 최종 폴백: `~/.config/ante/`. `resolve_config_dir()`은
         "디렉토리가 실제로 존재할 때만 ~/.config/ante 사용"으로 동작하지만,
         init은 이 디렉토리를 **만드는** 명령이므로 존재 여부와 무관하게
         스펙(기본: ~/.config/ante)을 따른다.

    `init`이 root 그룹의 `--config-dir`/`ANTE_CONFIG_DIR`을 무시하면 이후
    CLI들이 `get_db_path()`로 보는 `<config_dir>/db/ante.db`와 init이 만든
    DB 경로가 어긋난다(Codex 12차 리뷰 Finding 1).
    """
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
    """DB에 role='master' member row가 있는지 확인.

    DB 파일은 있으나 스키마/데이터가 없는 "orphan" 상태에서도
    False를 반환하도록 예외를 흡수한다.
    """
    from ante.core.database import Database

    db = Database(db_path)
    try:
        await db.connect()
    except Exception:  # noqa: BLE001
        return False
    try:
        try:
            row = await db.fetch_one(
                "SELECT member_id FROM members WHERE role = ? LIMIT 1",
                ("master",),
            )
        except Exception:  # noqa: BLE001
            # members 테이블이 아직 없을 수 있음 (orphan DB)
            return False
        return row is not None
    finally:
        await db.close()


async def _test_account_state(
    db_path: str,
) -> Literal["active", "inactive", "missing"]:
    """default test account(account_id='test')의 3-state 판정.

    - "active":  status='active' 인 'test' 계좌 존재 → 재생성 불필요 (skip)
    - "inactive": 'test' 계좌가 있으나 suspended/deleted 등 비활성 상태
                  → init이 `AccountService.create_default_test_account()`를
                  호출하면 account_id 중복으로 예외가 터지므로, 사용자에게
                  명시적 에러로 안내해야 한다 (묵시적 skip 금지).
    - "missing": 'test' 계좌 자체가 없음 → 재생성 대상

    AccountService가 만드는 행(`account_id='test'`)을 기준으로 판정 범위를
    좁히므로 임의의 custom `broker_type='test'` 계좌(account_id!='test')는
    "missing"으로 취급된다.
    """
    from ante.core.database import Database

    db = Database(db_path)
    try:
        await db.connect()
    except Exception:  # noqa: BLE001
        return "missing"
    try:
        try:
            row = await db.fetch_one(
                "SELECT status FROM accounts WHERE account_id = ? LIMIT 1",
                ("test",),
            )
        except Exception:  # noqa: BLE001
            # accounts 테이블이 아직 없을 수 있음 (orphan DB)
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
    """text 모드에서 master bootstrap 직후 비밀값을 stdout에 출력한다.

    성공/실패와 무관하게 이 블록 **한 번**만 비밀값을 노출한다. completion 블록은
    요약/다음 단계 안내만 출력하며 비밀값을 재출력하지 않는다 (1회 노출 불변식).
    """
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
    """JSON 모드 실패 경로 전용 복구 이벤트 (stderr 한 줄 JSON).

    test account 생성 실패 시에만 호출되며, stdout payload가 비밀값 없는 에러
    응답으로 대체되므로 stderr에 비밀값 1회 노출을 보장해 Agent가 lockout에서
    복구할 수 있게 한다. 성공 경로에서는 호출되지 않는다 (stdout payload로 1회
    노출).
    """
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

    # DB 레코드 상태 조회 (DB 파일이 있을 때만)
    master_exists = False
    test_account_status: Literal["active", "inactive", "missing"] = "missing"
    if db_file_exists:
        master_exists = _run(_master_exists_in_db(str(db_path)))
        test_account_status = _run(_test_account_state(str(db_path)))
    test_account_exists = test_account_status == "active"

    # test account가 suspended/deleted 등 비활성 상태면 명시적 에러로 안내한다.
    # AccountService.create_default_test_account()가 account_id='test' 중복으로
    # 예외를 던지므로 묵시적 skip/재생성을 시도하면 init 자체가 실패한다.
    if test_account_status == "inactive":
        _fail(
            fmt,
            "default test account(account_id='test')가 비활성 상태입니다. "
            "`ante account activate test`로 활성화하거나 해당 row를 정리한 "
            "뒤 재시도하세요.",
            code="test_account_inactive",
        )

    # state 1: 모든 상태 완료 → 거부
    if all_files_exist and master_exists and test_account_exists:
        _fail(
            fmt,
            f"init이 이미 완료된 상태입니다: {config_path}\n"
            "  재설치를 원하면 디렉토리를 삭제한 뒤 다시 실행하세요.",
            code="already_initialized",
        )

    # 1. 디렉토리 생성 및 누락 파일 보충 (state 2/3/4/5 공통)
    config_path.mkdir(parents=True, exist_ok=True)
    # db.path는 절대 경로로 기록한다. 서버(`ante system start`)와 IPC가
    # cwd와 무관하게 동일한 DB 파일을 보도록 보장하기 위함이다.
    db_absolute = (config_path / _DB_FILENAME).resolve()
    system_toml_content = SYSTEM_TOML_TEMPLATE.format(db_path=str(db_absolute))
    _ensure_file(artifacts["system.toml"], system_toml_content)
    # secrets.env는 ANTE_DB_ENCRYPTION_KEY를 보장하기 위해 별도 helper로 처리한다.
    # 이미 존재하는 파일은 내용을 보존하면서 키 라인만 갱신/추가하며, 신규
    # 생성 시에는 SECRETS_ENV_TEMPLATE을 사용해 만든다.
    effective_key = _ensure_encryption_key_in_secrets_env(artifacts["secrets.env"])
    artifacts["secrets.env"].chmod(0o600)
    # in-process os.environ 설정: 현재 환경변수가 invalid/empty/unset일 때만
    # override하고, non-empty valid env는 그대로 보존한다(env-wins).
    if not _validate_fernet_key(os.environ.get(_ENCRYPTION_KEY_NAME)):
        os.environ[_ENCRYPTION_KEY_NAME] = effective_key
    db_path.parent.mkdir(parents=True, exist_ok=True)

    token = ""
    recovery_key = ""
    password = ""
    master_info: dict = {}
    test_account: dict = {}
    master_already_existed = master_exists

    # 2. master bootstrap — master row 없을 때만 (state 4/5)
    if not master_exists:
        password = generate_password()
        try:
            master_info, token, recovery_key = _run(
                _bootstrap_master(str(db_path), member_id, name, password)
            )
        except ValueError as e:
            _fail(fmt, str(e), code="bootstrap_failed")
        # text 모드는 여기서 비밀값을 1회 노출 (completion 블록은 재출력 금지).
        # JSON 성공 경로는 stdout payload로 1회 노출되므로 여기서 stderr 이벤트를
        # 내보내지 않는다 (중복 노출 방지). JSON 실패 경로만 아래 except에서
        # stderr 이벤트로 복구 수단을 유지한다.
        if not fmt.is_json:
            _emit_master_credentials_text(master_info, password, token, recovery_key)

    # 3. test account 생성 — test account row 없을 때만 (state 3/4/5)
    if not test_account_exists:
        try:
            test_account = _run(_create_test_account(str(db_path)))
        except Exception as e:  # noqa: BLE001
            if master_info:
                # master는 이미 생성됐다. JSON 모드라면 stdout은 에러 payload가
                # 쓰이므로 stderr에 복구용 이벤트를 1회 내보낸다. text 모드는
                # 위에서 이미 블록을 출력했다.
                if fmt.is_json:
                    _emit_master_credentials_json_stderr(
                        master_info, password, token, recovery_key, config_path
                    )
                _fail(
                    fmt,
                    f"테스트 계좌 생성 실패: {e}. "
                    "master는 위에 출력된 비밀값으로 접근 가능. "
                    "원인 해결 후 재실행 시 test account만 생성됨.",
                    code="test_account_failed",
                )
            else:
                _fail(fmt, f"테스트 계좌 생성 실패: {e}", code="test_account_failed")

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

    # text completion — 비밀값은 위 _emit_master_credentials_text 블록에서 1회
    # 노출되었으므로 여기서는 요약 + 다음 단계 안내만 출력한다 (1회 노출 불변식).
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
