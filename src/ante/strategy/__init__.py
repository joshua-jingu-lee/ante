"""Strategy — 전략 정의·검증·등록·로딩."""

from typing import Any

from ante.strategy.base import (
    DataProvider,
    OrderAction,
    OrderView,
    PortfolioView,
    Signal,
    Strategy,
    StrategyMeta,
    TradeHistoryView,
)
from ante.strategy.context import StrategyContext
from ante.strategy.exceptions import (
    IncompatibleExchangeError,
    StrategyError,
    StrategyFileAccessError,
    StrategyLoadError,
    StrategyValidationError,
)
from ante.strategy.loader import StrategyLoader
from ante.strategy.registry import StrategyRecord, StrategyRegistry, StrategyStatus
from ante.strategy.snapshot import StrategySnapshot
from ante.strategy.validator import (
    VALID_EXCHANGES,
    StrategyValidator,
    ValidationResult,
    validate_exchange,
)

__all__ = [
    "DataProvider",
    "IncompatibleExchangeError",
    "IndicatorCalculator",
    "OrderAction",
    "OrderView",
    "PortfolioView",
    "Signal",
    "Strategy",
    "StrategyContext",
    "StrategyError",
    "StrategyFileAccessError",
    "StrategyLoadError",
    "StrategyLoader",
    "StrategyMeta",
    "StrategyRecord",
    "StrategyRegistry",
    "StrategySnapshot",
    "StrategyStatus",
    "StrategyValidationError",
    "TradeHistoryView",
    "StrategyValidator",
    "VALID_EXCHANGES",
    "ValidationResult",
    "validate_exchange",
]


def __getattr__(name: str) -> Any:
    """PEP 562 lazy attribute access — heavy indicators 모듈을 지연 적재.

    ``from ante.strategy import IndicatorCalculator`` 형태의 기존 import
    패턴은 그대로 동작하지만, 호출 시점에야 ``ante.strategy.indicators``를
    적재하므로 plain ``import ante.strategy``는 light한 상태를 유지한다.
    """
    if name == "IndicatorCalculator":
        from ante.strategy.indicators import IndicatorCalculator

        return IndicatorCalculator
    raise AttributeError(f"module 'ante.strategy' has no attribute {name!r}")
