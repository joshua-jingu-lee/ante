"""Bot CLI success output ↔ registry OutputContract drift lock (#1847 sub-PR 2).

본 모듈은 :data:`ante.contracts.cli_registry.CLI_COMMAND_REGISTRY` 에 등록된
bot 도메인 11 leaf 의 ``OutputContract`` 와 ``ante bot ... --format json``
실제 출력 envelope shape 사이의 drift 를 lock 한다.

#1846 (account) / #1847 sub-PR 1 (member) 1:1 동형 패턴. drift 모델:

- ``envelope="standard"`` entry → CLI success envelope ``{status, message,
  data}`` (envelopes.md SSOT). ``fmt.success(...)`` callsite 가 dump 한다.
- ``envelope="raw_legacy"`` entry → JSON mode 에서 ``fmt.output(...)`` 로
  평면 dict (혹은 IPC envelope passthrough) 를 그대로 dump 한다
  (``status``/``message``/``data`` 3 키 모두 동시에 부재).

본 PR 은 ``bot.py`` 본문을 *바꾸지 않으며*, registry entry 가 실제 callsite
shape 와 일치함을 단순 lock 만 한다. callsite shape 가 drift 하면 본 test
가 즉시 FAIL 한다 (registry 갱신 또는 callsite 정렬 중 한쪽이 책임).

13 시나리오 (11 leaf + signal-key 분기 mixed +1 + registry sanity +1):

0. registry sanity — bot 11 entries 의 envelope 이 ``standard`` /
   ``raw_legacy`` 분류 범위 내.
1. ``list`` empty (rows 0) → ``raw_legacy`` (``{message, bots}``)
2. ``list`` non-empty → ``raw_legacy`` (``{bots: [...]}``)
3. ``info`` → ``raw_legacy`` (평면 detail dict)
4. ``create`` → ``standard`` (``fmt.success(message, data)``)
5. ``remove`` → ``standard`` (``fmt.success(message, data)``)
6. ``signal-key`` query (no --rotate) → ``raw_legacy`` (``{bot_id, signal_key}``)
7. ``signal-key --rotate`` → ``standard`` (``fmt.success(message, data)``)
   분기 mixed lock — registry 는 raw_legacy 우선이지만 rotate 분기가
   standard envelope 임을 별도 lock 해 분기 mixed 사실을 명시한다
   (account ``set-credentials`` 동형 정책). #2111: rotate 는 runtime IPC
   (``bot.signal_key.rotate``) 로 라우팅되지만 출력 계약(standard envelope)
   은 그대로 보존된다 — 라우팅 변경이 출력-shape 변경이 아님을 lock 한다.
8. ``positions`` empty → ``raw_legacy`` (``{message, positions}``)
9. ``positions`` non-empty → ``raw_legacy`` (``{positions: [...]}``)
10. ``update`` → ``raw_legacy`` (``fmt.output(result)`` 평면)
11. ``logs`` → ``raw_legacy`` (``fmt.output(result)`` 평면 ``{bot_id, logs,
    total}``)
12. ``start`` → ``raw_legacy`` (IPC ``{bot: ...}`` envelope passthrough)
13. ``stop`` → ``raw_legacy`` (IPC envelope passthrough)
14. ``status`` → ``raw_legacy`` (IPC ``{bot: ...}`` envelope passthrough)
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from ante.contracts.cli_registry import CLI_COMMAND_REGISTRY
from ante.member.models import Member, MemberRole, MemberStatus, MemberType
from tests.unit.cli.conftest import mock_bot_services_factory

# ── envelope shape predicates (envelopes.md SSOT, account/member 동형) ────

_STANDARD_KEYS = frozenset({"status", "message", "data"})


def _is_standard_envelope(payload: dict[str, Any]) -> bool:
    """``{status: "ok", message, data}`` 3 필수 키가 모두 존재하는지."""
    return (
        isinstance(payload, dict)
        and payload.get("status") == "ok"
        and set(payload.keys()) >= _STANDARD_KEYS
        and isinstance(payload.get("message"), str)
        and isinstance(payload.get("data"), (dict, type(None)))
    )


def _is_raw_legacy_envelope(payload: dict[str, Any]) -> bool:
    """평면 dict 이고 standard envelope 의 3 필수 키 셋이 모두 갖춰져 있지 않다.

    raw_legacy 는 평면 도메인 payload (혹은 IPC envelope passthrough) 를
    그대로 dump 한다. 만약 dict 가 ``{status, message, data}`` 3 키를 동시에
    갖고 ``status == "ok"`` 면 standard envelope 으로 분류된다 (애매한 경계
    방지).
    """
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


def test_registry_bot_entries_envelopes_classified() -> None:
    """bot 11 entry 의 envelope 이 ``standard`` 또는 ``raw_legacy`` 두 값만 사용한다.

    본 단언은 본 모듈 fixture 의 envelope predicate 두 함수가 11 entry 를
    모두 분류할 수 있음을 lock 한다. envelope SSOT (#1821) 에 새 값이
    추가되면 본 분류기를 갱신해야 함을 표면화한다.
    """
    accepted = {"standard", "raw_legacy"}
    bot_entries = [
        (path, contract)
        for path, contract in CLI_COMMAND_REGISTRY.items()
        if path[:1] == ("bot",)
    ]
    assert len(bot_entries) == 11, (
        f"bot 11 entries 가 모두 등록되어야 한다. 실제: {len(bot_entries)}"
    )
    for path, contract in bot_entries:
        assert contract.output.envelope in accepted, (
            f"{path}: registry envelope='{contract.output.envelope}' 가 본 "
            f"drift test 의 분류 범위 ({sorted(accepted)}) 를 벗어남. "
            "envelope SSOT (#1821) 가 새 값을 추가했다면 본 분류기를 갱신하라."
        )


# ── CLI fixture (member drift test 동형) ───────────────────────────────────


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
    """master member 로 인증을 우회한다 (account/member drift test 동형)."""
    with patch(
        "ante.cli.main.authenticate_member",
        side_effect=lambda ctx: ctx.obj.update({"member": _MOCK_MASTER}),
    ):
        yield


def _invoke(args: list[str]):
    """``ante --format json bot ...`` 를 실행하고 결과를 반환한다."""
    from ante.cli.main import cli

    runner = CliRunner()
    env = {"ANTE_MEMBER_TOKEN": ""}
    return runner.invoke(cli, args, env=env, catch_exceptions=False)


def _load_json_payload(output: str) -> dict[str, Any]:
    """CLI ``--format json`` 출력의 첫 JSON 객체를 파싱한다.

    ``OutputFormatter`` 가 ``json.dumps(..., indent=2)`` 로 multi-line dump
    하기 때문에 처음 ``{`` 부터 ``raw_decode`` 로 한 객체를 파싱하고 나머지
    stdout (text 모드 잔존물 등) 는 무시한다 (member drift test 동형).
    """
    text = output.lstrip()
    assert text, f"CLI 출력이 비어 있다: {output!r}"
    start = text.find("{")
    assert start >= 0, f"JSON 객체 시작을 찾을 수 없다: {output!r}"
    decoder = json.JSONDecoder()
    obj, _end = decoder.raw_decode(text[start:])
    return obj


def _make_mock_db(rows_by_query: dict[str, Any] | None = None) -> AsyncMock:
    """``Database`` mock — ``connect`` / ``close`` / ``fetch_*`` async 메서드.

    ``rows_by_query`` 는 ``fetch_all`` / ``fetch_one`` 호출 시 반환할
    *기본* 응답을 dict 로 받는다. 실제 분기별 응답을 세밀하게 제어하려면
    호출자가 mock 객체를 받은 뒤 ``side_effect`` 를 덮어쓰면 된다.
    """
    db = AsyncMock()
    db.connect = AsyncMock()
    db.close = AsyncMock()
    db.fetch_all = AsyncMock(return_value=(rows_by_query or {}).get("fetch_all", []))
    db.fetch_one = AsyncMock(return_value=(rows_by_query or {}).get("fetch_one", None))
    db.execute = AsyncMock()
    return db


@pytest.fixture
def mock_create_services():
    """``ante.cli.commands.bot._create_services`` 를 mock 한다.

    반환값 ``(db, eventbus, manager, account_service)`` 의 4-tuple 을 그대로
    돌려준다. 각 테스트는 yield 받은 ``(db, manager, account_service)`` 의
    mock 메서드 응답을 자체적으로 customize 한다.

    #1900: ``_create_services`` 는 ``@asynccontextmanager`` async ctxmgr 이고
    production callsite 는 ``async with _create_services(ctx=ctx) as (...):``
    형태로 호출한다. plain ``async def`` stub 은 ``ctx=`` kwarg 와 ``async
    with`` lifecycle 둘 다 충족하지 못해 회귀가 발생했다. shared
    ``mock_bot_services_factory`` 헬퍼로 마이그레이션한다.
    """
    db = _make_mock_db()
    eventbus = MagicMock()
    manager = AsyncMock()
    account_service = AsyncMock()

    with patch(
        "ante.cli.commands.bot._create_services",
        new=mock_bot_services_factory(db, eventbus, manager, account_service),
    ):
        yield db, eventbus, manager, account_service


@pytest.fixture
def mock_ipc_send():
    """``ipc_send`` 를 mock 한다 (runtime_ipc 분기 leaf 용).

    각 테스트가 ``mock_ipc.return_value`` 를 설정해 IPC 응답을 customize
    한다. ``bot.py`` 는 ``from ante.cli.commands.ipc_helpers import ipc_send``
    를 함수 내부에서 lazy import 하므로 원본 모듈을 patch 해야 한다.
    """
    with patch("ante.cli.commands.ipc_helpers.ipc_send", new=AsyncMock()) as m:
        yield m


@pytest.fixture
def mock_database_direct():
    """``ante.core.database.Database`` 생성자를 mock 한다 (positions/logs 용).

    ``bot positions`` / ``bot logs`` 는 ``_create_services`` 를 거치지 않고
    ``Database(get_db_path())`` 를 직접 호출하므로 이 fixture 가 별도로
    필요하다.
    """
    db = _make_mock_db()
    with patch("ante.core.database.Database", return_value=db) as cls:
        yield db, cls


# ── 1. bot list (empty / non-empty) → raw_legacy ──────────────────────────


def test_bot_list_empty_envelope_matches_raw_legacy(mock_create_services) -> None:
    """``bot list`` empty: ``{message, bots: []}`` 평면 dict (raw_legacy)."""
    db, _, _, _ = mock_create_services
    db.fetch_all.return_value = []

    result = _invoke(["--format", "json", "bot", "list"])
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_raw_legacy_envelope(payload), (
        f"bot list empty: standard envelope 아니어야 함 (registry "
        f"envelope=raw_legacy 와 정합). 실제 payload={payload!r}"
    )
    assert payload == {"message": "등록된 봇이 없습니다.", "bots": []}


def test_bot_list_non_empty_envelope_matches_raw_legacy(mock_create_services) -> None:
    """``bot list`` non-empty: ``{bots: [...]}`` 평면 dict (raw_legacy)."""
    db, _, _, _ = mock_create_services
    db.fetch_all.return_value = [
        {
            "bot_id": "bot-1",
            "name": "테스트 봇",
            "strategy_id": "strat-1",
            "account_id": "acc-1",
            "status": "stopped",
            "created_at": "2026-01-01T00:00:00",
        }
    ]

    result = _invoke(["--format", "json", "bot", "list"])
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_raw_legacy_envelope(payload), (
        f"bot list non-empty: standard envelope 아니어야 함. payload={payload!r}"
    )
    assert "bots" in payload
    assert isinstance(payload["bots"], list)
    assert len(payload["bots"]) == 1
    assert payload["bots"][0]["bot_id"] == "bot-1"


# ── 2. bot info → raw_legacy ───────────────────────────────────────────────


def test_bot_info_envelope_matches_raw_legacy(mock_create_services) -> None:
    """``bot info``: 평면 detail dict (raw_legacy)."""
    db, _, _, _ = mock_create_services
    db.fetch_one.return_value = {
        "bot_id": "bot-1",
        "name": "테스트 봇",
        "strategy_id": "strat-1",
        "account_id": "acc-1",
        "status": "running",
        "created_at": "2026-01-01T00:00:00",
    }

    result = _invoke(["--format", "json", "bot", "info", "bot-1"])
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_raw_legacy_envelope(payload), (
        f"bot info: standard envelope 아니어야 함. payload={payload!r}"
    )
    assert payload["bot_id"] == "bot-1"
    assert payload["status"] == "running"


# ── 3. bot create → standard ──────────────────────────────────────────────


def test_bot_create_envelope_matches_operation_standard(mock_ipc_send) -> None:
    """``bot create``: 단일 경로 ``fmt.success(message, data)`` → standard."""
    mock_ipc_send.return_value = {
        "bot_id": "bot-1",
        "name": "새 봇",
        "strategy_id": "strat-1",
        "account_id": "acc-1",
        "status": "stopped",
    }

    result = _invoke(
        [
            "--format",
            "json",
            "bot",
            "create",
            "--name",
            "새 봇",
            "--strategy",
            "strat-1",
            "--account",
            "acc-1",
        ]
    )
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_standard_envelope(payload), (
        f"bot create: standard envelope 이어야 함. payload={payload!r}"
    )
    assert "봇 생성 완료" in payload["message"]
    assert payload["data"]["bot_id"] == "bot-1"


# ── 4. bot remove → standard ──────────────────────────────────────────────


def test_bot_remove_envelope_matches_operation_standard(mock_ipc_send) -> None:
    """``bot remove --yes``: 단일 경로 ``fmt.success(message, data)`` → standard.

    runtime IPC 분기 (``is_active_runtime() == True``) 를 사용하기 위해
    ``is_active_runtime`` 도 함께 patch 한다. cold-path fallback shape 는
    동일 ``fmt.success`` 분기이므로 IPC 경로 단언만으로 envelope 분류는
    충분하다 (account ``suspend/activate`` 동형 정책).
    """
    mock_ipc_send.return_value = {
        "removed": True,
        "bot_id": "bot-1",
    }

    with patch("ante.cli.commands.bot.is_active_runtime", return_value=True):
        result = _invoke(
            ["--format", "json", "bot", "remove", "bot-1", "--yes"],
        )
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_standard_envelope(payload), (
        f"bot remove: standard envelope 이어야 함. payload={payload!r}"
    )
    assert "봇 삭제 완료" in payload["message"]
    assert payload["data"]["removed"] is True


# ── 5. bot signal-key (query) → raw_legacy ────────────────────────────────


def test_bot_signal_key_query_envelope_matches_raw_legacy(
    mock_create_services,
) -> None:
    """``bot signal-key`` (no --rotate): ``{bot_id, signal_key}`` 평면 dict.

    bot.py 540-547: 단순 조회 경로는 JSON 모드에서 ``fmt.output(result)`` 로
    평면 dict 를 dump 한다. registry 의 ``raw_legacy`` 정책에 부합.
    """
    db, _, _, _ = mock_create_services
    # bot 존재 + strategy_id 필요 (rotate 게이트용이지만 query 분기도 SELECT)
    db.fetch_one.return_value = {"strategy_id": "strat-1"}

    # SignalKeyManager 의 initialize / get_key 를 mock 한다.
    skm = AsyncMock()
    skm.initialize = AsyncMock()
    skm.get_key = AsyncMock(return_value="sig-key-abc")

    with patch("ante.bot.signal_key.SignalKeyManager", return_value=skm):
        result = _invoke(["--format", "json", "bot", "signal-key", "bot-1"])
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_raw_legacy_envelope(payload), (
        f"bot signal-key query: standard envelope 아니어야 함. payload={payload!r}"
    )
    assert payload["bot_id"] == "bot-1"
    assert payload["signal_key"] == "sig-key-abc"


# ── 6. bot signal-key --rotate → standard (mixed-branch lock) ─────────────


def test_bot_signal_key_rotate_envelope_matches_operation_standard(
    mock_ipc_send,
) -> None:
    """``bot signal-key --rotate``: ``fmt.success(message, data)`` → standard.

    분기 mixed lock — registry 는 raw_legacy 우선이지만 rotate 분기가
    standard envelope 임을 별도 lock 해 분기 mixed 사실을 명시한다
    (account ``set-credentials`` 동형 정책). registry 가 ``raw_legacy`` 우선
    분류임은 query 분기 test 가 lock 한다.

    #2111: rotate 는 runtime IPC (``bot.signal_key.rotate``) 로 라우팅되지만
    출력 계약(standard envelope)은 그대로 보존된다. 본 test 는 (1) rotate 가
    ``bot.signal_key.rotate`` IPC 로 라우팅되는 것과 (2) 출력이 standard
    envelope 인 것을 함께 단언해, 라우팅 변경이 출력-shape 변경이 아님을
    lock 한다.
    """
    mock_ipc_send.return_value = {
        "bot_id": "bot-1",
        "signal_key": "new-sig-key-xyz",
        "rotated": True,
    }

    result = _invoke(["--format", "json", "bot", "signal-key", "bot-1", "--rotate"])
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_standard_envelope(payload), (
        f"bot signal-key --rotate: standard envelope 이어야 함 (분기 mixed). "
        f"payload={payload!r}"
    )
    assert "시그널 키 재발급 완료" in payload["message"]
    assert payload["data"]["signal_key"] == "new-sig-key-xyz"
    assert payload["data"]["rotated"] is True

    # rotate 는 runtime IPC (``bot.signal_key.rotate``) 로 라우팅된다 (#2111).
    mock_ipc_send.assert_awaited_once()
    call_args = mock_ipc_send.await_args
    assert call_args.args[0] == "bot.signal_key.rotate"
    assert call_args.args[1] == {"bot_id": "bot-1"}


# ── 7. bot positions (empty / non-empty) → raw_legacy ─────────────────────


def test_bot_positions_empty_envelope_matches_raw_legacy(
    mock_database_direct,
) -> None:
    """``bot positions`` empty: ``{message, positions: []}`` 평면 dict.

    실재 bot, 0 포지션 분기 (bot.py 622-625) 를 lock 한다. 미존재 bot 분기
    (BOT_NOT_FOUND) 는 success envelope 단언 대상이 아니므로 본 test 의
    책임 밖이다.
    """
    db, _ = mock_database_direct
    # bot 존재 확인 → 실재 (SELECT account_id FROM bots WHERE bot_id = ?).
    # #2137: account_id 스코핑 — valid account_id row 를 반환한다.
    db.fetch_one.return_value = {"account_id": "acc-1"}

    # TradeService.get_positions 가 빈 list 반환하도록 mock.
    trade_service = AsyncMock()
    trade_service.get_positions = AsyncMock(return_value=[])

    # PositionHistory / TradeRecorder / PerformanceTracker initialize 도
    # 호출되므로 stub.
    position_history = AsyncMock()
    position_history.initialize = AsyncMock()
    recorder = AsyncMock()
    recorder.initialize = AsyncMock()

    with (
        patch("ante.trade.position.PositionHistory", return_value=position_history),
        patch("ante.trade.recorder.TradeRecorder", return_value=recorder),
        patch("ante.trade.performance.PerformanceTracker", return_value=AsyncMock()),
        patch("ante.trade.service.TradeService", return_value=trade_service),
    ):
        result = _invoke(["--format", "json", "bot", "positions", "bot-1"])
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_raw_legacy_envelope(payload), (
        f"bot positions empty: standard envelope 아니어야 함. payload={payload!r}"
    )
    assert payload == {"message": "보유 포지션 없음", "positions": []}


def test_bot_positions_non_empty_envelope_matches_raw_legacy(
    mock_database_direct,
) -> None:
    """``bot positions`` non-empty: ``{positions: [...]}`` 평면 dict."""
    db, _ = mock_database_direct
    # #2137: account_id 스코핑 — valid account_id row 를 반환한다.
    db.fetch_one.return_value = {"account_id": "acc-1"}

    # Position dataclass 같은 객체 mock.
    pos = MagicMock()
    pos.symbol = "AAPL"
    pos.quantity = 10.0
    pos.avg_entry_price = 150.0
    pos.realized_pnl = 5.0

    trade_service = AsyncMock()
    trade_service.get_positions = AsyncMock(return_value=[pos])

    position_history = AsyncMock()
    position_history.initialize = AsyncMock()
    recorder = AsyncMock()
    recorder.initialize = AsyncMock()

    with (
        patch("ante.trade.position.PositionHistory", return_value=position_history),
        patch("ante.trade.recorder.TradeRecorder", return_value=recorder),
        patch("ante.trade.performance.PerformanceTracker", return_value=AsyncMock()),
        patch("ante.trade.service.TradeService", return_value=trade_service),
    ):
        result = _invoke(["--format", "json", "bot", "positions", "bot-1"])
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_raw_legacy_envelope(payload), (
        f"bot positions non-empty: standard envelope 아니어야 함. payload={payload!r}"
    )
    assert "positions" in payload
    assert len(payload["positions"]) == 1
    assert payload["positions"][0]["symbol"] == "AAPL"


# ── 8. bot update → raw_legacy ────────────────────────────────────────────


def test_bot_update_envelope_matches_raw_legacy(mock_ipc_send) -> None:
    """``bot update``: JSON 모드 ``fmt.output(result)`` 평면 dict (raw_legacy).

    bot.py 716-717: JSON 모드는 IPC 응답을 그대로 dump. text 는 click.echo.
    registry 의 ``raw_legacy`` 정책에 부합.
    """
    mock_ipc_send.return_value = {
        "bot_id": "bot-1",
        "updates": {"name": "새 이름"},
    }

    result = _invoke(
        [
            "--format",
            "json",
            "bot",
            "update",
            "bot-1",
            "--name",
            "새 이름",
        ]
    )
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_raw_legacy_envelope(payload), (
        f"bot update: standard envelope 아니어야 함. payload={payload!r}"
    )
    assert payload["bot_id"] == "bot-1"


# ── 9. bot logs → raw_legacy ──────────────────────────────────────────────


def test_bot_logs_envelope_matches_raw_legacy(mock_database_direct) -> None:
    """``bot logs``: JSON 모드 ``fmt.output(result)`` 평면 ``{bot_id, logs, total}``.

    bot.py 836-837: JSON 모드는 평면 dict 를 dump. text 는 fmt.table 또는
    "(logs 없음)". registry 의 ``raw_legacy`` 정책에 부합.
    """
    db, _ = mock_database_direct
    db.fetch_one.return_value = {"1": 1}  # bot 존재

    # EventHistoryStore.query / count mock.
    store = AsyncMock()
    store.initialize = AsyncMock()
    store.query = AsyncMock(
        return_value=[
            {
                "event_id": "evt-1",
                "timestamp": "2026-01-01T00:00:00",
                "payload": {"result": "ok", "message": "step 완료"},
            }
        ]
    )
    store.count = AsyncMock(return_value=1)

    with patch("ante.eventbus.history.EventHistoryStore", return_value=store):
        result = _invoke(["--format", "json", "bot", "logs", "bot-1"])
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_raw_legacy_envelope(payload), (
        f"bot logs: standard envelope 아니어야 함. payload={payload!r}"
    )
    assert payload["bot_id"] == "bot-1"
    assert payload["total"] == 1
    assert isinstance(payload["logs"], list)
    assert payload["logs"][0]["event_id"] == "evt-1"


# ── 10. bot start → raw_legacy (IPC envelope passthrough) ─────────────────


def test_bot_start_envelope_matches_raw_legacy(mock_ipc_send) -> None:
    """``bot start``: JSON 모드 IPC ``{bot: ...}`` envelope passthrough.

    bot.py 887-888: JSON 모드는 IPC 응답을 ``fmt.output(result)`` 로 그대로
    dump (``fmt.success`` wrapping 없음 — feedback_cli_json_envelope_
    passthrough 메모 정책). registry 의 ``raw_legacy`` 정책에 부합.
    """
    mock_ipc_send.return_value = {
        "bot": {
            "bot_id": "bot-1",
            "status": "running",
            "name": "테스트 봇",
        }
    }

    result = _invoke(["--format", "json", "bot", "start", "bot-1"])
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_raw_legacy_envelope(payload), (
        f"bot start: standard envelope 아니어야 함 (IPC passthrough). "
        f"payload={payload!r}"
    )
    assert payload["bot"]["bot_id"] == "bot-1"
    assert payload["bot"]["status"] == "running"


# ── 11. bot stop → raw_legacy (IPC envelope passthrough) ──────────────────


def test_bot_stop_envelope_matches_raw_legacy(mock_ipc_send) -> None:
    """``bot stop``: JSON 모드 IPC envelope passthrough."""
    mock_ipc_send.return_value = {
        "bot": {
            "bot_id": "bot-1",
            "status": "stopped",
        }
    }

    result = _invoke(["--format", "json", "bot", "stop", "bot-1"])
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_raw_legacy_envelope(payload), (
        f"bot stop: standard envelope 아니어야 함 (IPC passthrough). "
        f"payload={payload!r}"
    )
    assert payload["bot"]["bot_id"] == "bot-1"
    assert payload["bot"]["status"] == "stopped"


# ── 12. bot status → raw_legacy (IPC envelope passthrough) ────────────────


def test_bot_status_envelope_matches_raw_legacy(mock_ipc_send) -> None:
    """``bot status``: JSON 모드 IPC ``{bot: ...}`` envelope passthrough.

    bot.py 962-963: JSON 모드는 IPC 응답을 ``fmt.output(result)`` 로 그대로
    dump. text 모드는 click.echo detail. registry 의 ``raw_legacy`` 정책에
    부합.
    """
    mock_ipc_send.return_value = {
        "bot": {
            "bot_id": "bot-1",
            "name": "테스트 봇",
            "status": "running",
            "account_id": "acc-1",
            "strategy_id": "strat-1",
        }
    }

    result = _invoke(["--format", "json", "bot", "status", "bot-1"])
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_raw_legacy_envelope(payload), (
        f"bot status: standard envelope 아니어야 함 (IPC passthrough). "
        f"payload={payload!r}"
    )
    assert payload["bot"]["bot_id"] == "bot-1"
