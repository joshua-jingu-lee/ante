"""파티션 persist 원자성 + 손상 파티션 self-heal 계약 테스트(#2413).

배경: `ParquetStore._persist_partition` 이 임시파일+rename 없이 최종 경로에
직접 `write_parquet` 했기 때문에, write 도중 중단(OOM/kill/전원)이 있으면
0바이트/부분 parquet이 남았다. 이후 어떤 실행도 이 손상 파티션을 읽으려다
실패해 `store_merge`(=checkpoint 전진 게이트) 경고만 남기고 skip → 해당
(심볼×월) 파티션이 영구히 반영 불가(loud-stuck) 상태가 됐다.

수정(#2413):
  - `_atomic_write_parquet`: mkstemp → write → `Path.replace` 원자 교체
    (checkpoint.save 미러). 중단 시 최종 경로에 부분 파일이 남지 않는다.
  - read 실패(손상/0바이트/미완성)와 concat/schema 실패를 **분리**한다:
      * read 실패 → 손상 파일을 `.corrupted`로 격리 + 현재 group으로 fresh
        재생성(self-heal) + `store_recovered` 경고(≠`store_merge` = 비게이트).
      * read 성공 후 concat/schema 실패 → 기존 보존 + `store_merge`(현행).

`store_recovered` 는 checkpoint 전진 게이트(`type=="store_merge"` 필터)를
by-construction 유발하지 않으므로, self-heal 후 checkpoint가 전진해 stuck이
해소된다. 이 파일은 store 계층의 원자성/self-heal/genuine-merge-fail 3축을
잠근다.
"""

from __future__ import annotations

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


# ── (A) self-heal: 읽기 불가 파티션 → 격리 + fresh 재생성 + store_recovered ─────


def test_self_heal_recreates_corrupt_partition(tmp_path) -> None:
    """손상 파티션 위 write → 데이터 채움 + `.corrupted` 격리 + store_recovered.

    현행(수정 전): read 실패를 store_merge로 보존·skip → 데이터 미반영, 격리
    없음. 이 테스트는 self-heal 계약을 잠근다(RED → GREEN).
    """
    store = ParquetStore(base_path=tmp_path)
    part_dir = tmp_path / "ohlcv" / "1d" / "KRX" / "005930"
    part_dir.mkdir(parents=True)
    corrupt = part_dir / "2025-11.parquet"
    # 중단 시 남는 0바이트/부분 parquet을 모사한 읽기 불가 파일.
    corrupt.write_bytes(b"corrupt-not-parquet")

    df = _ohlcv_df("005930", [3, 4], month=11)
    net = store.write("005930", "1d", df, data_type="ohlcv")

    # (a) 데이터가 fresh write로 채워진다(신규 파티션 경로와 동일 net-new).
    assert net == 2
    healed = pl.read_parquet(corrupt)
    assert len(healed) == 2
    read_back = store.read("005930", "1d", data_type="ohlcv")
    assert not read_back.is_empty()
    assert len(read_back) == 2

    # (b) 손상 파일이 `.corrupted`로 격리된다.
    quarantined = corrupt.with_suffix(".corrupted")
    assert quarantined.exists()
    assert quarantined.read_bytes() == b"corrupt-not-parquet"

    # (c) store_recovered 경고 존재, store_merge 는 없음(비게이트).
    warnings = store.drain_warnings()
    assert any(w.get("type") == "store_recovered" for w in warnings)
    assert all(w.get("type") != "store_merge" for w in warnings)
    recovered = next(w for w in warnings if w.get("type") == "store_recovered")
    assert "2025-11.parquet" in recovered["path"]
    # known-limitation(forward-only 침묵 공백 가능성)이 경고 메시지에 표면화된다.
    assert "유실" in recovered["message"] or "공백" in recovered["message"]


def test_self_heal_does_not_gate_checkpoint(tmp_path) -> None:
    """self-heal 이벤트는 store_merge 게이트를 유발하지 않는다(전진 허용)."""
    store = ParquetStore(base_path=tmp_path)
    part_dir = tmp_path / "ohlcv" / "1d" / "KRX" / "005930"
    part_dir.mkdir(parents=True)
    (part_dir / "2025-11.parquet").write_bytes(b"corrupt-not-parquet")

    store.write("005930", "1d", _ohlcv_df("005930", [3], month=11), data_type="ohlcv")

    # checkpoint 전진 게이트 소비자(pending_merge_failure_count)는 store_merge만
    # 센다 → self-heal(store_recovered)은 0 = 전진 허용.
    assert store.pending_merge_failure_count() == 0


def test_self_heal_uniquifies_repeated_corruption(tmp_path) -> None:
    """이미 `.corrupted`가 있으면 덮어쓰지 않고 uniquifier로 증적 보존한다.

    validate(fix)는 `.corrupted`로 덮어쓰지만, self-heal은 반복 손상 시
    이전 격리본을 보존하기 위한 **의도적 divergence**다.
    """
    store = ParquetStore(base_path=tmp_path)
    part_dir = tmp_path / "ohlcv" / "1d" / "KRX" / "005930"
    part_dir.mkdir(parents=True)
    corrupt = part_dir / "2025-11.parquet"

    # 1차 손상 → self-heal → `.corrupted` 생성.
    corrupt.write_bytes(b"corrupt-A")
    store.write("005930", "1d", _ohlcv_df("005930", [3], month=11), data_type="ohlcv")
    store.drain_warnings()
    assert corrupt.with_suffix(".corrupted").read_bytes() == b"corrupt-A"

    # 2차 손상(같은 파티션 다시 깨짐) → self-heal → 기존 격리본 덮어쓰지 않음.
    corrupt.write_bytes(b"corrupt-B")
    store.write("005930", "1d", _ohlcv_df("005930", [4], month=11), data_type="ohlcv")
    store.drain_warnings()

    # 이전 격리본(A)은 그대로, 신규 격리본(B)은 uniquifier 경로에 보존.
    assert corrupt.with_suffix(".corrupted").read_bytes() == b"corrupt-A"
    uniquified = part_dir / "2025-11.corrupted.1"
    assert uniquified.exists()
    assert uniquified.read_bytes() == b"corrupt-B"


# ── (B) 원자성: write 중단 → 최종 파티션에 부분/0바이트 파일이 남지 않음 ────────


def test_atomic_write_no_partial_on_interrupt(tmp_path, monkeypatch) -> None:
    """write_parquet 중단(부분 바이트 후 raise) → 최종 파티션 미생성 + tmp 잔재 없음.

    현행(수정 전): 최종 경로에 직접 write → 부분 바이트가 최종 파일로 남는다(RED).
    수정 후: tmp에 write 후 replace → 실패 시 tmp cleanup, 최종 경로는 무손상.

    단순 즉시-raise는 현행에서도 최종 파일을 만들지 않아 RED가 성립하지 않으므로,
    **대상 경로에 partial bytes를 쓴 뒤 raise**하는 monkeypatch로 재현한다.
    """
    store = ParquetStore(base_path=tmp_path)
    df = _ohlcv_df("000660", [3, 4], month=11)

    real_write = pl.DataFrame.write_parquet

    def _partial_then_raise(self, file, *args, **kwargs):
        # 실제 중단을 모사: 대상(tmp 또는 현행 최종 경로)에 부분 바이트를 남긴 뒤 raise.
        Path(file).write_bytes(b"partial-parquet-bytes")
        raise RuntimeError("simulated interruption mid-write")

    monkeypatch.setattr(pl.DataFrame, "write_parquet", _partial_then_raise)

    with pytest.raises(RuntimeError, match="simulated interruption"):
        store.write("000660", "1d", df, data_type="ohlcv")

    monkeypatch.setattr(pl.DataFrame, "write_parquet", real_write)

    part_dir = tmp_path / "ohlcv" / "1d" / "KRX" / "000660"
    filepath = part_dir / "2025-11.parquet"
    # 최종 파티션 파일은 이전 상태(부재) 유지 — 부분/0바이트 파일이 남지 않는다.
    assert not filepath.exists()
    # tmp 잔재(.tmp)가 남지 않는다(cleanup).
    if part_dir.exists():
        assert list(part_dir.glob("*.tmp")) == []


def test_atomic_write_preserves_existing_on_interrupt(tmp_path, monkeypatch) -> None:
    """merge write 중단 → 기존 유효 파티션이 손상되지 않고 보존된다."""
    store = ParquetStore(base_path=tmp_path)

    # 유효한 기존 파티션 저장(정상 경로).
    store.write("000660", "1d", _ohlcv_df("000660", [3], month=11), data_type="ohlcv")
    part_dir = tmp_path / "ohlcv" / "1d" / "KRX" / "000660"
    filepath = part_dir / "2025-11.parquet"
    before = filepath.read_bytes()

    real_write = pl.DataFrame.write_parquet

    def _partial_then_raise(self, file, *args, **kwargs):
        Path(file).write_bytes(b"partial-parquet-bytes")
        raise RuntimeError("simulated interruption mid-merge-write")

    monkeypatch.setattr(pl.DataFrame, "write_parquet", _partial_then_raise)

    # merge write가 중단돼도 기존 파일은 tmp+replace 원자성으로 무손상.
    net = store.write(
        "000660", "1d", _ohlcv_df("000660", [4], month=11), data_type="ohlcv"
    )

    monkeypatch.setattr(pl.DataFrame, "write_parquet", real_write)

    # 기존 파일 바이트 불변(원자 교체 실패 시 tmp만 버려짐).
    assert filepath.read_bytes() == before
    assert list(part_dir.glob("*.tmp")) == []
    # merge write 실패는 저장 반영 없음 → net 0(기존 보존).
    assert net == 0


# ── (C) genuine merge-fail(read 성공 후 concat 실패) → 보존 + store_merge ─────


def _noncoercible_partition(store: ParquetStore, symbol: str) -> None:
    """공유키 컬럼이 List 타입인 **유효**(읽기 가능) fundamental 파티션을 배치한다.

    다음 write(scalar 공유키)와 `pl.concat(how="diagonal_relaxed")` 하면
    List↔scalar supertype 결정 실패로 SchemaError가 raise된다 → read는 성공하나
    concat이 실패하는 genuine merge-fail(=store_merge 경로)을 결정적으로 재현한다.
    corrupt(읽기 불가) 파일과 달리 self-heal 대상이 아니다.
    """
    part_dir = store.base_path / "fundamental" / "KRX" / symbol
    part_dir.mkdir(parents=True, exist_ok=True)
    df = pl.DataFrame(
        {
            "date": [date(2025, 11, 10)],
            "symbol": [symbol],
            "market_cap": [[1, 2, 3]],  # List → scalar와 non-coercible
            "source": ["data_go_kr"],
        }
    )
    df.write_parquet(str(part_dir / "2025-11.parquet"))


def test_genuine_merge_fail_preserves_and_warns_store_merge(tmp_path) -> None:
    """read 성공 후 concat 실패 → 기존 보존 + store_merge + net 0 + 게이트 유발.

    self-heal 도입이 유효한(읽을 수 있는) 결합-불가 파티션을 파괴하지 않고,
    checkpoint 전진 게이트(store_merge) 회귀를 보존함을 확인한다(#1964/#2028).
    """
    store = ParquetStore(base_path=tmp_path)
    _noncoercible_partition(store, "005930")
    filepath = tmp_path / "fundamental" / "KRX" / "005930" / "2025-11.parquet"
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

    # 저장 반영 없음(기존 보존).
    assert net == 0
    warnings = store.drain_warnings()
    assert any(w.get("type") == "store_merge" for w in warnings)
    assert all(w.get("type") != "store_recovered" for w in warnings)
    # 기존 파일 무손상(읽기 가능 파티션은 self-heal 격리 대상이 아니다).
    assert filepath.read_bytes() == before
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


# ── (D) 정상 경로 무회귀: 신규/merge write 는 원자적이며 net-new 정확 ───────────


def test_normal_paths_remain_atomic_and_correct(tmp_path) -> None:
    """신규 파티션·merge 정상 경로가 원자 write로도 net-new/데이터를 정확히 유지한다."""
    store = ParquetStore(base_path=tmp_path)
    part_dir = tmp_path / "ohlcv" / "1d" / "KRX" / "005930"

    # 신규 파티션.
    net1 = store.write(
        "005930", "1d", _ohlcv_df("005930", [3, 4], month=11), data_type="ohlcv"
    )
    assert net1 == 2
    assert (part_dir / "2025-11.parquet").exists()
    assert list(part_dir.glob("*.tmp")) == []

    # merge(신규 1일 추가).
    net2 = store.write(
        "005930", "1d", _ohlcv_df("005930", [5], month=11), data_type="ohlcv"
    )
    assert net2 == 1
    assert len(pl.read_parquet(part_dir / "2025-11.parquet")) == 3
    assert list(part_dir.glob("*.tmp")) == []

    # 재write(dedup) → net-new 0, tmp 잔재 없음.
    net3 = store.write(
        "005930", "1d", _ohlcv_df("005930", [5], month=11), data_type="ohlcv"
    )
    assert net3 == 0
    assert list(part_dir.glob("*.tmp")) == []
