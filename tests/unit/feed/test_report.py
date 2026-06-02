"""리포트 생성기 단위 테스트."""

from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl
import pytest

from ante.data.store import ParquetStore
from ante.feed.models.result import CollectionResult
from ante.feed.pipeline.backfill_runner import BackfillRunner
from ante.feed.report.generator import REPORTS_DIR, ReportGenerator


@pytest.fixture
def feed_dir(tmp_path: Path) -> Path:
    """임시 .feed 디렉토리를 생성한다."""
    d = tmp_path / ".feed"
    d.mkdir()
    return d


@pytest.fixture
def data_path(tmp_path: Path) -> Path:
    """임시 데이터 루트 디렉토리를 반환한다."""
    return tmp_path


@pytest.fixture
def sample_result() -> CollectionResult:
    """테스트용 CollectionResult를 생성한다."""
    return CollectionResult(
        mode="daily",
        started_at="2026-03-17T16:00:12Z",
        finished_at="2026-03-17T16:05:34Z",
        duration_seconds=322.0,
        target_date="2026-03-16",
        symbols_total=2487,
        symbols_success=2485,
        symbols_failed=2,
        rows_written=2485,
        data_types=["ohlcv", "fundamental"],
        failures=[
            {
                "symbol": "003920",
                "date": "2026-03-16",
                "source": "data_go_kr",
                "reason": "API 타임아웃",
                "retries": 3,
            },
        ],
        warnings=[
            {
                "symbol": "005930",
                "date": "2026-03-16",
                "type": "business_rule",
                "message": "전일 대비 가격 변동 30% 초과",
            },
        ],
        config_errors=[
            {
                "key": "ANTE_DART_API_KEY",
                "message": "API 키 미설정",
            },
        ],
    )


@pytest.fixture
def empty_result() -> CollectionResult:
    """failures/warnings/config_errors가 비어있는 CollectionResult."""
    return CollectionResult(
        mode="backfill",
        started_at="2026-03-15T10:00:00Z",
        finished_at="2026-03-15T10:30:00Z",
        duration_seconds=1800.0,
        target_date="2026-03-14",
        symbols_total=100,
        symbols_success=100,
        symbols_failed=0,
        rows_written=100,
        data_types=["ohlcv"],
    )


class TestReportGenerate:
    """generate() 메서드 테스트."""

    def test_returns_dict(
        self, feed_dir: Path, sample_result: CollectionResult
    ) -> None:
        """generate()는 dict를 반환한다."""
        gen = ReportGenerator(feed_dir)
        report = gen.generate(sample_result)
        assert isinstance(report, dict)

    def test_top_level_keys(
        self, feed_dir: Path, sample_result: CollectionResult
    ) -> None:
        """리포트에 필수 최상위 키가 존재한다."""
        gen = ReportGenerator(feed_dir)
        report = gen.generate(sample_result)

        required_keys = {
            "mode",
            "started_at",
            "finished_at",
            "duration_seconds",
            "target_date",
            "summary",
            "failures",
            "warnings",
            "config_errors",
        }
        assert required_keys <= set(report.keys())

    def test_mode_value(self, feed_dir: Path, sample_result: CollectionResult) -> None:
        """mode 필드가 CollectionResult의 값과 일치한다."""
        gen = ReportGenerator(feed_dir)
        report = gen.generate(sample_result)
        assert report["mode"] == "daily"

    def test_summary_structure(
        self, feed_dir: Path, sample_result: CollectionResult
    ) -> None:
        """summary에 필수 키가 모두 포함된다."""
        gen = ReportGenerator(feed_dir)
        report = gen.generate(sample_result)
        summary = report["summary"]

        assert summary["symbols_total"] == 2487
        assert summary["symbols_success"] == 2485
        assert summary["symbols_failed"] == 2
        assert summary["failures_total"] == 1
        assert summary["rows_written"] == 2485
        assert summary["data_types"] == ["ohlcv", "fundamental"]

    def test_failures_type(
        self, feed_dir: Path, sample_result: CollectionResult
    ) -> None:
        """failures는 list이다."""
        gen = ReportGenerator(feed_dir)
        report = gen.generate(sample_result)
        assert isinstance(report["failures"], list)
        assert len(report["failures"]) == 1

    def test_warnings_type(
        self, feed_dir: Path, sample_result: CollectionResult
    ) -> None:
        """warnings는 list이다."""
        gen = ReportGenerator(feed_dir)
        report = gen.generate(sample_result)
        assert isinstance(report["warnings"], list)
        assert len(report["warnings"]) == 1

    def test_config_errors_type(
        self, feed_dir: Path, sample_result: CollectionResult
    ) -> None:
        """config_errors는 list이다."""
        gen = ReportGenerator(feed_dir)
        report = gen.generate(sample_result)
        assert isinstance(report["config_errors"], list)
        assert len(report["config_errors"]) == 1


class TestReportGenerateEmpty:
    """빈 결과 처리 테스트."""

    def test_empty_failures(
        self, feed_dir: Path, empty_result: CollectionResult
    ) -> None:
        """failures가 빈 배열일 때 정상 생성된다."""
        gen = ReportGenerator(feed_dir)
        report = gen.generate(empty_result)
        assert report["failures"] == []

    def test_empty_warnings(
        self, feed_dir: Path, empty_result: CollectionResult
    ) -> None:
        """warnings가 빈 배열일 때 정상 생성된다."""
        gen = ReportGenerator(feed_dir)
        report = gen.generate(empty_result)
        assert report["warnings"] == []

    def test_empty_config_errors(
        self, feed_dir: Path, empty_result: CollectionResult
    ) -> None:
        """config_errors가 빈 배열일 때 정상 생성된다."""
        gen = ReportGenerator(feed_dir)
        report = gen.generate(empty_result)
        assert report["config_errors"] == []

    def test_empty_failures_total_zero(
        self, feed_dir: Path, empty_result: CollectionResult
    ) -> None:
        """failures가 비어있으면 summary.failures_total이 0이다(#2117)."""
        gen = ReportGenerator(feed_dir)
        report = gen.generate(empty_result)
        assert report["summary"]["failures_total"] == 0

    def test_empty_result_has_all_keys(
        self, feed_dir: Path, empty_result: CollectionResult
    ) -> None:
        """빈 결과에도 모든 필수 키가 존재한다."""
        gen = ReportGenerator(feed_dir)
        report = gen.generate(empty_result)
        required_keys = {
            "mode",
            "started_at",
            "finished_at",
            "duration_seconds",
            "target_date",
            "summary",
            "failures",
            "warnings",
            "config_errors",
        }
        assert required_keys <= set(report.keys())


class TestReportSave:
    """save() 메서드 테스트."""

    def test_creates_file(
        self,
        feed_dir: Path,
        data_path: Path,
        sample_result: CollectionResult,
    ) -> None:
        """save()는 JSON 파일을 생성한다."""
        gen = ReportGenerator(feed_dir)
        report = gen.generate(sample_result)
        path = gen.save(data_path, report, "daily")
        assert path.exists()

    def test_file_path_pattern(
        self,
        feed_dir: Path,
        data_path: Path,
        sample_result: CollectionResult,
    ) -> None:
        """파일 경로가 {YYYY-MM-DD}-{mode}.json 패턴이다."""
        gen = ReportGenerator(feed_dir)
        report = gen.generate(sample_result)
        path = gen.save(data_path, report, "daily")

        assert path.name == "2026-03-17-daily.json"
        assert path.parent == data_path / ".feed" / REPORTS_DIR

    def test_file_is_valid_json(
        self,
        feed_dir: Path,
        data_path: Path,
        sample_result: CollectionResult,
    ) -> None:
        """저장된 파일이 유효한 JSON이다."""
        gen = ReportGenerator(feed_dir)
        report = gen.generate(sample_result)
        path = gen.save(data_path, report, "daily")

        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
        assert isinstance(data, dict)
        assert data["mode"] == "daily"

    def test_creates_reports_dir(
        self,
        feed_dir: Path,
        data_path: Path,
        sample_result: CollectionResult,
    ) -> None:
        """reports 디렉토리가 없으면 자동 생성한다."""
        gen = ReportGenerator(feed_dir)
        report = gen.generate(sample_result)
        gen.save(data_path, report, "daily")

        assert (data_path / ".feed" / REPORTS_DIR).is_dir()

    def test_backfill_mode_filename(
        self,
        feed_dir: Path,
        data_path: Path,
        empty_result: CollectionResult,
    ) -> None:
        """backfill 모드일 때 파일명에 backfill이 포함된다."""
        gen = ReportGenerator(feed_dir)
        report = gen.generate(empty_result)
        path = gen.save(data_path, report, "backfill")

        assert path.name == "2026-03-15-backfill.json"

    def test_saved_content_matches_report(
        self,
        feed_dir: Path,
        data_path: Path,
        sample_result: CollectionResult,
    ) -> None:
        """저장된 JSON 내용이 generate()의 반환값과 일치한다."""
        gen = ReportGenerator(feed_dir)
        report = gen.generate(sample_result)
        path = gen.save(data_path, report, "daily")

        raw = path.read_text(encoding="utf-8")
        saved = json.loads(raw)
        assert saved == report


class TestReportListReports:
    """list_reports() 메서드 테스트."""

    def test_empty_when_no_reports(self, feed_dir: Path) -> None:
        """리포트가 없으면 빈 리스트를 반환한다."""
        gen = ReportGenerator(feed_dir)
        assert gen.list_reports() == []

    def test_returns_existing_reports(self, feed_dir: Path) -> None:
        """저장된 리포트 파일 목록을 반환한다."""
        reports_dir = feed_dir / REPORTS_DIR
        reports_dir.mkdir()
        (reports_dir / "2026-03-15-daily.json").write_text("{}", encoding="utf-8")
        (reports_dir / "2026-03-16-daily.json").write_text("{}", encoding="utf-8")

        gen = ReportGenerator(feed_dir)
        reports = gen.list_reports()
        assert len(reports) == 2

    def test_limit_parameter(self, feed_dir: Path) -> None:
        """limit 파라미터가 반환 개수를 제한한다."""
        reports_dir = feed_dir / REPORTS_DIR
        reports_dir.mkdir()
        for i in range(5):
            (reports_dir / f"2026-03-{10 + i:02d}-daily.json").write_text(
                "{}", encoding="utf-8"
            )

        gen = ReportGenerator(feed_dir)
        reports = gen.list_reports(limit=3)
        assert len(reports) == 3

    def test_sorted_reverse(self, feed_dir: Path) -> None:
        """최신 순으로 정렬된다."""
        reports_dir = feed_dir / REPORTS_DIR
        reports_dir.mkdir()
        (reports_dir / "2026-03-10-daily.json").write_text("{}", encoding="utf-8")
        (reports_dir / "2026-03-15-daily.json").write_text("{}", encoding="utf-8")

        gen = ReportGenerator(feed_dir)
        reports = gen.list_reports()
        assert reports[0].name == "2026-03-15-daily.json"
        assert reports[1].name == "2026-03-10-daily.json"


def _write_report(reports_dir: Path, filename: str, started_at: str | None) -> None:
    """started_at만 담은 최소 리포트 JSON을 기록한다(테스트 헬퍼)."""
    payload: dict = {"mode": filename.split("-")[-1].removesuffix(".json")}
    if started_at is not None:
        payload["started_at"] = started_at
    (reports_dir / filename).write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )


class TestListReportsSortedByStartedAt:
    """list_reports()가 파일명이 아닌 started_at 기준으로 정렬되는지 검증(#2047)."""

    def test_same_date_backfill_after_daily_is_latest(self, feed_dir: Path) -> None:
        """같은 날짜에서 늦게 끝난 backfill이 최신으로 선택된다.

        파일명 역정렬은 daily('d') > backfill('b')라 daily를 최신으로 오판한다.
        started_at(daily 07:00Z < backfill 08:00Z) 기준이면 backfill이 최신이다.
        """
        reports_dir = feed_dir / REPORTS_DIR
        reports_dir.mkdir()
        _write_report(reports_dir, "2026-06-01-daily.json", "2026-06-01T07:00:00Z")
        _write_report(reports_dir, "2026-06-01-backfill.json", "2026-06-01T08:00:00Z")

        gen = ReportGenerator(feed_dir)
        reports = gen.list_reports(limit=1)

        assert len(reports) == 1
        assert reports[0].name == "2026-06-01-backfill.json"

    def test_different_dates_picks_later_date(self, feed_dir: Path) -> None:
        """날짜가 다르면 늦은 날짜의 리포트가 최신으로 선택된다."""
        reports_dir = feed_dir / REPORTS_DIR
        reports_dir.mkdir()
        _write_report(reports_dir, "2026-06-01-backfill.json", "2026-06-01T08:00:00Z")
        _write_report(reports_dir, "2026-06-02-daily.json", "2026-06-02T07:00:00Z")

        gen = ReportGenerator(feed_dir)
        reports = gen.list_reports()

        assert reports[0].name == "2026-06-02-daily.json"
        assert reports[1].name == "2026-06-01-backfill.json"

    def test_missing_or_malformed_started_at_sorted_last(self, feed_dir: Path) -> None:
        """started_at 누락/손상 리포트는 크래시 없이 후순위로 밀린다."""
        reports_dir = feed_dir / REPORTS_DIR
        reports_dir.mkdir()
        # 정상 리포트.
        _write_report(reports_dir, "2026-06-01-daily.json", "2026-06-01T07:00:00Z")
        # started_at 누락.
        _write_report(reports_dir, "2026-06-02-daily.json", None)
        # started_at malformed.
        _write_report(reports_dir, "2026-06-03-daily.json", "not-a-timestamp")
        # JSON 자체가 손상.
        (reports_dir / "2026-06-04-daily.json").write_text("{ broken", encoding="utf-8")

        gen = ReportGenerator(feed_dir)
        reports = gen.list_reports()

        # 4개 모두 목록에 포함(전체 실패 방지).
        assert len(reports) == 4
        # 정상 started_at을 가진 리포트가 가장 앞(최신).
        assert reports[0].name == "2026-06-01-daily.json"
        # 키가 동률(min)인 나머지는 파일명 역순 보조키로 안정 정렬.
        rest = [p.name for p in reports[1:]]
        assert rest == [
            "2026-06-04-daily.json",
            "2026-06-03-daily.json",
            "2026-06-02-daily.json",
        ]

    def test_tie_started_at_uses_filename_secondary_key(self, feed_dir: Path) -> None:
        """동일 started_at(tie)은 파일명 역순 보조키로 안정 정렬된다."""
        reports_dir = feed_dir / REPORTS_DIR
        reports_dir.mkdir()
        same = "2026-06-01T08:00:00Z"
        _write_report(reports_dir, "2026-06-01-backfill.json", same)
        _write_report(reports_dir, "2026-06-01-daily.json", same)

        gen = ReportGenerator(feed_dir)
        reports = gen.list_reports()

        # tie면 파일명 역순: 'daily' > 'backfill'.
        assert [p.name for p in reports] == [
            "2026-06-01-daily.json",
            "2026-06-01-backfill.json",
        ]

    def test_naive_started_at_is_normalized_aware(self, feed_dir: Path) -> None:
        """tz 없는 started_at도 UTC aware로 normalize되어 비교 가능하다."""
        reports_dir = feed_dir / REPORTS_DIR
        reports_dir.mkdir()
        # naive(타임존 없음) vs aware Z.
        _write_report(reports_dir, "2026-06-01-daily.json", "2026-06-01T07:00:00")
        _write_report(reports_dir, "2026-06-01-backfill.json", "2026-06-01T08:00:00Z")

        gen = ReportGenerator(feed_dir)
        reports = gen.list_reports(limit=1)

        # naive 비교로 인한 TypeError 없이 backfill(08:00)이 최신.
        assert reports[0].name == "2026-06-01-backfill.json"


class _AnomalyDataGoKrCollector:
    """store merge 이상을 발생시키는 stub data.go.kr collector.

    `.collect()`가 호출되면, 사전에 손상시켜 둔(읽기 불가) 파티션 위로
    fundamental write를 시도한다. ParquetStore는 기존 파일을 덮어쓰지 않고
    `store_merge` 이상 경고만 버퍼에 적재한다(#1964 silent-overwrite 제거).
    """

    async def collect(
        self,
        target_date: str,
        store: ParquetStore,
    ) -> tuple[int, set[str], list[dict]]:
        df = pl.DataFrame(
            {
                "date": [date(2025, 9, 30)],
                "symbol": ["005930"],
                "market_cap": [510000000000],
                "source": ["data_go_kr"],
            }
        )
        store.write("005930", "krx", df, data_type="fundamental")
        return 1, {"005930"}, []


class TestBackfillReportSurfacesStoreMergeWarning:
    """store merge 이상이 CollectionResult.warnings로 전파되는지 검증한다(#1964)."""

    async def test_backfill_report_surfaces_store_merge_warning(
        self, tmp_path: Path
    ) -> None:
        """store merge anomaly가 backfill 결과의 warnings에 등장한다.

        수정 전에는 store 덮어쓰기가 stderr 로그로만 남고
        CollectionResult.warnings는 비어 있었다.
        """
        data_path = tmp_path / "data"
        feed_dir = data_path / ".feed"
        (feed_dir / "checkpoints").mkdir(parents=True)

        # 손상된(읽기 불가) 파티션을 사전 배치 → 다음 write에서 merge 실패 유발.
        part_dir = data_path / "fundamental" / "KRX" / "005930"
        part_dir.mkdir(parents=True)
        (part_dir / "2025-09.parquet").write_bytes(b"corrupt-not-parquet")

        store = ParquetStore(base_path=data_path)
        runner = BackfillRunner(
            data_go_kr_collector=_AnomalyDataGoKrCollector(),
            dart_collector=None,
            store=store,
        )

        result = await runner.run(
            data_path=data_path,
            config={"schedule": {"backfill_since": "2025-09-29"}},
            feed_dir=feed_dir,
            started_at=datetime.now(tz=UTC),
            is_blocked_day=lambda config, target_date: False,
            is_trading_paused=lambda config: False,
        )

        store_merge_warnings = [
            w for w in result.warnings if w.get("type") == "store_merge"
        ]
        assert store_merge_warnings, (
            f"store_merge 경고가 result.warnings에 없음: {result.warnings}"
        )
        assert "2025-09.parquet" in store_merge_warnings[0]["path"]

        # 손상 파일은 보존됨(데이터 손실 방지).
        assert (part_dir / "2025-09.parquet").read_bytes() == b"corrupt-not-parquet"


class TestReportFailuresTotalSurfacesNonSymbolFailures:
    """비-심볼(날짜/소스) 실패가 summary.failures_total로 표면화되는지 검증(#2117).

    symbols_failed는 종목 귀속 실패만 세므로 날짜/소스 단위 실패는 0으로 남지만,
    failures_total은 len(failures)라 정직하게 표면화된다.
    """

    def test_date_level_failure_surfaces_in_failures_total(
        self, feed_dir: Path
    ) -> None:
        """data.go.kr 날짜 단위 실패는 symbols_failed=0이어도 failures_total>0."""
        # backfill_runner가 기록하는 date-level failure 형태({date,source,reason}).
        result = CollectionResult(
            mode="backfill",
            started_at="2026-03-17T16:00:12Z",
            finished_at="2026-03-17T16:05:34Z",
            duration_seconds=10.0,
            symbols_total=0,
            symbols_success=0,
            symbols_failed=0,
            rows_written=0,
            data_types=[],
            failures=[
                {
                    "date": "2026-03-16",
                    "source": "data_go_kr",
                    "reason": "HTTP 500 after 3 retries",
                },
            ],
        )

        gen = ReportGenerator(feed_dir)
        report = gen.generate(result)
        summary = report["summary"]

        # 날짜 단위 실패는 종목에 귀속되지 않아 symbols_failed에 잡히지 않는다.
        assert summary["symbols_failed"] == 0
        # 그러나 failures_total로는 정직하게 표면화된다.
        assert summary["failures_total"] == 1
        assert len(report["failures"]) == 1

    def test_dart_source_failure_surfaces_in_failures_total(
        self, feed_dir: Path
    ) -> None:
        """DART 소스 단위 실패는 symbols_failed=0이어도 failures_total>0."""
        # backfill_runner가 기록하는 DART source failure 형태({source,reason}).
        result = CollectionResult(
            mode="backfill",
            started_at="2026-03-17T16:00:12Z",
            finished_at="2026-03-17T16:05:34Z",
            duration_seconds=10.0,
            symbols_total=0,
            symbols_success=0,
            symbols_failed=0,
            rows_written=0,
            data_types=[],
            failures=[
                {
                    "source": "dart",
                    "reason": "DART API 연결 실패",
                },
            ],
        )

        gen = ReportGenerator(feed_dir)
        report = gen.generate(result)
        summary = report["summary"]

        assert summary["symbols_failed"] == 0
        assert summary["failures_total"] == 1

    def test_symbol_level_failure_keeps_symbols_failed_accurate(
        self, feed_dir: Path
    ) -> None:
        """심볼 단위 성공/실패는 symbols_failed가 정확히 유지된다(부풀리지 않음)."""
        result = CollectionResult(
            mode="daily",
            started_at="2026-03-17T16:00:12Z",
            finished_at="2026-03-17T16:05:34Z",
            duration_seconds=10.0,
            target_date="2026-03-16",
            symbols_total=3,
            symbols_success=2,
            symbols_failed=1,
            rows_written=2,
            data_types=["ohlcv"],
            failures=[
                {
                    "symbol": "003920",
                    "date": "2026-03-16",
                    "source": "data_go_kr",
                    "reason": "타임아웃",
                },
            ],
        )

        gen = ReportGenerator(feed_dir)
        report = gen.generate(result)
        summary = report["summary"]

        # 심볼 귀속 실패는 그대로 symbols_failed에 잡히고 failures_total과 일치.
        assert summary["symbols_failed"] == 1
        assert summary["failures_total"] == 1

    def test_mixed_symbol_and_date_failures(self, feed_dir: Path) -> None:
        """심볼+날짜 단위 실패 혼재 시 failures_total > symbols_failed."""
        result = CollectionResult(
            mode="backfill",
            started_at="2026-03-17T16:00:12Z",
            finished_at="2026-03-17T16:05:34Z",
            duration_seconds=10.0,
            symbols_total=2,
            symbols_success=1,
            symbols_failed=1,
            rows_written=1,
            data_types=["ohlcv"],
            failures=[
                {"symbol": "003920", "reason": "심볼 단위 실패"},
                {"date": "2026-03-15", "source": "data_go_kr", "reason": "날짜 실패"},
                {"source": "dart", "reason": "소스 실패"},
            ],
        )

        gen = ReportGenerator(feed_dir)
        report = gen.generate(result)
        summary = report["summary"]

        # symbols_failed는 심볼 귀속분만(1), failures_total은 전체(3).
        assert summary["symbols_failed"] == 1
        assert summary["failures_total"] == 3


_SPEC_DOC = (
    Path(__file__).resolve().parents[3]
    / "docs"
    / "specs"
    / "data-feed"
    / "10-checkpoints-and-reports.md"
)


def _spec_report_summary_keys() -> set[str]:
    """스펙 문서 리포트 예시 JSON의 summary 필드셋을 추출한다.

    fenced ```json 블록 중 `"summary"`를 포함하는 첫 블록을 골라, 줄단위
    `//` 주석을 제거한 뒤 파싱한다(스펙 예시는 주석을 포함하므로).
    """
    text = _SPEC_DOC.read_text(encoding="utf-8")
    blocks = re.findall(r"```json\n(.*?)```", text, re.DOTALL)
    for block in blocks:
        if '"summary"' not in block:
            continue
        no_comments = "\n".join(
            line for line in block.splitlines() if not line.strip().startswith("//")
        )
        payload = json.loads(no_comments)
        return set(payload["summary"].keys())
    raise AssertionError("스펙 문서에서 summary 예시 블록을 찾지 못함")


class TestSpecSummaryFieldsetParity:
    """스펙 예시의 summary 필드셋과 generate() summary 직렬화가 정합한지 검증(#2117)."""

    def test_generate_summary_keys_match_spec(
        self, feed_dir: Path, sample_result: CollectionResult
    ) -> None:
        """generate() summary 키 집합 == 스펙 예시 summary 필드셋."""
        gen = ReportGenerator(feed_dir)
        report = gen.generate(sample_result)

        assert set(report["summary"].keys()) == _spec_report_summary_keys()

    def test_spec_contains_failures_total(self) -> None:
        """스펙 예시 summary에 failures_total 필드가 명시돼 있다."""
        assert "failures_total" in _spec_report_summary_keys()
