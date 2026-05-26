"""Config CLI success output ↔ registry OutputContract drift lock (#1847 sub-PR 8).

본 모듈은 :data:`ante.contracts.cli_registry.CLI_COMMAND_REGISTRY` 에 등록된
config 도메인 3 leaf 의 ``OutputContract`` 와 ``ante config ... --format
json`` 실제 출력 envelope shape 사이의 drift 를 lock 한다.

#1846 / #1847 sub-PR 1-7 1:1 동형 패턴. drift 모델:

- ``envelope="standard"`` entry → CLI success envelope ``{status: "ok",
  message, data}`` (envelopes.md SSOT). ``fmt.success(...)`` callsite 가
  dump 한다.
- ``envelope="raw_legacy"`` entry → JSON mode 에서 ``fmt.output(...)`` 또는
  ``fmt.table(...)`` 으로 평면 dict 또는 row list 를 그대로 dump 한다
  (standard envelope 의 3 키 셋이 동시에 부재 또는 ``status != "ok"``).

본 PR 은 ``config.py`` 본문을 *바꾸지 않으며*, registry entry 가 실제
callsite shape 와 일치함을 단순 lock 만 한다. callsite shape 가 drift
하면 본 test 가 즉시 FAIL 한다.

``config set`` 은 JSON mode 에서 ``fmt.output({"status": "success",
**result})`` 평면 dict 를 dump 한다 (config.py:182-184). ``status`` 키가
존재하나 값이 ``"success"`` (``"ok"`` 아님) 이므로 raw_legacy 분류 SSOT
predicate 의 standard envelope 인식에서 벗어난다 — registry 는 ``raw_legacy``
로 lock.

5 시나리오 (registry sanity +1 + 3 leaf raw_legacy + history empty +1):

0. registry sanity — config 3 entries 의 envelope 분류기 범위 내.
1. ``get`` 단일 키 → ``raw_legacy`` (``{key, value, source}``)
2. ``get`` 전체 목록 → ``raw_legacy`` (``{configs: [...]}``)
3. ``set`` → ``raw_legacy`` (``{status: "success", **result}``)
4. ``history`` empty → ``raw_legacy`` (``{key, history: []}``)
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


def test_registry_config_entries_envelopes_classified() -> None:
    """config 3 entry 의 envelope 이 ``standard`` 또는 ``raw_legacy`` 만 사용.

    본 단언은 본 모듈 fixture 의 envelope predicate 두 함수가 3 entry 를
    모두 분류할 수 있음을 lock 한다.
    """
    accepted = {"standard", "raw_legacy"}
    config_entries = [
        (path, contract)
        for path, contract in CLI_COMMAND_REGISTRY.items()
        if path[:1] == ("config",)
    ]
    assert len(config_entries) == 3, (
        f"config 3 entries 가 모두 등록되어야 한다. 실제: {len(config_entries)}"
    )
    for path, contract in config_entries:
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
    """``ante --format json config ...`` 를 실행하고 결과를 반환한다."""
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


# ── 1. get 단일 키 → raw_legacy ───────────────────────────────────────────


def test_config_get_single_key_envelope_matches_raw_legacy(tmp_path: Path) -> None:
    """``config get <key>`` 단일: ``{key, value, source}`` 평면.

    config.py:81: ``fmt.output(result)`` 단일 키 결과 평면 dict.
    DynamicConfigService / Config 를 mock 해 static source 결과 강제.
    """
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    # ``get_db_path`` 가 config_dir 기준 ``db/ante.db`` 를 resolve 한다.
    (config_dir / "db").mkdir()

    # 정적 default 키 (예: ``system.log_level``) 는 ``defaults.DEFAULTS`` 에
    # 등재되어 있어 ``_resolve_single`` 이 ``source: static`` 으로 반환한다.
    # dynamic.exists 가 False 이면 static 경로로 흐른다.
    result = _invoke(
        [
            "--config-dir",
            str(config_dir),
            "--format",
            "json",
            "config",
            "get",
            "system.log_level",
        ]
    )
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_raw_legacy_payload(payload), (
        f"config get 단일: standard envelope 아님. payload={payload!r}"
    )
    assert payload["key"] == "system.log_level"
    assert "value" in payload
    assert payload["source"] in {"static", "dynamic"}


# ── 2. get 전체 목록 → raw_legacy ─────────────────────────────────────────


def test_config_get_all_envelope_matches_raw_legacy(tmp_path: Path) -> None:
    """``config get`` 전체 목록: ``{configs: [...]}`` 평면.

    config.py:91: ``fmt.output({"configs": result})`` 전체 목록 평면 dict.
    """
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "db").mkdir()

    result = _invoke(
        [
            "--config-dir",
            str(config_dir),
            "--format",
            "json",
            "config",
            "get",
        ]
    )
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_raw_legacy_payload(payload), (
        f"config get 전체: standard envelope 아님. payload={payload!r}"
    )
    assert "configs" in payload
    assert isinstance(payload["configs"], list)


# ── 3. set → raw_legacy ───────────────────────────────────────────────────


def test_config_set_envelope_matches_raw_legacy() -> None:
    """``config set <k> <v>``: ``{status: "success", **result}`` 평면.

    config.py:182-184: ``fmt.output({"status": "success", **result})`` 평면.
    ``status`` 키가 ``"success"`` (``"ok"`` 아님) 이므로 raw_legacy 분류.
    """
    ipc_response = {
        "key": "system.log_level",
        "value": "INFO",
        "previous": "WARNING",
        "changed_by": "test-master",
    }
    with patch(
        "ante.cli.commands.ipc_helpers.ipc_send",
        new=AsyncMock(return_value=ipc_response),
    ):
        result = _invoke(
            [
                "--format",
                "json",
                "config",
                "set",
                "system.log_level",
                "INFO",
            ]
        )
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_raw_legacy_payload(payload), (
        f"config set: standard envelope 아님. payload={payload!r}"
    )
    # ``status: "success"`` 는 standard envelope ``"ok"`` 와 다르다.
    assert payload["status"] == "success"
    assert payload["key"] == "system.log_level"
    assert payload["value"] == "INFO"


# ── 4. history empty → raw_legacy ─────────────────────────────────────────


def test_config_history_empty_envelope_matches_raw_legacy(tmp_path: Path) -> None:
    """``config history <key>`` empty: ``{key, history: []}`` 평면.

    config.py:219: ``fmt.output({"key": key, "history": rows})`` 평면 dict.
    빈 DB 로 history empty 분기 강제.
    """
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "db").mkdir()

    result = _invoke(
        [
            "--config-dir",
            str(config_dir),
            "--format",
            "json",
            "config",
            "history",
            "system.log_level",
        ]
    )
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_raw_legacy_payload(payload), (
        f"config history empty: standard envelope 아님. payload={payload!r}"
    )
    assert payload["key"] == "system.log_level"
    assert payload["history"] == []
