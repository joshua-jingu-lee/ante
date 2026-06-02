"""CLI registry ``runtime_ipc`` ↔ IPC ``CommandRegistry`` drift 가드.

Refs #1853 (#1819 epic 종결): ``src/ante/contracts/cli_registry.py`` 의
``execution="runtime_ipc"`` entries 가 가리키는 ``ipc_command`` 가 실제로
``ante.ipc.registry.register_all_handlers()`` 에 등록된 commands 중
하나이거나, ``EXPECTED_MISSING_IPC_COMMANDS`` baseline (후속 wiring stub —
docs/specs/ipc/ipc.md 명시) 중 하나여야 한다.

baseline 밖의 미존재 (예: 오타, 명칭 변경 누락) → 즉시 FAIL.

baseline entries 의 후속 wiring 은 별도 child issue 에서 점진 제거되며,
removal 시 본 모듈의 ``EXPECTED_MISSING_IPC_COMMANDS`` 도 함께 갱신해야 한다
(SSOT 한쪽만 갱신되는 회귀를 본 test 가 차단).

Refs #2112: ``bot.list`` / ``bot.info`` / ``bot.positions`` /
``bot.signal_key`` (read) 4건이 ``register_all_handlers()`` 에 wiring 되어
baseline 에서 제거되었다 (12→8). 잔여 baseline 은 member.* 8건이었다.

Refs #2113: member admin mutation 8건(``member.register`` / ``member.set_emoji``
/ ``member.suspend`` / ``member.reactivate`` / ``member.revoke`` /
``member.rotate_token`` / ``member.reset_password`` /
``member.regenerate_recovery_key``)이 ``register_all_handlers()`` 에 wiring
되어 baseline 에서 제거되었다 (8→0). baseline 이 비었다.
"""

from __future__ import annotations

import pytest

from ante.contracts.cli_registry import all_contracts
from ante.ipc.registry import CommandRegistry, register_all_handlers

# ``docs/specs/ipc/ipc.md`` 명시 — ``register_all_handlers()`` 에 아직 wiring
# 되지 않은 commands. CLI registry 의 ``ipc_command`` stub 값은 후속 wiring
# 이슈로 점진 제거된다.
#
# Refs #2113: member.* 8 (ipc.md:160-168 표) 이 모두 wiring 완료되어 baseline
# 이 비었다 (8→0). bot.* 4 는 #2112 에서, member.* 8 은 #2113 에서 제거.
EXPECTED_MISSING_IPC_COMMANDS: frozenset[str] = frozenset()


@pytest.fixture
def loaded_registry() -> CommandRegistry:
    registry = CommandRegistry()
    register_all_handlers(registry)
    return registry


def test_baseline_size_locked() -> None:
    """baseline 크기를 8 로 lock — 후속 wiring 이슈가 줄여나갈 때 본 lock 도
    함께 갱신해야 한다 (SSOT 동기화 강제).

    Refs #2112: bot.* read 4건 wiring 완료로 12→8.
    Refs #2113: member.* 8건 wiring 완료로 8→0 (baseline 비었음)."""
    assert len(EXPECTED_MISSING_IPC_COMMANDS) == 0, (
        f"baseline size={len(EXPECTED_MISSING_IPC_COMMANDS)}; "
        "후속 wiring 이슈에서 baseline 항목을 제거했다면 본 lock 도 함께 갱신."
    )


def test_cli_runtime_ipc_entries_reference_registered_or_baseline(
    loaded_registry: CommandRegistry,
) -> None:
    """CLI ``execution="runtime_ipc"`` entries 의 ``ipc_command`` 값은
    ``CommandRegistry`` 에 등록되어 있거나 ``EXPECTED_MISSING_IPC_COMMANDS``
    baseline 에 등록되어 있어야 한다.

    drift 시나리오: CLI registry 에 새 runtime_ipc entry 가 추가되었으나
    IPC ``register_all_handlers()`` 에 wiring 되지 않았고 baseline 에도 없는
    경우 → FAIL. baseline 추가는 후속 wiring 이슈와 동기화된 의도적 결정만
    허용한다.
    """
    registered = set(loaded_registry.commands)
    failures: list[str] = []
    for contract in all_contracts():
        if contract.execution != "runtime_ipc":
            continue
        ipc_cmd = contract.ipc_command
        if ipc_cmd is None:
            failures.append(
                f"CLI {'.'.join(contract.path)!r} execution=runtime_ipc 인데 "
                "ipc_command=None — runtime IPC entries 는 반드시 IPC "
                "command name 을 stub 으로라도 보유해야 합니다."
            )
            continue
        if ipc_cmd in registered:
            continue
        if ipc_cmd in EXPECTED_MISSING_IPC_COMMANDS:
            continue
        failures.append(
            f"CLI {'.'.join(contract.path)!r} → ipc_command={ipc_cmd!r} "
            "이 IPC CommandRegistry 에도 EXPECTED_MISSING_IPC_COMMANDS "
            "baseline 에도 없습니다. ``register_all_handlers()`` 에 wiring "
            "하거나 baseline 에 등록하세요."
        )
    assert not failures, "CLI runtime_ipc cross-ref drift:\n" + "\n".join(failures)


def test_baseline_does_not_overlap_registered(
    loaded_registry: CommandRegistry,
) -> None:
    """baseline 항목이 실제 registered command 와 겹치지 않는다.

    drift 시나리오: 후속 wiring 으로 IPC handler 가 등록되었는데 baseline 에서
    제거하지 않은 경우 → FAIL. baseline 은 "아직 wiring 안 됨" 의미이므로
    registered 와 disjoint 해야 한다.
    """
    registered = set(loaded_registry.commands)
    overlap = EXPECTED_MISSING_IPC_COMMANDS & registered
    assert not overlap, (
        f"baseline 항목이 이미 IPC CommandRegistry 에 등록되어 있습니다: "
        f"{sorted(overlap)!r}. wiring 이 완료된 항목은 baseline 에서 제거해야 "
        "합니다."
    )


def test_baseline_entries_have_cli_runtime_ipc_reference() -> None:
    """baseline 의 모든 항목은 CLI registry 에 ``runtime_ipc`` entry 로 실제로
    참조되어야 한다 (dead baseline 방지).

    drift 시나리오: CLI 에서 entry 가 제거되었거나 ``execution`` 이 변경되어
    더 이상 baseline 이 의미 없게 된 경우 → FAIL.
    """
    cli_ipc_refs: set[str] = set()
    for contract in all_contracts():
        if contract.execution == "runtime_ipc" and contract.ipc_command:
            cli_ipc_refs.add(contract.ipc_command)
    dead = EXPECTED_MISSING_IPC_COMMANDS - cli_ipc_refs
    assert not dead, (
        f"baseline 에 있으나 CLI runtime_ipc 참조가 없는 항목 (dead baseline): "
        f"{sorted(dead)!r}. CLI registry 변경에 맞춰 baseline 도 정리하세요."
    )
