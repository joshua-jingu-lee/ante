"""list_datasets 핸들러 단위 테스트.

이벤트 루프 블로킹 해소 (#949) 관련 변경사항을 검증한다:
- 종목 목록 수집 후 페이지네이션 -> 해당 페이지만 date_range 계산
- row_count, file_size는 목록 응답에서 항상 0
- 동기 I/O가 run_in_executor로 래핑되어 이벤트 루프를 블로킹하지 않음
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from ante.data.schemas import TIMEFRAMES
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
        _caller_id="test-caller",
        store=None,
        symbol=None,
        timeframe=None,
        data_type="ohlcv",
        offset=0,
        limit=50,
    )
    assert result == {"items": [], "total": 0}


@pytest.mark.asyncio
async def test_list_datasets_store_none_invalid_timeframe_still_400():
    """store 미주입(None) 환경에서도 invalid timeframe은 400으로 거부된다.

    Codex 브랜치 리뷰 [P2] blocking 회귀 고정: timeframe 검증이
    store-None 조기 반환 뒤에 있으면 store 미주입 앱/테스트에서
    invalid timeframe이 200 empty로 새어 나간다. 검증은 store 유무와
    무관하게 API 경계에서 일어나야 한다.
    """
    with pytest.raises(HTTPException) as exc_info:
        await list_datasets(
            _caller_id="test-caller",
            store=None,
            symbol=None,
            timeframe="oracle-invalid-timeframe",
            data_type="ohlcv",
            offset=0,
            limit=50,
        )

    assert exc_info.value.status_code == 400
    detail = exc_info.value.detail
    assert "oracle-invalid-timeframe" in detail
    for tf in TIMEFRAMES:
        assert tf in detail


@pytest.mark.asyncio
async def test_list_datasets_store_none_valid_timeframe_still_empty():
    """store=None + valid timeframe은 기존대로 200 empty (동작 회귀)."""
    result = await list_datasets(
        _caller_id="test-caller",
        store=None,
        symbol=None,
        timeframe="1d",
        data_type="ohlcv",
        offset=0,
        limit=50,
    )
    assert result == {"items": [], "total": 0}


@pytest.mark.asyncio
async def test_list_datasets_pagination_limits_enrichment():
    """페이지네이션이 적용되어 해당 페이지 종목만 enrich한다."""
    syms = [f"00{i:04d}" for i in range(5)]
    store = _make_store({"1d": syms})

    result = await list_datasets(
        _caller_id="test-caller",
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
        _caller_id="test-caller",
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
        _caller_id="test-caller",
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
        _caller_id="test-caller",
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
        _caller_id="test-caller",
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
        _caller_id="test-caller",
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
        _caller_id="test-caller",
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
        _caller_id="test-caller",
        store=store,
        symbol=None,
        timeframe="1d",
        data_type="ohlcv",
        offset=0,
        limit=50,
    )

    store._resolve_path.assert_not_called()


@pytest.mark.asyncio
async def test_list_datasets_no_data_type_returns_all():
    """data_type 미지정 시 ohlcv + fundamental 모두 반환한다."""
    store = _make_store({"1d": ["005930"], "fundamental": ["005930", "000660"]})

    result = await list_datasets(
        _caller_id="test-caller",
        store=store,
        symbol=None,
        timeframe="1d",
        data_type=None,
        offset=0,
        limit=50,
    )

    types = {item["data_type"] for item in result["items"]}
    assert types == {"ohlcv", "fundamental"}
    # fundamental 2건 + ohlcv 1건
    assert result["total"] == 3


@pytest.mark.asyncio
async def test_list_datasets_data_type_ohlcv():
    """data_type=ohlcv 지정 시 ohlcv만 반환한다."""
    store = _make_store({"1d": ["005930"], "fundamental": ["005930"]})

    result = await list_datasets(
        _caller_id="test-caller",
        store=store,
        symbol=None,
        timeframe="1d",
        data_type="ohlcv",
        offset=0,
        limit=50,
    )

    types = {item["data_type"] for item in result["items"]}
    assert types == {"ohlcv"}
    assert result["total"] == 1


@pytest.mark.asyncio
async def test_list_datasets_data_type_fundamental():
    """data_type=fundamental 지정 시 fundamental만 반환한다."""
    store = _make_store({"1d": ["005930"], "fundamental": ["005930"]})

    result = await list_datasets(
        _caller_id="test-caller",
        store=store,
        symbol=None,
        timeframe=None,
        data_type="fundamental",
        offset=0,
        limit=50,
    )

    types = {item["data_type"] for item in result["items"]}
    assert types == {"fundamental"}
    assert result["total"] == 1


# --- timeframe vocabulary 검증 (#1594) ---


@pytest.mark.asyncio
async def test_list_datasets_invalid_timeframe_rejected_400():
    """oracle 류 invalid timeframe은 200 empty가 아니라 400으로 거부된다.

    수정 전 RED: store.list_symbols(invalid_tf) -> [] -> 200 empty.
    수정 후 GREEN: API 경계에서 400 거부.
    """
    store = _make_store({"1d": ["005930"]})

    with pytest.raises(HTTPException) as exc_info:
        await list_datasets(
            _caller_id="test-caller",
            store=store,
            symbol=None,
            timeframe="oracle-invalid-timeframe",
            data_type="ohlcv",
            offset=0,
            limit=50,
        )

    assert exc_info.value.status_code == 400
    detail = exc_info.value.detail
    assert "oracle-invalid-timeframe" in detail
    # 허용 목록(TIMEFRAMES 전체)이 detail에 포함되어야 한다
    for tf in TIMEFRAMES:
        assert tf in detail
    # invalid timeframe이면 store 조회 자체가 일어나지 않아야 한다
    store.list_symbols.assert_not_called()


@pytest.mark.asyncio
async def test_list_datasets_invalid_timeframe_short_token_rejected_400():
    """짧은 토큰('invalid')도 동일하게 400으로 거부된다."""
    store = _make_store({"1d": ["005930"]})

    with pytest.raises(HTTPException) as exc_info:
        await list_datasets(
            _caller_id="test-caller",
            store=store,
            symbol=None,
            timeframe="invalid",
            data_type="ohlcv",
            offset=0,
            limit=50,
        )

    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
@pytest.mark.parametrize("tf", ["1m", "5m", "15m", "1h", "1d"])
async def test_list_datasets_valid_timeframe_ok_regression(tf):
    """TIMEFRAMES vocabulary 내 모든 값은 200(정상 조회)로 회귀 보장."""
    store = _make_store({tf: ["005930"]})

    result = await list_datasets(
        _caller_id="test-caller",
        store=store,
        symbol=None,
        timeframe=tf,
        data_type="ohlcv",
        offset=0,
        limit=50,
    )

    assert result["total"] == 1
    assert result["items"][0]["timeframe"] == tf


@pytest.mark.asyncio
async def test_list_datasets_no_timeframe_returns_all_regression():
    """timeframe 미지정은 기존대로 TIMEFRAMES 전체 조회 (검증 통과)."""
    store = _make_store({"1d": ["005930"], "1h": ["000660"]})

    result = await list_datasets(
        _caller_id="test-caller",
        store=store,
        symbol=None,
        timeframe=None,
        data_type="ohlcv",
        offset=0,
        limit=50,
    )

    assert result["total"] == 2


@pytest.mark.asyncio
async def test_list_datasets_fundamental_invalid_timeframe_still_rejected():
    """data_type=fundamental 이어도 invalid timeframe 파라미터는 400 거부.

    검증은 API 경계(데이터 유형 분기 이전)에서 일어나므로
    fundamental 조회라도 invalid timeframe은 거부된다.
    """
    store = _make_store({"fundamental": ["005930"]})

    with pytest.raises(HTTPException) as exc_info:
        await list_datasets(
            _caller_id="test-caller",
            store=store,
            symbol=None,
            timeframe="oracle-invalid-timeframe",
            data_type="fundamental",
            offset=0,
            limit=50,
        )

    assert exc_info.value.status_code == 400


# --- 범위 고정 회귀: symbol·data_type 은 본 PR 범위 외 (HTTP 경계) ---


@pytest.fixture
def _http_client():
    """FastAPI Request 레이어가 필요한 회귀(422 Literal, symbol 200 empty)용."""
    pytest.importorskip("httpx", reason="httpx required for web API tests")

    import tempfile
    from pathlib import Path

    from ante.data.store import ParquetStore
    from ante.web.app import create_app
    from tests.unit.conftest import make_authed_client, make_master_member_service

    with tempfile.TemporaryDirectory() as tmp:
        store = ParquetStore(base_path=Path(tmp) / "data")
        app = create_app(data_store=store, member_service=make_master_member_service())
        yield make_authed_client(app)


def test_list_datasets_invalid_symbol_still_200_empty_scope_lock(_http_client):
    """범위 고정: invalid symbol은 본 PR에서 200 empty 유지 (후속 후보 0).

    symbol vocabulary 거부는 exchange-aware symbol SSOT 후속 작업이며,
    본 PR(#1594)은 timeframe만 거부한다. invalid symbol이 400/422로
    바뀌면 범위 침범이므로 이 회귀가 막는다.
    """
    resp = _http_client.get("/api/data/datasets", params={"symbol": "ABCDEF"})
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"items": [], "total": 0}


def test_list_datasets_bogus_data_type_still_422_regression(_http_client):
    """data_type enum 외 값은 기존 Literal 동작대로 422 (미변경 회귀)."""
    resp = _http_client.get("/api/data/datasets", params={"data_type": "bogus"})
    assert resp.status_code == 422


def test_list_datasets_invalid_timeframe_http_400(_http_client):
    """HTTP 경계에서도 invalid timeframe은 400 + detail(허용 목록)."""
    resp = _http_client.get(
        "/api/data/datasets",
        params={"data_type": "ohlcv", "timeframe": "oracle-invalid-timeframe"},
    )
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert "oracle-invalid-timeframe" in detail
    for tf in TIMEFRAMES:
        assert tf in detail
