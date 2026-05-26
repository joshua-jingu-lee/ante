"""Treasury CLI success output ↔ registry OutputContract drift lock (#1847 sub-PR 4).

본 모듈은 :data:`ante.contracts.cli_registry.CLI_COMMAND_REGISTRY` 에 등록된
treasury 도메인 9 leaf 의 ``OutputContract`` 와 ``ante treasury ... --format
json`` 실제 출력 envelope shape 사이의 drift 를 lock 한다.

#1846 (account) / #1847 sub-PR 1 (member) / #1847 sub-PR 2 (bot) / #1847
sub-PR 3 (approval) 1:1 동형 패턴. drift 모델:

- ``envelope="standard"`` entry → CLI success envelope ``{status, message,
  data}`` (envelopes.md SSOT). ``fmt.success(...)`` callsite 가 dump 한다.
- ``envelope="raw_legacy"`` entry → JSON mode 에서 ``fmt.output(...)`` 으로
  평면 dict 를 그대로 dump 한다 (``status`` / ``message`` / ``data`` 3 키
  모두 동시에 부재 또는 ``status != "ok"``).

본 PR 은 ``treasury.py`` 본문을 *바꾸지 않으며*, registry entry 가 실제
callsite shape 와 일치함을 단순 lock 만 한다. callsite shape 가 drift 하면
본 test 가 즉시 FAIL 한다 (registry 갱신 또는 callsite 정렬 중 한쪽이
책임).

12 시나리오 (9 leaf + registry sanity +1 + transactions empty 분리 +1 +
snapshot range 분리 +1):

0. registry sanity — treasury 9 entries 의 envelope 이 ``standard`` /
   ``raw_legacy`` 분류 범위 내.
1. ``status`` → ``raw_legacy`` (``fmt.output(result)`` 평면 ``{account_balance,
   ...}``)
2. ``transactions`` empty (no such table 분기) → ``raw_legacy`` (``{items: [],
   total: 0}``)
3. ``transactions`` non-empty → ``raw_legacy`` (``{items: [...], total}``)
4. ``budgets`` → ``raw_legacy`` (``fmt.output(result)`` 평면 ``{budgets:
   [...]}``)
5. ``set-balance`` → ``raw_legacy`` (``fmt.output(result)`` 평면 ``{account_id,
   total_balance, updated_at}`` — IPC 분기)
6. ``allocate`` → ``standard`` (``fmt.success(message, data)``)
7. ``deallocate`` → ``standard`` (``fmt.success(message, data)``)
8. ``snapshot`` single → ``raw_legacy`` (``fmt.output(result)`` 평면 snapshot dict)
9. ``snapshot`` range → ``raw_legacy`` (``fmt.output(result)`` 평면 snapshot list)
10. ``portfolio value`` → ``raw_legacy`` (``fmt.output(result)`` 평면
    ``{total_value, daily_pnl, ...}``)
11. ``portfolio history`` → ``raw_legacy`` (``fmt.output(result)`` 평면
    ``{data: [...], start_date, end_date}``)
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from ante.contracts.cli_registry import CLI_COMMAND_REGISTRY
from ante.member.models import Member, MemberRole, MemberStatus, MemberType
from ante.treasury.models import BotBudget

# ── envelope shape predicates (envelopes.md SSOT, account/member/bot/approval 동형) ──

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
    """평면 dict 또는 list 로 standard envelope 의 3 필수 키 셋이 부재함을 단언.

    raw_legacy 는 ``fmt.output(dict)`` 출력의 super-set 이다. ``fmt.table``
    callsite 는 본 treasury 도메인에서 *text 모드 전용* 이고 JSON 모드는
    별도 분기로 ``fmt.output(dict)`` 를 호출한다 (bot ``list``/``positions``
    동형 — JSON 분기와 text 분기가 다른 shape).
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


def test_registry_treasury_entries_envelopes_classified() -> None:
    """treasury 9 entry 의 envelope 이 ``standard`` 또는 ``raw_legacy`` 만 사용.

    본 단언은 본 모듈 fixture 의 envelope predicate 두 함수가 9 entry 를
    모두 분류할 수 있음을 lock 한다. envelope SSOT (#1821) 에 새 값이
    추가되면 본 분류기를 갱신해야 함을 표면화한다.
    """
    accepted = {"standard", "raw_legacy"}
    treasury_entries = [
        (path, contract)
        for path, contract in CLI_COMMAND_REGISTRY.items()
        if path[:1] == ("treasury",)
    ]
    assert len(treasury_entries) == 9, (
        f"treasury 9 entries 가 모두 등록되어야 한다. 실제: {len(treasury_entries)}"
    )
    for path, contract in treasury_entries:
        assert contract.output.envelope in accepted, (
            f"{path}: registry envelope='{contract.output.envelope}' 가 본 "
            f"drift test 의 분류 범위 ({sorted(accepted)}) 를 벗어남. "
            "envelope SSOT (#1821) 가 새 값을 추가했다면 본 분류기를 갱신하라."
        )


# ── CLI fixture (account/member/bot/approval drift test 동형) ──────────────


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
    """master member 로 인증 우회 (account/member/bot/approval drift test 동형)."""
    with patch(
        "ante.cli.main.authenticate_member",
        side_effect=lambda ctx: ctx.obj.update({"member": _MOCK_MASTER}),
    ):
        yield


def _invoke(args: list[str]):
    """``ante --format json treasury ...`` 를 실행하고 결과를 반환한다."""
    from ante.cli.main import cli

    runner = CliRunner()
    env = {"ANTE_MEMBER_TOKEN": ""}
    return runner.invoke(cli, args, env=env, catch_exceptions=False)


def _load_json_payload(output: str) -> Any:
    """CLI ``--format json`` 출력의 첫 JSON value 를 파싱한다.

    ``OutputFormatter`` 가 ``json.dumps(..., indent=2)`` 로 multi-line dump
    하기 때문에 처음 ``{`` 또는 ``[`` 부터 ``raw_decode`` 로 한 value 를
    파싱하고 나머지 stdout (text 모드 잔존물 등) 는 무시한다 (approval
    drift test 동형). ``fmt.success``/``fmt.output`` 출력은 dict.
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


def _make_mock_db(
    fetch_one: Any = None,
    fetch_all: list[Any] | None = None,
    raise_on_query: Exception | None = None,
) -> AsyncMock:
    """``Database`` mock — ``connect`` / ``close`` / ``fetch_*`` async 메서드.

    ``transactions`` leaf 는 ``Database(get_db_path())`` 를 직접 생성하므로
    이 mock 이 필요하다. ``raise_on_query`` 가 주어지면 ``fetch_one`` /
    ``fetch_all`` 가 그 예외를 raise (``no such table`` 분기 lock 용).
    """
    db = AsyncMock()
    db.connect = AsyncMock()
    db.close = AsyncMock()
    if raise_on_query is not None:
        db.fetch_one = AsyncMock(side_effect=raise_on_query)
        db.fetch_all = AsyncMock(side_effect=raise_on_query)
    else:
        db.fetch_one = AsyncMock(return_value=fetch_one)
        db.fetch_all = AsyncMock(return_value=fetch_all or [])
    db.execute = AsyncMock()
    return db


def _make_mock_treasury(
    *,
    summary: dict[str, Any] | None = None,
    budgets: list[BotBudget] | None = None,
    daily_snapshot: dict[str, Any] | None = None,
    snapshots_range: list[dict[str, Any]] | None = None,
    latest_snapshot: dict[str, Any] | None = None,
    account_id: str = "acc-1",
) -> AsyncMock:
    """``Treasury`` mock — CLI 가 호출하는 메서드들의 응답을 customize.

    ``Treasury`` 는 sync/async 메서드 mix 다 (``get_summary``/``list_budgets``
    은 sync; ``get_daily_snapshot``/``get_snapshots``/``get_latest_snapshot``/
    ``set_account_balance`` 는 async). ``AsyncMock`` 은 모든 attribute 접근에
    AsyncMock 을 반환하므로 sync 메서드는 ``MagicMock`` 으로 덮어쓴다.
    """
    t = AsyncMock()
    t.account_id = account_id
    # sync 메서드는 MagicMock 으로 덮어쓴다.
    t.get_summary = MagicMock(
        return_value=summary
        or {
            "account_balance": 10_000_000.0,
            "purchasable_amount": 10_000_000.0,
            "total_evaluation": 12_500_000.0,
            "total_profit_loss": 500_000.0,
            "total_allocated": 2_500_000.0,
            "total_reserved": 0.0,
            "unallocated": 7_500_000.0,
            "bot_count": 2,
        }
    )
    t.list_budgets = MagicMock(return_value=budgets or [])
    # async 메서드.
    t.get_daily_snapshot = AsyncMock(return_value=daily_snapshot)
    t.get_snapshots = AsyncMock(return_value=snapshots_range or [])
    t.get_latest_snapshot = AsyncMock(return_value=latest_snapshot)
    t.set_account_balance = AsyncMock()
    # 잔고 (set-balance cold_path 분기 fallback shape).
    t.account_balance = (summary or {}).get("account_balance", 10_000_000.0)
    return t


@pytest.fixture
def mock_create_treasury():
    """``treasury._create_treasury`` 를 patch — ``(treasury_mock, db_mock)`` 반환.

    #1857: ``_create_treasury`` 는 async context manager 로 변환되었다.
    """
    from contextlib import asynccontextmanager

    t = _make_mock_treasury()
    db = AsyncMock()
    db.close = AsyncMock()

    @asynccontextmanager
    async def _stub_create(account_id=None, *, ctx=None):  # noqa: ANN001, ANN202
        yield t, db

    with patch(
        "ante.cli.commands.treasury._create_treasury",
        new=_stub_create,
    ):
        yield t, db


@pytest.fixture
def mock_ipc_send():
    """``ipc_send`` 를 mock 한다 (runtime_ipc 분기 leaf 용).

    각 테스트가 ``mock_ipc.return_value`` 를 설정해 IPC 응답을 customize.
    treasury.py 는 ``from ante.cli.commands.ipc_helpers import ipc_send``
    를 함수 내부에서 lazy import 하므로 원본 모듈을 patch 해야 한다.
    ``set-balance`` 는 ``is_active_runtime() == True`` 분기로만 IPC 를
    사용하므로 그 게이트도 함께 patch 해야 한다 (account/bot 동형).
    """
    with patch("ante.cli.commands.ipc_helpers.ipc_send", new=AsyncMock()) as m:
        yield m


# ── 1. treasury status → raw_legacy ────────────────────────────────────────


def test_treasury_status_envelope_matches_raw_legacy(mock_create_treasury) -> None:
    """``treasury status``: ``fmt.output(result)`` 평면 summary dict (raw_legacy)."""
    _t, _db = mock_create_treasury

    result = _invoke(["--format", "json", "treasury", "status", "--account", "acc-1"])
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_raw_legacy_payload(payload), (
        f"treasury status: standard envelope 아니어야 함 (registry "
        f"envelope=raw_legacy 와 정합). 실제 payload={payload!r}"
    )
    # summary 평면 키 셋: account_balance / purchasable_amount /
    # total_evaluation / total_profit_loss / total_allocated /
    # total_reserved / unallocated / bot_count.
    assert payload["account_balance"] == 10_000_000.0
    assert payload["bot_count"] == 2


# ── 2. treasury transactions (empty no-table / non-empty) → raw_legacy ────


def test_treasury_transactions_empty_envelope_matches_raw_legacy() -> None:
    """``treasury transactions`` (no such table 분기): ``{items: [], total: 0}``.

    treasury.py 240-243: ``treasury_transactions`` 테이블이 부재하면 SELECT
    실패가 빈 결과로 다운그레이드된다. JSON 모드는 ``fmt.output(result)``.
    """
    db = _make_mock_db(raise_on_query=Exception("no such table: treasury_transactions"))
    # treasury.py 가 함수 내부에서 ``from ante.core.database import Database``
    # 를 lazy import 하므로 원본 모듈만 patch 한다.
    with patch("ante.core.database.Database", return_value=db):
        result = _invoke(["--format", "json", "treasury", "transactions"])
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_raw_legacy_payload(payload), (
        f"treasury transactions empty: standard envelope 아님. payload={payload!r}"
    )
    assert payload == {"items": [], "total": 0}


def test_treasury_transactions_non_empty_envelope_matches_raw_legacy() -> None:
    """``treasury transactions`` non-empty: ``{items: [...], total}`` 평면.

    treasury.py 244-256: row mapping 으로 ``items`` 리스트 + ``total`` 카운트.
    """
    sample_row = {
        "id": 1,
        "account_id": "acc-1",
        "transaction_type": "allocate",
        "bot_id": "bot-1",
        "amount": 100_000.0,
        "description": "테스트 할당",
        "created_at": "2026-01-01T00:00:00",
    }
    db = _make_mock_db(
        fetch_one={"cnt": 1},
        fetch_all=[sample_row],
    )
    with patch("ante.core.database.Database", return_value=db):
        result = _invoke(["--format", "json", "treasury", "transactions"])
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_raw_legacy_payload(payload), (
        f"treasury transactions non-empty: standard envelope 아님. payload={payload!r}"
    )
    assert payload["total"] == 1
    assert len(payload["items"]) == 1
    assert payload["items"][0]["id"] == 1
    assert payload["items"][0]["type"] == "allocate"
    assert payload["items"][0]["bot_id"] == "bot-1"


# ── 3. treasury budgets → raw_legacy ─────────────────────────────────────


def test_treasury_budgets_envelope_matches_raw_legacy(mock_create_treasury) -> None:
    """``treasury budgets`` (with --account): ``{budgets: [...]}`` 평면.

    treasury.py 290-327: ``fmt.output({"budgets": items})`` JSON 모드.
    """
    t, _db = mock_create_treasury
    t.list_budgets = MagicMock(
        return_value=[
            BotBudget(
                bot_id="bot-1",
                account_id="acc-1",
                allocated=1_000_000.0,
                available=900_000.0,
                reserved=100_000.0,
            )
        ]
    )

    result = _invoke(["--format", "json", "treasury", "budgets", "--account", "acc-1"])
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_raw_legacy_payload(payload), (
        f"treasury budgets: standard envelope 아님. payload={payload!r}"
    )
    assert "budgets" in payload
    assert isinstance(payload["budgets"], list)
    assert payload["budgets"][0]["bot_id"] == "bot-1"
    assert payload["budgets"][0]["allocated"] == 1_000_000.0


# ── 4. treasury set-balance → raw_legacy ─────────────────────────────────


def test_treasury_set_balance_envelope_matches_raw_legacy(mock_ipc_send) -> None:
    """``treasury set-balance`` (IPC 분기): ``{account_id, total_balance, ...}`` 평면.

    treasury.py 386-389: ``fmt.output(result)`` JSON 모드. IPC 응답을 그대로
    dump 한다 (account ``set-credentials`` 동형 — IPC envelope passthrough).
    runtime IPC 분기를 강제하기 위해 ``is_active_runtime`` 도 True 로 patch.
    """
    mock_ipc_send.return_value = {
        "account_id": "acc-1",
        "total_balance": 15_000_000.0,
        "updated_at": "2026-01-01T00:00:00+00:00",
    }

    with patch("ante.cli.cold_path.is_active_runtime", return_value=True):
        result = _invoke(
            [
                "--format",
                "json",
                "treasury",
                "set-balance",
                "15000000",
                "--account",
                "acc-1",
            ]
        )
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_raw_legacy_payload(payload), (
        f"treasury set-balance: standard envelope 아님. payload={payload!r}"
    )
    assert payload["account_id"] == "acc-1"
    assert payload["total_balance"] == 15_000_000.0


# ── 5. treasury allocate → standard ──────────────────────────────────────


def test_treasury_allocate_envelope_matches_operation_standard(mock_ipc_send) -> None:
    """``treasury allocate``: 단일 success 경로 ``fmt.success(message, data)``.

    treasury.py 453-457: ``fmt.success(message, {"bot_id", "amount",
    "account_id"})`` standard envelope.
    """
    mock_ipc_send.return_value = {
        "success": True,
        "bot_id": "bot-1",
        "amount": 100_000.0,
    }

    result = _invoke(
        [
            "--format",
            "json",
            "treasury",
            "allocate",
            "bot-1",
            "100000",
            "--account",
            "acc-1",
        ]
    )
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_standard_envelope(payload), (
        f"treasury allocate: standard envelope 이어야 함. payload={payload!r}"
    )
    assert "예산 할당 완료" in payload["message"]
    assert payload["data"]["bot_id"] == "bot-1"
    assert payload["data"]["amount"] == 100_000.0
    assert payload["data"]["account_id"] == "acc-1"


# ── 6. treasury deallocate → standard ────────────────────────────────────


def test_treasury_deallocate_envelope_matches_operation_standard(
    mock_ipc_send,
) -> None:
    """``treasury deallocate``: 단일 success 경로 ``fmt.success(message, data)``.

    treasury.py 515-519: ``fmt.success(message, {"bot_id", "amount",
    "account_id"})`` standard envelope (allocate 동형).
    """
    mock_ipc_send.return_value = {
        "success": True,
        "bot_id": "bot-1",
        "amount": 50_000.0,
    }

    result = _invoke(
        [
            "--format",
            "json",
            "treasury",
            "deallocate",
            "bot-1",
            "50000",
            "--account",
            "acc-1",
        ]
    )
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_standard_envelope(payload), (
        f"treasury deallocate: standard envelope 이어야 함. payload={payload!r}"
    )
    assert "예산 회수 완료" in payload["message"]
    assert payload["data"]["bot_id"] == "bot-1"
    assert payload["data"]["amount"] == 50_000.0


# ── 7. treasury snapshot (single / range) → raw_legacy ───────────────────


_SAMPLE_SNAPSHOT = {
    "account_id": "acc-1",
    "snapshot_date": "2026-01-01",
    "total_asset": 12_500_000.0,
    "ante_eval_amount": 2_500_000.0,
    "ante_purchase_amount": 2_500_000.0,
    "unallocated": 10_000_000.0,
    "account_balance": 10_000_000.0,
    "total_allocated": 2_500_000.0,
    "bot_count": 2,
    "daily_pnl": 0.0,
    "daily_return": 0.0,
    "net_trade_amount": 0.0,
    "unrealized_pnl": 0.0,
    "created_at": "2026-01-01T23:59:59+00:00",
}


def test_treasury_snapshot_single_envelope_matches_raw_legacy(
    mock_create_treasury,
) -> None:
    """``treasury snapshot --date``: 평면 snapshot dict (raw_legacy)."""
    t, _db = mock_create_treasury
    t.get_daily_snapshot = AsyncMock(return_value=_SAMPLE_SNAPSHOT)

    result = _invoke(
        [
            "--format",
            "json",
            "treasury",
            "snapshot",
            "--date",
            "2026-01-01",
            "--account",
            "acc-1",
        ]
    )
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_raw_legacy_payload(payload), (
        f"treasury snapshot single: standard envelope 아님. payload={payload!r}"
    )
    assert payload["snapshot_date"] == "2026-01-01"
    assert payload["total_asset"] == 12_500_000.0


def test_treasury_snapshot_range_envelope_matches_raw_legacy(
    mock_create_treasury,
) -> None:
    """``treasury snapshot --from --to``: 평면 snapshot list (raw_legacy).

    treasury.py 596-601: 기간 조회 분기는 ``get_snapshots`` 가 list 를 반환,
    JSON 모드는 ``fmt.output(result)`` 가 list 를 그대로 dump.
    """
    t, _db = mock_create_treasury
    t.get_snapshots = AsyncMock(
        return_value=[
            _SAMPLE_SNAPSHOT,
            {**_SAMPLE_SNAPSHOT, "snapshot_date": "2026-01-02"},
        ]
    )

    result = _invoke(
        [
            "--format",
            "json",
            "treasury",
            "snapshot",
            "--from",
            "2026-01-01",
            "--to",
            "2026-01-02",
            "--account",
            "acc-1",
        ]
    )
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_raw_legacy_payload(payload), (
        f"treasury snapshot range: standard envelope 아님. payload={payload!r}"
    )
    assert isinstance(payload, list)
    assert len(payload) == 2
    assert payload[0]["snapshot_date"] == "2026-01-01"


# ── 8. treasury portfolio value → raw_legacy ─────────────────────────────


def test_treasury_portfolio_value_envelope_matches_raw_legacy(
    mock_create_treasury,
) -> None:
    """``treasury portfolio value`` (with --account): ``{total_value, ...}`` 평면.

    treasury.py 715-722: ``fmt.output(result)`` 평면 dict (``total_value``,
    ``daily_pnl``, ``daily_return``, ``unrealized_pnl``, ``accounts``,
    ``updated_at``).
    """
    t, _db = mock_create_treasury
    t.get_latest_snapshot = AsyncMock(
        return_value={
            "total_asset": 12_500_000.0,
            "daily_pnl": 150_000.0,
            "daily_return": 1.2,
            "unrealized_pnl": 50_000.0,
            "snapshot_date": "2026-01-01",
            "created_at": "2026-01-01T23:59:59+00:00",
        }
    )

    result = _invoke(
        [
            "--format",
            "json",
            "treasury",
            "portfolio",
            "value",
            "--account",
            "acc-1",
        ]
    )
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_raw_legacy_payload(payload), (
        f"treasury portfolio value: standard envelope 아님. payload={payload!r}"
    )
    assert payload["total_value"] == 12_500_000.0
    assert payload["daily_pnl"] == 150_000.0
    assert "accounts" in payload
    assert isinstance(payload["accounts"], list)


# ── 9. treasury portfolio history → raw_legacy ───────────────────────────


def test_treasury_portfolio_history_envelope_matches_raw_legacy(
    mock_create_treasury,
) -> None:
    """``treasury portfolio history`` (with --account): ``{data, start_date,
    end_date}`` 평면.

    treasury.py 814: ``return {"data": data, "start_date": ..., "end_date":
    ...}`` → JSON 모드는 ``fmt.output(result)``.
    """
    t, _db = mock_create_treasury
    t.get_snapshots = AsyncMock(
        return_value=[
            {
                "snapshot_date": "2026-01-01",
                "total_asset": 12_500_000.0,
                "daily_pnl": 0.0,
                "daily_return": 0.0,
                "unrealized_pnl": 0.0,
            },
            {
                "snapshot_date": "2026-01-02",
                "total_asset": 12_650_000.0,
                "daily_pnl": 150_000.0,
                "daily_return": 1.2,
                "unrealized_pnl": 50_000.0,
            },
        ]
    )

    result = _invoke(
        [
            "--format",
            "json",
            "treasury",
            "portfolio",
            "history",
            "--account",
            "acc-1",
            "--from",
            "2026-01-01",
            "--to",
            "2026-01-02",
        ]
    )
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_raw_legacy_payload(payload), (
        f"treasury portfolio history: standard envelope 아님. payload={payload!r}"
    )
    assert "data" in payload
    assert isinstance(payload["data"], list)
    assert len(payload["data"]) == 2
    assert payload["start_date"] == "2026-01-01"
    assert payload["end_date"] == "2026-01-02"
