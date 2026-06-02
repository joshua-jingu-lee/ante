"""``treasury.allocate``/``treasury.deallocate`` IPC cross-account 가드 (#2128).

요청자가 ``bot_id`` 와 다른 ``account_id`` 를 보내면 잘못된 account_id 가
``treasury_manager.get(...)`` → ``Treasury.allocate/deallocate(...)`` 로 흘러
다른 계좌의 예산이 변경되는 cross-account corruption 이 발생한다.

#2128 fix: ``_handle_broker_reconcile`` (Refs #1240 P2-1) 의 account 일치 가드를
1:1 미러해, ``BotNotFoundError`` 가드 직후 / ``treasury_manager.get`` 이전에
``bot.config.account_id`` 와 요청 ``account_id`` 를 비교하여 불일치 시
``InvalidAccountIdError`` (code="VALIDATION_ERROR", #1633 SSOT) 로 거부한다.

검증축 (이슈 #2128 Verification a~e):

a. allocate: bot.config.account_id=acc-a, 요청 acc-b → ``InvalidAccountIdError``
   + ``treasury.allocate`` 미호출
b. deallocate: 동일
c. account 일치 (acc-a/acc-a) → 정상 allocate/deallocate 도달
d. bot None → ``BotNotFoundError`` (기존 #1792 회귀 보존)
e. bot.config.account_id=None (legacy) → 차단하지 않음 (reconcile 와 동형)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from ante.account.errors import InvalidAccountIdError
from ante.bot.exceptions import BotNotFoundError
from ante.ipc.registry import (
    _handle_treasury_allocate,
    _handle_treasury_deallocate,
)


def _make_svc(*, bot: object | None) -> MagicMock:
    """allocate/deallocate handler 직접 호출용 mock ServiceRegistry.

    ``bot`` 이 None 이면 ``get_bot`` 이 None 을 반환(BotNotFoundError 분기),
    아니면 해당 bot 을 반환한다.
    """
    fake_bot_manager = MagicMock()
    fake_bot_manager.get_bot.return_value = bot

    fake_treasury = MagicMock()
    fake_treasury.allocate = AsyncMock(return_value=True)
    fake_treasury.deallocate = AsyncMock(return_value=True)
    fake_treasury_manager = MagicMock()
    fake_treasury_manager.get.return_value = fake_treasury

    svc = MagicMock()
    svc.bot_manager = fake_bot_manager
    svc.treasury_manager = fake_treasury_manager
    return svc


def _bot_with_account(account_id: str | None) -> MagicMock:
    fake_bot = MagicMock()
    fake_bot.config = MagicMock()
    fake_bot.config.account_id = account_id
    return fake_bot


# ── 축 a: allocate mismatch 거부 ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_allocate_rejects_account_mismatch() -> None:
    svc = _make_svc(bot=_bot_with_account("acc-a"))

    with pytest.raises(InvalidAccountIdError, match="acc-a"):
        await _handle_treasury_allocate(
            svc,
            {"bot_id": "bot-1", "account_id": "acc-b", "amount": 1000.0},
            "cli-user",
        )

    # treasury_manager.get / Treasury.allocate 까지 절대 도달하지 않아야 한다.
    svc.treasury_manager.get.assert_not_called()
    svc.treasury_manager.get.return_value.allocate.assert_not_called()


# ── 축 b: deallocate mismatch 거부 ───────────────────────────────────────


@pytest.mark.asyncio
async def test_deallocate_rejects_account_mismatch() -> None:
    svc = _make_svc(bot=_bot_with_account("acc-a"))

    with pytest.raises(InvalidAccountIdError, match="acc-a"):
        await _handle_treasury_deallocate(
            svc,
            {"bot_id": "bot-1", "account_id": "acc-b", "amount": 1000.0},
            "cli-user",
        )

    svc.treasury_manager.get.assert_not_called()
    svc.treasury_manager.get.return_value.deallocate.assert_not_called()


# ── 축 b': deallocate context 문자열 확인 ───────────────────────────────


@pytest.mark.asyncio
async def test_deallocate_mismatch_uses_deallocate_context() -> None:
    """deallocate 가드의 에러 메시지 context 는 ``ipc.treasury.deallocate``."""
    svc = _make_svc(bot=_bot_with_account("acc-a"))

    with pytest.raises(InvalidAccountIdError, match=r"ipc\.treasury\.deallocate"):
        await _handle_treasury_deallocate(
            svc,
            {"bot_id": "bot-1", "account_id": "acc-b", "amount": 1000.0},
            "cli-user",
        )


@pytest.mark.asyncio
async def test_allocate_mismatch_uses_allocate_context() -> None:
    """allocate 가드의 에러 메시지 context 는 ``ipc.treasury.allocate``."""
    svc = _make_svc(bot=_bot_with_account("acc-a"))

    with pytest.raises(InvalidAccountIdError, match=r"ipc\.treasury\.allocate"):
        await _handle_treasury_allocate(
            svc,
            {"bot_id": "bot-1", "account_id": "acc-b", "amount": 1000.0},
            "cli-user",
        )


# ── 축 c: account 일치 → 정상 도달 ──────────────────────────────────────


@pytest.mark.asyncio
async def test_allocate_passes_when_account_matches() -> None:
    svc = _make_svc(bot=_bot_with_account("acc-a"))

    result = await _handle_treasury_allocate(
        svc,
        {"bot_id": "bot-1", "account_id": "acc-a", "amount": 1000.0},
        "cli-user",
    )

    assert result == {"account_id": "acc-a", "bot_id": "bot-1", "success": True}
    svc.treasury_manager.get.assert_called_once_with("acc-a")
    svc.treasury_manager.get.return_value.allocate.assert_awaited_once_with(
        "bot-1", 1000.0
    )


@pytest.mark.asyncio
async def test_deallocate_passes_when_account_matches() -> None:
    svc = _make_svc(bot=_bot_with_account("acc-a"))

    result = await _handle_treasury_deallocate(
        svc,
        {"bot_id": "bot-1", "account_id": "acc-a", "amount": 1000.0},
        "cli-user",
    )

    assert result == {"account_id": "acc-a", "bot_id": "bot-1", "success": True}
    svc.treasury_manager.get.assert_called_once_with("acc-a")
    svc.treasury_manager.get.return_value.deallocate.assert_awaited_once_with(
        "bot-1", 1000.0
    )


# ── 축 d: bot None → BotNotFoundError (기존 #1792 회귀 보존) ────────────


@pytest.mark.asyncio
async def test_allocate_missing_bot_raises_bot_not_found() -> None:
    svc = _make_svc(bot=None)

    with pytest.raises(BotNotFoundError):
        await _handle_treasury_allocate(
            svc,
            {"bot_id": "unknown-bot", "account_id": "acc-a", "amount": 1000.0},
            "cli-user",
        )

    svc.treasury_manager.get.assert_not_called()


@pytest.mark.asyncio
async def test_deallocate_missing_bot_raises_bot_not_found() -> None:
    svc = _make_svc(bot=None)

    with pytest.raises(BotNotFoundError):
        await _handle_treasury_deallocate(
            svc,
            {"bot_id": "unknown-bot", "account_id": "acc-a", "amount": 1000.0},
            "cli-user",
        )

    svc.treasury_manager.get.assert_not_called()


# ── 축 e: legacy bot.config.account_id=None → 차단하지 않음 ─────────────


@pytest.mark.asyncio
async def test_allocate_legacy_none_account_id_not_blocked() -> None:
    """legacy bot(config.account_id=None)은 mismatch 가드가 차단하지 않는다.

    reconcile 의 ``and bot_account_id`` None-safe 가드와 동형 — None 이면
    비교를 건너뛰고 정상 경로(``treasury.allocate`` 도달)로 진행한다.
    """
    svc = _make_svc(bot=_bot_with_account(None))

    result = await _handle_treasury_allocate(
        svc,
        {"bot_id": "bot-1", "account_id": "acc-a", "amount": 1000.0},
        "cli-user",
    )

    assert result == {"account_id": "acc-a", "bot_id": "bot-1", "success": True}
    svc.treasury_manager.get.return_value.allocate.assert_awaited_once_with(
        "bot-1", 1000.0
    )


@pytest.mark.asyncio
async def test_deallocate_legacy_none_account_id_not_blocked() -> None:
    svc = _make_svc(bot=_bot_with_account(None))

    result = await _handle_treasury_deallocate(
        svc,
        {"bot_id": "bot-1", "account_id": "acc-a", "amount": 1000.0},
        "cli-user",
    )

    assert result == {"account_id": "acc-a", "bot_id": "bot-1", "success": True}
    svc.treasury_manager.get.return_value.deallocate.assert_awaited_once_with(
        "bot-1", 1000.0
    )
