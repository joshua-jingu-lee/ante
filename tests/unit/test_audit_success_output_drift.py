"""Audit CLI success output ↔ registry OutputContract drift lock (#1847 sub-PR 9).

본 모듈은 :data:`ante.contracts.cli_registry.CLI_COMMAND_REGISTRY` 에 등록된
audit 도메인 1 leaf 의 ``OutputContract`` 와 ``ante audit ... --format json``
실제 출력 envelope shape 사이의 drift 를 lock 한다.

#1846 (account) / #1847 sub-PR 1-8 1:1 동형 패턴. drift 모델:

- ``envelope="standard"`` entry → CLI success envelope ``{status, message,
  data}`` (envelopes.md SSOT). ``fmt.success(...)`` callsite 가 dump 한다.
- ``envelope="raw_legacy"`` entry → JSON mode 에서 ``fmt.output(...)`` 또는
  ``fmt.table(...)`` 으로 평면 dict 또는 row list 를 그대로 dump 한다
  (standard envelope 의 3 키 셋이 동시에 부재 또는 ``status != "ok"``).

본 PR 은 ``audit.py`` 본문을 *바꾸지 않으며*, registry entry 가 실제
callsite shape 와 일치함을 단순 lock 만 한다. callsite shape 가 drift
하면 본 test 가 즉시 FAIL 한다.

3 시나리오 (registry sanity +1 + list empty +1 + list non-empty +1):

0. registry sanity — audit 1 entry 의 envelope 분류기 범위 내.
1. ``list`` empty → ``raw_legacy`` (``{message, logs: []}``).
2. ``list`` non-empty → ``raw_legacy`` (``{logs: [...]}``).
"""

from __future__ import annotations

import json
from pathlib import Path
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


def test_registry_audit_entries_envelopes_classified() -> None:
    """audit 1 entry 의 envelope 이 ``standard`` 또는 ``raw_legacy`` 만 사용."""
    accepted = {"standard", "raw_legacy"}
    audit_entries = [
        (path, contract)
        for path, contract in CLI_COMMAND_REGISTRY.items()
        if path[:1] == ("audit",)
    ]
    assert len(audit_entries) == 1, (
        f"audit 1 entry 가 모두 등록되어야 한다. 실제: {len(audit_entries)}"
    )
    for path, contract in audit_entries:
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
    """``ante --format json audit ...`` 를 실행하고 결과를 반환한다."""
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


# ── 1. list empty → raw_legacy ─────────────────────────────────────────────


def test_audit_list_empty_envelope_matches_raw_legacy(tmp_path: Path) -> None:
    """``audit list`` empty: ``{message, logs: []}`` 평면 (raw_legacy).

    audit.py:89: ``fmt.output({"message": "감사 로그가 없습니다.", "logs": []})``
    분기. ``AuditLogger.query`` 가 빈 리스트를 반환할 때.
    """
    with (
        patch(
            "ante.audit.AuditLogger.initialize",
            new=AsyncMock(),
        ),
        patch(
            "ante.audit.AuditLogger.query",
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
                "audit",
                "list",
            ]
        )
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_raw_legacy_payload(payload), (
        f"audit list empty: standard envelope 아님. payload={payload!r}"
    )
    assert payload == {"message": "감사 로그가 없습니다.", "logs": []}


# ── 2. list non-empty → raw_legacy ─────────────────────────────────────────


def test_audit_list_non_empty_envelope_matches_raw_legacy(tmp_path: Path) -> None:
    """``audit list`` non-empty: ``{logs: [...]}`` 평면.

    audit.py:93: ``if fmt.is_json: fmt.output({"logs": result})`` 분기.
    ``AuditLogger.query`` 가 row dict list 를 반환할 때.
    """
    rows = [
        {
            "id": 1,
            "member_id": "test-master",
            "action": "test.action",
            "resource": "test-resource",
            "detail": "{}",
            "ip": "127.0.0.1",
            "created_at": "2026-01-15T10:00:00",
        },
        {
            "id": 2,
            "member_id": "test-master",
            "action": "test.other",
            "resource": "another",
            "detail": "{}",
            "ip": "127.0.0.1",
            "created_at": "2026-01-15T10:01:00",
        },
    ]
    with (
        patch(
            "ante.audit.AuditLogger.initialize",
            new=AsyncMock(),
        ),
        patch(
            "ante.audit.AuditLogger.query",
            new=AsyncMock(return_value=rows),
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
                "audit",
                "list",
            ]
        )
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_raw_legacy_payload(payload), (
        f"audit list non-empty: standard envelope 아님. payload={payload!r}"
    )
    assert "logs" in payload
    assert isinstance(payload["logs"], list)
    assert len(payload["logs"]) == 2
    assert payload["logs"][0]["id"] == 1
    assert payload["logs"][0]["action"] == "test.action"
