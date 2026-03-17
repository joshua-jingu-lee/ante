"""데이터 관리 API."""

from __future__ import annotations

import shutil

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/datasets")
async def list_datasets(request: Request) -> dict:
    """보유 데이터셋 목록."""
    store = getattr(request.app.state, "data_store", None)
    if store is None:
        return {"datasets": []}

    from ante.data.schemas import TIMEFRAMES

    datasets = []
    for tf in TIMEFRAMES:
        symbols = store.list_symbols(tf)
        for symbol in symbols:
            date_range = store.get_date_range(symbol, tf)
            datasets.append(
                {
                    "symbol": symbol,
                    "timeframe": tf,
                    "start": date_range[0] if date_range else None,
                    "end": date_range[1] if date_range else None,
                }
            )
    return {"datasets": datasets}


@router.get("/schema")
async def get_data_schema(request: Request) -> dict:
    """OHLCV 데이터 스키마."""
    from ante.data.schemas import OHLCV_SCHEMA

    return {k: str(v) for k, v in OHLCV_SCHEMA.items()}


@router.get("/storage")
async def get_storage_summary(request: Request) -> dict:
    """저장 용량 현황."""
    store = getattr(request.app.state, "data_store", None)
    if store is None:
        return {"total_bytes": 0, "total_mb": 0.0, "by_timeframe": {}}
    usage = store.get_storage_usage()
    total = sum(usage.values())
    return {
        "total_bytes": total,
        "total_mb": round(total / 1024 / 1024, 1),
        "by_timeframe": {
            tf: round(size / 1024 / 1024, 1) for tf, size in usage.items()
        },
    }


@router.delete("/datasets/{dataset_id}", status_code=204)
async def delete_dataset(request: Request, dataset_id: str) -> None:
    """데이터셋 삭제.

    dataset_id 형식: "{symbol}__{timeframe}" (예: "005930__1d")
    """
    from fastapi import HTTPException

    store = getattr(request.app.state, "data_store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="Data store not available")

    parts = dataset_id.split("__", 1)
    if len(parts) != 2:
        raise HTTPException(
            status_code=400,
            detail="dataset_id는 '{symbol}__{timeframe}' 형식이어야 합니다",
        )

    symbol, timeframe = parts
    path = store.base_path / "ohlcv" / timeframe / symbol
    if not path.exists():
        raise HTTPException(status_code=404, detail="데이터셋을 찾을 수 없습니다")
    shutil.rmtree(path)
