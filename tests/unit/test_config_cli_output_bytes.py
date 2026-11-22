"""config 3개 명령 × 성공 분기 × {text, json}의 출력 바이트를 고정한다 (#2773).

비교 대상은 stdout과 stderr를 합친 ``result.output`` 전체다. ``config set`` 만
IPC를 한 번 부르고 나머지는 부르지 않는다(사례마다 호출 횟수를 단언한다).
설정 값에 든 비밀값 모양의 문자열은 마스킹 없이 지금처럼 stdout에 나간다.
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

_SECRET = "tok-config-fixture-0001"

_DEFAULTS: dict[str, Any] = {
    "system.log_level": "INFO",
    "rules.daily_loss_limit": 0.05,
}

_STATIC: dict[str, Any] = {"system.log_level": "DEBUG", "db.path": "db/ante.db"}

_DYNAMIC_ROWS: list[dict[str, Any]] = [
    {"key": "notification.webhook", "value": f'"{_SECRET}"', "category": "x"},
    {"key": "risk.max_orders", "value": "12", "category": "risk"},
]

_HISTORY: list[dict[str, Any]] = [
    {
        "id": 2,
        "key": "risk.max_orders",
        "old_value": "10",
        "new_value": "12",
        "changed_by": "test-master",
        "changed_at": "2026-01-02 09:00:00",
    },
    {
        "id": 1,
        "key": "risk.max_orders",
        "old_value": None,
        "new_value": "10",
        "changed_by": "agent-1",
        "changed_at": "2026-01-01 08:30:00",
    },
]

_CASES: dict[str, list[str]] = {
    "get_dynamic": ["config", "get", "notification.webhook"],
    "get_static": ["config", "get", "system.log_level"],
    "get_all": ["config", "get"],
    "get_all_empty": ["config", "get"],
    "set": ["config", "set", "risk.max_orders", "12"],
    "history_empty": ["config", "history", "risk.max_orders"],
    "history_rows": ["config", "history", "risk.max_orders", "--limit", "5"],
}

_IPC_CALLS = {"set": 1}


@pytest.fixture(autouse=True)
def _bypass_auth() -> Iterator[None]:
    with patch(
        "ante.cli.main.authenticate_member",
        side_effect=lambda ctx: ctx.obj.update({"member": _MASTER}),
    ):
        yield


def _invoke_case(
    branch: str, mode: str, *, mix_stderr: bool = True
) -> tuple[Result, AsyncMock]:
    from ante.cli.main import cli

    empty = branch == "get_all_empty"
    static_config = SimpleNamespace(
        get=lambda key, default=None: _STATIC.get(key, default)
    )
    dynamic = SimpleNamespace(
        exists=AsyncMock(side_effect=lambda key: key == "notification.webhook"),
        get=AsyncMock(return_value=_SECRET),
        get_history=AsyncMock(
            return_value=[] if branch == "history_empty" else list(_HISTORY)
        ),
    )
    db = SimpleNamespace(
        fetch_all=AsyncMock(return_value=[] if empty else list(_DYNAMIC_ROWS))
    )

    @asynccontextmanager
    async def _create_services(
        ctx: Any = None,
    ) -> AsyncIterator[tuple[Any, Any, Any]]:
        yield static_config, dynamic, db

    ipc_send = AsyncMock(return_value={"key": "risk.max_orders", "value": "12"})
    args = list(_CASES[branch])
    full_args = ["--format", "json", *args] if mode == "json" else args
    with ExitStack() as stack:
        for target, value in (
            ("ante.cli.commands.config._create_services", _create_services),
            ("ante.config.defaults.DEFAULTS", {} if empty else dict(_DEFAULTS)),
            ("ante.cli.commands.ipc_helpers.ipc_send", ipc_send),
        ):
            stack.enter_context(patch(target, new=value))
        result = CliRunner(mix_stderr=mix_stderr).invoke(
            cli, full_args, env={"ANTE_MEMBER_TOKEN": ""}, catch_exceptions=False
        )
    return result, ipc_send


_CONFIG_OUTPUT_BYTES: dict[tuple[str, str], str] = {
    ("get_dynamic", "text"): (
        "  notification.webhook = tok-config-fixture-0001 (source: dynamic)\n"
    ),
    ("get_dynamic", "json"): (
        "{\n"
        '  "key": "notification.webhook",\n'
        '  "value": "tok-config-fixture-0001",\n'
        '  "source": "dynamic"\n'
        "}\n"
    ),
    ("get_static", "text"): ("  system.log_level = DEBUG (source: static)\n"),
    ("get_static", "json"): (
        "{\n"
        '  "key": "system.log_level",\n'
        '  "value": "DEBUG",\n'
        '  "source": "static"\n'
        "}\n"
    ),
    ("get_all", "text"): (
        "  rules.daily_loss_limit                   = 0.05                 (static)\n"
        "  system.log_level                         = DEBUG                (static)\n"
        "  notification.webhook                     = tok-config-fixture-0001 (dynami"
        "c)\n"
        "  risk.max_orders                          = 12                   (dynamic)"
        "\n"
    ),
    ("get_all", "json"): (
        "{\n"
        '  "configs": [\n'
        "    {\n"
        '      "key": "rules.daily_loss_limit",\n'
        '      "value": 0.05,\n'
        '      "source": "static"\n'
        "    },\n"
        "    {\n"
        '      "key": "system.log_level",\n'
        '      "value": "DEBUG",\n'
        '      "source": "static"\n'
        "    },\n"
        "    {\n"
        '      "key": "notification.webhook",\n'
        '      "value": "tok-config-fixture-0001",\n'
        '      "source": "dynamic"\n'
        "    },\n"
        "    {\n"
        '      "key": "risk.max_orders",\n'
        '      "value": 12,\n'
        '      "source": "dynamic"\n'
        "    }\n"
        "  ]\n"
        "}\n"
    ),
    ("get_all_empty", "text"): ("  (설정 없음)\n"),
    ("get_all_empty", "json"): ('{\n  "configs": []\n}\n'),
    ("set", "text"): ("설정 변경 완료: risk.max_orders = 12\n"),
    ("set", "json"): (
        '{\n  "status": "success",\n  "key": "risk.max_orders",\n  "value": "12"\n}\n'
    ),
    ("history_empty", "text"): ("  'risk.max_orders'에 대한 변경 이력이 없습니다.\n"),
    ("history_empty", "json"): ('{\n  "key": "risk.max_orders",\n  "history": []\n}\n'),
    ("history_rows", "text"): (
        "  변경 이력: risk.max_orders (최근 5건)\n"
        "  시각                       변경자              이전값                  → "
        "새값                  \n"
        "  --------------------------------------------------------------------------"
        "----------\n"
        "  2026-01-02 09:00:00      test-master      10                   → 12       "
        "           \n"
        "  2026-01-01 08:30:00      agent-1          (없음)                 → 10     "
        "             \n"
    ),
    ("history_rows", "json"): (
        "{\n"
        '  "key": "risk.max_orders",\n'
        '  "history": [\n'
        "    {\n"
        '      "id": 2,\n'
        '      "key": "risk.max_orders",\n'
        '      "old_value": "10",\n'
        '      "new_value": "12",\n'
        '      "changed_by": "test-master",\n'
        '      "changed_at": "2026-01-02 09:00:00"\n'
        "    },\n"
        "    {\n"
        '      "id": 1,\n'
        '      "key": "risk.max_orders",\n'
        '      "old_value": null,\n'
        '      "new_value": "10",\n'
        '      "changed_by": "agent-1",\n'
        '      "changed_at": "2026-01-01 08:30:00"\n'
        "    }\n"
        "  ]\n"
        "}\n"
    ),
}


class TestConfigOutputBytes:
    def test_cases_cover_every_branch_and_mode(self) -> None:
        assert set(_CONFIG_OUTPUT_BYTES) == {
            (branch, mode) for branch in _CASES for mode in ("text", "json")
        }

    @pytest.mark.parametrize(
        ("branch", "mode"), [(b, m) for b in _CASES for m in ("text", "json")]
    )
    def test_output_bytes(self, branch: str, mode: str) -> None:
        result, ipc_send = _invoke_case(branch, mode)
        assert result.exit_code == 0, result.output
        assert result.output == _CONFIG_OUTPUT_BYTES[(branch, mode)]
        assert ipc_send.await_count == _IPC_CALLS.get(branch, 0)

    @pytest.mark.parametrize(
        ("branch", "mode"), [(b, m) for b in _CASES for m in ("text", "json")]
    )
    def test_success_output_goes_to_stdout_only(self, branch: str, mode: str) -> None:
        result, _ = _invoke_case(branch, mode, mix_stderr=False)
        assert result.exit_code == 0, result.output
        assert result.stdout == _CONFIG_OUTPUT_BYTES[(branch, mode)]
        assert result.stderr == ""

    def test_set_sends_key_and_value_once(self) -> None:
        _, ipc_send = _invoke_case("set", "json")
        ipc_send.assert_awaited_once_with(
            "config.set", {"key": "risk.max_orders", "value": "12"}, actor="test-master"
        )

    @pytest.mark.parametrize(
        ("branch", "mode"),
        [(b, m) for b in ("get_dynamic", "get_all") for m in ("text", "json")],
    )
    def test_secret_value_appears_once_on_stdout(self, branch: str, mode: str) -> None:
        result, _ = _invoke_case(branch, mode, mix_stderr=False)
        assert result.stdout.count(_SECRET) == 1
        assert _SECRET not in result.stderr
