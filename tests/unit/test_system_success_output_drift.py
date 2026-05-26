"""System CLI success output ↔ registry OutputContract drift lock (#1847 sub-PR 7).

본 모듈은 :data:`ante.contracts.cli_registry.CLI_COMMAND_REGISTRY` 에 등록된
system 도메인 5 leaf 의 ``OutputContract`` 와 ``ante system ... --format json``
실제 출력 envelope shape 사이의 drift 를 lock 한다.

#1846 (account) / #1847 sub-PR 1 (member) / sub-PR 2 (bot) / sub-PR 3
(approval) / sub-PR 4 (treasury) / sub-PR 5 (strategy) / sub-PR 6 (data /
report) / sub-PR 7 (broker) 1:1 동형 패턴. drift 모델:

- ``envelope="standard"`` entry → CLI success envelope ``{status, message,
  data}`` (envelopes.md SSOT). ``fmt.success(...)`` callsite 가 dump 한다.
- ``envelope="raw_legacy"`` entry → JSON mode 에서 ``fmt.output(...)`` 또는
  ``fmt.table(...)`` 으로 평면 dict 또는 row list 를 그대로 dump 한다
  (standard envelope 의 3 필수 키 셋이 동시에 부재 또는 ``status != "ok"``).

본 PR 은 ``system.py`` 본문을 *바꾸지 않으며*, registry entry 가 실제 callsite
shape 와 일치함을 단순 lock 만 한다. callsite shape 가 drift 하면 본 test 가
즉시 FAIL 한다 (registry 갱신 또는 callsite 정렬 중 한쪽이 책임).

system.py 특이사항:

- ``start`` 는 ``fmt.success("시스템 시작 중...")`` 후 ``subprocess.run`` 으로
  자식 ``python -m ante.main`` 을 실행하고 ``SystemExit(proc.returncode)`` 한다.
  본 fixture 는 ``subprocess.run`` 을 mock 해 자식 실행을 건너뛰고 returncode 0
  으로 만든 뒤 success envelope 만 단언한다.
- ``stop`` 은 PID 파일 + ``os.kill(pid, SIGTERM)`` 을 호출한다. 본 fixture 는
  ``read_pid_file`` / ``_is_process_alive`` / ``os.kill`` 을 mock 해 success
  분기를 강제한다.
- ``status`` 는 로컬 DB 와 AccountService 를 직접 사용한다. 본 fixture 는
  DB / AccountService 를 mock 한다.
- ``halt`` / ``clear-halt`` 는 ``ipc_send`` 호출 결과를 wrapping 한다 — IPC
  response 를 mock 한다.

6 시나리오 (5 leaf + registry sanity +1):

0. registry sanity — system 5 entries 의 envelope 이 ``standard`` /
   ``raw_legacy`` 분류 범위 내.
1. ``start`` → ``standard`` (``fmt.success("시스템 시작 중...")``)
2. ``stop`` → ``standard`` (``fmt.success(..., {"pid": pid})``)
3. ``status`` → ``raw_legacy`` (``fmt.output({trading_state, bot_count})``)
4. ``halt`` → ``standard`` (``fmt.success(f"...", data)``)
5. ``clear-halt`` → ``standard`` (``fmt.success(f"...", data)``)
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from ante.contracts.cli_registry import CLI_COMMAND_REGISTRY
from ante.member.models import Member, MemberRole, MemberStatus, MemberType

# ── envelope shape predicates (envelopes.md SSOT, 동형 정책) ───────────────

_STANDARD_KEYS = frozenset({"status", "message", "data"})


def _is_standard_envelope(payload: Any) -> bool:
    """``{status: "ok", message, data}`` 3 필수 키가 모두 존재하는지.

    ``data`` 슬롯은 dict (``{}``, ``{pid: ...}`` 등) 또는 ``None`` 모두 허용.
    ``OutputFormatter.success`` 가 ``data=None`` 입력을 ``{}`` 으로
    normalize 하므로 실제 출력은 dict 다.
    """
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


def test_registry_system_entries_envelopes_classified() -> None:
    """system 5 entry 의 envelope 이 ``standard`` 또는 ``raw_legacy`` 만 사용.

    본 단언은 본 모듈 fixture 의 envelope predicate 두 함수가 5 entry 를
    모두 분류할 수 있음을 lock 한다. envelope SSOT (#1821) 에 새 값이
    추가되면 본 분류기를 갱신해야 함을 표면화한다.
    """
    accepted = {"standard", "raw_legacy"}
    system_entries = [
        (path, contract)
        for path, contract in CLI_COMMAND_REGISTRY.items()
        if path[:1] == ("system",)
    ]
    assert len(system_entries) == 5, (
        f"system 5 entries 가 모두 등록되어야 한다. 실제: {len(system_entries)}"
    )
    for path, contract in system_entries:
        assert contract.output.envelope in accepted, (
            f"{path}: registry envelope='{contract.output.envelope}' 가 본 "
            f"drift test 의 분류 범위 ({sorted(accepted)}) 를 벗어남. "
            "envelope SSOT (#1821) 가 새 값을 추가했다면 본 분류기를 갱신하라."
        )


# ── CLI fixture (account/member/bot/approval/treasury/strategy/data/report/
#                broker 동형) ──


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
    """``ante --format json system ...`` 를 실행하고 결과를 반환한다."""
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


# ── 1. start → standard ────────────────────────────────────────────────────


def test_system_start_envelope_matches_operation_standard(tmp_path) -> None:
    """``system start``: ``fmt.success("시스템 시작 중...")`` → standard envelope.

    system.py:94: ``fmt.success("시스템 시작 중...")`` — data 인자 없음.
    ``OutputFormatter.success`` 가 ``data=None`` → ``{}`` 으로 normalize 한다
    (formatter.py:93). JSON 모드 dump: ``{status:"ok", message:"시스템 시작
    중...", data: {}}``.

    이후 ``subprocess.run`` 으로 자식 ``python -m ante.main`` 을 실행하고
    ``SystemExit(proc.returncode)`` 한다. 본 fixture 는 ``subprocess.run`` 을
    mock 해 자식 실행을 건너뛰고 returncode 0 으로 만든다. ``read_pid_file``
    는 None (실행 중인 인스턴스 없음) 으로 mock 한다.
    """
    mock_proc = MagicMock()
    mock_proc.returncode = 0

    with (
        patch("ante.main.read_pid_file", return_value=None),
        patch("subprocess.run", return_value=mock_proc) as run_mock,
    ):
        result = _invoke(
            [
                "--format",
                "json",
                "system",
                "start",
                "--config-dir",
                str(tmp_path),
            ]
        )

    # ``SystemExit(0)`` 후 exit_code 0.
    assert result.exit_code == 0, result.output
    # subprocess.run 이 mock 되어 실제 자식 spawn 은 일어나지 않는다.
    run_mock.assert_called_once()

    payload = _load_json_payload(result.output)
    assert _is_standard_envelope(payload), (
        f"system start: standard envelope 이어야 함. payload={payload!r}"
    )
    assert payload["message"] == "시스템 시작 중..."
    # data 슬롯은 빈 dict.
    assert payload["data"] == {}


# ── 2. stop → standard ─────────────────────────────────────────────────────


def test_system_stop_envelope_matches_operation_standard(tmp_path) -> None:
    """``system stop``: ``fmt.success("종료 시그널 전송 완료", {"pid": pid})`` →
    standard envelope.

    system.py:152: ``fmt.success("종료 시그널 전송 완료", {"pid": pid})``.
    """
    fake_pid = 12345
    with (
        patch("ante.main.read_pid_file", return_value=fake_pid),
        patch(
            "ante.cli.commands.system._is_process_alive",
            return_value=True,
        ),
        patch("ante.cli.commands.system.os.kill") as kill_mock,
    ):
        result = _invoke(
            [
                "--format",
                "json",
                "--config-dir",
                str(tmp_path),
                "system",
                "stop",
            ]
        )
    assert result.exit_code == 0, result.output
    kill_mock.assert_called_once()

    payload = _load_json_payload(result.output)
    assert _is_standard_envelope(payload), (
        f"system stop: standard envelope 이어야 함. payload={payload!r}"
    )
    assert "종료 시그널" in payload["message"]
    assert payload["data"] == {"pid": fake_pid}


# ── 3. status → raw_legacy ─────────────────────────────────────────────────


def test_system_status_envelope_matches_raw_legacy() -> None:
    """``system status``: JSON 모드 ``fmt.output(result)`` → raw_legacy.

    system.py:203: ``if fmt.is_json: fmt.output(result)`` → ``{trading_state,
    bot_count}`` 평면 dict. text 모드는 click.echo 2 줄.

    fixture: AccountService.list + Database.fetch_one 을 mock 한다.
    """
    from ante.account.models import Account, AccountStatus, TradingMode

    fake_account = Account(
        account_id="acct-1",
        name="Test Account",
        exchange="KRX",
        currency="KRW",
        trading_mode=TradingMode.VIRTUAL,
        broker_type="test",
        status=AccountStatus.ACTIVE,
    )
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
            "ante.account.service.AccountService.initialize",
            new=AsyncMock(),
        ),
        patch(
            "ante.account.service.AccountService.list",
            new=AsyncMock(return_value=[fake_account]),
        ),
        patch(
            "ante.core.database.Database.fetch_one",
            new=AsyncMock(return_value={"cnt": 3}),
        ),
    ):
        result = _invoke(["--format", "json", "system", "status"])
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_raw_legacy_payload(payload), (
        f"system status: standard envelope 아님. payload={payload!r}"
    )
    assert payload["trading_state"] == "active"
    assert payload["bot_count"] == 3


# ── 4. halt → standard ─────────────────────────────────────────────────────


def test_system_halt_envelope_matches_operation_standard() -> None:
    """``system halt``: ``fmt.success(f"시스템 HALTED ...", data)`` → standard.

    system.py:224: ``fmt.success(f"시스템 HALTED — {count}개 계좌 거래 중지",
    data)``. IPC response (``data`` slot) 를 그대로 wrapping.
    """
    ipc_response = {
        "data": {
            "accounts_changed": 5,
            "actor": "test-master",
            "reason": "drill",
        }
    }
    with patch(
        "ante.cli.commands.ipc_helpers.ipc_send",
        new=AsyncMock(return_value=ipc_response),
    ):
        result = _invoke(
            [
                "--format",
                "json",
                "system",
                "halt",
                "--reason",
                "drill",
            ]
        )
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_standard_envelope(payload), (
        f"system halt: standard envelope 이어야 함. payload={payload!r}"
    )
    assert "HALTED" in payload["message"]
    assert payload["data"]["accounts_changed"] == 5


# ── 5. clear-halt → standard ───────────────────────────────────────────────


def test_system_clear_halt_envelope_matches_operation_standard() -> None:
    """``system clear-halt``: ``fmt.success(f"...", data)`` → standard.

    system.py:242: ``fmt.success(f"시스템 정지 해제 — {count}개 계좌 ACTIVE
    복구 (봇은 자동 재시작되지 않음)", data)``. halt 동형 IPC wrapping.
    """
    ipc_response = {
        "data": {
            "accounts_changed": 2,
            "actor": "test-master",
            "reason": "post-drill",
        }
    }
    with patch(
        "ante.cli.commands.ipc_helpers.ipc_send",
        new=AsyncMock(return_value=ipc_response),
    ):
        result = _invoke(
            [
                "--format",
                "json",
                "system",
                "clear-halt",
                "--reason",
                "post-drill",
            ]
        )
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_standard_envelope(payload), (
        f"system clear-halt: standard envelope 이어야 함. payload={payload!r}"
    )
    assert "정지 해제" in payload["message"]
    assert payload["data"]["accounts_changed"] == 2
