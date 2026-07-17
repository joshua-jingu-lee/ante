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
        rows, _stored_ok, symbols, warns = await collector.collect(
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
        _rows, _stored_ok, _symbols, warns = await collector.collect(
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
    """단일 연도만 순회하도록 _resolve_year_range를 고정해 collect 실행.

    ``_collect_quarters`` 는 #1993 이후 ``(net_delta, stored_ok, syms, warns)``
    4-tuple을 반환한다. 기존 호출부 호환을 위해 stored_ok를 떼고
    ``(net_delta, syms, warns)`` 3-tuple로 어댑트해 반환한다(net_delta=rows_written).
    """
    # end_year를 고정(_today_kst 기반 현재 연도 대신)하여 단일 연도만 순회.
    net_delta, _stored_ok, syms, warns = await collector._collect_quarters(  # type: ignore[attr-defined]
        {"00126380": "005930"},
        store,
        checkpoint,
        2015,
        end_year,
        None,
    )
    return net_delta, syms, warns


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


def _stored_df_quarter(year: str, month: int) -> pl.DataFrame:
    """분기별로 distinct한 period_end(date)를 가진 정규화 결과(재수집 delta 검증용)."""
    from calendar import monthrange

    day = monthrange(int(year), month)[1]
    return pl.DataFrame(
        {
            "date": [date(int(year), month, day)],
            "symbol": ["005930"],
            "revenue": [100],
            "source": ["dart"],
        }
    )


class TestRecollectQuarterDeltaZero:
    """#1993/#2028: 재수집 분기는 net_delta=0이어도 QuarterStatus.OK로 전진한다.

    rows_written을 net-new 저장 delta로 바꾸면 이미 저장된 분기를 다시 수집할 때
    net_delta=0이 된다. QuarterStatus 판정을 net-delta가 아니라 **storable_rows**
    (정규화/저장 가능 행 수) 기준으로 유지하므로, 재수집 분기는 storable>0이라
    OK로 checkpoint가 정상 전진한다(net-delta로 판정하면 no-storable HALT로
    오판해 stall). #2028 QuarterStatus(SKIP_EMPTY/HALT/OK) 동작은 무변경이다.
    """

    async def test_recollect_quarter_storable_positive_net_delta_zero_ok(
        self, tmp_path: Path
    ) -> None:
        """이미 저장된 분기 재수집: storable>0, net_delta=0, status=OK, 전진."""
        from ante.feed.pipeline.dart_collector import QuarterStatus

        # 분기별 distinct date(3/31, 6/30, 9/30, 12/31)로 실제 신규 저장 보장.
        behaviors: dict[tuple[str, str], object] = {
            ("2015", "11013"): [_raw_item("2015", "11013")],
            ("2015", "11012"): [_raw_item("2015", "11012")],
            ("2015", "11014"): [_raw_item("2015", "11014")],
            ("2015", "11011"): [_raw_item("2015", "11011")],
        }
        norm_results = {
            ("2015", "11013"): _stored_df_quarter("2015", 3),
            ("2015", "11012"): _stored_df_quarter("2015", 6),
            ("2015", "11014"): _stored_df_quarter("2015", 9),
            ("2015", "11011"): _stored_df_quarter("2015", 12),
        }
        collector, checkpoint, store, _source, config = _make_collector_env(
            tmp_path, behaviors, norm_results
        )

        # 1차 수집: 4개 분기 신규 저장 → net_delta>0.
        rows1, syms1, warns1 = await _run_collect(
            tmp_path, collector, checkpoint, store, config
        )
        assert checkpoint.get_last_date() == "2015-Q4"
        assert rows1 > 0
        assert warns1 == []
        assert syms1 == {"005930"}

        # 단일 분기 재수집(_fetch_quarter 직접): 이미 저장됨 → net_delta=0 + OK.
        warns2: list[dict] = []
        net_delta, syms2, status, store_merge_failed = await collector._fetch_quarter(
            ["00126380"],
            {"00126380": "005930"},
            store,
            2015,
            "11013",
            warns2,
        )
        # storable>0이라 OK(no-storable HALT 아님), net_delta=0(재수집 dedup).
        # store-merge 정상이므로 store_merge_failed=False(checkpoint 전진 자격).
        assert status is QuarterStatus.OK
        assert net_delta == 0
        assert syms2 == {"005930"}
        assert warns2 == []
        assert store_merge_failed is False

        # 2차 전체 재수집(fresh checkpoint): 전부 재수집(net_delta=0)이어도 OK로
        # checkpoint가 Q4까지 정상 전진(stall 없음). #2028 무회귀.
        checkpoint2 = Checkpoint(tmp_path / ".feed", "dart", "fundamental")
        net_delta2, stored_ok2, _syms3, warns3 = await collector._collect_quarters(
            {"00126380": "005930"},
            store,
            checkpoint2,
            2015,
            2015,
            None,
        )
        assert checkpoint2.get_last_date() == "2015-Q4"
        assert net_delta2 == 0  # 전부 재수집 → net-new 0(과대계상 제거)
        assert stored_ok2 is True  # storable 저장 분기 존재 → stored_ok True
        assert warns3 == []


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
        written, syms, status, store_merge_failed = await collector._fetch_quarter(
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
        assert store_merge_failed is False

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

        rows, stored_ok, _syms, warns = await collector._collect_quarters(
            {"00126380": "005930"},
            store,
            checkpoint,
            2015,
            2015,
            None,
        )

        assert checkpoint.get_last_date() is None
        assert rows == 0
        # 전 분기 빈 응답(SKIP_EMPTY) → 저장 반영 전무 → stored_ok=False.
        assert stored_ok is False
        assert warns == []


class TestDailyLatestQuarter:
    """#2101: daily 모드는 최신 collectable 분기 1개만 수집한다.

    수정 전 ``feed run daily``는 ``collect()``를 daily 구분 없이 호출해
    ``_resolve_year_range``로 backfill_since(예 2015)부터 전 분기를 순회했다
    (사실상 DART backfill 동작). daily=True는 today(KST) 기준 최신 collectable
    분기 1개만 ``_fetch_quarter``하고, checkpoint/SKIP_EMPTY/HALT 로직(#2028/
    #2054)은 backfill 경로와 동일하게 보존한다.
    """

    async def test_daily_collects_only_latest_quarter_ignoring_backfill_since(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """(a) daily=True + checkpoint 부재 → 최신 분기 1개만 fetch(backfill 무시).

        today=2026-05-29, backfill_since=2015. backfill(daily=False)이라면 2015~2026
        전 분기를 순회하겠지만, daily=True는 2026-05-29 기준 최신 collectable 분기
        (2026-Q1, period_end 3/31)만 fetch한다. 2015 등 과거 분기는 fetch하지 않는다.
        """
        import ante.feed.pipeline.dart_collector as dc

        monkeypatch.setattr(dc, "_today_kst", lambda: date(2026, 5, 29))

        feed_dir = tmp_path / ".feed"
        feed_dir.mkdir()
        store = ParquetStore(base_path=tmp_path / "data")
        checkpoint = Checkpoint(feed_dir, "dart", "fundamental")

        # 최신 분기(2026-Q1)는 데이터를 반환(written>0)하도록 스크립트.
        behaviors: dict[tuple[str, str], object] = {
            ("2026", "11013"): [_raw_item("2026", "11013")],
        }
        source = _ScriptedDARTSource({"00126380": "005930"}, behaviors)
        normalizer = _ScriptedNormalizer({("2026", "11013"): _stored_df("2026")})
        collector = DARTCollector(source=source, normalizer=normalizer)

        config = {"schedule": {"backfill_since": "2015-01-01"}}
        rows, _stored_ok, syms, warns = await collector.collect(
            data_path=tmp_path / "data",
            feed_dir=feed_dir,
            checkpoint=checkpoint,
            config=config,
            store=store,
            daily=True,
        )

        # 정확히 최신 분기 1개(2026-Q1)만 fetch. 과거/미래 분기 없음.
        assert source.fetched == [("2026", "11013")]
        assert rows > 0
        assert syms == {"005930"}
        assert warns == []
        # 최신 분기 성공 → checkpoint가 2026-Q1로 전진.
        assert checkpoint.get_last_date() == "2026-Q1"

    async def test_daily_latest_quarter_already_done_zero_fetch(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """(b) daily=True + 최신 분기 checkpoint done → 0 fetch(skip).

        today=2026-05-29 → 최신 collectable = 2026-Q1. checkpoint가 이미 2026-Q1이면
        재수집하지 않는다(fetch 0회).
        """
        import ante.feed.pipeline.dart_collector as dc

        monkeypatch.setattr(dc, "_today_kst", lambda: date(2026, 5, 29))

        feed_dir = tmp_path / ".feed"
        feed_dir.mkdir()
        store = ParquetStore(base_path=tmp_path / "data")
        checkpoint = Checkpoint(feed_dir, "dart", "fundamental")
        checkpoint.save("2026-Q1")  # 최신 분기 이미 완료

        source = _ScriptedDARTSource({"00126380": "005930"}, {})
        collector = DARTCollector(source=source)

        config = {"schedule": {"backfill_since": "2015-01-01"}}
        rows, _stored_ok, syms, warns = await collector.collect(
            data_path=tmp_path / "data",
            feed_dir=feed_dir,
            checkpoint=checkpoint,
            config=config,
            store=store,
            daily=True,
        )

        assert source.fetched == []  # fetch 0회
        assert rows == 0
        assert syms == set()
        assert warns == []
        # checkpoint는 변하지 않음(이미 최신).
        assert checkpoint.get_last_date() == "2026-Q1"

    async def test_daily_latest_quarter_empty_response_skip_empty(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """(e-1) daily 최신 분기 빈 응답(미공시) → SKIP_EMPTY: 미전진(checkpoint None).

        분기종료 직후·공시 전 빈 응답은 SKIP_EMPTY로 처리해 checkpoint를
        전진시키지 않는다(#2028 보존). 다음 daily run에서 재시도된다.
        """
        import ante.feed.pipeline.dart_collector as dc

        monkeypatch.setattr(dc, "_today_kst", lambda: date(2026, 5, 29))

        feed_dir = tmp_path / ".feed"
        feed_dir.mkdir()
        store = ParquetStore(base_path=tmp_path / "data")
        checkpoint = Checkpoint(feed_dir, "dart", "fundamental")

        # 최신 분기(2026-Q1) 미지정 → 빈 응답([]).
        source = _ScriptedDARTSource({"00126380": "005930"}, {})
        collector = DARTCollector(source=source)

        config = {"schedule": {"backfill_since": "2015-01-01"}}
        rows, _stored_ok, _syms, warns = await collector.collect(
            data_path=tmp_path / "data",
            feed_dir=feed_dir,
            checkpoint=checkpoint,
            config=config,
            store=store,
            daily=True,
        )

        # 최신 분기 1개만 fetch했으나 빈 응답 → 미전진.
        assert source.fetched == [("2026", "11013")]
        assert rows == 0
        assert warns == []
        assert checkpoint.get_last_date() is None  # SKIP_EMPTY 미전진

    async def test_daily_latest_quarter_transient_failure_halts(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """(e-2) daily 최신 분기 transient 실패 → HALT: warn 추가 + checkpoint 미전진.

        ``_fetch_quarter``의 HALT 경로(transient 예외)가 daily 경로에서도
        동일하게 동작한다(#2054 보존). checkpoint는 전진하지 않고 warn이 표면화된다.
        """
        import ante.feed.pipeline.dart_collector as dc

        monkeypatch.setattr(dc, "_today_kst", lambda: date(2026, 5, 29))

        feed_dir = tmp_path / ".feed"
        feed_dir.mkdir()
        store = ParquetStore(base_path=tmp_path / "data")
        checkpoint = Checkpoint(feed_dir, "dart", "fundamental")

        behaviors: dict[tuple[str, str], object] = {
            ("2026", "11013"): RuntimeError("transient upstream"),
        }
        source = _ScriptedDARTSource({"00126380": "005930"}, behaviors)
        collector = DARTCollector(source=source)

        config = {"schedule": {"backfill_since": "2015-01-01"}}
        rows, _stored_ok, _syms, warns = await collector.collect(
            data_path=tmp_path / "data",
            feed_dir=feed_dir,
            checkpoint=checkpoint,
            config=config,
            store=store,
            daily=True,
        )

        assert source.fetched == [("2026", "11013")]
        assert rows == 0
        assert checkpoint.get_last_date() is None  # HALT 미전진
        assert len(warns) == 1
        assert warns[0]["reprt_code"] == "11013"


class TestLatestCollectableQuarter:
    """#2101: ``_latest_collectable_quarter`` 산출이 period_end<=today 최대로 정확."""

    def test_mid_year_picks_q1(self) -> None:
        """(d-1) 2026-05-29 → 2026-Q1(3/31)이 최신 collectable(Q2~Q4는 미래)."""
        result = DARTCollector._latest_collectable_quarter(date(2026, 5, 29))
        assert result == (2026, "11013")  # 2026-Q1

    def test_after_q2_period_end_picks_q2(self) -> None:
        """(d-2) 2026-08-15 → 2026-Q2(6/30)가 최신(Q3 9/30은 미래)."""
        result = DARTCollector._latest_collectable_quarter(date(2026, 8, 15))
        assert result == (2026, "11012")  # 2026-Q2

    def test_year_start_boundary_picks_prev_annual(self) -> None:
        """(d-3) 연초 경계 2026-01-15 → 2025-Q4(annual, 2025-12-31)가 최신.

        annual은 익년 초까지 미공시일 수 있으나 period_end<=today 기준이므로
        2025-12-31<=2026-01-15로 collectable이다. 2026-Q1(3/31)은 미래라 제외.
        """
        result = DARTCollector._latest_collectable_quarter(date(2026, 1, 15))
        assert result == (2025, "11011")  # 2025-Q4(annual)

    def test_exact_period_end_is_collectable(self) -> None:
        """(d-4) today == period_end(2026-03-31) → 그 분기(2026-Q1) collectable(<=)."""
        result = DARTCollector._latest_collectable_quarter(date(2026, 3, 31))
        assert result == (2026, "11013")  # 2026-Q1

    def test_year_end_picks_annual(self) -> None:
        """(d-5) 2026-12-31 → 2026-Q4(annual, 12/31)가 최신 collectable."""
        result = DARTCollector._latest_collectable_quarter(date(2026, 12, 31))
        assert result == (2026, "11011")  # 2026-Q4


class TestBackfillUnchangedRegression:
    """#2101: daily=False(기본, backfill)는 기존 전 분기 순회를 유지(회귀 락)."""

    async def test_backfill_default_iterates_all_quarters(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """(c) collect(daily=False) → backfill_since~현재 전 분기 순회(무변경).

        today=2016-05-29, backfill_since=2015. daily 구분 없는 기존 동작은
        2015 전 분기(Q1~Q4) + 2016 collectable 분기(Q1)를 순회한다. daily 플래그
        도입 후에도 기본값 False 경로는 동일하게 전 분기를 fetch한다.
        """
        import ante.feed.pipeline.dart_collector as dc

        monkeypatch.setattr(dc, "_today_kst", lambda: date(2016, 5, 29))

        feed_dir = tmp_path / ".feed"
        feed_dir.mkdir()
        store = ParquetStore(base_path=tmp_path / "data")
        checkpoint = Checkpoint(feed_dir, "dart", "fundamental")

        source = _ScriptedDARTSource({"00126380": "005930"}, {})
        collector = DARTCollector(source=source)

        config = {"schedule": {"backfill_since": "2015-01-01"}}
        # daily 인자 생략(기본 False) → backfill 경로.
        await collector.collect(
            data_path=tmp_path / "data",
            feed_dir=feed_dir,
            checkpoint=checkpoint,
            config=config,
            store=store,
        )

        # 2015 전 분기 + 2016-Q1(collectable). 2016-Q2~Q4(6/30 이후)는 미래라 제외.
        assert source.fetched == [
            ("2015", "11013"),
            ("2015", "11012"),
            ("2015", "11014"),
            ("2015", "11011"),
            ("2016", "11013"),
        ]


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


class TestAvailableDateEndToEnd:
    """#2010: raw_items의 rcept_no가 collector→실제 normalizer→store를 거쳐

    available_date(point-in-time 접수일)로 저장되는지 end-to-end로 확인한다.
    (collector는 raw dict를 projection 없이 normalize에 넘긴다.)
    """

    async def test_rcept_no_flows_to_store_as_available_date(
        self, tmp_path: Path
    ) -> None:
        """raw_items에 rcept_no가 있으면 store에 available_date가 저장된다."""
        store = ParquetStore(base_path=tmp_path / "data")
        # 실제 DARTNormalizer를 쓰는 collector(normalizer 미주입 → 기본 실제 사용).
        collector = DARTCollector(source=object())

        raw_items = [
            {
                "rcept_no": "20250315000001",  # 앞 8자리 = 접수일 2025-03-15
                "corp_code": "00126380",
                "account_nm": "당기순이익",
                "thstrm_amount": "200,000",
                "fs_div": "CFS",
                "reprt_code": "11013",  # 1Q → period_end 3/31
                "bsns_year": "2025",
            },
        ]

        storable_rows, net_delta, syms = collector._normalize_and_store(
            raw_items,
            {"00126380": "005930"},
            store,
        )

        # 신규 write: storable_rows == net_delta == 1 (#1993).
        assert storable_rows == 1
        assert net_delta == 1
        assert syms == {"005930"}

        result = store.read("005930", "krx", data_type="fundamental")
        assert len(result) == 1
        assert "available_date" in result.columns
        assert result["date"][0] == date(2025, 3, 31)  # period_end
        assert result["available_date"][0] == date(2025, 3, 15)  # 접수일

    async def test_no_rcept_no_stores_null_available_date(self, tmp_path: Path) -> None:
        """raw_items에 rcept_no가 없어도 정상 저장되고 available_date=null."""
        store = ParquetStore(base_path=tmp_path / "data")
        collector = DARTCollector(source=object())

        raw_items = [
            {
                "corp_code": "00126380",
                "account_nm": "당기순이익",
                "thstrm_amount": "200,000",
                "fs_div": "CFS",
                "reprt_code": "11011",
                "bsns_year": "2025",
            },
        ]

        storable_rows, net_delta, syms = collector._normalize_and_store(
            raw_items,
            {"00126380": "005930"},
            store,
        )

        # 신규 write: storable_rows == net_delta == 1 (#1993).
        assert storable_rows == 1
        assert net_delta == 1
        result = store.read("005930", "krx", data_type="fundamental")
        assert "available_date" in result.columns
        assert result["available_date"][0] is None


# ── store_merge 게이트(#1993 Finding 2): DART checkpoint 미전진 ───────────────


def _merge_fail_partition(store: ParquetStore, symbol: str, month: str) -> Path:
    """해당 fundamental 파티션 월에 결합-불가(non-coercible·읽기 가능) 파일을 배치한다.

    공유키 컬럼 ``revenue`` 를 List로 두면, 다음 ``store.write``(scalar
    ``revenue``)가 이 파일을 읽은 뒤 ``pl.concat(how="diagonal_relaxed")`` 하려다
    supertype 결정 실패로 raise한다. ParquetStore는 기존 파일을 덮어쓰지 않고
    ``store_merge`` 경고만 ``_pending_warnings`` 에 적재한다(net_delta=0, 기존
    보존). read는 성공하고 concat만 실패하는 genuine merge-fail이므로 #2413
    self-heal(읽기 불가 → store_recovered) 대상이 아니라 store_merge **게이트**
    경로를 결정적으로 재현한다(checkpoint 미전진 회귀 보존).

    Returns:
        배치한 파일 경로.
    """
    part_dir = store.base_path / "fundamental" / "KRX" / symbol
    part_dir.mkdir(parents=True, exist_ok=True)
    filepath = part_dir / f"{month}.parquet"
    year, mon = (int(x) for x in month.split("-"))
    pl.DataFrame(
        {
            "date": [date(year, mon, 1)],
            "symbol": [symbol],
            "revenue": [[1, 2, 3]],  # List → scalar revenue와 concat 불가
            "source": ["dart"],
        }
    ).write_parquet(str(filepath))
    return filepath


def _corrupt_partition(store: ParquetStore, symbol: str, month: str) -> Path:
    """해당 fundamental 파티션 월에 **진짜 손상**(읽기 불가) 파일을 배치한다.

    중단 write가 남긴 0바이트/부분 parquet을 모사한다. 다음 ``store.write`` 가
    이 파일을 읽으려다 실패(parquet decode-fail)하면 ParquetStore는 손상 파일을
    ``.corrupted`` 로 격리하고 현재 group으로 재생성한다(#2413 self-heal,
    ``store_recovered`` = 비게이트 → checkpoint 전진). ``_merge_fail_partition``
    (읽기 가능·결합 불가 = store_merge 게이트)과 구분되는 경로다.

    Returns:
        배치한 손상 파일 경로.
    """
    part_dir = store.base_path / "fundamental" / "KRX" / symbol
    part_dir.mkdir(parents=True, exist_ok=True)
    filepath = part_dir / f"{month}.parquet"
    filepath.write_bytes(b"corrupt-not-parquet")
    return filepath


class TestStorePendingMergeFailureCountPeek:
    """ParquetStore.pending_merge_failure_count는 비파괴적 peek다(#1993 Finding 2)."""

    def test_counts_only_store_merge_and_does_not_drain(self, tmp_path: Path) -> None:
        """store_merge 경고만 세고, 호출 후에도 drain_warnings가 동일 경고 반환."""
        store = ParquetStore(base_path=tmp_path / "data")

        # 결합-불가 파티션 위로 write → store_merge 경고 1건 적재(net_delta=0).
        _merge_fail_partition(store, "005930", "2015-12")
        df = _stored_df_quarter("2015", 12)
        net_delta = store.write("005930", "krx", df, data_type="fundamental")
        assert net_delta == 0

        # peek: store_merge 1건. 비-store_merge 경고는 세지 않는다.
        assert store.pending_merge_failure_count() == 1
        # 반복 호출해도 동일(비파괴적).
        assert store.pending_merge_failure_count() == 1

        # drain은 여전히 경고를 반환한다 = peek가 버퍼를 비우지 않았다.
        drained = store.drain_warnings()
        assert len(drained) == 1
        assert drained[0]["type"] == "store_merge"
        # drain 후에는 count 0.
        assert store.pending_merge_failure_count() == 0

    def test_zero_when_no_merge_failure(self, tmp_path: Path) -> None:
        """정상 write(merge 실패 없음)는 count 0."""
        store = ParquetStore(base_path=tmp_path / "data")
        df = _stored_df_quarter("2015", 12)
        net_delta = store.write("005930", "krx", df, data_type="fundamental")
        assert net_delta == 1
        assert store.pending_merge_failure_count() == 0


class TestDartStoreMergeFailureBlocksCheckpoint:
    """#1993 Finding 2: DART store-merge 실패 분기는 checkpoint를 전진시키지 않는다.

    DART는 checkpoint.save를 collector 내부에서 한다(data.go.kr처럼 runner R1
    drain 가드를 거치지 않음). store.write가 merge 실패(net_delta=0 + store_merge
    경고)를 내면 QuarterStatus는 storable_rows>0이라 OK지만, checkpoint는
    store_merge_failed로 게이트되어 미전진해야 한다(다음 run 재시도). 비파괴적
    peek로 분기 전후 증가분을 보므로 runner의 drain 소유권은 보존된다.
    """

    async def test_backfill_merge_failure_trailing_quarter_blocks_advance(
        self, tmp_path: Path
    ) -> None:
        """backfill 경로: trailing 분기 merge 실패 → checkpoint 그 분기 미전진.

        2015 단일 연도 4분기를 distinct 월에 저장하되, 마지막 분기 Q4(2015-12)
        파티션을 결합-불가(non-coercible·읽기 가능)로 배치해 merge 실패를
        유발한다. Q1~Q3는 정상 저장되어 Q3까지 전진하지만, trailing Q4는
        store-merge 실패로 미전진한다(checkpoint=Q3, 다음 run에 Q4부터 재시도).
        store-merge는 halt가 아니므로 Q1~Q3 전진은 기존대로 유지되고 결합-불가
        trailing 분기만 막힌다. 대상 월(Q4)에만 배치하므로 전역 concat
        monkeypatch 없이 per-quarter 선택성이 보존된다.

        주의: store-merge는 halt를 세우지 않으므로(지침), 내부(non-trailing)
        분기가 막히면 후속 데이터 분기의 save가 checkpoint를 jump 전진시킨다.
        따라서 단일 분기 미전진을 결정적으로 검증하려면 trailing 분기를
        결합-불가로 만든다(daily 경로의 단일 분기 케이스와 동형).
        """
        behaviors: dict[tuple[str, str], object] = {
            ("2015", "11013"): [_raw_item("2015", "11013")],
            ("2015", "11012"): [_raw_item("2015", "11012")],
            ("2015", "11014"): [_raw_item("2015", "11014")],
            ("2015", "11011"): [_raw_item("2015", "11011")],
        }
        norm_results = {
            ("2015", "11013"): _stored_df_quarter("2015", 3),
            ("2015", "11012"): _stored_df_quarter("2015", 6),
            ("2015", "11014"): _stored_df_quarter("2015", 9),
            ("2015", "11011"): _stored_df_quarter("2015", 12),
        }
        collector, checkpoint, store, _source, _config = _make_collector_env(
            tmp_path, behaviors, norm_results
        )

        # trailing Q4(2015-12) 결합-불가 → 이 분기 write가 merge 실패(net_delta=0).
        # 대상 월에만 배치 → Q1~Q3 선택 전진 유지(전역 concat monkeypatch 금지).
        _merge_fail_partition(store, "005930", "2015-12")

        net_delta, stored_ok, syms, warns = await collector._collect_quarters(
            {"00126380": "005930"},
            store,
            checkpoint,
            2015,
            2015,
            None,
        )

        # Q1~Q3는 정상 전진, trailing Q4는 store-merge 실패라 미전진 → checkpoint=Q3.
        assert checkpoint.get_last_date() == "2015-Q3"

        # storable_rows>0 분기가 존재 → stored_ok=True(QuarterStatus 의미 무변경).
        assert stored_ok is True
        assert syms == {"005930"}
        # store_merge 경고는 store 버퍼에 남아(비파괴적 peek) runner가 drain한다.
        # collector는 warns에 store_merge를 넣지 않는다(드레인 소유권은 runner).
        assert all(w.get("type") != "store_merge" for w in warns)
        assert store.pending_merge_failure_count() >= 1

    async def test_backfill_merge_failure_single_quarter_blocks_advance(
        self, tmp_path: Path
    ) -> None:
        """backfill 경로(단일 collectable 분기): merge 실패 → checkpoint 미전진.

        end_year=start_year에 last_checkpoint를 Q3로 두어 Q4 한 분기만
        collectable하게 만든다. 그 단일 분기를 결합-불가로 배치하면 QuarterStatus는
        OK여도 checkpoint가 Q3에서 전진하지 못한다(store_merge_failed 게이트).
        """
        behaviors: dict[tuple[str, str], object] = {
            ("2015", "11011"): [_raw_item("2015", "11011")],  # Q4만 데이터
        }
        norm_results = {("2015", "11011"): _stored_df_quarter("2015", 12)}
        collector, checkpoint, store, _source, _config = _make_collector_env(
            tmp_path, behaviors, norm_results
        )

        # Q4(2015-12) 결합-불가 → merge 실패.
        _merge_fail_partition(store, "005930", "2015-12")

        # 사전 checkpoint=Q3(Q1~Q3 완료 상태). last_checkpoint=Q3 → Q4만 순회.
        checkpoint.save("2015-Q3")

        net_delta, stored_ok, syms, warns = await collector._collect_quarters(
            {"00126380": "005930"},
            store,
            checkpoint,
            2015,
            2015,
            "2015-Q3",
        )

        # 단일 분기 Q4가 merge 실패 → checkpoint는 Q3에서 미전진(다음 run 재시도).
        assert checkpoint.get_last_date() == "2015-Q3"
        assert stored_ok is True  # storable_rows>0 → QuarterStatus OK
        assert syms == {"005930"}
        assert all(w.get("type") != "store_merge" for w in warns)
        assert store.pending_merge_failure_count() >= 1

    async def test_backfill_clean_recollect_quarter_still_advances(
        self, tmp_path: Path
    ) -> None:
        """회귀 가드: store_merge 없는 재수집 분기(net_delta=0)는 전진(#1993 무회귀).

        결합-불가 파티션 없이 2회 collect한다. 2차는 dedup으로 net_delta=0이지만
        store_merge 경고가 없으므로 checkpoint가 정상 전진해야 한다(Finding 2
        게이트가 정상 재수집을 막지 않음을 확인).
        """
        behaviors: dict[tuple[str, str], object] = {
            ("2015", "11013"): [_raw_item("2015", "11013")],
            ("2015", "11012"): [_raw_item("2015", "11012")],
            ("2015", "11014"): [_raw_item("2015", "11014")],
            ("2015", "11011"): [_raw_item("2015", "11011")],
        }
        norm_results = {
            ("2015", "11013"): _stored_df_quarter("2015", 3),
            ("2015", "11012"): _stored_df_quarter("2015", 6),
            ("2015", "11014"): _stored_df_quarter("2015", 9),
            ("2015", "11011"): _stored_df_quarter("2015", 12),
        }
        collector, checkpoint, store, _source, _config = _make_collector_env(
            tmp_path, behaviors, norm_results
        )

        # 1차: 정상 저장 → Q4까지 전진.
        await collector._collect_quarters(
            {"00126380": "005930"}, store, checkpoint, 2015, 2015, None
        )
        assert checkpoint.get_last_date() == "2015-Q4"

        # 2차(fresh checkpoint): 전부 재수집(net_delta=0), store_merge 없음 → 전진.
        checkpoint2 = Checkpoint(tmp_path / ".feed", "dart", "fundamental")
        net_delta2, _stored_ok2, _syms2, warns2 = await collector._collect_quarters(
            {"00126380": "005930"}, store, checkpoint2, 2015, 2015, None
        )
        assert net_delta2 == 0  # 재수집 → net-new 0
        assert checkpoint2.get_last_date() == "2015-Q4"  # store_merge 없음 → 전진
        assert all(w.get("type") != "store_merge" for w in warns2)
        assert store.pending_merge_failure_count() == 0

    async def test_daily_merge_failure_quarter_no_checkpoint_advance(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """daily 경로: 최신 분기 merge 실패 → checkpoint 미전진(QuarterStatus OK).

        ``_collect_latest_quarter`` 도 backfill과 동일하게 store_merge_failed를
        게이트한다. today=2026-05-29 → 최신 2026-Q1(period_end 3/31, 파티션
        2026-03). 그 파티션을 결합-불가로 배치해 merge 실패를 유발하면 checkpoint
        미전진.
        """
        import ante.feed.pipeline.dart_collector as dc

        monkeypatch.setattr(dc, "_today_kst", lambda: date(2026, 5, 29))

        feed_dir = tmp_path / ".feed"
        feed_dir.mkdir()
        store = ParquetStore(base_path=tmp_path / "data")
        checkpoint = Checkpoint(feed_dir, "dart", "fundamental")

        # 최신 분기(2026-Q1, period_end 3/31 → 파티션 2026-03)를 결합-불가로 배치한다.
        _merge_fail_partition(store, "005930", "2026-03")

        behaviors: dict[tuple[str, str], object] = {
            ("2026", "11013"): [_raw_item("2026", "11013")],
        }
        source = _ScriptedDARTSource({"00126380": "005930"}, behaviors)
        normalizer = _ScriptedNormalizer(
            {("2026", "11013"): _stored_df_quarter("2026", 3)}
        )
        collector = DARTCollector(source=source, normalizer=normalizer)

        config = {"schedule": {"backfill_since": "2015-01-01"}}
        rows, stored_ok, syms, warns = await collector.collect(
            data_path=tmp_path / "data",
            feed_dir=feed_dir,
            checkpoint=checkpoint,
            config=config,
            store=store,
            daily=True,
        )

        # 최신 분기만 fetch했고 merge 실패 → net_delta=0, checkpoint 미전진.
        assert source.fetched == [("2026", "11013")]
        assert rows == 0
        # storable_rows>0이라 QuarterStatus는 OK → stored_ok=True(의미 무변경).
        assert stored_ok is True
        assert syms == {"005930"}
        # store_merge 게이트로 checkpoint는 전진하지 않는다(다음 daily run 재시도).
        assert checkpoint.get_last_date() is None
        # collector는 store_merge를 warns에 넣지 않고 store 버퍼에 남긴다.
        assert all(w.get("type") != "store_merge" for w in warns)
        assert store.pending_merge_failure_count() >= 1

    async def test_daily_clean_recollect_quarter_still_advances(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """회귀 가드: daily 재수집(net_delta=0, store_merge 없음)은 전진.

        #1993 무회귀.
        """
        import ante.feed.pipeline.dart_collector as dc

        monkeypatch.setattr(dc, "_today_kst", lambda: date(2026, 5, 29))

        feed_dir = tmp_path / ".feed"
        feed_dir.mkdir()
        store = ParquetStore(base_path=tmp_path / "data")
        behaviors: dict[tuple[str, str], object] = {
            ("2026", "11013"): [_raw_item("2026", "11013")],
        }
        source = _ScriptedDARTSource({"00126380": "005930"}, behaviors)
        normalizer = _ScriptedNormalizer(
            {("2026", "11013"): _stored_df_quarter("2026", 3)}
        )
        collector = DARTCollector(source=source, normalizer=normalizer)
        config = {"schedule": {"backfill_since": "2015-01-01"}}

        # 1차: 정상 저장 → 2026-Q1 전진.
        checkpoint = Checkpoint(feed_dir, "dart", "fundamental")
        await collector.collect(
            data_path=tmp_path / "data",
            feed_dir=feed_dir,
            checkpoint=checkpoint,
            config=config,
            store=store,
            daily=True,
        )
        assert checkpoint.get_last_date() == "2026-Q1"

        # 2차(fresh checkpoint): 재수집 net_delta=0, store_merge 없음 → 전진.
        checkpoint2 = Checkpoint(feed_dir, "dart", "fundamental")
        rows2, _stored_ok2, _syms2, warns2 = await collector.collect(
            data_path=tmp_path / "data",
            feed_dir=feed_dir,
            checkpoint=checkpoint2,
            config=config,
            store=store,
            daily=True,
        )
        assert rows2 == 0  # 재수집 → net-new 0
        assert checkpoint2.get_last_date() == "2026-Q1"  # store_merge 없음 → 전진
        assert all(w.get("type") != "store_merge" for w in warns2)
        assert store.pending_merge_failure_count() == 0


class TestDartCorruptPartitionSelfHealVsTransient:
    """#2413 리뷰 [5]: DART 게이트 경로에서 corrupt/일시적-read-오류/merge-fail 구분.

    - (a) 진짜 corrupt(읽기 불가) 파티션 → self-heal(store_recovered 비게이트) →
      checkpoint **전진**.
    - (b) 일시적/환경 read 오류(PermissionError) → 격리 금지 + store_merge(게이트)
      → checkpoint **미전진**(유효 파티션 손실 방지, 리뷰 [0] 정합).
    - (c) merge-fail(non-coercible) → store_merge → 미전진(별도 게이트 테스트에서 커버).
    """

    async def test_backfill_corrupt_quarter_self_heals_and_advances(
        self, tmp_path: Path
    ) -> None:
        """진짜 corrupt(읽기 불가) trailing 분기 → self-heal → checkpoint 전진.

        merge-fail(차단)과 달리 corrupt는 store_recovered(비게이트)로 처리되어
        stuck을 만들지 않고 Q4까지 전진한다. self-heal이 게이트되게 회귀하면 이
        테스트가 깨진다.
        """
        behaviors: dict[tuple[str, str], object] = {
            ("2015", "11013"): [_raw_item("2015", "11013")],
            ("2015", "11012"): [_raw_item("2015", "11012")],
            ("2015", "11014"): [_raw_item("2015", "11014")],
            ("2015", "11011"): [_raw_item("2015", "11011")],
        }
        norm_results = {
            ("2015", "11013"): _stored_df_quarter("2015", 3),
            ("2015", "11012"): _stored_df_quarter("2015", 6),
            ("2015", "11014"): _stored_df_quarter("2015", 9),
            ("2015", "11011"): _stored_df_quarter("2015", 12),
        }
        collector, checkpoint, store, _source, _config = _make_collector_env(
            tmp_path, behaviors, norm_results
        )

        # trailing Q4(2015-12)를 진짜 손상(읽기 불가)으로 배치 → self-heal 대상.
        _corrupt_partition(store, "005930", "2015-12")

        net_delta, stored_ok, syms, warns = await collector._collect_quarters(
            {"00126380": "005930"},
            store,
            checkpoint,
            2015,
            2015,
            None,
        )

        # self-heal(store_recovered 비게이트) → Q4까지 전진, stuck 없음.
        assert checkpoint.get_last_date() == "2015-Q4"
        assert stored_ok is True
        assert syms == {"005930"}
        # store_merge 게이트는 유발되지 않는다(self-heal이므로).
        assert store.pending_merge_failure_count() == 0
        assert net_delta > 0
        # 손상 파일은 격리되고 파티션은 재생성된다.
        part_dir = store.base_path / "fundamental" / "KRX" / "005930"
        assert (part_dir / "2015-12.corrupted").exists()
        assert (part_dir / "2015-12.parquet").exists()
        # store_recovered 경고는 store 버퍼에 남아 runner가 drain한다.
        drained = store.drain_warnings()
        assert any(w.get("type") == "store_recovered" for w in drained)

    async def test_backfill_transient_read_error_quarter_blocks_advance(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """일시적 read 오류(EACCES)로 실패한 trailing 분기 → 격리 금지 + 미전진.

        유효 파티션 위에서 난 PermissionError를 corruption으로 오판해 self-heal하면
        수개월치가 격리되고 checkpoint가 전진해 조용한 손실이 난다. 격리하지 않고
        store_merge(게이트)로 미전진시켜 다음 run 재시도하도록 잠근다(리뷰 [0]).
        """
        behaviors: dict[tuple[str, str], object] = {
            ("2015", "11013"): [_raw_item("2015", "11013")],
            ("2015", "11012"): [_raw_item("2015", "11012")],
            ("2015", "11014"): [_raw_item("2015", "11014")],
            ("2015", "11011"): [_raw_item("2015", "11011")],
        }
        norm_results = {
            ("2015", "11013"): _stored_df_quarter("2015", 3),
            ("2015", "11012"): _stored_df_quarter("2015", 6),
            ("2015", "11014"): _stored_df_quarter("2015", 9),
            ("2015", "11011"): _stored_df_quarter("2015", 12),
        }
        collector, checkpoint, store, _source, _config = _make_collector_env(
            tmp_path, behaviors, norm_results
        )

        # trailing Q4(2015-12)에 **유효한** 파티션을 배치(정상이면 merge 성공).
        part_dir = store.base_path / "fundamental" / "KRX" / "005930"
        part_dir.mkdir(parents=True, exist_ok=True)
        valid_q4 = part_dir / "2015-12.parquet"
        _stored_df_quarter("2015", 12).write_parquet(str(valid_q4))
        before = valid_q4.read_bytes()

        # 그 파티션 read만 PermissionError로 실패시킨다(일시적/환경 오류 모사).
        real_read = pl.read_parquet

        def _raise_eacces(source, *args, **kwargs):
            if str(source).endswith("2015-12.parquet"):
                raise PermissionError(13, "Permission denied")
            return real_read(source, *args, **kwargs)

        monkeypatch.setattr(pl, "read_parquet", _raise_eacces)

        net_delta, stored_ok, syms, warns = await collector._collect_quarters(
            {"00126380": "005930"},
            store,
            checkpoint,
            2015,
            2015,
            None,
        )

        monkeypatch.setattr(pl, "read_parquet", real_read)

        # 일시적 오류 → 격리 금지 + store_merge(게이트) → Q4 미전진(checkpoint=Q3).
        assert checkpoint.get_last_date() == "2015-Q3"
        assert store.pending_merge_failure_count() >= 1
        assert all(w.get("type") != "store_merge" for w in warns)
        # 유효 파티션은 격리되지 않고 원본 보존.
        assert not (part_dir / "2015-12.corrupted").exists()
        assert valid_q4.read_bytes() == before
