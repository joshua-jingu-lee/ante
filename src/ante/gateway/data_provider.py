"""LiveDataProvider — 라이브 모드에서 전략에 데이터를 제공."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ante.strategy.base import DataProvider

if TYPE_CHECKING:
    from ante.gateway.gateway import APIGateway


class LiveDataProvider(DataProvider):
    """라이브 모드 DataProvider. APIGateway 경유로 캐시 활용."""

    def __init__(self, gateway: APIGateway) -> None:
        self._gateway = gateway

    async def get_ohlcv(
        self,
        symbol: str,
        timeframe: str = "1d",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """OHLCV 데이터 조회. 추후 DataPipeline 연동 시 확장."""
        # Phase 4 (Data Pipeline)에서 Parquet 기반으로 교체 예정
        return []

    async def get_current_price(self, symbol: str) -> float:
        """현재가 조회 (APIGateway 캐시 활용)."""
        return await self._gateway.get_current_price(symbol)

    async def get_indicator(
        self,
        symbol: str,
        indicator: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """기술 지표 계산. 추후 구현."""
        return {}
