"""전략 파일 접근 보안 경계 공용 helper (#2083).

라이브 ``StrategyContext`` 와 ``BacktestStrategyContext`` 가 동일한 전략 파일
접근 시맨틱(strategies/ 디렉터리 샌드박스)을 공유하도록, 보안 경계 로직을 이
모듈에 **단일 소유**시킨다.

보안 시맨틱(SSOT):

- 절대 경로는 거부한다 (``StrategyFileAccessError``, ``"Absolute paths"``).
- ``strategies_dir`` 하위로 resolve 되지 않는 경로(``../`` 탈출, symlink 탈출
  포함)는 거부한다 (``StrategyFileAccessError``, ``"escapes"``). base/candidate
  를 **모두 ``resolve()`` 후** 비교해 symlink escape 도 차단한다.
- 미존재 파일은 거부한다 (``StrategyFileAccessError``, ``"File not found"``).

에러 메시지는 라이브 ``StrategyContext`` 의 기존 동작과 1:1 동일하게 보존한다
(기존 strategy context 테스트가 메시지를 lock 한다).
"""

from __future__ import annotations

from pathlib import Path

from ante.strategy.exceptions import StrategyFileAccessError

# strategies/ 디렉토리 기준 경로 (프로젝트 루트 기준).
# 기존 ``ante.strategy.context._STRATEGIES_ROOT`` 와 동일 값/계산을 이리로 이동.
STRATEGIES_ROOT = Path("strategies")


def resolve_strategy_path(strategies_dir: Path, path: str) -> Path:
    """전략 파일 경로를 검증하고 절대 경로로 변환.

    Args:
        strategies_dir: 허용된 샌드박스 루트. resolve 된 절대 경로를 권장한다.
        path: 전략이 요청한 상대 경로.

    Returns:
        ``strategies_dir`` 하위로 resolve 된 절대 경로.

    Raises:
        StrategyFileAccessError: 절대 경로이거나, resolve 결과가
            ``strategies_dir`` 하위가 아닌 경우(symlink 탈출 포함).
    """
    # 절대 경로 차단
    if Path(path).is_absolute():
        raise StrategyFileAccessError(f"Absolute paths are not allowed: {path}")

    # 경로 탈출 시도 차단. base/candidate 모두 resolve() 후 비교하여
    # symlink escape 도 차단한다.
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
