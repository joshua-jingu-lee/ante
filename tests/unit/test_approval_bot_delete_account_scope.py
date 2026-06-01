"""#2141: bot_delete approval 검증의 account_id 스코핑 회귀 테스트.

``_validate_bot_delete`` 는 봇 row 에서 계좌를 알고 있으므로 보유 포지션 카운트를
``PositionHistory.get_positions_sync(bot_id, account_id=bot.config.account_id)`` 로
봇 계좌에 스코프해야 한다. account_id 없이 호출하면 같은 bot_id 의 타 계좌
stale/legacy 포지션까지 세어 삭제 결재가 잘못 거부될 수 있다 (#2138/2140/2139/
2136/2137 account_id 스코핑 family 와 동형).

main.py 내부 클로저(``_validate_bot_delete``)를 직접 import 할 수 없으므로,
실제 ``_init_approval(s)`` 를 실행해 등록된 validator 를 ApprovalService 에서
꺼내 호출한다. 이렇게 하면 재현 대역이 아니라 실제 코드 경로(클로저가 실제로
account_id 를 전달하는지)를 검증한다.
"""

from __future__ import annotations

import asyncio
import contextlib
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from ante.bot.config import BotConfig, BotStatus
from ante.core.database import Database
from ante.eventbus.bus import EventBus
from ante.main import Services, _init_approval

_ACCOUNT_A = "acc-a"
_ACCOUNT_B = "acc-b"
_BOT_ID = "bot-shared"


@pytest.fixture
async def db(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    await db.connect()
    # Refs #1897: aiosqlite Connection 누수 차단.
    try:
        yield db
    finally:
        await db.close()


@pytest.fixture
async def eventbus():
    return EventBus()


class _FakePositionHistory:
    """get_positions_sync 의 account_id 스코핑을 재현하는 대역.

    실제 ``PositionHistory.get_positions_sync`` 와 동일하게 account_id 가
    주어지면 해당 계좌 포지션만, None 이면 같은 bot_id 의 모든 계좌 포지션을
    반환한다. validator 가 어떤 account_id 로 호출했는지 캡처한다.
    """

    def __init__(self, by_account: dict[str, list]):
        self._by_account = by_account
        self.calls: list[dict] = []

    def get_positions_sync(self, bot_id: str, *, account_id: str | None = None):
        self.calls.append({"bot_id": bot_id, "account_id": account_id})
        if account_id is not None:
            return list(self._by_account.get(account_id, []))
        positions: list = []
        for acct_positions in self._by_account.values():
            positions.extend(acct_positions)
        return positions


def _make_services(
    db: Database,
    eventbus: EventBus,
    *,
    bot_account_id: str,
    bot_status: BotStatus,
    positions_by_account: dict[str, list],
) -> tuple[Services, _FakePositionHistory]:
    """_init_approval 실행에 필요한 최소 mock 으로 채운 Services 를 구성한다."""
    bot = SimpleNamespace(
        bot_id=_BOT_ID,
        status=bot_status,
        config=BotConfig(
            bot_id=_BOT_ID,
            strategy_id="strat-1",
            name=_BOT_ID,
            account_id=bot_account_id,
        ),
    )

    bot_manager = MagicMock()
    bot_manager.get_bot = MagicMock(
        side_effect=lambda bid: bot if bid == _BOT_ID else None
    )

    position_history = _FakePositionHistory(positions_by_account)

    config = MagicMock()
    config.get = MagicMock(return_value={})

    s = Services()
    s.db = db
    s.eventbus = eventbus
    s.config = config
    s.bot_manager = bot_manager
    s.position_history = position_history
    s.account_service = None
    return s, position_history


async def _run_bot_delete_validator(s: Services):
    """_init_approval 을 실제 실행하고 등록된 bot_delete validator 를 호출한다."""
    await _init_approval(s)
    try:
        validator = s.approval_service._validators["bot_delete"]
        return validator({"bot_id": _BOT_ID})
    finally:
        # 만료 스케줄러 task 정리 (DB connection 은 fixture 가 닫는다).
        if s.approval_expire_task is not None:
            s.approval_expire_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await s.approval_expire_task


def _fake_position(symbol: str):
    return SimpleNamespace(
        symbol=symbol,
        quantity=1.0,
        avg_entry_price=100.0,
    )


class TestBotDeleteAccountScope:
    """bot_delete 검증이 봇 계좌로 스코프되는지 회귀 검증."""

    async def test_other_account_positions_do_not_block_delete(self, db, eventbus):
        """봇 계좌(acc-a)엔 포지션이 없고 타 계좌(acc-b)에만 포지션이 있으면
        삭제 검증은 pass 해야 한다 (타 계좌 포지션 때문에 거부하지 않음)."""
        s, position_history = _make_services(
            db,
            eventbus,
            bot_account_id=_ACCOUNT_A,
            bot_status=BotStatus.STOPPED,
            positions_by_account={_ACCOUNT_B: [_fake_position("BBB")]},
        )

        results = await _run_bot_delete_validator(s)

        assert len(results) == 1
        assert results[0].grade == "pass"
        # validator 가 봇 계좌(acc-a)로 스코프해서 조회했는지 확인.
        assert position_history.calls == [{"bot_id": _BOT_ID, "account_id": _ACCOUNT_A}]

    async def test_bot_account_positions_block_delete(self, db, eventbus):
        """봇 계좌(acc-a)에 포지션이 있으면 삭제 검증은 fail 해야 한다."""
        s, position_history = _make_services(
            db,
            eventbus,
            bot_account_id=_ACCOUNT_A,
            bot_status=BotStatus.STOPPED,
            positions_by_account={
                _ACCOUNT_A: [_fake_position("AAA")],
                _ACCOUNT_B: [_fake_position("BBB")],
            },
        )

        results = await _run_bot_delete_validator(s)

        fail_results = [r for r in results if r.grade == "fail"]
        assert len(fail_results) == 1
        # 봇 계좌 포지션 1건만 카운트되어야 한다 (타 계좌 BBB 미포함).
        assert "보유 포지션 1건 존재" in fail_results[0].detail
        assert fail_results[0].reviewer == "system:trade"
        assert position_history.calls == [{"bot_id": _BOT_ID, "account_id": _ACCOUNT_A}]

    async def test_validator_passes_bot_account_id_to_get_positions_sync(
        self, db, eventbus
    ):
        """validator 는 get_positions_sync 를 account_id=봇 계좌로 호출한다.

        (인자 캡처 검증)
        """
        s, position_history = _make_services(
            db,
            eventbus,
            bot_account_id=_ACCOUNT_A,
            bot_status=BotStatus.STOPPED,
            positions_by_account={},
        )

        await _run_bot_delete_validator(s)

        assert position_history.calls == [{"bot_id": _BOT_ID, "account_id": _ACCOUNT_A}]
