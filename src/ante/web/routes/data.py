"""데이터 관리 API."""

from __future__ import annotations

import asyncio
import logging
import shutil
from concurrent.futures import ThreadPoolExecutor
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from ante.web.deps import get_audit_logger_optional, get_data_store
from ante.web.schemas import (
    DataSchemaResponse,
    DatasetDetailResponse,
    DatasetListResponse,
    FeedStatusResponse,
    StorageSummaryResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# 지원하는 데이터 유형
DATA_TYPES = ["ohlcv", "fundamental"]

_executor = ThreadPoolExecutor(max_workers=2)


@router.get("/datasets", response_model=DatasetListResponse)
async def list_datasets(
    store: Annotated[Any | None, Depends(get_data_store)],
    symbol: str | None = None,
    timeframe: str | None = None,
    data_type: str | None = Query(
        None, description="데이터 유형 (ohlcv, fundamental, 미지정 시 전체)"
    ),
    offset: int = 0,
    limit: int = 50,
) -> dict:
    """보유 데이터셋 목록 (페이지네이션 지원).

    data_type 미지정 시 모든 유형을 반환하고, 지정 시 해당 유형만 반환한다.

    종목 목록만 먼저 수집하여 페이지네이션을 적용한 뒤,
    해당 페이지의 종목에 대해서만 date_range를 계산한다.
    row_count와 file_size는 상세 조회 전용이므로 기본값(0)을 반환한다.

    Returns:
        {items: [...], total: int}
    """
    if store is None:
        return {"items": [], "total": 0}

    loop = asyncio.get_event_loop()

    def _collect_datasets() -> list[dict[str, Any]]:
        """종목 목록만 수집 (동기 I/O를 스레드에서 수행)."""
        datasets: list[dict[str, Any]] = []

        # fundamental 수집 (data_type이 None 또는 "fundamental"일 때)
        if data_type is None or data_type == "fundamental":
            symbols = store.list_symbols(data_type="fundamental")
            for sym in symbols:
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

        # ohlcv 수집 (data_type이 None 또는 "ohlcv"일 때)
        if data_type is None or data_type == "ohlcv":
            from ante.data.schemas import TIMEFRAMES

            tf_list = [timeframe] if timeframe else TIMEFRAMES
            for tf in tf_list:
                syms = store.list_symbols(tf)
                for sym in syms:
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
        return datasets

    all_datasets = await loop.run_in_executor(_executor, _collect_datasets)
    total = len(all_datasets)

    # 페이지네이션 적용 후 해당 페이지만 date_range 계산
    paged = all_datasets[offset : offset + limit]

    def _enrich(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """페이지 내 항목에 date_range만 보강 (동기 I/O)."""
        for item in items:
            dt = item["data_type"]
            tf = item["timeframe"]
            sym = item["symbol"]
            try:
                dr = store.get_date_range(
                    sym, tf if dt == "ohlcv" else "", data_type=dt
                )
                item["start_date"] = dr[0] if dr else None
                item["end_date"] = dr[1] if dr else None
            except Exception:
                item["start_date"] = None
                item["end_date"] = None
            # row_count, file_size는 상세 조회 전용 — 목록에서는 기본값 반환
            item["row_count"] = 0
            item["file_size"] = 0
        return items

    enriched = await loop.run_in_executor(_executor, _enrich, paged)
    return {"items": enriched, "total": total}


@router.get("/datasets/{dataset_id}", response_model=DatasetDetailResponse)
async def get_dataset_detail(
    dataset_id: str,
    store: Annotated[Any | None, Depends(get_data_store)],
) -> dict:
    """데이터셋 상세 조회 (메타데이터 + 최근 5행 미리보기).

    dataset_id 형식: "{symbol}__{timeframe}" (예: "005930__1d")
    """
    if store is None:
        raise HTTPException(status_code=503, detail="Data store not available")

    parts = dataset_id.split("__", 1)
    if len(parts) != 2:
        raise HTTPException(
            status_code=400,
            detail="dataset_id는 '{symbol}__{timeframe}' 형식이어야 합니다",
        )

    symbol, timeframe = parts

    # fundamental 타입 판별
    is_fundamental = timeframe == "fundamental"
    data_type = "fundamental" if is_fundamental else "ohlcv"
    tf_for_store = "" if is_fundamental else timeframe

    # 존재 여부 확인
    path = store._resolve_path(symbol, tf_for_store, data_type=data_type)
    if not path.exists():
        raise HTTPException(status_code=404, detail="데이터셋을 찾을 수 없습니다")

    # 메타데이터
    date_range = store.get_date_range(symbol, tf_for_store, data_type=data_type)
    row_count = 0 if is_fundamental else store.get_row_count(symbol, tf_for_store)
    file_size = 0
    try:
        if path.exists():
            file_size = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    except Exception:
        pass

    dataset_meta = {
        "id": dataset_id,
        "symbol": symbol,
        "timeframe": timeframe if not is_fundamental else "",
        "data_type": data_type,
        "start_date": date_range[0] if date_range else None,
        "end_date": date_range[1] if date_range else None,
        "row_count": row_count,
        "file_size": file_size,
    }

    # 최근 5행 미리보기
    preview: list[dict[str, Any]] = []
    try:
        df = store.read(symbol, tf_for_store, limit=5, data_type=data_type)
        if not df.is_empty():
            # DataFrame → list[dict] 변환 (날짜/시간 → ISO 문자열)
            for row in df.iter_rows(named=True):
                record: dict[str, Any] = {}
                for k, v in row.items():
                    if hasattr(v, "isoformat"):
                        record[k] = v.isoformat()
                    elif isinstance(v, float) and (v != v):  # NaN check
                        record[k] = None
                    else:
                        record[k] = v
                preview.append(record)
    except Exception:
        logger.warning("데이터셋 미리보기 로드 실패: %s", dataset_id)

    return {"dataset": dataset_meta, "preview": preview}


@router.get("/schema", response_model=DataSchemaResponse)
async def get_data_schema(
    data_type: str = Query("ohlcv", description="데이터 유형 (ohlcv, fundamental)"),
) -> dict:
    """데이터 스키마 조회. data_type에 따라 해당 스키마를 반환."""
    if data_type == "fundamental":
        from ante.data.schemas import FUNDAMENTAL_SCHEMA

        return {k: str(v) for k, v in FUNDAMENTAL_SCHEMA.items()}

    from ante.data.schemas import OHLCV_SCHEMA

    return {k: str(v) for k, v in OHLCV_SCHEMA.items()}


@router.get("/storage", response_model=StorageSummaryResponse)
async def get_storage_summary(
    store: Annotated[Any | None, Depends(get_data_store)],
) -> dict:
    """저장 용량 현황."""
    if store is None:
        return {
            "total_bytes": 0,
            "total_mb": 0.0,
            "by_timeframe": {},
            "by_data_type": {},
        }
    usage = store.get_storage_usage()
    total = sum(usage.values())

    # 유형별 용량 집계: ohlcv = timeframe 키들의 합, 나머지는 그대로
    ohlcv_keys = {"fundamental", "tick"}
    ohlcv_total = sum(v for k, v in usage.items() if k not in ohlcv_keys)
    by_data_type: dict[str, float] = {}
    if ohlcv_total > 0:
        by_data_type["ohlcv"] = round(ohlcv_total / 1024 / 1024, 1)
    if usage.get("fundamental", 0) > 0:
        by_data_type["fundamental"] = round(usage["fundamental"] / 1024 / 1024, 1)

    return {
        "total_bytes": total,
        "total_mb": round(total / 1024 / 1024, 1),
        "by_timeframe": {
            tf: round(size / 1024 / 1024, 1) for tf, size in usage.items()
        },
        "by_data_type": by_data_type,
    }


@router.delete(
    "/datasets/{dataset_id}",
    status_code=204,
    responses={
        400: {"description": "Invalid dataset_id format"},
        404: {"description": "Dataset not found"},
        503: {"description": "Data store not available"},
    },
)
async def delete_dataset(
    dataset_id: str,
    request: Request,
    store: Annotated[Any | None, Depends(get_data_store)],
    audit_logger: Annotated[Any | None, Depends(get_audit_logger_optional)],
    data_type: str = Query("ohlcv", description="데이터 유형 (ohlcv, fundamental)"),
) -> None:
    """데이터셋 삭제.

    dataset_id 형식: "{symbol}__{timeframe}" (예: "005930__1d")
    fundamental의 경우: "{symbol}__fundamental" (예: "005930__fundamental")
    """
    if store is None:
        raise HTTPException(status_code=503, detail="Data store not available")

    parts = dataset_id.split("__", 1)
    if len(parts) != 2:
        raise HTTPException(
            status_code=400,
            detail="dataset_id는 '{symbol}__{timeframe}' 형식이어야 합니다",
        )

    symbol, timeframe = parts

    if data_type == "fundamental":
        path = store._resolve_path(symbol, "", data_type="fundamental")
    else:
        path = store._resolve_path(symbol, timeframe, data_type="ohlcv")

    if not path.exists():
        raise HTTPException(status_code=404, detail="데이터셋을 찾을 수 없습니다")
    shutil.rmtree(path)

    if audit_logger:
        await audit_logger.log(
            member_id=getattr(request.state, "member_id", "anonymous"),
            action="data.delete_dataset",
            resource=f"dataset:{dataset_id}",
            ip=request.client.host if request.client else "",
        )


@router.get("/feed-status", response_model=FeedStatusResponse)
async def get_feed_status(
    store: Annotated[Any | None, Depends(get_data_store)],
) -> dict:
    """Feed 파이프라인 상태 조회.

    Feed 초기화 여부, 소스별 체크포인트 현황, 최근 리포트 요약,
    API 키 설정 상태를 반환한다.
    """
    import json
    from pathlib import Path

    data_path: Path | None = getattr(store, "base_path", None) if store else None

    result: dict = {
        "initialized": False,
        "checkpoints": [],
        "recent_reports": [],
        "api_keys": [],
    }

    if data_path is None:
        return result

    try:
        from ante.feed.config import FeedConfig

        config = FeedConfig(data_path)
        result["initialized"] = config.is_initialized()

        if not result["initialized"]:
            # 미초기화 상태에서도 API 키 상태는 반환
            result["api_keys"] = config.check_api_keys()
            return result

        # 체크포인트 현황
        checkpoint_dir = config.feed_dir / "checkpoints"
        if checkpoint_dir.exists():
            for cp_file in sorted(checkpoint_dir.glob("*.json")):
                try:
                    cp_data = json.loads(cp_file.read_text(encoding="utf-8"))
                    result["checkpoints"].append(cp_data)
                except (json.JSONDecodeError, OSError):
                    logger.warning("체크포인트 파일 읽기 실패: %s", cp_file)

        # 최근 리포트 (최대 5개)
        reports_dir = config.feed_dir / "reports"
        if reports_dir.exists():
            report_files = sorted(reports_dir.glob("*.json"), reverse=True)[:5]
            for rpt_file in report_files:
                try:
                    rpt_data = json.loads(rpt_file.read_text(encoding="utf-8"))
                    result["recent_reports"].append(rpt_data)
                except (json.JSONDecodeError, OSError):
                    logger.warning("리포트 파일 읽기 실패: %s", rpt_file)

        # API 키 상태
        result["api_keys"] = config.check_api_keys()

    except Exception:
        logger.exception("Feed 상태 조회 실패")

    return result
