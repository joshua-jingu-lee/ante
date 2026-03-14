"""KIS WebSocket 실시간 스트리밍 클라이언트.

KIS Open API WebSocket을 통해 실시간 시세(H0STCNT0)와
체결 통보(H0STCNI0)를 수신한다.
실행 시 websockets 패키지가 필요하다.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ante.eventbus.bus import EventBus

logger = logging.getLogger(__name__)

# KIS WebSocket 채널
CHANNEL_PRICE = "H0STCNT0"  # 실시간 시세
CHANNEL_EXECUTION = "H0STCNI0"  # 실시간 체결 통보

# 최대 구독 종목 수
MAX_SUBSCRIPTIONS = 40

# 재연결 설정
DEFAULT_RECONNECT_DELAY = 1.0
DEFAULT_MAX_RECONNECT_DELAY = 60.0
DEFAULT_PING_INTERVAL = 30.0


PriceCallback = Callable[[str, float], Coroutine[Any, Any, None]]
ExecutionCallback = Callable[[dict[str, Any]], Coroutine[Any, Any, None]]


class KISStreamClient:
    """KIS WebSocket 실시간 스트리밍 클라이언트.

    - 실시간 시세 수신 (H0STCNT0)
    - 실시간 체결 통보 수신 (H0STCNI0)
    - 자동 재연결
    - 최대 40종목 구독 제한
    """

    def __init__(
        self,
        websocket_url: str,
        app_key: str,
        app_secret: str,
        approval_key: str | None = None,
        eventbus: EventBus | None = None,
        ping_interval: float = DEFAULT_PING_INTERVAL,
    ) -> None:
        self._url = websocket_url
        self._app_key = app_key
        self._app_secret = app_secret
        self._approval_key = approval_key
        self._eventbus = eventbus
        self._ping_interval = ping_interval

        self._ws: Any = None
        self._running = False
        self._recv_task: asyncio.Task[None] | None = None
        self._subscribed_symbols: set[str] = set()

        # 콜백
        self._price_callbacks: list[PriceCallback] = []
        self._execution_callbacks: list[ExecutionCallback] = []

        # 재연결 상태
        self._reconnect_delay = DEFAULT_RECONNECT_DELAY

    @property
    def is_connected(self) -> bool:
        """WebSocket 연결 상태."""
        return self._ws is not None and self._running

    @property
    def subscribed_symbols(self) -> set[str]:
        """현재 구독 중인 종목."""
        return set(self._subscribed_symbols)

    def on_price(self, callback: PriceCallback) -> None:
        """시세 콜백 등록."""
        self._price_callbacks.append(callback)

    def on_execution(self, callback: ExecutionCallback) -> None:
        """체결 통보 콜백 등록."""
        self._execution_callbacks.append(callback)

    async def connect(self) -> None:
        """WebSocket 연결 및 수신 루프 시작."""
        if self._running:
            logger.warning("KIS WebSocket 이미 연결됨")
            return

        if not self._approval_key:
            self._approval_key = await self._get_approval_key()

        self._running = True
        self._recv_task = asyncio.create_task(
            self._connection_loop(), name="kis-stream"
        )
        logger.info("KIS WebSocket 연결 시작: %s", self._url)

    async def disconnect(self) -> None:
        """WebSocket 연결 해제."""
        self._running = False

        if self._recv_task and not self._recv_task.done():
            self._recv_task.cancel()
            try:
                await self._recv_task
            except asyncio.CancelledError:
                pass
            self._recv_task = None

        await self._close_ws()
        self._subscribed_symbols.clear()
        logger.info("KIS WebSocket 연결 해제")

    async def subscribe(self, symbol: str) -> bool:
        """종목 시세 구독."""
        if symbol in self._subscribed_symbols:
            return True

        if len(self._subscribed_symbols) >= MAX_SUBSCRIPTIONS:
            logger.warning(
                "최대 구독 한도 초과 (%d/%d): %s",
                len(self._subscribed_symbols),
                MAX_SUBSCRIPTIONS,
                symbol,
            )
            return False

        if self._ws:
            await self._send_subscribe(symbol, CHANNEL_PRICE, "1")
            self._subscribed_symbols.add(symbol)
            logger.info("종목 구독: %s (총 %d)", symbol, len(self._subscribed_symbols))
            return True

        # 연결 전이면 목록에만 추가 (연결 후 자동 구독)
        self._subscribed_symbols.add(symbol)
        return True

    async def unsubscribe(self, symbol: str) -> None:
        """종목 시세 구독 해제."""
        if symbol not in self._subscribed_symbols:
            return

        if self._ws:
            await self._send_subscribe(symbol, CHANNEL_PRICE, "2")

        self._subscribed_symbols.discard(symbol)
        logger.info("종목 구독 해제: %s", symbol)

    async def subscribe_execution(self) -> None:
        """체결 통보 구독."""
        if self._ws:
            msg = {
                "header": {
                    "approval_key": self._approval_key,
                    "custtype": "P",
                    "tr_type": "1",
                    "content-type": "utf-8",
                },
                "body": {
                    "input": {
                        "tr_id": CHANNEL_EXECUTION,
                        "tr_key": "",
                    }
                },
            }
            await self._ws.send(json.dumps(msg))
            logger.info("체결 통보 구독 시작")

    # ── 내부 메서드 ──────────────────────────────────

    async def _connection_loop(self) -> None:
        """WebSocket 연결 유지 루프 (자동 재연결)."""
        while self._running:
            try:
                await self._connect_and_recv()
            except asyncio.CancelledError:
                raise
            except Exception:
                if not self._running:
                    break
                logger.warning(
                    "KIS WebSocket 연결 끊김, %.1f초 후 재연결",
                    self._reconnect_delay,
                    exc_info=True,
                )
                await self._publish_disconnected("connection_lost")
                await asyncio.sleep(self._reconnect_delay)
                self._reconnect_delay = min(
                    self._reconnect_delay * 2, DEFAULT_MAX_RECONNECT_DELAY
                )

    async def _connect_and_recv(self) -> None:
        """WebSocket 연결 후 메시지 수신."""
        try:
            import websockets
        except ImportError as e:
            raise ImportError(
                "websockets 패키지가 필요합니다: pip install websockets"
            ) from e

        async with websockets.connect(
            self._url,
            ping_interval=self._ping_interval,
        ) as ws:
            self._ws = ws
            self._reconnect_delay = DEFAULT_RECONNECT_DELAY
            logger.info("KIS WebSocket 연결 완료")
            await self._publish_connected()

            # 기존 구독 복구
            await self._resubscribe_all()

            # 수신 루프
            async for message in ws:
                if not self._running:
                    break
                try:
                    await self._handle_message(message)
                except Exception:
                    logger.exception("WebSocket 메시지 처리 오류")

        self._ws = None

    async def _resubscribe_all(self) -> None:
        """재연결 후 기존 구독 복구."""
        symbols = list(self._subscribed_symbols)
        for symbol in symbols:
            await self._send_subscribe(symbol, CHANNEL_PRICE, "1")
            await asyncio.sleep(0.1)  # rate limit 방지

    async def _send_subscribe(self, symbol: str, tr_id: str, tr_type: str) -> None:
        """구독/해제 메시지 전송."""
        if not self._ws:
            return

        msg = {
            "header": {
                "approval_key": self._approval_key,
                "custtype": "P",
                "tr_type": tr_type,  # 1: 구독, 2: 해제
                "content-type": "utf-8",
            },
            "body": {
                "input": {
                    "tr_id": tr_id,
                    "tr_key": symbol,
                }
            },
        }
        await self._ws.send(json.dumps(msg))

    async def _handle_message(self, raw: str | bytes) -> None:
        """수신 메시지 분류 및 처리."""
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")

        # JSON 응답 (구독 확인 등)
        if raw.startswith("{"):
            data = json.loads(raw)
            header = data.get("header", {})
            tr_id = header.get("tr_id", "")
            if tr_id == CHANNEL_EXECUTION:
                await self._handle_execution_json(data)
            return

        # 파이프 구분 데이터 (실시간 시세)
        await self._handle_pipe_data(raw)

    async def _handle_pipe_data(self, raw: str) -> None:
        """파이프(|) 구분 실시간 시세 데이터 처리.

        KIS WebSocket 시세 데이터 형식:
        0|H0STCNT0|004|005930^...^현재가^...
        """
        parts = raw.split("|")
        if len(parts) < 4:
            return

        tr_id = parts[1]
        if tr_id == CHANNEL_PRICE:
            await self._handle_price_data(parts[3])
        elif tr_id == CHANNEL_EXECUTION:
            await self._handle_execution_data(parts[3])

    async def _handle_price_data(self, data_str: str) -> None:
        """실시간 시세 데이터 파싱 및 콜백 호출.

        H0STCNT0 응답 필드 (^로 구분):
        [0]: 종목코드, [1]: 시각, ..., [2]: 현재가
        """
        fields = data_str.split("^")
        if len(fields) < 3:
            return

        symbol = fields[0]
        try:
            price = float(fields[2])
        except (ValueError, IndexError):
            return

        for callback in self._price_callbacks:
            try:
                await callback(symbol, price)
            except Exception:
                logger.exception("시세 콜백 오류: %s", symbol)

    async def _handle_execution_data(self, data_str: str) -> None:
        """실시간 체결 통보 데이터 파싱."""
        fields = data_str.split("^")
        if len(fields) < 10:
            return

        execution = {
            "symbol": fields[0],
            "order_id": fields[1],
            "side": "buy" if fields[4] == "02" else "sell",
            "quantity": float(fields[5]) if fields[5] else 0.0,
            "price": float(fields[6]) if fields[6] else 0.0,
            "timestamp": datetime.now(UTC),
        }

        for callback in self._execution_callbacks:
            try:
                await callback(execution)
            except Exception:
                logger.exception("체결 통보 콜백 오류")

    async def _handle_execution_json(self, data: dict[str, Any]) -> None:
        """JSON 형식 체결 통보 처리."""
        body = data.get("body", {})
        output = body.get("output", {})
        if not output:
            return

        execution = {
            "symbol": output.get("pdno", ""),
            "order_id": output.get("odno", ""),
            "side": "buy" if output.get("sll_buy_dvsn_cd") == "02" else "sell",
            "quantity": float(output.get("ccld_qty", 0)),
            "price": float(output.get("ccld_pric", 0)),
            "timestamp": datetime.now(UTC),
        }

        for callback in self._execution_callbacks:
            try:
                await callback(execution)
            except Exception:
                logger.exception("체결 통보 콜백 오류")

    async def _get_approval_key(self) -> str:
        """WebSocket 접속키 발급."""
        try:
            import aiohttp
        except ImportError as e:
            raise ImportError("aiohttp 패키지가 필요합니다: pip install aiohttp") from e

        # WebSocket URL에서 REST URL 유추
        if "21000" in self._url:
            rest_url = "https://openapivts.koreainvestment.com:29443"
        else:
            rest_url = "https://openapi.koreainvestment.com:9443"

        url = f"{rest_url}/oauth2/Approval"
        data = {
            "grant_type": "client_credentials",
            "appkey": self._app_key,
            "secretkey": self._app_secret,
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=data) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise RuntimeError(f"WebSocket 접속키 발급 실패: {text}")
                result = await resp.json()
                return result["approval_key"]

    async def _close_ws(self) -> None:
        """WebSocket 연결 닫기."""
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

    async def _publish_connected(self) -> None:
        """연결 이벤트 발행."""
        if self._eventbus:
            from ante.eventbus.events import StreamConnectedEvent

            await self._eventbus.publish(
                StreamConnectedEvent(broker="kis", url=self._url)
            )

    async def _publish_disconnected(self, reason: str) -> None:
        """연결 해제 이벤트 발행."""
        if self._eventbus:
            from ante.eventbus.events import StreamDisconnectedEvent

            await self._eventbus.publish(
                StreamDisconnectedEvent(broker="kis", reason=reason)
            )
