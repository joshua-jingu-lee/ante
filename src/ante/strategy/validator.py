"""StrategyValidator — AST 기반 전략 파일 정적 검증."""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

from ante.core.exchange import STRATEGY_EXCHANGES
from ante.core.market_data_vocab import is_krx_symbol

VALID_EXCHANGES: set[str] = set(STRATEGY_EXCHANGES)


_NOT_TEXT_SOURCE = "전략 파일을 텍스트 전략 소스로 읽을 수 없습니다."
_FILE_NOT_READABLE = "전략 파일에 접근할 수 없습니다."


def _syntax_msg(e: SyntaxError) -> str:
    """`SyntaxError` 를 정수 line/offset 만 노출하는 content-free 메시지로 정규화."""
    return f"Syntax error (line {e.lineno or 0}, offset {e.offset or 0})"


@dataclass
class ValidationResult:
    """검증 결과."""

    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class _StrategyClassMatch:
    """ante ``Strategy`` 상속으로 인정된 module-level 클래스 + 정의 시점 바인딩 스냅샷.

    ``_find_strategy_classes`` 가 후보 strategy 클래스를 찾을 때, 그 **클래스 정의
    시점**의 ``StrategyMeta`` 바인딩(``strategymeta_binding``)과 module-alias
    (``module_aliases``) 스냅샷을 함께 담는다. ``meta`` 가 ``StrategyMeta(...)``
    인지 검사(``_meta_is_strategy_meta_call``)는 이 스냅샷을 import 바인딩 컨텍스트로
    사용해 Strategy 와 동일한 order-aware import-resolution 으로 해석한다.
    """

    node: ast.ClassDef
    strategymeta_binding: dict[str, str]
    module_aliases: frozenset[str]

    @property
    def name(self) -> str:
        return self.node.name


class StrategyValidator:
    """AST 기반 전략 파일 정적 검증."""

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

        try:
            source = filepath.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(filepath))
        except SyntaxError as e:
            return ValidationResult(valid=False, errors=[_syntax_msg(e)])
        except OSError:
            return ValidationResult(valid=False, errors=[_FILE_NOT_READABLE])
        except (UnicodeDecodeError, ValueError):
            return ValidationResult(valid=False, errors=[_NOT_TEXT_SOURCE])

        strategy_classes = self._find_strategy_classes(tree)
        if len(strategy_classes) == 0:
            errors.append("No class inheriting from Strategy found")
        elif len(strategy_classes) > 1:
            errors.append(
                f"Multiple Strategy subclasses found: "
                f"{[c.name for c in strategy_classes]}"
            )

        if len(strategy_classes) == 1:
            match = strategy_classes[0]
            cls = match.node
            if not self._has_class_var(cls, "meta"):
                errors.append("Missing 'meta' class variable (StrategyMeta)")
            elif not self._meta_is_strategy_meta_call(
                cls, match.strategymeta_binding, match.module_aliases
            ):
                errors.append("'meta' must be a StrategyMeta(...) instance")
            if not self._has_method(cls, "on_step"):
                errors.append("Missing required method: on_step()")

            errors.extend(self._async_hook_violations(cls))

            if self._has_accepts_external_signals(cls) and not self._has_method(
                cls, "on_data"
            ):
                warnings.append(
                    "Strategy has accepts_external_signals=True but does not "
                    "implement on_data() — external signals will use default handler"
                )

        if len(strategy_classes) == 1:
            module_consts = self._module_string_constants(tree)
            exchange_value = self._extract_meta_exchange(
                strategy_classes[0].node, module_consts
            )
            if exchange_value is not None and exchange_value not in VALID_EXCHANGES:
                errors.append(
                    f"Invalid exchange value: '{exchange_value}'. "
                    f"Valid values: {sorted(VALID_EXCHANGES)}"
                )

            if exchange_value == "KRX":
                symbols = self._extract_meta_symbols(
                    strategy_classes[0].node, module_consts
                )
                if symbols is not None:
                    for symbol in symbols:
                        if not is_krx_symbol(symbol):
                            warnings.append(
                                f"Symbol '{symbol}' does not match KRX symbol "
                                f"format (exchange=KRX)"
                            )

        forbidden = self._find_forbidden_imports(tree)
        for module in forbidden:
            errors.append(f"Forbidden import: {module}")

        errors.extend(self._find_forbidden_builtins(tree))

        errors.extend(self._find_forbidden_toplevel(tree))

        warnings.extend(self._find_dangerous_patterns(tree))

        return ValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )

    _STRATEGY_MODULES: set[str] = {"ante.strategy", "ante.strategy.base"}

    def _find_strategy_classes(self, tree: ast.Module) -> list[_StrategyClassMatch]:
        """ante ``Strategy`` 를 상속하는 module-level 클래스 + 바인딩 스냅샷 탐색."""
        name_binding: dict[str, str] = {}
        strategymeta_binding: dict[str, str] = {}
        module_aliases: set[str] = set()
        result: list[_StrategyClassMatch] = []

        def _discard_module_aliases(name: str) -> None:
            """이름 재바인딩 시 그 이름이 가리키던 module-alias 를 제거."""
            module_aliases.discard(name)
            for stale in {a for a in module_aliases if a.split(".", 1)[0] == name}:
                module_aliases.discard(stale)

        def _invalidate(name: str) -> None:
            """이름 재바인딩 시 Strategy/StrategyMeta 바인딩·module-alias 무효화."""
            name_binding[name] = "other"
            strategymeta_binding.pop(name, None)
            _discard_module_aliases(name)

        for node in tree.body:
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    _invalidate(alias.asname or alias.name)
                if node.module in self._STRATEGY_MODULES and node.level == 0:
                    for alias in node.names:
                        bound = alias.asname or alias.name
                        if alias.name == "Strategy":
                            name_binding[bound] = "ante_strategy"
                        elif alias.name == "StrategyMeta":
                            strategymeta_binding[bound] = "ante_strategy_meta"
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    bound = alias.asname or alias.name
                    _invalidate(bound)
                    if alias.name in self._STRATEGY_MODULES:
                        module_aliases.add(bound)
            elif isinstance(node, ast.ClassDef):
                for base in node.bases:
                    if self._base_is_strategy(base, name_binding, module_aliases):
                        result.append(
                            _StrategyClassMatch(
                                node=node,
                                strategymeta_binding=dict(strategymeta_binding),
                                module_aliases=frozenset(module_aliases),
                            )
                        )
                        break
                _discard_module_aliases(node.name)
                strategymeta_binding.pop(node.name, None)
                name_binding[node.name] = "local_class"
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    for name in self._assign_target_names(target):
                        _invalidate(name)
            elif isinstance(node, ast.AnnAssign):
                if node.value is not None and isinstance(node.target, ast.Name):
                    _invalidate(node.target.id)
            elif isinstance(node, ast.Delete):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        _invalidate(target.id)
        return result

    @staticmethod
    def _assign_target_names(target: ast.expr) -> list[str]:
        """Assign 타깃에서 module-level 로 재바인딩되는 Name id 들을 수집."""
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
        """base 표현식이 (정의 시점 바인딩 기준) 실제 ante Strategy 인지 판정."""
        if isinstance(base, ast.Name):
            return name_binding.get(base.id) == "ante_strategy"
        if isinstance(base, ast.Attribute) and base.attr == "Strategy":
            return self._attr_value_to_str(base.value) in module_aliases
        return False

    @staticmethod
    def _attr_value_to_str(node: ast.expr) -> str | None:
        """`ante.strategy` / `astg` 등 dotted name 표현식을 문자열로 평탄화."""
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
        """클래스 body 에 정의된 메서드의 async 여부."""
        result: bool | None = None
        for node in cls.body:
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                if node.name == name:
                    result = isinstance(node, ast.AsyncFunctionDef)
        return result

    def _async_hook_violations(self, cls: ast.ClassDef) -> list[str]:
        """런타임 await hook 이 sync ``def`` 로 정의된 위반 목록."""
        errors: list[str] = []
        for hook in sorted(self.ASYNC_HOOKS):
            is_async = self._method_is_async(cls, hook)
            if is_async is False:
                errors.append(f"{hook}() must be async (use 'async def')")
        return errors

    def _meta_is_strategy_meta_call(
        self,
        cls: ast.ClassDef,
        strategymeta_binding: dict[str, str],
        module_aliases: frozenset[str],
    ) -> bool:
        """``meta`` 의 마지막 값-할당이 **ante** ``StrategyMeta(...)`` 호출인지 검사."""
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
        if isinstance(func, ast.Name):
            return strategymeta_binding.get(func.id) == "ante_strategy_meta"
        if isinstance(func, ast.Attribute) and func.attr == "StrategyMeta":
            return self._attr_value_to_str(func.value) in module_aliases
        return False

    @staticmethod
    def _module_string_constants(tree: ast.Module) -> dict[str, str]:
        """모듈 레벨 `NAME = "literal"` 문자열 상수 map (정적 해석용)."""
        consts: dict[str, str] = {}
        for node in tree.body:
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
        """meta에서 exchange 값을 추출. 없으면 None 반환."""
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

    def _extract_meta_symbols(
        self, cls: ast.ClassDef, module_consts: dict[str, str]
    ) -> list[str] | None:
        """meta에서 symbols 값을 정적 해석해 추출 (_extract_meta_exchange 동형)."""
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
                        if kw.arg != "symbols":
                            continue
                        if not isinstance(kw.value, ast.List):
                            return None
                        symbols: list[str] = []
                        for elt in kw.value.elts:
                            if isinstance(elt, ast.Constant) and isinstance(
                                elt.value, str
                            ):
                                symbols.append(elt.value)
                            else:
                                return None
                        return symbols
        return None

    def _has_accepts_external_signals(self, cls: ast.ClassDef) -> bool:
        """meta에 accepts_external_signals=True 설정 여부 탐지."""
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
        if isinstance(func, ast.Name) and func.id in self.FORBIDDEN_BUILTINS:
            return func.id
        if isinstance(func, ast.Subscript) and self._is_builtins_ref(func.value):
            key = func.slice
            if (
                isinstance(key, ast.Constant)
                and isinstance(key.value, str)
                and key.value in self.FORBIDDEN_BUILTINS
            ):
                return key.value
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
                if node.decorator_list:
                    errors.append(
                        f"Forbidden top-level decorator at line {node.lineno}: "
                        f"{type(node).__name__}"
                    )
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
                self._check_toplevel_body(node.body, errors)
                self._check_toplevel_body(node.orelse, errors)
                continue
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
                continue
            if isinstance(node, ast.Assign | ast.AnnAssign):
                value = node.value
                if value is None:
                    continue
                if self._is_literal_assign_value(value):
                    continue
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
            return True
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
