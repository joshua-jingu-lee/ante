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

if TYPE_CHECKING:
    from ante.bot.bot import Bot
    from ante.eventbus.bus import EventBus
    from ante.strategy.context import StrategyContext

logger = logging.getLogger(__name__)


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
    ) -> None:
        self._bot = bot
        self._eventbus = eventbus
        self._ctx = ctx
        self._input = input_stream or sys.stdin
        self._output = output_stream or sys.stdout
        self._running = False

    def _write(self, data: dict[str, Any]) -> None:
        """JSON Line 출력."""
        try:
            self._output.write(json.dumps(data, default=str) + "\n")
            self._output.flush()
        except (BrokenPipeError, OSError):
            self._running = False

    async def run(self) -> None:
        """채널 실행 루프. stdin에서 읽고 처리."""
        self._running = True
        self._subscribe_events()

        loop = asyncio.get_event_loop()
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await loop.connect_read_pipe(lambda: protocol, self._input)

        while self._running:
            try:
                line = await reader.readline()
                if not line:
                    break
                await self._handle_line(line.decode("utf-8").strip())
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("채널 메시지 처리 오류")

        self._running = False
        self._unsubscribe_events()

    async def _handle_line(self, line: str) -> None:
        """수신 메시지 파싱 및 라우팅."""
        if not line:
            return

        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            self._write({"type": "error", "message": "Invalid JSON"})
            return

        msg_type = msg.get("type", "")
        if msg_type == "signal":
            await self._handle_signal(msg)
        elif msg_type == "query":
            await self._handle_query(msg)
        elif msg_type == "ping":
            self._write({"type": "pong"})
        else:
            self._write({"type": "error", "message": f"Unknown type: {msg_type}"})

    async def _handle_signal(self, msg: dict[str, Any]) -> None:
        """외부 시그널 → ExternalSignalEvent 발행."""
        from ante.eventbus.events import ExternalSignalEvent

        signal_id = f"sig-{uuid4().hex[:12]}"

        event = ExternalSignalEvent(
            bot_id=self._bot.bot_id,
            signal_id=signal_id,
            symbol=msg.get("symbol", ""),
            action=msg.get("side", msg.get("action", "")),
            reason=msg.get("reason", "external_signal"),
            confidence=float(msg.get("confidence", 0.0)),
            metadata={
                k: v
                for k, v in msg.items()
                if k not in ("type", "symbol", "side", "action", "reason", "confidence")
            },
        )

        await self._eventbus.publish(event)
        self._write({"type": "ack", "signal_id": signal_id})

    async def _handle_query(self, msg: dict[str, Any]) -> None:
        """데이터 조회 요청 처리."""
        method = msg.get("method", "")
        params = msg.get("params", {})

        try:
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
                data = await self._ctx.get_ohlcv(
                    symbol=params.get("symbol", ""),
                    timeframe=params.get("timeframe", "1d"),
                    limit=params.get("limit", 100),
                )
            else:
                self._write({"type": "error", "message": f"Unknown method: {method}"})
                return

            self._write({"type": "result", "method": method, "data": data})
        except Exception as e:
            self._write({"type": "error", "message": str(e)})

    # ── EventBus 구독 (Ante → 외부 이벤트 전달) ──────

    def _subscribe_events(self) -> None:
        """체결/주문 상태 이벤트 구독."""
        from ante.eventbus.events import (
            OrderCancelledEvent,
            OrderFailedEvent,
            OrderFilledEvent,
            OrderRejectedEvent,
            OrderSubmittedEvent,
        )

        self._eventbus.subscribe(OrderFilledEvent, self._on_fill)
        for evt in (
            OrderSubmittedEvent,
            OrderRejectedEvent,
            OrderCancelledEvent,
            OrderFailedEvent,
        ):
            self._eventbus.subscribe(evt, self._on_order_update)

    def _unsubscribe_events(self) -> None:
        """이벤트 구독 해제."""
        from ante.eventbus.events import (
            OrderCancelledEvent,
            OrderFailedEvent,
            OrderFilledEvent,
            OrderRejectedEvent,
            OrderSubmittedEvent,
        )

        self._eventbus.unsubscribe(OrderFilledEvent, self._on_fill)
        for evt in (
            OrderSubmittedEvent,
            OrderRejectedEvent,
            OrderCancelledEvent,
            OrderFailedEvent,
        ):
            self._eventbus.unsubscribe(evt, self._on_order_update)

    async def _on_fill(self, event: object) -> None:
        """체결 이벤트 → 외부 전달.

        Note: EventBus 핸들러 — isawaitable 패턴을 위해 async def 유지.
        """
        from ante.eventbus.events import OrderFilledEvent

        if not isinstance(event, OrderFilledEvent):
            return
        if event.bot_id != self._bot.bot_id:
            return

        self._write(
            {
                "type": "fill",
                "order_id": event.order_id,
                "symbol": event.symbol,
                "side": event.side,
                "quantity": event.quantity,
                "price": event.price,
                "commission": event.commission,
                "timestamp": event.timestamp,
            }
        )

    async def _on_order_update(self, event: object) -> None:
        """주문 상태 변경 → 외부 전달.

        Note: EventBus 핸들러 — isawaitable 패턴을 위해 async def 유지.
        """
        bot_id = getattr(event, "bot_id", None)
        if bot_id != self._bot.bot_id:
            return

        from ante.eventbus.events import (
            OrderCancelledEvent,
            OrderFailedEvent,
            OrderRejectedEvent,
            OrderSubmittedEvent,
        )

        status = ""
        reason = ""
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

        if status:
            self._write(
                {
                    "type": "order_update",
                    "order_id": getattr(event, "order_id", ""),
                    "status": status,
                    "reason": reason,
                }
            )
