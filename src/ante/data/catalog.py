"""Data Pipeline — 보유 데이터 탐색 인터페이스."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ante.data.schemas import OHLCV_SCHEMA, TIMEFRAMES

if TYPE_CHECKING:
    from ante.data.store import ParquetStore


class DataCatalog:
    """보유 데이터 탐색 인터페이스. CLI `ante data list/schema`에서 사용."""

    def __init__(self, store: ParquetStore) -> None:
        self._store = store

    def list_datasets(self) -> list[dict]:
        """보유 데이터셋 목록. 종목×타임프레임 조합."""
        datasets = []
        for tf in TIMEFRAMES:
            symbols = self._store.list_symbols(tf)
            for symbol in symbols:
                date_range = self._store.get_date_range(symbol, tf)
                datasets.append(
                    {
                        "symbol": symbol,
                        "timeframe": tf,
                        "start": date_range[0] if date_range else None,
                        "end": date_range[1] if date_range else None,
                    }
                )
        return datasets

    def get_schema(
        self, symbol: str | None = None, timeframe: str | None = None
    ) -> dict:
        """데이터셋 스키마 조회. 현재는 OHLCV 스키마 고정 반환."""
        return {k: str(v) for k, v in OHLCV_SCHEMA.items()}

    def delete_dataset(self, symbol: str, timeframe: str) -> bool:
        """데이터셋(종목×타임프레임) 전체 삭제. 삭제 성공 여부 반환."""
        import shutil

        path = self._store._base / "ohlcv" / timeframe / symbol
        if not path.exists():
            return False
        shutil.rmtree(path)
        return True

    def get_storage_summary(self) -> dict:
        """저장 용량 요약."""
        usage = self._store.get_storage_usage()
        total = sum(usage.values())
        return {
            "total_bytes": total,
            "total_mb": round(total / 1024 / 1024, 1),
            "by_timeframe": {
                tf: round(size / 1024 / 1024, 1) for tf, size in usage.items()
            },
        }
