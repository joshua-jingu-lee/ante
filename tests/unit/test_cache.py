"""ResponseCache 단위 테스트.

SPLIT-3 (#1242): ``invalidate(pattern)`` 은 substring match → prefix-exact
match 로 변경된다. multi-account 환경에서 ``acc-1`` invalidate 가
``acc-12`` 의 캐시까지 함께 지우는 cross-account leakage 를 차단한다.
"""

from __future__ import annotations

from ante.gateway.cache import ResponseCache


class TestInvalidateBasic:
    """기본 invalidate 동작 검증."""

    def test_invalidate_empty_pattern_clears_all(self) -> None:
        """빈 pattern 은 전체 초기화 (기존 계약 유지)."""
        cache = ResponseCache()
        cache.set("acc-1:price:005930", 50000.0, ttl=5)
        cache.set("acc-2:balance", {"total": 10000}, ttl=30)
        cache.set("ohlcv:KRX:005930:1d:100", [], ttl=60)

        cache.invalidate("")

        assert cache.size == 0
        assert cache.get("acc-1:price:005930") is None
        assert cache.get("acc-2:balance") is None

    def test_invalidate_exact_key_removes_only_that_key(self) -> None:
        """완전 일치하는 key 만 제거."""
        cache = ResponseCache()
        cache.set("acc-1:balance", {"total": 1000}, ttl=30)
        cache.set("acc-1:positions", [], ttl=30)

        cache.invalidate("acc-1:balance")

        assert cache.get("acc-1:balance") is None
        assert cache.get("acc-1:positions") is not None


class TestInvalidatePrefixIsolation:
    """SPLIT-3 (#1242) prefix-exact invalidate 회귀."""

    def test_prefix_isolation_acc1_does_not_invalidate_acc12(self) -> None:
        """``acc-1`` invalidate 가 ``acc-12`` 의 캐시를 지우지 않는다."""
        cache = ResponseCache()
        cache.set("acc-1:balance", {"total": 1000}, ttl=30)
        cache.set("acc-1:positions", [], ttl=30)
        cache.set("acc-12:balance", {"total": 9999}, ttl=30)
        cache.set("acc-12:positions", [{"sym": "X"}], ttl=30)

        # acc-1 의 balance 만 invalidate
        cache.invalidate("acc-1:balance")

        # acc-1:balance 만 사라지고, acc-12:balance 는 유지된다.
        assert cache.get("acc-1:balance") is None
        assert cache.get("acc-12:balance") == {"total": 9999}
        # acc-1:positions 도 유지 (다른 key)
        assert cache.get("acc-1:positions") == []
        # acc-12:positions 도 유지
        assert cache.get("acc-12:positions") == [{"sym": "X"}]

    def test_prefix_isolation_account_namespace(self) -> None:
        """``acc-1:`` prefix invalidate 가 ``acc-12:*`` 를 지키는지 확인."""
        cache = ResponseCache()
        cache.set("acc-1:price:005930", 50000.0, ttl=5)
        cache.set("acc-1:positions", [], ttl=30)
        cache.set("acc-12:price:005930", 50000.0, ttl=5)
        cache.set("acc-12:positions", [], ttl=30)

        # acc-1: 로 시작하는 모든 key 삭제 (실제 호출 형태)
        cache.invalidate("acc-1:")

        # acc-1: prefix 캐시는 사라진다
        assert cache.get("acc-1:price:005930") is None
        assert cache.get("acc-1:positions") is None
        # acc-12: prefix 캐시는 유지된다 (substring match 였다면 사라졌을 것)
        assert cache.get("acc-12:price:005930") == 50000.0
        assert cache.get("acc-12:positions") == []

    def test_prefix_isolation_price_per_symbol(self) -> None:
        """``acc-1:price:005930`` invalidate 가 다른 symbol 을 지키는지 확인."""
        cache = ResponseCache()
        cache.set("acc-1:price:005930", 50000.0, ttl=5)
        cache.set("acc-1:price:000660", 100000.0, ttl=5)
        cache.set("acc-1:price:005930-extended", 50100.0, ttl=5)

        cache.invalidate("acc-1:price:005930")

        # 정확히 prefix 매치되는 key 만 삭제 (005930-extended 도 prefix 매치)
        assert cache.get("acc-1:price:005930") is None
        # 005930-extended 는 "acc-1:price:005930" 으로 시작하므로 함께 사라진다.
        assert cache.get("acc-1:price:005930-extended") is None
        # 000660 은 prefix 가 다르므로 유지
        assert cache.get("acc-1:price:000660") == 100000.0

    def test_prefix_substring_no_longer_matches_middle(self) -> None:
        """substring 위치에 있는 pattern 은 매칭되지 않는다 (회귀 차단).

        예: ``balance`` 라는 substring 은 ``acc-1:balance`` 를 지우지 못한다.
        """
        cache = ResponseCache()
        cache.set("acc-1:balance", {"total": 1000}, ttl=30)

        # substring 매치 시도 — prefix-exact 정책에서는 매칭 실패
        cache.invalidate("balance")

        # acc-1:balance 는 살아있다 (prefix 가 "balance" 가 아님)
        assert cache.get("acc-1:balance") == {"total": 1000}
