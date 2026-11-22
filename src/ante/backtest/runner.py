"""Backtest subprocess 진입점."""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

from ante.backtest.service import BACKTEST_RESULT_SENTINEL


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
        from pathlib import Path

        Path(output_path).write_text(json.dumps(payload, indent=2, default=str))

    return {
        **payload,
        "result_path": result.result_path,
        "strategy_name": result.strategy_name,
        "strategy_version": result.strategy_version,
    }


def main() -> None:
    """stdin에서 config JSON을 읽고, 결과를 stdout으로 출력."""
    config = json.loads(sys.stdin.read())
    result = asyncio.run(run_backtest(config))
    print(f"{BACKTEST_RESULT_SENTINEL}{json.dumps(result, default=str)}")


if __name__ == "__main__":
    main()
