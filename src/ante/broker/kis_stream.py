"""KIS WebSocket 실시간 스트리밍 클라이언트."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable, Coroutine
from datetime import UTC
from typing import TYPE_CHECKING, Any, cast

from ante.broker.kis import DEFAULT_TIMEOUT_AUTH
from ante.core import clock

if TYPE_CHECKING:
    from ante.eventbus.bus import EventBus

logger = logging.getLogger(__name__)

CHANNEL_PRICE = "H0STCNT0"
CHANNEL_EXECUTION = "H0STCNI0"
TR_ID_PINGPONG = "PINGPONG"

PRICE_RECORD_FIELDS = 46
MAX_CONTROL_FRAME_PAYLOAD = 125

MAX_SUBSCRIPTIONS = 40

DEFAULT_RECONNECT_DELAY = 1.0
DEFAULT_MAX_RECONNECT_DELAY = 60.0
DEFAULT_PING_INTERVAL = 30.0


PriceCallback = Callable[[str, float], Coroutine[Any, Any, None]]
ExecutionCallback = Callable[[dict[str, Any]], Coroutine[Any, Any, None]]


def _is_pingpong(message: object) -> bool:
    """KIS PINGPONG JSON 메시지인지 본다. 어떤 입력에도 예외를 내지 않는다."""
    if isinstance(message, bytes):
        try:
            text = message.decode("utf-8")
        except UnicodeDecodeError:
            return False
    elif isinstance(message, str):
        text = message
    else:
        return False
    if not text.startswith("{"):
        return False
    try:
        data = json.loads(text)
    except (ValueError, RecursionError):
        return False
    if not isinstance(data, dict):
        return False
    header = data.get("header")
    return isinstance(header, dict) and header.get("tr_id") == TR_ID_PINGPONG


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
        *,
        account_id: str = "",
    ) -> None:
        self._url = websocket_url
        self._app_key = app_key
        self._app_secret = app_secret
        self._approval_key = approval_key
        self._eventbus = eventbus
        self._ping_interval = ping_interval
        self._account_id = account_id

        self._ws: Any = None
        self._running = False
        self._recv_task: asyncio.Task[None] | None = None
        self._subscribed_symbols: set[str] = set()

        self._price_callbacks: list[PriceCallback] = []
        self._execution_callbacks: list[ExecutionCallback] = []

        self._reconnect_delay = DEFAULT_RECONNECT_DELAY
        self._pong_too_long_warned = False
        self._record_count_warned = False

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

            await self._resubscribe_all()

            async for message in ws:
                if not self._running:
                    break
                if _is_pingpong(message):
                    await self._send_pong(ws, message)
                    continue
                try:
                    await self._handle_message(message)
                except Exception:
                    logger.exception("WebSocket 메시지 처리 오류")

        self._ws = None
        if self._running:
            raise ConnectionError("KIS WebSocket 서버가 연결을 닫았다")

    async def _send_pong(self, ws: Any, message: str | bytes) -> None:
        """받은 원문을 pong으로 되돌리고, 제어 프레임 한도를 넘으면 보내지 않는다."""
        payload = message if isinstance(message, bytes) else message.encode("utf-8")
        if len(payload) > MAX_CONTROL_FRAME_PAYLOAD:
            level = logging.DEBUG if self._pong_too_long_warned else logging.WARNING
            self._pong_too_long_warned = True
            logger.log(
                level,
                "KIS PINGPONG 원문이 %d바이트라 pong(최대 %d바이트)을 보내지 않는다",
                len(payload),
                MAX_CONTROL_FRAME_PAYLOAD,
            )
            return
        await ws.pong(message)

    async def _resubscribe_all(self) -> None:
        """재연결 후 기존 구독 복구."""
        symbols = list(self._subscribed_symbols)
        for symbol in symbols:
            await self._send_subscribe(symbol, CHANNEL_PRICE, "1")
            await asyncio.sleep(0.1)

    async def _send_subscribe(self, symbol: str, tr_id: str, tr_type: str) -> None:
        """구독/해제 메시지 전송."""
        if not self._ws:
            return

        msg = {
            "header": {
                "approval_key": self._approval_key,
                "custtype": "P",
                "tr_type": tr_type,
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

        if raw.startswith("{"):
            data = json.loads(raw)
            header = data.get("header", {})
            tr_id = header.get("tr_id", "")
            if tr_id == CHANNEL_EXECUTION:
                await self._handle_execution_json(data)
            return

        await self._handle_pipe_data(raw)

    async def _handle_pipe_data(self, raw: str) -> None:
        """파이프(|) 구분 실시간 데이터 처리(시세 H0STCNT0·체결 통보 H0STCNI0)."""
        parts = raw.split("|")
        if len(parts) < 4:
            return

        tr_id = parts[1]
        if tr_id == CHANNEL_PRICE:
            await self._handle_price_data(parts[3], parts[2])
        elif tr_id == CHANNEL_EXECUTION:
            await self._handle_execution_data(parts[3])

    async def _handle_price_data(self, data_str: str, count_str: str) -> None:
        """시세 프레임의 레코드마다 차례로 가격 콜백을 부른다."""
        for record in self._price_records(data_str.split("^"), count_str):
            if len(record) < 3:
                continue
            try:
                price = float(record[2])
            except ValueError:
                continue
            await self._dispatch_price(record[0], price)

    def _price_records(self, fields: list[str], count_str: str) -> list[list[str]]:
        """건수 × 46필드로 레코드를 나누고, 맞지 않으면 첫 레코드만 돌려준다."""
        try:
            count = int(count_str)
        except ValueError:
            count = 0
        if count > 0 and len(fields) == count * PRICE_RECORD_FIELDS:
            return [
                fields[start : start + PRICE_RECORD_FIELDS]
                for start in range(0, len(fields), PRICE_RECORD_FIELDS)
            ]
        level = logging.DEBUG if self._record_count_warned else logging.WARNING
        self._record_count_warned = True
        logger.log(
            level,
            "KIS 시세 프레임의 값 %d개가 건수 %r × %d와 맞지 않아 첫 레코드만 처리한다",
            len(fields),
            count_str,
            PRICE_RECORD_FIELDS,
        )
        return [fields]

    async def _dispatch_price(self, symbol: str, price: float) -> None:
        """가격 콜백을 차례로 부르고, 콜백의 오류는 남기고 넘어간다."""
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
            "timestamp": clock.now(UTC),
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
            "timestamp": clock.now(UTC),
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

        if "31000" in self._url:
            rest_url = "https://openapivts.koreainvestment.com:29443"
        else:
            rest_url = "https://openapi.koreainvestment.com:9443"

        url = f"{rest_url}/oauth2/Approval"
        data = {
            "grant_type": "client_credentials",
            "appkey": self._app_key,
            "secretkey": self._app_secret,
        }

        timeout = aiohttp.ClientTimeout(total=DEFAULT_TIMEOUT_AUTH)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=data) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise RuntimeError(f"WebSocket 접속키 발급 실패: {text}")
                result = await resp.json()
                return cast("str", result["approval_key"])

    async def _close_ws(self) -> None:
        """WebSocket 연결 닫기."""
        if self._ws:
            try:
                await self._ws.close()
            except Exception as e:
                logger.warning("WebSocket 종료 실패: %s", e)
            self._ws = None

    async def _publish_connected(self) -> None:
        """연결 이벤트 발행."""
        if self._eventbus:
            from ante.eventbus.events import StreamConnectedEvent

            await self._eventbus.publish(
                StreamConnectedEvent(
                    account_id=self._account_id,
                    broker="kis",
                    url=self._url,
                )
            )

    async def _publish_disconnected(self, reason: str) -> None:
        """연결 해제 이벤트 발행."""
        if self._eventbus:
            from ante.eventbus.events import StreamDisconnectedEvent

            await self._eventbus.publish(
                StreamDisconnectedEvent(
                    account_id=self._account_id,
                    broker="kis",
                    reason=reason,
                )
            )
