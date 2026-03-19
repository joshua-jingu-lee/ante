"""PriceSimulator 단위 테스트.

시드 재현성, 가격 범위, KRX 호가 단위(tick size) 검증.
"""

from __future__ import annotations

import pytest

from ante.broker.test import (
    VIRTUAL_STOCK_PRESETS,
    PriceSimulator,
    StockPreset,
    _tick_size,
    tick_round,
)

# ── tick_round / tick_size 검증 ─────────────────────────────


class TestTickRound:
    """KRX 호가 단위 반올림 검증."""

    @pytest.mark.parametrize(
        ("price", "expected_tick"),
        [
            (1_500, 1),
            (3_000, 5),
            (10_000, 10),
            (30_000, 50),
            (72_000, 100),
            (250_000, 500),
            (600_000, 1_000),
        ],
    )
    def test_tick_size_by_price_range(self, price: float, expected_tick: int) -> None:
        """가격 구간별 호가 단위가 올바르다."""
        assert _tick_size(price) == expected_tick

    @pytest.mark.parametrize(
        ("price", "expected"),
        [
            # 100원 단위 (50,000~200,000)
            (72_051, 72_100),
            (72_049, 72_000),
            (72_150, 72_200),  # 정확히 .5 → banker's rounding (짝수)
            # 500원 단위 (200,000~500,000)
            (390_300, 390_500),
            (390_249, 390_000),
            # 50원 단위 (20,000~50,000)
            (48_026, 48_050),
            (48_024, 48_000),
            # 10원 단위 (5,000~20,000)
            (10_006, 10_010),
            (10_004, 10_000),
        ],
    )
    def test_tick_round_values(self, price: float, expected: float) -> None:
        """호가 단위 반올림이 정확하다."""
        assert tick_round(price) == expected


# ── PriceSimulator 기본 동작 ────────────────────────────────


class TestPriceSimulatorBasic:
    """PriceSimulator 기본 동작 검증."""

    def test_default_presets(self) -> None:
        """기본 프리셋 6종으로 초기화된다."""
        sim = PriceSimulator()
        assert len(sim.symbols) == 6
        assert set(sim.symbols) == set(VIRTUAL_STOCK_PRESETS.keys())

    def test_custom_presets(self) -> None:
        """커스텀 프리셋으로 초기화할 수 있다."""
        custom = {
            "999999": StockPreset("999999", "테스트종목", 100_000, 0.02),
        }
        sim = PriceSimulator(presets=custom)
        assert sim.symbols == ["999999"]
        assert sim.get_price("999999") == 100_000

    def test_initial_price_matches_preset(self) -> None:
        """초기 가격이 프리셋 기준가를 호가 단위로 반올림한 값이다."""
        sim = PriceSimulator()
        for symbol, preset in VIRTUAL_STOCK_PRESETS.items():
            assert sim.get_price(symbol) == tick_round(preset.base_price)

    def test_tick_returns_float(self) -> None:
        """tick()은 float를 반환한다."""
        sim = PriceSimulator()
        price = sim.tick("000001")
        assert isinstance(price, float)

    def test_tick_updates_price(self) -> None:
        """tick() 호출 후 get_price()가 갱신된 값을 반환한다."""
        sim = PriceSimulator()
        new_price = sim.tick("000001")
        assert sim.get_price("000001") == new_price

    def test_unknown_symbol_tick_raises(self) -> None:
        """등록되지 않은 종목으로 tick() 호출 시 KeyError."""
        sim = PriceSimulator()
        with pytest.raises(KeyError, match="등록되지 않은 종목"):
            sim.tick("999999")

    def test_unknown_symbol_get_price_raises(self) -> None:
        """등록되지 않은 종목으로 get_price() 호출 시 KeyError."""
        sim = PriceSimulator()
        with pytest.raises(KeyError, match="등록되지 않은 종목"):
            sim.get_price("999999")


# ── 시드 재현성 ─────────────────────────────────────────────


class TestSeedReproducibility:
    """동일 시드 → 동일 가격 시퀀스 재현성 검증."""

    def test_same_seed_same_sequence(self) -> None:
        """동일 시드로 초기화하면 동일한 가격 시퀀스를 생성한다."""
        seq1 = self._generate_sequence(seed=42, ticks=100)
        seq2 = self._generate_sequence(seed=42, ticks=100)
        assert seq1 == seq2

    def test_different_seed_different_sequence(self) -> None:
        """다른 시드로 초기화하면 다른 가격 시퀀스를 생성한다."""
        # 낮은 가격대(호가 단위 1원)를 사용하여 변동이 반올림에 묻히지 않게 함
        preset = {"T01": StockPreset("T01", "테스트", 1_000, 0.03)}
        seq1 = self._generate_sequence_with_preset(preset, seed=42, ticks=100)
        seq2 = self._generate_sequence_with_preset(preset, seed=99, ticks=100)
        assert seq1 != seq2

    def test_reproducibility_across_symbols(self) -> None:
        """여러 종목을 교차 호출해도 시드 재현성이 유지된다."""
        symbols = ["000001", "000002", "000003"]

        def run(seed: int) -> list[float]:
            sim = PriceSimulator(seed=seed)
            prices = []
            for _ in range(20):
                for s in symbols:
                    prices.append(sim.tick(s))
            return prices

        assert run(42) == run(42)

    @staticmethod
    def _generate_sequence(seed: int, ticks: int) -> list[float]:
        sim = PriceSimulator(seed=seed)
        return [sim.tick("000001") for _ in range(ticks)]

    @staticmethod
    def _generate_sequence_with_preset(
        presets: dict[str, StockPreset], seed: int, ticks: int
    ) -> list[float]:
        sim = PriceSimulator(presets=presets, seed=seed)
        symbol = next(iter(presets))
        return [sim.tick(symbol) for _ in range(ticks)]


# ── 가격 범위 및 호가 단위 검증 ─────────────────────────────


class TestPriceProperties:
    """가격 변동 특성 검증."""

    def test_prices_remain_positive(self) -> None:
        """1000틱 진행 후에도 가격이 양수를 유지한다."""
        sim = PriceSimulator(seed=12345)
        for symbol in sim.symbols:
            for _ in range(1000):
                price = sim.tick(symbol)
                assert price > 0, f"{symbol} 가격이 0 이하: {price}"

    def test_prices_conform_to_tick_size(self) -> None:
        """모든 가격이 KRX 호가 단위의 정수배이다."""
        sim = PriceSimulator(seed=42)
        for symbol in sim.symbols:
            for _ in range(500):
                price = sim.tick(symbol)
                tick = _tick_size(price)
                remainder = price % tick
                assert remainder == 0, (
                    f"{symbol}: {price}는 호가단위 {tick}의 배수가 아님"
                )

    def test_price_changes_are_small_per_tick(self) -> None:
        """틱 단위 변동폭이 일변동성보다 훨씬 작다."""
        sim = PriceSimulator(seed=42)
        symbol = "000001"
        prev = sim.get_price(symbol)
        max_return = 0.0
        for _ in range(1000):
            curr = sim.tick(symbol)
            if prev > 0:
                ret = abs(curr - prev) / prev
                max_return = max(max_return, ret)
            prev = curr
        # 틱 단위 최대 수익률은 일변동성(1.8%)의 일부여야 함
        # σ_tick ≈ 0.018 / √23400 ≈ 0.000118, 3σ ≈ 0.00035
        # 호가 단위 반올림 효과를 고려하여 넉넉하게 1%로 설정
        assert max_return < 0.01, f"틱 최대 변동률 {max_return:.6f}이 1%를 초과"

    def test_presets_property_returns_copy(self) -> None:
        """presets 프로퍼티가 내부 상태의 복사본을 반환한다."""
        sim = PriceSimulator()
        presets = sim.presets
        presets.pop("000001")
        assert "000001" in sim.presets
