"""StrategyValidator — AST 기반 전략 파일 정적 검증."""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

VALID_EXCHANGES: set[str] = {"KRX", "NYSE", "NASDAQ", "AMEX", "TEST", "*"}


@dataclass
class ValidationResult:
    """검증 결과."""

    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class StrategyValidator:
    """AST 기반 전략 파일 정적 검증."""

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

        # 1. 파싱
        try:
            source = filepath.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(filepath))
        except SyntaxError as e:
            return ValidationResult(
                valid=False,
                errors=[f"Syntax error: {e}"],
            )

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
            if not self._has_class_var(cls, "meta"):
                errors.append("Missing 'meta' class variable (StrategyMeta)")
            if not self._has_method(cls, "on_step"):
                errors.append("Missing required method: on_step()")

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
            exchange_value = self._extract_meta_exchange(strategy_classes[0])
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

    def _find_strategy_classes(self, tree: ast.Module) -> list[ast.ClassDef]:
        """Strategy를 상속하는 클래스 노드 탐색."""
        result: list[ast.ClassDef] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                for base in node.bases:
                    if isinstance(base, ast.Name) and base.id == "Strategy":
                        result.append(node)
                    elif isinstance(base, ast.Attribute) and base.attr == "Strategy":
                        result.append(node)
        return result

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

    def _extract_meta_exchange(self, cls: ast.ClassDef) -> str | None:
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
                        if kw.arg == "exchange" and isinstance(kw.value, ast.Constant):
                            return str(kw.value.value)
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
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id in self.FORBIDDEN_BUILTINS:
                    errors.append(
                        f"Forbidden built-in call: "
                        f"{node.func.id}() at line {node.lineno}"
                    )
        return errors

    def _find_forbidden_toplevel(self, tree: ast.Module) -> list[str]:
        """금지된 최상위 코드 탐지 (에러)."""
        errors: list[str] = []
        for node in tree.body:
            if isinstance(node, ast.Import | ast.ImportFrom):
                continue
            if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            if isinstance(node, ast.Pass):
                continue
            if isinstance(node, ast.If):
                continue
            # 모듈 docstring (문자열 리터럴 Expr)
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
                continue
            # 리터럴 상수 할당
            if isinstance(node, ast.Assign | ast.AnnAssign):
                value = node.value
                if value is not None and not self._contains_call(value):
                    continue
                if value is None:
                    # 타입 어노테이션만 있는 경우 (x: int)
                    continue
            errors.append(
                f"Forbidden top-level code at line {node.lineno}: {type(node).__name__}"
            )
        return errors

    def _contains_call(self, node: ast.AST) -> bool:
        """AST 서브트리에 함수 호출이 포함되어 있는지 확인."""
        if isinstance(node, ast.Call):
            return True
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                return True
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
