"""Report CLI success output ↔ registry OutputContract drift lock (#1847 sub-PR 6).

본 모듈은 :data:`ante.contracts.cli_registry.CLI_COMMAND_REGISTRY` 에 등록된
report 도메인 5 leaf 의 ``OutputContract`` 와 ``ante report ... --format json``
실제 출력 envelope shape 사이의 drift 를 lock 한다.

#1846 (account) / #1847 sub-PR 1 (member) / sub-PR 2 (bot) / sub-PR 3
(approval) / sub-PR 4 (treasury) / sub-PR 5 (strategy) / sub-PR 6 (data)
1:1 동형 패턴. drift 모델:

- ``envelope="standard"`` entry → CLI success envelope ``{status, message,
  data}`` (envelopes.md SSOT). ``fmt.success(...)`` callsite 가 dump 한다.
- ``envelope="raw_legacy"`` entry → JSON mode 에서 ``fmt.output(...)`` 또는
  ``fmt.table(...)`` 으로 평면 dict 또는 row list 를 그대로 dump 한다
  (standard envelope 의 3 키 셋이 동시에 부재 또는 ``status != "ok"``).

본 PR 은 ``report.py`` 본문을 *바꾸지 않으며*, registry entry 가 실제 callsite
shape 와 일치함을 단순 lock 만 한다. callsite shape 가 drift 하면 본 test 가
즉시 FAIL 한다.

9 시나리오 (5 leaf + registry sanity +1 + list empty 분기 +1 + performance
empty 분기 +1 + performance non-empty +1):

0. registry sanity — report 5 entries 의 envelope 이 ``standard`` /
   ``raw_legacy`` 분류 범위 내.
1. ``schema`` → ``raw_legacy`` (``fmt.output(get_schema())``)
2. ``submit`` (success) → ``standard`` (``fmt.success(message, result)``)
3. ``list`` empty → ``raw_legacy`` (``fmt.table([], columns)`` → ``[]``)
4. ``list`` non-empty → ``raw_legacy`` (``fmt.table(rows, columns)`` → row list)
5. ``performance`` empty → ``raw_legacy`` (``{message, summaries: []}``)
6. ``performance`` non-empty (daily) → ``raw_legacy`` (``{period, summaries}``)
7. ``view`` (found) → ``raw_legacy`` (``fmt.output(result)``)
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner

from ante.contracts.cli_registry import CLI_COMMAND_REGISTRY
from ante.member.models import Member, MemberRole, MemberStatus, MemberType
from ante.report.models import ReportStatus, StrategyReport

# ── envelope shape predicates (envelopes.md SSOT, 동형 정책) ───────────────

_STANDARD_KEYS = frozenset({"status", "message", "data"})


def _is_standard_envelope(payload: Any) -> bool:
    """``{status: "ok", message, data}`` 3 필수 키가 모두 존재하는지."""
    return (
        isinstance(payload, dict)
        and payload.get("status") == "ok"
        and set(payload.keys()) >= _STANDARD_KEYS
        and isinstance(payload.get("message"), str)
        and isinstance(payload.get("data"), (dict, type(None)))
    )


def _is_raw_legacy_payload(payload: Any) -> bool:
    """평면 dict / list 로 standard envelope 의 3 필수 키 셋이 부재함을 단언."""
    if isinstance(payload, list):
        return True
    if not isinstance(payload, dict):
        return False
    if (
        set(payload.keys()) >= _STANDARD_KEYS
        and payload.get("status") == "ok"
        and isinstance(payload.get("data"), dict)
    ):
        return False
    return True


# ── registry entry 정합 sanity (envelope vocab) ───────────────────────────


def test_registry_report_entries_envelopes_classified() -> None:
    """report 5 entry 의 envelope 이 ``standard`` 또는 ``raw_legacy`` 만 사용.

    본 단언은 본 모듈 fixture 의 envelope predicate 두 함수가 5 entry 를
    모두 분류할 수 있음을 lock 한다. envelope SSOT (#1821) 에 새 값이
    추가되면 본 분류기를 갱신해야 함을 표면화한다.
    """
    accepted = {"standard", "raw_legacy"}
    report_entries = [
        (path, contract)
        for path, contract in CLI_COMMAND_REGISTRY.items()
        if path[:1] == ("report",)
    ]
    assert len(report_entries) == 5, (
        f"report 5 entries 가 모두 등록되어야 한다. 실제: {len(report_entries)}"
    )
    for path, contract in report_entries:
        assert contract.output.envelope in accepted, (
            f"{path}: registry envelope='{contract.output.envelope}' 가 본 "
            f"drift test 의 분류 범위 ({sorted(accepted)}) 를 벗어남. "
            "envelope SSOT (#1821) 가 새 값을 추가했다면 본 분류기를 갱신하라."
        )


# ── CLI fixture (account/member/bot/approval/treasury/strategy/data 동형) ──


_MOCK_MASTER = Member(
    member_id="test-master",
    type=MemberType.HUMAN,
    role=MemberRole.MASTER,
    org="default",
    name="Test Master",
    status=MemberStatus.ACTIVE,
    scopes=[],
)


@pytest.fixture(autouse=True)
def bypass_auth():
    """master member 로 인증 우회 (동형 패턴)."""
    with patch(
        "ante.cli.main.authenticate_member",
        side_effect=lambda ctx: ctx.obj.update({"member": _MOCK_MASTER}),
    ):
        yield


def _invoke(args: list[str]):
    """``ante --format json report ...`` 를 실행하고 결과를 반환한다."""
    from ante.cli.main import cli

    runner = CliRunner()
    env = {"ANTE_MEMBER_TOKEN": ""}
    return runner.invoke(cli, args, env=env, catch_exceptions=False)


def _load_json_payload(output: str) -> Any:
    """CLI ``--format json`` 출력의 첫 JSON value 를 파싱한다."""
    text = output.lstrip()
    assert text, f"CLI 출력이 비어 있다: {output!r}"
    start_brace = text.find("{")
    start_bracket = text.find("[")
    candidates = [s for s in (start_brace, start_bracket) if s >= 0]
    assert candidates, f"JSON 시작 토큰을 찾을 수 없다: {output!r}"
    start = min(candidates)
    decoder = json.JSONDecoder()
    obj, _end = decoder.raw_decode(text[start:])
    return obj


# ── helpers: StrategyReport factory ────────────────────────────────────────


def _make_report(
    *,
    report_id: str = "rpt-1",
    strategy_name: str = "my_strategy",
    status: ReportStatus = ReportStatus.SUBMITTED,
) -> StrategyReport:
    """테스트용 ``StrategyReport`` factory."""
    return StrategyReport(
        report_id=report_id,
        strategy_name=strategy_name,
        strategy_version="1.0.0",
        strategy_path="strategies/my_strategy.py",
        status=status,
        submitted_at=datetime(2026, 1, 1, tzinfo=UTC),
        submitted_by="agent",
        backtest_period="2024-01 ~ 2026-03",
        total_return_pct=15.3,
        total_trades=42,
        sharpe_ratio=1.2,
        max_drawdown_pct=-8.5,
        win_rate=58.0,
        summary="테스트 전략",
        rationale="모멘텀",
        risks="없음",
    )


# ── 1. schema → raw_legacy ─────────────────────────────────────────────────


def test_report_schema_envelope_matches_raw_legacy() -> None:
    """``report schema``: ``fmt.output(store.get_schema())`` 평면 dict.

    report.py:44: ``fmt.output(store.get_schema())``. ``ReportStore.get_schema``
    는 ``{required_fields, optional_fields, format, example}`` 평면 dict 를
    반환한다 (store.py:248-284).
    """
    result = _invoke(["--format", "json", "report", "schema"])
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_raw_legacy_payload(payload), (
        f"report schema: standard envelope 아님. payload={payload!r}"
    )
    assert "required_fields" in payload
    assert "optional_fields" in payload
    assert "format" in payload
    assert isinstance(payload["required_fields"], list)


# ── 2. submit (success) → standard ─────────────────────────────────────────


def test_report_submit_success_envelope_matches_operation_standard(tmp_path) -> None:
    """``report submit`` 성공: ``fmt.success(message, result)`` → standard.

    report.py:182: ``fmt.success(f"Report submitted: {result['report_id']}",
    result)``. 단일 success 경로 — JSON / text 모두 standard envelope.
    """
    payload_data = {
        "strategy_name": "my_strategy",
        "strategy_version": "1.0.0",
        "strategy_path": "strategies/my_strategy.py",
        "backtest_period": "2024-01 ~ 2026-03",
        "total_return_pct": 15.3,
        "total_trades": 42,
        "sharpe_ratio": 1.2,
        "max_drawdown_pct": -8.5,
        "win_rate": 58.0,
        "summary": "테스트 전략",
        "rationale": "모멘텀",
    }
    json_path = tmp_path / "report.json"
    json_path.write_text(json.dumps(payload_data), encoding="utf-8")

    # ReportStore.initialize + submit 를 mock. Database connect/close 도.
    with (
        patch(
            "ante.core.database.Database.connect",
            new=AsyncMock(),
        ),
        patch(
            "ante.core.database.Database.close",
            new=AsyncMock(),
        ),
        patch(
            "ante.report.ReportStore.initialize",
            new=AsyncMock(),
        ),
        patch(
            "ante.report.ReportStore.submit",
            new=AsyncMock(return_value="rpt-new-1"),
        ),
    ):
        result = _invoke(
            [
                "--format",
                "json",
                "report",
                "submit",
                str(json_path),
                "--db-path",
                str(tmp_path / "ante.db"),
            ]
        )
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_standard_envelope(payload), (
        f"report submit success: standard envelope 이어야 함. payload={payload!r}"
    )
    assert "submitted" in payload["message"].lower()
    assert payload["data"]["report_id"] == "rpt-new-1"
    assert payload["data"]["strategy"] == "my_strategy"


# ── 3. list empty → raw_legacy ─────────────────────────────────────────────


def test_report_list_empty_envelope_matches_raw_legacy(tmp_path) -> None:
    """``report list`` empty: ``fmt.table([], columns)`` → ``[]`` (JSON mode).

    report.py:256: ``fmt.table(rows, ["report_id", "strategy", "status",
    "submitted_at"])``. ``OutputFormatter.table`` JSON 모드는 row list 를
    ``json.dumps`` 한다 (formatter.py:63-64). 빈 리스트는 ``[]`` 그대로.
    """
    with (
        patch("ante.core.database.Database.connect", new=AsyncMock()),
        patch("ante.core.database.Database.close", new=AsyncMock()),
        patch("ante.report.ReportStore.initialize", new=AsyncMock()),
        patch(
            "ante.report.ReportStore.list_reports",
            new=AsyncMock(return_value=[]),
        ),
    ):
        result = _invoke(
            [
                "--format",
                "json",
                "report",
                "list",
                "--db-path",
                str(tmp_path / "ante.db"),
            ]
        )
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_raw_legacy_payload(payload), (
        f"report list empty: standard envelope 아님. payload={payload!r}"
    )
    assert payload == []


# ── 4. list non-empty → raw_legacy ─────────────────────────────────────────


def test_report_list_non_empty_envelope_matches_raw_legacy(tmp_path) -> None:
    """``report list`` non-empty: row list 그대로 dump (raw_legacy).

    report.py:256: ``fmt.table(rows, ...)``. JSON 모드는 row list dump.
    row shape: ``{report_id, strategy, status, submitted_at}``.
    """
    reports = [_make_report(report_id="rpt-1", strategy_name="strat-A")]
    with (
        patch("ante.core.database.Database.connect", new=AsyncMock()),
        patch("ante.core.database.Database.close", new=AsyncMock()),
        patch("ante.report.ReportStore.initialize", new=AsyncMock()),
        patch(
            "ante.report.ReportStore.list_reports",
            new=AsyncMock(return_value=reports),
        ),
    ):
        result = _invoke(
            [
                "--format",
                "json",
                "report",
                "list",
                "--db-path",
                str(tmp_path / "ante.db"),
            ]
        )
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_raw_legacy_payload(payload), (
        f"report list non-empty: standard envelope 아님. payload={payload!r}"
    )
    assert isinstance(payload, list)
    assert len(payload) == 1
    assert payload[0]["report_id"] == "rpt-1"
    assert payload[0]["strategy"] == "strat-A"
    assert payload[0]["status"] == "submitted"


# ── 5. performance empty → raw_legacy ──────────────────────────────────────


def test_report_performance_empty_envelope_matches_raw_legacy(tmp_path) -> None:
    """``report performance`` empty: ``{message, summaries: []}`` 평면.

    report.py:375: ``fmt.output({"message": "집계 데이터가 없습니다.",
    "summaries": []})``. ``PerformanceTracker.get_daily_summary`` 가 빈 list
    반환할 때.
    """
    with (
        patch("ante.core.database.Database.connect", new=AsyncMock()),
        patch("ante.core.database.Database.close", new=AsyncMock()),
        patch(
            "ante.trade.performance.PerformanceTracker.get_daily_summary",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "ante.cli.main.get_db_path",
            return_value=str(tmp_path / "ante.db"),
        ),
    ):
        result = _invoke(
            [
                "--format",
                "json",
                "report",
                "performance",
                "--period",
                "daily",
            ]
        )
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_raw_legacy_payload(payload), (
        f"report performance empty: standard envelope 아님. payload={payload!r}"
    )
    assert payload == {"message": "집계 데이터가 없습니다.", "summaries": []}


# ── 6. performance non-empty (daily) → raw_legacy ──────────────────────────


def test_report_performance_non_empty_envelope_matches_raw_legacy(tmp_path) -> None:
    """``report performance`` non-empty: ``{period, summaries: [...]}``.

    report.py:379: ``if fmt.is_json: fmt.output({"period": period,
    "summaries": result})``. ``DailySummary`` asdict 가 row 리스트로 변환된다.
    """
    from ante.trade.models import DailySummary

    daily = DailySummary(
        date="2026-01-01",
        realized_pnl=10_000.0,
        trade_count=3,
        win_rate=0.67,
    )

    with (
        patch("ante.core.database.Database.connect", new=AsyncMock()),
        patch("ante.core.database.Database.close", new=AsyncMock()),
        patch(
            "ante.trade.performance.PerformanceTracker.get_daily_summary",
            new=AsyncMock(return_value=[daily]),
        ),
        patch(
            "ante.cli.main.get_db_path",
            return_value=str(tmp_path / "ante.db"),
        ),
    ):
        result = _invoke(
            [
                "--format",
                "json",
                "report",
                "performance",
                "--period",
                "daily",
            ]
        )
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_raw_legacy_payload(payload), (
        f"report performance non-empty: standard envelope 아님. payload={payload!r}"
    )
    assert payload["period"] == "daily"
    assert isinstance(payload["summaries"], list)
    assert payload["summaries"][0]["date"] == "2026-01-01"
    assert payload["summaries"][0]["realized_pnl"] == 10_000.0


# ── 7. view (found) → raw_legacy ───────────────────────────────────────────


def test_report_view_found_envelope_matches_raw_legacy(tmp_path) -> None:
    """``report view`` 발견: ``fmt.output(result)`` 평면 detail dict.

    report.py:441: ``if fmt.is_json: fmt.output(result)`` → 평면 dict
    (``{report_id, strategy, status, submitted_at, submitted_by,
    backtest_period, total_return_pct, total_trades, sharpe_ratio,
    max_drawdown_pct, win_rate, summary, rationale, risks,
    recommendations}``). text 는 click.echo.
    """
    report = _make_report(report_id="rpt-view-1", strategy_name="strat-V")
    with (
        patch("ante.core.database.Database.connect", new=AsyncMock()),
        patch("ante.core.database.Database.close", new=AsyncMock()),
        patch("ante.report.ReportStore.initialize", new=AsyncMock()),
        patch(
            "ante.report.ReportStore.get",
            new=AsyncMock(return_value=report),
        ),
    ):
        result = _invoke(
            [
                "--format",
                "json",
                "report",
                "view",
                "rpt-view-1",
                "--db-path",
                str(tmp_path / "ante.db"),
            ]
        )
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_raw_legacy_payload(payload), (
        f"report view found: standard envelope 아님. payload={payload!r}"
    )
    assert payload["report_id"] == "rpt-view-1"
    assert payload["status"] == "submitted"
    assert payload["total_trades"] == 42
    assert "strategy" in payload  # ``{name} v{version}`` 형식.
