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
    t = Treasury(
        db=db, eventbus=eventbus, buy_commission_rate=0.00015, account_id="acc-test"
    )
    await t.initialize()
    return t


class FakeBroker:
    """테스트용 가짜 브로커.

    #2384: get_account_balance는 purchasable_amount 키를 더 이상 포함하지 않으며
    (substitute_amount로 대체), purchasable_amount는 get_buyable의
    order_buyable_amount로 별도 주입된다. 본 Fake도 새 _do_sync write-path를
    따라 get_buyable stub을 제공한다(BrokerAdapter subclass는 아니다).
    """

    def __init__(
        self,
        balance: dict | None = None,
        positions: list | None = None,
        buyable_amount: float = 4_800_000.0,
    ) -> None:
        self._balance = balance or {
            "cash": 5_000_000.0,
            "total_assets": 12_000_000.0,
            "purchase_amount": 7_000_000.0,
            "eval_amount": 7_200_000.0,
            "total_profit_loss": 200_000.0,
            "substitute_amount": 0.0,
        }
        self._positions = positions or []
        self._buyable_amount = buyable_amount
        self.call_count = 0
        self.buyable_call_count = 0
        self.last_buyable_symbol: str | None = None

    async def get_account_balance(self) -> dict:
        self.call_count += 1
        return self._balance

    async def get_buyable(
        self,
        symbol: str,
        price: float | None = None,
        order_type: str = "market",
    ) -> dict:
        self.buyable_call_count += 1
        self.last_buyable_symbol = symbol
        return {
            "order_buyable_amount": self._buyable_amount,
            "max_buyable_amount": self._buyable_amount,
            "order_cash": self._balance.get("cash", 0.0),
            "order_buyable_qty": 0.0,
            "max_buyable_qty": 0.0,
        }

    async def get_positions(self) -> list:
        return self._positions


class FakePositionHistory:
    """테스트용 가짜 PositionHistory."""

    def __init__(self, positions: list | None = None) -> None:
        self._positions = positions or []
        self.last_account_id: str | None = "__unset__"  # type: ignore[assignment]

    async def get_all_positions(self, *, account_id: str | None = None) -> list:
        # 호출 시 전달된 account_id 캡처 (테스트 검증용).
        self.last_account_id = account_id
        if account_id is None:
            return list(self._positions)
        return [
            p for p in self._positions if getattr(p, "account_id", None) == account_id
        ]


class FailingBroker:
    """동기화 실패 시나리오용 (get_account_balance 실패)."""

    async def get_account_balance(self) -> dict:
        raise ConnectionError("API 연결 실패")

    async def get_buyable(
        self,
        symbol: str,
        price: float | None = None,
        order_type: str = "market",
    ) -> dict:
        raise ConnectionError("매수가능 조회 실패")

    async def get_positions(self) -> list:
        return []


class BuyableFailingBroker(FakeBroker):
    """get_account_balance는 성공하나 get_buyable만 실패하는 시나리오용 (#2384 G7)."""

    async def get_buyable(
        self,
        symbol: str,
        price: float | None = None,
        order_type: str = "market",
    ) -> dict:
        self.buyable_call_count += 1
        raise ConnectionError("매수가능 조회 실패")


# ── US-1: KIS 잔고 필드 전체 동기화 ───────────────


class TestSyncBalance:
    async def test_sync_balance_updates_all_fields(self, treasury):
        """sync_balance가 잔고 필드를 갱신하되 purchasable_amount는 미반영 (#2384)."""
        # 사전 주입된 purchasable_amount (get_buyable write-path 모사)
        treasury._purchasable_amount = 99_000.0

        await treasury.sync_balance(
            {
                "cash": 5_000_000.0,
                "total_assets": 12_000_000.0,
                "purchase_amount": 7_000_000.0,
                "eval_amount": 7_200_000.0,
                "total_profit_loss": 200_000.0,
            }
        )

        assert treasury._account_balance == 5_000_000.0
        assert treasury._total_evaluation == 12_000_000.0
        assert treasury._purchase_amount == 7_000_000.0
        assert treasury._eval_amount == 7_200_000.0
        assert treasury._total_profit_loss == 200_000.0
        # #2384: sync_balance는 purchasable_amount를 읽지 않으므로 기존값 불변.
        assert treasury._purchasable_amount == 99_000.0

    async def test_sync_balance_ignores_purchasable_amount(self, treasury):
        """sync_balance에 purchasable_amount를 넘겨도 반영하지 않는다 (#2384 G2)."""
        treasury._purchasable_amount = 12_345.0
        # 레거시 호출자가 purchasable_amount를 넣어도 무시되는 새 계약 고정.
        await treasury.sync_balance(
            {"cash": 5_000_000.0, "purchasable_amount": 4_800_000.0}
        )
        assert treasury._account_balance == 5_000_000.0
        assert treasury._purchasable_amount == 12_345.0  # 미반영

    async def test_sync_balance_recalculates_unallocated(self, treasury):
        """sync_balance가 미할당 자금 재계산."""
        await treasury.set_account_balance(10_000_000.0)
        await treasury.allocate("bot1", 3_000_000.0)

        await treasury.sync_balance({"cash": 8_000_000.0})

        assert treasury._account_balance == 8_000_000.0
        assert treasury.unallocated == 5_000_000.0  # 8M - 3M

    async def test_sync_balance_preserves_existing_on_missing_keys(self, treasury):
        """누락된 키는 기존 값 유지 (purchasable_amount는 sync_balance 무관)."""
        treasury._purchasable_amount = 4_800_000.0  # get_buyable write-path 모사
        await treasury.sync_balance(
            {
                "cash": 5_000_000.0,
                "total_assets": 12_000_000.0,
                "purchase_amount": 7_000_000.0,
                "eval_amount": 7_200_000.0,
                "total_profit_loss": 200_000.0,
            }
        )

        # cash만 업데이트
        await treasury.sync_balance({"cash": 6_000_000.0})

        assert treasury._account_balance == 6_000_000.0
        # #2384: purchasable_amount는 sync_balance가 건드리지 않으므로 유지.
        assert treasury._purchasable_amount == 4_800_000.0  # 유지

    async def test_set_account_balance_backward_compatible(self, treasury):
        """기존 set_account_balance 하위 호환성."""
        await treasury.set_account_balance(10_000_000.0)
        assert treasury.account_balance == 10_000_000.0
        assert treasury.unallocated == 10_000_000.0

    async def test_sync_balance_persists_to_db(self, treasury, db, eventbus):
        """sync_balance 결과가 DB에 저장되어 재시작 후 복원."""
        # purchasable_amount는 get_buyable write-path로 채워지는 값을 모사.
        treasury._purchasable_amount = 4_800_000.0
        await treasury.sync_balance(
            {
                "cash": 5_000_000.0,
                "total_assets": 12_000_000.0,
                "purchase_amount": 7_000_000.0,
                "eval_amount": 7_200_000.0,
                "total_profit_loss": 200_000.0,
            }
        )

        # 새 인스턴스로 복원 확인 (계좌별 행 구조 — 핵심 필드만 영속화)
        t2 = Treasury(db=db, eventbus=eventbus, account_id="acc-test")
        await t2.initialize()

        assert t2._account_balance == 5_000_000.0
        assert t2._purchasable_amount == 4_800_000.0
        assert t2._total_evaluation == 12_000_000.0

    async def test_purchasable_amount_in_kis(self):
        """#2384: KIS get_account_balance는 psbl_sbst_amt를 substitute_amount로
        매핑하고 purchasable_amount 키를 포함하지 않는다."""
        from unittest.mock import AsyncMock

        from ante.broker.kis import KISAdapter

        adapter = KISAdapter.__new__(KISAdapter)
        adapter.base_url = "https://example.test"  # type: ignore[attr-defined]
        adapter.is_paper = True  # type: ignore[attr-defined]
        # inquire-balance(output2) 응답을 모킹.
        adapter._request = AsyncMock(  # type: ignore[method-assign]
            return_value={
                "rt_cd": "0",
                "output2": [
                    {
                        "dnca_tot_amt": "5000000",
                        "tot_evlu_amt": "12000000",
                        "pchs_amt_smtl_amt": "7000000",
                        "evlu_amt_smtl_amt": "7200000",
                        "evlu_pfls_smtl_amt": "200000",
                        "psbl_sbst_amt": "321000",
                    }
                ],
            }
        )
        adapter._balance_params = lambda: {}  # type: ignore[method-assign]

        balance = await adapter.get_account_balance()

        # psbl_sbst_amt → substitute_amount (대용가능금액 보존)
        assert balance["substitute_amount"] == 321_000.0
        # purchasable_amount(주문가능액) 키는 제거 — get_buyable이 SSOT (#2384)
        assert "purchasable_amount" not in balance


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
        """동기화 루프가 필드를 갱신 (purchasable_amount는 get_buyable 주입)."""
        broker = FakeBroker()
        pos_history = FakePositionHistory()

        treasury.start_sync(broker, pos_history, interval_seconds=100)
        await asyncio.sleep(0.05)
        await treasury.stop_sync()

        assert treasury._account_balance == 5_000_000.0
        # #2384: purchasable_amount는 get_buyable의 order_buyable_amount로 주입.
        assert treasury._purchasable_amount == 4_800_000.0
        assert treasury._total_evaluation == 12_000_000.0
        # 대표 종목으로 cycle당 1회 probe 호출됨.
        assert broker.buyable_call_count >= 1
        assert broker.last_buyable_symbol == "005930"

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

    async def test_get_buyable_failure_keeps_old_value_no_event(
        self, treasury, eventbus
    ):
        """#2384 G7: get_buyable 실패 시 purchasable_amount 이전값 유지 +
        BalanceSyncedEvent 미발행."""
        received = []
        eventbus.subscribe(BalanceSyncedEvent, lambda e: received.append(e))

        # 사전 주입된 매수가능액(이전 cycle 값 모사).
        treasury._purchasable_amount = 7_777_000.0

        broker = BuyableFailingBroker()
        pos_history = FakePositionHistory()

        treasury.start_sync(broker, pos_history, interval_seconds=100)
        await asyncio.sleep(0.05)
        await treasury.stop_sync()

        # get_buyable는 호출되었으나 실패 → 예외로 cycle 중단.
        assert broker.buyable_call_count >= 1
        # 이전값 유지 (0으로 덮어쓰지 않음).
        assert treasury._purchasable_amount == 7_777_000.0
        # 잘못된 매수가능액으로 이벤트를 발행하지 않는다.
        assert received == []

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
                    account_id="acc-test",
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
                    account_id="acc-test",
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

    async def test_live_mode_explicit(self, treasury):
        """trading_mode='live' 명시해도 기존 동작과 동일."""
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

        treasury.start_sync(
            broker, pos_history, interval_seconds=100, trading_mode="live"
        )
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
        # #2384: purchasable_amount는 get_buyable write-path로 주입되는 값을 모사
        # (sync_balance는 더 이상 purchasable_amount를 반영하지 않는다).
        treasury._purchasable_amount = 4_800_000.0
        await treasury.sync_balance(
            {
                "cash": 5_000_000.0,
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


# ── US-5: Virtual 모드 동기화 ──────────────────────


class TestVirtualSync:
    async def test_virtual_sync_calculates_from_positions(self, treasury):
        """Virtual 모드에서 Trade DB 포지션 기반으로 purchase/eval 계산."""
        pos_history = FakePositionHistory(
            positions=[
                PositionSnapshot(
                    bot_id="bot1",
                    symbol="005930",
                    quantity=100.0,
                    avg_entry_price=70000.0,
                    account_id="acc-test",
                ),
                PositionSnapshot(
                    bot_id="bot1",
                    symbol="035720",
                    quantity=50.0,
                    avg_entry_price=60000.0,
                    account_id="acc-test",
                ),
            ]
        )

        treasury.start_sync(
            broker=None,
            position_history=pos_history,
            interval_seconds=100,
            trading_mode="virtual",
        )
        await asyncio.sleep(0.05)
        await treasury.stop_sync()

        # price_resolver 없으면 avg_entry_price 사용 -> eval == purchase
        assert treasury._purchase_amount == 10_000_000.0  # 100*70000 + 50*60000
        assert treasury._eval_amount == 10_000_000.0
        assert treasury._external_purchase_amount == 0.0
        assert treasury._external_eval_amount == 0.0

    async def test_virtual_sync_with_price_resolver(self, treasury):
        """Virtual 모드에서 price_resolver 사용 시 eval 금액이 시세 반영."""
        prices = {"005930": 75000.0, "035720": 62000.0}

        async def mock_price_resolver(symbol: str) -> float:
            return prices[symbol]

        pos_history = FakePositionHistory(
            positions=[
                PositionSnapshot(
                    bot_id="bot1",
                    symbol="005930",
                    quantity=100.0,
                    avg_entry_price=70000.0,
                    account_id="acc-test",
                ),
                PositionSnapshot(
                    bot_id="bot1",
                    symbol="035720",
                    quantity=50.0,
                    avg_entry_price=60000.0,
                    account_id="acc-test",
                ),
            ]
        )

        treasury.start_sync(
            broker=None,
            position_history=pos_history,
            interval_seconds=100,
            trading_mode="virtual",
            price_resolver=mock_price_resolver,
        )
        await asyncio.sleep(0.05)
        await treasury.stop_sync()

        assert treasury._purchase_amount == 10_000_000.0  # 100*70000 + 50*60000
        assert treasury._eval_amount == 10_600_000.0  # 100*75000 + 50*62000

    async def test_virtual_sync_price_resolver_fallback(self, treasury):
        """price_resolver 실패 시 avg_entry_price로 fallback."""

        async def failing_resolver(symbol: str) -> float:
            raise ConnectionError("시세 조회 실패")

        pos_history = FakePositionHistory(
            positions=[
                PositionSnapshot(
                    bot_id="bot1",
                    symbol="005930",
                    quantity=100.0,
                    avg_entry_price=70000.0,
                    account_id="acc-test",
                ),
            ]
        )

        treasury.start_sync(
            broker=None,
            position_history=pos_history,
            interval_seconds=100,
            trading_mode="virtual",
            price_resolver=failing_resolver,
        )
        await asyncio.sleep(0.05)
        await treasury.stop_sync()

        # fallback: avg_entry_price 사용
        assert treasury._purchase_amount == 7_000_000.0
        assert treasury._eval_amount == 7_000_000.0

    async def test_virtual_sync_empty_positions(self, treasury):
        """Virtual 모드에서 포지션이 없으면 0."""
        pos_history = FakePositionHistory(positions=[])

        treasury.start_sync(
            broker=None,
            position_history=pos_history,
            interval_seconds=100,
            trading_mode="virtual",
        )
        await asyncio.sleep(0.05)
        await treasury.stop_sync()

        assert treasury._purchase_amount == 0.0
        assert treasury._eval_amount == 0.0

    async def test_virtual_sync_get_summary_reflects_values(self, treasury):
        """Virtual 동기화 후 get_summary()에 ante 필드가 정상 반영."""
        prices = {"005930": 75000.0}

        async def mock_resolver(symbol: str) -> float:
            return prices[symbol]

        pos_history = FakePositionHistory(
            positions=[
                PositionSnapshot(
                    bot_id="bot1",
                    symbol="005930",
                    quantity=100.0,
                    avg_entry_price=70000.0,
                    account_id="acc-test",
                ),
            ]
        )

        treasury.start_sync(
            broker=None,
            position_history=pos_history,
            interval_seconds=100,
            trading_mode="virtual",
            price_resolver=mock_resolver,
        )
        await asyncio.sleep(0.05)
        await treasury.stop_sync()

        summary = treasury.get_summary()

        # Virtual 모드: external = 0 이므로 ante = total
        assert summary["ante_purchase_amount"] == 7_000_000.0  # 100 * 70000
        assert summary["ante_eval_amount"] == 7_500_000.0  # 100 * 75000
        assert summary["ante_profit_loss"] == 500_000.0  # 7.5M - 7M

    async def test_virtual_sync_publishes_event(self, treasury, eventbus):
        """Virtual 동기화 성공 시 BalanceSyncedEvent 발행."""
        received = []
        eventbus.subscribe(BalanceSyncedEvent, lambda e: received.append(e))

        pos_history = FakePositionHistory(
            positions=[
                PositionSnapshot(
                    bot_id="bot1",
                    symbol="005930",
                    quantity=100.0,
                    avg_entry_price=70000.0,
                    account_id="acc-test",
                ),
            ]
        )

        treasury.start_sync(
            broker=None,
            position_history=pos_history,
            interval_seconds=100,
            trading_mode="virtual",
        )
        await asyncio.sleep(0.05)
        await treasury.stop_sync()

        assert len(received) == 1
        assert received[0].external_purchase_amount == 0.0
        assert received[0].external_eval_amount == 0.0

    async def test_virtual_sync_updates_last_synced(self, treasury):
        """Virtual 동기화 후 last_synced_at 갱신."""
        pos_history = FakePositionHistory(positions=[])

        assert treasury.last_synced_at is None

        treasury.start_sync(
            broker=None,
            position_history=pos_history,
            interval_seconds=100,
            trading_mode="virtual",
        )
        await asyncio.sleep(0.05)
        await treasury.stop_sync()

        assert treasury.last_synced_at is not None


# ── #1240 review: cross-account 필터링 회귀 ───────


class TestCrossAccountFilter:
    """Treasury 가 자기 계좌 포지션만 집계하는지 검증.

    SPLIT-1 부터 거래/포지션 row 가 실제 account_id 를 갖기 시작하므로,
    단일 계좌 바인딩된 Treasury 가 cross-account 데이터를 끌어오면
    treasury_state, BalanceSyncedEvent, 가상 평가금액에 타 계좌 포지션이
    섞이게 된다. 이를 회귀로 차단한다.
    """

    async def test_treasury_sync_filters_other_account_positions(
        self, treasury, eventbus
    ):
        """Live sync: Treasury(account='acc-test') 의 sync 가 acc-b 포지션을
        external 분류에 포함하지 않는다.

        ``FakePositionHistory.get_all_positions(account_id=...)`` 가
        acc-test 행만 돌려주므로, 005930 도 internal 로 분류되어
        external_* 가 0 이어야 한다.
        """
        broker = FakeBroker(
            positions=[
                {
                    "symbol": "005930",
                    "quantity": 100.0,
                    "avg_price": 71000.0,
                    "eval_amount": 7_200_000.0,
                },
            ]
        )
        # 같은 symbol 을 acc-test (자기) + acc-b (타) 양쪽이 보유.
        pos_history = FakePositionHistory(
            positions=[
                PositionSnapshot(
                    bot_id="bot-a",
                    symbol="005930",
                    quantity=100.0,
                    avg_entry_price=71000.0,
                    account_id="acc-test",
                ),
                PositionSnapshot(
                    bot_id="bot-b",
                    symbol="999999",
                    quantity=10.0,
                    avg_entry_price=10000.0,
                    account_id="acc-b",
                ),
            ]
        )

        treasury.start_sync(broker, pos_history, interval_seconds=100)
        await asyncio.sleep(0.05)
        await treasury.stop_sync()

        # Treasury 가 자기 account_id 로 명시 필터링했어야 한다.
        assert pos_history.last_account_id == "acc-test"
        # 005930 은 internal 로 분류되어 external 0.
        assert treasury._external_purchase_amount == 0.0
        assert treasury._external_eval_amount == 0.0

    async def test_treasury_virtual_sync_filters_other_account(self, treasury):
        """Virtual sync: 타 계좌 포지션이 자기 계좌의 평가금액에 섞이지 않는다."""
        pos_history = FakePositionHistory(
            positions=[
                PositionSnapshot(
                    bot_id="bot-a",
                    symbol="005930",
                    quantity=100.0,
                    avg_entry_price=70000.0,
                    account_id="acc-test",
                ),
                PositionSnapshot(
                    bot_id="bot-b",
                    symbol="000660",
                    quantity=50.0,
                    avg_entry_price=200000.0,
                    account_id="acc-b",
                ),
            ]
        )

        treasury.start_sync(
            broker=None,
            position_history=pos_history,
            interval_seconds=100,
            trading_mode="virtual",
        )
        await asyncio.sleep(0.05)
        await treasury.stop_sync()

        # 자기 account_id 로만 집계되었어야 한다.
        assert pos_history.last_account_id == "acc-test"
        assert treasury._purchase_amount == 7_000_000.0  # 100 * 70000
        assert treasury._eval_amount == 7_000_000.0
