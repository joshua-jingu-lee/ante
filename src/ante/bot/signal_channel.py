"""SignalChannel — JSON Lines 파이프 기반 양방향 시그널 채널.

외부 에이전트와 봇 사이의 stdin/stdout 기반 통신 채널.
HTTP API 대신 로컬 파이프를 사용하여 네트워크 공격면이 없다.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from typing import TYPE_CHECKING, Any, TextIO
from uuid import uuid4

from ante.eventbus.fill_dedup_guard import FillDedupGuard

if TYPE_CHECKING:
    from collections.abc import Callable

    from ante.bot.bot import Bot
    from ante.eventbus.bus import EventBus
    from ante.strategy.context import StrategyContext

logger = logging.getLogger(__name__)

SIGNAL_METADATA_MAX_KEYS = 64
SIGNAL_METADATA_MAX_BYTES = 16_384


class SignalChannel:
    """JSON Lines 파이프 기반 양방향 시그널 채널.

    - stdin으로 signal/query 수신
    - stdout으로 ack/result/fill/order_update 전송
    - 체결/주문 상태 이벤트를 자동 전달
    """

    def __init__(
        self,
        bot: Bot,
        eventbus: EventBus,
        ctx: StrategyContext,
        input_stream: TextIO | None = None,
        output_stream: TextIO | None = None,
        *,
        sink: Callable[[dict[str, Any]], None] | None = None,
        is_full: Callable[[], bool] | None = None,
        on_lagged: Callable[[], None] | None = None,
    ) -> None:
        self._bot = bot
        self._eventbus = eventbus
        self._ctx = ctx
        self._input = input_stream or sys.stdin
        self._output = output_stream or sys.stdout
        self._running = False
        self._fill_dedup_guard = FillDedupGuard()

        self._sink = sink
        self._is_full = is_full
        self._on_lagged = on_lagged
        self._closed = False
        self._accepting = True
        self._inflight: asyncio.Task[Any] | None = None

    def _write(self, data: dict[str, Any]) -> None:
        """JSON Line 출력 (legacy stdin/stdout 경로 — ``sink=None`` 일 때만)."""
        try:
            self._output.write(json.dumps(data, default=str) + "\n")
            self._output.flush()
        except (BrokenPipeError, OSError):
            self._running = False

    def _emit(self, data: dict[str, Any]) -> None:
        """출력 seam — sink 주입 시 newline-free dict enqueue, 아니면 legacy write.

        데몬 경로(``sink`` 주입)는 framing 을 writer_task 가 단독 소유하므로
        newline 을 붙이지 않는다(INV-OUT-1 1:1 framing). legacy 경로(``sink=None``)
        는 기존 ``_write``(``+'\n'``+flush)로 byte-identical 폴백한다.
        """
        if self._sink is not None:
            self._sink(data)
        else:
            self._write(data)

    def mark_closed(self) -> None:
        """채널을 닫힘으로 표시 (동기·idempotent). ``_unsubscribe_events`` 전 호출.

        ``_closed`` (stale-publish layer2) 와 ``_accepting`` (rotate admit-gate)
        를 set 한다. ``ChannelHandle.on_closed`` 로 바인딩되어 daemon-initiated
        close 가 await 없이 호출한다.
        """
        self._closed = True
        self._accepting = False

    def _schedule_lagged(self) -> None:
        """laggard 감지 → teardown 트리거 (idempotent, await 없음).

        out_queue full 로 프레임을 drop 해야 할 때 1회 호출한다. ``_closed`` 를
        flip 해 이후 ``_on_fill``/``_on_order_update`` 가 첫 줄 no-op 하게 하고,
        ``_on_lagged`` 콜백으로 데몬 supervisor 의 disconnect-laggard 를 깨운다.
        bus 핸들러 inline 에서 호출되므로 socket I/O await 은 하지 않는다
        (INV-OUT-2/6 — teardown 은 daemon ``call_soon`` 위임).
        """
        if self._closed:
            return
        self._closed = True
        self._accepting = False
        if self._on_lagged is not None:
            self._on_lagged()

    async def _handle_line(self, line: str) -> None:
        """stdin 라인 파싱 → ``_handle_message`` 위임.

        ``json.loads`` 만 담당하고(empty-guard·``JSONDecodeError``) routing 은
        ``_handle_message(dict)`` 가 한다. 데몬 경로(``_run_signal_stream``)는
        protocol.decode 로 이미 dict 를 얻으므로 ``_handle_message`` 를 직접
        호출한다(json.loads 중복 회피). CLI relay(#2338) 전환 후 in-process
        ``connect_read_pipe`` 루프(구 ``run()``)는 제거됐고, 본 메서드는 단위
        테스트의 라인-레벨 진입점으로만 남는다.
        """
        if not line:
            return

        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            self._emit({"type": "error", "message": "Invalid JSON"})
            return

        await self._handle_message(msg)

    async def _handle_message(self, msg: Any) -> None:
        """디코드된 프레임 라우팅 (#2337 데몬/legacy 공통 진입점).

        (1) 비-dict 프레임은 비치명 격리: ``{type:error,'Invalid JSON'}`` 후
        return(daemon read loop 비전파).
        (2) rotate admit-gate — ``_accepting=False`` 면 ``{type:error,
        'channel closing'}`` 후 return(at-most-one trailing). close 가
        ``_accepting`` 만 끄고 in-flight 는 shield 로 보호한다(F2).
        (3) per-frame ``try`` 래핑 routing(signal/query/ping/unknown). 핸들러
        예외는 ``{type:error,str(e)}`` 로 격리해 daemon read 루프로 전파하지
        않는다.
        """
        if not isinstance(msg, dict):
            self._emit({"type": "error", "message": "Invalid JSON"})
            return

        if not self._accepting:
            self._emit({"type": "error", "message": "channel closing"})
            return

        try:
            msg_type = msg.get("type", "")
            if msg_type == "signal":
                await self._handle_signal(msg)
            elif msg_type == "query":
                await self._handle_query(msg)
            elif msg_type == "ping":
                self._emit({"type": "pong"})
            else:
                self._emit({"type": "error", "message": f"Unknown type: {msg_type}"})
        except Exception as e:
            self._emit({"type": "error", "message": str(e)})

    async def _handle_signal(self, msg: dict[str, Any]) -> None:
        """외부 시그널 → ExternalSignalEvent 발행.

        F2(rotate shield, #2337): publish 를 ``_inflight`` task 로 분리하고
        read_task 는 ``asyncio.shield`` 로 await 한다. read_task 가 close
        오케스트레이터에 의해 cancel 돼도 in-flight publish(별도 task)는 shield
        로 보호되어 백그라운드 완료한다 — ``strategy.on_data`` 체인에 cancellation
        주입으로 인한 상태 손상을 막는다. metadata 는 publish 전 key-count/size
        로 bound 한다(§14 비치명 drop).
        """
        from ante.eventbus.events import ExternalSignalEvent

        signal_id = f"sig-{uuid4().hex[:12]}"

        metadata = {
            k: v
            for k, v in msg.items()
            if k not in ("type", "symbol", "side", "action", "reason", "confidence")
        }
        if len(metadata) > SIGNAL_METADATA_MAX_KEYS or (
            len(json.dumps(metadata, default=str).encode("utf-8"))
            > SIGNAL_METADATA_MAX_BYTES
        ):
            self._emit(
                {
                    "type": "error",
                    "message": "signal metadata too large",
                }
            )
            return

        event = ExternalSignalEvent(
            account_id=self._bot.config.account_id,
            bot_id=self._bot.bot_id,
            signal_id=signal_id,
            symbol=msg.get("symbol", ""),
            action=msg.get("side", msg.get("action", "")),
            reason=msg.get("reason", "external_signal"),
            confidence=float(msg.get("confidence", 0.0)),
            metadata=metadata,
        )

        self._inflight = asyncio.ensure_future(self._eventbus.publish(event))
        try:
            await asyncio.shield(self._inflight)
        except asyncio.CancelledError:
            raise
        finally:
            self._inflight = None
        self._emit({"type": "ack", "signal_id": signal_id})

    async def _handle_query(self, msg: dict[str, Any]) -> None:
        """데이터 조회 요청 처리."""
        method = msg.get("method", "")
        params = msg.get("params", {})

        try:
            data: Any = None
            if method == "positions":
                data = self._ctx.get_positions()
            elif method == "balance":
                data = self._ctx.get_balance()
            elif method == "open_orders":
                data = self._ctx.get_open_orders()
            elif method == "current_price":
                symbol = params.get("symbol", "")
                data = await self._ctx.get_current_price(symbol)
            elif method == "ohlcv":
                df = await self._ctx.get_ohlcv(
                    symbol=params.get("symbol", ""),
                    timeframe=params.get("timeframe", "1d"),
                    limit=params.get("limit", 100),
                )
                data = df.to_dicts()
            else:
                self._emit({"type": "error", "message": f"Unknown method: {method}"})
                return

            self._emit({"type": "result", "method": method, "data": data})
        except Exception as e:
            self._emit({"type": "error", "message": str(e)})

    def _subscribe_events(self) -> None:
        """체결/주문 상태 이벤트 구독."""
        from ante.eventbus.events import (
            OrderCancelFailedEvent,
            OrderCancelledEvent,
            OrderFailedEvent,
            OrderFilledEvent,
            OrderModifyExecutedEvent,
            OrderModifyRejectedEvent,
            OrderRejectedEvent,
            OrderSubmittedEvent,
            StopOrderExpiredEvent,
            StopOrderRegisteredEvent,
            StopOrderTriggeredEvent,
        )

        self._eventbus.subscribe(OrderFilledEvent, self._on_fill)
        for evt in (
            OrderSubmittedEvent,
            OrderRejectedEvent,
            OrderCancelledEvent,
            OrderFailedEvent,
            OrderCancelFailedEvent,
            OrderModifyExecutedEvent,
            OrderModifyRejectedEvent,
            StopOrderRegisteredEvent,
            StopOrderTriggeredEvent,
            StopOrderExpiredEvent,
        ):
            self._eventbus.subscribe(evt, self._on_order_update)

    def _unsubscribe_events(self) -> None:
        """이벤트 구독 해제."""
        from ante.eventbus.events import (
            OrderCancelFailedEvent,
            OrderCancelledEvent,
            OrderFailedEvent,
            OrderFilledEvent,
            OrderModifyExecutedEvent,
            OrderModifyRejectedEvent,
            OrderRejectedEvent,
            OrderSubmittedEvent,
            StopOrderExpiredEvent,
            StopOrderRegisteredEvent,
            StopOrderTriggeredEvent,
        )

        self._eventbus.unsubscribe(OrderFilledEvent, self._on_fill)
        for evt in (
            OrderSubmittedEvent,
            OrderRejectedEvent,
            OrderCancelledEvent,
            OrderFailedEvent,
            OrderCancelFailedEvent,
            OrderModifyExecutedEvent,
            OrderModifyRejectedEvent,
            StopOrderRegisteredEvent,
            StopOrderTriggeredEvent,
            StopOrderExpiredEvent,
        ):
            self._eventbus.unsubscribe(evt, self._on_order_update)

    async def _on_fill(self, event: object) -> None:
        """체결 이벤트 → 외부 전달.

        Note: EventBus 핸들러 — isawaitable 패턴을 위해 async def 유지.

        outbox at-least-once 재전달 시 같은 fill 의 중복 write 를 bounded
        dedup 한다. 비빈키 ``fill_dedup_key`` 가 이미 처리됐으면 write skip. 빈키
        (재전달 없는 단발 경로)는 가드 비대상으로 항상 write. payload 에
        ``fill_dedup_key`` 를 실어 외부 에이전트의 자체 dedup 도 지원한다.
        """
        from ante.eventbus.events import OrderFilledEvent

        if self._closed:
            return
        if not isinstance(event, OrderFilledEvent):
            return
        if event.bot_id != self._bot.bot_id:
            return

        key = event.fill_dedup_key
        payload = {
            "type": "fill",
            "order_id": event.order_id,
            "symbol": event.symbol,
            "side": event.side,
            "quantity": event.quantity,
            "price": event.price,
            "commission": event.commission,
            "timestamp": event.timestamp,
            "fill_dedup_key": key,
        }
        if key and key in self._fill_dedup_guard:
            return
        if self._is_full is not None and self._is_full():
            self._schedule_lagged()
            return
        self._emit(payload)
        if key:
            self._fill_dedup_guard.seen_or_add(key)

    async def _on_order_update(self, event: object) -> None:
        """주문 상태 변경 → 외부 전달.

        Note: EventBus 핸들러 — isawaitable 패턴을 위해 async def 유지.
        """
        if self._closed:
            return
        bot_id = getattr(event, "bot_id", None)
        if bot_id != self._bot.bot_id:
            return

        from ante.eventbus.events import (
            OrderCancelFailedEvent,
            OrderCancelledEvent,
            OrderFailedEvent,
            OrderModifyExecutedEvent,
            OrderModifyRejectedEvent,
            OrderRejectedEvent,
            OrderSubmittedEvent,
            StopOrderExpiredEvent,
            StopOrderRegisteredEvent,
            StopOrderTriggeredEvent,
        )

        status = ""
        reason = ""
        order_id = getattr(event, "order_id", "")
        if isinstance(event, OrderSubmittedEvent):
            status = "submitted"
        elif isinstance(event, OrderRejectedEvent):
            status = "rejected"
            reason = event.reason
        elif isinstance(event, OrderCancelledEvent):
            status = "cancelled"
            reason = event.reason
        elif isinstance(event, OrderFailedEvent):
            status = "failed"
            reason = event.error_message
        elif isinstance(event, OrderCancelFailedEvent):
            status = "cancel_failed"
            reason = event.error_message
        elif isinstance(event, OrderModifyExecutedEvent):
            status = "modified"
            reason = event.reason
        elif isinstance(event, OrderModifyRejectedEvent):
            status = "modify_rejected"
            reason = event.reason
        elif isinstance(event, StopOrderRegisteredEvent):
            status = "stop_registered"
            order_id = event.stop_order_id
        elif isinstance(event, StopOrderTriggeredEvent):
            status = "stop_triggered"
            order_id = event.stop_order_id
        elif isinstance(event, StopOrderExpiredEvent):
            status = "stop_expired"
            order_id = event.stop_order_id
            reason = event.reason

        if status:
            if self._is_full is not None and self._is_full():
                self._schedule_lagged()
                return
            self._emit(
                {
                    "type": "order_update",
                    "order_id": order_id,
                    "status": status,
                    "reason": reason,
                }
            )
