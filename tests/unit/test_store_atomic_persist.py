"""파티션 persist 원자성 + 0바이트 손상 파티션 자동복구 계약 테스트(#2413).

배경: `ParquetStore._persist_partition` 이 임시파일+rename 없이 최종 경로에
직접 `write_parquet` 했기 때문에, write 도중 중단(OOM/kill/전원)이 있으면
0바이트/부분 parquet이 남았다. 이후 어떤 실행도 이 0바이트 파티션을 읽으려다
실패해 `store_merge`(=checkpoint 전진 게이트) 경고만 남기고 skip → 해당
(심볼×월) 파티션이 영구히 반영 불가(loud-stuck) 상태가 됐다.

수정(#2413, Option B — 0바이트-only 자동복구):
  - `_atomic_write_parquet`: mkstemp → write → mode 조정 → `Path.replace` 원자
    교체(checkpoint.save 미러). 중단 시 최종 경로에 부분 parquet이 남지 않는다.
  - **0바이트** 기존 파티션(중단 write 잔재)은 부재로 간주하고 신규 group으로
    **자동복구**한다(`store_recovered`, 비게이트 → checkpoint 전진 → stuck 해소).
  - **비어있지 않은** 기존 파티션의 read/concat 실패(읽기 불가·non-coercible
    스키마)는 **기존 보존 + `store_merge`(게이트→재시도)**로 처리한다(loud-stuck →
    `ante data validate --fix` + 재backfill로 사용자 복구). 자동 격리/self-heal 없음.

`store_recovered`는 checkpoint 전진 게이트(`type=="store_merge"` 필터)를
by-construction 유발하지 않으므로, 0바이트 자동복구 후 checkpoint가 전진한다.
"""

from __future__ import annotations

import os
from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl
import pytest

from ante.data.store import ParquetStore


def _ohlcv_df(symbol: str, days: list[int], year: int = 2025, month: int = 11):
    """주어진 일(day)들로 1d OHLCV DataFrame을 만든다(파티션은 월별)."""
    ts = [datetime(year, month, d, tzinfo=UTC) for d in days]
    n = len(ts)
    return pl.DataFrame(
        {
            "timestamp": pl.Series(ts, dtype=pl.Datetime(time_unit="us")),
            "symbol": [symbol] * n,
            "open": [50000.0] * n,
            "high": [50100.0] * n,
            "low": [49900.0] * n,
            "close": [50050.0] * n,
            "volume": [1000] * n,
            "source": ["test"] * n,
        }
    )


# ── (A) 0바이트 자동복구: 부재로 간주 + 신규 write + store_recovered(비게이트) ──


def test_zero_byte_partition_auto_recovers(tmp_path) -> None:
    """0바이트 파티션 위 write → 데이터 채움 + store_recovered + store_merge 없음.

    현행(수정 전): 0바이트 read 실패를 store_merge로 skip → 데이터 미반영, 영구
    stuck. 0바이트 자동복구 계약을 잠근다.
    """
    store = ParquetStore(base_path=tmp_path)
    part_dir = tmp_path / "ohlcv" / "1d" / "KRX" / "005930"
    part_dir.mkdir(parents=True)
    zero = part_dir / "2025-11.parquet"
    zero.write_bytes(b"")  # 중단 비원자 write가 남긴 0바이트 잔재

    df = _ohlcv_df("005930", [3, 4], month=11)
    net = store.write("005930", "1d", df, data_type="ohlcv")

    # 데이터가 신규 group으로 채워진다(신규-파티션 경로와 동일 net-new).
    assert net == 2
    healed = pl.read_parquet(zero)
    assert len(healed) == 2
    read_back = store.read("005930", "1d", data_type="ohlcv")
    assert len(read_back) == 2

    # store_recovered(비게이트) 존재, store_merge 없음. 격리(.corrupted) 없음.
    warnings = store.drain_warnings()
    assert any(w.get("type") == "store_recovered" for w in warnings)
    assert all(w.get("type") != "store_merge" for w in warnings)
    assert not zero.with_suffix(".corrupted").exists()
    recovered = next(w for w in warnings if w.get("type") == "store_recovered")
    assert "2025-11.parquet" in recovered["path"]
    # known-limitation(forward-only 공백 가능성)을 경고 메시지로 표면화한다.
    assert "유실" in recovered["message"] or "공백" in recovered["message"]


def test_zero_byte_recovery_does_not_gate_checkpoint(tmp_path) -> None:
    """0바이트 자동복구는 store_merge 게이트를 유발하지 않는다(전진 허용)."""
    store = ParquetStore(base_path=tmp_path)
    part_dir = tmp_path / "ohlcv" / "1d" / "KRX" / "005930"
    part_dir.mkdir(parents=True)
    (part_dir / "2025-11.parquet").write_bytes(b"")

    store.write("005930", "1d", _ohlcv_df("005930", [3], month=11), data_type="ohlcv")

    # checkpoint 전진 게이트 소비자(pending_merge_failure_count)는 store_merge만
    # 센다 → 0바이트 복구(store_recovered)는 0 = 전진 허용.
    assert store.pending_merge_failure_count() == 0


def test_zero_byte_recovery_uses_0644_not_stub_mode(tmp_path) -> None:
    """0바이트 복구본은 신규와 동일한 0o644 — pre-#2413 stub mode 보존 금지([670]).

    restrictive umask(0o077)에서 만들어진 stub은 owner-only(0o600)일 수 있다. 복구가
    stub mode를 보존하면 복구본도 owner-only가 되어 분리 reader가 EACCES. stub mode를
    mode 소스로 쓰지 않고 0o644를 강제함을 잠근다(CI umask와 무관하게 결정적).
    """
    store = ParquetStore(base_path=tmp_path)
    part_dir = tmp_path / "ohlcv" / "1d" / "KRX" / "005930"
    part_dir.mkdir(parents=True)
    stub = part_dir / "2025-11.parquet"
    stub.write_bytes(b"")
    os.chmod(stub, 0o600)  # restrictive umask stub 모사(owner-only)

    store.write("005930", "1d", _ohlcv_df("005930", [3], month=11))

    mode = stub.stat().st_mode & 0o777
    assert mode == 0o644, f"복구본이 stub mode 보존: {oct(mode)} (0o644이어야 함)"


def test_zero_byte_recovery_warning_only_after_write_success(
    tmp_path, monkeypatch
) -> None:
    """0바이트 복구 write가 raise하면 store_recovered 경고를 적재하지 않는다([828]).

    경고를 write 전에 적재하면 write가 ENOSPC/EACCES/kill로 실패해도 "자동복구됨"
    허위 성공 신호가 버퍼에 남는다. 경고는 write 성공 직후에만 적재해야 한다.
    """
    store = ParquetStore(base_path=tmp_path)
    part_dir = tmp_path / "ohlcv" / "1d" / "KRX" / "005930"
    part_dir.mkdir(parents=True)
    zero = part_dir / "2025-11.parquet"
    zero.write_bytes(b"")

    real_write = pl.DataFrame.write_parquet

    def _raise_write(self, file, *args, **kwargs):
        raise RuntimeError("disk full (ENOSPC) during recovery write")

    monkeypatch.setattr(pl.DataFrame, "write_parquet", _raise_write)

    with pytest.raises(RuntimeError, match="disk full"):
        store.write("005930", "1d", _ohlcv_df("005930", [3], month=11))

    monkeypatch.setattr(pl.DataFrame, "write_parquet", real_write)

    # write 실패 → 허위 store_recovered가 버퍼에 없어야 한다.
    assert store.drain_warnings() == []
    assert store.pending_merge_failure_count() == 0
    # 파일은 여전히 0바이트(복구 안 됨) + tmp 잔재 없음.
    assert zero.stat().st_size == 0
    assert list(part_dir.glob("*.tmp")) == []


# ── (B) 비-0바이트 unreadable → preserve + store_merge(loud-stuck, 자동복구 없음) ─


def test_nonempty_unreadable_partition_preserved_and_gates(tmp_path) -> None:
    """비어있지 않은 손상 파티션 → 기존 보존 + store_merge + net 0 + 격리 없음.

    0바이트가 아닌 unreadable 파티션은 자동복구하지 않고(loud-stuck) 기존 파일을
    보존한다(pre-#2413 보존 동작). 복구는 사용자가 `ante data validate --fix` +
    재backfill로 수행한다.
    """
    store = ParquetStore(base_path=tmp_path)
    part_dir = tmp_path / "ohlcv" / "1d" / "KRX" / "005930"
    part_dir.mkdir(parents=True)
    corrupt = part_dir / "2025-11.parquet"
    corrupt.write_bytes(b"corrupt-not-parquet")  # 비어있지 않은 손상(읽기 불가)

    net = store.write("005930", "1d", _ohlcv_df("005930", [3], month=11))

    assert net == 0  # 저장 반영 없음(기존 파일 보존)
    # 손상 파일은 그대로 보존(자동 격리·복구 없음).
    assert corrupt.read_bytes() == b"corrupt-not-parquet"
    assert not corrupt.with_suffix(".corrupted").exists()
    warnings = store.drain_warnings()
    assert any(w.get("type") == "store_merge" for w in warnings)
    assert all(w.get("type") != "store_recovered" for w in warnings)


def test_nonempty_unreadable_partition_gates_checkpoint(tmp_path) -> None:
    """비-0바이트 손상 → store_merge 게이트(checkpoint 미전진, 다음 run 재시도)."""
    store = ParquetStore(base_path=tmp_path)
    part_dir = tmp_path / "ohlcv" / "1d" / "KRX" / "005930"
    part_dir.mkdir(parents=True)
    (part_dir / "2025-11.parquet").write_bytes(b"corrupt-not-parquet")

    store.write("005930", "1d", _ohlcv_df("005930", [3], month=11))
    assert store.pending_merge_failure_count() == 1


# ── (C) genuine merge-fail(read 성공 후 concat 실패) → 보존 + store_merge ─────


def _noncoercible_partition(store: ParquetStore, symbol: str) -> Path:
    """공유키 컬럼이 List 타입인 **유효**(읽기 가능) fundamental 파티션을 배치한다.

    다음 write(scalar 공유키)와 `pl.concat(how="diagonal_relaxed")` 하면
    List↔scalar supertype 결정 실패로 SchemaError가 raise된다 → read는 성공하나
    concat이 실패하는 genuine merge-fail(=store_merge 경로)을 결정적으로 재현한다.
    """
    part_dir = store.base_path / "fundamental" / "KRX" / symbol
    part_dir.mkdir(parents=True, exist_ok=True)
    filepath = part_dir / "2025-11.parquet"
    pl.DataFrame(
        {
            "date": [date(2025, 11, 10)],
            "symbol": [symbol],
            "market_cap": [[1, 2, 3]],  # List → scalar와 non-coercible
            "source": ["data_go_kr"],
        }
    ).write_parquet(str(filepath))
    return filepath


def test_genuine_merge_fail_preserves_and_warns_store_merge(tmp_path) -> None:
    """read 성공 후 concat 실패 → 기존 보존 + store_merge + net 0 + 격리 없음."""
    store = ParquetStore(base_path=tmp_path)
    filepath = _noncoercible_partition(store, "005930")
    before = filepath.read_bytes()

    new = pl.DataFrame(
        {
            "date": [date(2025, 11, 15)],
            "symbol": ["005930"],
            "market_cap": [200],  # scalar
            "source": ["data_go_kr"],
        }
    )
    net = store.write("005930", "krx", new, data_type="fundamental")

    assert net == 0
    warnings = store.drain_warnings()
    assert any(w.get("type") == "store_merge" for w in warnings)
    assert all(w.get("type") != "store_recovered" for w in warnings)
    assert filepath.read_bytes() == before  # 유효 파티션 무손상
    assert not filepath.with_suffix(".corrupted").exists()


def test_genuine_merge_fail_gates_checkpoint(tmp_path) -> None:
    """genuine merge-fail은 store_merge 게이트를 유발한다(checkpoint 미전진)."""
    store = ParquetStore(base_path=tmp_path)
    _noncoercible_partition(store, "005930")
    new = pl.DataFrame(
        {
            "date": [date(2025, 11, 15)],
            "symbol": ["005930"],
            "market_cap": [200],
            "source": ["data_go_kr"],
        }
    )
    store.write("005930", "krx", new, data_type="fundamental")
    assert store.pending_merge_failure_count() == 1


# ── (D) 원자성: write 중단 → 최종 파티션에 부분/0바이트 파일이 남지 않음 ────────


def test_atomic_write_no_partial_on_interrupt(tmp_path, monkeypatch) -> None:
    """write_parquet 중단(부분 바이트 후 raise) → 최종 파티션 미생성 + tmp 잔재 없음.

    현행(수정 전): 최종 경로에 직접 write → 부분 바이트가 최종 파일로 남는다.
    수정 후: tmp에 write 후 replace → 실패 시 tmp cleanup, 최종 경로는 무손상.
    """
    store = ParquetStore(base_path=tmp_path)
    df = _ohlcv_df("000660", [3, 4], month=11)

    real_write = pl.DataFrame.write_parquet

    def _partial_then_raise(self, file, *args, **kwargs):
        Path(file).write_bytes(b"partial-parquet-bytes")
        raise RuntimeError("simulated interruption mid-write")

    monkeypatch.setattr(pl.DataFrame, "write_parquet", _partial_then_raise)

    with pytest.raises(RuntimeError, match="simulated interruption"):
        store.write("000660", "1d", df, data_type="ohlcv")

    monkeypatch.setattr(pl.DataFrame, "write_parquet", real_write)

    part_dir = tmp_path / "ohlcv" / "1d" / "KRX" / "000660"
    filepath = part_dir / "2025-11.parquet"
    assert not filepath.exists()  # 부분/0바이트 파일이 남지 않는다
    if part_dir.exists():
        assert list(part_dir.glob("*.tmp")) == []  # tmp 잔재 없음(cleanup)


def test_atomic_write_preserves_existing_on_interrupt(tmp_path, monkeypatch) -> None:
    """merge write 중단 → 기존 유효 파티션 무손상 보존 + store_merge + net 0."""
    store = ParquetStore(base_path=tmp_path)
    store.write("000660", "1d", _ohlcv_df("000660", [3], month=11), data_type="ohlcv")
    part_dir = tmp_path / "ohlcv" / "1d" / "KRX" / "000660"
    filepath = part_dir / "2025-11.parquet"
    before = filepath.read_bytes()

    real_write = pl.DataFrame.write_parquet

    def _partial_then_raise(self, file, *args, **kwargs):
        Path(file).write_bytes(b"partial-parquet-bytes")
        raise RuntimeError("simulated interruption mid-merge-write")

    monkeypatch.setattr(pl.DataFrame, "write_parquet", _partial_then_raise)

    # merge write가 중단돼도 예외를 삼켜 store_merge로 처리(기존 원자성 보존).
    net = store.write(
        "000660", "1d", _ohlcv_df("000660", [4], month=11), data_type="ohlcv"
    )

    monkeypatch.setattr(pl.DataFrame, "write_parquet", real_write)

    assert filepath.read_bytes() == before  # 기존 파일 바이트 불변
    assert list(part_dir.glob("*.tmp")) == []
    assert net == 0
    assert any(w.get("type") == "store_merge" for w in store.drain_warnings())


# ── (E) 파티션 파일 권한: 신규 0o644 고정 + 기존 operator mode 보존 ──────────────


def test_new_partition_mode_is_0644(tmp_path) -> None:
    """신규 파티션 mode == 0o644(owner-only 금지, mkstemp 0o600 폐기)."""
    store = ParquetStore(base_path=tmp_path)
    part_dir = tmp_path / "ohlcv" / "1d" / "KRX" / "005930"
    store.write("005930", "1d", _ohlcv_df("005930", [3], month=11))
    mode = (part_dir / "2025-11.parquet").stat().st_mode & 0o777
    assert mode == 0o644, f"신규 파티션 mode={oct(mode)} != 0o644"


def test_merge_preserves_existing_operator_mode(tmp_path) -> None:
    """기존 target이 있으면 그 operator mode를 보존한다(0o600 등).

    매 merge write가 기존 파티션 mode를 0o644로 폐기하지 않도록 잠근다.
    """
    store = ParquetStore(base_path=tmp_path)
    part_dir = tmp_path / "ohlcv" / "1d" / "KRX" / "005930"

    store.write("005930", "1d", _ohlcv_df("005930", [3], month=11))
    filepath = part_dir / "2025-11.parquet"
    os.chmod(filepath, 0o600)  # operator가 잠근 상태 모사

    store.write("005930", "1d", _ohlcv_df("005930", [4], month=11))
    mode = filepath.stat().st_mode & 0o777
    assert mode == 0o600, f"merge가 operator mode 폐기: {oct(mode)}"


# ── (F) 정상 경로 무회귀: 신규/merge write 는 원자적이며 net-new 정확 ───────────


def test_normal_paths_remain_atomic_and_correct(tmp_path) -> None:
    """신규 파티션·merge 정상 경로가 원자 write로도 net-new/데이터를 정확히 유지한다."""
    store = ParquetStore(base_path=tmp_path)
    part_dir = tmp_path / "ohlcv" / "1d" / "KRX" / "005930"

    net1 = store.write(
        "005930", "1d", _ohlcv_df("005930", [3, 4], month=11), data_type="ohlcv"
    )
    assert net1 == 2
    assert (part_dir / "2025-11.parquet").exists()
    assert list(part_dir.glob("*.tmp")) == []

    net2 = store.write(
        "005930", "1d", _ohlcv_df("005930", [5], month=11), data_type="ohlcv"
    )
    assert net2 == 1
    assert len(pl.read_parquet(part_dir / "2025-11.parquet")) == 3
    assert list(part_dir.glob("*.tmp")) == []

    net3 = store.write(
        "005930", "1d", _ohlcv_df("005930", [5], month=11), data_type="ohlcv"
    )
    assert net3 == 0
    assert list(part_dir.glob("*.tmp")) == []


# ── (G) orphan .tmp 회수는 validate(fix=True)에서만(read-scoped fs 무변조) ──────


def test_validate_fix_sweeps_orphan_tmp(tmp_path) -> None:
    """validate(fix=True)는 orphan *.tmp를 회수하고 stale_tmp_removed로 리포트한다."""
    store = ParquetStore(base_path=tmp_path)
    store.write("005930", "1d", _ohlcv_df("005930", [3], month=11))
    part_dir = tmp_path / "ohlcv" / "1d" / "KRX" / "005930"
    (part_dir / "tmpAAA.tmp").write_bytes(b"x")
    (part_dir / "tmpBBB.tmp").write_bytes(b"y")

    result = store.validate("005930", "1d", fix=True)

    assert result["stale_tmp_removed"] == 2
    assert list(part_dir.glob("*.tmp")) == []
    assert result["valid"] == 1  # 정상 파티션은 그대로


def test_validate_no_fix_does_not_touch_tmp(tmp_path) -> None:
    """validate(fix=False)는 read-scoped라 orphan *.tmp를 삭제하지 않는다."""
    store = ParquetStore(base_path=tmp_path)
    store.write("005930", "1d", _ohlcv_df("005930", [3], month=11))
    part_dir = tmp_path / "ohlcv" / "1d" / "KRX" / "005930"
    (part_dir / "tmpAAA.tmp").write_bytes(b"x")

    result = store.validate("005930", "1d")  # fix=False(기본)

    assert result["stale_tmp_removed"] == 0
    assert (part_dir / "tmpAAA.tmp").exists()  # fs 무변조
