"""전략 파일 접근 보안 경계 공용 helper."""

from __future__ import annotations

from pathlib import Path

from ante.strategy.exceptions import StrategyFileAccessError

STRATEGIES_ROOT = Path("strategies")


def resolve_strategy_path(strategies_dir: Path, path: str) -> Path:
    """전략 파일 경로를 검증하고 절대 경로로 변환.

    Args:
        strategies_dir: 허용된 샌드박스 루트. resolve 된 절대 경로를 권장한다.
        path: 전략이 요청한 상대 경로.

    Raises:
        StrategyFileAccessError: 절대 경로이거나, resolve 결과가
            ``strategies_dir`` 하위가 아닌 경우(symlink 탈출 포함).
    """
    if Path(path).is_absolute():
        raise StrategyFileAccessError(f"Absolute paths are not allowed: {path}")

    base = strategies_dir.resolve()
    resolved = (base / path).resolve()
    if not resolved.is_relative_to(base):
        raise StrategyFileAccessError(f"Path escapes strategies directory: {path}")

    return resolved


def load_strategy_file(strategies_dir: Path, path: str) -> bytes:
    """전략 전용 파일 읽기 (바이너리).

    ``strategies_dir`` 하위 경로만 허용하며, 경로 탈출 시도를 차단한다.

    Raises:
        StrategyFileAccessError: 경로 검증 실패 또는 파일 미존재.
    """
    resolved = resolve_strategy_path(strategies_dir, path)

    if not resolved.exists():
        raise StrategyFileAccessError(f"File not found: {path}")

    return resolved.read_bytes()


def load_strategy_text(strategies_dir: Path, path: str, encoding: str = "utf-8") -> str:
    """전략 전용 파일 읽기 (텍스트).

    ``strategies_dir`` 하위 경로만 허용하며, 경로 탈출 시도를 차단한다.

    Raises:
        StrategyFileAccessError: 경로 검증 실패 또는 파일 미존재.
    """
    data = load_strategy_file(strategies_dir, path)
    return data.decode(encoding)
