"""FillReconcileScheduler — 계좌별 event-gated 체결 백스톱 폴러 (#1946).

REST ``get_order_history`` 를 백스톱으로 폴해 추적 주문의 체결을 ``FillApplier`` 로
멱등 반영한다. 실시간 체결 통보 스트림 유무·paper/live 무관하게 정합성을 보증한다.

rate budget 보호:
- **event-gated**: open 주문이 없으면 폴하지 않는다(0콜, idle).
- open 이 있을 때만 ``get_order_history`` 를 **사이클당 1콜**.
- cadence **≥60s**. 주문 제출·가격 fallback 과 동일한 broker rate-limit 큐를
  공유하므로(``_rate_limit_wait``), 보수적 cadence + 1콜/사이클로 제출 starvation 을
  방지한다.

position-derived bounded fallback (#2314·#2316 §11):
- KIS 모의 ``inquire-daily-ccld``(``get_order_history``)는 일별 결제기준 원장이라
  당일 체결을 0건으로 지연 반영한다. 반면 잔고(``get_positions``)는 체결기준
  즉시반영이다. 백스톱이 당일 0건을 줄 때 잔고 증분(``broker_qty -
  internal_account_qty``)에서 self-submitted 체결을 **보수적 역도출**해
  ``FillApplier.apply_cumulative`` 로 멱등 수렴한다(§11.8 단일 권위 — 새 권위자
  미생성). **KIS paper 한정 기본 활성**(§11.6), disable flag 로 rollback 가능.

상세 설계: ``docs/specs/broker-adapter/18-fill-recovery.md`` (§11).
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from typing import TYPE_CHECKING

from ante.account.scoping import require_account_id

if TYPE_CHECKING:
    from ante.broker.base import BrokerAdapter
    from ante.eventbus.bus import EventBus
    from ante.trade.fill_applier import FillApplier
    from ante.trade.order_tracker import OrderTracker, OrderTrackerRecord
    from ante.trade.service import TradeService

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


def _normalize_history_date(raw: str) -> str:
    """``get_order_history`` 의 ``timestamp`` 를 KST 영업일 ``YYYYMMDD`` 로 정규화.

    ``OrderTracker.lookup_order_id`` 와 ``FillApplier.apply_cumulative`` 는
    ``submitted_date`` 를 KST 영업일 ``YYYYMMDD`` 문자열로 가정해 tracker seed 의
    ``submitted_date`` 와 ``<=`` 비교한다(order_tracker.py §4.1). 그런데
    Test/Mock 어댑터의 ``get_order_history`` 는 ``created_at.isoformat()`` (ISO
    8601) 을 ``timestamp`` 로 내보내므로, 정규화 없이 그대로 넘기면 ISO 문자열이
    ``YYYYMMDD`` 와의 문자열 비교에서 항상 큰 값이 되어 매핑이 누락되고 복구가
    no-op(applied=0)이 된다(#2004). KIS 어댑터는 이미 ``ord_dt`` (YYYYMMDD) 를
    내보내므로 그대로 통과시킨다.

    Args:
        raw: ``get_order_history`` item 의 ``timestamp`` 원문 문자열.

    Returns:
        KST 영업일 ``YYYYMMDD``. 빈 문자열이거나 ISO 파싱이 불가하면 ``""`` 를
        반환해 호출부가 ``to_date`` fallback 을 적용하게 한다.
    """
    if re.fullmatch(r"\d{8}", raw):
        # YYYYMMDD passthrough (KIS ord_dt).
        return raw
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return ""
    if dt.tzinfo is None:
        # naive ISO 는 UTC 로 가정한 뒤 KST 영업일로 환산한다.
        dt = dt.replace(tzinfo=UTC)
    return business_date_kst(dt)


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
        trade_service: TradeService | None = None,
        eventbus: EventBus | None = None,
        fallback_enabled: bool = True,
    ) -> None:
        """계좌별 체결 백스톱 폴러.

        Args:
            broker: 계좌 BrokerAdapter. ``get_order_history`` 백스톱과 (#2314
                fallback 활성 시) ``get_positions`` 잔고 역도출을 제공한다.
            order_tracker: 추적 주문 저장소.
            fill_applier: 단일 멱등 choke point. 모든 체결 수렴은 이 경로뿐이다.
            account_id: 계좌 ID.
            poll_interval: 주기 폴 cadence(초). ``MIN_POLL_INTERVAL`` 하한.
            trade_service: 내부 account-level 포지션 조회 의존성(#2316 §11.1
                ``internal_account_qty`` = ``get_all_positions(account_id)`` 합산).
                position-derived fallback 에만 쓰인다. ``None`` 이면 fallback 은
                동작하지 않는다(legacy/partial wiring).
            eventbus: late-ccld over-attribution alert(#2316 §11.4) 발행용.
                ``None`` 이면 alert 를 surface 하지 못하나(best-effort), 멱등성·
                수렴 정확성은 영향받지 않는다.
            fallback_enabled: position-derived fallback **마스터 disable flag**
                (#2316 §11.6). KIS paper 기본 활성을 두되 ``False`` 로 rollback
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
        """**poll-first**: open(만료 전) → history 1콜 → fallback → 그 후 EOD 만료.

        순서가 곧 정합성 invariant 다 (#1946 메타리뷰, #2316 §11.2).

        1. ``get_open_orders`` 로 추적 open(non-terminal)을 **만료 전에** 읽는다.
           ``from_date`` 는 그 open 들의 가장 이른 ``submitted_date`` 로 잡아, 전일
           open 이 있으면 폴 window 가 그 영업일까지 거슬러 올라간다(I8).
        2. open 이 있으면 ``get_order_history`` 1콜 → 관측 체결을
           ``FillApplier.apply_cumulative`` 로 멱등 적용한다(복구). 다운타임 중
           체결분(전일 open 포함)이 여기서 ``filled``/``partially_filled`` 로 전이
           되어 다음 단계의 만료 대상에서 **자동 제외**된다(I1·I2).
        3. **(신규 #2314)** ②(ccld) 적용 후에도 남은 미복구 open buy 가 있으면
           ``get_positions`` 잔고 역도출 fallback 을 적용한다(KIS paper 한정 기본
           활성, §11). ccld 가 체결을 줘 capacity 가 advance 된 경우엔 ``excess``
           가 0 으로 수렴해 fallback 이 본질적으로 no-op 이며, 애초에 미복구 open
           buy 가 없으면 ``get_positions`` 자체를 **호출하지 않아 rate budget 을
           보호**한다(§11.2).
        4. **fallback 후에** ``expire_stale`` 로 EOD 경과 + 체결 미관측
           (genuinely-dead)인 ``open`` 만 ``expired`` 로 전이한다. 부분 체결
           (``partially_filled``)은 만료 대상이 아니다(체결 진행 중). 만료를
           fallback **앞**에 두면 모의 당일 미반영 체결을 가진 open 이 복구 전에
           expired 되어 fallback 이 대상을 잃는다(§11.5).

        expire 를 poll **앞**에 두면(이전 결함), 전일 open 이 다운타임 중 체결됐어도
        복구 전에 expired 되어 폴 0콜·미복구로 남고, ``catch_up_once`` 가
        ``succeeded=True`` 를 반환해 barrier external-buy 차단이 무력화된다(#1945
        회귀). poll-first 가 이 구조를 해소한다(I3).

        Returns:
            적용된 체결(delta>0) 건수(ccld + fallback 합산).

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
            # ISO timestamp(Test/Mock) 는 KST 영업일 YYYYMMDD 로 정규화한다.
            # tracker 의 submitted_date(<=) 매칭 전제와 맞춰 복구 no-op 을
            # 방지한다(#2004). KIS ord_dt(YYYYMMDD)는 그대로 통과. 빈/파싱불가
            # 는 to_date(오늘 KST) 로 fallback.
            item_date = (
                _normalize_history_date(str(item.get("timestamp", ""))) or to_date
            )
            # #2316 §11.4 late-ccld over-attribution alert: fallback 이 full fill
            # 로 올린 누적보다 ccld 가 **더 낮은** 절대 누적을 주면 CAS 단조성으로
            # no-op 이라 정정은 불가하나, 침묵 흡수하지 않고 surface 한다. 적용
            # 전에 현재 recorded 와 비교한다(아래 apply_cumulative 가 멱등 no-op).
            await self._maybe_alert_late_ccld(
                broker_order_id=broker_order_id,
                observed_cumulative=cumulative,
                submitted_date=item_date,
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

        # 3) **(신규 #2314·#2316 §11)** ccld 가 채우지 못한 미복구 open buy 가
        #    남아 있을 때만 잔고-역도출 fallback 을 적용한다. open 을 ccld 적용
        #    **후** 재조회해 advance 된 recorded_filled_qty 를 반영한다.
        applied += await self._apply_position_fallback()

        # 4) fallback 이 끝난 **뒤에** EOD 경과 + 체결 미관측(genuinely-dead) open
        #    만 만료한다. 위 폴/fallback 으로 체결된 주문은 이미 filled/
        #    partially_filled 로 전이돼 expire_stale 의 만료 대상(genuinely-dead
        #    open)에서 자동 제외된다(I2·§11.5).
        await self._tracker.expire_stale(self._account_id, before_date=today)
        return applied

    async def _maybe_alert_late_ccld(
        self,
        *,
        broker_order_id: str,
        observed_cumulative: float,
        submitted_date: str,
    ) -> None:
        """late-ccld over-attribution 가능성을 surface (#2316 §11.4, normative).

        fallback 이 full fill(``observed_cumulative = ordered_qty``)로 advance 한
        뒤, 이후 ccld 폴이 그 주문에 **더 낮은 절대 누적**(현 ``recorded_filled_qty``
        미만)을 주면 CAS 단조성으로 ``record_fill`` 이 no-op 이라 정정은 불가하다.
        이는 fallback 이 협소 외부 매수(§11.7)를 self 로 흡수했을 가능성을 뜻하므로,
        침묵 흡수하지 않고 ``PositionMismatchEvent``/``NotificationEvent`` 로
        경보한다(비가역이라 정정은 못 하나 운영 관측 가능).

        조건: ``0 < observed_cumulative < recorded_filled_qty``. eventbus 미주입이면
        best-effort 로 생략(멱등성·정확성에는 영향 없음).
        """
        if self._eventbus is None:
            return
        # terminal-inclusive lookup: fallback 으로 filled(terminal)된 주문도 잡아야
        # over-attribution 을 surface 할 수 있다(non-terminal scope 면 누락).
        record = await self._tracker.find_by_broker_order(
            self._account_id, broker_order_id, submitted_date
        )
        if record is None:
            return
        order_id = record.order_id
        recorded = record.recorded_filled_qty
        # ccld 가 0 이거나 현재 recorded 이상이면 정상 경로(멱등 advance/no-op).
        # recorded 보다 **낮은 양수** 누적일 때만 over-attribution 의심.
        if not (0 < observed_cumulative < recorded):
            return
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
        await self._eventbus.publish(
            NotificationEvent(
                level="warning",
                title="체결 over-attribution 의심 (모의 fallback)",
                message=(
                    f"잔고 역도출 fallback 이 {record.symbol} 주문(odno="
                    f"{broker_order_id})을 recorded={recorded} 로 올렸으나, 이후 "
                    f"ccld 가 더 낮은 누적={observed_cumulative} (diff={diff})를 "
                    "반환했습니다. 비가역이라 정정되지 않으며 협소 외부 매수 흡수 "
                    "가능성을 경보합니다(§11.4·§11.7)."
                ),
                category="reconcile",
            )
        )

    async def _apply_position_fallback(self) -> int:
        """position-derived bounded fallback (#2314·#2316 §11). 적용 건수 반환.

        ②(ccld) 적용 후에도 남은 **미복구 open buy** 가 있을 때만, 잔고
        (``get_positions``, 체결기준 즉시반영) 증분에서 self-submitted full fill 을
        보수적으로 역도출해 ``FillApplier.apply_cumulative`` 로 멱등 수렴한다.

        gate(전부 AND):
        - ``fallback_enabled`` (마스터 disable flag, §11.6) 와 ``broker.is_paper``
          가 모두 true(KIS paper 한정 기본 활성).
        - ``trade_service`` 주입(``internal_account_qty`` 조회 의존성, §11.1).
        - ccld 가 채우지 못한 **미복구 open buy(``recorded_filled_qty == 0``)** 가
          남아 있음. 없으면 ``get_positions`` 를 **호출하지 않는다**(rate budget
          보호, §11.2).

        적용(symbol 단위, §11.3 full-fill 정확매칭 — 전부 AND):
        - 그 ``(account, symbol, side="buy")`` 의 추적 open buy 가 **정확히 하나**.
        - 그 유일 주문이 ``recorded_filled_qty == 0``.
        - 잔고 excess(``broker_qty - internal_account_qty``)가 그 주문
          ``ordered_qty`` 와 **정확히 일치**(``excess == ordered_qty``).
        → ``observed_cumulative = ordered_qty`` (full fill), avg_price=잔고 평단으로
          ``apply_cumulative`` **만** 호출한다(§11.8 단일 권위). partial/모호 excess·
          다중 open buy 는 미적용(D+1 ccld 대기).
        """
        if not (self._fallback_enabled and self._trade_service is not None):
            return 0
        # §11.6 KIS paper 한정. base BrokerAdapter 에 is_paper 가 없으므로 안전
        # getattr(미정의/실전이면 비활성).
        if not getattr(self._broker, "is_paper", False):
            return 0

        # ccld 적용 **후** open 을 재조회해 advance 된 recorded 를 반영한다.
        open_orders = await self._tracker.get_open_orders(self._account_id)
        # 미복구(recorded==0) open **buy** 만 후보. ccld 가 부분이라도 반영한
        # 주문(recorded>0)은 §11.3-2 위반이라 제외. 이 후보가 없으면 잔고 콜 생략.
        unrecovered_buys = [
            o
            for o in open_orders
            if o.side == "buy" and o.recorded_filled_qty == 0 and o.ordered_qty > 0
        ]
        if not unrecovered_buys:
            # §11.2 rate budget: 미복구 open buy 가 없으면 get_positions 미호출.
            return 0

        # 후보가 있을 때만 잔고 1콜. (symbol 별로 유일 매칭만 적용하므로 한 번에
        # 전 symbol 잔고를 받아 in-memory 매칭한다.)
        broker_positions = await self._broker.get_positions()
        broker_qty_by_symbol: dict[str, float] = {}
        avg_price_by_symbol: dict[str, float] = {}
        for bp in broker_positions:
            symbol = str(bp.get("symbol", ""))
            if not symbol:
                continue
            qty = float(bp.get("quantity", 0.0) or 0.0)
            broker_qty_by_symbol[symbol] = broker_qty_by_symbol.get(symbol, 0.0) + qty
            # 잔고 평단(§11.4 avg_price 근거). 동일 symbol 다중 row 는 드무나,
            # 첫 양수 평단을 유지한다(잔고가 제공하는 유일 가격 정보).
            if symbol not in avg_price_by_symbol:
                avg_price_by_symbol[symbol] = float(bp.get("avg_price", 0.0) or 0.0)

        # §11.1 internal_account_qty = 계좌 전 bot 포지션 합(특정 bot 아님).
        internal_positions = await self._trade_service.get_all_positions(
            account_id=self._account_id
        )
        internal_qty_by_symbol: dict[str, float] = {}
        for p in internal_positions:
            if p.quantity > 0:
                internal_qty_by_symbol[p.symbol] = (
                    internal_qty_by_symbol.get(p.symbol, 0.0) + p.quantity
                )

        # symbol 별 미복구 open buy 그룹. §11.3-1 유일성 판정용.
        buys_by_symbol: dict[str, list[OrderTrackerRecord]] = {}
        for o in unrecovered_buys:
            buys_by_symbol.setdefault(o.symbol, []).append(o)

        applied = 0
        for symbol, orders in buys_by_symbol.items():
            # §11.3-1 다중 open buy(같은 symbol) → 미적용(외부/혼재 위험 회피).
            if len(orders) != 1:
                logger.debug(
                    "fallback 미적용(다중 open buy): account=%s symbol=%s count=%d",
                    self._account_id,
                    symbol,
                    len(orders),
                )
                continue
            order = orders[0]
            broker_qty = broker_qty_by_symbol.get(symbol, 0.0)
            internal_qty = internal_qty_by_symbol.get(symbol, 0.0)
            excess = broker_qty - internal_qty
            # §11.1 excess <= 0 → 대상 없음(no-op).
            if excess <= 0:
                continue
            # §11.3-3 full-fill 정확매칭: excess == ordered_qty 일 때만 적용.
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
            # §11.3·§11.8: full fill 절대 누적을 FillApplier **만** 호출해 수렴.
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
