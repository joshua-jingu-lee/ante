"""무거래 zero-OHLC 행의 backtest-load flat-bar 정규화 테스트(#2071).

data.go.kr 무거래/거래정지 행(``open==high==low==0 & close>0 & volume==0``,
amount 컬럼 존재 시 ``amount==0``)을 ``BacktestDataProvider.load`` 가 backtest
view 한정으로 flat bar(``O=H=L=C=close``)로 정규화하는지 검증한다. 저장 raw는
불변이어야 하고(데이터 무손실 우선), 정확 시그니처 밖의 행은 마스킹하지 않는다.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import polars as pl

from ante.backtest.data_provider import BacktestDataProvider


def _ts(n: int) -> list[datetime]:
    start = datetime(2026, 1, 2, 0, 0, tzinfo=UTC)
    return [start + timedelta(days=i) for i in range(n)]


def _df(rows: list[dict], *, with_amount: bool = True) -> pl.DataFrame:
    """행 dict 목록으로 OHLCV DataFrame 구성. timestamp는 일별로 자동 부여."""
    n = len(rows)
    ts = _ts(n)
    data: dict[str, list] = {
        "timestamp": ts,
        "symbol": ["005930"] * n,
        "open": [float(r["open"]) for r in rows],
        "high": [float(r["high"]) for r in rows],
        "low": [float(r["low"]) for r in rows],
        "close": [float(r["close"]) for r in rows],
        "volume": [int(r["volume"]) for r in rows],
    }
    if with_amount:
        data["amount"] = [int(r.get("amount", 0)) for r in rows]
    data["source"] = ["data.go.kr"] * n
    return pl.DataFrame(data)


def _provider_with(raw_df: pl.DataFrame) -> tuple[BacktestDataProvider, MagicMock]:
    """store.read가 ``raw_df`` 를 반환하도록 mock한 provider."""
    store = MagicMock()
    store.read.return_value = raw_df
    store.resolve_path.return_value = MagicMock(exists=MagicMock(return_value=False))
    provider = BacktestDataProvider(
        store=store, start_date="2026-01-01", end_date="2026-12-31"
    )
    return provider, store


def _cached(provider: BacktestDataProvider, symbol: str = "005930") -> pl.DataFrame:
    """load 후 캐시에 들어간 (정규화된) view를 꺼낸다."""
    return provider._cache[f"{symbol}:1d"]


# (a) 정확 시그니처(O=H=L=0, C>0, V=0, amount=0) → O=H=L=C 정규화 ─────────


async def test_no_trade_signature_normalized_to_flat_bar():
    raw = _df(
        [
            {
                "open": 50000,
                "high": 50500,
                "low": 49500,
                "close": 50250,
                "volume": 1000,
            },
            {"open": 0, "high": 0, "low": 0, "close": 465, "volume": 0, "amount": 0},
        ]
    )
    provider, _ = _provider_with(raw)
    provider.load("005930", "1d")
    view = _cached(provider)

    # 무거래 행이 flat bar로 정규화됨: O=H=L=C=close(465).
    assert view["open"][1] == 465.0
    assert view["high"][1] == 465.0
    assert view["low"][1] == 465.0
    assert view["close"][1] == 465.0
    # 정상 행은 무변경.
    assert view["open"][0] == 50000.0
    assert view["high"][0] == 50500.0
    assert view["low"][0] == 49500.0


async def test_no_trade_signature_without_amount_column_normalized():
    """amount 컬럼이 없는 df도 (O=H=L=0,C>0,V=0)만으로 정규화된다."""
    raw = _df(
        [{"open": 0, "high": 0, "low": 0, "close": 51600, "volume": 0}],
        with_amount=False,
    )
    provider, _ = _provider_with(raw)
    provider.load("005930", "1d")
    view = _cached(provider)
    assert view["open"][0] == 51600.0
    assert view["high"][0] == 51600.0
    assert view["low"][0] == 51600.0


# (b) partial-zero(open>0, low=0) → 무변경 (실제 데이터 오류 마스킹 금지) ─────


async def test_partial_zero_not_normalized():
    raw = _df(
        [{"open": 100, "high": 200, "low": 0, "close": 150, "volume": 0, "amount": 0}]
    )
    provider, _ = _provider_with(raw)
    provider.load("005930", "1d")
    view = _cached(provider)
    # partial-zero(low=0이지만 open>0)는 정확 시그니처가 아니므로 무변경.
    assert view["open"][0] == 100.0
    assert view["high"][0] == 200.0
    assert view["low"][0] == 0.0
    assert view["close"][0] == 150.0


# (c) volume>0 또는 amount>0(거래 발생) → 무변경 ───────────────────────────


async def test_volume_positive_not_normalized():
    raw = _df(
        [{"open": 0, "high": 0, "low": 0, "close": 465, "volume": 5, "amount": 0}]
    )
    provider, _ = _provider_with(raw)
    provider.load("005930", "1d")
    view = _cached(provider)
    # volume>0이면 거래가 발생한 것이므로 zero OHL을 보정하지 않는다.
    assert view["open"][0] == 0.0
    assert view["high"][0] == 0.0
    assert view["low"][0] == 0.0


async def test_amount_positive_not_normalized():
    raw = _df(
        [{"open": 0, "high": 0, "low": 0, "close": 465, "volume": 0, "amount": 123}]
    )
    provider, _ = _provider_with(raw)
    provider.load("005930", "1d")
    view = _cached(provider)
    # amount>0이면 거래가 발생한 것이므로 보정하지 않는다.
    assert view["open"][0] == 0.0
    assert view["high"][0] == 0.0
    assert view["low"][0] == 0.0


# (d) 정상 bar(O,H,L,C>0) → 무변경 ──────────────────────────────────────────


async def test_normal_bar_unchanged():
    raw = _df(
        [
            {
                "open": 50000,
                "high": 50500,
                "low": 49500,
                "close": 50250,
                "volume": 1000,
            },
            {
                "open": 51000,
                "high": 51500,
                "low": 50500,
                "close": 51250,
                "volume": 2000,
            },
        ]
    )
    provider, _ = _provider_with(raw)
    provider.load("005930", "1d")
    view = _cached(provider)
    assert view["open"].to_list() == [50000.0, 51000.0]
    assert view["high"].to_list() == [50500.0, 51500.0]
    assert view["low"].to_list() == [49500.0, 50500.0]


# (e) 저장 raw 무영향 — load만 정규화, store가 돌려준 raw 객체는 불변 ─────────


async def test_storage_raw_unaffected():
    """store.read mock으로 raw 반환 후, raw 객체 자체는 정규화로 변형되지 않는다.

    저장 raw(parquet)는 데이터 무손실 우선 원칙으로 불변이어야 한다. 정규화는
    캐시 view에만 적용되며, store가 돌려준 DataFrame은 그대로 남아야 한다.
    """
    raw = _df(
        [{"open": 0, "high": 0, "low": 0, "close": 465, "volume": 0, "amount": 0}]
    )
    provider, store = _provider_with(raw)
    provider.load("005930", "1d")

    # store가 돌려준 raw 객체는 여전히 zero-OHL(불변).
    returned_raw = store.read.return_value
    assert returned_raw["open"][0] == 0.0
    assert returned_raw["high"][0] == 0.0
    assert returned_raw["low"][0] == 0.0
    # 캐시 view만 정규화됨.
    assert _cached(provider)["open"][0] == 465.0


# (f) 무거래일 intraday range가 0 ──────────────────────────────────────────


async def test_no_trade_intraday_range_zero():
    raw = _df(
        [{"open": 0, "high": 0, "low": 0, "close": 104600, "volume": 0, "amount": 0}]
    )
    provider, _ = _provider_with(raw)
    provider.load("005930", "1d")
    view = _cached(provider)
    intraday_range = view["high"][0] - view["low"][0]
    assert intraday_range == 0.0
    # carrying price(close)는 보존.
    assert view["close"][0] == 104600.0


# (g) get_ohlcv on-demand 경로도 load 경유라 정규화 적용 ──────────────────────


async def test_get_ohlcv_on_demand_normalized():
    """캐시 미스 → get_ohlcv가 load()를 거치므로 정규화가 적용된다."""
    raw = _df(
        [
            {
                "open": 50000,
                "high": 50500,
                "low": 49500,
                "close": 50250,
                "volume": 1000,
            },
            {"open": 0, "high": 0, "low": 0, "close": 465, "volume": 0, "amount": 0},
        ]
    )
    provider, _ = _provider_with(raw)
    # load를 직접 호출하지 않고 get_ohlcv로 lazy-load 유도.
    provider.advance()  # idx 0
    provider.advance()  # idx 1 (마지막 행까지 노출)
    df = await provider.get_ohlcv("005930", "1d", limit=100)
    # on-demand 경로에서도 무거래 행이 flat bar로 정규화됨.
    last = df.tail(1)
    assert last["open"][0] == 465.0
    assert last["high"][0] == 465.0
    assert last["low"][0] == 465.0


# 빈 df(존재하지 않는 심볼) → 가드 ──────────────────────────────────────────


async def test_empty_df_passthrough():
    provider, _ = _provider_with(pl.DataFrame())
    # OHLCV 컬럼이 없는 빈 df는 그대로 통과(에러 없음).
    provider.load("999999", "1d")
    assert _cached(provider, "999999").is_empty()
