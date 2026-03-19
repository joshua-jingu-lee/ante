"""ante init — 설정 디렉토리 초기화."""

from __future__ import annotations

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

    config_path = Path(target_dir) if target_dir else Path.home() / ".config" / "ante"

    if config_path.exists():
        existing = []
        if (config_path / _SYSTEM_TOML_FILENAME).exists():
            existing.append(_SYSTEM_TOML_FILENAME)
        if (config_path / _SECRETS_ENV_FILENAME).exists():
            existing.append(_SECRETS_ENV_FILENAME)
        if existing and not seed:
            fmt.error(
                f"설정 디렉토리가 이미 존재합니다: {config_path}\n"
                f"  기존 파일: {', '.join(existing)}"
            )
            return

    config_path.mkdir(parents=True, exist_ok=True)

    system_toml = config_path / _SYSTEM_TOML_FILENAME
    if not system_toml.exists():
        system_toml.write_text(SYSTEM_TOML_TEMPLATE)

    secrets_env = config_path / _SECRETS_ENV_FILENAME
    if not secrets_env.exists():
        secrets_env.write_text(SECRETS_ENV_TEMPLATE)

    created_files = [_SYSTEM_TOML_FILENAME, _SECRETS_ENV_FILENAME]

    if seed:
        import asyncio

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
