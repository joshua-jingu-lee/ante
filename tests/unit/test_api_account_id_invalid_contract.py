"""제공된 runtime-invalid ``account_id`` read-API ingress 422 회귀 (#1624, oracle A7).

account-scoped Web **READ** API query 표면(inventory #1~#10)이 제공된
runtime-invalid ``account_id`` (``"default"``/패턴위반/``""``)를
``docs/specs/account/14-account-id-contract.md`` "Runtime invalid (어떤 시점에도
거부)" 계약대로 ingress에서 거부하지 않고 404/500/200-empty로 흘리던
contract-drift(fingerprint ``46e7221b5bac``)를
``ante.web.utils.account_params.reject_invalid_account_id`` 공유 가드로 차단한다.

검증축 (이슈 Verification SSOT):

1. inventory #1~#10 × {``default``, ``bad_id``(패턴위반), ``""``} → 422 +
   ``application/problem+json`` + ``type=/errors/validation``
2. ``account_id`` 미지정(query 파라미터 부재 → ``None``) → 기존 응답/status
   동일 (#1218 omitted all-account/단일-treasury 분기 회귀 0)
3. valid-pattern but absent(``acc-9999``, 패턴 일치·미존재) per-flow 기대값
   고정 — resolver/detail 계열(#1/#2/#4/#6/#7/#8)=404, list-filter 계열
   (#3 trades/#5 transactions/#10 bots)=기존 200 empty, #9 strategy
   performance=404 (invalid-format/fallback ↔ genuine not-found 분리, 422
   과적용 0)

#3 trades는 특히 ingress 가드가 ``TradeService.get_trades`` downstream의
``require_account_id`` → ``InvalidAccountIdError`` → Web generic 500 escape
경로보다 **먼저** 422를 반환함을 검증한다 (stub이 실제 recorder 계약 미러).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

httpx = pytest.importorskip("httpx", reason="httpx required for web API tests")


from ante.account.scoping import require_account_id  # noqa: E402
from ante.web.app import create_app  # noqa: E402
from tests.unit.conftest import (  # noqa: E402
    make_authed_client,
    make_master_member_service,
)

# 제공된 runtime-invalid 값 3종 (이슈 Verification 축 1).
INVALID_VALUES = ["default", "bad_id!", ""]
# 패턴 일치·미존재 (이슈 Verification 축 3 — 422 과적용 방지).
ABSENT_VALID = "acc-9999"


# ── 공유 stub ─────────────────────────────────────────────


class _StubDB:
    """``treasury._db`` + strategies ``get_db`` 자리.

    - treasury transactions(#5): ``COUNT(*)`` → 0, 본문 → ``[]`` (200 empty).
    - strategy performance(#9): ``SELECT 1 FROM accounts WHERE account_id=?``
      → 항상 ``None`` (계좌 미존재 → 404). ``acc-9999`` 패턴 일치이나
      미존재이므로 genuine not-found 404.
    """

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
    mock.account_id = "test"
    mock.currency = "KRW"
    # response_model 정합: 미설정 시 MagicMock이 ``synced_at`` str 검증을
    # 깨므로 None으로 둬 해당 optional 필드를 제외시킨다 (stub 충실도).
    mock.last_synced_at = None
    mock.buy_commission_rate = 0.00015
    mock.sell_commission_rate = 0.00195
    mock.get_summary.return_value = {
        "total_evaluation": 0.0,
        "total_profit_loss": 0.0,
        "account_balance": 0.0,
    }
    mock.get_latest_snapshot = AsyncMock(return_value=None)
    mock.get_snapshots = AsyncMock(return_value=[])
    mock.get_daily_snapshot = AsyncMock(return_value=None)
    return mock


class _StubTreasuryManager:
    """``treasury_manager`` 자리.

    ``get(account_id)``: 미존재 계좌는 ``KeyError`` (resolver/get_summary가
    404로 정규화). 어떤 valid account도 등록돼 있지 않으므로 ``acc-9999``는
    KeyError → 404 (resolver/detail 계열 valid-absent 기대값).
    """

    def __init__(self) -> None:
        self._t: dict[str, Any] = {}

    def get(self, account_id: str) -> Any:
        if account_id not in self._t:
            raise KeyError(account_id)
        return self._t[account_id]

    def list_all(self) -> list[Any]:
        return list(self._t.values())


class _StubTradeService:
    """``TradeService`` 자리 — ``recorder.get_trades`` 계약 미러.

    실제 ``TradeRecorder.get_trades``는 ``account_id is not None``일 때
    ``require_account_id``를 호출해 runtime-invalid면
    ``InvalidAccountIdError``를 raise한다 (Web generic 500 escape 경로).
    ingress 가드가 이 호출 **이전**에 422를 반환함을 검증하기 위해 동일
    계약을 stub에 재현한다. valid account는 빈 목록 반환 (200 empty).
    """

    def __init__(self) -> None:
        self.called_with: list[str | None] = []

    async def get_trades(self, *, account_id: str | None = None, **_: Any) -> list[Any]:
        self.called_with.append(account_id)
        if account_id is not None:
            require_account_id(account_id, context="trade_recorder.get_trades")
        return []


class _StubRegistry:
    """``strategy_registry`` 자리. 전략은 존재하므로 strategy-not-found(404)
    가 account 가드/검증을 가리지 않는다."""

    def __init__(self) -> None:
        self._record = MagicMock(
            name="strat-x",
            author_name="a",
            author_id="a",
        )

    async def get(self, strategy_id: str) -> Any:
        return self._record


class _StubBotManager:
    """``bot_manager`` 자리.

    - list_bots(#10): valid account 필터는 매칭 0건 → 200 empty.
    - get_strategy_performance(#9): ``_find_bot_for_strategy``가 봇을 찾지
      못하도록 빈 목록 — query account_id 경로만 검증 (omitted→400 분기는
      #1218 보존, 별도 케이스).
    """

    def list_bots(self) -> list[dict]:
        return [{"bot_id": "b1", "account_id": "test", "strategy_id": ""}]


# ── fixtures ──────────────────────────────────────────────


@pytest.fixture
def treasury() -> MagicMock:
    return _make_treasury()


@pytest.fixture
def trade_service() -> _StubTradeService:
    return _StubTradeService()


@pytest.fixture
def app_client(treasury: MagicMock, trade_service: _StubTradeService):
    """inventory #1~#10 전체를 한 app에 마운트한 authed client."""
    app = create_app(
        treasury=treasury,
        treasury_manager=_StubTreasuryManager(),
        trade_service=trade_service,
        strategy_registry=_StubRegistry(),
        bot_manager=_StubBotManager(),
        db=_StubDB(),
        member_service=make_master_member_service(),
    )
    return make_authed_client(app)


# inventory # → (method path, extra params). account_id는 케이스에서 주입.
INVENTORY: dict[int, tuple[str, dict[str, Any]]] = {
    1: ("/api/portfolio/value", {}),
    2: ("/api/portfolio/history", {}),
    3: ("/api/trades", {"limit": 1}),
    4: ("/api/treasury", {}),
    5: ("/api/treasury/transactions", {"limit": 1}),
    6: ("/api/treasury/snapshots", {}),
    7: ("/api/treasury/snapshots/latest", {}),
    8: ("/api/treasury/snapshots/2026-01-15", {}),
    9: ("/api/strategies/strat-x/performance", {}),
    10: ("/api/bots", {"limit": 1}),
}

# valid-pattern but absent per-flow 기대값 (이슈 Verification 축 3).
# resolver/detail 계열 + strategy perf = 404, list-filter 계열 = 200 empty.
ABSENT_EXPECTED_STATUS: dict[int, int] = {
    1: 404,
    2: 404,
    3: 200,
    4: 404,
    5: 200,
    6: 404,
    7: 404,
    8: 404,
    9: 404,
    10: 200,
}


# ── 축 1: 제공된 runtime-invalid → 422 problem+json ───────


class TestProvidedInvalidRejected422:
    """inventory #1~#10 × {default, bad_id, ""} → 422 + problem+json +
    ``type=/errors/validation``."""

    @pytest.mark.parametrize("inv", sorted(INVENTORY))
    @pytest.mark.parametrize("value", INVALID_VALUES)
    def test_invalid_account_id_422(self, app_client, inv: int, value: str) -> None:
        path, params = INVENTORY[inv]
        resp = app_client.get(path, params={**params, "account_id": value})
        assert resp.status_code == 422, (
            f"inv#{inv} {path} account_id={value!r}: {resp.status_code} {resp.text}"
        )
        assert resp.headers["content-type"] == "application/problem+json", (
            f"inv#{inv} ct={resp.headers.get('content-type')}"
        )
        body = resp.json()
        assert body["type"] == "/errors/validation", f"inv#{inv} {body}"
        assert body["status"] == 422, f"inv#{inv} {body}"
        # traceback 노출 금지: detail은 스펙 보존 메시지여야 한다.
        assert "Traceback" not in body["detail"], f"inv#{inv} {body}"
        assert "account_id" in body["detail"], f"inv#{inv} {body}"

    def test_trades_invalid_blocks_before_service_500_escape(
        self, app_client, trade_service: _StubTradeService
    ) -> None:
        """#3: 가드가 ``TradeService.get_trades`` 위임 이전에 422를 반환 —
        downstream ``InvalidAccountIdError`` → generic 500 escape 차단."""
        resp = app_client.get(
            "/api/trades", params={"account_id": "default", "limit": 1}
        )
        assert resp.status_code == 422, resp.text
        # service가 아예 호출되지 않아야 한다 (ingress 차단 증명).
        assert trade_service.called_with == [], trade_service.called_with


# ── 축 2: omitted(None) → 기존 동작/status 불변 (#1218 회귀 0) ──


class TestOmittedAccountIdRegression:
    """``account_id`` query 파라미터 부재 → 가드 통과, 기존 status 유지.

    #1/#2/#4/#6/#7/#10 = 200 (단일-treasury/all-account 분기), #3/#5 = 200
    (전체 필터), #8 = 404 (snapshot 미존재, account 무관), #9 = 400
    (#1218 omitted + 봇 추출 불가 정책 보존, **422 아님**)."""

    OMITTED_EXPECTED: dict[int, int] = {
        1: 200,
        2: 200,
        3: 200,
        4: 200,
        5: 200,
        6: 200,
        7: 200,
        8: 404,
        9: 400,
        10: 200,
    }

    @pytest.mark.parametrize("inv", sorted(INVENTORY))
    def test_omitted_account_id_preserved(self, app_client, inv: int) -> None:
        path, params = INVENTORY[inv]
        resp = app_client.get(path, params=params)
        expected = self.OMITTED_EXPECTED[inv]
        assert resp.status_code == expected, (
            f"inv#{inv} {path} omitted: expected {expected} got "
            f"{resp.status_code} {resp.text}"
        )
        # 핵심: omitted는 절대 422가 아니어야 한다 (#1218 회귀 0).
        assert resp.status_code != 422, f"inv#{inv} omitted leaked 422"


# ── 축 3: valid-pattern but absent → per-flow (422 과적용 0) ──


class TestValidPatternButAbsentPerFlow:
    """``account_id=acc-9999`` (패턴 일치·미존재): invalid-format ↔ genuine
    not-found 분리. resolver/detail+strategy=404, list-filter=200 empty.
    어느 경로도 422가 아니다 (가드 과적용 0)."""

    @pytest.mark.parametrize("inv", sorted(INVENTORY))
    def test_valid_absent_per_flow(self, app_client, inv: int) -> None:
        path, params = INVENTORY[inv]
        resp = app_client.get(path, params={**params, "account_id": ABSENT_VALID})
        expected = ABSENT_EXPECTED_STATUS[inv]
        assert resp.status_code == expected, (
            f"inv#{inv} {path} account_id={ABSENT_VALID}: expected "
            f"{expected} got {resp.status_code} {resp.text}"
        )
        # 핵심: valid-pattern은 절대 가드 422를 맞으면 안 된다 (과적용 0).
        assert resp.status_code != 422, (
            f"inv#{inv} valid-but-absent leaked 422 (가드 과적용)"
        )

    def test_trades_valid_absent_reaches_service_200(
        self, app_client, trade_service: _StubTradeService
    ) -> None:
        """#3: valid-but-absent는 가드를 통과해 service에 도달, 200 empty.

        ``TradeService.get_trades``가 ``acc-9999``로 호출되고
        ``require_account_id``가 valid로 통과(빈 목록)함을 확인 —
        invalid-format와 genuine-absent의 동작 분리 증명."""
        resp = app_client.get(
            "/api/trades",
            params={"account_id": ABSENT_VALID, "limit": 1},
        )
        assert resp.status_code == 200, resp.text
        assert trade_service.called_with == [ABSENT_VALID], trade_service.called_with
        assert resp.json()["trades"] == []


# ── OpenAPI 422 entry 동기 ────────────────────────────────


class TestOpenAPI422Documented:
    """inventory #1~#10 라우트가 OpenAPI ``responses``에 422 +
    ``application/problem+json`` 매핑을 노출한다."""

    OPENAPI_PATHS: dict[int, str] = {
        1: "/api/portfolio/value",
        2: "/api/portfolio/history",
        3: "/api/trades",
        4: "/api/treasury",
        5: "/api/treasury/transactions",
        6: "/api/treasury/snapshots",
        7: "/api/treasury/snapshots/latest",
        8: "/api/treasury/snapshots/{date}",
        9: "/api/strategies/{strategy_id}/performance",
        10: "/api/bots",
    }

    @pytest.mark.parametrize("inv", sorted(OPENAPI_PATHS))
    def test_route_documents_422(self, app_client, inv: int) -> None:
        schema = app_client.app.openapi()  # type: ignore[attr-defined]
        path = self.OPENAPI_PATHS[inv]
        get_spec = schema["paths"][path]["get"]
        responses = get_spec["responses"]
        assert "422" in responses, f"inv#{inv} {path} missing 422"
        content = responses["422"]["content"]
        assert "application/problem+json" in content, (
            f"inv#{inv} {path} 422 missing problem+json: {content}"
        )
        ref = content["application/problem+json"]["schema"]["$ref"]
        assert ref == "#/components/schemas/ErrorResponse", (
            f"inv#{inv} {path} 422 ref={ref}"
        )
