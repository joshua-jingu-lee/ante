"""DARTCollector 체크포인트 키 형식 테스트."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl
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


class _ScriptedDARTSource:
    """(year, reprt_code)별로 raise/raw_items 응답을 스크립트로 지정하는 스텁.

    behaviors[(year, reprt_code)] 값:
      - Exception 인스턴스 → 해당 분기 fetch_financial에서 raise
      - list[dict]          → 해당 분기 raw_items로 반환
      - 미지정              → 빈 리스트([]) 반환(terminal no-data)
    """

    def __init__(
        self,
        corp_code_map: dict[str, str],
        behaviors: dict[tuple[str, str], object] | None = None,
    ) -> None:
        self._corp_code_map = corp_code_map
        self._behaviors = behaviors or {}
        self.fetched: list[tuple[str, str]] = []

    async def fetch_corp_codes(self, save_path: Path) -> dict[str, str]:
        return self._corp_code_map

    async def fetch_financial(
        self,
        corp_codes: list[str],
        year: str,
        reprt_code: str,
    ) -> list[dict]:
        self.fetched.append((year, reprt_code))
        behavior = self._behaviors.get((year, reprt_code), [])
        if isinstance(behavior, Exception):
            raise behavior
        assert isinstance(behavior, list)
        return behavior


class _ScriptedNormalizer:
    """raw_items 길이/내용과 무관하게 미리 정한 DataFrame을 반환하는 스텁.

    _normalize_and_store가 `normalize(df, corp_code_map)`를 호출하므로
    동일 시그니처를 제공한다. 반환 DataFrame의 row 수가 written을 결정한다.
    """

    def __init__(self, result_for: dict[tuple[str, str], pl.DataFrame]) -> None:
        # raw_items 첫 항목의 (bsns_year, reprt_code)로 결과를 선택한다.
        self._result_for = result_for

    def normalize(
        self,
        df: pl.DataFrame,
        corp_code_map: dict[str, str],
    ) -> pl.DataFrame:
        first = df.row(0, named=True)
        key = (str(first["bsns_year"]), str(first["reprt_code"]))
        result = self._result_for.get(key)
        if result is not None:
            return result
        # 기본: symbol 1개, 1행을 가진 정상 정규화 결과
        return pl.DataFrame(
            {
                "date": [date(int(key[0]), 12, 31)],
                "symbol": ["005930"],
                "revenue": [100],
                "source": ["dart"],
            }
        )


def _raw_item(year: str, reprt_code: str) -> dict:
    """ScriptedNormalizer가 (year, reprt_code)를 식별할 수 있는 최소 raw row."""
    return {
        "corp_code": "00126380",
        "bsns_year": year,
        "reprt_code": reprt_code,
        "account_nm": "매출액",
        "thstrm_amount": "100",
        "fs_div": "OFS",
    }


def _stored_df(year: str) -> pl.DataFrame:
    """정상 저장(written>0)을 유발하는 정규화 결과 DataFrame."""
    return pl.DataFrame(
        {
            "date": [date(int(year), 12, 31)],
            "symbol": ["005930"],
            "revenue": [100],
            "source": ["dart"],
        }
    )


def _make_collector_env(
    tmp_path: Path,
    behaviors: dict[tuple[str, str], object],
    norm_results: dict[tuple[str, str], pl.DataFrame] | None = None,
) -> tuple[DARTCollector, Checkpoint, ParquetStore, _ScriptedDARTSource, dict]:
    """공통 collect 환경(과거 연도 single-year)을 구성한다.

    backfill_since를 과거(2015)로 두고 today를 KST 현재로 두면 모든 분기가
    collectable하므로 본 테스트들은 단일 연도(2015) 4분기를 순회한다.
    """
    feed_dir = tmp_path / ".feed"
    feed_dir.mkdir()
    store = ParquetStore(base_path=tmp_path / "data")
    checkpoint = Checkpoint(feed_dir, "dart", "fundamental")
    source = _ScriptedDARTSource({"00126380": "005930"}, behaviors)
    normalizer = _ScriptedNormalizer(norm_results or {})
    collector = DARTCollector(source=source, normalizer=normalizer)
    config = {"schedule": {"backfill_since": "2015-01-01"}}
    return collector, checkpoint, store, source, config


async def _run_collect(
    tmp_path: Path,
    collector: DARTCollector,
    checkpoint: Checkpoint,
    store: ParquetStore,
    config: dict,
    end_year: int = 2015,
) -> tuple[int, set[str], list[dict]]:
    """단일 연도만 순회하도록 _resolve_year_range를 고정해 collect 실행."""
    # end_year를 고정(_today_kst 기반 현재 연도 대신)하여 단일 연도만 순회.
    return await collector._collect_quarters(  # type: ignore[attr-defined]
        {"00126380": "005930"},
        store,
        checkpoint,
        2015,
        end_year,
        None,
    )


# 2015-Q1 period-end(3/31)는 today(2026+)보다 과거이므로 모든 분기 collectable.
# REPRT_CODES 시간순: 11013(Q1) 11012(Q2) 11014(Q3) 11011(Q4).


class TestCheckpointHaltOnFailure:
    """#2054: 분기 수집 실패 시 checkpoint가 전진하지 않는지 검증한다."""

    async def test_single_transient_failure_no_checkpoint(self, tmp_path: Path) -> None:
        """(a) 단일 분기 transient 실패 → 해당 분기 checkpoint 미저장.

        Q1(11013)에서 RuntimeError raise. 이후 Q2/Q3/Q4는 정상 성공해도
        halt 이후라 checkpoint는 전진하지 않는다(None).
        """
        behaviors: dict[tuple[str, str], object] = {
            ("2015", "11013"): RuntimeError("temporary upstream error"),
            ("2015", "11012"): [_raw_item("2015", "11012")],
            ("2015", "11014"): [_raw_item("2015", "11014")],
            ("2015", "11011"): [_raw_item("2015", "11011")],
        }
        collector, checkpoint, store, _source, config = _make_collector_env(
            tmp_path, behaviors
        )
        rows, syms, warns = await _run_collect(
            tmp_path, collector, checkpoint, store, config
        )

        assert checkpoint.get_last_date() is None
        assert len(warns) == 1
        assert warns[0]["reprt_code"] == "11013"

    async def test_q2_failure_does_not_advance_past_q1(self, tmp_path: Path) -> None:
        """(b) Q2 실패 후 Q3 성공이어도 checkpoint가 Q1에 머무름(monotonic 회귀).

        Q1 성공 → checkpoint=2015-Q1. Q2 실패 → halt. Q3 성공해도 save 안 함.
        checkpoint가 Q3로 전진하면 다음 run에서 Q2가 skip되어 영구 누락된다.
        """
        behaviors: dict[tuple[str, str], object] = {
            ("2015", "11013"): [_raw_item("2015", "11013")],  # Q1 성공
            ("2015", "11012"): RuntimeError("Q2 transient"),  # Q2 실패
            ("2015", "11014"): [_raw_item("2015", "11014")],  # Q3 성공
            ("2015", "11011"): [_raw_item("2015", "11011")],  # Q4 성공
        }
        collector, checkpoint, store, _source, config = _make_collector_env(
            tmp_path, behaviors
        )
        await _run_collect(tmp_path, collector, checkpoint, store, config)

        # 실패 분기(Q2)를 넘어 전진하지 않는다. Q1에 고정.
        assert checkpoint.get_last_date() == "2015-Q1"

    async def test_terminal_no_data_advances_checkpoint(self, tmp_path: Path) -> None:
        """(c) not raw_items(terminal no-data) → checkpoint 정상 전진(빈-성공).

        모든 분기가 빈 응답([]). 정당한 빈-성공이므로 checkpoint는 마지막
        분기(Q4)까지 전진하여 무한 재시도를 방지한다.
        """
        behaviors: dict[tuple[str, str], object] = {}  # 전부 [] 반환
        collector, checkpoint, store, _source, config = _make_collector_env(
            tmp_path, behaviors
        )
        _rows, _syms, warns = await _run_collect(
            tmp_path, collector, checkpoint, store, config
        )

        assert checkpoint.get_last_date() == "2015-Q4"
        assert warns == []

    async def test_raw_present_but_stored_zero_halts(self, tmp_path: Path) -> None:
        """(d) raw_items>0인데 정규화/저장 0건 → warns 추가 + checkpoint 미전진.

        Q1은 raw_items가 있으나 normalize가 빈 DataFrame을 반환(no-storable).
        데이터 손실을 surface(warns)하고 checkpoint는 전진하지 않는다.
        """
        empty_norm = pl.DataFrame(
            {"date": [], "symbol": [], "revenue": [], "source": []},
            schema={
                "date": pl.Date,
                "symbol": pl.Utf8,
                "revenue": pl.Int64,
                "source": pl.Utf8,
            },
        )
        behaviors: dict[tuple[str, str], object] = {
            ("2015", "11013"): [_raw_item("2015", "11013")],  # raw 있음
        }
        norm_results = {("2015", "11013"): empty_norm}  # 정규화 결과 0건
        collector, checkpoint, store, _source, config = _make_collector_env(
            tmp_path, behaviors, norm_results
        )
        _rows, _syms, warns = await _run_collect(
            tmp_path, collector, checkpoint, store, config
        )

        assert checkpoint.get_last_date() is None
        assert len(warns) == 1
        assert warns[0]["reprt_code"] == "11013"
        assert "no-storable" in warns[0]["message"]

    async def test_all_success_advances_checkpoint(self, tmp_path: Path) -> None:
        """(e) 전 분기 정상 저장 → checkpoint가 마지막 분기까지 정상 전진."""
        behaviors: dict[tuple[str, str], object] = {
            ("2015", "11013"): [_raw_item("2015", "11013")],
            ("2015", "11012"): [_raw_item("2015", "11012")],
            ("2015", "11014"): [_raw_item("2015", "11014")],
            ("2015", "11011"): [_raw_item("2015", "11011")],
        }
        norm_results = {
            ("2015", "11013"): _stored_df("2015"),
            ("2015", "11012"): _stored_df("2015"),
            ("2015", "11014"): _stored_df("2015"),
            ("2015", "11011"): _stored_df("2015"),
        }
        collector, checkpoint, store, _source, config = _make_collector_env(
            tmp_path, behaviors, norm_results
        )
        rows, syms, warns = await _run_collect(
            tmp_path, collector, checkpoint, store, config
        )

        assert checkpoint.get_last_date() == "2015-Q4"
        assert warns == []
        assert rows > 0
        assert syms == {"005930"}

    async def test_issue_repro_all_fail_no_checkpoint(self, tmp_path: Path) -> None:
        """(f) 이슈 재현: 전 분기 transient 실패 → checkpoint 미전진(None)."""
        err = RuntimeError("temporary upstream error")
        behaviors: dict[tuple[str, str], object] = {
            ("2015", "11013"): err,
            ("2015", "11012"): err,
            ("2015", "11014"): err,
            ("2015", "11011"): err,
        }
        collector, checkpoint, store, _source, config = _make_collector_env(
            tmp_path, behaviors
        )
        rows, _syms, warns = await _run_collect(
            tmp_path, collector, checkpoint, store, config
        )

        assert checkpoint.get_last_date() is None
        assert rows == 0
        assert len(warns) == 4
