"""Rate Limiter — 슬라이딩 윈도우 기반 API 호출 제한."""

from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass


@dataclass
class RateLimitConfig:
    """Rate limit 설정."""

    max_requests: int
    window_seconds: float


class RateLimiter:
    """슬라이딩 윈도우 기반 rate limiter.

    asyncio.Lock으로 복수 봇의 동시 요청을 직렬화한다.
    """

    def __init__(self, config: RateLimitConfig) -> None:
        self._config = config
        self._timestamps: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """요청 슬롯 확보. 제한 초과 시 대기."""
        async with self._lock:
            now = time.monotonic()
            while (
                self._timestamps
                and now - self._timestamps[0] > self._config.window_seconds
            ):
                self._timestamps.popleft()

            if len(self._timestamps) >= self._config.max_requests:
                wait = self._config.window_seconds - (now - self._timestamps[0])
                if wait > 0:
                    await asyncio.sleep(wait)

            self._timestamps.append(time.monotonic())

    @property
    def pending_count(self) -> int:
        """현재 윈도우 내 요청 수."""
        now = time.monotonic()
        while (
            self._timestamps and now - self._timestamps[0] > self._config.window_seconds
        ):
            self._timestamps.popleft()
        return len(self._timestamps)
