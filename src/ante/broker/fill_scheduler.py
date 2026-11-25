"""FillReconcileScheduler — 계좌별 event-gated 체결 백스톱 폴러."""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from typing import TYPE_CHECKING

from ante.broker.exceptions import APIError, CircuitOpenError
from ante.core import clock
from ante.core.account_id import require_account_id

if TYPE_CHECKING:
    from ante.broker.base import BrokerAdapter
    from ante.eventbus.bus import EventBus
    from ante.instrument.service import InstrumentService
    from ante.trade.fill_applier import FillApplier
    from ante.trade.order_tracker import OrderTracker, OrderTrackerRecord
    from ante.trade.service import TradeService

logger = logging.getLogger(__name__)

_KST = timezone(timedelta(hours=9))

MIN_POLL_INTERVAL = 60.0
DEFAULT_POLL_INTERVAL = 60.0

CATCH_UP_MAX_ATTEMPTS = 3
CATCH_UP_BACKOFF_BASE = 1.0

LOOP_BACKOFF_MULTIPLIER_CAP = 8

_LOOP_BACKOFF_EXCEPTIONS: tuple[type[Exception], ...] = (
    TimeoutError,
    CircuitOpenError,
    APIError,
    ConnectionError,
    OSError,
)


def business_date_kst(when: datetime | None = None) -> str:
    """KST 기준 영업일 ``YYYYMMDD`` (KIS ord_dt 매칭용)."""
    moment = when or clock.now(UTC)
    return moment.astimezone(_KST).strftime("%Y%m%d")


def _normalize_history_date(raw: str) -> str:
    """``get_order_history`` 의 ``timestamp`` 를 KST 영업일 ``YYYYMMDD`` 로 정규화."""
    if re.fullmatch(r"\d{8}", raw):
        return raw
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return business_date_kst(dt)


@dataclass(frozen=True, slots=True)
class _FallbackVerifyEntry:
    """fallback 이 advance 한 주문의 사후 ccld 검증 항목.

    이 항목은 **in-memory 보조 상태일 뿐**이며 OrderTracker/positions/trades/
    outbox 를 직접 수정하지 않는다(§11.8 단일 권위 보존). 폴 window 의 from_date
    가 ``submitted_date`` 까지 거슬러 덮도록 보장하고, ccld 절대 누적이 fallback
    이 advance 한 ``recorded`` 미만이면 alert 1회 후 제거, 동일/높으면 조용히
    제거한다. 무한 누적 방지를 위해 영업일 경계(D+1)에 정리한다(§11.5).
    """

    recorded: float
    submitted_date: str


@dataclass(frozen=True, slots=True)
class CatchUpResult:
    """기동 카치업 결과.

    ``succeeded`` 는 startup 폴이 **명시적으로 끝났는지**(정상 0건/open-없음/체결
    적용 포함)를 뜻한다. CB/rate/network 로 폴 자체가 실패하면 ``succeeded=False``
    다 — 이 경우를 "0건 성공" 과 반드시 구분해야, main barrier 가 reconcile
    external-buy 분류를 건너뛰어 미복구 체결을 "외부 매수" 로 오분류하지 않는다.

    Attributes:
        applied: 적용된 체결(delta>0) 건수.
    """

    succeeded: bool
    applied: int


class FillReconcileScheduler:
    """계좌별 체결 백스톱 폴러."""

    def __init__(
        self,
        *,
        broker: BrokerAdapter,
        order_tracker: OrderTracker,
        fill_applier: FillApplier,
        account_id: str,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        trade_service: TradeService | None = None,
        eventbus: EventBus | None = None,
        fallback_enabled: bool = True,
        instrument_service: InstrumentService | None = None,
    ) -> None:
        """계좌별 체결 백스톱 폴러.

        Args:
            eventbus: late-ccld over-attribution alert(§11.4) 발행용.
                ``None`` 이면 alert 를 surface 하지 못하나(best-effort), 멱등성·
                수렴 정확성은 영향받지 않는다.
            fallback_enabled: position-derived fallback **마스터 disable flag**
                (§11.6). KIS paper 기본 활성을 두되 ``False`` 로 rollback
                가능. 실제 적용은 추가로 ``broker.is_paper`` 가 true 여야 한다.
        """
        require_account_id(account_id, context="fill_scheduler.__init__")
        self._broker = broker
        self._tracker = order_tracker
        self._applier = fill_applier
        self._account_id = account_id
        self._poll_interval = max(poll_interval, MIN_POLL_INTERVAL)
        self._trade_service = trade_service
        self._eventbus = eventbus
        self._fallback_enabled = fallback_enabled
        self._instrument_service = instrument_service
        self._task: asyncio.Task[None] | None = None
        self._running = False
        self._fallback_verify: dict[str, _FallbackVerifyEntry] = {}
        self._last_success_poll_date: str | None = None

    @property
    def account_id(self) -> str:
        return self._account_id

    async def catch_up_once(self) -> CatchUpResult:
        """기동 카치업: open 주문이 있으면 1회 폴 → FillApplier.

        다운타임 중 발생한 체결을 멱등 따라잡는다. open 이 없으면 0콜·0건이며
        명시적 **성공**(``succeeded=True``)으로 본다.

        폴 자체가 CB/rate/network 로 실패하면 **bounded backoff 로 재시도**하고,
        그래도 실패하면 ``succeeded=False`` 를 반환한다. 주기 루프(``_loop``)와
        달리 startup 폴 실패를 "0건 성공" 으로 삼키지 않는다 — main barrier 가
        이 결과로 reconcile external-buy 분류를 건너뛸지 결정하기 때문이다.
        """
        last_exc: Exception | None = None
        for attempt in range(1, CATCH_UP_MAX_ATTEMPTS + 1):
            try:
                applied = await self._poll_and_apply()
            except Exception as exc:
                last_exc = exc
                if attempt < CATCH_UP_MAX_ATTEMPTS:
                    backoff = CATCH_UP_BACKOFF_BASE * attempt
                    logger.warning(
                        "기동 카치업 폴 실패 (account=%s, attempt=%d/%d) — "
                        "%.1fs 후 재시도",
                        self._account_id,
                        attempt,
                        CATCH_UP_MAX_ATTEMPTS,
                        backoff,
                        exc_info=True,
                    )
                    await asyncio.sleep(backoff)
                continue
            else:
                return CatchUpResult(succeeded=True, applied=applied)

        logger.error(
            "기동 카치업 폴 %d회 모두 실패 (account=%s) — reconcile external-buy "
            "분류를 연기한다",
            CATCH_UP_MAX_ATTEMPTS,
            self._account_id,
            exc_info=last_exc,
        )
        return CatchUpResult(succeeded=False, applied=0)

    async def start(self) -> None:
        """주기 폴 루프 시작 (catch_up_once 와 별개의 background task)."""
        if self._task and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(
            self._loop(), name=f"fill-reconcile-{self._account_id}"
        )
        logger.info(
            "FillReconcileScheduler 시작 (account=%s, cadence=%.0fs)",
            self._account_id,
            self._poll_interval,
        )

    async def stop(self) -> None:
        """루프 중지."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _loop(self) -> None:
        """steady-state 주기 폴 루프 (+ 연속 실패 cooldown)."""
        consecutive_transient_failures = 0
        while self._running:
            if consecutive_transient_failures > 0:
                multiplier = min(
                    2**consecutive_transient_failures, LOOP_BACKOFF_MULTIPLIER_CAP
                )
                sleep_for = self._poll_interval * multiplier
            else:
                sleep_for = self._poll_interval
            await asyncio.sleep(sleep_for)
            if not self._running:
                return
            try:
                await self._poll_and_apply()
            except asyncio.CancelledError:
                raise
            except _LOOP_BACKOFF_EXCEPTIONS:
                consecutive_transient_failures += 1
                logger.warning(
                    "FillReconcileScheduler 폴 오류 (account=%s, 연속실패=%d) — "
                    "%.0fs 후 재시도",
                    self._account_id,
                    consecutive_transient_failures,
                    self._poll_interval
                    * min(
                        2**consecutive_transient_failures,
                        LOOP_BACKOFF_MULTIPLIER_CAP,
                    ),
                    exc_info=True,
                )
            except Exception:
                consecutive_transient_failures = 0
                logger.warning(
                    "FillReconcileScheduler 폴 오류 (account=%s) — 다음 사이클 재시도",
                    self._account_id,
                    exc_info=True,
                )
            else:
                consecutive_transient_failures = 0

    async def _poll_and_apply(self) -> int:
        """**poll-first**: open·감시(만료 전) → history 1콜 → fallback → EOD 만료."""
        today = business_date_kst()

        open_orders = await self._tracker.get_open_orders(self._account_id)
        watch = await self._tracker.get_late_fill_watch(
            self._account_id, self._late_fill_watch_since(today)
        )
        if not open_orders and not self._fallback_verify and not watch:
            return 0

        candidate_dates = [o.submitted_date for o in open_orders]
        candidate_dates.extend(o.submitted_date for o in watch)
        candidate_dates.extend(e.submitted_date for e in self._fallback_verify.values())
        from_date = min(candidate_dates)
        to_date = today

        history = await self._broker.get_order_history(
            from_date=from_date, to_date=to_date
        )

        applied = 0
        for item in history:
            broker_order_id = str(item.get("order_id", ""))
            if not broker_order_id:
                continue
            cumulative = float(item.get("filled_quantity", 0.0) or 0.0)
            if cumulative <= 0:
                continue
            avg_price = float(item.get("price", 0.0) or 0.0)
            item_date = (
                _normalize_history_date(str(item.get("timestamp", ""))) or to_date
            )
            await self._verify_fallback_against_ccld(
                broker_order_id=broker_order_id,
                observed_cumulative=cumulative,
                item_date=item_date,
            )
            delta = await self._applier.apply_cumulative(
                account_id=self._account_id,
                broker_order_id=broker_order_id,
                observed_cumulative=cumulative,
                avg_price=avg_price,
                submitted_date=item_date,
            )
            if delta > 0:
                applied += 1

        applied += await self._apply_position_fallback()

        await self._tracker.expire_stale(self._account_id, before_date=today)
        self._expire_stale_fallback_verify(before_date=today)
        self._last_success_poll_date = today
        return applied

    def _late_fill_watch_since(self, today: str) -> str:
        """감시 창의 시작(오늘 첫 성공 폴 전이면 어제의 KST 자정)을 UTC 문자열로."""
        start = datetime.strptime(today, "%Y%m%d").replace(tzinfo=_KST)
        if self._last_success_poll_date != today:
            start -= timedelta(days=1)
        return start.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S")

    def _expire_stale_fallback_verify(self, *, before_date: str) -> None:
        """``_fallback_verify`` 의 D-1 이전 항목을 정리한다 (§11.5)."""
        stale = [
            odno
            for odno, entry in self._fallback_verify.items()
            if entry.submitted_date < before_date
        ]
        for odno in stale:
            del self._fallback_verify[odno]
        if stale:
            logger.debug(
                "fallback verify EOD 정리: account=%s, %d건 (before=%s)",
                self._account_id,
                len(stale),
                before_date,
            )

    async def _verify_fallback_against_ccld(
        self,
        *,
        broker_order_id: str,
        observed_cumulative: float,
        item_date: str,
    ) -> None:
        """fallback 적용 주문의 ccld 절대 누적을 검증해 over-attribution 을 surface."""
        entry = self._fallback_verify.get(broker_order_id)
        if entry is None:
            return
        if entry.submitted_date != item_date:
            return
        recorded = entry.recorded
        if 0 < observed_cumulative < recorded:
            await self._emit_late_ccld_alert(
                broker_order_id=broker_order_id,
                recorded=recorded,
                observed_cumulative=observed_cumulative,
                submitted_date=entry.submitted_date,
            )
        self._fallback_verify.pop(broker_order_id, None)

    async def _emit_late_ccld_alert(
        self,
        *,
        broker_order_id: str,
        recorded: float,
        observed_cumulative: float,
        submitted_date: str,
    ) -> None:
        """late-ccld over-attribution 경보 1회 발행 (§11.4, normative)."""
        if self._eventbus is None:
            return
        record = await self._tracker.find_by_broker_order(
            self._account_id, broker_order_id, submitted_date
        )
        if record is None:
            return
        order_id = record.order_id
        diff = recorded - observed_cumulative
        logger.warning(
            "late-ccld over-attribution 의심: account=%s odno=%s order=%s "
            "recorded=%s ccld_cumulative=%s diff=%s — 비가역(CAS no-op), 경보만",
            self._account_id,
            broker_order_id,
            order_id,
            recorded,
            observed_cumulative,
            diff,
        )
        from ante.eventbus.events import NotificationEvent, PositionMismatchEvent

        await self._eventbus.publish(
            PositionMismatchEvent(
                account_id=self._account_id,
                bot_id=record.bot_id,
                symbol=record.symbol,
                internal_qty=recorded,
                broker_qty=observed_cumulative,
                reason=(
                    "late_ccld_over_attribution: position-derived fallback advanced "
                    f"recorded={recorded} but ccld returned lower cumulative="
                    f"{observed_cumulative} (odno={broker_order_id}, "
                    f"order={order_id}, diff={diff}) — irreversible (CAS no-op)"
                ),
            )
        )
        symbol_label = (
            self._instrument_service.format_label(record.symbol)
            if self._instrument_service is not None
            else record.symbol
        )
        await self._eventbus.publish(
            NotificationEvent(
                level="warning",
                title="체결 over-attribution 의심 (모의 fallback)",
                message=(
                    f"잔고 역도출 fallback 이 {symbol_label} 주문(odno="
                    f"{broker_order_id})을 recorded={recorded} 로 올렸으나, 이후 "
                    f"ccld 가 더 낮은 누적={observed_cumulative} (diff={diff})를 "
                    "반환했습니다. 비가역이라 정정되지 않으며 협소 외부 매수 흡수 "
                    "가능성을 경보합니다(§11.4·§11.7)."
                ),
                category="reconcile",
            )
        )

    async def _apply_position_fallback(self) -> int:
        """position-derived bounded fallback (§11). 적용 건수 반환."""
        if not (self._fallback_enabled and self._trade_service is not None):
            return 0
        if not getattr(self._broker, "is_paper", False):
            return 0

        open_orders = await self._tracker.get_open_orders(self._account_id)
        open_buy_count_by_symbol: dict[str, int] = {}
        for o in open_orders:
            if o.side == "buy":
                open_buy_count_by_symbol[o.symbol] = (
                    open_buy_count_by_symbol.get(o.symbol, 0) + 1
                )
        unrecovered_buys = [
            o
            for o in open_orders
            if o.side == "buy" and o.recorded_filled_qty == 0 and o.ordered_qty > 0
        ]
        if not unrecovered_buys:
            return 0

        broker_positions = await self._broker.get_positions()
        broker_qty_by_symbol: dict[str, float] = {}
        avg_price_by_symbol: dict[str, float] = {}
        for bp in broker_positions:
            symbol = str(bp.get("symbol", ""))
            if not symbol:
                continue
            qty = float(bp.get("quantity", 0.0) or 0.0)
            broker_qty_by_symbol[symbol] = broker_qty_by_symbol.get(symbol, 0.0) + qty
            if symbol not in avg_price_by_symbol:
                avg_price_by_symbol[symbol] = float(bp.get("avg_price", 0.0) or 0.0)

        internal_positions = await self._trade_service.get_all_positions(
            account_id=self._account_id
        )
        internal_qty_by_symbol: dict[str, float] = {}
        for p in internal_positions:
            if p.quantity > 0:
                internal_qty_by_symbol[p.symbol] = (
                    internal_qty_by_symbol.get(p.symbol, 0.0) + p.quantity
                )

        buys_by_symbol: dict[str, list[OrderTrackerRecord]] = {}
        for o in unrecovered_buys:
            buys_by_symbol.setdefault(o.symbol, []).append(o)

        applied = 0
        for symbol, orders in buys_by_symbol.items():
            if open_buy_count_by_symbol.get(symbol, 0) != 1:
                logger.debug(
                    "fallback 미적용(다중 non-terminal open buy): account=%s "
                    "symbol=%s open_buy_count=%d",
                    self._account_id,
                    symbol,
                    open_buy_count_by_symbol.get(symbol, 0),
                )
                continue
            order = orders[0]
            broker_qty = broker_qty_by_symbol.get(symbol, 0.0)
            internal_qty = internal_qty_by_symbol.get(symbol, 0.0)
            excess = broker_qty - internal_qty
            if excess <= 0:
                continue
            if excess != order.ordered_qty:
                logger.debug(
                    "fallback 미적용(partial/모호 excess): account=%s symbol=%s "
                    "excess=%s ordered=%s — D+1 ccld 대기",
                    self._account_id,
                    symbol,
                    excess,
                    order.ordered_qty,
                )
                continue
            avg_price = avg_price_by_symbol.get(symbol, order.avg_fill_price)
            delta = await self._applier.apply_cumulative(
                account_id=self._account_id,
                broker_order_id=order.broker_order_id,
                observed_cumulative=order.ordered_qty,
                avg_price=avg_price,
                submitted_date=order.submitted_date,
            )
            if delta > 0:
                applied += 1
                self._fallback_verify[order.broker_order_id] = _FallbackVerifyEntry(
                    recorded=order.ordered_qty,
                    submitted_date=order.submitted_date,
                )
                logger.info(
                    "position-derived fallback 수렴: account=%s symbol=%s odno=%s "
                    "order=%s full_fill=%s @ %s (excess==ordered)",
                    self._account_id,
                    symbol,
                    order.broker_order_id,
                    order.order_id,
                    order.ordered_qty,
                    avg_price,
                )
        return applied
