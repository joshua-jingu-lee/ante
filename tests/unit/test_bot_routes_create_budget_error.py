"""POST /api/bots — budget 배정 실패 시 422 + 롤백 검증.

Refs #1335: 과거에는 ``except Exception: pass`` 로 budget 배정 실패를
silent 하게 삼켜 client 가 201 Created 를 받았다. 이제 ``TreasuryError``
는 422 로 매핑되고 신규 봇은 best-effort 롤백된다.
"""

from __future__ import annotations

import pytest

httpx = pytest.importorskip("httpx", reason="httpx required for web API tests")

from fastapi.testclient import TestClient  # noqa: E402

from ante.web.app import create_app  # noqa: E402

# 기존 테스트 파일의 Fake 들을 재사용한다.
from tests.unit.test_bot_api import (  # noqa: E402
    FakeAccount,
    FakeAccountService,
    FakeBotManager,
    FakeStrategyRecord,
    FakeStrategyRegistry,
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
    app = create_app(
        bot_manager=bot_manager,
        account_service=account_service,
        strategy_registry=strategy_registry,
    )
    return TestClient(app)


def _install_treasury_error_on_update(
    bot_manager: FakeBotManager, exc: Exception
) -> None:
    """update_bot 호출 시 budget 인자가 있으면 ``exc`` 를 raise 하도록 패치.

    실제 ``BotManager.update_bot`` 의 budget 분기 동작을 흉내 낸다.
    """
    original_update_bot = bot_manager.update_bot

    async def _patched(bot_id, **kwargs):
        if "budget" in kwargs and kwargs["budget"] is not None:
            raise exc
        return await original_update_bot(bot_id, **kwargs)

    bot_manager.update_bot = _patched  # type: ignore[assignment]


class TestCreateBotBudgetError:
    """POST /api/bots 의 budget 배정 실패 매핑."""

    def test_create_bot_with_oversized_budget_returns_422(
        self, client, bot_manager
    ) -> None:
        """``InsufficientFundsError`` (TreasuryError 하위) → 422."""
        from ante.treasury.exceptions import InsufficientFundsError

        _install_treasury_error_on_update(
            bot_manager,
            InsufficientFundsError(
                "미할당 잔액 부족: 필요 1,000,000,000,000, 가용 1,000,000"
            ),
        )

        resp = client.post(
            "/api/bots",
            json={
                "bot_id": "bot-overbudget",
                "strategy_id": "s1",
                "account_id": "test",
                "budget": 1_000_000_000_000.0,
            },
        )

        assert resp.status_code == 422
        assert "잔액 부족" in resp.json()["detail"]

    def test_create_bot_treasury_not_configured_returns_422(
        self, client, bot_manager
    ) -> None:
        """``TreasuryNotConfiguredError`` → 422 (TreasuryError 하위)."""
        from ante.treasury.exceptions import TreasuryNotConfiguredError

        _install_treasury_error_on_update(
            bot_manager,
            TreasuryNotConfiguredError("treasury manager not configured"),
        )

        resp = client.post(
            "/api/bots",
            json={
                "bot_id": "bot-noconfig",
                "strategy_id": "s1",
                "account_id": "test",
                "budget": 100_000.0,
            },
        )

        assert resp.status_code == 422
        assert "treasury" in resp.json()["detail"].lower()

    def test_create_bot_budget_failure_rolls_back_bot(
        self, client, bot_manager
    ) -> None:
        """422 후 GET /api/bots/{id} → 404 (롤백 확인)."""
        from ante.treasury.exceptions import InsufficientFundsError

        _install_treasury_error_on_update(
            bot_manager, InsufficientFundsError("insufficient")
        )

        bot_id = "bot-rollback"
        create_resp = client.post(
            "/api/bots",
            json={
                "bot_id": bot_id,
                "strategy_id": "s1",
                "account_id": "test",
                "budget": 5_000_000.0,
            },
        )
        assert create_resp.status_code == 422

        get_resp = client.get(f"/api/bots/{bot_id}")
        assert get_resp.status_code == 404
        assert bot_manager.get_bot(bot_id) is None

    def test_create_bot_with_valid_budget_succeeds(self, client, bot_manager) -> None:
        """budget 배정 성공 → 201."""
        # budget 인자가 와도 FakeBotManager.update_bot 은 budget 키를
        # filter out 하므로 별도 패치 없이 정상 동작한다.
        resp = client.post(
            "/api/bots",
            json={
                "bot_id": "bot-ok",
                "strategy_id": "s1",
                "account_id": "test",
                "budget": 5_000_000.0,
            },
        )
        assert resp.status_code == 201
        assert resp.json()["bot"]["bot_id"] == "bot-ok"
        # 봇이 존재해야 한다.
        assert bot_manager.get_bot("bot-ok") is not None

    def test_create_bot_budget_failure_with_rollback_failure_returns_500(
        self, client, bot_manager
    ) -> None:
        """budget 배정 실패 + 롤백 실패 → 500 + partial state detail."""
        from ante.bot.exceptions import BotError
        from ante.treasury.exceptions import InsufficientFundsError

        _install_treasury_error_on_update(
            bot_manager, InsufficientFundsError("insufficient")
        )

        # delete_bot 도 실패하도록 패치.
        async def _failing_delete(bot_id, handle_positions="keep"):
            raise BotError(f"delete failed for {bot_id}")

        bot_manager.delete_bot = _failing_delete  # type: ignore[assignment]

        resp = client.post(
            "/api/bots",
            json={
                "bot_id": "bot-doublefail",
                "strategy_id": "s1",
                "account_id": "test",
                "budget": 5_000_000.0,
            },
        )

        assert resp.status_code == 500
        detail = resp.json()["detail"]
        assert "budget allocation failed" in detail
        assert "rollback also failed" in detail
        assert "bot-doublefail" in detail
        assert "partial state" in detail

    def test_create_bot_other_exception_during_budget_update_propagates(
        self, client, bot_manager
    ) -> None:
        """비-TreasuryError 는 422 로 매핑하지 않고 propagate (FastAPI 가 500)."""
        # RuntimeError 는 TreasuryError 하위가 아니므로 catch 되지 않아야
        # 한다. TestClient 는 raise_server_exceptions=True 가 기본이므로
        # 예외가 그대로 전파된다.
        _install_treasury_error_on_update(
            bot_manager, RuntimeError("unexpected internal error")
        )

        with pytest.raises(RuntimeError, match="unexpected internal error"):
            client.post(
                "/api/bots",
                json={
                    "bot_id": "bot-otherexc",
                    "strategy_id": "s1",
                    "account_id": "test",
                    "budget": 5_000_000.0,
                },
            )
