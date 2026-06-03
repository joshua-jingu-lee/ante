"""Backtest CLI success output ↔ registry OutputContract drift lock (#1847 sub-PR 9).

본 모듈은 :data:`ante.contracts.cli_registry.CLI_COMMAND_REGISTRY` 에 등록된
backtest 도메인 2 leaf (``backtest run`` / ``backtest history``) 의
``OutputContract`` 와 ``ante backtest ... --format json`` 실제 출력 envelope
shape 사이의 drift 를 lock 한다.

#1846 (account) / #1847 sub-PR 1-8 1:1 동형 패턴. drift 모델:

- ``envelope="standard"`` entry → CLI success envelope ``{status, message,
  data}`` (envelopes.md SSOT).
- ``envelope="raw_legacy"`` entry → JSON mode 에서 ``fmt.output(...)`` 또는
  ``fmt.table(...)`` 으로 평면 dict 또는 row list 를 그대로 dump.

본 PR 은 ``backtest.py`` 본문을 *바꾸지 않으며*, registry entry 가 실제
callsite shape 와 일치함을 단순 lock 만 한다. callsite shape 가 drift
하면 본 test 가 즉시 FAIL 한다.

4 시나리오 (registry sanity +1 + run success +1 + history empty +1 +
history non-empty +1):

0. registry sanity — backtest 2 entries 의 envelope 분류기 범위 내.
1. ``run`` success (mock service.run_subprocess) → ``raw_legacy`` (envelope dict).
2. ``history`` empty → ``raw_legacy`` (``{message, runs: []}``).
3. ``history`` non-empty → ``raw_legacy`` (``{strategy_name, runs: [...]}``).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from ante.contracts.cli_registry import CLI_COMMAND_REGISTRY
from ante.member.models import Member, MemberRole, MemberStatus, MemberType

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


def test_registry_backtest_entries_envelopes_classified() -> None:
    """backtest 2 entries 의 envelope 이 ``standard`` 또는 ``raw_legacy`` 만 사용."""
    accepted = {"standard", "raw_legacy"}
    backtest_entries = [
        (path, contract)
        for path, contract in CLI_COMMAND_REGISTRY.items()
        if path[:1] == ("backtest",)
    ]
    assert len(backtest_entries) == 2, (
        f"backtest 2 entries 가 모두 등록되어야 한다. 실제: {len(backtest_entries)}"
    )
    for path, contract in backtest_entries:
        assert contract.output.envelope in accepted, (
            f"{path}: registry envelope='{contract.output.envelope}' 가 본 "
            f"drift test 의 분류 범위 ({sorted(accepted)}) 를 벗어남."
        )


# ── CLI fixture (동형 패턴) ────────────────────────────────────────────────


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
    """``ante --format json backtest ...`` 를 실행하고 결과를 반환한다."""
    from ante.cli.main import cli

    runner = CliRunner()
    env = {"ANTE_MEMBER_TOKEN": ""}
    return runner.invoke(cli, args, env=env, catch_exceptions=False)


def _load_json_payload(output: str) -> Any:
    """CLI ``--format json`` 출력의 첫 JSON value 를 파싱한다 (동형 패턴)."""
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


# ── 1. run success → raw_legacy ───────────────────────────────────────────


def test_backtest_run_success_envelope_matches_raw_legacy(tmp_path: Path) -> None:
    """``backtest run`` success: ``fmt.output(result_dict, template)`` 평면 dict.

    backtest.py: ``fmt.output(result_dict, ...)`` 평면 dict. ``result_dict`` 는
    ``run_subprocess`` 가 반환하는 envelope(``to_dict()`` superset + 런타임
    result_path/strategy_name/strategy_version)이며 ``run_id`` 추가 후 평면 shape.
    ``BacktestService.run_subprocess`` 를 mock 해 성공 경로를 강제한다 (#2001).
    """
    # strategy file (Path(exists=True) callback 통과용)
    strat_path = tmp_path / "strat.py"
    strat_path.write_text("# dummy strategy file\n", encoding="utf-8")
    db_path = tmp_path / "ante.db"

    # run_subprocess 가 반환하는 envelope dict — 평면 shape.
    result_envelope = {
        "strategy": "test_strategy_v1.0.0",
        "period": "2025-01-01 ~ 2025-12-31",
        "initial_balance": 10_000_000.0,
        "final_balance": 11_250_000.0,
        "total_return_pct": 12.5,
        "total_trades": 0,
        "metrics": {
            "sharpe_ratio": 1.5,
            "max_drawdown": 5.0,
            "win_rate": 0.6,
        },
        "equity_curve": [],
        "trades": [],
        "config": {},
        "datasets": [],
        # #2001: 런타임 메타데이터 3키.
        "result_path": "",
        "strategy_name": "test_strategy",
        "strategy_version": "1.0.0",
    }

    with (
        patch(
            "ante.backtest.service.BacktestService.run_subprocess",
            new=AsyncMock(return_value=result_envelope),
        ),
        patch(
            "ante.backtest.run_store.BacktestRunStore.initialize",
            new=AsyncMock(),
        ),
        patch(
            "ante.backtest.run_store.BacktestRunStore.save",
            new=AsyncMock(return_value="run-001"),
        ),
        patch(
            "ante.core.database.Database.connect",
            new=AsyncMock(),
        ),
        patch(
            "ante.core.database.Database.close",
            new=AsyncMock(),
        ),
    ):
        result = _invoke(
            [
                "--config-dir",
                str(tmp_path),
                "--format",
                "json",
                "backtest",
                "run",
                str(strat_path),
                "--start",
                "2025-01-01",
                "--end",
                "2025-12-31",
                "--symbols",
                "005930",
                "--db-path",
                str(db_path),
            ]
        )
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_raw_legacy_payload(payload), (
        f"backtest run success: standard envelope 아님. payload={payload!r}"
    )
    assert payload["strategy"] == "test_strategy_v1.0.0"
    assert payload["total_return_pct"] == 12.5
    assert payload["run_id"] == "run-001"
    assert "metrics" in payload


# ── 2. history empty → raw_legacy ──────────────────────────────────────────


def test_backtest_history_empty_envelope_matches_raw_legacy(tmp_path: Path) -> None:
    """``backtest history <name>`` empty: ``{message, runs: []}`` 평면.

    backtest.py:262-265: empty → ``fmt.output({"message": ..., "runs": []},
    ...)`` 분기. ``BacktestRunStore.list_by_strategy`` 가 빈 리스트 반환.
    """
    db_path = tmp_path / "ante.db"
    with (
        patch(
            "ante.backtest.run_store.BacktestRunStore.initialize",
            new=AsyncMock(),
        ),
        patch(
            "ante.backtest.run_store.BacktestRunStore.list_by_strategy",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "ante.core.database.Database.connect",
            new=AsyncMock(),
        ),
        patch(
            "ante.core.database.Database.close",
            new=AsyncMock(),
        ),
    ):
        result = _invoke(
            [
                "--config-dir",
                str(tmp_path),
                "--format",
                "json",
                "backtest",
                "history",
                "test_strategy",
                "--db-path",
                str(db_path),
            ]
        )
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_raw_legacy_payload(payload), (
        f"backtest history empty: standard envelope 아님. payload={payload!r}"
    )
    assert payload == {
        "message": "'test_strategy' 백테스트 이력이 없습니다.",
        "runs": [],
    }


# ── 3. history non-empty → raw_legacy ──────────────────────────────────────


def test_backtest_history_non_empty_envelope_matches_raw_legacy(
    tmp_path: Path,
) -> None:
    """``backtest history <name>`` non-empty: ``{strategy_name, runs: [...]}`` 평면.

    backtest.py:269: ``if fmt.is_json: fmt.output({"strategy_name":
    strategy_name, "runs": rows})``. ``BacktestRunStore.list_by_strategy`` 가
    ``BacktestRun`` list 를 반환하고 각 row 는 ``to_dict()`` 결과로 평면 dict.
    """
    run_row = MagicMock()
    run_row.to_dict.return_value = {
        "run_id": "run-001",
        "strategy_name": "test_strategy",
        "strategy_version": "1.0.0",
        "total_return_pct": 12.5,
        "sharpe_ratio": 1.5,
        "max_drawdown_pct": 5.0,
        "total_trades": 10,
        "win_rate": 0.6,
        "created_at": "2026-01-15T10:00:00",
    }
    db_path = tmp_path / "ante.db"
    with (
        patch(
            "ante.backtest.run_store.BacktestRunStore.initialize",
            new=AsyncMock(),
        ),
        patch(
            "ante.backtest.run_store.BacktestRunStore.list_by_strategy",
            new=AsyncMock(return_value=[run_row]),
        ),
        patch(
            "ante.core.database.Database.connect",
            new=AsyncMock(),
        ),
        patch(
            "ante.core.database.Database.close",
            new=AsyncMock(),
        ),
    ):
        result = _invoke(
            [
                "--config-dir",
                str(tmp_path),
                "--format",
                "json",
                "backtest",
                "history",
                "test_strategy",
                "--db-path",
                str(db_path),
            ]
        )
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_raw_legacy_payload(payload), (
        f"backtest history non-empty: standard envelope 아님. payload={payload!r}"
    )
    assert payload["strategy_name"] == "test_strategy"
    assert isinstance(payload["runs"], list)
    assert len(payload["runs"]) == 1
    assert payload["runs"][0]["run_id"] == "run-001"
    assert payload["runs"][0]["total_return_pct"] == 12.5
