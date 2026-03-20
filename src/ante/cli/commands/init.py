"""ante init — 대화형 통합 초기 설정."""

from __future__ import annotations

import asyncio
import stat
from pathlib import Path

import click

from ante.cli.main import get_formatter

_SYSTEM_TOML_FILENAME = "system.toml"
_SECRETS_ENV_FILENAME = "secrets.env"

SYSTEM_TOML_TEMPLATE = """\
# Ante 시스템 설정

[system]
log_level = "INFO"
timezone = "Asia/Seoul"

[db]
path = "db/ante.db"

[web]
host = "0.0.0.0"
port = 8000
"""

SECRETS_ENV_TEMPLATE = """\
# Ante 비밀값 설정
# 환경변수가 이 파일보다 우선합니다.

# KIS 증권 API
# KIS_APP_KEY=
# KIS_APP_SECRET=
# KIS_ACCOUNT_NO=

# 텔레그램 알림 (선택)
# TELEGRAM_BOT_TOKEN=
# TELEGRAM_CHAT_ID=
"""


def _run(coro):  # noqa: ANN001, ANN202
    """동기 CLI에서 async 함수 실행."""
    return asyncio.run(coro)


def _resolve_config_path(target_dir: str | None) -> Path:
    return Path(target_dir) if target_dir else Path.home() / ".config" / "ante"


def _create_config_files(config_path: Path) -> None:
    """설정 디렉토리와 기본 파일을 생성한다."""
    config_path.mkdir(parents=True, exist_ok=True)

    system_toml = config_path / _SYSTEM_TOML_FILENAME
    if not system_toml.exists():
        system_toml.write_text(SYSTEM_TOML_TEMPLATE)

    secrets_env = config_path / _SECRETS_ENV_FILENAME
    if not secrets_env.exists():
        secrets_env.write_text(SECRETS_ENV_TEMPLATE)


def _write_secrets_env(config_path: Path, entries: dict[str, str]) -> None:
    """secrets.env에 키-값 쌍을 추가한다. 기존 내용 보존."""
    secrets_env = config_path / _SECRETS_ENV_FILENAME
    content = secrets_env.read_text() if secrets_env.exists() else ""

    lines = []
    for key, value in entries.items():
        lines.append(f"{key}={value}\n")

    if lines:
        secrets_env.write_text(content + "\n" + "".join(lines))
        secrets_env.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0600


def _set_broker_test(config_path: Path) -> None:
    """system.toml에 broker.type = 'test'를 추가한다."""
    system_toml = config_path / _SYSTEM_TOML_FILENAME
    content = system_toml.read_text()
    if "[broker]" not in content:
        content += '\n[broker]\ntype = "test"\n'
        system_toml.write_text(content)


def _prompt_master_account() -> tuple[str, str, str]:
    """Master 계정 정보를 대화형으로 입력받는다."""
    click.echo("\n── 1. Master 계정 ──────────────────────────────")
    member_id = click.prompt("Member ID")
    name = click.prompt("이름")
    password = click.prompt("패스워드", hide_input=True, confirmation_prompt=True)
    return member_id, name, password


def _prompt_kis() -> dict[str, str] | None:
    """KIS 연동 정보를 입력받는다. 스킵 시 None 반환."""
    click.echo("\n── 2. 증권사 연동 (KIS) ────────────────────────")
    click.echo("  건너뛰면 Test 증권사로 설정됩니다.")
    click.echo("  나중에 secrets.env에서 변경할 수 있습니다.")
    if not click.confirm("KIS 연동 정보를 입력하시겠습니까?", default=False):
        return None

    app_key = click.prompt("APP KEY")
    app_secret = click.prompt("APP SECRET")
    account_no = click.prompt("계좌번호 (예: 50123456-01)")
    is_virtual = click.confirm("모의투자 여부", default=False)
    return {
        "KIS_APP_KEY": app_key,
        "KIS_APP_SECRET": app_secret,
        "KIS_ACCOUNT_NO": account_no,
        "KIS_VIRTUAL": "1" if is_virtual else "0",
    }


def _prompt_telegram() -> dict[str, str] | None:
    """Telegram 연동 정보를 입력받는다. 스킵 시 None 반환."""
    click.echo("\n── 3. 텔레그램 알림 (선택) ─────────────────────")
    click.echo("  나중에 secrets.env에서 설정할 수 있습니다.")
    if not click.confirm("텔레그램 알림을 설정하시겠습니까?", default=False):
        return None

    bot_token = click.prompt("봇 토큰")
    chat_id = click.prompt("채팅 ID")
    return {
        "TELEGRAM_BOT_TOKEN": bot_token,
        "TELEGRAM_CHAT_ID": chat_id,
    }


def _prompt_datafeed(config_path: Path) -> None:
    """DataFeed API 키를 입력받아 .feed/.env에 저장한다."""
    click.echo("\n── 4. 데이터 수집 API (선택) ───────────────────")
    click.echo("  설정하면 백테스팅용 KRX 시세·재무 데이터를 자동 수집할 수 있습니다.")
    click.echo("  data.go.kr과 DART의 Open API Key가 필요합니다.")
    click.echo("  나중에 `ante feed config set` 명령어로도 설정할 수 있습니다.")

    from ante.feed.config import FeedConfig

    feed_cfg = FeedConfig(str(config_path / "data"))

    if click.confirm("data.go.kr API 키를 입력하시겠습니까?", default=False):
        key = click.prompt("data.go.kr API 키")
        feed_cfg.set_api_key("ANTE_DATAGOKR_API_KEY", key)

    if click.confirm("DART API 키를 입력하시겠습니까?", default=False):
        key = click.prompt("DART API 키")
        feed_cfg.set_api_key("ANTE_DART_API_KEY", key)


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
                "role": m.role,
                "emoji": m.emoji,
            },
            token,
            recovery_key,
        )
    finally:
        await db.close()


@click.command("init")
@click.option(
    "--dir",
    "target_dir",
    type=click.Path(),
    default=None,
    help="설정 디렉토리 경로 (기본: ~/.config/ante/)",
)
@click.option(
    "--seed",
    is_flag=True,
    default=False,
    help="E2E 테스트용 시드 데이터 주입",
)
@click.pass_context
def init(ctx: click.Context, target_dir: str | None, seed: bool) -> None:
    """설정 디렉토리 및 기본 설정 파일 생성."""
    fmt = get_formatter(ctx)
    config_path = _resolve_config_path(target_dir)

    # --seed: 기존 동작 유지 (시드 데이터 주입 전용)
    if seed:
        _run_seed_mode(fmt, config_path)
        return

    # 멱등성: 이미 설정이 존재하면 거부
    if config_path.exists():
        existing = []
        if (config_path / _SYSTEM_TOML_FILENAME).exists():
            existing.append(_SYSTEM_TOML_FILENAME)
        if (config_path / _SECRETS_ENV_FILENAME).exists():
            existing.append(_SECRETS_ENV_FILENAME)
        if existing:
            fmt.error(
                f"설정 디렉토리가 이미 존재합니다: {config_path}\n"
                f"  기존 파일: {', '.join(existing)}"
            )
            return

    click.echo("\nAnte 초기 설정을 시작합니다.")

    # 1. 설정 파일 생성
    _create_config_files(config_path)

    # 2. Master 계정 입력
    member_id, name, password = _prompt_master_account()

    # 3. KIS 연동
    kis_info = _prompt_kis()
    if kis_info:
        _write_secrets_env(config_path, kis_info)
        broker_label = (
            "KIS (모의투자)" if kis_info.get("KIS_VIRTUAL") == "1" else "KIS (실투자)"
        )
    else:
        _set_broker_test(config_path)
        broker_label = "Test"

    # 4. Telegram 연동
    telegram_info = _prompt_telegram()
    if telegram_info:
        _write_secrets_env(config_path, telegram_info)

    # 5. DataFeed API 키
    _prompt_datafeed(config_path)

    # 6. Bootstrap master 계정
    db_path = str(config_path / "db" / "ante.db")
    (config_path / "db").mkdir(parents=True, exist_ok=True)

    try:
        result, token, recovery_key = _run(
            _bootstrap_master(db_path, member_id, name, password)
        )
    except ValueError as e:
        fmt.error(str(e))
        return

    # 7. 결과 출력
    click.echo("\n── 완료 ────────────────────────────────────────")

    if fmt.is_json:
        fmt.output(
            {
                **result,
                "config_dir": str(config_path),
                "broker": broker_label,
                "token": token,
                "recovery_key": recovery_key,
            }
        )
        return

    click.echo("\n✅ 초기 설정 완료")
    click.echo(f"  설정 디렉토리: {config_path}")
    click.echo(f"  Member ID   : {result['member_id']}")
    click.echo(f"  이모지      : {result['emoji']}")
    click.echo(f"  브로커      : {broker_label}")
    click.echo(f"\n🔑 토큰: {token}")
    click.echo("\n   셸 프로필에 추가하면 매번 입력하지 않아도 됩니다:")
    click.echo(f"   echo 'export ANTE_MEMBER_TOKEN={token}' >> ~/.zshrc")
    click.echo("\n   또는 현재 세션에서만 사용:")
    click.echo(f"   export ANTE_MEMBER_TOKEN={token}")
    click.echo("\n   이제 시스템을 시작할 수 있습니다:")
    click.echo("   ante system start")
    click.echo(f"\n⚠️  Recovery Key: {recovery_key}")
    click.echo("   이 키는 다시 표시되지 않습니다. 안전한 곳에 보관하세요.")


def _run_seed_mode(fmt, config_path: Path) -> None:  # noqa: ANN001
    """--seed 모드: 설정 파일 + 시드 데이터 주입."""
    config_path.mkdir(parents=True, exist_ok=True)

    system_toml = config_path / _SYSTEM_TOML_FILENAME
    if not system_toml.exists():
        system_toml.write_text(SYSTEM_TOML_TEMPLATE)

    secrets_env = config_path / _SECRETS_ENV_FILENAME
    if not secrets_env.exists():
        secrets_env.write_text(SECRETS_ENV_TEMPLATE)

    created_files = [_SYSTEM_TOML_FILENAME, _SECRETS_ENV_FILENAME]

    from tests.fixtures.seed.seeder import inject_seed_data

    db_path = str(config_path / "db" / "ante.db")
    (config_path / "db").mkdir(parents=True, exist_ok=True)
    data_dir = str(config_path / "data")

    result = asyncio.run(inject_seed_data(db_path, data_dir))
    created_files.append("db/ante.db (시드 데이터)")
    if result.get("parquet_path"):
        created_files.append("data/ (샘플 OHLCV)")

    fmt.success(
        f"설정 초기화 완료: {config_path}",
        {
            "config_dir": str(config_path),
            "files": created_files,
        },
    )
