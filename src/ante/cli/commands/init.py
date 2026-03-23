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
port = 3982
"""

SECRETS_ENV_TEMPLATE = """\
# Ante 비밀값 설정
# 환경변수가 이 파일보다 우선합니다.

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


def _prompt_master_account() -> tuple[str, str, str]:
    """Master 계정 정보를 대화형으로 입력받는다."""
    click.echo("\n── [1/4] Master 계정 ───────────────────────────")
    member_id = click.prompt("Member ID")
    name = click.prompt("이름")
    password = click.prompt("패스워드", hide_input=True, confirmation_prompt=True)
    return member_id, name, password


def _get_available_brokers() -> list[tuple[str, str]]:
    """등록 가능한 브로커 목록을 반환한다.

    Returns:
        (broker_type, display_label) 튜플 리스트.
    """
    from ante.account.presets import BROKER_PRESETS

    excluded = {"test"}
    result = []
    for broker_type, preset in BROKER_PRESETS.items():
        if broker_type in excluded:
            continue
        label = f"{broker_type} ({preset.exchange} / {preset.currency})"
        result.append((broker_type, label))
    return result


def _prompt_account() -> list[dict[str, str]]:
    """계좌 등록 정보를 대화형으로 입력받는다.

    Returns:
        등록할 계좌 정보 딕셔너리 리스트. 빈 리스트면 테스트 계좌만 생성.
    """
    from ante.account.presets import BROKER_PRESETS

    click.echo("\n── [2/4] 계좌 설정 ─────────────────────────────")
    click.echo("  등록하지 않으면 테스트 계좌가 자동으로 생성됩니다.")
    click.echo("  나중에 `ante account create` 명령어로도 추가할 수 있습니다.")

    accounts: list[dict[str, str]] = []
    brokers = _get_available_brokers()

    while True:
        if not click.confirm("실제 거래 계좌를 등록하시겠습니까?", default=False):
            break

        # 브로커 선택
        click.echo("\n  브로커를 선택하세요:")
        for i, (_, label) in enumerate(brokers, 1):
            click.echo(f"    {i}) {label}")

        choice = click.prompt("  선택", type=click.IntRange(1, len(brokers)), default=1)
        broker_type = brokers[choice - 1][0]
        preset = BROKER_PRESETS[broker_type]

        # 계좌 ID, 이름
        account_id = click.prompt("  계좌 ID", default=preset.default_account_id)
        account_name = click.prompt("  이름", default=preset.default_name)

        # 인증 정보 입력
        credentials: dict[str, str] = {}
        for cred_key in preset.required_credentials:
            value = click.prompt(f"  {cred_key}")
            credentials[cred_key] = value

        accounts.append(
            {
                "account_id": account_id,
                "name": account_name,
                "broker_type": broker_type,
                "credentials": credentials,
            }
        )

        click.echo(
            f'  -> 계좌 "{account_id}" 등록 예정 '
            f"({preset.exchange} / {preset.currency} / {broker_type})"
        )

    return accounts


def _prompt_telegram() -> dict[str, str] | None:
    """Telegram 연동 정보를 입력받는다. 스킵 시 None 반환."""
    click.echo("\n── [3/4] 텔레그램 알림 (선택) ──────────────────")
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
    click.echo("\n── [4/4] 데이터 수집 API (선택) ────────────────")
    click.echo("  설정하면 백테스팅용 KRX 시세·재무 데이터를 자동 수집할 수 있습니다.")
    click.echo("  data.go.kr과 DART의 Open API Key가 필요합니다.")
    click.echo("  나중에 `ante feed config set` 명령어로도 설정할 수 있습니다.")

    from ante.feed.config import FeedConfig

    feed_cfg = FeedConfig(str(config_path / "data"))

    if click.confirm("data.go.kr API 키를 입력하시겠습니까?", default=False):
        key = click.prompt("data.go.kr API 키")
        feed_cfg.set_api_key("ANTE_DATAGOKR_API_KEY", key)

    try:
        want_dart = click.confirm("DART API 키를 입력하시겠습니까?", default=False)
    except (click.Abort, EOFError):
        want_dart = False
    if want_dart:
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


async def _create_accounts(
    db_path: str,
    account_inputs: list[dict[str, str]],
) -> list[dict[str, str]]:
    """AccountService를 통해 계좌를 생성한다.

    테스트 계좌는 항상 생성되고, account_inputs가 있으면 실제 계좌도 생성한다.

    Returns:
        생성된 계좌 정보 딕셔너리 리스트 (account_id, broker_type 포함).
    """
    from ante.account.models import Account, TradingMode
    from ante.account.presets import BROKER_PRESETS
    from ante.account.service import AccountService
    from ante.core.database import Database
    from ante.eventbus.bus import EventBus

    db = Database(db_path)
    await db.connect()
    try:
        eventbus = EventBus()
        service = AccountService(db, eventbus)
        await service.initialize()

        created: list[dict[str, str]] = []

        # 테스트 계좌 자동 생성
        test_account = await service.create_default_test_account()
        created.append(
            {
                "account_id": test_account.account_id,
                "broker_type": test_account.broker_type,
                "exchange": test_account.exchange,
            }
        )

        # 실제 계좌 생성
        for info in account_inputs:
            broker_type = info["broker_type"]
            preset = BROKER_PRESETS[broker_type]
            account = Account(
                account_id=info["account_id"],
                name=info["name"],
                exchange=preset.exchange,
                currency=preset.currency,
                timezone=preset.timezone,
                trading_hours_start=preset.trading_hours_start,
                trading_hours_end=preset.trading_hours_end,
                trading_mode=TradingMode.LIVE,
                broker_type=broker_type,
                credentials=info["credentials"],
                buy_commission_rate=preset.buy_commission_rate,
                sell_commission_rate=preset.sell_commission_rate,
            )
            await service.create(account)
            created.append(
                {
                    "account_id": account.account_id,
                    "broker_type": broker_type,
                    "exchange": preset.exchange,
                }
            )

        return created
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

    # 3. 계좌 설정
    account_inputs = _prompt_account()

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

    # 7. 계좌 생성 (테스트 계좌 자동 + 실제 계좌)
    try:
        created_accounts = _run(_create_accounts(db_path, account_inputs))
    except Exception as e:
        fmt.error(f"계좌 생성 실패: {e}")
        return

    # 계좌 라벨 생성
    if account_inputs:
        labels = [f"{a['account_id']} ({a['broker_type']})" for a in created_accounts]
        account_label = ", ".join(labels)
    else:
        account_label = "test (테스트 계좌만)"

    # 8. 결과 출력
    click.echo("\n── 완료 ────────────────────────────────────────")

    if fmt.is_json:
        fmt.output(
            {
                **result,
                "config_dir": str(config_path),
                "accounts": created_accounts,
                "token": token,
                "recovery_key": recovery_key,
            }
        )
        return

    click.echo("\n초기 설정 완료")
    click.echo(f"  설정 디렉토리: {config_path}")
    click.echo(f"  Member ID   : {result['member_id']}")
    click.echo(f"  이모지      : {result['emoji']}")
    click.echo(f"  계좌        : {account_label}")
    click.echo(f"\n  토큰: {token}")
    click.echo("\n   셸 프로필에 추가하면 매번 입력하지 않아도 됩니다:")
    click.echo(f"   echo 'export ANTE_MEMBER_TOKEN={token}' >> ~/.zshrc")
    click.echo("\n   또는 현재 세션에서만 사용:")
    click.echo(f"   export ANTE_MEMBER_TOKEN={token}")
    click.echo("\n   이제 시스템을 시작할 수 있습니다:")
    click.echo("   ante system start")
    click.echo(f"\n   Recovery Key: {recovery_key}")
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
