"""CLI registry ↔ docs command table drift tests (#1848 Family A).

#1815 epic 의 마지막 sub. ``src/ante/contracts/cli_registry.py`` 의
``CLI_COMMAND_REGISTRY`` 와 ``docs/specs/cli/03-commands.md`` 의 ``| ante ... |``
표 행에서 추출한 command path 집합을 양방향 비교한다.

두 invariant 를 강제한다:

* **registry → docs**: registry 의 모든 leaf path 는 docs 표에 반드시 등장한다.
  registry 가 새 leaf 를 등록했는데 docs 표에 누락되면 본 테스트가 FAIL 한다
  (allowlist 우회 없음 — 본 방향은 baseline 0 invariant).
* **docs → registry**: docs 표에 등장하는 path 중 registry 미등록인 path 는
  ``docs_drift_allowlist.yaml`` 에 baseline 으로 등록된 set 과 일치해야 한다.
  새 docs row 가 추가되었는데 registry 미등록이면 본 테스트가 FAIL 한다.

본 PR (#1848) 시점에 baseline 등록된 9 path 는 #1815 epic 본문이 명시한
leaf coverage 잔여 11 leaves + docs aggregated group row + notification group
의 carry-over 다. 본 baseline 의 *사유* 는 ``docs_drift_allowlist.yaml`` 의
inline 주석을 참조한다.

본 테스트는 docs 본문이나 registry entries 를 *수정* 하지 않는다. drift 검출만
한다 — 보정은 별도 PR 에서 처리한다는 #1848 stop condition 을 따른다.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ante.contracts.cli_registry import CLI_COMMAND_REGISTRY
from tests.unit.contracts.helpers import collect_docs_command_paths

# ── fixtures / paths ────────────────────────────────────────────────────────


def _repo_root() -> Path:
    """본 test file 기준 repo root 를 절대 경로로 반환한다.

    ``tests/unit/contracts/test_cli_registry_docs_drift.py`` → 3 단계 위.
    """
    return Path(__file__).resolve().parent.parent.parent.parent


def _docs_path() -> Path:
    return _repo_root() / "docs" / "specs" / "cli" / "03-commands.md"


def _allowlist_path() -> Path:
    return Path(__file__).resolve().parent / "docs_drift_allowlist.yaml"


# ── allowlist loader ────────────────────────────────────────────────────────


def _load_docs_only_allowlist() -> frozenset[tuple[str, ...]]:
    """``docs_drift_allowlist.yaml`` 의 ``docs_only_paths`` section 을 로드한다.

    YAML 의 ``path`` 필드는 list[str] 로 저장되며, 본 helper 가 tuple 로 정규화
    한다. ``reason`` 은 test 가 참조하지 않는다 (사람 리뷰 근거 용).
    """
    data = yaml.safe_load(_allowlist_path().read_text(encoding="utf-8")) or {}
    raw = data.get("docs_only_paths") or []
    return frozenset(tuple(item["path"]) for item in raw)


# ── tests ───────────────────────────────────────────────────────────────────


def test_registry_paths_are_subset_of_docs() -> None:
    """registry 의 모든 leaf path 는 docs 표에 등장해야 한다 (baseline 0).

    allowlist 우회 없음. registry 가 새 leaf 를 등록했는데 docs 표에 누락된
    경우 본 테스트가 FAIL 한다. drift 발견 시 docs 표를 갱신해야 한다.

    본 방향의 baseline 이 0 인 이유는 #1815 epic 본문이 명시했듯 registry 가
    docs SSOT 의 *부분집합* 이어야 하기 때문이다 — docs 는 group aggregated
    row 같은 추가 entry 를 가질 수 있지만, registry 의 모든 leaf 는 반드시
    docs 표에 등장해야 한다.
    """
    docs_paths = collect_docs_command_paths(_docs_path())
    registry_paths = frozenset(CLI_COMMAND_REGISTRY.keys())

    missing = registry_paths - docs_paths
    assert not missing, (
        "CLI_COMMAND_REGISTRY 에 등록된 leaf 가 docs/specs/cli/03-commands.md "
        f"표에 누락됨 (count={len(missing)}): {sorted(missing)}. "
        "docs 표를 갱신하거나 registry entry 를 제거할 것."
    )


def test_docs_only_paths_match_baseline() -> None:
    """docs 표에 등장하지만 registry 미등록인 path 는 baseline 과 일치해야 한다.

    새 docs row 가 추가되었는데 registry 미등록이면 본 테스트가 FAIL 한다.
    drift 발견 시 두 선택지가 있다:

    * registry 에 해당 leaf 를 등록 (선호) — docs 가 SSOT.
    * 의도적 carry-over 면 ``docs_drift_allowlist.yaml`` 에 sustained rationale
      과 함께 등록하고 본 baseline 을 갱신.

    본 테스트는 양방향 동치를 강제한다: baseline 에 있지만 docs 에서 사라진
    path 도 FAIL — stale entry 가 누적되지 않도록 sanity 한다.
    """
    docs_paths = collect_docs_command_paths(_docs_path())
    registry_paths = frozenset(CLI_COMMAND_REGISTRY.keys())
    baseline = _load_docs_only_allowlist()

    actual_docs_only = docs_paths - registry_paths

    unexpected_new = actual_docs_only - baseline
    assert not unexpected_new, (
        "docs/specs/cli/03-commands.md 표에 등장하지만 registry 미등록이고 "
        f"baseline 에도 없는 path (count={len(unexpected_new)}): "
        f"{sorted(unexpected_new)}. "
        "registry 에 등록하거나 docs_drift_allowlist.yaml 의 docs_only_paths "
        "section 에 사유와 함께 추가할 것."
    )

    stale_baseline = baseline - actual_docs_only
    assert not stale_baseline, (
        "docs_drift_allowlist.yaml 의 docs_only_paths 에 등록되어 있지만 "
        f"실제 docs 표 - registry 차집합에는 없는 stale entry "
        f"(count={len(stale_baseline)}): {sorted(stale_baseline)}. "
        "registry 에 새로 등록되어 더 이상 carry-over 가 아니거나 docs 에서 "
        "행이 삭제되었다면 baseline 에서도 entry 를 제거할 것."
    )


def test_docs_command_paths_extraction_smoke() -> None:
    """parser smoke test — docs 표가 최소 한 자릿수 이상의 path 를 생성한다.

    구조적 회귀 (예: 정규식이 zero-match 가 되거나 file path 가 잘못 변경되어
    텍스트가 empty 가 되는 경우) 를 빠르게 잡는다.
    """
    docs_paths = collect_docs_command_paths(_docs_path())
    # 본 PR 시점 docs 표는 약 100 개 distinct command path 를 가지므로 50 을
    # 최소선으로 잡는다 — 향후 docs 가 크게 축소되어도 50 이하면 invariant 위반.
    assert len(docs_paths) >= 50, (
        f"docs/specs/cli/03-commands.md 에서 추출된 command path 가 너무 적음 "
        f"({len(docs_paths)} < 50). 표 parser 또는 docs 파일 자체에 회귀 의심."
    )


@pytest.mark.parametrize(
    "expected_known_path",
    [
        ("init",),
        ("update",),
        ("feed", "init"),
        ("notification",),
    ],
)
def test_known_docs_only_paths_present_in_baseline(
    expected_known_path: tuple[str, ...],
) -> None:
    """#1815 epic 본문이 명시한 known carry-over 가 baseline 에 등록되어 있다.

    Smoke regression — baseline 파일이 의도치 않게 빈 list 로 회귀하거나
    epic 문서가 명시한 carry-over set 이 누락되면 즉시 FAIL 한다. 본 테스트
    자체는 baseline 의 *완전성* 을 강제하지 않는다 (full 동치는
    :func:`test_docs_only_paths_match_baseline` 가 본다). 본 테스트는 epic 의
    핵심 4 carry-over 가 사라지지 않는지만 본다.
    """
    baseline = _load_docs_only_allowlist()
    assert expected_known_path in baseline, (
        f"#1815 epic 본문이 명시한 carry-over path {expected_known_path!r} 가 "
        "docs_drift_allowlist.yaml 의 docs_only_paths 에 누락됨. "
        "epic 본문과 baseline 의 정합성을 확인할 것."
    )
