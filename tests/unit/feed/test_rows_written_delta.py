"""rows_written을 net-new 저장 delta로 산출하는 store/collector 계약 테스트(#1993).

기존 ``ParquetStore.write`` 는 None을 반환했고 collector는 입력 ``len`` 을
누적했다. 이는 dedup/재수집/지표 in-place overwrite를 모두 과대계상해
report ``rows_written`` 이 실제 저장량을 크게 초과했다(관측: 4.7M vs 6.8M).

수정(#1993):
  - ``_persist_partition`` / ``write`` 가 **net-new 저장 행 수**(int)를 반환한다:
    ``max(0, len(merged) - len(existing))`` (legacy 중복 정리 시 음수 → 0 clamp,
    merge 실패 시 0, 빈 입력 0, 신규 write는 dedup 결과 행 수).
  - collector는 입력 len이 아니라 ``store.write`` 반환을 누적한다.

이 파일은 store 계층(a~e)과 collector 누적(j)을 잠근다. checkpoint/DART
QuarterStatus 무회귀(f~h)는 각 runner/collector 테스트에서 검증한다.
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

from ante.data.store import ParquetStore
from ante.feed.pipeline.data_go_kr_collector import DataGoKrCollector


def _ohlcv_df(symbol: str, days: list[int], month: int = 3) -> pl.DataFrame:
    """주어진 일(day)들로 1d OHLCV DataFrame을 만든다(파티션은 월별)."""
    from datetime import datetime

    ts = [datetime(2026, month, d) for d in days]
    n = len(ts)
    return pl.DataFrame(
        {
            "timestamp": pl.Series(
                ts, dtype=pl.Datetime(time_unit="us")
            ).dt.replace_time_zone("UTC"),
            "symbol": [symbol] * n,
            "open": [50000.0] * n,
            "high": [50100.0] * n,
            "low": [49900.0] * n,
            "close": [50050.0] * n,
            "volume": [1000] * n,
            "source": ["test"] * n,
        }
    )


# ── (a) 신규 write → delta == 입력 행 수 ──────────────────────────────────────


def test_new_write_returns_input_len(tmp_path) -> None:
    """기존 파일이 없는 신규 write는 dedup 결과 행 수(=입력 행 수)를 반환한다."""
    store = ParquetStore(base_path=tmp_path)
    df = _ohlcv_df("005930", [2, 3, 4])

    net = store.write("005930", "1d", df, data_type="ohlcv")

    assert net == 3
    assert store.get_row_count("005930", "1d") == 3


# ── (b) 재write(동일 데이터) → delta == 0 (dedup) ─────────────────────────────


def test_rewrite_same_data_returns_zero(tmp_path) -> None:
    """같은 데이터를 다시 write하면 natural-key dedup으로 net-new=0이다."""
    store = ParquetStore(base_path=tmp_path)
    df = _ohlcv_df("005930", [2, 3, 4])

    first = store.write("005930", "1d", df, data_type="ohlcv")
    second = store.write("005930", "1d", df, data_type="ohlcv")

    assert first == 3
    assert second == 0  # 재수집 dedup → net-new 없음
    assert store.get_row_count("005930", "1d") == 3  # 행 수 불변


def test_partial_overlap_returns_only_new_rows(tmp_path) -> None:
    """일부만 신규(겹치는 날짜 + 새 날짜)면 net-new는 새 날짜 수만큼이다."""
    store = ParquetStore(base_path=tmp_path)
    store.write("005930", "1d", _ohlcv_df("005930", [2, 3]), data_type="ohlcv")

    # 3(중복) + 4,5(신규) → net-new 2.
    net = store.write("005930", "1d", _ohlcv_df("005930", [3, 4, 5]), data_type="ohlcv")

    assert net == 2
    assert store.get_row_count("005930", "1d") == 4  # 2,3,4,5


# ── (c) legacy 중복 정리(merged < existing) → max(0) = 0 ──────────────────────


def test_legacy_duplicate_cleanup_clamps_to_zero(tmp_path) -> None:
    """기존 파일에 natural-key 중복이 있어 merge가 행을 줄여도 delta는 0으로 clamp.

    fundamental natural key는 (date, source). 기존 파일에 같은 (date, source)
    중복 2행을 심어두면 merge dedup이 1행으로 줄여 merged < existing이 된다.
    이때 net-new = max(0, len(merged) - len(existing)) = 0(음수 금지).
    """
    store = ParquetStore(base_path=tmp_path)
    # 같은 (date, source) 중복 2행을 가진 fundamental 파티션을 직접 배치.
    dup = pl.DataFrame(
        {
            "date": [date(2026, 3, 31), date(2026, 3, 31)],
            "symbol": ["005930", "005930"],
            "market_cap": [100, 100],
            "source": ["data_go_kr", "data_go_kr"],
        }
    )
    part_dir = tmp_path / "fundamental" / "KRX" / "005930"
    part_dir.mkdir(parents=True)
    dup.write_parquet(str(part_dir / "2026-03.parquet"))

    # 같은 (date, source) 1행을 write → merge dedup이 (2+1)→1로 줄어든다.
    new = pl.DataFrame(
        {
            "date": [date(2026, 3, 31)],
            "symbol": ["005930"],
            "market_cap": [200],
            "source": ["data_go_kr"],
        }
    )
    net = store.write("005930", "krx", new, data_type="fundamental")

    # merged(1) < existing(2) → max(0, 1-2) = 0.
    assert net == 0


# ── (d) 다파티션 write → 파티션별 delta 합 ────────────────────────────────────


def test_multi_partition_sums_deltas(tmp_path) -> None:
    """여러 월 파티션에 걸친 write는 파티션별 net-new의 합을 반환한다."""
    store = ParquetStore(base_path=tmp_path)
    # 3월 2일 + 4월 2일 → 두 월 파티션, 각 1행 신규.
    df = pl.concat(
        [_ohlcv_df("005930", [2], month=3), _ohlcv_df("005930", [2], month=4)]
    )

    net = store.write("005930", "1d", df, data_type="ohlcv")

    assert net == 2  # 2026-03(1) + 2026-04(1)


# ── (e) merge 실패(손상 파티션 보존) → delta == 0 + store_merge 경고 ──────────


def test_merge_failure_returns_zero_and_warns(tmp_path) -> None:
    """기존 파티션이 손상이면 merge 실패 → 기존 보존 + net-new 0 + store_merge 경고."""
    store = ParquetStore(base_path=tmp_path)
    part_dir = tmp_path / "fundamental" / "KRX" / "005930"
    part_dir.mkdir(parents=True)
    (part_dir / "2026-03.parquet").write_bytes(b"corrupt-not-parquet")

    new = pl.DataFrame(
        {
            "date": [date(2026, 3, 31)],
            "symbol": ["005930"],
            "market_cap": [200],
            "source": ["data_go_kr"],
        }
    )
    net = store.write("005930", "krx", new, data_type="fundamental")

    assert net == 0  # 저장 반영 없음(기존 파일 보존)
    warnings = store.drain_warnings()
    assert any(w.get("type") == "store_merge" for w in warnings)
    # 손상 파일은 보존(데이터 손실 방지).
    assert (part_dir / "2026-03.parquet").read_bytes() == b"corrupt-not-parquet"


# ── (j) collector rows_written == store 실제 저장 합(재수집 0) ────────────────


class _FakeSource:
    """data.go.kr source 스텁: fetch가 고정 raw_items를 반환한다."""

    def __init__(self, items: list[dict]) -> None:
        self._items = items

    async def fetch(self, target_date: str) -> list[dict]:
        return list(self._items)


def _raw(symbol: str) -> dict:
    """정규화 가능한 최소 data.go.kr raw row."""
    return {
        "srtnCd": symbol,
        "basDt": "20260102",
        "mrktCtg": "KOSPI",
        "clpr": "50000",
        "mkp": "49900",
        "hipr": "50500",
        "lopr": "49500",
        "trqu": "1000",
        "itmsNm": "삼성전자",
        "lstgStCnt": "5969782550",
        "mrktTotAmt": "300000000000000",
    }


@pytest.mark.asyncio
async def test_collector_rows_written_is_store_net_delta(tmp_path) -> None:
    """collector net_delta = store 실제 저장 합. 재수집 시 net_delta=0, stored_ok=True.

    (a) 첫 수집: 유효 데이터 저장 → net_delta>0, stored_ok=True.
    (b) 같은 날짜 재수집: dedup으로 net_delta=0, **stored_ok=True**(유효 데이터가
        store에 반영됨 — checkpoint stall 방지). 입력 len 누적이 아니라 store
        실제 저장 delta를 보고하므로 재수집이 rows_written을 과대계상하지 않는다.
    """
    store = ParquetStore(base_path=tmp_path)
    collector = DataGoKrCollector(source=_FakeSource([_raw("005930")]))

    net1, stored_ok1, syms1, _w1 = await collector.collect("20260102", store)
    assert net1 > 0
    assert stored_ok1 is True
    assert syms1 == {"005930"}

    # 같은 날짜 재수집 → net_delta=0(dedup), stored_ok=True(유효 데이터 반영).
    net2, stored_ok2, syms2, _w2 = await collector.collect("20260102", store)
    assert net2 == 0
    assert stored_ok2 is True
    assert syms2 == {"005930"}


@pytest.mark.asyncio
async def test_collector_empty_response_stored_ok_false(tmp_path) -> None:
    """빈 응답(raw 없음) → net_delta=0 AND stored_ok=False(저장 반영 전무)."""
    store = ParquetStore(base_path=tmp_path)
    collector = DataGoKrCollector(source=_FakeSource([]))

    net, stored_ok, syms, _w = await collector.collect("20260102", store)

    assert net == 0
    assert stored_ok is False
    assert syms == set()
