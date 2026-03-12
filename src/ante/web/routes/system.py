"""시스템 상태 API."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/status")
async def get_system_status() -> dict:
    """시스템 상태 조회."""
    return {
        "status": "running",
        "version": "0.1.0",
    }


@router.get("/health")
async def health_check() -> dict:
    """헬스체크."""
    return {"ok": True}
