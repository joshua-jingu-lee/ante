"""날짜 범위 생성 모듈 (backfill vs daily 모드)."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import date

logger = logging.getLogger(__name__)


def generate_backfill_dates(
    start: str,
    end: str | None = None,
    last_checkpoint: str | None = None,
) -> Iterator[str]:
    """Backfill 모드에서 수집할 날짜 범위를 생성한다.

    체크포인트가 있으면 그 다음 날부터 시작한다.
    영업일 필터링은 하지 않으며 orchestrator에서 처리한다.

    Args:
        start: 시작 날짜 (YYYY-MM-DD, config의 backfill_since).
        end: 종료 날짜 (YYYY-MM-DD). None이면 오늘.
        last_checkpoint: 마지막 체크포인트 날짜 (YYYY-MM-DD). 있으면 그 다음 날부터.

    Yields:
        날짜 문자열 (YYYY-MM-DD), 오름차순.
    """
    ...


def generate_daily_date(reference: date | None = None) -> str:
    """Daily 모드에서 수집할 날짜 (전일)를 반환한다.

    Args:
        reference: 기준 날짜. None이면 오늘.

    Returns:
        전일 날짜 문자열 (YYYY-MM-DD).
    """
    ...


def is_business_day(target: str) -> bool:
    """해당 날짜가 영업일(월~금)인지 확인한다.

    공휴일은 고려하지 않는다 (한국 공휴일 데이터 없음).

    Args:
        target: 확인할 날짜 (YYYY-MM-DD).

    Returns:
        영업일이면 True.
    """
    ...
