"""DataSource Protocol 및 RateLimiter 기반 클래스."""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Callable
from datetime import timedelta, timezone
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable
from urllib.parse import quote

from ante.core import clock

if TYPE_CHECKING:
    from datetime import date

logger = logging.getLogger(__name__)

_KST = timezone(timedelta(hours=9))

_KEY_PARAM_PATTERN = re.compile(r"(?i)(crtfc_key|servicekey)(=|%3D)[^&'\"\s]*")


def redact_source_text(text: str, api_key: str) -> str:
    """문자열에서 API 키와 키를 싣는 쿼리 파라미터의 값을 가린다.

    키 값(원문과 URL 인코딩 꼴)을 직접 바꾸고, 키를 싣는 쿼리 파라미터
    (``crtfc_key``·``serviceKey``)의 값도 가린다. 키가 빈 문자열이면 직접
    치환은 건너뛴다. 키가 없는 문자열은 그대로 돌려준다.
    """
    if api_key:
        forms = {api_key, quote(api_key, safe=""), quote(api_key, safe="/")}
        forms.add(quote(api_key, safe="/?:@"))
        for form in sorted(forms, key=len, reverse=True):
            text = text.replace(form, "***")
    return _KEY_PARAM_PATTERN.sub(r"\1\2***", text)


def describe_source_error(exc: BaseException, api_key: str) -> str:
    """예외를 종류 이름과 API 키를 가린 메시지로 바꾼다.

    가림은 ``redact_source_text`` 를 따른다. 상태 코드·주소의 경로·나머지
    쿼리는 남는다. 메시지가 비면 종류 이름만 돌려준다.
    """
    message = redact_source_text(str(exc), api_key)
    name = type(exc).__name__
    return f"{name}: {message}" if message else name


@runtime_checkable
class DataSource(Protocol):
    """데이터 소스 어댑터 프로토콜.

    모든 소스 구현체(data_go_kr, dart, pykrx 등)가 따르는 인터페이스.
    orchestrator는 이 프로토콜을 통해 소스를 다룬다.
    """

    async def fetch(self, date: str, **kwargs: Any) -> list[dict[str, Any]]:
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
        self._last_refill = clock.monotonic()
        self._lock = asyncio.Lock()
        self._daily_limit = daily_limit
        self._daily_count = 0
        self._now_date: Callable[[], date] = now_date or (
            lambda: clock.now(_KST).date()
        )
        self._daily_date: date | None = None

    async def acquire(self) -> None:
        """토큰 하나를 소비한다. 필요 시 대기한다."""
        async with self._lock:
            now = clock.monotonic()
            elapsed = now - self._last_refill
            self._tokens = min(self._burst, self._tokens + elapsed * self._rate)
            self._last_refill = now

            if self._tokens < 1:
                wait_time = (1 - self._tokens) / self._rate
                await asyncio.sleep(wait_time)
                self._tokens = 0
                self._last_refill = now + wait_time
            else:
                self._tokens -= 1

    def _roll_daily_date(self) -> None:
        """현재 날짜가 직전 기록과 다르면 일일 카운터를 리셋한다."""
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
