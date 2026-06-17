"""Refs #1160 — startup booting marker ordering tests."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from ante.config import Config


def test_starting_marker_path_derives_from_runtime_pid_dir(tmp_path: Path) -> None:
    """Marker는 canonical runtime PID directory에서 파생된다."""
    from ante.main import _starting_marker_path

    config = Config.load(config_dir=tmp_path)

    assert _starting_marker_path(config) == tmp_path / "run" / ".starting"


def test_write_starting_marker_creates_file_with_current_pid(
    tmp_path: Path,
) -> None:
    """Marker write는 현재 PID를 기록한다."""
    from ante.main import (
        _read_starting_marker_pid,
        _remove_starting_marker,
        _starting_marker_path,
        _write_starting_marker,
    )

    config = Config.load(config_dir=tmp_path)
    try:
        _write_starting_marker(config)

        assert _starting_marker_path(config).exists()
        assert _read_starting_marker_pid(config) == os.getpid()
    finally:
        _remove_starting_marker(config)


def test_remove_starting_marker_unlinks_file(tmp_path: Path) -> None:
    """Marker remove는 기존 marker를 제거한다."""
    from ante.main import (
        _remove_starting_marker,
        _starting_marker_path,
        _write_starting_marker,
    )

    config = Config.load(config_dir=tmp_path)
    _write_starting_marker(config)

    _remove_starting_marker(config)

    assert not _starting_marker_path(config).exists()


def test_remove_starting_marker_safe_when_missing(tmp_path: Path) -> None:
    """Marker가 없어도 cleanup은 예외를 내지 않는다."""
    from ante.main import _remove_starting_marker, _starting_marker_path

    config = Config.load(config_dir=tmp_path)

    _remove_starting_marker(config)

    assert not _starting_marker_path(config).exists()


def test_read_starting_marker_pid_returns_none_when_absent_or_corrupt(
    tmp_path: Path,
) -> None:
    """Marker 부재/손상은 stale marker로 해석된다."""
    from ante.main import _read_starting_marker_pid, _starting_marker_path

    config = Config.load(config_dir=tmp_path)
    marker = _starting_marker_path(config)

    assert _read_starting_marker_pid(config) is None

    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("not-a-pid")

    assert _read_starting_marker_pid(config) is None


@pytest.mark.asyncio
async def test_main_writes_marker_before_pid_and_removes_after_init_ipc(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """main()은 marker → PID → IPC ready → marker 제거 순서를 보존한다."""
    import ante.db.migrations as migrations
    import ante.main as main_module
    import ante.update.checker as update_checker

    monkeypatch.setenv("ANTE_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(
        main_module,
        "_LEGACY_PID_FALLBACK",
        tmp_path / "legacy" / "ante.pid",
    )

    calls: list[str] = []

    original_write_marker = main_module._write_starting_marker
    original_write_pid = main_module._write_pid_file
    original_remove_marker = main_module._remove_starting_marker

    def tracked_write_marker(config: Config) -> None:
        calls.append("write_marker")
        original_write_marker(config)

    def tracked_write_pid(config: Config) -> None:
        calls.append("write_pid")
        original_write_pid(config)

    def tracked_remove_marker(config: Config) -> None:
        calls.append("remove_marker")
        original_remove_marker(config)

    monkeypatch.setattr(main_module, "_write_starting_marker", tracked_write_marker)
    monkeypatch.setattr(main_module, "_write_pid_file", tracked_write_pid)
    monkeypatch.setattr(main_module, "_remove_starting_marker", tracked_remove_marker)

    async def fake_check_update_on_startup() -> None:
        return None

    async def fake_run_migrations(db: object, data_path: Path) -> list[str]:
        return []

    monkeypatch.setattr(
        update_checker, "check_update_on_startup", fake_check_update_on_startup
    )
    monkeypatch.setattr(migrations, "run_migrations", fake_run_migrations)

    async def fake_init_core(s: main_module.Services) -> None:
        calls.append("init_core")
        s.db = object()

    async def fake_init_ipc(s: main_module.Services) -> None:
        assert s.config is not None
        calls.append("init_ipc")
        assert main_module._read_starting_marker_pid(s.config) == os.getpid()
        assert s.config.runtime_pid_path().exists()
        s.config.runtime_socket_path().parent.mkdir(parents=True, exist_ok=True)
        s.config.runtime_socket_path().touch()

    async def fake_run(s: main_module.Services) -> None:
        assert s.config is not None
        calls.append("run")
        assert not main_module._starting_marker_path(s.config).exists()
        assert s.config.runtime_pid_path().exists()

    async def fake_init_step(s: main_module.Services) -> None:
        return None

    for name in (
        "_init_services",
        "_init_account",
        "_init_trading",
        "_init_gateway",
        "_init_feed",
        "_init_approval",
        "_init_notification",
    ):
        monkeypatch.setattr(main_module, name, fake_init_step)
    monkeypatch.setattr(main_module, "_init_core", fake_init_core)
    monkeypatch.setattr(main_module, "_init_ipc", fake_init_ipc)
    monkeypatch.setattr(main_module, "_run", fake_run)

    await main_module.main()

    config = Config.load(config_dir=tmp_path)
    assert not main_module._starting_marker_path(config).exists()
    assert not config.runtime_pid_path().exists()
    assert calls[:4] == ["write_marker", "write_pid", "init_core", "init_ipc"]
    assert calls[calls.index("init_ipc") + 1] == "remove_marker"
    assert calls[-1] == "remove_marker"


@pytest.mark.asyncio
async def test_main_removes_marker_on_init_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """초기화 실패 시에도 marker와 PID를 cleanup한다."""
    import ante.main as main_module

    monkeypatch.setenv("ANTE_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(
        main_module,
        "_LEGACY_PID_FALLBACK",
        tmp_path / "legacy" / "ante.pid",
    )

    async def failing_init_core(s: Any) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(main_module, "_init_core", failing_init_core)

    with pytest.raises(RuntimeError, match="boom"):
        await main_module.main()

    config = Config.load(config_dir=tmp_path)
    assert not main_module._starting_marker_path(config).exists()
    assert not config.runtime_pid_path().exists()


# ── #2385: _sync_instruments 전 계좌 unique exchange 동기화 ────────────────


def _make_sync_account(
    account_id: str,
    exchange: str,
    *,
    broker_type: str = "kis-domestic",
    trading_mode: Any = None,
) -> Any:
    """``account_id``/``exchange``/(broker_type, trading_mode) 를 갖는 Account 더블.

    #2397 R1: ``_sync_instruments`` 는 non-exempt(LIVE) connected 계좌만 순회한다.
    디폴트는 ``kis-domestic``/``LIVE``(비면제)로 둬 #2385 멀티-계좌 동기화 invariant
    를 그대로 유지한다. 면제(virtual/test) 회귀는 별도 테스트에서 명시 구성한다.
    """
    from types import SimpleNamespace

    from ante.account.models import TradingMode

    if trading_mode is None:
        trading_mode = TradingMode.LIVE
    return SimpleNamespace(
        account_id=account_id,
        exchange=exchange,
        broker_type=broker_type,
        trading_mode=trading_mode,
    )


def _make_sync_services(broker_instruments: dict[str, Any]) -> tuple[Any, list[Any]]:
    """``_sync_instruments`` 용 Services 더블 + bulk_upsert 호출 기록.

    ``broker_instruments`` 는 account_id → broker.get_instruments() 반환값
    (list[dict] 또는 raise 할 Exception 인스턴스) 매핑이다.

    #2399 attempt3-a: ``_sync_instruments`` 는 startup connect 성공(broker_ready)
    계좌만 순회한다(``_broker_not_ready_live`` 필터). 프로덕션 흐름에서 connect
    루프가 broker_ready 를 마킹한 상태를 반영해, ``broker_instruments`` 의 모든
    account_id 를 기본 broker_ready 로 마킹한다. not_ready skip 회귀를 검증하는
    테스트는 helper 호출 **후** 해당 계좌를 명시 ``mark_not_ready`` 로 덮는다.
    """
    from unittest.mock import AsyncMock

    import ante.main as main_module
    from ante.account.readiness import ReadinessFlag

    s = main_module.Services()
    for account_id in broker_instruments:
        s.runtime_readiness.mark_ready(account_id, ReadinessFlag.BROKER)

    upsert_calls: list[Any] = []

    async def _bulk_upsert(instruments: list[Any]) -> int:
        upsert_calls.append(instruments)
        return len(instruments)

    instrument_service = AsyncMock()
    instrument_service.bulk_upsert = AsyncMock(side_effect=_bulk_upsert)
    s.instrument_service = instrument_service  # type: ignore[assignment]

    async def _get_broker(account_id: str) -> Any:
        result = broker_instruments[account_id]
        broker = AsyncMock()

        async def _get_instruments() -> Any:
            if isinstance(result, Exception):
                raise result
            return result

        broker.get_instruments = AsyncMock(side_effect=_get_instruments)
        return broker

    account_service = AsyncMock()
    account_service.get_broker = AsyncMock(side_effect=_get_broker)
    s.account_service = account_service  # type: ignore[assignment]

    return s, upsert_calls


@pytest.mark.asyncio
async def test_sync_instruments_does_not_stop_at_first_broker() -> None:
    """(a) LIVE 2계좌(다른 exchange) 순서에서 둘째 exchange 도 적재된다.

    과거 첫 성공 broker `return` 구조에서는 첫 broker 가 둘째 exchange 마스터
    적재를 선점했다(#2385 회귀). 첫 broker return 제거를 잠근다. (#2397 R1 이후
    면제 계좌는 순회 대상에서 빠지므로 비면제 LIVE 2계좌로 invariant 를 유지한다.)
    """
    import ante.main as main_module

    accounts = [
        _make_sync_account("kospi", "KOSPI"),
        _make_sync_account("oracle-paper", "KRX"),
    ]
    s, upsert_calls = _make_sync_services(
        {
            "kospi": [{"symbol": "000001", "name": "알파전자"}],
            "oracle-paper": [{"symbol": "069500", "name": "KODEX 200"}],
        }
    )

    await main_module._sync_instruments(s, accounts)

    # 두 exchange 모두 동기화되어야 한다 (첫 broker return 제거).
    assert len(upsert_calls) == 2
    upserted = {inst.symbol: inst for batch in upsert_calls for inst in batch}
    assert "069500" in upserted, "KRX 069500 마스터가 적재되어야 한다"
    krx = upserted["069500"]
    assert krx.exchange == "KRX"
    assert krx.name == "KODEX 200"


@pytest.mark.asyncio
async def test_sync_instruments_skips_exempt_accounts() -> None:
    """#2397 R1: 면제(virtual/test) 계좌는 get_broker 미호출·순회 제외.

    면제 계좌의 dummy exchange 가 실 exchange 마스터 적재를 선점하던 #2385
    회귀를 broker_ready 면제로 차단한다(KIS 재노출 방지와 동일 메커니즘).
    """
    import ante.main as main_module
    from ante.account.models import TradingMode

    accounts = [
        # 면제: test/virtual → 순회 제외(get_broker 미호출).
        _make_sync_account(
            "test", "TEST", broker_type="test", trading_mode=TradingMode.VIRTUAL
        ),
        # 면제: kis-domestic/virtual → 순회 제외.
        _make_sync_account(
            "kis-virtual",
            "KRX",
            broker_type="kis-domestic",
            trading_mode=TradingMode.VIRTUAL,
        ),
        # 비면제: kis-domestic/live → 순회 대상.
        _make_sync_account("kis-live", "KRX", trading_mode=TradingMode.LIVE),
    ]
    s, upsert_calls = _make_sync_services(
        {
            "test": [{"symbol": "000001", "name": "더미"}],
            "kis-virtual": [{"symbol": "111111", "name": "가상"}],
            "kis-live": [{"symbol": "069500", "name": "KODEX 200"}],
        }
    )

    await main_module._sync_instruments(s, accounts)

    # 면제 계좌의 broker 는 조회조차 되지 않아야 한다(KIS 재노출 차단).
    s.account_service.get_broker.assert_awaited_once_with("kis-live")
    # LIVE 계좌의 실 마스터만 적재.
    assert len(upsert_calls) == 1
    upserted = {inst.symbol for batch in upsert_calls for inst in batch}
    assert upserted == {"069500"}


@pytest.mark.asyncio
async def test_sync_instruments_skips_broker_not_ready_live() -> None:
    """#2399 attempt3-a: startup broker not_ready LIVE 계좌는 get_broker 미호출.

    not_ready LIVE 계좌가 있어도 instrument sync 가 그 계좌에 토큰을 재타격하지
    않는다(EGW00133 1/min). ready LIVE 계좌만 동기화되고, not_ready 계좌의
    get_broker 는 조회조차 되지 않는다(필터). per-account try/except 와 무관하게
    전체 sync 가 깨지지 않는다.
    """
    import ante.main as main_module
    from ante.account.readiness import ReadinessFlag

    accounts = [
        _make_sync_account("kis-down", "KOSPI"),  # broker not_ready LIVE → skip.
        _make_sync_account("kis-ok", "KRX"),  # broker ready LIVE → 동기화.
    ]
    s, upsert_calls = _make_sync_services(
        {
            "kis-down": [{"symbol": "000001", "name": "내려간계좌"}],
            "kis-ok": [{"symbol": "069500", "name": "KODEX 200"}],
        }
    )
    # helper 가 둘 다 broker_ready 로 마킹했으므로 kis-down 만 not_ready 로 덮는다.
    s.runtime_readiness.mark_not_ready("kis-down", ReadinessFlag.BROKER, "EGW00133")

    await main_module._sync_instruments(s, accounts)

    # not_ready 계좌는 get_broker 미호출, ready 계좌만 1회 조회.
    s.account_service.get_broker.assert_awaited_once_with("kis-ok")
    assert len(upsert_calls) == 1
    upserted = {inst.symbol for batch in upsert_calls for inst in batch}
    assert upserted == {"069500"}


@pytest.mark.asyncio
async def test_sync_instruments_dedupes_same_exchange() -> None:
    """(b) 동일 exchange 2계좌 → 해당 exchange 는 1회만 sync."""
    import ante.main as main_module

    accounts = [
        _make_sync_account("kis-1", "KRX"),
        _make_sync_account("kis-2", "KRX"),
    ]
    s, upsert_calls = _make_sync_services(
        {
            "kis-1": [{"symbol": "069500", "name": "KODEX 200"}],
            "kis-2": [{"symbol": "102110", "name": "TIGER 200"}],
        }
    )

    await main_module._sync_instruments(s, accounts)

    # 첫 계좌가 KRX 를 동기화했으므로 둘째 계좌는 skip → bulk_upsert 1회.
    assert len(upsert_calls) == 1
    # 둘째 계좌의 broker 는 조회조차 되지 않아야 한다.
    s.account_service.get_broker.assert_awaited_once_with("kis-1")


@pytest.mark.asyncio
async def test_sync_instruments_empty_result_not_marked_synced() -> None:
    """(c) 빈 결과 → synced 처리 금지(같은 exchange 후속 계좌가 여전히 sync)."""
    import ante.main as main_module

    accounts = [
        _make_sync_account("kis-empty", "KRX"),
        _make_sync_account("kis-real", "KRX"),
    ]
    s, upsert_calls = _make_sync_services(
        {
            "kis-empty": [],  # 빈 결과 → continue, synced 처리 금지
            "kis-real": [{"symbol": "069500", "name": "KODEX 200"}],
        }
    )

    await main_module._sync_instruments(s, accounts)

    # 빈 결과는 synced 처리되지 않아 후속 계좌가 KRX 를 동기화해야 한다.
    assert len(upsert_calls) == 1
    upserted = {inst.symbol for batch in upsert_calls for inst in batch}
    assert "069500" in upserted
    # 두 계좌 모두 broker 조회됨 (빈 결과 계좌가 KRX 를 점유하지 않음).
    assert s.account_service.get_broker.await_count == 2


@pytest.mark.asyncio
async def test_sync_instruments_all_fail_keeps_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """(d) 전 계좌 실패 → "종목 동기화 실패 — 기존 캐시 데이터로 운영" 경고 보존."""
    import logging

    import ante.main as main_module

    accounts = [
        _make_sync_account("kis-1", "KRX"),
        _make_sync_account("kis-2", "KOSDAQ"),
    ]
    s, upsert_calls = _make_sync_services(
        {
            "kis-1": RuntimeError("broker down"),
            "kis-2": RuntimeError("broker down"),
        }
    )

    with caplog.at_level(logging.WARNING, logger="ante.main"):
        await main_module._sync_instruments(s, accounts)

    assert len(upsert_calls) == 0
    assert any(
        "종목 동기화 실패 — 기존 캐시 데이터로 운영" in rec.message
        for rec in caplog.records
    ), "전 계좌 실패 시 기존 경고가 보존되어야 한다"
