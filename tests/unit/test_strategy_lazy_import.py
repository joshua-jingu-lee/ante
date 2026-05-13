"""ante.strategy import isolation 회귀 테스트 (#1463).

``import ante.strategy`` 또는 ``from ante.strategy import <light symbol>``이
heavy dependency(``pandas``, ``pandas_ta``, ``numba``, ``talib``)를 eager
load하지 않는지 검증한다. heavy 의존성은 ``IndicatorCalculator`` 같은 실제
지표 계산 경로가 호출될 때만 로드되어야 한다.

격리를 위해 각 시나리오는 별도의 ``subprocess``에서 실행한다. ``sys.modules``를
런타임에 비교하는 방식은 같은 ``pytest`` 프로세스 안에서 이미 다른 테스트가
heavy 모듈을 로드했다면 거짓 양성(또는 음성)을 일으킬 수 있기 때문이다.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC = _REPO_ROOT / "src"

# eager-load되면 안 되는 heavy 의존성 prefix.
_HEAVY_PREFIXES: tuple[str, ...] = (
    "pandas",
    "pandas_ta",
    "numba",
    "talib",
)


def _run_isolated(snippet: str) -> tuple[int, str, str]:
    """별도 파이썬 프로세스에서 snippet을 실행하고 (rc, stdout, stderr)를 반환.

    ``-I``(isolated) 플래그는 ``PYTHONPATH``를 무시하므로, 대신 ``sys.path``
    선두에 ``src/``를 직접 삽입하는 부트스트랩을 snippet 앞에 prepend한다.
    """
    bootstrap = f"import sys; sys.path.insert(0, {str(_SRC)!r})\n"
    proc = subprocess.run(  # noqa: S603 — 신뢰 입력, 고정된 인터프리터
        [sys.executable, "-I", "-c", bootstrap + snippet],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode, proc.stdout, proc.stderr


def _loaded_heavy_modules_after(import_stmt: str) -> set[str]:
    """``import_stmt`` 실행 후 ``sys.modules``에 존재하는 heavy 모듈 이름 집합."""
    snippet = (
        "import sys\n"
        f"{import_stmt}\n"
        "import json\n"
        "prefixes = " + repr(_HEAVY_PREFIXES) + "\n"
        "found = sorted({m for m in sys.modules if m.split('.', 1)[0] in prefixes})\n"
        "print(json.dumps(found))\n"
    )
    rc, stdout, stderr = _run_isolated(snippet)
    if rc != 0:
        pytest.fail(
            f"isolated import probe failed (rc={rc}):\nstdout={stdout}\nstderr={stderr}"
        )
    import json as _json

    return set(_json.loads(stdout.strip()))


class TestAnteStrategyLazyImport:
    """``ante.strategy`` package init이 heavy deps를 끌어오지 않아야 한다."""

    def test_import_ante_strategy_does_not_load_pandas(self) -> None:
        """``import ante.strategy`` 자체는 pandas/pandas_ta를 로드하지 않는다."""
        loaded = _loaded_heavy_modules_after("import ante.strategy")
        pandas_roots = {"pandas", "pandas_ta"}
        pandas_like = {m for m in loaded if m.split(".", 1)[0] in pandas_roots}
        assert pandas_like == set(), (
            "import ante.strategy must not eager-load pandas/pandas_ta; "
            f"got {sorted(pandas_like)}"
        )

    def test_import_ante_strategy_does_not_load_numba(self) -> None:
        """``import ante.strategy``는 numba(JIT 컴파일러)를 끌어오지 않는다.

        numba는 import 비용이 가장 큰 의존성(수백 ms~수 초)이라 CLI cold-path
        latency 회귀 게이트로 활용한다.
        """
        loaded = _loaded_heavy_modules_after("import ante.strategy")
        numba_like = {m for m in loaded if m.split(".", 1)[0] == "numba"}
        assert numba_like == set(), (
            "import ante.strategy must not eager-load numba; "
            f"got {sorted(numba_like)[:5]} ({len(numba_like)} modules)"
        )

    def test_import_strategy_registry_submodule_stays_light(self) -> None:
        """``import ante.strategy.registry``는 heavy deps를 로드하지 않는다.

        registry 자체는 ``aiosqlite`` + ``dataclass``만 사용하는 light 모듈이지만,
        과거에는 부모 패키지 ``__init__``이 ``indicators``를 끌어오면서
        ``import ante.strategy.registry``만으로도 pandas/numba가 함께 로드되었다.
        """
        loaded = _loaded_heavy_modules_after("import ante.strategy.registry")
        assert loaded == set(), (
            "import ante.strategy.registry must stay light; "
            f"unexpectedly loaded {sorted(loaded)[:5]} "
            f"({len(loaded)} heavy modules)"
        )

    def test_from_ante_strategy_import_status_stays_light(self) -> None:
        """``from ante.strategy import StrategyStatus``는 heavy deps를 끌어오지 않는다.

        CLI preflight 등 light enum만 필요한 cold-path가 heavy import에 막히지
        않아야 한다 (#1416 / #1461).
        """
        loaded = _loaded_heavy_modules_after(
            "from ante.strategy import StrategyStatus, StrategyRecord, StrategyError"
        )
        assert loaded == set(), (
            "light symbol access via ante.strategy must not eager-load heavy deps; "
            f"got {sorted(loaded)[:5]} ({len(loaded)} modules)"
        )

    def test_indicator_calculator_access_loads_pandas(self) -> None:
        """``IndicatorCalculator`` 접근 시점에 pandas가 로드되어야 한다.

        lazy-load의 반대 방향 회귀: heavy 의존성이 실제로는 쓸 수 있어야 한다.
        """
        loaded = _loaded_heavy_modules_after(
            "from ante.strategy import IndicatorCalculator\n"
            "assert IndicatorCalculator.is_available()"
        )
        # pandas는 IndicatorCalculator 경로에서 항상 로드되어야 한다.
        assert any(m == "pandas" or m.startswith("pandas.") for m in loaded), (
            "IndicatorCalculator access must materialize pandas import; "
            f"got {sorted(loaded)[:5]}"
        )


class TestAnteStrategyPublicSymbolsStable:
    """lazy 전환 이후에도 기존 퍼블릭 import 계약이 유지되어야 한다 (#1463 scope)."""

    def test_public_symbols_resolve_via_top_level(self) -> None:
        """``__all__`` 의 모든 심볼이 lazy __getattr__로 접근 가능해야 한다."""
        import ante.strategy as pkg

        for name in pkg.__all__:
            assert hasattr(pkg, name), (
                f"ante.strategy must expose {name!r} (declared in __all__) "
                "via lazy __getattr__"
            )

    def test_public_symbol_identity_matches_submodule(self) -> None:
        """top-level alias와 submodule alias는 동일 객체여야 한다."""
        import ante.strategy
        import ante.strategy.registry

        assert ante.strategy.StrategyStatus is ante.strategy.registry.StrategyStatus

    def test_dir_lists_lazy_attrs(self) -> None:
        """``dir(ante.strategy)`` 는 lazy 심볼을 포함해 IDE/REPL 보조를 유지한다."""
        import ante.strategy as pkg

        listed = set(dir(pkg))
        # __all__ 의 모든 심볼이 dir에 나타나야 한다.
        assert set(pkg.__all__).issubset(listed)

    def test_unknown_attribute_raises_attribute_error(self) -> None:
        """알 수 없는 속성은 일반 ``AttributeError``로 실패한다 (메시지 회귀 차단)."""
        import ante.strategy as pkg

        with pytest.raises(AttributeError):
            _ = pkg.ThisAttributeDoesNotExist  # type: ignore[attr-defined]
