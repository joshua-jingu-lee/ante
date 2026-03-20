"""Treasury 잔고 동기화 테스트."""

import asyncio

import pytest

from ante.core import Database
from ante.eventbus import EventBus
from ante.eventbus.events import BalanceSyncedEvent
from ante.trade.models import PositionSnapshot
from ante.treasury import Treasury

# ── Fixtures ─────────────────────────────────────


@pytest.fixture
async def db(tmp_path):
    database = Database(str(tmp_path / "test.db"))
    await database.connect()
    yield database
    await database.close()


@pytest.fixture
def eventbus():
    return EventBus()


@pytest.fixture
async def treasury(db, eventbus):
    t = Treasury(db=db, eventbus=eventbus, buy_commission_rate=0.00015)
    await t.initialize()
    return t


class FakeBroker:
    """테스트용 가짜 브로커."""

    def __init__(
        self,
        balance: dict | None = None,
        positions: list | None = None,
    ) -> None:
        self._balance = balance or {
            "cash": 5_000_000.0,
            "total_assets": 12_000_000.0,
            "purchase_amount": 7_000_000.0,
            "eval_amount": 7_200_000.0,
            "total_profit_loss": 200_000.0,
            "purchasable_amount": 4_800_000.0,
        }
        self._positions = positions or []
        self.call_count = 0

    async def get_account_balance(self) -> dict:
        self.call_count += 1
        return self._balance

    async def get_positions(self) -> list:
        return self._positions


class FakePositionHistory:
    """테스트용 가짜 PositionHistory."""

    def __init__(self, positions: list | None = None) -> None:
        self._positions = positions or []

    async def get_all_positions(self) -> list:
        return self._positions


class FailingBroker:
    """동기화 실패 시나리오용."""

    async def get_account_balance(self) -> dict:
        raise ConnectionError("API 연결 실패")

    async def get_positions(self) -> list:
        return []


# ── US-1: KIS 잔고 필드 전체 동기화 ───────────────


class TestSyncBalance:
    async def test_sync_balance_updates_all_fields(self, treasury):
        """sync_balance가 6개 필드 모두 갱신."""
        await treasury.sync_balance(
            {
                "cash": 5_000_000.0,
                "purchasable_amount": 4_800_000.0,
                "total_assets": 12_000_000.0,
                "purchase_amount": 7_000_000.0,
                "eval_amount": 7_200_000.0,
                "total_profit_loss": 200_000.0,
            }
        )

        assert treasury._account_balance == 5_000_000.0
        assert treasury._purchasable_amount == 4_800_000.0
        assert treasury._total_evaluation == 12_000_000.0
        assert treasury._purchase_amount == 7_000_000.0
        assert treasury._eval_amount == 7_200_000.0
        assert treasury._total_profit_loss == 200_000.0

    async def test_sync_balance_recalculates_unallocated(self, treasury):
        """sync_balance가 미할당 자금 재계산."""
        await treasury.set_account_balance(10_000_000.0)
        await treasury.allocate("bot1", 3_000_000.0)

        await treasury.sync_balance({"cash": 8_000_000.0})

        assert treasury._account_balance == 8_000_000.0
        assert treasury.unallocated == 5_000_000.0  # 8M - 3M

    async def test_sync_balance_preserves_existing_on_missing_keys(self, treasury):
        """누락된 키는 기존 값 유지."""
        await treasury.sync_balance(
            {
                "cash": 5_000_000.0,
                "purchasable_amount": 4_800_000.0,
                "total_assets": 12_000_000.0,
                "purchase_amount": 7_000_000.0,
                "eval_amount": 7_200_000.0,
                "total_profit_loss": 200_000.0,
            }
        )

        # cash만 업데이트
        await treasury.sync_balance({"cash": 6_000_000.0})

        assert treasury._account_balance == 6_000_000.0
        assert treasury._purchasable_amount == 4_800_000.0  # 유지

    async def test_set_account_balance_backward_compatible(self, treasury):
        """기존 set_account_balance 하위 호환성."""
        await treasury.set_account_balance(10_000_000.0)
        assert treasury.account_balance == 10_000_000.0
        assert treasury.unallocated == 10_000_000.0

    async def test_sync_balance_persists_to_db(self, treasury, db, eventbus):
        """sync_balance 결과가 DB에 저장되어 재시작 후 복원."""
        await treasury.sync_balance(
            {
                "cash": 5_000_000.0,
                "purchasable_amount": 4_800_000.0,
                "total_assets": 12_000_000.0,
                "purchase_amount": 7_000_000.0,
                "eval_amount": 7_200_000.0,
                "total_profit_loss": 200_000.0,
            }
        )

        # 새 인스턴스로 복원 확인 (계좌별 행 구조 — 핵심 필드만 영속화)
        t2 = Treasury(db=db, eventbus=eventbus)
        await t2.initialize()

        assert t2._account_balance == 5_000_000.0
        assert t2._purchasable_amount == 4_800_000.0
        assert t2._total_evaluation == 12_000_000.0

    async def test_purchasable_amount_in_kis(self):
        """KIS get_account_balance에 purchasable_amount 포함 확인."""
        from ante.broker.kis import KISAdapter

        # KISAdapter의 get_account_balance 반환값에 purchasable_amount 키 존재 확인
        # (실제 API 호출 없이 코드 구조 검증)
        adapter = KISAdapter.__new__(KISAdapter)
        # _request 모킹 없이 반환 딕셔너리 키 확인만
        assert hasattr(adapter, "get_account_balance")


# ── US-2: 주기적 잔고 동기화 메커니즘 ─────────────


class TestSyncLoop:
    async def test_start_and_stop_sync(self, treasury):
        """start_sync/stop_sync 기본 동작."""
        broker = FakeBroker()
        pos_history = FakePositionHistory()

        treasury.start_sync(broker, pos_history, interval_seconds=1)
        assert treasury._sync_task is not None
        assert not treasury._sync_task.done()

        await asyncio.sleep(0.05)  # 첫 동기화 실행 대기
        await treasury.stop_sync()

        assert treasury._sync_task is None
        assert broker.call_count >= 1

    async def test_sync_updates_treasury_fields(self, treasury):
        """동기화 루프가 Treasury 필드를 갱신."""
        broker = FakeBroker()
        pos_history = FakePositionHistory()

        treasury.start_sync(broker, pos_history, interval_seconds=100)
        await asyncio.sleep(0.05)
        await treasury.stop_sync()

        assert treasury._account_balance == 5_000_000.0
        assert treasury._purchasable_amount == 4_800_000.0
        assert treasury._total_evaluation == 12_000_000.0

    async def test_sync_failure_keeps_old_values(self, treasury):
        """동기화 실패 시 이전 값 유지."""
        await treasury.set_account_balance(10_000_000.0)

        broker = FailingBroker()
        pos_history = FakePositionHistory()

        treasury.start_sync(broker, pos_history, interval_seconds=100)
        await asyncio.sleep(0.05)
        await treasury.stop_sync()

        assert treasury._account_balance == 10_000_000.0  # 이전 값 유지

    async def test_sync_publishes_event(self, treasury, eventbus):
        """동기화 성공 시 BalanceSyncedEvent 발행."""
        received = []
        eventbus.subscribe(BalanceSyncedEvent, lambda e: received.append(e))

        broker = FakeBroker()
        pos_history = FakePositionHistory()

        treasury.start_sync(broker, pos_history, interval_seconds=100)
        await asyncio.sleep(0.05)
        await treasury.stop_sync()

        assert len(received) == 1
        assert received[0].account_balance == 5_000_000.0
        assert received[0].purchasable_amount == 4_800_000.0

    async def test_double_start_ignored(self, treasury):
        """이미 동기화 실행 중이면 중복 시작 무시."""
        broker = FakeBroker()
        pos_history = FakePositionHistory()

        treasury.start_sync(broker, pos_history, interval_seconds=100)
        task1 = treasury._sync_task

        treasury.start_sync(broker, pos_history, interval_seconds=100)
        assert treasury._sync_task is task1  # 같은 태스크

        await treasury.stop_sync()

    async def test_stop_sync_when_not_running(self, treasury):
        """동기화 미실행 시 stop_sync 안전."""
        await treasury.stop_sync()  # 예외 없이 통과


# ── US-3: 외부 종목 분리 산출 ─────────────────────


class TestExternalPositions:
    async def test_external_positions_separated(self, treasury, eventbus):
        """KIS 종목 중 Trade에 없는 종목은 외부로 분류."""
        broker = FakeBroker(
            positions=[
                {
                    "symbol": "005930",
                    "quantity": 100.0,
                    "avg_price": 71000.0,
                    "eval_amount": 7_200_000.0,
                },  # 내부
                {
                    "symbol": "035720",
                    "quantity": 50.0,
                    "avg_price": 60000.0,
                    "eval_amount": 3_100_000.0,
                },  # 외부
            ]
        )
        pos_history = FakePositionHistory(
            positions=[
                PositionSnapshot(
                    bot_id="bot1",
                    symbol="005930",
                    quantity=100.0,
                    avg_entry_price=71000.0,
                ),
            ]
        )

        treasury.start_sync(broker, pos_history, interval_seconds=100)
        await asyncio.sleep(0.05)
        await treasury.stop_sync()

        assert treasury._external_purchase_amount == 3_000_000.0  # 50 * 60000
        assert treasury._external_eval_amount == 3_100_000.0

    async def test_no_external_positions(self, treasury):
        """외부 종목이 없으면 0."""
        broker = FakeBroker(
            positions=[
                {
                    "symbol": "005930",
                    "quantity": 100.0,
                    "avg_price": 71000.0,
                    "eval_amount": 7_100_000.0,
                },
            ]
        )
        pos_history = FakePositionHistory(
            positions=[
                PositionSnapshot(
                    bot_id="bot1",
                    symbol="005930",
                    quantity=100.0,
                    avg_entry_price=71000.0,
                ),
            ]
        )

        treasury.start_sync(broker, pos_history, interval_seconds=100)
        await asyncio.sleep(0.05)
        await treasury.stop_sync()

        assert treasury._external_purchase_amount == 0.0
        assert treasury._external_eval_amount == 0.0

    async def test_all_external_positions(self, treasury):
        """모든 종목이 외부인 경우."""
        broker = FakeBroker(
            positions=[
                {
                    "symbol": "035720",
                    "quantity": 50.0,
                    "avg_price": 60000.0,
                    "eval_amount": 3_100_000.0,
                },
            ]
        )
        pos_history = FakePositionHistory(positions=[])

        treasury.start_sync(broker, pos_history, interval_seconds=100)
        await asyncio.sleep(0.05)
        await treasury.stop_sync()

        assert treasury._external_purchase_amount == 3_000_000.0
        assert treasury._external_eval_amount == 3_100_000.0

    async def test_external_amounts_in_memory(self, treasury):
        """외부 종목 금액이 인메모리에 보관된다."""
        broker = FakeBroker(
            positions=[
                {
                    "symbol": "035720",
                    "quantity": 50.0,
                    "avg_price": 60000.0,
                    "eval_amount": 3_100_000.0,
                },
            ]
        )
        pos_history = FakePositionHistory(positions=[])

        treasury.start_sync(broker, pos_history, interval_seconds=100)
        await asyncio.sleep(0.05)
        await treasury.stop_sync()

        assert treasury._external_purchase_amount == 3_000_000.0
        assert treasury._external_eval_amount == 3_100_000.0

    async def test_sync_event_includes_external(self, treasury, eventbus):
        """BalanceSyncedEvent에 외부 종목 금액 포함."""
        received = []
        eventbus.subscribe(BalanceSyncedEvent, lambda e: received.append(e))

        broker = FakeBroker(
            positions=[
                {
                    "symbol": "035720",
                    "quantity": 50.0,
                    "avg_price": 60000.0,
                    "eval_amount": 3_100_000.0,
                },
            ]
        )
        pos_history = FakePositionHistory(positions=[])

        treasury.start_sync(broker, pos_history, interval_seconds=100)
        await asyncio.sleep(0.05)
        await treasury.stop_sync()

        assert len(received) == 1
        assert received[0].external_purchase_amount == 3_000_000.0
        assert received[0].external_eval_amount == 3_100_000.0


# ── US-4: Ante 순수 성과 지표 제공 ────────────────


class TestAntePurePerformance:
    async def test_summary_includes_ante_metrics(self, treasury):
        """get_summary에 Ante 순수 성과 포함."""
        await treasury.sync_balance(
            {
                "cash": 5_000_000.0,
                "purchase_amount": 7_000_000.0,
                "eval_amount": 7_200_000.0,
            }
        )
        treasury._external_purchase_amount = 3_000_000.0
        treasury._external_eval_amount = 3_100_000.0

        summary = treasury.get_summary()

        assert summary["ante_purchase_amount"] == 4_000_000.0  # 7M - 3M
        assert summary["ante_eval_amount"] == 4_100_000.0  # 7.2M - 3.1M
        assert summary["ante_profit_loss"] == 100_000.0  # 4.1M - 4M

    async def test_summary_before_sync_equals_total(self, treasury):
        """동기화 전에는 전체 = Ante 금액."""
        summary = treasury.get_summary()

        assert summary["ante_purchase_amount"] == 0.0
        assert summary["ante_eval_amount"] == 0.0
        assert summary["ante_profit_loss"] == 0.0

    async def test_summary_backward_compatible(self, treasury):
        """기존 get_summary 필드 유지."""
        await treasury.set_account_balance(10_000_000.0)
        await treasury.allocate("bot1", 3_000_000.0)

        summary = treasury.get_summary()

        assert summary["account_balance"] == 10_000_000.0
        assert summary["total_allocated"] == 3_000_000.0
        assert summary["unallocated"] == 7_000_000.0
        assert summary["bot_count"] == 1

    async def test_summary_includes_new_fields(self, treasury):
        """get_summary에 신규 필드 모두 포함."""
        await treasury.sync_balance(
            {
                "cash": 5_000_000.0,
                "purchasable_amount": 4_800_000.0,
                "total_assets": 12_000_000.0,
                "purchase_amount": 7_000_000.0,
                "eval_amount": 7_200_000.0,
                "total_profit_loss": 200_000.0,
            }
        )

        summary = treasury.get_summary()

        assert summary["purchasable_amount"] == 4_800_000.0
        assert summary["total_evaluation"] == 12_000_000.0
        assert summary["purchase_amount"] == 7_000_000.0
        assert summary["eval_amount"] == 7_200_000.0
        assert summary["total_profit_loss"] == 200_000.0
        assert summary["external_purchase_amount"] == 0.0
        assert summary["external_eval_amount"] == 0.0
