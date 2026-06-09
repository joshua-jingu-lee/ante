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

# Refs #2334 §14 (#2337): ExternalSignal metadata bound (비치명 drop). 외부
# 에이전트가 거대 metadata 를 실어 publish 파이프라인을 부풀리는 경로를 막는다.
# key-count/size 둘 중 하나라도 초과하면 ``{type:error}`` 후 publish 하지 않고
# drop 한다(known-limitation — 정밀 byte 산정이 아닌 보수적 상한).
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
        # 기존 위치/이름 인자(bot/eventbus/ctx/input_stream/output_stream)는
        # 불변이다(4 테스트 + cli/commands/signal.py 의존). 신규 데몬 데이터플레인
        # seam 은 keyword-only-with-default 로만 추가한다(#2337 백워드 호환).
        self._bot = bot
        self._eventbus = eventbus
        self._ctx = ctx
        self._input = input_stream or sys.stdin
        self._output = output_stream or sys.stdout
        self._running = False
        # #1957: 체결 이벤트 bounded 멱등 가드. outbox at-least-once 재전달 시
        # 같은 fill 의 중복 JSON write 를 억제한다(best-effort — 재기동/maxlen
        # 초과는 known-limitation). 외부 에이전트는 payload 의 fill_dedup_key 로
        # 자체 dedup 도 가능하다.
        self._fill_dedup_guard = FillDedupGuard()

        # #2337 데몬 데이터플레인 seam:
        # - ``_sink``: newline 없는 dict enqueue 콜백(데몬 writer_task 가 framing).
        #   ``None`` 이면 legacy ``_write``(stdin/stdout, ``+'\n'``) 로 폴백한다.
        # - ``_is_full``: out_queue full 여부(disconnect-laggard 게이트).
        # - ``_on_lagged``: laggard 감지 시 teardown 트리거(call_soon 위임).
        self._sink = sink
        self._is_full = is_full
        self._on_lagged = on_lagged
        # 데몬-위임 종료/회전 가드. ``_closed`` 는 stale-publish layer2(첫 줄
        # no-op), ``_accepting`` 은 rotate admit-gate(``_handle_message``).
        self._closed = False
        self._accepting = True
        # F2: read_task 가 실행 중인 in-flight publish task. close 오케스트레이터가
        # grace 동안 await 후 read_task 만 cancel 하기 위해 추적한다.
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
        """legacy stdin 라인 파싱 → ``_handle_message`` 위임.

        ``json.loads`` 만 담당하고(empty-guard·``JSONDecodeError``) routing 은
        ``_handle_message(dict)`` 가 한다. ``run()``(legacy connect_read_pipe)
        은 본 메서드 경유라 투명하다. 데몬 경로(``_run_signal_stream``)는
        protocol.decode 로 이미 dict 를 얻으므로 ``_handle_message`` 를 직접
        호출한다(json.loads 중복 회피).
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
        except Exception as e:  # noqa: BLE001 — daemon read loop 비전파 격리.
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
        # metadata bound(§14): key-count/size 초과 시 비치명 drop(publish 안 함).
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
            # shield: read_task 가 cancel 돼도 inflight publish 는 계속 진행한다.
            await asyncio.shield(self._inflight)
        except asyncio.CancelledError:
            # read_task cancel 이 여기로 전파돼도 inflight(별도 task)는 shield 로
            # 보호되어 백그라운드 완료한다 — at-most-one trailing 보장.
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

    # ── EventBus 구독 (Ante → 외부 이벤트 전달) ──────

    def _subscribe_events(self) -> None:
        """체결/주문 상태 이벤트 구독."""
        from ante.eventbus.events import (
            OrderCancelFailedEvent,
            OrderCancelledEvent,
            OrderFailedEvent,
            OrderFilledEvent,
            OrderModifyRejectedEvent,
            OrderRejectedEvent,
            OrderSubmittedEvent,
            StopOrderExpiredEvent,
            StopOrderRegisteredEvent,
            StopOrderTriggeredEvent,
        )

        self._eventbus.subscribe(OrderFilledEvent, self._on_fill)
        # ``OrderModifyRejectedEvent`` — 외부 채널 구독자에게도 정정 거부/
        # 미구현 통보를 ``order_update`` 메시지로 전달한다.
        # stop 주문 등록·발동·만료도 외부 채널에 동일한 ``{type:
        # "order_update", ...}`` shape 로 전달한다 (외부 소비자 파싱 분기
        # 추가 부담 회피).
        for evt in (
            OrderSubmittedEvent,
            OrderRejectedEvent,
            OrderCancelledEvent,
            OrderFailedEvent,
            OrderCancelFailedEvent,
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
            OrderModifyRejectedEvent,
            OrderRejectedEvent,
            OrderSubmittedEvent,
            StopOrderExpiredEvent,
            StopOrderRegisteredEvent,
            StopOrderTriggeredEvent,
        )

        self._eventbus.unsubscribe(OrderFilledEvent, self._on_fill)
        # 등록과 동일하게 ``OrderModifyRejectedEvent`` 와 stop 이벤트 3종
        # 해지.
        for evt in (
            OrderSubmittedEvent,
            OrderRejectedEvent,
            OrderCancelledEvent,
            OrderFailedEvent,
            OrderCancelFailedEvent,
            OrderModifyRejectedEvent,
            StopOrderRegisteredEvent,
            StopOrderTriggeredEvent,
            StopOrderExpiredEvent,
        ):
            self._eventbus.unsubscribe(evt, self._on_order_update)

    async def _on_fill(self, event: object) -> None:
        """체결 이벤트 → 외부 전달.

        Note: EventBus 핸들러 — isawaitable 패턴을 위해 async def 유지.

        #1957: outbox at-least-once 재전달 시 같은 fill 의 중복 write 를 bounded
        dedup 한다. 비빈키 ``fill_dedup_key`` 가 이미 처리됐으면 write skip. 빈키
        (재전달 없는 단발 경로)는 가드 비대상으로 항상 write. payload 에
        ``fill_dedup_key`` 를 실어 외부 에이전트의 자체 dedup 도 지원한다.
        """
        from ante.eventbus.events import OrderFilledEvent

        # #2337 단일 await-free 임계구역. dedup-mark-after-enqueue(INV-OUT-4):
        # read-only ``__contains__`` 게이트 → ``_emit`` → ``seen_or_add`` 커밋.
        # full-drop 시 미마킹(재전달 보존). bus 핸들러 inline 이라 socket await
        # 0(INV-OUT-2).
        # ① stale-publish layer2 — close 가 await 전 ``_closed`` set(첫 줄 no-op).
        if self._closed:
            return
        # ② isinstance + bot_id 필터.
        if not isinstance(event, OrderFilledEvent):
            return
        if event.bot_id != self._bot.bot_id:
            return

        # ③ payload 구성(byte-identical).
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
        # ④ 비빈키 read-only dedup 게이트(non-committing). 이미 처리된 키면 skip.
        if key and key in self._fill_dedup_guard:
            return
        # ⑤ disconnect-laggard — full 이면 schedule_lagged + return(seen 미마킹,
        #    재전달 보존). legacy(sink=None, is_full=None)는 skip → 항상 성공.
        if self._is_full is not None and self._is_full():
            self._schedule_lagged()
            return
        # ⑥ enqueue.
        self._emit(payload)
        # ⑦ enqueue 성공 **후** dedup 커밋(full-drop 시 미마킹).
        if key:
            self._fill_dedup_guard.seen_or_add(key)

    async def _on_order_update(self, event: object) -> None:
        """주문 상태 변경 → 외부 전달.

        Note: EventBus 핸들러 — isawaitable 패턴을 위해 async def 유지.
        """
        # #2337 ① stale-publish layer2(첫 줄 no-op) → ② bot_id 필터.
        if self._closed:
            return
        bot_id = getattr(event, "bot_id", None)
        if bot_id != self._bot.bot_id:
            return

        from ante.eventbus.events import (
            OrderCancelFailedEvent,
            OrderCancelledEvent,
            OrderFailedEvent,
            OrderModifyRejectedEvent,
            OrderRejectedEvent,
            OrderSubmittedEvent,
            StopOrderExpiredEvent,
            StopOrderRegisteredEvent,
            StopOrderTriggeredEvent,
        )

        status = ""
        reason = ""
        # 외부 dict shape 호환을 위해 ``order_id`` 는 일반 주문이면 그대로
        # ``event.order_id``, stop 이벤트면 ``stop_order_id`` 를 사용한다.
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
        elif isinstance(event, OrderModifyRejectedEvent):
            # 정정 거부/미구현 통보를 status 로 잠그고, 외부 dict shape 는
            # 기존 ``{type:"order_update", ...}`` 패턴을 그대로 유지한다.
            # ``type`` 을 ``"modify_rejected"`` 같은 새 형태로 바꾸면 외부
            # 소비자(stdin/stdout 기반 에이전트) 가 파싱 분기를 추가해야
            # 하므로 의도적으로 잠갔다.
            status = "modify_rejected"
            reason = event.reason
        elif isinstance(event, StopOrderRegisteredEvent):
            # stop 등록 통보. 외부 채널에는 식별 핵심인 stop_order_id 만
            # ``order_id`` 키로 전달하고, dict shape 는 기존 ``{type:
            # "order_update", order_id, status, reason}`` 그대로 유지.
            status = "stop_registered"
            order_id = event.stop_order_id
        elif isinstance(event, StopOrderTriggeredEvent):
            # stop 트리거 통보.
            status = "stop_triggered"
            order_id = event.stop_order_id
        elif isinstance(event, StopOrderExpiredEvent):
            # stop 만료 통보. ``reason`` 은 ``"session_ended"`` |
            # ``"manager_stopped"``.
            status = "stop_expired"
            order_id = event.stop_order_id
            reason = event.reason

        if status:
            # disconnect-laggard — full 이면 schedule_lagged + return(dedup 없음).
            # legacy(is_full=None)는 skip → 항상 _emit.
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
