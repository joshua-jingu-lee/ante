"""``_create_services`` 계열 mock anti-pattern scanner (#1900).

``src/ante/cli/commands/*.py`` 의 ``@asynccontextmanager`` factory 들을 자동
수집(introspection)하여 allowlist로 잡고, ``tests/unit/`` 의 ``patch`` 호출 중
다음 anti-pattern 들을 보고한다.

1. **tuple-return on plain MagicMock**::

       with patch("ante.cli.commands.bot._create_services") as mock_cs:
           mock_cs.return_value = (db, eb, mgr, svc)

       # 또는 default MagicMock + return_value kwarg
       with patch(
           "ante.cli.commands.bot._create_services",
           return_value=(db, eb, mgr, svc),
       ):

   ``return_value`` 가 ``async with`` 호출 시 ``__aenter__`` 가 없는 tuple/
   MagicMock 으로 설정되면 production async ctxmgr lifecycle을 깨뜨린다.

2. **AsyncMock with tuple return_value**::

       with patch(
           "ante.cli.commands.bot._create_services",
           new_callable=AsyncMock,
           return_value=(db, eb, mgr, svc),
       ):

   ``AsyncMock`` 이 coroutine 을 돌리지만 결과는 tuple이라 ``async with`` 에
   직접 사용 불가.

3. **plain ``new=`` substitute (non-async-ctxmgr)**::

       with patch(
           "ante.cli.commands.bot._create_services",
           new=MagicMock(return_value=(...)),
       ):

       # ``new`` 는 두 번째 positional 인수로도 전달 가능 (signature:
       # ``patch(target, new, spec, create, spec_set, autospec, new_callable)``)
       with patch(
           "ante.cli.commands.bot._create_services",
           MagicMock(return_value=(...)),
       ):

   ``async with`` 패턴을 모사하지 않는 ``new=`` substitute. ``new`` 내부
   ``return_value`` 가 tuple 이면 ``tuple-return-on-patch`` 로 보고된다.

4. **async def stub without ctx kwarg**::

       async def _stub():
           return (db, eb, ...)
       with patch("ante.cli.commands.bot._create_services", new=_stub):
           ...

   ``async with`` 호출이 fail하고, ``ctx=`` kwarg 전달 시 ``TypeError`` 발생.

5. **decorator 형태 (``@patch(...)``)** — codex review attempt 2 finding 2.

   위 1~4 패턴은 ``with patch(...)`` (With statement) 뿐 아니라 함수/메소드
   데코레이터 형태로도 등장한다::

       @patch("ante.cli.commands.bot._create_services", return_value=(...))
       def test_x(...): ...

       @patch(
           "ante.cli.commands.bot._create_services",
           new_callable=AsyncMock,
           return_value=(...),
       )
       def test_x(self, mock_): ...

   scanner 는 ``FunctionDef``/``AsyncFunctionDef`` 의 ``decorator_list`` 안의
   ``patch(...)`` 호출도 with-statement 와 동일한 로직으로 검사한다.

Helper(``mock_*_factory(...)``) 또는 ``@asynccontextmanager`` 로 직접 정의된
async ctxmgr 만 정상으로 인정한다.

allowlist는 ``broker._create_account_service`` 만 explicit-deny (legacy
plain await-tuple 패턴 — #1818 follow-up). 그 외 모든 CLI async ctxmgr
factory를 자동 sweep 대상으로 한다.

Usage::

    python scripts/scan_create_services_anti_pattern.py tests/unit/

종료 코드 0 = 위반 0건, 1 = 위반 발견.
"""

from __future__ import annotations

import argparse
import ast
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CLI_COMMANDS_DIR = REPO_ROOT / "src" / "ante" / "cli" / "commands"

# Legacy factory 명시 제외 (broker._create_account_service — #1818 follow-up).
LEGACY_DENY = {"ante.cli.commands.broker._create_account_service"}


@dataclass(frozen=True)
class Violation:
    """anti-pattern 1건."""

    path: Path
    lineno: int
    kind: str
    target: str
    detail: str

    def format(self) -> str:
        try:
            rel = self.path.resolve().relative_to(REPO_ROOT)
        except ValueError:
            rel = self.path
        return f"{rel}:{self.lineno}: [{self.kind}] {self.target} — {self.detail}"


# ── Step 1: production factory allowlist 자동 수집 ─────────────────────


def discover_async_ctxmgr_factories() -> set[str]:
    """``src/ante/cli/commands/*.py`` 에서 ``@asynccontextmanager`` 적용 async
    함수의 fully-qualified target string set 을 반환한다.

    예: ``ante.cli.commands.bot._create_services``.
    """
    targets: set[str] = set()
    for py_path in sorted(CLI_COMMANDS_DIR.glob("*.py")):
        if py_path.name.startswith("_") and py_path.name != "__init__.py":
            # private helper (e.g. _password.py) 도 stub 정의가 있으면 검사
            pass
        module_name = py_path.stem
        if module_name == "__init__":
            continue
        try:
            tree = ast.parse(py_path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.AsyncFunctionDef):
                continue
            if not _has_async_ctxmgr_decorator(node):
                continue
            target = f"ante.cli.commands.{module_name}.{node.name}"
            if target in LEGACY_DENY:
                continue
            targets.add(target)
    return targets


def _has_async_ctxmgr_decorator(node: ast.AsyncFunctionDef) -> bool:
    """``@asynccontextmanager`` 데코레이터 적용 여부."""
    for deco in node.decorator_list:
        # forms: ``asynccontextmanager`` / ``contextlib.asynccontextmanager``
        if isinstance(deco, ast.Name) and deco.id == "asynccontextmanager":
            return True
        if isinstance(deco, ast.Attribute) and deco.attr == "asynccontextmanager":
            return True
    return False


# ── Step 2: tests/unit/ 내 위반 검출 ────────────────────────────────────


class PatchVisitor(ast.NodeVisitor):
    """``patch("ante.cli.commands.<mod>.<fn>", ...)`` 호출을 분석."""

    def __init__(self, path: Path, allowlist: set[str]) -> None:
        self.path = path
        self.allowlist = allowlist
        self.violations: list[Violation] = []
        # async ctxmgr stubs (name -> bool indicating ctx kwarg accepted)
        # multi-pass: 1st pass collect stubs, 2nd pass analyze patch sites.
        self._async_def_stubs: dict[str, ast.AsyncFunctionDef] = {}

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._async_def_stubs[node.name] = node
        self._check_decorator_list(node.decorator_list)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._check_decorator_list(node.decorator_list)
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        # 클래스 데코레이터에서도 patch(...) 가 등장 가능 (e.g. @patch(... ) on class).
        self._check_decorator_list(node.decorator_list)
        self.generic_visit(node)

    def _check_decorator_list(self, decorators: list[ast.expr]) -> None:
        """``@patch(...)`` 형태의 데코레이터를 with-statement 와 동일한 anti-pattern
        규칙으로 검사한다 (codex review attempt 2 finding 2).

        ``@patch(target, ...)`` / ``@patch.object(...)`` 둘 다 ``Call`` 노드로
        등장. ``patch.object`` 는 첫 번째 인수가 string target이 아니라 객체
        참조이므로 ``_extract_patch_target`` 에서 ``None`` 이 반환되어 자연스럽게
        스킵된다. ``patch(target, ...)`` 형태만 본격 분석한다.
        """
        for deco in decorators:
            if not isinstance(deco, ast.Call):
                continue
            if not self._is_patch_call(deco):
                continue
            self._check_patch_call(deco, parent_with=None, alias=None)

    def visit_With(self, node: ast.With) -> None:
        for item in node.items:
            self._check_with_item(item, node)
        self.generic_visit(node)

    def _check_with_item(self, item: ast.withitem, parent_with: ast.With) -> None:
        call = item.context_expr
        if not isinstance(call, ast.Call):
            return
        if not self._is_patch_call(call):
            return
        alias: str | None = None
        if item.optional_vars is not None and isinstance(item.optional_vars, ast.Name):
            alias = item.optional_vars.id
        self._check_patch_call(call, parent_with=parent_with, alias=alias)

    def _check_patch_call(
        self,
        call: ast.Call,
        parent_with: ast.With | None,
        alias: str | None,
    ) -> None:
        """``patch(target, ...)`` 호출(``with`` 문맥 또는 데코레이터)에 대한
        공통 anti-pattern 검사 로직.
        """
        target = self._extract_patch_target(call)
        if target is None or target not in self.allowlist:
            return

        # Inspect patch kwargs/new value
        (
            new_value,
            new_callable_value,
            return_value_kwarg,
            side_effect_kwarg,
        ) = self._extract_patch_kwargs(call)

        # Case A: new_callable=AsyncMock + return_value=tuple
        if new_callable_value is not None and return_value_kwarg is not None:
            if self._is_asyncmock(new_callable_value) and self._is_tuple_or_list(
                return_value_kwarg
            ):
                self.violations.append(
                    Violation(
                        path=self.path,
                        lineno=call.lineno,
                        kind="asyncmock-tuple-return",
                        target=target,
                        detail=(
                            "new_callable=AsyncMock + return_value=tuple — "
                            "async with 가 동작하지 않는다. "
                            "mock_*_factory(...) 사용 권장."
                        ),
                    )
                )
                return

        # Case A': default MagicMock + return_value=tuple (no new/new_callable)
        # ``patch(target, return_value=(db, ...))`` 형태. default MagicMock 이
        # tuple 을 반환해 ``async with`` 진입 시 ``__aenter__`` 가 없다.
        if (
            new_value is None
            and new_callable_value is None
            and return_value_kwarg is not None
            and self._is_tuple_or_list(return_value_kwarg)
        ):
            self.violations.append(
                Violation(
                    path=self.path,
                    lineno=call.lineno,
                    kind="tuple-return-on-patch",
                    target=target,
                    detail=(
                        "patch(..., return_value=tuple) — default MagicMock 이 "
                        "tuple 을 반환해 async with 가 동작하지 않는다. "
                        "mock_*_factory(...) 사용 권장."
                    ),
                )
            )
            return

        # Case B: new=async_def_without_ctx OR new=MagicMock/non-ctxmgr
        if new_value is not None:
            self._check_new_substitute(new_value, call, target)

        # Case B': side_effect=async_def_without_ctx — production 이 ctx=
        # kwarg 로 호출하므로 stub 도 같은 시그니처를 가져야 한다.
        if side_effect_kwarg is not None:
            self._check_side_effect_stub(side_effect_kwarg, call, target)

        # Case C: with patch(...) as mock_cs: mock_cs.return_value = tuple
        # 데코레이터 형태(parent_with=None, alias=None) 는 alias 가 없으므로 skip.
        if parent_with is not None and alias is not None:
            self._check_with_alias_tuple_return(alias, parent_with, call, target)

    @staticmethod
    def _is_patch_call(call: ast.Call) -> bool:
        # patch(...) or unittest.mock.patch(...) or mock.patch(...)
        func = call.func
        if isinstance(func, ast.Name) and func.id == "patch":
            return True
        if isinstance(func, ast.Attribute) and func.attr == "patch":
            return True
        return False

    @staticmethod
    def _extract_patch_target(call: ast.Call) -> str | None:
        if not call.args:
            return None
        arg = call.args[0]
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            return arg.value
        return None

    @staticmethod
    def _extract_patch_kwargs(
        call: ast.Call,
    ) -> tuple[ast.expr | None, ast.expr | None, ast.expr | None, ast.expr | None]:
        """``unittest.mock.patch(target, new, spec, create, spec_set, autospec,
        new_callable, *, **kwargs)`` 의 positional / keyword 인수를 모두 훑어
        ``(new, new_callable, return_value, side_effect)`` 를 추출한다.

        positional signature (Python stdlib):

            patch(target, new=DEFAULT, spec=None, create=False,
                  spec_set=None, autospec=None, new_callable=None,
                  *, unsafe=False, **kwargs)

        ``return_value`` / ``side_effect`` 는 ``**kwargs`` 패스스루로만 전달되어
        positional 매핑이 불가능하다 (keyword 전용).
        """
        new_value: ast.expr | None = None
        new_callable_value: ast.expr | None = None
        return_value_kwarg: ast.expr | None = None
        side_effect_kwarg: ast.expr | None = None

        # positional mapping: index 0 = target (이미 _extract_patch_target),
        # index 1 = new, index 6 = new_callable.
        # 1..6: (new, spec, create, spec_set, autospec, new_callable)
        positional_slots: list[str] = [
            "target",
            "new",
            "spec",
            "create",
            "spec_set",
            "autospec",
            "new_callable",
        ]
        for idx, arg in enumerate(call.args):
            if idx == 0:
                continue
            if idx >= len(positional_slots):
                break
            slot = positional_slots[idx]
            if slot == "new":
                new_value = arg
            elif slot == "new_callable":
                new_callable_value = arg

        for kw in call.keywords:
            if kw.arg == "new":
                new_value = kw.value
            elif kw.arg == "new_callable":
                new_callable_value = kw.value
            elif kw.arg == "return_value":
                return_value_kwarg = kw.value
            elif kw.arg == "side_effect":
                side_effect_kwarg = kw.value
        return new_value, new_callable_value, return_value_kwarg, side_effect_kwarg

    @staticmethod
    def _is_asyncmock(node: ast.expr) -> bool:
        if isinstance(node, ast.Name) and node.id == "AsyncMock":
            return True
        if isinstance(node, ast.Attribute) and node.attr == "AsyncMock":
            return True
        return False

    @staticmethod
    def _is_magicmock(node: ast.expr) -> bool:
        if isinstance(node, ast.Name) and node.id == "MagicMock":
            return True
        if isinstance(node, ast.Attribute) and node.attr == "MagicMock":
            return True
        return False

    @staticmethod
    def _is_tuple_or_list(node: ast.expr) -> bool:
        return isinstance(node, (ast.Tuple, ast.List))

    @staticmethod
    def _call_return_value_kwarg(call: ast.Call) -> ast.expr | None:
        """``MagicMock(return_value=...)`` / ``AsyncMock(return_value=...)`` 등
        Call 노드의 ``return_value=`` keyword 인수 값을 반환한다.
        """
        for kw in call.keywords:
            if kw.arg == "return_value":
                return kw.value
        return None

    def _check_new_substitute(
        self, new_value: ast.expr, call: ast.Call, target: str
    ) -> None:
        # new=AsyncMock(...) or new=AsyncMock() ← non-ctxmgr factory
        if isinstance(new_value, ast.Call):
            inner_return_value = self._call_return_value_kwarg(new_value)
            inner_returns_tuple = (
                inner_return_value is not None
                and self._is_tuple_or_list(inner_return_value)
            )
            if self._is_asyncmock(new_value.func):
                # AsyncMock() is a coroutine, not async ctxmgr.
                # If return_value kwarg/attr is tuple, this fails async with.
                # Heuristic: any AsyncMock() substitute for these factories is suspect
                # unless explicit MagicMock side_effect = async ctxmgr.
                if inner_returns_tuple:
                    self.violations.append(
                        Violation(
                            path=self.path,
                            lineno=call.lineno,
                            kind="tuple-return-on-patch",
                            target=target,
                            detail=(
                                "new=AsyncMock(return_value=tuple) — "
                                "async with 가 동작하지 않는다. "
                                "mock_*_factory(...) 사용 권장."
                            ),
                        )
                    )
                    return
                self.violations.append(
                    Violation(
                        path=self.path,
                        lineno=call.lineno,
                        kind="asyncmock-new-substitute",
                        target=target,
                        detail=(
                            "new=AsyncMock(...) substitute — async ctxmgr lifecycle "
                            "을 모사하지 않는다. mock_*_factory(...) 사용 권장."
                        ),
                    )
                )
                return
            if self._is_magicmock(new_value.func):
                if inner_returns_tuple:
                    self.violations.append(
                        Violation(
                            path=self.path,
                            lineno=call.lineno,
                            kind="tuple-return-on-patch",
                            target=target,
                            detail=(
                                "new=MagicMock(return_value=tuple) — "
                                "async with 가 동작하지 않는다. "
                                "mock_*_factory(...) 사용 권장."
                            ),
                        )
                    )
                    return
                self.violations.append(
                    Violation(
                        path=self.path,
                        lineno=call.lineno,
                        kind="magicmock-new-substitute",
                        target=target,
                        detail=(
                            "new=MagicMock(...) substitute — async ctxmgr lifecycle "
                            "을 모사하지 않는다. mock_*_factory(...) 사용 권장."
                        ),
                    )
                )
                return

        # new=<name referencing local async def stub>
        if isinstance(new_value, ast.Name) and new_value.id in self._async_def_stubs:
            stub = self._async_def_stubs[new_value.id]
            if not self._stub_is_ctxmgr(stub):
                self.violations.append(
                    Violation(
                        path=self.path,
                        lineno=call.lineno,
                        kind="async-def-stub-not-ctxmgr",
                        target=target,
                        detail=(
                            f"new={new_value.id} — async def stub은 ctxmgr 가 아니라 "
                            "coroutine 만 반환. async with 가 fail. "
                            "@asynccontextmanager 또는 mock_*_factory 사용 권장."
                        ),
                    )
                )
                return
            if not self._stub_accepts_ctx_kwarg(stub):
                self.violations.append(
                    Violation(
                        path=self.path,
                        lineno=call.lineno,
                        kind="async-stub-missing-ctx-kwarg",
                        target=target,
                        detail=(
                            f"new={new_value.id} — production 은 ``ctx=`` kwarg 로 "
                            "호출하지만 stub이 ctx 파라미터를 받지 않는다."
                        ),
                    )
                )

    @staticmethod
    def _stub_is_ctxmgr(stub: ast.AsyncFunctionDef) -> bool:
        for deco in stub.decorator_list:
            if isinstance(deco, ast.Name) and deco.id == "asynccontextmanager":
                return True
            if isinstance(deco, ast.Attribute) and deco.attr == "asynccontextmanager":
                return True
        return False

    @staticmethod
    def _stub_accepts_ctx_kwarg(stub: ast.AsyncFunctionDef) -> bool:
        # ``**kwargs`` 가 있으면 ctx= kwarg 호환 (production 호출 시 ctx=
        # 가 kwargs 에 들어간다).
        if stub.args.kwarg is not None:
            return True
        all_args = (
            list(stub.args.args)
            + list(stub.args.kwonlyargs)
            + list(stub.args.posonlyargs)
        )
        for arg in all_args:
            if arg.arg == "ctx":
                return True
        return False

    def _check_side_effect_stub(
        self, side_effect_value: ast.expr, call: ast.Call, target: str
    ) -> None:
        """``side_effect=<name>`` 이 local async def stub 을 참조하면 ctx kwarg
        과 ctxmgr lifecycle 모두 검사한다.
        """
        if not isinstance(side_effect_value, ast.Name):
            return
        if side_effect_value.id not in self._async_def_stubs:
            return
        stub = self._async_def_stubs[side_effect_value.id]
        if not self._stub_accepts_ctx_kwarg(stub):
            self.violations.append(
                Violation(
                    path=self.path,
                    lineno=call.lineno,
                    kind="async-stub-side-effect-missing-ctx-kwarg",
                    target=target,
                    detail=(
                        f"side_effect={side_effect_value.id} — production은 "
                        "``ctx=`` kwarg 로 호출하지만 stub이 ctx 파라미터 부재. "
                        "mock_*_factory 사용 권장."
                    ),
                )
            )
        elif not self._stub_is_ctxmgr(stub):
            # production 은 ``async with`` 진입이라 단순 coroutine 도 fail.
            self.violations.append(
                Violation(
                    path=self.path,
                    lineno=call.lineno,
                    kind="async-stub-side-effect-not-ctxmgr",
                    target=target,
                    detail=(
                        f"side_effect={side_effect_value.id} — async def stub 은 "
                        "async ctxmgr 가 아니라 coroutine 을 반환한다. "
                        "@asynccontextmanager 변환 또는 mock_*_factory 권장."
                    ),
                )
            )

    def _check_with_alias_tuple_return(
        self,
        alias: str,
        parent_with: ast.With,
        call: ast.Call,
        target: str,
    ) -> None:
        """``with patch(...) as mock_cs:`` body 안에서 ``mock_cs.return_value =
        <tuple or MagicMock>`` 할당을 찾는다.
        """
        for stmt in ast.walk(parent_with):
            if not isinstance(stmt, ast.Assign):
                continue
            for tgt in stmt.targets:
                if not isinstance(tgt, ast.Attribute):
                    continue
                if tgt.attr != "return_value":
                    continue
                base = tgt.value
                if not isinstance(base, ast.Name) or base.id != alias:
                    continue
                # alias.return_value = tuple/list → 위반
                value = stmt.value
                if isinstance(value, (ast.Tuple, ast.List)):
                    self.violations.append(
                        Violation(
                            path=self.path,
                            lineno=stmt.lineno,
                            kind="tuple-return-on-patch",
                            target=target,
                            detail=(
                                f"{alias}.return_value = tuple — "
                                "async with 가 동작하지 않음. mock_*_factory 권장."
                            ),
                        )
                    )
                elif isinstance(value, ast.Call) and (
                    self._is_magicmock(value.func) or self._is_asyncmock(value.func)
                ):
                    self.violations.append(
                        Violation(
                            path=self.path,
                            lineno=stmt.lineno,
                            kind="mock-return-on-patch",
                            target=target,
                            detail=(
                                f"{alias}.return_value = MagicMock/AsyncMock — "
                                "async with 가 동작 안할 가능성. mock_*_factory 권장."
                            ),
                        )
                    )


def scan_file(path: Path, allowlist: set[str]) -> list[Violation]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return []
    visitor = PatchVisitor(path, allowlist)
    visitor.visit(tree)
    return visitor.violations


def scan_paths(paths: Iterable[Path], allowlist: set[str]) -> list[Violation]:
    violations: list[Violation] = []
    for root in paths:
        if root.is_file() and root.suffix == ".py":
            violations.extend(scan_file(root, allowlist))
            continue
        for py_path in sorted(root.rglob("*.py")):
            violations.extend(scan_file(py_path, allowlist))
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="검사 대상 경로(파일 또는 디렉토리, 보통 tests/unit/).",
    )
    parser.add_argument(
        "--list-allowlist",
        action="store_true",
        help="자동 수집된 production factory allowlist 만 출력하고 종료.",
    )
    args = parser.parse_args(argv)

    allowlist = discover_async_ctxmgr_factories()
    if args.list_allowlist:
        for t in sorted(allowlist):
            print(t)
        print(f"# total: {len(allowlist)} (legacy denied: {sorted(LEGACY_DENY)})")
        return 0

    if not args.paths:
        parser.error("paths required (or use --list-allowlist)")

    violations = scan_paths(args.paths, allowlist)
    if not violations:
        print(
            f"OK — anti-pattern 0건 (allowlist {len(allowlist)} factory, "
            f"denied: {sorted(LEGACY_DENY)})"
        )
        return 0

    for v in violations:
        print(v.format())
    print(f"\nFAIL — anti-pattern {len(violations)} 건")
    return 1


if __name__ == "__main__":
    sys.exit(main())
