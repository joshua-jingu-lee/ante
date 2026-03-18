"""데이터 관리 API."""

from __future__ import annotations

import logging
import shutil

from fastapi import APIRouter, Query, Request

logger = logging.getLogger(__name__)

router = APIRouter()

# 지원하는 데이터 유형
DATA_TYPES = ["ohlcv", "fundamental"]


@router.get("/datasets")
async def list_datasets(
    request: Request,
    data_type: str = Query("ohlcv", description="데이터 유형 (ohlcv, fundamental)"),
) -> dict:
    """보유 데이터셋 목록.

    data_type에 따라 해당 유형의 데이터셋만 반환한다.
    - ohlcv: 타임프레임별 OHLCV 시세 데이터
    - fundamental: 재무 데이터 (타임프레임 없음, 'krx' 고정)
    """
    store = getattr(request.app.state, "data_store", None)
    if store is None:
        return {"datasets": [], "data_type": data_type}

    datasets = []

    if data_type == "fundamental":
        symbols = store.list_symbols(data_type="fundamental")
        for symbol in symbols:
            date_range = store.get_date_range(symbol, "", data_type="fundamental")
            datasets.append(
                {
                    "symbol": symbol,
                    "timeframe": "",
                    "data_type": "fundamental",
                    "start": date_range[0] if date_range else None,
                    "end": date_range[1] if date_range else None,
                }
            )
    else:
        from ante.data.schemas import TIMEFRAMES

        for tf in TIMEFRAMES:
            symbols = store.list_symbols(tf)
            for symbol in symbols:
                date_range = store.get_date_range(symbol, tf)
                datasets.append(
                    {
                        "symbol": symbol,
                        "timeframe": tf,
                        "data_type": "ohlcv",
                        "start": date_range[0] if date_range else None,
                        "end": date_range[1] if date_range else None,
                    }
                )

    return {"datasets": datasets, "data_type": data_type}


@router.get("/schema")
async def get_data_schema(
    request: Request,
    data_type: str = Query("ohlcv", description="데이터 유형 (ohlcv, fundamental)"),
) -> dict:
    """데이터 스키마 조회. data_type에 따라 해당 스키마를 반환."""
    if data_type == "fundamental":
        from ante.data.schemas import FUNDAMENTAL_SCHEMA

        return {k: str(v) for k, v in FUNDAMENTAL_SCHEMA.items()}

    from ante.data.schemas import OHLCV_SCHEMA

    return {k: str(v) for k, v in OHLCV_SCHEMA.items()}


@router.get("/storage")
async def get_storage_summary(request: Request) -> dict:
    """저장 용량 현황."""
    store = getattr(request.app.state, "data_store", None)
    if store is None:
        return {"total_bytes": 0, "total_mb": 0.0, "by_timeframe": {}}
    usage = store.get_storage_usage()
    total = sum(usage.values())
    return {
        "total_bytes": total,
        "total_mb": round(total / 1024 / 1024, 1),
        "by_timeframe": {
            tf: round(size / 1024 / 1024, 1) for tf, size in usage.items()
        },
    }


@router.delete("/datasets/{dataset_id}", status_code=204)
async def delete_dataset(
    request: Request,
    dataset_id: str,
    data_type: str = Query("ohlcv", description="데이터 유형 (ohlcv, fundamental)"),
) -> None:
    """데이터셋 삭제.

    dataset_id 형식: "{symbol}__{timeframe}" (예: "005930__1d")
    fundamental의 경우: "{symbol}__fundamental" (예: "005930__fundamental")
    """
    from fastapi import HTTPException

    store = getattr(request.app.state, "data_store", None)
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
        path = store.base_path / "ohlcv" / timeframe / symbol

    if not path.exists():
        raise HTTPException(status_code=404, detail="데이터셋을 찾을 수 없습니다")
    shutil.rmtree(path)


@router.get("/feed-status")
async def get_feed_status(request: Request) -> dict:
    """Feed 파이프라인 상태 조회.

    Feed 초기화 여부, 소스별 체크포인트 현황, 최근 리포트 요약,
    API 키 설정 상태를 반환한다.
    """
    import json
    from pathlib import Path

    store = getattr(request.app.state, "data_store", None)
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
