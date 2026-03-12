"""StrategyValidator — AST 기반 전략 파일 정적 검증."""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path


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

        # 4. 금지 모듈 import
        forbidden = self._find_forbidden_imports(tree)
        for module in forbidden:
            errors.append(f"Forbidden import: {module}")

        # 5. 위험 패턴 경고
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

    def _find_dangerous_patterns(self, tree: ast.Module) -> list[str]:
        """위험 패턴 탐지 (경고 수준)."""
        warnings: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id in (
                    "eval",
                    "exec",
                    "compile",
                    "__import__",
                ):
                    warnings.append(
                        f"Dangerous built-in call: "
                        f"{node.func.id}() at line {node.lineno}"
                    )
                elif node.func.id == "open":
                    warnings.append(f"File access via open() at line {node.lineno}")
        return warnings
