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
같이 1:1 대응한다 (normative — 후속 #1846/#1847 등록 시 동일 매핑 사용):

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
process`` 표기는 #1815 결정으로 ``"long_running"`` 에 흡수된다 — 후속
spec 이 별도 모드로 분리할 필요가 생기면 vocab 을 늘리고 본 모듈을
업데이트한다.
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


# ── #1846: account domain OutputContract migration ───────────────────────
#
# account 도메인 9 leaf 의 contract entry. ``src/ante/cli/commands/account.py``
# 의 ``@require_scope`` marker 와 ``fmt.*`` 호출 패턴, 그리고
# ``docs/specs/cli/03-commands.md:82-90`` 실행 분류와 1:1 정합한다.
#
# raw_legacy 분류 (4 commands): ``account list`` / ``info`` / ``credentials`` /
# ``set-credentials`` 는 현재 ``fmt.output(dict)`` 으로 평면 dict 를 직접
# 출력한다. 본 entry 는 그 사실을 ``OutputContract(kind="raw",
# envelope="raw_legacy")`` 조합으로 표현해 lock 만 한다 — account.py 본문
# 변경 없음 (drift test 가 callsite 변경 시 FAIL).
#
# standard envelope (4 commands): ``account create`` / ``delete`` /
# ``repair-timezone`` 는 cold_path 이고 ``fmt.success(message, data=...)``
# 으로 표준 envelope (`{status, message, data}`) 을 dump 한다. ``account
# suspend`` / ``activate`` 는 runtime_ipc passthrough 이며 IPC 응답을 받은
# 뒤 CLI surface 에서 ``fmt.success`` 로 한 번 wrapping 한다 (envelopes.md
# "Wrapping 경계" SSOT).
#
# scope 문자열은 colon SSOT (``account:read`` / ``account:write``) 를 그대로
# 사용한다 — Family B drift test 가 marker 와 정합 검증.
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
        # set-credentials 는 분기 mixed: 일반 경로는 fmt.success (standard),
        # 그러나 broker 가 credentials 를 요구하지 않는 short-circuit 경로는
        # ``fmt.output({"message": ...})`` 평면 dict 를 dump 한다. plan v2
        # decision 에 따라 raw 우선으로 표현하고, drift test 가 양쪽 경로를
        # 모두 단언한다.
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


# ── #1847 sub-PR 1: member domain OutputContract migration ───────────────
#
# member 도메인 12 leaf 의 contract entry. ``src/ante/cli/commands/member.py``
# 의 ``@require_scope`` / ``@require_master`` marker 와 ``fmt.*`` 호출 패턴,
# 그리고 ``docs/specs/cli/03-commands.md:647-690`` (member 표 + 실행 분류
# 141-148) 와 1:1 정합한다.
#
# raw_legacy 분류 (7 commands): ``list`` / ``info`` / ``list-invalid-roles`` /
# ``register`` / ``update-scopes`` / ``rotate-token`` / ``regenerate-recovery
# -key`` 는 JSON mode 에서 ``fmt.output(dict)`` 평면 dict 를 그대로 dump 한다
# (token / scopes / detail 평면 표현). ``OutputContract(kind="raw", envelope=
# "raw_legacy")`` 조합으로 표현해 lock 만 한다 — member.py 본문 변경 없음
# (drift test 가 callsite 변경 시 FAIL).
#
# standard envelope (5 commands): ``set-emoji`` / ``suspend`` / ``reactivate``
# / ``revoke`` / ``reset-password`` 는 단일 경로 ``fmt.success(message,
# data?=...)`` 만 호출하며 표준 envelope (`{status, message, data}`) 을 dump
# 한다. JSON mode 분기 없음 (text 와 JSON 양쪽 모두 fmt.success).
#
# scope/master 분류:
# - ``member:read`` scope: ``list`` / ``info`` / ``list-invalid-roles`` (3 개)
# - master decorator: ``register`` / ``set-emoji`` / ``update-scopes`` /
#   ``suspend`` / ``reactivate`` / ``revoke`` / ``rotate-token`` (7 개)
# - public allowlist (``_AUTH_EXEMPT_COMMAND_PATHS``): ``reset-password`` /
#   ``regenerate-recovery-key`` (2 개) — recovery key / 현재 패스워드 자체가
#   인증 수단이므로 토큰 인증 미요구.
#
# execution 분류는 ``docs/specs/cli/03-commands.md:141-148`` 의 spec SSOT 를
# 따른다 — ``member list/info/list-invalid-roles`` 는 ``offline`` 이며 그
# 외 9 commands 는 ``runtime IPC`` 다. ``ipc_command`` 필드는 stub 값만
# 채운다 (예: ``"member.register"``); 단순 문자열 lock 이며 server-side IPC
# registry 와의 cross-ref drift test 는 #1819 의 책임이다 (이슈 #1847 본문
# v2 결정). 현재 member.py 에서 ``ipc_send`` 분기를 실제로 실행하는 것은
# ``update-scopes`` 1 개 뿐이고 나머지 8 commands 는 cold_path 로 직접
# ``MemberService`` 를 호출하지만, 본 PR 은 spec SSOT 분류만 등록한다 —
# 실제 ``ipc_send`` 분기 추가는 #1819 또는 별도 후속 이슈가 책임진다
# (callsite envelope shape 자체는 drift test 가 lock).
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
        # JSON mode: ``fmt.output({**result, "token": token})`` 평면 dict.
        # text mode 는 ``fmt.success`` + ``click.echo`` 로 token 을 별도
        # 표시하지만 JSON mode shape 가 raw_legacy 우선 정책에 부합한다.
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="runtime_ipc",
        ipc_command="member.register",
    ),
    CliCommandContract(
        path=("member", "set-emoji"),
        auth=AuthContract(mode="master", scopes=frozenset()),
        # 단일 경로 ``fmt.success(message, data)`` — JSON/text 모두 standard.
        output=OutputContract(kind="operation", envelope="standard"),
        execution="runtime_ipc",
        ipc_command="member.set_emoji",
    ),
    CliCommandContract(
        path=("member", "update-scopes"),
        auth=AuthContract(mode="master", scopes=frozenset()),
        # JSON mode: ``fmt.output(result)`` 평면 dict; text 는 fmt.success.
        # member.py 에서 실제로 ``ipc_send`` 분기를 실행하는 유일한 leaf 다
        # (line 601-606). IPC handler 도 등록되어 있다
        # (``src/ante/ipc/registry.py:727``).
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="runtime_ipc",
        ipc_command="member.update_scopes",
    ),
    CliCommandContract(
        path=("member", "suspend"),
        auth=AuthContract(mode="master", scopes=frozenset()),
        # 단일 경로 ``fmt.success(f"멤버 정지 완료: ...", result)``.
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
        # JSON mode: ``fmt.output({**result, "token": token})`` 평면 dict.
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="runtime_ipc",
        ipc_command="member.rotate_token",
    ),
    CliCommandContract(
        path=("member", "reset-password"),
        # ``_AUTH_EXEMPT_COMMAND_PATHS`` 등재 — recovery key 자체가 인증 수단.
        auth=AuthContract(mode="public", scopes=frozenset()),
        # 단일 경로 ``fmt.success("패스워드가 변경되었습니다.")`` — data 없음.
        output=OutputContract(kind="operation", envelope="standard"),
        execution="runtime_ipc",
        ipc_command="member.reset_password",
    ),
    CliCommandContract(
        path=("member", "regenerate-recovery-key"),
        # ``_AUTH_EXEMPT_COMMAND_PATHS`` 등재 — 현재 패스워드 자체가 인증 수단.
        auth=AuthContract(mode="public", scopes=frozenset()),
        # JSON mode: ``fmt.output({"recovery_key": new_key})`` 평면 dict.
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


# ── #1847 sub-PR 2: bot domain OutputContract migration ─────────────────
#
# bot 도메인 11 leaf 의 contract entry. ``src/ante/cli/commands/bot.py``
# 의 ``@require_scope`` marker 와 ``fmt.*`` 호출 패턴, 그리고
# ``docs/specs/cli/03-commands.md:91-102`` (bot 표) / ``329-372`` (생명주기
# narrative) 와 1:1 정합한다.
#
# raw_legacy 분류 (8 commands): ``list`` / ``info`` / ``positions`` /
# ``signal-key`` / ``logs`` / ``update`` / ``start`` / ``stop`` / ``status``
# 는 JSON 모드에서 ``fmt.output(dict)`` 또는 ``fmt.output(result)`` 평면
# dict 를 그대로 dump 한다. ``status`` / ``positions`` 등은 도메인
# envelope (``{bot: ...}`` / ``{positions: [...]}``) 형태이며 standard
# envelope (``{status, message, data}``) 3 키 셋과는 다르다 — ``fmt.success``
# 로 wrapping 하지 않고 IPC payload 를 그대로 passthrough 하는 정책
# (feedback_cli_json_envelope_passthrough 메모) 의 결과다.
# ``OutputContract(kind="raw", envelope="raw_legacy")`` 조합으로 표현해 lock
# 만 한다 — bot.py 본문 변경 없음 (drift test 가 callsite 변경 시 FAIL).
#
# standard envelope (2 commands): ``create`` / ``remove`` 는 단일 경로
# ``fmt.success(message, data)`` 만 호출하며 표준 envelope
# (``{status, message, data}``) 을 dump 한다. JSON mode 분기 없음 (text 와
# JSON 양쪽 모두 fmt.success).
#
# ``signal-key`` 는 분기 mixed: ``--rotate`` 경로는 ``fmt.success`` (standard),
# 그러나 단순 조회 경로는 JSON 에서 ``fmt.output(result)`` 평면 dict 를
# dump 한다 (line 540-547). account ``set-credentials`` 와 동형 분기 mixed
# 이며, plan 정책에 따라 raw 우선으로 표현한다. drift test 가 양쪽 경로를
# 모두 단언한다.
#
# scope 분류:
# - ``bot:read`` scope (5 개): ``list`` / ``info`` / ``positions`` /
#   ``logs`` / ``status``
# - ``bot:admin`` scope (6 개): ``create`` / ``remove`` / ``signal-key`` /
#   ``update`` / ``start`` / ``stop``
# - public allowlist: 없음 — bot 도메인은 ``_AUTH_EXEMPT_COMMAND_PATHS``
#   에 등재된 leaf 가 0 개다.
#
# execution 분류는 ``docs/specs/cli/03-commands.md:91-102`` 의 spec SSOT 를
# 따른다 — ``bot logs`` 는 ``offline`` 이며 그 외 10 commands 는 ``runtime
# IPC`` (또는 ``runtime IPC + snapshot/cold-path fallback``) 다. spec 의
# fallback 표기는 primary 분류 ``runtime_ipc`` 에 흡수된다 (account
# ``suspend/activate`` / member ``update-scopes`` 와 동형 정책 — fallback
# 분기가 있어도 spec primary 분류만 lock). ``ipc_command`` 필드는 stub
# 값만 채운다 (예: ``"bot.start"``); 단순 문자열 lock 이며 server-side IPC
# registry 와의 cross-ref drift test 는 #1819 의 책임이다.
BOT_CONTRACTS: tuple[CliCommandContract, ...] = (
    CliCommandContract(
        path=("bot", "list"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"bot:read"})),
        # JSON mode: empty → ``fmt.output({"message": ..., "bots": []})`` 평면,
        # non-empty → ``fmt.output({"bots": [...]})`` 평면. text 는 fmt.table.
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="runtime_ipc",
        ipc_command="bot.list",
    ),
    CliCommandContract(
        path=("bot", "info"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"bot:read"})),
        # JSON mode: ``fmt.output(result)`` 평면 detail dict. text 는 click.echo.
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="runtime_ipc",
        ipc_command="bot.info",
    ),
    CliCommandContract(
        path=("bot", "create"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"bot:admin"})),
        # 단일 경로 ``fmt.success(f"봇 생성 완료: ...", result)`` — standard.
        output=OutputContract(kind="operation", envelope="standard"),
        execution="runtime_ipc",
        ipc_command="bot.create",
    ),
    CliCommandContract(
        path=("bot", "remove"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"bot:admin"})),
        # 단일 경로 ``fmt.success(f"봇 삭제 완료...", result)`` — standard.
        # spec 은 ``runtime IPC + cold-path fallback`` 이지만 primary 분류만
        # lock (account ``suspend/activate`` 동형 정책).
        output=OutputContract(kind="operation", envelope="standard"),
        execution="runtime_ipc",
        ipc_command="bot.remove",
    ),
    CliCommandContract(
        path=("bot", "signal-key"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"bot:admin"})),
        # 분기 mixed: ``--rotate`` 경로는 ``fmt.success`` (standard), 단순
        # 조회 경로는 JSON 모드에서 ``fmt.output(result)`` 평면 dict
        # (bot.py line 540-547). plan v2 decision 에 따라 raw 우선으로
        # 표현 (account ``set-credentials`` 동형 정책) — drift test 가 양쪽
        # 분기를 모두 단언한다.
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="runtime_ipc",
        ipc_command="bot.signal_key",
    ),
    CliCommandContract(
        path=("bot", "positions"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"bot:read"})),
        # JSON mode: empty → ``{"message": ..., "positions": []}``,
        # non-empty → ``{"positions": [...]}`` 평면.
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="runtime_ipc",
        ipc_command="bot.positions",
    ),
    CliCommandContract(
        path=("bot", "update"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"bot:admin"})),
        # JSON mode: ``fmt.output(result)`` 평면 dict; text 는 click.echo.
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="runtime_ipc",
        ipc_command="bot.update",
    ),
    CliCommandContract(
        path=("bot", "logs"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"bot:read"})),
        # JSON mode: ``fmt.output(result)`` 평면 ``{bot_id, logs, total}``
        # dict; text 는 fmt.table 또는 "(logs 없음)".
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="offline",
    ),
    CliCommandContract(
        path=("bot", "start"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"bot:admin"})),
        # JSON mode: IPC ``{bot: ...}`` envelope passthrough via
        # ``fmt.output(result)``; text 는 friendly message.
        # (feedback_cli_json_envelope_passthrough 메모 정책 — IPC/Web API
        # envelope 와 같은 shape 보존을 위해 ``fmt.success`` wrapping 하지
        # 않음).
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="runtime_ipc",
        ipc_command="bot.start",
    ),
    CliCommandContract(
        path=("bot", "stop"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"bot:admin"})),
        # JSON mode: IPC envelope passthrough via ``fmt.output(result)``.
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="runtime_ipc",
        ipc_command="bot.stop",
    ),
    CliCommandContract(
        path=("bot", "status"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"bot:read"})),
        # JSON mode: IPC ``{bot: ...}`` envelope passthrough via
        # ``fmt.output(result)``; text 는 click.echo detail.
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


# ── #1847 sub-PR 3: approval domain OutputContract migration ────────────
#
# approval 도메인 10 leaf 의 contract entry. ``src/ante/cli/commands/approval.py``
# 의 ``@require_scope`` marker 와 ``fmt.*`` 호출 패턴, 그리고
# ``docs/specs/cli/03-commands.md:136-139`` (실행 분류) / ``572-585`` (커맨드
# 표) 와 1:1 정합한다.
#
# raw_legacy 분류 (3 commands): ``list`` / ``audit-types`` 는 ``fmt.table(rows,
# columns)`` 로 JSON 모드에서 row list 를 그대로 dump 한다 (``[{id, type,
# status, ...}, ...]`` 평면 list — standard envelope 의 ``{status, message,
# data}`` 3 키 셋 부재). ``info`` 는 ``fmt.output(result)`` 로 평면 detail dict
# 를 그대로 dump 한다. 세 leaf 모두 ``OutputContract(kind="raw", envelope=
# "raw_legacy")`` 조합으로 lock — approval.py 본문 변경 없음 (drift test 가
# callsite 변경 시 FAIL).
#
# standard envelope (7 commands): ``request`` / ``review`` / ``reopen`` /
# ``cancel-invalid`` / ``cancel`` / ``approve`` / ``reject`` 는 단일 경로
# ``fmt.success(message, data)`` 만 호출하며 표준 envelope (``{status,
# message, data}``) 을 dump 한다. JSON mode 분기 없음 (text 와 JSON 양쪽
# 모두 fmt.success).
#
# scope 분류 (#1815 SSOT, approval.py @require_scope marker 와 1:1 정합):
# - ``approval:read`` scope (4 개): ``list`` / ``info`` / ``review`` /
#   ``audit-types``. ``review`` 는 검토 의견 추가이지만 spec / marker SSOT 가
#   ``approval:read`` 로 지정한다 (의견 기록은 결재 자체 mutation 이 아니라
#   side-channel 메타데이터 추가라는 #1462 결정).
# - ``approval:write`` scope (3 개): ``request`` / ``reopen`` / ``cancel``.
#   ``cancel`` 은 requester ownership rule (본인만) 으로 보호되어 ``write`` 만
#   요구. 다른 사람의 결재 cleanup 은 ``cancel-invalid`` (admin) 으로 분리.
# - ``approval:admin`` scope (3 개): ``approve`` / ``reject`` / ``cancel-invalid``.
# - public allowlist: 없음 — approval 도메인은 ``_AUTH_EXEMPT_COMMAND_PATHS``
#   에 등재된 leaf 가 0 개다.
#
# execution 분류 (``docs/specs/cli/03-commands.md:136-139`` SSOT):
# - ``offline`` (4 개): ``list`` / ``info`` / ``review`` / ``audit-types``.
#   각 leaf 내부에서 ``Database`` 를 직접 생성해 ``ApprovalService`` 를
#   호출한다 (cold-path 동형이나 spec 분류는 ``offline``).
# - ``runtime_ipc`` (6 개): ``request`` / ``reopen`` / ``cancel-invalid`` /
#   ``cancel`` / ``approve`` / ``reject``. ``ipc_send`` 로 IPC handler 를 호출.
#
# ``ipc_command`` 필드는 stub 값만 채운다 (예: ``"approval.request"``); 단순
# 문자열 lock 이며 server-side IPC registry 와의 cross-ref drift test 는
# #1819 의 책임이다 (member/bot domain 동형 정책). approval.py 호출 사이트
# 의 IPC command name 과 그대로 일치한다 (``approval.request`` /
# ``approval.reopen`` / ``approval.cancel_invalid`` / ``approval.cancel`` /
# ``approval.approve`` / ``approval.reject``).
APPROVAL_CONTRACTS: tuple[CliCommandContract, ...] = (
    CliCommandContract(
        path=("approval", "list"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"approval:read"})),
        # JSON mode: ``fmt.table(rows, columns)`` → row list 를 그대로 dump.
        # row dict shape: ``{id, type, status, requester, title, created_at}``.
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="offline",
    ),
    CliCommandContract(
        path=("approval", "info"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"approval:read"})),
        # JSON mode: ``fmt.output(result)`` → 평면 detail dict
        # ({id, type, status, requester, title, body, params, reviews,
        # history, reference_id, expires_at, created_at, resolved_at,
        # resolved_by, reject_reason}).
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="offline",
    ),
    CliCommandContract(
        path=("approval", "review"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"approval:read"})),
        # 단일 경로 ``fmt.success(f"검토 의견 추가: ...", result)`` → standard.
        output=OutputContract(kind="operation", envelope="standard"),
        execution="offline",
    ),
    CliCommandContract(
        path=("approval", "audit-types"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"approval:read"})),
        # JSON mode: ``fmt.table(rows, columns)`` → row list 를 그대로 dump.
        # row dict shape: ``{id, type, status, requester, created_at,
        # expires_at}`` (legacy invalid-type row 만 결과로 포함, #1472).
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="offline",
    ),
    CliCommandContract(
        path=("approval", "request"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"approval:write"})),
        # 단일 경로 ``fmt.success(f"결재 요청 생성: ...", result)`` → standard.
        output=OutputContract(kind="operation", envelope="standard"),
        execution="runtime_ipc",
        ipc_command="approval.request",
    ),
    CliCommandContract(
        path=("approval", "reopen"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"approval:write"})),
        # 단일 경로 ``fmt.success(f"결재 재상신: ...", result)`` → standard.
        output=OutputContract(kind="operation", envelope="standard"),
        execution="runtime_ipc",
        ipc_command="approval.reopen",
    ),
    CliCommandContract(
        path=("approval", "cancel"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"approval:write"})),
        # 단일 경로 ``fmt.success(f"결재 철회: ...", result)`` → standard.
        output=OutputContract(kind="operation", envelope="standard"),
        execution="runtime_ipc",
        ipc_command="approval.cancel",
    ),
    CliCommandContract(
        path=("approval", "approve"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"approval:admin"})),
        # 단일 경로 ``fmt.success(f"결재 승인: ...", result)`` → standard.
        output=OutputContract(kind="operation", envelope="standard"),
        execution="runtime_ipc",
        ipc_command="approval.approve",
    ),
    CliCommandContract(
        path=("approval", "reject"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"approval:admin"})),
        # 단일 경로 ``fmt.success(f"결재 거절: ...", result)`` → standard.
        output=OutputContract(kind="operation", envelope="standard"),
        execution="runtime_ipc",
        ipc_command="approval.reject",
    ),
    CliCommandContract(
        path=("approval", "cancel-invalid"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"approval:admin"})),
        # 단일 경로 ``fmt.success(f"invalid-type 결재 cleanup: ...", result)`` →
        # standard. legacy invalid-type row administrative cleanup (#1472).
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


# ── #1847 sub-PR 4: treasury domain OutputContract migration ────────────
#
# treasury 도메인 9 leaf 의 contract entry. ``src/ante/cli/commands/treasury.py``
# 의 ``@require_scope`` marker 와 ``fmt.*`` 호출 패턴, 그리고
# ``docs/specs/cli/03-commands.md:112-119`` (실행 분류) / ``408-427`` (커맨드
# 표) 와 1:1 정합한다.
#
# 이슈 #1847 본문은 treasury "8 leaf" 로 추정했지만 실측 Click leaf iterator
# (:func:`tests.unit.contracts.helpers.iter_click_leaf_commands`) 는 9 leaf 를
# 반환한다 — spec 표 (408-427) 가 ``portfolio value/history`` 를 한 줄로 묶어
# 표현하지만 Click subgroup ``treasury portfolio`` 아래 ``value`` /
# ``history`` 두 leaf 가 별도로 존재하기 때문이다. registry 는 canonical
# Click tree 기준이므로 9 entries 를 모두 등록한다 (leaf coverage helper SSOT).
#
# raw_legacy 분류 (7 commands): ``status`` / ``transactions`` / ``budgets`` /
# ``set-balance`` / ``snapshot`` / ``portfolio value`` / ``portfolio history``
# 는 JSON 모드에서 ``fmt.output(result)`` 평면 dict 를 그대로 dump 한다
# (``transactions`` / ``budgets`` / ``portfolio history`` 는 text 모드에서
# ``fmt.table`` 사용; JSON 모드는 분기로 ``fmt.output`` 호출). 도메인 envelope
# 형태 (``{account_balance, ...}``, ``{items, total}``, ``{budgets: [...]}``,
# ``{total_value, ...}``, ``{data, start_date, end_date}``) 이며 standard
# envelope ``{status, message, data}`` 3 키 셋과는 다르다. ``OutputContract(
# kind="raw", envelope="raw_legacy")`` 조합으로 표현해 lock 만 한다 —
# treasury.py 본문 변경 없음 (drift test 가 callsite 변경 시 FAIL).
#
# standard envelope (2 commands): ``allocate`` / ``deallocate`` 는
# ``fmt.success(message, data)`` 만 호출하며 표준 envelope (``{status,
# message, data}``) 을 dump 한다 (success 분기 — error 분기는 ``fmt.error``
# 이므로 본 drift test 의 success-output scope 밖). JSON / text 분기 없음.
#
# scope 분류 (#1815 SSOT, treasury.py @require_scope marker 와 1:1 정합):
# - ``treasury:read`` scope (6 개): ``status`` / ``transactions`` /
#   ``budgets`` / ``snapshot`` / ``portfolio value`` / ``portfolio history``.
# - ``treasury:admin`` scope (3 개): ``set-balance`` / ``allocate`` /
#   ``deallocate``.
# - public allowlist: 없음 — treasury 도메인은 ``_AUTH_EXEMPT_COMMAND_PATHS``
#   에 등재된 leaf 가 0 개다.
#
# execution 분류 (``docs/specs/cli/03-commands.md:112-119`` SSOT):
# - ``offline`` (6 개): ``status`` / ``transactions`` / ``budgets`` /
#   ``snapshot`` / ``portfolio value`` / ``portfolio history``. 각 leaf 는
#   ``Database`` 와 ``Treasury`` / ``TreasuryManager`` 를 직접 생성해
#   persisted snapshot/budget/transaction 을 조회한다.
# - ``runtime_ipc`` (3 개): ``allocate`` / ``deallocate`` / ``set-balance``.
#   ``ipc_send`` 로 IPC handler (``treasury.allocate`` / ``treasury.deallocate``
#   / ``treasury.set_balance``) 를 호출한다. ``set-balance`` 는
#   ``is_active_runtime()`` 분기로 cold_path fallback 을 보유하지만 spec
#   primary 분류는 runtime_ipc 다 (account ``suspend``/``activate`` /
#   member ``update-scopes`` 동형 — fallback 분기가 있어도 spec primary
#   분류만 lock).
#
# ``ipc_command`` 필드는 stub 값만 채운다 (예: ``"treasury.allocate"``);
# 단순 문자열 lock 이며 server-side IPC registry 와의 cross-ref drift test 는
# #1819 의 책임이다 (account/member/bot/approval 동형 정책). treasury.py
# 호출 사이트의 IPC command name 과 그대로 일치한다 (``treasury.allocate`` /
# ``treasury.deallocate`` / ``treasury.set_balance``).
TREASURY_CONTRACTS: tuple[CliCommandContract, ...] = (
    CliCommandContract(
        path=("treasury", "status"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"treasury:read"})),
        # JSON mode: ``fmt.output(result)`` 평면 dict (``{account_balance,
        # purchasable_amount, total_evaluation, total_profit_loss,
        # total_allocated, total_reserved, unallocated, bot_count}``). text 는
        # click.echo 8 줄.
        # purchasable_amount 의미(#2384): KIS inquire-psbl-order
        # nrcvb_buy_amt(주문가능액 SSOT, get_buyable). treasury status summary
        # 키 셋 자체는 불변(raw_legacy passthrough) — 본 변경은 산출출처 정렬
        # (Live 동기화 시 get_buyable의 order_buyable_amount를 주입). 한편
        # get_account_balance(broker balance)는 purchasable_amount 키를 제거하고
        # substitute_amount(=psbl_sbst_amt)를 노출하도록 갱신됨(#2384).
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="offline",
    ),
    CliCommandContract(
        path=("treasury", "transactions"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"treasury:read"})),
        # JSON mode: ``fmt.output(result)`` 평면 dict (``{items: [...], total}``).
        # text 는 fmt.table.
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="offline",
    ),
    CliCommandContract(
        path=("treasury", "budgets"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"treasury:read"})),
        # JSON mode: ``fmt.output(result)`` 평면 dict (``{budgets: [...]}``).
        # text 는 fmt.table.
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="offline",
    ),
    CliCommandContract(
        path=("treasury", "set-balance"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"treasury:admin"})),
        # JSON mode: ``fmt.output(result)`` 평면 dict — IPC 분기와 cold_path
        # 분기 모두 ``{account_id, total_balance, updated_at, ...}`` 평면 shape
        # 를 그대로 dump 한다 (account ``set-credentials`` 동형 raw_legacy
        # 정책). spec 은 ``runtime IPC`` 이며 ``is_active_runtime()`` 분기로
        # cold_path fallback 을 보유하지만 primary 분류만 lock.
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="runtime_ipc",
        ipc_command="treasury.set_balance",
    ),
    CliCommandContract(
        path=("treasury", "allocate"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"treasury:admin"})),
        # 단일 success 경로 ``fmt.success(f"예산 할당 완료: ...", data)`` →
        # standard envelope (#1809 typed reject 이후 success 분기는 항상
        # ``success=True``). error 분기는 ``fmt.error`` 이므로 본 drift test
        # 의 success-output scope 밖.
        output=OutputContract(kind="operation", envelope="standard"),
        execution="runtime_ipc",
        ipc_command="treasury.allocate",
    ),
    CliCommandContract(
        path=("treasury", "deallocate"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"treasury:admin"})),
        # 단일 success 경로 ``fmt.success(f"예산 회수 완료: ...", data)`` →
        # standard envelope (allocate 동형).
        output=OutputContract(kind="operation", envelope="standard"),
        execution="runtime_ipc",
        ipc_command="treasury.deallocate",
    ),
    CliCommandContract(
        path=("treasury", "snapshot"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"treasury:read"})),
        # JSON mode: ``fmt.output(result)`` 평면 dict 또는 list (단일 일자는
        # snapshot dict, 기간 조회는 snapshot dict list). 어느 분기든 평면
        # shape 그대로 dump.
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="offline",
    ),
    CliCommandContract(
        path=("treasury", "portfolio", "value"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"treasury:read"})),
        # JSON mode: ``fmt.output(result)`` 평면 dict (``{total_value,
        # daily_pnl, daily_return, unrealized_pnl, accounts: [...],
        # updated_at}``). text 는 click.echo 4 줄.
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="offline",
    ),
    CliCommandContract(
        path=("treasury", "portfolio", "history"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"treasury:read"})),
        # JSON mode: ``fmt.output(result)`` 평면 dict (``{data: [...],
        # start_date, end_date}``). text 는 fmt.table.
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


# ── #1847 sub-PR 5: strategy domain OutputContract migration ────────────
#
# strategy 도메인 7 leaf 의 contract entry. ``src/ante/cli/commands/strategy.py``
# 의 ``@require_scope`` marker 와 ``fmt.*`` 호출 패턴, 그리고
# ``docs/specs/cli/03-commands.md:105-111`` (실행 분류) / ``395-403`` (커맨드
# 표) 와 1:1 정합한다.
#
# raw_legacy 분류 (6 commands): ``submit`` / ``list`` / ``set-status`` /
# ``info`` / ``summary`` / ``performance`` 는 JSON 모드에서 ``fmt.output(
# result)`` 평면 dict 를 그대로 dump 한다. ``submit`` 는 성공 시 ``{submitted:
# True, strategy_id, ...}`` 평면 dict, ``list`` 는 ``{strategies: [...]}`` 또는
# ``{message, strategies: []}`` 평면, ``set-status`` 는 IPC 또는 cold_path
# 분기 결과 평면, ``info`` 는 metadata + params 평면 dict, ``summary`` 는
# ``{strategy_id, period, bot_id, items}`` 평면, ``performance`` 는
# ``{strategy_name, strategy_id, metrics}`` 평면. 도메인 envelope 형태이며
# standard envelope ``{status, message, data}`` 3 키 셋과는 다르다.
# ``OutputContract(kind="raw", envelope="raw_legacy")`` 조합으로 표현해 lock
# 만 한다 — strategy.py 본문 변경 없음 (drift test 가 callsite 변경 시 FAIL).
#
# standard envelope (1 command): ``validate`` 는 단일 success 경로
# ``fmt.success(f"Strategy validation passed: ...", data)`` 만 호출하며 표준
# envelope (``{status, message, data}``) 을 dump 한다. invalid 분기는 별도
# ``fmt.error`` 또는 ``fmt.output({"status": "error", ...})`` 이지만 본 drift
# test 의 success-output scope 밖이다.
#
# scope 분류 (#1815 SSOT, strategy.py @require_scope marker 와 1:1 정합):
# - ``strategy:read`` scope (4 개): ``list`` / ``info`` / ``summary`` /
#   ``performance``.
# - ``strategy:write`` scope (3 개): ``validate`` / ``submit`` / ``set-status``.
# - public allowlist: 없음 — strategy 도메인은 ``_AUTH_EXEMPT_COMMAND_PATHS``
#   에 등재된 leaf 가 0 개다.
#
# execution 분류 (``docs/specs/cli/03-commands.md:105-111`` SSOT):
# - ``offline`` (6 개): ``validate`` / ``submit`` / ``list`` / ``info`` /
#   ``summary`` / ``performance``. 각 leaf 는 ``Database`` 와
#   ``StrategyRegistry`` / ``PerformanceTracker`` / ``StrategyValidator`` /
#   ``StrategyLoader`` 를 직접 생성한다.
# - ``runtime_ipc`` (1 개): ``set-status``. ``is_active_runtime()`` 분기로
#   ``ipc_send("strategy.set_status", ...)`` 를 호출하고, runtime 비활성 시
#   cold_path fallback 으로 ``StrategyRegistry`` 를 직접 사용한다. spec
#   primary 분류는 runtime_ipc 다 (account ``suspend``/``activate`` /
#   member ``update-scopes`` / treasury ``set-balance`` 동형 — fallback 분기가
#   있어도 spec primary 분류만 lock).
#
# ``ipc_command`` 필드는 stub 값만 채운다 (``"strategy.set_status"``); 단순
# 문자열 lock 이며 server-side IPC registry 와의 cross-ref drift test 는
# #1819 의 책임이다 (account/member/bot/approval/treasury 동형 정책).
# strategy.py 호출 사이트의 IPC command name 과 그대로 일치한다.
STRATEGY_CONTRACTS: tuple[CliCommandContract, ...] = (
    CliCommandContract(
        path=("strategy", "validate"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"strategy:write"})),
        # 단일 success 경로 ``fmt.success(f"Strategy validation passed: ...",
        # data)`` → standard envelope. invalid 분기는 ``fmt.error`` / ``fmt.output(
        # {"status": "error", ...})`` 이지만 success-output drift scope 밖.
        output=OutputContract(kind="operation", envelope="standard"),
        execution="offline",
    ),
    CliCommandContract(
        path=("strategy", "submit"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"strategy:write"})),
        # JSON mode 성공 경로: ``fmt.output(result)`` 평면 dict (``{submitted:
        # True, strategy_id, name, version, ...}``). text 모드는 ``fmt.success``
        # 분기. validation/load/meta_validation/register 실패 분기도 모두
        # ``fmt.output({"submitted": False, "stage", "code", ...})`` 평면 dict
        # 이지만 success-output drift scope 밖 (실패 분기는 별도).
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="offline",
    ),
    CliCommandContract(
        path=("strategy", "list"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"strategy:read"})),
        # JSON mode: empty → ``fmt.output({"message": "등록된 전략 없음",
        # "strategies": []})`` 평면, non-empty → ``fmt.output({"strategies":
        # [...]})`` 평면. text 는 fmt.table.
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="offline",
    ),
    CliCommandContract(
        path=("strategy", "info"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"strategy:read"})),
        # JSON mode: ``fmt.output(result)`` 평면 metadata + params dict
        # (``{strategy_id, name, version, status, description, author_name,
        # author_id, filepath, registered_at, validation_warnings, params?,
        # param_schema?, rationale?, risks?, other_versions?}``). text 는
        # click.echo 8+ 줄.
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="offline",
    ),
    CliCommandContract(
        path=("strategy", "performance"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"strategy:read"})),
        # JSON mode: ``fmt.output(result)`` 평면 dict (``{strategy_name,
        # strategy_id, metrics: {...}}``). text 는 click.echo 다수 줄.
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="offline",
    ),
    CliCommandContract(
        path=("strategy", "set-status"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"strategy:write"})),
        # JSON mode: ``fmt.output(result)`` 평면 dict — IPC 분기와 cold_path
        # 분기 모두 ``{strategy_id, status, name, version, ...}`` 평면 shape
        # 를 그대로 dump 한다 (account ``set-credentials`` / treasury
        # ``set-balance`` 동형 raw_legacy 정책). spec 은 ``runtime IPC`` 이며
        # ``is_active_runtime()`` 분기로 cold_path fallback 을 보유하지만
        # primary 분류만 lock.
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="runtime_ipc",
        ipc_command="strategy.set_status",
    ),
    CliCommandContract(
        path=("strategy", "summary"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"strategy:read"})),
        # JSON mode: ``fmt.output(result)`` 평면 dict (``{strategy_id, period,
        # bot_id, items: [...]}``). text 는 fmt.table 또는 empty 분기에서
        # ``fmt.output({"message": "성과 집계 없음", "items": []})``.
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


# ── #1847 sub-PR 6: data domain OutputContract migration ────────────────
#
# data 도메인 6 leaf 의 contract entry. ``src/ante/cli/commands/data.py`` 의
# ``@require_scope`` marker 와 ``fmt.*`` 호출 패턴, 그리고
# ``docs/specs/cli/03-commands.md:481-492`` (data 표) 와 1:1 정합한다.
#
# raw_legacy 분류 (6 commands, 전체): ``list`` / ``info`` / ``delete`` /
# ``schema`` / ``storage`` / ``validate`` 모두 JSON 모드에서 ``fmt.output(
# dict)`` 평면 dict 를 그대로 dump 한다. 도메인 envelope (``{datasets,
# count}``, ``{dataset, preview}``, schema flat dict, ``{total_bytes,
# total_mb, by_timeframe}``, ``{results, summary}``) 이며 standard envelope
# ``{status, message, data}`` 3 키 셋과는 다르다. ``OutputContract(kind=
# "raw", envelope="raw_legacy")`` 조합으로 표현해 lock 만 한다 — data.py
# 본문 변경 없음 (drift test 가 callsite 변경 시 FAIL).
#
# ``delete`` 는 분기 mixed: JSON 모드는 ``fmt.output(result)`` 평면 dict
# (line 208), text 모드는 ``fmt.success(f"데이터셋 삭제 완료: ...", result)``
# (line 210). plan v2 decision 에 따라 raw 우선으로 표현 (account
# ``set-credentials`` / bot ``signal-key`` / treasury ``set-balance`` 동형
# raw_legacy 정책) — drift test 가 JSON 모드를 단언한다.
#
# scope 분류 (#1815 SSOT, data.py @require_scope marker 와 1:1 정합):
# - ``data:read`` scope (5 개): ``list`` / ``info`` / ``schema`` /
#   ``storage`` / ``validate``.
# - ``data:write`` scope (1 개): ``delete``.
# - public allowlist: 없음 — data 도메인은 ``_AUTH_EXEMPT_COMMAND_PATHS``
#   에 등재된 leaf 가 0 개다.
#
# execution 분류 (``docs/specs/cli/03-commands.md:481-492`` SSOT):
# - ``offline`` (6 개, 전체): 모든 data 명령은 local ``ParquetStore`` 와
#   (필요 시) local ``Database`` 를 직접 생성한다. runtime IPC handler 없음.
DATA_CONTRACTS: tuple[CliCommandContract, ...] = (
    CliCommandContract(
        path=("data", "list"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"data:read"})),
        # JSON mode: empty → ``fmt.output({"datasets": [], "count": 0})``
        # 평면, non-empty → ``fmt.output({"datasets": [...], "count": N})``
        # 평면 (data.py:75/95). text 는 fmt.table.
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="offline",
    ),
    CliCommandContract(
        path=("data", "info"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"data:read"})),
        # JSON mode: ``fmt.output(result)`` 평면 dict (``{dataset: {...},
        # preview: [...]}``). text 는 click.echo (data.py:135-154).
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="offline",
    ),
    CliCommandContract(
        path=("data", "delete"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"data:write"})),
        # 분기 mixed: JSON mode 는 ``fmt.output(result)`` 평면 dict
        # (data.py:208), text 는 ``fmt.success(f"데이터셋 삭제 완료: ...",
        # result)`` (data.py:210). plan v2 decision 에 따라 raw 우선으로 표현
        # (account ``set-credentials`` / bot ``signal-key`` / treasury
        # ``set-balance`` 동형 raw_legacy 정책) — drift test 가 JSON 모드를
        # 단언한다.
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="offline",
    ),
    CliCommandContract(
        path=("data", "schema"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"data:read"})),
        # JSON mode: ``fmt.output({k: str(v) for k, v in OHLCV_SCHEMA.items()})``
        # 평면 dict (data.py:223). text 모드도 동일 호출 — fmt.output 내부
        # 분기.
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="offline",
    ),
    CliCommandContract(
        path=("data", "storage"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"data:read"})),
        # JSON mode: ``fmt.output(summary, "Total: {total_mb} MB")`` 평면 dict
        # (``{total_bytes, total_mb, by_timeframe}``, data.py:247). text 는
        # template format string 으로 출력.
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="offline",
    ),
    CliCommandContract(
        path=("data", "validate"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"data:read"})),
        # JSON mode: empty → ``fmt.output({"message": "검증할 데이터가
        # 없습니다.", "results": []})`` (data.py:313), non-empty → ``fmt.output(
        # {"results": [...], "summary": {total_files, valid, corrupted,
        # fixed}})`` (data.py:326). text 는 click.echo.
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


# ── #1847 sub-PR 6: report domain OutputContract migration ──────────────
#
# report 도메인 5 leaf 의 contract entry. ``src/ante/cli/commands/report.py``
# 의 ``@require_scope`` marker 와 ``fmt.*`` 호출 패턴, 그리고
# ``docs/specs/cli/03-commands.md:503-531`` (report 표 + performance
# narrative) 와 1:1 정합한다.
#
# raw_legacy 분류 (4 commands): ``schema`` / ``list`` / ``performance`` /
# ``view`` 는 JSON 모드에서 ``fmt.output(dict)`` 또는 ``fmt.table(rows, ...)``
# 로 평면 dict / row list 를 그대로 dump 한다. 도메인 envelope (``{fields,
# required, optional, ...}``, row list, ``{period, summaries}``, detail dict)
# 이며 standard envelope ``{status, message, data}`` 3 키 셋과는 다르다.
# ``OutputContract(kind="raw", envelope="raw_legacy")`` 조합으로 표현해 lock
# 만 한다 — report.py 본문 변경 없음 (drift test 가 callsite 변경 시 FAIL).
#
# standard envelope (1 command): ``submit`` 는 단일 success 경로
# ``fmt.success(f"Report submitted: ...", result)`` (report.py:182) 만 호출
# 하며 표준 envelope (``{status, message, data}``) 을 dump 한다. JSON / text
# 분기 없음 — 성공 시 fmt.success 만 호출. error 분기는 ``fmt.error`` 이지만
# 본 drift test 의 success-output scope 밖.
#
# scope 분류 (#1815 SSOT, report.py @require_scope marker 와 1:1 정합):
# - ``report:read`` scope (4 개): ``schema`` / ``list`` / ``performance`` /
#   ``view``.
# - ``report:write`` scope (1 개): ``submit``.
# - public allowlist: 없음 — report 도메인은 ``_AUTH_EXEMPT_COMMAND_PATHS``
#   에 등재된 leaf 가 0 개다.
#
# execution 분류 (``docs/specs/cli/03-commands.md:503-531`` SSOT):
# - ``offline`` (5 개, 전체): 모든 report 명령은 local ``Database`` 와
#   ``ReportStore`` / ``BacktestRunStore`` / ``PerformanceTracker`` 를 직접
#   생성한다. runtime IPC handler 없음.
REPORT_CONTRACTS: tuple[CliCommandContract, ...] = (
    CliCommandContract(
        path=("report", "schema"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"report:read"})),
        # JSON mode: ``fmt.output(store.get_schema())`` 평면 dict
        # (``{fields, required, optional, ...}`` 형태, report.py:44).
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="offline",
    ),
    CliCommandContract(
        path=("report", "submit"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"report:write"})),
        # 단일 success 경로 ``fmt.success(f"Report submitted: {report_id}",
        # result)`` (report.py:182) → standard envelope. error 분기는
        # ``fmt.error`` 이지만 success-output drift scope 밖.
        output=OutputContract(kind="operation", envelope="standard"),
        execution="offline",
    ),
    CliCommandContract(
        path=("report", "list"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"report:read"})),
        # JSON mode: ``fmt.table(rows, ["report_id", "strategy", "status",
        # "submitted_at"])`` → row list 를 그대로 dump (report.py:256).
        # row dict shape: ``{report_id, strategy, status, submitted_at}``.
        # text 는 동일 fmt.table 분기.
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="offline",
    ),
    CliCommandContract(
        path=("report", "performance"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"report:read"})),
        # JSON mode: empty → ``fmt.output({"message": "집계 데이터가 없습니다.",
        # "summaries": []})`` (report.py:375), non-empty → ``fmt.output({"period",
        # "summaries": [...]})`` (report.py:379). text 는 fmt.table 분기.
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="offline",
    ),
    CliCommandContract(
        path=("report", "view"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"report:read"})),
        # JSON mode: ``fmt.output(result)`` 평면 detail dict (report.py:441)
        # — ``{report_id, strategy, status, submitted_at, submitted_by,
        # backtest_period, total_return_pct, total_trades, sharpe_ratio,
        # max_drawdown_pct, win_rate, summary, rationale, risks,
        # recommendations}``. text 는 click.echo 다수 줄.
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="offline",
    ),
)
"""Report domain 5 leaf 의 contract tuple (#1847 sub-PR 6).

순서는 ``docs/specs/cli/03-commands.md:505-510`` 의 report 표 (schema →
submit → list → performance → view) 와 시각적으로 일치하도록 정렬된다.
``CLI_COMMAND_REGISTRY`` 에는 모듈 import 시 자동으로 등록된다.
"""


# ── #1847 sub-PR 7: broker domain OutputContract migration ──────────────
#
# broker 도메인 5 leaf 의 contract entry (#1847 sub-PR 7 의 4 + #2412 의
# ``order-history``). ``src/ante/cli/commands/broker.py`` 의
# ``@require_scope`` marker 와 ``fmt.*`` 호출 패턴, 그리고
# ``docs/specs/cli/03-commands.md:123-127`` (실행 분류) / ``450-464`` (커맨드
# 표) 와 1:1 정합한다.
#
# raw_legacy 분류 (5 commands, 전체): ``status`` / ``balance`` / ``positions``
# / ``order-history`` / ``reconcile`` 모두 JSON 모드에서 ``fmt.output(result)``
# 또는 ``fmt.table(pos_list, columns)`` 평면 dict / row list 를 그대로 dump
# 한다. 도메인 envelope (``{connected, healthy, exchange, ...}``, ``{현금/
# 매수가능 평면}``, ``{positions: [...]}``, ``{orders: [...]}``,
# ``{total_symbols, discrepancies, match, ...}``) 이며 standard envelope
# ``{status, message, data}`` 3 키 셋과는 다르다.
# ``OutputContract(kind="raw", envelope="raw_legacy")`` 조합으로 표현해 lock
# 만 한다 — 기존 4 leaf 의 broker.py 본문 변경 없음 (drift test 가 callsite
# 변경 시 FAIL).
#
# ``positions`` 는 분기 mixed: empty → ``fmt.output({"message": ...,
# "positions": []})`` (broker.py:278), non-empty JSON → ``fmt.output({"positions":
# [...]})`` (broker.py:282), non-empty text → ``fmt.table(...)`` (broker.py:285).
# 모두 도메인 envelope 평면 — raw_legacy 정책 (account/treasury/strategy/data
# 분기 mixed 동형).
#
# scope 분류 (#1815 SSOT, broker.py @require_scope marker 와 1:1 정합):
# - ``broker:read`` scope (5 개, 전체): ``status`` / ``balance`` /
#   ``positions`` / ``order-history`` / ``reconcile``. ``reconcile --fix`` 는
#   mutating 분기이지만 marker 는 ``broker:read`` 로 유지된다 (#1843 sub-PR 5
#   audit_actor scope 결정 — write scope 분리 없음).
# - public allowlist: 없음 — broker 도메인은 ``_AUTH_EXEMPT_COMMAND_PATHS``
#   에 등재된 leaf 가 0 개다.
#
# execution 분류 (``docs/specs/cli/03-commands.md:123-127`` SSOT):
# - ``runtime_ipc`` (5 개, 전체): 모든 broker live 커맨드는 spec 상 서버가
#   시작 시 생성한 BrokerAdapter 를 통해 실행하는 런타임 IPC 커맨드다 (spec
#   458-463 narrative). broker.py 의 실제 callsite 는 ``ipc_send(...)`` 우선
#   + ``click.ClickException`` 발생 시 cold_path fallback (직접 BrokerAdapter
#   생성) 분기를 보유하지만 spec primary 분류는 runtime_ipc 다 (account
#   ``suspend``/``activate`` / member ``update-scopes`` / treasury
#   ``set-balance`` / strategy ``set-status`` 동형 — fallback 분기가 있어도
#   spec primary 분류만 lock).
#
# ``ipc_command`` 필드는 stub 값만 채운다 (예: ``"broker.status"``); 단순
# 문자열 lock 이며 server-side IPC registry 와의 cross-ref drift test 는
# #1819 의 책임이다 (account/member/bot/approval/treasury/strategy 동형 정책).
# broker.py 호출 사이트의 IPC command name 과 그대로 일치한다 (``broker.status``
# / ``broker.balance`` / ``broker.positions`` / ``broker.order_history`` /
# ``broker.reconcile``).
BROKER_CONTRACTS: tuple[CliCommandContract, ...] = (
    CliCommandContract(
        path=("broker", "status"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"broker:read"})),
        # JSON mode: ``fmt.output(result)`` 평면 dict (``{connected, healthy,
        # exchange?, error?}``, broker.py:159). text 는 click.echo 다수 줄.
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="runtime_ipc",
        ipc_command="broker.status",
    ),
    CliCommandContract(
        path=("broker", "balance"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"broker:read"})),
        # JSON mode: ``fmt.output(result)`` 평면 broker 잔고 dict
        # (broker.py:220). 키 셋은 broker adapter 가 반환하는 그대로 (IPC
        # 분기는 server BrokerAdapter response 의 평면 dict, fallback 분기는
        # KIS/Mock adapter 의 ``get_account_balance()`` 반환값).
        # get_account_balance() 반환 키 셋(#2384): cash, total_assets,
        # purchase_amount, eval_amount, total_profit_loss,
        # substitute_amount(=psbl_sbst_amt 대용가능금액). purchasable_amount
        # 키는 더 이상 포함하지 않음(주문가능액은 별도 get_buyable() 경로).
        # raw_legacy passthrough 라 키 셋 자체는 enforce 안 함(drift fixture
        # 미파괴) — 구현 #2384 merge 후 실행 가능.
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="runtime_ipc",
        ipc_command="broker.balance",
    ),
    CliCommandContract(
        path=("broker", "positions"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"broker:read"})),
        # 분기 mixed: empty → ``fmt.output({"message": "보유 종목 없음",
        # "positions": []})`` (broker.py:278), non-empty JSON →
        # ``fmt.output({"positions": [...]})`` (broker.py:282), non-empty text
        # → ``fmt.table(pos_list, columns)`` (broker.py:285). 모두 도메인
        # envelope 평면.
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="runtime_ipc",
        ipc_command="broker.positions",
    ),
    CliCommandContract(
        path=("broker", "order-history"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"broker:read"})),
        # Refs #2412. JSON mode: ``fmt.output(result)`` 로 IPC envelope 을
        # 그대로 passthrough 한 평면 dict (``{orders: [...]}``). 빈 결과도
        # 동일 shape (``{"orders": []}``) — ``positions`` 의 empty 분기
        # ``message`` 키 혼합은 따르지 않는다. text 는 known-limitation
        # 헤더 1줄 + ``fmt.table(orders, 8 columns)``.
        #
        # 형제 4종과 동일한 ``kind="raw"`` / ``envelope="raw_legacy"`` 다 —
        # ``collection`` 을 쓰면 broker 도메인 안에서 형제와 갈라진다
        # (IPC 쪽 ``result_kind="collection"`` 은 별개 vocabulary 다).
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="runtime_ipc",
        ipc_command="broker.order_history",
    ),
    CliCommandContract(
        path=("broker", "reconcile"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"broker:read"})),
        # JSON mode: ``fmt.output(result)`` 평면 dict (``{total_symbols,
        # discrepancies, match, fix_applied, corrections}``, broker.py:406).
        # text 는 click.echo + (불일치가 있으면) fmt.table. ``--fix`` 분기는
        # IPC mutating 호출이지만 success envelope shape 는 동일.
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


# ── #1847 sub-PR 7: system domain OutputContract migration ──────────────
#
# system 도메인 5 leaf 의 contract entry. ``src/ante/cli/commands/system.py``
# 의 ``@require_scope`` marker 와 ``fmt.*`` 호출 패턴, 그리고
# ``docs/specs/cli/03-commands.md:77-81`` (실행 분류) / ``156-164`` (커맨드
# 표) 와 1:1 정합한다.
#
# standard envelope (4 commands): ``start`` / ``stop`` / ``halt`` /
# ``clear-halt`` 는 단일 success 경로 ``fmt.success(message[, data])`` 만
# 호출하며 표준 envelope (``{status, message, data}``) 을 dump 한다.
# - ``start`` (system.py:94): ``fmt.success("시스템 시작 중...")`` — data
#   인자 없음 (``OutputFormatter.success`` 가 ``None`` → ``{}`` 으로 normalize).
#   JSON 모드에서 ``data: {}`` 평면 dict 슬롯이 있다.
# - ``stop`` (system.py:152): ``fmt.success("종료 시그널 전송 완료", {"pid": pid})``.
# - ``halt`` (system.py:224): ``fmt.success(f"시스템 HALTED — {count}개 ...", data)``.
# - ``clear-halt`` (system.py:242): ``fmt.success(f"시스템 정지 해제 — ...", data)``.
# JSON / text 분기 없음 (text 와 JSON 양쪽 모두 fmt.success).
#
# raw_legacy 분류 (1 command): ``status`` (system.py:202-206) 는 JSON 모드
# 분기에서 ``fmt.output(result)`` 로 평면 dict (``{trading_state, bot_count}``)
# 를 그대로 dump 한다. text 모드는 click.echo 2 줄. ``OutputContract(kind=
# "raw", envelope="raw_legacy")`` 조합으로 표현해 lock 만 한다.
#
# scope 분류 (#1815 SSOT, system.py @require_scope marker 와 1:1 정합):
# - ``system:read`` scope (1 개): ``status``.
# - ``system:admin`` scope (4 개): ``start`` / ``stop`` / ``halt`` /
#   ``clear-halt``.
# - public allowlist: 없음 — system 도메인은 ``_AUTH_EXEMPT_COMMAND_PATHS``
#   에 등재된 leaf 가 0 개다.
#
# execution 분류 (``docs/specs/cli/03-commands.md:77-81`` SSOT):
# - ``long_running`` (2 개): ``start`` / ``stop``. spec 표는 ``external
#   process`` 표기이며 본 registry 의 ExecutionClass vocab 매핑 (모듈 docstring
#   normative 표) 에 따라 ``"long_running"`` 에 흡수된다.
# - ``offline`` (1 개): ``status``. 로컬 DB / PID 상태 조회.
# - ``runtime_ipc`` (2 개): ``halt`` / ``clear-halt``. ``ipc_send`` 로 IPC
#   handler (``system.halt`` / ``system.clear_halt``) 를 호출.
#
# ``ipc_command`` 필드는 ``halt`` / ``clear-halt`` 의 IPC command name stub
# 만 채운다 (``"system.halt"`` / ``"system.clear_halt"``); 단순 문자열 lock
# 이며 server-side IPC registry 와의 cross-ref drift test 는 #1819 의 책임이다.
# ``start`` / ``stop`` 은 IPC 가 아니라 OS process 제어 (``subprocess.run`` /
# ``os.kill(SIGTERM)``) 이므로 ``ipc_command`` 는 ``None``.
SYSTEM_CONTRACTS: tuple[CliCommandContract, ...] = (
    CliCommandContract(
        path=("system", "start"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"system:admin"})),
        # 단일 success 경로 ``fmt.success("시스템 시작 중...")`` (system.py:94)
        # — data 인자 없음. JSON 모드 dump 는 ``{status: "ok", message:
        # "시스템 시작 중...", data: {}}`` standard envelope. 이후 subprocess
        # 가 inherit 된 stderr 로 자식 로그를 흘려 ``json.loads`` 파싱이
        # 단일 document 로 보장된다 (#1757 stdout 격리).
        output=OutputContract(kind="operation", envelope="standard"),
        execution="long_running",
    ),
    CliCommandContract(
        path=("system", "stop"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"system:admin"})),
        # 단일 success 경로 ``fmt.success("종료 시그널 전송 완료", {"pid": pid})``
        # (system.py:152) → standard envelope (``data: {pid}``). error 분기는
        # ``fmt.error`` 이며 본 drift test 의 success-output scope 밖.
        output=OutputContract(kind="operation", envelope="standard"),
        execution="long_running",
    ),
    CliCommandContract(
        path=("system", "status"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"system:read"})),
        # JSON mode 분기: ``fmt.output(result)`` 평면 dict (``{trading_state,
        # bot_count}``, system.py:203). text 는 click.echo 2 줄.
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="offline",
    ),
    CliCommandContract(
        path=("system", "halt"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"system:admin"})),
        # 단일 success 경로 ``fmt.success(f"시스템 HALTED — {count}개 계좌
        # 거래 중지", data)`` (system.py:224) → standard envelope. IPC response
        # 의 ``data`` slot (``{accounts_changed, ...}``) 을 그대로 wrapping.
        output=OutputContract(kind="operation", envelope="standard"),
        execution="runtime_ipc",
        ipc_command="system.halt",
    ),
    CliCommandContract(
        path=("system", "clear-halt"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"system:admin"})),
        # 단일 success 경로 ``fmt.success(f"시스템 정지 해제 — ...", data)``
        # (system.py:242) → standard envelope. halt 동형 IPC wrapping.
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


# ── #1847 sub-PR 8: instrument domain OutputContract migration ──────────
#
# instrument 도메인 4 leaf 의 contract entry. ``src/ante/cli/commands/
# instrument.py`` 의 ``@require_scope`` marker 와 ``fmt.*`` 호출 패턴,
# 그리고 ``docs/specs/cli/03-commands.md:150`` (실행 분류) / ``691-704``
# (커맨드 표) 와 1:1 정합한다.
#
# raw_legacy 분류 (3 commands): ``list`` / ``sync`` / ``search`` 는 JSON
# 모드에서 ``fmt.output(dict)`` 또는 ``fmt.table(rows, columns)`` 평면
# dict / row list 를 그대로 dump 한다.
# - ``list`` (instrument.py:107/110): empty → ``fmt.output({"instruments":
#   [], "count": 0})`` 평면; non-empty → ``fmt.table(results, [symbol,
#   name, name_en, type, listed])`` row list.
# - ``sync`` (instrument.py:233-243): ``fmt.output({"sync_result": {...},
#   "message": "동기화 완료: ..."})`` 평면 — standard envelope 의 ``status``
#   키 부재이므로 raw_legacy. text 와 JSON 양쪽 동일 호출.
# - ``search`` (instrument.py:296/299): empty → ``fmt.output({"results":
#   [], "count": 0})`` 평면; non-empty → ``fmt.table(results, [symbol,
#   exchange, name, name_en, type])`` row list.
#
# standard / raw_legacy 분기 mixed (1 command): ``import`` 는 두 분기를
# 가진다.
# - dry-run 경로 (instrument.py:441-454): JSON → ``fmt.output({"dry_run":
#   True, "total": N, "preview": [...]})`` 평면 dict; text → click.echo +
#   fmt.table.
# - 실제 import 경로 (instrument.py:471-474): ``fmt.success(f"종목 import
#   완료: {count}건", {"count": count, "file": str(path)})`` standard
#   envelope.
# plan v2 mixed-branch policy (account ``set-credentials`` / bot ``signal-
# key`` / treasury ``set-balance`` / strategy ``set-status`` / data
# ``delete`` 동형) 에 따라 raw 우선으로 표현해 ``raw_legacy`` 로 lock.
# drift test 가 양쪽 분기를 모두 단언한다.
#
# scope 분류 (#1815 SSOT, instrument.py @require_scope marker 와 1:1 정합):
# - ``data:read`` scope (2 개): ``list`` / ``search``.
# - ``data:write`` scope (2 개): ``sync`` / ``import``.
# - public allowlist: 없음 — instrument 도메인은 ``_AUTH_EXEMPT_COMMAND_PATHS``
#   에 등재된 leaf 가 0 개다.
#
# execution 분류 (``docs/specs/cli/03-commands.md:150`` SSOT):
# - ``offline`` (4 개, 전체): 모든 instrument 명령은 local ``Database`` 와
#   ``InstrumentService`` 를 직접 생성한다. ``sync`` 는 ``KISAdapter`` 외부
#   호출이 있지만 spec 분류는 ``offline`` (runtime IPC handler 없음).
#   runtime IPC handler 없음.
INSTRUMENT_CONTRACTS: tuple[CliCommandContract, ...] = (
    CliCommandContract(
        path=("instrument", "list"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"data:read"})),
        # JSON mode: empty → ``fmt.output({"instruments": [], "count": 0})``
        # 평면 (instrument.py:107), non-empty → ``fmt.table(results, [...])``
        # row list (instrument.py:110). text 는 동일 fmt.table.
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="offline",
    ),
    CliCommandContract(
        path=("instrument", "sync"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"data:write"})),
        # JSON mode: ``fmt.output({"sync_result": {...}, "message": ...})``
        # 평면 dict (instrument.py:233-243). text 도 동일 호출.
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="offline",
    ),
    CliCommandContract(
        path=("instrument", "search"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"data:read"})),
        # JSON mode: empty → ``fmt.output({"results": [], "count": 0})``
        # 평면 (instrument.py:296), non-empty → ``fmt.table(results, [...])``
        # row list (instrument.py:299). text 는 동일 fmt.table.
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="offline",
    ),
    CliCommandContract(
        path=("instrument", "import"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"data:write"})),
        # 분기 mixed: dry-run JSON → ``fmt.output({"dry_run": True, "total":
        # N, "preview": [...]})`` 평면 (instrument.py:442-448); 실제 import
        # → ``fmt.success(f"종목 import 완료: {count}건", {"count": count,
        # "file": str(path)})`` standard envelope (instrument.py:471-474).
        # plan v2 mixed-branch policy (account ``set-credentials`` / bot
        # ``signal-key`` / treasury ``set-balance`` / strategy ``set-status``
        # / data ``delete`` 동형) — raw 우선으로 표현. drift test 가 양쪽
        # 분기를 단언한다.
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="offline",
    ),
)
"""Instrument domain 4 leaf 의 contract tuple (#1847 sub-PR 8).

순서는 ``docs/specs/cli/03-commands.md:691-704`` 의 instrument 표
(list → sync → search → import) 와 시각적으로 일치하도록 정렬된다.
``CLI_COMMAND_REGISTRY`` 에는 모듈 import 시 자동으로 등록된다.
"""


# ── #1847 sub-PR 8: config domain OutputContract migration ──────────────
#
# config 도메인 3 leaf 의 contract entry. ``src/ante/cli/commands/config.py``
# 의 ``@require_scope`` marker 와 ``fmt.*`` 호출 패턴, 그리고
# ``docs/specs/cli/03-commands.md:133-135`` (실행 분류) / ``564-571`` (커맨드
# 표) 와 1:1 정합한다.
#
# raw_legacy 분류 (3 commands, 전체): ``get`` / ``set`` / ``history`` 모두
# JSON 모드에서 ``fmt.output(dict)`` 평면 dict 를 그대로 dump 한다.
# - ``get`` (config.py:81/91): 단일 키 → ``fmt.output(result)`` 평면
#   (``{key, value, source}``); 전체 목록 → ``fmt.output({"configs":
#   result})`` 평면. text 는 click.echo.
# - ``set`` (config.py:182-184): ``fmt.output({"status": "success", **result})``
#   평면. ``status`` 키가 존재하나 값이 ``"success"`` (standard envelope 의
#   ``status == "ok"`` 와 다름) → raw_legacy 분류 (drift predicate 가
#   ``status == "ok"`` 만 standard 로 인정).
# - ``history`` (config.py:219): ``fmt.output({"key": key, "history": rows})``
#   평면. text 는 click.echo 다수 줄.
#
# scope 분류 (#1815 SSOT, config.py @require_scope marker 와 1:1 정합):
# - ``config:read`` scope (2 개): ``get`` / ``history``.
# - ``config:write`` scope (1 개): ``set``.
# - public allowlist: 없음 — config 도메인은 ``_AUTH_EXEMPT_COMMAND_PATHS``
#   에 등재된 leaf 가 0 개다.
#
# execution 분류 (``docs/specs/cli/03-commands.md:133-135`` SSOT):
# - ``offline`` (2 개): ``get`` / ``history``. 각 leaf 는 local ``Database``
#   와 ``DynamicConfigService`` 를 직접 생성한다.
# - ``runtime_ipc`` (1 개): ``set``. ``ipc_send("config.set", ...)`` 를
#   호출한다 (config.py:148). IPC handler 등록: ``ipc/registry.py:729``.
#
# ``ipc_command`` 필드는 stub 값만 채운다 (``"config.set"``); 단순 문자열
# lock 이며 server-side IPC registry 와의 cross-ref drift test 는 #1819
# 의 책임이다 (account/member/bot/approval/treasury/strategy/broker/system
# 동형 정책). config.py 호출 사이트의 IPC command name 과 그대로 일치한다.
CONFIG_CONTRACTS: tuple[CliCommandContract, ...] = (
    CliCommandContract(
        path=("config", "get"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"config:read"})),
        # JSON mode: 단일 키 → ``fmt.output(result)`` 평면 (``{key, value,
        # source}``, config.py:81); 전체 목록 → ``fmt.output({"configs":
        # result})`` 평면 (config.py:91). text 는 click.echo. missing 분기
        # (``source == "not_found"``) 는 fmt.error 이지만 success-output
        # drift scope 밖.
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="offline",
    ),
    CliCommandContract(
        path=("config", "set"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"config:write"})),
        # JSON mode: ``fmt.output({"status": "success", **result})`` 평면
        # (config.py:183-184). ``status`` 키가 존재하나 값이 ``"success"``
        # (standard envelope ``status == "ok"`` 와 다름) → raw_legacy 분류.
        # text 는 ``fmt.success(...)`` 호출 (config.py:186-189) 이지만 본
        # registry 는 JSON mode shape 를 SSOT 로 한다 (passthrough policy).
        # error 분기는 ``fmt.error`` 이며 success-output drift scope 밖.
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="runtime_ipc",
        ipc_command="config.set",
    ),
    CliCommandContract(
        path=("config", "history"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"config:read"})),
        # JSON mode: ``fmt.output({"key": key, "history": rows})`` 평면
        # (config.py:219). text 는 click.echo 다수 줄.
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="offline",
    ),
)
"""Config domain 3 leaf 의 contract tuple (#1847 sub-PR 8).

순서는 ``docs/specs/cli/03-commands.md:564-571`` 의 config 표
(get → set → history) 와 시각적으로 일치하도록 정렬된다.
``CLI_COMMAND_REGISTRY`` 에는 모듈 import 시 자동으로 등록된다.
"""


# ── #1847 sub-PR 8: rule domain OutputContract migration ────────────────
#
# rule 도메인 3 leaf 의 contract entry. ``src/ante/cli/commands/rule.py``
# 의 ``@require_scope`` marker 와 ``fmt.*`` 호출 패턴, 그리고
# ``docs/specs/cli/03-commands.md:120-122`` (실행 분류) / ``429-448`` (커맨드
# 표) 와 1:1 정합한다.
#
# raw_legacy 분류 (3 commands, 전체): ``list`` / ``info`` / ``update`` 모두
# JSON 모드에서 ``fmt.output(dict)`` 또는 ``fmt.table(rows, columns)`` 평면
# dict / row list 를 그대로 dump 한다.
# - ``list`` (rule.py:224/228/230): empty → ``fmt.output({"message": "등록된
#   룰이 없습니다.", "rules": []})`` 평면; non-empty JSON → ``fmt.output(
#   {"rules": result})`` 평면; non-empty text → fmt.table.
# - ``info`` (rule.py:276): ``fmt.output(result)`` 평면 detail dict
#   (``{rule_id, name, scope, enabled, priority, description}``). text 는
#   click.echo.
# - ``update`` (rule.py:412): JSON → ``fmt.output(result)`` 평면 dict
#   (IPC 응답 또는 cold_path response 평면 shape 그대로). text 는 click.echo.
#
# scope 분류 (#1815 SSOT, rule.py @require_scope marker 와 1:1 정합):
# - ``rule:read`` scope (2 개): ``list`` / ``info``.
# - ``rule:admin`` scope (1 개): ``update``.
# - public allowlist: 없음 — rule 도메인은 ``_AUTH_EXEMPT_COMMAND_PATHS``
#   에 등재된 leaf 가 0 개다.
#
# execution 분류 (``docs/specs/cli/03-commands.md:120-122`` SSOT):
# - ``offline`` (2 개): ``list`` / ``info``. 각 leaf 는 local ``Database`` /
#   ``RuleEngine`` 를 직접 생성한다.
# - ``runtime_ipc`` (1 개): ``update``. ``is_active_runtime()`` 분기로
#   ``ipc_send("rule.update", ...)`` 를 호출하고, runtime 비활성 시 cold_path
#   fallback 으로 ``update_account_rule_config`` 를 직접 사용한다. spec
#   primary 분류는 runtime_ipc 다 (account ``suspend``/``activate`` /
#   member ``update-scopes`` / treasury ``set-balance`` / strategy
#   ``set-status`` 동형 — fallback 분기가 있어도 spec primary 분류만 lock).
#
# ``ipc_command`` 필드는 stub 값만 채운다 (``"rule.update"``); 단순 문자열
# lock 이며 server-side IPC registry 와의 cross-ref drift test 는 #1819 의
# 책임이다. rule.py 호출 사이트의 IPC command name 과 그대로 일치한다.
# IPC handler 등록: ``ipc/registry.py:722``.
RULE_CONTRACTS: tuple[CliCommandContract, ...] = (
    CliCommandContract(
        path=("rule", "list"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"rule:read"})),
        # JSON mode: empty → ``fmt.output({"message": "등록된 룰이 없습니다.",
        # "rules": []})`` 평면 (rule.py:224); non-empty JSON → ``fmt.output(
        # {"rules": result})`` 평면 (rule.py:228); text → fmt.table
        # (rule.py:230). missing account / invalid account_id 분기는
        # fmt.error 이며 success-output drift scope 밖.
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="offline",
    ),
    CliCommandContract(
        path=("rule", "info"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"rule:read"})),
        # JSON mode: ``fmt.output(result)`` 평면 detail dict (``{rule_id,
        # name, scope, enabled, priority, description}``, rule.py:276).
        # text 는 click.echo 다수 줄. missing rule 분기는 fmt.error
        # (RULE_NOT_FOUND) 이며 success-output drift scope 밖.
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="offline",
    ),
    CliCommandContract(
        path=("rule", "update"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"rule:admin"})),
        # JSON mode: ``fmt.output(result)`` 평면 dict — IPC 분기와 cold_path
        # 분기 모두 동일 평면 shape (``{account_id, rule_type, rule: {...},
        # ...}``) 를 그대로 dump 한다 (rule.py:412). text 는 click.echo.
        # spec 은 ``runtime IPC`` 이며 ``is_active_runtime()`` 분기로
        # cold_path fallback 을 보유하지만 primary 분류만 lock.
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


# ── #1847 sub-PR 9 (final): trade domain OutputContract migration ───────
#
# trade 도메인 2 leaf 의 contract entry. ``src/ante/cli/commands/trade.py``
# 의 ``@require_scope`` marker 와 ``fmt.*`` 호출 패턴, 그리고
# ``docs/specs/cli/03-commands.md:383-394`` (trade 표) 와 1:1 정합한다.
#
# raw_legacy 분류 (2 commands, 전체): ``list`` / ``info`` 모두 JSON 모드에서
# ``fmt.output(dict)`` 또는 ``fmt.table(rows, columns)`` 평면 dict / row list
# 를 그대로 dump 한다.
# - ``list`` (trade.py:121/125/127): empty → ``fmt.output({"message": "거래
#   내역 없음", "trades": []})`` 평면; non-empty JSON → ``fmt.output(
#   {"trades": [...]})`` 평면; non-empty text → fmt.table.
# - ``info`` (trade.py:190): JSON → ``fmt.output(result)`` 평면 detail dict
#   (``{trade_id, bot_id, strategy_id, symbol, side, quantity, price, status,
#   timestamp, ...}``). text 는 click.echo 다수 줄. not-found 분기는
#   ``fmt.error("거래를 찾을 수 없습니다: ...", code="TRADE_NOT_FOUND")``
#   이며 success-output drift scope 밖.
#
# scope 분류 (#1815 SSOT, trade.py @require_scope marker 와 1:1 정합):
# - ``trade:read`` scope (2 개, 전체): ``list`` / ``info``.
# - public allowlist: 없음 — trade 도메인은 ``_AUTH_EXEMPT_COMMAND_PATHS``
#   에 등재된 leaf 가 0 개다.
#
# execution 분류 (``docs/specs/cli/03-commands.md:140`` SSOT — trade 는
# offline 분류):
# - ``offline`` (2 개, 전체): ``list`` / ``info``. 각 leaf 는 local
#   ``Database`` 와 ``TradeService`` / ``PositionHistory`` / ``TradeRecorder``
#   를 직접 생성한다. runtime IPC handler 없음.
TRADE_CONTRACTS: tuple[CliCommandContract, ...] = (
    CliCommandContract(
        path=("trade", "list"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"trade:read"})),
        # JSON mode: empty → ``fmt.output({"message": "거래 내역 없음",
        # "trades": []})`` 평면 (trade.py:121); non-empty JSON → ``fmt.output(
        # {"trades": [...]})`` 평면 (trade.py:125); text → fmt.table
        # (trade.py:127). inverted date range 분기는 ``fmt.error`` 이며
        # success-output drift scope 밖.
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="offline",
    ),
    CliCommandContract(
        path=("trade", "info"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"trade:read"})),
        # JSON mode: ``fmt.output(result)`` 평면 detail dict (trade.py:190)
        # — ``{trade_id, bot_id, strategy_id, symbol, side, quantity, price,
        # status, timestamp, ...}``. text 는 click.echo. not-found / generic
        # 오류 분기는 ``fmt.error`` 이며 success-output drift scope 밖.
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="offline",
    ),
)
"""Trade domain 2 leaf 의 contract tuple (#1847 sub-PR 9, final).

순서는 ``docs/specs/cli/03-commands.md:383-394`` 의 trade 표
(list → info) 와 시각적으로 일치하도록 정렬된다.
``CLI_COMMAND_REGISTRY`` 에는 모듈 import 시 자동으로 등록된다.
"""


# ── #1847 sub-PR 9 (final): backtest domain OutputContract migration ────
#
# backtest 도메인 2 leaf 의 contract entry. ``src/ante/cli/commands/
# backtest.py`` 의 ``@require_scope`` marker 와 ``fmt.*`` 호출 패턴, 그리고
# ``docs/specs/cli/03-commands.md:494-503`` (backtest 표) 와 1:1 정합한다.
#
# raw_legacy 분류 (2 commands, 전체): ``run`` / ``history`` 모두 JSON 모드에서
# ``fmt.output(result_dict)`` 또는 ``fmt.output(...)`` 평면 dict 를 그대로
# dump 한다.
# - ``run`` (backtest.py:173-181): ``fmt.output(result_dict, "Run ID:
#   {run_id}\\n...")`` 평면. ``result_dict`` 는 backtest 결과의 평면 shape
#   (``{strategy, period, total_return_pct, total_trades, final_balance,
#   trades, metrics, run_id, ...}``) 으로 standard envelope 3 키 셋과 다름.
#   text 모드는 template 으로 출력되고, JSON 모드는 평면 dict 그대로 dump.
# - ``history`` (backtest.py:262/269/271): empty → ``fmt.output({"message":
#   ..., "runs": []}, ...)`` 평면; non-empty JSON → ``fmt.output(
#   {"strategy_name": strategy_name, "runs": rows})`` 평면; non-empty text →
#   fmt.table. invalid date 분기는 ``fmt.error`` 이며 success-output drift
#   scope 밖.
#
# scope 분류 (#1815 SSOT, backtest.py @require_scope marker 와 1:1 정합):
# - ``backtest:run`` scope (2 개, 전체): ``run`` / ``history``.
# - public allowlist: 없음 — backtest 도메인은 ``_AUTH_EXEMPT_COMMAND_PATHS``
#   에 등재된 leaf 가 0 개다.
#
# execution 분류 (``docs/specs/cli/03-commands.md:149`` SSOT — backtest run
# 은 long-running, history 는 offline):
# - ``long_running`` (1 개): ``run``. 백테스트 실행은 progress bar 를 보여주는
#   장시간 작업이다. spec 표는 ``long-running`` 표기이며 본 registry 의
#   ExecutionClass vocab 매핑 (모듈 docstring normative 표) 에 따라
#   ``"long_running"`` 으로 분류.
# - ``offline`` (1 개): ``history``. local ``Database`` 와 ``BacktestRunStore``
#   를 직접 생성해 persisted run history 를 조회한다.
BACKTEST_CONTRACTS: tuple[CliCommandContract, ...] = (
    CliCommandContract(
        path=("backtest", "run"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"backtest:run"})),
        # JSON mode: ``fmt.output(result_dict, "Run ID: {run_id}\\n...")``
        # 평면 dict (backtest.py:173-181). ``result_dict`` 는 backtest 결과의
        # 평면 shape (strategy / period / total_return_pct / total_trades /
        # final_balance / trades / metrics / run_id) — standard envelope 3 키
        # 셋과 다르므로 raw_legacy. invalid date/exchange/timeframe/symbol /
        # generic error 분기는 ``fmt.error`` 이며 success-output drift scope
        # 밖.
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="long_running",
    ),
    CliCommandContract(
        path=("backtest", "history"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"backtest:run"})),
        # JSON mode: empty → ``fmt.output({"message": ..., "runs": []}, ...)``
        # 평면 (backtest.py:262-265); non-empty JSON → ``fmt.output(
        # {"strategy_name": strategy_name, "runs": rows})`` 평면 (backtest.py:
        # 269); non-empty text → fmt.table (backtest.py:271). generic error
        # 분기는 ``fmt.error`` 이며 success-output drift scope 밖.
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="offline",
    ),
)
"""Backtest domain 2 leaf 의 contract tuple (#1847 sub-PR 9, final).

순서는 ``docs/specs/cli/03-commands.md:494-503`` 의 backtest 표
(run → history) 와 시각적으로 일치하도록 정렬된다.
``CLI_COMMAND_REGISTRY`` 에는 모듈 import 시 자동으로 등록된다.
"""


# ── #1847 sub-PR 9 (final): audit domain OutputContract migration ───────
#
# audit 도메인 1 leaf 의 contract entry. ``src/ante/cli/commands/audit.py``
# 의 ``@require_scope`` marker 와 ``fmt.*`` 호출 패턴, 그리고
# ``docs/specs/cli/03-commands.md:710-720`` (audit 표) 와 1:1 정합한다.
#
# raw_legacy 분류 (1 command, 전체): ``list`` 는 JSON 모드에서 ``fmt.output(
# dict)`` 평면 dict 를 그대로 dump 한다.
# - ``list`` (audit.py:89/93/95): empty → ``fmt.output({"message": "감사
#   로그가 없습니다.", "logs": []})`` 평면; non-empty JSON → ``fmt.output(
#   {"logs": [...]})`` 평면; non-empty text → fmt.table. inverted date
#   range 분기는 ``fmt.error("INVALID_DATE_RANGE", ...)`` 이며 success-output
#   drift scope 밖.
#
# scope 분류 (#1815 SSOT, audit.py @require_scope marker 와 1:1 정합):
# - ``audit:read`` scope (1 개, 전체): ``list``.
# - public allowlist: 없음 — audit 도메인은 ``_AUTH_EXEMPT_COMMAND_PATHS``
#   에 등재된 leaf 가 0 개다.
#
# execution 분류 (``docs/specs/cli/03-commands.md`` SSOT — audit list 는
# offline 분류):
# - ``offline`` (1 개, 전체): ``list``. local ``Database`` 와 ``AuditLogger``
#   를 직접 생성해 persisted audit row 를 조회한다. runtime IPC handler 없음.
AUDIT_CONTRACTS: tuple[CliCommandContract, ...] = (
    CliCommandContract(
        path=("audit", "list"),
        auth=AuthContract(mode="scoped", scopes=frozenset({"audit:read"})),
        # JSON mode: empty → ``fmt.output({"message": "감사 로그가 없습니다.",
        # "logs": []})`` 평면 (audit.py:89); non-empty JSON → ``fmt.output(
        # {"logs": [...]})`` 평면 (audit.py:93); text → fmt.table
        # (audit.py:95). inverted date range 분기는 ``fmt.error`` 이며
        # success-output drift scope 밖.
        output=OutputContract(kind="raw", envelope="raw_legacy"),
        execution="offline",
    ),
)
"""Audit domain 1 leaf 의 contract tuple (#1847 sub-PR 9, final).

순서는 ``docs/specs/cli/03-commands.md:710-720`` 의 audit 표 (list 단일) 와
시각적으로 일치한다. ``CLI_COMMAND_REGISTRY`` 에는 모듈 import 시 자동으로
등록된다.
"""


# ── #1847 sub-PR 9 (final): signal domain OutputContract migration ──────
#
# signal 도메인 1 leaf 의 contract entry. ``src/ante/cli/commands/signal.py``
# 의 ``@require_auth`` marker 와 ``fmt.*`` 호출 패턴, 그리고
# ``docs/specs/cli/03-commands.md:721-727`` (signal 표) 와 1:1 정합한다.
#
# stream 분류 (1 command, 전체): ``connect`` 는 bidirectional JSON Lines
# 시그널 채널을 stdin/stdout 위로 수립한다 (long-running / streaming 실행).
# 일반 ``fmt.success`` / ``fmt.output`` 단일 envelope dump 는 *발생하지
# 않는다* — validation 실패 분기 (``_fail``) 만 JSON 모드에서 ``fmt.error(
# msg, code=...)`` envelope 을 dump 하고 즉시 SystemExit 한다 (signal.py:93-
# 104). 핸드셰이크 OK 후에는 CLI 가 데몬과 양방향 relay(``_pump_in`` /
# ``_pump_out``) 만 수행해 JSON Lines stream 을 stdin/stdout 위로 운반한다
# (#2338 thin IPC relay — in-process ``SignalChannel`` 미구성). fmt 계열 호출
# 없음. envelope SSOT (#1821) 의 ``ContractKind = "stream"`` 으로 분류한다.
#
# envelope 표기: 본 leaf 는 단일 envelope dump 가 없으므로 ``raw_legacy``
# 로 표시한다 — 일반 success/data envelope 이 부재하다는 의미를 본 registry
# 의 두 envelope 분류 (``standard`` / ``raw_legacy``) 안에서 표현하기 위한
# 정책. drift test 는 success-output dump 가 없음을 sanity 차원에서만 lock
# 한다 (registry envelope vocab 분류기 sanity 만 적용).
#
# auth 분류 (signal.py @require_auth marker — scope 없음):
# - public allowlist 미적용 (signal.py:25 의 ``@require_auth`` 데코레이터는
#   토큰 인증을 요구한다). scope 는 없으므로 ``authenticated`` 분류.
#
# execution 분류 (``docs/specs/cli/03-commands.md`` SSOT — signal connect
# 는 long-running / streaming 분류):
# - ``long_running`` (1 개, 전체): ``connect``. ``asyncio.run(_run_connect)``
#   가 데몬으로 ``signal.connect`` 핸드셰이크를 보낸 뒤 OK 면 동일 연결 위에서
#   ``gather(pump_in, pump_out)`` 양방향 relay (stream loop) 를 실행한다 (#2338
#   thin IPC relay — daemon-위임). 본 registry 의 ExecutionClass vocab 매핑
#   (모듈 docstring normative 표) 에 따라 ``"long_running"`` 으로 분류 (streaming
#   도 흡수).
SIGNAL_CONTRACTS: tuple[CliCommandContract, ...] = (
    CliCommandContract(
        path=("signal", "connect"),
        # signal.py:25 의 ``@require_auth`` 만 적용 — scope 없음.
        auth=AuthContract(mode="authenticated", scopes=frozenset()),
        # stream 채널 leaf: 단일 success envelope dump 가 없으므로 raw_legacy
        # 로 표시한다 (registry 의 두 envelope 분류 안에서 "envelope 부재"
        # 를 표현하기 위한 정책). kind="stream" 으로 streaming nature 를
        # 명시.
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
