"""CLI command contract registry (#1844 shell, #1846 account, #1847 sweep).

`#1815` 부모 epic 의 코드 결과물. CLI command 별 auth / output /
execution 계약을 한 곳에서 관리하는 registry 다.

본 모듈이 제공하는 것:

* :class:`AuthContract` — auth mode + scope frozenset (#1815 normative).
* :class:`OutputContract` — result shape + envelope + data slot.
* :class:`CliCommandContract` — root-to-leaf command path + 3 sub-contract +
  execution class + (optional) IPC command name.
* :data:`ACCOUNT_CONTRACTS` — account 도메인 9 leaf contract tuple (#1846).
* :data:`MEMBER_CONTRACTS` — member 도메인 12 leaf contract tuple
  (#1847 sub-PR 1).
* :data:`BOT_CONTRACTS` — bot 도메인 11 leaf contract tuple
  (#1847 sub-PR 2).
* :data:`APPROVAL_CONTRACTS` — approval 도메인 10 leaf contract tuple
  (#1847 sub-PR 3).
* :data:`TREASURY_CONTRACTS` — treasury 도메인 9 leaf contract tuple
  (#1847 sub-PR 4).
* :data:`STRATEGY_CONTRACTS` — strategy 도메인 7 leaf contract tuple
  (#1847 sub-PR 5).
* :data:`DATA_CONTRACTS` — data 도메인 6 leaf contract tuple
  (#1847 sub-PR 6).
* :data:`REPORT_CONTRACTS` — report 도메인 5 leaf contract tuple
  (#1847 sub-PR 6).
* :data:`BROKER_CONTRACTS` — broker 도메인 5 leaf contract tuple
  (#1847 sub-PR 7 + #2412 ``order-history``).
* :data:`SYSTEM_CONTRACTS` — system 도메인 5 leaf contract tuple
  (#1847 sub-PR 7).
* :data:`INSTRUMENT_CONTRACTS` — instrument 도메인 4 leaf contract tuple
  (#1847 sub-PR 8).
* :data:`CONFIG_CONTRACTS` — config 도메인 3 leaf contract tuple
  (#1847 sub-PR 8).
* :data:`RULE_CONTRACTS` — rule 도메인 3 leaf contract tuple
  (#1847 sub-PR 8).
* :data:`TRADE_CONTRACTS` — trade 도메인 2 leaf contract tuple
  (#1847 sub-PR 9 — final).
* :data:`BACKTEST_CONTRACTS` — backtest 도메인 2 leaf contract tuple
  (#1847 sub-PR 9 — final).
* :data:`AUDIT_CONTRACTS` — audit 도메인 1 leaf contract tuple
  (#1847 sub-PR 9 — final).
* :data:`SIGNAL_CONTRACTS` — signal 도메인 1 leaf contract tuple
  (#1847 sub-PR 9 — final).
* :data:`CLI_COMMAND_REGISTRY` — leaf path tuple → contract mapping. 본
  PR 시점에는 account 9 + member 12 + bot 11 + approval 10 + treasury 9
  + strategy 7 + data 6 + report 5 + broker 5 + system 5 + instrument 4
  + config 3 + rule 3 + trade 2 + backtest 2 + audit 1 + signal 1 = 95
  entries 가 채워져 있다 (#2412 로 broker 4→5, 94→95).
* :func:`get_contract` / :func:`all_contracts` — read-only accessor.

본 모듈이 의도적으로 *제공하지 않는* 것 (스펙 non-goal):

* output payload migration (`#1846` / `#1847` 는 raw_legacy 를 *문서화*
  만 하며 fmt callsite 를 바꾸지 않는다 — diff guard 가 본 PR 의 invariant).
* drift test guard 완전 활성화 — 미등록 leaf FAIL 은 `#1848` 의 책임.
* IPC server-side metadata (`#1819`). ``ipc_command`` 필드는 stub 값만
  채우며 cross-ref drift test 는 `#1819` 가 담당한다.
* auth enforcement / error taxonomy 변경.

`AuthMode` / `ContractKind` / `EnvelopeForm` vocabulary 는
:mod:`ante.contracts.vocab` 의 Literal SSOT (`#1822`) 를 그대로 가져온다.
별도 alias 를 만들거나 string literal 을 중복 정의하지 않는다.

`raw_legacy` 응답은 ``OutputContract(kind="raw", envelope="raw_legacy")``
조합으로 표현한다. ``raw_legacy`` 는 :data:`ContractKind` 가 아니라
:data:`EnvelopeForm` 값이라는 사실이 #1820 결정이며, 이 점은 본 모듈의
dataclass 시그니처가 그대로 강제한다.

``execution`` Literal 값과 ``docs/specs/cli/03-commands.md`` 표기는 다음과
같이 1:1 대응한다 (normative):

============================  ============================
``03-commands.md`` 표기        ``CliCommandContract.execution``
============================  ============================
``bootstrap/maintenance``     ``"bootstrap"``
``offline``                   ``"offline"``
``runtime IPC``               ``"runtime_ipc"``
``cold-path``                 ``"cold_path"``
``long-running/streaming``    ``"long_running"``
``external process``          ``"long_running"`` (#1815 5 값에 흡수)
============================  ============================

본 registry import 는 어떤 CLI command 도 실행하지 않는다 — 모듈 import
side effect 가 없는지 :mod:`tests.unit.contracts.test_cli_registry_shell`
가 lock 한다.
"""

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

``docs/specs/cli/03-commands.md`` 의 5 모드와 1:1 정합한다. ``external
process`` 표기는 #1815 결정으로 ``"long_running"`` 에 흡수된다.
"""


@dataclass(frozen=True)
class AuthContract:
    """CLI command 의 인증 요구 계약.

    Attributes:
        mode: 인증 모드. :data:`ante.contracts.vocab.AuthMode` Literal 값
            중 하나 (``"public"`` / ``"authenticated"`` / ``"scoped"`` /
            ``"master"``).
        scopes: ``mode == "scoped"`` 일 때 요구되는 scope 집합. #1815
            본문은 **복수 scope** 를 요구할 수 있도록 ``frozenset[str]``
            을 normative 로 못박았다 (단일 ``str`` 또는 ``str | None``
            아님). ``mode`` 가 ``"scoped"`` 가 아니면 빈 frozenset 이
            default 다.
    """

    mode: AuthMode
    scopes: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class OutputContract:
    """CLI command 의 출력 계약.

    Attributes:
        kind: :data:`ante.contracts.vocab.ContractKind` Literal — 응답
            payload 의 result shape 종류. ``"entity"`` / ``"operation"`` /
            ``"collection"`` / ``"raw"`` / ``"stream"``. 본 vocabulary 는
            #1822 SSOT 다.
        data_key: standard envelope 의 ``data`` 슬롯 안에서 사용할 key
            이름 (예: ``"account"``, ``"bots"``). ``raw`` / ``stream``
            계열 또는 단일 slot 이 필요 없는 경우 ``None``.
        envelope: 응답 envelope 형태. ``"standard"`` (#1821 envelope SSOT)
            가 기본이며, 후방 호환이 필요한 legacy 출력은 ``"raw_legacy"``
            를 지정한다. ``raw_legacy`` 는 :data:`ContractKind` 가 아니라
            envelope form 이라는 사실 (#1820) 을 본 dataclass 시그니처가
            강제한다.
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
        auth: 인증 요구 계약.
        output: 출력 계약.
        execution: :data:`ExecutionClass` Literal — 실행 모드.
            ``docs/specs/cli/03-commands.md`` 의 5 모드와 1:1 정합.
        ipc_command: ``execution == "runtime_ipc"`` 일 때 호출할 IPC
            command 이름 (예: ``"bot.start"``). 다른 execution 모드에서는
            ``None`` 이 일반적이다.
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
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="offline",
    ),
    CliCommandContract(
        path=("account", "info"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"account:read"})),
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="offline",
    ),
    CliCommandContract(
        path=("account", "credentials"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"account:read"})),
        output=OutputContract(kind="raw", envelope="raw_legacy"),
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
        output=OutputContract(kind="raw", envelope="raw_legacy"),
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
"""Account domain 9 leaf 의 contract tuple (#1846).

본 tuple 의 순서는 ``docs/specs/cli/03-commands.md`` 의 account 표
(82-90 줄) 와 시각적으로 일치하도록 read → write → state-transition 순서로
정렬된다. ``CLI_COMMAND_REGISTRY`` 에는 모듈 import 시 자동으로 등록된다.
"""


MEMBER_CONTRACTS: tuple[CliCommandContract, ...] = (
    CliCommandContract(
        path=("member", "list"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"member:read"})),
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="offline",
    ),
    CliCommandContract(
        path=("member", "info"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"member:read"})),
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="offline",
    ),
    CliCommandContract(
        path=("member", "list-invalid-roles"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"member:read"})),
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="offline",
    ),
    CliCommandContract(
        path=("member", "register"),
        auth=AuthContract(mode="master", scopes=frozenset()),
        output=OutputContract(kind="raw", envelope="raw_legacy"),
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
        output=OutputContract(kind="raw", envelope="raw_legacy"),
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
        output=OutputContract(kind="raw", envelope="raw_legacy"),
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
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="runtime_ipc",
        ipc_command="member.regenerate_recovery_key",
    ),
)
"""Member domain 12 leaf 의 contract tuple (#1847 sub-PR 1).

순서는 ``docs/specs/cli/03-commands.md:647-690`` 의 member 표 (read →
admin mutation → public allowlist) 와 시각적으로 일치하도록 정렬된다.
``CLI_COMMAND_REGISTRY`` 에는 모듈 import 시 자동으로 등록된다.
"""


BOT_CONTRACTS: tuple[CliCommandContract, ...] = (
    CliCommandContract(
        path=("bot", "list"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"bot:read"})),
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="runtime_ipc",
        ipc_command="bot.list",
    ),
    CliCommandContract(
        path=("bot", "info"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"bot:read"})),
        output=OutputContract(kind="raw", envelope="raw_legacy"),
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
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="runtime_ipc",
        ipc_command="bot.signal_key",
    ),
    CliCommandContract(
        path=("bot", "positions"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"bot:read"})),
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="runtime_ipc",
        ipc_command="bot.positions",
    ),
    CliCommandContract(
        path=("bot", "update"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"bot:admin"})),
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="runtime_ipc",
        ipc_command="bot.update",
    ),
    CliCommandContract(
        path=("bot", "logs"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"bot:read"})),
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="offline",
    ),
    CliCommandContract(
        path=("bot", "start"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"bot:admin"})),
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="runtime_ipc",
        ipc_command="bot.start",
    ),
    CliCommandContract(
        path=("bot", "stop"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"bot:admin"})),
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="runtime_ipc",
        ipc_command="bot.stop",
    ),
    CliCommandContract(
        path=("bot", "status"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"bot:read"})),
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="runtime_ipc",
        ipc_command="bot.status",
    ),
)
"""Bot domain 11 leaf 의 contract tuple (#1847 sub-PR 2).

순서는 ``docs/specs/cli/03-commands.md:91-102`` 의 bot 표 (read → admin
mutation → lifecycle) 와 시각적으로 일치하도록 정렬된다.
``CLI_COMMAND_REGISTRY`` 에는 모듈 import 시 자동으로 등록된다.
"""


APPROVAL_CONTRACTS: tuple[CliCommandContract, ...] = (
    CliCommandContract(
        path=("approval", "list"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"approval:read"})),
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="offline",
    ),
    CliCommandContract(
        path=("approval", "info"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"approval:read"})),
        output=OutputContract(kind="raw", envelope="raw_legacy"),
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
        output=OutputContract(kind="raw", envelope="raw_legacy"),
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
"""Approval domain 10 leaf 의 contract tuple (#1847 sub-PR 3).

순서는 ``docs/specs/cli/03-commands.md:572-585`` 의 approval 표 (read →
write → admin) 와 시각적으로 일치하도록 정렬된다.
``CLI_COMMAND_REGISTRY`` 에는 모듈 import 시 자동으로 등록된다.
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
"""Treasury domain 9 leaf 의 contract tuple (#1847 sub-PR 4).

순서는 ``docs/specs/cli/03-commands.md:112-119`` 의 treasury 실행 분류 표
(status → transactions → budgets → set-balance → allocate → deallocate →
snapshot → portfolio value/history) 와 시각적으로 일치하도록 정렬된다.
``CLI_COMMAND_REGISTRY`` 에는 모듈 import 시 자동으로 등록된다.
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
"""Strategy domain 7 leaf 의 contract tuple (#1847 sub-PR 5).

순서는 ``docs/specs/cli/03-commands.md:105-111`` 의 strategy 실행 분류 표
(validate → submit → list → info → performance → set-status → summary) 와
시각적으로 일치하도록 정렬된다. ``CLI_COMMAND_REGISTRY`` 에는 모듈 import
시 자동으로 등록된다.
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
"""Data domain 6 leaf 의 contract tuple (#1847 sub-PR 6).

순서는 ``docs/specs/cli/03-commands.md:481-492`` 의 data 표 (list →
info → delete → schema → storage → validate) 와 정합하도록 정렬된다.
``CLI_COMMAND_REGISTRY`` 에는 모듈 import 시 자동으로 등록된다.

spec 표 (487-492) 는 4 leaf (list/schema/storage/validate) 만 명시하지만
``info`` / ``delete`` 는 실제 ``data.py`` 에 존재하는 leaf 로 ``ante data
--help`` Click subgroup iteration 이 6 leaf 를 반환한다. registry 는
canonical Click tree (leaf coverage helper SSOT) 기준이므로 6 entries 를
모두 등록한다 (treasury sub-PR 4 ``portfolio value/history`` 동형 — spec
표가 일부 leaf 만 명시하더라도 실측 Click tree 가 SSOT).
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
"""Report domain 5 leaf 의 contract tuple (#1847 sub-PR 6).

순서는 ``docs/specs/cli/03-commands.md:505-510`` 의 report 표 (schema →
submit → list → performance → view) 와 시각적으로 일치하도록 정렬된다.
``CLI_COMMAND_REGISTRY`` 에는 모듈 import 시 자동으로 등록된다.
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
"""Broker domain 5 leaf 의 contract tuple (#1847 sub-PR 7 + #2412).

순서는 ``docs/specs/cli/03-commands.md:123-127`` 의 broker 실행 분류 표
(status → balance → positions → order-history → reconcile) 와 시각적으로
일치하도록 정렬된다. ``CLI_COMMAND_REGISTRY`` 에는 모듈 import 시 자동으로
등록된다.
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
"""System domain 5 leaf 의 contract tuple (#1847 sub-PR 7).

순서는 ``docs/specs/cli/03-commands.md:77-81`` 의 system 실행 분류 표
(start → stop → status → halt → clear-halt) 와 시각적으로 일치하도록
정렬된다. ``CLI_COMMAND_REGISTRY`` 에는 모듈 import 시 자동으로 등록된다.
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
"""Instrument domain 4 leaf 의 contract tuple (#1847 sub-PR 8).

순서는 ``docs/specs/cli/03-commands.md:691-704`` 의 instrument 표
(list → sync → search → import) 와 시각적으로 일치하도록 정렬된다.
``CLI_COMMAND_REGISTRY`` 에는 모듈 import 시 자동으로 등록된다.
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
"""Config domain 3 leaf 의 contract tuple (#1847 sub-PR 8).

순서는 ``docs/specs/cli/03-commands.md:564-571`` 의 config 표
(get → set → history) 와 시각적으로 일치하도록 정렬된다.
``CLI_COMMAND_REGISTRY`` 에는 모듈 import 시 자동으로 등록된다.
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
"""Rule domain 3 leaf 의 contract tuple (#1847 sub-PR 8).

순서는 ``docs/specs/cli/03-commands.md:429-448`` 의 rule 표
(list → info → update) 와 시각적으로 일치하도록 정렬된다.
``CLI_COMMAND_REGISTRY`` 에는 모듈 import 시 자동으로 등록된다.
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
"""Trade domain 2 leaf 의 contract tuple (#1847 sub-PR 9, final).

순서는 ``docs/specs/cli/03-commands.md:383-394`` 의 trade 표
(list → info) 와 시각적으로 일치하도록 정렬된다.
``CLI_COMMAND_REGISTRY`` 에는 모듈 import 시 자동으로 등록된다.
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
"""Backtest domain 2 leaf 의 contract tuple (#1847 sub-PR 9, final).

순서는 ``docs/specs/cli/03-commands.md:494-503`` 의 backtest 표
(run → history) 와 시각적으로 일치하도록 정렬된다.
``CLI_COMMAND_REGISTRY`` 에는 모듈 import 시 자동으로 등록된다.
"""


AUDIT_CONTRACTS: tuple[CliCommandContract, ...] = (
    CliCommandContract(
        path=("audit", "list"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"audit:read"})),
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="offline",
    ),
)
"""Audit domain 1 leaf 의 contract tuple (#1847 sub-PR 9, final).

순서는 ``docs/specs/cli/03-commands.md:710-720`` 의 audit 표 (list 단일) 와
시각적으로 일치한다. ``CLI_COMMAND_REGISTRY`` 에는 모듈 import 시 자동으로
등록된다.
"""


SIGNAL_CONTRACTS: tuple[CliCommandContract, ...] = (
    CliCommandContract(
        path=("signal", "connect"),
        auth=AuthContract(mode="authenticated", scopes=frozenset()),
        output=OutputContract(kind="stream", envelope="raw_legacy"),
        execution="long_running",
    ),
)
"""Signal domain 1 leaf 의 contract tuple (#1847 sub-PR 9, final).

순서는 ``docs/specs/cli/03-commands.md:721-727`` 의 signal 표 (connect 단일)
와 시각적으로 일치한다. ``CLI_COMMAND_REGISTRY`` 에는 모듈 import 시 자동으로
등록된다.
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

본 PR 시점에는 account 9 + member 12 + bot 11 + approval 10 + treasury 9
+ strategy 7 + data 6 + report 5 + broker 5 + system 5 + instrument 4
+ config 3 + rule 3 + trade 2 + backtest 2 + audit 1 + signal 1 = 95
entries 가 등록되어 있다 (#1846 / #1847 sub-PR 1 / #1847 sub-PR 2 /
#1847 sub-PR 3 / #1847 sub-PR 4 / #1847 sub-PR 5 / #1847 sub-PR 6 /
#1847 sub-PR 7 / #1847 sub-PR 8 / #1847 sub-PR 9 / #2412
``broker order-history``). #1847 sweep 은 sub-PR 9 로 완료되었고
(sub-PR 9 = final), registry 미등록 leaf 가 FAIL 이어야 하는 drift guard
는 `#1848` 가 활성화한다. 이후 신규 leaf 는 도입 이슈가 직접 등록한다
(#2412 로 broker 4→5, 94→95).

미등록 잔여 leaf (95 / 실측 Click leaf count 비교): ``ante`` root 의
init / update / notification group 은 leaf 가 없거나 (notification은
0 leaf — spec 707-708 narrative), update 단일 leaf 는 root-level command
로 본 registry sweep 범위 밖이다. 정확한 잔여 leaf 식별은
:func:`tests.unit.contracts.helpers.iter_click_leaf_commands` 의 실측을
기준으로 한다 (leaf coverage report 참조).
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

    본 PR 시점에는 account 9 + member 12 + bot 11 + approval 10 + treasury
    9 + strategy 7 + data 6 + report 5 + broker 5 + system 5 + instrument
    4 + config 3 + rule 3 + trade 2 + backtest 2 + audit 1 + signal 1 = 95
    entries 가 등록되어 있다 (#1846 / #1847 sub-PR 1 / #1847 sub-PR 2 /
    #1847 sub-PR 3 / #1847 sub-PR 4 / #1847 sub-PR 5 / #1847 sub-PR 6 /
    #1847 sub-PR 7 / #1847 sub-PR 8 / #1847 sub-PR 9 / #2412
    ``broker order-history``).
    """
    yield from CLI_COMMAND_REGISTRY.values()
