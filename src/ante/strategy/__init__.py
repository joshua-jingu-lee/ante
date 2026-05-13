"""Strategy — 전략 정의·검증·등록·로딩.

이 패키지의 ``__init__``은 import 비용이 큰 의존성(`pandas`, `pandas_ta`,
`numpy`, `numba` 등)을 **eager-load 하지 않는다**. 이전에는 모든 서브모듈을
top-level에서 ``from .x import Y`` 형태로 재노출하여 ``import ante.strategy``,
또는 단순히 ``import ante.strategy.exceptions``만 해도 패키지 초기화 과정에서
``indicators`` 경로를 통해 ``pandas_ta``/``numba`` 같은 heavy dependency가
연쇄적으로 import되었다. 결과적으로 CLI cold-path(예: ``ante strategy list
--status <invalid>``의 invalid 입력 거부 경로)에서도 수백 개 모듈이 불필요하게
로드되었고, optional 의존성이 깨진 환경에서는 입력 검증 단계 이전에 traceback이
발생했다(이슈 #1416, #1463).

본 모듈은 PEP 562 ``__getattr__``/``__dir__``을 사용해 퍼블릭 심볼을 lazy하게
노출한다. 직접 ``from ante.strategy.<submodule> import X`` 형태로 접근하는
caller(예: ``ante.cli.commands.strategy``, ``ante.web.routes.strategies``)는
필요한 서브모듈만 import하므로 영향을 받지 않는다. ``from ante.strategy import
StrategyRegistry`` 같은 기존 퍼블릭 import 경로도 그대로 동작한다.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

# 퍼블릭 심볼 → 정의된 서브모듈 매핑. heavy 의존성을 가진 심볼도 포함되지만,
# 실제 import는 사용자가 해당 속성에 접근하는 시점에 수행한다.
_LAZY_ATTRS: dict[str, str] = {
    # base — light: dataclass / ABC / StrategyMeta 만 사용 (polars는 TYPE_CHECKING)
    "DataProvider": "ante.strategy.base",
    "OrderAction": "ante.strategy.base",
    "OrderView": "ante.strategy.base",
    "PortfolioView": "ante.strategy.base",
    "Signal": "ante.strategy.base",
    "Strategy": "ante.strategy.base",
    "StrategyMeta": "ante.strategy.base",
    "TradeHistoryView": "ante.strategy.base",
    # context — light (base/exceptions만 사용)
    "StrategyContext": "ante.strategy.context",
    # exceptions — light
    "IncompatibleExchangeError": "ante.strategy.exceptions",
    "StrategyError": "ante.strategy.exceptions",
    "StrategyFileAccessError": "ante.strategy.exceptions",
    "StrategyLoadError": "ante.strategy.exceptions",
    "StrategyValidationError": "ante.strategy.exceptions",
    # indicators — heavy: pandas / pandas_ta / numpy eager load 유발
    "IndicatorCalculator": "ante.strategy.indicators",
    # loader — light (importlib만 사용)
    "StrategyLoader": "ante.strategy.loader",
    # registry — light (dataclass / StrEnum)
    "StrategyRecord": "ante.strategy.registry",
    "StrategyRegistry": "ante.strategy.registry",
    "StrategyStatus": "ante.strategy.registry",
    # snapshot — light (shutil)
    "StrategySnapshot": "ante.strategy.snapshot",
    # validator — light (ast)
    "StrategyValidator": "ante.strategy.validator",
    "VALID_EXCHANGES": "ante.strategy.validator",
    "ValidationResult": "ante.strategy.validator",
    "validate_exchange": "ante.strategy.validator",
}


def __getattr__(name: str) -> object:
    """Lazy attribute resolution per PEP 562.

    퍼블릭 심볼을 실제 접근 시점에 import한다. 이렇게 하면 단순히
    ``import ante.strategy``를 수행했을 때 heavy 의존성(``pandas_ta``/``numba`` 등)이
    eager load되지 않고, ``from ante.strategy import StrategyStatus`` 같은 light
    심볼 import도 indicator 경로를 우회한다.
    """
    module_path = _LAZY_ATTRS.get(name)
    if module_path is None:
        raise AttributeError(f"module 'ante.strategy' has no attribute {name!r}")

    import importlib

    module = importlib.import_module(module_path)
    value = getattr(module, name)
    # 캐시: 후속 접근은 일반 attribute lookup으로 처리된다.
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_LAZY_ATTRS))


# 정적 분석기/타입 체커는 다음 import 블록만 본다. 런타임에는 평가되지 않으므로
# heavy 의존성을 eager-load하지 않는다.
if TYPE_CHECKING:
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
    from ante.strategy.indicators import IndicatorCalculator
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
