"""전후 표 도구(``scripts/ipc_request_diff.py``)의 분류와 종료 코드 (#2683 ①).

종료 코드는 하위 프로세스로 판정한다. 분류마다 픽스처 기록 한 쌍을 둔다.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "ipc_request_diff.py"
COMMAND = "demo.run"

OK = {
    "status": "ok",
    "code": None,
    "message": None,
    "result": '{"done": true}',
    "calls": '[["svc.demo.run", ["a1"], {}]]',
}
EXECUTION = {
    "status": "error",
    "code": "EXECUTION_ERROR",
    "message": "'name'",
    "result": "null",
    "calls": "[]",
}
REJECTED = {
    "status": "error",
    "code": "VALIDATION_ERROR",
    "message": "demo.run 인자 검증 실패: name(missing)",
    "result": "null",
    "calls": "[]",
}


EXTRA_REJECTED = "demo.run 인자 검증 실패: zz_extra(extra_forbidden)"
ACCOUNT_REJECTED = "demo.run 인자 검증 실패: account_id(invalid_account_id)"


def _run(
    *argv: str | Path, env: dict[str, str] | None = None, code: str | None = None
) -> tuple[int, str, str]:
    full = {**os.environ, "PYTHONPATH": str(REPO_ROOT / "src"), **(env or {})}
    head = (
        [sys.executable, str(SCRIPT)] if code is None else [sys.executable, "-c", code]
    )
    proc = subprocess.run(
        [*head, *map(str, argv)],
        capture_output=True,
        text=True,
        env=full,
        check=False,
    )
    return proc.returncode, proc.stdout, proc.stderr


def _request(name: str, kind: str, args: Any, **extra: Any) -> dict[str, Any]:
    return {"name": name, "kind": kind, "args": args, **extra}


def _compare(
    tmp_path: Path,
    requests: list[dict[str, Any]],
    before: dict[str, Any],
    after: dict[str, Any],
    *options: str,
    command: str = COMMAND,
    before_again: dict[str, Any] | None = None,
) -> tuple[int, str, str]:
    files = {
        "requests.json": {"commands": {command: requests}},
        "b1.json": {"rows": before, "ratchet": {"ipc_args_reads": 2}},
        "b2.json": {"rows": before if before_again is None else before_again},
        "a.json": {"rows": after, "ratchet": {"ipc_args_reads": 0}},
    }
    for name, data in files.items():
        (tmp_path / name).write_text(json.dumps(data), encoding="utf-8")
    return _run(
        "compare",
        "--requests",
        tmp_path / "requests.json",
        "--before",
        tmp_path / "b1.json",
        "--before",
        tmp_path / "b2.json",
        "--after",
        tmp_path / "a.json",
        *options,
    )


def _count(stdout: str, cls: str) -> int:
    for line in stdout.splitlines():
        if line.startswith(f"{cls} "):
            return int(line.rsplit(" ", 1)[1])
    raise AssertionError(stdout)


CLI = _request("demo.run:cli:0", "cli", {"name": "a1"})
MISSING = _request("demo.run:missing:name", "missing", {}, key="name")


def test_identical_records_pass_with_the_full_report(tmp_path: Path) -> None:
    rows = {"demo.run:cli:0": OK, "demo.run:missing:name": EXECUTION}
    code, out, err = _compare(tmp_path, [CLI, MISSING], rows, rows)
    assert (code, err) == (0, "")
    assert out == (
        "rows: 2\n"
        "같음 2\n"
        "거부로 바뀜 0\n"
        "코드 바뀜 0\n"
        "메시지 바뀜 0\n"
        "다름 0\n"
        "비결정 0\n"
        "code changes:\n"
        "changed rows:\n"
        "different rows:\n"
        "ratchet: ipc_handlers_without_model None -> None, "
        "ipc_args_reads 2 -> 0, cli_direct_ipc_send None -> None\n"
    )


def test_code_change_is_reported_with_its_codes(tmp_path: Path) -> None:
    code, out, _ = _compare(
        tmp_path,
        [CLI, MISSING],
        {"demo.run:cli:0": OK, "demo.run:missing:name": EXECUTION},
        {"demo.run:cli:0": OK, "demo.run:missing:name": REJECTED},
    )
    assert code == 0
    assert _count(out, "코드 바뀜") == 1
    assert "  EXECUTION_ERROR -> VALIDATION_ERROR 1\n" in out
    assert (
        "  코드 바뀜 demo.run:missing:name: EXECUTION_ERROR 'name' -> "
        "VALIDATION_ERROR demo.run 인자 검증 실패: name(missing)\n"
    ) in out


@pytest.mark.parametrize(
    ("before_code", "options", "exit_code"),
    [
        pytest.param("BOT_NOT_FOUND", (), 1, id="outside-the-allowed-set"),
        pytest.param(
            "BOT_NOT_FOUND", ("--allow-code", "BOT_NOT_FOUND"), 0, id="allowed"
        ),
    ],
)
def test_code_change_needs_an_allowed_before_code(
    tmp_path: Path, before_code: str, options: tuple[str, ...], exit_code: int
) -> None:
    code, out, _ = _compare(
        tmp_path,
        [MISSING],
        {"demo.run:missing:name": {**EXECUTION, "code": before_code}},
        {"demo.run:missing:name": REJECTED},
        *options,
    )
    assert code == exit_code
    assert _count(out, "다름") == exit_code


def test_reject_after_a_service_call(tmp_path: Path) -> None:
    extra = _request("demo.run:extra", "extra", {"name": "a1", "zz_extra": "zz-v"})
    code, out, _ = _compare(
        tmp_path,
        [extra],
        {"demo.run:extra": OK},
        {"demo.run:extra": {**REJECTED, "message": EXTRA_REJECTED}},
    )
    assert (code, _count(out, "거부로 바뀜")) == (0, 1)


@pytest.mark.parametrize(
    ("kind", "exit_code"),
    [pytest.param("account", 0, id="account"), pytest.param("value", 1, id="value")],
)
def test_message_change_only_for_account_rows(
    tmp_path: Path, kind: str, exit_code: int
) -> None:
    row = _request("demo.run:x", kind, {"account_id": ""}, key="account_id")
    code, out, _ = _compare(
        tmp_path,
        [row],
        {"demo.run:x": {**REJECTED, "message": "invalid account_id: old"}},
        {"demo.run:x": {**REJECTED, "message": ACCOUNT_REJECTED}},
    )
    assert code == exit_code
    assert _count(out, "메시지 바뀜") == 1 - exit_code


def test_a_changed_cli_row_is_different(tmp_path: Path) -> None:
    after = {**OK, "calls": '[["svc.demo.run", ["a2"], {}]]'}
    code, out, _ = _compare(
        tmp_path, [CLI], {"demo.run:cli:0": OK}, {"demo.run:cli:0": after}
    )
    assert code == 1
    assert "  demo.run:cli:0: a CLI request changed\n" in out


def test_a_rejected_cli_row_is_different(tmp_path: Path) -> None:
    code, out, _ = _compare(
        tmp_path, [CLI], {"demo.run:cli:0": OK}, {"demo.run:cli:0": REJECTED}
    )
    assert (code, _count(out, "다름")) == (1, 1)


def test_a_same_json_type_value_must_stay(tmp_path: Path) -> None:
    row = _request(
        "demo.run:value:name:str5", "value", {"name": "5"}, key="name", same_type=True
    )
    code, out, _ = _compare(
        tmp_path,
        [row],
        {"demo.run:value:name:str5": OK},
        {"demo.run:value:name:str5": REJECTED},
    )
    assert code == 1
    assert "  demo.run:value:name:str5: a value of the CLI JSON type changed\n" in out


def test_a_row_missing_after_is_different(tmp_path: Path) -> None:
    code, out, _ = _compare(
        tmp_path,
        [CLI, MISSING],
        {"demo.run:cli:0": OK, "demo.run:missing:name": EXECUTION},
        {"demo.run:cli:0": OK},
    )
    assert code == 1
    assert "  demo.run:missing:name: missing in a record\n" in out


def test_a_row_only_after_is_an_input_error(tmp_path: Path) -> None:
    code, out, err = _compare(
        tmp_path,
        [CLI],
        {"demo.run:cli:0": OK},
        {"demo.run:cli:0": OK, "demo.run:new": OK},
    )
    assert (code, out) == (2, "")
    assert "rows not in the request set: demo.run:new" in err


def test_unstable_rows_leave_the_comparison(tmp_path: Path) -> None:
    code, out, _ = _compare(
        tmp_path,
        [CLI, MISSING],
        {"demo.run:cli:0": OK, "demo.run:missing:name": EXECUTION},
        {"demo.run:cli:0": OK, "demo.run:missing:name": OK},
        before_again={
            "demo.run:cli:0": OK,
            "demo.run:missing:name": {**EXECUTION, "message": "other"},
        },
    )
    assert code == 0
    assert "비결정 1\n  demo.run:missing:name\n" in out
    assert _count(out, "같음") == 1


def test_an_unstable_cli_row_is_different(tmp_path: Path) -> None:
    code, out, _ = _compare(
        tmp_path,
        [CLI],
        {"demo.run:cli:0": OK},
        {"demo.run:cli:0": OK},
        before_again={"demo.run:cli:0": {**OK, "result": "{}"}},
    )
    assert code == 1
    assert "  demo.run:cli:0: a CLI request is not deterministic\n" in out


def test_a_reflected_value_is_different(tmp_path: Path) -> None:
    row = _request("demo.run:missing:name", "missing", {"tag": "zz-secret"})
    code, out, _ = _compare(
        tmp_path,
        [row],
        {"demo.run:missing:name": EXECUTION},
        {"demo.run:missing:name": {**REJECTED, "message": "bad zz-secret"}},
    )
    assert code == 1
    assert "the after response reflects 'zz-secret'" in out


REGISTRY_SOURCE = """
async def _handle_run(svc, args, actor):
    return {{"name": args["name"], "n": args.get("n", 1), {extra}}}


def register_all_handlers(registry):
    registry.register("demo.run", _handle_run, is_mutating=True)
"""


def _build(
    tmp_path: Path, extra: str, cli_args: list[dict[str, Any]] | None = None
) -> tuple[int, str, str]:
    registry = tmp_path / "src" / "ante" / "ipc" / "registry.py"
    registry.parent.mkdir(parents=True)
    registry.write_text(REGISTRY_SOURCE.format(extra=extra), encoding="utf-8")
    rows = [{"name": "a1", "n": 2.5}] if cli_args is None else cli_args
    cli = [{"command": "demo.run", "args": a, "row": "r"} for a in rows]
    (tmp_path / "cli.json").write_text(json.dumps(cli), encoding="utf-8")
    return _run(
        "--root",
        tmp_path,
        "build",
        "--command",
        "demo.run",
        "--requests",
        "requests.json",
        "--cli-records",
        tmp_path / "cli.json",
    )


def test_build_writes_the_candidates_of_each_read_key(tmp_path: Path) -> None:
    code, out, err = _build(tmp_path, "")
    assert (code, out, err) == (0, "requests: 13 in 1 commands\n", "")
    data = json.loads((tmp_path / "requests.json").read_text(encoding="utf-8"))
    names = [row["name"] for row in data["commands"]["demo.run"]]
    assert names == [
        "demo.run:cli:0",
        "demo.run:value:n:str5",
        "demo.run:value:n:int7",
        "demo.run:value:n:true",
        "demo.run:value:n:null",
        "demo.run:missing:name",
        "demo.run:value:name:str5",
        "demo.run:value:name:int7",
        "demo.run:value:name:true",
        "demo.run:value:name:null",
        "demo.run:extra",
        "demo.run:array",
        "demo.run:nan:n",
    ]
    same = {
        r["name"]: r["same_type"]
        for r in data["commands"]["demo.run"]
        if "same_type" in r
    }
    assert same["demo.run:value:n:int7"] is True
    assert same["demo.run:value:name:str5"] is True
    assert same["demo.run:value:name:int7"] is False


def _same_types(tmp_path: Path) -> dict[str, bool]:
    data = json.loads((tmp_path / "requests.json").read_text(encoding="utf-8"))
    return {
        r["name"]: r["same_type"]
        for r in data["commands"]["demo.run"]
        if "same_type" in r
    }


def test_build_same_type_reads_a_key_sent_only_by_a_later_cli_row(
    tmp_path: Path,
) -> None:
    code, _, err = _build(tmp_path, "", [{"name": "a1"}, {"name": "a1", "n": 2.5}])
    assert (code, err) == (0, "")
    same = _same_types(tmp_path)
    assert same["demo.run:value:n:int7"] is True
    assert same["demo.run:value:n:str5"] is False
    assert same["demo.run:value:n:true"] is False
    assert same["demo.run:value:n:null"] is False


def test_build_same_type_takes_the_json_type_of_every_cli_row(
    tmp_path: Path,
) -> None:
    code, _, err = _build(
        tmp_path, "", [{"name": "a1", "n": 2.5}, {"name": "a1", "n": "x"}]
    )
    assert (code, err) == (0, "")
    same = _same_types(tmp_path)
    assert same["demo.run:value:n:int7"] is True
    assert same["demo.run:value:n:str5"] is True
    assert same["demo.run:value:n:true"] is False
    assert same["demo.run:value:n:null"] is False


def test_build_replaces_a_clock_value_with_a_fixed_marker(tmp_path: Path) -> None:
    rows = [
        {"name": "a1", "expires_at": ""},
        {"name": "a1", "expires_at": "2026-11-25T02:22:59.691054+00:00"},
    ]
    code, _, err = _build(tmp_path, "", rows)
    assert (code, err) == (0, "")
    data = json.loads((tmp_path / "requests.json").read_text(encoding="utf-8"))
    cli = [r["args"] for r in data["commands"]["demo.run"] if r["kind"] == "cli"]
    assert cli == [
        {"name": "a1", "expires_at": ""},
        {"name": "a1", "expires_at": "2030-01-01T00:00:00+00:00"},
    ]


def test_build_keeps_the_cli_key_order(tmp_path: Path) -> None:
    code, _, err = _build(tmp_path, "", [{"name": "a1", "n": 2.5}])
    assert (code, err) == (0, "")
    data = json.loads((tmp_path / "requests.json").read_text(encoding="utf-8"))
    rows = data["commands"]["demo.run"]
    assert list(rows[0]) == ["args", "kind", "name"]
    assert list(rows[0]["args"]) == ["name", "n"]
    assert list(rows[1]) == ["args", "key", "kind", "name", "same_type"]
    assert list(rows[1]["args"]) == ["name", "n"]


def test_build_rejects_another_use_of_the_args(tmp_path: Path) -> None:
    code, out, err = _build(tmp_path, '"all": dict(args)')
    assert (code, out) == (2, "")
    assert "unsupported use of args: dict(args)" in err


def test_record_dispatches_the_committed_request_set(tmp_path: Path) -> None:
    out_path = tmp_path / "record.json"
    code, out, err = _run("record", "--out", out_path)
    assert (code, err) == (0, "")
    data = json.loads(out_path.read_text(encoding="utf-8"))
    assert len(data["rows"]) > 0
    assert out == f"recorded: {len(data['rows'])} rows\n"
    assert data["rows"]["strategy.set_status:cli:0"] == {
        "status": "ok",
        "code": None,
        "message": None,
        "result": '{"status": "archived", "strategy_id": "s1"}',
        "calls": (
            '[["svc.strategy_registry.update_status", '
            '["s1", "<StrategyStatus.ARCHIVED: \'archived\'>"], {}], '
            '["svc.audit_logger.log", [], {"action": "strategy.set_status", '
            '"detail": "status=archived", "ip": "", "member_id": "ipc-diff", '
            '"resource": "strategy:s1"}]]'
        ),
    }


def test_a_narrowed_field_may_change_code(tmp_path: Path) -> None:
    row = _request(
        "strategy.set_status:value:status:str5",
        "value",
        {"strategy_id": "s1", "status": "5"},
        key="status",
        same_type=True,
    )
    code, out, _ = _compare(
        tmp_path,
        [row],
        {"strategy.set_status:value:status:str5": EXECUTION},
        {
            "strategy.set_status:value:status:str5": {
                **REJECTED,
                "message": "strategy.set_status 인자 검증 실패: status(literal_error)",
            }
        },
        command="strategy.set_status",
    )
    assert (code, _count(out, "코드 바뀜")) == (0, 1)


@pytest.mark.parametrize(
    ("command", "key", "args", "after", "cls", "exit_code"),
    [
        pytest.param(
            "bot.list",
            "account_id",
            {"account_id": "5"},
            "bot.list 인자 검증 실패: account_id(invalid_account_id)",
            "메시지 바뀜",
            0,
            id="nullable-account-id",
        ),
        pytest.param(
            "bot.start",
            "bot_id",
            {"bot_id": "5"},
            "bot.start 인자 검증 실패: bot_id(string_type)",
            "다름",
            1,
            id="plain-str",
        ),
    ],
)
def test_a_nullable_narrowed_field_may_change_message(
    tmp_path: Path,
    command: str,
    key: str,
    args: dict[str, Any],
    after: str,
    cls: str,
    exit_code: int,
) -> None:
    name = f"{command}:value:{key}:str5"
    row = _request(name, "value", args, key=key, same_type=True)
    before = {**REJECTED, "message": "invalid account_id: '5'"}
    code, out, _ = _compare(
        tmp_path,
        [row],
        {name: before},
        {name: {**REJECTED, "message": after}},
        command=command,
    )
    assert (code, _count(out, cls)) == (exit_code, 1)


@pytest.mark.parametrize(
    ("message", "exit_code"),
    [
        pytest.param(EXTRA_REJECTED, 0, id="model-rejection"),
        pytest.param("invalid account_id", 1, id="handler-validation-error"),
    ],
)
def test_reject_needs_the_request_model_message(
    tmp_path: Path, message: str, exit_code: int
) -> None:
    extra = _request("demo.run:extra", "extra", {"name": "a1", "zz_extra": "zz-v"})
    code, out, _ = _compare(
        tmp_path,
        [extra],
        {"demo.run:extra": OK},
        {"demo.run:extra": {**REJECTED, "message": message}},
    )
    assert (code, _count(out, "거부로 바뀜"), _count(out, "다름")) == (
        exit_code,
        1 - exit_code,
        exit_code,
    )


@pytest.mark.parametrize(
    ("message", "exit_code"),
    [
        pytest.param(REJECTED["message"], 0, id="model-rejection"),
        pytest.param("name is required", 1, id="handler-validation-error"),
    ],
)
def test_code_change_needs_the_request_model_message(
    tmp_path: Path, message: str, exit_code: int
) -> None:
    code, out, _ = _compare(
        tmp_path,
        [MISSING],
        {"demo.run:missing:name": EXECUTION},
        {"demo.run:missing:name": {**REJECTED, "message": message}},
    )
    assert (code, _count(out, "코드 바뀜"), _count(out, "다름")) == (
        exit_code,
        1 - exit_code,
        exit_code,
    )


@pytest.mark.parametrize(
    ("before_again", "exit_code"),
    [
        pytest.param(
            {"demo.run:cli:0": OK, "demo.run:missing:name": EXECUTION},
            0,
            id="same-rows",
        ),
        pytest.param({"demo.run:cli:0": OK}, 2, id="a-row-missing-in-the-second"),
    ],
)
def test_before_records_need_the_same_rows(
    tmp_path: Path, before_again: dict[str, Any], exit_code: int
) -> None:
    rows = {"demo.run:cli:0": OK, "demo.run:missing:name": EXECUTION}
    code, _out, err = _compare(
        tmp_path, [CLI, MISSING], rows, rows, before_again=before_again
    )
    assert code == exit_code
    if exit_code == 2:
        assert "the before records differ in rows: demo.run:missing:name" in err


def _fake_dirs(tmp_path: Path) -> dict[str, str]:
    env = {}
    for key in ("ANTE_CONFIG_DIR", "HOME"):
        path = tmp_path / f"user-{key.lower()}"
        path.mkdir()
        env[key] = str(path)
    return env


def test_record_does_not_touch_the_user_directories(tmp_path: Path) -> None:
    env = _fake_dirs(tmp_path)
    code, _out, err = _run("record", "--out", tmp_path / "record.json", env=env)
    assert (code, err) == (0, "")
    assert [list(Path(path).iterdir()) for path in env.values()] == [[], []]


SEEN_ENV = """
import json, os, sys
sys.argv[0] = {script!r}
sys.path.insert(0, os.path.dirname({script!r}))
import ipc_request_diff as tool
KEYS = ("ANTE_CONFIG_DIR", "HOME")
def _seen(args):
    seen = {{k: os.environ[k] for k in KEYS}}
    exist = [os.path.isdir(v) for v in seen.values()]
    print(json.dumps({{"seen": seen, "exist": exist}}))
    return 0
tool.cmd_record = _seen
code = tool.main(sys.argv[1:])
print(json.dumps({{"after": {{k: os.environ[k] for k in KEYS}}}}))
sys.exit(code)
"""


def test_build_and_record_run_in_a_temporary_config_and_home(tmp_path: Path) -> None:
    env = _fake_dirs(tmp_path)
    code, out, err = _run(
        "record",
        "--out",
        tmp_path / "unused.json",
        env=env,
        code=SEEN_ENV.format(script=str(SCRIPT)),
    )
    assert (code, err) == (0, "")
    first, second = (json.loads(line) for line in out.splitlines())
    seen = first["seen"]
    assert first["exist"] == [True, True]
    assert all(seen[key] != env[key] for key in env)
    assert all(not Path(path).exists() for path in seen.values())
    assert second == {"after": env}
