"""Member CLI success output ↔ registry OutputContract drift lock (#1847 sub-PR 1).

본 모듈은 :data:`ante.contracts.cli_registry.CLI_COMMAND_REGISTRY` 에 등록된
member 도메인 12 leaf 의 ``OutputContract`` 와 ``ante member ... --format
json`` 실제 출력 envelope shape 사이의 drift 를 lock 한다.

#1846 (account) 1:1 동형 패턴. drift 모델:

- ``envelope="standard"`` entry → CLI success envelope ``{status, message,
  data}`` (envelopes.md SSOT). ``fmt.success(...)`` callsite 가 dump 한다.
- ``envelope="raw_legacy"`` entry → JSON mode 에서 ``fmt.output(...)`` 로
  평면 dict 를 그대로 dump 한다 (``status``/``message``/``data`` 3 키
  모두 부재).

본 PR 은 ``member.py`` 본문을 *바꾸지 않으며*, registry entry 가 실제
callsite shape 와 일치함을 단순 lock 만 한다. callsite shape 가 drift 하면
본 test 가 즉시 FAIL 한다 (registry 갱신 또는 callsite 정렬 중 한쪽이
책임).

13 시나리오 (12 leaf + registry sanity 1):

0. registry sanity — member 12 entries 의 envelope 이 ``standard`` /
   ``raw_legacy`` 분류 범위 내.
1. ``list`` empty (rows 0) → ``raw_legacy`` (``{message, members}``)
2. ``list`` non-empty (rows > 0) → ``raw_legacy`` (``{members: [...]}``)
3. ``info`` → ``raw_legacy`` (평면 detail dict)
4. ``list-invalid-roles`` empty → ``raw_legacy`` (``{recommended_action,
   valid_roles, ..., actionable, legacy_revoked}`` 평면)
5. ``register`` → ``raw_legacy`` (``{**result, token}`` 평면)
6. ``set-emoji`` → ``standard`` (``fmt.success(message, data)``)
7. ``update-scopes`` cold_path → ``raw_legacy`` (``fmt.output(result)``)
8. ``suspend`` → ``standard`` (``fmt.success(message, data)``)
9. ``reactivate`` → ``standard``
10. ``revoke`` (--yes) → ``standard``
11. ``rotate-token`` → ``raw_legacy`` (``{**result, token}`` 평면)
12. ``reset-password`` → ``standard`` (``fmt.success("...")`` — data 없음)
13. ``regenerate-recovery-key`` → ``raw_legacy`` (``{recovery_key}``)
"""

from __future__ import annotations

import json
import os
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner

from ante.contracts.cli_registry import CLI_COMMAND_REGISTRY
from ante.member.models import Member, MemberRole, MemberStatus, MemberType

# ── envelope shape predicates (envelopes.md SSOT, account drift test 동형) ──

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

    raw_legacy 는 평면 도메인 payload 를 그대로 dump 한다. 만약 dict 가
    ``{status, message, data}`` 3 키를 동시에 갖고 ``status == "ok"`` 면
    standard envelope 으로 분류된다 (애매한 경계 방지).
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


def test_registry_member_entries_envelopes_classified() -> None:
    """member 12 entry 의 envelope 이 ``standard`` 또는 ``raw_legacy`` 두 값만 사용한다.

    본 단언은 본 모듈 fixture 의 envelope predicate 두 함수가 12 entry 를
    모두 분류할 수 있음을 lock 한다. envelope SSOT (#1821) 에 새 값이
    추가되면 본 분류기를 갱신해야 함을 표면화한다.
    """
    accepted = {"standard", "raw_legacy"}
    member_entries = [
        (path, contract)
        for path, contract in CLI_COMMAND_REGISTRY.items()
        if path[:1] == ("member",)
    ]
    assert len(member_entries) == 12, (
        f"member 12 entries 가 모두 등록되어야 한다. 실제: {len(member_entries)}"
    )
    for path, contract in member_entries:
        assert contract.output.envelope in accepted, (
            f"{path}: registry envelope='{contract.output.envelope}' 가 본 "
            f"drift test 의 분류 범위 ({sorted(accepted)}) 를 벗어남. "
            "envelope SSOT (#1821) 가 새 값을 추가했다면 본 분류기를 갱신하라."
        )


# ── CLI fixture (test_member_cli_ipc_error_equivalence.py 동형) ────────────


_MOCK_MASTER = Member(
    member_id="test-master",
    type=MemberType.HUMAN,
    role=MemberRole.MASTER,
    org="default",
    name="Test Master",
    status=MemberStatus.ACTIVE,
    scopes=[],
)


def _mock_member(
    member_id: str = "agent-1",
    *,
    type: str = MemberType.AGENT,
    role: str = MemberRole.DEFAULT,
    org: str = "default",
    name: str = "Agent 1",
    emoji: str = "",
    status: str = MemberStatus.ACTIVE,
    scopes: list[str] | None = None,
    token_hash: str = "",
    created_at: str = "2026-01-01T00:00:00",
    created_by: str = "test-master",
    last_active_at: str = "",
    token_expires_at: str = "",
) -> Member:
    """테스트용 ``Member`` mock 객체."""
    return Member(
        member_id=member_id,
        type=type,
        role=role,
        org=org,
        name=name,
        emoji=emoji,
        status=status,
        scopes=scopes if scopes is not None else [],
        token_hash=token_hash,
        created_at=created_at,
        created_by=created_by,
        last_active_at=last_active_at,
        token_expires_at=token_expires_at,
    )


@pytest.fixture
def mock_member_service():
    """``MemberService`` mock fixture (member.py ``_create_service`` 우회)."""
    svc = AsyncMock()
    db = AsyncMock()

    async def _create_service():
        return svc, db

    with patch(
        "ante.cli.commands.member._create_service",
        new=_create_service,
    ):
        yield svc


@pytest.fixture(autouse=True)
def bypass_auth():
    """master member 로 인증을 우회한다 (account drift test 동형)."""
    with patch(
        "ante.cli.main.authenticate_member",
        side_effect=lambda ctx: ctx.obj.update({"member": _MOCK_MASTER}),
    ):
        yield


@pytest.fixture
def offline_runtime():
    """runtime_ipc 명령이 cold_path 분기로 떨어지도록 active runtime 을 무력화한다."""
    with (
        patch("ante.main.read_pid_file", return_value=None),
        patch(
            "ante.cli.commands.ipc_helpers.get_socket_path",
            return_value="/tmp/__ante_member_drift_test__.sock",
        ),
    ):
        yield


def _invoke(args: list[str]):
    """``ante --format json member ...`` 를 실행하고 결과를 반환한다."""
    from ante.cli.main import cli

    runner = CliRunner()
    env = {"ANTE_MEMBER_TOKEN": ""}
    return runner.invoke(cli, args, env=env, catch_exceptions=False)


def _load_json_payload(output: str) -> dict[str, Any]:
    """CLI ``--format json`` 출력의 첫 JSON 객체를 파싱한다.

    Click ``CliRunner`` 가 한 invocation 의 stdout 을 합쳐주므로 일반적으로
    한 객체의 JSON 만 나온다. ``OutputFormatter`` 가 ``json.dumps(...,
    indent=2)`` 로 multi-line dump 하기 때문에 처음 ``{`` 부터 ``raw_decode``
    로 한 객체를 먼저 파싱하고 나머지 stdout (text 모드 ``click.echo``
    잔존물 등) 는 무시한다.
    """
    text = output.lstrip()
    assert text, f"CLI 출력이 비어 있다: {output!r}"
    start = text.find("{")
    assert start >= 0, f"JSON 객체 시작을 찾을 수 없다: {output!r}"
    decoder = json.JSONDecoder()
    obj, _end = decoder.raw_decode(text[start:])
    return obj


# ── 1. member list (empty / non-empty) → raw_legacy ────────────────────────


def test_member_list_empty_envelope_matches_raw_legacy(
    mock_member_service: AsyncMock,
) -> None:
    """``member list`` empty 결과: ``{message, members}`` 평면 dict (raw_legacy)."""
    mock_member_service.list_members.return_value = []
    result = _invoke(["--format", "json", "member", "list"])
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_raw_legacy_envelope(payload), (
        f"member list empty: standard envelope 아니어야 함 (registry "
        f"envelope=raw_legacy 와 정합). 실제 payload={payload!r}"
    )
    assert payload == {"message": "등록된 멤버가 없습니다.", "members": []}


def test_member_list_non_empty_envelope_matches_raw_legacy(
    mock_member_service: AsyncMock,
) -> None:
    """``member list`` non-empty: ``{members: [...]}`` 평면 dict (raw_legacy)."""
    mock_member_service.list_members.return_value = [_mock_member("agent-1")]
    result = _invoke(["--format", "json", "member", "list"])
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_raw_legacy_envelope(payload), (
        f"member list non-empty: standard envelope 아니어야 함. payload={payload!r}"
    )
    assert "members" in payload
    assert isinstance(payload["members"], list)
    assert len(payload["members"]) == 1
    assert payload["members"][0]["member_id"] == "agent-1"


# ── 2. member info → raw_legacy ────────────────────────────────────────────


def test_member_info_envelope_matches_raw_legacy(
    mock_member_service: AsyncMock,
) -> None:
    """``member info``: 평면 detail dict (raw_legacy)."""
    mock_member_service.get.return_value = _mock_member("agent-1")
    result = _invoke(["--format", "json", "member", "info", "agent-1"])
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_raw_legacy_envelope(payload), (
        f"member info: standard envelope 아니어야 함. payload={payload!r}"
    )
    assert payload["member_id"] == "agent-1"
    assert payload["role"] == MemberRole.DEFAULT


# ── 3. member list-invalid-roles empty → raw_legacy ────────────────────────


def test_member_list_invalid_roles_empty_envelope_matches_raw_legacy(
    mock_member_service: AsyncMock,
) -> None:
    """``member list-invalid-roles`` empty: ``{recommended_action, valid_roles,
    actionable_count, legacy_revoked_count, actionable, legacy_revoked}`` 평면.
    """
    from ante.member.service import InvalidRoleScan

    mock_member_service.find_invalid_role_members.return_value = InvalidRoleScan(
        actionable=[],
        legacy_revoked=[],
    )
    result = _invoke(["--format", "json", "member", "list-invalid-roles"])
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_raw_legacy_envelope(payload), (
        f"member list-invalid-roles: standard envelope 아니어야 함. payload={payload!r}"
    )
    assert payload["recommended_action"] == "review_then_revoke"
    assert payload["actionable_count"] == 0
    assert payload["legacy_revoked_count"] == 0
    assert payload["actionable"] == []
    assert payload["legacy_revoked"] == []


# ── 4. member register → raw_legacy ────────────────────────────────────────


def test_member_register_envelope_matches_raw_legacy(
    mock_member_service: AsyncMock,
) -> None:
    """``member register``: JSON 모드 ``{**result, "token": ...}`` 평면 dict.

    text 모드는 ``fmt.success`` + ``click.echo(token)`` 분기지만, JSON 모드
    는 token 을 평면 dict 에 합쳐 ``fmt.output`` 으로 dump 한다 (member.py
    line 538-543). registry 의 ``raw_legacy`` 정책에 부합.
    """
    new_member = _mock_member("agent-2", role=MemberRole.DEFAULT, name="새 에이전트")
    mock_member_service.register.return_value = (new_member, "fresh-token-xyz")
    result = _invoke(
        [
            "--format",
            "json",
            "member",
            "register",
            "--id",
            "agent-2",
            "--type",
            "agent",
        ]
    )
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_raw_legacy_envelope(payload), (
        f"member register: standard envelope 아니어야 함. payload={payload!r}"
    )
    assert payload["member_id"] == "agent-2"
    assert payload["token"] == "fresh-token-xyz"


# ── 5. member set-emoji → standard ─────────────────────────────────────────


def test_member_set_emoji_envelope_matches_operation_standard(
    mock_member_service: AsyncMock,
) -> None:
    """``member set-emoji``: 단일 경로 ``fmt.success(message, data)`` → standard."""
    updated = _mock_member("agent-1", emoji="🤖")
    mock_member_service.update_emoji.return_value = updated
    result = _invoke(
        ["--format", "json", "member", "set-emoji", "agent-1", "🤖"],
    )
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_standard_envelope(payload), (
        f"member set-emoji: standard envelope 이어야 함. payload={payload!r}"
    )
    assert "이모지 설정 완료" in payload["message"]
    assert payload["data"]["emoji"] == "🤖"


# ── 6. member update-scopes (cold_path 분기) → raw_legacy ──────────────────


def test_member_update_scopes_cold_path_envelope_matches_raw_legacy(
    mock_member_service: AsyncMock, offline_runtime
) -> None:
    """``member update-scopes`` cold_path: ``fmt.output(result)`` 평면 dict.

    member.py 599-621: ``is_active_runtime()`` 가 False (서버 미실행) 면
    직접 ``MemberService.update_scopes`` 를 호출하고 결과 dict 를
    ``fmt.output`` 으로 dump 한다. ``offline_runtime`` fixture 가 active
    runtime 을 무력화해 cold_path 분기로 진입한다.
    """
    updated = _mock_member("agent-1", scopes=["account:read", "member:read"])
    mock_member_service.update_scopes.return_value = updated
    result = _invoke(
        [
            "--format",
            "json",
            "member",
            "update-scopes",
            "agent-1",
            "--scopes",
            "account:read,member:read",
        ]
    )
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_raw_legacy_envelope(payload), (
        f"member update-scopes cold_path: standard envelope 아니어야 함. "
        f"payload={payload!r}"
    )
    assert payload["member_id"] == "agent-1"
    assert "account:read" in payload["scopes"]


# ── 7. member suspend → standard ───────────────────────────────────────────


def test_member_suspend_envelope_matches_operation_standard(
    mock_member_service: AsyncMock,
) -> None:
    """``member suspend``: 단일 경로 ``fmt.success(message, data)`` → standard."""
    suspended = _mock_member("agent-1", status=MemberStatus.SUSPENDED)
    mock_member_service.suspend.return_value = suspended
    result = _invoke(["--format", "json", "member", "suspend", "agent-1"])
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_standard_envelope(payload), (
        f"member suspend: standard envelope 이어야 함. payload={payload!r}"
    )
    assert "정지 완료" in payload["message"]
    assert payload["data"]["status"] == MemberStatus.SUSPENDED


# ── 8. member reactivate → standard ────────────────────────────────────────


def test_member_reactivate_envelope_matches_operation_standard(
    mock_member_service: AsyncMock,
) -> None:
    """``member reactivate``: ``fmt.success(message, data)`` → standard."""
    reactivated = _mock_member("agent-1", status=MemberStatus.ACTIVE)
    mock_member_service.reactivate.return_value = reactivated
    result = _invoke(["--format", "json", "member", "reactivate", "agent-1"])
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_standard_envelope(payload), (
        f"member reactivate: standard envelope 이어야 함. payload={payload!r}"
    )
    assert "재활성화 완료" in payload["message"]
    assert payload["data"]["status"] == MemberStatus.ACTIVE


# ── 9. member revoke (--yes) → standard ────────────────────────────────────


def test_member_revoke_envelope_matches_operation_standard(
    mock_member_service: AsyncMock,
) -> None:
    """``member revoke --yes``: ``fmt.success(message, data)`` → standard."""
    revoked = _mock_member("agent-1", status=MemberStatus.REVOKED)
    mock_member_service.revoke.return_value = revoked
    result = _invoke(
        ["--format", "json", "member", "revoke", "agent-1", "--yes"],
    )
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_standard_envelope(payload), (
        f"member revoke: standard envelope 이어야 함. payload={payload!r}"
    )
    assert "폐기 완료" in payload["message"]
    assert payload["data"]["status"] == MemberStatus.REVOKED


# ── 10. member rotate-token → raw_legacy ───────────────────────────────────


def test_member_rotate_token_envelope_matches_raw_legacy(
    mock_member_service: AsyncMock,
) -> None:
    """``member rotate-token``: JSON 모드 ``{**result, "token": ...}`` 평면 dict.

    text 모드는 ``click.echo`` 로 새 토큰을 별도 표시하지만 JSON 모드는
    평면 dict 에 token 을 합쳐 ``fmt.output`` 으로 dump 한다 (member.py
    line 821-826). registry 의 ``raw_legacy`` 정책에 부합.
    """
    rotated = _mock_member("agent-1")
    mock_member_service.rotate_token.return_value = (rotated, "new-token-abc")
    result = _invoke(
        ["--format", "json", "member", "rotate-token", "agent-1"],
    )
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_raw_legacy_envelope(payload), (
        f"member rotate-token: standard envelope 아니어야 함. payload={payload!r}"
    )
    assert payload["member_id"] == "agent-1"
    assert payload["token"] == "new-token-abc"


# ── 11. member reset-password → standard ───────────────────────────────────


def test_member_reset_password_envelope_matches_operation_standard(
    mock_member_service: AsyncMock,
) -> None:
    """``member reset-password``: 단일 ``fmt.success(message)`` (data 없음) → standard.

    fmt.success 가 data 인자를 주지 않으면 envelope 의 ``data`` 는 빈 dict
    또는 None 으로 dump 된다. envelope predicate 는 ``data`` 가 dict /
    None 둘 다 허용한다.
    """
    # reset-password 는 master 멤버를 찾아 reset_password 를 호출한다.
    mock_member_service.list_members.return_value = [_MOCK_MASTER]
    mock_member_service.reset_password.return_value = None

    env_key = "ANTE_TEST_NEW_PASSWORD_DRIFT"
    with patch.dict(os.environ, {env_key: "new-password-123"}):
        result = _invoke(
            [
                "--format",
                "json",
                "member",
                "reset-password",
                "--recovery-key",
                "test-recovery-key",
                "--new-password-env",
                env_key,
            ]
        )
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_standard_envelope(payload), (
        f"member reset-password: standard envelope 이어야 함. payload={payload!r}"
    )
    assert "패스워드가 변경" in payload["message"]


# ── 12. member regenerate-recovery-key → raw_legacy ────────────────────────


def test_member_regenerate_recovery_key_envelope_matches_raw_legacy(
    mock_member_service: AsyncMock,
) -> None:
    """``member regenerate-recovery-key``: JSON ``{"recovery_key": ...}`` 평면 dict.

    text 모드는 ``click.echo`` 로 신규 키를 별도 표시하지만 JSON 모드는
    ``fmt.output({"recovery_key": new_key})`` 평면 dict (member.py
    line 954-955). registry 의 ``raw_legacy`` 정책에 부합.
    """
    mock_member_service.list_members.return_value = [_MOCK_MASTER]
    mock_member_service.regenerate_recovery_key.return_value = "fresh-recovery-key-xyz"

    env_key = "ANTE_TEST_CURRENT_PASSWORD_DRIFT"
    with patch.dict(os.environ, {env_key: "current-password-456"}):
        result = _invoke(
            [
                "--format",
                "json",
                "member",
                "regenerate-recovery-key",
                "--password-env",
                env_key,
            ]
        )
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_raw_legacy_envelope(payload), (
        f"member regenerate-recovery-key: standard envelope 아니어야 함. "
        f"payload={payload!r}"
    )
    assert payload == {"recovery_key": "fresh-recovery-key-xyz"}
