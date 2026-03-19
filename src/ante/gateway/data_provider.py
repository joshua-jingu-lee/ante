"""LiveDataProvider — 라이브 모드에서 전략에 데이터를 제공."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from ante.strategy.base import DataProvider

if TYPE_CHECKING:
    from ante.gateway.gateway import APIGateway

logger = logging.getLogger(__name__)


class LiveDataProvider(DataProvider):
    """라이브 모드 DataProvider. APIGateway 경유로 캐시 활용.

    Note: DataProvider 인터페이스 준수를 위해 async def를 유지한다.
    """

    def __init__(self, gateway: APIGateway) -> None:
        self._gateway = gateway

    async def get_ohlcv(
        self,
        symbol: str,
        timeframe: str = "1d",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """OHLCV 데이터 조회 (APIGateway 경유).

        APIGateway.get_ohlcv()를 통해 과거 봉 데이터를 가져온다.
        BrokerAdapter에 get_ohlcv가 구현되어 있지 않으면 빈 리스트를 반환한다.
        """
        return await self._gateway.get_ohlcv(symbol, timeframe=timeframe, limit=limit)

    async def get_current_price(self, symbol: str) -> float:
        """현재가 조회 (APIGateway 캐시 활용)."""
        return await self._gateway.get_current_price(symbol)

    async def get_indicator(
        self,
        symbol: str,
        indicator: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """기술 지표 계산.

        OHLCV 데이터를 조회한 뒤 IndicatorCalculator로 지표를 계산한다.
        pandas-ta는 정규 의존성이므로 항상 사용 가능하다.
        OHLCV 데이터가 없으면 빈 딕셔너리를 반환한다.
        """
        from ante.strategy.indicators import IndicatorCalculator, ohlcv_to_dataframe

        ohlcv_data = await self.get_ohlcv(symbol, limit=500)
        if not ohlcv_data:
            logger.warning(
                "OHLCV 데이터 없음 — 지표 계산 불가: %s %s", symbol, indicator
            )
            return {}

        arrays = ohlcv_to_dataframe(ohlcv_data)
        return IndicatorCalculator.compute(indicator, arrays, **(params or {}))
