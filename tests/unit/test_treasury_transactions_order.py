"""``treasury transactions``가 같은 초의 행을 삽입 역순으로 내놓는다 (#2821).

실제 SQLite에 ``TREASURY_SCHEMA``를 적용하고, 생성 시각이 같은 행들의 순서와
``--limit``/``--offset`` 페이지 경계를 출력으로 확인한다.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from ante.core.database import Database
from ante.member.models import Member
from ante.treasury.treasury import TREASURY_SCHEMA

_MASTER = Member(
    member_id="test-master",
    type="human",
    role="master",
    org="default",
    name="Test Master",
    status="active",
)

_EARLIER = "2026-01-05 09:29:59"
_SAME_SECOND = "2026-01-05 09:30:00"


@pytest.fixture(autouse=True)
def _bypass_auth() -> Iterator[None]:
    with patch(
        "ante.cli.main.authenticate_member",
        side_effect=lambda ctx: ctx.obj.update({"member": _MASTER}),
    ):
        yield


@pytest.fixture
def ledger_db(tmp_path: Path) -> Iterator[str]:
    db_path = str(tmp_path / "treasury.db")

    async def _seed() -> None:
        db = Database(db_path)
        await db.connect()
        try:
            await db.execute_script(TREASURY_SCHEMA)
            for created_at in (_EARLIER, _SAME_SECOND, _SAME_SECOND, _SAME_SECOND):
                await db.execute(
                    "INSERT INTO treasury_transactions"
                    " (bot_id, account_id, transaction_type, amount, created_at)"
                    " VALUES (?, ?, ?, ?, ?)",
                    ("bot-1", "acc-1", "allocate", 1000.0, created_at),
                )
        finally:
            await db.close()

    asyncio.run(_seed())

    @asynccontextmanager
    async def _open_cli_db(ctx: Any, **_: Any) -> AsyncIterator[Database]:
        db = Database(db_path)
        await db.connect()
        try:
            yield db
        finally:
            await db.close()

    with patch("ante.cli.commands.treasury.open_cli_db", new=_open_cli_db):
        yield db_path


def _ids(*extra: str) -> list[int]:
    from ante.cli.main import cli

    result = CliRunner(mix_stderr=False).invoke(
        cli,
        ["--format", "json", "treasury", "transactions", *extra],
        env={"ANTE_MEMBER_TOKEN": ""},
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output
    return [item["id"] for item in json.loads(result.stdout)["data"]["items"]]


def test_same_second_rows_are_newest_insert_first(ledger_db: str) -> None:
    assert _ids() == [4, 3, 2, 1]


def test_pages_cover_every_row_exactly_once(ledger_db: str) -> None:
    first = _ids("--limit", "2", "--offset", "0")
    second = _ids("--limit", "2", "--offset", "2")
    assert first == [4, 3]
    assert second == [2, 1]
    assert set(first) | set(second) == {1, 2, 3, 4}
    assert not set(first) & set(second)
