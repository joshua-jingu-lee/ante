"""``rule update`` 직접 실행 분기의 스키마 준비 (#2773에서 drift 테스트에서 옮김).

런타임이 없으면 ``rule update`` 는 IPC 없이 DB의 계좌 설정을 고친다. 그때
``audit_log``·``accounts`` 테이블이 없는 DB에서도 스키마를 준비하고, 감사
기록을 남기거나 ``ACCOUNT_NOT_FOUND`` 로 끝난다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from ante.member.models import Member, MemberRole, MemberStatus, MemberType

_MOCK_MASTER = Member(
    member_id="test-master",
    type=MemberType.HUMAN,
    role=MemberRole.MASTER,
    org="default",
    name="Test Master",
    status=MemberStatus.ACTIVE,
    scopes=[],
)


@pytest.fixture(autouse=True)
def bypass_auth():
    with patch(
        "ante.cli.main.authenticate_member",
        side_effect=lambda ctx: ctx.obj.update({"member": _MOCK_MASTER}),
    ):
        yield


def _invoke(args: list[str]):
    from ante.cli.main import cli

    runner = CliRunner()
    env = {"ANTE_MEMBER_TOKEN": ""}
    return runner.invoke(cli, args, env=env, catch_exceptions=False)


def _load_json_payload(output: str) -> Any:
    return json.loads(output)


def _seed_account(config_dir: Path, account_id: str = "acct-001") -> Path:
    """rule list/info 가 요구하는 account 가 존재하는 DB 를 생성한다.

    ``_create_rule_engine`` (rule.py:91-103) 은 ``SELECT 1 FROM accounts``
    로 lightweight 존재 검증을 수행하며 미존재 시 ``AccountNotFoundError``
    를 raise 한다. ``AccountService.initialize()`` 를 한 번 호출해 schema
    DDL 만 적용하고, 직접 INSERT 로 account_id 단일 row 를 시드한다
    (``AccountService.create`` 는 cold-path guard 와 credentials 정책
    검증을 수반하므로 본 fixture 의 minimal seeding 에는 적합하지 않다).
    """
    import asyncio

    from ante.account.service import AccountService
    from ante.core.database import Database
    from ante.eventbus.bus import EventBus

    (config_dir / "db").mkdir(parents=True, exist_ok=True)
    db_path = config_dir / "db" / "ante.db"

    async def _seed() -> None:
        db = Database(str(db_path))
        await db.connect()
        try:
            eventbus = EventBus()
            svc = AccountService(db=db, eventbus=eventbus)
            # initialize() 가 ``accounts`` schema DDL 만 보장하고, 본 fixture
            # 는 후속 INSERT 로 single test row 를 시드한다.
            await svc.initialize()
            await db.execute(
                "INSERT INTO accounts ("
                "  account_id, name, exchange, currency, broker_type, "
                "  trading_mode, credentials, broker_config, status"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    account_id,
                    "Test Account",
                    "KRX",
                    "KRW",
                    "test",
                    "virtual",
                    "{}",
                    "{}",
                    "active",
                ),
            )
        finally:
            await db.close()

    asyncio.run(_seed())
    return db_path


def _invoke_cold_update(config_dir: Path, account_id: str = "acct-001"):
    with patch("ante.cli.cold_path.is_active_runtime", return_value=False):
        return _invoke(
            [
                "--config-dir",
                str(config_dir),
                "--format",
                "json",
                "rule",
                "update",
                "daily_loss_limit",
                "--account",
                account_id,
                "--enabled",
                "--param",
                "max_daily_loss_percent=0.05",
            ]
        )


def _table_names(db_path: Path) -> set[str]:
    import sqlite3

    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        return {r[0] for r in rows}
    finally:
        conn.close()


def test_rule_update_cold_path_records_audit_on_db_without_audit_table(
    tmp_path: Path,
) -> None:
    """cold-path update 는 audit_log 스키마를 준비하고 감사 기록을 남긴다."""
    import sqlite3

    from ante.account.crypto import encrypt_credentials

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    db_path = _seed_account(config_dir)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "UPDATE accounts SET credentials = ? WHERE account_id = ?",
            (encrypt_credentials({}), "acct-001"),
        )
        conn.commit()
    finally:
        conn.close()
    assert "audit_log" not in _table_names(db_path)

    result = _invoke_cold_update(config_dir)

    assert result.exit_code == 0, result.output
    payload = _load_json_payload(result.output)
    assert payload["account_id"] == "acct-001"
    assert payload["rule"]["params"]["max_daily_loss_percent"] == 0.05
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(
            "SELECT member_id, action, resource FROM audit_log"
        ).fetchall()
    finally:
        conn.close()
    assert rows == [
        (
            "test-master",
            "account.rule.update",
            "account:acct-001:rule:daily_loss_limit",
        )
    ]


def test_rule_update_cold_path_on_db_without_accounts_table(tmp_path: Path) -> None:
    """cold-path update 는 accounts 스키마를 준비한 뒤 계좌를 조회한다.

    계좌 테이블이 없는 DB 에서도 스키마 오류가 아니라 ACCOUNT_NOT_FOUND 로
    끝나고, 명령 뒤에는 accounts 테이블이 존재한다.
    """
    import asyncio

    from ante.core.database import Database

    config_dir = tmp_path / "config"
    (config_dir / "db").mkdir(parents=True)
    db_path = config_dir / "db" / "ante.db"

    async def _touch() -> None:
        db = Database(str(db_path))
        await db.connect()
        await db.close()

    asyncio.run(_touch())
    assert "accounts" not in _table_names(db_path)

    result = _invoke_cold_update(config_dir)

    assert result.exit_code == 1, result.output
    payload = _load_json_payload(result.output)
    assert payload["status"] == "error"
    assert payload["code"] == "ACCOUNT_NOT_FOUND"
    assert "accounts" in _table_names(db_path)
