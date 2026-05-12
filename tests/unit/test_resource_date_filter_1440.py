"""Portfolio history / Treasury snapshots / transactions의 ISO date-only 검증
회귀 테스트 (Issue #1440).

oracle A7 시그니처에서 발견된 contract drift: 아래 4개 endpoint가
``start_date``/``end_date``/path ``{date}`` 파라미터로 임의 문자열
(``oracle-not-a-date``)을 200으로 통과시켰다. 본 PR은 핸들러 진입 직전에
공용 헬퍼 ``ante.web.utils.date_params``를 호출해 ISO ``YYYY-MM-DD``만
허용하도록 강제한다.

대상 4개 endpoint:

* ``GET /api/portfolio/history``  (start_date/end_date)
* ``GET /api/treasury/snapshots`` (start_date/end_date)
* ``GET /api/treasury/snapshots/{date}`` (path)
* ``GET /api/treasury/transactions`` (start_date/end_date)

핵심 invariants (Implementation Plan v2 + Codex Plan Review r1 findings):

* invalid 입력(``oracle-not-a-date``) → 422.
* 캘린더 invalid (``2026-13-32``, ``2026-02-30``) → 422. ``datetime.strptime``
  방식이므로 정규식만으로 막을 수 없는 케이스도 잡힌다.
* valid 입력(``2026-05-01``) → 200 회귀 (기존 caller 패턴 보호).
* default 입력(no date) → 200 회귀.
* malformed path ``/api/treasury/snapshots/not-a-date`` → 422 (404 아님).
  FastAPI ``Path(pattern=...)`` 정규식 일차 차단.
* transactions ``start_date=2026-05-01`` → SQL 호출에
  ``'2026-05-01 00:00:00'``이 포함된다. ``end_date``는 ``'... 23:59:59'``로
  확장된다. ``treasury_transactions.created_at``의 SQLite
  ``datetime('now')`` 포맷(``YYYY-MM-DD HH:MM:SS``)과 일치.

SSOT: ``docs/specs/web-api/05-resource-endpoints.md``는 4개 endpoint를
"필터: account_id, start_date, end_date, ..."로 명시하며 free-form 허용
명시는 없다. ISO 8601 강제는 spec drift 교정에 해당한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock

import pytest

httpx = pytest.importorskip("httpx", reason="httpx required for web API tests")

from ante.web.app import create_app  # noqa: E402
from tests.unit.conftest import (  # noqa: E402
    make_authed_client,
    make_master_member_service,
)

# ──────────────────────────────────────────────────────────────────────
# Fake DB / Treasury fixtures
# ──────────────────────────────────────────────────────────────────────


@dataclass
class _SQLCall:
    """``db.fetch_all`` / ``db.fetch_one`` 호출 인자 기록용."""

    query: str
    params: tuple


class _SpyDB:
    """``treasury._db`` 자리에 들어가는 mock DB. SQL 호출과 params를 기록한다."""

    def __init__(self) -> None:
        self.calls: list[_SQLCall] = []

    async def fetch_one(self, query: str, params: tuple) -> dict | None:
        self.calls.append(_SQLCall(query=query, params=tuple(params)))
        if "COUNT(*)" in query:
            return {"cnt": 0}
        return None

    async def fetch_all(self, query: str, params: tuple) -> list[dict]:
        self.calls.append(_SQLCall(query=query, params=tuple(params)))
        return []


_SNAPSHOT_FIXTURE = {
    "account_id": "acc-001",
    "snapshot_date": "2026-05-01",
    "total_asset": 50_000_000.0,
    "ante_eval_amount": 40_000_000.0,
    "ante_purchase_amount": 38_000_000.0,
    "unallocated": 10_000_000.0,
    "account_balance": 10_000_000.0,
    "total_allocated": 40_000_000.0,
    "bot_count": 3,
    "daily_pnl": 500_000.0,
    "daily_return": 1.01,
    "net_trade_amount": 200_000.0,
    "unrealized_pnl": 2_000_000.0,
    "created_at": "2026-05-01T18:00:00+09:00",
}


@pytest.fixture
def spy_db() -> _SpyDB:
    return _SpyDB()


@pytest.fixture
def treasury(spy_db: _SpyDB) -> MagicMock:
    """portfolio + treasury 양쪽 라우트가 공유할 mock Treasury.

    * ``_db``: transactions 라우트 SQL spy.
    * ``get_snapshots`` / ``get_daily_snapshot``: snapshots/history 라우트가
      호출하는 async 인터페이스. valid 호출일 때만 fixture가 도달하므로
      여기서는 단순히 빈 리스트 / fixture 데이터를 반환.
    """
    mock = MagicMock()
    mock._db = spy_db
    mock.get_summary.return_value = {
        "total_evaluation": 0.0,
        "account_balance": 0.0,
    }
    mock.get_latest_snapshot = AsyncMock(return_value=None)
    mock.get_snapshots = AsyncMock(return_value=[])
    mock.get_daily_snapshot = AsyncMock(return_value=_SNAPSHOT_FIXTURE)
    return mock


@pytest.fixture
def client(treasury: MagicMock):
    app = create_app(
        treasury=treasury,
        member_service=make_master_member_service(),
    )
    return make_authed_client(app)


# ──────────────────────────────────────────────────────────────────────
# 422: invalid date 파라미터 (oracle A7 본문)
# ──────────────────────────────────────────────────────────────────────

_INVALID_FREEFORM = "oracle-not-a-date"
_INVALID_CALENDAR_MONTH = "2026-13-32"
_INVALID_CALENDAR_DAY = "2026-02-30"


class TestPortfolioHistoryInvalidDate:
    """``GET /api/portfolio/history`` invalid date 거부."""

    @pytest.mark.parametrize("field", ["start_date", "end_date"])
    def test_freeform_string_returns_422(self, client, treasury, field) -> None:
        resp = client.get(
            "/api/portfolio/history",
            params={field: _INVALID_FREEFORM},
        )
        assert resp.status_code == 422, (
            f"portfolio history {field}={_INVALID_FREEFORM!r} → "
            f"{resp.status_code} ({resp.text})"
        )
        treasury.get_snapshots.assert_not_awaited()

    @pytest.mark.parametrize("field", ["start_date", "end_date"])
    @pytest.mark.parametrize(
        "invalid",
        [_INVALID_CALENDAR_MONTH, _INVALID_CALENDAR_DAY],
    )
    def test_calendar_invalid_returns_422(
        self, client, treasury, field, invalid
    ) -> None:
        resp = client.get(
            "/api/portfolio/history",
            params={field: invalid},
        )
        assert resp.status_code == 422, (
            f"portfolio history {field}={invalid!r} (calendar invalid) → "
            f"{resp.status_code} ({resp.text})"
        )
        treasury.get_snapshots.assert_not_awaited()


class TestTreasurySnapshotsInvalidDate:
    """``GET /api/treasury/snapshots`` invalid start/end_date 거부."""

    @pytest.mark.parametrize("field", ["start_date", "end_date"])
    def test_freeform_string_returns_422(self, client, treasury, field) -> None:
        resp = client.get(
            "/api/treasury/snapshots",
            params={field: _INVALID_FREEFORM},
        )
        assert resp.status_code == 422, (
            f"treasury snapshots {field}={_INVALID_FREEFORM!r} → "
            f"{resp.status_code} ({resp.text})"
        )
        treasury.get_snapshots.assert_not_awaited()

    @pytest.mark.parametrize("field", ["start_date", "end_date"])
    @pytest.mark.parametrize(
        "invalid",
        [_INVALID_CALENDAR_MONTH, _INVALID_CALENDAR_DAY],
    )
    def test_calendar_invalid_returns_422(
        self, client, treasury, field, invalid
    ) -> None:
        resp = client.get(
            "/api/treasury/snapshots",
            params={field: invalid},
        )
        assert resp.status_code == 422
        treasury.get_snapshots.assert_not_awaited()


class TestTreasurySnapshotByDateInvalidPath:
    """``GET /api/treasury/snapshots/{date}`` invalid path 거부.

    이전 구현은 임의 path를 ``get_daily_snapshot``에 그대로 넘기고, None
    반환 시 404로 응답했다 (oracle: ``snapshot-by-date returns 404 for
    not-a-date``). 본 PR은 ``Path(pattern=...)`` + handler defense로
    malformed/캘린더 invalid path를 422로 거부한다.
    """

    def test_freeform_path_returns_422(self, client, treasury) -> None:
        resp = client.get(f"/api/treasury/snapshots/{_INVALID_FREEFORM}")
        assert resp.status_code == 422, (
            f"snapshots/{_INVALID_FREEFORM} → {resp.status_code} ({resp.text}). "
            "malformed path는 404가 아닌 422로 거부되어야 한다."
        )
        treasury.get_daily_snapshot.assert_not_awaited()

    def test_calendar_invalid_path_returns_422(self, client, treasury) -> None:
        """``2026-13-32``는 정규식 ``^\\d{4}-\\d{2}-\\d{2}$``는 통과하지만
        ``datetime.strptime``에서 거부된다 (defense-in-depth)."""
        resp = client.get(f"/api/treasury/snapshots/{_INVALID_CALENDAR_MONTH}")
        assert resp.status_code == 422, (
            f"snapshots/{_INVALID_CALENDAR_MONTH} (calendar invalid) → "
            f"{resp.status_code} ({resp.text})"
        )
        treasury.get_daily_snapshot.assert_not_awaited()

    def test_calendar_invalid_day_path_returns_422(self, client, treasury) -> None:
        resp = client.get(f"/api/treasury/snapshots/{_INVALID_CALENDAR_DAY}")
        assert resp.status_code == 422
        treasury.get_daily_snapshot.assert_not_awaited()


class TestTreasuryTransactionsInvalidDate:
    """``GET /api/treasury/transactions`` invalid start/end_date 거부.

    transactions endpoint는 ``treasury._db.fetch_*`` SQL을 직접 호출한다.
    422 거부 시 SQL이 단 한 번도 호출되지 않아야 한다.
    """

    @pytest.mark.parametrize("field", ["start_date", "end_date"])
    def test_freeform_string_returns_422(self, client, spy_db: _SpyDB, field) -> None:
        resp = client.get(
            "/api/treasury/transactions",
            params={field: _INVALID_FREEFORM},
        )
        assert resp.status_code == 422, (
            f"treasury transactions {field}={_INVALID_FREEFORM!r} → "
            f"{resp.status_code} ({resp.text})"
        )
        assert spy_db.calls == [], (
            "422 거부 시 SQL이 호출되어선 안 된다 (defense-in-depth). "
            f"실제 호출: {spy_db.calls}"
        )

    @pytest.mark.parametrize("field", ["start_date", "end_date"])
    @pytest.mark.parametrize(
        "invalid",
        [_INVALID_CALENDAR_MONTH, _INVALID_CALENDAR_DAY],
    )
    def test_calendar_invalid_returns_422(
        self, client, spy_db: _SpyDB, field, invalid
    ) -> None:
        resp = client.get(
            "/api/treasury/transactions",
            params={field: invalid},
        )
        assert resp.status_code == 422
        assert spy_db.calls == []


# ──────────────────────────────────────────────────────────────────────
# 200: valid date 회귀 (기존 caller 패턴 보호)
# ──────────────────────────────────────────────────────────────────────


class TestValidDateRegression:
    """정상 ``YYYY-MM-DD`` 입력과 default(no date) 둘 다 200을 회귀 확인."""

    def test_portfolio_history_valid_dates(self, client, treasury) -> None:
        resp = client.get(
            "/api/portfolio/history",
            params={"start_date": "2026-05-01", "end_date": "2026-05-13"},
        )
        assert resp.status_code == 200, resp.text
        treasury.get_snapshots.assert_awaited_once_with("2026-05-01", "2026-05-13")

    def test_portfolio_history_default_no_date(self, client) -> None:
        resp = client.get("/api/portfolio/history")
        assert resp.status_code == 200, resp.text

    def test_treasury_snapshots_valid_dates(self, client, treasury) -> None:
        resp = client.get(
            "/api/treasury/snapshots",
            params={"start_date": "2026-05-01", "end_date": "2026-05-13"},
        )
        assert resp.status_code == 200, resp.text
        treasury.get_snapshots.assert_awaited_once_with("2026-05-01", "2026-05-13")

    def test_treasury_snapshots_default_no_date(self, client) -> None:
        resp = client.get("/api/treasury/snapshots")
        assert resp.status_code == 200, resp.text

    def test_treasury_snapshot_by_date_valid(self, client, treasury) -> None:
        resp = client.get("/api/treasury/snapshots/2026-05-01")
        assert resp.status_code == 200, resp.text
        treasury.get_daily_snapshot.assert_awaited_once_with("2026-05-01")

    def test_treasury_transactions_valid_dates(self, client, spy_db: _SpyDB) -> None:
        resp = client.get(
            "/api/treasury/transactions",
            params={"start_date": "2026-05-01", "end_date": "2026-05-13"},
        )
        assert resp.status_code == 200, resp.text
        # SQL이 최소 한 번 이상 호출되었어야 한다 (COUNT + SELECT).
        assert len(spy_db.calls) >= 1

    def test_treasury_transactions_default_no_date(
        self, client, spy_db: _SpyDB
    ) -> None:
        resp = client.get("/api/treasury/transactions")
        assert resp.status_code == 200, resp.text


# ──────────────────────────────────────────────────────────────────────
# SQL boundary 검증 (transactions만 — created_at SQLite datetime 포맷)
# ──────────────────────────────────────────────────────────────────────


class TestTransactionsSQLBoundary:
    """transactions endpoint의 SQL params가 SQLite ``datetime('now')`` 포맷
    (``YYYY-MM-DD HH:MM:SS``) boundary를 정확히 전달하는지 검증.

    plan v2 Codex Plan Review r1 finding: ``treasury_transactions.created_at``
    은 bot logs의 ISO datetime과 달리 SQLite ``YYYY-MM-DD HH:MM:SS`` 포맷이다.
    boundary 확장이 잘못되면 SQL 텍스트 비교에서 inclusive bound가 깨진다.
    """

    def test_start_date_expands_to_zero_oclock(self, client, spy_db: _SpyDB) -> None:
        """``start_date=2026-05-01`` → SQL params에 ``'2026-05-01 00:00:00'``."""
        resp = client.get(
            "/api/treasury/transactions",
            params={"start_date": "2026-05-01"},
        )
        assert resp.status_code == 200, resp.text
        # COUNT 또는 SELECT의 어느 쪽 params에라도 boundary string이 들어가야 한다.
        all_params: list = []
        for call in spy_db.calls:
            all_params.extend(call.params)
        assert "2026-05-01 00:00:00" in all_params, (
            f"start_date=2026-05-01의 SQL boundary가 누락됐다. "
            f"실제 params: {all_params}"
        )

    def test_end_date_expands_to_end_of_day(self, client, spy_db: _SpyDB) -> None:
        """``end_date=2026-05-01`` → SQL params에 ``'2026-05-01 23:59:59'``."""
        resp = client.get(
            "/api/treasury/transactions",
            params={"end_date": "2026-05-01"},
        )
        assert resp.status_code == 200, resp.text
        all_params: list = []
        for call in spy_db.calls:
            all_params.extend(call.params)
        assert "2026-05-01 23:59:59" in all_params, (
            f"end_date=2026-05-01의 SQL boundary가 누락됐다. 실제 params: {all_params}"
        )

    def test_both_dates_emit_both_boundaries(self, client, spy_db: _SpyDB) -> None:
        resp = client.get(
            "/api/treasury/transactions",
            params={
                "start_date": "2026-05-01",
                "end_date": "2026-05-13",
            },
        )
        assert resp.status_code == 200, resp.text
        all_params: list = []
        for call in spy_db.calls:
            all_params.extend(call.params)
        assert "2026-05-01 00:00:00" in all_params
        assert "2026-05-13 23:59:59" in all_params


# ──────────────────────────────────────────────────────────────────────
# helper unit (date_params 자체)
# ──────────────────────────────────────────────────────────────────────


class TestDateParamHelper:
    """``ante.web.utils.date_params`` 헬퍼 단위 테스트."""

    def test_validate_iso_date_only_passes_valid(self) -> None:
        from ante.web.utils.date_params import validate_iso_date_only

        assert validate_iso_date_only("2026-05-01", "start_date") == "2026-05-01"

    def test_validate_iso_date_only_none_passthrough(self) -> None:
        from ante.web.utils.date_params import validate_iso_date_only

        assert validate_iso_date_only(None, "start_date") is None

    def test_validate_iso_date_only_rejects_freeform(self) -> None:
        from fastapi import HTTPException

        from ante.web.utils.date_params import validate_iso_date_only

        with pytest.raises(HTTPException) as exc:
            validate_iso_date_only("oracle-not-a-date", "start_date")
        assert exc.value.status_code == 422

    def test_validate_iso_date_only_rejects_calendar_invalid(self) -> None:
        from fastapi import HTTPException

        from ante.web.utils.date_params import validate_iso_date_only

        with pytest.raises(HTTPException) as exc:
            validate_iso_date_only("2026-13-32", "date")
        assert exc.value.status_code == 422

    def test_sql_datetime_helper_start_bound(self) -> None:
        from ante.web.utils.date_params import (
            validate_iso_date_param_for_sql_datetime,
        )

        assert (
            validate_iso_date_param_for_sql_datetime(
                "2026-05-01", "start_date", end_of_day=False
            )
            == "2026-05-01 00:00:00"
        )

    def test_sql_datetime_helper_end_bound(self) -> None:
        from ante.web.utils.date_params import (
            validate_iso_date_param_for_sql_datetime,
        )

        assert (
            validate_iso_date_param_for_sql_datetime(
                "2026-05-01", "end_date", end_of_day=True
            )
            == "2026-05-01 23:59:59"
        )

    def test_sql_datetime_helper_none_passthrough(self) -> None:
        from ante.web.utils.date_params import (
            validate_iso_date_param_for_sql_datetime,
        )

        assert (
            validate_iso_date_param_for_sql_datetime(
                None, "start_date", end_of_day=False
            )
            is None
        )

    def test_sql_datetime_helper_rejects_calendar_invalid(self) -> None:
        from fastapi import HTTPException

        from ante.web.utils.date_params import (
            validate_iso_date_param_for_sql_datetime,
        )

        with pytest.raises(HTTPException) as exc:
            validate_iso_date_param_for_sql_datetime(
                "2026-02-30", "start_date", end_of_day=False
            )
        assert exc.value.status_code == 422
