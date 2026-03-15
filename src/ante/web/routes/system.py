"""시스템 상태 API."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter()


class KillSwitchRequest(BaseModel):
    """킬 스위치 제어 요청."""

    action: str  # "halt" | "activate"
    reason: str = ""


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


@router.post("/kill-switch")
async def kill_switch(request: Request, body: KillSwitchRequest) -> dict:
    """킬 스위치 제어 (halt/activate)."""
    from datetime import UTC, datetime

    from ante.config.system_state import TradingState

    system_state = getattr(request.app.state, "system_state", None)
    if system_state is None:
        raise HTTPException(status_code=503, detail="System state not available")

    if body.action == "halt":
        target = TradingState.HALTED
    elif body.action == "activate":
        target = TradingState.ACTIVE
    else:
        raise HTTPException(
            status_code=400,
            detail="action은 'halt' 또는 'activate'만 허용됩니다",
        )

    await system_state.set_state(target, reason=body.reason, changed_by="dashboard")
    return {
        "status": system_state.trading_state.value,
        "changed_at": datetime.now(UTC).isoformat(),
    }
