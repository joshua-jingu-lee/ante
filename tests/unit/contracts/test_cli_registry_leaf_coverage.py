"""CLI contract registry leaf coverage report (#1844).

본 test 는 **report-only** 다. 본 PR 시점에 :data:`CLI_COMMAND_REGISTRY`
는 빈 dict 이므로 registered/total ratio 는 0 이며, 누락 leaf 가
FAIL 을 만들지 않는다 — 그 enforcement 는 `#1845` (drift guard) /
`#1848` (final coverage) 의 책임이다.

본 test 가 확인하는 것:

* :func:`tests.unit.contracts.helpers.iter_click_leaf_commands` 가 적어도
  1 개 이상 leaf 를 yield 한다 (skeleton 동작 확인).
* 누락 leaf 목록을 stdout 으로 print (``pytest -s`` 시 확인 가능) —
  후속 PR 가 채울 작업 분량 가시화.
* 등록 카운트 baseline (본 PR 시점 0) 을 print 한다.

본 test 가 *하지 않는 것*:

* 누락 leaf 에 대한 FAIL — `#1845` / `#1848`.
* leaf path normalization 정책 lock — `#1845`.
* helper hidden-subtree exclusion 검증 — :mod:`tests.unit.contracts.test_helpers`
  가 이미 lock 한다.
"""

from __future__ import annotations

from ante.contracts.cli_registry import CLI_COMMAND_REGISTRY
from tests.unit.contracts.helpers import iter_click_leaf_commands


def test_cli_registry_leaf_coverage_report() -> None:
    leaves = {leaf.path for leaf in iter_click_leaf_commands()}
    registered = set(CLI_COMMAND_REGISTRY.keys())
    missing = leaves - registered
    extraneous = registered - leaves

    # report-only — stdout 으로 카운트 출력.
    total = len(leaves)
    print(
        f"\nCLI registry coverage (baseline #1844): "
        f"{len(registered)}/{total} leaves registered"
    )
    if missing:
        sample = sorted(missing)[:10]
        print(f"  Missing sample (first {len(sample)} of {len(missing)}):")
        for path in sample:
            print(f"    - {path}")
    if extraneous:
        # 본 PR 시점에는 registry 가 비어있으므로 extraneous 도 0 이다.
        # 후속 PR 가 잘못된 path 를 등록하면 여기서 가시화된다 (FAIL 은
        # `#1845` enforcement 책임).
        extras = sorted(extraneous)
        print(f"  Extraneous paths in registry (not in Click tree): {extras}")

    # skeleton lock: Click leaf iterator 가 실제로 leaf 를 발견하는지 확인.
    assert total > 0, (
        "iter_click_leaf_commands() 가 leaf 를 0 개 발견했다 — Click root "
        "또는 helper 가 깨졌을 가능성. tests.unit.contracts.test_helpers 의 "
        "skeleton test 도 함께 확인하라."
    )

    # baseline lock: 본 PR 시점 registry 는 빈 dict 다. 후속 PR 가 entry 를
    # 추가하기 시작하면 이 단언은 자연스럽게 제거 / 완화된다.
    assert registered == set(), (
        "본 PR (#1844) 시점 CLI_COMMAND_REGISTRY 는 빈 dict 여야 한다. "
        "entry 등록은 #1846 / #1847 의 책임이며, 그 시점에 본 baseline "
        f"단언을 갱신한다. 현재 등록: {sorted(registered)}"
    )
