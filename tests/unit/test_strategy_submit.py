"""전략 submit 시 rationale/risks 전달 검증 테스트."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from ante.cli.main import cli
from ante.member.models import Member, MemberRole, MemberType
from ante.strategy.base import Signal, Strategy, StrategyMeta

_MOCK_MASTER = Member(
    member_id="test-master",
    type=MemberType.HUMAN,
    role=MemberRole.MASTER,
    org="default",
    name="Test Master",
    status="active",
    scopes=[],
)


# ── 테스트용 전략 클래스 ─────────────────────────────


class MinimalStrategy(Strategy):
    """get_rationale/get_risks 오버라이드 없는 최소 전략."""

    meta = StrategyMeta(
        name="minimal",
        version="0.1.0",
        description="test",
    )

    async def on_step(self, context: dict[str, Any]) -> list[Signal]:
        return []


class RichStrategy(Strategy):
    """rationale/risks를 오버라이드한 전략."""

    meta = StrategyMeta(
        name="rich",
        version="0.1.0",
        description="test with rationale",
    )

    async def on_step(self, context: dict[str, Any]) -> list[Signal]:
        return []

    def get_rationale(self) -> str:
        return "test rationale"

    def get_risks(self) -> list[str]:
        return ["risk A", "risk B"]

    def get_params(self) -> dict[str, Any]:
        return {"period": 14}

    def get_param_schema(self) -> dict[str, str]:
        return {"period": "lookback period"}


# ── Fixtures ─────────────────────────────────────────


@pytest.fixture()
def runner():
    r = CliRunner()
    original_invoke = r.invoke

    def _invoke_with_auth(cli_cmd, args=None, **kwargs):
        with patch("ante.cli.main.authenticate_member") as mock_auth:

            def _set_member(ctx):
                ctx.obj = ctx.obj or {}
                ctx.obj["member"] = _MOCK_MASTER

            mock_auth.side_effect = _set_member
            return original_invoke(cli_cmd, args, **kwargs)

    r.invoke = _invoke_with_auth
    return r


def _mock_registry() -> MagicMock:
    registry = MagicMock()
    registry.initialize = AsyncMock()
    record = MagicMock()
    record.strategy_id = "rich_v0.1.0"
    record.name = "rich"
    record.version = "0.1.0"
    record.description = "test with rationale"
    record.author_name = "agent"
    record.author_id = "agent"
    record.filepath = "/tmp/rich.py"
    record.registered_at = MagicMock()
    record.registered_at.isoformat.return_value = "2026-01-01T00:00:00"
    record.validation_warnings = []
    registry.register = AsyncMock(return_value=record)
    return registry


def _mock_db() -> MagicMock:
    db = MagicMock()
    db.connect = AsyncMock()
    db.close = AsyncMock()
    return db


# ── Strategy ABC 기본 메서드 테스트 ──────────────────


class TestStrategyABCDefaults:
    """Strategy ABC의 기본 get_rationale/get_risks 반환값 검증."""

    def test_default_get_rationale(self) -> None:
        instance = MinimalStrategy(ctx=None)
        assert instance.get_rationale() == ""

    def test_default_get_risks(self) -> None:
        instance = MinimalStrategy(ctx=None)
        assert instance.get_risks() == []

    def test_default_get_params(self) -> None:
        instance = MinimalStrategy(ctx=None)
        assert instance.get_params() == {}

    def test_default_get_param_schema(self) -> None:
        instance = MinimalStrategy(ctx=None)
        assert instance.get_param_schema() == {}


class TestStrategyOverrides:
    """오버라이드된 get_rationale/get_risks 반환값 검증."""

    def test_overridden_get_rationale(self) -> None:
        instance = RichStrategy(ctx=None)
        assert instance.get_rationale() == "test rationale"

    def test_overridden_get_risks(self) -> None:
        instance = RichStrategy(ctx=None)
        assert instance.get_risks() == ["risk A", "risk B"]

    def test_overridden_get_params(self) -> None:
        instance = RichStrategy(ctx=None)
        assert instance.get_params() == {"period": 14}

    def test_overridden_get_param_schema(self) -> None:
        instance = RichStrategy(ctx=None)
        assert instance.get_param_schema() == {"period": "lookback period"}


# ── Submit CLI: rationale/risks 추출 → register 전달 검증 ──


class TestSubmitRationaleRisks:
    """submit 커맨드에서 rationale/risks가 register에 전달되는지 검증."""

    def test_submit_extracts_rationale_risks(self, runner) -> None:
        """submit 시 전략 인스턴스에서 rationale/risks를 추출."""
        db = _mock_db()
        registry = _mock_registry()

        validation_result = MagicMock()
        validation_result.valid = True
        validation_result.errors = []
        validation_result.warnings = []

        with (
            patch("ante.strategy.validator.StrategyValidator") as mock_validator_cls,
            patch("ante.strategy.loader.StrategyLoader") as mock_loader,
            patch(
                "ante.cli.commands.strategy._create_registry",
                new_callable=AsyncMock,
                return_value=(registry, db),
            ),
        ):
            mock_validator_cls.return_value.validate.return_value = validation_result
            mock_loader.load.return_value = RichStrategy

            result = runner.invoke(
                cli,
                ["strategy", "submit", __file__],
            )

            assert result.exit_code == 0
            registry.register.assert_called_once()
            call_kwargs = registry.register.call_args
            assert call_kwargs.kwargs.get("rationale") == "test rationale"
            assert call_kwargs.kwargs.get("risks") == ["risk A", "risk B"]

    def test_submit_with_no_rationale_risks(self, runner) -> None:
        """rationale/risks가 없는 전략은 빈 값으로 전달."""
        db = _mock_db()
        registry = _mock_registry()

        validation_result = MagicMock()
        validation_result.valid = True
        validation_result.errors = []
        validation_result.warnings = []

        with (
            patch("ante.strategy.validator.StrategyValidator") as mock_validator_cls,
            patch("ante.strategy.loader.StrategyLoader") as mock_loader,
            patch(
                "ante.cli.commands.strategy._create_registry",
                new_callable=AsyncMock,
                return_value=(registry, db),
            ),
        ):
            mock_validator_cls.return_value.validate.return_value = validation_result
            mock_loader.load.return_value = MinimalStrategy

            result = runner.invoke(
                cli,
                ["strategy", "submit", __file__],
            )

            assert result.exit_code == 0
            registry.register.assert_called_once()
            call_kwargs = registry.register.call_args
            assert call_kwargs.kwargs.get("rationale") == ""
            assert call_kwargs.kwargs.get("risks") == []
