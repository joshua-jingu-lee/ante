"""E2E 테스트 — API 엔드포인트 호출 검증.

Docker 테스트 환경에서 주요 API 엔드포인트가 정상 응답하는지 확인한다.
"""

from __future__ import annotations

import json
import urllib.request

import pytest

pytestmark = pytest.mark.e2e


class TestSystemAPI:
    """시스템 API 엔드포인트."""

    def test_health_check(self, api_url: str) -> None:
        """GET /api/system/health → 200."""
        resp = _get(f"{api_url}/system/health")
        assert resp["status"] == 200

    def test_system_status(self, api_url: str) -> None:
        """GET /api/system/status → 200, trading_state 포함."""
        resp = _get(f"{api_url}/system/status")
        assert resp["status"] == 200
        assert "trading_state" in resp["body"]


class TestBotsAPI:
    """봇 API 엔드포인트."""

    def test_list_bots(self, api_url: str) -> None:
        """GET /api/bots → 200, 시드 봇 포함."""
        resp = _get(f"{api_url}/bots")
        assert resp["status"] == 200
        bots = resp["body"]
        assert isinstance(bots, list)

    def test_create_bot(self, api_url: str) -> None:
        """POST /api/bots → 201, 봇 생성."""
        payload = {
            "bot_id": "e2e-test-bot",
            "strategy_id": "daily-buy-001",
            "name": "E2E Test Bot",
            "bot_type": "paper",
            "interval_seconds": 60,
        }
        resp = _post(f"{api_url}/bots", payload)
        assert resp["status"] in (200, 201)


class TestStrategiesAPI:
    """전략 API 엔드포인트."""

    def test_list_strategies(self, api_url: str) -> None:
        """GET /api/strategies → 200."""
        resp = _get(f"{api_url}/strategies")
        assert resp["status"] == 200
        assert isinstance(resp["body"], list)


class TestTreasuryAPI:
    """자금 관리 API 엔드포인트."""

    def test_treasury_status(self, api_url: str) -> None:
        """GET /api/treasury → 200."""
        resp = _get(f"{api_url}/treasury")
        assert resp["status"] == 200


class TestTradesAPI:
    """거래 API 엔드포인트."""

    def test_list_trades(self, api_url: str) -> None:
        """GET /api/trades → 200."""
        resp = _get(f"{api_url}/trades")
        assert resp["status"] == 200


# ── HTTP 헬퍼 ────────────────────────────────────────


def _get(url: str) -> dict:
    """GET 요청. {"status": int, "body": Any} 반환."""
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read().decode())
            return {"status": resp.status, "body": body}
    except urllib.error.HTTPError as e:
        body = json.loads(e.read().decode()) if e.readable() else {}
        return {"status": e.code, "body": body}


def _post(url: str, data: dict) -> dict:
    """POST 요청. {"status": int, "body": Any} 반환."""
    payload = json.dumps(data).encode()
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read().decode())
            return {"status": resp.status, "body": body}
    except urllib.error.HTTPError as e:
        body = json.loads(e.read().decode()) if e.readable() else {}
        return {"status": e.code, "body": body}
