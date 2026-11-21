from __future__ import annotations

from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict
from pydantic_core import PydanticCustomError

from ante.core.account_id import is_invalid_account_id

__all__ = [
    "AccountActivateRequest",
    "AccountId",
    "AccountSuspendRequest",
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


def _valid_account_id(value: str) -> str:
    if is_invalid_account_id(value):
        raise PydanticCustomError("invalid_account_id", "invalid account_id")
    return value


AccountId = Annotated[str, AfterValidator(_valid_account_id)]


class SystemHaltRequest(IPCRequest):
    reason: str = "IPC halt"


class SystemClearHaltRequest(IPCRequest):
    pass


class StrategySetStatusRequest(IPCRequest):
    strategy_id: str
    status: Literal["registered", "adopted", "archived"]


class AccountSuspendRequest(IPCRequest):
    account_id: AccountId
    reason: str = "IPC suspend"


class AccountActivateRequest(IPCRequest):
    account_id: AccountId
