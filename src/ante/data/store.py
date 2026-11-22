"""Data Pipeline — Parquet 파일 읽기/쓰기/관리."""

from __future__ import annotations

import logging
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any, Literal, cast

import polars as pl

from ante.core.exchange import CANONICAL_EXCHANGES, is_canonical

logger = logging.getLogger(__name__)


class ParquetReadError(Exception):
    """Parquet 파티션을 읽는 도중 손상 파일을 만났을 때 발생.

    `ParquetStore.read(..., strict=True)` 경로 전용 예외다. tolerant
    경로(`strict=False`, 기본)는 손상 파티션을 logger.warning + continue로
    skip하므로 이 예외를 발생시키지 않는다(feed/CLI 회귀 방지). strict
    경로(backtest data 로드 등)는 손상 파티션을 만나면 부분 데이터로
    silent 성공하지 않고 이 예외로 즉시 실패한다.
    """


def _is_safe_path_segment(seg: str) -> bool:
    """단일 path segment가 traversal-safe한지 판정."""
    if not seg:
        return False
    if seg in (".", ".."):
        return False
    if "/" in seg or "\\" in seg or "\x00" in seg:
        return False
    if os.path.isabs(seg):
        return False
    if os.path.splitdrive(seg)[0]:
        return False
    return True


CompressionType = Literal["lz4", "uncompressed", "snappy", "gzip", "brotli", "zstd"]

_TIME_COLUMN: dict[str, str] = {
    "ohlcv": "timestamp",
    "fundamental": "date",
    "tick": "timestamp",
}

_DATE_ONLY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_SUBMINUTE_TIMEFRAMES: frozenset[str] = frozenset({"10s", "30s"})

_LEGACY_MONTHLY_GLOB = "????-??.parquet"


def _natural_key(data_type: str, columns: list[str]) -> list[str]:
    """data_type별 merge/dedup용 natural key 컬럼 목록을 결정한다."""
    cols = set(columns)
    if data_type == "fundamental":
        if "date" in cols and "source" in cols:
            return ["date", "source"]
        if "date" in cols:
            return ["date"]
        return []
    if "timestamp" in cols:
        return ["timestamp"]
    return []


def _date_str(value: object) -> str:
    """Datetime/Date/str을 YYYY-MM-DD 문자열로."""
    if hasattr(value, "isoformat"):
        return cast("str", value.isoformat()[:10])
    return str(value)[:10]


_KNOWN_EXCHANGES: frozenset[str] = CANONICAL_EXCHANGES

_LEGACY_KRX_SYMBOL_PATTERN: re.Pattern[str] = re.compile(r"^\d{6}$")


def _get_actual_dir_name(parent: Path, name: str) -> str | None:
    """파일시스템 상의 실제 디렉토리 이름을 반환."""
    if not parent.exists():
        return None
    for entry in parent.iterdir():
        if entry.is_dir() and entry.name.lower() == name.lower():
            return entry.name
    return None


def migrate_parquet_paths(data_path: Path) -> int:
    """기존 exchange 없는 경로를 KRX/ 하위로 이동.

    Args:
        data_path: 데이터 저장소 루트 경로 (예: data/)

    Returns:
        이동된 디렉토리 수
    """
    moved = 0

    ohlcv_path = data_path / "ohlcv"
    if ohlcv_path.exists():
        for timeframe_dir in ohlcv_path.iterdir():
            if not timeframe_dir.is_dir():
                continue
            for symbol_dir in list(timeframe_dir.iterdir()):
                if not symbol_dir.is_dir():
                    continue
                if symbol_dir.name in _KNOWN_EXCHANGES:
                    continue
                if not _LEGACY_KRX_SYMBOL_PATTERN.match(symbol_dir.name):
                    logger.warning(
                        "마이그레이션 스킵: %s — KRX 심볼 형식(6자리 숫자)이 아님",
                        symbol_dir,
                    )
                    continue
                target = timeframe_dir / "KRX" / symbol_dir.name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(symbol_dir), str(target))
                moved += 1
                logger.info("마이그레이션: %s → %s", symbol_dir, target)

    for dtype in ("fundamental", "tick"):
        dtype_path = data_path / dtype
        if not dtype_path.exists():
            continue
        krx_lower = dtype_path / "krx"
        if not krx_lower.exists():
            continue
        actual_name = _get_actual_dir_name(dtype_path, "krx")
        if actual_name == "KRX":
            continue
        target = dtype_path / "KRX"
        if not target.exists():
            shutil.move(str(krx_lower), str(target))
            moved += 1
            logger.info("마이그레이션: %s → %s", krx_lower, target)

    if moved > 0:
        logger.info("마이그레이션 완료: %d개 디렉토리 이동", moved)

    return moved


class ParquetStore:
    """Parquet 파일 관리. 다양한 데이터 타입의 읽기/쓰기/파티셔닝 담당."""

    def __init__(
        self,
        base_path: str | Path = "data/",
        compression: CompressionType = "snappy",
    ) -> None:
        self._base = Path(base_path)
        self._compression = compression
        self._pending_warnings: list[dict[str, Any]] = []

    @property
    def base_path(self) -> Path:
        return self._base

    def drain_warnings(self) -> list[dict[str, Any]]:
        """누적된 store 이상 경고를 반환하고 버퍼를 비운다."""
        drained = list(self._pending_warnings)
        self._pending_warnings.clear()
        return drained

    def pending_merge_failure_count(self) -> int:
        """현재 버퍼에 쌓인 ``store_merge`` 경고 수를 **비파괴적으로** 센다.

        ``drain_warnings()`` 와 달리 버퍼를 비우지 않는다(read-only count).
        DART collector처럼 checkpoint.save를 자체적으로 수행하는 호출자가
        ``store.write`` 직전/직후 이 값을 비교해 이번 단계에서 발생한
        store-merge 실패(파티션 merge 실패 → 기존 파일 보존, 데이터 미반영)를
        감지하는 데 쓴다. 누적 카운트이므로 **직전/직후 증가분**으로
        이번 단계의 실패를 판정해야 한다(이전 단계 경고가 아직 runner에 의해
        drain되지 않았을 수 있음).
        """
        return sum(1 for w in self._pending_warnings if w.get("type") == "store_merge")

    def _resolve_path(
        self,
        symbol: str,
        timeframe: str,
        data_type: str = "ohlcv",
        exchange: str = "KRX",
    ) -> Path:
        """data_type에 따라 저장 경로를 결정."""
        used_segments: tuple[str, ...]
        if data_type == "ohlcv":
            candidate = self._base / "ohlcv" / timeframe / exchange / symbol
            expected_parent = self._base / "ohlcv" / timeframe / exchange
            used_segments = (timeframe, exchange, symbol)
        elif data_type == "fundamental":
            candidate = self._base / "fundamental" / exchange / symbol
            expected_parent = self._base / "fundamental" / exchange
            used_segments = (exchange, symbol)
        elif data_type == "tick":
            candidate = self._base / "tick" / exchange / symbol
            expected_parent = self._base / "tick" / exchange
            used_segments = (exchange, symbol)
        else:
            candidate = self._base / data_type / timeframe / exchange / symbol
            expected_parent = self._base / data_type / timeframe / exchange
            used_segments = (data_type, timeframe, exchange, symbol)

        for seg in used_segments:
            if not _is_safe_path_segment(seg):
                raise ValueError(
                    f"path traversal 차단: 안전하지 않은 경로 segment '{seg}' "
                    f"(data_type={data_type})"
                )

        resolved_base = self._base.resolve()
        resolved_parent = expected_parent.resolve()
        resolved_candidate = candidate.resolve()
        if (
            resolved_candidate.parent != resolved_parent
            or not resolved_candidate.is_relative_to(resolved_base)
        ):
            raise ValueError(
                f"path traversal 차단: 해석된 경로가 예상 위치를 벗어남 "
                f"(symbol={symbol!r}, timeframe={timeframe!r}, "
                f"data_type={data_type!r})"
            )

        return candidate

    def resolve_path(
        self,
        symbol: str,
        timeframe: str,
        data_type: str = "ohlcv",
        exchange: str = "KRX",
    ) -> Path:
        """데이터 경로를 해석한다. _resolve_path()의 public 인터페이스."""
        return self._resolve_path(symbol, timeframe, data_type, exchange)

    def read(
        self,
        symbol: str,
        timeframe: str,
        start: str | None = None,
        end: str | None = None,
        limit: int | None = None,
        data_type: str = "ohlcv",
        exchange: str = "KRX",
        strict: bool = False,
    ) -> pl.DataFrame:
        """Parquet에서 데이터 읽기.

        Args:
            start: 시작 시간 (ISO 형식, inclusive)
            end: 종료 시간 (ISO 형식, inclusive). date-only(`YYYY-MM-DD`)는
                해당 날짜 whole-day inclusive(당일 23:59:59.999까지)로
                해석되어 intraday 당일 장중 데이터가 포함된다.
                시간 성분이 있는 형식은 그 정확 instant까지 inclusive다.
            limit: 최근 N건만 반환
        """
        path = self._resolve_path(symbol, timeframe, data_type, exchange)
        if not path.exists():
            return pl.DataFrame()

        files = sorted(path.glob("*.parquet"))
        if not files:
            return pl.DataFrame()

        dfs = []
        for f in files:
            try:
                dfs.append(pl.read_parquet(f))
            except Exception as exc:
                if strict:
                    raise ParquetReadError(
                        f"Corrupt parquet partition: {f}: {exc}"
                    ) from exc
                logger.warning("Failed to read parquet file: %s", f)
                continue

        if not dfs:
            return pl.DataFrame()

        df = pl.concat(dfs, how="diagonal_relaxed")
        time_col = _TIME_COLUMN.get(data_type, "timestamp")

        if start and time_col in df.columns:
            df = df.filter(
                pl.col(time_col) >= pl.lit(start).str.to_datetime(time_zone="UTC")
            )
        if end and time_col in df.columns:
            if _DATE_ONLY_RE.match(end):
                df = df.filter(
                    pl.col(time_col)
                    < pl.lit(end).str.to_datetime(time_zone="UTC") + pl.duration(days=1)
                )
            else:
                df = df.filter(
                    pl.col(time_col) <= pl.lit(end).str.to_datetime(time_zone="UTC")
                )

        if time_col in df.columns:
            df = df.sort(time_col)

        if limit:
            df = df.tail(limit)

        return df

    def write(
        self,
        symbol: str,
        timeframe: str,
        data: pl.DataFrame,
        data_type: str = "ohlcv",
        exchange: str = "KRX",
    ) -> int:
        """데이터를 Parquet에 기록. 파티셔닝, 중복 제거(merge).

        신규 write/append/경로 생성은 canonical exchange만 허용한다
        (core.md ``## Canonical Exchange Vocabulary``). `append()`는
        `self.write(...)`로 위임하므로 이 guard가 append도 함께 커버한다.
        read/`_resolve_path`/`migrate_parquet_paths` 등 기존·legacy 조회
        표면에는 검증을 추가하지 않는다(Legacy out-of-vocabulary read 면제).
        """
        if not isinstance(exchange, str) or not is_canonical(exchange):
            raise ValueError(
                f"유효하지 않은 exchange: '{exchange}'. "
                f"허용 값: {sorted(CANONICAL_EXCHANGES)}"
            )

        if data.is_empty():
            return 0

        time_col = _TIME_COLUMN.get(data_type, "timestamp")
        if time_col in data.columns and bool(data[time_col].is_null().any()):
            raise ValueError(
                f"partition key '{time_col}'에 null 값이 있어 저장을 거부합니다 "
                f"(symbol={symbol}, timeframe={timeframe}, data_type={data_type})"
            )

        path = self._resolve_path(symbol, timeframe, data_type, exchange)
        path.mkdir(parents=True, exist_ok=True)

        key = _natural_key(data_type, data.columns)

        use_daily = data_type == "ohlcv" and timeframe in _SUBMINUTE_TIMEFRAMES
        if use_daily and next(path.glob(_LEGACY_MONTHLY_GLOB), None) is not None:
            use_daily = False
            logger.warning(
                "legacy 월별 파티션 존재 — 일별 전환은 #2267, 월별 유지"
                "(coexistence 미생성): %s",
                path,
            )

        if use_daily:
            partitioned = self._partition_by_day(data, time_col)
        else:
            partitioned = self._partition_by_month(data, time_col)

        net_delta = 0
        for part_val, group in partitioned:
            filepath = path / f"{part_val}.parquet"
            net_delta += self._persist_partition(filepath, group, key)

        logger.debug(
            "Wrote %s/%s: input=%d net_new=%d",
            symbol,
            timeframe,
            len(data),
            net_delta,
        )
        return net_delta

    def _partition_by_month(
        self, data: pl.DataFrame, time_col: str
    ) -> list[tuple[str, pl.DataFrame]]:
        """데이터를 월별로 분할하여 (월, DataFrame) 리스트 반환."""
        if time_col in data.columns:
            if data[time_col].dtype == pl.Date:
                month_series = data[time_col].cast(pl.Utf8).str.slice(0, 7)
            else:
                month_series = data[time_col].dt.strftime("%Y-%m")
        else:
            month_series = pl.Series(["unknown"] * len(data))

        data_with_month = data.with_columns(month_series.alias("_month"))
        return [
            (
                month_val,
                data_with_month.filter(pl.col("_month") == month_val).drop("_month"),
            )
            for month_val in data_with_month["_month"].unique().to_list()
        ]

    def _partition_by_day(
        self, data: pl.DataFrame, time_col: str
    ) -> list[tuple[str, pl.DataFrame]]:
        """데이터를 일별로 분할하여 (`YYYY-MM-DD`, DataFrame) 리스트 반환."""
        if time_col in data.columns:
            if data[time_col].dtype == pl.Date:
                day_series = data[time_col].cast(pl.Utf8).str.slice(0, 10)
            else:
                day_series = data[time_col].dt.strftime("%Y-%m-%d")
        else:
            day_series = pl.Series(["unknown"] * len(data))

        data_with_day = data.with_columns(day_series.alias("_day"))
        return [
            (
                day_val,
                data_with_day.filter(pl.col("_day") == day_val).drop("_day"),
            )
            for day_val in data_with_day["_day"].unique().to_list()
        ]

    @staticmethod
    def _dedup_sort_by_key(df: pl.DataFrame, key: list[str]) -> pl.DataFrame:
        """natural key로 dedup(`keep="last"`) 후 정렬한다(멱등 merge)."""
        if key:
            present = [c for c in key if c in df.columns]
            if present:
                return df.unique(subset=present, keep="last").sort(present)
        return df

    @staticmethod
    def _sweep_stale_tmp(partition_dir: Path) -> int:
        """대상 파티션 dir의 stale ``*.tmp`` (orphan)를 삭제하고 삭제 수를 반환."""
        removed = 0
        try:
            stale_files = list(partition_dir.glob("*.tmp"))
        except OSError:
            return 0
        for stale in stale_files:
            try:
                stale.unlink()
                removed += 1
            except OSError:
                pass
        return removed

    @staticmethod
    def _apply_partition_mode(
        tmp_path: str, target: Path, preserve_existing_mode: bool
    ) -> None:
        """replace 전 tmp 파일 mode를 결정한다."""
        mode = 0o644
        if preserve_existing_mode:
            try:
                mode = os.stat(target).st_mode & 0o777
            except OSError:
                mode = 0o644
        os.chmod(tmp_path, mode)

    def _atomic_write_parquet(
        self,
        df: pl.DataFrame,
        filepath: Path,
        *,
        preserve_existing_mode: bool = True,
    ) -> None:
        """DataFrame을 파티션 파일에 **원자적으로** 기록(write-then-replace)."""
        fd, tmp_path = tempfile.mkstemp(dir=filepath.parent, suffix=".tmp")
        os.close(fd)
        try:
            df.write_parquet(tmp_path, compression=self._compression)
            self._apply_partition_mode(tmp_path, filepath, preserve_existing_mode)
            Path(tmp_path).replace(filepath)
        except BaseException:
            Path(tmp_path).unlink(missing_ok=True)
            raise

    def _quarantine_corrupt(self, filepath: Path) -> Path:
        """손상 파티션을 ``.corrupted`` 로 격리(**rename**)하고 격리 경로를 반환."""
        target = filepath.with_suffix(".corrupted")
        n = 1
        while target.exists():
            target = filepath.with_name(f"{filepath.stem}.corrupted.{n}")
            n += 1
        filepath.rename(target)
        return target

    def _record_merge_failure(
        self, filepath: Path, exc: BaseException, *, message: str | None = None
    ) -> int:
        """기존 파일 보존 + ``store_merge`` 경고를 적재하고 net-new 0을 반환한다."""
        logger.warning(
            "Parquet 파티션 merge 실패: %s — 기존 파일 보존, write 건너뜀 (%s)",
            filepath,
            exc,
        )
        self._pending_warnings.append(
            {
                "type": "store_merge",
                "path": str(filepath),
                "message": message
                or (
                    f"파티션 merge 실패로 이번 write를 건너뛰어 기존 데이터를 "
                    f"보존했습니다: {exc}"
                ),
            }
        )
        return 0

    @staticmethod
    def _is_zero_byte(filepath: Path) -> bool:
        """target이 **확실히 0바이트**인지 판정. stat 실패 시 False(단정 금지)."""
        try:
            return filepath.stat().st_size == 0
        except OSError:
            return False

    def _persist_partition(
        self, filepath: Path, group: pl.DataFrame, key: list[str]
    ) -> int:
        """단일 파티션을 Parquet 파일에 기록. 기존 파일이 있으면 merge."""
        if filepath.exists() and not self._is_zero_byte(filepath):
            try:
                existing = pl.read_parquet(filepath)
                existing_len = len(existing)
                merged = pl.concat([existing, group], how="diagonal_relaxed")
                merged = self._dedup_sort_by_key(merged, key)
                self._atomic_write_parquet(merged, filepath)
                return max(0, len(merged) - existing_len)
            except Exception as exc:
                return self._record_merge_failure(filepath, exc)

        is_zero_byte_recovery = filepath.exists()
        group = self._dedup_sort_by_key(group, key)
        self._atomic_write_parquet(group, filepath, preserve_existing_mode=False)

        if is_zero_byte_recovery:
            logger.warning(
                "0바이트 손상 파티션 자동복구: %s — 신규 수집분으로 재생성. "
                "이전 데이터가 있었다면 forward-only 공백 가능(range 재backfill 필요).",
                filepath,
            )
            self._pending_warnings.append(
                {
                    "type": "store_recovered",
                    "path": str(filepath),
                    "message": (
                        f"0바이트 손상 파티션을 신규 수집분으로 자동복구했습니다: "
                        f"{filepath}. 주의: 이 파티션에 이전 데이터가 있었다면 이번 "
                        f"복구는 현재 group만 담으므로 checkpoint 이전 구간이 유실될 "
                        f"수 있습니다(forward-only 공백). 완전 복구는 명시 range "
                        f"재backfill로만 가능합니다."
                    ),
                }
            )

        return len(group)

    def append(
        self,
        symbol: str,
        timeframe: str,
        rows: list[dict[str, Any]],
        data_type: str = "ohlcv",
        exchange: str = "KRX",
    ) -> None:
        """버퍼 데이터를 기존 Parquet에 추가."""
        df = pl.DataFrame(rows)
        self.write(symbol, timeframe, df, data_type=data_type, exchange=exchange)

    def list_symbols(
        self,
        timeframe: str = "1d",
        data_type: str = "ohlcv",
        exchange: str = "KRX",
    ) -> list[str]:
        """보유 데이터의 종목 목록."""
        if data_type == "ohlcv":
            path = self._base / "ohlcv" / timeframe / exchange
        elif data_type in ("fundamental", "tick"):
            path = self._base / data_type / exchange
        else:
            path = self._base / data_type / timeframe / exchange
        if not path.exists():
            return []
        return sorted([d.name for d in path.iterdir() if d.is_dir()])

    def get_date_range(
        self,
        symbol: str,
        timeframe: str,
        data_type: str = "ohlcv",
        exchange: str = "KRX",
    ) -> tuple[str, str] | None:
        """종목의 데이터 기간 조회. (첫 row 날짜, 마지막 row 날짜) YYYY-MM-DD 반환.

        파일은 월별 stem 정렬이므로 첫 파일 min(time_col) = 전역 최소,
        마지막 파일 max(time_col) = 전역 최대. 읽기 실패/빈 컬럼 시 파일 stem fallback.
        """
        path = self._resolve_path(symbol, timeframe, data_type, exchange)
        files = sorted(path.glob("*.parquet")) if path.exists() else []
        if not files:
            return None
        time_col = _TIME_COLUMN.get(data_type, "timestamp")
        try:
            first_min = pl.read_parquet(files[0]).select(pl.col(time_col).min()).item()
            last_max = pl.read_parquet(files[-1]).select(pl.col(time_col).max()).item()
        except Exception:
            return files[0].stem, files[-1].stem
        if first_min is None or last_max is None:
            return files[0].stem, files[-1].stem
        return _date_str(first_min), _date_str(last_max)

    def get_row_count(
        self,
        symbol: str,
        timeframe: str,
        data_type: str = "ohlcv",
        exchange: str = "KRX",
    ) -> int:
        """종목의 총 행 수 조회. Parquet 메타데이터만 읽어 빠르게 반환."""
        path = self._resolve_path(symbol, timeframe, data_type, exchange)
        if not path.exists():
            return 0
        files = sorted(path.glob("*.parquet"))
        total = 0
        for f in files:
            try:
                total += pl.scan_parquet(f).select(pl.len()).collect().item()
            except Exception:
                logger.warning("Failed to read row count: %s", f)
                continue
        return total

    def get_storage_usage(self) -> dict[str, int]:
        """저장 용량 현황 (바이트). 데이터 타입/타임프레임별 합산."""
        usage: dict[str, int] = {}
        ohlcv_path = self._base / "ohlcv"
        if ohlcv_path.exists():
            for tf_dir in ohlcv_path.iterdir():
                if tf_dir.is_dir():
                    size = sum(f.stat().st_size for f in tf_dir.rglob("*.parquet"))
                    usage[tf_dir.name] = size
        for dtype in ("fundamental", "tick"):
            dtype_path = self._base / dtype
            if dtype_path.exists():
                size = sum(f.stat().st_size for f in dtype_path.rglob("*.parquet"))
                if size > 0:
                    usage[dtype] = size
        return usage

    def validate(
        self,
        symbol: str,
        timeframe: str,
        fix: bool = False,
        data_type: str = "ohlcv",
        exchange: str = "KRX",
    ) -> dict[str, Any]:
        """Parquet 파일 무결성 검증.

        Args:
            fix: True이면 손상 파일을 .corrupted 확장자로 이동

        Returns:
            {"symbol": str, "timeframe": str, "total": int,
             "valid": int, "corrupted": int, "corrupted_files": list[str],
             "stale_tmp_removed": int}
        """
        path = self._resolve_path(symbol, timeframe, data_type, exchange)
        result: dict[str, Any] = {
            "symbol": symbol,
            "timeframe": timeframe,
            "total": 0,
            "valid": 0,
            "corrupted": 0,
            "corrupted_files": [],
            "stale_tmp_removed": 0,
        }

        if not path.exists():
            return result

        if fix:
            stale_removed = self._sweep_stale_tmp(path)
            result["stale_tmp_removed"] = stale_removed
            if stale_removed:
                logger.info("orphan .tmp %d개 회수: %s", stale_removed, path)

        files = sorted(path.glob("*.parquet"))
        result["total"] = len(files)

        for f in files:
            try:
                pl.read_parquet(f)
                result["valid"] += 1
            except Exception:
                logger.warning("손상된 Parquet 파일 발견: %s", f)
                result["corrupted"] += 1
                result["corrupted_files"].append(str(f))
                if fix:
                    corrupted_path = self._quarantine_corrupt(f)
                    logger.info("손상 파일 이동: %s → %s", f, corrupted_path)

        return result

    def delete_file(
        self,
        symbol: str,
        timeframe: str,
        month: str,
        data_type: str = "ohlcv",
        exchange: str = "KRX",
    ) -> bool:
        """특정 Parquet 파일 삭제. 성공 여부 반환."""
        path = self._resolve_path(symbol, timeframe, data_type, exchange)
        filepath = path / f"{month}.parquet"
        if filepath.exists():
            filepath.unlink()
            logger.info("Deleted parquet file: %s", filepath)
            return True
        return False
