"""백테스트 실행 설정 및 데이터셋 메타정보."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class BacktestConfig:
    """백테스트 실행 설정."""

    strategy_path: str = ""
    symbols: list[str] = field(default_factory=list)
    timeframe: str = "1d"
    start_date: str = ""
    end_date: str = ""
    initial_balance: float = 10_000_000.0
    buy_commission_rate: float = 0.00015
    sell_commission_rate: float = 0.00195
    slippage_rate: float = 0.001
    data_paths: list[str] = field(default_factory=lambda: ["data/"])


@dataclass(frozen=True)
class DatasetInfo:
    """로드된 데이터셋 메타정보 (불변)."""

    symbol: str = ""
    timeframe: str = ""
    row_count: int = 0
    start_date: str = ""
    end_date: str = ""
    data_dir: str = ""
    file_count: int = 0
