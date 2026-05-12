"""``StrategyReport`` dataclass invariant 가드 단위 테스트 (#1415).

``StrategyReport.__post_init__``는 defense-in-depth 가드로, CLI/Web API/내부
호출자를 통해 들어오는 invalid 값이 ReportStore까지 흘러가는 것을 차단한다.

SSOT:
- ``src/ante/web/schemas.py::ReportSubmitRequest`` — 입력 검증 SSOT
- ``src/ante/report/models.py::StrategyReport`` — dataclass guard (본 모듈)

검증 대상 invariants:
- ``total_trades >= 0``
- ``win_rate ∈ [0.0, 100.0]`` 또는 ``None``
- ``total_return_pct``/``sharpe_ratio``/``max_drawdown_pct``/``win_rate``는 finite

또한 ``ReportStore._row_to_report``가 정상 DB row를 회귀 통과시키는지 검증해
**legacy DB row 재구성 회귀**를 보호한다.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from ante.core.database import Database
from ante.report.models import ReportStatus, StrategyReport
from ante.report.store import ReportStore


def _kwargs(**overrides) -> dict:
    """invariant 통과 가능한 최소 dataclass kwargs."""
    base = {
        "report_id": "rpt-invariant",
        "strategy_name": "invariant_probe",
        "strategy_version": "0.1.0",
        "strategy_path": "strategies/probe.py",
        "status": ReportStatus.SUBMITTED,
        "submitted_at": datetime.now(tz=UTC),
    }
    base.update(overrides)
    return base


# ── total_trades ────────────────────────────────────────────


class TestTotalTradesGuard:
    def test_negative_raises(self) -> None:
        with pytest.raises(ValueError, match="total_trades"):
            StrategyReport(**_kwargs(total_trades=-1))

    @pytest.mark.parametrize("value", [0, 1, 100])
    def test_non_negative_ok(self, value: int) -> None:
        # raises 없으면 통과
        StrategyReport(**_kwargs(total_trades=value))


# ── win_rate ────────────────────────────────────────────────


class TestWinRateGuard:
    def test_above_100_raises(self) -> None:
        with pytest.raises(ValueError, match="win_rate"):
            StrategyReport(**_kwargs(win_rate=101.0))

    def test_negative_raises(self) -> None:
        with pytest.raises(ValueError, match="win_rate"):
            StrategyReport(**_kwargs(win_rate=-0.1))

    @pytest.mark.parametrize("value", [0.0, 0.58, 50.0, 58.0, 100.0])
    def test_in_range_ok(self, value: float) -> None:
        StrategyReport(**_kwargs(win_rate=value))

    def test_none_ok(self) -> None:
        StrategyReport(**_kwargs(win_rate=None))


# ── finite invariant ────────────────────────────────────────


class TestFiniteGuard:
    @pytest.mark.parametrize(
        "field",
        ["total_return_pct", "sharpe_ratio", "max_drawdown_pct"],
    )
    def test_nan_raises(self, field: str) -> None:
        with pytest.raises(ValueError, match=f"{field}.*finite"):
            StrategyReport(**_kwargs(**{field: float("nan")}))

    @pytest.mark.parametrize(
        "field",
        ["total_return_pct", "sharpe_ratio", "max_drawdown_pct"],
    )
    def test_inf_raises(self, field: str) -> None:
        with pytest.raises(ValueError, match=f"{field}.*finite"):
            StrategyReport(**_kwargs(**{field: float("inf")}))

    def test_win_rate_nan_raises(self) -> None:
        # win_rate은 range 가드가 먼저 발동 (NaN은 [0, 100] 비교에서 False가 되어
        # range 에러로 raise). 두 가드 중 하나라도 차단하면 됨.
        with pytest.raises(ValueError):
            StrategyReport(**_kwargs(win_rate=float("nan")))


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
    """``_row_to_report``가 정상 row를 그대로 재구성하는지 검증.

    ``StrategyReport.__post_init__`` 가드가 추가됨으로써 legacy DB row 로딩 시
    raise가 발생할 가능성을 회귀 검증한다. 새 DB에서는 invalid 값이 저장될 입구가
    없으므로 (CLI: #1415로 닫힘, Web API: 이미 닫힘, draft.py: default 통과)
    정상 row는 그대로 통과해야 한다.
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
        """정상 값을 submit한 뒤 get으로 재구성해도 가드를 통과해야 함."""
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
