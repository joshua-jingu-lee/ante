"""데이터 관리 API."""

from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/datasets")
async def list_datasets(request: Request) -> dict:
    """보유 데이터셋 목록."""
    catalog = getattr(request.app.state, "data_catalog", None)
    if catalog is None:
        return {"datasets": []}
    return {"datasets": catalog.list_datasets()}


@router.get("/schema")
async def get_data_schema(request: Request) -> dict:
    """OHLCV 데이터 스키마."""
    catalog = getattr(request.app.state, "data_catalog", None)
    if catalog is None:
        from ante.data.schemas import OHLCV_SCHEMA

        return {k: str(v) for k, v in OHLCV_SCHEMA.items()}
    return catalog.get_schema()


@router.get("/storage")
async def get_storage_summary(request: Request) -> dict:
    """저장 용량 현황."""
    catalog = getattr(request.app.state, "data_catalog", None)
    if catalog is None:
        return {"total_bytes": 0, "total_mb": 0.0, "by_timeframe": {}}
    return catalog.get_storage_summary()


@router.delete("/datasets/{dataset_id}", status_code=204)
async def delete_dataset(request: Request, dataset_id: str) -> None:
    """데이터셋 삭제.

    dataset_id 형식: "{symbol}__{timeframe}" (예: "005930__1d")
    """
    from fastapi import HTTPException

    catalog = getattr(request.app.state, "data_catalog", None)
    if catalog is None:
        raise HTTPException(status_code=503, detail="Data catalog not available")

    parts = dataset_id.split("__", 1)
    if len(parts) != 2:
        raise HTTPException(
            status_code=400,
            detail="dataset_id는 '{symbol}__{timeframe}' 형식이어야 합니다",
        )

    symbol, timeframe = parts
    deleted = catalog.delete_dataset(symbol, timeframe)
    if not deleted:
        raise HTTPException(status_code=404, detail="데이터셋을 찾을 수 없습니다")
