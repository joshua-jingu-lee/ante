"""Backtest subprocess 진입점."""

from __future__ import annotations

import asyncio
import json
import sys
import traceback
from pathlib import Path
from typing import Any

from ante.backtest.service import BACKTEST_FAILURE_SENTINEL, BACKTEST_RESULT_SENTINEL


async def run_backtest(config: dict[str, Any]) -> dict[str, Any]:
    """백테스트 실행 후 결과를 additive envelope dict로 반환."""
    from ante.backtest.service import BacktestService

    service = BacktestService(
        data_path=config.get("data_path", "data/"),
    )
    result = await service.run(config)

    payload = result.to_dict()

    output_path = config.get("output_path")
    if output_path:
        Path(output_path).write_text(json.dumps(payload, indent=2, default=str))

    return {
        **payload,
        "result_path": result.result_path,
        "strategy_name": result.strategy_name,
        "strategy_version": result.strategy_version,
    }


def _strategy_location(exc: BaseException, strategy_path: object) -> str | None:
    """traceback에서 전략 파일의 가장 안쪽 프레임을 ``파일 이름:줄``로 돌려준다."""
    if not isinstance(strategy_path, str) or not strategy_path:
        return None
    target = Path(strategy_path).resolve()
    location = None
    for frame in traceback.extract_tb(exc.__traceback__):
        if Path(frame.filename).resolve() == target:
            location = f"{target.name}:{frame.lineno}"
    return location


def main() -> None:
    """stdin에서 config JSON을 읽고, 결과 또는 실패 sentinel을 stdout으로 출력."""
    config = json.loads(sys.stdin.read())
    try:
        result = asyncio.run(run_backtest(config))
    except Exception as exc:
        strategy_path = (
            config.get("strategy_path") if isinstance(config, dict) else None
        )
        failure = {
            "type": type(exc).__name__,
            "message": str(exc),
            "location": _strategy_location(exc, strategy_path),
        }
        print()
        print(f"{BACKTEST_FAILURE_SENTINEL}{json.dumps(failure)}", flush=True)
        raise SystemExit(1) from exc
    print(f"{BACKTEST_RESULT_SENTINEL}{json.dumps(result, default=str)}")


if __name__ == "__main__":
    main()
