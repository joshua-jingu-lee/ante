from __future__ import annotations

from pydantic import BaseModel, ConfigDict

__all__ = ["IPCRequest"]


class IPCRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        allow_inf_nan=False,
        hide_input_in_errors=True,
        frozen=True,
    )
