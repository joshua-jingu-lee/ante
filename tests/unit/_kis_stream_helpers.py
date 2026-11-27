"""KISStreamClient 수신 루프 테스트용 가짜 웹소켓과 46필드 시세 레코드 (#3106).

실제 접속 없이 ``websockets`` 모듈을 바꿔 끼운다. 가짜 ``pong``은 websockets 16의
``Connection.pong``처럼 str을 UTF-8로 인코딩하고, 125바이트를 넘는 제어 프레임에서
``ProtocolError("control frame too long")``를 낸다(``Frame.check``).
"""

from __future__ import annotations

import asyncio
import sys
import types
from typing import Any

from websockets.exceptions import ProtocolError

from ante.broker.kis_stream import CHANNEL_PRICE

PRICE_FIELDS = 46


def price_record(symbol: str, price: object) -> list[str]:
    """H0STCNT0 레코드 하나(46필드). 0번은 종목, 2번은 현재가."""
    fields = [""] * PRICE_FIELDS
    fields[0] = symbol
    fields[1] = "100000"
    fields[2] = str(price)
    return fields


def price_frame(*records: list[str], count: str | None = None) -> str:
    """``0|H0STCNT0|건수|값`` 프레임. 건수를 주지 않으면 레코드 수로 쓴다."""
    values: list[str] = []
    for record in records:
        values.extend(record)
    return f"0|{CHANNEL_PRICE}|{count or f'{len(records):03d}'}|" + "^".join(values)


class FakeSocket:
    """대본대로 메시지를 내는 가짜 웹소켓 연결."""

    def __init__(
        self,
        script: list[str | bytes] | None = None,
        *,
        block_at_end: bool = True,
        pong_error: BaseException | None = None,
    ) -> None:
        self.script = list(script or [])
        self.block_at_end = block_at_end
        self.pong_error = pong_error
        self.sent: list[str] = []
        self.pongs: list[Any] = []
        self.drained = asyncio.Event()
        self._closed = asyncio.Event()

    async def pong(self, data: Any = b"") -> None:
        if isinstance(data, (bytes, bytearray, memoryview)):
            payload = bytes(data)
        elif isinstance(data, str):
            payload = data.encode()
        else:
            raise TypeError("data must be str or bytes-like")
        if self.pong_error is not None:
            raise self.pong_error
        if len(payload) > 125:
            raise ProtocolError("control frame too long")
        self.pongs.append(data)

    async def send(self, message: str) -> None:
        self.sent.append(message)

    async def close(self) -> None:
        self._closed.set()

    def __aiter__(self) -> Any:
        return self._messages()

    async def _messages(self) -> Any:
        for message in self.script:
            yield message
        self.drained.set()
        if self.block_at_end:
            await self._closed.wait()


class FakeWebsockets:
    """``websockets`` 모듈 대역. ``connect``가 준비한 소켓을 차례로 돌려준다.

    준비한 소켓이 떨어지면 곧바로 정상 종료하는 빈 소켓을 돌려준다.
    """

    def __init__(self, sockets: list[FakeSocket], log: list[str]) -> None:
        self.sockets = list(sockets)
        self.log = log
        self.connect_calls = 0
        self.on_connect: Any = None

    def connect(self, url: str, **kwargs: Any) -> Any:
        self.connect_calls += 1
        self.log.append("connect")
        if self.on_connect is not None:
            self.on_connect(self.connect_calls)
        sock = self.sockets.pop(0) if self.sockets else FakeSocket(block_at_end=False)
        return _FakeConnect(sock)

    def install(self, monkeypatch: Any) -> None:
        module = types.ModuleType("websockets")
        module.connect = self.connect  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "websockets", module)


class _FakeConnect:
    def __init__(self, sock: FakeSocket) -> None:
        self._sock = sock

    async def __aenter__(self) -> FakeSocket:
        return self._sock

    async def __aexit__(self, *exc: object) -> None:
        return None
