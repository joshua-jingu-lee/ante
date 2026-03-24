"""list_datasets 핸들러 단위 테스트.

이벤트 루프 블로킹 해소 (#949) 관련 변경사항을 검증한다:
- 종목 목록 수집 후 페이지네이션 -> 해당 페이지만 date_range 계산
- row_count, file_size는 목록 응답에서 항상 0
- 동기 I/O가 run_in_executor로 래핑되어 이벤트 루프를 블로킹하지 않음
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from ante.web.routes.data import list_datasets

# --- 헬퍼 ---


def _make_store(symbols_by_tf: dict[str, list[str]] | None = None) -> MagicMock:
    """테스트용 mock DataStore를 생성한다."""
    store = MagicMock()

    if symbols_by_tf is None:
        symbols_by_tf = {}

    def _list_symbols(tf=None, data_type=None):
        if data_type == "fundamental":
            return symbols_by_tf.get("fundamental", [])
        return symbols_by_tf.get(tf, [])

    store.list_symbols.side_effect = _list_symbols
    store.get_date_range.return_value = ("2024-01-01", "2024-12-31")
    store.get_row_count.return_value = 100
    return store


# --- 테스트 ---


@pytest.mark.asyncio
async def test_list_datasets_returns_empty_when_no_store():
    """store가 None이면 빈 응답을 반환한다."""
    result = await list_datasets(
        store=None, symbol=None, timeframe=None, data_type="ohlcv", offset=0, limit=50
    )
    assert result == {"items": [], "total": 0}


@pytest.mark.asyncio
async def test_list_datasets_pagination_limits_enrichment():
    """페이지네이션이 적용되어 해당 페이지 종목만 enrich한다."""
    syms = [f"00{i:04d}" for i in range(5)]
    store = _make_store({"1d": syms})

    result = await list_datasets(
        store=store,
        symbol=None,
        timeframe="1d",
        data_type="ohlcv",
        offset=0,
        limit=2,
    )

    assert result["total"] == 5
    assert len(result["items"]) == 2
    # get_date_range는 페이지 내 2건에 대해서만 호출
    assert store.get_date_range.call_count == 2


@pytest.mark.asyncio
async def test_list_datasets_row_count_and_file_size_are_zero():
    """목록 응답의 row_count, file_size는 항상 0이다."""
    store = _make_store({"1d": ["005930"]})

    result = await list_datasets(
        store=store,
        symbol=None,
        timeframe="1d",
        data_type="ohlcv",
        offset=0,
        limit=50,
    )

    item = result["items"][0]
    assert item["row_count"] == 0
    assert item["file_size"] == 0
    # get_row_count는 호출되지 않아야 한다
    store.get_row_count.assert_not_called()


@pytest.mark.asyncio
async def test_list_datasets_date_range_included():
    """목록 응답에 start_date, end_date가 포함된다."""
    store = _make_store({"1d": ["005930"]})

    result = await list_datasets(
        store=store,
        symbol=None,
        timeframe="1d",
        data_type="ohlcv",
        offset=0,
        limit=50,
    )

    item = result["items"][0]
    assert item["start_date"] == "2024-01-01"
    assert item["end_date"] == "2024-12-31"


@pytest.mark.asyncio
async def test_list_datasets_fundamental_type():
    """fundamental 데이터 타입 조회가 동작한다."""
    store = _make_store({"fundamental": ["005930"]})

    result = await list_datasets(
        store=store,
        symbol=None,
        timeframe=None,
        data_type="fundamental",
        offset=0,
        limit=50,
    )

    assert result["total"] == 1
    item = result["items"][0]
    assert item["data_type"] == "fundamental"
    assert item["id"] == "005930__fundamental"
    assert item["row_count"] == 0
    assert item["file_size"] == 0


@pytest.mark.asyncio
async def test_list_datasets_symbol_filter():
    """symbol 필터가 적용된다."""
    store = _make_store({"1d": ["005930", "000660", "035720"]})

    result = await list_datasets(
        store=store,
        symbol="005930",
        timeframe="1d",
        data_type="ohlcv",
        offset=0,
        limit=50,
    )

    assert result["total"] == 1
    assert result["items"][0]["symbol"] == "005930"


@pytest.mark.asyncio
async def test_list_datasets_offset_pagination():
    """offset 페이지네이션이 올바르게 동작한다."""
    syms = [f"SYM{i}" for i in range(10)]
    store = _make_store({"1d": syms})

    result = await list_datasets(
        store=store,
        symbol=None,
        timeframe="1d",
        data_type="ohlcv",
        offset=8,
        limit=5,
    )

    assert result["total"] == 10
    # offset=8, limit=5 -> 8,9 인덱스만 반환
    assert len(result["items"]) == 2


@pytest.mark.asyncio
async def test_list_datasets_date_range_exception_handled():
    """get_date_range에서 예외가 발생해도 None으로 처리된다."""
    store = _make_store({"1d": ["005930"]})
    store.get_date_range.side_effect = Exception("disk error")

    result = await list_datasets(
        store=store,
        symbol=None,
        timeframe="1d",
        data_type="ohlcv",
        offset=0,
        limit=50,
    )

    item = result["items"][0]
    assert item["start_date"] is None
    assert item["end_date"] is None


@pytest.mark.asyncio
async def test_list_datasets_no_resolve_path_called():
    """목록 API에서는 _resolve_path (file_size 계산)를 호출하지 않는다."""
    store = _make_store({"1d": ["005930"]})

    await list_datasets(
        store=store,
        symbol=None,
        timeframe="1d",
        data_type="ohlcv",
        offset=0,
        limit=50,
    )

    store._resolve_path.assert_not_called()
