"""Backtest subprocess 진입점.

Usage: python -m ante.backtest.runner < config.json
"""

from __future__ import annotations

import asyncio
import json
import sys

from ante.backtest.service import BACKTEST_RESULT_SENTINEL


async def run_backtest(config: dict) -> dict:
    """백테스트 실행 후 결과를 additive envelope dict로 반환 (#2001).

    반환 dict 는 ``result.to_dict()`` 의 모든 키를 보존하는 superset 이며,
    ``to_dict()`` 가 (artifact self-reference 회피 + draft 소비 shape 유지를
    위해) 직렬화에서 제외하는 런타임 메타데이터 3키를 명시적으로 surface 한다:

    - ``result_path``: ``service.run()`` 이 저장한 durable artifact 경로
      (#1998). subprocess(stdout) → ``run_subprocess`` → CLI ``_save_backtest_run``
      → ``backtest_runs.result_path`` 추적성 전파용. 저장 실패 시 ``""``.
    - ``strategy_name`` / ``strategy_version``: ``to_dict`` 가 combined
      ``strategy`` (``"{name}_v{version}"``) 만 제공하므로, CLI 가 split 파싱
      없이 개별 키를 직접 쓰도록 surface 한다.

    이는 ``run_backtest()`` 반환 계약의 **명시적 additive 확장**이다
    (``to_dict()`` 직렬화 계약 자체는 무변경). ``output_path`` 로 기록하는
    파일 아티팩트는 envelope 가 아닌 ``to_dict()`` 그대로 유지한다 —
    ReportDraftGenerator 등 artifact 소비 shape 를 바꾸지 않기 위함이다.
    """
    from ante.backtest.service import BacktestService

    service = BacktestService(
        data_path=config.get("data_path", "data/"),
    )
    result = await service.run(config)

    payload = result.to_dict()

    output_path = config.get("output_path")
    if output_path:
        from pathlib import Path

        # 파일 아티팩트는 to_dict() 그대로 유지(envelope 아님 — artifact 소비
        # shape 무변경). stdout envelope 와 의도적으로 형식을 분리한다.
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
