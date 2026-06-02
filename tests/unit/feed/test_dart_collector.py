"""DARTCollector 체크포인트 키 형식 테스트."""

from __future__ import annotations

import json
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
        checkpoint가 2026-Q4까지 전진했다. 미래 컷오프 이후에도 Q1이 빈 응답
        이면 SKIP_EMPTY로 미전진하므로(#2028) 어떤 미래 분기로도 전진하지
        않는다(미래 컷오프 #1964 동작 자체는 유지).
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
        # 미래 분기(Q2/Q3/Q4)로 전진하지 않음. Q1은 빈 응답이라 SKIP_EMPTY로
        # 미전진(#2028)하므로 checkpoint는 None에 머문다.
        assert last not in {"2026-Q2", "2026-Q3", "2026-Q4"}
        assert last is None

        # 미래 분기는 fetch조차 하지 않는다 (period-end > today).
        future_codes = {"11012", "11014", "11011"}  # Q2/Q3/Q4 reprt_code
        fetched_2026 = {rc for (yr, rc) in source.fetched if yr == "2026"}
        assert fetched_2026 & future_codes == set()
        assert ("2026", "11013") in source.fetched  # Q1은 fetch됨


class TestEmptyCorpCodeMapWarning:
    """#2079: corp_code_map이 비면 structured warning을 반환에 표면화한다."""

    async def test_empty_corp_code_map_surfaces_warning(
        self,
        tmp_path: Path,
    ) -> None:
        """(a) 이슈 재현: 빈 매핑 → rows=0/symbols=∅/warns 1건(empty_corp_code_map).

        수정 전에는 logger.warning만 남기고 `(0, set(), [])`를 반환해
        CLI/report에서 clean no-op처럼 보였다. 이제 구조화 warning을
        반환에 포함해 표면화한다.
        """
        feed_dir = tmp_path / ".feed"
        feed_dir.mkdir()
        store = ParquetStore(base_path=tmp_path / "data")
        checkpoint = Checkpoint(feed_dir, "dart", "fundamental")

        # fetch_corp_codes가 빈 dict를 반환하는 가짜 source.
        source = _StubDARTSource({})
        collector = DARTCollector(source=source)

        config = {"schedule": {"backfill_since": "2026-01-01"}}
        rows, symbols, warns = await collector.collect(
            data_path=tmp_path / "data",
            feed_dir=feed_dir,
            checkpoint=checkpoint,
            config=config,
            store=store,
        )

        assert rows == 0
        assert symbols == set()
        assert len(warns) == 1
        assert warns[0]["type"] == "empty_corp_code_map"
        assert warns[0]["source"] == "dart"
        # 빈 매핑이면 분기 fetch는 수행되지 않는다.
        assert source.fetched == []

    async def test_non_empty_map_has_no_empty_corp_warning(
        self,
        tmp_path: Path,
    ) -> None:
        """(b) 비어있지 않은 매핑 경로는 empty_corp_code_map warning을 내지 않는다."""
        feed_dir = tmp_path / ".feed"
        feed_dir.mkdir()
        store = ParquetStore(base_path=tmp_path / "data")
        checkpoint = Checkpoint(feed_dir, "dart", "fundamental")

        # fetch_financial이 빈 응답(terminal no-data)을 반환하므로 다른 warn 없음.
        source = _StubDARTSource({"00126380": "005930"})
        collector = DARTCollector(source=source)

        config = {"schedule": {"backfill_since": "2026-01-01"}}
        _rows, _symbols, warns = await collector.collect(
            data_path=tmp_path / "data",
            feed_dir=feed_dir,
            checkpoint=checkpoint,
            config=config,
            store=store,
        )

        assert all(w.get("type") != "empty_corp_code_map" for w in warns)


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

    async def test_empty_quarters_do_not_advance_checkpoint(
        self, tmp_path: Path
    ) -> None:
        """(c) not raw_items(미공시 가능) → checkpoint 미전진, halt 미설정(#2028).

        모든 분기가 빈 응답([]). 분기종료 직후·공시 전 빈 응답일 수 있으므로
        SKIP_EMPTY로 처리해 checkpoint를 전진시키지 않는다(이후 공시 누락
        방지). 단 halt가 아니므로 전 분기 fetch는 계속 수행된다.

        수정 전에는 빈-성공(ok=True)으로 checkpoint가 Q4까지 전진해, 분기종료
        직후 빈 응답을 "완료"로 확정하고 이후 공시를 영구 누락했다(#2028 버그).
        """
        behaviors: dict[tuple[str, str], object] = {}  # 전부 [] 반환
        collector, checkpoint, store, source, config = _make_collector_env(
            tmp_path, behaviors
        )
        _rows, _syms, warns = await _run_collect(
            tmp_path, collector, checkpoint, store, config
        )

        # 빈 분기는 미전진 → 다음 run에서 재시도 가능(공시 누락 방지).
        assert checkpoint.get_last_date() is None
        assert warns == []
        # halt가 아니므로 전 분기(4개)를 모두 fetch한다(stall 없음).
        assert source.fetched == [
            ("2015", "11013"),
            ("2015", "11012"),
            ("2015", "11014"),
            ("2015", "11011"),
        ]

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


class TestEmptyQuarterSkip:
    """#2028: 빈 분기(not raw_items)를 SKIP_EMPTY로 처리해 checkpoint를 전진/

    halt시키지 않으면서도 후속 분기 처리를 계속하는지 검증한다.

    근본 버그: 분기종료 직후·공시 전 빈 응답을 "완료"(ok=True)로 확정해
    checkpoint가 전진하면 이후 공시를 영구 누락했다. SKIP_EMPTY는 미전진하되
    halt를 세우지 않아 stall 없이 trailing 분기 재시도를 보장한다.
    """

    async def test_fetch_quarter_returns_skip_empty_for_no_data(
        self, tmp_path: Path
    ) -> None:
        """_fetch_quarter가 not raw_items에 SKIP_EMPTY를 반환한다(3-상태 계약)."""
        from ante.feed.pipeline.dart_collector import QuarterStatus

        collector, _checkpoint, store, _source, _config = _make_collector_env(
            tmp_path, behaviors={}
        )
        warns: list[dict] = []
        written, syms, status = await collector._fetch_quarter(
            ["00126380"],
            {"00126380": "005930"},
            store,
            2015,
            "11013",
            warns,
        )
        assert status is QuarterStatus.SKIP_EMPTY
        assert written == 0
        assert syms == set()
        assert warns == []

    async def test_empty_quarter_skips_without_halt(self, tmp_path: Path) -> None:
        """(a) 빈 분기 → checkpoint 미전진 AND halt 미설정(후속 처리 계속).

        Q1만 빈 응답, Q2~Q4는 정상 저장. halt가 세워지지 않으므로 Q2~Q4는
        정상 save되어 checkpoint가 Q4까지 전진한다(빈 Q1이 stall을 일으키지
        않음). 빈 분기 자체는 미전진하되 후속 데이터 분기가 jump 커버한다.
        """
        behaviors: dict[tuple[str, str], object] = {
            ("2015", "11012"): [_raw_item("2015", "11012")],  # Q2 data
            ("2015", "11014"): [_raw_item("2015", "11014")],  # Q3 data
            ("2015", "11011"): [_raw_item("2015", "11011")],  # Q4 data
            # Q1(11013) 미지정 → [] (빈, SKIP_EMPTY)
        }
        norm_results = {
            ("2015", "11012"): _stored_df("2015"),
            ("2015", "11014"): _stored_df("2015"),
            ("2015", "11011"): _stored_df("2015"),
        }
        collector, checkpoint, store, source, config = _make_collector_env(
            tmp_path, behaviors, norm_results
        )
        rows, _syms, warns = await _run_collect(
            tmp_path, collector, checkpoint, store, config
        )

        # 빈 Q1이 halt를 세우지 않아 Q2~Q4가 정상 저장 → Q4까지 전진.
        assert checkpoint.get_last_date() == "2015-Q4"
        assert warns == []
        assert rows > 0
        # 빈 분기에서 stall하지 않고 전 분기 fetch 진행.
        assert ("2015", "11011") in source.fetched

    async def test_internal_empty_quarter_jump_covered(self, tmp_path: Path) -> None:
        """(b) 내부 빈 분기 D1<Qe<D2 → checkpoint=D2(Qe jump, halt 없어 D2 저장).

        Q1(data) → checkpoint Q1. Q2(empty, SKIP_EMPTY) → 미전진·미halt.
        Q3(data) → checkpoint Q3로 jump(내부 빈 Q2를 건너뛴 커버). Q4(empty)는
        trailing이므로 미전진. 최종 checkpoint는 마지막 데이터 분기 Q3.
        """
        behaviors: dict[tuple[str, str], object] = {
            ("2015", "11013"): [_raw_item("2015", "11013")],  # Q1 data (D1)
            # Q2(11012) 미지정 → [] (내부 빈, Qe)
            ("2015", "11014"): [_raw_item("2015", "11014")],  # Q3 data (D2)
            # Q4(11011) 미지정 → [] (trailing 빈)
        }
        norm_results = {
            ("2015", "11013"): _stored_df("2015"),
            ("2015", "11014"): _stored_df("2015"),
        }
        collector, checkpoint, store, _source, config = _make_collector_env(
            tmp_path, behaviors, norm_results
        )
        await _run_collect(tmp_path, collector, checkpoint, store, config)

        # 내부 빈 Q2를 jump하여 D2(Q3)로 전진. halt가 없어 D2가 정상 저장됨.
        assert checkpoint.get_last_date() == "2015-Q3"

    async def test_trailing_empty_quarter_retryable(self, tmp_path: Path) -> None:
        """(c) trailing 빈 분기 → 마지막 데이터 분기 유지(재시도 가능).

        Q1(data) → checkpoint Q1. Q2~Q4 모두 빈(SKIP_EMPTY) → 미전진. 최종
        checkpoint는 Q1에 머물러 다음 run에서 Q2부터 재개(공시되면 수집).
        수정 전에는 빈 Q2~Q4가 ok=True로 전진해 Q4가 "완료"되어 이후 공시를
        누락했다.
        """
        behaviors: dict[tuple[str, str], object] = {
            ("2015", "11013"): [_raw_item("2015", "11013")],  # Q1 data
            # Q2/Q3/Q4 미지정 → [] (trailing 빈)
        }
        norm_results = {("2015", "11013"): _stored_df("2015")}
        collector, checkpoint, store, source, config = _make_collector_env(
            tmp_path, behaviors, norm_results
        )
        await _run_collect(tmp_path, collector, checkpoint, store, config)

        # 마지막 데이터 분기(Q1) 유지 → 다음 run에서 Q2부터 재시도.
        assert checkpoint.get_last_date() == "2015-Q1"
        # trailing 빈 분기도 모두 fetch(stall 없음).
        assert ("2015", "11011") in source.fetched

    async def test_issue_repro_empty_source_no_advance(self, tmp_path: Path) -> None:
        """(e) 이슈 재현: fake source fetch_financial=[] → 그 분기 미전진.

        모든 분기가 빈 응답인 fake source. 어떤 분기도 checkpoint를 전진시키지
        않으므로(미공시 분기 완료 오인 제거) 최종 checkpoint는 None에 머문다.
        """
        source = _StubDARTSource({"00126380": "005930"})  # 항상 [] 반환
        collector = DARTCollector(source=source)
        feed_dir = tmp_path / ".feed"
        feed_dir.mkdir()
        store = ParquetStore(base_path=tmp_path / "data")
        checkpoint = Checkpoint(feed_dir, "dart", "fundamental")

        rows, _syms, warns = await collector._collect_quarters(
            {"00126380": "005930"},
            store,
            checkpoint,
            2015,
            2015,
            None,
        )

        assert checkpoint.get_last_date() is None
        assert rows == 0
        assert warns == []


class _CountingCorpCodeSource:
    """fetch_corp_codes 호출 횟수를 기록하고 save_path에 결과를 작성하는 스텁.

    캐시 미스(다운로드) 경로가 정확히 몇 번 발동하는지 검증하기 위해
    호출 카운터를 노출한다. save_path가 주어지면 실제 다운로드 동작을
    흉내내 캐시 파일도 기록한다(_load_corp_codes의 save_path 갱신 계약).
    """

    def __init__(self, corp_code_map: dict[str, str]) -> None:
        self._corp_code_map = corp_code_map
        self.calls = 0

    async def fetch_corp_codes(self, save_path: Path) -> dict[str, str]:
        self.calls += 1
        save_path.write_text(json.dumps(self._corp_code_map))
        return dict(self._corp_code_map)


class TestCorpCodeCacheReuse:
    """#2021: 존재하는 corp_code 캐시를 재사용하고, 비정상 캐시는 재다운로드한다."""

    async def test_valid_cache_hit_skips_download(self, tmp_path: Path) -> None:
        """(a) 유효 non-empty 캐시 존재 → fetch_corp_codes 미호출, 캐시 맵 반환."""
        feed_dir = tmp_path / ".feed"
        feed_dir.mkdir()
        cache = feed_dir / "dart_corp_codes.json"
        cache.write_text(json.dumps({"00126380": "005930"}))

        source = _CountingCorpCodeSource({"99999999": "000000"})
        collector = DARTCollector(source=source)

        result = await collector._load_corp_codes(feed_dir)

        assert source.calls == 0
        assert result == {"00126380": "005930"}

    async def test_missing_cache_downloads(self, tmp_path: Path) -> None:
        """(b) 캐시 파일 없음 → fetch_corp_codes 호출(1회), 다운로드 맵 반환."""
        feed_dir = tmp_path / ".feed"
        feed_dir.mkdir()

        source = _CountingCorpCodeSource({"00126380": "005930"})
        collector = DARTCollector(source=source)

        result = await collector._load_corp_codes(feed_dir)

        assert source.calls == 1
        assert result == {"00126380": "005930"}

    async def test_corrupt_cache_falls_back_to_download(self, tmp_path: Path) -> None:
        """(c) 손상된 JSON 캐시 → 재다운로드(1회)."""
        feed_dir = tmp_path / ".feed"
        feed_dir.mkdir()
        (feed_dir / "dart_corp_codes.json").write_text("not json{")

        source = _CountingCorpCodeSource({"00126380": "005930"})
        collector = DARTCollector(source=source)

        result = await collector._load_corp_codes(feed_dir)

        assert source.calls == 1
        assert result == {"00126380": "005930"}

    async def test_empty_dict_cache_falls_back_to_download(
        self, tmp_path: Path
    ) -> None:
        """(d) 빈 dict({}) 캐시 → 재다운로드(1회)."""
        feed_dir = tmp_path / ".feed"
        feed_dir.mkdir()
        (feed_dir / "dart_corp_codes.json").write_text(json.dumps({}))

        source = _CountingCorpCodeSource({"00126380": "005930"})
        collector = DARTCollector(source=source)

        result = await collector._load_corp_codes(feed_dir)

        assert source.calls == 1
        assert result == {"00126380": "005930"}

    async def test_non_dict_cache_falls_back_to_download(self, tmp_path: Path) -> None:
        """(e) 비-dict JSON([]) 캐시 → 재다운로드(1회)."""
        feed_dir = tmp_path / ".feed"
        feed_dir.mkdir()
        (feed_dir / "dart_corp_codes.json").write_text(json.dumps([]))

        source = _CountingCorpCodeSource({"00126380": "005930"})
        collector = DARTCollector(source=source)

        result = await collector._load_corp_codes(feed_dir)

        assert source.calls == 1
        assert result == {"00126380": "005930"}
