"""Error taxonomy drift guard tests (#1841).

두 판정으로 drift 를 정적 sweep 으로 차단한다:

* Family B — ``*Error`` class 가 class-level ``code`` 도 없고
  ``EXCEPTION_TO_SPEC`` 에도 등록 안 됨 (=``EXECUTION_ERROR`` 로 접힘).
* Staleness — allowlist entry 가 더 이상 존재하지 않는 class 를 가리키면 검출.

baseline 은 ``error_drift_allowlist.yaml`` 에 구조화 보관되며, 신규/수정
drift 만 본 test 가 차단한다. code 없는 ``fmt.error`` (옛 Family A) 는
진입점 래칫 ``cli_error_calls`` 가 막는다 (#2738).

Anchor 정책 (#1841 plan): exception entry 는 ``(module, class_anchor)`` 2중 anchor.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from ante.contracts.error_registry import EXCEPTION_TO_SPEC
from tests.unit.contracts.helpers import (
    iter_exception_classes,
    load_drift_allowlist,
)

# ── 공통 경로 ─────────────────────────────────────────────────────────────────

# tests/unit/contracts/test_error_drift.py → parents[3] == repository root.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_SRC_ROOT = _REPO_ROOT / "src" / "ante"
_ALLOWLIST_PATH = Path(__file__).with_name("error_drift_allowlist.yaml")


def _module_dotted(path: Path) -> str:
    """``src/ante/foo/bar.py`` → ``ante.foo.bar`` (allowlist module key 형식)."""
    rel = path.resolve().relative_to(_REPO_ROOT / "src")
    return str(rel.with_suffix("")).replace("/", ".")


# ── Family B — domain exception EXECUTION_ERROR 접힘 drift ──────────────────


def _registry_module_names() -> set[tuple[str, str]]:
    """``EXCEPTION_TO_SPEC`` 의 ``(module, class_name)`` 짝 집합.

    #1842 가 ``ante.account.errors.InvalidBrokerTypeError`` 를 registry 에
    등록하면서, 동명의 별개 class 인 ``ante.broker.registry.InvalidBrokerTypeError``
    가 이름만 비교하던 이전 staleness scanner 에서 stale 판정을 받는 회귀가
    발견되었다. helper 의 MRO lookup 은 type 기반이라 두 class 를 정확히
    분리하므로, drift test 도 ``(module, class_name)`` 2중 anchor 로 정렬해
    동명 별개 class 가 서로의 보호 면적을 침범하지 않도록 한다.
    """

    return {(cls.__module__, cls.__name__) for cls in EXCEPTION_TO_SPEC.keys()}


def test_exception_classes_have_code_or_registry_or_allowlisted() -> None:
    """모든 ``*Error`` class 는 다음 중 하나여야 한다.

    1. class-level ``code`` 속성 보유 (``has_code == True``).
    2. ``EXCEPTION_TO_SPEC`` 에 등록되어 helper 가 ErrorSpec 을 resolve.
    3. ``pending_migration`` allowlist 에 등록 (baseline, #1842/#1843
       후속 작업으로 단계 제거).

    셋 모두에 해당하지 않는 class 는 ``EXECUTION_ERROR`` 로 fallback 되어
    taxonomy drift 가 발생한다.

    #1842: 동명 별개 class 를 정확히 분리하기 위해 registry membership 판정
    을 ``(module, name)`` 2중 anchor 로 한다 (allowlist entry shape 와 정렬).
    """
    registry_module_names = _registry_module_names()
    allowlist = load_drift_allowlist()
    allowed: set[tuple[str, str]] = {
        (entry.module, entry.class_anchor) for entry in allowlist.pending_migration
    }

    drift: list[str] = []
    for exc in iter_exception_classes(_SRC_ROOT):
        if exc.has_code:
            continue
        module = _module_dotted(exc.path)
        if (module, exc.name) in registry_module_names:
            continue
        if (module, exc.name) in allowed:
            continue
        drift.append(f"{module}::{exc.name} (L{exc.lineno})")

    assert not drift, (
        "*Error class 가 class-level code 도 없고 EXCEPTION_TO_SPEC 에도 "
        "등록되지 않았다. class 에 code 속성을 추가하거나 registry 에 "
        "등록하거나 tests/unit/contracts/error_drift_allowlist.yaml 의 "
        "pending_migration 에 추가하라.\n" + "\n".join(drift)
    )


# ── Staleness — allowlist entry 의 anchor 가 실존하는지 검증 ─────────────────


def _scan_exception_anchors() -> set[tuple[str, str]]:
    """현재 source 에서 검출되는 모든 code-less, registry-미등록 ``*Error`` anchor.

    #1842: registry membership 판정을 ``(module, name)`` 2중 anchor 로 한다 —
    동명 별개 class (예: ``account.errors.InvalidBrokerTypeError`` vs
    ``broker.registry.InvalidBrokerTypeError``)가 서로의 staleness 보호 면적을
    침범하지 않게 한다.
    """
    registry_module_names = _registry_module_names()
    anchors: set[tuple[str, str]] = set()
    for exc in iter_exception_classes(_SRC_ROOT):
        if exc.has_code:
            continue
        module = _module_dotted(exc.path)
        if (module, exc.name) in registry_module_names:
            continue
        anchors.add((module, exc.name))
    return anchors


def test_drift_allowlist_no_stale_exception_entries() -> None:
    """allowlist 의 exception entry 는 현재 source 에 anchor 가 존재해야 한다.

    class 가 EXCEPTION_TO_SPEC 에 등록되었거나, class-level code 속성을
    부여받았거나, class 가 삭제/이동되면 stale entry 가 된다.
    """
    allowlist = load_drift_allowlist()
    actual = _scan_exception_anchors()

    stale = [
        f"{entry.module}::{entry.class_anchor}"
        for entry in allowlist.pending_migration
        if (entry.module, entry.class_anchor) not in actual
    ]

    assert not stale, (
        "drift allowlist 의 exception entry 가 더 이상 source 에 매치하지 "
        "않는다. class 가 EXCEPTION_TO_SPEC 에 등록되었거나 code 속성을 "
        "얻었으면 allowlist 에서 제거하라.\n" + "\n".join(stale)
    )


# ── 회귀 시연 anchor (#1841 plan verification) ───────────────────────────────


def test_drift_allowlist_has_only_pending_migration() -> None:
    """allowlist YAML 의 section 은 ``pending_migration`` 하나다 (구조 lock)."""
    data = yaml.safe_load(_ALLOWLIST_PATH.read_text(encoding="utf-8"))
    assert set(data) == {"pending_migration"}
    assert load_drift_allowlist().pending_migration
