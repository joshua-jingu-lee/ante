"""FillReconcileScheduler — 계좌별 event-gated 체결 백스톱 폴러 (#1946).

REST ``get_order_history`` 를 백스톱으로 폴해 추적 주문의 체결을 ``FillApplier`` 로
멱등 반영한다. 실시간 체결 통보 스트림 유무·paper/live 무관하게 정합성을 보증한다.

rate budget 보호:
- **event-gated**: open 주문이 없으면 폴하지 않는다(0콜, idle).
- open 이 있을 때만 ``get_order_history`` 를 **사이클당 1콜**.
- cadence **≥60s**. 주문 제출·가격 fallback 과 동일한 broker rate-limit 큐를
  공유하므로(``_rate_limit_wait``), 보수적 cadence + 1콜/사이클로 제출 starvation 을
  방지한다.

상세 설계: ``docs/specs/broker-adapter/18-fill-recovery.md``.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta, timezone
from typing import TYPE_CHECKING

from ante.account.scoping import require_account_id

if TYPE_CHECKING:
    from ante.broker.base import BrokerAdapter
    from ante.trade.fill_applier import FillApplier
    from ante.trade.order_tracker import OrderTracker

logger = logging.getLogger(__name__)

# KIS 주문/체결 이력은 KST(UTC+9) 영업일(ord_dt, YYYYMMDD)을 기준으로 한다.
_KST = timezone(timedelta(hours=9))

# 최소 폴 cadence. rate budget(paper 5/min·live 20/min, 제출/가격/대사 공유)을
# 보호하기 위해 60s 미만으로 내려가지 않는다.
MIN_POLL_INTERVAL = 60.0
DEFAULT_POLL_INTERVAL = 60.0


def business_date_kst(when: datetime | None = None) -> str:
    """KST 기준 영업일 ``YYYYMMDD`` (KIS ord_dt 매칭용)."""
    moment = when or datetime.now(UTC)
    return moment.astimezone(_KST).strftime("%Y%m%d")


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
    ) -> None:
        require_account_id(account_id, context="fill_scheduler.__init__")
        self._broker = broker
        self._tracker = order_tracker
        self._applier = fill_applier
        self._account_id = account_id
        self._poll_interval = max(poll_interval, MIN_POLL_INTERVAL)
        self._task: asyncio.Task[None] | None = None
        self._running = False

    @property
    def account_id(self) -> str:
        return self._account_id

    async def catch_up_once(self) -> int:
        """기동 카치업: open 주문이 있으면 1회 폴 → FillApplier.

        다운타임 중 발생한 체결을 멱등 따라잡는다. 적용된 체결 이벤트 수를
        반환한다. open 이 없으면 0콜·0건.

        **barrier 보장**: main 기동에서 이 메서드의 await 완료 후에만
        ``ReconcileScheduler.start()`` 를 시작해, position reconcile 이 미복구
        체결을 "외부 매수" 로 오분류하지 않게 한다.
        """
        return await self._poll_and_apply()

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
        while self._running:
            await asyncio.sleep(self._poll_interval)
            if not self._running:
                return
            try:
                await self._poll_and_apply()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "FillReconcileScheduler 폴 오류 (account=%s)", self._account_id
                )

    async def _poll_and_apply(self) -> int:
        """open 있을 때만 get_order_history 1콜 → 매칭 주문 FillApplier 적용.

        Returns:
            적용된 체결(delta>0) 건수.
        """
        open_orders = await self._tracker.get_open_orders(self._account_id)
        if not open_orders:
            # event-gated: 추적 open 주문이 없으면 폴하지 않는다 (0콜).
            return 0

        # window: 가장 이른 추적 open 주문의 영업일부터 오늘(KST)까지.
        from_date = min(o.submitted_date for o in open_orders)
        to_date = business_date_kst()

        try:
            # 사이클당 1콜. (브로커 어댑터가 pagination 을 내부에서 처리.)
            history = await self._broker.get_order_history(
                from_date=from_date, to_date=to_date
            )
        except Exception:
            # CB open·rate·네트워크 실패 — 다음 사이클에서 멱등 재시도.
            logger.warning(
                "FillReconcileScheduler get_order_history 실패 (account=%s)",
                self._account_id,
                exc_info=True,
            )
            return 0

        applied = 0
        for item in history:
            broker_order_id = str(item.get("order_id", ""))
            if not broker_order_id:
                continue
            cumulative = float(item.get("filled_quantity", 0.0) or 0.0)
            if cumulative <= 0:
                continue
            avg_price = float(item.get("price", 0.0) or 0.0)
            item_date = str(item.get("timestamp", "")) or to_date
            delta = await self._applier.apply_cumulative(
                account_id=self._account_id,
                broker_order_id=broker_order_id,
                observed_cumulative=cumulative,
                avg_price=avg_price,
                submitted_date=item_date,
            )
            if delta > 0:
                applied += 1
        return applied
