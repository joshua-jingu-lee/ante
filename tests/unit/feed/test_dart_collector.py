"""DARTCollector 체크포인트 키 형식 테스트."""

from __future__ import annotations

from ante.feed.pipeline.dart_collector import REPRT_TO_QUARTER, DARTCollector


class TestCheckpointKeyFormat:
    """체크포인트 키가 YYYY-QN 형식인지 확인한다."""

    def test_checkpoint_key_format(self) -> None:
        """REPRT_TO_QUARTER 매핑으로 생성된 키가 YYYY-QN 형식이다."""
        for reprt_code, quarter in REPRT_TO_QUARTER.items():
            key = f"2026-{quarter}"
            assert key.startswith("2026-Q")
            assert key in {"2026-Q1", "2026-Q2", "2026-Q3", "2026-Q4"}

    def test_all_reprt_codes_mapped(self) -> None:
        """모든 REPRT_CODE가 매핑에 존재한다."""
        from ante.feed.pipeline.dart_collector import REPRT_CODES

        for code in REPRT_CODES:
            assert code in REPRT_TO_QUARTER


class TestCheckpointOrdering:
    """Q1 < Q2 < Q3 < Q4 문자열 비교 정합성 확인."""

    def test_quarter_ordering_same_year(self) -> None:
        """같은 연도 내에서 Q1 < Q2 < Q3 < Q4 순서가 보장된다."""
        keys = [f"2026-{q}" for q in ["Q1", "Q2", "Q3", "Q4"]]
        assert keys == sorted(keys)

    def test_quarter_ordering_across_years(self) -> None:
        """연도가 다르면 연도 기준으로 정렬된다."""
        keys = ["2025-Q4", "2026-Q1"]
        assert keys == sorted(keys)

    def test_old_format_ordering_broken(self) -> None:
        """기존 REPRT_CODE 형식은 시간순과 문자열 순서가 불일치한다.

        11011(Q4)이 11012(Q2)보다 작아서 문자열 비교 시 순서가 뒤바뀐다.
        """
        old_keys_time_order = ["2026-11013", "2026-11012", "2026-11014", "2026-11011"]
        assert sorted(old_keys_time_order) != old_keys_time_order


class TestCheckpointMigration:
    """기존 YYYY-REPRT_CODE -> YYYY-QN 변환 테스트."""

    def test_migrate_q1(self) -> None:
        result = DARTCollector._migrate_checkpoint_key("2026-11013")
        assert result == "2026-Q1"

    def test_migrate_q2(self) -> None:
        result = DARTCollector._migrate_checkpoint_key("2026-11012")
        assert result == "2026-Q2"

    def test_migrate_q3(self) -> None:
        result = DARTCollector._migrate_checkpoint_key("2026-11014")
        assert result == "2026-Q3"

    def test_migrate_q4(self) -> None:
        result = DARTCollector._migrate_checkpoint_key("2026-11011")
        assert result == "2026-Q4"

    def test_already_migrated_passthrough(self) -> None:
        """이미 QN 형식이면 그대로 반환한다."""
        result = DARTCollector._migrate_checkpoint_key("2026-Q3")
        assert result == "2026-Q3"

    def test_none_passthrough(self) -> None:
        """None은 그대로 반환한다."""
        result = DARTCollector._migrate_checkpoint_key(None)
        assert result is None

    def test_empty_string_passthrough(self) -> None:
        """빈 문자열은 그대로 반환한다."""
        result = DARTCollector._migrate_checkpoint_key("")
        assert result == ""
