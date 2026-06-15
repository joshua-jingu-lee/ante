"""Broker CLI success output ↔ registry OutputContract drift lock (#1847 sub-PR 7).

본 모듈은 :data:`ante.contracts.cli_registry.CLI_COMMAND_REGISTRY` 에 등록된
broker 도메인 4 leaf 의 ``OutputContract`` 와 ``ante broker ... --format json``
실제 출력 envelope shape 사이의 drift 를 lock 한다.

#1846 (account) / #1847 sub-PR 1 (member) / sub-PR 2 (bot) / sub-PR 3
(approval) / sub-PR 4 (treasury) / sub-PR 5 (strategy) / sub-PR 6 (data /
report) 1:1 동형 패턴. drift 모델:

- ``envelope="standard"`` entry → CLI success envelope ``{status, message,
  data}`` (envelopes.md SSOT). ``fmt.success(...)`` callsite 가 dump 한다.
- ``envelope="raw_legacy"`` entry → JSON mode 에서 ``fmt.output(...)`` 또는
  ``fmt.table(...)`` 으로 평면 dict 또는 row list 를 그대로 dump 한다
  (standard envelope 의 3 키 셋이 동시에 부재 또는 ``status != "ok"``).

본 PR 은 ``broker.py`` 본문을 *바꾸지 않으며*, registry entry 가 실제 callsite
shape 와 일치함을 단순 lock 만 한다. callsite shape 가 drift 하면 본 test 가
즉시 FAIL 한다 (registry 갱신 또는 callsite 정렬 중 한쪽이 책임).

broker.py 는 모든 4 leaf 가 IPC 우선 + cold_path fallback 구조 (``ipc_send``
가 ``click.ClickException`` 을 raise 하면 fallback) 를 가진다. 본 drift test
는 IPC 분기를 강제로 success path 로 mock 해 success envelope 단언만 한다
— fallback 분기의 drift 는 별도 covered 가 필요하면 후속 sub-PR 가 추가한다.

8 시나리오 (4 leaf + registry sanity +1 + positions empty 분기 +1 +
positions non-empty +1 + reconcile match 분기 +1):

0. registry sanity — broker 4 entries 의 envelope 이 ``standard`` /
   ``raw_legacy`` 분류 범위 내.
1. ``status`` → ``raw_legacy`` (``fmt.output(result)``)
2. ``balance`` → ``raw_legacy`` (``fmt.output(result)``)
3. ``positions`` empty → ``raw_legacy`` (``{message, positions: []}``)
4. ``positions`` non-empty → ``raw_legacy`` (``{positions: [...]}``)
5. ``reconcile`` (match) → ``raw_legacy`` (``{total_symbols, ..., match: True}``)
6. ``reconcile`` --fix → ``raw_legacy`` (``{total_symbols, ..., fix_applied: True}``)
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, patch

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
    """평면 dict / list 로 standard envelope 의 3 필수 키 셋이 부재함을 단언.

    raw_legacy 는 ``fmt.output(dict)`` / ``fmt.table(rows)`` 출력의 super-set
    이다. ``status``/``message``/``data`` 3 키가 동시에 갖춰지고 ``status ==
    "ok"`` 면 standard envelope 으로 분류 (애매한 경계 방지). 그렇지 않으면
    모든 평면 도메인 payload 는 raw_legacy.
    """
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


def test_registry_broker_entries_envelopes_classified() -> None:
    """broker 4 entry 의 envelope 이 ``standard`` 또는 ``raw_legacy`` 만 사용.

    본 단언은 본 모듈 fixture 의 envelope predicate 두 함수가 4 entry 를
    모두 분류할 수 있음을 lock 한다. envelope SSOT (#1821) 에 새 값이
    추가되면 본 분류기를 갱신해야 함을 표면화한다.
    """
    accepted = {"standard", "raw_legacy"}
    broker_entries = [
        (path, contract)
        for path, contract in CLI_COMMAND_REGISTRY.items()
        if path[:1] == ("broker",)
    ]
    assert len(broker_entries) == 4, (
        f"broker 4 entries 가 모두 등록되어야 한다. 실제: {len(broker_entries)}"
    )
    for path, contract in broker_entries:
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
    """``ante --format json broker ...`` 를 실행하고 결과를 반환한다."""
    from ante.cli.main import cli

    runner = CliRunner()
    env = {"ANTE_MEMBER_TOKEN": ""}
    return runner.invoke(cli, args, env=env, catch_exceptions=False)


def _load_json_payload(output: str) -> Any:
    """CLI ``--format json`` 출력의 첫 JSON value 를 파싱한다.

    ``OutputFormatter`` 가 ``json.dumps(..., indent=2)`` 로 multi-line dump
    하기 때문에 처음 ``{`` 또는 ``[`` 부터 ``raw_decode`` 로 한 value 를
    파싱하고 나머지 stdout (text 모드 잔존물 등) 는 무시한다 (data / report
    drift test 동형).
    """
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


# ── 1. status → raw_legacy ─────────────────────────────────────────────────


def test_broker_status_envelope_matches_raw_legacy() -> None:
    """``broker status``: ``fmt.output(result)`` 평면 dict (raw_legacy).

    broker.py:159: ``if fmt.is_json: fmt.output(result)`` → IPC server
    BrokerAdapter response 평면 dict (``{connected, healthy, exchange?,
    error?}``). 본 fixture 는 ``ipc_send`` 를 mock 해 IPC 분기를 강제한다.
    """
    ipc_response = {
        "connected": True,
        "healthy": True,
        "exchange": "KIS",
    }
    with patch(
        "ante.cli.commands.ipc_helpers.ipc_send",
        new=AsyncMock(return_value=ipc_response),
    ):
        result = _invoke(
            [
                "--format",
                "json",
                "broker",
                "status",
                "--account",
                "acct-001",
            ]
        )
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_raw_legacy_payload(payload), (
        f"broker status: standard envelope 아님. payload={payload!r}"
    )
    assert payload["connected"] is True
    assert payload["healthy"] is True
    assert payload["exchange"] == "KIS"


# ── 2. balance → raw_legacy ────────────────────────────────────────────────


def test_broker_balance_envelope_matches_raw_legacy() -> None:
    """``broker balance``: ``fmt.output(result)`` 평면 dict (raw_legacy).

    broker.py:220: ``if fmt.is_json: fmt.output(result)`` → broker adapter
    가 반환하는 평면 잔고 dict. 본 fixture 는 IPC 분기를 mock 한다.
    """
    # #2384: get_account_balance(broker balance passthrough)는 purchasable_amount
    # 키를 더 이상 포함하지 않고(주문가능액 SSOT는 get_buyable), psbl_sbst_amt를
    # substitute_amount로 보존한다. fixture 를 새 계약과 일치시킨다.
    ipc_response = {
        "account_balance": 10_000_000.0,
        "substitute_amount": 0.0,
        "total_evaluation": 12_500_000.0,
        "total_profit_loss": 2_500_000.0,
    }
    with patch(
        "ante.cli.commands.ipc_helpers.ipc_send",
        new=AsyncMock(return_value=ipc_response),
    ):
        result = _invoke(
            [
                "--format",
                "json",
                "broker",
                "balance",
                "--account",
                "acct-001",
            ]
        )
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_raw_legacy_payload(payload), (
        f"broker balance: standard envelope 아님. payload={payload!r}"
    )
    assert payload["account_balance"] == 10_000_000.0
    assert payload["total_evaluation"] == 12_500_000.0


# ── 3. positions empty → raw_legacy ────────────────────────────────────────


def test_broker_positions_empty_envelope_matches_raw_legacy() -> None:
    """``broker positions`` empty: ``{message, positions: []}`` 평면.

    broker.py:278: ``fmt.output({"message": "보유 종목 없음", "positions": []})``.
    IPC 가 빈 positions 를 반환할 때 분기.
    """
    ipc_response = {"positions": []}
    with patch(
        "ante.cli.commands.ipc_helpers.ipc_send",
        new=AsyncMock(return_value=ipc_response),
    ):
        result = _invoke(
            [
                "--format",
                "json",
                "broker",
                "positions",
                "--account",
                "acct-001",
            ]
        )
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_raw_legacy_payload(payload), (
        f"broker positions empty: standard envelope 아님. payload={payload!r}"
    )
    assert payload == {"message": "보유 종목 없음", "positions": []}


# ── 4. positions non-empty → raw_legacy ────────────────────────────────────


def test_broker_positions_non_empty_envelope_matches_raw_legacy() -> None:
    """``broker positions`` non-empty: ``{positions: [...]}`` 평면.

    broker.py:282: ``if fmt.is_json: fmt.output({"positions": pos_list})``.
    """
    pos_rows = [
        {
            "symbol": "005930",
            "quantity": 10,
            "avg_price": 70000,
            "eval_amount": 720000,
        },
        {
            "symbol": "000660",
            "quantity": 5,
            "avg_price": 120000,
            "eval_amount": 600000,
        },
    ]
    ipc_response = {"positions": pos_rows}
    with patch(
        "ante.cli.commands.ipc_helpers.ipc_send",
        new=AsyncMock(return_value=ipc_response),
    ):
        result = _invoke(
            [
                "--format",
                "json",
                "broker",
                "positions",
                "--account",
                "acct-001",
            ]
        )
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_raw_legacy_payload(payload), (
        f"broker positions non-empty: standard envelope 아님. payload={payload!r}"
    )
    assert isinstance(payload["positions"], list)
    assert len(payload["positions"]) == 2
    assert payload["positions"][0]["symbol"] == "005930"


# ── 5. reconcile (match) → raw_legacy ──────────────────────────────────────


def test_broker_reconcile_match_envelope_matches_raw_legacy() -> None:
    """``broker reconcile`` (match): ``fmt.output(result)`` 평면 dict.

    broker.py:406: ``if fmt.is_json: fmt.output(result)`` → ``{total_symbols,
    discrepancies, match, fix_applied, corrections}``.
    """
    ipc_response = {
        "total_symbols": 3,
        "discrepancies": [],
        "match": True,
        "fix_applied": False,
        "corrections": 0,
    }
    with patch(
        "ante.cli.commands.ipc_helpers.ipc_send",
        new=AsyncMock(return_value=ipc_response),
    ):
        result = _invoke(
            [
                "--format",
                "json",
                "broker",
                "reconcile",
                "--account",
                "acct-001",
            ]
        )
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_raw_legacy_payload(payload), (
        f"broker reconcile match: standard envelope 아님. payload={payload!r}"
    )
    assert payload["total_symbols"] == 3
    assert payload["match"] is True
    assert payload["fix_applied"] is False


# ── 6. reconcile --fix → raw_legacy ────────────────────────────────────────


def test_broker_reconcile_fix_envelope_matches_raw_legacy() -> None:
    """``broker reconcile --fix``: IPC mutating ``fmt.output(result)`` 평면.

    broker.py:406 동일 callsite. ``--fix`` 분기는 IPC ``broker.reconcile``
    호출 (line 317) 후 동일 success envelope shape 로 dump.
    """
    ipc_response = {
        "total_symbols": 4,
        "discrepancies": [
            {
                "symbol": "005930",
                "broker_qty": 10.0,
                "internal_qty": 8.0,
                "diff": 2.0,
            },
        ],
        "match": False,
        "fix_applied": True,
        "corrections": 1,
    }
    with patch(
        "ante.cli.commands.ipc_helpers.ipc_send",
        new=AsyncMock(return_value=ipc_response),
    ):
        result = _invoke(
            [
                "--format",
                "json",
                "broker",
                "reconcile",
                "--account",
                "acct-001",
                "--fix",
            ]
        )
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_raw_legacy_payload(payload), (
        f"broker reconcile --fix: standard envelope 아님. payload={payload!r}"
    )
    assert payload["fix_applied"] is True
    assert payload["corrections"] == 1
    assert isinstance(payload["discrepancies"], list)
