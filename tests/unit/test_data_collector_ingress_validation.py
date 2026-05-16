"""DataCollector symbol/timeframe ingress 검증 단위 테스트 (#1614).

선행: #1612(계약)·#1613(코드 SSOT). 공용 helper `_is_valid_ingress`
+ 3지점 defense-in-depth(`_collect_loop` pre-callback / `add_data` /
`_flush` 최종 guard) + invalid-drop vs append-exception-retry 구분 +
`flush_all` 이번 호출 append 성공분만 count 를 검증한다.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from ante.data.collector import DataCollector


def _row(minute: int = 0) -> dict:
    return {
        "timestamp": datetime(2026, 3, 1, 9, minute, tzinfo=UTC),
        "symbol": "005930",
        "open": 50000.0,
        "high": 50100.0,
        "low": 49900.0,
        "close": 50050.0,
        "volume": 1000,
        "source": "test",
    }


def _make_collector(buffer_size: int = 100, exchange: str = "KRX") -> DataCollector:
    """`_store` 를 MagicMock 으로 둔 collector (append 호출 정밀 검증용)."""
    store = MagicMock()
    eventbus = AsyncMock()
    return DataCollector(
        store=store,
        eventbus=eventbus,
        buffer_size=buffer_size,
        exchange=exchange,
    )


# ── add_data ingress 거부 ────────────────────────────────


class TestAddDataIngress:
    def test_reject_non_krx_6digit_symbol(self, caplog):
        c = _make_collector()
        with caplog.at_level(logging.WARNING):
            c.add_data("ABCDEF", "1m", _row())
        assert "ABCDEF:1m" not in c.buffer
        assert c.buffer == {}
        c._store.append.assert_not_called()
        assert "ingress reject (add_data)" in caplog.text

    def test_reject_1d_write_ownership_boundary(self, caplog):
        c = _make_collector()
        with caplog.at_level(logging.WARNING):
            c.add_data("005930", "1d", _row())
        assert "005930:1d" not in c.buffer
        c._store.append.assert_not_called()
        assert "ingress reject (add_data)" in caplog.text

    def test_reject_tick_no_ohlcv_path(self, caplog):
        c = _make_collector()
        with caplog.at_level(logging.WARNING):
            c.add_data("005930", "tick", _row())
        assert "005930:tick" not in c.buffer
        c._store.append.assert_not_called()

    def test_reject_oracle_invalid_timeframe(self, caplog):
        c = _make_collector()
        with caplog.at_level(logging.WARNING):
            c.add_data("005930", "oracle-invalid-timeframe", _row())
        assert c.buffer == {}
        c._store.append.assert_not_called()

    @pytest.mark.parametrize("tf", ["1m", "5m", "15m", "1h"])
    def test_valid_canonical_timeframes_buffered(self, tf):
        c = _make_collector()
        c.add_data("005930", tf, _row())
        assert c.buffer[f"005930:{tf}"] == [_row()]
        c._store.append.assert_not_called()  # buffer_size 미달, flush 안 됨

    def test_valid_input_flush_append_preserved(self):
        c = _make_collector(buffer_size=2)
        c.add_data("005930", "1m", _row(0))
        assert "005930:1m" in c.buffer
        c.add_data("005930", "1m", _row(1))  # buffer full → auto flush
        assert "005930:1m" not in c.buffer
        c._store.append.assert_called_once()
        args, kwargs = c._store.append.call_args
        assert args[0] == "005930"
        assert args[1] == "1m"
        assert len(args[2]) == 2
        assert kwargs["exchange"] == "KRX"

    def test_non_str_timeframe_list_no_typeerror(self, caplog):
        c = _make_collector()
        with caplog.at_level(logging.WARNING):
            c.add_data("005930", ["1m"], _row())  # type: ignore[arg-type]
        assert c.buffer == {}
        c._store.append.assert_not_called()
        assert "ingress reject (add_data)" in caplog.text

    def test_non_str_timeframe_int_no_typeerror(self, caplog):
        c = _make_collector()
        with caplog.at_level(logging.WARNING):
            c.add_data("005930", 1, _row())  # type: ignore[arg-type]
        assert c.buffer == {}
        c._store.append.assert_not_called()

    def test_non_krx_exchange_skips_symbol_shape(self):
        c = _make_collector(exchange="NASDAQ")
        c.add_data("AAPL", "1m", _row())
        assert c.buffer["AAPL:1m"] == [_row()]


# ── _collect_loop pre-callback guard (R1-F1) ─────────────


class TestCollectLoopGuard:
    async def test_invalid_timeframe_callback_not_called(self):
        c = _make_collector()
        callback = AsyncMock(return_value=[_row()])
        c.set_data_callback(callback)
        c._collect_interval = 0.05

        c.start(["005930"], ["oracle-invalid-timeframe"])
        await asyncio.sleep(0.08)
        c.stop()

        callback.assert_not_called()
        assert c.buffer == {}
        c._store.append.assert_not_called()

    async def test_mixed_valid_invalid_only_valid_collected(self):
        c = _make_collector()
        seen: list[tuple[str, str]] = []

        async def cb(symbol, tf):
            seen.append((symbol, tf))
            return [_row()]

        c.set_data_callback(cb)
        c._collect_interval = 0.05
        c.start(["005930", "BADSYM"], ["1m", "1d"])
        await asyncio.sleep(0.08)
        c.stop()

        # 통과는 (005930, 1m) 만. BADSYM(비6자리)·1d(write-ownership) 거부
        assert (("005930", "1m")) in seen
        assert ("005930", "1d") not in seen
        assert ("BADSYM", "1m") not in seen
        assert ("BADSYM", "1d") not in seen
        assert all(s == "005930" and t == "1m" for s, t in seen)


# ── _flush 최종 guard + buffer 우회 + count (R1-F2/R2-F1/R3-F1) ──


class TestFlushGuardAndCount:
    def test_buffer_bypass_mixed_keys_only_valid_appended(self, caplog):
        c = _make_collector()
        n = 4
        valid_rows = [_row(i) for i in range(n)]
        # public buffer 프로퍼티 직접 주입 (add_data 검증 우회)
        c.buffer["005930:oracle-invalid-timeframe"] = [_row()]  # invalid tf
        c.buffer["badkey"] = [_row()]  # no-colon
        c.buffer["005930:1m:extra"] = [_row()]  # extra-colon
        c.buffer[("005930", "1m")] = [_row()]  # type: ignore[index]  # non-str key
        c.buffer["AAPL:1m"] = [_row()]  # KRX 비6자리 symbol
        c.buffer["005930:1m"] = valid_rows  # valid (rows=N)

        with caplog.at_level(logging.WARNING):
            total = c.flush_all()  # raise 없이 완주해야 함

        # valid 키만 append, 정확히 rows=N
        c._store.append.assert_called_once()
        args, kwargs = c._store.append.call_args
        assert args[0] == "005930"
        assert args[1] == "1m"
        assert len(args[2]) == n
        # flush_all 반환 == valid append rows 수(N)만 (drop invalid 미포함)
        assert total == n
        # invalid 전부 drop (pop 됨)
        assert c.buffer == {}
        assert "flush guard: drop malformed buffered key" in caplog.text
        assert "flush guard: drop non-str buffered key" in caplog.text
        assert "flush guard: drop invalid buffered key" in caplog.text

    def test_stop_via_flush_all_no_raise_on_malformed(self):
        c = _make_collector()
        c.buffer["badkey"] = [_row()]
        c.buffer[("x",)] = [_row()]  # type: ignore[index]
        # stop() → flush_all() 경유, raise 없이 완주
        c.stop()
        assert c.buffer == {}
        c._store.append.assert_not_called()

    def test_flush_returns_append_success_count(self):
        c = _make_collector()
        c.buffer["005930:5m"] = [_row(0), _row(1), _row(2)]
        result = c._flush("005930:5m")
        assert result == 3
        c._store.append.assert_called_once()

    def test_flush_empty_key_returns_zero(self):
        c = _make_collector()
        assert c._flush("005930:1m") == 0
        assert c._flush("nonexistent:1m") == 0

    def test_flush_invalid_key_drop_returns_zero_no_retry(self, caplog):
        c = _make_collector()
        c.buffer["005930:1d"] = [_row()]  # write-ownership 위반
        with caplog.at_level(logging.WARNING):
            result = c._flush("005930:1d")
        assert result == 0
        c._store.append.assert_not_called()
        # invalid drop: pop 되어 사라짐 (retry 안 함)
        assert "005930:1d" not in c.buffer
        assert "flush guard: drop invalid buffered key" in caplog.text


# ── append-failure retry 보존 (R4-F1) ────────────────────


class TestAppendFailureRetryPreserved:
    def test_append_exception_rebuffers_rows_for_retry(self, caplog):
        c = _make_collector()
        rows = [_row(0), _row(1)]
        c.buffer["005930:1m"] = list(rows)
        c._store.append.side_effect = RuntimeError("transient store error")

        with caplog.at_level(logging.ERROR):
            total = c.flush_all()

        # 이번 회차 append 0
        assert total == 0
        # rows 미유실 — 같은 key 에 재버퍼링 (다음 flush 재시도 가능)
        assert c.buffer["005930:1m"] == rows
        assert "Failed to flush data" in caplog.text

    def test_append_exception_preserves_rebuffer_order(self):
        c = _make_collector()
        first = [_row(0)]
        c.buffer["005930:1m"] = list(first)
        c._store.append.side_effect = RuntimeError("boom")
        c.flush_all()
        # append 실패 후 pending 에 새 row 추가됨
        c.add_data("005930", "1m", _row(5))
        c._store.append.side_effect = RuntimeError("boom2")
        c.flush_all()
        # 기존 rows + existing 순서 보존 (rows + self._buffer[key])
        assert c.buffer["005930:1m"] == [_row(0), _row(5)]

    def test_invalid_drop_vs_append_fail_distinguished(self, caplog):
        """invalid-drop(pop·gone, retry 안 함) vs append-fail(retry 보존)."""
        c = _make_collector()
        # invalid: append-fail side_effect 와 무관하게 drop 되어야 함
        c.buffer["005930:1d"] = [_row()]
        # valid: append-fail 시 retry 보존
        valid_rows = [_row(0), _row(1)]
        c.buffer["005930:1m"] = list(valid_rows)
        c._store.append.side_effect = RuntimeError("transient")

        with caplog.at_level(logging.WARNING):
            total = c.flush_all()

        assert total == 0
        # invalid: pop·gone (retry 안 함)
        assert "005930:1d" not in c.buffer
        # valid append-fail: rows 재버퍼링 (retry 보존)
        assert c.buffer["005930:1m"] == valid_rows
        # invalid 는 append 호출 자체가 없음 (1m 만 호출 시도됨)
        for call in c._store.append.call_args_list:
            assert call.args[1] != "1d"


# ── 프로덕션 구성 경로 회귀 (main.py 초기화 → event-driven add_data) ──


class TestProductionConfigPathRegression:
    def test_main_py_style_init_and_event_driven_add_data(self):
        """main.py:978 스타일 구성(exchange 기본 KRX) + 이벤트 기반 add_data.

        프로덕션은 KRX 6자리 종목·canonical timeframe 이벤트를 직접
        `add_data` 로 흘린다. 본 경로가 기존대로 버퍼링·flush 되는지 +
        out-of-vocab 이벤트가 거부되는지 회귀.
        """
        store = MagicMock()
        eventbus = AsyncMock()
        # main.py:978 구성 형태 (기본 exchange="KRX")
        collector = DataCollector(
            store=store,
            eventbus=eventbus,
            buffer_size=2,
        )

        # event-driven 정상 시세 이벤트 (KRX 6자리 + canonical tf)
        collector.add_data("005930", "1m", _row(0))
        collector.add_data("005930", "1m", _row(1))  # buffer full → flush
        store.append.assert_called_once()
        assert store.append.call_args.args[0] == "005930"
        assert store.append.call_args.args[1] == "1m"

        # out-of-vocab 이벤트는 거부 (경로 미생성)
        store.append.reset_mock()
        collector.add_data("00593", "1m", _row(2))  # 5자리
        collector.add_data("005930", "1d", _row(3))  # write-ownership
        collector.flush_all()
        store.append.assert_not_called()
