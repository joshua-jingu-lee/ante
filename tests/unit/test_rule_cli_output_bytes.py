"""rule 3개 명령 × 성공 분기 × {text, json}의 출력 바이트를 고정한다 (#2773).

비교 대상은 stdout과 stderr를 합친 ``result.output`` 전체다. ``rule update`` 는
실행 중인 런타임이 있으면 IPC를 한 번 부르고(IPC 분기), 없으면 부르지 않고
직접 설정을 고친다(직접 실행 분기). 두 분기를 각각 고정한다.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import ExitStack, asynccontextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner, Result

from ante.member.models import Member

_MASTER = Member(
    member_id="test-master",
    type="human",
    role="master",
    org="default",
    name="Test Master",
    status="active",
)


def _rule(rule_id: str, name: str, enabled: bool, priority: int) -> SimpleNamespace:
    return SimpleNamespace(
        rule_id=rule_id,
        name=name,
        enabled=enabled,
        priority=priority,
        description=f"{name} 설명",
    )


_GLOBAL = [_rule("daily_loss_limit", "일일 손실 한도", True, 10)]
_STRATEGY = {"momentum": [_rule("max_position_count", "최대 포지션 수", False, 20)]}

_UPDATE_RESULT: dict[str, Any] = {
    "account_id": "acct-001",
    "rule_type": "max_position_count",
    "rule": {
        "type": "max_position_count",
        "enabled": True,
        "params": {"max_count": 20},
    },
    "dropped_items": [],
}

_DROPPED = [
    {"stored_index": 1, "rule_type": "nope"},
    {"stored_index": 3, "rule_type": None},
    {"stored_index": 4, "rule_type": "a\nb"},
]

_UPDATE = [
    "rule",
    "update",
    "max_position_count",
    "--account",
    "acct-001",
    "--param",
    "max_count=20",
]

_CASES: dict[str, list[str]] = {
    "list_empty": ["rule", "list", "--account", "acct-001"],
    "list_rows": ["rule", "list", "--account", "acct-001"],
    "list_global": ["rule", "list", "--account", "acct-001", "--scope", "global"],
    "list_strategy": ["rule", "list", "--account", "acct-001", "--scope", "strategy"],
    "info": ["rule", "info", "max_position_count", "--account", "acct-001"],
    "update_ipc": list(_UPDATE),
    "update_ipc_no_rule": list(_UPDATE),
    "update_ipc_no_dropped_key": list(_UPDATE),
    "update_ipc_dropped": list(_UPDATE),
    "update_direct": list(_UPDATE),
    "update_direct_dropped": list(_UPDATE),
    "update_direct_disabled": [
        "rule",
        "update",
        "max_position_count",
        "--account",
        "acct-001",
        "--disabled",
        "--params-json",
        '{"max_count": 5}',
    ],
}

_IPC_CALLS = {
    "update_ipc": 1,
    "update_ipc_no_rule": 1,
    "update_ipc_no_dropped_key": 1,
    "update_ipc_dropped": 1,
}


@pytest.fixture(autouse=True)
def _bypass_auth() -> Iterator[None]:
    with patch(
        "ante.cli.main.authenticate_member",
        side_effect=lambda ctx: ctx.obj.update({"member": _MASTER}),
    ):
        yield


class _Initializable:
    def __init__(self, *_: Any, **__: Any) -> None:
        return None

    async def initialize(self) -> None:
        return None


def _invoke_case(
    branch: str, mode: str, *, mix_stderr: bool = True
) -> tuple[Result, AsyncMock, AsyncMock]:
    from ante.cli.main import cli

    empty = branch == "list_empty"
    engine = SimpleNamespace(
        _global_rules=[] if empty else list(_GLOBAL),
        _strategy_rules={} if empty else dict(_STRATEGY),
    )

    @asynccontextmanager
    async def _create_rule_engine(
        account_id: str, *, ctx: Any = None
    ) -> AsyncIterator[tuple[Any, Any]]:
        yield engine, AsyncMock()

    @asynccontextmanager
    async def _open_cli_db(ctx: Any, **_: Any) -> AsyncIterator[AsyncMock]:
        yield AsyncMock()

    ipc_result = dict(_UPDATE_RESULT)
    if branch == "update_ipc_no_rule":
        del ipc_result["rule"]
    if branch == "update_ipc_no_dropped_key":
        del ipc_result["dropped_items"]
    if branch == "update_ipc_dropped":
        ipc_result["dropped_items"] = list(_DROPPED)
    ipc_send = AsyncMock(return_value=ipc_result)
    direct_result = dict(_UPDATE_RESULT)
    if branch == "update_direct_disabled":
        direct_result["rule"] = {
            "type": "max_position_count",
            "enabled": False,
            "params": {"max_count": 5},
        }
    if branch == "update_direct_dropped":
        direct_result["dropped_items"] = list(_DROPPED)
    update = AsyncMock(return_value=direct_result)
    active = branch.startswith("update_ipc")
    args = list(_CASES[branch])
    full_args = ["--format", "json", *args] if mode == "json" else args
    with ExitStack() as stack:
        for target, value in (
            ("ante.cli.commands.rule._create_rule_engine", _create_rule_engine),
            ("ante.cli.commands.rule._load_rules_from_config", lambda engine: None),
            ("ante.cli.commands.rule.open_cli_db", _open_cli_db),
            ("ante.cli.cold_path.is_active_runtime", lambda: active),
            ("ante.cli.commands.ipc_helpers.ipc_send", ipc_send),
            ("ante.rule.config_update.update_account_rule_config", update),
            ("ante.account.service.AccountService", _Initializable),
            ("ante.config.DynamicConfigService", _Initializable),
            ("ante.audit.AuditLogger", _Initializable),
            ("ante.config.Config", SimpleNamespace(load=lambda **_: {})),
        ):
            stack.enter_context(patch(target, new=value))
        result = CliRunner(mix_stderr=mix_stderr).invoke(
            cli, full_args, env={"ANTE_MEMBER_TOKEN": ""}, catch_exceptions=False
        )
    return result, ipc_send, update


_DROPPED_TEXT = (
    "룰 수정 완료: acct-001 max_position_count enabled=True\n"
    "저장값에서 쓸 수 없는 항목 3건을 버림: stored_index=1 rule_type='nope', "
    "stored_index=3 rule_type=None, stored_index=4 rule_type='a\\nb' "
    "(원문은 ante config history accounts.acct-001.rules의 이전 값, "
    "seed에서 읽었으면 설정 파일에 남음)\n"
)
_DROPPED_JSON = (
    "{\n"
    '  "status": "ok",\n'
    '  "message": "",\n'
    '  "data": {\n'
    '    "account_id": "acct-001",\n'
    '    "rule_type": "max_position_count",\n'
    '    "rule": {\n'
    '      "type": "max_position_count",\n'
    '      "enabled": true,\n'
    '      "params": {\n'
    '        "max_count": 20\n'
    "      }\n"
    "    },\n"
    '    "dropped_items": [\n'
    "      {\n"
    '        "stored_index": 1,\n'
    '        "rule_type": "nope"\n'
    "      },\n"
    "      {\n"
    '        "stored_index": 3,\n'
    '        "rule_type": null\n'
    "      },\n"
    "      {\n"
    '        "stored_index": 4,\n'
    '        "rule_type": "a\\nb"\n'
    "      }\n"
    "    ]\n"
    "  }\n"
    "}\n"
)

_RULE_OUTPUT_BYTES: dict[tuple[str, str], str] = {
    ("list_empty", "text"): ("등록된 룰이 없습니다.\n"),
    ("list_empty", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "message": "등록된 룰이 없습니다.",\n'
        '    "rules": []\n'
        "  }\n"
        "}\n"
    ),
    ("list_rows", "text"): (
        "     rule_id |         name |        scope |      enabled |     priority\n"
        "------------------------------------------------------------------------\n"
        "daily_loss_limit |     일일 손실 한도 |       global |         True |       "
        "    10\n"
        "max_position_count |     최대 포지션 수 | strategy:momentum |        False |"
        "           20\n"
    ),
    ("list_rows", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "rules": [\n'
        "      {\n"
        '        "rule_id": "daily_loss_limit",\n'
        '        "name": "일일 손실 한도",\n'
        '        "scope": "global",\n'
        '        "enabled": true,\n'
        '        "priority": 10,\n'
        '        "description": "일일 손실 한도 설명"\n'
        "      },\n"
        "      {\n"
        '        "rule_id": "max_position_count",\n'
        '        "name": "최대 포지션 수",\n'
        '        "scope": "strategy:momentum",\n'
        '        "enabled": false,\n'
        '        "priority": 20,\n'
        '        "description": "최대 포지션 수 설명"\n'
        "      }\n"
        "    ]\n"
        "  }\n"
        "}\n"
    ),
    ("list_global", "text"): (
        "     rule_id |         name |        scope |      enabled |     priority\n"
        "------------------------------------------------------------------------\n"
        "daily_loss_limit |     일일 손실 한도 |       global |         True |       "
        "    10\n"
    ),
    ("list_global", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "rules": [\n'
        "      {\n"
        '        "rule_id": "daily_loss_limit",\n'
        '        "name": "일일 손실 한도",\n'
        '        "scope": "global",\n'
        '        "enabled": true,\n'
        '        "priority": 10,\n'
        '        "description": "일일 손실 한도 설명"\n'
        "      }\n"
        "    ]\n"
        "  }\n"
        "}\n"
    ),
    ("list_strategy", "text"): (
        "     rule_id |         name |        scope |      enabled |     priority\n"
        "------------------------------------------------------------------------\n"
        "max_position_count |     최대 포지션 수 | strategy:momentum |        False |"
        "           20\n"
    ),
    ("list_strategy", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "rules": [\n'
        "      {\n"
        '        "rule_id": "max_position_count",\n'
        '        "name": "최대 포지션 수",\n'
        '        "scope": "strategy:momentum",\n'
        '        "enabled": false,\n'
        '        "priority": 20,\n'
        '        "description": "최대 포지션 수 설명"\n'
        "      }\n"
        "    ]\n"
        "  }\n"
        "}\n"
    ),
    ("info", "text"): (
        "  rule_id        : max_position_count\n"
        "  name           : 최대 포지션 수\n"
        "  scope          : strategy:momentum\n"
        "  enabled        : False\n"
        "  priority       : 20\n"
        "  description    : 최대 포지션 수 설명\n"
    ),
    ("info", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "rule_id": "max_position_count",\n'
        '    "name": "최대 포지션 수",\n'
        '    "scope": "strategy:momentum",\n'
        '    "enabled": false,\n'
        '    "priority": 20,\n'
        '    "description": "최대 포지션 수 설명"\n'
        "  }\n"
        "}\n"
    ),
    ("update_ipc", "text"): (
        "룰 수정 완료: acct-001 max_position_count enabled=True\n"
    ),
    ("update_ipc", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "account_id": "acct-001",\n'
        '    "rule_type": "max_position_count",\n'
        '    "rule": {\n'
        '      "type": "max_position_count",\n'
        '      "enabled": true,\n'
        '      "params": {\n'
        '        "max_count": 20\n'
        "      }\n"
        "    },\n"
        '    "dropped_items": []\n'
        "  }\n"
        "}\n"
    ),
    ("update_ipc_no_rule", "text"): (
        "룰 수정 완료: acct-001 max_position_count enabled=None\n"
    ),
    ("update_ipc_no_rule", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "account_id": "acct-001",\n'
        '    "rule_type": "max_position_count",\n'
        '    "dropped_items": []\n'
        "  }\n"
        "}\n"
    ),
    ("update_direct", "text"): (
        "룰 수정 완료: acct-001 max_position_count enabled=True\n"
    ),
    ("update_direct", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "account_id": "acct-001",\n'
        '    "rule_type": "max_position_count",\n'
        '    "rule": {\n'
        '      "type": "max_position_count",\n'
        '      "enabled": true,\n'
        '      "params": {\n'
        '        "max_count": 20\n'
        "      }\n"
        "    },\n"
        '    "dropped_items": []\n'
        "  }\n"
        "}\n"
    ),
    ("update_direct_disabled", "text"): (
        "룰 수정 완료: acct-001 max_position_count enabled=False\n"
    ),
    ("update_direct_disabled", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "account_id": "acct-001",\n'
        '    "rule_type": "max_position_count",\n'
        '    "rule": {\n'
        '      "type": "max_position_count",\n'
        '      "enabled": false,\n'
        '      "params": {\n'
        '        "max_count": 5\n'
        "      }\n"
        "    },\n"
        '    "dropped_items": []\n'
        "  }\n"
        "}\n"
    ),
    ("update_ipc_no_dropped_key", "text"): (
        "룰 수정 완료: acct-001 max_position_count enabled=True\n"
    ),
    ("update_ipc_no_dropped_key", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "account_id": "acct-001",\n'
        '    "rule_type": "max_position_count",\n'
        '    "rule": {\n'
        '      "type": "max_position_count",\n'
        '      "enabled": true,\n'
        '      "params": {\n'
        '        "max_count": 20\n'
        "      }\n"
        "    }\n"
        "  }\n"
        "}\n"
    ),
    ("update_ipc_dropped", "text"): _DROPPED_TEXT,
    ("update_ipc_dropped", "json"): _DROPPED_JSON,
    ("update_direct_dropped", "text"): _DROPPED_TEXT,
    ("update_direct_dropped", "json"): _DROPPED_JSON,
}


class TestRuleOutputBytes:
    def test_cases_cover_every_branch_and_mode(self) -> None:
        assert set(_RULE_OUTPUT_BYTES) == {
            (branch, mode) for branch in _CASES for mode in ("text", "json")
        }

    @pytest.mark.parametrize(
        ("branch", "mode"), [(b, m) for b in _CASES for m in ("text", "json")]
    )
    def test_output_bytes(self, branch: str, mode: str) -> None:
        result, ipc_send, update = _invoke_case(branch, mode)
        assert result.exit_code == 0, result.output
        assert result.output == _RULE_OUTPUT_BYTES[(branch, mode)]
        assert ipc_send.await_count == _IPC_CALLS.get(branch, 0)
        assert update.await_count == int(branch.startswith("update_direct"))

    @pytest.mark.parametrize(
        ("branch", "mode"), [(b, m) for b in _CASES for m in ("text", "json")]
    )
    def test_success_output_goes_to_stdout_only(self, branch: str, mode: str) -> None:
        result, _, _ = _invoke_case(branch, mode, mix_stderr=False)
        assert result.exit_code == 0, result.output
        assert result.stdout == _RULE_OUTPUT_BYTES[(branch, mode)]
        assert result.stderr == ""

    def test_update_ipc_request(self) -> None:
        _, ipc_send, _ = _invoke_case("update_ipc", "json")
        ipc_send.assert_awaited_once_with(
            "rule.update",
            {
                "account_id": "acct-001",
                "rule_type": "max_position_count",
                "params": {"max_count": 20},
            },
            actor="test-master",
        )
