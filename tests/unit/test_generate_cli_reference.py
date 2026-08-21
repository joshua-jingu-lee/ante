"""scripts/generate_cli_reference.py 동작 검증 테스트."""

from __future__ import annotations

import ast
import importlib.util
import io
import types
from pathlib import Path

import click
import pytest

# scripts/ 디렉토리는 패키지가 아니므로 importlib로 직접 로드
_SCRIPT_PATH = (
    Path(__file__).resolve().parents[2] / "scripts" / "generate_cli_reference.py"
)
_spec = importlib.util.spec_from_file_location("generate_cli_reference", _SCRIPT_PATH)
_mod = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(_mod)  # type: ignore[union-attr]

_collect_commands = _mod._collect_commands
_format_param_type = _mod._format_param_type
_format_default = _mod._format_default
_get_params = _mod._get_params
_get_required_scopes = _mod._get_required_scopes
_format_scope_cell = _mod._format_scope_cell
_format_token_cell = _mod._format_token_cell
_write_command_detail = _mod._write_command_detail
CLI_GENERATED_NOTICE = _mod.CLI_GENERATED_NOTICE
CLI_MODULE_GUIDE_NOTICE = _mod.CLI_MODULE_GUIDE_NOTICE
generate_cli_reference = _mod.generate_cli_reference

# ── 헬퍼 함수 테스트 ─────────────────────────────────────────────────────────


class TestCollectCommands:
    """_collect_commands가 Click 명령어 트리를 올바르게 순회하는지 검증."""

    def test_collects_leaf_commands(self) -> None:
        """리프 명령어가 수집된다."""

        @click.group()
        def root() -> None:
            pass

        @root.command()
        def sub() -> None:
            """서브커맨드."""

        result = _collect_commands(root)
        names = [name for name, _ in result]
        assert "sub" in names

    def test_collects_nested_commands(self) -> None:
        """중첩 그룹의 명령어가 수집된다."""

        @click.group()
        def root() -> None:
            pass

        @root.group()
        def grp() -> None:
            """그룹."""

        @grp.command()
        def leaf() -> None:
            """리프."""

        result = _collect_commands(root)
        names = [name for name, _ in result]
        assert "grp leaf" in names

    def test_groups_are_included(self) -> None:
        """그룹 자체도 결과에 포함된다."""

        @click.group()
        def root() -> None:
            pass

        @root.group()
        def grp() -> None:
            """그룹."""

        @grp.command()
        def leaf() -> None:
            """리프."""

        result = _collect_commands(root)
        names = [name for name, _ in result]
        assert "grp" in names

    def test_hidden_leaf_command_excluded(self) -> None:
        """hidden 리프 명령은 수집 결과에서 제외된다 (#1682)."""

        @click.group()
        def root() -> None:
            pass

        @root.command()
        def visible() -> None:
            """노출."""

        @root.command(hidden=True)
        def secret() -> None:
            """숨김."""

        result = _collect_commands(root)
        names = [name for name, _ in result]
        assert "visible" in names
        assert "secret" not in names

    def test_hidden_group_and_subtree_excluded(self) -> None:
        """hidden 그룹은 그룹 자체와 하위 재귀 전체가 제외된다 (#1682).

        notification 빈 그룹을 ``@click.group(hidden=True)`` 로 숨기면
        guide/cli.md(생성물)에서 그룹 heading 과 하위 명령이 모두
        사라져야 한다. generic·mechanism-agnostic 검증.
        """

        @click.group()
        def root() -> None:
            pass

        @root.group(name="shown")
        def visible_grp() -> None:
            """노출 그룹."""

        @visible_grp.command(name="run")
        def visible_leaf() -> None:
            """노출 리프."""

        @root.group(name="hidden", hidden=True)
        def hidden_grp() -> None:
            """숨김 그룹."""

        @hidden_grp.command(name="buried")
        def buried_leaf() -> None:
            """숨김 그룹 하위 리프."""

        result = _collect_commands(root)
        names = [name for name, _ in result]
        # hidden 그룹 자체 + 하위 재귀 전부 부재
        assert "hidden" not in names
        assert "hidden buried" not in names
        # 노출 그룹과 그 하위는 영향 없음 (회귀 0)
        assert "shown" in names
        assert "shown run" in names

    def test_hidden_group_absent_from_generated_markdown(self) -> None:
        """hidden 그룹은 생성된 markdown TOC/heading 에 미포함 (#1682)."""

        @click.group()
        def root() -> None:
            """루트."""

        @root.group(hidden=True)
        def notification() -> None:
            """알림 관리."""

        @root.group()
        def shown() -> None:
            """노출 그룹."""

        @shown.command()
        def run() -> None:
            """실행."""

        # get_cli 를 더미 트리로 패치하여 전체 생성 경로를 검증한다.
        original_get_cli = _mod.get_cli
        _mod.get_cli = lambda: root
        try:
            buf = io.StringIO()
            generate_cli_reference(buf)
            content = buf.getvalue()
        finally:
            _mod.get_cli = original_get_cli

        assert "notification" not in content
        assert "## notification" not in content
        assert "](#notification" not in content
        # 노출 그룹은 정상 생성 (회귀 0)
        assert "## shown" in content
        assert "ante shown run" in content


class TestFormatParamType:
    """_format_param_type가 파라미터 타입을 올바르게 포맷팅하는지 검증."""

    def test_choice_type(self) -> None:

        param = click.Option(["--fmt"], type=click.Choice(["text", "json"]))
        assert _format_param_type(param) == "text / json"

    def test_int_range_type(self) -> None:

        param = click.Option(["--n"], type=click.IntRange(1, 100))
        result = _format_param_type(param)
        assert "1" in result
        assert "100" in result

    def test_path_type(self) -> None:

        param = click.Option(["--path"], type=click.Path())
        assert _format_param_type(param) == "PATH"

    def test_string_type(self) -> None:

        param = click.Option(["--name"], type=click.STRING)
        result = _format_param_type(param)
        assert result == "TEXT"


class TestFormatDefault:
    """_format_default가 기본값을 올바르게 포맷팅하는지 검증."""

    def test_none_default(self) -> None:

        param = click.Option(["--x"], default=None)
        assert _format_default(param) == "\u2014"

    def test_bool_false_default(self) -> None:

        param = click.Option(["--x"], is_flag=True, default=False)
        assert _format_default(param) == "false"

    def test_string_default(self) -> None:

        param = click.Option(["--x"], default="hello")
        assert _format_default(param) == "hello"

    def test_empty_tuple_default(self) -> None:

        param = click.Option(["--x"], multiple=True)
        assert _format_default(param) == "\u2014"


class TestGetParams:
    """_get_params가 help 옵션을 제외하는지 검증."""

    def test_excludes_help(self) -> None:

        @click.command()
        @click.option("--name", help="이름")
        def cmd(name: str) -> None:
            pass

        params = _get_params(cmd)
        names = [p.name for p in params]
        assert "name" in names
        assert "help" not in names


class TestGetRequiredScopes:
    """_get_required_scopes가 콜백 체인에서 scope를 올바르게 추출하는지 검증."""

    def test_no_scope_returns_empty(self) -> None:
        """scope 데코레이터가 없으면 빈 튜플 반환."""

        @click.command()
        def cmd() -> None:
            pass

        assert _get_required_scopes(cmd) == ()

    def test_extracts_scope_from_callback(self) -> None:
        """_required_scopes 속성이 있으면 추출."""
        import functools

        def inner() -> None:
            pass

        @functools.wraps(inner)
        def wrapper() -> None:
            pass

        wrapper._required_scopes = ("strategy:read",)

        cmd = click.Command("test", callback=wrapper)
        assert _get_required_scopes(cmd) == ("strategy:read",)

    def test_extracts_scope_from_wrapped_chain(self) -> None:
        """__wrapped__ 체인을 따라가서 scope 추출."""
        import functools

        def inner() -> None:
            pass

        inner._required_scopes = ("data:write",)

        @functools.wraps(inner)
        def outer() -> None:
            pass

        cmd = click.Command("test", callback=outer)
        assert _get_required_scopes(cmd) == ("data:write",)


class TestFormatScopeCell:
    """scope 셀 포맷팅 테스트."""

    def test_empty_scopes(self) -> None:
        assert _format_scope_cell(()) == "\u2014"

    def test_single_scope(self) -> None:
        assert _format_scope_cell(("strategy:write",)) == "`strategy:write`"

    def test_multiple_scopes(self) -> None:
        result = _format_scope_cell(("strategy:read", "data:read"))
        assert "`strategy:read`" in result
        assert "`data:read`" in result


class TestFormatTokenCell:
    """토큰 셀 포맷팅 테스트."""

    def test_no_scope(self) -> None:
        assert _format_token_cell(()) == "\u2014"

    def test_with_scope(self) -> None:
        assert _format_token_cell(("strategy:write",)) == "H\u00b7A"


# ── 전체 생성 테스트 ─────────────────────────────────────────────────────────


class TestGenerateCliReference:
    """generate_cli_reference가 ante CLI에서 올바른 문서를 생성하는지 검증."""

    def test_generates_markdown(self) -> None:
        """마크다운 문서가 생성된다."""

        buf = io.StringIO()
        count = generate_cli_reference(buf)
        content = buf.getvalue()

        assert content.startswith("# Ante CLI Reference")
        assert count > 0

    def test_subcommand_count_at_least_60(self) -> None:
        """60개 이상의 서브커맨드가 문서화된다."""

        buf = io.StringIO()
        count = generate_cli_reference(buf)

        assert count >= 60, f"서브커맨드 {count}개 — 60개 이상 필요"

    def test_contains_summary_table(self) -> None:
        """명령어 요약 테이블이 포함된다."""

        buf = io.StringIO()
        generate_cli_reference(buf)
        content = buf.getvalue()

        assert "## 명령어 요약" in content
        assert "| 명령 | 설명 | scope | 토큰 |" in content

    def test_contains_global_options(self) -> None:
        """글로벌 옵션 섹션이 포함된다."""

        buf = io.StringIO()
        generate_cli_reference(buf)
        content = buf.getvalue()

        assert "## 글로벌 옵션" in content
        assert "`--format`" in content

    def test_contains_known_commands(self) -> None:
        """알려진 명령어들이 문서에 포함된다."""

        buf = io.StringIO()
        generate_cli_reference(buf)
        content = buf.getvalue()

        expected_commands = [
            "ante bot create",
            "ante bot list",
            "ante strategy validate",
            "ante system halt",
            "ante system clear-halt",
            "ante trade list",
            "ante feed init",
        ]
        for cmd in expected_commands:
            assert cmd in content, f"'{cmd}'가 문서에 없음"

        # 제거된 커맨드는 문서에 존재하지 않아야 한다 (issue #1125)
        assert "ante member bootstrap" not in content, (
            "제거된 ante member bootstrap이 CLI reference에 남아있습니다"
        )
        # legacy `ante system activate`는 #1213에서 제거됨 (SSOT 정책: hard remove)
        assert "ante system activate" not in content, (
            "legacy 'ante system activate'가 CLI reference에 남아있습니다 (Refs #1213)"
        )

    def test_intro_notice(self) -> None:
        """사용자 친화적 소개 문구가 포함된다."""

        buf = io.StringIO()
        generate_cli_reference(buf)
        content = buf.getvalue()

        assert "CLI 명령어를 정리한 문서" in content
        assert "마지막 갱신" in content

    def test_header_preserves_generated_and_module_guide_notices(self) -> None:
        """재생성 시 자동 생성 안내와 모듈 가이드 링크가 사라지지 않는다."""

        buf = io.StringIO()
        generate_cli_reference(buf)
        content = buf.getvalue()

        assert CLI_GENERATED_NOTICE in content
        assert CLI_MODULE_GUIDE_NOTICE in content
        assert "[모듈과 운영 영역](modules.md)" in content

    def test_options_have_details(self) -> None:
        """옵션이 있는 명령어에 옵션 테이블이 포함된다."""

        buf = io.StringIO()
        generate_cli_reference(buf)
        content = buf.getvalue()

        # bot create는 --name, --strategy 등 옵션이 많음
        assert "**Options:**" in content

    def test_contains_scope_columns(self) -> None:
        """요약 테이블에 scope·토큰 컬럼이 포함된다."""

        buf = io.StringIO()
        generate_cli_reference(buf)
        content = buf.getvalue()

        assert "| scope | 토큰 |" in content
        # 범례가 포함되어야 한다
        assert "**H**: Human 토큰" in content

    def test_command_detail_has_scope_info(self) -> None:
        """커맨드 상세에 scope·토큰 정보가 포함된다."""

        buf = io.StringIO()
        generate_cli_reference(buf)
        content = buf.getvalue()

        assert "**필요 scope**:" in content
        assert "**토큰**:" in content

    def test_all_subcommands_have_description(self) -> None:
        """모든 서브커맨드에 설명(docstring)이 존재한다.

        요약 테이블의 설명 열이 비어 있으면 안 된다 (#494).
        """
        import re

        buf = io.StringIO()
        generate_cli_reference(buf)
        content = buf.getvalue()

        # 요약 테이블에서 명령어 행 추출
        summary_rows = re.findall(r"\| `(ante [^`]+)` \| (.*?) \| .* \| .* \|", content)
        assert len(summary_rows) > 0, "요약 테이블에서 명령어를 찾지 못함"

        blank = [cmd for cmd, desc in summary_rows if not desc.strip()]
        assert blank == [], f"설명이 비어 있는 명령어: {blank}"


# ── usage line: required option 인라인 표시 (#1696) ─────────────────────────


def _render_usage(cmd: click.Command, full_name: str) -> str:
    """``_write_command_detail`` 의 usage line(```bash ... ```) 한 줄을 추출한다."""
    buf = io.StringIO()
    _write_command_detail(buf, full_name, cmd)
    content = buf.getvalue()
    # ```bash\n<usage>\n``` 패턴에서 usage 한 줄을 뽑는다.
    marker = "```bash\n"
    start = content.index(marker) + len(marker)
    end = content.index("\n```", start)
    return content[start:end]


class TestUsageLineRequiredOptionInline:
    """``_write_command_detail`` usage line이 required option을 인라인 표시 (#1696).

    7 case A~G 매트릭스 (이슈 #1696 Implementation Plan v3.1):
      A. required-only        → ``--account <ACCOUNT_ID>`` 인라인, ``[OPTIONS]`` 부재
      B. 혼합                  → required 인라인 + ``[OPTIONS]``
      C. non-required-only 회귀 → 기존 ``[OPTIONS]`` 유지
      D. 다중 required, 인자 없음 → 다중 인라인 + ``[OPTIONS]``
      E. metavar 변환          → ``--type`` → ``<APPROVAL_TYPE>``
      F. 인자 + 단일 required  → 인자 + 인라인, ``[OPTIONS]`` 부재
      G. 다중 인자 + 단일 required → 인자2 + 인라인, ``[OPTIONS]`` 부재
    """

    def test_case_a_required_only_no_options_token(self) -> None:
        """A. required-only: ``ante broker status --account <ACCOUNT_ID>``."""

        @click.command(name="status")
        @click.option("--account", "account_id", required=True)
        def status(account_id: str) -> None:
            """잔고 상태."""

        usage = _render_usage(status, "broker status")
        assert usage == "ante broker status --account <ACCOUNT_ID>"
        assert "[OPTIONS]" not in usage

    def test_case_b_mixed_required_and_optional(self) -> None:
        """B. 혼합: ``ante broker reconcile --account <ACCOUNT_ID> [OPTIONS]``."""

        @click.command(name="reconcile")
        @click.option("--account", "account_id", required=True)
        @click.option("--force", is_flag=True, default=False)
        def reconcile(account_id: str, force: bool) -> None:
            """리컨실."""

        usage = _render_usage(reconcile, "broker reconcile")
        assert usage == "ante broker reconcile --account <ACCOUNT_ID> [OPTIONS]"

    def test_case_c_nonrequired_only_regression(self) -> None:
        """C. non-required-only 회귀: ``[OPTIONS]`` 유지, 인라인 없음."""

        @click.command(name="list")
        @click.option("--limit", type=int, default=50)
        @click.option("--format", "output_format", default="text")
        def list_cmd(limit: int, output_format: str) -> None:
            """목록."""

        usage = _render_usage(list_cmd, "audit list")
        assert usage == "ante audit list [OPTIONS]"

    def test_case_d_multi_required_no_arg(self) -> None:
        """D. 다중 required, 인자 없음: bot create 형태."""

        @click.command(name="create")
        @click.option("--name", required=True)
        @click.option("--strategy", required=True)
        @click.option("--description", default=None)
        def create(name: str, strategy: str, description: str | None) -> None:
            """봇 생성."""

        usage = _render_usage(create, "bot create")
        assert usage == "ante bot create --name <NAME> --strategy <STRATEGY> [OPTIONS]"

    def test_case_e_metavar_conversion_from_human_name(self) -> None:
        """E. metavar 변환: ``--type`` (human_name=approval_type) → 대문자화."""

        @click.command(name="request")
        @click.option("--type", "approval_type", required=True)
        @click.option("--title", required=True)
        @click.option("--note", default=None)
        def request_cmd(approval_type: str, title: str, note: str | None) -> None:
            """승인 요청."""

        usage = _render_usage(request_cmd, "approval request")
        assert (
            usage
            == "ante approval request --type <APPROVAL_TYPE> --title <TITLE> [OPTIONS]"
        )

    def test_case_f_arg_plus_single_required_option(self) -> None:
        """F. 인자 + required option: ``rule info <RULE_ID> --account <ACCOUNT_ID>``."""

        @click.command(name="info")
        @click.argument("rule_id")
        @click.option("--account", "account_id", required=True)
        def info(rule_id: str, account_id: str) -> None:
            """룰 상세."""

        usage = _render_usage(info, "rule info")
        assert usage == "ante rule info <RULE_ID> --account <ACCOUNT_ID>"
        assert "[OPTIONS]" not in usage

    def test_case_g_multi_arg_plus_single_required_option(self) -> None:
        """G. 다중 인자 + 단일 required: treasury allocate 형태."""

        @click.command(name="allocate")
        @click.argument("bot_id")
        @click.argument("amount")
        @click.option("--account", "account_id", required=True)
        def allocate(bot_id: str, amount: str, account_id: str) -> None:
            """예산 할당."""

        usage = _render_usage(allocate, "treasury allocate")
        assert (
            usage == "ante treasury allocate <BOT_ID> <AMOUNT> --account <ACCOUNT_ID>"
        )
        assert "[OPTIONS]" not in usage


# ── --check 모드 (#2472) ─────────────────────────────────────────────────────


def _bypass_import_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    """``main()``의 워크트리 import 가드를 무력화한다.

    가드 자체는 :meth:`TestCheckMode.test_import_guard_failure_is_fail_loud`가
    잠근다. 나머지 테스트는 실행 환경의 ``PYTHONPATH``에 의존하지 않도록
    가드를 우회한다.
    """
    monkeypatch.setattr(_mod, "_assert_current_worktree_import_path", lambda: None)


def _render(generated_at: str) -> str:
    """주어진 스탬프로 CLI 레퍼런스 전문을 문자열로 만든다."""
    buf = io.StringIO()
    _mod.generate_cli_reference(buf, generated_at=generated_at)
    return buf.getvalue()


def _install_failing_import_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    """``main()``의 워크트리 import 가드가 반드시 실패하도록 만든다.

    실제 가드는 실행 환경의 ``PYTHONPATH``에 따라 통과/실패가 갈리므로
    서브프로세스 없이 결정적으로 실패시킨다.
    """

    class _FakeImportPathCheckError(RuntimeError):
        pass

    def _raise(project_root: Path) -> None:
        raise _FakeImportPathCheckError(
            "Import path sanity check failed for package 'ante'."
        )

    monkeypatch.setattr(
        _mod,
        "_load_import_guard",
        lambda: types.SimpleNamespace(
            ImportPathCheckError=_FakeImportPathCheckError,
            check_import_path=_raise,
        ),
    )


class TestCheckMode:
    """``--check``가 형제 생성기(#2472)와 같은 계약을 지키는지 검증."""

    def test_check_passes_on_up_to_date_output(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """산출물이 최신이면 0으로 종료한다."""
        _bypass_import_guard(monkeypatch)
        output = tmp_path / "cli.md"
        output.write_text(_render(_mod._today_kst()), encoding="utf-8")

        rc = _mod.main(["--check", "--output", str(output)])

        assert rc == 0
        assert "is up to date." in capsys.readouterr().out

    def test_check_fails_on_stale_output(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """본문이 어긋나면 1로 종료하고 재생성 명령을 안내한다."""
        _bypass_import_guard(monkeypatch)
        output = tmp_path / "cli.md"
        stale = _render("2020-01-01").replace("## 명령어 요약", "## 옛 명령어 요약")
        output.write_text(stale, encoding="utf-8")

        rc = _mod.main(["--check", "--output", str(output)])

        captured = capsys.readouterr().out
        assert rc == 1
        assert "is stale." in captured
        assert "scripts/generate_cli_reference.py" in captured

    def test_check_never_writes_output(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``--check``는 산출물을 만들지도 고치지도 않는다."""
        _bypass_import_guard(monkeypatch)
        missing = tmp_path / "nested" / "cli.md"

        rc_missing = _mod.main(["--check", "--output", str(missing)])

        assert rc_missing == 1
        assert not missing.exists()
        assert not missing.parent.exists()

        existing = tmp_path / "cli.md"
        stale = _render("2020-01-01").replace("## 명령어 요약", "## 옛 명령어 요약")
        existing.write_text(stale, encoding="utf-8")

        rc_existing = _mod.main(["--check", "--output", str(existing)])

        assert rc_existing == 1
        assert existing.read_text(encoding="utf-8") == stale

    def test_check_passes_when_committed_stamp_is_not_today(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """커밋된 스탬프가 오늘이 아니어도 본문이 같으면 0으로 종료한다 (#2472)."""
        _bypass_import_guard(monkeypatch)
        assert _mod._today_kst() != "2020-01-01"
        output = tmp_path / "cli.md"
        content = _render("2020-01-01")
        assert "> 마지막 갱신: 2020-01-01" in content
        output.write_text(content, encoding="utf-8")

        rc = _mod.main(["--check", "--output", str(output)])

        assert rc == 0

    def test_generate_still_writes_today_stamp(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """일반 generate는 기존대로 오늘 날짜 스탬프를 기록한다."""
        _bypass_import_guard(monkeypatch)
        output = tmp_path / "cli.md"
        output.write_text(_render("2020-01-01"), encoding="utf-8")

        rc = _mod.main(["--output", str(output)])

        assert rc == 0
        assert f"> 마지막 갱신: {_mod._today_kst()}\n" in output.read_text(
            encoding="utf-8"
        )

    def test_stdout_and_check_are_mutually_exclusive(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """``--stdout``과 ``--check``는 함께 쓸 수 없다."""
        _bypass_import_guard(monkeypatch)

        with pytest.raises(SystemExit) as excinfo:
            _mod.main(["--stdout", "--check"])

        assert excinfo.value.code == 2
        assert "--stdout and --check cannot be used together" in capsys.readouterr().err

    def test_relative_output_resolves_against_project_root(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """상대 ``--output``은 cwd가 아니라 ``PROJECT_ROOT`` 기준으로 해석된다."""
        _bypass_import_guard(monkeypatch)
        project_root = tmp_path / "root"
        project_root.mkdir()
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        monkeypatch.setattr(_mod, "PROJECT_ROOT", project_root)
        monkeypatch.chdir(elsewhere)

        rc = _mod.main(["--output", "guide/cli.md"])

        assert rc == 0
        assert (project_root / "guide" / "cli.md").exists()
        assert not (elsewhere / "guide").exists()

    def test_import_guard_failure_is_fail_loud(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """워크트리 import 가드가 실패하면 ``main()``이 즉시 1로 종료한다."""
        _install_failing_import_guard(monkeypatch)

        with pytest.raises(SystemExit) as excinfo:
            _mod.main(["--check"])

        assert excinfo.value.code == 1
        assert "Import path sanity check failed" in capsys.readouterr().err

    def test_help_answers_before_import_guard(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """``--help``는 워크트리 import 가드와 무관하게 rc=0으로 답한다.

        가드를 ``main()`` 첫 줄에 두면 introspection이 전혀 필요 없는
        ``--help``까지 워크트리에서만 rc=1이 된다 — base ``5512e3cf``에서는
        어디서든 rc=0이었으므로 그 배치는 이 저장소에 회귀다(#2472).
        가드는 ``parse_args()`` 뒤에 있어야 한다. 이 락이 없으면 다음
        미러링 변경이 조용히 되돌린다.
        """
        _install_failing_import_guard(monkeypatch)

        with pytest.raises(SystemExit) as excinfo:
            _mod.main(["--help"])

        captured = capsys.readouterr()
        assert excinfo.value.code == 0
        assert "usage:" in captured.out
        assert "Import path sanity check failed" not in captured.err


# ── 생성기 전수 --check 규범 (#2472) ─────────────────────────────────────────

_REPO_ROOT = Path(__file__).resolve().parents[2]

# 목록을 하드코딩하지 않는다 — 하드코딩하면 새로 추가된 네 번째 생성기를
# 놓쳐 아래 락이 무의미해진다.
_GENERATOR_SOURCES = sorted((_REPO_ROOT / "scripts").glob("generate_*.py"))

_MAIN_GUARD = 'if __name__ == "__main__":'


def _module_ast(path: Path) -> ast.Module:
    """생성기 소스를 **실행하지 않고** AST로만 읽는다."""
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _has_main_guard(tree: ast.Module) -> bool:
    """모듈에 ``if __name__ == "__main__":`` 진입 가드가 있는가."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        if (
            isinstance(test, ast.Compare)
            and isinstance(test.left, ast.Name)
            and test.left.id == "__name__"
            and len(test.ops) == 1
            and isinstance(test.ops[0], ast.Eq)
            and len(test.comparators) == 1
            and isinstance(test.comparators[0], ast.Constant)
            and test.comparators[0].value == "__main__"
        ):
            return True
    return False


def _registers_option(tree: ast.Module, option: str) -> bool:
    """``<parser>.add_argument("<option>", ...)`` 호출이 AST에 있는가.

    AST 노드 판정이므로 주석·docstring·``ArgumentParser(description=...)``
    산문에 등장하는 같은 문자열에는 원리적으로 매치되지 않는다.
    """
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr != "add_argument":
            continue
        for arg in node.args:
            if isinstance(arg, ast.Constant) and arg.value == option:
                return True
    return False


_GENERATOR_ASTS = {path: _module_ast(path) for path in _GENERATOR_SOURCES}
_CLI_GENERATORS = [
    path for path in _GENERATOR_SOURCES if _has_main_guard(_GENERATOR_ASTS[path])
]
_HELPER_SOURCES = [path for path in _GENERATOR_SOURCES if path not in _CLI_GENERATORS]

_SELECTION_NOTE = (
    "대상 선별 기준: `scripts/generate_*.py` 중 AST에 "
    + _MAIN_GUARD
    + " 진입 가드가 있는 파일. 가드가 없는 파일은 CLI 진입점이 아니라 공유 "
    + "헬퍼로 보고 제외한다. "
    + "glob 히트="
    + str([path.name for path in _GENERATOR_SOURCES])
    + " / 대상="
    + str([path.name for path in _CLI_GENERATORS])
    + " / 제외="
    + str([path.name for path in _HELPER_SOURCES])
)

assert _CLI_GENERATORS, (
    "생성기 CLI 진입점을 하나도 찾지 못했다 — 대상 선별이 어긋나면 아래 전수 "
    "락이 vacuous pass 한다 (#2472). " + _SELECTION_NOTE
)


class TestAllGeneratorsProvideCheckMode:
    """``scripts/generate_*.py`` 전수가 전용 ``--check``를 제공하는지 잠근다.

    #2472는 세 문서(``.agent/skills/generated-artifact-sync.md`` ·
    ``.agent/skills/review-pr.md`` · ``docs/runbooks/01-development-process.md``)
    에 「모든 생성 산출물은 전용 ``--check``를 제공한다. 새 산출물을 추가하면
    커밋된 날짜 스탬프를 동결하는 ``--check``도 함께 만든다」를 성문화하면서,
    전용 check가 없는 산출물용 fallback 절차를 제거했다. 집행 장치가 없으면
    네 번째 생성기가 ``--check`` 없이 추가되는 순간 그 전칭 규범이 조용히
    거짓이 되고 #2472가 없앤 실패 모드가 그대로 재발한다.

    **판정은 소스 AST로만 한다 — 생성기를 실행하지 않는다.** 실행 기반 판정은
    이 락이 잡아야 할 바로 그 회귀(argv를 무시하는 생성기)에 대해 위험하다.
    그런 생성기는 ``--check``든 ``--help``든 받으면 그냥 generate 모드로 돌아
    **추적 산출물을 덮어쓴다** — 락이 워크트리를 오염시킨다(실측). AST 판정은
    부작용이 0이고, ``PYTHONPATH`` 주입도 locale 의존도 없다. 덤으로 주석 ·
    docstring · ``description`` 산문에 있는 ``--check`` 언급에 false-pass 하는
    문자열 검색의 결함도 구조적으로 사라진다.

    대상은 ``scripts/generate_*.py`` 중 ``__main__`` 진입 가드를 가진 파일이다.
    가드가 없는 공유 헬퍼(예: ``generate_common.py``)는 CLI가 아니므로 제외해
    false FAIL을 막는다. 「argparse가 있는 파일만」으로 좁히지 않는다 — 그러면
    정작 잡아야 할 *argparse 없는 생성기*가 빠져나간다.

    산출물의 실제 최신성까지는 보지 않는다. 그것은 각 생성기 자신의 책임이고,
    이 저장소의 ``project-structure.md``는 #2472와 무관한 선행 드리프트로
    stale이다(#2472 Non-Goals).

    자리에 관하여: 저장소 전역 규범을 잠그므로 본래는
    ``tests/unit/contracts/``가 맞는 위치다. 다만 #2472는 변경 파일 집합을
    5개로 제한한다 — 신규 파일은 ``project-structure.md`` 재생성 축을 열고,
    그 산출물은 base에서 이미 stale이라 이 PR이 무관한 드리프트를 조용히
    고치게 된다. 그 제약이 풀리면 contract 테스트로 옮기는 것이 옳다.
    """

    @pytest.mark.parametrize(
        "script",
        _CLI_GENERATORS,
        ids=lambda script: script.name,
    )
    def test_generator_registers_check_flag(self, script: Path) -> None:
        """각 생성기가 ``--check``를 argparse 옵션으로 등록한다."""
        assert _registers_option(_GENERATOR_ASTS[script], "--check"), (
            f"{script.name} 가 전용 --check 를 등록하지 않는다. #2472가 성문화한 "
            "「모든 생성 산출물은 전용 --check를 제공한다」 규범 위반이다. "
            "새 생성기를 추가할 때는 커밋된 날짜 스탬프를 동결하는 --check를 "
            "함께 만든다. 이 파일이 생성기가 아니라 공유 헬퍼라면 "
            + _MAIN_GUARD
            + " 진입 가드를 두지 않으면 대상에서 빠진다.\n"
            + _SELECTION_NOTE
        )
