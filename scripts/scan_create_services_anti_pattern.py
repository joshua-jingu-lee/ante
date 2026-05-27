"""``_create_services`` 계열 mock anti-pattern scanner (#1900).

ADVISORY MODE (#1900 attempt 7 final)
======================================

본 scanner 는 **advisory tool** 이다. 정적 AST 분석으로 best-effort 하게
anti-pattern 형태를 detect 하며, false positive / false negative 가 모두
가능하다. 기본 동작은 다음과 같다.

* violation 발견 시 stdout 으로 reporting (사람과 agent 모두 읽기 좋은 형식).
* **exit code 는 항상 ``0``** — CI 게이트가 아니다. helper migration 검토 보조용.
* 기본 verification 본질은 **named 회귀 4건 + helper contract test 22/22** 이며,
  본 scanner 는 그 보조 도구다.

CI gate / pre-commit 등에서 차단 게이트로 쓰려면 ``--strict`` 플래그를 명시한다.
``--strict`` 가 지정되면 violation 발견 시 exit code 1 을 반환한다.

본 scanner 의 알려진 한계(KNOWN-LIMITATION 섹션 참조)는 정밀화하지 않는다.
추가 형태(false negative)나 추가 false positive 가 발견되면 별도 follow-up
이슈로 분리한다 — 본 PR 안에서 unbounded 하게 scanner 정밀도를 확장하지 않는다.

본 scanner 사용 패턴
====================

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

6. **decorator-injected mock arg body assignment** — codex review attempt 3
   finding 1.

   ``@patch(target)`` 데코레이터는 함수 인자에 mock 객체를 주입한다. 함수
   본문에서 주입된 mock arg 에 ``return_value = tuple`` 을 직접 할당하는 형태
   도 동일 anti-pattern 이다::

       @patch("ante.cli.commands.bot._create_services")
       def test_foo(self, mock_cs):
           mock_cs.return_value = (db, eb, mgr, svc)   # tuple-return 위반

   Python ``@patch`` 의 mock 주입 규칙은 데코레이터 스택의 가장 안쪽(가장 아래)
   부터 첫 mock arg 로 매핑된다 (bottom-up applied, but 함수 인자 매핑은
   innermost-first). scanner 는 ``decorator_list`` 를 역순으로 함수 인자에
   매핑한 뒤, 매핑된 alias 에 대해 body 의 ``<alias>.return_value = tuple/list``
   할당을 ``tuple-return-on-patch-decorator-alias`` 카테고리로 보고한다.

Helper(``mock_*_factory(...)``) 또는 ``@asynccontextmanager`` 로 직접 정의된
async ctxmgr 만 정상으로 인정한다.

allowlist는 ``broker._create_account_service`` 만 explicit-deny (legacy
plain await-tuple 패턴 — #1818 follow-up). 그 외 모든 CLI async ctxmgr
factory를 자동 sweep 대상으로 한다.

또한 각 production factory 의 시그니처(positional args + kwonly args)도
함께 수집하여 ``new=<stub>`` / ``side_effect=<stub>`` 로 지정된 local stub 이
production 호출 시그니처를 **arity** 측면에서 받지 못하면 위반으로 보고한다
(codex review attempt 5 finding 1 + attempt 6 finding 1 — false-positive fix).
예::

    # production: async def _create_treasury(account_id, *, ctx=None)
    async def _stub(*, ctx=None):                 # ← positional 0개, 부족
        ...
    with patch("ante.cli.commands.treasury._create_treasury", new=_stub):
        ...   # production 이 _stub("acc", ctx=ctx) 호출 시 TypeError

stub 이 ``*args`` / ``**kwargs`` 로 모든 인수를 swallow 하거나, **arity** 가
production positional 이상이면 통과 (stub 인자 **이름** 은 비교하지 않는다 —
positional forward 의미상 이름 무관, attempt 6 finding 1 false-positive fix).

Usage::

    # advisory (default) — violation 출력만, exit 0
    python scripts/scan_create_services_anti_pattern.py tests/unit/

    # strict — violation 있으면 exit 1 (사용자 opt-in)
    python scripts/scan_create_services_anti_pattern.py --strict tests/unit/

종료 코드 (advisory, default): **항상 0**.
종료 코드 (``--strict``): 위반 0건이면 0, 위반 발견이면 1.

KNOWN-LIMITATION (정적 분석 범위 한계)
======================================

본 advisory tool 의 알려진 한계
-------------------------------

본 scanner 는 정적 AST 분석으로 다음 anti-pattern 형태를 catch 한다 (ON):

* ``with patch(...) as alias: alias.return_value = tuple``
* ``with patch(...)`` (1-positional + ``return_value=tuple`` kwarg)
* ``with patch(..., new_callable=<callable>, return_value=tuple)``
  (codex review attempt 4 finding 1: ``AsyncMock``/``MagicMock``/generic
  ``Mock``/custom callable 모두 catch. ``AsyncMock`` 만 별도 카테고리,
  나머지는 통합 ``tuple-return-on-patch`` 보고.)
* ``with patch(target, MagicMock/AsyncMock(return_value=tuple))`` (2-positional
  ``new``)
* ``@patch(...)`` 데코레이터 (위 모든 형태 + decorated FunctionDef body 의
  ``mock_arg.return_value = tuple`` 할당)
* **Target-specific stub call-signature validation (ON)** — codex review
  attempt 5 finding 1: production factory 의 positional args 를 정확히 수집해
  ``new=<stub>`` / ``side_effect=<stub>`` 가 같은 positional args 를 받을 수
  있는지 검증. 예: ``treasury._create_treasury(account_id, *, ctx=None)``
  의 stub 이 ``ctx=None`` 만 받으면 ``async-stub-positional-arity-mismatch``
  위반.
* **Class-level @patch decorator method body assignment (ON)** — codex review
  attempt 5 finding 2 + attempt 6 finding 2: ``@patch(target)`` 이 클래스
  데코레이터로 적용되면 클래스 내 **``test_`` 로 시작하는 method (Python
  ``unittest.mock.patch.TEST_PREFIX`` 규칙) 만** 매핑 검사 대상이다. helper
  method (``_setup``, ``_helper``, ``setUp``, ``tearDown`` 등) 는 class
  decorator 의 mock 주입을 받지 않으므로 매핑에서 제외한다. method args 는
  ``self`` 다음에 method-level decorator slot (innermost-first) → class-level
  decorator slot (innermost-first) 순으로 매핑한다 (Python
  ``unittest.mock.patch`` 실제 주입 규칙).

Decorator stack 의 mock arg slot 매핑은 Python ``unittest.mock.patch`` 실제
주입 규칙과 정렬한다 (codex review attempt 4 finding 2):

* ``@patch(target)`` (no new/new_callable): mock arg 주입 → slot 소비 + alias 검사
* ``@patch(target, new=X)``: mock arg 주입 안 됨 → slot 자체 소비 안 함 (skip)
* ``@patch(target, new_callable=Cls)``: mock arg 주입 → slot 소비 + alias 검사

또한 ``scan_file`` 은 2-pass 로 동작한다 (codex review attempt 4 finding 3):

1. Pass 1 — ``ast.walk(tree)`` 로 모든 ``AsyncFunctionDef`` 를 pre-collect 하여
   ``_async_def_stubs`` 에 등록한다.
2. Pass 2 — ``visitor.visit(tree)`` 로 patch site 를 검사한다.

따라서 ``new=<stub>`` / ``side_effect=<stub>`` 의 stub 정의가 patch site 보다
파일 아래쪽에 있어도 정확히 resolve 된다.

다음은 본 scanner 범위 밖 (정적 분석으로는 catch 불가, follow-up 분리, **본
PR scope 밖**):

* ``@patch.object(Class, "attr", ...)`` — target 이 string 이 아닌 reference
* ``patch.multiple``, ``patch.dict``, ``patch.stopall`` 등 부수 API
* 동적 patch (런타임에 mock 객체를 다른 변수로 전달 후 ``alias.return_value`` 할당)
* mock 객체를 매개변수로 받는 helper 함수 (간접 mock 조작)
* ``side_effect`` 로 tuple 을 yield 하는 generator/iterator 형태
  (의도적일 수 있음)

이러한 형태가 실제로 anti-pattern 으로 사용되면 별도 이슈로 분리하여 추가
보강한다 (#1900 follow-up). 본 scanner 는 advisory tool 로 known-incomplete
정밀도를 normative 로 선언한다.

알려진 false positive (advisory)
--------------------------------

본 scanner 는 정적 분석의 trade-off 로 다음 false positive 형태를 명시적으로
완화한다 (#1900 attempt 7 final, Finding 1/2 fix 결과):

* (Finding 1 — fix) ``new=<stub>`` / ``side_effect=<stub>`` 의 stub positional
  arg **이름** 이 production positional arg 이름과 다르더라도 위반이 아니다.
  실제 호출은 positional forward (``stub("acc", ctx=ctx)``) 이므로 이름이 아닌
  **arity (수용 가능 여부)** 만 검사한다. 예::

      # production: async def _create_treasury(account_id, *, ctx=None)
      @asynccontextmanager
      async def _stub(acc, *, ctx=None):   # 이름 "acc" ≠ "account_id" 이지만 호환
          yield (...)

  scanner 는 stub positional arity (``*args`` 또는 ``len(stub) >= len(prod)``)
  만 검증하며 이름 비교는 수행하지 않는다.

* (Finding 2 — fix) class-level ``@patch(target)`` 데코레이터의 mock 주입 대상
  은 **클래스 내 ``test_`` 로 시작하는 method 만** 이다 (Python ``unittest.mock.
  patch`` 의 ``TEST_PREFIX = "test"`` 규칙). helper method (``_setup``,
  ``_helper``, ``setUp``, ``tearDown`` 등) 는 mock 주입을 받지 않으므로 class
  decorator stack 매핑에서 제외한다. 예::

      @patch("ante.cli.commands.bot._create_services")
      class TestX:
          def _helper(self, value):          # ← test_ 접두어 없음 → mock 주입 안 됨
              return value

          def test_a(self, mock_services):   # ← mock 주입 받음 (class decorator)
              mock_services.return_value = ...

알려진 false negative (advisory)
--------------------------------

본 scanner 의 sound 범위 밖 (위 "본 PR scope 밖" 5개 형태) + #1900 attempt 1~5
finding 5건은 모두 본 PR 에서 fix 되었으나, 추가 형태가 발견되면 별도 follow-up
이슈로 분리한다. advisory mode 의 본질은 unbounded scanner refinement 가 아니라
사람/agent 가 reporting 을 검토 보조 도구로 활용하는 것이다.

본 PR scope 요약
----------------

* 10 factory ``_create_services`` 계열 mock anti-pattern sweep
* 각 factory 별 ``mock_*_factory`` helper + helper contract test 22 건
* 4건 named 회귀 (#1900 본문 명시) PASS lock
* scanner: **advisory** verification (default exit 0, ``--strict`` opt-in)
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

# ``unittest.mock.patch`` 의 class decorator 가 mock 을 주입하는 method prefix
# 기본값 (Python 표준 라이브러리 ``patch.TEST_PREFIX = "test"``). 본 scanner 는
# class-level decorator stack 을 ``test`` 접두어 method 에만 매핑한다 (codex
# review attempt 6 finding 2 — false-positive fix).
_TEST_PREFIX = "test"


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


@dataclass(frozen=True)
class FactorySignature:
    """production async ctxmgr factory 의 call-signature (codex review attempt
    5 finding 1).

    stub 호출 시 production 의 positional args 를 받지 못하면 ``TypeError`` 가
    발생한다. scanner 는 ``new=<stub>`` / ``side_effect=<stub>`` 가 같은
    positional/kwonly args 를 수용할 수 있는지 검증한다.
    """

    positional_args: tuple[str, ...]
    kwonly_args: tuple[str, ...]


# ── Step 1: production factory allowlist 자동 수집 ─────────────────────


def discover_async_ctxmgr_factories() -> dict[str, FactorySignature]:
    """``src/ante/cli/commands/*.py`` 에서 ``@asynccontextmanager`` 적용 async
    함수의 fully-qualified target → ``FactorySignature`` mapping 을 반환한다.

    예: ``ante.cli.commands.bot._create_services`` →
    ``FactorySignature(positional_args=('ctx',), kwonly_args=())``.

    하위 호환: ``dict in/keys()`` 로 ``set`` 처럼 사용 가능 (PatchVisitor 가
    ``target in self.allowlist`` 로 멤버십만 검사).
    """
    targets: dict[str, FactorySignature] = {}
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
            positional = tuple(
                a.arg for a in (list(node.args.posonlyargs) + list(node.args.args))
            )
            kwonly = tuple(a.arg for a in node.args.kwonlyargs)
            targets[target] = FactorySignature(
                positional_args=positional, kwonly_args=kwonly
            )
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

    def __init__(self, path: Path, allowlist: dict[str, FactorySignature]) -> None:
        self.path = path
        self.allowlist = allowlist
        self.violations: list[Violation] = []
        # class decorator stack (innermost-first) — codex review attempt 5
        # finding 2: class-level ``@patch(...)`` 가 모든 method 의 body 에
        # mock arg 를 주입하므로 visit 진입 시 push, leave 시 pop.
        self._class_decorator_stack: list[list[ast.Call]] = []
        # async ctxmgr stubs (name -> AsyncFunctionDef node).
        # 2-pass scan (codex review attempt 4 finding 3): ``scan_file`` 이
        # ``ast.walk`` 로 모든 ``AsyncFunctionDef`` 를 pre-collect 한 후
        # ``visitor.visit(tree)`` 로 patch site 검사를 수행한다. 이로써 파일 아래
        # 쪽에 정의된 async def stub 도 위쪽 patch site 검사에서 보인다.
        self._async_def_stubs: dict[str, ast.AsyncFunctionDef] = {}

    def prepare_async_def_stubs(self, tree: ast.AST) -> None:
        """Pass 1 (pre-visit): 트리 전체에서 ``AsyncFunctionDef`` 를 수집한다.

        ``scan_file`` 이 ``visitor.visit(tree)`` 호출 직전에 한 번 호출하여,
        patch site 검사 시 파일 순서와 무관하게 stub 참조가 보이도록 한다.
        """
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef):
                self._async_def_stubs[node.name] = node

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        # pre-collect 단계에서 이미 등록되었으므로 중복 등록 불요.
        # (defensive: 재진입에도 안전하도록 동일 키 덮어쓰기 허용)
        self._async_def_stubs[node.name] = node
        self._check_decorator_list(node.decorator_list, function_node=node)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._check_decorator_list(node.decorator_list, function_node=node)
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        # 클래스 데코레이터에서도 patch(...) 가 등장 가능 (e.g. @patch(... ) on class).
        # ``ClassDef`` 자체에는 mock 주입 함수 인자가 없으므로 alias-body 검사를
        # 직접 실행하진 않지만, **클래스 데코레이터는 클래스 내 모든 test method
        # 의 body 에 mock arg 를 주입한다** (Python ``unittest.mock.patch`` 실제
        # 동작). codex review attempt 5 finding 2 — class decorator stack 을
        # push 해 method 방문 시 method-level decorator 와 함께 매핑한다.
        self._check_decorator_list(node.decorator_list, function_node=None)
        # ``new=`` 가 지정되지 않은 patch decorator 만 slot 을 소비한다 (Finding 1
        # 정정 규칙과 동일). innermost-first 순으로 stack 에 push.
        class_patch_decos_innermost_first: list[ast.Call] = []
        for deco in reversed(node.decorator_list):
            if not isinstance(deco, ast.Call):
                continue
            if not self._is_patch_call(deco):
                continue
            new_value, _new_callable_value, _, _ = self._extract_patch_kwargs(deco)
            if new_value is not None:
                # ``new=`` 지정 patch 는 mock arg 를 주입하지 않으므로 slot 자체에서
                # 제외 — 본 stack 에 push 하지 않는다.
                continue
            class_patch_decos_innermost_first.append(deco)

        self._class_decorator_stack.append(class_patch_decos_innermost_first)
        try:
            self.generic_visit(node)
        finally:
            self._class_decorator_stack.pop()

    def _check_decorator_list(
        self,
        decorators: list[ast.expr],
        function_node: ast.FunctionDef | ast.AsyncFunctionDef | None,
    ) -> None:
        """``@patch(...)`` 형태의 데코레이터를 with-statement 와 동일한 anti-pattern
        규칙으로 검사한다 (codex review attempt 2 finding 2 + attempt 3 finding 1).

        ``@patch(target, ...)`` / ``@patch.object(...)`` 둘 다 ``Call`` 노드로
        등장. ``patch.object`` 는 첫 번째 인수가 string target이 아니라 객체
        참조이므로 ``_extract_patch_target`` 에서 ``None`` 이 반환되어 자연스럽게
        스킵된다. ``patch(target, ...)`` 형태만 본격 분석한다.

        ``function_node`` 가 주어지면 (FunctionDef/AsyncFunctionDef) decorator
        stack 을 역순으로 함수 인자에 매핑하여 body 의 ``<alias>.return_value =
        tuple`` 할당도 함께 검사한다 (attempt 3 finding 1).
        """
        # 1차: 각 decorator 의 patch(...) call 자체에 대한 anti-pattern 검사
        for deco in decorators:
            if not isinstance(deco, ast.Call):
                continue
            if not self._is_patch_call(deco):
                continue
            self._check_patch_call(deco, parent_with=None, alias=None)

        # 2차: decorator-injected mock arg 의 body assignment 검사
        if function_node is not None:
            self._check_decorator_mock_arg_body(decorators, function_node)

    def _check_decorator_mock_arg_body(
        self,
        decorators: list[ast.expr],
        function_node: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> None:
        """decorator stack 의 ``@patch(target)`` 매핑된 mock 함수 인자가 body
        에서 ``<alias>.return_value = tuple/list`` 로 사용되는지 검사한다
        (attempt 3 finding 1 + attempt 5 finding 2).

        Python ``@patch`` 의 mock 주입 규칙:

        ``decorator_list`` 는 source 순서대로 (위에서 아래) 저장. 적용은
        bottom-up. 함수 인자 매핑은 **가장 안쪽 (가장 아래) decorator 가 첫 mock
        arg**.

        예::

            @patch("A")     # 위 (outer)
            @patch("B")     # 가장 안쪽 (innermost, applied first)
            def test(self, mock_B, mock_A): ...

        ``decorator_list = [Call("A"), Call("B")]`` → 역순 ``[Call("B"),
        Call("A")]`` 을 함수 positional args (self/cls 제외) 에 순서대로 매핑.

        ``new`` 또는 ``new_callable`` 이 지정된 ``@patch`` 는 mock 인자를 주입하지
        않으므로 매핑에서 제외한다 (Python 스펙).

        Class-level ``@patch`` (codex review attempt 5 finding 2): test method
        의 args slot 은 ``self`` 다음에 **method-level decorator slot (innermost-
        first)** → **class-level decorator slot (innermost-first)** 순으로
        매핑된다. ``self._class_decorator_stack[-1]`` 가 현재 enclosing class
        decorator stack (이미 innermost-first 정렬, ``new=`` 제외).
        """
        # 1) 함수 positional args 에서 self/cls 제외한 리스트
        positional_args = list(function_node.args.posonlyargs) + list(
            function_node.args.args
        )
        if positional_args and positional_args[0].arg in ("self", "cls"):
            positional_args = positional_args[1:]

        # 2) decorator_list 역순 → 매핑 대상 patch decorator 만 필터.
        # Python ``unittest.mock.patch`` 의 mock arg 주입 규칙 (codex review
        # attempt 4 finding 2 정정):
        #
        #   * ``@patch(target)`` (no new/new_callable): mock arg **주입**
        #   * ``@patch(target, new=X)``: mock arg **주입 안 함** (X 그대로 사용)
        #     → slot 자체를 소비 안 함
        #   * ``@patch(target, new_callable=Cls)``: mock arg **주입** (Cls() 결과)
        #     → slot 소비 + alias 매핑/검사 대상
        #
        # ``new=`` 가 지정된 decorator 는 slot 매핑에서 완전 제외한다 (skip).
        # 그 외 (no new / new_callable=) 는 매핑 대상으로 보존.
        method_patch_decos_innermost_first: list[ast.Call] = []
        for deco in reversed(decorators):
            if not isinstance(deco, ast.Call):
                continue
            if not self._is_patch_call(deco):
                continue
            new_value, _new_callable_value, _, _ = self._extract_patch_kwargs(deco)
            if new_value is not None:
                # ``new=`` 지정 patch 는 mock arg 를 주입하지 않으므로 slot 매핑
                # 자체에서 제외한다. (Python 실제 주입 규칙)
                continue
            method_patch_decos_innermost_first.append(deco)

        # 2b) class decorator stack (innermost-first, ``new=`` 제외) 을 method
        # decorator slot 뒤에 append.
        #
        # codex review attempt 6 finding 2 — false positive fix: Python
        # ``unittest.mock.patch`` 의 class decorator 는 ``patch.TEST_PREFIX``
        # (기본값 ``"test"``) 로 시작하는 method 에만 mock 을 주입한다. helper
        # method (``_setup``, ``_helper``, ``setUp``, ``tearDown`` 등) 는 mock
        # 주입을 받지 않으므로 class decorator stack 매핑에서 제외한다.
        #
        # method-level decorator (``method_patch_decos_innermost_first``) 는
        # method name 과 무관하게 항상 매핑되므로 본 분기에 영향받지 않는다.
        all_patch_decos = list(method_patch_decos_innermost_first)
        if self._class_decorator_stack and function_node.name.startswith(_TEST_PREFIX):
            all_patch_decos.extend(self._class_decorator_stack[-1])

        # 3) 각 decorator 를 positional_args 의 앞부터 매핑하면서 alias 검사.
        # 이 단계에 도달한 decorator 는 모두 mock arg slot 을 소비한다
        # (no new + with-or-without new_callable). allowlist 밖 target 도
        # slot 은 소비되지만 검사 대상이 아니라 alias 검증을 건너뛴다.
        for idx, deco in enumerate(all_patch_decos):
            if idx >= len(positional_args):
                # 함수 시그니처에 mock arg 가 모자라면 매핑 불가 — 정적 매핑 한계.
                break
            target = self._extract_patch_target(deco)
            if target is None or target not in self.allowlist:
                # slot 은 소비되었지만 검사 대상이 아님.
                continue
            alias = positional_args[idx].arg
            self._check_function_body_alias_tuple_return(
                alias=alias,
                function_node=function_node,
                deco=deco,
                target=target,
            )

    def _check_function_body_alias_tuple_return(
        self,
        alias: str,
        function_node: ast.FunctionDef | ast.AsyncFunctionDef,
        deco: ast.Call,
        target: str,
    ) -> None:
        """함수 body 안에서 ``<alias>.return_value = tuple/list`` (또는
        ``MagicMock/AsyncMock``) 할당을 찾아 위반으로 보고한다.

        ``with patch(...) as alias:`` 의 ``_check_with_alias_tuple_return`` 과
        동일한 의미. 다만 카테고리를 분리 (``tuple-return-on-patch-decorator-
        alias``) 하여 출력 가독성을 보존한다.
        """
        for stmt in function_node.body:
            for sub in ast.walk(stmt):
                if not isinstance(sub, ast.Assign):
                    continue
                for tgt in sub.targets:
                    if not isinstance(tgt, ast.Attribute):
                        continue
                    if tgt.attr != "return_value":
                        continue
                    base = tgt.value
                    if not isinstance(base, ast.Name) or base.id != alias:
                        continue
                    value = sub.value
                    if isinstance(value, (ast.Tuple, ast.List)):
                        self.violations.append(
                            Violation(
                                path=self.path,
                                lineno=sub.lineno,
                                kind="tuple-return-on-patch-decorator-alias",
                                target=target,
                                detail=(
                                    f"{alias}.return_value = tuple — "
                                    "@patch decorator 로 주입된 mock 인자에 tuple "
                                    "을 반환값으로 할당하면 async with 가 동작하지 "
                                    "않는다. mock_*_factory 사용 권장."
                                ),
                            )
                        )
                    elif isinstance(value, ast.Call) and (
                        self._is_magicmock(value.func) or self._is_asyncmock(value.func)
                    ):
                        self.violations.append(
                            Violation(
                                path=self.path,
                                lineno=sub.lineno,
                                kind="mock-return-on-patch-decorator-alias",
                                target=target,
                                detail=(
                                    f"{alias}.return_value = MagicMock/AsyncMock — "
                                    "@patch decorator 로 주입된 mock 인자에 "
                                    "non-ctxmgr mock 을 할당. async with 가 동작 "
                                    "안할 가능성. mock_*_factory 권장."
                                ),
                            )
                        )

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

        # Case A: new_callable=<callable> + return_value=tuple
        # codex review attempt 4 finding 1: ``new_callable`` 은 ``AsyncMock`` 만이
        # 아니라 ``MagicMock``, generic ``Mock``, 그 외 callable factory 모두 가능.
        # ``patch`` 는 ``new_callable()`` 결과에 ``return_value=tuple`` 을 설정
        # 하므로 callable 종류에 무관하게 동일 anti-pattern 이다.
        # ``AsyncMock`` 인 경우만 카테고리를 분리해 보고하고, 그 외는 통합
        # ``tuple-return-on-patch`` 로 보고한다 (출력 카테고리 일관성).
        if (
            new_callable_value is not None
            and return_value_kwarg is not None
            and self._is_tuple_or_list(return_value_kwarg)
        ):
            if self._is_asyncmock(new_callable_value):
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
            # 그 외 callable (MagicMock / Mock / custom factory) — 통합 카테고리
            self.violations.append(
                Violation(
                    path=self.path,
                    lineno=call.lineno,
                    kind="tuple-return-on-patch",
                    target=target,
                    detail=(
                        "new_callable=<callable> + return_value=tuple — "
                        "callable() 결과가 tuple 을 반환해 async with 가 동작 "
                        "하지 않는다. mock_*_factory(...) 사용 권장."
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
                return
            # codex review attempt 5 finding 1: production positional args 를
            # stub 이 받지 못하면 호출 시 TypeError.
            signature = self.allowlist[target]
            mismatch = self._stub_positional_arity_mismatch(stub, signature)
            if mismatch is not None:
                self.violations.append(
                    Violation(
                        path=self.path,
                        lineno=call.lineno,
                        kind="async-stub-positional-arity-mismatch",
                        target=target,
                        detail=(
                            f"new={new_value.id} — {mismatch}. "
                            "mock_*_factory 사용 권장."
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

    @staticmethod
    def _stub_positional_arity_mismatch(
        stub: ast.AsyncFunctionDef, signature: FactorySignature
    ) -> str | None:
        """stub 이 production 의 positional args 를 받지 못하면 mismatch 사유
        문자열을, 호환되면 ``None`` 을 반환한다 (codex review attempt 5
        finding 1 + attempt 6 finding 1 — false-positive fix).

        호환 조건 (advisory, arity 만 검증; **이름은 비교하지 않는다**):

        * stub 이 ``*args`` 를 가지면 production positional 을 모두 swallow → OK.
        * stub 의 positional arity (posonly + args 개수) 가 production positional
          arity 이상이면 OK. (production 은 stub 을 positional 로 그대로 forward
          하므로 stub 인자 이름이 prod 이름과 달라도 호출 가능. 예: prod 가
          ``account_id`` 이고 stub 이 ``acc`` 이어도 ``stub("acc-val", ctx=ctx)``
          호출은 OK).
        * production 이 단일 ``ctx`` positional 만 가질 때 stub 이 ctx kwarg-only
          만 받으면 OK (``await factory(ctx=ctx)`` 가능 — 별도 분기).
        * production 의 kwonly args (예: ``ctx`` kwarg-only) 는 ``_stub_accepts_
          ctx_kwarg`` 가 별도 검사한다 (본 함수는 positional arity 만 검증).

        codex review attempt 6 finding 1 — false positive fix: 기존 구현은 stub
        positional arg **이름** 이 production 이름과 완전히 일치해야 통과시켰는데,
        이는 실제 호출 규칙(positional forward)과 어긋난 false positive 였다.
        본 fix 이후 이름 비교는 제거되고 arity 만 검사한다.

        반환: ``None`` (호환) 또는 mismatch reason string.
        """
        # stub 이 *args 면 모든 positional swallow — OK.
        if stub.args.vararg is not None:
            return None

        stub_positional = [a.arg for a in stub.args.posonlyargs] + [
            a.arg for a in stub.args.args
        ]
        prod_positional = list(signature.positional_args)

        # production 이 positional 0 면 검사 불요.
        if not prod_positional:
            return None

        # production 이 단일 ``ctx`` positional 일 때 stub 의 ctx kwarg-only 만으로
        # 도 호환 (``await factory(ctx=ctx)`` 가능). 별도 fast-path.
        if (
            len(prod_positional) == 1
            and prod_positional[0] == "ctx"
            and PatchVisitor._stub_accepts_ctx_kwarg(stub)
        ):
            return None

        # arity 만 검증: stub positional 수가 부족하면 호출 시 TypeError.
        # 이름은 비교하지 않는다 (positional forward 의미상 이름 무관).
        if len(stub_positional) < len(prod_positional):
            return (
                f"production positional args {prod_positional} 중 "
                f"{len(prod_positional) - len(stub_positional)} 개가 stub "
                f"positional arity({len(stub_positional)}) 로 부족하다 "
                "(stub 이 *args 를 받거나 positional 수를 늘려야 호출 가능)"
            )
        return None

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
            return
        if not self._stub_is_ctxmgr(stub):
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
            return
        # codex review attempt 5 finding 1: production positional args 호환성도
        # ``side_effect=`` stub 에 동일하게 적용.
        signature = self.allowlist[target]
        mismatch = self._stub_positional_arity_mismatch(stub, signature)
        if mismatch is not None:
            self.violations.append(
                Violation(
                    path=self.path,
                    lineno=call.lineno,
                    kind="async-stub-side-effect-positional-arity-mismatch",
                    target=target,
                    detail=(
                        f"side_effect={side_effect_value.id} — {mismatch}. "
                        "mock_*_factory 사용 권장."
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


def scan_file(path: Path, allowlist: dict[str, FactorySignature]) -> list[Violation]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return []
    visitor = PatchVisitor(path, allowlist)
    # 2-pass scan (codex review attempt 4 finding 3): pre-collect async def
    # stubs across the entire tree before traversing patch sites, so that
    # ``new=<stub_name>`` / ``side_effect=<stub_name>`` references can resolve
    # regardless of file order.
    visitor.prepare_async_def_stubs(tree)
    visitor.visit(tree)
    return visitor.violations


def scan_paths(
    paths: Iterable[Path], allowlist: dict[str, FactorySignature]
) -> list[Violation]:
    violations: list[Violation] = []
    for root in paths:
        if root.is_file() and root.suffix == ".py":
            violations.extend(scan_file(root, allowlist))
            continue
        for py_path in sorted(root.rglob("*.py")):
            violations.extend(scan_file(py_path, allowlist))
    return violations


def main(argv: list[str] | None = None) -> int:
    """Scanner CLI entrypoint.

    Default mode: **advisory** — violation 발견 여부와 무관하게 exit code 0
    반환 (informational reporting only). #1900 attempt 7 final 결정.

    ``--strict`` 지정 시: violation 있으면 exit 1, 없으면 exit 0 (사용자
    opt-in CI gate).
    """
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
    parser.add_argument(
        "--strict",
        action="store_true",
        help=(
            "advisory mode 가 아닌 strict mode 로 동작. violation 발견 시 "
            "exit code 1 반환 (기본은 advisory: 항상 exit 0)."
        ),
    )
    args = parser.parse_args(argv)

    allowlist = discover_async_ctxmgr_factories()
    if args.list_allowlist:
        for t in sorted(allowlist):
            sig = allowlist[t]
            sig_repr = (
                f"positional={list(sig.positional_args)} kwonly={list(sig.kwonly_args)}"
            )
            print(f"{t}  # {sig_repr}")
        print(f"# total: {len(allowlist)} (legacy denied: {sorted(LEGACY_DENY)})")
        return 0

    if not args.paths:
        parser.error("paths required (or use --list-allowlist)")

    violations = scan_paths(args.paths, allowlist)
    if not violations:
        mode_label = "strict" if args.strict else "advisory"
        print(
            f"OK — anti-pattern 0건 (allowlist {len(allowlist)} factory, "
            f"denied: {sorted(LEGACY_DENY)}, mode={mode_label})"
        )
        return 0

    for v in violations:
        print(v.format())
    if args.strict:
        print(f"\nFAIL — anti-pattern {len(violations)} 건 (strict mode)")
        return 1
    # advisory (default): violation 보고는 하되 exit 0.
    print(
        f"\nADVISORY — anti-pattern {len(violations)} 건 보고 (advisory mode, "
        "exit 0). --strict 플래그로 CI gate 활성화 가능."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
