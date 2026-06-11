"""PositionReconciler 단위 테스트."""

from __future__ import annotations

import pytest

from ante.account.errors import InvalidAccountIdError
from ante.core.database import Database
from ante.eventbus.bus import EventBus
from ante.eventbus.events import (
    NotificationEvent,
    PositionMismatchEvent,
    ReconcileEvent,
)
from ante.trade.order_tracker import OrderTracker
from ante.trade.performance import PerformanceTracker
from ante.trade.position import PositionHistory
from ante.trade.reconciler import (
    REASON_EXTERNAL_BUY,
    REASON_SELF_SUBMITTED,
    REASON_UNATTRIBUTED_HOLDING,
    PositionReconciler,
)
from ante.trade.recorder import TradeRecorder
from ante.trade.service import TradeService

# ── Fixtures ─────────────────────────────────────────


@pytest.fixture
async def db(tmp_path):
    database = Database(str(tmp_path / "test.db"))
    await database.connect()
    yield database
    await database.close()


@pytest.fixture
async def position_history(db):
    ph = PositionHistory(db)
    await ph.initialize()
    return ph


@pytest.fixture
async def recorder(db, position_history):
    rec = TradeRecorder(db, position_history)
    await rec.initialize()
    return rec


@pytest.fixture
async def service(recorder, position_history):
    perf = PerformanceTracker(recorder._db)
    return TradeService(recorder, position_history, perf)


@pytest.fixture
def eventbus():
    return EventBus()


@pytest.fixture
async def order_tracker(db):
    ot = OrderTracker(db)
    await ot.initialize()
    return ot


@pytest.fixture
def reconciler(service, eventbus, order_tracker):
    return PositionReconciler(
        trade_service=service,
        eventbus=eventbus,
        order_tracker=order_tracker,
    )


async def _seed_open_order(
    order_tracker,
    *,
    order_id,
    bot_id,
    symbol,
    ordered_qty,
    account_id="acc-test",
    side="buy",
    recorded_filled_qty=0.0,
    submitted_date="2026-05-29",
    strategy_id="strat-1",
    broker_order_id=None,
):
    """테스트용 추적 주문 seed (필요 시 부분 체결 advance)."""
    await order_tracker.open(
        order_id=order_id,
        account_id=account_id,
        bot_id=bot_id,
        strategy_id=strategy_id,
        broker_order_id=broker_order_id or f"odno-{order_id}",
        symbol=symbol,
        side=side,
        order_type="market",
        ordered_qty=ordered_qty,
        submitted_date=submitted_date,
        submitted_at=f"{submitted_date} 09:00:00",
    )
    if recorded_filled_qty > 0:
        await order_tracker.record_fill(order_id, recorded_filled_qty, 50000)


async def _set_position(
    position_history,
    bot_id,
    symbol,
    qty,
    avg_price,
    *,
    account_id="acc-test",
):
    """테스트용 포지션 설정."""
    await position_history.force_update(
        bot_id=bot_id,
        symbol=symbol,
        quantity=qty,
        avg_entry_price=avg_price,
        account_id=account_id,
    )


# ── 시나리오 1: 전량 외부 매도 ─────────────────────


class TestFullExternalSell:
    async def test_full_sell_detected_and_corrected(
        self, reconciler, position_history, eventbus
    ):
        """내부 50주, 브로커 0주 → 포지션 0주로 보정."""
        await _set_position(position_history, "bot-1", "005930", 50, 50000)

        mismatch_events: list = []
        reconcile_events: list = []
        eventbus.subscribe(PositionMismatchEvent, lambda e: mismatch_events.append(e))
        eventbus.subscribe(ReconcileEvent, lambda e: reconcile_events.append(e))

        corrections = await reconciler.reconcile(
            bot_id="bot-1",
            broker_positions=[],  # 브로커에 없음
            account_id="acc-test",
        )

        assert len(corrections) == 1
        assert corrections[0]["old_quantity"] == 50
        assert corrections[0]["new_quantity"] == 0
        assert corrections[0]["reason"] == "외부 청산"

        # 이벤트 발행 확인
        assert len(mismatch_events) == 1
        assert mismatch_events[0].symbol == "005930"
        assert mismatch_events[0].internal_qty == 50
        assert mismatch_events[0].broker_qty == 0

        assert len(reconcile_events) == 1
        assert reconcile_events[0].discrepancy_count == 1

        # 포지션 실제로 0주로 변경됨
        pos = await position_history.get_current("bot-1", "005930")
        assert pos["quantity"] == 0


# ── 시나리오 2: 일부 외부 매도 ─────────────────────


class TestPartialExternalSell:
    async def test_partial_sell_corrected(self, reconciler, position_history):
        """내부 50주, 브로커 30주 → 30주로 보정."""
        await _set_position(position_history, "bot-1", "005930", 50, 50000)

        corrections = await reconciler.reconcile(
            bot_id="bot-1",
            broker_positions=[
                {"symbol": "005930", "quantity": 30, "avg_price": 50000},
            ],
            account_id="acc-test",
        )

        assert len(corrections) == 1
        assert corrections[0]["old_quantity"] == 50
        assert corrections[0]["new_quantity"] == 30
        assert corrections[0]["reason"] == "외부 일부 매도"


# ── 시나리오 3: 불일치 없음 ────────────────────────


class TestNoMismatch:
    async def test_no_correction_when_matched(
        self, reconciler, position_history, eventbus
    ):
        """포지션 일치 시 보정 없음."""
        await _set_position(position_history, "bot-1", "005930", 50, 50000)

        reconcile_events: list = []
        eventbus.subscribe(ReconcileEvent, lambda e: reconcile_events.append(e))

        corrections = await reconciler.reconcile(
            bot_id="bot-1",
            broker_positions=[
                {"symbol": "005930", "quantity": 50, "avg_price": 50000},
            ],
            account_id="acc-test",
        )

        assert corrections == []
        assert len(reconcile_events) == 0

    async def test_no_correction_both_empty(self, reconciler):
        """내부/브로커 모두 빈 포지션."""
        corrections = await reconciler.reconcile(
            bot_id="bot-1", broker_positions=[], account_id="acc-test"
        )
        assert corrections == []

    async def test_other_account_position_is_not_reconciled(
        self, reconciler, position_history
    ):
        """Reconciler는 요청 account_id의 내부 포지션만 대조한다."""
        await _set_position(
            position_history,
            "bot-1",
            "005930",
            50,
            50000,
            account_id="acc-other",
        )

        corrections = await reconciler.reconcile(
            bot_id="bot-1",
            broker_positions=[],
            account_id="acc-test",
        )

        assert corrections == []
        other = await position_history.get_current(
            "bot-1", "005930", account_id="acc-other"
        )
        assert other["quantity"] == 50


# ── 시나리오 4: 외부 매수 ──────────────────────────


class TestExternalBuy:
    async def test_external_buy_detected(
        self, reconciler, position_history, order_tracker
    ):
        """내부 10주(잔존) + 추적 open buy 존재(capacity>0) & excess>capacity →
        외부 매수로 보정 (#2352 재분류: i_qty>0 || capacity>0 만 외부 매수 보장).

        ante open buy 5주 + 내부 10주, 브로커 20주 → excess 10 > capacity 5 →
        외부 매수. internal_qty>0 이므로 미귀속 보유(#2352) 대상이 아니다.
        """
        await _set_position(position_history, "bot-1", "005930", 10, 50000)
        await _seed_open_order(
            order_tracker,
            order_id="ord-eb",
            bot_id="bot-1",
            symbol="005930",
            ordered_qty=5,
        )

        corrections = await reconciler.reconcile(
            bot_id="bot-1",
            broker_positions=[
                {"symbol": "005930", "quantity": 20, "avg_price": 55000},
            ],
            account_id="acc-test",
        )

        assert len(corrections) == 1
        assert corrections[0]["new_quantity"] == 20
        assert corrections[0]["reason"] == REASON_EXTERNAL_BUY

    async def test_external_buy_skipped_when_flag_set(
        self, reconciler, position_history, order_tracker, eventbus
    ):
        """skip_external_buy=True 면 "외부 매수" 보정·이벤트를 건너뛴다
        (#1946 Finding 1 barrier).

        #2352 재분류: barrier 가 적용되려면 외부 매수로 분류돼야 하므로,
        internal_qty>0(잔존) 케이스로 구성한다(미귀속 보유와 직교).
        """
        await _set_position(position_history, "bot-1", "005930", 10, 50000)

        mismatch_events: list = []
        eventbus.subscribe(PositionMismatchEvent, lambda e: mismatch_events.append(e))

        corrections = await reconciler.reconcile(
            bot_id="bot-1",
            broker_positions=[
                {"symbol": "005930", "quantity": 20, "avg_price": 55000},
            ],
            account_id="acc-test",
            skip_external_buy=True,
        )

        assert corrections == []  # external-buy 억제.
        assert mismatch_events == []  # 이벤트도 발행 안 함.
        # 포지션도 보정되지 않음 (10 유지 — barrier 가 외부 매수 보정을 억제).
        pos = await position_history.get_current("bot-1", "005930")
        assert pos["quantity"] == 10

    async def test_skip_external_buy_does_not_affect_other_classes(
        self, reconciler, position_history, eventbus
    ):
        """skip_external_buy=True 라도 "외부 청산"·"외부 일부 매도" 는 정상 보정한다
        (skip 은 external-buy 만 타겟 — 다른 안전 보정은 유지).
        """
        # 내부 50주 보유 (외부 청산 시나리오).
        await _set_position(position_history, "bot-1", "005930", 50, 50000)
        # 다른 종목: 내부 40주, 브로커 20주 (외부 일부 매도).
        await _set_position(position_history, "bot-1", "000660", 40, 80000)

        corrections = await reconciler.reconcile(
            bot_id="bot-1",
            broker_positions=[
                # 005930: 브로커 0주 → 외부 청산 (skip 대상 아님).
                {"symbol": "000660", "quantity": 20, "avg_price": 80000},
                # 신규 외부 매수 종목 (skip 대상).
                {"symbol": "035720", "quantity": 10, "avg_price": 30000},
            ],
            account_id="acc-test",
            skip_external_buy=True,
        )

        reasons = {c["symbol"]: c["reason"] for c in corrections}
        # 외부 청산·일부 매도는 보정됨, external-buy(035720)는 억제.
        assert reasons.get("005930") == "외부 청산"
        assert reasons.get("000660") == "외부 일부 매도"
        assert "035720" not in reasons


# ── 시나리오 5: 복수 종목 불일치 ───────────────────


class TestMultipleSymbols:
    async def test_multiple_corrections(self, reconciler, position_history, eventbus):
        """여러 종목 동시 불일치."""
        await _set_position(position_history, "bot-1", "005930", 50, 50000)
        await _set_position(position_history, "bot-1", "000660", 30, 80000)

        mismatch_events: list = []
        eventbus.subscribe(PositionMismatchEvent, lambda e: mismatch_events.append(e))

        corrections = await reconciler.reconcile(
            bot_id="bot-1",
            broker_positions=[
                {"symbol": "005930", "quantity": 0, "avg_price": 0},
                # 000660 은 브로커에 없음
            ],
            account_id="acc-test",
        )

        assert len(corrections) == 2
        assert len(mismatch_events) == 2


# ── 시나리오 6: self-submitted unrecorded fill 분류 (#1950) ──


class TestSelfSubmittedFill:
    """broker > internal(외부 매수 후보) 분기에서 ante 미반영 체결(self)을
    외부 매수와 구분한다 (#1950).
    """

    async def test_self_submitted_within_capacity_skips_correction(
        self, reconciler, position_history, order_tracker, eventbus
    ):
        """R1-3 (a): excess ≤ ante 미체결 capacity → self_submitted.

        correct_position skip + info 알림 + 보정 없음(자동 매도 유발 X).
        """
        # ante buy 주문 20주 미체결(open), 내부 0주, 브로커 20주.
        await _seed_open_order(
            order_tracker,
            order_id="ord-1",
            bot_id="bot-1",
            symbol="005930",
            ordered_qty=20,
        )

        mismatch_events: list = []
        notif_events: list = []
        eventbus.subscribe(PositionMismatchEvent, lambda e: mismatch_events.append(e))
        eventbus.subscribe(NotificationEvent, lambda e: notif_events.append(e))

        corrections = await reconciler.reconcile(
            bot_id="bot-1",
            broker_positions=[
                {"symbol": "005930", "quantity": 20, "avg_price": 55000},
            ],
            account_id="acc-test",
        )

        # 보정 skip — FillApplier(#1946) 에 위임.
        assert corrections == []
        # 포지션 보정 안 됨.
        pos = await position_history.get_current("bot-1", "005930")
        assert pos["quantity"] == 0
        # PositionMismatchEvent 는 self-submitted 사유로 발행.
        assert len(mismatch_events) == 1
        assert mismatch_events[0].reason == REASON_SELF_SUBMITTED
        # NotificationEvent 는 info 레벨(자동 매도 유발 안 함).
        assert len(notif_events) == 1
        assert notif_events[0].level == "info"

    async def test_self_submitted_with_partial_fill_capacity(
        self, reconciler, order_tracker
    ):
        """capacity = ordered − recorded (부분 체결 반영). excess ≤ 잔량 → self."""
        # 50주 주문 중 30주 이미 기록 → 잔량 capacity = 20.
        await _seed_open_order(
            order_tracker,
            order_id="ord-1",
            bot_id="bot-1",
            symbol="005930",
            ordered_qty=50,
            recorded_filled_qty=30,
        )
        # 내부 0, 브로커 20 → excess 20 == capacity 20 → self.
        corrections = await reconciler.reconcile(
            bot_id="bot-1",
            broker_positions=[
                {"symbol": "005930", "quantity": 20, "avg_price": 55000},
            ],
            account_id="acc-test",
        )
        assert corrections == []

    async def test_excess_over_capacity_is_external_buy(
        self, reconciler, order_tracker
    ):
        """R1-3 (b): excess > capacity → 외부 매수 정상 보정.

        #2352 경계 보존: capacity > 0(추적 open buy 존재) 이면 internal_qty==0
        이어도 미귀속 보유로 빠지지 않고 #1950 그대로 외부 매수 force-write 한다.
        신규 detect-only 분기는 capacity==0 부분집합만 변경한다.
        """
        # ante 미체결 10주, 브로커 30주(내부 0) → excess 30 > capacity 10.
        await _seed_open_order(
            order_tracker,
            order_id="ord-1",
            bot_id="bot-1",
            symbol="005930",
            ordered_qty=10,
        )
        corrections = await reconciler.reconcile(
            bot_id="bot-1",
            broker_positions=[
                {"symbol": "005930", "quantity": 30, "avg_price": 55000},
            ],
            account_id="acc-test",
        )
        assert len(corrections) == 1
        assert corrections[0]["reason"] == REASON_EXTERNAL_BUY
        assert corrections[0]["new_quantity"] == 30

    async def test_no_matching_order_is_unattributed_holding(
        self, reconciler, order_tracker
    ):
        """매칭 주문 없음 + internal_qty==0 → 미귀속 보유 detect-only (#2352).

        #2352 재분류: 과거에는 외부 매수 force-write 였으나, 어느 봇도 추적하지
        않은 보유(capacity==0 && internal_qty==0)는 보정하지 않는다.
        """
        corrections = await reconciler.reconcile(
            bot_id="bot-1",
            broker_positions=[
                {"symbol": "005930", "quantity": 20, "avg_price": 55000},
            ],
            account_id="acc-test",
        )
        assert corrections == []

    async def test_bot_id_mismatch_is_unattributed_holding(
        self, reconciler, order_tracker
    ):
        """다른 봇의 ante 주문은 매칭 안 됨 + internal==0 → 미귀속 보유 (#2352).

        bot-2 의 매수 주문은 bot-1 의 self-check 에 잡히지 않으므로 bot-1 입장에서
        capacity==0. 과거 외부 매수 → 미귀속 보유 detect-only 로 재분류.
        """
        await _seed_open_order(
            order_tracker,
            order_id="ord-1",
            bot_id="bot-2",
            symbol="005930",
            ordered_qty=20,
        )
        corrections = await reconciler.reconcile(
            bot_id="bot-1",
            broker_positions=[
                {"symbol": "005930", "quantity": 20, "avg_price": 55000},
            ],
            account_id="acc-test",
        )
        assert corrections == []

    async def test_sell_order_does_not_match_is_unattributed_holding(
        self, reconciler, order_tracker
    ):
        """side=sell 주문은 self-check(buy) 에 매칭 안 됨 + internal==0 → 미귀속
        보유 (#2352 재분류). buy capacity==0 이므로 미귀속.
        """
        await _seed_open_order(
            order_tracker,
            order_id="ord-1",
            bot_id="bot-1",
            symbol="005930",
            ordered_qty=20,
            side="sell",
        )
        corrections = await reconciler.reconcile(
            bot_id="bot-1",
            broker_positions=[
                {"symbol": "005930", "quantity": 20, "avg_price": 55000},
            ],
            account_id="acc-test",
        )
        assert corrections == []

    async def test_self_check_runs_when_skip_external_buy_false(
        self, reconciler, position_history, order_tracker, eventbus
    ):
        """R1-1/F1: 주기 reconcile(skip_external_buy=False)에서도 self-check 동작.

        self → 보정 skip (외부 매수로 재오분류되지 않음).
        """
        await _seed_open_order(
            order_tracker,
            order_id="ord-1",
            bot_id="bot-1",
            symbol="005930",
            ordered_qty=20,
        )
        notif_events: list = []
        eventbus.subscribe(NotificationEvent, lambda e: notif_events.append(e))

        corrections = await reconciler.reconcile(
            bot_id="bot-1",
            broker_positions=[
                {"symbol": "005930", "quantity": 20, "avg_price": 55000},
            ],
            account_id="acc-test",
            skip_external_buy=False,  # 주기 reconcile.
        )

        # self 로 분류되어 보정 skip — info 알림만.
        assert corrections == []
        assert len(notif_events) == 1
        assert notif_events[0].level == "info"

    async def test_self_classified_even_with_skip_external_buy(
        self, reconciler, order_tracker, eventbus
    ):
        """R1-1: self-check 는 skip_external_buy 와 직교. self 는 info 알림 발행
        (barrier 의 외부 매수 억제와 별개로 self 는 항상 info 알림).
        """
        await _seed_open_order(
            order_tracker,
            order_id="ord-1",
            bot_id="bot-1",
            symbol="005930",
            ordered_qty=20,
        )
        notif_events: list = []
        eventbus.subscribe(NotificationEvent, lambda e: notif_events.append(e))

        corrections = await reconciler.reconcile(
            bot_id="bot-1",
            broker_positions=[
                {"symbol": "005930", "quantity": 20, "avg_price": 55000},
            ],
            account_id="acc-test",
            skip_external_buy=True,
        )
        assert corrections == []
        # self 는 skip_external_buy 와 무관하게 info 알림 발행.
        assert len(notif_events) == 1
        assert notif_events[0].level == "info"

    async def test_account_scoped_matching(self, reconciler, order_tracker):
        """다른 account 의 ante 주문은 매칭 안 됨 + internal==0 → 미귀속 보유.

        #2352 재분류: acc-other 의 주문은 acc-test self-check 에 잡히지 않아
        capacity==0 이고 internal_qty==0 이므로 미귀속 보유 detect-only.
        """
        await _seed_open_order(
            order_tracker,
            order_id="ord-1",
            bot_id="bot-1",
            symbol="005930",
            ordered_qty=20,
            account_id="acc-other",
        )
        corrections = await reconciler.reconcile(
            bot_id="bot-1",
            broker_positions=[
                {"symbol": "005930", "quantity": 20, "avg_price": 55000},
            ],
            account_id="acc-test",
        )
        assert corrections == []


# ── 시나리오 7: R2-2 혼재(self + 숨은 외부) bounded ──────


class TestMixedBoundedCase:
    """R2-2: excess ≤ capacity 인 혼재(self + 숨은 외부)는 self_submitted 로
    분류(보정 skip)되고, ante 주문 해소 후 다음 reconcile 에서의 거동을 검증한다.

    #2352 재서술: #1950 의 "주문 해소 후 잔여 excess 가 external 로 검출·보정"
    보장은 ``internal_qty > 0 || capacity > 0`` 케이스에 한정된다. 주문이 해소된
    뒤에도 ``internal_qty == 0 && capacity == 0`` 이면 그 보유는 미귀속 보유로
    영구 detect-only(force-write 보류)가 된다 — internal 이 0 인 채 capacity 가
    사라진 보유는 어느 봇도 추적하지 않는 보유이므로 그 봇 소유로 단정하지 않는다.
    """

    async def test_holding_unattributed_after_order_resolves_with_zero_internal(
        self, reconciler, position_history, order_tracker
    ):
        """혼재 → self(보정 skip) → ante 주문 terminal & internal==0 → 미귀속 보유.

        #2352: 주문 해소 후 internal 이 0 이고 capacity 도 0 이면 외부 매수
        force-write 가 아니라 미귀속 보유 detect-only 다(#1950 bounded invariant
        재서술).
        """
        # ante 미체결 buy 100주(open). 브로커 60주(내부 0) — excess 60 ≤ capacity
        # 100 → self 로 분류(보정 skip).
        await _seed_open_order(
            order_tracker,
            order_id="ord-1",
            bot_id="bot-1",
            symbol="005930",
            ordered_qty=100,
        )
        corrections = await reconciler.reconcile(
            bot_id="bot-1",
            broker_positions=[
                {"symbol": "005930", "quantity": 60, "avg_price": 55000},
            ],
            account_id="acc-test",
        )
        # 1차: self → 보정 skip.
        assert corrections == []
        pos = await position_history.get_current("bot-1", "005930")
        assert pos["quantity"] == 0

        # ante 주문이 EOD expire_stale 로 해소(terminal) — open set 이탈.
        await order_tracker.mark_terminal("ord-1", "expired")

        # 2차 reconcile: 매칭 open 주문 없음(capacity==0) & internal==0 → 미귀속
        # 보유 detect-only (force-write 안 함).
        corrections2 = await reconciler.reconcile(
            bot_id="bot-1",
            broker_positions=[
                {"symbol": "005930", "quantity": 60, "avg_price": 55000},
            ],
            account_id="acc-test",
        )
        assert corrections2 == []

    async def test_residual_external_detected_when_internal_nonzero(
        self, reconciler, position_history, order_tracker
    ):
        """internal_qty > 0(잔존) 이면 주문 해소 후 잔여 excess 가 여전히 외부
        매수로 검출·보정된다 (#2352: bounded invariant 의 internal>0 가지 보존).
        """
        # 내부 30주 잔존 + ante 미체결 buy 100주(open). 브로커 90주 →
        # excess 60 ≤ capacity 100 → self(보정 skip).
        await _set_position(position_history, "bot-1", "005930", 30, 50000)
        await _seed_open_order(
            order_tracker,
            order_id="ord-1",
            bot_id="bot-1",
            symbol="005930",
            ordered_qty=100,
        )
        corrections = await reconciler.reconcile(
            bot_id="bot-1",
            broker_positions=[
                {"symbol": "005930", "quantity": 90, "avg_price": 55000},
            ],
            account_id="acc-test",
        )
        assert corrections == []

        # ante 주문 해소(terminal) — capacity==0. 그러나 internal_qty==30(>0)
        # 이므로 미귀속 보유 대상이 아니다 → 잔여 excess 가 외부 매수로 검출.
        await order_tracker.mark_terminal("ord-1", "expired")
        corrections2 = await reconciler.reconcile(
            bot_id="bot-1",
            broker_positions=[
                {"symbol": "005930", "quantity": 90, "avg_price": 55000},
            ],
            account_id="acc-test",
        )
        assert len(corrections2) == 1
        assert corrections2[0]["reason"] == REASON_EXTERNAL_BUY
        assert corrections2[0]["new_quantity"] == 90


# ── 시나리오 8: OrderTracker 미주입 하위 호환 ──────────


class TestNoOrderTracker:
    async def test_external_buy_without_order_tracker(self, service, eventbus):
        """order_tracker 미주입 시 self-check·미귀속 판정 생략 → 기존 외부 매수.

        #2352 하위 호환: capacity 판정 불가(order_tracker None)이면 신규 미귀속
        보유 detect-only 분기를 적용하지 않고 기존 외부 매수 force-write 를 유지한다.
        """
        rec = PositionReconciler(trade_service=service, eventbus=eventbus)
        corrections = await rec.reconcile(
            bot_id="bot-1",
            broker_positions=[
                {"symbol": "005930", "quantity": 20, "avg_price": 55000},
            ],
            account_id="acc-test",
        )
        assert len(corrections) == 1
        assert corrections[0]["reason"] == REASON_EXTERNAL_BUY


# ── 시나리오 9: 미귀속 보유 carryover detect-only (#2352) ──


class TestUnattributedHolding:
    """#2352: 단일봇 미거래 carryover(internal_qty==0 && capacity==0)는 그 봇의
    '외부 매수' 로 force-write 되지 않고 detect-only(보정 skip, 이벤트/critical
    알림 유지)로 처리된다 — 전략 오매도(#2317 canary) 방지.
    """

    async def test_unattributed_holding_skips_correction_keeps_events(
        self, reconciler, position_history, order_tracker, eventbus
    ):
        """internal==0 && capacity==0(추적 open buy 전무) → correct_position 미호출
        + reason="미귀속 보유" PositionMismatchEvent + critical NotificationEvent.
        """
        mismatch_events: list = []
        notif_events: list = []
        reconcile_events: list = []
        eventbus.subscribe(PositionMismatchEvent, lambda e: mismatch_events.append(e))
        eventbus.subscribe(NotificationEvent, lambda e: notif_events.append(e))
        eventbus.subscribe(ReconcileEvent, lambda e: reconcile_events.append(e))

        # 내부 0, 브로커 2주(이월/미거래). 추적 open buy 전무 → 미귀속 보유.
        corrections = await reconciler.reconcile(
            bot_id="bot-1",
            broker_positions=[
                {"symbol": "069500", "quantity": 2, "avg_price": 30000},
            ],
            account_id="acc-test",
        )

        # 보정 0건 — correct_position 미호출(force-write 없음).
        assert corrections == []
        # 포지션은 0 유지 (전략이 미보유 종목을 자기 포지션으로 인식하지 않는다).
        pos = await position_history.get_current("bot-1", "069500")
        assert pos["quantity"] == 0
        # PositionMismatchEvent 는 미귀속 보유 사유로 발행(운영자 관측 유지).
        assert len(mismatch_events) == 1
        assert mismatch_events[0].reason == REASON_UNATTRIBUTED_HOLDING
        assert mismatch_events[0].symbol == "069500"
        assert mismatch_events[0].internal_qty == 0
        assert mismatch_events[0].broker_qty == 2
        # NotificationEvent 는 critical(미귀속 보유는 운영 안전 경로).
        assert len(notif_events) == 1
        assert notif_events[0].level == "critical"
        # 보정 0건 → ReconcileEvent(보정 완료)는 발행 안 됨.
        assert reconcile_events == []

    async def test_canary_scenario_no_force_write(
        self, reconciler, position_history, order_tracker
    ):
        """#2317 canary 재현 고정: 069500 내부 0 → 브로커 2 가 force-write 되지
        않는다(과거: 외부 매수로 quantity=2 force-write → 전략 오매도).
        """
        await reconciler.reconcile(
            bot_id="oracle-probe-bot",
            broker_positions=[
                {"symbol": "069500", "quantity": 2, "avg_price": 30000},
            ],
            account_id="acc-test",
        )
        pos = await position_history.get_current("oracle-probe-bot", "069500")
        # 미보유 종목이 봇 포지션으로 기록되지 않음 — 오매도 방지.
        assert pos["quantity"] == 0

    async def test_unattributed_holding_skips_even_under_skip_external_buy(
        self, reconciler, position_history, order_tracker, eventbus
    ):
        """미귀속 보유는 is_external_buy=False 이므로 skip_external_buy barrier 와
        직교 — barrier 가 켜져도 critical 관측은 발행되고 보정은 여전히 skip.
        """
        mismatch_events: list = []
        eventbus.subscribe(PositionMismatchEvent, lambda e: mismatch_events.append(e))

        corrections = await reconciler.reconcile(
            bot_id="bot-1",
            broker_positions=[
                {"symbol": "069500", "quantity": 2, "avg_price": 30000},
            ],
            account_id="acc-test",
            skip_external_buy=True,
        )

        assert corrections == []
        # external-buy barrier 와 직교 — 미귀속 보유 이벤트는 발행된다.
        assert len(mismatch_events) == 1
        assert mismatch_events[0].reason == REASON_UNATTRIBUTED_HOLDING

    async def test_self_submitted_still_takes_precedence(
        self, reconciler, position_history, order_tracker, eventbus
    ):
        """capacity>0(추적 open buy 존재, excess<=capacity)는 #1950 self_submitted
        우선 — 미귀속 보유로 빠지지 않는다(경계 보존).
        """
        await _seed_open_order(
            order_tracker,
            order_id="ord-1",
            bot_id="bot-1",
            symbol="005930",
            ordered_qty=20,
        )
        notif_events: list = []
        eventbus.subscribe(NotificationEvent, lambda e: notif_events.append(e))

        corrections = await reconciler.reconcile(
            bot_id="bot-1",
            broker_positions=[
                {"symbol": "005930", "quantity": 20, "avg_price": 55000},
            ],
            account_id="acc-test",
        )

        assert corrections == []
        # self_submitted → info 알림(미귀속 보유 critical 아님).
        assert len(notif_events) == 1
        assert notif_events[0].level == "info"

    async def test_no_order_tracker_keeps_external_buy_for_carryover(
        self, service, eventbus
    ):
        """order_tracker 미주입이면 미귀속 판정 불가 → 기존 외부 매수 force-write
        유지(하위 호환 — main.py 두 배선 경로는 항상 주입).
        """
        rec = PositionReconciler(trade_service=service, eventbus=eventbus)
        corrections = await rec.reconcile(
            bot_id="bot-1",
            broker_positions=[
                {"symbol": "069500", "quantity": 2, "avg_price": 30000},
            ],
            account_id="acc-test",
        )
        assert len(corrections) == 1
        assert corrections[0]["reason"] == REASON_EXTERNAL_BUY


# ── #2058: account-scoped 승격 (account_id 전파 + entry validation) ──────


class TestReconcileAccountIdPropagation:
    """#2058: reconcile 이 발행하는 이벤트에 입력 account_id 가 전파되는지 검증."""

    async def test_mismatch_event_carries_input_account_id(
        self, reconciler, position_history, eventbus
    ):
        """(a) 발행된 PositionMismatchEvent.account_id == reconcile 입력 account_id."""
        await _set_position(
            position_history, "bot-1", "005930", 50, 50000, account_id="acc-test"
        )

        mismatch_events: list = []
        eventbus.subscribe(PositionMismatchEvent, lambda e: mismatch_events.append(e))

        await reconciler.reconcile(
            bot_id="bot-1",
            broker_positions=[],  # 전량 외부 청산
            account_id="acc-test",
        )

        assert len(mismatch_events) == 1
        assert mismatch_events[0].account_id == "acc-test"

    async def test_reconcile_event_carries_input_account_id(
        self, reconciler, position_history, eventbus
    ):
        """(b) 발행된 ReconcileEvent.account_id == reconcile 입력 account_id."""
        await _set_position(
            position_history, "bot-1", "005930", 50, 50000, account_id="acc-test"
        )

        reconcile_events: list = []
        eventbus.subscribe(ReconcileEvent, lambda e: reconcile_events.append(e))

        await reconciler.reconcile(
            bot_id="bot-1",
            broker_positions=[],
            account_id="acc-test",
        )

        assert len(reconcile_events) == 1
        assert reconcile_events[0].account_id == "acc-test"


class TestReconcileEntryValidation:
    """#2058: reconcile() 진입부 require_account_id fail-fast 검증.

    marker(_requires_account_id)가 아니라 entry validation 에서 raise되어,
    invalid account_id 는 어떤 이벤트도 발행되기 전에 차단된다.
    """

    @pytest.mark.parametrize("invalid", [None, "", "default"])
    async def test_invalid_account_id_raises_at_entry(
        self, reconciler, position_history, eventbus, invalid
    ):
        """(c) invalid account_id 면 InvalidAccountIdError raise + 이벤트 미발행."""
        await _set_position(
            position_history, "bot-1", "005930", 50, 50000, account_id="acc-test"
        )

        mismatch_events: list = []
        reconcile_events: list = []
        eventbus.subscribe(PositionMismatchEvent, lambda e: mismatch_events.append(e))
        eventbus.subscribe(ReconcileEvent, lambda e: reconcile_events.append(e))

        with pytest.raises(InvalidAccountIdError):
            await reconciler.reconcile(
                bot_id="bot-1",
                broker_positions=[],
                account_id=invalid,  # type: ignore[arg-type]
            )

        # entry 에서 차단되어 어떤 이벤트도 발행되지 않는다.
        assert mismatch_events == []
        assert reconcile_events == []


class TestReconcileEventsAccountScopedMarker:
    """#2058: 두 이벤트의 account-scoped marker 동작 (test_external_signals 동형)."""

    def test_mismatch_requires_account_id_marker(self) -> None:
        """_requires_account_id marker 가 True 이고 account_id 필드가 존재한다."""
        assert PositionMismatchEvent._requires_account_id is True
        assert "account_id" in PositionMismatchEvent.__dataclass_fields__

    def test_reconcile_requires_account_id_marker(self) -> None:
        """_requires_account_id marker 가 True 이고 account_id 필드가 존재한다."""
        assert ReconcileEvent._requires_account_id is True
        assert "account_id" in ReconcileEvent.__dataclass_fields__

    def test_mismatch_valid_account_id_constructs(self) -> None:
        """valid account_id 면 정상 생성된다."""
        event = PositionMismatchEvent(
            account_id="acc-test",
            bot_id="bot-1",
            symbol="005930",
            internal_qty=50.0,
            broker_qty=0.0,
            reason="외부 청산",
        )
        assert event.account_id == "acc-test"

    def test_reconcile_valid_account_id_constructs(self) -> None:
        """valid account_id 면 정상 생성된다."""
        event = ReconcileEvent(
            account_id="acc-test",
            bot_id="bot-1",
            discrepancy_count=1,
            corrections=[],
        )
        assert event.account_id == "acc-test"

    @pytest.mark.parametrize("invalid", [None, "", "default"])
    def test_mismatch_invalid_account_id_raises(self, invalid: str | None) -> None:
        """invalid account_id 면 InvalidAccountIdError raise."""
        with pytest.raises(InvalidAccountIdError):
            PositionMismatchEvent(
                account_id=invalid,  # type: ignore[arg-type]
                bot_id="bot-1",
                symbol="005930",
                internal_qty=50.0,
                broker_qty=0.0,
                reason="외부 청산",
            )

    @pytest.mark.parametrize("invalid", [None, "", "default"])
    def test_reconcile_invalid_account_id_raises(self, invalid: str | None) -> None:
        """invalid account_id 면 InvalidAccountIdError raise."""
        with pytest.raises(InvalidAccountIdError):
            ReconcileEvent(
                account_id=invalid,  # type: ignore[arg-type]
                bot_id="bot-1",
                discrepancy_count=1,
                corrections=[],
            )


# ── dry_run detect-only (#2119/#2122) ────────────────


class TestReconcileDryRun:
    """``dry_run=True`` 는 분류·이벤트는 유지하되 correct_position 을 보류한다.

    기존 external-buy/self-check 분류 로직은 무변경이며, 이벤트도 동일하게
    발행되어야 한다 — 보정(correct_position)만 건너뛴다.
    """

    async def test_dry_run_skips_correction_keeps_events(
        self, reconciler, position_history, eventbus
    ):
        """dry_run=True: 외부 청산을 탐지하나 보정은 0건. 이벤트는 발행."""
        await _set_position(position_history, "bot-1", "005930", 50, 50000)

        mismatch_events: list = []
        notif_events: list = []
        reconcile_events: list = []
        eventbus.subscribe(PositionMismatchEvent, lambda e: mismatch_events.append(e))
        eventbus.subscribe(NotificationEvent, lambda e: notif_events.append(e))
        eventbus.subscribe(ReconcileEvent, lambda e: reconcile_events.append(e))

        corrections = await reconciler.reconcile(
            bot_id="bot-1",
            broker_positions=[],  # 브로커 0주 → 외부 청산 분류.
            account_id="acc-test",
            dry_run=True,
        )

        # 보정 0건 — correct_position 미호출.
        assert corrections == []
        # 포지션은 그대로 (보정 안 됨).
        pos = await position_history.get_current("bot-1", "005930")
        assert pos["quantity"] == 50
        # 분류/탐지 이벤트는 그대로 발행.
        assert len(mismatch_events) == 1
        assert mismatch_events[0].reason == "외부 청산"
        assert len(notif_events) == 1
        # 보정이 0이므로 ReconcileEvent(보정 완료)는 발행 안 됨.
        assert reconcile_events == []

    async def test_dry_run_no_mismatch_no_events(
        self, reconciler, position_history, eventbus
    ):
        """dry_run=True 라도 일치하면 이벤트도 보정도 없음."""
        await _set_position(position_history, "bot-1", "005930", 50, 50000)
        mismatch_events: list = []
        eventbus.subscribe(PositionMismatchEvent, lambda e: mismatch_events.append(e))

        corrections = await reconciler.reconcile(
            bot_id="bot-1",
            broker_positions=[{"symbol": "005930", "quantity": 50, "avg_price": 1}],
            account_id="acc-test",
            dry_run=True,
        )

        assert corrections == []
        assert mismatch_events == []

    async def test_default_dry_run_false_still_corrects(
        self, reconciler, position_history
    ):
        """기존 호출자 무회귀: dry_run 미지정(기본 False)은 보정 동작 유지."""
        await _set_position(position_history, "bot-1", "005930", 50, 50000)

        corrections = await reconciler.reconcile(
            bot_id="bot-1",
            broker_positions=[],
            account_id="acc-test",
        )

        assert len(corrections) == 1
        pos = await position_history.get_current("bot-1", "005930")
        assert pos["quantity"] == 0


# ── account-level detect-only 합산 (#2118/#2120) ─────


class TestAccountLevelDetection:
    """계좌 총합 broker vs 전 봇(상태 무관) open internal 합산 비교.

    같은 심볼을 보유한 다중봇을 per-bot 비교가 false external-buy/청산으로
    오판하던 것을 합산으로 제거한다(#2118/#2120). correct_position 은 절대
    호출하지 않고 account-scoped NotificationEvent 만 발행한다.
    """

    async def test_multi_bot_same_symbol_sum_matches(
        self, reconciler, position_history, eventbus
    ):
        """(e/#2118) 두 봇 internal 30+70=100, 브로커 100 → 불일치 없음."""
        await _set_position(position_history, "bot-1", "005930", 30, 50000)
        await _set_position(position_history, "bot-2", "005930", 70, 50000)

        notif_events: list = []
        eventbus.subscribe(NotificationEvent, lambda e: notif_events.append(e))

        mismatches = await reconciler.detect_account_level(
            [{"symbol": "005930", "quantity": 100, "avg_price": 50000}],
            account_id="acc-test",
        )

        # 합산 일치 → false-positive 없음.
        assert mismatches == []
        assert notif_events == []

    async def test_multi_bot_sum_mismatch_emits_account_notification(
        self, reconciler, position_history, eventbus
    ):
        """(d) 합산 80, 브로커 100 → 계좌 단위 불일치 + account NotificationEvent.

        PositionMismatchEvent(bot-scoped)는 발행하지 않고 NotificationEvent 만.
        correct_position 미호출 (반환 mismatch 만, 보정 0).
        """
        await _set_position(position_history, "bot-1", "005930", 30, 50000)
        await _set_position(position_history, "bot-2", "005930", 50, 50000)

        notif_events: list = []
        mismatch_events: list = []
        eventbus.subscribe(NotificationEvent, lambda e: notif_events.append(e))
        eventbus.subscribe(PositionMismatchEvent, lambda e: mismatch_events.append(e))

        mismatches = await reconciler.detect_account_level(
            [{"symbol": "005930", "quantity": 100, "avg_price": 50000}],
            account_id="acc-test",
        )

        assert len(mismatches) == 1
        assert mismatches[0]["symbol"] == "005930"
        assert mismatches[0]["internal_qty"] == 80
        assert mismatches[0]["broker_qty"] == 100
        assert mismatches[0]["diff"] == 20
        # account-scoped: NotificationEvent 만, bot-scoped 이벤트 없음.
        assert len(notif_events) == 1
        assert notif_events[0].category == "broker"
        assert mismatch_events == []
        # 포지션은 보정되지 않음 (detect-only).
        pos1 = await position_history.get_current("bot-1", "005930")
        pos2 = await position_history.get_current("bot-2", "005930")
        assert pos1["quantity"] == 30
        assert pos2["quantity"] == 50

    async def test_zero_bots_with_broker_position_detected(self, reconciler, eventbus):
        """(k) 0봇 + broker 보유 → 계좌 단위 불일치 탐지 (no-op 아님)."""
        notif_events: list = []
        eventbus.subscribe(NotificationEvent, lambda e: notif_events.append(e))

        mismatches = await reconciler.detect_account_level(
            [{"symbol": "005930", "quantity": 10, "avg_price": 50000}],
            account_id="acc-test",
        )

        assert len(mismatches) == 1
        assert mismatches[0]["internal_qty"] == 0
        assert mismatches[0]["broker_qty"] == 10
        assert len(notif_events) == 1

    async def test_compute_account_diff_is_side_effect_free(
        self, reconciler, position_history, eventbus
    ):
        """compute_account_diff 는 이벤트/보정 없이 diff 만 반환한다(순수)."""
        await _set_position(position_history, "bot-1", "005930", 30, 50000)

        notif_events: list = []
        eventbus.subscribe(NotificationEvent, lambda e: notif_events.append(e))

        diff = await reconciler.compute_account_diff(
            [{"symbol": "005930", "quantity": 100, "avg_price": 50000}],
            account_id="acc-test",
        )

        assert len(diff) == 1
        assert diff[0]["diff"] == 70
        # 순수 — 이벤트 미발행.
        assert notif_events == []

    async def test_account_level_invalid_account_id_raises(self, reconciler):
        """(j) account-level 경로도 require_account_id 회귀."""
        with pytest.raises(InvalidAccountIdError):
            await reconciler.detect_account_level(
                [{"symbol": "005930", "quantity": 10}],
                account_id="default",
            )
