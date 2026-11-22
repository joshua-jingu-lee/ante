"""docs/specs/ipc/ipc.md ↔ IPC ``CommandRegistry`` drift 가드.

Refs #1853 (#1819 epic 종결): ``docs/specs/ipc/ipc.md`` 의 런타임 커맨드 전수
목록에 있는 IPC command name 이 모두 ``register_all_handlers()`` 에 등록되어
있는지 본다(스펙→코드). 등록된 명령마다의 taxonomy 와 코드→스펙 방향은
레지스트리에서 생성한 ``docs/architecture/generated/ipc-commands.md`` 를
``scripts/generate_ipc_commands.py --check`` 가 대조한다(#2683).

본 테스트는 IPC envelope shape 이나 args schema 를 검증하지 않는다. 그 책임은
``tests/unit/ipc/test_registry.py`` 와 contracts 모듈 테스트에 있다.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from ante.ipc.registry import CommandRegistry, register_all_handlers

# ``docs/specs/ipc/ipc.md`` 절대 경로 — repo root 기반 resolve.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_IPC_SPEC_PATH = _REPO_ROOT / "docs" / "specs" / "ipc" / "ipc.md"


# 도메인 prefix 화이트리스트. docs 표의 ``IPC 커맨드`` 컬럼에 나오는 백틱
# inline literal 중 이 prefix 로 시작하는 토큰만 IPC command name 후보로
# 수집한다(``ipc.bot.create`` context 문자열, ``BotManager.create_bot()`` 같은
# 호출 표기는 제외).
_IPC_COMMAND_PREFIXES = (
    "system.",
    "account.",
    "bot.",
    "treasury.",
    "rule.",
    "strategy.",
    "member.",
    "config.",
    "approval.",
    "broker.",
    # Refs #2334 (#2336 PR#1): signal.connect drift lock 활성화. prefix 추가
    # 전에는 docs 의 signal.* row 가 silent skip(dead lock) 됐다.
    "signal.",
)

# docs 표에는 등장하지만 IPC ``CommandRegistry`` 등록 대상이 아닌 토큰.
# ipc.md:97-103 / 273-276 명시: 후속 wiring 대상, cold-path 전용, 또는 표
# 본문 prose 에서 언급된 contextual command name.
_DOCS_NON_REGISTRY_TOKENS = frozenset(
    {
        # Refs #2113: member.* 8 (register/set_emoji/suspend/reactivate/revoke/
        # rotate_token/reset_password/regenerate_recovery_key) 이 모두
        # ``register_all_handlers()`` 에 wiring 되어 화이트리스트에서 제거됨.
        # cold-path 전용 — ipc.md:70-74 / 193 / 273
        "account.delete",
        "account.create",
        "account.set_credentials",
    }
)
# Refs #2112: 종전 ``bot.query`` placeholder 토큰은 ``bot.list`` / ``bot.info`` /
# ``bot.positions`` / ``bot.signal_key`` (read) 4건 wiring 완료로 docs/specs/
# ipc.md 에서 제거되었고, 4건은 모두 ``register_all_handlers()`` 에 등록되므로
# non-registry 화이트리스트에서 더 이상 필요 없다.


def _parse_docs_runtime_commands() -> set[str]:
    """docs ``런타임 커맨드 전수 목록`` 영역(``## CLI 커맨드 분류`` 아래)에서
    백틱으로 감싼 IPC command name 을 수집한다.

    ``## IPCServer lifecycle state`` 절 이전까지를 범위로 본다.
    """
    text = _IPC_SPEC_PATH.read_text(encoding="utf-8")
    start_match = re.search(r"^## CLI 커맨드 분류", text, flags=re.MULTILINE)
    end_match = re.search(r"^## IPCServer lifecycle state", text, flags=re.MULTILINE)
    assert start_match is not None and end_match is not None, (
        "docs/specs/ipc/ipc.md 의 런타임 커맨드 분류 절 경계를 찾지 못했습니다."
    )
    section = text[start_match.end() : end_match.start()]
    tokens = re.findall(r"`([^`]+)`", section)
    found: set[str] = set()
    for tok in tokens:
        if not any(tok.startswith(p) for p in _IPC_COMMAND_PREFIXES):
            continue
        # ``ipc.bot.create`` 같은 context 문자열 제외 (앞에 ``ipc.`` 가 붙음).
        if tok.startswith("ipc."):
            continue
        # python attribute/index 표기는 IPC command name 아님
        # (예: ``account.credentials["app_key"]``).
        if any(ch in tok for ch in '[]()" '):
            continue
        found.add(tok)
    return found


@pytest.fixture
def loaded_registry() -> CommandRegistry:
    registry = CommandRegistry()
    register_all_handlers(registry)
    return registry


def test_docs_runtime_section_commands_exist_in_registry(
    loaded_registry: CommandRegistry,
) -> None:
    """docs 런타임 커맨드 표의 모든 IPC command (후속 wiring stub 제외) 이
    registry 에 등록되어 있다.

    drift 시나리오: docs 에 새 command 가 추가되었으나 ``register_all_handlers``
    가 갱신되지 않은 경우 → FAIL.
    """
    docs_cmds = _parse_docs_runtime_commands()
    registry_cmds = set(loaded_registry.commands)
    # docs 에 명시된 후속 wiring stub 은 검증에서 제외.
    docs_expected = docs_cmds - _DOCS_NON_REGISTRY_TOKENS
    missing = docs_expected - registry_cmds
    assert not missing, (
        f"docs 런타임 커맨드 절에 명시된 IPC commands 가 registry 에 없습니다: "
        f"{sorted(missing)!r}. ``register_all_handlers()`` 또는 docs/specs/ipc/"
        f"ipc.md 중 한쪽이 누락된 drift 입니다."
    )
