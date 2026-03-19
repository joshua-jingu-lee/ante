"""scripts/generate_cli_reference.py 동작 검증 테스트."""

from __future__ import annotations

import io

import click

# ── 헬퍼 함수 테스트 ─────────────────────────────────────────────────────────


class TestCollectCommands:
    """_collect_commands가 Click 명령어 트리를 올바르게 순회하는지 검증."""

    def test_collects_leaf_commands(self) -> None:
        """리프 명령어가 수집된다."""
        from scripts.generate_cli_reference import _collect_commands

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
        from scripts.generate_cli_reference import _collect_commands

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
        from scripts.generate_cli_reference import _collect_commands

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


class TestFormatParamType:
    """_format_param_type가 파라미터 타입을 올바르게 포맷팅하는지 검증."""

    def test_choice_type(self) -> None:
        from scripts.generate_cli_reference import _format_param_type

        param = click.Option(["--fmt"], type=click.Choice(["text", "json"]))
        assert _format_param_type(param) == "text / json"

    def test_int_range_type(self) -> None:
        from scripts.generate_cli_reference import _format_param_type

        param = click.Option(["--n"], type=click.IntRange(1, 100))
        result = _format_param_type(param)
        assert "1" in result
        assert "100" in result

    def test_path_type(self) -> None:
        from scripts.generate_cli_reference import _format_param_type

        param = click.Option(["--path"], type=click.Path())
        assert _format_param_type(param) == "PATH"

    def test_string_type(self) -> None:
        from scripts.generate_cli_reference import _format_param_type

        param = click.Option(["--name"], type=click.STRING)
        result = _format_param_type(param)
        assert result == "TEXT"


class TestFormatDefault:
    """_format_default가 기본값을 올바르게 포맷팅하는지 검증."""

    def test_none_default(self) -> None:
        from scripts.generate_cli_reference import _format_default

        param = click.Option(["--x"], default=None)
        assert _format_default(param) == "\u2014"

    def test_bool_false_default(self) -> None:
        from scripts.generate_cli_reference import _format_default

        param = click.Option(["--x"], is_flag=True, default=False)
        assert _format_default(param) == "false"

    def test_string_default(self) -> None:
        from scripts.generate_cli_reference import _format_default

        param = click.Option(["--x"], default="hello")
        assert _format_default(param) == "hello"

    def test_empty_tuple_default(self) -> None:
        from scripts.generate_cli_reference import _format_default

        param = click.Option(["--x"], multiple=True)
        assert _format_default(param) == "\u2014"


class TestGetParams:
    """_get_params가 help 옵션을 제외하는지 검증."""

    def test_excludes_help(self) -> None:
        from scripts.generate_cli_reference import _get_params

        @click.command()
        @click.option("--name", help="이름")
        def cmd(name: str) -> None:
            pass

        params = _get_params(cmd)
        names = [p.name for p in params]
        assert "name" in names
        assert "help" not in names


# ── 전체 생성 테스트 ─────────────────────────────────────────────────────────


class TestGenerateCliReference:
    """generate_cli_reference가 ante CLI에서 올바른 문서를 생성하는지 검증."""

    def test_generates_markdown(self) -> None:
        """마크다운 문서가 생성된다."""
        from scripts.generate_cli_reference import generate_cli_reference

        buf = io.StringIO()
        count = generate_cli_reference(buf)
        content = buf.getvalue()

        assert content.startswith("# Ante CLI Reference")
        assert count > 0

    def test_subcommand_count_at_least_60(self) -> None:
        """60개 이상의 서브커맨드가 문서화된다."""
        from scripts.generate_cli_reference import generate_cli_reference

        buf = io.StringIO()
        count = generate_cli_reference(buf)

        assert count >= 60, f"서브커맨드 {count}개 — 60개 이상 필요"

    def test_contains_summary_table(self) -> None:
        """명령어 요약 테이블이 포함된다."""
        from scripts.generate_cli_reference import generate_cli_reference

        buf = io.StringIO()
        generate_cli_reference(buf)
        content = buf.getvalue()

        assert "## 명령어 요약" in content
        assert "| 명령 | 설명 |" in content

    def test_contains_global_options(self) -> None:
        """글로벌 옵션 섹션이 포함된다."""
        from scripts.generate_cli_reference import generate_cli_reference

        buf = io.StringIO()
        generate_cli_reference(buf)
        content = buf.getvalue()

        assert "## 글로벌 옵션" in content
        assert "`--format`" in content

    def test_contains_known_commands(self) -> None:
        """알려진 명령어들이 문서에 포함된다."""
        from scripts.generate_cli_reference import generate_cli_reference

        buf = io.StringIO()
        generate_cli_reference(buf)
        content = buf.getvalue()

        expected_commands = [
            "ante bot create",
            "ante bot list",
            "ante member bootstrap",
            "ante strategy validate",
            "ante system halt",
            "ante trade list",
            "ante feed init",
        ]
        for cmd in expected_commands:
            assert cmd in content, f"'{cmd}'가 문서에 없음"

    def test_auto_generation_notice(self) -> None:
        """자동 생성 안내 문구가 포함된다."""
        from scripts.generate_cli_reference import generate_cli_reference

        buf = io.StringIO()
        generate_cli_reference(buf)
        content = buf.getvalue()

        assert "자동 생성" in content
        assert "직접 수정하지 마세요" in content

    def test_options_have_details(self) -> None:
        """옵션이 있는 명령어에 옵션 테이블이 포함된다."""
        from scripts.generate_cli_reference import generate_cli_reference

        buf = io.StringIO()
        generate_cli_reference(buf)
        content = buf.getvalue()

        # bot create는 --name, --strategy 등 옵션이 많음
        assert "**Options:**" in content
