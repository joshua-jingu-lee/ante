"""Dataset read/delete helpers shared by CLI surfaces."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any, Literal

from ante.data.schemas import TIMEFRAMES
from ante.data.store import ParquetStore, _is_safe_path_segment

logger = logging.getLogger(__name__)

DataType = Literal["ohlcv", "fundamental"]


def validate_dataset_filters(
    *,
    timeframe: str | None = None,
    data_type: str | None = None,
) -> DataType | None:
    """Validate dataset list filters and return normalized data_type."""
    if timeframe is not None and timeframe not in TIMEFRAMES:
        raise ValueError(
            f"허용되지 않은 timeframe 값: {timeframe} (허용: {', '.join(TIMEFRAMES)})"
        )
    if data_type is None:
        return None
    if data_type not in ("ohlcv", "fundamental"):
        raise ValueError("data_type은 ohlcv 또는 fundamental이어야 합니다")
    if data_type == "fundamental" and timeframe is not None:
        raise ValueError(
            "fundamental 데이터셋에는 timeframe 필터를 적용할 수 없습니다 "
            "(timeframe은 OHLCV 전용)"
        )
    return data_type  # type: ignore[return-value]


def list_datasets(
    store: ParquetStore,
    *,
    symbol: str | None = None,
    timeframe: str | None = None,
    data_type: DataType | None = None,
    offset: int = 0,
    limit: int = 50,
) -> dict[str, Any]:
    """Return dataset metadata with filters and pagination."""
    validate_dataset_filters(timeframe=timeframe, data_type=data_type)
    datasets: list[dict[str, Any]] = []

    if data_type is None or data_type == "fundamental":
        for sym in store.list_symbols(data_type="fundamental"):
            if symbol and sym != symbol:
                continue
            datasets.append(
                {
                    "id": f"{sym}__fundamental",
                    "symbol": sym,
                    "timeframe": "",
                    "data_type": "fundamental",
                }
            )

    if data_type is None or data_type == "ohlcv":
        tf_list = [timeframe] if timeframe else TIMEFRAMES
        for tf in tf_list:
            for sym in store.list_symbols(tf):
                if symbol and sym != symbol:
                    continue
                datasets.append(
                    {
                        "id": f"{sym}__{tf}",
                        "symbol": sym,
                        "timeframe": tf,
                        "data_type": "ohlcv",
                    }
                )

    total = len(datasets)
    paged = datasets[offset : offset + limit]
    for item in paged:
        dt = item["data_type"]
        tf = item["timeframe"]
        sym = item["symbol"]
        try:
            dr = store.get_date_range(sym, tf if dt == "ohlcv" else "", data_type=dt)
            item["start_date"] = dr[0] if dr else None
            item["end_date"] = dr[1] if dr else None
        except Exception:
            item["start_date"] = None
            item["end_date"] = None
        item["row_count"] = None
        item["file_size"] = None

    return {"items": paged, "total": total}


def parse_dataset_id(dataset_id: str) -> tuple[str, str, DataType, str]:
    """Parse and validate ``{symbol}__{timeframe}`` dataset IDs."""
    parts = dataset_id.split("__", 1)
    if len(parts) != 2:
        raise ValueError("dataset_id는 '{symbol}__{timeframe}' 형식이어야 합니다")

    symbol, timeframe = parts
    if not _is_safe_path_segment(symbol) or not _is_safe_path_segment(timeframe):
        raise ValueError(
            "dataset_id의 symbol/timeframe에 허용되지 않는 "
            "경로 문자가 포함되어 있습니다"
        )

    data_type: DataType = "fundamental" if timeframe == "fundamental" else "ohlcv"
    tf_for_store = "" if data_type == "fundamental" else timeframe
    return symbol, timeframe, data_type, tf_for_store


def get_dataset_detail(store: ParquetStore, dataset_id: str) -> dict[str, Any]:
    """Return dataset metadata plus a five-row preview."""
    symbol, timeframe, data_type, tf_for_store = parse_dataset_id(dataset_id)
    path = store.resolve_path(symbol, tf_for_store, data_type=data_type)
    if not path.exists():
        raise FileNotFoundError("데이터셋을 찾을 수 없습니다")

    date_range = store.get_date_range(symbol, tf_for_store, data_type=data_type)
    row_count = store.get_row_count(symbol, tf_for_store, data_type=data_type)
    file_size = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    dataset_meta = {
        "id": dataset_id,
        "symbol": symbol,
        "timeframe": "" if data_type == "fundamental" else timeframe,
        "data_type": data_type,
        "start_date": date_range[0] if date_range else None,
        "end_date": date_range[1] if date_range else None,
        "row_count": row_count,
        "file_size": file_size,
    }

    preview: list[dict[str, Any]] = []
    try:
        df = store.read(symbol, tf_for_store, limit=5, data_type=data_type)
        if not df.is_empty():
            for row in df.iter_rows(named=True):
                record: dict[str, Any] = {}
                for key, value in row.items():
                    if hasattr(value, "isoformat"):
                        record[key] = value.isoformat()
                    elif isinstance(value, float) and value != value:
                        record[key] = None
                    else:
                        record[key] = value
                preview.append(record)
    except Exception:
        logger.warning("데이터셋 미리보기 로드 실패: %s", dataset_id, exc_info=True)

    return {"dataset": dataset_meta, "preview": preview}


def delete_dataset(
    store: ParquetStore,
    dataset_id: str,
    *,
    data_type: DataType | None = None,
) -> dict[str, Any]:
    """Delete a dataset directory after path-safe ID validation."""
    symbol, timeframe, derived_type, tf_for_store = parse_dataset_id(dataset_id)
    if data_type is not None and data_type != derived_type:
        raise ValueError(
            f"data_type='{data_type}'가 dataset_id에서 파생된 유형 "
            f"'{derived_type}'와 일치하지 않습니다"
        )
    path = store.resolve_path(symbol, tf_for_store, data_type=derived_type)
    if not path.exists():
        raise FileNotFoundError("데이터셋을 찾을 수 없습니다")
    shutil.rmtree(path)
    return {
        "dataset_id": dataset_id,
        "symbol": symbol,
        "timeframe": "" if derived_type == "fundamental" else timeframe,
        "data_type": derived_type,
        "path": str(Path(path)),
        "deleted": True,
    }
