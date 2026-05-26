"""CLI pagination 옵션 invalid range 거부 + valid range 회귀 보존 매트릭스 테스트.

이슈 #1512: 5개 CLI 조회 명령(`audit list`, `trade list`, `backtest history`,
`instrument search`, `config history`)이 음수/0 `--limit` 또는 음수 `--offset`을
exit 0으로 처리하던 ingress drift를 닫는다.

스펙 참조:
- 5개 명령은 모두 `docs/specs/cli/03-commands.md`의 `offline` 분류이며,
  `src/ante/ipc/registry.py:371-426` `register_all_handlers()`에 해당 IPC
  route가 없다 (등록된 22개 handler: system/account/bot/treasury/config.set/
  approval/broker만 — #1712 ``bot.start``/``bot.stop``/``bot.status`` 포함).
  따라서 IPC integration test는 N/A.
- 본 테스트는 CLI Click 데코레이터의 `IntRange` ingress 가드만 검증한다.
- 서비스 직접 호출(`AuditLogger.query`, `TradeRecorder.get_trades`,
  `BacktestRunStore.list_by_strategy`, `InstrumentService.search`,
  `DynamicConfigService.get_history`)이 invalid pagination을 SQL까지 전달하는
  잔여 갭은 본 이슈 Non-Goals이며 별도 follow-up 후보로 명시되어 있다.

Codex Plan Review v2 권고:
- CliRunner는 `mix_stderr=False`로 만들어 stderr 단정 fragility를 방지한다.
- 정확한 에러 메시지 텍스트 의존 대신 exit_code != 0 + `Invalid value` 또는
  range 키워드(`-1`, `0`, `offset`, `limit`)가 stderr/output에 포함되는지로
  강건하게 검증한다.
"""

from __future__ import annotations

import inspect
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from ante.cli.main import cli
from ante.member.models import Member, MemberRole, MemberType

_MOCK_MASTER = Member(
    member_id="test-master",
    type=MemberType.HUMAN,
    role=MemberRole.MASTER,
    org="default",
    name="Test Master",
    status="active",
    scopes=[],
)


def _make_runner() -> CliRunner:
    """`mix_stderr=False` runner. click 버전에 따라 fallback."""
    if "mix_stderr" in inspect.signature(CliRunner).parameters:
        return CliRunner(mix_stderr=False)
    return CliRunner()


@pytest.fixture()
def runner() -> CliRunner:
    """인증된 상태의 CliRunner. `authenticate_member`를 patch한다.

    `mix_stderr=False`로 stderr 분리 단정을 명시적으로 허용한다 (Codex v2 권고).
    """
    r = _make_runner()
    original_invoke = r.invoke

    def _invoke_with_auth(cli_cmd, args=None, **kwargs):  # noqa: ANN001, ANN202
        with patch("ante.cli.main.authenticate_member") as mock_auth:

            def _set_member(ctx):  # noqa: ANN001
                ctx.obj = ctx.obj or {}
                ctx.obj["member"] = _MOCK_MASTER

            mock_auth.side_effect = _set_member
            return original_invoke(cli_cmd, args, **kwargs)

    r.invoke = _invoke_with_auth
    return r


def _mock_db() -> MagicMock:
    db = MagicMock()
    db.connect = AsyncMock()
    db.close = AsyncMock()
    return db


def _assert_range_rejected(result, *, hint_keywords: tuple[str, ...]) -> None:
    """invalid range 거부에 대한 강건한 단정.

    click의 정확한 에러 메시지 텍스트를 의존하지 않고, exit != 0 + (stderr 또는
    output에 'Invalid value' 또는 hint 키워드 중 하나 포함)으로 검증한다.
    """
    assert result.exit_code != 0, (
        f"exit_code expected != 0, got {result.exit_code}; output={result.output!r}"
    )
    # stderr가 분리됐을 수 있으므로 안전하게 둘 다 본다.
    combined = (result.output or "") + (getattr(result, "stderr", "") or "")
    haystack = combined.lower()
    has_invalid_value = "invalid value" in haystack
    has_hint = any(k.lower() in haystack for k in hint_keywords)
    assert has_invalid_value or has_hint, (
        f"expected 'Invalid value' or one of {hint_keywords} in output/stderr; "
        f"got output={result.output!r}, stderr={getattr(result, 'stderr', '')!r}"
    )


# ── invalid range 거부 ────────────────────────────────────────────


class TestAuditListOffsetInvalid:
    """`audit list --offset -1` → IntRange(min=0) 거부."""

    def test_negative_offset_rejected(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["audit", "list", "--offset", "-1"])
        _assert_range_rejected(result, hint_keywords=("offset", "-1"))


class TestTradeListLimitInvalid:
    """`trade list --limit -1` / `--limit 0` → IntRange(min=1) 거부."""

    def test_negative_limit_rejected(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["trade", "list", "--limit", "-1"])
        _assert_range_rejected(result, hint_keywords=("limit", "-1"))

    def test_zero_limit_rejected(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["trade", "list", "--limit", "0"])
        _assert_range_rejected(result, hint_keywords=("limit", "0"))


class TestBacktestHistoryLimitInvalid:
    """`backtest history STRATEGY --limit -1` / `--limit 0` 거부."""

    def test_negative_limit_rejected(self, runner: CliRunner) -> None:
        result = runner.invoke(
            cli, ["backtest", "history", "some_strategy", "--limit", "-1"]
        )
        _assert_range_rejected(result, hint_keywords=("limit", "-1"))

    def test_zero_limit_rejected(self, runner: CliRunner) -> None:
        result = runner.invoke(
            cli, ["backtest", "history", "some_strategy", "--limit", "0"]
        )
        _assert_range_rejected(result, hint_keywords=("limit", "0"))


class TestInstrumentSearchLimitInvalid:
    """`instrument search KEYWORD --limit 0` 거부."""

    def test_zero_limit_rejected(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["instrument", "search", "samsung", "--limit", "0"])
        _assert_range_rejected(result, hint_keywords=("limit", "0"))

    def test_negative_limit_rejected(self, runner: CliRunner) -> None:
        result = runner.invoke(
            cli, ["instrument", "search", "samsung", "--limit", "-1"]
        )
        _assert_range_rejected(result, hint_keywords=("limit", "-1"))


class TestConfigHistoryLimitInvalid:
    """`config history KEY --limit 0` 거부."""

    def test_zero_limit_rejected(self, runner: CliRunner) -> None:
        result = runner.invoke(
            cli, ["config", "history", "risk.some_key", "--limit", "0"]
        )
        _assert_range_rejected(result, hint_keywords=("limit", "0"))

    def test_negative_limit_rejected(self, runner: CliRunner) -> None:
        result = runner.invoke(
            cli, ["config", "history", "risk.some_key", "--limit", "-1"]
        )
        _assert_range_rejected(result, hint_keywords=("limit", "-1"))


# ── valid range 회귀 보존 ─────────────────────────────────────────


class TestAuditListOffsetValid:
    """`audit list --offset 0` ingress 통과 (회귀 보존).

    `audit list`는 핸들러 내부에서 `Database`/`AuditLogger`를 lazy import하므로
    mock 정확도가 fragile하다. 본 invariant는 "IntRange(min=0)이 0을 거부하지
    않는다"이므로 click range error 부재만 강건하게 단정한다. backend mock 정확
    회귀는 별도 audit 전용 테스트가 담당한다.
    """

    def test_zero_offset_passes_ingress(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["audit", "list", "--offset", "0"])
        combined = (result.output or "") + (getattr(result, "stderr", "") or "")
        assert "Invalid value" not in combined, (
            f"valid --offset 0 should not trigger click range error; "
            f"got output={result.output!r}, stderr={getattr(result, 'stderr', '')!r}"
        )


class TestTradeListLimitValid:
    """`trade list --limit 50` 정상 통과 (회귀 보존, format_option 패턴 재사용)."""

    def test_default_limit_passes_ingress(self, runner: CliRunner) -> None:
        svc = MagicMock()
        svc.get_trades = AsyncMock(return_value=[])
        db = _mock_db()

        with patch(
            "ante.cli.commands.trade._create_trade_service",
            new_callable=AsyncMock,
            return_value=(svc, db),
        ):
            result = runner.invoke(cli, ["trade", "list", "--limit", "50"])

        assert result.exit_code == 0, (
            f"valid --limit 50 should pass; got exit={result.exit_code}, "
            f"output={result.output!r}, stderr={getattr(result, 'stderr', '')!r}"
        )


class TestBacktestHistoryLimitValid:
    """`backtest history STRATEGY --limit 20` ingress 통과."""

    def test_default_limit_passes_ingress(self, runner: CliRunner) -> None:
        # backtest history는 BacktestRunStore를 lazy import하므로 그쪽을 patch한다.
        with patch("ante.backtest.run_store.BacktestRunStore") as mock_store_cls:
            mock_store = MagicMock()
            mock_store.list_by_strategy = AsyncMock(return_value=[])
            mock_store_cls.return_value = mock_store

            result = runner.invoke(
                cli, ["backtest", "history", "some_strategy", "--limit", "20"]
            )

        # ingress 통과만 확인 — DB가 없어 backend에서 실패할 수 있어도
        # 'Invalid value' 같은 click range error는 없어야 한다.
        combined = (result.output or "") + (getattr(result, "stderr", "") or "")
        assert "Invalid value" not in combined, (
            f"valid --limit 20 should not trigger click range error; "
            f"got output={result.output!r}, stderr={getattr(result, 'stderr', '')!r}"
        )


class TestInstrumentSearchLimitValid:
    """`instrument search KEYWORD --limit 20` ingress 통과."""

    def test_default_limit_passes_ingress(self, runner: CliRunner) -> None:
        result = runner.invoke(
            cli, ["instrument", "search", "samsung", "--limit", "20"]
        )
        combined = (result.output or "") + (getattr(result, "stderr", "") or "")
        assert "Invalid value" not in combined, (
            f"valid --limit 20 should not trigger click range error; "
            f"got output={result.output!r}, stderr={getattr(result, 'stderr', '')!r}"
        )


class TestConfigHistoryLimitValid:
    """`config history KEY --limit 20` ingress 통과 (format_option 패턴 재사용)."""

    def test_default_limit_passes_ingress(self, runner: CliRunner) -> None:
        mock_config = MagicMock()
        mock_dynamic = AsyncMock()
        mock_dynamic.get_history = AsyncMock(return_value=[])
        mock_db = AsyncMock()
        mock_db.close = AsyncMock()

        with patch(
            "ante.cli.commands.config._create_services",
            new_callable=AsyncMock,
            return_value=(mock_config, mock_dynamic, mock_db),
        ):
            result = runner.invoke(
                cli, ["config", "history", "risk.some_key", "--limit", "20"]
            )

        assert result.exit_code == 0, (
            f"valid --limit 20 should pass; got exit={result.exit_code}, "
            f"output={result.output!r}, stderr={getattr(result, 'stderr', '')!r}"
        )
