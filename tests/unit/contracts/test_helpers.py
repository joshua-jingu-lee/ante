"""Contract drift helper skeleton 자체 unit test (Refs #1823).

이 테스트는 helper API 가 동작한다는 것만 검증한다 — repository-wide drift
count exact assertion 은 추가하지 않는다 (그것은 #1815/#1816/#1818/#1819
후속 epic 의 책임).
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import click
import pytest

from tests.unit.contracts.helpers import (
    CliLeafCommand,
    ExceptionClassInfo,
    FmtErrorCallsite,
    iter_click_leaf_commands,
    iter_exception_classes,
    iter_fmt_error_calls,
    iter_ipc_command_specs,
)

# ── iter_click_leaf_commands ──────────────────────────────────────────────


class TestIterClickLeafCommands:
    """Click leaf command iterator skeleton."""

    def test_yields_leaf_only(self) -> None:
        """그룹 자체는 yield 하지 않고 leaf 만 yield 한다."""

        @click.group()
        def root() -> None:
            pass

        @root.command()
        def alpha() -> None:
            """alpha leaf."""

        @root.group()
        def grp() -> None:
            """그룹."""

        @grp.command()
        def beta() -> None:
            """nested leaf."""

        results = list(iter_click_leaf_commands(root))
        paths = [r.path for r in results]
        assert ("alpha",) in paths
        assert ("grp", "beta") in paths
        # group "grp" 자체는 leaf 가 아니다.
        assert ("grp",) not in paths

    def test_excludes_hidden_subtree(self) -> None:
        """hidden 그룹/leaf 는 모두 제외 (#1682 generic·mechanism-agnostic)."""

        @click.group()
        def root() -> None:
            pass

        @root.command(hidden=True)
        def secret() -> None:
            """hidden leaf."""

        @root.command()
        def visible() -> None:
            """visible leaf."""

        @root.group(name="buried", hidden=True)
        def buried() -> None:
            """hidden group."""

        @buried.command()
        def underground() -> None:
            """hidden subtree leaf."""

        results = list(iter_click_leaf_commands(root))
        paths = [r.path for r in results]
        assert ("visible",) in paths
        assert ("secret",) not in paths
        assert ("buried", "underground") not in paths

    def test_returns_dataclass_with_command_object(self) -> None:
        """결과는 CliLeafCommand 이고 command 객체에 접근 가능하다."""

        @click.group()
        def root() -> None:
            pass

        @root.command()
        def leaf() -> None:
            """leaf doc."""

        results = list(iter_click_leaf_commands(root))
        assert len(results) == 1
        item = results[0]
        assert isinstance(item, CliLeafCommand)
        assert item.path == ("leaf",)
        assert isinstance(item.command, click.Command)
        assert item.command.help == "leaf doc."

    def test_default_root_loads_ante_cli(self) -> None:
        """root 미지정 시 ante.cli.main.cli 를 사용 (live smoke).

        count exact assertion 은 두지 않는다 — helper 가 동작하는지만
        확인. 후속 epic 이 exact count 를 lock 한다.
        """
        results = list(iter_click_leaf_commands())
        assert len(results) > 0
        # path 는 항상 비어있지 않은 튜플.
        for item in results:
            assert isinstance(item.path, tuple)
            assert len(item.path) >= 1
            assert isinstance(item.command, click.Command)


# ── iter_ipc_command_specs ────────────────────────────────────────────────


class TestIterIpcCommandSpecs:
    """IPC registry spec iterator skeleton."""

    def test_injected_registry_fixture(self) -> None:
        """주입된 registry 의 등록 spec 만 yield."""
        from ante.ipc.registry import CommandRegistry

        registry = CommandRegistry()

        async def dummy(svc, args, actor):  # type: ignore[no-untyped-def]
            return {}

        registry.register("alpha", dummy, is_mutating=True)
        registry.register("beta", dummy, is_mutating=False)

        specs = list(iter_ipc_command_specs(registry))
        names = {s.name for s in specs}
        assert names == {"alpha", "beta"}
        # taxonomy 가 그대로 보존된다.
        spec_by_name = {s.name: s for s in specs}
        assert spec_by_name["alpha"].is_mutating is True
        assert spec_by_name["beta"].is_mutating is False

    def test_default_registry_smoke(self) -> None:
        """registry 미지정 시 register_all_handlers 결과를 사용 (live smoke)."""
        specs = list(iter_ipc_command_specs())
        # count exact assertion 은 후속 epic. iterator 동작만 확인.
        assert len(specs) > 0
        # 각 항목은 name / is_mutating 을 가진 CommandSpec.
        for spec in specs:
            assert isinstance(spec.name, str) and spec.name
            assert isinstance(spec.is_mutating, bool)

    def test_empty_registry_yields_nothing(self) -> None:
        """등록 없는 registry 는 빈 iterator."""
        from ante.ipc.registry import CommandRegistry

        registry = CommandRegistry()
        assert list(iter_ipc_command_specs(registry)) == []


# ── iter_exception_classes ────────────────────────────────────────────────


class TestIterExceptionClasses:
    """``*Error`` class AST iterator skeleton."""

    def test_detects_class_with_literal_code(self, tmp_path: Path) -> None:
        """class-level ``code: str = "FOO"`` literal 추출."""
        src = textwrap.dedent(
            """
            class FooError(Exception):
                code: str = "FOO_ERROR"
            """
        ).lstrip()
        module = tmp_path / "errors.py"
        module.write_text(src, encoding="utf-8")

        results = list(iter_exception_classes(tmp_path))
        assert len(results) == 1
        info = results[0]
        assert isinstance(info, ExceptionClassInfo)
        assert info.name == "FooError"
        assert info.has_code is True
        assert info.code_value == "FOO_ERROR"
        assert info.path == module
        assert info.lineno == 1

    def test_detects_class_without_code(self, tmp_path: Path) -> None:
        """class body 에 ``code`` 가 없으면 has_code=False."""
        src = textwrap.dedent(
            """
            class BareError(Exception):
                pass
            """
        ).lstrip()
        (tmp_path / "bare.py").write_text(src, encoding="utf-8")

        results = list(iter_exception_classes(tmp_path))
        assert len(results) == 1
        info = results[0]
        assert info.name == "BareError"
        assert info.has_code is False
        assert info.code_value is None

    def test_detects_non_literal_code(self, tmp_path: Path) -> None:
        """``code = MODULE_CONST`` 면 has_code=True, code_value=None."""
        src = textwrap.dedent(
            """
            MY_CODE = "BAR"

            class BarError(Exception):
                code = MY_CODE
            """
        ).lstrip()
        (tmp_path / "non_literal.py").write_text(src, encoding="utf-8")

        results = list(iter_exception_classes(tmp_path))
        assert len(results) == 1
        info = results[0]
        assert info.name == "BarError"
        assert info.has_code is True
        assert info.code_value is None

    def test_detects_plain_assignment_literal(self, tmp_path: Path) -> None:
        """``code = "LITERAL"`` (annotation 없음) 도 인식한다."""
        src = textwrap.dedent(
            """
            class PlainError(Exception):
                code = "PLAIN_CODE"
            """
        ).lstrip()
        (tmp_path / "plain.py").write_text(src, encoding="utf-8")

        results = list(iter_exception_classes(tmp_path))
        assert len(results) == 1
        info = results[0]
        assert info.has_code is True
        assert info.code_value == "PLAIN_CODE"

    def test_skips_non_error_classes(self, tmp_path: Path) -> None:
        """``*Error`` suffix 가 아닌 class 는 yield 하지 않는다."""
        src = textwrap.dedent(
            """
            class NotAnException:
                code: str = "X"

            class HelperClass:
                pass

            class RealError(Exception):
                code: str = "REAL"
            """
        ).lstrip()
        (tmp_path / "mixed.py").write_text(src, encoding="utf-8")

        results = list(iter_exception_classes(tmp_path))
        names = [r.name for r in results]
        assert names == ["RealError"]

    def test_walks_nested_subdirectories(self, tmp_path: Path) -> None:
        """root 하위 모든 ``.py`` 를 재귀 sweep."""
        (tmp_path / "a").mkdir()
        (tmp_path / "a" / "x.py").write_text(
            "class AError(Exception):\n    code: str = 'A'\n",
            encoding="utf-8",
        )
        (tmp_path / "b").mkdir()
        (tmp_path / "b" / "y.py").write_text(
            "class BError(Exception):\n    pass\n",
            encoding="utf-8",
        )

        results = list(iter_exception_classes(tmp_path))
        names = {r.name for r in results}
        assert names == {"AError", "BError"}

    def test_skips_syntax_error_files(self, tmp_path: Path) -> None:
        """SyntaxError 파일은 helper 가 깨지지 않고 skip 한다."""
        (tmp_path / "good.py").write_text(
            "class GoodError(Exception):\n    code: str = 'G'\n",
            encoding="utf-8",
        )
        (tmp_path / "broken.py").write_text("def broken(\n", encoding="utf-8")

        results = list(iter_exception_classes(tmp_path))
        names = [r.name for r in results]
        assert names == ["GoodError"]

    def test_missing_root_returns_empty(self, tmp_path: Path) -> None:
        """존재하지 않는 root 는 빈 iterator."""
        ghost = tmp_path / "does_not_exist"
        assert list(iter_exception_classes(ghost)) == []


# ── iter_fmt_error_calls ──────────────────────────────────────────────────


class TestIterFmtErrorCalls:
    """``fmt.error(...)`` callsite iterator skeleton."""

    def test_detects_code_keyword(self, tmp_path: Path) -> None:
        """``fmt.error(msg, code="X")`` → has_code_keyword=True."""
        src = textwrap.dedent(
            """
            def fail(fmt):
                fmt.error("boom", code="EXPLODED")
            """
        ).lstrip()
        (tmp_path / "a.py").write_text(src, encoding="utf-8")

        results = list(iter_fmt_error_calls(tmp_path))
        assert len(results) == 1
        c = results[0]
        assert isinstance(c, FmtErrorCallsite)
        assert c.has_code_keyword is True
        assert c.has_positional_code is False
        assert c.has_effective_code is True
        assert c.has_empty_code_fallback is False
        assert "EXPLODED" in c.snippet

    def test_detects_positional_code(self, tmp_path: Path) -> None:
        """``fmt.error("msg", "CODE")`` → has_positional_code=True."""
        src = textwrap.dedent(
            """
            def fail(fmt):
                fmt.error("boom", "CODE_X")
            """
        ).lstrip()
        (tmp_path / "b.py").write_text(src, encoding="utf-8")

        results = list(iter_fmt_error_calls(tmp_path))
        assert len(results) == 1
        c = results[0]
        assert c.has_code_keyword is False
        assert c.has_positional_code is True
        assert c.has_effective_code is True
        assert c.has_empty_code_fallback is False

    def test_detects_missing_code(self, tmp_path: Path) -> None:
        """``fmt.error("msg")`` → has_effective_code=False (#1816 대상)."""
        src = textwrap.dedent(
            """
            def fail(fmt):
                fmt.error("oops")
            """
        ).lstrip()
        (tmp_path / "c.py").write_text(src, encoding="utf-8")

        results = list(iter_fmt_error_calls(tmp_path))
        assert len(results) == 1
        c = results[0]
        assert c.has_code_keyword is False
        assert c.has_positional_code is False
        assert c.has_effective_code is False
        assert c.has_empty_code_fallback is False

    def test_detects_empty_string_code(self, tmp_path: Path) -> None:
        """``fmt.error(msg, code="")`` → has_empty_code_fallback=True."""
        src = textwrap.dedent(
            """
            def fail(fmt):
                fmt.error("oops", code="")
            """
        ).lstrip()
        (tmp_path / "d.py").write_text(src, encoding="utf-8")

        results = list(iter_fmt_error_calls(tmp_path))
        assert len(results) == 1
        c = results[0]
        assert c.has_code_keyword is True
        assert c.has_effective_code is True
        assert c.has_empty_code_fallback is True

    def test_detects_getattr_empty_fallback(self, tmp_path: Path) -> None:
        """``code=getattr(e, "code", "")`` → has_empty_code_fallback=True."""
        src = textwrap.dedent(
            """
            def fail(fmt, e):
                fmt.error(str(e), code=getattr(e, "code", ""))
            """
        ).lstrip()
        (tmp_path / "e.py").write_text(src, encoding="utf-8")

        results = list(iter_fmt_error_calls(tmp_path))
        assert len(results) == 1
        c = results[0]
        assert c.has_code_keyword is True
        assert c.has_empty_code_fallback is True

    def test_detects_dict_get_empty_fallback(self, tmp_path: Path) -> None:
        """``code=result.get("code", "")`` → has_empty_code_fallback=True."""
        src = textwrap.dedent(
            """
            def fail(fmt, result):
                fmt.error(result["error"], code=result.get("code", ""))
            """
        ).lstrip()
        (tmp_path / "f.py").write_text(src, encoding="utf-8")

        results = list(iter_fmt_error_calls(tmp_path))
        assert len(results) == 1
        c = results[0]
        assert c.has_code_keyword is True
        assert c.has_empty_code_fallback is True

    def test_non_empty_getattr_default_not_flagged(self, tmp_path: Path) -> None:
        """비-empty default 의 getattr 는 fallback flag 끄지 않는다."""
        src = textwrap.dedent(
            """
            def fail(fmt, e):
                fmt.error(str(e), code=getattr(e, "code", "DEFAULT"))
            """
        ).lstrip()
        (tmp_path / "g.py").write_text(src, encoding="utf-8")

        results = list(iter_fmt_error_calls(tmp_path))
        assert len(results) == 1
        c = results[0]
        assert c.has_code_keyword is True
        assert c.has_empty_code_fallback is False

    def test_matches_alias_attribute_call(self, tmp_path: Path) -> None:
        """``self._fmt.error(...)`` / ``formatter.error(...)`` 같은 alias 도 매치."""
        src = textwrap.dedent(
            """
            def fail(self, formatter):
                self._fmt.error("boom", code="A")
                formatter.error("boom", code="B")
            """
        ).lstrip()
        (tmp_path / "h.py").write_text(src, encoding="utf-8")

        results = list(iter_fmt_error_calls(tmp_path))
        assert len(results) == 2
        codes = sorted(c.snippet for c in results)
        # snippet 은 줄 raw — code value 가 포함되어야 한다.
        assert any('"A"' in s for s in codes)
        assert any('"B"' in s for s in codes)

    def test_snippet_captures_callsite_line(self, tmp_path: Path) -> None:
        """snippet 은 callsite 시작 줄의 source line 을 담는다."""
        src = textwrap.dedent(
            """
            # leading comment
            def fail(fmt):
                fmt.error("boom", code="LINE_LEVEL")
            """
        ).lstrip()
        (tmp_path / "i.py").write_text(src, encoding="utf-8")

        results = list(iter_fmt_error_calls(tmp_path))
        assert len(results) == 1
        c = results[0]
        assert c.lineno == 3
        assert "LINE_LEVEL" in c.snippet

    def test_skips_syntax_error_files(self, tmp_path: Path) -> None:
        """SyntaxError 파일은 helper 가 깨지지 않고 skip 한다."""
        (tmp_path / "good.py").write_text(
            'def f(fmt): fmt.error("ok", code="C")\n',
            encoding="utf-8",
        )
        (tmp_path / "broken.py").write_text("def broken(\n", encoding="utf-8")

        results = list(iter_fmt_error_calls(tmp_path))
        assert len(results) == 1
        assert results[0].has_code_keyword is True

    def test_missing_root_returns_empty(self, tmp_path: Path) -> None:
        """존재하지 않는 root 는 빈 iterator."""
        ghost = tmp_path / "nope"
        assert list(iter_fmt_error_calls(ghost)) == []


# ── module surface ─────────────────────────────────────────────────────────


def test_public_surface_importable() -> None:
    """helper 모듈의 public API 를 한 번에 import 가능."""
    from tests.unit.contracts import helpers

    expected = {
        "CliLeafCommand",
        "ExceptionClassInfo",
        "FmtErrorCallsite",
        "iter_click_leaf_commands",
        "iter_exception_classes",
        "iter_fmt_error_calls",
        "iter_ipc_command_specs",
    }
    assert expected.issubset(set(helpers.__all__))
    for name in expected:
        assert hasattr(helpers, name), name


# ── repository-wide sanity ────────────────────────────────────────────────


def test_helpers_run_against_repo_without_exact_assert() -> None:
    """helper 가 repository 전체 sweep 에 대해 깨지지 않는다.

    repository-wide drift count exact assertion 은 #1815/#1816/#1818/#1819
    후속 epic 의 책임이다. 여기서는 helper 가 실제 repo 에서도 깨지지
    않고 iterator 가 비어있지 않다는 것만 확인한다.
    """
    repo_root = Path(__file__).resolve().parents[3]
    src_ante = repo_root / "src" / "ante"
    cli_root = repo_root / "src" / "ante" / "cli"

    if not src_ante.exists():
        pytest.skip("src/ante not present in this layout")

    error_classes = list(iter_exception_classes(src_ante))
    assert error_classes, "expected at least one *Error class under src/ante"

    fmt_calls = list(iter_fmt_error_calls(cli_root))
    assert fmt_calls, "expected at least one fmt.error callsite under src/ante/cli"

    # path 는 절대 경로로 받아오는지 확인 (#1816 enforcement 가 추적용).
    for info in error_classes:
        assert info.path.is_absolute() or info.path.exists()
    for call in fmt_calls:
        assert call.path.is_absolute() or call.path.exists()
