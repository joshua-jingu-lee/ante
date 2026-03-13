"""Web API Pydantic 요청/응답 모델."""

from __future__ import annotations

from pydantic import BaseModel


class StatusResponse(BaseModel):
    """시스템 상태 응답."""

    status: str
    version: str = "0.1.0"


class ErrorResponse(BaseModel):
    """RFC 7807 Problem Details 에러 응답."""

    type: str = "/errors/internal"
    title: str = "Internal Server Error"
    detail: str = ""
    status: int = 500
    instance: str = ""


class ReportSubmitRequest(BaseModel):
    """리포트 제출 요청."""

    strategy_name: str
    strategy_version: str
    backtest_result: dict
    summary: str = ""
    recommendation: str = ""


class DataInjectRequest(BaseModel):
    """데이터 주입 요청 (JSON body)."""

    symbol: str
    timeframe: str = "1d"
    source: str = "external"
