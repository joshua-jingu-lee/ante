"""Rule CLI success output ↔ registry OutputContract drift lock (#1847 sub-PR 8).

본 모듈은 :data:`ante.contracts.cli_registry.CLI_COMMAND_REGISTRY` 에 등록된
rule 도메인 3 leaf 의 ``OutputContract`` 와 ``ante rule ... --format json``
실제 출력 envelope shape 사이의 drift 를 lock 한다.

#1846 / #1847 sub-PR 1-7 1:1 동형 패턴. drift 모델:

- ``envelope="standard"`` entry → CLI success envelope ``{status: "ok",
  message, data}`` (envelopes.md SSOT). ``fmt.success(...)`` callsite 가
  dump 한다.
- ``envelope="raw_legacy"`` entry → JSON mode 에서 ``fmt.output(...)`` 또는
  ``fmt.table(...)`` 으로 평면 dict 또는 row list 를 그대로 dump 한다
  (standard envelope 의 3 키 셋이 동시에 부재 또는 ``status != "ok"``).

본 PR 은 ``rule.py`` 본문을 *바꾸지 않으며*, registry entry 가 실제
callsite shape 와 일치함을 단순 lock 만 한다. callsite shape 가 drift
하면 본 test 가 즉시 FAIL 한다.

``rule update`` 는 IPC 우선 + cold_path fallback 구조 (``is_active_runtime()``
분기로 ``ipc_send`` 호출, 비활성 시 ``update_account_rule_config`` 직접
호출) 다. 본 drift test 는 IPC 분기를 강제로 success path 로 mock 해
success envelope 단언만 한다 — fallback 분기 cover 는 후속 PR 책임.

6 시나리오 (registry sanity +1 + list empty +1 + list non-empty +1 +
info found +1 + info not-found는 error라 제외 + update success +1 +
update payload shape +1):

0. registry sanity — rule 3 entries 의 envelope 분류기 범위 내.
1. ``list`` empty (account 존재) → ``raw_legacy`` (``{message, rules: []}``)
2. ``list`` non-empty (config 로딩) → ``raw_legacy`` (``{rules: [...]}``)
3. ``info`` found → ``raw_legacy`` (``{rule_id, name, ...}``)
4. ``update`` IPC success → ``raw_legacy`` (``{account_id, rule, ...}``)
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


def test_registry_rule_entries_envelopes_classified() -> None:
    """rule 3 entry 의 envelope 이 ``standard`` 또는 ``raw_legacy`` 만 사용."""
    accepted = {"standard", "raw_legacy"}
    rule_entries = [
        (path, contract)
        for path, contract in CLI_COMMAND_REGISTRY.items()
        if path[:1] == ("rule",)
    ]
    assert len(rule_entries) == 3, (
        f"rule 3 entries 가 모두 등록되어야 한다. 실제: {len(rule_entries)}"
    )
    for path, contract in rule_entries:
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
    """``ante --format json rule ...`` 를 실행하고 결과를 반환한다."""
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


# ── account 생성 helper (rule list/info 는 account 존재 검증을 수행) ────


def _seed_account(config_dir: Path, account_id: str = "acct-001") -> Path:
    """rule list/info 가 요구하는 account 가 존재하는 DB 를 생성한다.

    ``_create_rule_engine`` (rule.py:91-103) 은 ``SELECT 1 FROM accounts``
    로 lightweight 존재 검증을 수행하며 미존재 시 ``AccountNotFoundError``
    를 raise 한다. ``AccountService.initialize()`` 를 한 번 호출해 schema
    DDL 만 적용하고, 직접 INSERT 로 account_id 단일 row 를 시드한다
    (``AccountService.create`` 는 cold-path guard 와 credentials 정책
    검증을 수반하므로 본 fixture 의 minimal seeding 에는 적합하지 않다).
    """
    import asyncio

    from ante.account.service import AccountService
    from ante.core.database import Database
    from ante.eventbus.bus import EventBus

    (config_dir / "db").mkdir(parents=True, exist_ok=True)
    db_path = config_dir / "db" / "ante.db"

    async def _seed() -> None:
        db = Database(str(db_path))
        await db.connect()
        try:
            eventbus = EventBus()
            svc = AccountService(db=db, eventbus=eventbus)
            # initialize() 가 ``accounts`` schema DDL 만 보장하고, 본 fixture
            # 는 후속 INSERT 로 single test row 를 시드한다.
            await svc.initialize()
            await db.execute(
                "INSERT INTO accounts ("
                "  account_id, name, exchange, currency, broker_type, "
                "  trading_mode, credentials, broker_config, status"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    account_id,
                    "Test Account",
                    "KRX",
                    "KRW",
                    "test",
                    "virtual",
                    "{}",
                    "{}",
                    "active",
                ),
            )
        finally:
            await db.close()

    asyncio.run(_seed())
    return db_path


# ── 1. list empty → raw_legacy ────────────────────────────────────────────


def test_rule_list_empty_envelope_matches_raw_legacy(tmp_path: Path) -> None:
    """``rule list`` empty (account 존재): ``{message, rules: []}`` 평면.

    rule.py:224: ``if not result: fmt.output({"message": ..., "rules": []})``.
    account 는 시드하지만 룰 설정 파일이 없으므로 ``_collect_rules`` 가
    빈 리스트 반환.
    """
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    _seed_account(config_dir)

    result = _invoke(
        [
            "--config-dir",
            str(config_dir),
            "--format",
            "json",
            "rule",
            "list",
            "--account",
            "acct-001",
        ]
    )
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_raw_legacy_payload(payload), (
        f"rule list empty: standard envelope 아님. payload={payload!r}"
    )
    assert payload == {"message": "등록된 룰이 없습니다.", "rules": []}


# ── 2. list non-empty → raw_legacy ────────────────────────────────────────


def test_rule_list_non_empty_envelope_matches_raw_legacy(tmp_path: Path) -> None:
    """``rule list`` non-empty: ``{rules: [...]}`` 평면.

    rule.py:228: ``if fmt.is_json: fmt.output({"rules": result})``.
    ``rules.global`` 을 system.toml 에 설정해 ``RuleEngine`` 이 로드하도록
    강제한다.
    """
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    _seed_account(config_dir)

    # rules.global 을 inline 으로 정의해 RuleEngine.load_rules_from_config 가
    # 1 개 룰을 로드하도록 한다.
    # ``trading_hours`` 는 ``RULE_REGISTRY`` (engine.py:240-247) 에 등재된
    # 6 rule type 중 하나로, 본 fixture 가 RuleEngine 에 정상 로드된다.
    (config_dir / "system.toml").write_text(
        "[[rules.global]]\n"
        'id = "trading_hours"\n'
        'name = "거래 시간 제한"\n'
        'type = "trading_hours"\n'
        "enabled = true\n"
        "priority = 100\n"
        'description = "test rule"\n'
        "\n"
        "[rules.global.params]\n"
        'start = "09:00"\n'
        'end = "15:30"\n',
        encoding="utf-8",
    )

    result = _invoke(
        [
            "--config-dir",
            str(config_dir),
            "--format",
            "json",
            "rule",
            "list",
            "--account",
            "acct-001",
        ]
    )
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_raw_legacy_payload(payload), (
        f"rule list non-empty: standard envelope 아님. payload={payload!r}"
    )
    assert "rules" in payload
    assert isinstance(payload["rules"], list)
    assert len(payload["rules"]) >= 1
    first = payload["rules"][0]
    assert "rule_id" in first
    assert "scope" in first
    assert "enabled" in first


# ── 3. info found → raw_legacy ─────────────────────────────────────────────


def test_rule_info_found_envelope_matches_raw_legacy(tmp_path: Path) -> None:
    """``rule info <rule_id>`` found: ``{rule_id, name, ...}`` 평면.

    rule.py:276: ``if fmt.is_json: fmt.output(result)``. 단일 룰 정보의
    평면 detail dict.
    """
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    _seed_account(config_dir)

    # ``trading_hours`` 는 ``RULE_REGISTRY`` (engine.py:240-247) 에 등재된
    # 6 rule type 중 하나로, 본 fixture 가 RuleEngine 에 정상 로드된다.
    (config_dir / "system.toml").write_text(
        "[[rules.global]]\n"
        'id = "trading_hours"\n'
        'name = "거래 시간 제한"\n'
        'type = "trading_hours"\n'
        "enabled = true\n"
        "priority = 100\n"
        'description = "test rule"\n'
        "\n"
        "[rules.global.params]\n"
        'start = "09:00"\n'
        'end = "15:30"\n',
        encoding="utf-8",
    )

    result = _invoke(
        [
            "--config-dir",
            str(config_dir),
            "--format",
            "json",
            "rule",
            "info",
            "trading_hours",
            "--account",
            "acct-001",
        ]
    )
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_raw_legacy_payload(payload), (
        f"rule info found: standard envelope 아님. payload={payload!r}"
    )
    assert payload["rule_id"] == "trading_hours"
    assert "name" in payload
    assert "scope" in payload
    assert payload["enabled"] is True


# ── 4. update IPC success → raw_legacy ─────────────────────────────────────


def test_rule_update_ipc_envelope_matches_raw_legacy() -> None:
    """``rule update`` IPC: ``fmt.output(result)`` 평면 dict.

    rule.py:412: ``if fmt.is_json: fmt.output(result)``. IPC success 분기를
    강제로 mock — ``is_active_runtime`` True, ``ipc_send`` 가 평면 response
    반환.
    """
    ipc_response = {
        "account_id": "acct-001",
        "rule_type": "max_position_count",
        "rule": {
            "type": "max_position_count",
            "enabled": True,
            "params": {"max_count": 20},
        },
        "changed_by": "test-master",
    }
    with (
        patch(
            "ante.cli.cold_path.is_active_runtime",
            return_value=True,
        ),
        patch(
            "ante.cli.commands.ipc_helpers.ipc_send",
            new=AsyncMock(return_value=ipc_response),
        ),
    ):
        result = _invoke(
            [
                "--format",
                "json",
                "rule",
                "update",
                "max_position_count",
                "--account",
                "acct-001",
                "--enabled",
                "--param",
                "max_count=20",
            ]
        )
    assert result.exit_code == 0, result.output

    payload = _load_json_payload(result.output)
    assert _is_raw_legacy_payload(payload), (
        f"rule update IPC: standard envelope 아님. payload={payload!r}"
    )
    assert payload["account_id"] == "acct-001"
    assert payload["rule_type"] == "max_position_count"
    assert payload["rule"]["enabled"] is True
    assert payload["rule"]["params"]["max_count"] == 20
