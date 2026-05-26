"""Instrument CLI success output ↔ registry OutputContract drift lock (#1847 sub-PR 8).

본 모듈은 :data:`ante.contracts.cli_registry.CLI_COMMAND_REGISTRY` 에 등록된
instrument 도메인 4 leaf 의 ``OutputContract`` 와 ``ante instrument ...
--format json`` 실제 출력 envelope shape 사이의 drift 를 lock 한다.

#1846 (account) / #1847 sub-PR 1 (member) / sub-PR 2 (bot) / sub-PR 3
(approval) / sub-PR 4 (treasury) / sub-PR 5 (strategy) / sub-PR 6 (data /
report) / sub-PR 7 (broker / system) 1:1 동형 패턴. drift 모델:

- ``envelope="standard"`` entry → CLI success envelope ``{status, message,
  data}`` (envelopes.md SSOT). ``fmt.success(...)`` callsite 가 dump 한다.
- ``envelope="raw_legacy"`` entry → JSON mode 에서 ``fmt.output(...)`` 또는
  ``fmt.table(...)`` 으로 평면 dict 또는 row list 를 그대로 dump 한다
  (standard envelope 의 3 키 셋이 동시에 부재 또는 ``status != "ok"``).

본 PR 은 ``instrument.py`` 본문을 *바꾸지 않으며*, registry entry 가 실제
callsite shape 와 일치함을 단순 lock 만 한다. callsite shape 가 drift 하면
본 test 가 즉시 FAIL 한다 (registry 갱신 또는 callsite 정렬 중 한쪽이 책임).

``instrument import`` 는 dry-run / 실제 import 분기 mixed 다 — plan v2
mixed-branch policy 에 따라 registry 는 raw_legacy 로 lock 하고, 본 test
가 dry-run (raw_legacy) 과 실제 import (standard envelope 분기) 의 양쪽
실제 dump shape 를 모두 단언한다.

6 시나리오 (registry sanity +1 + 4 leaf raw_legacy +4 + import dry-run +1):

0. registry sanity — instrument 4 entries 의 envelope 분류기 범위 내.
1. ``list`` empty → ``raw_legacy`` (``{"instruments": [], "count": 0}``)
2. ``sync`` → ``raw_legacy`` (``{"sync_result": {...}, "message": ...}``)
3. ``search`` empty → ``raw_legacy`` (``{"results": [], "count": 0}``)
4. ``import`` dry-run → ``raw_legacy`` (``{dry_run, total, preview}``)
5. ``import`` 실제 import → standard envelope 분기 (``{status: "ok",
   message, data: {count, file}}``); raw_legacy lock 정책에 대한 mixed
   분기 인식 단언.
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


def test_registry_instrument_entries_envelopes_classified() -> None:
    """instrument 4 entry 의 envelope 이 ``standard`` 또는 ``raw_legacy`` 만 사용.

    본 단언은 본 모듈 fixture 의 envelope predicate 두 함수가 4 entry 를
    모두 분류할 수 있음을 lock 한다. envelope SSOT (#1821) 에 새 값이
    추가되면 본 분류기를 갱신해야 함을 표면화한다.
    """
    accepted = {"standard", "raw_legacy"}
    instrument_entries = [
        (path, contract)
        for path, contract in CLI_COMMAND_REGISTRY.items()
        if path[:1] == ("instrument",)
    ]
    assert len(instrument_entries) == 4, (
        f"instrument 4 entries 가 모두 등록되어야 한다. 실제: {len(instrument_entries)}"
    )
    for path, contract in instrument_entries:
        assert contract.output.envelope in accepted, (
            f"{path}: registry envelope='{contract.output.envelope}' 가 본 "
            f"drift test 의 분류 범위 ({sorted(accepted)}) 를 벗어남. "
            "envelope SSOT (#1821) 가 새 값을 추가했다면 본 분류기를 갱신하라."
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
    """``ante --format json instrument ...`` 를 실행하고 결과를 반환한다."""
    from ante.cli.main import cli

    runner = CliRunner()
    env = {"ANTE_MEMBER_TOKEN": ""}
    return runner.invoke(cli, args, env=env, catch_exceptions=False)


def _load_json_payload(output: str) -> Any:
    """CLI ``--format json`` 출력의 첫 JSON value 를 파싱한다.

    ``OutputFormatter`` 가 ``json.dumps(..., indent=2)`` 로 multi-line dump
    하기 때문에 처음 ``{`` 또는 ``[`` 부터 ``raw_decode`` 로 한 value 를
    파싱하고 나머지 stdout (text 모드 잔존물 등) 는 무시한다 (동형 패턴).
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


# ── 1. list empty → raw_legacy ─────────────────────────────────────────────


def test_instrument_list_empty_envelope_matches_raw_legacy(tmp_path: Path) -> None:
    """``instrument list`` empty: ``{"instruments": [], "count": 0}`` 평면.

    instrument.py:107: ``if not results: fmt.output({"instruments": [],
    "count": 0})``. 비어있는 DB 로 empty 분기 강제.
    """
    db_path = tmp_path / "test.db"
    result = _invoke(
        [
            "--format",
            "json",
            "instrument",
            "list",
            "--db-path",
            str(db_path),
        ]
    )
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_raw_legacy_payload(payload), (
        f"instrument list empty: standard envelope 아님. payload={payload!r}"
    )
    assert payload == {"instruments": [], "count": 0}


# ── 2. sync → raw_legacy ───────────────────────────────────────────────────


def test_instrument_sync_envelope_matches_raw_legacy(tmp_path: Path) -> None:
    """``instrument sync``: ``fmt.output({"sync_result": ..., "message": ...})``.

    instrument.py:233-243: ``fmt.output({"sync_result": result, "message":
    "동기화 완료: ..."})`` 평면 dict. KISAdapter 와 InstrumentService 를
    mock 해 sync success 경로를 강제한다.
    """
    db_path = tmp_path / "test.db"
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    # system.toml 에 broker.app_key 가 있어야 ``broker_config.get("app_key")``
    # falsy 분기 (line 163-164) 를 회피한다.
    (config_dir / "system.toml").write_text(
        '[broker]\napp_key = "dummy-key"\napp_secret = "dummy-secret"\n',
        encoding="utf-8",
    )

    raw_instruments = [
        {
            "symbol": "005930",
            "name": "삼성전자",
            "name_en": "Samsung Electronics",
            "instrument_type": "stock",
            "listed": True,
        },
        {
            "symbol": "000660",
            "name": "SK하이닉스",
            "name_en": "SK Hynix",
            "instrument_type": "stock",
            "listed": True,
        },
    ]

    # KISAdapter 의 connect/disconnect 와 get_instruments 를 mock.
    mock_adapter = AsyncMock()
    mock_adapter.connect = AsyncMock()
    mock_adapter.disconnect = AsyncMock()
    mock_adapter.get_instruments = AsyncMock(return_value=raw_instruments)

    with patch(
        "ante.broker.kis.KISAdapter",
        return_value=mock_adapter,
    ):
        result = _invoke(
            [
                "--config-dir",
                str(config_dir),
                "--format",
                "json",
                "instrument",
                "sync",
                "--db-path",
                str(db_path),
            ]
        )
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_raw_legacy_payload(payload), (
        f"instrument sync: standard envelope 아님. payload={payload!r}"
    )
    assert "sync_result" in payload
    assert "message" in payload
    assert payload["sync_result"]["total"] == 2


# ── 3. search empty → raw_legacy ──────────────────────────────────────────


def test_instrument_search_empty_envelope_matches_raw_legacy(tmp_path: Path) -> None:
    """``instrument search`` empty: ``{"results": [], "count": 0}`` 평면.

    instrument.py:296: ``if not results: fmt.output({"results": [],
    "count": 0})``. 비어있는 DB 로 empty 분기 강제.
    """
    db_path = tmp_path / "test.db"
    result = _invoke(
        [
            "--format",
            "json",
            "instrument",
            "search",
            "nonexistent-keyword",
            "--db-path",
            str(db_path),
        ]
    )
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_raw_legacy_payload(payload), (
        f"instrument search empty: standard envelope 아님. payload={payload!r}"
    )
    assert payload == {"results": [], "count": 0}


# ── 4. import dry-run → raw_legacy ────────────────────────────────────────


def test_instrument_import_dry_run_envelope_matches_raw_legacy(
    tmp_path: Path,
) -> None:
    """``instrument import --dry-run`` JSON: ``{dry_run, total, preview}`` 평면.

    instrument.py:441-448: ``if fmt.is_json: fmt.output({"dry_run": True,
    "total": N, "preview": [...]})``. CSV 파일을 임시 작성해 dry-run 호출.
    """
    db_path = tmp_path / "test.db"
    csv_path = tmp_path / "sample.csv"
    csv_path.write_text(
        "symbol,exchange,name,name_en,instrument_type,listed\n"
        "005930,KRX,삼성전자,Samsung Electronics,stock,true\n"
        "000660,KRX,SK하이닉스,SK Hynix,stock,true\n",
        encoding="utf-8",
    )
    result = _invoke(
        [
            "--format",
            "json",
            "instrument",
            "import",
            str(csv_path),
            "--dry-run",
            "--db-path",
            str(db_path),
        ]
    )
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_raw_legacy_payload(payload), (
        f"instrument import dry-run: standard envelope 아님. payload={payload!r}"
    )
    assert payload["dry_run"] is True
    assert payload["total"] == 2
    assert isinstance(payload["preview"], list)
    assert len(payload["preview"]) == 2


# ── 5. import 실제 → standard envelope 분기 (mixed-branch awareness) ───────


def test_instrument_import_actual_envelope_is_standard_branch(
    tmp_path: Path,
) -> None:
    """``instrument import`` (실제) 분기: ``fmt.success(..., {count, file})`` standard.

    instrument.py:471-474: ``fmt.success(f"종목 import 완료: {count}건",
    {"count": count, "file": str(path)})`` → standard envelope. registry 는
    raw 우선 정책 (mixed-branch policy — account ``set-credentials`` / bot
    ``signal-key`` / treasury ``set-balance`` / strategy ``set-status`` /
    data ``delete`` 동형) 으로 ``raw_legacy`` 로 lock 되어 있으나, 본 test
    는 실제 import 분기의 standard envelope shape 가 깨지지 않음을
    독립적으로 단언한다.
    """
    db_path = tmp_path / "test.db"
    csv_path = tmp_path / "sample.csv"
    csv_path.write_text(
        "symbol,exchange,name,name_en,instrument_type,listed\n"
        "005930,KRX,삼성전자,Samsung Electronics,stock,true\n",
        encoding="utf-8",
    )
    result = _invoke(
        [
            "--format",
            "json",
            "instrument",
            "import",
            str(csv_path),
            "--db-path",
            str(db_path),
        ]
    )
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_standard_envelope(payload), (
        f"instrument import 실제 분기: standard envelope 이어야 한다 "
        f"(mixed-branch awareness). payload={payload!r}"
    )
    assert payload["data"]["count"] == 1
    assert payload["data"]["file"].endswith("sample.csv")
