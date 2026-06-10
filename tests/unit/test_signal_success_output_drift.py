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
SystemExit 한다. success-output drift test 의 일반 envelope 매칭 scope 밖이며,
본 모듈은 registry envelope 분류기 sanity 만 lock.

#2338 마이그레이션: ``signal connect`` 가 데몬-위임 thin IPC relay 로 재작성
되어 invalid key 거부는 더 이상 in-process ``validate_key`` 가 아니라 데몬의
**Phase-B error frame** 으로 도착한다. 본 모듈의 invalid-key JSON drift lock
도 in-process ``Database``/``SignalKeyManager`` patch 에서 IPC-layer mock
(``asyncio.open_unix_connection`` + ``INVALID_SIGNAL_KEY`` Phase-B frame)으로
repoint 한다 — relay 가 ``resp["error"]`` 를 ``_fail`` 로 flatten 해 동일한
``fmt.error`` envelope 을 byte-identical 로 dump 함을 lock 한다.

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
from unittest.mock import patch

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

    #2338 데몬-위임 relay: invalid key 는 데몬 Phase-B error frame
    (``{status:error, error:{code:INVALID_SIGNAL_KEY, message:...}}``)으로
    도착하고, relay 가 이를 ``_fail`` 로 flatten 해 JSON 모드 stdout 으로
    ``{status:error, code, message}`` envelope 을 dump 하고 exit 1.

    본 시나리오는 success-output drift 의 일반 envelope 매칭 scope 밖이지만,
    signal connect 의 유일한 stdout JSON dump 경로이므로 본 모듈이 함께
    lock 한다 (registry stream leaf 의 "success envelope 부재" 를 보완).
    """
    import asyncio
    import struct

    payload = json.dumps(
        {
            "id": "h1",
            "status": "error",
            "error": {"code": "INVALID_SIGNAL_KEY", "message": "Invalid signal key"},
        },
        ensure_ascii=False,
    ).encode("utf-8")
    frame = struct.pack("!I", len(payload)) + payload

    class _Reader:
        def __init__(self) -> None:
            self._buf = frame
            self._pos = 0

        async def readexactly(self, n: int):  # noqa: ANN202
            if self._pos + n > len(self._buf):
                partial = self._buf[self._pos :]
                self._pos = len(self._buf)
                raise asyncio.IncompleteReadError(partial, n)
            chunk = self._buf[self._pos : self._pos + n]
            self._pos += n
            return chunk

    class _Writer:
        def write(self, _data: bytes) -> None:
            return None

        async def drain(self) -> None:
            return None

        def close(self) -> None:
            return None

        async def wait_closed(self) -> None:
            return None

    async def _open(*_a, **_k):  # noqa: ANN002, ANN003, ANN202
        return _Reader(), _Writer()

    with (
        patch("ante.cli.commands.signal.Path.exists", return_value=True),
        patch(
            "ante.cli.commands.signal.get_socket_path",
            return_value="/tmp/test-ante.sock",
        ),
        patch("asyncio.open_unix_connection", _open),
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
    payload_out = _load_json_payload(result.stdout)
    assert isinstance(payload_out, dict)
    assert payload_out.get("status") == "error"
    assert payload_out.get("code") == "INVALID_SIGNAL_KEY"
    assert "message" in payload_out


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
