"""Approval CLI success output ↔ registry OutputContract drift lock (#1847 sub-PR 3).

본 모듈은 :data:`ante.contracts.cli_registry.CLI_COMMAND_REGISTRY` 에 등록된
approval 도메인 10 leaf 의 ``OutputContract`` 와 ``ante approval ... --format
json`` 실제 출력 envelope shape 사이의 drift 를 lock 한다.

#1846 (account) / #1847 sub-PR 1 (member) / #1847 sub-PR 2 (bot) 1:1 동형
패턴. drift 모델:

- ``envelope="standard"`` entry → CLI success envelope ``{status, message,
  data}`` (envelopes.md SSOT). ``fmt.success(...)`` callsite 가 dump 한다.
- ``envelope="raw_legacy"`` entry → JSON mode 에서 ``fmt.output(...)`` 또는
  ``fmt.table(...)`` 으로 평면 dict 또는 list 를 그대로 dump 한다 (``status``
  / ``message`` / ``data`` 3 키 모두 동시에 부재; ``fmt.table`` 은 list 를
  dump 하므로 dict shape 자체가 아님).

본 PR 은 ``approval.py`` 본문을 *바꾸지 않으며*, registry entry 가 실제
callsite shape 와 일치함을 단순 lock 만 한다. callsite shape 가 drift 하면
본 test 가 즉시 FAIL 한다 (registry 갱신 또는 callsite 정렬 중 한쪽이
책임).

13 시나리오 (10 leaf + list/audit-types empty/non-empty 분리 +1 + registry
sanity +1):

0. registry sanity — approval 10 entries 의 envelope 이 ``standard`` /
   ``raw_legacy`` 분류 범위 내.
1. ``list`` empty → ``raw_legacy`` (``fmt.table([], columns)`` → ``[]``)
2. ``list`` non-empty → ``raw_legacy`` (row list)
3. ``info`` → ``raw_legacy`` (``fmt.output(result)`` 평면 detail dict)
4. ``review`` → ``standard`` (``fmt.success(message, data)``)
5. ``audit-types`` empty → ``raw_legacy`` (``fmt.table([], columns)`` → ``[]``)
6. ``audit-types`` non-empty → ``raw_legacy`` (row list)
7. ``request`` → ``standard`` (``fmt.success(message, data)``)
8. ``reopen`` → ``standard`` (``fmt.success(message, data)``)
9. ``cancel`` → ``standard`` (``fmt.success(message, data)``)
10. ``approve`` → ``standard`` (``fmt.success(message, data)``)
11. ``reject`` → ``standard`` (``fmt.success(message, data)``)
12. ``cancel-invalid`` → ``standard`` (``fmt.success(message, data)``)
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from ante.approval.models import ApprovalRequest
from ante.contracts.cli_registry import CLI_COMMAND_REGISTRY
from ante.member.models import Member, MemberRole, MemberStatus, MemberType

# ── envelope shape predicates (envelopes.md SSOT, account/member/bot 동형) ──

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

    raw_legacy 는 ``fmt.output(dict)`` 또는 ``fmt.table(rows, cols)`` 출력의
    super-set 이다. 후자는 dict 가 아닌 list 를 dump 하므로 standard envelope
    predicate 가 자동으로 false 가 된다.
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


def test_registry_approval_entries_envelopes_classified() -> None:
    """approval 10 entry 의 envelope 이 ``standard`` 또는 ``raw_legacy`` 만 사용.

    본 단언은 본 모듈 fixture 의 envelope predicate 두 함수가 10 entry 를
    모두 분류할 수 있음을 lock 한다. envelope SSOT (#1821) 에 새 값이
    추가되면 본 분류기를 갱신해야 함을 표면화한다.
    """
    accepted = {"standard", "raw_legacy"}
    approval_entries = [
        (path, contract)
        for path, contract in CLI_COMMAND_REGISTRY.items()
        if path[:1] == ("approval",)
    ]
    assert len(approval_entries) == 10, (
        f"approval 10 entries 가 모두 등록되어야 한다. 실제: {len(approval_entries)}"
    )
    for path, contract in approval_entries:
        assert contract.output.envelope in accepted, (
            f"{path}: registry envelope='{contract.output.envelope}' 가 본 "
            f"drift test 의 분류 범위 ({sorted(accepted)}) 를 벗어남. "
            "envelope SSOT (#1821) 가 새 값을 추가했다면 본 분류기를 갱신하라."
        )


# ── CLI fixture (account/member/bot drift test 동형) ───────────────────────


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
    """master member 로 인증을 우회한다 (account/member/bot drift test 동형)."""
    with patch(
        "ante.cli.main.authenticate_member",
        side_effect=lambda ctx: ctx.obj.update({"member": _MOCK_MASTER}),
    ):
        yield


def _invoke(args: list[str]):
    """``ante --format json approval ...`` 를 실행하고 결과를 반환한다."""
    from ante.cli.main import cli

    runner = CliRunner()
    env = {"ANTE_MEMBER_TOKEN": ""}
    return runner.invoke(cli, args, env=env, catch_exceptions=False)


def _load_json_payload(output: str) -> Any:
    """CLI ``--format json`` 출력의 첫 JSON value 를 파싱한다.

    ``OutputFormatter`` 가 ``json.dumps(..., indent=2)`` 로 multi-line dump
    하기 때문에 처음 ``{`` 또는 ``[`` 부터 ``raw_decode`` 로 한 value 를
    파싱하고 나머지 stdout (text 모드 잔존물 등) 는 무시한다 (member/bot
    drift test 동형). ``fmt.table`` 출력은 list, ``fmt.success``/``fmt.output``
    출력은 dict.
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


def _make_mock_db() -> AsyncMock:
    """``Database`` mock — ``connect`` / ``close`` / ``fetch_*`` async 메서드.

    approval.py 의 offline leaf (``list``/``info``/``review``/``audit-types``)
    는 ``Database`` 를 직접 생성 + ``ApprovalService(db, eventbus)`` 패턴을
    사용하므로 ``Database`` 생성자 자체를 patch 하는 fixture 와 짝지어 쓴다.
    """
    db = AsyncMock()
    db.connect = AsyncMock()
    db.close = AsyncMock()
    db.fetch_all = AsyncMock(return_value=[])
    db.fetch_one = AsyncMock(return_value=None)
    db.execute = AsyncMock()
    return db


@pytest.fixture
def mock_approval_service():
    """``ApprovalService`` 생성자를 patch 해 service.method 응답을 customize.

    approval.py 의 offline leaf 는 ``from ante.approval import ApprovalService``
    를 함수 내부에서 import 한 뒤 생성자를 호출하므로 ``ante.approval.service``
    모듈에서 patch 한다 (``ante.approval`` 패키지의 re-export 와 일치).
    """
    service = AsyncMock()
    service.initialize = AsyncMock()

    db = _make_mock_db()
    with (
        patch("ante.approval.ApprovalService", return_value=service),
        patch("ante.core.database.Database", return_value=db),
        patch("ante.eventbus.bus.EventBus", return_value=MagicMock()),
    ):
        yield service, db


@pytest.fixture
def mock_ipc_send():
    """``ipc_send`` 를 mock 한다 (runtime_ipc 분기 leaf 용).

    각 테스트가 ``mock_ipc.return_value`` 를 설정해 IPC 응답을 customize.
    approval.py 는 ``from ante.cli.commands.ipc_helpers import ipc_send``
    를 함수 내부에서 lazy import 하므로 원본 모듈을 patch 해야 한다.
    """
    with patch("ante.cli.commands.ipc_helpers.ipc_send", new=AsyncMock()) as m:
        yield m


def _make_request(
    id: str = "abcd1234-aaaa-bbbb-cccc-1234567890ab",
    type: str = "bot_create",
    status: str = "pending",
    requester: str = "test-master",
    title: str = "Test 결재",
    **overrides: Any,
) -> ApprovalRequest:
    """테스트용 ``ApprovalRequest`` 인스턴스."""
    base = dict(
        id=id,
        type=type,
        status=status,
        requester=requester,
        title=title,
        body="",
        params={},
        reviews=[],
        history=[],
        reference_id="",
        expires_at="",
        created_at="2026-01-01T00:00:00",
        resolved_at="",
        resolved_by="",
        reject_reason="",
    )
    base.update(overrides)
    return ApprovalRequest(**base)  # type: ignore[arg-type]


# ── 1. approval list (empty / non-empty) → raw_legacy ─────────────────────


def test_approval_list_empty_envelope_matches_raw_legacy(mock_approval_service) -> None:
    """``approval list`` empty: ``fmt.table([], cols)`` → ``[]`` JSON list."""
    service, _db = mock_approval_service
    service.list_approvals = AsyncMock(return_value=[])

    result = _invoke(["--format", "json", "approval", "list"])
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_raw_legacy_payload(payload), (
        f"approval list empty: standard envelope 아니어야 함 (registry "
        f"envelope=raw_legacy 와 정합). 실제 payload={payload!r}"
    )
    assert payload == []


def test_approval_list_non_empty_envelope_matches_raw_legacy(
    mock_approval_service,
) -> None:
    """``approval list`` non-empty: ``fmt.table(rows, cols)`` → row JSON list."""
    service, _db = mock_approval_service
    service.list_approvals = AsyncMock(
        return_value=[
            _make_request(
                id="abcd1234aaaabbbb",
                type="bot_create",
                status="pending",
                title="Test 결재",
            )
        ]
    )

    result = _invoke(["--format", "json", "approval", "list"])
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_raw_legacy_payload(payload), (
        f"approval list non-empty: standard envelope 아니어야 함. payload={payload!r}"
    )
    assert isinstance(payload, list)
    assert len(payload) == 1
    # row dict 키 셋: id (prefix 8), type, status, requester, title, created_at
    row = payload[0]
    assert row["id"] == "abcd1234"
    assert row["type"] == "bot_create"
    assert row["status"] == "pending"
    assert row["title"] == "Test 결재"


# ── 2. approval info → raw_legacy ─────────────────────────────────────────


def test_approval_info_envelope_matches_raw_legacy(mock_approval_service) -> None:
    """``approval info``: ``fmt.output(result)`` 평면 detail dict (raw_legacy).

    approval.py 287: JSON 모드는 ``fmt.output(result)`` 로 평면 dict 를 dump.
    """
    service, _db = mock_approval_service
    req = _make_request(
        id="abcd1234-aaaa-bbbb-cccc-1234567890ab",
        type="bot_create",
        status="pending",
        title="Test 결재",
        body="본문",
    )
    service.get = AsyncMock(return_value=req)
    service.list_approvals = AsyncMock(return_value=[req])

    result = _invoke(
        ["--format", "json", "approval", "info", "abcd1234-aaaa-bbbb-cccc-1234567890ab"]
    )
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_raw_legacy_payload(payload), (
        f"approval info: standard envelope 아니어야 함. payload={payload!r}"
    )
    assert payload["id"] == "abcd1234-aaaa-bbbb-cccc-1234567890ab"
    assert payload["type"] == "bot_create"
    assert payload["status"] == "pending"


# ── 3. approval review → standard ─────────────────────────────────────────


def test_approval_review_envelope_matches_operation_standard(
    mock_approval_service,
) -> None:
    """``approval review``: 단일 경로 ``fmt.success(message, data)`` → standard."""
    service, _db = mock_approval_service
    service.add_review = AsyncMock(
        return_value=_make_request(
            id="abcd1234-aaaa-bbbb-cccc-1234567890ab",
            reviews=[{"reviewer": "test-master", "result": "pass", "detail": ""}],
        )
    )

    result = _invoke(
        [
            "--format",
            "json",
            "approval",
            "review",
            "abcd1234-aaaa-bbbb-cccc-1234567890ab",
            "--result",
            "pass",
        ]
    )
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_standard_envelope(payload), (
        f"approval review: standard envelope 이어야 함. payload={payload!r}"
    )
    assert "검토 의견 추가" in payload["message"]
    assert payload["data"]["reviewer"] == "test-master"
    assert payload["data"]["result"] == "pass"


# ── 4. approval audit-types (empty / non-empty) → raw_legacy ──────────────


def test_approval_audit_types_empty_envelope_matches_raw_legacy(
    mock_approval_service,
) -> None:
    """``approval audit-types`` empty: ``fmt.table([], cols)`` → ``[]`` list."""
    service, _db = mock_approval_service
    service.list_invalid_type_requests = AsyncMock(return_value=[])

    result = _invoke(["--format", "json", "approval", "audit-types"])
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_raw_legacy_payload(payload), (
        f"approval audit-types empty: standard envelope 아님. payload={payload!r}"
    )
    assert payload == []


def test_approval_audit_types_non_empty_envelope_matches_raw_legacy(
    mock_approval_service,
) -> None:
    """``approval audit-types`` non-empty: ``fmt.table(rows, cols)`` row list."""
    service, _db = mock_approval_service
    service.list_invalid_type_requests = AsyncMock(
        return_value=[
            _make_request(
                id="invalid-row-1",
                type="legacy_invalid_type",
                status="pending",
                expires_at="2026-12-31T00:00:00",
            )
        ]
    )

    result = _invoke(["--format", "json", "approval", "audit-types"])
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_raw_legacy_payload(payload), (
        f"approval audit-types non-empty: standard envelope 아님. payload={payload!r}"
    )
    assert isinstance(payload, list)
    assert len(payload) == 1
    # audit-types row 키 셋: id, type, status, requester, created_at, expires_at
    assert payload[0]["id"] == "invalid-row-1"
    assert payload[0]["type"] == "legacy_invalid_type"


# ── 5. approval request → standard ────────────────────────────────────────


def test_approval_request_envelope_matches_operation_standard(mock_ipc_send) -> None:
    """``approval request``: 단일 경로 ``fmt.success(message, result)`` → standard."""
    mock_ipc_send.return_value = {
        "id": "abcd1234-aaaa-bbbb-cccc-1234567890ab",
        "type": "bot_create",
        "status": "pending",
        "requester": "test-master",
        "title": "Test 결재",
    }

    result = _invoke(
        [
            "--format",
            "json",
            "approval",
            "request",
            "--type",
            "bot_create",
            "--title",
            "Test 결재",
        ]
    )
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_standard_envelope(payload), (
        f"approval request: standard envelope 이어야 함. payload={payload!r}"
    )
    assert "결재 요청 생성" in payload["message"]
    assert payload["data"]["id"] == "abcd1234-aaaa-bbbb-cccc-1234567890ab"


# ── 6. approval reopen → standard ─────────────────────────────────────────


def test_approval_reopen_envelope_matches_operation_standard(mock_ipc_send) -> None:
    """``approval reopen``: 단일 경로 ``fmt.success(message, result)`` → standard."""
    mock_ipc_send.return_value = {
        "id": "abcd1234-aaaa-bbbb-cccc-1234567890ab",
        "status": "pending",
    }

    result = _invoke(
        [
            "--format",
            "json",
            "approval",
            "reopen",
            "abcd1234-aaaa-bbbb-cccc-1234567890ab",
        ]
    )
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_standard_envelope(payload), (
        f"approval reopen: standard envelope 이어야 함. payload={payload!r}"
    )
    assert "결재 재상신" in payload["message"]
    assert payload["data"]["id"] == "abcd1234-aaaa-bbbb-cccc-1234567890ab"


# ── 7. approval cancel → standard ─────────────────────────────────────────


def test_approval_cancel_envelope_matches_operation_standard(mock_ipc_send) -> None:
    """``approval cancel``: 단일 경로 ``fmt.success(message, result)`` → standard."""
    mock_ipc_send.return_value = {
        "id": "abcd1234-aaaa-bbbb-cccc-1234567890ab",
        "status": "cancelled",
    }

    result = _invoke(
        [
            "--format",
            "json",
            "approval",
            "cancel",
            "abcd1234-aaaa-bbbb-cccc-1234567890ab",
        ]
    )
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_standard_envelope(payload), (
        f"approval cancel: standard envelope 이어야 함. payload={payload!r}"
    )
    assert "결재 철회" in payload["message"]
    assert payload["data"]["status"] == "cancelled"


# ── 8. approval approve → standard ────────────────────────────────────────


def test_approval_approve_envelope_matches_operation_standard(mock_ipc_send) -> None:
    """``approval approve``: 단일 경로 ``fmt.success(message, result)`` → standard."""
    mock_ipc_send.return_value = {
        "id": "abcd1234-aaaa-bbbb-cccc-1234567890ab",
        "status": "approved",
    }

    result = _invoke(
        [
            "--format",
            "json",
            "approval",
            "approve",
            "abcd1234-aaaa-bbbb-cccc-1234567890ab",
        ]
    )
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_standard_envelope(payload), (
        f"approval approve: standard envelope 이어야 함. payload={payload!r}"
    )
    assert "결재 승인" in payload["message"]
    assert payload["data"]["status"] == "approved"


# ── 9. approval reject → standard ─────────────────────────────────────────


def test_approval_reject_envelope_matches_operation_standard(mock_ipc_send) -> None:
    """``approval reject``: 단일 경로 ``fmt.success(message, result)`` → standard."""
    mock_ipc_send.return_value = {
        "id": "abcd1234-aaaa-bbbb-cccc-1234567890ab",
        "status": "rejected",
        "reject_reason": "검토 미흡",
    }

    result = _invoke(
        [
            "--format",
            "json",
            "approval",
            "reject",
            "abcd1234-aaaa-bbbb-cccc-1234567890ab",
            "--reason",
            "검토 미흡",
        ]
    )
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_standard_envelope(payload), (
        f"approval reject: standard envelope 이어야 함. payload={payload!r}"
    )
    assert "결재 거절" in payload["message"]
    assert payload["data"]["status"] == "rejected"


# ── 10. approval cancel-invalid → standard ────────────────────────────────


def test_approval_cancel_invalid_envelope_matches_operation_standard(
    mock_ipc_send,
) -> None:
    """``approval cancel-invalid``: ``fmt.success(message, result)`` → standard.

    legacy invalid-type row administrative cleanup (#1472). ``cancel`` 과 달리
    ``approval_id`` IPC key 를 사용하지만, 호출 사이트의 envelope shape 자체
    는 ``fmt.success(...)`` → standard 로 동일하다.
    """
    mock_ipc_send.return_value = {
        "id": "invalid-row-1",
        "status": "cancelled",
        "cleanup": True,
    }

    result = _invoke(
        ["--format", "json", "approval", "cancel-invalid", "invalid-row-1"]
    )
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_standard_envelope(payload), (
        f"approval cancel-invalid: standard envelope 이어야 함. payload={payload!r}"
    )
    assert "invalid-type 결재 cleanup" in payload["message"]
    assert payload["data"]["status"] == "cancelled"
