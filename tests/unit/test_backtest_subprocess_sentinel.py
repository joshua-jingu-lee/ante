"""run_subprocess 결과 라인을 sentinel marker로 stdout noise와 분리 (#2065).

``BacktestService.run_subprocess`` 는 이전에 subprocess stdout **전체**를
``json.loads`` 했다. 전략 import/실행 중 임의의 ``print`` noise가 결과
JSON 앞에 섞이면 ``JSONDecodeError`` 로 백테스트가 fake-fail 했다. runner
가 결과를 ``BACKTEST_RESULT_SENTINEL`` prefix 한 줄로 출력하고
``run_subprocess`` 는 그 sentinel 라인만 파싱하도록 변경했다.

검증 4축:
- (a) 재현: import 시점 stdout noise 전략 + 실제 subprocess →
  ``JSONDecodeError`` 없이 결과 dict 정상 수신.
- (b) 회귀: noise 없는 정상 전략 → 결과 정상 수신.
- (c) sentinel 라인 부재 → ``BacktestError`` ("did not emit a result line").
- (d) runner 결과 출력이 ``BACKTEST_RESULT_SENTINEL`` prefix 한 줄.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ante.backtest import runner
from ante.backtest.exceptions import BacktestError
from ante.backtest.service import BACKTEST_RESULT_SENTINEL, BacktestService

_NOISE_STRATEGY = """\
print("strategy import noise")
import sys
print("more stdout noise from module top", file=sys.stdout)
from typing import Any

from ante.strategy.base import Signal, Strategy, StrategyMeta


class NoiseStrategy(Strategy):
    meta = StrategyMeta(name="noise", version="1.0", description="noisy import")

    async def on_step(self, context: dict[str, Any]) -> list[Signal]:
        return []
"""

_CLEAN_STRATEGY = """\
from typing import Any

from ante.strategy.base import Signal, Strategy, StrategyMeta


class CleanStrategy(Strategy):
    meta = StrategyMeta(name="clean", version="1.0", description="no noise")

    async def on_step(self, context: dict[str, Any]) -> list[Signal]:
        return []
"""

_RESULT_KEYS = {
    "strategy",
    "period",
    "initial_balance",
    "final_balance",
    "total_return_pct",
    "total_trades",
}


def _write_strategy(tmp_path: Path, source: str) -> Path:
    strat = tmp_path / "strat.py"
    strat.write_text(source, encoding="utf-8")
    return strat


def _cfg(tmp_path: Path, strat: Path) -> dict:
    # symbols=[] (no-symbols backtest 정상) → 데이터 적재 불필요로 경량.
    return {
        "strategy_path": str(strat),
        "symbols": [],
        "timeframe": "1d",
        "exchange": "KRX",
        "start_date": "2026-01-01",
        "end_date": "2026-01-05",
        "data_path": str(tmp_path / "data"),
    }


# ── (a) 재현: stdout noise + 실제 subprocess → 정상 dict ──────────────────


class TestSubprocessTolerantToStdoutNoise:
    """전략 import 시점 stdout print noise가 있어도 결과 정상 수신."""

    @pytest.mark.asyncio
    async def test_import_noise_does_not_break_result_parsing(
        self, tmp_path: Path
    ) -> None:
        strat = _write_strategy(tmp_path, _NOISE_STRATEGY)
        svc = BacktestService(data_path=str(tmp_path / "data"))

        # 변경 전이라면 noise 라인 때문에 json.loads(stdout) 가
        # JSONDecodeError 를 던졌다. 이제는 sentinel 라인만 파싱한다.
        out = await svc.run_subprocess(_cfg(tmp_path, strat))

        assert isinstance(out, dict)
        assert _RESULT_KEYS <= set(out)
        assert out["strategy"] == "noise_v1.0"


# ── (b) 회귀: noise 없는 정상 전략 → 정상 수신 ───────────────────────────


class TestSubprocessCleanStrategyRegression:
    """noise 없는 전략도 동일하게 정상 dict 수신 (기존 경로 회귀)."""

    @pytest.mark.asyncio
    async def test_clean_strategy_returns_result(self, tmp_path: Path) -> None:
        strat = _write_strategy(tmp_path, _CLEAN_STRATEGY)
        svc = BacktestService(data_path=str(tmp_path / "data"))

        out = await svc.run_subprocess(_cfg(tmp_path, strat))

        assert isinstance(out, dict)
        assert _RESULT_KEYS <= set(out)
        assert out["strategy"] == "clean_v1.0"


# ── (c) sentinel 라인 부재 → BacktestError ───────────────────────────────


class TestSubprocessMissingSentinel:
    """stdout 에 sentinel 라인이 없으면 BacktestError 로 명시 실패."""

    def _patched_spawn(self, stdout: bytes, returncode: int = 0):
        mock_proc = MagicMock()

        async def _fake_communicate(input=None):
            return (stdout, b"")

        mock_proc.communicate = _fake_communicate
        mock_proc.returncode = returncode

        async def _fake_spawn(*args, **kwargs):
            return mock_proc

        return patch(
            "ante.backtest.service.asyncio.create_subprocess_exec",
            side_effect=_fake_spawn,
        )

    @pytest.mark.asyncio
    async def test_no_sentinel_line_raises_backtest_error(self) -> None:
        # returncode==0 인데도 sentinel 라인이 전혀 없는 stdout —
        # noise 만 있고 결과 라인을 못 찾은 경우.
        stdout = b'just noise\n{"ok": true}\nmore noise\n'
        svc = BacktestService()
        cfg = {
            "strategy_path": "s.py",
            "start_date": "2026-01-01",
            "end_date": "2026-01-02",
        }
        with self._patched_spawn(stdout):
            with pytest.raises(BacktestError, match="did not emit a result line"):
                await svc.run_subprocess(cfg)

    @pytest.mark.asyncio
    async def test_sentinel_line_among_noise_is_extracted(self) -> None:
        # 결과 라인이 noise 사이에 끼어 있어도 sentinel 로 정확히 추출.
        payload = json.dumps({"strategy": "x_v1.0", "total_trades": 0})
        stdout = (
            b"leading noise from strategy import\n"
            + f"{BACKTEST_RESULT_SENTINEL}{payload}\n".encode()
            + b"trailing noise\n"
        )
        svc = BacktestService()
        cfg = {
            "strategy_path": "s.py",
            "start_date": "2026-01-01",
            "end_date": "2026-01-02",
        }
        with self._patched_spawn(stdout):
            out = await svc.run_subprocess(cfg)

        assert out == {"strategy": "x_v1.0", "total_trades": 0}


# ── (d) runner 결과 출력 형식: sentinel prefix 한 줄 ──────────────────────


class TestRunnerEmitsSentinelLine:
    """runner.main() 결과 print 가 BACKTEST_RESULT_SENTINEL prefix 한 줄."""

    def test_main_prints_single_sentinel_line(self, capsys, monkeypatch) -> None:
        cfg = {
            "strategy_path": "s.py",
            "start_date": "2026-01-01",
            "end_date": "2026-01-02",
        }
        result_dict = {"strategy": "x_v1.0", "total_trades": 0}

        monkeypatch.setattr(
            "ante.backtest.runner.sys.stdin.read",
            lambda: json.dumps(cfg),
        )

        async def _fake_run_backtest(config: dict) -> dict:
            return result_dict

        monkeypatch.setattr(runner, "run_backtest", _fake_run_backtest)

        runner.main()

        captured = capsys.readouterr().out
        result_lines = [
            line
            for line in captured.splitlines()
            if line.startswith(BACKTEST_RESULT_SENTINEL)
        ]
        # sentinel 결과 라인은 정확히 한 줄.
        assert len(result_lines) == 1
        payload = result_lines[0][len(BACKTEST_RESULT_SENTINEL) :]
        # payload 는 단일 라인 JSON (indent 없음) → 그대로 round-trip.
        assert json.loads(payload) == result_dict
