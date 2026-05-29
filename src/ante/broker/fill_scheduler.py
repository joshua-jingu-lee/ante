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
from dataclasses import dataclass
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

# 기동 카치업 bounded backoff. startup 폴이 CB/rate/network 로 실패하면 짧게
# 재시도해 일시 장애를 흡수한다. 모두 실패하면 succeeded=False 로 보고해 barrier
# 가 reconcile external-buy 분류를 건너뛰게 한다(미복구 체결 오분류 방지, #1946).
CATCH_UP_MAX_ATTEMPTS = 3
CATCH_UP_BACKOFF_BASE = 1.0


def business_date_kst(when: datetime | None = None) -> str:
    """KST 기준 영업일 ``YYYYMMDD`` (KIS ord_dt 매칭용)."""
    moment = when or datetime.now(UTC)
    return moment.astimezone(_KST).strftime("%Y%m%d")


@dataclass(frozen=True, slots=True)
class CatchUpResult:
    """기동 카치업 결과 (#1946 Finding 1).

    ``succeeded`` 는 startup 폴이 **명시적으로 끝났는지**(정상 0건/open-없음/체결
    적용 포함)를 뜻한다. CB/rate/network 로 폴 자체가 실패하면 ``succeeded=False``
    다 — 이 경우를 "0건 성공" 과 반드시 구분해야, main barrier 가 reconcile
    external-buy 분류를 건너뛰어 미복구 체결을 "외부 매수" 로 오분류하지 않는다.

    Attributes:
        succeeded: startup 폴이 성공(또는 명시적 open-없음)했는지.
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

    async def catch_up_once(self) -> CatchUpResult:
        """기동 카치업: open 주문이 있으면 1회 폴 → FillApplier.

        다운타임 중 발생한 체결을 멱등 따라잡는다. open 이 없으면 0콜·0건이며
        명시적 **성공**(``succeeded=True``)으로 본다.

        폴 자체가 CB/rate/network 로 실패하면 **bounded backoff 로 재시도**하고,
        그래도 실패하면 ``succeeded=False`` 를 반환한다. 주기 루프(``_loop``)와
        달리 startup 폴 실패를 "0건 성공" 으로 삼키지 않는다 — main barrier 가
        이 결과로 reconcile external-buy 분류를 건너뛸지 결정하기 때문이다
        (#1946 Finding 1).

        **barrier 보장**: main 기동에서 이 메서드의 await 완료 후에만
        ``ReconcileScheduler.start()`` 를 시작하고, ``succeeded`` 가 False 면
        external-buy 분류를 연기해, position reconcile 이 미복구 체결을
        "외부 매수" 로 오분류하지 않게 한다.
        """
        last_exc: Exception | None = None
        for attempt in range(1, CATCH_UP_MAX_ATTEMPTS + 1):
            try:
                applied = await self._poll_and_apply()
            except Exception as exc:  # CB open·rate·network — bounded 재시도.
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

        # 모든 시도 실패 — startup 폴 미성공. barrier 가 external-buy 분류를 연기.
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
        while self._running:
            await asyncio.sleep(self._poll_interval)
            if not self._running:
                return
            try:
                await self._poll_and_apply()
            except asyncio.CancelledError:
                raise
            except Exception:
                # 주기 루프는 폴 실패(CB/rate/network)를 삼키고 다음 사이클에
                # 멱등 재시도한다. (startup 카치업과 달리 barrier 영향 없음.)
                logger.warning(
                    "FillReconcileScheduler 폴 오류 (account=%s) — 다음 사이클 재시도",
                    self._account_id,
                    exc_info=True,
                )

    async def _poll_and_apply(self) -> int:
        """**poll-first**: open(만료 전) → history 1콜 → 적용 → 그 후 EOD 만료.

        순서가 곧 정합성 invariant 다 (#1946 메타리뷰).

        1. ``get_open_orders`` 로 추적 open(non-terminal)을 **만료 전에** 읽는다.
           ``from_date`` 는 그 open 들의 가장 이른 ``submitted_date`` 로 잡아, 전일
           open 이 있으면 폴 window 가 그 영업일까지 거슬러 올라간다(I8).
        2. open 이 있으면 ``get_order_history`` 1콜 → 관측 체결을
           ``FillApplier.apply_cumulative`` 로 멱등 적용한다(복구). 다운타임 중
           체결분(전일 open 포함)이 여기서 ``filled``/``partially_filled`` 로 전이
           되어 다음 단계의 만료 대상에서 **자동 제외**된다(I1·I2).
        3. **복구 후에** ``expire_stale`` 로 EOD 경과 + 체결 미관측(genuinely-dead)
           인 ``open`` 만 ``expired`` 로 전이한다. 부분 체결(``partially_filled``)은
           만료 대상이 아니다(체결 진행 중). 이로써 일중 미체결 주문의 무한 폴은
           막되, 다운타임 체결분을 만료/외부매수로 오분류하지 않는다(I2·I7).

        expire 를 poll **앞**에 두면(이전 결함), 전일 open 이 다운타임 중 체결됐어도
        복구 전에 expired 되어 폴 0콜·미복구로 남고, ``catch_up_once`` 가
        ``succeeded=True`` 를 반환해 barrier external-buy 차단이 무력화된다(#1945
        회귀). poll-first 가 이 구조를 해소한다(I3).

        Returns:
            적용된 체결(delta>0) 건수.

        Raises:
            Exception: ``get_order_history`` 실패(CB open·rate·network)를 그대로
                전파한다. 주기 루프(``_loop``)는 이를 잡아 삼키고 다음 사이클에
                멱등 재시도하나, ``catch_up_once`` 는 startup 폴 실패를 감지해
                barrier 결정에 반영한다. (실패 시 만료도 돌지 않아, 미복구
                체결분이 다음 성공 사이클의 폴 window 에 그대로 남는다 — I8.)
        """
        today = business_date_kst()

        # 1) 만료 **전에** open 을 읽어 폴 window 를 잡는다. 전일 open(다운타임
        #    체결 가능)도 이 시점엔 살아 있어 from_date 를 거슬러 덮는다(I8).
        open_orders = await self._tracker.get_open_orders(self._account_id)
        if not open_orders:
            # event-gated: 추적 open 주문이 없으면 폴하지 않는다 (0콜).
            # 만료시킬 open 도 없으므로 expire_stale 도 생략한다.
            return 0

        from_date = min(o.submitted_date for o in open_orders)
        to_date = today

        # 2) 사이클당 1콜로 history 를 폴해 다운타임 체결을 **먼저** 복구한다.
        #    (브로커 어댑터가 pagination 을 내부에서 처리.) 실패는 호출자에게
        #    전파한다(주기 루프는 삼키고, catch_up 은 재시도/보고) — 이때 아래
        #    expire 는 실행되지 않아 미복구 체결분이 영구 만료되지 않는다(I7).
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

        # 3) 복구가 끝난 **뒤에** EOD 경과 + 체결 미관측(genuinely-dead) open 만
        #    만료한다. 위 폴로 체결된 주문은 이미 filled/partially_filled 로 전이돼
        #    expire_stale 의 만료 대상(genuinely-dead open)에서 자동 제외된다(I2).
        await self._tracker.expire_stale(self._account_id, before_date=today)
        return applied
