"""Refs #2143 — BOT_SCHEMA ``account_id`` NOT NULL (no DEFAULT) 검증.

스펙(bot/03-design-decisions + account/14-account-id-contract)은
``account_id TEXT NOT NULL`` (DEFAULT 없음). 이전 ``DEFAULT 'test'`` 는
계좌 누락 row 를 실패시키지 않고 'test' 로 귀속시키는 버그였다.
"""

from __future__ import annotations

import sqlite3

import pytest

from ante.bot.manager import BOT_SCHEMA


@pytest.fixture
def conn() -> sqlite3.Connection:
    """BOT_SCHEMA 로 생성한 fresh in-memory DB."""
    connection = sqlite3.connect(":memory:")
    connection.executescript(BOT_SCHEMA)
    yield connection
    connection.close()


def test_insert_without_account_id_raises_integrity_error(
    conn: sqlite3.Connection,
) -> None:
    """account_id 없이 insert 하면 NOT NULL(no default) 위반으로 실패한다.

    이전 ``DEFAULT 'test'`` 라면 'test' 로 silent 귀속됐을 row 가
    이제 결정적으로 거부된다.
    """
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """INSERT INTO bots (bot_id, strategy_id, config_json)
               VALUES (?, ?, ?)""",
            ("bot-1", "strat", "{}"),
        )


def test_insert_with_account_id_succeeds(conn: sqlite3.Connection) -> None:
    """account_id 를 명시한 insert 는 정상 성공한다(회귀 방지)."""
    conn.execute(
        """INSERT INTO bots (bot_id, strategy_id, account_id, config_json)
           VALUES (?, ?, ?, ?)""",
        ("bot-1", "strat", "acct-1", "{}"),
    )
    row = conn.execute(
        "SELECT account_id FROM bots WHERE bot_id = ?",
        ("bot-1",),
    ).fetchone()
    assert row == ("acct-1",)


def test_account_id_has_no_column_default(conn: sqlite3.Connection) -> None:
    """``PRAGMA table_info`` 에서 account_id 의 dflt_value 는 None 이다.

    이전 ``DEFAULT 'test'`` 가 사라졌음을 컬럼 메타데이터로 확인한다.
    """
    columns = {
        row[1]: row for row in conn.execute("PRAGMA table_info(bots)").fetchall()
    }
    account_id_col = columns["account_id"]
    # PRAGMA table_info: (cid, name, type, notnull, dflt_value, pk)
    notnull = account_id_col[3]
    dflt_value = account_id_col[4]
    assert notnull == 1
    assert dflt_value is None
