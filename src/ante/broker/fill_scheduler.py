"""FillReconcileScheduler — 계좌별 event-gated 체결 백스톱 폴러 (#1946).

REST ``get_order_history`` 를 백스톱으로 폴해 추적 주문의 체결을 ``FillApplier`` 로
멱등 반영한다. 실시간 체결 통보 스트림 유무·paper/live 무관하게 정합성을 보증한다.

rate budget 보호:
- **event-gated**: open 주문이 없고 ``_fallback_verify`` 도 비어있으면 폴하지
  않는다(0콜, idle). open 또는 verify 가 있을 때만 ``get_order_history`` 를
  **사이클당 1콜**(#2318 Finding ②: fallback 이 주문을 filled 로 올려 open 이
  비어도, verify set 이 남아 있으면 ccld 를 계속 폴해 §11.4 late-ccld alert 를
  도달 가능하게 한다 — verify set 은 ccld 1회 관측 또는 영업일 경계에 정리되는
  bounded in-memory 보조 상태다).
- cadence **≥60s**. 주문 제출·가격 fallback 과 동일한 broker rate-limit 큐를
  공유하므로(``_rate_limit_wait``), 보수적 cadence + 1콜/사이클로 제출 starvation 을
  방지한다.

position-derived bounded fallback (#2314·#2316 §11):
- KIS 모의 ``inquire-daily-ccld``(``get_order_history``)는 일별 결제기준 원장이라
  당일 체결을 지연 반영할 수 있다. 레거시 tr_id(``*8001R`` 세대)는 모의 당일 체결을
  0건으로 반환했으나, 신 tr_id ``VTTC0081R``(#2349)은 당일 체결을 반환함이 #2317
  라이브로 확인됐다(백스톱 지연/유실에 무관히 fallback 은 멱등 백업으로 유지).
  반면 잔고(``get_positions``)는 체결기준 즉시반영이다. 백스톱이 당일 0건을 줄 때
  잔고 증분(``broker_qty - internal_account_qty``)에서 self-submitted 체결을
  **보수적 역도출**해
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
from ante.broker.exceptions import APIError, CircuitOpenError

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

# steady-state 폴 루프(_loop) 연속 실패 cooldown 상한 배수 (#2350).
# n번째 연속 실패 직후 sleep = poll_interval × min(2^n, LOOP_BACKOFF_MULTIPLIER_CAP)
# (첫 실패 ×2, 이후 ×4, ×8 cap). 기본 poll 60s 기준 상한 480s — CB
# recovery_timeout(60s)·reconciler 주기(1800s)보다 짧아 복구 관측을 놓치지 않으면서
# late-ccld 타임아웃 연타로 차단기 OPEN 을 60s 주기로 갱신·연장하지 않게 한다. fill
# 반영 지연 상한도 480s 로 bounded. catch_up_once 의 bounded backoff 와는 비간섭.
LOOP_BACKOFF_MULTIPLIER_CAP = 8

# steady-state cooldown 집계 대상 broker-transient 예외(#2350). 이 부류만 연속 실패
# 카운터에 누적해 cooldown 을 연장한다. 그 외 예외(내부 버그류)는 backoff 로 은폐하지
# 않고 카운터를 0 으로 리셋해 기존대로 즉시 다음 주기 + 경고 로그를 유지한다(현행
# 동작 보존, #2350 Codex R1 P2).
_LOOP_BACKOFF_EXCEPTIONS: tuple[type[Exception], ...] = (
    TimeoutError,
    CircuitOpenError,
    APIError,
    ConnectionError,
    OSError,
)


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
class _FallbackVerifyEntry:
    """fallback 이 advance 한 주문의 사후 ccld 검증 항목 (#2318 Finding ②).

    fallback 이 주문을 ``filled``(terminal)로 올리면 다음 사이클의
    ``get_open_orders`` 가 비어 ``_poll_and_apply`` 가 early-return → ccld 미폴 →
    §11.4 late-ccld alert 가 production 에서 도달 불가(dead code)가 된다. 이를
    막기 위해 fallback 적용 주문을 in-memory verify set 에 등록하고, 폴 게이트를
    ``open 또는 verify 가 있으면`` 으로 확장해 그 주문의 ccld 를 계속 폴한다.

    이 항목은 **in-memory 보조 상태일 뿐**이며 OrderTracker/positions/trades/
    outbox 를 직접 수정하지 않는다(§11.8 단일 권위 보존). 폴 window 의 from_date
    가 ``submitted_date`` 까지 거슬러 덮도록 보장하고, ccld 절대 누적이 fallback
    이 advance 한 ``recorded`` 미만이면 alert 1회 후 제거, 동일/높으면 조용히
    제거한다. 무한 누적 방지를 위해 영업일 경계(D+1)에 정리한다(§11.5).

    Attributes:
        recorded: fallback 이 ``apply_cumulative`` 로 advance 한 절대 누적(= full
            fill ``ordered_qty``). ccld 가 이보다 낮은 양수 누적을 주면 잠재
            over-attribution.
        submitted_date: fallback 적용 주문의 영업일(``YYYYMMDD``). 폴 window
            from_date 가 이 날짜까지 거슬러 덮어 ccld 가 매칭 가능하게 한다.
    """

    recorded: float
    submitted_date: str


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
        # #2318 Finding ②: fallback 이 filled(terminal)로 올린 주문의 사후 ccld
        # 검증 set(broker_order_id → 검증 항목). fallback 이 open 을 비우면
        # _poll_and_apply 폴 게이트가 막혀 §11.4 alert 가 도달 불가(dead code)가
        # 되므로, 이 set 이 비어있지 않으면 ccld 를 계속 폴한다. in-memory 보조
        # 상태일 뿐(§11.8 OrderTracker/positions/trades/outbox 직접 수정 금지).
        self._fallback_verify: dict[str, _FallbackVerifyEntry] = {}

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
        """steady-state 주기 폴 루프 (+ #2350 연속 실패 cooldown).

        정상 사이클은 ``poll_interval`` 고정 주기로 ``_poll_and_apply`` 를 반복한다.
        broker-transient 실패(``_LOOP_BACKOFF_EXCEPTIONS``: TimeoutError/
        CircuitOpenError/APIError/Connection/OSError)가 **연속**되면 sleep 을
        ``poll_interval × min(2^n, LOOP_BACKOFF_MULTIPLIER_CAP)`` 로 늘려(첫 실패 ×2,
        이후 ×4, ×8 cap) late-ccld 타임아웃 연타로 차단기 OPEN 을 60s 주기로
        갱신·연장하지 않게 한다(#2350). 정상 완료 시 카운터를 0 으로 리셋해
        ``poll_interval`` 고정 주기로 복귀한다. broker-transient 가 아닌 예외(내부
        버그류)는 backoff 로 은폐하지 않는다 — 연속 실패 카운터를 0 으로 리셋해(선행
        transient 로 올라간 backoff 가 있으면 함께 해제) 즉시 다음 주기 + 경고 로그를
        유지한다(#2350 Codex R1 P2). 이 cooldown 은 ``_loop`` steady-state 한정이며
        ``catch_up_once`` 의 bounded backoff 와 비간섭이다.
        """
        consecutive_transient_failures = 0
        while self._running:
            # 연속 broker-transient 실패가 있으면 sleep 을 늘려 OPEN 갱신/타임아웃
            # 연타를 흡수한다. 0 이면 기존 poll_interval 고정 주기(성공 경로 불변).
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
                # broker-transient 폴 실패(CB open/rate/network/타임아웃)를 삼키고
                # 다음 사이클에 멱등 재시도하되, 연속 실패 카운터를 올려 cooldown 을
                # 연장한다(#2350). (startup 카치업과 달리 barrier 영향 없음.)
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
                # broker-transient 가 아닌 예외(내부 버그류)는 cooldown 으로 은폐하지
                # 않는다. 선행 transient 실패로 backoff 가 올라가 있었다면 카운터를 0
                # 으로 리셋해 다음 사이클이 base poll_interval 로 복귀하게 한다(내부
                # 결함을 이전 backoff 로 계속 잠재우지 않음, #2350 Codex R1 P2).
                # 이후 경고 로그를 남기고 기존대로 즉시 다음 주기에 멱등 재시도한다.
                consecutive_transient_failures = 0
                logger.warning(
                    "FillReconcileScheduler 폴 오류 (account=%s) — 다음 사이클 재시도",
                    self._account_id,
                    exc_info=True,
                )
            else:
                # 정상 완료 — cooldown 카운터 리셋, poll_interval 고정 주기 복귀.
                consecutive_transient_failures = 0

    async def _poll_and_apply(self) -> int:
        """**poll-first**: open(만료 전) → history 1콜 → fallback → 그 후 EOD 만료.

        순서가 곧 정합성 invariant 다 (#1946 메타리뷰, #2316 §11.2).

        1. ``get_open_orders`` 로 추적 open(non-terminal)을 **만료 전에** 읽는다.
           ``from_date`` 는 그 open 들의 가장 이른 ``submitted_date`` 로 잡아, 전일
           open 이 있으면 폴 window 가 그 영업일까지 거슬러 올라간다(I8). **(신규
           #2318 Finding ②)** fallback 이 filled 로 올려 open 이 비어도
           ``_fallback_verify`` 가 비어있지 않으면 ccld 를 계속 폴해 §11.4 late-ccld
           alert 를 도달 가능하게 한다. 이 경우 ``from_date`` 는 verify 항목의
           가장 이른 ``submitted_date`` 까지 거슬러 덮어 ccld 가 그 주문을 관측할
           수 있게 한다. open·verify 가 **둘 다 없으면** 폴하지 않는다(rate budget,
           §11.2).
        2. open 이 있으면 ``get_order_history`` 1콜 → 관측 체결을
           ``FillApplier.apply_cumulative`` 로 멱등 적용한다(복구). 다운타임 중
           체결분(전일 open 포함)이 여기서 ``filled``/``partially_filled`` 로 전이
           되어 다음 단계의 만료 대상에서 **자동 제외**된다(I1·I2). history loop 는
           각 항목에서 ``_fallback_verify`` 에 등록된 주문이면 §11.4 late-ccld 검증
           (ccld 절대 누적 < fallback recorded → alert)을 수행하고, 동일/높거나
           alert 후엔 그 항목을 verify 에서 제거한다(bounded).
        3. **(신규 #2314)** ②(ccld) 적용 후에도 남은 미복구 open buy 가 있으면
           ``get_positions`` 잔고 역도출 fallback 을 적용한다(KIS paper 한정 기본
           활성, §11). ccld 가 체결을 줘 capacity 가 advance 된 경우엔 ``excess``
           가 0 으로 수렴해 fallback 이 본질적으로 no-op 이며, 애초에 미복구 open
           buy 가 없으면 ``get_positions`` 자체를 **호출하지 않아 rate budget 을
           보호**한다(§11.2). fallback 이 적용한 주문은 ``_fallback_verify`` 에
           등록돼 이후 사이클의 ccld 검증 대상이 된다.
        4. **fallback 후에** ``expire_stale`` 로 EOD 경과 + 체결 미관측
           (genuinely-dead)인 ``open`` 만 ``expired`` 로 전이한다. 부분 체결
           (``partially_filled``)은 만료 대상이 아니다(체결 진행 중). 만료를
           fallback **앞**에 두면 모의 당일 미반영 체결을 가진 open 이 복구 전에
           expired 되어 fallback 이 대상을 잃는다(§11.5). 같은 영업일 경계에서
           ``_fallback_verify`` 의 D-1 이전(``submitted_date < today``) 항목을 정리해
           무한 누적을 막는다(§11.5).

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
        # #2318 Finding ②: fallback 이 filled 로 올려 open 이 비어도 verify set 이
        # 비어있지 않으면 ccld 를 계속 폴해 §11.4 late-ccld alert 를 reachable 하게
        # 한다. open·verify 가 **둘 다 없으면** 폴하지 않는다(§11.2 rate budget).
        if not open_orders and not self._fallback_verify:
            # event-gated: 추적 open·verify 가 모두 없으면 폴하지 않는다 (0콜).
            # 만료시킬 open 도 없으므로 expire_stale 도 생략한다.
            return 0

        # from_date 는 open 의 가장 이른 submitted_date 와 verify 항목의 가장 이른
        # submitted_date 중 더 이른 쪽으로 잡아(I8), verify-only 사이클에서도 ccld
        # 가 fallback 적용 주문을 관측할 수 있게 한다(#2318 Finding ②).
        candidate_dates = [o.submitted_date for o in open_orders]
        candidate_dates.extend(e.submitted_date for e in self._fallback_verify.values())
        from_date = min(candidate_dates)
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
            # #2316 §11.4 / #2318 Finding ②: fallback 이 full fill 로 올린 주문이
            # _fallback_verify 에 등록돼 있으면, ccld 절대 누적이 fallback 이
            # advance 한 recorded 보다 **낮은** 양수면 over-attribution alert 를
            # 발행하고(비가역·CAS no-op) verify 에서 제거한다. 동일/높으면(정상)
            # 조용히 제거한다. 이 검증을 거쳐야 §11.4 alert 가 실제 poll 경로에서
            # 도달 가능하다. #2318 Codex 리뷰: KIS odno(broker_order_id)는 영업일
            # 재사용 가능하므로(§4.1 유일키 = (account, odno, submitted_date)),
            # ccld 행을 verify 항목과 매칭할 때 **(odno, item_date)** 쌍으로 비교해
            # 폴 window 에 섞여 든 다른 날짜 재사용 odno 가 verify 항목을 잘못
            # 매칭/alert/pop 하지 않게 한다(정확매칭, §11.3).
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

        # 3) **(신규 #2314·#2316 §11)** ccld 가 채우지 못한 미복구 open buy 가
        #    남아 있을 때만 잔고-역도출 fallback 을 적용한다. open 을 ccld 적용
        #    **후** 재조회해 advance 된 recorded_filled_qty 를 반영한다.
        applied += await self._apply_position_fallback()

        # 4) fallback 이 끝난 **뒤에** EOD 경과 + 체결 미관측(genuinely-dead) open
        #    만 만료한다. 위 폴/fallback 으로 체결된 주문은 이미 filled/
        #    partially_filled 로 전이돼 expire_stale 의 만료 대상(genuinely-dead
        #    open)에서 자동 제외된다(I2·§11.5).
        await self._tracker.expire_stale(self._account_id, before_date=today)
        # #2318 Finding ②: verify set 의 D-1 이전 항목을 영업일 경계에서 정리해
        # 무한 누적을 막는다(§11.5 EOD 정리). 당일 항목은 그날의 late-ccld 검증을
        # 위해 유지한다.
        self._expire_stale_fallback_verify(before_date=today)
        return applied

    def _expire_stale_fallback_verify(self, *, before_date: str) -> None:
        """``_fallback_verify`` 의 D-1 이전 항목을 정리한다 (#2318 Finding ②, §11.5).

        영업일 경계(``submitted_date < before_date``, 즉 D+1 이후)에 도달한 verify
        항목은 그 영업일의 ccld 가 이미 반영됐을 시한이 지났으므로(D+1 결제기준
        원장) 정리해 in-memory set 의 무한 누적을 막는다. 당일(``== before_date``)
        항목은 그날의 late-ccld 검증을 위해 유지한다. ``expire_stale`` 과 동일한
        ``submitted_date < before_date`` 경계를 써 정리 시점을 EOD 만료와 정렬한다.
        """
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
        """fallback 적용 주문의 ccld 절대 누적을 검증해 over-attribution 을 surface.

        (#2316 §11.4, #2318 Finding ② — normative, 실제 poll 경로에서 reachable)

        ``_fallback_verify`` 에 등록된 주문(fallback 이 full fill 로 advance)에 대해
        ``_poll_and_apply`` 의 history loop 가 이 메서드를 호출한다. ccld 가 그 주문에
        **더 낮은 절대 누적**(fallback 이 advance 한 ``recorded`` 미만의 양수)을 주면
        CAS 단조성으로 ``record_fill`` 이 no-op 이라 정정은 불가하나(비가역),
        ``PositionMismatchEvent``/``NotificationEvent`` 로 경보해 협소 외부 흡수
        (§11.7) 가능성을 침묵 흡수하지 않고 surface 한다. 동일/높은 ccld(정상
        advance/멱등)면 조용히 처리한다. 어느 경우든 검증 후 그 항목을 verify 에서
        제거한다(bounded — ccld 가 한 번 관측되면 검증 완료).

        #2318 Codex 리뷰(date-scope): KIS ``odno``(broker_order_id)는 **영업일
        재사용** 가능하므로(spec §4.1 유일키 = ``(account, odno, submitted_date)``,
        odno 단독은 전역 유일 키가 아님), 폴 window(``from_date`` 가 verify 항목의
        ``submitted_date`` 까지 거슬러 덮음)에 **다른 날짜의 같은 odno** ccld 행이
        섞여 들 수 있다. 그 행을 verify 항목과 매칭하면 late-ccld alert 를 오발화하고
        verify 항목을 pop 해, 실제 fallback-advanced 주문이 영영 검증되지 않는다.
        이를 막기 위해 ccld 행의 ``item_date`` 가 verify 항목의 ``submitted_date`` 와
        **일치할 때만** 검증/alert/pop 한다. 날짜가 다르면 그 verify 항목에 대해
        무시한다(다른 날짜 재사용 odno — OrderTracker 의
        ``(account, odno, submitted_date)`` 조회 계약과 정합. ``find_by_broker_order``
        가 date scope 를 인자로 안 받으므로, 매칭을 date 까지 좁히는 책임을 이 verify
        비교 지점에 둔다).

        eventbus 미주입이면 alert 는 best-effort 로 생략하나, verify 항목 제거(누적
        방지)는 그대로 수행한다(멱등성·정확성 영향 없음).
        """
        entry = self._fallback_verify.get(broker_order_id)
        if entry is None:
            return
        # #2318 Codex 리뷰: date-scope 정확매칭. ccld 행의 영업일(item_date)이 verify
        # 항목의 submitted_date 와 다르면 다른 날짜 재사용 odno 이므로 이 항목에 대해
        # 무시한다(검증/alert/pop 안 함). 같은 날짜 ccld 만 그 항목을 검증·확정한다.
        if entry.submitted_date != item_date:
            return
        recorded = entry.recorded
        # ccld 가 0 이거나 fallback recorded 이상이면 정상 경로(멱등 advance/no-op).
        # recorded 보다 **낮은 양수** 누적일 때만 over-attribution 의심.
        if 0 < observed_cumulative < recorded:
            await self._emit_late_ccld_alert(
                broker_order_id=broker_order_id,
                recorded=recorded,
                observed_cumulative=observed_cumulative,
                submitted_date=entry.submitted_date,
            )
        # ccld 가 한 번 관측됐으므로 검증 완료 — verify 에서 제거(bounded).
        self._fallback_verify.pop(broker_order_id, None)

    async def _emit_late_ccld_alert(
        self,
        *,
        broker_order_id: str,
        recorded: float,
        observed_cumulative: float,
        submitted_date: str,
    ) -> None:
        """late-ccld over-attribution 경보 1회 발행 (#2316 §11.4, normative).

        비가역(CAS no-op)이라 정정은 못 하나 운영 관측 가능하게
        ``PositionMismatchEvent``/``NotificationEvent`` 를 발행한다. bot_id/symbol/
        order_id 는 ``find_by_broker_order``(terminal 포함)로 복원한다 — fallback 이
        full fill 로 ``filled``(terminal)된 주문이라 non-terminal scope 로는 누락된다.
        eventbus 미주입이면 best-effort 로 생략한다.
        """
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
        - 그 ``(account, symbol, side="buy")`` 의 추적 **non-terminal**(open/
          partially_filled) buy 주문이 **정확히 하나**(#2318 Finding ①: 유일성은
          미복구 후보만이 아닌 **모든 non-terminal open buy** 총수로 판정한다.
          partially_filled open buy(recorded>0)가 공존하면 그 symbol 의 open buy
          총수가 2 이상이라 §11.3-1 위반 → 미적용).
        - 그 유일 주문이 ``recorded_filled_qty == 0``.
        - 잔고 excess(``broker_qty - internal_account_qty``)가 그 주문
          ``ordered_qty`` 와 **정확히 일치**(``excess == ordered_qty``).
        → ``observed_cumulative = ordered_qty`` (full fill), avg_price=잔고 평단으로
          ``apply_cumulative`` **만** 호출한다(§11.8 단일 권위). partial/모호 excess·
          다중 open buy 는 미적용(D+1 ccld 대기). 적용 주문은 ``_fallback_verify``
          에 등록해 이후 ccld 검증(§11.4)을 받게 한다(#2318 Finding ②).
        """
        if not (self._fallback_enabled and self._trade_service is not None):
            return 0
        # §11.6 KIS paper 한정. base BrokerAdapter 에 is_paper 가 없으므로 안전
        # getattr(미정의/실전이면 비활성).
        if not getattr(self._broker, "is_paper", False):
            return 0

        # ccld 적용 **후** open 을 재조회해 advance 된 recorded 를 반영한다.
        open_orders = await self._tracker.get_open_orders(self._account_id)
        # #2318 Finding ①: 유일성 판정은 그 symbol 의 **모든 non-terminal(open/
        # partially_filled) buy** 총수로 한다. recorded>0 인 partially_filled open
        # buy 가 unrecovered(recorded==0) buy 와 공존하면, 미복구만 세서 len==1 로
        # 통과시키면 §11.3-1("그 symbol 의 추적 open buy 가 **정확히 하나**")를
        # 위반한다. 모든 non-terminal open buy 를 symbol 별로 센다.
        open_buy_count_by_symbol: dict[str, int] = {}
        for o in open_orders:
            if o.side == "buy":
                open_buy_count_by_symbol[o.symbol] = (
                    open_buy_count_by_symbol.get(o.symbol, 0) + 1
                )
        # 미복구(recorded==0) open **buy** 만 적용 후보. ccld 가 부분이라도 반영한
        # 주문(recorded>0)은 §11.3-2 위반이라 후보에서 제외. 이 후보가 없으면 잔고
        # 콜 생략(§11.2 rate budget).
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

        # symbol 별 미복구 open buy 그룹(적용 후보). 유일성 판정은 아래에서 그
        # symbol 의 **모든 non-terminal open buy 총수**(open_buy_count_by_symbol)로
        # 한다 — 미복구 후보 그룹 크기가 아니다(#2318 Finding ①).
        buys_by_symbol: dict[str, list[OrderTrackerRecord]] = {}
        for o in unrecovered_buys:
            buys_by_symbol.setdefault(o.symbol, []).append(o)

        applied = 0
        for symbol, orders in buys_by_symbol.items():
            # §11.3-1 유일성: 그 symbol 의 **모든 non-terminal open buy 총수**가
            # 정확히 1 이어야 한다(#2318 Finding ①). partially_filled open buy
            # (recorded>0)가 공존하면 총수≥2 라 미적용 — 미복구 후보만 세서 통과
            # 시키는 결함을 닫는다. (미복구 후보 자체가 같은 symbol 에 둘 이상이면
            # 총수도 자동 ≥2 라 이 게이트가 함께 막는다.)
            if open_buy_count_by_symbol.get(symbol, 0) != 1:
                logger.debug(
                    "fallback 미적용(다중 non-terminal open buy): account=%s "
                    "symbol=%s open_buy_count=%d",
                    self._account_id,
                    symbol,
                    open_buy_count_by_symbol.get(symbol, 0),
                )
                continue
            # 유일 open buy 총수==1 이고 미복구 후보가 정확히 그 주문일 때만 진입.
            # (unrecovered_buys 에서 온 orders 는 recorded==0 임이 보장된다.)
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
                # #2318 Finding ②: fallback 이 full fill 로 advance 했으므로
                # verify set 에 등록한다. 이후 사이클의 ccld 가 더 낮은 절대 누적을
                # 주면 §11.4 over-attribution alert 가 실제 poll 경로에서 발행된다
                # (fallback 이 주문을 filled 로 올려 open 이 비어도 verify 가
                # 폴 게이트를 열어 ccld 가 도달한다).
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
