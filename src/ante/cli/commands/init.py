"""ante init — 비대화형 최소 초기 설정."""

from __future__ import annotations

import asyncio
from pathlib import Path

import click

from ante.cli.commands._password import generate_password
from ante.cli.main import get_formatter

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

    실행 순서: 1. 디렉토리 생성 → 2. master bootstrap → 3. test account 생성
    """
    fmt = get_formatter(ctx)
    config_path = _resolve_config_path(target_dir)

    # 멱등성: 3개 파일 모두 존재 시 거부
    if _all_artifacts_exist(config_path):
        raise click.ClickException(
            f"init이 이미 완료된 상태입니다: {config_path}\n"
            "  재설치를 원하면 디렉토리를 삭제한 뒤 다시 실행하세요."
        )

    # 1. 디렉토리 생성
    config_path.mkdir(parents=True, exist_ok=True)

    artifacts = _expected_artifacts(config_path)
    _ensure_file(artifacts["system.toml"], SYSTEM_TOML_TEMPLATE)
    _ensure_file(artifacts["secrets.env"], SECRETS_ENV_TEMPLATE)
    artifacts["secrets.env"].chmod(0o600)

    db_path = artifacts["db/ante.db"]
    db_existed_before = db_path.exists()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    token = ""
    recovery_key = ""
    password = ""
    master_info: dict = {}
    test_account: dict = {}

    if not db_existed_before:
        password = generate_password()
        # 2. master bootstrap
        try:
            master_info, token, recovery_key = _run(
                _bootstrap_master(str(db_path), member_id, name, password)
            )
        except ValueError as e:
            raise click.ClickException(str(e)) from e

        # 3. test account 생성
        try:
            test_account = _run(_create_test_account(str(db_path)))
        except Exception as e:  # noqa: BLE001
            raise click.ClickException(f"테스트 계좌 생성 실패: {e}") from e

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
        click.echo(f"  이름        : {master_info['name']}")
        click.echo(f"  이모지      : {master_info['emoji']}")
    if test_account:
        click.echo(
            f"  테스트 계좌 : {test_account['account_id']} ({test_account['exchange']})"
        )
    if master_info:
        click.echo(f"\n  패스워드     : {password}")
        click.echo(f"  토큰         : {token}")
        click.echo(f"  Recovery Key : {recovery_key}")
        click.echo("\n  위 3개 값은 이 화면에만 표시됩니다. 안전한 곳에 보관하세요.")
        click.echo("\n  셸에 토큰 등록:")
        click.echo(f"   export ANTE_MEMBER_TOKEN={token}")
        click.echo("\n  이제 시스템을 시작할 수 있습니다:")
        click.echo("   ante system start")
