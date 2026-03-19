"""동적 설정 API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ante.web.schemas import ConfigListResponse, ConfigUpdateResponse

router = APIRouter()


class ConfigUpdateRequest(BaseModel):
    """설정 값 변경 요청."""

    value: Any
    category: str = ""


@router.get("", response_model=ConfigListResponse)
async def list_configs(request: Request) -> dict:
    """동적 설정 전체 조회."""
    config_service = getattr(request.app.state, "dynamic_config", None)
    if config_service is None:
        raise HTTPException(status_code=503, detail="Config service not available")

    configs = await config_service.get_all()
    return {"configs": configs}


@router.put("/{key:path}", response_model=ConfigUpdateResponse)
async def update_config(request: Request, key: str, body: ConfigUpdateRequest) -> dict:
    """동적 설정 값 변경."""
    config_service = getattr(request.app.state, "dynamic_config", None)
    if config_service is None:
        raise HTTPException(status_code=503, detail="Config service not available")

    if not await config_service.exists(key):
        raise HTTPException(status_code=404, detail=f"설정을 찾을 수 없습니다: {key}")

    old_value = await config_service.get(key)

    # category: 요청에 없으면 key에서 추출 (예: "risk.max_mdd" -> "risk")
    category = body.category or key.split(".")[0]

    await config_service.set(key, body.value, category=category, changed_by="dashboard")

    return {"key": key, "old_value": old_value, "new_value": body.value}
