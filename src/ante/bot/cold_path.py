"""Cold-path bot maintenance helpers.

These helpers run only while the Ante server is stopped. They intentionally do
not instantiate ``BotManager`` because no in-memory bot task, EventBus
subscriber, PaperExecutor, or broker adapter exists in cold-path mode.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ante.bot.config import BotStatus
from ante.bot.exceptions import BotNotFoundError

if TYPE_CHECKING:
    from ante.core.database import Database

logger = logging.getLogger(__name__)


async def _release_treasury_budget(
    db: Database,
    *,
    bot_id: str,
    preferred_account_id: str,
) -> float:
    """Release persisted Treasury budget for ``bot_id``.

    Mirrors ``BotManager.delete_bot``: try the bot's account first, then scan
    all persisted budget account ids because legacy or cross-account rows may
    not match ``bots.account_id`` (Refs #982/#1161).
    """
    from ante.eventbus.bus import EventBus
    from ante.treasury.treasury import Treasury

    async def release_for(account_id: str) -> float:
        treasury = Treasury(db=db, eventbus=EventBus(), account_id=account_id)
        await treasury.initialize()
        return await treasury.release_budget(bot_id)

    checked: set[str] = set()
    released = await release_for(preferred_account_id)
    checked.add(preferred_account_id)
    if released > 0:
        return released

    # Legacy rows created before account-scoped budgets may have the migration
    # default ``account_id=''``. Treat those as belonging to the bot row's
    # account before falling back to the cross-account scan, otherwise the blank
    # row can survive a cold-path delete.
    await db.execute(
        "UPDATE bot_budgets SET account_id = ? WHERE bot_id = ? AND account_id = ''",
        (preferred_account_id, bot_id),
    )
    released = await release_for(preferred_account_id)
    if released > 0:
        return released

    rows = await db.fetch_all(
        "SELECT DISTINCT account_id FROM bot_budgets WHERE bot_id = ?",
        (bot_id,),
    )
    for row in rows:
        account_id = row.get("account_id")
        if not account_id:
            continue
        if account_id in checked:
            continue
        released = await release_for(account_id)
        checked.add(account_id)
        if released > 0:
            return released

    return 0.0


async def cold_path_remove_bot(
    db: Database,
    bot_id: str,
    *,
    strategies_dir: Path,
) -> dict[str, Any]:
    """Soft-delete a bot while the Ante server is stopped.

    Cold-path removal is equivalent to hot-path ``handle_positions="keep"``:
    it never liquidates positions because no live broker adapter exists. If the
    persisted bot status is ``running``/``stopping``, that status is treated as
    stale: server tasks and observers are already gone, and the next server boot
    skips ``status='deleted'`` rows.
    """
    from ante.bot.manager import BOT_SCHEMA
    from ante.bot.signal_key import SignalKeyManager
    from ante.strategy.snapshot import StrategySnapshot

    await db.execute_script(BOT_SCHEMA)
    row = await db.fetch_one(
        "SELECT bot_id, account_id, status FROM bots"
        " WHERE bot_id = ? AND status != 'deleted'",
        (bot_id,),
    )
    if row is None:
        raise BotNotFoundError(bot_id)

    account_id = row.get("account_id") or "test"
    previous_status = row.get("status") or BotStatus.CREATED.value

    signal_key_manager = SignalKeyManager(db)
    await signal_key_manager.initialize()
    signal_key_revoked = await signal_key_manager.revoke(bot_id)

    StrategySnapshot(strategies_dir).cleanup(bot_id)

    budget_released = await _release_treasury_budget(
        db,
        bot_id=bot_id,
        preferred_account_id=account_id,
    )

    await db.execute(
        "UPDATE bots SET status = 'deleted', updated_at = datetime('now')"
        " WHERE bot_id = ?",
        (bot_id,),
    )
    logger.info(
        "cold-path 봇 삭제: %s (previous_status=%s, budget_released=%s)",
        bot_id,
        previous_status,
        budget_released,
    )

    return {
        "bot_id": bot_id,
        "removed": True,
        "cold_path": True,
        "previous_status": previous_status,
        "signal_key_revoked": signal_key_revoked,
        "budget_released": budget_released,
    }
