"""StrategyLoader — 전략 파일 동적 로딩."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from ante.strategy.base import Strategy
from ante.strategy.exceptions import StrategyLoadError


class StrategyLoader:
    """전략 파일을 동적으로 로드하여 Strategy 클래스를 반환."""

    @staticmethod
    def load(filepath: Path) -> type[Strategy]:
        """전략 파일에서 Strategy 하위 클래스를 로드.

        Args:
            filepath: 전략 파일 경로

        Returns:
            Strategy를 상속한 클래스 (인스턴스 아님)

        Raises:
            StrategyLoadError: 파일 로드 실패 또는 Strategy 하위 클래스 미발견
        """
        if not filepath.exists():
            raise StrategyLoadError(f"File not found: {filepath}")

        spec = importlib.util.spec_from_file_location(
            f"strategy_{filepath.stem}",
            filepath,
        )
        if spec is None or spec.loader is None:
            raise StrategyLoadError(f"Cannot load module: {filepath}")

        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except Exception as e:
            raise StrategyLoadError(f"Failed to execute module {filepath}: {e}") from e

        strategy_classes = [
            obj
            for obj in vars(module).values()
            if isinstance(obj, type)
            and issubclass(obj, Strategy)
            and obj is not Strategy
        ]

        if len(strategy_classes) == 0:
            raise StrategyLoadError(f"No Strategy subclass found in {filepath}")
        if len(strategy_classes) > 1:
            raise StrategyLoadError(
                f"Multiple Strategy subclasses in {filepath}: "
                f"{[c.__name__ for c in strategy_classes]}"
            )

        return strategy_classes[0]
