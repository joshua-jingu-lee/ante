"""CLI dependency-isolation smoke tests (#1464).

`ante.cli.commands.*` 모듈이 import 시점에 heavy 분석 의존성(`pandas`,
`pandas_ta`, `numba`, `numpy`, `polars`, `sklearn`, `talib`)을 eager-import
하지 않는지 검증한다.

#1461/#1463에서 적용한 lazy import 패턴이 회귀하지 않도록 차단하는 것이
목적이다. 같은 pytest 프로세스에서는 `sys.modules` 캐시 때문에 한번 다른
테스트가 heavy 모듈을 import해 두면 새 import에서도 이미 적재된 것처럼
보이므로, **fresh interpreter subprocess**를 띄워 격리된 환경에서 검증한다.

회귀 차단 시나리오:
    1. `ante.cli.commands.strategy`에 `import pandas`를 추가하면 본
       smoke test가 즉시 실패한다.
    2. `ante.strategy.__init__`에서 `from .registry import ...`만 했더라도
       registry가 `pandas_ta` 등을 top-level에서 import하면 실패한다.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

# 추가 패키지 import 회귀 케이스 (#1463 — `ante.strategy.__init__` lazy 분리).
# plain ``import ante.strategy``는 light해야 하며, ``IndicatorCalculator`` 같은
# heavy 심볼은 PEP 562 ``__getattr__``로 lazy 노출된다. 본 케이스는 CLI 명령
# 모듈과 별개로 패키지 자체의 import surface를 회귀 차단한다.
STRATEGY_PACKAGE_MODULES: tuple[str, ...] = ("ante.strategy",)

# CLI 명령 모듈 (src/ante/cli/commands/ 하위)
# `_password`처럼 언더스코어로 시작하는 private helper는 제외한다.
CLI_COMMAND_MODULES: tuple[str, ...] = (
    "account",
    "approval",
    "audit",
    "backtest",
    "bot",
    "broker",
    "config",
    "data",
    "init",
    "instrument",
    "member",
    "notification",
    "report",
    "rule",
    "signal",
    "strategy",
    "system",
    "trade",
    "treasury",
    "update",
)

# 분석/수치 heavy dependencies. 이 목록은 백테스트/전략 평가에서만
# 필요해야 하며, CLI dispatch path에 들어오면 안 된다.
HEAVY_MODULES: tuple[str, ...] = (
    "pandas",
    "pandas_ta",
    "numba",
    "numpy",
    "polars",
    "sklearn",
    "talib",
)


def _run_isolated_import(
    target: str,
    *,
    extra_imports: tuple[str, ...] = (),
) -> dict[str, list[str]]:
    """Fresh interpreter에서 `target`을 import하고 적재된 heavy 모듈을 반환.

    Args:
        target: import 대상 모듈 경로 (예: ``ante.cli.commands.strategy``).
        extra_imports: target import 전에 미리 import할 모듈 목록.
            heavy import 회귀를 의도적으로 만들 때(메타-테스트) 사용한다.

    Returns:
        ``{"loaded": [...]}`` 형태의 dict. ``loaded``는 ``HEAVY_MODULES``
        중 `sys.modules`에 등록된 모듈명 리스트.
    """
    pre = "\n".join(f"import {mod}" for mod in extra_imports)
    script = textwrap.dedent(
        f"""
        import json
        import sys

        {pre}

        import {target}

        heavy = {HEAVY_MODULES!r}
        loaded = [name for name in heavy if name in sys.modules]
        sys.stdout.write(json.dumps({{"loaded": loaded}}))
        """
    )

    # 현재 worktree의 `src/` 경로를 PYTHONPATH로 못박아, 다른 worktree에
    # 설치된 ante가 import되는 사고를 막는다. tests/conftest.py의
    # check_import_path와 같은 의도다.
    repo_root = Path(__file__).resolve().parents[2]
    src_path = repo_root / "src"
    env_path = str(src_path)

    result = subprocess.run(  # noqa: S603 — controlled args
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
        env={
            "PYTHONPATH": env_path,
            "PATH": "/usr/bin:/bin",
            "ANTE_DB_ENCRYPTION_KEY": "x" * 44,
        },
    )

    if result.returncode != 0:
        pytest.fail(
            f"isolated import of {target!r} failed:\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        pytest.fail(
            f"isolated import produced non-JSON stdout for {target!r}: "
            f"{result.stdout!r} (stderr={result.stderr!r})"
        )
        raise  # pragma: no cover — pytest.fail raises


@pytest.mark.parametrize("command", CLI_COMMAND_MODULES)
def test_cli_command_module_does_not_eager_import_heavy_deps(command: str) -> None:
    """각 CLI 명령 모듈은 import 시 heavy 분석 의존성을 적재하지 않는다.

    회귀 시나리오: ``ante.cli.commands.strategy``에 ``import pandas``를 추가하면
    `loaded`에 ``"pandas"``가 포함되어 본 테스트가 실패한다.
    """
    target = f"ante.cli.commands.{command}"
    payload = _run_isolated_import(target)
    loaded = payload["loaded"]
    assert loaded == [], (
        f"{target} import 시 heavy 분석 의존성이 적재되었습니다: {loaded}. "
        "CLI dispatch path는 lazy import를 유지해야 합니다 (see #1461/#1463)."
    )


@pytest.mark.parametrize("package", STRATEGY_PACKAGE_MODULES)
def test_strategy_package_does_not_eager_import_heavy_deps(package: str) -> None:
    """``ante.strategy`` 패키지 import 시 heavy 분석 의존성이 적재되지 않는다.

    회귀 시나리오: ``ante.strategy.__init__``에서 ``from ante.strategy.indicators
    import IndicatorCalculator``를 다시 top-level로 끌어오면 본 테스트가 즉시
    실패한다. PEP 562 ``__getattr__`` lazy 패턴을 유지해야 한다 (#1463).
    """
    payload = _run_isolated_import(package)
    loaded = payload["loaded"]
    assert loaded == [], (
        f"{package} import 시 heavy 분석 의존성이 적재되었습니다: {loaded}. "
        "`ante.strategy.__init__`은 PEP 562 `__getattr__`로 `IndicatorCalculator`만 "
        "lazy 노출해야 합니다 (see #1463)."
    )


def test_cli_main_does_not_eager_import_heavy_deps() -> None:
    """`ante.cli.main`(CLI 진입점) import에도 heavy 의존성이 새지 않는다."""
    payload = _run_isolated_import("ante.cli.main")
    loaded = payload["loaded"]
    assert loaded == [], (
        f"ante.cli.main import 시 heavy 분석 의존성이 적재되었습니다: {loaded}. "
        "CLI 진입 경로 어디에도 pandas/pandas_ta/numba 등을 top-level로 두면 안 됩니다."
    )


def test_isolation_helper_detects_planted_heavy_import() -> None:
    """헬퍼 자체 회귀 검증: heavy 모듈을 강제로 미리 import하면 잡아낸다.

    이 테스트는 ``_run_isolated_import``가 실제로 heavy import를 감지하는지를
    확인하기 위한 메타-테스트다. ``extra_imports``로 ``numpy``를 먼저 적재
    시키면, target import 후에도 `sys.modules`에 남아 있어야 한다.

    *numpy*를 쓰는 이유: ante의 prod 의존성 트리에 확실히 들어 있고 heavy
    목록에 포함되기 때문이다 (`pandas-ta` 의존성 체인).
    """
    payload = _run_isolated_import(
        "ante.cli.commands.strategy",
        extra_imports=("numpy",),
    )
    assert "numpy" in payload["loaded"], (
        "isolation helper가 사전 적재된 heavy import를 감지하지 못했습니다. "
        "회귀 차단 기능이 작동하지 않습니다."
    )
