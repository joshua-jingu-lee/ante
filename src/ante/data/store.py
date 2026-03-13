"""Data Pipeline — Parquet 파일 읽기/쓰기/관리."""

from __future__ import annotations

import logging
from pathlib import Path

import polars as pl

logger = logging.getLogger(__name__)


class ParquetStore:
    """Parquet 파일 관리. OHLCV 데이터의 읽기/쓰기/파티셔닝 담당."""

    def __init__(
        self, base_path: str | Path = "data/", compression: str = "snappy"
    ) -> None:
        self._base = Path(base_path)
        self._compression = compression

    @property
    def base_path(self) -> Path:
        return self._base

    async def read(
        self,
        symbol: str,
        timeframe: str,
        start: str | None = None,
        end: str | None = None,
        limit: int | None = None,
    ) -> pl.DataFrame:
        """Parquet에서 OHLCV 데이터 읽기.

        Args:
            symbol: 종목 코드
            timeframe: 타임프레임 (1m, 5m, 15m, 1h, 1d)
            start: 시작 시간 (ISO 형식, inclusive)
            end: 종료 시간 (ISO 형식, inclusive)
            limit: 최근 N건만 반환
        """
        path = self._base / "ohlcv" / timeframe / symbol
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

        if start:
            df = df.filter(
                pl.col("timestamp") >= pl.lit(start).str.to_datetime(time_zone="UTC")
            )
        if end:
            df = df.filter(
                pl.col("timestamp") <= pl.lit(end).str.to_datetime(time_zone="UTC")
            )

        df = df.sort("timestamp")

        if limit:
            df = df.tail(limit)

        return df

    async def write(self, symbol: str, timeframe: str, data: pl.DataFrame) -> None:
        """데이터를 Parquet에 기록. 월별 파티셔닝, 중복 제거(merge)."""
        if data.is_empty():
            return

        path = self._base / "ohlcv" / timeframe / symbol
        path.mkdir(parents=True, exist_ok=True)

        # 월별 파티셔닝
        month_col = data["timestamp"].dt.strftime("%Y-%m")
        data_with_month = data.with_columns(month_col.alias("_month"))

        for month_val in data_with_month["_month"].unique().to_list():
            group = data_with_month.filter(pl.col("_month") == month_val).drop("_month")
            filepath = path / f"{month_val}.parquet"

            if filepath.exists():
                try:
                    existing = pl.read_parquet(filepath)
                    merged = (
                        pl.concat([existing, group])
                        .unique(subset=["timestamp"])
                        .sort("timestamp")
                    )
                    merged.write_parquet(str(filepath), compression=self._compression)
                except Exception:
                    logger.warning(
                        "Failed to merge with existing file: %s, overwriting", filepath
                    )
                    group.sort("timestamp").write_parquet(
                        str(filepath), compression=self._compression
                    )
            else:
                group.sort("timestamp").write_parquet(
                    str(filepath), compression=self._compression
                )

        logger.debug("Wrote %d rows for %s/%s", len(data), symbol, timeframe)

    async def append(self, symbol: str, timeframe: str, rows: list[dict]) -> None:
        """버퍼 데이터를 기존 Parquet에 추가."""
        df = pl.DataFrame(rows)
        await self.write(symbol, timeframe, df)

    def list_symbols(self, timeframe: str = "1d") -> list[str]:
        """보유 데이터의 종목 목록."""
        path = self._base / "ohlcv" / timeframe
        if not path.exists():
            return []
        return sorted([d.name for d in path.iterdir() if d.is_dir()])

    def get_date_range(self, symbol: str, timeframe: str) -> tuple[str, str] | None:
        """종목의 데이터 기간 조회. (첫 파일 stem, 마지막 파일 stem) 반환."""
        path = self._base / "ohlcv" / timeframe / symbol
        files = sorted(path.glob("*.parquet")) if path.exists() else []
        if not files:
            return None
        return files[0].stem, files[-1].stem

    def get_storage_usage(self) -> dict[str, int]:
        """저장 용량 현황 (바이트). timeframe별 합산."""
        usage: dict[str, int] = {}
        ohlcv_path = self._base / "ohlcv"
        if not ohlcv_path.exists():
            return usage
        for tf_dir in ohlcv_path.iterdir():
            if tf_dir.is_dir():
                size = sum(f.stat().st_size for f in tf_dir.rglob("*.parquet"))
                usage[tf_dir.name] = size
        return usage

    async def validate(
        self,
        symbol: str,
        timeframe: str,
        fix: bool = False,
    ) -> dict:
        """Parquet 파일 무결성 검증.

        Args:
            symbol: 종목 코드
            timeframe: 타임프레임
            fix: True이면 손상 파일을 .corrupted 확장자로 이동

        Returns:
            {"symbol": str, "timeframe": str, "total": int,
             "valid": int, "corrupted": int, "corrupted_files": list[str]}
        """
        path = self._base / "ohlcv" / timeframe / symbol
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

    def delete_file(self, symbol: str, timeframe: str, month: str) -> bool:
        """특정 Parquet 파일 삭제. 성공 여부 반환."""
        filepath = self._base / "ohlcv" / timeframe / symbol / f"{month}.parquet"
        if filepath.exists():
            filepath.unlink()
            logger.info("Deleted parquet file: %s", filepath)
            return True
        return False
