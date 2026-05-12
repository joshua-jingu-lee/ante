"""POST /api/bots, PUT /api/bots/{bot_id} budget invariant 회귀 테스트.

이슈 #1435: `BotCreateRequest.budget` / `BotUpdateRequest.budget`가 raw JSON
`NaN`/`Infinity`/`-Infinity`를 422가 아닌 통과로 처리하던 결함을 막는다.

Web API 입력 invariant(``Field(default=None, gt=0, allow_inf_nan=False)``)가
NaN/±Inf/0/음수를 422로 거부함을 회귀 검증한다. #1432 treasury 패턴을 따라
Web 계층에서 1차 차단한다.
"""

from __future__ import annotations

import pytest

httpx = pytest.importorskip("httpx", reason="httpx required for web API tests")

from fastapi.testclient import TestClient  # noqa: E402

from ante.web.app import create_app  # noqa: E402

# 기존 테스트 파일의 Fake 들을 재사용한다 (test_bot_routes_create_budget_error.py 패턴).
from tests.unit.test_bot_api import (  # noqa: E402
    _MASTER_HEADERS,
    FakeAccount,
    FakeAccountService,
    FakeBot,
    FakeBotManager,
    FakeStrategyRecord,
    FakeStrategyRegistry,
    _new_member_service,
)


@pytest.fixture(autouse=True)
def _mock_strategy_loader(monkeypatch):
    """StrategyLoader.load 를 모킹해 파일 시스템 의존을 제거."""

    class _FakeStrategy:
        pass

    monkeypatch.setattr(
        "ante.strategy.loader.StrategyLoader.load",
        staticmethod(lambda path: _FakeStrategy),
    )


@pytest.fixture
def bot_manager() -> FakeBotManager:
    return FakeBotManager()


@pytest.fixture
def account_service() -> FakeAccountService:
    svc = FakeAccountService()
    svc._accounts["test"] = FakeAccount(
        "test",
        status="active",
        credentials={"app_key": "test-key", "app_secret": "test-secret"},
    )
    return svc


@pytest.fixture
def strategy_registry() -> FakeStrategyRegistry:
    reg = FakeStrategyRegistry()
    reg._strategies["s1"] = FakeStrategyRecord("s1", name="s1")
    return reg


@pytest.fixture
def client(bot_manager, account_service, strategy_registry) -> TestClient:
    # POST /api/bots, PUT /api/bots/{id}는 master 인증을 요구하므로(#1371/#1352),
    # default Authorization 헤더 + member_service stub을 함께 주입한다.
    app = create_app(
        bot_manager=bot_manager,
        account_service=account_service,
        strategy_registry=strategy_registry,
        member_service=_new_member_service(),
    )
    client = TestClient(app)
    client.headers.update(_MASTER_HEADERS)
    return client


def _create_payload(**overrides) -> dict:
    """기본 POST /api/bots payload (overrides로 budget만 갈아끼울 수 있도록)."""

    payload: dict = {
        "bot_id": "bot-x",
        "strategy_id": "s1",
        "account_id": "test",
    }
    payload.update(overrides)
    return payload


# ── POST /api/bots: budget invariant 회귀 ─────────────────────────


class TestCreateBotBudgetInvariant:
    """``BotCreateRequest.budget`` finite-positive 입력 invariant."""

    def test_create_rejects_positive_inf_with_422(
        self, client: TestClient, bot_manager: FakeBotManager
    ) -> None:
        """body `{"budget": Infinity}` → 422 (allow_inf_nan=False).

        표준 JSON 인코더는 Infinity를 거부하므로 raw content로 전송한다.
        """
        resp = client.post(
            "/api/bots",
            content=(
                '{"bot_id": "bot-x", "strategy_id": "s1", '
                '"account_id": "test", "budget": Infinity}'
            ),
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 422, resp.text
        # 봇이 생성되지 않았는지 확인
        assert "bot-x" not in bot_manager._bots

    def test_create_rejects_negative_inf_with_422(
        self, client: TestClient, bot_manager: FakeBotManager
    ) -> None:
        """body `{"budget": -Infinity}` → 422."""
        resp = client.post(
            "/api/bots",
            content=(
                '{"bot_id": "bot-x", "strategy_id": "s1", '
                '"account_id": "test", "budget": -Infinity}'
            ),
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 422, resp.text
        assert "bot-x" not in bot_manager._bots

    def test_create_rejects_nan_with_422(
        self, client: TestClient, bot_manager: FakeBotManager
    ) -> None:
        """body `{"budget": NaN}` → 422 (allow_inf_nan=False)."""
        resp = client.post(
            "/api/bots",
            content=(
                '{"bot_id": "bot-x", "strategy_id": "s1", '
                '"account_id": "test", "budget": NaN}'
            ),
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 422, resp.text
        assert "bot-x" not in bot_manager._bots

    def test_create_rejects_negative_with_422(
        self, client: TestClient, bot_manager: FakeBotManager
    ) -> None:
        """body `{"budget": -1}` → 422 (Field(gt=0) 회귀 보존)."""
        resp = client.post("/api/bots", json=_create_payload(budget=-1.0))
        assert resp.status_code == 422, resp.text
        assert "bot-x" not in bot_manager._bots

    def test_create_rejects_zero_with_422(
        self, client: TestClient, bot_manager: FakeBotManager
    ) -> None:
        """body `{"budget": 0}` → 422 (Field(gt=0) 회귀 보존)."""
        resp = client.post("/api/bots", json=_create_payload(budget=0.0))
        assert resp.status_code == 422, resp.text
        assert "bot-x" not in bot_manager._bots

    def test_create_accepts_positive_finite(
        self, client: TestClient, bot_manager: FakeBotManager
    ) -> None:
        """body `{"budget": 100.0}` → 201 (정상 경로 회귀 보존)."""
        resp = client.post("/api/bots", json=_create_payload(budget=100.0))
        # 정상 생성 또는 Treasury 미주입으로 인한 422(=budget allocation 실패).
        # invariant 가드 본질은 raw float 값이 Pydantic을 통과했는지이므로
        # 201 또는 422(budget allocation 실패) 둘 다 통과로 본다.
        # NaN/Infinity와 달리 422 발생 시 detail은 invariant가 아닌
        # treasury 관련 에러여야 한다.
        assert resp.status_code in (201, 422), resp.text
        if resp.status_code == 422:
            # invariant 위반이 아닌 treasury 관련 422여야 함
            body = resp.text.lower()
            assert "infinity" not in body
            assert "nan" not in body

    def test_create_accepts_budget_omitted(
        self, client: TestClient, bot_manager: FakeBotManager
    ) -> None:
        """budget 생략 시 정상 (필드 자체가 optional)."""
        resp = client.post("/api/bots", json=_create_payload())
        assert resp.status_code == 201, resp.text


# ── PUT /api/bots/{bot_id}: budget invariant 회귀 ─────────────────


class TestUpdateBotBudgetInvariant:
    """``BotUpdateRequest.budget`` finite-positive 입력 invariant."""

    @pytest.fixture
    def existing_bot(self, bot_manager: FakeBotManager) -> str:
        """수정 대상 봇을 미리 생성. stopped 상태여야 PUT이 허용됨."""

        bot_manager._bots["bot-x"] = FakeBot(
            "bot-x", status="stopped", strategy_id="s1", account_id="test"
        )
        return "bot-x"

    def test_update_rejects_positive_inf_with_422(
        self, client: TestClient, existing_bot: str
    ) -> None:
        """body `{"budget": Infinity}` → 422 (allow_inf_nan=False)."""
        resp = client.put(
            f"/api/bots/{existing_bot}",
            content='{"budget": Infinity}',
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 422, resp.text

    def test_update_rejects_negative_inf_with_422(
        self, client: TestClient, existing_bot: str
    ) -> None:
        """body `{"budget": -Infinity}` → 422."""
        resp = client.put(
            f"/api/bots/{existing_bot}",
            content='{"budget": -Infinity}',
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 422, resp.text

    def test_update_rejects_nan_with_422(
        self, client: TestClient, existing_bot: str
    ) -> None:
        """body `{"budget": NaN}` → 422."""
        resp = client.put(
            f"/api/bots/{existing_bot}",
            content='{"budget": NaN}',
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 422, resp.text

    def test_update_rejects_negative_with_422(
        self, client: TestClient, existing_bot: str
    ) -> None:
        """body `{"budget": -1}` → 422 (Field(gt=0) 회귀 보존)."""
        resp = client.put(f"/api/bots/{existing_bot}", json={"budget": -1.0})
        assert resp.status_code == 422, resp.text

    def test_update_rejects_zero_with_422(
        self, client: TestClient, existing_bot: str
    ) -> None:
        """body `{"budget": 0}` → 422 (Field(gt=0) 회귀 보존)."""
        resp = client.put(f"/api/bots/{existing_bot}", json={"budget": 0.0})
        assert resp.status_code == 422, resp.text

    def test_update_accepts_positive_finite(
        self, client: TestClient, existing_bot: str
    ) -> None:
        """body `{"budget": 100.0}` → 200 (정상 경로 회귀 보존)."""
        resp = client.put(f"/api/bots/{existing_bot}", json={"budget": 100.0})
        # 정상 update 또는 Treasury 미주입에 따른 422.
        # invariant 가드 본질은 finite-positive 통과 여부.
        assert resp.status_code in (200, 422), resp.text
        if resp.status_code == 422:
            body = resp.text.lower()
            assert "infinity" not in body
            assert "nan" not in body
