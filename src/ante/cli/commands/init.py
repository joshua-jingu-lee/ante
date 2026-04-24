"""ante init — 비대화형 최소 초기 설정."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Literal

import click

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
path = "db/ante.db"

[web]
host = "0.0.0.0"
port = 3982
"""

SECRETS_ENV_TEMPLATE = """\
# Ante 비밀값 설정
# 환경변수가 이 파일보다 우선합니다.

# 텔레그램 알림 (선택) - 사용 시 주석 해제하고 값 채우기
# TELEGRAM_BOT_TOKEN=
# TELEGRAM_CHAT_ID=
"""


def _run(coro):  # noqa: ANN001, ANN202
    """동기 CLI에서 async 함수 실행."""
    return asyncio.run(coro)


def _resolve_config_path(target_dir: str | None) -> Path:
    return Path(target_dir) if target_dir else Path.home() / ".config" / "ante"


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
    config_path = _resolve_config_path(target_dir)

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
    _ensure_file(artifacts["system.toml"], SYSTEM_TOML_TEMPLATE)
    _ensure_file(artifacts["secrets.env"], SECRETS_ENV_TEMPLATE)
    artifacts["secrets.env"].chmod(0o600)
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
