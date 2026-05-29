"""FillDedupGuard 단위 테스트 (#1957)."""

from __future__ import annotations

from ante.eventbus import FillDedupGuard
from ante.eventbus.fill_dedup_guard import DEFAULT_FILL_DEDUP_MAXLEN


def test_first_seen_returns_false_then_true():
    """처음 보는 키는 False(처리), 같은 키 재호출은 True(skip)."""
    guard = FillDedupGuard()
    assert guard.seen_or_add("k1") is False
    assert guard.seen_or_add("k1") is True
    assert guard.seen_or_add("k1") is True


def test_distinct_keys_independent():
    """서로 다른 키는 독립적으로 처리된다."""
    guard = FillDedupGuard()
    assert guard.seen_or_add("a") is False
    assert guard.seen_or_add("b") is False
    assert guard.seen_or_add("a") is True
    assert guard.seen_or_add("b") is True


def test_maxlen_eviction_set_mirror_synced():
    """maxlen 초과 시 가장 오래된 키가 evict 되고 set 미러가 동기화된다."""
    guard = FillDedupGuard(maxlen=2)
    assert guard.seen_or_add("a") is False
    assert guard.seen_or_add("b") is False
    # 'c' 추가 시 'a' evict
    assert guard.seen_or_add("c") is False
    # 'a' 는 evict 되어 다시 신규로 취급 (known-limitation: bounded)
    assert guard.seen_or_add("a") is False
    # 'b','c' 는 여전히 윈도우 안 — 단, 'a' 재삽입이 'b' 를 evict 했을 수 있음
    # 'c' 는 항상 윈도우 안 (가장 최근 2개: a 재삽입 직전 c, a)
    assert guard.seen_or_add("c") is True


def test_set_and_deque_stay_consistent_under_eviction():
    """eviction 반복 후에도 set 미러가 deque 윈도우와 정확히 일치한다."""
    guard = FillDedupGuard(maxlen=3)
    for k in ("k1", "k2", "k3", "k4", "k5"):
        guard.seen_or_add(k)
    # 윈도우 = 최근 3개 {k3, k4, k5}. set 미러도 동일해야 한다.
    assert guard._seen == {"k3", "k4", "k5"}
    assert list(guard._order) == ["k3", "k4", "k5"]
    # evict 된 k1,k2 는 신규로 취급
    assert guard.seen_or_add("k1") is False
    # 윈도우 안 키는 여전히 skip
    assert guard.seen_or_add("k5") is True


def test_default_maxlen():
    """기본 maxlen 은 512 (설계 결정 4)."""
    assert DEFAULT_FILL_DEDUP_MAXLEN == 512
    guard = FillDedupGuard()
    assert guard._order.maxlen == 512


def test_empty_string_is_a_normal_key():
    """빈 문자열도 평범한 키로 취급된다 (빈키 비대상 정책은 호출자 책임).

    소비자는 ``if event.fill_dedup_key and guard.seen_or_add(key)`` 로 빈키를
    가드 호출 전에 단락 평가한다 — 가드 자체는 빈 문자열을 차별하지 않는다.
    """
    guard = FillDedupGuard()
    assert guard.seen_or_add("") is False
    assert guard.seen_or_add("") is True
