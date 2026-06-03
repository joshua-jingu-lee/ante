"""non-CLI backtest exchange plumbing 테스트 (#1585).

CLI 검증과 분리 — service/provider가 exchange를 무시해도 CLI 테스트는
통과하므로 별도 고정한다:

- `_validate_config`: exchange 미지정 → KRX 기본 / 명시 → 그대로 (default plumbing).
- `BacktestService.run()`: `BacktestDataProvider`를 `exchange=<config.exchange>`로 생성.
- `BacktestDataProvider.load()`: store.read() **및** store.resolve_path() 양쪽에
  동일 exchange 전달 (resolve_path 메타 hop 회귀 고정).
- `BacktestExecutor`: `exchange=` ctor 인자를 받아 `_execute_signal`이 만든
  `BacktestTrade.exchange`에 그대로 라벨링 (executor→trade hop 회귀 고정).
- `BacktestService.run()`: `BacktestExecutor`를 `exchange=<config.exchange>`로
  생성 (service→executor hop 회귀 고정).
"""

from __future__ import annotations

import dataclasses
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import polars as pl
import pytest

from ante.backtest import runner
from ante.backtest.config import BacktestConfig
from ante.backtest.data_provider import BacktestDataProvider
from ante.backtest.executor import BacktestExecutor
from ante.backtest.result import BacktestResult, BacktestTrade
from ante.backtest.service import BacktestService
from ante.strategy.base import Signal, Strategy, StrategyMeta
from ante.strategy.validator import ValidationResult


def _bypass_validator():
    """service.run의 StrategyValidator 게이트(#2039)를 우회한다.

    이 파일의 run() exchange-plumbing 테스트는 StrategyLoader를 mock해 실제
    전략 파일 없이 ``s.py`` 경로로 run을 구동한다. #2039에서 load 직전 추가된
    정적 검증이 실제 파일을 읽지 않도록 valid 결과로 대체한다.
    """
    return patch(
        "ante.backtest.service.StrategyValidator.validate",
        return_value=ValidationResult(valid=True),
    )


class TestValidateConfigExchangeDefault:
    """_validate_config exchange default plumbing (검증 아님)."""

    def test_exchange_missing_defaults_to_krx(self):
        svc = BacktestService()
        validated = svc._validate_config(
            {
                "strategy_path": "s.py",
                "start_date": "2026-01-01",
                "end_date": "2026-01-02",
            }
        )
        assert isinstance(validated, BacktestConfig)
        assert validated.exchange == "KRX"

    def test_explicit_exchange_preserved(self):
        svc = BacktestService()
        validated = svc._validate_config(
            {
                "strategy_path": "s.py",
                "start_date": "2026-01-01",
                "end_date": "2026-01-02",
                "exchange": "NYSE",
            }
        )
        assert validated.exchange == "NYSE"

    def test_validate_config_rejects_non_canonical_exchange(self):
        """_validate_config가 non-canonical exchange를 거부한다 (#2034 supersede).

        #1585 당시에는 "게이트는 CLI ingress, 서비스 이중검증 금지"였으나,
        #2034가 programmatic dict 경로의 fake-success(invalid exchange가
        그대로 통과)를 닫기 위해 ``_validate_config`` 단일 chokepoint에
        canonical 검증(SSOT ``is_canonical``)을 추가하면서 이 정책을
        supersede했다 (timeframe/symbol #1604와 동형). CLI는 ingress에서
        별도 거부하지만 programmatic 직접 호출의 fake-success를 닫는다.
        """
        from ante.backtest.exceptions import BacktestConfigError

        svc = BacktestService()
        with pytest.raises(BacktestConfigError, match="Invalid exchange"):
            svc._validate_config(
                {
                    "strategy_path": "s.py",
                    "start_date": "2026-01-01",
                    "end_date": "2026-01-02",
                    "exchange": "ORACLE_INVALID_EXCHANGE",
                }
            )


class TestServicePassesExchangeToProvider:
    """BacktestService.run() → BacktestDataProvider(exchange=...) ctor 전달."""

    @pytest.mark.asyncio
    async def test_run_constructs_provider_with_config_exchange(self):
        config = {
            "strategy_path": "s.py",
            "start_date": "2026-01-01",
            "end_date": "2026-01-02",
            "symbols": ["005930"],
            "exchange": "NYSE",
        }

        provider_instance = MagicMock()
        provider_instance.loaded_datasets = []

        executor_instance = MagicMock()

        async def _fake_run(progress_callback=None):
            return BacktestResult(
                strategy_name="S",
                strategy_version="1",
                start_date="2026-01-01",
                end_date="2026-01-02",
                initial_balance=1.0,
                final_balance=1.0,
                total_return=0.0,
            )

        executor_instance.run = _fake_run

        with (
            _bypass_validator(),
            patch("ante.backtest.service.StrategyLoader") as mock_loader,
            patch("ante.backtest.service.ParquetStore") as mock_store_cls,
            patch(
                "ante.backtest.service.BacktestDataProvider",
                return_value=provider_instance,
            ) as mock_provider_cls,
            patch(
                "ante.backtest.service.BacktestExecutor",
                return_value=executor_instance,
            ),
        ):
            mock_loader.load.return_value = MagicMock()
            mock_store_cls.return_value = MagicMock()
            svc = BacktestService()
            await svc.run(config)

        _, kwargs = mock_provider_cls.call_args
        assert kwargs["exchange"] == "NYSE"

    @pytest.mark.asyncio
    async def test_run_defaults_provider_exchange_to_krx(self):
        config = {
            "strategy_path": "s.py",
            "start_date": "2026-01-01",
            "end_date": "2026-01-02",
            "symbols": [],
        }

        provider_instance = MagicMock()
        provider_instance.loaded_datasets = []
        executor_instance = MagicMock()

        async def _fake_run(progress_callback=None):
            return BacktestResult(
                strategy_name="S",
                strategy_version="1",
                start_date="2026-01-01",
                end_date="2026-01-02",
                initial_balance=1.0,
                final_balance=1.0,
                total_return=0.0,
            )

        executor_instance.run = _fake_run

        with (
            _bypass_validator(),
            patch("ante.backtest.service.StrategyLoader") as mock_loader,
            patch("ante.backtest.service.ParquetStore"),
            patch(
                "ante.backtest.service.BacktestDataProvider",
                return_value=provider_instance,
            ) as mock_provider_cls,
            patch(
                "ante.backtest.service.BacktestExecutor",
                return_value=executor_instance,
            ),
        ):
            mock_loader.load.return_value = MagicMock()
            svc = BacktestService()
            await svc.run(config)

        _, kwargs = mock_provider_cls.call_args
        assert kwargs["exchange"] == "KRX"


class TestDataProviderForwardsExchangeToStore:
    """BacktestDataProvider.load() → store.read() + store.resolve_path() 양쪽 hop."""

    def _make_store(self):
        store = MagicMock()
        store.read.return_value = pl.DataFrame({"timestamp": [], "close": []})
        store.resolve_path.return_value = Path("/nonexistent/dir")
        return store

    def test_load_forwards_explicit_exchange_to_read_and_resolve_path(self):
        store = self._make_store()
        provider = BacktestDataProvider(
            store=store,
            start_date="2026-01-01",
            end_date="2026-01-02",
            exchange="NYSE",
        )

        provider.load("AAPL", "1d")

        # store.read() hop
        _, read_kwargs = store.read.call_args
        assert read_kwargs["exchange"] == "NYSE"
        # store.resolve_path() 메타 hop (read와 동일 exchange)
        _, resolve_kwargs = store.resolve_path.call_args
        assert resolve_kwargs["exchange"] == "NYSE"

    def test_load_defaults_exchange_krx_to_both_hops(self):
        store = self._make_store()
        provider = BacktestDataProvider(
            store=store,
            start_date="2026-01-01",
            end_date="2026-01-02",
        )

        provider.load("005930", "1d")

        _, read_kwargs = store.read.call_args
        assert read_kwargs["exchange"] == "KRX"
        _, resolve_kwargs = store.resolve_path.call_args
        assert resolve_kwargs["exchange"] == "KRX"


class _SingleBuyStrategy(Strategy):
    """첫 스텝에 buy 1건만 내는 최소 전략 (executor hop fixture)."""

    meta = StrategyMeta(name="single_buy", version="1", description="t")

    def __init__(self, ctx):  # noqa: D107
        super().__init__(ctx)
        self._fired = False

    async def on_step(self, context) -> list[Signal]:  # noqa: D102
        if self._fired:
            return []
        self._fired = True
        return [Signal(symbol="TEST", side="buy", quantity=1.0, reason="r")]


class _FakeDataProvider:
    """2스텝짜리 인메모리 data_provider (실제 store/API 호출 없음)."""

    def __init__(self) -> None:
        self._idx = 0
        self._ts = [datetime(2026, 1, 1), datetime(2026, 1, 2)]
        self.start = "2026-01-01"
        self.end = "2026-01-02"
        self.loaded_datasets: list = []

    def get_total_steps(self) -> int:
        return len(self._ts)

    def advance(self) -> bool:
        self._idx += 1
        return self._idx < len(self._ts)

    def get_current_timestamp(self):
        if self._idx >= len(self._ts):
            return None
        return self._ts[self._idx]

    async def get_current_price(self, symbol: str) -> float:
        return 100.0

    def get_current_bar_price(self, symbol: str) -> float | None:
        # 체결가 게이트(#2098): 현재 봉이 있으면 체결 가능가를 돌려준다.
        # 이 fake는 모든 step에 봉이 있다고 보므로 as-of 가격과 동일하게 100.0.
        if self.get_current_timestamp() is None:
            return None
        return 100.0


def _make_executor(exchange: str | None) -> BacktestExecutor:
    kwargs = {"exchange": exchange} if exchange is not None else {}
    return BacktestExecutor(
        strategy_cls=_SingleBuyStrategy,
        data_provider=_FakeDataProvider(),
        initial_balance=1_000_000.0,
        **kwargs,
    )


class TestExecutorLabelsTradeWithExchange:
    """BacktestExecutor(exchange=) → BacktestTrade.exchange (executor→trade hop)."""

    @pytest.mark.asyncio
    async def test_explicit_exchange_labels_result_trades(self):
        executor = _make_executor("NYSE")

        result = await executor.run()

        assert result.trades, "1건의 거래가 체결되어야 한다"
        assert all(t.exchange == "NYSE" for t in result.trades)

    @pytest.mark.asyncio
    async def test_default_exchange_labels_result_trades_krx(self):
        executor = _make_executor(None)

        result = await executor.run()

        assert result.trades
        assert all(t.exchange == "KRX" for t in result.trades)


class TestServicePassesExchangeToExecutor:
    """BacktestService.run() → BacktestExecutor(exchange=...) ctor 전달.

    end-to-end에 가깝게: `_validate_config(exchange=...)`가 만든
    `validated.exchange`가 executor 생성 인자로 흐르는지 고정.
    """

    async def _run_capture_executor_kwargs(self, config: dict) -> dict:
        provider_instance = MagicMock()
        provider_instance.loaded_datasets = []
        executor_instance = MagicMock()

        async def _fake_run(progress_callback=None):
            return BacktestResult(
                strategy_name="S",
                strategy_version="1",
                start_date="2026-01-01",
                end_date="2026-01-02",
                initial_balance=1.0,
                final_balance=1.0,
                total_return=0.0,
            )

        executor_instance.run = _fake_run

        with (
            _bypass_validator(),
            patch("ante.backtest.service.StrategyLoader") as mock_loader,
            patch("ante.backtest.service.ParquetStore"),
            patch(
                "ante.backtest.service.BacktestDataProvider",
                return_value=provider_instance,
            ),
            patch(
                "ante.backtest.service.BacktestExecutor",
                return_value=executor_instance,
            ) as mock_executor_cls,
        ):
            mock_loader.load.return_value = MagicMock()
            svc = BacktestService()
            await svc.run(config)

        _, kwargs = mock_executor_cls.call_args
        return kwargs

    @pytest.mark.asyncio
    async def test_run_constructs_executor_with_config_exchange(self):
        kwargs = await self._run_capture_executor_kwargs(
            {
                "strategy_path": "s.py",
                "start_date": "2026-01-01",
                "end_date": "2026-01-02",
                "symbols": [],
                "exchange": "NYSE",
            }
        )
        assert kwargs["exchange"] == "NYSE"

    @pytest.mark.asyncio
    async def test_run_defaults_executor_exchange_to_krx(self):
        kwargs = await self._run_capture_executor_kwargs(
            {
                "strategy_path": "s.py",
                "start_date": "2026-01-01",
                "end_date": "2026-01-02",
                "symbols": [],
            }
        )
        assert kwargs["exchange"] == "KRX"


class TestResultToDictSerializesExchange:
    """BacktestResult.to_dict() → trades[i]["exchange"] (직렬화 hop 회귀).

    CLI JSON / subprocess / report draft 세 소비자가 모두 result.to_dict()를
    무가공 전달하므로, 이 단일 지점에서 exchange가 직렬화되어야 override가
    구조화 출력 체결 행에 보인다 (Codex branch review [P2] + meta-review).
    """

    @pytest.mark.asyncio
    async def test_explicit_exchange_appears_in_to_dict_trades(self):
        executor = _make_executor("NYSE")

        result = await executor.run()

        out = result.to_dict()
        assert out["trades"], "1건의 거래가 직렬화되어야 한다"
        assert all(t["exchange"] == "NYSE" for t in out["trades"])

    @pytest.mark.asyncio
    async def test_default_exchange_appears_in_to_dict_trades_krx(self):
        executor = _make_executor(None)

        result = await executor.run()

        out = result.to_dict()
        assert out["trades"]
        assert all(t["exchange"] == "KRX" for t in out["trades"])

    def test_to_dict_trade_keeps_exchange_label_verbatim(self):
        """비-canonical 라벨도 to_dict가 그대로 직렬화 (재검증 없음)."""
        result = BacktestResult(
            strategy_name="S",
            strategy_version="1",
            start_date="2026-01-01",
            end_date="2026-01-02",
            initial_balance=1.0,
            final_balance=1.0,
            total_return=0.0,
            trades=[
                BacktestTrade(
                    timestamp=datetime(2026, 1, 1),
                    symbol="AAPL",
                    side="buy",
                    quantity=1.0,
                    price=100.0,
                    commission=0.0,
                    slippage=0.0,
                    reason="r",
                    exchange="NASDAQ",
                )
            ],
        )

        out = result.to_dict()

        assert out["trades"][0]["exchange"] == "NASDAQ"


class TestRunnerForwardsToDictUnmodified:
    """runner.run_backtest()는 service 결과의 to_dict() superset envelope 반환 (#2001).

    subprocess 실제 기동은 무거우므로, runner가 result.to_dict()의 모든 키를
    보존하면서 런타임 메타데이터(result_path/strategy_name/strategy_version)를
    additive 로 surface 함을 가벼운 단위로 갈음한다 (to_dict 출력 단언은
    in-process TestResultToDictSerializesExchange가 필수로 커버).
    """

    @pytest.mark.asyncio
    async def test_run_backtest_returns_service_result_to_dict_with_exchange(
        self,
    ):
        result = BacktestResult(
            strategy_name="S",
            strategy_version="1",
            start_date="2026-01-01",
            end_date="2026-01-02",
            initial_balance=1.0,
            final_balance=1.0,
            total_return=0.0,
            trades=[
                BacktestTrade(
                    timestamp=datetime(2026, 1, 1),
                    symbol="AAPL",
                    side="buy",
                    quantity=1.0,
                    price=100.0,
                    commission=0.0,
                    slippage=0.0,
                    reason="r",
                    exchange="NYSE",
                )
            ],
        )

        service_instance = MagicMock()

        async def _fake_run(config):
            return result

        service_instance.run = _fake_run

        with patch(
            "ante.backtest.service.BacktestService",
            return_value=service_instance,
        ):
            out = await runner.run_backtest(
                {
                    "strategy_path": "s.py",
                    "start_date": "2026-01-01",
                    "end_date": "2026-01-02",
                    "exchange": "NYSE",
                }
            )

        # #2001: envelope 은 to_dict() 의 superset — to_dict 의 모든 키/값을
        # 보존하면서 런타임 메타데이터 3키를 additive 로 추가한다.
        to_dict = result.to_dict()
        assert set(out) >= set(to_dict), "to_dict() 키가 모두 보존되어야 한다"
        for key, value in to_dict.items():
            assert out[key] == value, f"{key} 값이 to_dict 와 동일해야 한다"
        # 런타임 메타데이터 3키 surface.
        assert out["result_path"] == result.result_path
        assert out["strategy_name"] == "S"
        assert out["strategy_version"] == "1"
        assert out["trades"][0]["exchange"] == "NYSE"


class TestTradeSerializationCompletenessInvariant:
    """직렬화 누락 invariant: BacktestTrade의 public 필드 ⊆ to_dict trade 키.

    향후 BacktestTrade에 필드를 추가하면서 to_dict() 컴프리헨션 갱신을
    누락하면 이 테스트가 자동으로 감지한다 (이번 exchange 누락 재발 방지).
    """

    def test_all_trade_dataclass_fields_present_in_to_dict_trade(self):
        result = BacktestResult(
            strategy_name="S",
            strategy_version="1",
            start_date="2026-01-01",
            end_date="2026-01-02",
            initial_balance=1.0,
            final_balance=1.0,
            total_return=0.0,
            trades=[
                BacktestTrade(
                    timestamp=datetime(2026, 1, 1),
                    symbol="AAPL",
                    side="buy",
                    quantity=1.0,
                    price=100.0,
                    commission=0.0,
                    slippage=0.0,
                    reason="r",
                    exchange="NYSE",
                )
            ],
        )

        trade_dict = result.to_dict()["trades"][0]
        field_names = {f.name for f in dataclasses.fields(BacktestTrade)}

        missing = field_names - set(trade_dict.keys())
        assert not missing, (
            f"BacktestTrade 필드가 to_dict() trade 직렬화에서 누락됨: {missing}. "
            "result.py to_dict()의 trade 컴프리헨션에 추가하라."
        )
