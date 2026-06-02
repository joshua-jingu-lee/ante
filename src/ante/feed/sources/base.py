"""DataSource Protocol 및 RateLimiter 기반 클래스."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from datetime import date

logger = logging.getLogger(__name__)

# KST(UTC+9) 캘린더 기준. cli_scheduler.KST / backfill_runner._today_kst()와
# 동일 기준이어야 daily 한도 리셋의 "하루" 경계가 repo 전반과 정합한다.
_KST = timezone(timedelta(hours=9))


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

    일일 카운터는 self-resetting이다. ``increment_daily`` /
    ``is_daily_limit_reached`` 호출 시점에 KST 캘린더 날짜가 직전 기록과
    다르면 자동으로 0으로 리셋한다. 따라서 feed start 같은 상주 프로세스가
    자정을 넘겨도 별도 스케줄러 없이 daily_count가 새 날짜에 맞게 초기화된다
    (#2019).

    동시성: ``increment_daily`` / ``is_daily_limit_reached`` /
    ``reset_daily`` 는 sync 메서드로 유지한다(호출부 dart.py / data_go_kr.py가
    sync로 호출). DataFeed 소스는 단일 asyncio event loop에서 동작하고 이
    메서드들은 내부에 await 지점이 없으므로 코루틴 간 원자적이다. 별도 lock을
    두지 않는다. ``acquire()`` 의 ``asyncio.Lock`` 은 토큰 버킷 갱신만
    보호하며 이 sync 메서드들과는 별개의 임계영역이다.
    """

    def __init__(
        self,
        tps_limit: float,
        daily_limit: int,
        now_date: Callable[[], date] | None = None,
    ) -> None:
        """RateLimiter를 초기화한다.

        Args:
            tps_limit: 초당 허용 트랜잭션 수.
            daily_limit: 일일 최대 호출 수.
            now_date: 현재 날짜(KST 캘린더)를 반환하는 콜러블. 테스트에서
                날짜 경계를 결정적으로 주입하기 위한 훅이며, 미지정 시
                KST(UTC+9) 기준 현재 날짜를 사용한다. 기존 호출부의
                ``RateLimiter(tps, daily)`` 시그니처와 호환된다.
        """
        self._rate = tps_limit
        self._burst = int(tps_limit)
        self._tokens = float(self._burst)
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()
        self._daily_limit = daily_limit
        self._daily_count = 0
        self._now_date: Callable[[], date] = now_date or (
            lambda: datetime.now(tz=_KST).date()
        )
        # 일일 카운터가 마지막으로 귀속된 날짜. None이면 아직 미관측 상태로,
        # 첫 increment_daily / is_daily_limit_reached 시 현재 날짜로 baseline.
        self._daily_date: date | None = None

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
                # sleep 동안 흐른 시간을 다음 acquire의 elapsed로 재크레딧하면
                # 설정 TPS의 약 2배가 허용된다(#2048). _last_refill을 sleep
                # 종료 시점(now + wait_time)으로 명시 전진시켜 차단한다.
                self._last_refill = now + wait_time
            else:
                self._tokens -= 1

    def _roll_daily_date(self) -> None:
        """현재 날짜가 직전 기록과 다르면 일일 카운터를 리셋한다.

        single event loop 가정 하에 await 없이 동작하므로 코루틴 간 atomic.
        """
        d = self._now_date()
        if self._daily_date != d:
            self._daily_count = 0
            self._daily_date = d

    def increment_daily(self) -> None:
        """일일 호출 카운터를 1 증가시킨다.

        호출 시점 KST 날짜가 직전 기록과 다르면 먼저 0으로 리셋한 뒤 증가한다.
        """
        self._roll_daily_date()
        self._daily_count += 1

    def is_daily_limit_reached(self, threshold: float = 0.9) -> bool:
        """일일 한도의 threshold 비율에 도달했는지 확인한다.

        호출 시점 KST 날짜가 직전 기록과 다르면 먼저 0으로 리셋한다(증가 없이
        자정을 넘긴 check도 새 날짜의 0을 반영).

        Args:
            threshold: 한도 비율 (기본값 0.9 = 90%).

        Returns:
            한도에 도달하면 True.
        """
        self._roll_daily_date()
        return self._daily_count >= int(self._daily_limit * threshold)

    def reset_daily(self) -> None:
        """일일 카운터를 초기화한다 (명시적 리셋).

        카운터를 0으로 되돌리는 동시에 ``_daily_date`` 를 현재 KST 날짜로
        설정해, 명시 리셋 시점을 새 날짜 baseline으로 고정한다.
        """
        self._daily_count = 0
        self._daily_date = self._now_date()

    @property
    def daily_count(self) -> int:
        """현재 일일 호출 수."""
        return self._daily_count
