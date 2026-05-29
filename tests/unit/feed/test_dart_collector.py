"""DARTCollector 체크포인트 키 형식 테스트."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from ante.data.store import ParquetStore
from ante.feed.pipeline.checkpoint import Checkpoint
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


class _StubDARTSource:
    """fetch_corp_codes/fetch_financial을 흉내내는 최소 DART 소스 스텁.

    호출된 (year, reprt_code) 조합을 기록하여 미래 분기 fetch 여부를 검증한다.
    """

    def __init__(self, corp_code_map: dict[str, str]) -> None:
        self._corp_code_map = corp_code_map
        self.fetched: list[tuple[str, str]] = []

    async def fetch_corp_codes(self, save_path: Path) -> dict[str, str]:
        return self._corp_code_map

    async def fetch_financial(
        self,
        corp_codes: list[str],
        year: str,
        reprt_code: str,
    ) -> list[dict]:
        # fetch된 분기를 기록. 데이터는 없는 것으로 처리(과거 분기여도 빈 응답).
        self.fetched.append((year, reprt_code))
        return []


class TestCheckpointFutureQuarterClamp:
    """checkpoint가 today(KST) 기준 미래 분기로 전진하지 않는지 검증한다(#1964)."""

    async def test_dart_checkpoint_not_future_quarter(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """today=2026-05-29 mock 시 period-end > today 분기는 fetch/save 모두 skip.

        2026-05-29 기준:
          - 2026-Q1 (period-end 3/31) = collectable
          - 2026-Q2 (6/30) / Q3 (9/30) / Q4 (12/31) = 미래 → skip
        수정 전에는 _collect_quarters가 모든 분기를 무조건 save하여
        checkpoint가 2026-Q4까지 전진했다.
        """
        import ante.feed.pipeline.dart_collector as dc

        monkeypatch.setattr(dc, "_today_kst", lambda: date(2026, 5, 29))

        feed_dir = tmp_path / ".feed"
        feed_dir.mkdir()
        store = ParquetStore(base_path=tmp_path / "data")
        checkpoint = Checkpoint(feed_dir, "dart", "fundamental")

        source = _StubDARTSource({"00126380": "005930"})
        collector = DARTCollector(source=source)

        config = {"schedule": {"backfill_since": "2026-01-01"}}
        await collector.collect(
            data_path=tmp_path / "data",
            feed_dir=feed_dir,
            checkpoint=checkpoint,
            config=config,
            store=store,
        )

        last = checkpoint.get_last_date()
        # 미래 분기(Q2/Q3/Q4)로 전진하지 않음. Q1만 collectable.
        assert last not in {"2026-Q2", "2026-Q3", "2026-Q4"}
        assert last == "2026-Q1"

        # 미래 분기는 fetch조차 하지 않는다 (period-end > today).
        future_codes = {"11012", "11014", "11011"}  # Q2/Q3/Q4 reprt_code
        fetched_2026 = {rc for (yr, rc) in source.fetched if yr == "2026"}
        assert fetched_2026 & future_codes == set()
        assert ("2026", "11013") in source.fetched  # Q1은 fetch됨
