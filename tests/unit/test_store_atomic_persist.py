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


# ── (E) read 실패 판별: 일시적/환경 오류는 격리 금지(데이터 손실 방지, 리뷰 [0]) ──


def _valid_partition(tmp_path, month: str = "2025-11") -> Path:
    """유효한(읽기 가능) OHLCV 파티션을 배치하고 경로를 반환한다."""
    store = ParquetStore(base_path=tmp_path)
    store.write("005930", "1d", _ohlcv_df("005930", [1, 2], month=int(month[-2:])))
    return tmp_path / "ohlcv" / "1d" / "KRX" / "005930" / f"{month}.parquet"


def test_transient_permission_error_preserves_not_quarantined(
    tmp_path, monkeypatch
) -> None:
    """read PermissionError(EACCES) → 유효 파티션 격리 금지 + 기존 보존 + store_merge.

    읽기 실패를 무조건 corruption으로 간주하면 EACCES/stale-NFS가 유효 파티션(수개월치)
    위에서 나면 그 파티션이 격리되고 현재 group만 남은 채 store_recovered(비게이트)로
    checkpoint가 전진 → 조용한 데이터 손실. 진짜 corruption에만 self-heal이 발동함을
    잠근다(리뷰 [0]).
    """
    filepath = _valid_partition(tmp_path)
    before = filepath.read_bytes()
    store = ParquetStore(base_path=tmp_path)

    real_read = pl.read_parquet

    def _raise_eacces(source, *args, **kwargs):
        if str(source).endswith("2025-11.parquet"):
            raise PermissionError(13, "Permission denied")
        return real_read(source, *args, **kwargs)

    monkeypatch.setattr(pl, "read_parquet", _raise_eacces)

    new = _ohlcv_df("005930", [3], month=11)
    net = store.write("005930", "1d", new, data_type="ohlcv")

    monkeypatch.setattr(pl, "read_parquet", real_read)

    # 저장 반영 없음, 유효 파티션은 격리(.corrupted) 안 됨 + 원본 보존.
    assert net == 0
    assert not filepath.with_suffix(".corrupted").exists()
    assert filepath.read_bytes() == before
    warnings = store.drain_warnings()
    assert any(w.get("type") == "store_merge" for w in warnings)
    assert all(w.get("type") != "store_recovered" for w in warnings)


def test_transient_memory_error_preserves_not_quarantined(
    tmp_path, monkeypatch
) -> None:
    """read MemoryError → corruption 아님 → 격리 금지 + 기존 보존 + store_merge."""
    filepath = _valid_partition(tmp_path)
    before = filepath.read_bytes()
    store = ParquetStore(base_path=tmp_path)

    real_read = pl.read_parquet

    def _raise_oom(source, *args, **kwargs):
        if str(source).endswith("2025-11.parquet"):
            raise MemoryError("out of memory")
        return real_read(source, *args, **kwargs)

    monkeypatch.setattr(pl, "read_parquet", _raise_oom)

    net = store.write("005930", "1d", _ohlcv_df("005930", [3], month=11))

    monkeypatch.setattr(pl, "read_parquet", real_read)

    assert net == 0
    assert not filepath.with_suffix(".corrupted").exists()
    assert filepath.read_bytes() == before
    assert store.pending_merge_failure_count() == 1  # store_merge(게이트) 유발


def test_zero_byte_partition_self_heals(tmp_path) -> None:
    """0바이트 파티션(중단 write 잔재)은 진짜 corruption → self-heal + store_recovered.

    좁힌 corruption 판정(`_is_corrupt_parquet`) 하에서도 0바이트는 여전히
    self-heal 대상임을 잠근다(리뷰 [0] 정합).
    """
    store = ParquetStore(base_path=tmp_path)
    part_dir = tmp_path / "ohlcv" / "1d" / "KRX" / "005930"
    part_dir.mkdir(parents=True)
    zero = part_dir / "2025-11.parquet"
    zero.write_bytes(b"")  # 0바이트

    net = store.write("005930", "1d", _ohlcv_df("005930", [3, 4], month=11))

    assert net == 2
    assert len(pl.read_parquet(zero)) == 2
    assert zero.with_suffix(".corrupted").exists()
    warnings = store.drain_warnings()
    assert any(w.get("type") == "store_recovered" for w in warnings)
    assert all(w.get("type") != "store_merge" for w in warnings)


# ── (F) Class A: self-heal never raise + never file-less + 나머지 월 저장(리뷰 [777]) ─


def _fail_write_for_month(monkeypatch, fail_month: int):
    """`pl.DataFrame.write_parquet`를 특정 월 데이터에서만 raise하도록 monkeypatch.

    self-heal 재생성 write(대상 월 group)만 실패시키고 다른 월(정상 파티션) write는
    통과시켜, 단일 write() 안에서 한 파티션 self-heal 실패가 나머지 파티션 저장을
    막지 않음을 검증한다.
    """
    real_write = pl.DataFrame.write_parquet

    def _fake(self, file, *args, **kwargs):
        months = (
            set(self.get_column("timestamp").dt.month().to_list())
            if "timestamp" in self.columns
            else set()
        )
        if months == {fail_month}:
            raise RuntimeError("disk full during self-heal recreate")
        return real_write(self, file, *args, **kwargs)

    monkeypatch.setattr(pl.DataFrame, "write_parquet", _fake)
    return real_write


def test_self_heal_write_failure_never_raises_and_saves_other_partitions(
    tmp_path, monkeypatch
) -> None:
    """corrupt self-heal write 실패 → never raise + 손상본 유지 + 나머지 월 저장.

    Class A 불변식(리뷰 [777]): self-heal의 어떤 단계(격리·재생성 write·replace)가
    실패해도 예외가 write() 밖으로 전파되지 않고(크래시 방지), target이 file-less가
    되지 않으며(replace 전 실패라 손상본 유지), 같은 DataFrame의 나머지 월 파티션은
    정상 저장된다. store_merge(게이트)로 다음 run 재시도.
    """
    store = ParquetStore(base_path=tmp_path)
    part_dir = tmp_path / "ohlcv" / "1d" / "KRX" / "005930"
    part_dir.mkdir(parents=True)
    corrupt = part_dir / "2025-11.parquet"
    corrupt.write_bytes(b"corrupt-not-parquet")

    # 2025-11 self-heal 재생성 write만 실패(디스크 full 모사), 2025-12는 정상.
    _fail_write_for_month(monkeypatch, fail_month=11)

    df = pl.concat(
        [_ohlcv_df("005930", [3, 4], month=11), _ohlcv_df("005930", [5], month=12)]
    )
    # 예외가 전파되지 않아야 한다(never raise → 루프 지속).
    net = store.write("005930", "1d", df, data_type="ohlcv")

    monkeypatch.undo()

    # 2025-11: replace 전 write 실패라 target은 손상본 그대로(file-less 아님).
    assert corrupt.exists()
    assert corrupt.read_bytes() == b"corrupt-not-parquet"
    # write 단계에서 실패 → best-effort 격리(copy)는 실행 전이라 .corrupted 없음.
    assert not corrupt.with_suffix(".corrupted").exists()

    # 2025-12: 정상 파티션은 저장됨(한 파티션 실패가 나머지 저장을 막지 않음).
    dec = part_dir / "2025-12.parquet"
    assert dec.exists()
    assert len(pl.read_parquet(dec)) == 1
    assert net == 1  # 2025-12(1행)만 net-new, 2025-11은 0

    # store_merge(게이트) 표면화 + store_recovered 아님(재생성 실패라 회복 안 됨).
    warnings = store.drain_warnings()
    assert any(w.get("type") == "store_merge" for w in warnings)
    assert all(w.get("type") != "store_recovered" for w in warnings)
    # tmp 잔재 없음(실패 경로도 cleanup + sweep).
    assert list(part_dir.glob("*.tmp")) == []


def test_self_heal_quarantine_failure_still_heals_and_never_raises(
    tmp_path, monkeypatch
) -> None:
    """증적 격리(copy) 실패해도 healed 데이터가 landing되고 예외 미전파(리뷰 Class A).

    best-effort 격리이므로 copy 실패는 무시하고 healing을 우선한다. target은 tmp
    replace로 healed가 된다(격리 실패해도 landing).
    """
    store = ParquetStore(base_path=tmp_path)
    part_dir = tmp_path / "ohlcv" / "1d" / "KRX" / "005930"
    part_dir.mkdir(parents=True)
    corrupt = part_dir / "2025-11.parquet"
    corrupt.write_bytes(b"corrupt-not-parquet")

    # 증적 격리(copy)만 실패시킨다.
    def _raise_copy(src, dst, *args, **kwargs):
        raise OSError("copy failed (read-only .corrupted target)")

    monkeypatch.setattr("ante.data.store.shutil.copyfile", _raise_copy)

    net = store.write("005930", "1d", _ohlcv_df("005930", [3, 4], month=11))

    monkeypatch.undo()

    # 격리 실패해도 healed 데이터가 landing(never raise).
    assert net == 2
    assert len(pl.read_parquet(corrupt)) == 2
    warnings = store.drain_warnings()
    assert any(w.get("type") == "store_recovered" for w in warnings)
    assert list(part_dir.glob("*.tmp")) == []


def test_self_heal_never_uses_rename_outside_try(tmp_path, monkeypatch) -> None:
    """`Path.rename`이 실패해도 self-heal은 crash하지 않는다(리뷰 [777] 구조 회귀 가드).

    이전 구현은 격리 rename(`_quarantine_corrupt`)을 try 밖에서 먼저 호출해, rename
    실패(EROFS/EACCES/동시삭제)가 write() 루프로 전파돼 backfill/DART 전체를 크래시
    시켰다. self-heal은 이제 파괴적 rename을 쓰지 않고(best-effort copy + 원자 replace)
    healing을 완료해야 한다 — rename이 아예 불가해도 never raise.
    """
    store = ParquetStore(base_path=tmp_path)
    part_dir = tmp_path / "ohlcv" / "1d" / "KRX" / "005930"
    part_dir.mkdir(parents=True)
    corrupt = part_dir / "2025-11.parquet"
    corrupt.write_bytes(b"corrupt-not-parquet")

    def _rename_unavailable(self, target):
        raise OSError("rename unavailable (EROFS)")

    monkeypatch.setattr(Path, "rename", _rename_unavailable)

    # rename이 불가해도 예외가 전파되지 않고 healed가 landing해야 한다.
    net = store.write("005930", "1d", _ohlcv_df("005930", [3, 4], month=11))

    monkeypatch.undo()

    assert net == 2
    assert len(pl.read_parquet(corrupt)) == 2
    warnings = store.drain_warnings()
    assert any(w.get("type") == "store_recovered" for w in warnings)
    assert list(part_dir.glob("*.tmp")) == []


# ── (G) 파티션 파일 권한: mkstemp 0o600이 아니라 umask 존중(리뷰 [6]) ────────────


def test_atomic_write_respects_umask_permissions(tmp_path) -> None:
    """신규 파티션 mode == umask 존중값(0o666 & ~umask), owner-only 금지.

    mkstemp(0o600)+replace가 그대로면 파티션이 owner-only-readable이 되어 분리된
    reader 계정/그룹이 EACCES. df.write_parquet(umask 존중)과 동일 권한을 잠근다.
    """
    cur = os.umask(0)
    os.umask(cur)
    expected = 0o666 & ~cur

    store = ParquetStore(base_path=tmp_path)
    part_dir = tmp_path / "ohlcv" / "1d" / "KRX" / "005930"

    # 신규 파티션 write → umask 기본.
    store.write("005930", "1d", _ohlcv_df("005930", [3], month=11))
    new_mode = (part_dir / "2025-11.parquet").stat().st_mode & 0o777
    assert new_mode == expected, f"신규 파티션 mode={oct(new_mode)} != {oct(expected)}"

    # self-heal 재생성 파티션도 owner-only가 아니어야 한다(신규 손상본 mode 보존).
    store2 = ParquetStore(base_path=tmp_path)
    heal_dir = tmp_path / "ohlcv" / "1d" / "KRX" / "000660"
    heal_dir.mkdir(parents=True)
    (heal_dir / "2025-11.parquet").write_bytes(b"corrupt-not-parquet")
    store2.write("000660", "1d", _ohlcv_df("000660", [3], month=11))
    heal_mode = (heal_dir / "2025-11.parquet").stat().st_mode & 0o777
    assert heal_mode & 0o044, (
        f"self-heal mode={oct(heal_mode)} owner-only(그룹/other 불가)"
    )


def test_merge_preserves_existing_operator_mode(tmp_path) -> None:
    """기존 target이 있으면 그 operator mode를 보존한다(0o600 등, 리뷰 [668]).

    매 merge write가 기존 파티션 mode를 umask 기본(0o644)으로 폐기하지 않도록 잠근다.
    """
    store = ParquetStore(base_path=tmp_path)
    part_dir = tmp_path / "ohlcv" / "1d" / "KRX" / "005930"

    # 기존 파티션을 operator가 0o600으로 잠근 상태를 모사.
    store.write("005930", "1d", _ohlcv_df("005930", [3], month=11))
    filepath = part_dir / "2025-11.parquet"
    os.chmod(filepath, 0o600)

    # merge write → 기존 mode(0o600) 보존.
    store.write("005930", "1d", _ohlcv_df("005930", [4], month=11))
    merge_mode = filepath.stat().st_mode & 0o777
    assert merge_mode == 0o600, f"merge가 operator mode 폐기: {oct(merge_mode)}"


# ── (H) Class B: corruption 판정은 확정 마커에만(오분류=silent loss, 리뷰 [721]) ──


def test_is_corrupt_parquet_marker_and_zero_byte(tmp_path) -> None:
    """`_is_corrupt_parquet`: 정확한 마커/0바이트만 True, 그 외 False(보수적)."""
    valid = tmp_path / "valid.parquet"
    pl.DataFrame({"a": [1]}).write_parquet(str(valid))
    zero = tmp_path / "zero.parquet"
    zero.write_bytes(b"")
    missing = tmp_path / "missing.parquet"

    ce_corrupt = pl.exceptions.ComputeError(
        "parquet: File out of specification: The file must end with PAR1"
    )
    ce_io = pl.exceptions.ComputeError("parquet: generic I/O error while reading")

    # (1) ComputeError + 정확 마커 → corrupt(파일 상태 무관).
    assert ParquetStore._is_corrupt_parquet(valid, ce_corrupt) is True
    # (2) ComputeError지만 비-마커(I/O 등) + 유효 파일 → preserve(오분류 금지).
    assert ParquetStore._is_corrupt_parquet(valid, ce_io) is False
    # (3) 0바이트 → corrupt(마커 없어도 stat으로 확정).
    assert ParquetStore._is_corrupt_parquet(zero, OSError("x")) is True
    # (4) 일시적/환경 오류(PermissionError/MemoryError) + 유효 파일 → preserve.
    assert (
        ParquetStore._is_corrupt_parquet(valid, PermissionError(13, "denied")) is False
    )
    assert ParquetStore._is_corrupt_parquet(valid, MemoryError("oom")) is False
    # (5) stat 실패(파일 부재) + 비-마커 예외 → preserve(단정 금지).
    assert ParquetStore._is_corrupt_parquet(missing, OSError("stale nfs")) is False
    # (6) stat 실패라도 마커가 있으면 corrupt.
    assert ParquetStore._is_corrupt_parquet(missing, ce_corrupt) is True


def test_compute_error_non_corruption_message_preserves(tmp_path, monkeypatch) -> None:
    """유효 파티션 비-corruption ComputeError(I/O) → self-heal 안 함 + 보존.

    넓은 `startswith("parquet:")` 판정이 비손상 ComputeError까지 corruption으로
    오분류해 유효 이력을 조용히 잃던 회귀를 잠근다(리뷰 [721]).
    """
    filepath = _valid_partition(tmp_path)
    before = filepath.read_bytes()
    store = ParquetStore(base_path=tmp_path)

    real_read = pl.read_parquet

    def _raise_io_ce(source, *args, **kwargs):
        if str(source).endswith("2025-11.parquet"):
            raise pl.exceptions.ComputeError("parquet: transient I/O read error")
        return real_read(source, *args, **kwargs)

    monkeypatch.setattr(pl, "read_parquet", _raise_io_ce)
    net = store.write("005930", "1d", _ohlcv_df("005930", [3], month=11))
    monkeypatch.undo()

    assert net == 0
    assert not filepath.with_suffix(".corrupted").exists()  # 격리 안 함
    assert filepath.read_bytes() == before  # 유효 파티션 보존
    assert store.pending_merge_failure_count() == 1  # store_merge(게이트)


# ── (I) Class C: orphan .tmp 회수(리뷰 [661]) ─────────────────────────────────


def test_orphan_tmp_swept_on_write(tmp_path) -> None:
    """이전 크래시가 남긴 orphan *.tmp가 다음 write 진입 시 회수된다."""
    store = ParquetStore(base_path=tmp_path)
    part_dir = tmp_path / "ohlcv" / "1d" / "KRX" / "005930"
    part_dir.mkdir(parents=True)
    orphan = part_dir / "tmpDEADBEEF.tmp"
    orphan.write_bytes(b"leftover-partial")

    store.write("005930", "1d", _ohlcv_df("005930", [3], month=11))

    # orphan .tmp 회수 + 정상 파티션 생성.
    assert not orphan.exists()
    assert list(part_dir.glob("*.tmp")) == []
    assert (part_dir / "2025-11.parquet").exists()


def test_validate_sweeps_and_reports_orphan_tmp(tmp_path) -> None:
    """validate가 orphan *.tmp를 회수하고 stale_tmp_removed로 리포트한다(가시화)."""
    store = ParquetStore(base_path=tmp_path)
    store.write("005930", "1d", _ohlcv_df("005930", [3], month=11))
    part_dir = tmp_path / "ohlcv" / "1d" / "KRX" / "005930"
    (part_dir / "tmpAAA.tmp").write_bytes(b"x")
    (part_dir / "tmpBBB.tmp").write_bytes(b"y")

    result = store.validate("005930", "1d")

    assert result["stale_tmp_removed"] == 2
    assert list(part_dir.glob("*.tmp")) == []
    assert result["valid"] == 1  # 정상 파티션은 그대로
