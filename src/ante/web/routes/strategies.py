"""전략 관리 API."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.post("/validate")
async def validate_strategy(body: dict) -> dict:
    """전략 파일 정적 검증.

    Body: {"path": "/path/to/strategy.py"}
    """
    from ante.strategy.validator import StrategyValidator

    filepath = body.get("path", "")
    if not filepath:
        raise HTTPException(status_code=400, detail="path is required")

    path = Path(filepath)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Strategy file not found")

    validator = StrategyValidator()
    result = validator.validate(path)

    return {
        "valid": result.valid,
        "errors": result.errors,
        "warnings": result.warnings,
    }
