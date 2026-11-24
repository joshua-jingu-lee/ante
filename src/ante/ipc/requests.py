from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, SecretStr
from pydantic_core import PydanticCustomError

from ante.core.account_id import is_invalid_account_id
from ante.core.time import InvalidIsoDateError, iso_to_kis_date

__all__ = [
    "AccountActivateRequest",
    "AccountId",
    "AccountSuspendRequest",
    "ApprovalApproveRequest",
    "ApprovalCancelInvalidRequest",
    "ApprovalCancelRequest",
    "ApprovalRejectRequest",
    "ApprovalReopenRequest",
    "ApprovalRequestRequest",
    "BotCreateRequest",
    "BotInfoRequest",
    "BotListRequest",
    "BotPositionsRequest",
    "BotRemoveRequest",
    "BotSignalKeyRequest",
    "BotSignalKeyRotateRequest",
    "BotStartRequest",
    "BotStatusRequest",
    "BotStopRequest",
    "BotUpdateFields",
    "BotUpdateRequest",
    "BrokerBalanceRequest",
    "BrokerOrderHistoryRequest",
    "BrokerPositionsRequest",
    "BrokerReconcileRequest",
    "BrokerStatusRequest",
    "ConfigSetRequest",
    "IPCRequest",
    "IsoDate",
    "MemberReactivateRequest",
    "MemberRegenerateRecoveryKeyRequest",
    "MemberRegisterRequest",
    "MemberResetPasswordRequest",
    "MemberRevokeRequest",
    "MemberRotateTokenRequest",
    "MemberSetEmojiRequest",
    "MemberSuspendRequest",
    "MemberUpdateScopesRequest",
    "RuleUpdateRequest",
    "SignalConnectRequest",
    "StrategySetStatusRequest",
    "SystemClearHaltRequest",
    "SystemHaltRequest",
    "TreasuryAllocateRequest",
    "TreasuryDeallocateRequest",
    "TreasurySetBalanceRequest",
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


def _valid_iso_date(value: str) -> str:
    try:
        iso_to_kis_date(value)
    except InvalidIsoDateError:
        raise PydanticCustomError("invalid_iso_date", "invalid iso date") from None
    return value


IsoDate = Annotated[str, AfterValidator(_valid_iso_date)]


class SystemHaltRequest(IPCRequest):
    reason: str = "IPC halt"


class SystemClearHaltRequest(IPCRequest):
    reason: str = "IPC clear_halt"


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
    scopes: list[str]


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


class ApprovalRequestRequest(IPCRequest):
    type: str
    title: str
    body: str = ""
    params: dict[str, Any] | None = None
    reference_id: str = ""
    expires_at: str = ""


class ApprovalApproveRequest(IPCRequest):
    id: str


class ApprovalRejectRequest(IPCRequest):
    id: str
    reason: str = ""


class ApprovalCancelRequest(IPCRequest):
    id: str


class ApprovalCancelInvalidRequest(IPCRequest):
    approval_id: str


class ApprovalReopenRequest(IPCRequest):
    id: str
    body: str | None = None
    params: dict[str, Any] | None = None


class BotCreateRequest(IPCRequest):
    strategy_id: str
    account_id: AccountId
    bot_id: str = ""
    name: str = ""
    interval_seconds: int = 60


class BotRemoveRequest(IPCRequest):
    bot_id: str


class BotSignalKeyRotateRequest(IPCRequest):
    bot_id: str


class BotStartRequest(IPCRequest):
    bot_id: str


class BotStopRequest(IPCRequest):
    bot_id: str


class BotUpdateFields(IPCRequest):
    name: str | None = None
    strategy_id: str | None = None
    interval_seconds: int | None = None
    budget: float | None = Field(default=None, gt=0)
    auto_restart: bool | None = None
    max_restart_attempts: int | None = None
    restart_cooldown_seconds: int | None = None
    step_timeout_seconds: int | None = None
    max_signals_per_step: int | None = None
    account_id: str | None = None


class BotUpdateRequest(IPCRequest):
    bot_id: str
    updates: BotUpdateFields = Field(default_factory=BotUpdateFields)


class BotStatusRequest(IPCRequest):
    bot_id: str


class BotListRequest(IPCRequest):
    account_id: AccountId | None = None


class BotInfoRequest(IPCRequest):
    bot_id: str


class BotPositionsRequest(IPCRequest):
    bot_id: str


class BotSignalKeyRequest(IPCRequest):
    bot_id: str


class SignalConnectRequest(IPCRequest):
    key: SecretStr


class TreasuryAllocateRequest(IPCRequest):
    account_id: AccountId
    bot_id: str
    amount: float


class TreasuryDeallocateRequest(IPCRequest):
    account_id: AccountId
    bot_id: str
    amount: float


class TreasurySetBalanceRequest(IPCRequest):
    account_id: AccountId
    balance: float


class RuleUpdateRequest(IPCRequest):
    account_id: AccountId
    rule_type: str
    enabled: bool | None = None
    params: dict[str, Any] = {}


class ConfigSetRequest(IPCRequest):
    key: str
    value: str
    category: str = "user"


class BrokerStatusRequest(IPCRequest):
    account_id: AccountId


class BrokerBalanceRequest(IPCRequest):
    account_id: AccountId


class BrokerPositionsRequest(IPCRequest):
    account_id: AccountId


class BrokerOrderHistoryRequest(IPCRequest):
    account_id: AccountId
    from_date: IsoDate | None = None
    to_date: IsoDate | None = None


class BrokerReconcileRequest(IPCRequest):
    account_id: AccountId
    fix: bool = False
