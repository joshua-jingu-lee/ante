"""Data Pipeline — Parquet 파일 읽기/쓰기/관리."""

from __future__ import annotations

import logging
from pathlib import Path

import polars as pl

logger = logging.getLogger(__name__)

# data_type별 시간 컬럼명
_TIME_COLUMN: dict[str, str] = {
    "ohlcv": "timestamp",
    "fundamental": "date",
    "tick": "timestamp",
}


class ParquetStore:
    """Parquet 파일 관리. 다양한 데이터 타입의 읽기/쓰기/파티셔닝 담당."""

    def __init__(
        self, base_path: str | Path = "data/", compression: str = "snappy"
    ) -> None:
        self._base = Path(base_path)
        self._compression = compression

    @property
    def base_path(self) -> Path:
        return self._base

    def _resolve_path(
        self, symbol: str, timeframe: str, data_type: str = "ohlcv"
    ) -> Path:
        """data_type에 따라 저장 경로를 결정.

        - ohlcv: {base}/ohlcv/{timeframe}/{symbol}/
        - fundamental: {base}/fundamental/krx/{symbol}/
        - tick: {base}/tick/krx/{symbol}/
        """
        if data_type == "ohlcv":
            return self._base / "ohlcv" / timeframe / symbol
        elif data_type == "fundamental":
            return self._base / "fundamental" / "krx" / symbol
        elif data_type == "tick":
            return self._base / "tick" / "krx" / symbol
        else:
            return self._base / data_type / timeframe / symbol

    def read(
        self,
        symbol: str,
        timeframe: str,
        start: str | None = None,
        end: str | None = None,
        limit: int | None = None,
        data_type: str = "ohlcv",
    ) -> pl.DataFrame:
        """Parquet에서 데이터 읽기.

        Args:
            symbol: 종목 코드
            timeframe: 타임프레임 (1m, 5m, 15m, 1h, 1d)
            start: 시작 시간 (ISO 형식, inclusive)
            end: 종료 시간 (ISO 형식, inclusive)
            limit: 최근 N건만 반환
            data_type: 데이터 타입 (ohlcv, fundamental, tick)
        """
        path = self._resolve_path(symbol, timeframe, data_type)
        if not path.exists():
            return pl.DataFrame()

        files = sorted(path.glob("*.parquet"))
        if not files:
            return pl.DataFrame()

        dfs = []
        for f in files:
            try:
                dfs.append(pl.read_parquet(f))
            except Exception:
                logger.warning("Failed to read parquet file: %s", f)
                continue

        if not dfs:
            return pl.DataFrame()

        df = pl.concat(dfs)
        time_col = _TIME_COLUMN.get(data_type, "timestamp")

        if start and time_col in df.columns:
            df = df.filter(
                pl.col(time_col) >= pl.lit(start).str.to_datetime(time_zone="UTC")
            )
        if end and time_col in df.columns:
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
    ) -> None:
        """데이터를 Parquet에 기록. 월별 파티셔닝, 중복 제거(merge)."""
        if data.is_empty():
            return

        path = self._resolve_path(symbol, timeframe, data_type)
        path.mkdir(parents=True, exist_ok=True)

        time_col = _TIME_COLUMN.get(data_type, "timestamp")

        # 월별 파티셔닝
        if time_col in data.columns:
            if data[time_col].dtype == pl.Date:
                month_col = data[time_col].cast(pl.Utf8).str.slice(0, 7)
            else:
                month_col = data[time_col].dt.strftime("%Y-%m")
        else:
            month_col = pl.Series(["unknown"] * len(data))

        data_with_month = data.with_columns(month_col.alias("_month"))

        for month_val in data_with_month["_month"].unique().to_list():
            group = data_with_month.filter(pl.col("_month") == month_val).drop("_month")
            filepath = path / f"{month_val}.parquet"

            unique_col = time_col if time_col in group.columns else None

            if filepath.exists():
                try:
                    existing = pl.read_parquet(filepath)
                    merged = pl.concat([existing, group])
                    if unique_col:
                        merged = merged.unique(subset=[unique_col]).sort(unique_col)
                    merged.write_parquet(str(filepath), compression=self._compression)
                except Exception:
                    logger.warning(
                        "Failed to merge with existing file: %s, overwriting", filepath
                    )
                    if unique_col and unique_col in group.columns:
                        group = group.sort(unique_col)
                    group.write_parquet(str(filepath), compression=self._compression)
            else:
                if unique_col and unique_col in group.columns:
                    group = group.sort(unique_col)
                group.write_parquet(str(filepath), compression=self._compression)

        logger.debug("Wrote %d rows for %s/%s", len(data), symbol, timeframe)

    def append(
        self,
        symbol: str,
        timeframe: str,
        rows: list[dict],
        data_type: str = "ohlcv",
    ) -> None:
        """버퍼 데이터를 기존 Parquet에 추가."""
        df = pl.DataFrame(rows)
        self.write(symbol, timeframe, df, data_type=data_type)

    def list_symbols(
        self, timeframe: str = "1d", data_type: str = "ohlcv"
    ) -> list[str]:
        """보유 데이터의 종목 목록."""
        if data_type == "ohlcv":
            path = self._base / "ohlcv" / timeframe
        elif data_type in ("fundamental", "tick"):
            path = self._base / data_type / "krx"
        else:
            path = self._base / data_type / timeframe
        if not path.exists():
            return []
        return sorted([d.name for d in path.iterdir() if d.is_dir()])

    def get_date_range(
        self, symbol: str, timeframe: str, data_type: str = "ohlcv"
    ) -> tuple[str, str] | None:
        """종목의 데이터 기간 조회. (첫 파일 stem, 마지막 파일 stem) 반환."""
        path = self._resolve_path(symbol, timeframe, data_type)
        files = sorted(path.glob("*.parquet")) if path.exists() else []
        if not files:
            return None
        return files[0].stem, files[-1].stem

    def get_row_count(
        self, symbol: str, timeframe: str, data_type: str = "ohlcv"
    ) -> int:
        """종목의 총 행 수 조회. Parquet 메타데이터만 읽어 빠르게 반환."""
        path = self._resolve_path(symbol, timeframe, data_type)
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
        # ohlcv: timeframe별
        ohlcv_path = self._base / "ohlcv"
        if ohlcv_path.exists():
            for tf_dir in ohlcv_path.iterdir():
                if tf_dir.is_dir():
                    size = sum(f.stat().st_size for f in tf_dir.rglob("*.parquet"))
                    usage[tf_dir.name] = size
        # fundamental, tick
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
    ) -> dict:
        """Parquet 파일 무결성 검증.

        Args:
            symbol: 종목 코드
            timeframe: 타임프레임
            fix: True이면 손상 파일을 .corrupted 확장자로 이동
            data_type: 데이터 타입 (ohlcv, fundamental, tick)

        Returns:
            {"symbol": str, "timeframe": str, "total": int,
             "valid": int, "corrupted": int, "corrupted_files": list[str]}
        """
        path = self._resolve_path(symbol, timeframe, data_type)
        result: dict = {
            "symbol": symbol,
            "timeframe": timeframe,
            "total": 0,
            "valid": 0,
            "corrupted": 0,
            "corrupted_files": [],
        }

        if not path.exists():
            return result

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
                    corrupted_path = f.with_suffix(".corrupted")
                    f.rename(corrupted_path)
                    logger.info("손상 파일 이동: %s → %s", f, corrupted_path)

        return result

    def delete_file(
        self, symbol: str, timeframe: str, month: str, data_type: str = "ohlcv"
    ) -> bool:
        """특정 Parquet 파일 삭제. 성공 여부 반환."""
        path = self._resolve_path(symbol, timeframe, data_type)
        filepath = path / f"{month}.parquet"
        if filepath.exists():
            filepath.unlink()
            logger.info("Deleted parquet file: %s", filepath)
            return True
        return False
