"""SystemState 단위 테스트."""

import pytest

from ante.config import SystemState, TradingState
from ante.core import Database
from ante.eventbus.events import TradingStateChangedEvent


class FakeEventBus:
    """테스트용 EventBus 대역."""

    def __init__(self):
        self.published: list = []

    async def publish(self, event):
        self.published.append(event)


@pytest.fixture
async def db(tmp_path):
    database = Database(str(tmp_path / "test.db"))
    await database.connect()
    yield database
    await database.close()


@pytest.fixture
def eventbus():
    return FakeEventBus()


@pytest.fixture
async def state(db, eventbus):
    s = SystemState(db=db, eventbus=eventbus)
    await s.initialize()
    return s


async def test_initial_state_is_active(state):
    """초기 상태는 ACTIVE."""
    assert state.trading_state == TradingState.ACTIVE


async def test_set_state(state):
    """상태 변경이 인메모리에 즉시 반영된다."""
    await state.set_state(TradingState.HALTED, reason="test")
    assert state.trading_state == TradingState.HALTED


async def test_set_state_publishes_event(state, eventbus):
    """상태 변경 시 TradingStateChangedEvent를 발행한다."""
    await state.set_state(TradingState.REDUCING, reason="loss limit")

    assert len(eventbus.published) == 1
    event = eventbus.published[0]
    assert isinstance(event, TradingStateChangedEvent)
    assert event.old_state == "active"
    assert event.new_state == "reducing"
    assert event.reason == "loss limit"


async def test_same_state_no_event(state, eventbus):
    """동일 상태로 변경 시 이벤트를 발행하지 않는다."""
    await state.set_state(TradingState.ACTIVE)
    assert len(eventbus.published) == 0


async def test_state_persists_across_instances(db, eventbus):
    """DB에 영속화되어 새 인스턴스에서 복원된다."""
    state1 = SystemState(db=db, eventbus=eventbus)
    await state1.initialize()
    await state1.set_state(TradingState.HALTED, reason="persist test")

    state2 = SystemState(db=db, eventbus=eventbus)
    await state2.initialize()
    assert state2.trading_state == TradingState.HALTED


async def test_state_history_recorded(state, db):
    """상태 변경 이력이 기록된다."""
    await state.set_state(TradingState.REDUCING, reason="r1", changed_by="cli")
    await state.set_state(TradingState.HALTED, reason="r2", changed_by="web")

    rows = await db.fetch_all("SELECT * FROM system_state_history ORDER BY id")
    assert len(rows) == 2
    assert rows[0]["old_state"] == "active"
    assert rows[0]["new_state"] == "reducing"
    assert rows[1]["old_state"] == "reducing"
    assert rows[1]["new_state"] == "halted"


async def test_trading_state_enum_values():
    """TradingState enum 값 확인."""
    assert TradingState.ACTIVE == "active"
    assert TradingState.REDUCING == "reducing"
    assert TradingState.HALTED == "halted"
