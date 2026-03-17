"""리포트 생성기 단위 테스트."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ante.feed.models.result import CollectionResult
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
