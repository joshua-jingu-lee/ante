"""inverted date range (``start_date > end_date``) 422 회귀 (#1595, oracle A7).

4개 read API(portfolio history, treasury transactions, treasury snapshots,
bot logs)가 ``start_date=2026-02-01&end_date=2026-01-01`` 같은 불가능한 기간을
400/422가 아니라 200 empty result로 silently 흡수하던 contract drift를
``ante.web.utils.date_params.reject_inverted_date_range`` 공유 헬퍼로 차단한다.

검증축:
* inverted → 422 (4 endpoint 전부)
* 회귀(유효 start<end) → 200
* 회귀(동일 날짜 start==end) → 200
* bot logs cross-offset tz-aware: UTC 정규화 후 역전만 422, 같은 UTC 시각/정상
  cross-offset은 200 (aware/naive ``TypeError`` 없음)
* 회귀(미지정/한쪽만) → 200 (기존 default 동작 보존)
* 회귀(기존 invalid date ``2026-13-32``) → 422 (#1440 동작 미변경)
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

httpx = pytest.importorskip("httpx", reason="httpx required for web API tests")


from ante.eventbus import EventBus  # noqa: E402
from ante.eventbus.events import BotStepCompletedEvent  # noqa: E402
from ante.web.app import create_app  # noqa: E402
from tests.unit.conftest import (  # noqa: E402
    make_authed_client,
    make_master_member_service,
)

INVERTED = {"start_date": "2026-02-01", "end_date": "2026-01-01"}
VALID = {"start_date": "2026-01-01", "end_date": "2026-02-01"}
SAME = {"start_date": "2026-01-15", "end_date": "2026-01-15"}


# ── 공유 stub ─────────────────────────────────────────────


class _StubDB:
    """``treasury._db`` 자리. transactions 라우트의 SQL은 빈 결과를 돌려준다."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def fetch_one(self, query: str, params: tuple) -> dict | None:
        self.calls.append(query)
        if "COUNT(*)" in query:
            return {"cnt": 0}
        return None

    async def fetch_all(self, query: str, params: tuple) -> list[dict]:
        self.calls.append(query)
        return []


def _make_treasury() -> MagicMock:
    mock = MagicMock()
    mock._db = _StubDB()
    mock.get_summary.return_value = {
        "total_evaluation": 0.0,
        "total_profit_loss": 0.0,
        "account_balance": 0.0,
    }
    mock.get_latest_snapshot = AsyncMock(return_value=None)
    mock.get_snapshots = AsyncMock(return_value=[])
    mock.get_daily_snapshot = AsyncMock(return_value=None)
    return mock


class _FakeBotConfig:
    def __init__(self, bot_id: str) -> None:
        self.bot_id = bot_id
        self.account_id = "test"


class _FakeBot:
    def __init__(self, bot_id: str) -> None:
        self.bot_id = bot_id
        self.config = _FakeBotConfig(bot_id)

    def get_info(self) -> dict[str, Any]:
        return {"bot_id": self.bot_id, "name": self.bot_id, "status": "running"}


class _FakeBotManager:
    def __init__(self) -> None:
        self._bots: dict[str, _FakeBot] = {"probe-bot": _FakeBot("probe-bot")}

    def get_bot(self, bot_id: str) -> _FakeBot | None:
        return self._bots.get(bot_id)


# ── fixtures ──────────────────────────────────────────────


@pytest.fixture
def treasury() -> MagicMock:
    return _make_treasury()


@pytest.fixture
def treasury_client(treasury: MagicMock):
    app = create_app(
        treasury=treasury,
        member_service=make_master_member_service(),
    )
    return make_authed_client(app)


@pytest.fixture
def bot_logs_client():
    eb = EventBus()
    bot_manager = _FakeBotManager()
    app = create_app(
        bot_manager=bot_manager,
        eventbus=eb,
        member_service=make_master_member_service(),
    )
    return make_authed_client(app)


# ── 422: inverted range (oracle A7 본문) ──────────────────


class TestInvertedRangeRejected422:
    """``start_date=2026-02-01&end_date=2026-01-01`` → 4곳 모두 422."""

    def test_portfolio_history_inverted_422(self, treasury_client) -> None:
        resp = treasury_client.get("/api/portfolio/history", params=INVERTED)
        assert resp.status_code == 422, resp.text

    def test_treasury_transactions_inverted_422(
        self, treasury_client, treasury: MagicMock
    ) -> None:
        resp = treasury_client.get(
            "/api/treasury/transactions",
            params={**INVERTED, "limit": 1},
        )
        assert resp.status_code == 422, resp.text
        # defense-in-depth: 422 거부 시 SQL이 호출되어선 안 된다.
        assert treasury._db.calls == [], treasury._db.calls

    def test_treasury_snapshots_inverted_422(self, treasury_client) -> None:
        resp = treasury_client.get("/api/treasury/snapshots", params=INVERTED)
        assert resp.status_code == 422, resp.text

    def test_bot_logs_inverted_422(self, bot_logs_client) -> None:
        resp = bot_logs_client.get(
            "/api/bots/probe-bot/logs",
            params={**INVERTED, "limit": 1},
        )
        assert resp.status_code == 422, resp.text


# ── 200: 유효/동일 날짜 회귀 ──────────────────────────────


class TestValidRangeRegression:
    """start<end (유효) 와 start==end (동일) 는 200 유지."""

    @pytest.mark.parametrize("params", [VALID, SAME])
    def test_portfolio_history_200(self, treasury_client, params: dict) -> None:
        resp = treasury_client.get("/api/portfolio/history", params=params)
        assert resp.status_code == 200, resp.text

    @pytest.mark.parametrize("params", [VALID, SAME])
    def test_treasury_transactions_200(self, treasury_client, params: dict) -> None:
        resp = treasury_client.get(
            "/api/treasury/transactions",
            params={**params, "limit": 1},
        )
        assert resp.status_code == 200, resp.text

    @pytest.mark.parametrize("params", [VALID, SAME])
    def test_treasury_snapshots_200(self, treasury_client, params: dict) -> None:
        resp = treasury_client.get("/api/treasury/snapshots", params=params)
        assert resp.status_code == 200, resp.text

    @pytest.mark.parametrize("params", [VALID, SAME])
    def test_bot_logs_200(self, bot_logs_client, params: dict) -> None:
        resp = bot_logs_client.get(
            "/api/bots/probe-bot/logs",
            params={**params, "limit": 1},
        )
        assert resp.status_code == 200, resp.text


# ── 200: 미지정/한쪽만 (기존 default 동작 보존) ──────────


class TestUnspecifiedRangeRegression:
    """start/end 생략 또는 한쪽만 지정 → 거부하지 않고 200."""

    @pytest.mark.parametrize(
        "params",
        [
            {},
            {"start_date": "2026-01-01"},
            {"end_date": "2026-02-01"},
        ],
    )
    def test_portfolio_history_unspecified_200(
        self, treasury_client, params: dict
    ) -> None:
        resp = treasury_client.get("/api/portfolio/history", params=params)
        assert resp.status_code == 200, resp.text

    @pytest.mark.parametrize(
        "params",
        [
            {"limit": 1},
            {"start_date": "2026-01-01", "limit": 1},
            {"end_date": "2026-02-01", "limit": 1},
        ],
    )
    def test_treasury_transactions_unspecified_200(
        self, treasury_client, params: dict
    ) -> None:
        resp = treasury_client.get("/api/treasury/transactions", params=params)
        assert resp.status_code == 200, resp.text

    @pytest.mark.parametrize(
        "params",
        [
            {},
            {"start_date": "2026-01-01"},
            {"end_date": "2026-02-01"},
        ],
    )
    def test_treasury_snapshots_unspecified_200(
        self, treasury_client, params: dict
    ) -> None:
        resp = treasury_client.get("/api/treasury/snapshots", params=params)
        assert resp.status_code == 200, resp.text

    @pytest.mark.parametrize(
        "params",
        [
            {"limit": 1},
            {"start_date": "2026-01-01", "limit": 1},
            {"end_date": "2026-02-01", "limit": 1},
        ],
    )
    def test_bot_logs_unspecified_200(self, bot_logs_client, params: dict) -> None:
        resp = bot_logs_client.get("/api/bots/probe-bot/logs", params=params)
        assert resp.status_code == 200, resp.text


# ── 422: 기존 invalid date (#1440 동작 미변경) ────────────


class TestExistingInvalidDateRegression:
    """``start_date=2026-13-32`` 는 기존대로 422 (inverted 추가가 회귀시키지 않음)."""

    def test_portfolio_history_invalid_date_422(self, treasury_client) -> None:
        resp = treasury_client.get(
            "/api/portfolio/history",
            params={"start_date": "2026-13-32"},
        )
        assert resp.status_code == 422, resp.text

    def test_treasury_transactions_invalid_date_422(self, treasury_client) -> None:
        resp = treasury_client.get(
            "/api/treasury/transactions",
            params={"start_date": "2026-13-32", "limit": 1},
        )
        assert resp.status_code == 422, resp.text

    def test_treasury_snapshots_invalid_date_422(self, treasury_client) -> None:
        resp = treasury_client.get(
            "/api/treasury/snapshots",
            params={"start_date": "2026-13-32"},
        )
        assert resp.status_code == 422, resp.text

    def test_bot_logs_invalid_date_422(self, bot_logs_client) -> None:
        resp = bot_logs_client.get(
            "/api/bots/probe-bot/logs",
            params={"start_date": "2026-13-32", "limit": 1},
        )
        assert resp.status_code == 422, resp.text


# ── bot logs tz-aware cross-offset ────────────────────────


class TestBotLogsTzAwareInverted:
    """offset 정규화 후 순서로 판정 (aware/naive ``TypeError`` 없음).

    ``start=2026-02-01T00:00:00+09:00`` (UTC 2026-01-31T15:00:00) &
    ``end=2026-01-01T00:00:00Z`` → UTC 비교 시 start > end → 422.
    같은 UTC 시각 / 정상 cross-offset range → 200.
    """

    def test_cross_offset_inverted_422(self, bot_logs_client) -> None:
        resp = bot_logs_client.get(
            "/api/bots/probe-bot/logs",
            params={
                "start_date": "2026-02-01T00:00:00+09:00",
                "end_date": "2026-01-01T00:00:00Z",
                "limit": 1,
            },
        )
        assert resp.status_code == 422, resp.text

    def test_cross_offset_same_utc_instant_200(self, bot_logs_client) -> None:
        # 2026-01-01T09:00:00+09:00 == 2026-01-01T00:00:00Z (동일 UTC 시각).
        # end는 그대로, start==end UTC → 역전 아님 → 200.
        resp = bot_logs_client.get(
            "/api/bots/probe-bot/logs",
            params={
                "start_date": "2026-01-01T09:00:00+09:00",
                "end_date": "2026-01-01T00:00:00Z",
                "limit": 1,
            },
        )
        assert resp.status_code == 200, resp.text

    def test_cross_offset_valid_range_200(self, bot_logs_client) -> None:
        # start UTC 2026-01-01T00:00 < end UTC 2026-02-01T00:00 → 200.
        resp = bot_logs_client.get(
            "/api/bots/probe-bot/logs",
            params={
                "start_date": "2026-01-01T09:00:00+09:00",
                "end_date": "2026-02-01T00:00:00Z",
                "limit": 1,
            },
        )
        assert resp.status_code == 200, resp.text

    def test_cross_offset_valid_range_returns_events(self, bot_logs_client) -> None:
        """정상 cross-offset에서 이벤트가 실제로 반환되어 비교가 silently
        empty가 아님을 확인."""

        async def _publish() -> None:
            # eventbus는 fixture 내부에서 만들었으므로 app.state로 접근.
            app = bot_logs_client.app  # type: ignore[attr-defined]
            eb = app.state.eventbus
            await eb.publish(
                BotStepCompletedEvent(
                    bot_id="probe-bot",
                    account_id="test",
                    result="success",
                    message="signals=1",
                )
            )

        asyncio.get_event_loop().run_until_complete(_publish())
        resp = bot_logs_client.get(
            "/api/bots/probe-bot/logs",
            params={
                "start_date": "2020-01-01T00:00:00Z",
                "end_date": "2030-01-01T00:00:00Z",
                "limit": 10,
            },
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["logs"], resp.text
