"""``StrategyReport`` metric invariant 단위 테스트 (#1415).

``validate_strategy_report_metrics`` 함수는 저장 경계(CLI/Web submit)에서 명시 호출되는
opt-in invariant 검증이다. DB read path (``ReportStore._row_to_report``)는 legacy
invalid row를 허용하기 위해 이 함수를 호출하지 않는다.

SSOT:
- ``src/ante/web/schemas.py::ReportSubmitRequest`` — Web API 입력 검증 SSOT
- ``src/ante/report/models.py::validate_strategy_report_metrics`` — 저장 경계 가드

검증 대상 invariants:
- ``total_trades >= 0``
- ``win_rate ∈ [0.0, 100.0]`` 또는 ``None``
- ``total_return_pct``/``sharpe_ratio``/``max_drawdown_pct``/``win_rate``는 finite

또한 ``ReportStore._row_to_report``가 정상 row와 **legacy invalid row** 둘 다
회귀 통과시키는지 검증해 codex r1 P2 (legacy row 회귀)를 보호한다.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from ante.core.database import Database
from ante.report.models import (
    ReportStatus,
    StrategyReport,
    validate_strategy_report_metrics,
)
from ante.report.store import ReportStore


def _valid_kwargs(**overrides) -> dict:
    """함수 호출에 통과 가능한 최소 metric kwargs."""
    base = {
        "total_trades": 0,
        "win_rate": None,
        "total_return_pct": 0.0,
        "sharpe_ratio": None,
        "max_drawdown_pct": None,
    }
    base.update(overrides)
    return base


# ── total_trades ────────────────────────────────────────────


class TestTotalTradesGuard:
    def test_negative_raises(self) -> None:
        with pytest.raises(ValueError, match="total_trades"):
            validate_strategy_report_metrics(**_valid_kwargs(total_trades=-1))

    @pytest.mark.parametrize("value", [0, 1, 100])
    def test_non_negative_ok(self, value: int) -> None:
        # raises 없으면 통과
        validate_strategy_report_metrics(**_valid_kwargs(total_trades=value))


# ── win_rate ────────────────────────────────────────────────


class TestWinRateGuard:
    def test_above_100_raises(self) -> None:
        with pytest.raises(ValueError, match="win_rate"):
            validate_strategy_report_metrics(**_valid_kwargs(win_rate=101.0))

    def test_negative_raises(self) -> None:
        with pytest.raises(ValueError, match="win_rate"):
            validate_strategy_report_metrics(**_valid_kwargs(win_rate=-0.1))

    @pytest.mark.parametrize("value", [0.0, 0.58, 50.0, 58.0, 100.0])
    def test_in_range_ok(self, value: float) -> None:
        validate_strategy_report_metrics(**_valid_kwargs(win_rate=value))

    def test_none_ok(self) -> None:
        validate_strategy_report_metrics(**_valid_kwargs(win_rate=None))


# ── finite invariant ────────────────────────────────────────


class TestFiniteGuard:
    @pytest.mark.parametrize(
        "field",
        ["total_return_pct", "sharpe_ratio", "max_drawdown_pct"],
    )
    def test_nan_raises(self, field: str) -> None:
        with pytest.raises(ValueError, match=f"{field}.*finite"):
            validate_strategy_report_metrics(**_valid_kwargs(**{field: float("nan")}))

    @pytest.mark.parametrize(
        "field",
        ["total_return_pct", "sharpe_ratio", "max_drawdown_pct"],
    )
    def test_inf_raises(self, field: str) -> None:
        with pytest.raises(ValueError, match=f"{field}.*finite"):
            validate_strategy_report_metrics(**_valid_kwargs(**{field: float("inf")}))

    def test_win_rate_nan_raises(self) -> None:
        # win_rate은 range 가드가 먼저 발동 (NaN은 [0, 100] 비교에서 False가 되어
        # range 에러로 raise). 두 가드 중 하나라도 차단하면 됨.
        with pytest.raises(ValueError):
            validate_strategy_report_metrics(**_valid_kwargs(win_rate=float("nan")))


# ── dataclass __post_init__ 부재 확인 (codex r1 P2) ─────────


class TestNoPostInitGuard:
    """``StrategyReport`` dataclass 자체는 invariant raise하지 않아야 한다.

    codex r1 P2: ``__post_init__`` 가드를 유지하면 ``_row_to_report``의 DB read path가
    legacy invalid row를 재구성할 때 ``ValueError``로 fail해, 사용자가 잘못된 row를
    조회/정리할 길이 없어진다. 본 테스트는 가드 부재를 명시 회귀로 고정한다.
    """

    def test_dataclass_accepts_invalid_total_trades(self) -> None:
        """dataclass는 ``total_trades=-1`` invalid row를 raise 없이 재구성한다."""
        report = StrategyReport(
            report_id="rpt-legacy-neg-trades",
            strategy_name="legacy_probe",
            strategy_version="0.0.0",
            strategy_path="",
            status=ReportStatus.SUBMITTED,
            submitted_at=datetime.now(tz=UTC),
            total_trades=-1,
        )
        assert report.total_trades == -1

    def test_dataclass_accepts_out_of_range_win_rate(self) -> None:
        """dataclass는 ``win_rate=150.0`` invalid row를 raise 없이 재구성한다."""
        report = StrategyReport(
            report_id="rpt-legacy-bad-win",
            strategy_name="legacy_probe",
            strategy_version="0.0.0",
            strategy_path="",
            status=ReportStatus.SUBMITTED,
            submitted_at=datetime.now(tz=UTC),
            win_rate=150.0,
        )
        assert report.win_rate == 150.0

    def test_dataclass_accepts_nan_metric(self) -> None:
        """dataclass는 ``sharpe_ratio=NaN`` invalid row를 raise 없이 재구성한다."""
        import math

        report = StrategyReport(
            report_id="rpt-legacy-nan",
            strategy_name="legacy_probe",
            strategy_version="0.0.0",
            strategy_path="",
            status=ReportStatus.SUBMITTED,
            submitted_at=datetime.now(tz=UTC),
            sharpe_ratio=float("nan"),
        )
        assert math.isnan(report.sharpe_ratio)


# ── 정상 default 회귀 (draft.py 호환성) ─────────────────────


class TestDefaults:
    def test_minimal_defaults_ok(self) -> None:
        """``draft.py``의 ``generate_draft``가 default(0, None)로 생성하는 경로 보존."""
        # 모든 metric None/0 default
        report = StrategyReport(
            report_id="rpt-default",
            strategy_name="default_probe",
            strategy_version="0.0.0",
            strategy_path="",
            status=ReportStatus.DRAFT,
            submitted_at=datetime.now(tz=UTC),
        )
        assert report.total_trades == 0
        assert report.total_return_pct == 0.0
        assert report.sharpe_ratio is None
        assert report.max_drawdown_pct is None
        assert report.win_rate is None


# ── ReportStore._row_to_report 회귀 (legacy DB row 보존) ────


class TestRowToReportRegression:
    """``_row_to_report``가 정상 row + legacy invalid row를 모두 재구성하는지 검증.

    codex r1 P2: 이번 PR 이전에는 CLI submit이 invariant를 적용하지 않아 invalid row가
    DB에 저장될 수 있었다. PR 이후 가드가 추가되면 list/detail 조회 시 invalid row에서
    raise되어 사용자가 정리할 길이 없어진다. 본 테스트는 read path가 raise 없이 통과함을
    회귀 고정한다.
    """

    @pytest.fixture
    async def db(self, tmp_path):
        database = Database(str(tmp_path / "test.db"))
        await database.connect()
        yield database
        await database.close()

    @pytest.fixture
    async def store(self, db):
        s = ReportStore(db)
        await s.initialize()
        return s

    async def test_round_trip_preserves_valid_row(self, store) -> None:
        """정상 값을 submit한 뒤 get으로 재구성해도 통과해야 함."""
        original = StrategyReport(
            report_id="rpt-round-trip",
            strategy_name="round_trip",
            strategy_version="1.0.0",
            strategy_path="strategies/rt.py",
            status=ReportStatus.SUBMITTED,
            submitted_at=datetime.now(tz=UTC),
            submitted_by="agent",
            backtest_period="2024-01 ~ 2026-03",
            total_return_pct=15.3,
            total_trades=42,
            sharpe_ratio=1.2,
            max_drawdown_pct=-8.5,
            win_rate=58.0,
            summary="round trip",
            rationale="invariant 회귀",
            risks="",
            recommendations="",
            detail_json='{"equity_curve": []}',
        )
        await store.submit(original)
        fetched = await store.get("rpt-round-trip")

        assert fetched is not None
        assert fetched.report_id == "rpt-round-trip"
        assert fetched.total_trades == 42
        assert fetched.win_rate == pytest.approx(58.0)
        assert fetched.total_return_pct == pytest.approx(15.3)
        assert fetched.sharpe_ratio == pytest.approx(1.2)

    async def test_row_to_report_with_null_optional_metrics(self, store) -> None:
        """metric이 None인 row도 그대로 통과 (draft 경로 호환)."""
        report = StrategyReport(
            report_id="rpt-null-metrics",
            strategy_name="null_metrics",
            strategy_version="1.0.0",
            strategy_path="",
            status=ReportStatus.DRAFT,
            submitted_at=datetime.now(tz=UTC),
            total_return_pct=0.0,
            total_trades=0,
            sharpe_ratio=None,
            max_drawdown_pct=None,
            win_rate=None,
        )
        await store.submit(report)
        fetched = await store.get("rpt-null-metrics")
        assert fetched is not None
        assert fetched.sharpe_ratio is None
        assert fetched.max_drawdown_pct is None
        assert fetched.win_rate is None

    async def test_row_to_report_accepts_legacy_invalid_row(self, db) -> None:
        """codex r1 P2: invariant 위반 legacy row가 DB에 있어도 read는 통과해야 한다.

        이번 PR 이전 CLI는 ``total_trades=-1``, ``win_rate=150.0``, NaN/Inf 등을
        거부하지 않았다. 시나리오: 운영 중인 사용자가 ante를 업그레이드한 직후,
        과거에 저장된 invalid row가 DB에 존재. 이 경우 ``ante report list``/
        ``ante report view``가 ``ValueError``로 죽으면 사용자가 잘못된 row를 확인/정리할
        수단이 없다. read path는 raise 없이 통과시키고, **저장 경계** (CLI/Web submit
        에서 호출하는 ``validate_strategy_report_metrics``)에서만 차단한다.

        note: 테이블명은 ``reports`` (``store.py::REPORT_SCHEMA`` 참조). DB execute는
        자동 commit하므로 별도 commit() 호출 없이 다음 read에서 반영된다.
        """
        store = ReportStore(db)
        await store.initialize()

        # 스토어를 우회해 invalid row를 직접 INSERT (legacy DB 시뮬레이션).
        await db.execute(
            """
            INSERT INTO reports (
                report_id, strategy_name, strategy_version, strategy_path,
                status, submitted_at, submitted_by,
                backtest_period,
                total_return_pct, total_trades,
                sharpe_ratio, max_drawdown_pct, win_rate,
                summary, rationale, risks, recommendations,
                detail_json, user_notes, reviewed_at
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (
                "rpt-legacy-invalid",
                "legacy_invalid",
                "0.0.1",
                "strategies/legacy.py",
                "submitted",
                datetime.now(tz=UTC).isoformat(),
                "agent",
                "2024-01 ~ 2025-12",
                float("inf"),  # total_return_pct: Inf (legacy)
                -5,  # total_trades: 음수 (legacy)
                float("nan"),  # sharpe_ratio: NaN (legacy)
                -200.0,  # max_drawdown_pct: 범위 외이지만 finite
                150.0,  # win_rate: 범위 초과 (legacy)
                "legacy summary",
                "legacy rationale",
                "",
                "",
                "{}",
                "",
                None,
            ),
        )

        # read path: list — raise 없이 통과해야 한다. 핵심 회귀: invalid metric이
        # 든 row를 ``_row_to_report``가 ``ValueError`` 없이 ``StrategyReport``로
        # 재구성해야 함 (codex r1 P2).
        #
        # 주의: SQLite REAL 컬럼은 IEEE-754 NaN을 NULL로 저장한다. ``Inf``는 보존
        # 되거나 NULL이 될 수 있다(드라이버/플랫폼 의존). 본 테스트는 raise 부재
        # + ``total_trades``/``win_rate``처럼 결정적으로 보존되는 invalid 값에
        # 한해 회귀를 고정한다.
        rows = await store.list_reports()
        legacy_rows = [r for r in rows if r.report_id == "rpt-legacy-invalid"]
        assert len(legacy_rows) == 1
        legacy = legacy_rows[0]
        assert legacy.total_trades == -5  # INTEGER 컬럼: 음수 그대로 보존
        assert legacy.win_rate == 150.0  # REAL: 유한값은 그대로 보존
        # sharpe_ratio (NaN)는 SQLite에서 NULL로 변환될 수 있음 → read 통과만 확인
        # total_return_pct (Inf)도 마찬가지로 read가 raise 없이 통과하면 충분
        # (모든 metric 비교는 raise 없이 도달했다는 사실로 갈음)

        # read path: get(report_id) — raise 없이 통과해야 한다.
        fetched = await store.get("rpt-legacy-invalid")
        assert fetched is not None
        assert fetched.report_id == "rpt-legacy-invalid"
        assert fetched.total_trades == -5
        assert fetched.win_rate == 150.0
