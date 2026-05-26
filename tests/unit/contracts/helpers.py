"""Contract drift test helper skeleton (Refs #1823).

#1815/#1816/#1818/#1819 후속 epic 이 반복해서 작성할 drift-test 유틸을
공통 helper 로 추출한다. 본 모듈은 helper API 만 제공하고 실제 drift
policy/assertion 은 후속 epic 의 책임이다.

Helper 분류 (Refs #1820 결정 / #1823 plan):

* **import 기반** — Click CLI 트리, IPC ``CommandRegistry`` 는 module
  import 만으로 leaf 식별이 가능하므로 introspection 으로 다룬다.

  - :func:`iter_click_leaf_commands` — Click root group 에서 hidden
    subtree 를 제외한 leaf command 만 yield. 기본 root 는 ``ante.cli.main.cli``.
  - :func:`iter_ipc_command_specs` — :class:`CommandRegistry` 에서 등록된
    :class:`CommandSpec` 을 yield. registry 미지정 시 기본 registry 를
    만들고 :func:`register_all_handlers` 를 호출한다.

* **AST/텍스트 기반** — exception class 와 ``fmt.error(...)`` callsite
  sweep 은 import side effect 를 피하기 위해 file text 를 :func:`ast.parse`
  한다.

  - :func:`iter_exception_classes` — ``src/ante/**/*.py`` 의
    ``*Error`` class 와 class-level ``code`` 속성을 식별한다.
  - :func:`iter_fmt_error_calls` — ``src/ante/cli/**/*.py`` 의
    ``fmt.error(...)`` callsite 와 code argument classification 정보를
    yield 한다.

* **YAML 기반** — error taxonomy drift allowlist (#1841) 는 baseline
  callsite/class 를 구조화 보관한다.

  - :func:`load_drift_allowlist` — ``error_drift_allowlist.yaml`` 을
    파싱해 3 section (`intended_no_code`, `known_drift_fmt_error_no_code`,
    `pending_migration`) 의 :class:`DriftAllowlist` 를 반환한다.

본 helper 는 default repository root 를 알지 못한다. 호출자가 :class:`Path`
를 명시한다 (default 는 cwd 기준 ``Path("src/ante")``). 후속 enforcement
test 가 repository root 를 고정하는 책임을 진다.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import click
import yaml

if TYPE_CHECKING:
    from ante.ipc.registry import CommandRegistry, CommandSpec


# ── import 기반 helper ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class CliLeafCommand:
    """Click leaf command 식별자.

    Attributes:
        path: ``ante`` prefix 를 제외한 leaf 까지의 segment 튜플
            (예: ``("bot", "start")``).
        command: 해당 Click command 객체. 후속 enforcement 가
            ``cmd.callback`` chain / scope decorator 를 들여다볼 수 있다.
    """

    path: tuple[str, ...]
    command: click.Command


def _registration_order(group: click.Group) -> list[str]:
    """Click Group 의 등록 순서를 반환한다.

    Click 8+ 의 ``group.commands`` dict 는 삽입 순서를 보존한다. 일부
    custom Group 구현(MultiCommand) 에서는 dict 가 아닐 수 있으므로
    fallback 으로 ``list_commands`` 를 사용한다.

    (참고: scripts/generate_cli_reference.py:_registration_order 와 동일
    의도 — helper 가 module import side effect 를 늘리지 않도록 inline.)
    """
    commands = getattr(group, "commands", None)
    if isinstance(commands, dict):
        return list(commands.keys())
    ctx = click.Context(group, info_name=group.name or "ante")
    return list(group.list_commands(ctx))


def _walk_click(
    group: click.Group,
    prefix: tuple[str, ...],
) -> Iterator[CliLeafCommand]:
    """Click 트리를 DFS 로 순회하며 leaf 만 yield 한다.

    hidden subtree (그룹/leaf 모두) 는 ``cmd.hidden`` 표식을 따라
    완전히 제외한다. 그룹 자체는 leaf 가 아니므로 yield 하지 않는다.
    """
    ctx = click.Context(group, info_name=group.name or "ante")
    for name in _registration_order(group):
        cmd = group.get_command(ctx, name)
        if cmd is None:
            continue
        if getattr(cmd, "hidden", False):
            # generic·mechanism-agnostic: hidden 그룹은 하위 재귀까지 skip.
            continue
        path = (*prefix, name)
        if isinstance(cmd, click.Group):
            yield from _walk_click(cmd, path)
        else:
            yield CliLeafCommand(path=path, command=cmd)


def iter_click_leaf_commands(
    root: click.Group | None = None,
) -> Iterator[CliLeafCommand]:
    """Click root group 의 public leaf command 를 yield 한다.

    Args:
        root: 검사할 Click root. ``None`` 이면 ``ante.cli.main.cli`` 를
            가져온다 — 후속 enforcement test 가 inline Click fixture root
            를 주입할 수 있도록 keyword 가 아니라 positional default 로
            둔다.

    Yields:
        :class:`CliLeafCommand`: hidden subtree 를 제외한 leaf command.
        그룹 자체는 yield 하지 않는다.
    """
    if root is None:
        from ante.cli.main import cli as _cli  # 지연 import — fixture 주입 우선

        root = _cli
    yield from _walk_click(root, ())


@dataclass(frozen=True)
class AuthMetadata:
    """CLI leaf command 의 인증 marker 메타데이터 (#1845).

    :mod:`ante.cli.middleware` 의 decorator marker / allowlist 를 runtime
    introspection 으로 추출한다. 본 메타데이터는
    :data:`ante.contracts.cli_registry.CLI_COMMAND_REGISTRY` 의
    :class:`~ante.contracts.cli_registry.AuthContract` 와 drift 가 있는지
    검증하기 위해 사용된다.

    추출 규칙 (`src/ante/cli/middleware.py` 정의 기준):

    - ``is_public``: ``path in _AUTH_EXEMPT_COMMAND_PATHS`` (line 29).
      ``init`` / ``member reset-password`` / ``member regenerate-recovery-key``
      3 path 가 등재되어 있다.
    - ``is_master``: callback 의 ``_require_master_applied == True``
      attribute (line 257, ``@require_master`` 가 부착).
    - ``scopes``: callback 의 ``_required_scopes`` tuple
      (line 300, ``@require_scope(*scopes)`` 가 부착). ``frozenset`` 으로
      정규화한다. 없으면 빈 frozenset.
    - ``requires_auth``: callback 이 ``_require_auth_applied == True``
      (line 188) **또는** ``_wrapped_by_authenticated_group == True``
      (line 866). 후자는 :class:`AuthenticatedGroup.add_command` 가 leaf
      callback 을 자동 wrap 할 때 부착한다.

    분류 우선순위 (Family A → D):

    1. ``is_public`` (Family A) — allowlist 매치는 다른 marker 보다 우선.
    2. ``is_master`` (Family C) — master decorator 가 scope decorator 보다
       우선 (``@require_master`` 가 부착되면 ``_required_scopes`` 는 보통
       비어 있다).
    3. ``scopes`` non-empty (Family B) — scope decorator 가 부착된 경우.
    4. ``requires_auth`` only (Family D) — public/master/scoped 가 아니지만
       인증은 요구되는 fallback (``@require_auth`` 만 또는
       ``AuthenticatedGroup`` 자동 wrap 만).

    Attributes:
        path: ``ante`` prefix 를 제외한 root-to-leaf segment 튜플
            (예: ``("bot", "start")``). :class:`CliLeafCommand.path` 와 동일.
        is_public: ``_AUTH_EXEMPT_COMMAND_PATHS`` 매치 여부.
        is_master: ``_require_master_applied`` marker 존재.
        scopes: ``_required_scopes`` (frozenset 정규화). 없으면 빈 frozenset.
        requires_auth: ``_require_auth_applied`` 또는
            ``_wrapped_by_authenticated_group`` marker 존재.
    """

    path: tuple[str, ...]
    is_public: bool
    is_master: bool
    scopes: frozenset[str]
    requires_auth: bool


def iter_command_auth_metadata(
    root: click.Group | None = None,
) -> Iterator[AuthMetadata]:
    """모든 Click leaf command 의 :class:`AuthMetadata` 를 yield (#1845).

    :func:`iter_click_leaf_commands` 와 동일한 leaf 순회 순서를 따른다 —
    hidden subtree 는 제외, 그룹은 yield 하지 않는다.

    runtime introspection 만 사용하며, ``src/ante/cli/middleware.py`` 의
    sentinel marker / allowlist 를 직접 읽는다 (AST parsing 없음). 본
    helper 는 middleware 의 marker 정의가 바뀌면 같은 PR 에서 함께 갱신
    되어야 한다 — :class:`AuthMetadata` docstring 의 marker 위치 정보를
    참조한다.

    Args:
        root: 검사할 Click root. ``None`` 이면 ``ante.cli.main.cli`` 를
            가져온다. :func:`iter_click_leaf_commands` 와 동일.

    Yields:
        :class:`AuthMetadata`: leaf 별 인증 marker 메타데이터.
    """
    from ante.cli.middleware import _AUTH_EXEMPT_COMMAND_PATHS

    allowlist = set(_AUTH_EXEMPT_COMMAND_PATHS)
    for leaf in iter_click_leaf_commands(root):
        callback = leaf.command.callback
        is_public = leaf.path in allowlist
        is_master = bool(getattr(callback, "_require_master_applied", False))
        raw_scopes = getattr(callback, "_required_scopes", None)
        scopes: frozenset[str] = frozenset(raw_scopes) if raw_scopes else frozenset()
        requires_auth = bool(
            getattr(callback, "_require_auth_applied", False)
            or getattr(callback, "_wrapped_by_authenticated_group", False)
        )
        yield AuthMetadata(
            path=leaf.path,
            is_public=is_public,
            is_master=is_master,
            scopes=scopes,
            requires_auth=requires_auth,
        )


def iter_ipc_command_specs(
    registry: CommandRegistry | None = None,
) -> Iterator[CommandSpec]:
    """IPC ``CommandRegistry`` 의 등록된 ``CommandSpec`` 을 yield 한다.

    Args:
        registry: 검사할 registry. ``None`` 이면 새 빈 registry 를 만들고
            :func:`ante.ipc.registry.register_all_handlers` 를 호출해 default
            production registry 를 구성한다. 후속 enforcement test 가 작은
            fixture registry 를 주입할 수 있다.

    Yields:
        :class:`CommandSpec`: ``registry.commands`` 순서대로 ``CommandSpec``
        를 반환한다 (이름이 아니라 spec 자체).
    """
    from ante.ipc.registry import CommandRegistry, register_all_handlers

    if registry is None:
        registry = CommandRegistry()
        register_all_handlers(registry)
    for name in registry.commands:
        spec = registry.get(name)
        if spec is not None:
            yield spec


# ── AST/텍스트 기반 helper ─────────────────────────────────────────────────


@dataclass(frozen=True)
class ExceptionClassInfo:
    """``*Error`` class 의 정적 메타데이터.

    Attributes:
        path: 클래스가 정의된 ``.py`` 파일 경로.
        name: 클래스 이름.
        lineno: 클래스 정의 시작 줄.
        has_code: class body 에 ``code`` 속성 할당이 존재하면 True.
            ``code: str = "..."`` 또는 ``code = "..."`` 둘 다 포함한다.
        code_value: class-level ``code`` 가 literal string 이면 그 값,
            non-literal (모듈 상수 식별자 등) 이면 ``None``. ``has_code`` 가
            False 면 ``None``.
    """

    path: Path
    name: str
    lineno: int
    has_code: bool
    code_value: str | None


@dataclass(frozen=True)
class FmtErrorCallsite:
    """``fmt.error(...)`` 호출의 정적 메타데이터.

    Attributes:
        path: callsite 파일 경로.
        lineno: callsite 줄.
        has_code_keyword: ``code=`` keyword argument 가 존재하면 True.
        has_positional_code: 2번째 positional argument 가 존재하면 True
            (``fmt.error(message, "CODE")`` 패턴).
        has_effective_code: ``code=`` keyword 또는 positional code 중 어느
            하나라도 존재하면 True. False 면 callsite 가 code 인자를 전혀
            전달하지 않는다 (#1816 대상 후보).
        has_empty_code_fallback: code 인자가 빈 fallback 으로 떨어지는지
            **휴리스틱** 판정. 다음 중 어느 하나라도 매치하면 True:

            - 인자 값이 빈 문자열 literal ``""`` 또는 ``''``.
            - ``getattr(..., ..., "")`` 호출 (3번째 default 가 빈 문자열).
            - ``.get(..., "")`` 호출 (2번째 default 가 빈 문자열).

            드물게 false positive/negative 가능 — 후속 #1816 이
            classification 을 강화할 skeleton 으로 사용한다.
        snippet: 원본 source 의 callsite 줄 raw 문자열 (디버깅용).
    """

    path: Path
    lineno: int
    has_code_keyword: bool
    has_positional_code: bool
    has_effective_code: bool
    has_empty_code_fallback: bool
    snippet: str


def _iter_python_files(root: Path) -> Iterator[Path]:
    """``root`` 하위 ``.py`` 파일을 정렬된 순서로 yield 한다.

    ``__pycache__`` 같은 비-source 디렉토리는 ``.py`` 파일을 갖지 않으므로
    별도 필터는 불필요하다. 호출자가 ``root`` scope 를 좁히는 책임을 진다.
    """
    if not root.exists():
        return
    yield from sorted(root.rglob("*.py"))


def _parse_module(path: Path) -> ast.Module | None:
    """파일을 ``ast.parse`` 하고 실패하면 ``None``.

    helper 가 sweep 도중 ``SyntaxError`` 로 깨지지 않도록 try/except 한다.
    파일 자체가 깨졌으면 후속 enforcement 가 별도로 표면화한다.
    """
    try:
        source = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        return ast.parse(source, filename=str(path))
    except SyntaxError:
        return None


def _extract_class_code_attr(
    node: ast.ClassDef,
) -> tuple[bool, str | None]:
    """``code`` class attribute 의 존재/literal 값을 반환한다.

    ``code: str = "..."`` (:class:`ast.AnnAssign`) 와 ``code = "..."``
    (:class:`ast.Assign`) 둘 다 인식한다. literal 이 아니면 ``code_value``
    는 ``None`` 이다 (예: ``code = BOT_NOT_FOUND_CODE``).
    """
    for stmt in node.body:
        # ``code: str = "..."`` (annotated assignment)
        if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            if stmt.target.id == "code" and stmt.value is not None:
                value = stmt.value
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    return True, value.value
                return True, None
        # ``code = "..."`` (plain assignment); 다중 타깃은 첫 ``code`` 만.
        elif isinstance(stmt, ast.Assign):
            for target in stmt.targets:
                if isinstance(target, ast.Name) and target.id == "code":
                    if isinstance(stmt.value, ast.Constant) and isinstance(
                        stmt.value.value, str
                    ):
                        return True, stmt.value.value
                    return True, None
    return False, None


def _is_error_class(name: str) -> bool:
    """``name`` 이 ``*Error`` 인지 (suffix 일치, 단독 ``Error`` 도 포함)."""
    return name == "Error" or name.endswith("Error")


def iter_exception_classes(
    root: Path = Path("src/ante"),
) -> Iterator[ExceptionClassInfo]:
    """``root`` 하위 ``*Error`` class 정의를 yield 한다.

    AST 기반이라 module import 를 유발하지 않는다. base 가 ``Exception`` /
    다른 ``*Error`` / ``ValueError`` 등 어느 것이든 ``name`` 만으로 식별
    한다 — production code 가 ``Error`` suffix convention 을 따른다는
    가정을 따른다.

    Args:
        root: 검사할 루트 디렉토리. 기본 ``Path("src/ante")``. 후속
            enforcement test 가 repository root 절대경로를 합성해 주입할
            수 있다.

    Yields:
        :class:`ExceptionClassInfo`: 각 ``*Error`` class 의 정적 메타데이터.
        ``code`` 가 ``ValueError`` 등 stdlib 상속만으로 자동 채워지는 경우는
        ``has_code=False`` (class body 에 명시 할당이 없으므로).
    """
    for path in _iter_python_files(root):
        module = _parse_module(path)
        if module is None:
            continue
        for node in ast.walk(module):
            if isinstance(node, ast.ClassDef) and _is_error_class(node.name):
                has_code, code_value = _extract_class_code_attr(node)
                yield ExceptionClassInfo(
                    path=path,
                    name=node.name,
                    lineno=node.lineno,
                    has_code=has_code,
                    code_value=code_value,
                )


def _is_fmt_error_call(call: ast.Call) -> bool:
    """``call`` 이 ``<anything>.error(...)`` attribute call 인지.

    ``fmt.error(...)`` 뿐 아니라 ``self._fmt.error(...)`` /
    ``formatter.error(...)`` 같은 alias 도 모두 매치한다. 모듈 이름은
    아무거나 받고 attribute 가 정확히 ``error`` 인지로 식별한다.
    """
    func = call.func
    return isinstance(func, ast.Attribute) and func.attr == "error"


def _is_empty_string_literal(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) and node.value == ""


def _is_empty_default_fallback(node: ast.expr) -> bool:
    """``getattr(..., "")`` / ``.get(..., "")`` 형식의 빈 fallback 인지.

    헛수고 false positive 를 줄이려고 함수 이름이 ``getattr`` 또는
    attribute call ``.get(...)`` 일 때만 인정한다. 더 정확한 분류는 #1816
    이 책임진다.
    """
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Name) and func.id == "getattr":
        # ``getattr(obj, name, default)`` — default 가 3번째 인자.
        if len(node.args) >= 3 and _is_empty_string_literal(node.args[2]):
            return True
    if isinstance(func, ast.Attribute) and func.attr == "get":
        # ``mapping.get(key, default)`` — default 가 2번째 인자.
        if len(node.args) >= 2 and _is_empty_string_literal(node.args[1]):
            return True
    return False


def _classify_code_argument(call: ast.Call) -> tuple[bool, bool, bool, bool]:
    """``fmt.error(...)`` call 에서 code argument 정보를 추출한다.

    Returns:
        ``(has_code_keyword, has_positional_code, has_effective_code,
        has_empty_code_fallback)`` 튜플.
    """
    has_kw = False
    code_value_node: ast.expr | None = None

    for kw in call.keywords:
        if kw.arg == "code":
            has_kw = True
            code_value_node = kw.value
            break

    # ``fmt.error(message, "CODE")`` → 2번째 positional argument.
    # ``ast.Call.args`` 는 positional 만, ``**kwargs`` star unpack 은 제외한다.
    has_positional = len(call.args) >= 2
    if has_positional and code_value_node is None:
        code_value_node = call.args[1]

    has_effective = has_kw or has_positional

    has_empty_fallback = False
    if code_value_node is not None:
        if _is_empty_string_literal(code_value_node):
            has_empty_fallback = True
        elif _is_empty_default_fallback(code_value_node):
            has_empty_fallback = True

    return has_kw, has_positional, has_effective, has_empty_fallback


def _source_line(source_lines: list[str], lineno: int) -> str:
    """1-based ``lineno`` 의 source line 을 안전하게 반환한다."""
    if 1 <= lineno <= len(source_lines):
        return source_lines[lineno - 1].rstrip("\n")
    return ""


def iter_fmt_error_calls(
    root: Path = Path("src/ante/cli"),
) -> Iterator[FmtErrorCallsite]:
    """``root`` 하위 ``fmt.error(...)`` callsite 를 yield 한다.

    AST 기반이라 module import 를 유발하지 않는다. attribute name 이 정확히
    ``error`` 인 모든 attribute call 을 잡으므로 ``self._fmt.error(...)`` /
    ``formatter.error(...)`` 같은 alias 도 자동으로 매치된다.

    Args:
        root: 검사할 루트. 기본 ``Path("src/ante/cli")``. CLI 표면 밖에서
            ``fmt.error`` 호출이 사실상 없지만, 후속 enforcement 가 범위를
            확장해야 하면 ``Path("src/ante")`` 등을 명시하면 된다.

    Yields:
        :class:`FmtErrorCallsite`: callsite 별 code argument classification
        과 source snippet.
    """
    for path in _iter_python_files(root):
        try:
            source = path.read_text(encoding="utf-8")
        except OSError:
            continue
        try:
            module = ast.parse(source, filename=str(path))
        except SyntaxError:
            continue
        source_lines = source.splitlines()
        for node in ast.walk(module):
            if not isinstance(node, ast.Call):
                continue
            if not _is_fmt_error_call(node):
                continue
            (
                has_kw,
                has_pos,
                has_effective,
                has_empty_fallback,
            ) = _classify_code_argument(node)
            yield FmtErrorCallsite(
                path=path,
                lineno=node.lineno,
                has_code_keyword=has_kw,
                has_positional_code=has_pos,
                has_effective_code=has_effective,
                has_empty_code_fallback=has_empty_fallback,
                snippet=_source_line(source_lines, node.lineno),
            )


# ── YAML allowlist loader (#1841) ─────────────────────────────────────────


@dataclass(frozen=True)
class FmtErrorAllowlistEntry:
    """``fmt.error`` code 누락 callsite allowlist entry.

    Attributes:
        path: callsite 파일 경로 (repo root 기준 상대 경로 문자열).
        line: callsite 줄 (1-based).
        snippet_sha1: ``FmtErrorCallsite.snippet`` 의 SHA-1 12-char prefix.
        reason: baseline 등록 사유.
    """

    path: str
    line: int
    snippet_sha1: str
    reason: str


@dataclass(frozen=True)
class ExceptionAllowlistEntry:
    """``*Error`` class code/registry 미부여 allowlist entry.

    Attributes:
        module: dotted module path (예: ``ante.account.errors``).
        class_anchor: class 이름 (예: ``AccountError``).
        reason: baseline 등록 사유.
    """

    module: str
    class_anchor: str
    reason: str


@dataclass(frozen=True)
class DriftAllowlist:
    """3 section 으로 분리된 error taxonomy drift allowlist.

    Attributes:
        intended_no_code: code 인자를 영구적으로 갖지 않는 의도된 callsite.
        known_drift_fmt_error_no_code: baseline 시점에 code 가 부여되지
            않은 fmt.error callsite. #1843 이 단계적으로 제거.
        pending_migration: baseline 시점에 class-level code 도 없고
            ``EXCEPTION_TO_SPEC`` 등록도 안 된 ``*Error`` class.
            #1842/#1843 이 단계적으로 등록.
    """

    intended_no_code: tuple[FmtErrorAllowlistEntry, ...] = field(default_factory=tuple)
    known_drift_fmt_error_no_code: tuple[FmtErrorAllowlistEntry, ...] = field(
        default_factory=tuple
    )
    pending_migration: tuple[ExceptionAllowlistEntry, ...] = field(
        default_factory=tuple,
    )


def _default_allowlist_path() -> Path:
    """default YAML 위치 (본 helper 와 동일 디렉토리)."""
    return Path(__file__).parent / "error_drift_allowlist.yaml"


def load_drift_allowlist(path: Path | None = None) -> DriftAllowlist:
    """``error_drift_allowlist.yaml`` 을 파싱해 :class:`DriftAllowlist` 반환.

    Args:
        path: 로드할 YAML 경로. ``None`` 이면 helper 와 동일 디렉토리의
            ``error_drift_allowlist.yaml`` 사용. 후속 enforcement test 가
            fixture YAML 을 주입할 수 있다.

    Returns:
        :class:`DriftAllowlist`: 3 section 의 frozen dataclass tuple.
    """
    yaml_path = path if path is not None else _default_allowlist_path()
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}

    def _fmt_entries(key: str) -> tuple[FmtErrorAllowlistEntry, ...]:
        raw = data.get(key) or []
        return tuple(
            FmtErrorAllowlistEntry(
                path=str(item["path"]),
                line=int(item["line"]),
                snippet_sha1=str(item["snippet_sha1"]),
                reason=str(item.get("reason", "")),
            )
            for item in raw
        )

    raw_exc = data.get("pending_migration") or []
    exc_entries = tuple(
        ExceptionAllowlistEntry(
            module=str(item["module"]),
            class_anchor=str(item["class_anchor"]),
            reason=str(item.get("reason", "")),
        )
        for item in raw_exc
    )

    return DriftAllowlist(
        intended_no_code=_fmt_entries("intended_no_code"),
        known_drift_fmt_error_no_code=_fmt_entries("known_drift_fmt_error_no_code"),
        pending_migration=exc_entries,
    )


# ── public surface ────────────────────────────────────────────────────────


__all__ = [
    "AuthMetadata",
    "CliLeafCommand",
    "DriftAllowlist",
    "ExceptionAllowlistEntry",
    "ExceptionClassInfo",
    "FmtErrorAllowlistEntry",
    "FmtErrorCallsite",
    "iter_click_leaf_commands",
    "iter_command_auth_metadata",
    "iter_exception_classes",
    "iter_fmt_error_calls",
    "iter_ipc_command_specs",
    "load_drift_allowlist",
]
