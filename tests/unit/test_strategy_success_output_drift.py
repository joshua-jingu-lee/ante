"""Strategy CLI success output ↔ registry OutputContract drift lock (#1847 sub-PR 5).

본 모듈은 :data:`ante.contracts.cli_registry.CLI_COMMAND_REGISTRY` 에 등록된
strategy 도메인 7 leaf 의 ``OutputContract`` 와 ``ante strategy ... --format
json`` 실제 출력 envelope shape 사이의 drift 를 lock 한다.

#1846 (account) / #1847 sub-PR 1 (member) / #1847 sub-PR 2 (bot) / #1847
sub-PR 3 (approval) / #1847 sub-PR 4 (treasury) 1:1 동형 패턴. drift 모델:

- ``envelope="standard"`` entry → CLI success envelope ``{status, message,
  data}`` (envelopes.md SSOT). ``fmt.success(...)`` callsite 가 dump 한다.
- ``envelope="raw_legacy"`` entry → JSON mode 에서 ``fmt.output(...)`` 으로
  평면 dict 를 그대로 dump 한다 (``status`` / ``message`` / ``data`` 3 키
  모두 동시에 부재 또는 ``status != "ok"``).

본 PR 은 ``strategy.py`` 본문을 *바꾸지 않으며*, registry entry 가 실제
callsite shape 와 일치함을 단순 lock 만 한다. callsite shape 가 drift 하면
본 test 가 즉시 FAIL 한다 (registry 갱신 또는 callsite 정렬 중 한쪽이 책임).

10 시나리오 (7 leaf + registry sanity +1 + list empty 분기 +1 + summary
empty JSON 분기 +1):

0. registry sanity — strategy 7 entries 의 envelope 이 ``standard`` /
   ``raw_legacy`` 분류 범위 내.
1. ``validate`` (valid 분기) → ``standard`` (``fmt.success(message, data)``)
2. ``submit`` (성공 register) → ``raw_legacy`` (``fmt.output(result)`` 평면
   ``{submitted: True, strategy_id, ...}``)
3. ``list`` empty → ``raw_legacy`` (``{message, strategies: []}``)
4. ``list`` non-empty → ``raw_legacy`` (``{strategies: [...]}``)
5. ``info`` (found) → ``raw_legacy`` (``fmt.output(result)`` 평면 metadata
   + params dict)
6. ``summary`` (with items) → ``raw_legacy`` (``fmt.output(result)`` 평면
   ``{strategy_id, period, bot_id, items}``)
7. ``summary`` empty JSON 분기 → ``raw_legacy`` (``fmt.output(result)``
   동일 평면 ``{strategy_id, period, bot_id, items: []}``)
8. ``performance`` (found) → ``raw_legacy`` (``fmt.output(result)`` 평면
   ``{strategy_name, strategy_id, metrics}``)
9. ``set-status`` (IPC 분기) → ``raw_legacy`` (``fmt.output(result)`` 평면
   ``{strategy_id, status, name, version}``)
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
from ante.strategy.registry import StrategyRecord, StrategyStatus
from ante.strategy.validator import ValidationResult
from ante.trade.models import PerformanceMetrics
from tests.unit.cli.conftest import mock_strategy_registry_factory

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

    raw_legacy 는 ``fmt.output(dict)`` 출력의 super-set 이다. ``status``/
    ``message``/``data`` 3 키가 동시에 갖춰지고 ``status == "ok"`` 면
    standard envelope 으로 분류 (애매한 경계 방지). 그렇지 않으면 모든
    평면 도메인 payload 는 raw_legacy.
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


def test_registry_strategy_entries_envelopes_classified() -> None:
    """strategy 7 entry 의 envelope 이 ``standard`` 또는 ``raw_legacy`` 만 사용.

    본 단언은 본 모듈 fixture 의 envelope predicate 두 함수가 7 entry 를
    모두 분류할 수 있음을 lock 한다. envelope SSOT (#1821) 에 새 값이
    추가되면 본 분류기를 갱신해야 함을 표면화한다.
    """
    accepted = {"standard", "raw_legacy"}
    strategy_entries = [
        (path, contract)
        for path, contract in CLI_COMMAND_REGISTRY.items()
        if path[:1] == ("strategy",)
    ]
    assert len(strategy_entries) == 7, (
        f"strategy 7 entries 가 모두 등록되어야 한다. 실제: {len(strategy_entries)}"
    )
    for path, contract in strategy_entries:
        assert contract.output.envelope in accepted, (
            f"{path}: registry envelope='{contract.output.envelope}' 가 본 "
            f"drift test 의 분류 범위 ({sorted(accepted)}) 를 벗어남. "
            "envelope SSOT (#1821) 가 새 값을 추가했다면 본 분류기를 갱신하라."
        )


# ── CLI fixture (account/member/bot/approval/treasury drift test 동형) ──────


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
    """master member 로 인증 우회 (account/member/bot/approval/treasury 동형)."""
    with patch(
        "ante.cli.main.authenticate_member",
        side_effect=lambda ctx: ctx.obj.update({"member": _MOCK_MASTER}),
    ):
        yield


def _invoke(args: list[str]):
    """``ante --format json strategy ...`` 를 실행하고 결과를 반환한다."""
    from ante.cli.main import cli

    runner = CliRunner()
    env = {"ANTE_MEMBER_TOKEN": ""}
    return runner.invoke(cli, args, env=env, catch_exceptions=False)


def _load_json_payload(output: str) -> Any:
    """CLI ``--format json`` 출력의 첫 JSON value 를 파싱한다.

    ``OutputFormatter`` 가 ``json.dumps(..., indent=2)`` 로 multi-line dump
    하기 때문에 처음 ``{`` 또는 ``[`` 부터 ``raw_decode`` 로 한 value 를
    파싱하고 나머지 stdout (text 모드 잔존물 등) 는 무시한다 (treasury
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


# ── fixture: mock StrategyRegistry + Database (offline path) ───────────────


def _make_record(
    *,
    strategy_id: str = "strat-1",
    name: str = "my_strategy",
    version: str = "1.0.0",
    status: StrategyStatus = StrategyStatus.REGISTERED,
) -> StrategyRecord:
    """테스트용 ``StrategyRecord`` factory."""
    return StrategyRecord(
        strategy_id=strategy_id,
        name=name,
        version=version,
        filepath="/tmp/nonexistent_strategy.py",
        status=status,
        registered_at=datetime(2026, 1, 1, tzinfo=UTC),
        description="테스트 전략",
        author_name="agent",
        author_id="agent",
        validation_warnings=[],
    )


@pytest.fixture
def mock_create_registry():
    """``strategy._create_registry`` 를 patch — ``(registry_mock, db_mock)`` 반환.

    strategy.py 의 ``list`` / ``set-status`` (cold_path 분기) / ``info`` /
    ``summary`` / ``submit`` (register) 가 사용한다. ``performance`` 는 자체
    ``Database`` + ``StrategyRegistry`` 를 직접 생성하므로 별도 fixture 가
    필요하다.

    #1900: production ``_create_registry`` 는 ``@asynccontextmanager`` 이며
    ``async with _create_registry(ctx=ctx) as (registry, db):`` 형태로 호출된다.
    ``async def _stub_create()`` 는 ``ctx=`` kwarg 도 받지 못하고 ``async with``
    lifecycle 도 모사하지 못해 회귀(A 동형)가 발생했다. shared
    ``mock_strategy_registry_factory`` helper 로 마이그레이션.
    """
    registry = AsyncMock()
    db = AsyncMock()
    db.connect = AsyncMock()
    db.close = AsyncMock()
    db.fetch_one = AsyncMock(return_value=None)
    db.fetch_all = AsyncMock(return_value=[])
    registry.initialize = AsyncMock()

    with patch(
        "ante.cli.commands.strategy._create_registry",
        new=mock_strategy_registry_factory(registry, db),
    ):
        yield registry, db


# ── 1. validate (valid) → standard ─────────────────────────────────────────


def test_strategy_validate_valid_envelope_matches_operation_standard(tmp_path) -> None:
    """``strategy validate``: valid 분기는 ``fmt.success(message, data)`` → standard.

    strategy.py:86: ``fmt.success(f"Strategy validation passed: ...", data)``
    분기. invalid 분기는 별도 ``fmt.error`` / ``fmt.output({"status": "error",
    ...})`` 이지만 본 drift test 의 success-output scope 밖.
    """
    fake_path = tmp_path / "strat.py"
    fake_path.write_text("# stub\n", encoding="utf-8")

    valid_result = ValidationResult(valid=True, errors=[], warnings=[])
    with patch(
        "ante.strategy.validator.StrategyValidator.validate",
        return_value=valid_result,
    ):
        result = _invoke(["--format", "json", "strategy", "validate", str(fake_path)])
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_standard_envelope(payload), (
        f"strategy validate: standard envelope 이어야 함. payload={payload!r}"
    )
    assert "validation passed" in payload["message"].lower()
    assert payload["data"]["valid"] is True


# ── 2. submit (success register) → raw_legacy ──────────────────────────────


def test_strategy_submit_success_envelope_matches_raw_legacy(
    tmp_path, mock_create_registry
) -> None:
    """``strategy submit``: 성공 시 JSON 모드 ``fmt.output(result)`` 평면.

    strategy.py:276-277: ``if fmt.is_json: fmt.output(result)`` 평면
    ``{submitted: True, strategy_id, name, version, description, author_name,
    author_id, filepath, registered_at, validation_warnings}``. text 모드는
    ``fmt.success`` 분기지만 JSON 모드는 raw_legacy.
    """
    fake_path = tmp_path / "strat.py"
    fake_path.write_text("# stub\n", encoding="utf-8")

    registry, _db = mock_create_registry
    record = _make_record()
    registry.register = AsyncMock(return_value=record)

    # ValidationResult.valid=True 와 StrategyLoader 가 dummy class 반환을 mock.
    valid_result = ValidationResult(valid=True, errors=[], warnings=[])

    # dummy Strategy class 와 meta (실제 StrategyMeta 인스턴스가 필요).
    from ante.strategy.base import StrategyMeta

    fake_meta = StrategyMeta(
        name="my_strategy",
        version="1.0.0",
        description="테스트 전략",
        author_name="agent",
        author_id="agent",
    )

    class _FakeStrategy:
        meta = fake_meta

        def __init__(self, ctx):
            pass

        def get_rationale(self):
            return ""

        def get_risks(self):
            return []

    with (
        patch(
            "ante.strategy.validator.StrategyValidator.validate",
            return_value=valid_result,
        ),
        patch(
            "ante.strategy.loader.StrategyLoader.load",
            return_value=_FakeStrategy,
        ),
    ):
        result = _invoke(["--format", "json", "strategy", "submit", str(fake_path)])
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_raw_legacy_payload(payload), (
        f"strategy submit success: standard envelope 아님. payload={payload!r}"
    )
    assert payload["submitted"] is True
    assert payload["strategy_id"] == "strat-1"
    assert payload["name"] == "my_strategy"
    assert payload["version"] == "1.0.0"


# ── 3. list empty → raw_legacy ─────────────────────────────────────────────


def test_strategy_list_empty_envelope_matches_raw_legacy(mock_create_registry) -> None:
    """``strategy list`` empty: ``{message, strategies: []}`` 평면 (raw_legacy).

    strategy.py:352: ``fmt.output({"message": "등록된 전략 없음", "strategies":
    []})`` 분기. text/JSON 양쪽 모두 본 평면 dict 를 echo (`fmt.output` 내부
    branch). 정확히 JSON 모드를 단언한다.
    """
    registry, _db = mock_create_registry
    registry.list_strategies = AsyncMock(return_value=[])

    result = _invoke(["--format", "json", "strategy", "list"])
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_raw_legacy_payload(payload), (
        f"strategy list empty: standard envelope 아님. payload={payload!r}"
    )
    assert payload == {"message": "등록된 전략 없음", "strategies": []}


# ── 4. list non-empty → raw_legacy ─────────────────────────────────────────


def test_strategy_list_non_empty_envelope_matches_raw_legacy(
    mock_create_registry,
) -> None:
    """``strategy list`` non-empty: ``{strategies: [...]}`` 평면 (raw_legacy).

    strategy.py:355-356: ``if fmt.is_json: fmt.output({"strategies": rows})``.
    """
    registry, _db = mock_create_registry
    registry.list_strategies = AsyncMock(return_value=[_make_record()])

    result = _invoke(["--format", "json", "strategy", "list"])
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_raw_legacy_payload(payload), (
        f"strategy list non-empty: standard envelope 아님. payload={payload!r}"
    )
    assert "strategies" in payload
    assert isinstance(payload["strategies"], list)
    assert payload["strategies"][0]["strategy_id"] == "strat-1"
    assert payload["strategies"][0]["status"] == "registered"


# ── 5. info (found) → raw_legacy ───────────────────────────────────────────


def test_strategy_info_found_envelope_matches_raw_legacy(mock_create_registry) -> None:
    """``strategy info`` 발견: ``fmt.output(result)`` 평면 metadata dict.

    strategy.py:512-513: ``if fmt.is_json: fmt.output(result)`` → ``{strategy_id,
    name, version, status, description, author_name, author_id, filepath,
    registered_at, validation_warnings, ...}``. ``params`` / ``param_schema``
    는 ``_load_strategy_params`` 가 ``filepath`` 부재로 ``None`` 일 때 생략.
    """
    registry, _db = mock_create_registry
    record = _make_record(name="my_strategy")
    registry.get_by_name = AsyncMock(return_value=[record])

    result = _invoke(["--format", "json", "strategy", "info", "my_strategy"])
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_raw_legacy_payload(payload), (
        f"strategy info: standard envelope 아님. payload={payload!r}"
    )
    assert payload["name"] == "my_strategy"
    assert payload["strategy_id"] == "strat-1"
    assert payload["status"] == "registered"


# ── 6. summary (with items) → raw_legacy ───────────────────────────────────


def test_strategy_summary_with_items_envelope_matches_raw_legacy(
    mock_create_registry,
) -> None:
    """``strategy summary`` with items: ``fmt.output(result)`` 평면 dict.

    strategy.py:662-663: ``if fmt.is_json: fmt.output(result)`` → ``{strategy_id,
    period, bot_id, items: [...]}``. text 모드는 fmt.table 분기.
    """
    from ante.trade.models import DailySummary

    registry, _db = mock_create_registry
    record = _make_record()
    registry.get = AsyncMock(return_value=record)

    # _find_bot_id_for_strategy 는 db.fetch_one 을 호출한다.
    # mock_create_registry fixture 의 db 가 default 로 ``None`` 을 반환하지만,
    # 본 케이스에서 bot_id 가 있는 결과를 보고 싶다면 fetch_one 을 customize.
    _db.fetch_one = AsyncMock(return_value={"bot_id": "bot-1"})

    daily = DailySummary(
        date="2026-01-01",
        realized_pnl=10_000.0,
        trade_count=3,
        win_rate=0.67,
    )

    # PerformanceTracker.get_daily_summary 를 mock.
    with patch(
        "ante.trade.performance.PerformanceTracker.get_daily_summary",
        new=AsyncMock(return_value=[daily]),
    ):
        result = _invoke(
            ["--format", "json", "strategy", "summary", "strat-1", "--period", "daily"]
        )
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_raw_legacy_payload(payload), (
        f"strategy summary with items: standard envelope 아님. payload={payload!r}"
    )
    assert payload["strategy_id"] == "strat-1"
    assert payload["period"] == "daily"
    assert payload["bot_id"] == "bot-1"
    assert isinstance(payload["items"], list)
    assert len(payload["items"]) == 1
    assert payload["items"][0]["date"] == "2026-01-01"


# ── 7. summary empty JSON 분기 → raw_legacy ────────────────────────────────


def test_strategy_summary_empty_json_envelope_matches_raw_legacy(
    mock_create_registry,
) -> None:
    """``strategy summary`` JSON 모드 empty items: ``fmt.output(result)`` 평면.

    JSON 모드는 line 662 의 ``fmt.output(result)`` 로 평면 dict 를 그대로
    dump 한다 (items 가 비어도 동일 평면). text 모드 분기 (line 665-668) 의
    ``fmt.output({"message": "성과 집계 없음", "items": []})`` 는 별도
    분기지만 JSON 모드 entry 와는 무관 (`fmt.is_json:` 가 먼저 true).
    """
    registry, _db = mock_create_registry
    record = _make_record()
    registry.get = AsyncMock(return_value=record)
    _db.fetch_one = AsyncMock(return_value=None)  # bot_id 부재 → None.

    # PerformanceTracker.get_daily_summary 가 빈 list 반환.
    with patch(
        "ante.trade.performance.PerformanceTracker.get_daily_summary",
        new=AsyncMock(return_value=[]),
    ):
        result = _invoke(
            ["--format", "json", "strategy", "summary", "strat-1", "--period", "daily"]
        )
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_raw_legacy_payload(payload), (
        f"strategy summary empty json: standard envelope 아님. payload={payload!r}"
    )
    assert payload["strategy_id"] == "strat-1"
    assert payload["bot_id"] is None
    assert payload["items"] == []


# ── 8. performance (found) → raw_legacy ────────────────────────────────────


def test_strategy_performance_found_envelope_matches_raw_legacy() -> None:
    """``strategy performance`` (found): ``fmt.output(result)`` 평면 dict.

    strategy.py:807-808: ``if fmt.is_json: fmt.output(result)`` → ``{strategy_name,
    strategy_id, metrics: {...}}``. ``performance`` 는 ``_create_registry`` 를
    사용하지 않고 자체 ``Database`` + ``StrategyRegistry`` 를 만든다 — 그래서
    ``Database`` 클래스를 직접 patch 한다.
    """
    record = _make_record(name="my_strategy")

    # Database mock (account 존재 확인 쿼리 + close).
    db = AsyncMock()
    db.connect = AsyncMock()
    db.close = AsyncMock()
    db.fetch_one = AsyncMock(return_value={"1": 1})  # accounts 존재.
    db.fetch_all = AsyncMock(return_value=[])
    db.execute = AsyncMock()

    metrics = PerformanceMetrics(
        total_trades=10,
        winning_trades=6,
        losing_trades=4,
        win_rate=0.6,
        total_pnl=100_000.0,
        total_commission=1_000.0,
        net_pnl=99_000.0,
        avg_profit=20_000.0,
        avg_loss=5_000.0,
        profit_factor=4.0,
        max_drawdown=0.05,
        max_drawdown_amount=5_000.0,
        sharpe_ratio=None,
        first_trade_at=None,
        last_trade_at=None,
        active_days=5,
    )

    # StrategyRegistry.get_by_name 와 PerformanceTracker.calculate 를 mock.
    with (
        patch("ante.core.database.Database", return_value=db),
        patch(
            "ante.strategy.registry.StrategyRegistry.initialize",
            new=AsyncMock(),
        ),
        patch(
            "ante.strategy.registry.StrategyRegistry.get_by_name",
            new=AsyncMock(return_value=[record]),
        ),
        patch(
            "ante.trade.performance.PerformanceTracker.calculate",
            new=AsyncMock(return_value=metrics),
        ),
    ):
        result = _invoke(
            [
                "--format",
                "json",
                "strategy",
                "performance",
                "my_strategy",
                "--account-id",
                "acc-1",
            ]
        )
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_raw_legacy_payload(payload), (
        f"strategy performance: standard envelope 아님. payload={payload!r}"
    )
    assert payload["strategy_name"] == "my_strategy"
    assert payload["strategy_id"] == "strat-1"
    assert "metrics" in payload
    assert payload["metrics"]["total_trades"] == 10
    assert payload["metrics"]["win_rate"] == 0.6


# ── 9. set-status (IPC 분기) → raw_legacy ──────────────────────────────────


def test_strategy_set_status_ipc_envelope_matches_raw_legacy() -> None:
    """``strategy set-status`` (runtime IPC 분기): ``fmt.output(result)`` 평면.

    strategy.py:425-426: ``if fmt.is_json: fmt.output(result)`` → IPC 응답
    평면 dict (``{strategy_id, status, name, version}`` 또는 IPC handler 가
    돌려준 임의 평면). spec 은 runtime IPC primary 이며 cold_path fallback
    분기는 본 케이스에서 비활성화 (``is_active_runtime() == True`` 강제).

    treasury ``set-balance`` / account ``set-credentials`` 동형 raw_legacy
    정책 — IPC 응답을 wrapping 없이 그대로 dump.
    """
    ipc_response = {
        "strategy_id": "strat-1",
        "status": "adopted",
        "name": "my_strategy",
        "version": "1.0.0",
    }

    with (
        patch("ante.cli.cold_path.is_active_runtime", return_value=True),
        patch(
            "ante.cli.commands.ipc_helpers.ipc_send",
            new=AsyncMock(return_value=ipc_response),
        ),
    ):
        result = _invoke(
            [
                "--format",
                "json",
                "strategy",
                "set-status",
                "strat-1",
                "--status",
                "adopted",
            ]
        )
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_raw_legacy_payload(payload), (
        f"strategy set-status: standard envelope 아님. payload={payload!r}"
    )
    assert payload["strategy_id"] == "strat-1"
    assert payload["status"] == "adopted"
    assert payload["name"] == "my_strategy"
