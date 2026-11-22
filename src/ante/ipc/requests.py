from __future__ import annotations

from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, SecretStr
from pydantic_core import PydanticCustomError

from ante.core.account_id import is_invalid_account_id

__all__ = [
    "AccountActivateRequest",
    "AccountId",
    "AccountSuspendRequest",
    "IPCRequest",
    "MemberReactivateRequest",
    "MemberRegenerateRecoveryKeyRequest",
    "MemberRegisterRequest",
    "MemberResetPasswordRequest",
    "MemberRevokeRequest",
    "MemberRotateTokenRequest",
    "MemberSetEmojiRequest",
    "MemberSuspendRequest",
    "MemberUpdateScopesRequest",
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


class MemberUpdateScopesRequest(IPCRequest):
    member_id: str
    scopes: list[str] = []


class MemberRegisterRequest(IPCRequest):
    member_id: str
    member_type: str
    org: str = "default"
    name: str = ""
    scopes: list[str] = []


class MemberSetEmojiRequest(IPCRequest):
    member_id: str
    emoji: str


class MemberSuspendRequest(IPCRequest):
    member_id: str


class MemberReactivateRequest(IPCRequest):
    member_id: str


class MemberRevokeRequest(IPCRequest):
    member_id: str


class MemberRotateTokenRequest(IPCRequest):
    member_id: str


class MemberResetPasswordRequest(IPCRequest):
    recovery_key: SecretStr
    new_password: SecretStr


class MemberRegenerateRecoveryKeyRequest(IPCRequest):
    password: SecretStr
