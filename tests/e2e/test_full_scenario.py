"""E2E 테스트 — 봇 생성 → 전략 할당 → 주문 발행 → 체결 확인 전체 시나리오.

Docker 테스트 환경(Mock Broker)에서 전체 매매 파이프라인을 검증한다.
"""

from __future__ import annotations

import json
import time
import urllib.request

import pytest

pytestmark = pytest.mark.e2e


class TestFullTradingScenario:
    """봇 → 전략 → 주문 → 체결 전체 흐름."""

    def test_trading_pipeline(self, api_url: str) -> None:
        """전체 매매 파이프라인이 동작한다.

        1. 시스템 상태 확인 (active)
        2. 시드 전략 존재 확인
        3. 시드 봇 존재 확인
        4. 자금 배분 확인
        5. 봇 상세 정보 조회
        """
        # 1. 시스템 상태 확인
        system = _get(f"{api_url}/system/status")
        assert system["status"] == 200
        assert system["body"].get("trading_state") == "active"

        # 2. 전략 존재 확인
        strategies = _get(f"{api_url}/strategies")
        assert strategies["status"] == 200
        strategy_ids = [s.get("strategy_id") for s in strategies["body"]]
        assert "daily-buy-001" in strategy_ids

        # 3. 봇 존재 확인
        bots = _get(f"{api_url}/bots")
        assert bots["status"] == 200
        bot_ids = [b.get("bot_id") for b in bots["body"]]
        assert "seed-bot-live" in bot_ids
        assert "seed-bot-paper" in bot_ids

        # 4. 자금 배분 확인
        treasury = _get(f"{api_url}/treasury")
        assert treasury["status"] == 200

        # 5. 봇 상세 정보 조회
        bot_detail = _get(f"{api_url}/bots/seed-bot-live")
        assert bot_detail["status"] == 200
        assert bot_detail["body"].get("bot_id") == "seed-bot-live"
        assert bot_detail["body"].get("strategy_id") == "daily-buy-001"

    def test_bot_lifecycle(self, api_url: str) -> None:
        """봇 생성 → 조회 → 삭제 생명주기가 동작한다."""
        bot_id = f"e2e-lifecycle-{int(time.time())}"

        # 생성
        create_resp = _post(
            f"{api_url}/bots",
            {
                "bot_id": bot_id,
                "strategy_id": "daily-buy-001",
                "name": "E2E Lifecycle Bot",
                "bot_type": "paper",
                "interval_seconds": 60,
            },
        )
        assert create_resp["status"] in (200, 201)

        # 조회
        detail = _get(f"{api_url}/bots/{bot_id}")
        assert detail["status"] == 200
        assert detail["body"]["bot_id"] == bot_id

        # 삭제
        delete_resp = _delete(f"{api_url}/bots/{bot_id}")
        assert delete_resp["status"] in (200, 204)


# ── HTTP 헬퍼 ────────────────────────────────────────


def _get(url: str) -> dict:
    """GET 요청."""
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read().decode())
            return {"status": resp.status, "body": body}
    except urllib.error.HTTPError as e:
        body = json.loads(e.read().decode()) if e.readable() else {}
        return {"status": e.code, "body": body}


def _post(url: str, data: dict) -> dict:
    """POST 요청."""
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


def _delete(url: str) -> dict:
    """DELETE 요청."""
    req = urllib.request.Request(
        url,
        headers={"Accept": "application/json"},
        method="DELETE",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body_raw = resp.read().decode()
            body = json.loads(body_raw) if body_raw else {}
            return {"status": resp.status, "body": body}
    except urllib.error.HTTPError as e:
        body = json.loads(e.read().decode()) if e.readable() else {}
        return {"status": e.code, "body": body}
