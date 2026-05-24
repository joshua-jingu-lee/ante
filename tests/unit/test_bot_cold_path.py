"""Refs #1161 — bot remove cold-path cleanup tests."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from ante.core import Database


@pytest.fixture
async def db(tmp_path: Path):
    database = Database(str(tmp_path / "ante.db"))
    await database.connect()
    yield database
    await asyncio.wait_for(database.close(), timeout=5.0)


async def _insert_bot(
    db: Database,
    *,
    bot_id: str = "bot-1",
    account_id: str = "test",
    status: str = "created",
) -> None:
    from ante.bot.manager import BOT_SCHEMA

    await db.execute_script(BOT_SCHEMA)
    await db.execute(
        """INSERT INTO bots
           (bot_id, name, strategy_id, account_id, config_json, status)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (bot_id, "테스트봇", "strat", account_id, "{}", status),
    )


async def test_cold_path_remove_cleans_persisted_state(
    db: Database,
    tmp_path: Path,
) -> None:
    """cold-path remove는 signal key, snapshot, treasury budget, bot row를 정리한다."""
    from ante.bot.cold_path import cold_path_remove_bot
    from ante.bot.signal_key import SignalKeyManager
    from ante.eventbus import EventBus
    from ante.treasury.treasury import Treasury

    await _insert_bot(db, status="running")

    signal_keys = SignalKeyManager(db)
    await signal_keys.initialize()
    await signal_keys.generate("bot-1")

    strategies_dir = tmp_path / "strategies"
    snapshot_dir = strategies_dir / ".running" / "bot-1"
    snapshot_dir.mkdir(parents=True)
    (snapshot_dir / "strategy.py").write_text("x = 1\n")

    treasury = Treasury(db=db, eventbus=EventBus(), account_id="test")
    await treasury.initialize()
    await treasury.set_account_balance(1_000_000)
    await treasury.allocate("bot-1", 250_000)
    result = await cold_path_remove_bot(db, "bot-1", strategies_dir=strategies_dir)

    assert result["removed"] is True
    assert result["cold_path"] is True
    assert result["previous_status"] == "running"
    assert result["signal_key_revoked"] is True
    assert result["budget_released"] == 250_000

    bot_row = await db.fetch_one("SELECT status FROM bots WHERE bot_id = ?", ("bot-1",))
    assert bot_row == {"status": "deleted"}
    assert await signal_keys.get_key("bot-1") is None
    assert (
        await db.fetch_one("SELECT * FROM bot_budgets WHERE bot_id = ?", ("bot-1",))
        is None
    )
    assert not snapshot_dir.exists()

    release_rows = await db.fetch_all(
        "SELECT * FROM treasury_transactions"
        " WHERE bot_id = ? AND transaction_type = 'release'",
        ("bot-1",),
    )
    assert len(release_rows) == 1


async def test_cold_path_remove_releases_cross_account_budget(
    db: Database,
    tmp_path: Path,
) -> None:
    """bot row account와 budget account가 달라도 persisted budget을 찾아 환수한다."""
    from ante.bot.cold_path import cold_path_remove_bot
    from ante.eventbus import EventBus
    from ante.treasury.treasury import Treasury

    await _insert_bot(db, account_id="bot-account")
    treasury = Treasury(db=db, eventbus=EventBus(), account_id="budget-account")
    await treasury.initialize()
    await treasury.set_account_balance(500_000)
    await treasury.allocate("bot-1", 100_000)
    result = await cold_path_remove_bot(
        db,
        "bot-1",
        strategies_dir=tmp_path / "strategies",
    )

    assert result["budget_released"] == 100_000
    assert (
        await db.fetch_one("SELECT * FROM bot_budgets WHERE bot_id = ?", ("bot-1",))
        is None
    )


async def test_cold_path_remove_releases_legacy_empty_account_budget(
    db: Database,
    tmp_path: Path,
) -> None:
    """마이그레이션 기본값 account_id='' budget도 bot row 계좌로 환수한다."""
    from ante.bot.cold_path import cold_path_remove_bot
    from ante.eventbus import EventBus
    from ante.treasury.treasury import Treasury

    await _insert_bot(db, account_id="bot-account")
    treasury = Treasury(db=db, eventbus=EventBus(), account_id="bot-account")
    await treasury.initialize()
    await treasury.set_account_balance(500_000)
    await treasury.allocate("bot-1", 120_000)
    await db.execute(
        "UPDATE bot_budgets SET account_id = '' WHERE bot_id = ?",
        ("bot-1",),
    )

    result = await cold_path_remove_bot(
        db,
        "bot-1",
        strategies_dir=tmp_path / "strategies",
    )

    assert result["budget_released"] == 120_000
    assert (
        await db.fetch_one("SELECT * FROM bot_budgets WHERE bot_id = ?", ("bot-1",))
        is None
    )

    release = await db.fetch_one(
        "SELECT account_id FROM treasury_transactions"
        " WHERE bot_id = ? AND transaction_type = 'release'",
        ("bot-1",),
    )
    assert release == {"account_id": "bot-account"}


async def test_cold_path_remove_missing_bot_raises_bot_not_found(
    db: Database,
    tmp_path: Path,
) -> None:
    """존재하지 않거나 deleted 상태인 bot은 BOT_NOT_FOUND로 실패한다."""
    from ante.bot.cold_path import cold_path_remove_bot
    from ante.bot.exceptions import BOT_NOT_FOUND_CODE, BotNotFoundError

    with pytest.raises(BotNotFoundError) as exc_info:
        await cold_path_remove_bot(
            db,
            "missing",
            strategies_dir=tmp_path / "strategies",
        )

    assert exc_info.value.code == BOT_NOT_FOUND_CODE
    assert "missing" in str(exc_info.value)


async def test_cold_path_remove_invalid_account_id_rejects(
    db: Database,
    tmp_path: Path,
) -> None:
    """Refs #1241 SPLIT-2: bot row 의 account_id 가 invalid 면
    ``InvalidAccountIdError`` 로 거부한다.

    legacy row 의 ``"default"`` 또는 빈 문자열 account_id 는 잘못된 계좌의
    Treasury 환수 / 잘못된 cleanup 경로를 발생시킬 수 있어, ``or "test"``
    fallback 을 제거하고 명시적으로 거부한다.
    """
    from ante.account.errors import InvalidAccountIdError
    from ante.bot.cold_path import cold_path_remove_bot

    # invalid: 'default' 예약어
    await _insert_bot(db, account_id="default")

    with pytest.raises(InvalidAccountIdError, match="account_id"):
        await cold_path_remove_bot(
            db,
            "bot-1",
            strategies_dir=tmp_path / "strategies",
        )
