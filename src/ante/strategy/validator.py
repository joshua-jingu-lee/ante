"""StrategyValidator — AST 기반 전략 파일 정적 검증."""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

from ante.core.exchange import STRATEGY_EXCHANGES

# 코드 레벨 SSOT(`ante.core.exchange.STRATEGY_EXCHANGES` = canonical 5종 ∪
# {`*`})에 위임한다. 이름·타입(`set[str]`)·값·검증 결과·에러 메시지는
# 위임 전과 완전히 동일하게 보존한다(#1576 narrow-scope: zero-change).
VALID_EXCHANGES: set[str] = set(STRATEGY_EXCHANGES)


# #1675 — StrategyValidator source-read + AST-parse 단계 4클래스 정규화.
# 두 상수는 인코딩명/`codec`/`null`/raw byte/source line/path 콘텐츠를 포함
# 하지 않는 **고정 상수**다. 어떤 경우에도 `str(exception)`/예외 repr/codec명
# /byte/문자/토큰/소스 라인 텍스트를 `errors[]`에 포함하지 않는다.
_NOT_TEXT_SOURCE = "전략 파일을 텍스트 전략 소스로 읽을 수 없습니다."
_FILE_NOT_READABLE = "전략 파일에 접근할 수 없습니다."


def _syntax_msg(e: SyntaxError) -> str:
    """`SyntaxError` 를 정수 line/offset 만 노출하는 content-free 메시지로 정규화.

    `str(e)`/`{e}` 는 사용자가 제출한 원문 토큰·소스 라인을 그대로 반사할 수
    있으므로 절대 호출하지 않는다. `e.lineno`/`e.offset` 이 `None` 인 경우는
    `0` 으로 fallback 하여 형식 안정성을 유지한다.
    """
    return f"Syntax error (line {e.lineno or 0}, offset {e.offset or 0})"


@dataclass
class ValidationResult:
    """검증 결과."""

    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class StrategyValidator:
    """AST 기반 전략 파일 정적 검증."""

    # #2040 — base.py에서 `async def`이고 런타임이 await하는 hook 집합.
    # on_step=abstract async 필수, 나머지=async default(override 시 await됨).
    # on_start/on_stop은 sync 계약이라 의도적으로 제외.
    ASYNC_HOOKS: set[str] = {
        "on_step",
        "on_fill",
        "on_data",
        "on_order_update",
        "on_position_corrected",
    }

    FORBIDDEN_MODULES: set[str] = {
        "os",
        "sys",
        "subprocess",
        "shutil",
        "socket",
        "http",
        "urllib",
        "requests",
        "aiohttp",
        "httpx",
        "sqlite3",
        "sqlalchemy",
        "importlib",
        "ctypes",
        "pickle",
        "pathlib",
        "multiprocessing",
        "threading",
        "signal",
        "io",
        "tempfile",
        "glob",
        "builtins",
    }

    FORBIDDEN_BUILTINS: set[str] = {
        "eval",
        "exec",
        "compile",
        "__import__",
        "globals",
        "locals",
        "open",
    }

    def validate(self, filepath: Path) -> ValidationResult:
        """전략 파일 정적 검증."""
        errors: list[str] = []
        warnings: list[str] = []

        # 1. 파싱 — source-read + AST-parse 단계 4클래스 정규화 (#1675).
        # 예외 순서: `SyntaxError → OSError → (UnicodeDecodeError, ValueError)`.
        # 이 순서로 `IsADirectoryError`/`PermissionError`/`FileNotFoundError`가
        # `OSError`에서 잡히고, `UnicodeDecodeError`(ValueError 서브)는 마지막
        # 묶음에서 잡힌다. 어떤 경우에도 `str(e)`/예외 repr/codec명/byte/문자/
        # 토큰/소스 라인 텍스트를 `errors[]`에 포함하지 않는다.
        try:
            source = filepath.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(filepath))
        except SyntaxError as e:
            return ValidationResult(valid=False, errors=[_syntax_msg(e)])
        except OSError:
            return ValidationResult(valid=False, errors=[_FILE_NOT_READABLE])
        except (UnicodeDecodeError, ValueError):
            return ValidationResult(valid=False, errors=[_NOT_TEXT_SOURCE])

        # 2. Strategy 상속 클래스 존재
        strategy_classes = self._find_strategy_classes(tree)
        if len(strategy_classes) == 0:
            errors.append("No class inheriting from Strategy found")
        elif len(strategy_classes) > 1:
            errors.append(
                f"Multiple Strategy subclasses found: "
                f"{[c.name for c in strategy_classes]}"
            )

        # 3. 필수 요소 검사
        if len(strategy_classes) == 1:
            cls = strategy_classes[0]
            # #2041: meta 부재 → error. 존재하지만 StrategyMeta(...) 호출이
            # 아니면(dict/None/다른 호출 등) 타입 불일치 error.
            if not self._has_class_var(cls, "meta"):
                errors.append("Missing 'meta' class variable (StrategyMeta)")
            elif not self._meta_is_strategy_meta_call(cls):
                errors.append("'meta' must be a StrategyMeta(...) instance")
            if not self._has_method(cls, "on_step"):
                errors.append("Missing required method: on_step()")

            # #2040: 런타임이 await하는 hook이 sync `def`면 await 시 TypeError.
            # 정의된(클래스 body) async hook이 sync면 error.
            errors.extend(self._async_hook_violations(cls))

            # accepts_external_signals=True인 전략에 on_data() 구현 여부 경고
            if self._has_accepts_external_signals(cls) and not self._has_method(
                cls, "on_data"
            ):
                warnings.append(
                    "Strategy has accepts_external_signals=True but does not "
                    "implement on_data() — external signals will use default handler"
                )

        # 4. exchange 유효성 검증
        if len(strategy_classes) == 1:
            module_consts = self._module_string_constants(tree)
            exchange_value = self._extract_meta_exchange(
                strategy_classes[0], module_consts
            )
            if exchange_value is not None and exchange_value not in VALID_EXCHANGES:
                errors.append(
                    f"Invalid exchange value: '{exchange_value}'. "
                    f"Valid values: {sorted(VALID_EXCHANGES)}"
                )

        # 5. 금지 모듈 import
        forbidden = self._find_forbidden_imports(tree)
        for module in forbidden:
            errors.append(f"Forbidden import: {module}")

        # 5. 금지된 내장 함수 호출 (에러)
        errors.extend(self._find_forbidden_builtins(tree))

        # 6. 금지된 최상위 코드 (에러)
        errors.extend(self._find_forbidden_toplevel(tree))

        # 7. 위험 패턴 경고
        warnings.extend(self._find_dangerous_patterns(tree))

        return ValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )

    # ante.strategy / ante.strategy.base 에서 Strategy 를 export 하는 모듈 경로.
    _STRATEGY_MODULES: set[str] = {"ante.strategy", "ante.strategy.base"}

    def _find_strategy_classes(self, tree: ast.Module) -> list[ast.ClassDef]:
        """실제 ante ``Strategy`` 를 상속하는 module-level 클래스 노드 탐색 (#2042).

        **`tree.body`(module-scope)를 정의 순서대로 위에서 아래로 한 번** 순회하며
        이름별 "현재 바인딩"을 추적한다(`name_binding: dict[str, str]`,
        값 ∈ {``"ante_strategy"``, ``"local_class"``, ``"other"``})와 모듈 별칭
        (`module_aliases: set[str]`). 각 ``ClassDef`` 를 만나면 **먼저** 그 시점의
        바인딩으로 base 를 해석해 ante ``Strategy`` 상속 여부를 판정하고, **그
        다음** 그 클래스 이름을 ``local_class`` 로 갱신한다(이후 등장 클래스에만
        shadow 적용).

        Python 은 이름을 **실행 시점(정의 순서)** 에 바인딩하므로, 클래스 정의
        시점의 바인딩으로 base 를 해석해야 런타임/loader 의미와 정합한다. 예:
        ``import Strategy as S; class X(S); class S`` 는 X 정의 시점에 S 가 import
        된 ante ``Strategy`` 이므로 X 를 인정하고(loader 도 X 카운트), 그 뒤에 온
        ``class S`` 만 로컬로 재바인딩한다. 반대로 ``import Strategy; class
        Strategy; class X(Strategy)`` 는 X 정의 시점에 Strategy 가 이미 로컬
        클래스로 재바인딩된 뒤이므로 미인정한다(loader 도 비카운트).

        탐지·바인딩 추적·shadow 판정 모두 **module-scope(`tree.body`)** 로
        한정한다. loader 는 import·실행 후 module 네임스페이스(`vars(module)`)
        에서 Strategy subclass 를 찾으므로, 함수/클래스 내부에 중첩된 import·
        class 정의는 module attribute 가 아니라 loader 가 보지 못한다. 함수-로컬
        `from ante.strategy import Strategy` 같은 바인딩을 module-scope 클래스에
        적용하면(false positive) loader 와 불일치하므로, module-scope 로 한정해
        정합시킨다.

        재바인딩 무효화(`name_binding` ↔ `module_aliases` 대칭, #2042 4차):
        ``name_binding`` 뿐 아니라 ``module_aliases`` 도 정의 순서대로 재바인딩
        되면 무효화한다. 즉 ``import ante.strategy as astg; astg = other; class
        X(astg.Strategy)`` 는 X 정의 시점에 ``astg`` 가 이미 다른 값으로
        재바인딩됐으므로 미인정한다(loader 도 비카운트). 반대로 ``import
        ante.strategy as astg; class X(astg.Strategy); astg = other`` 는 X 가
        재바인딩 **이전**이라 인정한다. ``import ante.strategy``(dotted alias)는
        root 이름(``ante``)이 재바인딩되면 무효화한다. 재바인딩 노드는
        ``Assign``/value 있는 ``AnnAssign``/``ClassDef``/``Import``/``ImportFrom``
        /``del`` 이다.

        정적 name-resolution 모델 (bounded, #2042 known-limitation):
        다음을 정확히 모델링한다 — 직접/asname import (``from ante.strategy
        import Strategy [as S]``), ``import ante.strategy [as x]`` module-alias,
        module-level 정의 순서 기반 local-class shadow, 그리고 Name·module-alias
        의 재바인딩(``Assign``/``AnnAssign``/``ClassDef``/``del``/재import) 무효화.
        그 밖의 병리적 케이스 — 조건부 import, ``from ante.strategy import *``
        star-import, 간접 alias 체인(``x = ante.strategy; x.Strategy``), 동적
        import 등 — 는 정적으로 모델링하지 않는다(known-limitation). validate 는
        정적 best-effort pre-check 이며, 실제 Strategy 상속의 **authoritative
        gate 는 loader 의 런타임 ``issubclass(obj, Strategy)``** 다. 이 비대칭은
        의도적으로 수용한다(추가 round chase 차단). star-import 는 보수적으로
        Strategy 를 명시 바인딩하지 않아 미인정(loader 보다 약하나 흔치 않은
        known-limitation 범위).
        """
        name_binding: dict[str, str] = {}
        module_aliases: set[str] = set()
        result: list[ast.ClassDef] = []

        def _discard_module_aliases(name: str) -> None:
            """이름 재바인딩 시 그 이름이 가리키던 module-alias 를 제거.

            직접 별칭(``astg``)이거나, dotted alias(``ante.strategy``)의 root
            이름(``ante``)이 재바인딩되면 해당 alias 들을 module_aliases 에서
            제거한다.
            """
            module_aliases.discard(name)
            for stale in {a for a in module_aliases if a.split(".", 1)[0] == name}:
                module_aliases.discard(stale)

        def _invalidate(name: str) -> None:
            """이름 재바인딩 시 ante 바인딩/module-alias 둘 다 무효화 (대칭)."""
            # Name 바인딩: 이전이 무엇이든 ante 도 local 도 아닌 "other" 로.
            name_binding[name] = "other"
            _discard_module_aliases(name)

        for node in tree.body:  # module-level 정의 순서 단일 패스 (loader 정합)
            if isinstance(node, ast.ImportFrom):
                # 1) 재import 도 재바인딩 → 기존 ante 바인딩/alias 먼저 무효화.
                for alias in node.names:
                    _invalidate(alias.asname or alias.name)
                # 2) ante.strategy/.base 에서 module-scope import 된 ``Strategy``
                #    (asname 포함)의 바인딩명을 ante_strategy 로 (재)기록.
                if node.module in self._STRATEGY_MODULES and node.level == 0:
                    for alias in node.names:
                        if alias.name == "Strategy":
                            name_binding[alias.asname or alias.name] = "ante_strategy"
            elif isinstance(node, ast.Import):
                # ante.strategy(및 .base) 모듈 별칭을 Attribute 경로 해석용으로 기록.
                # ``import ante.strategy`` → "ante.strategy",
                # ``import ante.strategy as astg`` → "astg".
                for alias in node.names:
                    # 재import 도 재바인딩 → 바인딩명을 먼저 무효화한 뒤
                    # 해당 import 가 ante module 이면 alias 로 (재)등록.
                    bound = alias.asname or alias.name
                    _invalidate(bound)
                    if alias.name in self._STRATEGY_MODULES:
                        module_aliases.add(bound)
            elif isinstance(node, ast.ClassDef):
                # 1) 현재 바인딩으로 base 해석 → Strategy subclass 여부 판정.
                for base in node.bases:
                    if self._base_is_strategy(base, name_binding, module_aliases):
                        result.append(node)
                        break
                # 2) 그다음 이 클래스 이름을 로컬 클래스로 재바인딩(이후 shadow).
                #    클래스 정의는 그 이름의 module-alias 도 무효화한다(대칭).
                _discard_module_aliases(node.name)
                name_binding[node.name] = "local_class"
            elif isinstance(node, ast.Assign):
                # 이름 재바인딩은 보수적으로 "other"(ante 도 local 도 아님) +
                # module-alias 무효화(대칭).
                for target in node.targets:
                    for name in self._assign_target_names(target):
                        _invalidate(name)
            elif isinstance(node, ast.AnnAssign):
                # value 가 있는 AnnAssign 만 실제 바인딩 → 무효화.
                if node.value is not None and isinstance(node.target, ast.Name):
                    _invalidate(node.target.id)
            elif isinstance(node, ast.Delete):
                # `del astg` / `del Strategy` 도 바인딩 제거 → 무효화.
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        _invalidate(target.id)
        return result

    @staticmethod
    def _assign_target_names(target: ast.expr) -> list[str]:
        """Assign 타깃에서 module-level 로 재바인딩되는 Name id 들을 수집.

        ``x = ...`` → ``["x"]``, ``x = y = ...`` 는 각 target 이 별도로
        들어오므로 호출당 하나. ``x, y = ...`` (Tuple/List unpack)도 포함한다.
        Attribute/Subscript 타깃(``obj.x = ...``)은 module-level Name 재바인딩이
        아니므로 무시한다.
        """
        if isinstance(target, ast.Name):
            return [target.id]
        if isinstance(target, ast.Tuple | ast.List):
            names: list[str] = []
            for elt in target.elts:
                if isinstance(elt, ast.Name):
                    names.append(elt.id)
                elif isinstance(elt, ast.Starred) and isinstance(elt.value, ast.Name):
                    names.append(elt.value.id)
            return names
        return []

    def _base_is_strategy(
        self,
        base: ast.expr,
        name_binding: dict[str, str],
        module_aliases: set[str],
    ) -> bool:
        """base 표현식이 (정의 시점 바인딩 기준) 실제 ante Strategy 인지 판정 (#2042).

        ``name_binding`` 은 클래스 정의 시점까지의 module-level 바인딩 상태다.
        """
        # `class X(Strategy)` / `class X(S)` — 정의 시점에 그 이름이 ante
        # Strategy 로 바인딩돼 있을 때만 인정. local_class/other/미바인딩이면 미인정.
        if isinstance(base, ast.Name):
            return name_binding.get(base.id) == "ante_strategy"
        # `class X(astg.Strategy)` / `class X(ante.strategy.Strategy)` —
        # value 가 module_aliases 로 해석되는 경우만.
        if isinstance(base, ast.Attribute) and base.attr == "Strategy":
            return self._attr_value_to_str(base.value) in module_aliases
        return False

    @staticmethod
    def _attr_value_to_str(node: ast.expr) -> str | None:
        """`ante.strategy` / `astg` 등 dotted name 표현식을 문자열로 평탄화.

        Attribute/Name 만 dotted name 으로 해석하고, 그 외(Call 등)는 None.
        """
        parts: list[str] = []
        cur: ast.expr = node
        while isinstance(cur, ast.Attribute):
            parts.append(cur.attr)
            cur = cur.value
        if not isinstance(cur, ast.Name):
            return None
        parts.append(cur.id)
        return ".".join(reversed(parts))

    def _has_class_var(self, cls: ast.ClassDef, name: str) -> bool:
        """클래스 변수 할당 존재 여부."""
        for node in cls.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == name:
                        return True
            elif isinstance(node, ast.AnnAssign):
                if isinstance(node.target, ast.Name) and node.target.id == name:
                    return True
        return False

    def _has_method(self, cls: ast.ClassDef, name: str) -> bool:
        """메서드 정의 존재 여부."""
        for node in cls.body:
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                if node.name == name:
                    return True
        return False

    def _method_is_async(self, cls: ast.ClassDef, name: str) -> bool | None:
        """클래스 body 에 정의된 메서드의 async 여부 (#2040).

        Returns:
            정의돼 있고 ``async def`` → True,
            정의돼 있고 sync ``def`` → False,
            클래스에 정의되지 않음 → None.
        마지막 정의를 기준으로 한다(중복 정의 시 런타임 바인딩과 동일).
        """
        result: bool | None = None
        for node in cls.body:
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                if node.name == name:
                    result = isinstance(node, ast.AsyncFunctionDef)
        return result

    def _async_hook_violations(self, cls: ast.ClassDef) -> list[str]:
        """런타임 await hook 이 sync ``def`` 로 정의된 위반 목록 (#2040).

        ``ASYNC_HOOKS`` 중 클래스에 정의된 hook 이 sync 면 await 시 TypeError
        가 나므로 error. 정의되지 않은 hook(base default 상속)은 검사하지
        않는다(on_step 부재는 별도 "Missing required method" 검사가 담당).
        """
        errors: list[str] = []
        for hook in sorted(self.ASYNC_HOOKS):
            is_async = self._method_is_async(cls, hook)
            if is_async is False:
                errors.append(f"{hook}() must be async (use 'async def')")
        return errors

    def _meta_is_strategy_meta_call(self, cls: ast.ClassDef) -> bool:
        """``meta`` 의 마지막 값-할당이 ``StrategyMeta(...)`` 호출인지 검사 (#2041).

        클래스 body 를 순서대로 순회하여 ``meta`` 를 타깃으로 하는 **마지막**
        값-할당 노드를 선택한다(런타임은 마지막 할당값을 클래스 속성으로
        쓰므로 그와 일치). 그 value 가 ``ast.Call`` 이고 func 가
        ``Name(id="StrategyMeta")`` 또는 ``Attribute(attr="StrategyMeta")`` 여야
        True. dict/None/다른 호출 등은 False.

        값-할당 판정:
        - ``ast.Assign``: targets 에 ``Name(id="meta")`` 가 포함되면 value 가
          ``meta`` 의 런타임 속성값이 된다.
        - ``ast.AnnAssign``: target 이 ``Name(id="meta")`` 이고 **value 가 not
          None** 일 때만 값-할당. annotation-only(``meta: StrategyMeta``)는
          런타임에 클래스 속성을 만들지 않으므로 값-할당으로 치지 않는다.

        ``meta`` 값-할당이 하나도 없으면(annotation-only 만 있거나 부재) False.
        부재 자체는 별도 ``_has_class_var`` 검사가 담당하고, annotation-only 는
        StrategyMeta 인스턴스 값이 없으므로 must-be-StrategyMeta error 로 귀결돼
        두 검사가 모순되지 않는다(부재 → Missing, 존재하나 마지막 값이
        StrategyMeta 호출 아님 → must-be-StrategyMeta).
        """
        last_value: ast.expr | None = None
        for node in cls.body:
            if isinstance(node, ast.Assign):
                if any(
                    isinstance(t, ast.Name) and t.id == "meta" for t in node.targets
                ):
                    last_value = node.value
            elif isinstance(node, ast.AnnAssign):
                target = node.target
                if (
                    isinstance(target, ast.Name)
                    and target.id == "meta"
                    and node.value is not None
                ):
                    last_value = node.value
        if last_value is None:
            return False
        if not isinstance(last_value, ast.Call):
            return False
        func = last_value.func
        if isinstance(func, ast.Name) and func.id == "StrategyMeta":
            return True
        if isinstance(func, ast.Attribute) and func.attr == "StrategyMeta":
            return True
        return False

    @staticmethod
    def _module_string_constants(tree: ast.Module) -> dict[str, str]:
        """모듈 레벨 `NAME = "literal"` 문자열 상수 map (정적 해석용)."""
        consts: dict[str, str] = {}
        for node in tree.body:  # 모듈 레벨만
            if (
                isinstance(node, ast.Assign)
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
            ):
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        consts[t.id] = node.value.value
            elif (
                isinstance(node, ast.AnnAssign)
                and node.value is not None
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
                and isinstance(node.target, ast.Name)
            ):
                consts[node.target.id] = node.value.value
        return consts

    def _extract_meta_exchange(
        self, cls: ast.ClassDef, module_consts: dict[str, str]
    ) -> str | None:
        """meta에서 exchange 값을 추출. 없으면 None 반환.

        exchange kwarg 가 literal(`ast.Constant`)이면 그대로,
        모듈 레벨 문자열 상수 이름(`ast.Name`)이면 ``module_consts`` 로
        정적 해석한다. 해석 불가(계산식/비문자열 Name)는 None(기존 동작).
        """
        for node in cls.body:
            if isinstance(node, ast.Assign | ast.AnnAssign):
                target = (
                    node.targets[0] if isinstance(node, ast.Assign) else node.target
                )
                if not isinstance(target, ast.Name) or target.id != "meta":
                    continue
                value = node.value
                if isinstance(value, ast.Call):
                    for kw in value.keywords:
                        if kw.arg != "exchange":
                            continue
                        if isinstance(kw.value, ast.Constant):
                            return str(kw.value.value)
                        if (
                            isinstance(kw.value, ast.Name)
                            and kw.value.id in module_consts
                        ):
                            return module_consts[kw.value.id]
        return None

    def _has_accepts_external_signals(self, cls: ast.ClassDef) -> bool:
        """meta에 accepts_external_signals=True 설정 여부 탐지."""
        for node in cls.body:
            # meta = StrategyMeta(..., accepts_external_signals=True)
            if isinstance(node, ast.Assign | ast.AnnAssign):
                target = (
                    node.targets[0] if isinstance(node, ast.Assign) else node.target
                )
                if not isinstance(target, ast.Name) or target.id != "meta":
                    continue
                value = node.value
                if isinstance(value, ast.Call):
                    for kw in value.keywords:
                        if kw.arg == "accepts_external_signals" and isinstance(
                            kw.value, ast.Constant
                        ):
                            return bool(kw.value.value)
        return False

    def _find_forbidden_imports(self, tree: ast.Module) -> list[str]:
        """금지 모듈 import 탐색."""
        found: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top_module = alias.name.split(".")[0]
                    if top_module in self.FORBIDDEN_MODULES:
                        found.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    top_module = node.module.split(".")[0]
                    if top_module in self.FORBIDDEN_MODULES:
                        found.append(node.module)
        return found

    def _find_forbidden_builtins(self, tree: ast.Module) -> list[str]:
        """금지된 내장 함수 호출 탐지 (에러)."""
        errors: list[str] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = self._forbidden_builtin_name(node.func)
            if name is not None:
                errors.append(
                    f"Forbidden built-in call: {name}() at line {node.lineno}"
                )
        return errors

    def _forbidden_builtin_name(self, func: ast.expr) -> str | None:
        # 1) open(...) 직접 호출
        if isinstance(func, ast.Name) and func.id in self.FORBIDDEN_BUILTINS:
            return func.id
        # 2) __builtins__["open"](...)
        if isinstance(func, ast.Subscript) and self._is_builtins_ref(func.value):
            key = func.slice
            if (
                isinstance(key, ast.Constant)
                and isinstance(key.value, str)
                and key.value in self.FORBIDDEN_BUILTINS
            ):
                return key.value
        # 3) __builtins__.open(...)
        if isinstance(func, ast.Attribute) and self._is_builtins_ref(func.value):
            if func.attr in self.FORBIDDEN_BUILTINS:
                return func.attr
        return None

    @staticmethod
    def _is_builtins_ref(node: ast.expr) -> bool:
        return isinstance(node, ast.Name) and node.id == "__builtins__"

    def _find_forbidden_toplevel(self, tree: ast.Module) -> list[str]:
        """금지된 최상위 코드 탐지 (에러)."""
        errors: list[str] = []
        self._check_toplevel_body(tree.body, errors)
        return errors

    def _check_toplevel_body(self, body: list[ast.stmt], errors: list[str]) -> None:
        for node in body:
            if isinstance(node, ast.Import | ast.ImportFrom):
                continue
            if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
                # #2032/#2033: decorator는 정의 시점(import-time) 실행 → 전부 금지
                if node.decorator_list:
                    errors.append(
                        f"Forbidden top-level decorator at line {node.lineno}: "
                        f"{type(node).__name__}"
                    )
                # #2033: 함수 default argument 식의 import-time call 금지
                if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                    for default in [*node.args.defaults, *node.args.kw_defaults]:
                        if default is not None and self._contains_call(default):
                            lineno = getattr(default, "lineno", node.lineno)
                            errors.append(
                                f"Forbidden top-level code at line {lineno}: "
                                f"default argument call"
                            )
                continue
            if isinstance(node, ast.Pass):
                continue
            if isinstance(node, ast.If):
                # #2018: if/elif/else body는 import-time 실행 → 동일 규칙 재귀.
                # If.test 조건식은 범위 밖(eval/exec/금지 import는
                # _find_forbidden_builtins/_find_forbidden_imports의 walk가 전역 탐지).
                self._check_toplevel_body(node.body, errors)
                self._check_toplevel_body(node.orelse, errors)
                continue
            # 모듈 docstring (문자열 리터럴 Expr)
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
                continue
            # 리터럴 상수 할당
            if isinstance(node, ast.Assign | ast.AnnAssign):
                value = node.value
                if value is None:
                    continue  # 타입 어노테이션만 (x: int)
                if self._is_literal_assign_value(value):
                    continue  # 리터럴/Name/리터럴 컬렉션 허용
                # 비리터럴 실행식 (BinOp/Subscript/Comprehension/Call/...) →
                # 아래 errors.append로
            errors.append(
                f"Forbidden top-level code at line {node.lineno}: {type(node).__name__}"
            )

    def _contains_call(self, node: ast.AST) -> bool:
        """AST 서브트리에 함수 호출이 포함되어 있는지 확인."""
        if isinstance(node, ast.Call):
            return True
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                return True
        return False

    def _is_literal_assign_value(self, node: ast.expr) -> bool:
        """assignment 값이 부작용 없는 리터럴/참조인지 (import-time 실행식 거부)."""
        if isinstance(node, ast.Constant):
            return True
        if isinstance(node, ast.Name):
            return True  # 상수 참조(lookup) — 부작용 없음
        if isinstance(node, ast.UnaryOp):
            return self._is_literal_assign_value(node.operand)
        if isinstance(node, ast.List | ast.Tuple | ast.Set):
            return all(self._is_literal_assign_value(e) for e in node.elts)
        if isinstance(node, ast.Dict):
            return all(
                k is not None
                and self._is_literal_assign_value(k)
                and self._is_literal_assign_value(v)
                for k, v in zip(node.keys, node.values, strict=False)
            )
        return False

    def _find_dangerous_patterns(self, tree: ast.Module) -> list[str]:
        """위험 패턴 탐지 (경고 수준)."""
        warnings: list[str] = []
        # open()은 FORBIDDEN_BUILTINS로 승격되어 에러로 처리됨
        return warnings


def validate_exchange(
    strategy_exchange: str,
    account_exchange: str,
    *,
    strategy_name: str = "",
    account_name: str = "",
) -> None:
    """전략의 exchange와 계좌의 exchange 호환성을 런타임 검증.

    전략 exchange가 "*"이면 모든 계좌와 호환된다.
    그 외에는 전략 exchange와 계좌 exchange가 정확히 일치해야 한다.

    Raises:
        IncompatibleExchangeError: 호환되지 않는 경우.
        ValueError: 유효하지 않은 exchange 값인 경우.
    """
    from ante.strategy.exceptions import IncompatibleExchangeError

    if strategy_exchange not in VALID_EXCHANGES:
        raise ValueError(
            f"유효하지 않은 전략 exchange: '{strategy_exchange}'. "
            f"허용 값: {sorted(VALID_EXCHANGES)}"
        )

    if account_exchange not in VALID_EXCHANGES or account_exchange == "*":
        raise ValueError(
            f"유효하지 않은 계좌 exchange: '{account_exchange}'. "
            f"허용 값: {sorted(VALID_EXCHANGES - {'*'})}"
        )

    if strategy_exchange == "*":
        return

    if strategy_exchange != account_exchange:
        strategy_desc = f"'{strategy_name}'" if strategy_name else "전략"
        account_desc = f"'{account_name}'" if account_name else "계좌"
        raise IncompatibleExchangeError(
            f"{strategy_desc}의 exchange({strategy_exchange})와 "
            f"{account_desc}의 exchange({account_exchange})가 "
            f"호환되지 않습니다."
        )
