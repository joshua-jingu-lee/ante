"""Strategy — 전략 정의·검증·등록·로딩.

본 패키지의 plain ``import ante.strategy``는 의도적으로 light하다.
``ante.strategy.indicators``는 ``pandas`` / ``pandas-ta`` / ``numpy`` /
``numba`` 같은 heavy 분석 의존성을 끌어들이므로, CLI dispatch path가
이를 eager-import하지 않도록 PEP 562 ``__getattr__``로 **lazy 노출**한다
(#1463).

계약:
    - ``import ante.strategy`` 는 light: heavy 의존성을 끌지 않는다.
    - ``from ante.strategy import IndicatorCalculator`` 는 ``__getattr__``
      을 호출해 indicators 모듈을 lazy load 한다 (호환성 유지).
    - ``from ante.strategy import *`` 와 ``importlib.reload(...)`` 는
      본 lazy 보장 범위 밖이다. 와일드카드 import는 ``__all__``을 통해
      ``IndicatorCalculator``를 끌어가므로 heavy load가 발생한다.

회귀 차단:
    - ``tests/unit/test_cli_dependency_isolation.py``가 fresh subprocess
      helper로 ``import ante.strategy`` 시 heavy 모듈 적재 여부를 검사한다.
"""

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


def __getattr__(name: str):
    """PEP 562 lazy attribute access — heavy indicators 모듈을 지연 적재.

    ``from ante.strategy import IndicatorCalculator`` 형태의 기존 import
    패턴은 그대로 동작하지만, 호출 시점에야 ``ante.strategy.indicators``를
    적재하므로 plain ``import ante.strategy``는 light한 상태를 유지한다.
    """
    if name == "IndicatorCalculator":
        from ante.strategy.indicators import IndicatorCalculator

        return IndicatorCalculator
    raise AttributeError(f"module 'ante.strategy' has no attribute {name!r}")
