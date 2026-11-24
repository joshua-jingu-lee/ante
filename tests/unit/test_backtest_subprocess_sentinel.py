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

# #2039: 전략 파일은 import 시점에 코드를 실행할 수 없으므로(top-level
# print/`import sys` 는 StrategyValidator가 거부), stdout noise는 검증을
# 통과하는 위치인 ``on_step`` (런타임) 에서 print 한다. runner subprocess의
# stdout에 결과 sentinel 라인 외 noise가 섞여도 run_subprocess가 sentinel
# 라인만 파싱하는지(#2065)를 그대로 검증한다.
_NOISE_STRATEGY = """\
from typing import Any

from ante.strategy.base import Signal, Strategy, StrategyMeta


class NoiseStrategy(Strategy):
    meta = StrategyMeta(name="noise", version="1.0", description="noisy run")

    async def on_step(self, context: dict[str, Any]) -> list[Signal]:
        print("strategy runtime stdout noise")
        print("more stdout noise from on_step")
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


def _write_ohlcv(data_dir: Path, symbol: str, *, n: int = 5) -> None:
    """``data_dir`` 에 ``symbol`` 1d OHLCV를 적재(런타임 step 발생용)."""
    from datetime import UTC, datetime, timedelta

    import polars as pl

    from ante.data.store import ParquetStore

    start = datetime(2026, 1, 2, 9, 0, tzinfo=UTC)
    timestamps = pl.datetime_range(
        start,
        start + timedelta(days=n - 1),
        interval="1d",
        eager=True,
        time_zone="UTC",
    )
    df = pl.DataFrame(
        {
            "timestamp": timestamps,
            "symbol": [symbol] * n,
            "open": [50000.0 + i * 100 for i in range(n)],
            "high": [50000.0 + i * 100 + 50 for i in range(n)],
            "low": [50000.0 + i * 100 - 50 for i in range(n)],
            "close": [50000.0 + i * 100 + 25 for i in range(n)],
            "volume": [1000 + i * 10 for i in range(n)],
            "source": ["test"] * n,
        }
    )
    ParquetStore(base_path=data_dir).write(symbol, "1d", df)


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
        # on_step(런타임)에서 stdout noise를 내려면 step이 실행되어야 하므로
        # 데이터를 적재하고 symbol을 지정한다(#2039로 import-time noise 불가).
        _write_ohlcv(tmp_path / "data", "005930")
        svc = BacktestService(data_path=str(tmp_path / "data"))

        # 변경 전이라면 noise 라인 때문에 json.loads(stdout) 가
        # JSONDecodeError 를 던졌다. 이제는 sentinel 라인만 파싱한다.
        cfg = _cfg(tmp_path, strat)
        cfg["symbols"] = ["005930"]
        out = await svc.run_subprocess(cfg)

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


# ── (e) 자식 실패의 message: 트레이스백 대신 종류·메시지·전략 줄 (#2734) ────

_RAISING_STRATEGY = """\
from typing import Any

from ante.strategy.base import Signal, Strategy, StrategyMeta


class RaisingStrategy(Strategy):
    meta = StrategyMeta(name="raising", version="1.0", description="raises")

    async def on_step(self, context: dict[str, Any]) -> list[Signal]:
        raise ValueError({arg})
"""


def _raise_line(source: str) -> int:
    lines = source.splitlines()
    return next(i for i, line in enumerate(lines, 1) if "raise ValueError" in line)


def _assert_no_traceback(message: str, tmp_path: Path) -> None:
    assert "Traceback" not in message
    assert 'File "' not in message
    assert str(tmp_path) not in message
    assert str(tmp_path.resolve()) not in message


def _failure_sentinel() -> str:
    from ante.backtest import service

    return service.BACKTEST_FAILURE_SENTINEL


class TestSubprocessFailureMessage:
    """자식 실패의 BacktestError message에 트레이스백 전문이 실리지 않는다."""

    async def _run_raising(
        self, tmp_path: Path, arg: str, *, relative: bool
    ) -> tuple[str, int]:
        source = _RAISING_STRATEGY.format(arg=arg)
        strat = _write_strategy(tmp_path, source)
        _write_ohlcv(tmp_path / "data", "005930")
        svc = BacktestService(data_path=str(tmp_path / "data"))
        cfg = _cfg(tmp_path, strat)
        cfg["symbols"] = ["005930"]
        if relative:
            cfg["strategy_path"] = "strat.py"
        with pytest.raises(BacktestError) as exc_info:
            await svc.run_subprocess(cfg)
        return str(exc_info.value), _raise_line(source)

    @pytest.mark.asyncio
    async def test_strategy_exception_reports_type_message_and_line(
        self, tmp_path: Path
    ) -> None:
        message, line = await self._run_raising(tmp_path, '"boom"', relative=False)

        assert message == (
            f"Backtest subprocess failed: ValueError: boom (strat.py:{line})"
        )
        _assert_no_traceback(message, tmp_path)

    @pytest.mark.asyncio
    async def test_relative_strategy_path_still_finds_strategy_frame(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        message, line = await self._run_raising(tmp_path, '"boom"', relative=True)

        assert message == (
            f"Backtest subprocess failed: ValueError: boom (strat.py:{line})"
        )
        _assert_no_traceback(message, tmp_path)

    @pytest.mark.asyncio
    async def test_empty_exception_message_has_no_dangling_colon(
        self, tmp_path: Path
    ) -> None:
        message, line = await self._run_raising(tmp_path, "", relative=False)

        assert message == f"Backtest subprocess failed: ValueError (strat.py:{line})"

    @pytest.mark.asyncio
    async def test_validation_failure_has_type_and_message_without_location(
        self, tmp_path: Path
    ) -> None:
        strat = _write_strategy(tmp_path, "# dummy")
        svc = BacktestService(data_path=str(tmp_path / "data"))

        with pytest.raises(BacktestError) as exc_info:
            await svc.run_subprocess(_cfg(tmp_path, strat))

        message = str(exc_info.value)
        assert message.startswith(
            "Backtest subprocess failed: BacktestConfigError: 전략 검증 실패"
        )
        assert not message.endswith(")")
        _assert_no_traceback(message, tmp_path)


class TestSubprocessFailureWithoutSentinel:
    """실패 sentinel이 없거나 읽히지 않으면 종료 코드만 싣는다."""

    _CFG = {
        "strategy_path": "s.py",
        "start_date": "2026-01-01",
        "end_date": "2026-01-02",
    }

    def _patched_spawn(self, stdout: bytes, stderr: bytes, returncode: int):
        mock_proc = MagicMock()

        async def _fake_communicate(input=None):
            return (stdout, stderr)

        mock_proc.communicate = _fake_communicate
        mock_proc.returncode = returncode

        async def _fake_spawn(*args, **kwargs):
            return mock_proc

        return patch(
            "ante.backtest.service.asyncio.create_subprocess_exec",
            side_effect=_fake_spawn,
        )

    async def _message(self, stdout: bytes, stderr: bytes, returncode: int) -> str:
        with self._patched_spawn(stdout, stderr, returncode):
            with pytest.raises(BacktestError) as exc_info:
                await BacktestService().run_subprocess(dict(self._CFG))
        return str(exc_info.value)

    @pytest.mark.asyncio
    async def test_killed_child_reports_exit_code_only(self) -> None:
        stderr = b'Traceback (most recent call last):\n  File "/home/x/a.py"\n'

        message = await self._message(b"", stderr, -9)

        assert message == "Backtest subprocess failed (exit code -9)"

    @pytest.mark.asyncio
    async def test_malformed_failure_sentinel_reports_exit_code_only(self) -> None:
        stdout = f"{_failure_sentinel()}not json\n".encode()

        message = await self._message(stdout, b"Traceback /home/x", 1)

        assert message == "Backtest subprocess failed (exit code 1)"

    @pytest.mark.asyncio
    async def test_last_failure_sentinel_wins(self) -> None:
        sentinel = _failure_sentinel()
        fake = json.dumps({"type": "X", "message": "fake", "location": None})
        real = json.dumps({"type": "Y", "message": "real", "location": "s.py:3"})
        stdout = f"{sentinel}{fake}\npartial\n{sentinel}{real}\n".encode()

        message = await self._message(stdout, b"", 1)

        assert message == "Backtest subprocess failed: Y: real (s.py:3)"


class TestRunnerFailureSentinel:
    """runner.main()이 일반 예외를 실패 sentinel 한 줄과 exit 1로 바꾼다."""

    def _stdin(self, monkeypatch) -> None:
        cfg = {"strategy_path": "s.py", "start_date": "2026-01-01"}
        monkeypatch.setattr(
            "ante.backtest.runner.sys.stdin.read", lambda: json.dumps(cfg)
        )

    def test_exception_becomes_failure_sentinel_and_exit_1(
        self, capsys, monkeypatch
    ) -> None:
        self._stdin(monkeypatch)

        async def _boom(config: dict) -> dict:
            raise RuntimeError("bad")

        monkeypatch.setattr(runner, "run_backtest", _boom)
        print("no newline noise", end="")

        with pytest.raises(SystemExit) as exc_info:
            runner.main()

        assert exc_info.value.code == 1
        lines = capsys.readouterr().out.splitlines()
        sentinel = _failure_sentinel()
        assert lines[-1].startswith(sentinel)
        payload = json.loads(lines[-1][len(sentinel) :])
        assert payload == {"type": "RuntimeError", "message": "bad", "location": None}
        assert not any(line.startswith(BACKTEST_RESULT_SENTINEL) for line in lines)

    def test_keyboard_interrupt_is_not_caught(self, capsys, monkeypatch) -> None:
        self._stdin(monkeypatch)

        async def _interrupt(config: dict) -> dict:
            raise KeyboardInterrupt

        monkeypatch.setattr(runner, "run_backtest", _interrupt)

        with pytest.raises(KeyboardInterrupt):
            runner.main()

        assert capsys.readouterr().out == ""
