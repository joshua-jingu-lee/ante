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
async def get_system_status(request: Request) -> dict:
    """시스템 상태 조회."""
    result: dict = {
        "status": "running",
        "version": "0.1.0",
    }

    system_state = getattr(request.app.state, "system_state", None)
    if system_state is not None:
        result["trading_status"] = system_state.trading_state.value.upper()

        # HALTED 상태이면 최근 halt 이력에서 시각·사유를 가져옴
        if system_state.trading_state.value == "halted":
            halt_info = await _get_last_halt_info(system_state)
            if halt_info:
                result["halt_time"] = halt_info.get("created_at")
                result["halt_reason"] = halt_info.get("reason", "")

    return result


async def _get_last_halt_info(system_state: object) -> dict | None:
    """system_state_history에서 마지막 HALTED 전환 정보를 가져온다."""
    db = getattr(system_state, "_db", None)
    if db is None:
        return None
    row = await db.fetch_one(
        "SELECT reason, changed_by, created_at FROM system_state_history"
        " WHERE new_state = 'halted'"
        " ORDER BY id DESC LIMIT 1"
    )
    return dict(row) if row else None


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
