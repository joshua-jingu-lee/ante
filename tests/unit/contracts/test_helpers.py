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
    AuthMetadata,
    CliLeafCommand,
    DatabaseConstructionSite,
    DocsCommandRow,
    ExceptionClassInfo,
    FmtErrorCallsite,
    GetDbPathCall,
    collect_docs_command_paths,
    iter_click_leaf_commands,
    iter_command_auth_metadata,
    iter_database_constructions,
    iter_docs_command_rows,
    iter_exception_classes,
    iter_fmt_error_calls,
    iter_get_db_path_calls,
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


# ── iter_command_auth_metadata ────────────────────────────────────────────


class TestIterCommandAuthMetadata:
    """CLI leaf command 의 auth marker introspection (#1845)."""

    def test_default_root_yields_metadata_for_every_leaf(self) -> None:
        """root 미지정 시 ``ante.cli.main.cli`` 의 모든 leaf 에 1:1 매핑."""
        leaves = {leaf.path for leaf in iter_click_leaf_commands()}
        metadata = list(iter_command_auth_metadata())
        meta_paths = {m.path for m in metadata}
        assert meta_paths == leaves
        for m in metadata:
            assert isinstance(m, AuthMetadata)
            assert isinstance(m.scopes, frozenset)

    def test_public_allowlist_path_marked_public(self) -> None:
        """``_AUTH_EXEMPT_COMMAND_PATHS`` 등재 path 는 ``is_public=True``."""
        from ante.cli.middleware import _AUTH_EXEMPT_COMMAND_PATHS

        meta_by_path = {m.path: m for m in iter_command_auth_metadata()}
        for path in _AUTH_EXEMPT_COMMAND_PATHS:
            meta = meta_by_path.get(path)
            assert meta is not None, f"{path}: allowlist path 가 leaf 에 없다"
            assert meta.is_public is True

    def test_scope_decorator_extracts_marker_tuple(self) -> None:
        """``@require_scope(*scopes)`` 부착 leaf 는 ``scopes`` 추출."""
        meta_by_path = {m.path: m for m in iter_command_auth_metadata()}
        # ``bot list`` 는 ``@require_scope("bot:read")`` 로 부착되어 있다
        # (src/ante/cli/commands/bot.py:90).
        meta = meta_by_path.get(("bot", "list"))
        assert meta is not None
        assert meta.scopes == frozenset({"bot:read"})
        assert meta.is_master is False
        assert meta.requires_auth is True

    def test_master_decorator_marker_extracted(self) -> None:
        """``@require_master`` 부착 leaf 는 ``is_master=True``."""
        meta_by_path = {m.path: m for m in iter_command_auth_metadata()}
        # ``member register`` 는 ``@require_master`` 로 부착되어 있다
        # (src/ante/cli/commands/member.py:477).
        meta = meta_by_path.get(("member", "register"))
        assert meta is not None
        assert meta.is_master is True
        assert meta.requires_auth is True

    def test_injected_root_isolates_subtree(self) -> None:
        """주입된 root 에서도 marker 추출이 동작한다."""

        @click.group()
        def root() -> None:
            pass

        @root.command()
        def plain() -> None:
            """no decorator."""

        results = list(iter_command_auth_metadata(root))
        assert len(results) == 1
        meta = results[0]
        assert meta.path == ("plain",)
        # plain leaf: allowlist 없음, marker 없음.
        assert meta.is_public is False
        assert meta.is_master is False
        assert meta.scopes == frozenset()
        assert meta.requires_auth is False


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
        "AuthMetadata",
        "CliLeafCommand",
        "DatabaseConstructionSite",
        "ExceptionClassInfo",
        "FmtErrorCallsite",
        "GetDbPathCall",
        "iter_click_leaf_commands",
        "iter_command_auth_metadata",
        "iter_database_constructions",
        "iter_exception_classes",
        "iter_fmt_error_calls",
        "iter_get_db_path_calls",
        "iter_ipc_command_specs",
    }
    assert expected.issubset(set(helpers.__all__))
    for name in expected:
        assert hasattr(helpers, name), name


# ── iter_database_constructions (#1858) ───────────────────────────────────


class TestIterDatabaseConstructions:
    """``Database(...)`` 직접 생성 callsite iterator skeleton (#1858)."""

    def test_detects_direct_database_call(self, tmp_path: Path) -> None:
        """``Database(get_db_path())`` 패턴이 매치된다."""
        source = textwrap.dedent(
            """
            from ante.core.database import Database
            from ante.cli.main import get_db_path

            def cmd() -> None:
                db = Database(get_db_path())
            """
        ).strip()
        (tmp_path / "mod.py").write_text(source, encoding="utf-8")

        results = list(iter_database_constructions(tmp_path))
        assert len(results) == 1
        site = results[0]
        assert isinstance(site, DatabaseConstructionSite)
        assert site.path == tmp_path / "mod.py"
        assert site.lineno == 5
        assert "Database(get_db_path())" in site.snippet

    def test_ignores_isinstance_check(self, tmp_path: Path) -> None:
        """``isinstance(x, Database)`` 같은 non-construction 참조는 skip."""
        source = textwrap.dedent(
            """
            from ante.core.database import Database

            def check(x) -> bool:
                return isinstance(x, Database)
            """
        ).strip()
        (tmp_path / "mod.py").write_text(source, encoding="utf-8")

        results = list(iter_database_constructions(tmp_path))
        assert results == []

    def test_skips_syntax_error_files(self, tmp_path: Path) -> None:
        """SyntaxError 파일은 sweep 도중 skip 된다."""
        (tmp_path / "broken.py").write_text("def :=:", encoding="utf-8")
        results = list(iter_database_constructions(tmp_path))
        assert results == []

    def test_missing_root_returns_empty(self, tmp_path: Path) -> None:
        """존재하지 않는 root 는 빈 iterator 를 반환한다."""
        results = list(iter_database_constructions(tmp_path / "nonexistent"))
        assert results == []


# ── iter_get_db_path_calls (#1858) ────────────────────────────────────────


class TestIterGetDbPathCalls:
    """``get_db_path(...)`` 호출 iterator skeleton (#1858)."""

    def test_detects_no_arg_legacy_call(self, tmp_path: Path) -> None:
        """``get_db_path()`` (ctx 미전달) 패턴이 ``has_ctx_argument=False`` 로 매치."""
        source = textwrap.dedent(
            """
            from ante.cli.main import get_db_path

            def legacy() -> None:
                p = get_db_path()
            """
        ).strip()
        (tmp_path / "mod.py").write_text(source, encoding="utf-8")

        results = list(iter_get_db_path_calls(tmp_path))
        assert len(results) == 1
        call = results[0]
        assert isinstance(call, GetDbPathCall)
        assert call.has_ctx_argument is False

    def test_detects_ctx_call(self, tmp_path: Path) -> None:
        """``get_db_path(ctx)`` 패턴이 ``has_ctx_argument=True`` 로 매치."""
        source = textwrap.dedent(
            """
            from ante.cli.main import get_db_path

            def modern(ctx) -> None:
                p = get_db_path(ctx)
            """
        ).strip()
        (tmp_path / "mod.py").write_text(source, encoding="utf-8")

        results = list(iter_get_db_path_calls(tmp_path))
        assert len(results) == 1
        call = results[0]
        assert call.has_ctx_argument is True

    def test_ignores_attribute_call(self, tmp_path: Path) -> None:
        """``mod.get_db_path()`` 같은 attribute call 은 매치하지 않는다.

        본 helper 의 scope 는 callsite 안에서 직접 import 된 ``get_db_path``
        만 다룬다.
        """
        source = textwrap.dedent(
            """
            import ante.cli.main as m

            def cmd() -> None:
                p = m.get_db_path()
            """
        ).strip()
        (tmp_path / "mod.py").write_text(source, encoding="utf-8")

        results = list(iter_get_db_path_calls(tmp_path))
        assert results == []

    def test_missing_root_returns_empty(self, tmp_path: Path) -> None:
        results = list(iter_get_db_path_calls(tmp_path / "nonexistent"))
        assert results == []


# ── iter_docs_command_rows / collect_docs_command_paths (#1848) ───────────


class TestIterDocsCommandRows:
    """``docs/specs/cli/03-commands.md`` 표 행 파서 skeleton."""

    def test_extracts_simple_leaf_row(self, tmp_path: Path) -> None:
        """단일 leaf path 행을 그대로 추출한다."""
        doc = tmp_path / "spec.md"
        doc.write_text(
            "| `ante account list` | offline | runtime-safe |\n",
            encoding="utf-8",
        )
        rows = list(iter_docs_command_rows(doc))
        assert len(rows) == 1
        assert rows[0].paths == (("account", "list"),)

    def test_extracts_row_with_argument_placeholder(self, tmp_path: Path) -> None:
        """``<arg>`` 형태의 placeholder 토큰은 path 추출에서 끊긴다."""
        doc = tmp_path / "spec.md"
        doc.write_text(
            "| `ante account info <account_id>` | offline | x |\n",
            encoding="utf-8",
        )
        rows = list(iter_docs_command_rows(doc))
        assert rows[0].paths == (("account", "info"),)

    def test_extracts_row_with_option(self, tmp_path: Path) -> None:
        """``--option`` 토큰은 path 추출에서 끊긴다."""
        doc = tmp_path / "spec.md"
        doc.write_text(
            "| `ante account list [--status <status>]` | offline | x |\n",
            encoding="utf-8",
        )
        rows = list(iter_docs_command_rows(doc))
        assert rows[0].paths == (("account", "list"),)

    def test_expands_slash_alternation(self, tmp_path: Path) -> None:
        """슬래시로 구분된 토큰은 카테시안 곱으로 확장한다."""
        doc = tmp_path / "spec.md"
        doc.write_text(
            "| `ante data list/schema/storage ...` | offline | x |\n",
            encoding="utf-8",
        )
        rows = list(iter_docs_command_rows(doc))
        assert set(rows[0].paths) == {
            ("data", "list"),
            ("data", "schema"),
            ("data", "storage"),
        }

    def test_returns_typed_rows(self, tmp_path: Path) -> None:
        """yield 되는 객체는 :class:`DocsCommandRow` 인스턴스다."""
        doc = tmp_path / "spec.md"
        doc.write_text(
            "| `ante system status` | offline | x |\n",
            encoding="utf-8",
        )
        rows = list(iter_docs_command_rows(doc))
        assert isinstance(rows[0], DocsCommandRow)
        assert rows[0].lineno == 1
        assert "ante system status" in f"ante {rows[0].raw_first_cell}"

    def test_ignores_non_ante_rows(self, tmp_path: Path) -> None:
        """``| ante`` 로 시작하지 않는 행은 무시한다."""
        doc = tmp_path / "spec.md"
        doc.write_text(
            textwrap.dedent(
                """\
                | 분류 | 의미 |
                |------|------|
                | `offline` | x |
                | `ante system status` | offline | x |
                """,
            ),
            encoding="utf-8",
        )
        rows = list(iter_docs_command_rows(doc))
        assert len(rows) == 1
        assert rows[0].paths == (("system", "status"),)


class TestCollectDocsCommandPaths:
    """``collect_docs_command_paths`` aggregation 동작."""

    def test_collects_distinct_paths(self, tmp_path: Path) -> None:
        """여러 행에서 중복된 path 는 한 번만 등장한다."""
        doc = tmp_path / "spec.md"
        doc.write_text(
            textwrap.dedent(
                """\
                | `ante system status` | offline | x |
                | `ante system status` | offline | duplicate row |
                | `ante system halt` | runtime IPC | x |
                """,
            ),
            encoding="utf-8",
        )
        paths = collect_docs_command_paths(doc)
        assert paths == frozenset(
            {
                ("system", "status"),
                ("system", "halt"),
            },
        )

    def test_excludes_dash_meta_paths(self, tmp_path: Path) -> None:
        """``--version`` 처럼 dash 로 시작하는 segment 는 결과에서 제외된다."""
        doc = tmp_path / "spec.md"
        doc.write_text(
            "| `ante --version` | meta | meta row |\n"
            "| `ante system status` | offline | x |\n",
            encoding="utf-8",
        )
        paths = collect_docs_command_paths(doc)
        # ``--version`` 토큰은 path extraction 단계에서 break 되어 paths=()
        # 가 되지만, 만에 하나 row 가 ``--`` segment 로 추출되더라도 collect
        # 단계가 dash-leading segment 를 거른다.
        assert paths == frozenset({("system", "status")})

    def test_returns_frozenset(self, tmp_path: Path) -> None:
        """결과는 :class:`frozenset` 으로 immutable 하다."""
        doc = tmp_path / "spec.md"
        doc.write_text(
            "| `ante system status` | offline | x |\n",
            encoding="utf-8",
        )
        paths = collect_docs_command_paths(doc)
        assert isinstance(paths, frozenset)

    def test_runs_against_real_docs(self) -> None:
        """실제 ``docs/specs/cli/03-commands.md`` 에 대해 파서가 깨지지 않는다.

        본 테스트는 docs SSOT 변경 시 path extraction 이 zero-match 가 되거나
        구조적 회귀가 생기는지를 sanity check 한다. 정확한 path set 동치는
        :mod:`tests.unit.contracts.test_cli_registry_docs_drift` 의 책임.
        """
        repo_root = Path(__file__).resolve().parents[3]
        spec_path = repo_root / "docs" / "specs" / "cli" / "03-commands.md"
        if not spec_path.exists():
            pytest.skip("docs/specs/cli/03-commands.md not present in this layout")
        paths = collect_docs_command_paths(spec_path)
        assert len(paths) >= 50, (
            f"실제 docs 에서 추출된 path 수가 너무 적음 ({len(paths)} < 50)"
        )


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
