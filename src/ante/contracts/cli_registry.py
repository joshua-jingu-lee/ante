"""CLI command contract registry shell (#1844).

`#1815` 부모 epic 의 첫 코드 결과물. CLI command 별 auth / output /
execution 계약을 한 곳에서 관리하기 위한 *report-only* registry shell 을
정의한다. 본 모듈은 **빈 registry** 만 노출하며, 실제 command 별
contract entry 등록은 후속 PR (`#1846` account / `#1847` remaining) 의
책임이다.

본 모듈이 제공하는 것:

* :class:`AuthContract` — auth mode + scope frozenset (#1815 normative).
* :class:`OutputContract` — result shape + envelope + data slot.
* :class:`CliCommandContract` — root-to-leaf command path + 3 sub-contract +
  execution class + (optional) IPC command name.
* :data:`CLI_COMMAND_REGISTRY` — leaf path tuple → contract mapping. 본
  PR 시점에는 **빈 dict** 다.
* :func:`get_contract` / :func:`all_contracts` — read-only accessor.

본 모듈이 의도적으로 *제공하지 않는* 것 (스펙 non-goal):

* 실제 command entry 등록 (`#1846` / `#1847`).
* output payload migration.
* drift test guard (registry 미등록 leaf 가 FAIL 이어야 하는 시점은
  `#1845` / `#1848` 의 책임).
* IPC server-side metadata (`#1819`).
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
    "CLI_COMMAND_REGISTRY",
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


CLI_COMMAND_REGISTRY: dict[tuple[str, ...], CliCommandContract] = {}
"""Leaf command path → contract mapping.

본 PR 시점에는 **빈 dict** 다. 실제 command entry 등록은 후속 PR
(`#1846` account / `#1847` remaining) 의 책임이며, 그 시점에 본 dict 가
in-place mutate 되는 것이 정상 운용이다. registry 미등록 leaf 가 FAIL
이어야 하는 drift guard 는 `#1845` / `#1848` 가 활성화한다 — 본 PR 의
:mod:`tests.unit.contracts.test_cli_registry_leaf_coverage` 는
report-only baseline 이다.
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

    본 PR 시점에는 빈 iterator 다 — registry entry 가 0 이다.
    """
    yield from CLI_COMMAND_REGISTRY.values()
