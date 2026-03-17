"""DataSource Protocol 및 RateLimiter 기반 클래스."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


@runtime_checkable
class DataSource(Protocol):
    """데이터 소스 어댑터 프로토콜.

    모든 소스 구현체(data_go_kr, dart, pykrx 등)가 따르는 인터페이스.
    orchestrator는 이 프로토콜을 통해 소스를 다룬다.
    """

    async def fetch(self, date: str, **kwargs: Any) -> list[dict]:
        """지정된 날짜의 데이터를 수집한다.

        Args:
            date: 수집 대상 날짜 (YYYY-MM-DD 형식).
            **kwargs: 소스별 추가 파라미터.

        Returns:
            수집된 레코드 딕셔너리 목록.
        """
        ...


class RateLimiter:
    """공공 API 전용 Token Bucket 기반 Rate Limiter.

    data.go.kr (30 tps, 10,000건/일) 및 DART (20,000건/일)를 위한
    호출 속도 제어와 일일 한도 추적을 담당한다.
    """

    def __init__(self, tps_limit: float, daily_limit: int) -> None:
        """RateLimiter를 초기화한다.

        Args:
            tps_limit: 초당 허용 트랜잭션 수.
            daily_limit: 일일 최대 호출 수.
        """
        self._rate = tps_limit
        self._burst = int(tps_limit)
        self._tokens = float(self._burst)
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()
        self._daily_limit = daily_limit
        self._daily_count = 0

    async def acquire(self) -> None:
        """토큰 하나를 소비한다. 필요 시 대기한다."""
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill
            self._tokens = min(self._burst, self._tokens + elapsed * self._rate)
            self._last_refill = now

            if self._tokens < 1:
                wait_time = (1 - self._tokens) / self._rate
                await asyncio.sleep(wait_time)
                self._tokens = 0
            else:
                self._tokens -= 1

    def increment_daily(self) -> None:
        """일일 호출 카운터를 1 증가시킨다."""
        self._daily_count += 1

    def is_daily_limit_reached(self, threshold: float = 0.9) -> bool:
        """일일 한도의 threshold 비율에 도달했는지 확인한다.

        Args:
            threshold: 한도 비율 (기본값 0.9 = 90%).

        Returns:
            한도에 도달하면 True.
        """
        return self._daily_count >= int(self._daily_limit * threshold)

    def reset_daily(self) -> None:
        """일일 카운터를 초기화한다 (자정 후 호출)."""
        self._daily_count = 0

    @property
    def daily_count(self) -> int:
        """현재 일일 호출 수."""
        return self._daily_count
