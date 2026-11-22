"""CLI command contract registry."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Literal

from ante.contracts.vocab import AuthMode, ContractKind, EnvelopeForm

__all__ = [
    "ACCOUNT_CONTRACTS",
    "APPROVAL_CONTRACTS",
    "AUDIT_CONTRACTS",
    "BACKTEST_CONTRACTS",
    "BOT_CONTRACTS",
    "BROKER_CONTRACTS",
    "CLI_COMMAND_REGISTRY",
    "CONFIG_CONTRACTS",
    "DATA_CONTRACTS",
    "INSTRUMENT_CONTRACTS",
    "MEMBER_CONTRACTS",
    "REPORT_CONTRACTS",
    "RULE_CONTRACTS",
    "SIGNAL_CONTRACTS",
    "STRATEGY_CONTRACTS",
    "SYSTEM_CONTRACTS",
    "TRADE_CONTRACTS",
    "TREASURY_CONTRACTS",
    "AuthContract",
    "CliCommandContract",
    "ExecutionClass",
    "OutputContract",
    "all_contracts",
    "get_contract",
]


ExecutionClass = Literal[
    "bootstrap",
    "offline",
    "runtime_ipc",
    "cold_path",
    "long_running",
]
"""CLI command 의 실행 모드 vocabulary.
"""


@dataclass(frozen=True)
class AuthContract:
    """CLI command 의 인증 요구 계약.

    Attributes:
        scopes: ``mode == "scoped"`` 일 때 요구되는 scope 집합.
            **복수 scope** 를 요구할 수 있도록 ``frozenset[str]``
            이다 (단일 ``str`` 또는 ``str | None``
            아님). ``mode`` 가 ``"scoped"`` 가 아니면 빈 frozenset 이
            default 다.
    """

    mode: AuthMode
    scopes: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class OutputContract:
    """CLI command 의 출력 계약.

    Attributes:
        data_key: standard envelope 의 ``data`` 슬롯 안에서 사용할 key
            이름 (예: ``"account"``, ``"bots"``). ``raw`` / ``stream``
            계열 또는 단일 slot 이 필요 없는 경우 ``None``.
    """

    kind: ContractKind
    data_key: str | None = None
    envelope: EnvelopeForm = "standard"


@dataclass(frozen=True)
class CliCommandContract:
    """단일 CLI leaf command 의 전체 계약.

    Attributes:
        path: ``ante`` prefix 를 제외한 root-to-leaf segment 튜플
            (예: ``("account", "create")``, ``("bot", "start")``).
            :func:`tests.unit.contracts.helpers.iter_click_leaf_commands`
            가 반환하는 :class:`~tests.unit.contracts.helpers.CliLeafCommand.path`
            와 형태가 일치한다.
    """

    path: tuple[str, ...]
    auth: AuthContract
    output: OutputContract
    execution: ExecutionClass
    ipc_command: str | None = None


ACCOUNT_CONTRACTS: tuple[CliCommandContract, ...] = (
    CliCommandContract(
        path=("account", "list"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"account:read"})),
        output=OutputContract(kind="raw", envelope="standard"),
        execution="offline",
    ),
    CliCommandContract(
        path=("account", "info"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"account:read"})),
        output=OutputContract(kind="raw", envelope="standard"),
        execution="offline",
    ),
    CliCommandContract(
        path=("account", "credentials"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"account:read"})),
        output=OutputContract(kind="raw", envelope="standard"),
        execution="offline",
    ),
    CliCommandContract(
        path=("account", "create"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"account:write"})),
        output=OutputContract(kind="operation", envelope="standard"),
        execution="cold_path",
    ),
    CliCommandContract(
        path=("account", "set-credentials"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"account:write"})),
        output=OutputContract(kind="raw", envelope="standard"),
        execution="cold_path",
    ),
    CliCommandContract(
        path=("account", "delete"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"account:write"})),
        output=OutputContract(kind="operation", envelope="standard"),
        execution="cold_path",
    ),
    CliCommandContract(
        path=("account", "repair-timezone"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"account:write"})),
        output=OutputContract(kind="operation", envelope="standard"),
        execution="cold_path",
    ),
    CliCommandContract(
        path=("account", "suspend"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"account:write"})),
        output=OutputContract(kind="operation", envelope="standard"),
        execution="runtime_ipc",
        ipc_command="account.suspend",
    ),
    CliCommandContract(
        path=("account", "activate"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"account:write"})),
        output=OutputContract(kind="operation", envelope="standard"),
        execution="runtime_ipc",
        ipc_command="account.activate",
    ),
)
"""Account domain 9 leaf 의 contract tuple.
"""


MEMBER_CONTRACTS: tuple[CliCommandContract, ...] = (
    CliCommandContract(
        path=("member", "list"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"member:read"})),
        output=OutputContract(kind="raw", envelope="standard"),
        execution="offline",
    ),
    CliCommandContract(
        path=("member", "info"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"member:read"})),
        output=OutputContract(kind="raw", envelope="standard"),
        execution="offline",
    ),
    CliCommandContract(
        path=("member", "list-invalid-roles"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"member:read"})),
        output=OutputContract(kind="raw", envelope="standard"),
        execution="offline",
    ),
    CliCommandContract(
        path=("member", "register"),
        auth=AuthContract(mode="master", scopes=frozenset()),
        output=OutputContract(kind="raw", envelope="standard"),
        execution="runtime_ipc",
        ipc_command="member.register",
    ),
    CliCommandContract(
        path=("member", "set-emoji"),
        auth=AuthContract(mode="master", scopes=frozenset()),
        output=OutputContract(kind="operation", envelope="standard"),
        execution="runtime_ipc",
        ipc_command="member.set_emoji",
    ),
    CliCommandContract(
        path=("member", "update-scopes"),
        auth=AuthContract(mode="master", scopes=frozenset()),
        output=OutputContract(kind="raw", envelope="standard"),
        execution="runtime_ipc",
        ipc_command="member.update_scopes",
    ),
    CliCommandContract(
        path=("member", "suspend"),
        auth=AuthContract(mode="master", scopes=frozenset()),
        output=OutputContract(kind="operation", envelope="standard"),
        execution="runtime_ipc",
        ipc_command="member.suspend",
    ),
    CliCommandContract(
        path=("member", "reactivate"),
        auth=AuthContract(mode="master", scopes=frozenset()),
        output=OutputContract(kind="operation", envelope="standard"),
        execution="runtime_ipc",
        ipc_command="member.reactivate",
    ),
    CliCommandContract(
        path=("member", "revoke"),
        auth=AuthContract(mode="master", scopes=frozenset()),
        output=OutputContract(kind="operation", envelope="standard"),
        execution="runtime_ipc",
        ipc_command="member.revoke",
    ),
    CliCommandContract(
        path=("member", "rotate-token"),
        auth=AuthContract(mode="master", scopes=frozenset()),
        output=OutputContract(kind="raw", envelope="standard"),
        execution="runtime_ipc",
        ipc_command="member.rotate_token",
    ),
    CliCommandContract(
        path=("member", "reset-password"),
        auth=AuthContract(mode="public", scopes=frozenset()),
        output=OutputContract(kind="operation", envelope="standard"),
        execution="runtime_ipc",
        ipc_command="member.reset_password",
    ),
    CliCommandContract(
        path=("member", "regenerate-recovery-key"),
        auth=AuthContract(mode="public", scopes=frozenset()),
        output=OutputContract(kind="raw", envelope="standard"),
        execution="runtime_ipc",
        ipc_command="member.regenerate_recovery_key",
    ),
)
"""Member domain 12 leaf 의 contract tuple.
"""


BOT_CONTRACTS: tuple[CliCommandContract, ...] = (
    CliCommandContract(
        path=("bot", "list"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"bot:read"})),
        output=OutputContract(kind="raw", envelope="standard"),
        execution="runtime_ipc",
        ipc_command="bot.list",
    ),
    CliCommandContract(
        path=("bot", "info"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"bot:read"})),
        output=OutputContract(kind="raw", envelope="standard"),
        execution="runtime_ipc",
        ipc_command="bot.info",
    ),
    CliCommandContract(
        path=("bot", "create"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"bot:admin"})),
        output=OutputContract(kind="operation", envelope="standard"),
        execution="runtime_ipc",
        ipc_command="bot.create",
    ),
    CliCommandContract(
        path=("bot", "remove"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"bot:admin"})),
        output=OutputContract(kind="operation", envelope="standard"),
        execution="runtime_ipc",
        ipc_command="bot.remove",
    ),
    CliCommandContract(
        path=("bot", "signal-key"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"bot:admin"})),
        output=OutputContract(kind="raw", envelope="standard"),
        execution="runtime_ipc",
        ipc_command="bot.signal_key",
    ),
    CliCommandContract(
        path=("bot", "positions"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"bot:read"})),
        output=OutputContract(kind="raw", envelope="standard"),
        execution="runtime_ipc",
        ipc_command="bot.positions",
    ),
    CliCommandContract(
        path=("bot", "update"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"bot:admin"})),
        output=OutputContract(kind="raw", envelope="standard"),
        execution="runtime_ipc",
        ipc_command="bot.update",
    ),
    CliCommandContract(
        path=("bot", "logs"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"bot:read"})),
        output=OutputContract(kind="raw", envelope="standard"),
        execution="offline",
    ),
    CliCommandContract(
        path=("bot", "start"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"bot:admin"})),
        output=OutputContract(kind="raw", envelope="standard"),
        execution="runtime_ipc",
        ipc_command="bot.start",
    ),
    CliCommandContract(
        path=("bot", "stop"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"bot:admin"})),
        output=OutputContract(kind="raw", envelope="standard"),
        execution="runtime_ipc",
        ipc_command="bot.stop",
    ),
    CliCommandContract(
        path=("bot", "status"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"bot:read"})),
        output=OutputContract(kind="raw", envelope="standard"),
        execution="runtime_ipc",
        ipc_command="bot.status",
    ),
)
"""Bot domain 11 leaf 의 contract tuple.
"""


APPROVAL_CONTRACTS: tuple[CliCommandContract, ...] = (
    CliCommandContract(
        path=("approval", "list"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"approval:read"})),
        output=OutputContract(kind="raw", envelope="standard", data_key="approvals"),
        execution="offline",
    ),
    CliCommandContract(
        path=("approval", "info"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"approval:read"})),
        output=OutputContract(kind="raw", envelope="standard"),
        execution="offline",
    ),
    CliCommandContract(
        path=("approval", "review"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"approval:read"})),
        output=OutputContract(kind="operation", envelope="standard"),
        execution="offline",
    ),
    CliCommandContract(
        path=("approval", "audit-types"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"approval:read"})),
        output=OutputContract(kind="raw", envelope="standard", data_key="approvals"),
        execution="offline",
    ),
    CliCommandContract(
        path=("approval", "request"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"approval:write"})),
        output=OutputContract(kind="operation", envelope="standard"),
        execution="runtime_ipc",
        ipc_command="approval.request",
    ),
    CliCommandContract(
        path=("approval", "reopen"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"approval:write"})),
        output=OutputContract(kind="operation", envelope="standard"),
        execution="runtime_ipc",
        ipc_command="approval.reopen",
    ),
    CliCommandContract(
        path=("approval", "cancel"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"approval:write"})),
        output=OutputContract(kind="operation", envelope="standard"),
        execution="runtime_ipc",
        ipc_command="approval.cancel",
    ),
    CliCommandContract(
        path=("approval", "approve"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"approval:admin"})),
        output=OutputContract(kind="operation", envelope="standard"),
        execution="runtime_ipc",
        ipc_command="approval.approve",
    ),
    CliCommandContract(
        path=("approval", "reject"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"approval:admin"})),
        output=OutputContract(kind="operation", envelope="standard"),
        execution="runtime_ipc",
        ipc_command="approval.reject",
    ),
    CliCommandContract(
        path=("approval", "cancel-invalid"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"approval:admin"})),
        output=OutputContract(kind="operation", envelope="standard"),
        execution="runtime_ipc",
        ipc_command="approval.cancel_invalid",
    ),
)
"""Approval domain 10 leaf 의 contract tuple.
"""


TREASURY_CONTRACTS: tuple[CliCommandContract, ...] = (
    CliCommandContract(
        path=("treasury", "status"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"treasury:read"})),
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="offline",
    ),
    CliCommandContract(
        path=("treasury", "transactions"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"treasury:read"})),
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="offline",
    ),
    CliCommandContract(
        path=("treasury", "budgets"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"treasury:read"})),
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="offline",
    ),
    CliCommandContract(
        path=("treasury", "set-balance"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"treasury:admin"})),
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="runtime_ipc",
        ipc_command="treasury.set_balance",
    ),
    CliCommandContract(
        path=("treasury", "allocate"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"treasury:admin"})),
        output=OutputContract(kind="operation", envelope="standard"),
        execution="runtime_ipc",
        ipc_command="treasury.allocate",
    ),
    CliCommandContract(
        path=("treasury", "deallocate"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"treasury:admin"})),
        output=OutputContract(kind="operation", envelope="standard"),
        execution="runtime_ipc",
        ipc_command="treasury.deallocate",
    ),
    CliCommandContract(
        path=("treasury", "snapshot"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"treasury:read"})),
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="offline",
    ),
    CliCommandContract(
        path=("treasury", "portfolio", "value"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"treasury:read"})),
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="offline",
    ),
    CliCommandContract(
        path=("treasury", "portfolio", "history"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"treasury:read"})),
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="offline",
    ),
)
"""Treasury domain 9 leaf 의 contract tuple.
"""


STRATEGY_CONTRACTS: tuple[CliCommandContract, ...] = (
    CliCommandContract(
        path=("strategy", "validate"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"strategy:write"})),
        output=OutputContract(kind="operation", envelope="standard"),
        execution="offline",
    ),
    CliCommandContract(
        path=("strategy", "submit"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"strategy:write"})),
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="offline",
    ),
    CliCommandContract(
        path=("strategy", "list"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"strategy:read"})),
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="offline",
    ),
    CliCommandContract(
        path=("strategy", "info"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"strategy:read"})),
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="offline",
    ),
    CliCommandContract(
        path=("strategy", "performance"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"strategy:read"})),
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="offline",
    ),
    CliCommandContract(
        path=("strategy", "set-status"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"strategy:write"})),
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="runtime_ipc",
        ipc_command="strategy.set_status",
    ),
    CliCommandContract(
        path=("strategy", "summary"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"strategy:read"})),
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="offline",
    ),
)
"""Strategy domain 7 leaf 의 contract tuple.
"""


DATA_CONTRACTS: tuple[CliCommandContract, ...] = (
    CliCommandContract(
        path=("data", "list"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"data:read"})),
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="offline",
    ),
    CliCommandContract(
        path=("data", "info"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"data:read"})),
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="offline",
    ),
    CliCommandContract(
        path=("data", "delete"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"data:write"})),
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="offline",
    ),
    CliCommandContract(
        path=("data", "schema"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"data:read"})),
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="offline",
    ),
    CliCommandContract(
        path=("data", "storage"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"data:read"})),
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="offline",
    ),
    CliCommandContract(
        path=("data", "validate"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"data:read"})),
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="offline",
    ),
)
"""Data domain 6 leaf 의 contract tuple.
"""


REPORT_CONTRACTS: tuple[CliCommandContract, ...] = (
    CliCommandContract(
        path=("report", "schema"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"report:read"})),
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="offline",
    ),
    CliCommandContract(
        path=("report", "submit"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"report:write"})),
        output=OutputContract(kind="operation", envelope="standard"),
        execution="offline",
    ),
    CliCommandContract(
        path=("report", "list"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"report:read"})),
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="offline",
    ),
    CliCommandContract(
        path=("report", "performance"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"report:read"})),
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="offline",
    ),
    CliCommandContract(
        path=("report", "view"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"report:read"})),
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="offline",
    ),
)
"""Report domain 5 leaf 의 contract tuple.
"""


BROKER_CONTRACTS: tuple[CliCommandContract, ...] = (
    CliCommandContract(
        path=("broker", "status"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"broker:read"})),
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="runtime_ipc",
        ipc_command="broker.status",
    ),
    CliCommandContract(
        path=("broker", "balance"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"broker:read"})),
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="runtime_ipc",
        ipc_command="broker.balance",
    ),
    CliCommandContract(
        path=("broker", "positions"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"broker:read"})),
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="runtime_ipc",
        ipc_command="broker.positions",
    ),
    CliCommandContract(
        path=("broker", "order-history"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"broker:read"})),
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="runtime_ipc",
        ipc_command="broker.order_history",
    ),
    CliCommandContract(
        path=("broker", "reconcile"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"broker:read"})),
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="runtime_ipc",
        ipc_command="broker.reconcile",
    ),
)
"""Broker domain 5 leaf 의 contract tuple.
"""


SYSTEM_CONTRACTS: tuple[CliCommandContract, ...] = (
    CliCommandContract(
        path=("system", "start"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"system:admin"})),
        output=OutputContract(kind="operation", envelope="standard"),
        execution="long_running",
    ),
    CliCommandContract(
        path=("system", "stop"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"system:admin"})),
        output=OutputContract(kind="operation", envelope="standard"),
        execution="long_running",
    ),
    CliCommandContract(
        path=("system", "status"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"system:read"})),
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="offline",
    ),
    CliCommandContract(
        path=("system", "halt"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"system:admin"})),
        output=OutputContract(kind="operation", envelope="standard"),
        execution="runtime_ipc",
        ipc_command="system.halt",
    ),
    CliCommandContract(
        path=("system", "clear-halt"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"system:admin"})),
        output=OutputContract(kind="operation", envelope="standard"),
        execution="runtime_ipc",
        ipc_command="system.clear_halt",
    ),
)
"""System domain 5 leaf 의 contract tuple.
"""


INSTRUMENT_CONTRACTS: tuple[CliCommandContract, ...] = (
    CliCommandContract(
        path=("instrument", "list"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"data:read"})),
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="offline",
    ),
    CliCommandContract(
        path=("instrument", "sync"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"data:write"})),
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="offline",
    ),
    CliCommandContract(
        path=("instrument", "search"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"data:read"})),
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="offline",
    ),
    CliCommandContract(
        path=("instrument", "import"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"data:write"})),
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="offline",
    ),
)
"""Instrument domain 4 leaf 의 contract tuple.
"""


CONFIG_CONTRACTS: tuple[CliCommandContract, ...] = (
    CliCommandContract(
        path=("config", "get"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"config:read"})),
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="offline",
    ),
    CliCommandContract(
        path=("config", "set"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"config:write"})),
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="runtime_ipc",
        ipc_command="config.set",
    ),
    CliCommandContract(
        path=("config", "history"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"config:read"})),
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="offline",
    ),
)
"""Config domain 3 leaf 의 contract tuple.
"""


RULE_CONTRACTS: tuple[CliCommandContract, ...] = (
    CliCommandContract(
        path=("rule", "list"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"rule:read"})),
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="offline",
    ),
    CliCommandContract(
        path=("rule", "info"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"rule:read"})),
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="offline",
    ),
    CliCommandContract(
        path=("rule", "update"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"rule:admin"})),
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="runtime_ipc",
        ipc_command="rule.update",
    ),
)
"""Rule domain 3 leaf 의 contract tuple.
"""


TRADE_CONTRACTS: tuple[CliCommandContract, ...] = (
    CliCommandContract(
        path=("trade", "list"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"trade:read"})),
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="offline",
    ),
    CliCommandContract(
        path=("trade", "info"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"trade:read"})),
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="offline",
    ),
)
"""Trade domain 2 leaf 의 contract tuple.
"""


BACKTEST_CONTRACTS: tuple[CliCommandContract, ...] = (
    CliCommandContract(
        path=("backtest", "run"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"backtest:run"})),
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="long_running",
    ),
    CliCommandContract(
        path=("backtest", "history"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"backtest:run"})),
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="offline",
    ),
)
"""Backtest domain 2 leaf 의 contract tuple.
"""


AUDIT_CONTRACTS: tuple[CliCommandContract, ...] = (
    CliCommandContract(
        path=("audit", "list"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"audit:read"})),
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="offline",
    ),
)
"""Audit domain 1 leaf 의 contract tuple.
"""


SIGNAL_CONTRACTS: tuple[CliCommandContract, ...] = (
    CliCommandContract(
        path=("signal", "connect"),
        auth=AuthContract(mode="authenticated", scopes=frozenset()),
        output=OutputContract(kind="stream", envelope="raw_legacy"),
        execution="long_running",
    ),
)
"""Signal domain 1 leaf 의 contract tuple.
"""


CLI_COMMAND_REGISTRY: dict[tuple[str, ...], CliCommandContract] = {
    contract.path: contract
    for contract in (
        *ACCOUNT_CONTRACTS,
        *MEMBER_CONTRACTS,
        *BOT_CONTRACTS,
        *APPROVAL_CONTRACTS,
        *TREASURY_CONTRACTS,
        *STRATEGY_CONTRACTS,
        *DATA_CONTRACTS,
        *REPORT_CONTRACTS,
        *BROKER_CONTRACTS,
        *SYSTEM_CONTRACTS,
        *INSTRUMENT_CONTRACTS,
        *CONFIG_CONTRACTS,
        *RULE_CONTRACTS,
        *TRADE_CONTRACTS,
        *BACKTEST_CONTRACTS,
        *AUDIT_CONTRACTS,
        *SIGNAL_CONTRACTS,
    )
}
"""Leaf command path → contract mapping.
"""


def get_contract(path: tuple[str, ...]) -> CliCommandContract | None:
    """``path`` 에 해당하는 contract 를 반환하고, 없으면 ``None``.

    Args:
        path: root-to-leaf command path tuple (예: ``("account", "create")``).

    Returns:
        등록된 :class:`CliCommandContract` 또는 ``None``.
    """
    return CLI_COMMAND_REGISTRY.get(path)


def all_contracts() -> Iterator[CliCommandContract]:
    """등록된 모든 contract 를 dict 순회 순서로 yield 한다.

    account 9 + member 12 + bot 11 + approval 10 + treasury
    9 + strategy 7 + data 6 + report 5 + broker 5 + system 5 + instrument
    4 + config 3 + rule 3 + trade 2 + backtest 2 + audit 1 + signal 1 = 95
    entries 가 등록되어 있다.
    """
    yield from CLI_COMMAND_REGISTRY.values()
