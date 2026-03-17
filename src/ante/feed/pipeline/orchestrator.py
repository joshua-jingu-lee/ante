"""ETL 오케스트레이션 모듈.

Extract → Transform → Load 흐름과 가드/한도 관리를 담당한다.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ante.feed.config import FeedConfig
    from ante.feed.models.result import CollectionResult

logger = logging.getLogger(__name__)


class FeedOrchestrator:
    """DataFeed ETL 오케스트레이터.

    날짜별 루프를 실행하며 Extract → Transform → Load 흐름을 조율한다.

    책임:
      - 방어 가드(blocked_days, blocked_hours) 적용
      - 일일 한도 확인 및 도달 시 체크포인트 저장 후 종료
      - 소스별 수집 실패 스킵 및 집계
      - CollectionResult 생성
    """

    def __init__(self, config: FeedConfig) -> None:
        """FeedOrchestrator를 초기화한다.

        Args:
            config: DataFeed 설정 객체.
        """
        ...

    def run_backfill(self) -> CollectionResult:
        """Backfill을 1회 실행한다.

        backfill_since 이후 데이터를 일일 한도 내에서 수집한다.
        완료 또는 한도 도달 시 체크포인트를 저장하고 CollectionResult를 반환한다.

        Returns:
            수집 결과.
        """
        ...

    def run_daily(self) -> CollectionResult:
        """Daily 수집을 1회 실행한다.

        전일 데이터를 수집하고 CollectionResult를 반환한다.

        Returns:
            수집 결과.
        """
        ...

    def _is_guarded(self) -> bool:
        """현재 시각이 가드 조건에 해당하는지 확인한다.

        blocked_days와 blocked_hours(pause_during_trading이 true일 때)를 확인한다.

        Returns:
            가드 조건에 해당하면 True.
        """
        ...

    def _etl_one_day(self, date: str) -> dict:
        """하루치 데이터를 ETL 처리한다.

        Args:
            date: 처리할 날짜 (YYYY-MM-DD).

        Returns:
            처리 결과 딕셔너리 (symbols_success, symbols_failed, rows_written 등).
        """
        ...
