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
        self._check_toplevel_body(tree.body, errors)
        return errors

    def _check_toplevel_body(self, body: list[ast.stmt], errors: list[str]) -> None:
        for node in body:
            if isinstance(node, ast.Import | ast.ImportFrom):
                continue
            if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
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
                if value is not None and not self._contains_call(value):
                    continue
                if value is None:
                    # 타입 어노테이션만 있는 경우 (x: int)
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
