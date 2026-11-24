"""src/ante가 import하는 서드파티 모듈의 런타임 의존성 선언을 잠근다 (#2977)."""

from __future__ import annotations

import ast
import re
import sys
import tomllib
from importlib.metadata import packages_distributions
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "ante"

# 아직 선언하지 않은 배포 -> 사유. 선언되면 이 항목은 실패로 드러난다.
UNDECLARED_ALLOWLIST: dict[str, str] = {
    "packaging": "런타임 설치 폐포에 새 패키지를 더하므로 따로 정한다 (#2978)",
}


def _normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _declared() -> set[str]:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    names: set[str] = set()
    for requirement in data["project"]["dependencies"]:
        match = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)", requirement)
        assert match, requirement
        names.add(_normalize(match.group(1)))
    return names


def _imported_modules() -> dict[str, str]:
    """최상위 모듈 이름 -> 처음 import한 위치. 함수 안의 import도 센다."""
    found: dict[str, str] = {}
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            else:
                continue
            for name in names:
                top = name.split(".")[0]
                if top in sys.stdlib_module_names or top == "ante":
                    continue
                where = f"{path.relative_to(ROOT)}:{node.lineno}"
                found.setdefault(top, where)
    return found


def _imported_distributions() -> dict[str, str]:
    """import한 배포(정규화한 이름) -> 처음 import한 위치."""
    mapping = packages_distributions()
    modules = _imported_modules()
    unmapped = sorted(m for m in modules if m not in mapping)
    assert not unmapped, f"배포에 대응되지 않는 모듈: {unmapped}"
    result: dict[str, str] = {}
    for module, where in sorted(modules.items()):
        for dist in mapping[module]:
            result.setdefault(_normalize(dist), where)
    return result


def test_collector_sees_from_imports_and_function_level_imports() -> None:
    modules = _imported_modules()
    assert {"pydantic", "pydantic_core", "packaging"} <= modules.keys(), modules


def test_every_imported_distribution_is_declared() -> None:
    declared = _declared()
    missing = {
        dist: where
        for dist, where in _imported_distributions().items()
        if dist not in declared and dist not in UNDECLARED_ALLOWLIST
    }
    assert not missing, f"선언되지 않은 런타임 import: {missing}"


def test_allowlist_entries_are_still_imported_and_undeclared() -> None:
    imported = _imported_distributions()
    declared = _declared()
    for dist in UNDECLARED_ALLOWLIST:
        assert dist in imported, f"{dist}는 import되지 않는다 — 허용 목록에서 지운다"
        assert dist not in declared, f"{dist}는 선언됐다 — 허용 목록에서 지운다"
