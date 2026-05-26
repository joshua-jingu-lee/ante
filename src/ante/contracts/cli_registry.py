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
* :data:`CLI_COMMAND_REGISTRY` — leaf path tuple → contract mapping. 본
  PR 시점에는 account 9 + member 12 + bot 11 + approval 10 = 42 entries 가
  채워져 있다.
* :func:`get_contract` / :func:`all_contracts` — read-only accessor.

본 모듈이 의도적으로 *제공하지 않는* 것 (스펙 non-goal):

* 잔여 도메인 entry 등록 (`#1847` sub-PR 4 이후 — treasury / strategy /
  broker / data / report / system / instrument / config / rule / trade /
  backtest / audit / signal).
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
    "BOT_CONTRACTS",
    "CLI_COMMAND_REGISTRY",
    "MEMBER_CONTRACTS",
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


CLI_COMMAND_REGISTRY: dict[tuple[str, ...], CliCommandContract] = {
    contract.path: contract
    for contract in (
        *ACCOUNT_CONTRACTS,
        *MEMBER_CONTRACTS,
        *BOT_CONTRACTS,
        *APPROVAL_CONTRACTS,
    )
}
"""Leaf command path → contract mapping.

본 PR 시점에는 account 9 + member 12 + bot 11 + approval 10 = 42 entries
가 등록되어 있다 (#1846 / #1847 sub-PR 1 / #1847 sub-PR 2 / #1847 sub-PR
3). 나머지 도메인 (treasury / strategy / broker / data / report / system /
instrument / config / rule / trade / backtest / audit / signal) 의 entry
등록은 후속 PR (`#1847` sub-PR 4-9) 의 책임이다. registry 미등록 leaf 가
FAIL 이어야 하는 drift guard 는 `#1848` 가 활성화한다.
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

    본 PR 시점에는 account 9 + member 12 + bot 11 + approval 10 = 42
    entries 가 등록되어 있다 (#1846 / #1847 sub-PR 1 / #1847 sub-PR 2 /
    #1847 sub-PR 3).
    """
    yield from CLI_COMMAND_REGISTRY.values()
