"""Signal CLI success output ↔ registry OutputContract drift lock (#1847 sub-PR 9).

본 모듈은 :data:`ante.contracts.cli_registry.CLI_COMMAND_REGISTRY` 에 등록된
signal 도메인 1 leaf (``signal connect``) 의 ``OutputContract`` 와 실제
callsite 의 envelope shape 사이의 drift 를 lock 한다.

#1846 (account) / #1847 sub-PR 1-8 1:1 동형 패턴. drift 모델:

- ``envelope="standard"`` entry → CLI success envelope ``{status, message,
  data}`` (envelopes.md SSOT).
- ``envelope="raw_legacy"`` entry → JSON mode 에서 ``fmt.output(...)`` 또는
  ``fmt.table(...)`` 으로 평면 dict / row list 또는 envelope 부재.

``signal connect`` 는 bidirectional JSON Lines stream 채널을 stdin/stdout
위로 수립한다 (long-running / streaming). ``fmt.success`` / ``fmt.output``
단일 envelope dump 는 *발생하지 않는다*. validation 실패 분기 (``_fail``)
만 JSON 모드에서 ``fmt.error(msg, code=...)`` envelope 을 dump 하고 즉시
SystemExit (signal.py:93-104). success-output drift test 의 일반 envelope
매칭 scope 밖이며, 본 모듈은 registry envelope 분류기 sanity 만 lock.

3 시나리오 (registry sanity +1 + validation error envelope +1 + connect
가 fmt.success 를 호출하지 않음 +1):

0. registry sanity — signal 1 entry 의 envelope 분류기 범위 내.
1. invalid key → ``fmt.error`` envelope (``{status: "error", code:
   "INVALID_SIGNAL_KEY", message: ...}``) — JSON 모드 stdout, exit 1.
2. signal.py source 가 ``fmt.success`` / ``fmt.output`` 을 호출하지 않음 —
   stream leaf 이므로 success envelope 부재가 정상 (raw_legacy 분류 의도와
   1:1 정합).
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


def test_registry_signal_entries_envelopes_classified() -> None:
    """signal 1 entry 의 envelope 이 ``standard`` 또는 ``raw_legacy`` 만 사용."""
    accepted = {"standard", "raw_legacy"}
    signal_entries = [
        (path, contract)
        for path, contract in CLI_COMMAND_REGISTRY.items()
        if path[:1] == ("signal",)
    ]
    assert len(signal_entries) == 1, (
        f"signal 1 entry 가 모두 등록되어야 한다. 실제: {len(signal_entries)}"
    )
    for path, contract in signal_entries:
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
    """``ante --format json signal ...`` 를 실행하고 결과를 반환한다."""
    from ante.cli.main import cli

    runner = CliRunner(mix_stderr=False)
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


# ── 1. validation error envelope (invalid key) — fmt.error envelope ─────


def test_signal_connect_invalid_key_emits_error_envelope(tmp_path: Path) -> None:
    """``signal connect`` invalid key: ``fmt.error`` JSON envelope 발화.

    signal.py:50-52: ``validate_key`` 가 ``None`` 반환 시 ``_fail(fmt,
    "Invalid signal key", "INVALID_SIGNAL_KEY")``. JSON 모드는 stdout 으로
    ``{status: "error", code, message}`` envelope 을 dump 하고 exit 1.

    본 시나리오는 success-output drift 의 일반 envelope 매칭 scope 밖이지만,
    signal connect 의 유일한 stdout JSON dump 경로이므로 본 모듈이 함께
    lock 한다 (registry stream leaf 의 "success envelope 부재" 를 보완).
    """
    db = MagicMock()
    db.connect = AsyncMock()
    db.close = AsyncMock()
    skm = MagicMock()
    skm.initialize = AsyncMock()
    skm.validate_key = AsyncMock(return_value=None)

    # signal.py 는 ``_run_connect`` 내부에서 lazy import 하므로 원본 모듈을
    # 직접 patch 한다.
    with (
        patch("ante.core.database.Database", return_value=db),
        patch(
            "ante.bot.signal_key.SignalKeyManager",
            return_value=skm,
        ),
    ):
        result = _invoke(
            [
                "--config-dir",
                str(tmp_path),
                "--format",
                "json",
                "signal",
                "connect",
                "--key",
                "sk_invalid",
            ]
        )

    # invalid key 분기는 exit 1.
    assert result.exit_code == 1, result.stdout

    # JSON envelope 는 stdout 에 dump 된다 (fmt.error).
    payload = _load_json_payload(result.stdout)
    assert isinstance(payload, dict)
    assert payload.get("status") == "error"
    assert payload.get("code") == "INVALID_SIGNAL_KEY"
    assert "message" in payload


# ── 2. signal.py callsite 부재 단언 (success envelope 미생성) ───────────


def test_signal_connect_source_does_not_emit_fmt_success_or_output() -> None:
    """``signal.py`` 본문이 ``fmt.success`` / ``fmt.output`` 를 호출하지 않음.

    signal connect 는 stream leaf 이므로 standard envelope success path 가
    *부재* 함이 정상이다 (raw_legacy 분류 의도와 1:1 정합). 본 단언은
    callsite 가 미래에 success envelope 을 추가하면 (그러면 stream nature
    가 깨지므로) FAIL 하여 registry envelope 분류 갱신을 강제한다.
    """
    from pathlib import Path as _Path

    # signal.py source 를 모듈 파일 경로로 직접 read — repo-relative path 로
    # stable. 단순 string 검색으로 lock.
    import ante.cli.commands.signal as signal_mod

    src_path = _Path(signal_mod.__file__)
    body = src_path.read_text(encoding="utf-8")
    assert "fmt.success(" not in body, (
        "signal.py 가 ``fmt.success(`` 를 호출한다 — stream leaf 의 envelope "
        "분류 (raw_legacy) 와 충돌한다. registry envelope 을 갱신하거나 "
        "callsite 를 다시 stream-only 로 되돌리라."
    )
    assert "fmt.output(" not in body, (
        "signal.py 가 ``fmt.output(`` 를 호출한다 — stream leaf 의 envelope "
        "분류 (raw_legacy) 와 충돌한다. registry envelope 을 갱신하거나 "
        "callsite 를 다시 stream-only 로 되돌리라."
    )
    # fmt.error 만 발화 (validation 실패 경로).
    assert "fmt.error(" in body, (
        "signal.py 가 ``fmt.error(`` 를 호출하지 않는다 — validation 실패 "
        "envelope (test_signal_connect_invalid_key_emits_error_envelope) 도 "
        "drift 했을 가능성. registry / callsite 정합을 확인하라."
    )
