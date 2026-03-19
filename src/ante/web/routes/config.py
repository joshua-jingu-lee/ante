"""동적 설정 API."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ante.web.deps import get_dynamic_config
from ante.web.schemas import ConfigListResponse, ConfigUpdateResponse

router = APIRouter()


class ConfigUpdateRequest(BaseModel):
    """설정 값 변경 요청."""

    value: Any
    category: str = ""


@router.get(
    "",
    response_model=ConfigListResponse,
    responses={503: {"description": "Config service not available"}},
)
async def list_configs(
    config_service: Annotated[Any, Depends(get_dynamic_config)],
) -> dict:
    """동적 설정 전체 조회."""
    configs = await config_service.get_all()
    return {"configs": configs}


@router.put(
    "/{key:path}",
    response_model=ConfigUpdateResponse,
    responses={
        404: {"description": "Config key not found"},
        503: {"description": "Config service not available"},
    },
)
async def update_config(
    key: str,
    body: ConfigUpdateRequest,
    config_service: Annotated[Any, Depends(get_dynamic_config)],
) -> dict:
    """동적 설정 값 변경."""
    if not await config_service.exists(key):
        raise HTTPException(status_code=404, detail=f"설정을 찾을 수 없습니다: {key}")

    old_value = await config_service.get(key)

    # category: 요청에 없으면 key에서 추출 (예: "risk.max_mdd" -> "risk")
    category = body.category or key.split(".")[0]

    await config_service.set(key, body.value, category=category, changed_by="dashboard")

    return {"key": key, "old_value": old_value, "new_value": body.value}
