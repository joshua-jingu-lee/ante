"""CLI strategy list --status invalid 입력 검증 회귀 테스트 (#1461).

`ante --format json strategy list --status <invalid>`가 Python traceback이 아닌
flat JSON error(`STRATEGY_VALIDATION_ERROR`)로 종료하는지, 그리고 registry 진입이
선제 차단되는지 검증한다.
"""

from __future__ import annotations

import inspect
import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import click
import pytest
from click.testing import CliRunner

from ante.cli.commands.strategy import VALID_STRATEGY_STATUSES
from ante.cli.main import cli
from ante.member.models import Member, MemberRole, MemberType
from ante.strategy.registry import StrategyRecord, StrategyStatus

_MOCK_MASTER = Member(
    member_id="test-master",
    type=MemberType.HUMAN,
    role=MemberRole.MASTER,
    org="default",
    name="Test Master",
    status="active",
    scopes=[],
)

_NOW = datetime(2026, 3, 19, 12, 0, 0, tzinfo=UTC)

_SAMPLE_RECORD = StrategyRecord(
    strategy_id="momentum_v1.0",
    name="momentum",
    version="1.0",
    filepath="/strategies/momentum.py",
    status=StrategyStatus.ADOPTED,
    registered_at=_NOW,
    description="모멘텀 전략",
    author_name="agent",
    author_id="agent",
    validation_warnings=[],
)


@pytest.fixture
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


def _mock_db():
    db = MagicMock()
    db.connect = AsyncMock()
    db.close = AsyncMock()
    return db


def _mock_registry(strategies=None):
    registry = MagicMock()
    registry.list_strategies = AsyncMock(return_value=strategies or [])
    registry.get_by_name = AsyncMock(return_value=strategies or [])
    return registry


class TestStrategyListInvalidStatus:
    """`strategy list --status <invalid>` 입력 검증 (#1461)."""

    def test_invalid_status_json_returns_flat_error(self, runner):
        """JSON 모드: invalid status → exit 1 + flat JSON error.

        stdout이 `{"status":"error","code":"STRATEGY_VALIDATION_ERROR","message":...}`
        형태여야 하며 Python traceback 흔적이 없어야 한다.
        """
        result = runner.invoke(
            cli,
            [
                "--format",
                "json",
                "strategy",
                "list",
                "--status",
                "oracle_invalid_status",
            ],
        )
        assert result.exit_code == 1
        # stdout이 단일 JSON object여야 함.
        data = json.loads(result.output.strip())
        assert data["status"] == "error"
        assert data["code"] == "STRATEGY_VALIDATION_ERROR"
        assert "oracle_invalid_status" in data["message"]
        # traceback 흔적 차단
        assert "Traceback" not in result.output
        if result.stderr_bytes is not None:
            assert "Traceback" not in result.stderr

    def test_invalid_status_does_not_invoke_registry(self, runner):
        """invalid status는 `_create_registry`를 호출하지 않는다 (preflight).

        registry 진입 자체가 차단되어야 하므로 mock의 await 카운트는 0이어야 한다.
        """
        with patch(
            "ante.cli.commands.strategy._create_registry",
            new_callable=AsyncMock,
        ) as mock_create:
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "strategy",
                    "list",
                    "--status",
                    "oracle_invalid_status",
                ],
            )
            assert result.exit_code == 1
            mock_create.assert_not_called()

    def test_invalid_status_text_mode(self):
        """text 모드: invalid status → exit 1 + stderr `Error: ...`, stdout 비어있음.

        CliRunner의 stdout/stderr 분리는 생성자 인자(`mix_stderr=False`)로 지정해야
        하므로 본 케이스만 fixture와 별개로 runner를 만든다.
        """
        if "mix_stderr" in inspect.signature(CliRunner).parameters:
            r = CliRunner(mix_stderr=False)
        else:
            r = CliRunner()

        with (
            patch("ante.cli.main.authenticate_member") as mock_auth,
            patch(
                "ante.cli.commands.strategy._create_registry",
                new_callable=AsyncMock,
            ) as mock_create,
        ):

            def _set_member(ctx):
                ctx.obj = ctx.obj or {}
                ctx.obj["member"] = _MOCK_MASTER

            mock_auth.side_effect = _set_member
            result = r.invoke(
                cli,
                ["strategy", "list", "--status", "oracle_invalid_status"],
            )

        assert result.exit_code == 1
        mock_create.assert_not_called()
        assert result.stdout == ""
        assert "Error:" in result.stderr
        assert "Traceback" not in result.stderr

    def test_no_status_passes_preflight(self, runner):
        """status 미지정 → preflight 통과 → exit 0."""
        db = _mock_db()
        registry = _mock_registry([])

        with patch(
            "ante.cli.commands.strategy._create_registry",
            new_callable=AsyncMock,
            return_value=(registry, db),
        ):
            result = runner.invoke(cli, ["--format", "json", "strategy", "list"])
            assert result.exit_code == 0

    @pytest.mark.parametrize("valid_status", ["registered", "adopted", "archived"])
    def test_valid_statuses_pass_preflight(self, runner, valid_status):
        """SSOT enum의 모든 valid value는 preflight를 통과한다."""
        db = _mock_db()
        registry = _mock_registry([_SAMPLE_RECORD])

        with patch(
            "ante.cli.commands.strategy._create_registry",
            new_callable=AsyncMock,
            return_value=(registry, db),
        ):
            result = runner.invoke(
                cli,
                ["--format", "json", "strategy", "list", "--status", valid_status],
            )
            assert result.exit_code == 0
            registry.list_strategies.assert_called_once_with(
                status=StrategyStatus(valid_status),
            )

    def test_registry_hydration_error_maps_to_strategy_error(self, runner):
        """registry 단계의 일반 Exception은 `STRATEGY_ERROR`로 분류된다.

        invalid status preflight는 통과하지만(`_list()` 내부 실행 후) registry
        진입에서 실패하는 시나리오를 시뮬레이션한다.
        """
        db = _mock_db()
        registry = MagicMock()
        registry.list_strategies = AsyncMock(side_effect=RuntimeError("hydration boom"))

        with patch(
            "ante.cli.commands.strategy._create_registry",
            new_callable=AsyncMock,
            return_value=(registry, db),
        ):
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "strategy",
                    "list",
                    "--status",
                    "adopted",
                ],
            )
            assert result.exit_code == 1
            data = json.loads(result.output.strip())
            assert data["status"] == "error"
            assert data["code"] == "STRATEGY_ERROR"
            assert "hydration boom" in data["message"]
            assert "Traceback" not in result.output

    def test_click_exception_propagates_without_formatter(self, runner):
        """`_list()` 내부에서 `click.ClickException`이 발생하면 그대로 전파된다.

        formatter를 거치면 click의 표준 출력 경로(`UsageError`/`ClickException.show`)
        가 깨지므로, `except click.ClickException: raise` 분기로 보존되어야 한다.
        """
        db = _mock_db()
        registry = MagicMock()
        registry.list_strategies = AsyncMock(
            side_effect=click.UsageError("intentional click usage error")
        )

        with patch(
            "ante.cli.commands.strategy._create_registry",
            new_callable=AsyncMock,
            return_value=(registry, db),
        ):
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "strategy",
                    "list",
                    "--status",
                    "adopted",
                ],
            )
            # click.UsageError → exit_code 2, formatter JSON 미경유.
            assert result.exit_code == 2
            assert "intentional click usage error" in result.output
            # JSON shape이 아니어야 한다(formatter를 거치지 않았다는 회귀).
            assert '"code": "STRATEGY_ERROR"' not in result.output

    def test_preflight_set_matches_enum_ssot(self):
        """CLI preflight copy가 `StrategyStatus` SSOT와 동치인지 회귀.

        #1463(heavy import 분리)으로 preflight copy가 제거되기 전까지 drift를 차단한다.
        """
        assert VALID_STRATEGY_STATUSES == {s.value for s in StrategyStatus}
