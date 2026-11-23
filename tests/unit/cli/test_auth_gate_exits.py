"""인증·DB 암호화 키 관문의 출구 특성 테스트 (#2738 ⑧-3).

관문 출구 11곳(``authenticate_member``·``require_auth``·``require_master`` 둘·
``require_scope`` 둘·``enforce_scope`` 둘·암호화 키 관문·invoke 단계 관문·
callback 단계 관문)의 종료 코드·stdout·stderr를 바이트로 잠근다. 두 모드와
``--format``의 자리(루트·하위 명령·``=`` 형식·잘못된 값·``--`` 뒤)를 덮는다.

가장 중요한 불변식: 관문이 막는 모든 경우에 명령 본문이 실행되지 않는다.
실제 ``cli``의 셀은 본문의 첫 호출(``get_formatter``, data는
``resolve_data_path``)을 감시하고, 하네스의
셀은 관문 하나만 남긴 leaf로 본문 호출 기록이 비었음을 단언한다.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

import click
import pytest
from click.testing import CliRunner, Result
from cryptography.fernet import Fernet

from ante.cli.formatter import OutputFormatter, format_option
from ante.cli.main import cli
from ante.cli.middleware import (
    AuthenticatedGroup,
    enforce_scope,
    require_auth,
    require_master,
    require_scope,
)
from ante.member.models import Member, MemberRole, MemberType

_MASTER = Member(
    member_id="gate-master",
    type=MemberType.HUMAN,
    role=MemberRole.MASTER,
    org="default",
    name="Gate Master",
    status="active",
    scopes=[],
)
_AGENT = Member(
    member_id="gate-agent",
    type=MemberType.AGENT,
    role=MemberRole.DEFAULT,
    org="default",
    name="Gate Agent",
    status="active",
    scopes=["data:read"],
)

_REQ = "인증이 필요합니다. ANTE_MEMBER_TOKEN 환경변수를 설정해 주세요."
_FAILED = "인증 실패: 토큰이 유효하지 않습니다"
_MASTER_ONLY = "이 작업은 master 권한이 필요합니다."
_KEY_MISSING = (
    "ANTE_DB_ENCRYPTION_KEY 환경변수가 설정되지 않았습니다. "
    "`ante init` 또는 `secrets.env` 의 키 행을 확인하세요."
)
_KEY_INVALID = (
    "ANTE_DB_ENCRYPTION_KEY 형식이 유효하지 않습니다 "
    "(Fernet.generate_key() 출력 형식이어야 합니다)."
)


def _scope_msg(scopes: str) -> str:
    return f"권한이 부족합니다. 필요 권한: {scopes}"


def _json(code: str, message: str) -> str:
    import json

    return json.dumps({"status": "error", "code": code, "message": message}) + "\n"


@dataclass(frozen=True)
class Setup:
    """관문 앞의 상태. ``member``는 토큰이 판정된 결과다."""

    token: bool = False
    member: Member | None = None
    auth_error: str | None = None
    key: str = "valid"
    gate_off: bool = False


@pytest.fixture()
def env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Path]:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.setenv("ANTE_CONFIG_DIR", str(config_dir))
    monkeypatch.delenv("ANTE_MEMBER_TOKEN", raising=False)
    monkeypatch.setenv("ANTE_TOKEN_FILE", str(tmp_path / "absent.token"))
    yield config_dir


def _apply(monkeypatch: pytest.MonkeyPatch, setup: Setup) -> None:
    if setup.token:
        monkeypatch.setenv("ANTE_MEMBER_TOKEN", "ante_ak_gate")
    if setup.key == "missing":
        monkeypatch.delenv("ANTE_DB_ENCRYPTION_KEY", raising=False)
    elif setup.key == "invalid":
        monkeypatch.setenv("ANTE_DB_ENCRYPTION_KEY", "not-a-fernet-key")
    else:
        monkeypatch.setenv("ANTE_DB_ENCRYPTION_KEY", Fernet.generate_key().decode())

    def _fake_auth(token: str, db_path: str) -> Member:
        if setup.auth_error is not None:
            raise PermissionError(setup.auth_error)
        assert setup.member is not None
        return setup.member

    monkeypatch.setattr("ante.cli.middleware._run_authenticate", _fake_auth)
    if setup.gate_off:
        monkeypatch.setattr(
            AuthenticatedGroup,
            "_should_invoke_auth_gate",
            lambda self, ctx, all_args, path: False,
        )


def _invoke(group: click.Group, args: list[str]) -> Result:
    return CliRunner(mix_stderr=False).invoke(group, args)


# ── 실제 cli의 셀 ───────────────────────────────────────────────────────────

_NO_TOKEN = Setup()
_BAD_TOKEN = Setup(token=True, auth_error="토큰이 유효하지 않습니다")
_AGENT_TOKEN = Setup(token=True, member=_AGENT)
_MASTER_TOKEN = Setup(token=True, member=_MASTER)
_KEY_MISSING_SETUP = Setup(token=True, member=_MASTER, key="missing")
_KEY_INVALID_SETUP = Setup(token=True, member=_MASTER, key="invalid")

_TEXT = "text"
_JSON = "json"


@dataclass(frozen=True)
class Cell:
    """실제 ``cli`` 한 호출. ``out``은 stdout이 JSON 봉투인지 stderr 줄인지다."""

    id: str
    args: tuple[str, ...]
    setup: Setup
    module: str
    out: str
    code: str
    message: str


_ACCOUNT = "ante.cli.commands.account"
_MEMBER = "ante.cli.commands.member"
_DATA = "ante.cli.commands.data"
_BODY_FIRST_CALL = {_DATA: "resolve_data_path"}

_CELLS: tuple[Cell, ...] = (
    Cell(
        "no-token-root-text",
        ("account", "list"),
        _NO_TOKEN,
        _ACCOUNT,
        _TEXT,
        "auth_required",
        _REQ,
    ),
    Cell(
        "no-token-root-format-text",
        ("--format", "text", "account", "list"),
        _NO_TOKEN,
        _ACCOUNT,
        _TEXT,
        "auth_required",
        _REQ,
    ),
    Cell(
        "no-token-root-json",
        ("--format", "json", "account", "list"),
        _NO_TOKEN,
        _ACCOUNT,
        _JSON,
        "auth_required",
        _REQ,
    ),
    Cell(
        "no-token-root-json-eq",
        ("--format=json", "account", "list"),
        _NO_TOKEN,
        _ACCOUNT,
        _JSON,
        "auth_required",
        _REQ,
    ),
    Cell(
        "no-token-sub-json",
        ("account", "list", "--format", "json"),
        _NO_TOKEN,
        _ACCOUNT,
        _JSON,
        "auth_required",
        _REQ,
    ),
    Cell(
        "no-token-sub-json-eq",
        ("account", "list", "--format=json"),
        _NO_TOKEN,
        _ACCOUNT,
        _JSON,
        "auth_required",
        _REQ,
    ),
    Cell(
        "no-token-root-json-sub-text",
        ("--format", "json", "account", "list", "--format", "text"),
        _NO_TOKEN,
        _ACCOUNT,
        _TEXT,
        "auth_required",
        _REQ,
    ),
    Cell(
        "no-token-sub-xml",
        ("account", "list", "--format", "xml"),
        _NO_TOKEN,
        _ACCOUNT,
        _TEXT,
        "auth_required",
        _REQ,
    ),
    Cell(
        "no-token-after-dashdash",
        ("account", "info", "--", "--format", "json"),
        _NO_TOKEN,
        _ACCOUNT,
        _JSON,
        "auth_required",
        _REQ,
    ),
    Cell(
        "bad-token-root-text",
        ("account", "list"),
        _BAD_TOKEN,
        _ACCOUNT,
        _TEXT,
        "auth_failed",
        _FAILED,
    ),
    Cell(
        "bad-token-root-json",
        ("--format", "json", "account", "list"),
        _BAD_TOKEN,
        _ACCOUNT,
        _JSON,
        "auth_failed",
        _FAILED,
    ),
    Cell(
        "bad-token-sub-json",
        ("account", "list", "--format", "json"),
        _BAD_TOKEN,
        _ACCOUNT,
        _JSON,
        "auth_failed",
        _FAILED,
    ),
    Cell(
        "scope-root-text",
        ("account", "list"),
        _AGENT_TOKEN,
        _ACCOUNT,
        _TEXT,
        "permission_denied",
        _scope_msg("account:read"),
    ),
    Cell(
        "scope-root-json",
        ("--format", "json", "account", "list"),
        _AGENT_TOKEN,
        _ACCOUNT,
        _JSON,
        "permission_denied",
        _scope_msg("account:read"),
    ),
    Cell(
        "scope-sub-json",
        ("account", "list", "--format", "json"),
        _AGENT_TOKEN,
        _ACCOUNT,
        _JSON,
        "permission_denied",
        _scope_msg("account:read"),
    ),
    Cell(
        "scope-root-json-sub-text",
        ("--format", "json", "account", "list", "--format", "text"),
        _AGENT_TOKEN,
        _ACCOUNT,
        _TEXT,
        "permission_denied",
        _scope_msg("account:read"),
    ),
    Cell(
        "master-root-text",
        ("member", "suspend", "someone"),
        _AGENT_TOKEN,
        _MEMBER,
        _TEXT,
        "permission_denied",
        _MASTER_ONLY,
    ),
    Cell(
        "master-root-json",
        ("--format", "json", "member", "suspend", "someone"),
        _AGENT_TOKEN,
        _MEMBER,
        _JSON,
        "permission_denied",
        _MASTER_ONLY,
    ),
    Cell(
        "master-sub-json",
        (
            "member",
            "update-scopes",
            "someone",
            "--scopes",
            "x:read",
            "--format",
            "json",
        ),
        _AGENT_TOKEN,
        _MEMBER,
        _JSON,
        "permission_denied",
        _MASTER_ONLY,
    ),
    Cell(
        "enforce-root-text",
        ("data", "validate", "--fix"),
        _AGENT_TOKEN,
        _DATA,
        _TEXT,
        "permission_denied",
        _scope_msg("data:write"),
    ),
    Cell(
        "enforce-root-json",
        ("--format", "json", "data", "validate", "--fix"),
        _AGENT_TOKEN,
        _DATA,
        _JSON,
        "permission_denied",
        _scope_msg("data:write"),
    ),
    Cell(
        "key-missing-root-text",
        ("account", "list"),
        _KEY_MISSING_SETUP,
        _ACCOUNT,
        _TEXT,
        "DB_ENCRYPTION_KEY_MISSING",
        _KEY_MISSING,
    ),
    Cell(
        "key-missing-root-json",
        ("--format", "json", "account", "list"),
        _KEY_MISSING_SETUP,
        _ACCOUNT,
        _JSON,
        "DB_ENCRYPTION_KEY_MISSING",
        _KEY_MISSING,
    ),
    Cell(
        "key-missing-sub-json",
        ("account", "list", "--format", "json"),
        _KEY_MISSING_SETUP,
        _ACCOUNT,
        _JSON,
        "DB_ENCRYPTION_KEY_MISSING",
        _KEY_MISSING,
    ),
    Cell(
        "key-invalid-root-text",
        ("account", "list"),
        _KEY_INVALID_SETUP,
        _ACCOUNT,
        _TEXT,
        "DB_ENCRYPTION_KEY_INVALID",
        _KEY_INVALID,
    ),
    Cell(
        "key-invalid-root-json",
        ("--format", "json", "account", "list"),
        _KEY_INVALID_SETUP,
        _ACCOUNT,
        _JSON,
        "DB_ENCRYPTION_KEY_INVALID",
        _KEY_INVALID,
    ),
    Cell(
        "key-invalid-sub-json",
        ("account", "list", "--format", "json"),
        _KEY_INVALID_SETUP,
        _ACCOUNT,
        _JSON,
        "DB_ENCRYPTION_KEY_INVALID",
        _KEY_INVALID,
    ),
)


def _expected(out: str, code: str, message: str) -> tuple[int, str, str]:
    if out == _JSON:
        return 1, _json(code, message), ""
    return 1, "", f"Error: {code}: {message}\n"


@pytest.mark.parametrize("cell", _CELLS, ids=[c.id for c in _CELLS])
def test_real_cli_gate_exit(
    cell: Cell, env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import importlib

    _apply(monkeypatch, cell.setup)
    module = importlib.import_module(cell.module)
    first_call = _BODY_FIRST_CALL.get(cell.module, "get_formatter")
    original = getattr(module, first_call)
    with patch.object(module, first_call, wraps=original) as body:
        result = _invoke(cli, list(cell.args))
    assert body.call_count == 0
    assert (result.exit_code, result.stdout, result.stderr) == _expected(
        cell.out, cell.code, cell.message
    )


@pytest.mark.parametrize("out", [_TEXT, _JSON])
def test_undecodable_token_file_is_no_token(
    out: str, env: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    token_file = tmp_path / "token.bin"
    token_file.write_bytes(b"fake-tok\xff\xfe-tail\n")
    _apply(monkeypatch, _NO_TOKEN)
    monkeypatch.setenv("ANTE_TOKEN_FILE", str(token_file))
    result = _invoke(cli, ["--format", out, "account", "list"])
    assert (result.exit_code, result.stdout, result.stderr) == _expected(
        out, "auth_required", _REQ
    )
    for trace in ("0xff", "0xfe", "codec", "position", "fake-tok"):
        assert trace not in result.stdout + result.stderr


def test_account_group_level_format_is_usage_error(
    env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _apply(monkeypatch, _NO_TOKEN)
    result = _invoke(cli, ["account", "--format", "json", "list"])
    assert result.exit_code == 1
    assert result.stderr == ""
    assert result.stdout == _json("CLI_USAGE_ERROR", "No such option: --format")


# ── 관문 하나만 남긴 하네스 ─────────────────────────────────────────────────


def _build_harness(calls: list[str]) -> AuthenticatedGroup:
    @click.group(
        cls=AuthenticatedGroup,
        context_settings={"help_option_names": ["-h", "--help"]},
    )
    @click.option(
        "--format",
        "output_format",
        type=click.Choice(["text", "json"]),
        default="text",
    )
    @click.option("--config-dir", "config_dir", default=None, envvar="ANTE_CONFIG_DIR")
    @click.pass_context
    def root(ctx: click.Context, output_format: str, config_dir: str | None) -> None:
        ctx.ensure_object(dict)
        ctx.obj["format"] = output_format
        ctx.obj["formatter"] = OutputFormatter(output_format)
        if config_dir:
            ctx.obj["config_dir"] = Path(config_dir)

    def _record(name: str) -> None:
        calls.append(name)

    @click.command("bare")
    def bare() -> None:
        _record("bare")

    root.add_command(bare)
    bare.callback = lambda: _record("bare")

    @root.command("wrapped")
    def wrapped() -> None:
        _record("wrapped")

    @root.command("auth")
    @require_auth
    def auth() -> None:
        _record("auth")

    @root.command("master")
    @require_master
    def master() -> None:
        _record("master")

    @root.command("scope")
    @require_scope("x:write")
    def scope() -> None:
        _record("scope")

    @root.command("imperative")
    @click.pass_context
    def imperative(ctx: click.Context) -> None:
        enforce_scope(ctx, "x:write")
        _record("imperative")

    @click.command("imperative-bare")
    @click.pass_context
    def imperative_bare(ctx: click.Context) -> None:
        enforce_scope(ctx, "x:write")
        _record("imperative-bare")

    unwrapped = imperative_bare.callback
    root.add_command(imperative_bare)
    imperative_bare.callback = unwrapped

    @root.command("fmt")
    @format_option
    @click.pass_context
    @require_auth
    @require_scope("x:write")
    def fmt(ctx: click.Context) -> None:
        _record("fmt")

    return root


@dataclass(frozen=True)
class HarnessCell:
    """하네스 한 호출. ``leaf``가 막아야 할 관문 하나만 남긴 명령이다."""

    id: str
    args: tuple[str, ...]
    setup: Setup
    out: str
    code: str
    message: str


_HARNESS_KINDS: tuple[tuple[str, tuple[str, ...], Setup, str, str], ...] = (
    ("invoke-gate-no-token", ("bare",), _NO_TOKEN, "auth_required", _REQ),
    ("invoke-gate-bad-token", ("bare",), _BAD_TOKEN, "auth_failed", _FAILED),
    (
        "key-missing",
        ("bare",),
        _KEY_MISSING_SETUP,
        "DB_ENCRYPTION_KEY_MISSING",
        _KEY_MISSING,
    ),
    (
        "key-invalid",
        ("bare",),
        _KEY_INVALID_SETUP,
        "DB_ENCRYPTION_KEY_INVALID",
        _KEY_INVALID,
    ),
    (
        "callback-gate-no-token",
        ("wrapped",),
        Setup(gate_off=True),
        "auth_required",
        _REQ,
    ),
    (
        "callback-gate-bad-token",
        ("wrapped",),
        Setup(token=True, auth_error="토큰이 유효하지 않습니다", gate_off=True),
        "auth_failed",
        _FAILED,
    ),
    ("require-auth", ("auth",), Setup(gate_off=True), "auth_required", _REQ),
    ("require-master-none", ("master",), Setup(gate_off=True), "auth_required", _REQ),
    (
        "require-master-denied",
        ("master",),
        _AGENT_TOKEN,
        "permission_denied",
        _MASTER_ONLY,
    ),
    ("require-scope-none", ("scope",), Setup(gate_off=True), "auth_required", _REQ),
    (
        "require-scope-denied",
        ("scope",),
        _AGENT_TOKEN,
        "permission_denied",
        _scope_msg("x:write"),
    ),
    (
        "enforce-scope-none",
        ("imperative",),
        Setup(gate_off=True),
        "auth_required",
        _REQ,
    ),
    (
        "enforce-scope-bare-none",
        ("imperative-bare",),
        Setup(gate_off=True),
        "auth_required",
        _REQ,
    ),
    (
        "enforce-scope-denied",
        ("imperative",),
        _AGENT_TOKEN,
        "permission_denied",
        _scope_msg("x:write"),
    ),
)


def _harness_cells() -> tuple[HarnessCell, ...]:
    cells: list[HarnessCell] = []
    for kind, args, setup, code, message in _HARNESS_KINDS:
        cells.append(HarnessCell(f"{kind}-text", args, setup, _TEXT, code, message))
        cells.append(
            HarnessCell(
                f"{kind}-root-json",
                ("--format", "json", *args),
                setup,
                _JSON,
                code,
                message,
            )
        )
    cells.extend(
        (
            HarnessCell(
                "fmt-no-token-sub-json",
                ("fmt", "--format", "json"),
                _NO_TOKEN,
                _JSON,
                "auth_required",
                _REQ,
            ),
            HarnessCell(
                "fmt-denied-sub-json",
                ("fmt", "--format", "json"),
                _AGENT_TOKEN,
                _JSON,
                "permission_denied",
                _scope_msg("x:write"),
            ),
            HarnessCell(
                "fmt-require-auth-sub-json",
                ("fmt", "--format", "json"),
                Setup(gate_off=True),
                _JSON,
                "auth_required",
                _REQ,
            ),
            HarnessCell(
                "fmt-require-auth-root-json-sub-text",
                ("--format", "json", "fmt", "--format", "text"),
                Setup(gate_off=True),
                _TEXT,
                "auth_required",
                _REQ,
            ),
            HarnessCell(
                "key-missing-sub-json",
                ("fmt", "--format", "json"),
                _KEY_MISSING_SETUP,
                _JSON,
                "DB_ENCRYPTION_KEY_MISSING",
                _KEY_MISSING,
            ),
        )
    )
    return tuple(cells)


_HARNESS_CELLS = _harness_cells()


@pytest.mark.parametrize("cell", _HARNESS_CELLS, ids=[c.id for c in _HARNESS_CELLS])
def test_harness_gate_blocks_body(
    cell: HarnessCell, env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _apply(monkeypatch, cell.setup)
    calls: list[str] = []
    result = _invoke(_build_harness(calls), list(cell.args))
    assert calls == []
    assert (result.exit_code, result.stdout, result.stderr) == _expected(
        cell.out, cell.code, cell.message
    )


@pytest.mark.parametrize(
    ("args", "setup"),
    [
        (("bare",), _MASTER_TOKEN),
        (("wrapped",), Setup(token=True, member=_MASTER, gate_off=True)),
        (("auth",), Setup(token=True, member=_AGENT, gate_off=True)),
        (("master",), _MASTER_TOKEN),
        (("scope",), _MASTER_TOKEN),
        (("imperative",), _MASTER_TOKEN),
        (("fmt", "--format", "json"), _MASTER_TOKEN),
    ],
    ids=["bare", "wrapped", "auth", "master", "scope", "imperative", "fmt"],
)
def test_harness_control_body_runs_when_gate_passes(
    args: tuple[str, ...], setup: Setup, env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _apply(monkeypatch, setup)
    calls: list[str] = []
    result = _invoke(_build_harness(calls), list(args))
    assert (result.exit_code, result.stdout, result.stderr) == (0, "", "")
    assert calls == [args[0]]
