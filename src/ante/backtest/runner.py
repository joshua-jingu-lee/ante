"""Backtest subprocess 진입점.

Usage: python -m ante.backtest.runner < config.json
"""

from __future__ import annotations

import asyncio
import json
import sys


async def run_backtest(config: dict) -> dict:
    """백테스트 실행 후 결과를 dict로 반환."""
    from ante.backtest.service import BacktestService

    service = BacktestService(
        data_path=config.get("data_path", "data/"),
    )
    result = await service.run(config)

    output_path = config.get("output_path")
    if output_path:
        from pathlib import Path

        Path(output_path).write_text(
            json.dumps(result.to_dict(), indent=2, default=str)
        )

    return result.to_dict()


def main() -> None:
    """stdin에서 config JSON을 읽고, 결과를 stdout으로 출력."""
    config = json.loads(sys.stdin.read())
    result = asyncio.run(run_backtest(config))
    print(json.dumps(result, default=str))


if __name__ == "__main__":
    main()
