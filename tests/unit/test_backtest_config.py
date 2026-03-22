"""BacktestConfig / DatasetInfo 단위 테스트."""

from __future__ import annotations

import dataclasses

import pytest

from ante.backtest.config import BacktestConfig, DatasetInfo


class TestBacktestConfig:
    """BacktestConfig 데이터클래스 테스트."""

    def test_default_values(self) -> None:
        cfg = BacktestConfig()
        assert cfg.strategy_path == ""
        assert cfg.symbols == []
        assert cfg.timeframe == "1d"
        assert cfg.start_date == ""
        assert cfg.end_date == ""
        assert cfg.initial_balance == 10_000_000.0
        assert cfg.buy_commission_rate == 0.00015
        assert cfg.sell_commission_rate == 0.00195
        assert cfg.slippage_rate == 0.001
        assert cfg.data_paths == ["data/"]

    def test_explicit_values(self) -> None:
        cfg = BacktestConfig(
            strategy_path="strategies/ma_cross.py",
            symbols=["005930", "000660"],
            timeframe="1h",
            start_date="2025-01-01",
            end_date="2025-12-31",
            initial_balance=50_000_000.0,
            buy_commission_rate=0.0003,
            sell_commission_rate=0.002,
            slippage_rate=0.002,
            data_paths=["data/kr/", "data/us/"],
        )
        assert cfg.strategy_path == "strategies/ma_cross.py"
        assert cfg.symbols == ["005930", "000660"]
        assert cfg.timeframe == "1h"
        assert cfg.start_date == "2025-01-01"
        assert cfg.end_date == "2025-12-31"
        assert cfg.initial_balance == 50_000_000.0
        assert cfg.buy_commission_rate == 0.0003
        assert cfg.sell_commission_rate == 0.002
        assert cfg.slippage_rate == 0.002
        assert cfg.data_paths == ["data/kr/", "data/us/"]

    def test_data_paths_default_is_independent(self) -> None:
        """각 인스턴스의 data_paths가 독립적인 리스트인지 확인."""
        cfg1 = BacktestConfig()
        cfg2 = BacktestConfig()
        cfg1.data_paths.append("extra/")
        assert cfg2.data_paths == ["data/"]

    def test_symbols_default_is_independent(self) -> None:
        """각 인스턴스의 symbols가 독립적인 리스트인지 확인."""
        cfg1 = BacktestConfig()
        cfg2 = BacktestConfig()
        cfg1.symbols.append("005930")
        assert cfg2.symbols == []


class TestDatasetInfo:
    """DatasetInfo 데이터클래스 테스트."""

    def test_default_values(self) -> None:
        info = DatasetInfo()
        assert info.symbol == ""
        assert info.timeframe == ""
        assert info.row_count == 0
        assert info.start_date == ""
        assert info.end_date == ""
        assert info.data_dir == ""
        assert info.file_count == 0

    def test_all_fields(self) -> None:
        info = DatasetInfo(
            symbol="005930",
            timeframe="1d",
            row_count=1200,
            start_date="2020-01-02",
            end_date="2024-12-30",
            data_dir="data/ohlcv/1d/KRX/005930",
            file_count=60,
        )
        assert info.symbol == "005930"
        assert info.timeframe == "1d"
        assert info.row_count == 1200
        assert info.start_date == "2020-01-02"
        assert info.end_date == "2024-12-30"
        assert info.data_dir == "data/ohlcv/1d/KRX/005930"
        assert info.file_count == 60

    def test_frozen_immutability(self) -> None:
        """frozen=True로 인해 필드 변경 시 FrozenInstanceError 발생."""
        info = DatasetInfo(symbol="005930")
        with pytest.raises(dataclasses.FrozenInstanceError):
            info.symbol = "000660"  # type: ignore[misc]

    def test_frozen_immutability_all_fields(self) -> None:
        """모든 필드에 대해 일반 대입이 FrozenInstanceError를 발생시키는지 확인."""
        info = DatasetInfo(
            symbol="005930",
            timeframe="1d",
            row_count=100,
            start_date="2025-01-01",
            end_date="2025-12-31",
            data_dir="data/",
            file_count=5,
        )
        for f in dataclasses.fields(info):
            with pytest.raises(dataclasses.FrozenInstanceError):
                setattr(info, f.name, "changed")
