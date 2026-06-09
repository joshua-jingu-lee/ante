"""docs/specs/ipc/ipc.md ↔ IPC ``CommandRegistry`` drift 가드.

Refs #1853 (#1819 epic 종결): ``docs/specs/ipc/ipc.md`` 의 IPC commands
taxonomy 두 표(런타임 커맨드 전수 목록 / Handler taxonomy)와
``register_all_handlers()`` 등록 결과를 cross-ref 한다. drift 가 생기면 즉시
실패시켜, 코드/스펙 한쪽만 갱신되는 회귀를 차단한다.

검출 대상:

1. docs 표에 있는 IPC command name 이 모두 registry 에 존재한다(스펙→코드).
2. registry 에 있는 27 commands 가 모두 docs 표(Handler taxonomy)에 등장한다
   (코드→스펙).
3. docs Handler taxonomy 의 ``mutating`` / ``read-only`` 분류가 registry 의
   ``is_mutating`` 값과 정확히 일치한다.

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


def _parse_docs_taxonomy_table() -> dict[str, str]:
    """``docs/specs/ipc/ipc.md`` Handler taxonomy 표를 ``{command: taxonomy}``
    매핑으로 파싱한다.

    표 형식: ``| `<command>` | mutating/read-only | <근거> |``. 표 헤더 라인
    ``| IPC 커맨드 | taxonomy | 근거 |`` 등장 이후의 ``|`` 시작 라인만 수집한다.
    """
    text = _IPC_SPEC_PATH.read_text(encoding="utf-8")
    lines = text.splitlines()

    # 표 시작 헤더 찾기.
    header_idx: int | None = None
    for idx, line in enumerate(lines):
        if (
            line.startswith("|")
            and "IPC 커맨드" in line
            and "taxonomy" in line
            and "근거" in line
        ):
            header_idx = idx
            break
    assert header_idx is not None, (
        "docs/specs/ipc/ipc.md Handler taxonomy 표 헤더를 찾지 못했습니다 — "
        "스펙 구조가 변경된 경우 본 파서를 동기화해야 합니다."
    )

    result: dict[str, str] = {}
    # 헤더 다음 줄은 alignment row (``| --- | --- | --- |``). 본문은 그 다음.
    for line in lines[header_idx + 2 :]:
        if not line.startswith("|"):
            break  # 표 종료
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 2:
            continue
        cmd_cell, tax_cell = cells[0], cells[1]
        match = re.match(r"`([^`]+)`", cmd_cell)
        if not match:
            continue
        cmd = match.group(1)
        if not any(cmd.startswith(p) for p in _IPC_COMMAND_PREFIXES):
            continue
        taxonomy = tax_cell.strip().lower()
        if taxonomy in {"mutating", "read-only"}:
            result[cmd] = taxonomy
    return result


def _parse_docs_runtime_commands() -> set[str]:
    """docs ``런타임 커맨드 전수 목록`` 영역(``## CLI 커맨드 분류`` 아래)에서
    백틱으로 감싼 IPC command name 을 수집한다.

    ``## IPCServer lifecycle state`` 절 이전까지를 범위로 본다. Handler
    taxonomy 영역은 별도 파서(``_parse_docs_taxonomy_table``)가 담당한다.
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


def test_registry_commands_all_present_in_docs_taxonomy(
    loaded_registry: CommandRegistry,
) -> None:
    """registry 27 commands 가 모두 docs Handler taxonomy 표에 등장한다.

    drift 시나리오: registry 에 새 handler 가 등록되었으나 docs Handler
    taxonomy 표가 갱신되지 않은 경우 → FAIL.
    """
    docs_taxonomy = _parse_docs_taxonomy_table()
    registry_cmds = set(loaded_registry.commands)
    missing = registry_cmds - set(docs_taxonomy.keys())
    assert not missing, (
        f"registry 등록 IPC commands 가 docs Handler taxonomy 표에 없습니다: "
        f"{sorted(missing)!r}. docs/specs/ipc/ipc.md Handler taxonomy 섹션을 "
        f"갱신하세요."
    )


def test_docs_taxonomy_is_mutating_matches_registry(
    loaded_registry: CommandRegistry,
) -> None:
    """docs Handler taxonomy 의 ``mutating`` / ``read-only`` 분류가 registry
    ``is_mutating`` 값과 일치한다.

    drift 시나리오: 코드의 ``is_mutating=True/False`` 와 docs 분류가 어긋난
    경우 → FAIL. ``SHUTTING_DOWN`` lifecycle gate(#1184)와 직접 연관된
    invariant 이므로 강한 lock.
    """
    docs_taxonomy = _parse_docs_taxonomy_table()
    mismatches: list[str] = []
    for spec in loaded_registry.iter_specs():
        docs_label = docs_taxonomy.get(spec.name)
        if docs_label is None:
            # 부재는 위 test 가 별도로 잡는다 — 본 test 는 분류 일치만 검사.
            continue
        expected = "mutating" if spec.is_mutating else "read-only"
        if docs_label != expected:
            mismatches.append(
                f"{spec.name}: docs={docs_label!r} but registry "
                f"is_mutating={spec.is_mutating}"
            )
    assert not mismatches, (
        "docs Handler taxonomy 와 registry is_mutating 분류 drift: "
        + "; ".join(mismatches)
    )
