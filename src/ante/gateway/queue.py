"""RequestQueue — 우선순위 기반 API 요청 큐."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any


class RequestPriority(IntEnum):
    """요청 우선순위. 낮은 숫자가 높은 우선순위."""

    ORDER = 0
    ORDER_CANCEL = 1
    BALANCE = 10
    PRICE = 20
    HISTORY = 30


@dataclass
class APIRequest:
    """API 요청 래퍼."""

    priority: RequestPriority
    method: str
    endpoint: str
    params: dict[str, Any] | None = None
    data: dict[str, Any] | None = None
    requester_id: str = ""
    future: asyncio.Future[Any] | None = field(default=None, repr=False)


class RequestQueue:
    """우선순위 기반 API 요청 큐."""

    def __init__(self) -> None:
        self._queue: asyncio.PriorityQueue[tuple[int, int, APIRequest]] = (
            asyncio.PriorityQueue()
        )
        self._counter = 0

    async def put(self, request: APIRequest) -> asyncio.Future[Any]:
        """요청을 큐에 추가. Future를 반환하여 응답 대기 가능."""
        loop = asyncio.get_running_loop()
        future: asyncio.Future[Any] = loop.create_future()
        request.future = future
        self._counter += 1
        await self._queue.put((request.priority, self._counter, request))
        return future

    async def get(self) -> APIRequest:
        """우선순위 순으로 요청 꺼내기."""
        _, _, request = await self._queue.get()
        return request

    def empty(self) -> bool:
        """큐가 비었는지 확인."""
        return self._queue.empty()

    @property
    def qsize(self) -> int:
        """큐 크기."""
        return self._queue.qsize()
