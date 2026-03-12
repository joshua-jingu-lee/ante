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
