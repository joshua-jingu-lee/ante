"""CLI contract registry leaf coverage report (#1844 / #1846 / #1847 sub-PR 9 final).

본 test 는 #1847 sub-PR 9 (final) 시점의 leaf coverage 를 **명시 lock**
한다. #1844 시점에는 빈 baseline 이었고, #1846 가 account 9 entries 를
등록하면서 "registered > 0" 으로 완화되었으며, #1847 sub-PR 1-9 가 13
도메인을 순차 등록해 본 sub-PR 9 final 시점에서는 **94 leaf 가 등록**
되어 있다. 미등록 잔여 leaf 11 개 (feed 9 + init 1 + update 1) 는 본
sub-PR scope 밖이며 별도 follow-up 의 책임이다.

본 test 가 확인하는 것:

* :func:`tests.unit.contracts.helpers.iter_click_leaf_commands` 가 적어도
  1 개 이상 leaf 를 yield 한다 (skeleton 동작 확인).
* 누락 leaf 목록을 stdout 으로 print (``pytest -s`` 시 확인 가능) —
  후속 PR 가 채울 작업 분량 가시화.
* 13 sweep 도메인 (account / member / bot / approval / treasury / strategy /
  data / report / broker / system / instrument / config / rule / trade /
  backtest / audit / signal) 의 17 family 가 모두 등록되어 있음을 **명시
  lock**.
* 누락 leaf 가 known follow-up set (feed 도메인 9 + init + update) 안에
  머물러 있음을 lock — 본 sub-PR 9 가 등록 완료한 17 family 외 새 leaf
  가 발견되면 본 단언이 FAIL 하여 등록 누락을 표면화한다.

본 test 가 *하지 않는 것*:

* 누락 leaf 11 개에 대한 일반 FAIL — known follow-up 으로 명시 처리.
* leaf path normalization 정책 lock — `#1845`.
* helper hidden-subtree exclusion 검증 — :mod:`tests.unit.contracts.test_helpers`
  가 이미 lock 한다.
"""

from __future__ import annotations

from ante.contracts.cli_registry import CLI_COMMAND_REGISTRY
from tests.unit.contracts.helpers import iter_click_leaf_commands

# #1847 sub-PR 9 final 시점의 known follow-up 미등록 leaf set.
# - feed 도메인 9 leaf: spec 533-538 + 실측 Click tree 에 존재하나 본
#   #1847 sweep (13 도메인) 의 명시 범위 밖. 후속 별도 sub-PR 또는
#   epic 이 책임진다.
# - ``("init",)`` / ``("update",)``: ``ante init`` / ``ante update`` root-
#   level leaf. 본 #1847 sweep (subcommand group 13 도메인) 의 명시 범위 밖.
_KNOWN_FOLLOWUP_UNREGISTERED: frozenset[tuple[str, ...]] = frozenset(
    {
        ("feed", "config", "check"),
        ("feed", "config", "list"),
        ("feed", "config", "set"),
        ("feed", "init"),
        ("feed", "inject"),
        ("feed", "run", "backfill"),
        ("feed", "run", "daily"),
        ("feed", "start"),
        ("feed", "status"),
        ("init",),
        ("update",),
    }
)

# #1847 sub-PR 9 final 시점의 17 sweep 도메인 1-prefix.
# 본 set 는 본 sub-PR 9 가 lock 하는 도메인 family 의 normative roster.
_SWEEP_DOMAINS: frozenset[str] = frozenset(
    {
        "account",
        "member",
        "bot",
        "approval",
        "treasury",
        "strategy",
        "data",
        "report",
        "broker",
        "system",
        "instrument",
        "config",
        "rule",
        "trade",
        "backtest",
        "audit",
        "signal",
    }
)


def test_cli_registry_leaf_coverage_report() -> None:
    leaves = {leaf.path for leaf in iter_click_leaf_commands()}
    registered = set(CLI_COMMAND_REGISTRY.keys())
    missing = leaves - registered
    extraneous = registered - leaves

    # report-only — stdout 으로 카운트 출력.
    total = len(leaves)
    ratio_pct = round(100.0 * len(registered) / total, 1) if total else 0.0
    print(
        f"\nCLI registry coverage (#1847 sub-PR 9 final): "
        f"{len(registered)}/{total} leaves registered ({ratio_pct}%)"
    )
    if missing:
        all_missing = sorted(missing)
        print(f"  Missing ({len(all_missing)} total, known follow-up):")
        for path in all_missing:
            print(f"    - {path}")
    if extraneous:
        # registry path 가 Click tree 에 없는 stale entry. 본 PR 이 정상
        # 종료되면 0 이어야 한다 (#1845 enforcement 가 별도 lock 예정).
        extras = sorted(extraneous)
        print(f"  Extraneous paths in registry (not in Click tree): {extras}")

    # skeleton lock: Click leaf iterator 가 실제로 leaf 를 발견하는지 확인.
    assert total > 0, (
        "iter_click_leaf_commands() 가 leaf 를 0 개 발견했다 — Click root "
        "또는 helper 가 깨졌을 가능성. tests.unit.contracts.test_helpers 의 "
        "skeleton test 도 함께 확인하라."
    )

    # ── #1847 sub-PR 9 final lock: 17 sweep 도메인이 모두 등록되어 있음을 단언 ──
    #
    # 각 도메인이 최소 1 entry 이상 registry 에 등록되어 있어야 한다.
    # 13 sweep 도메인 (account/member/bot/approval/treasury/strategy/data/
    # report/broker/system/instrument/config/rule) 은 sub-PR 1-8 가, 4 sweep
    # 도메인 (trade/backtest/audit/signal) 은 본 sub-PR 9 가 책임진다.
    registered_top_prefixes = {p[0] for p in registered}
    missing_domains = _SWEEP_DOMAINS - registered_top_prefixes
    assert not missing_domains, (
        f"#1847 sub-PR 9 final 시점에 sweep 도메인이 일부 누락되었다: "
        f"{sorted(missing_domains)}. registry entry 등록 회귀가 의심된다."
    )

    # ── #1847 sub-PR 9 final lock: 미등록 leaf 는 known follow-up set 안에만 ──
    #
    # 17 sweep 도메인 안에서 미등록 leaf 가 발견되면 (sweep 도메인 안의 새 leaf
    # 가 추가되었거나, 본 PR 가 등록을 누락했거나) 본 단언이 FAIL 한다.
    # known follow-up (feed 9 + init + update) 외의 leaf 는 모두 registry 에
    # 등록되어 있어야 한다.
    unexpected_missing = missing - _KNOWN_FOLLOWUP_UNREGISTERED
    assert not unexpected_missing, (
        f"#1847 sub-PR 9 final 시점에 known follow-up 외 미등록 leaf 발견: "
        f"{sorted(unexpected_missing)}. 새 leaf 가 추가되었다면 registry 에 "
        "entry 를 등록하거나 known follow-up set 에 명시적으로 추가하라."
    )

    # ── #1847 sub-PR 9 final lock: 등록 카운트 ≥ 94 ──
    #
    # 본 sub-PR 9 시점에 13 sweep 도메인 + 4 sweep 도메인 = 17 family 의
    # 등록 leaf 가 합쳐 94 개임을 명시 lock. 추후 follow-up 이 feed/init/
    # update 를 등록하면 늘어날 수 있으므로 ≥ 94 로 단언한다.
    assert len(registered) >= 94, (
        f"#1847 sub-PR 9 final 시점 registry 는 ≥ 94 entries 여야 한다 "
        f"(실제: {len(registered)}). sub-PR 1-9 가 등록한 17 family 합산 "
        "회귀가 의심된다."
    )
