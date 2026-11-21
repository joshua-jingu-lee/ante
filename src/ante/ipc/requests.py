from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

__all__ = [
    "IPCRequest",
    "StrategySetStatusRequest",
    "SystemClearHaltRequest",
    "SystemHaltRequest",
]


class IPCRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        allow_inf_nan=False,
        hide_input_in_errors=True,
        frozen=True,
    )


class SystemHaltRequest(IPCRequest):
    reason: str = "IPC halt"


class SystemClearHaltRequest(IPCRequest):
    pass


class StrategySetStatusRequest(IPCRequest):
    strategy_id: str
    status: Literal["registered", "adopted", "archived"]
