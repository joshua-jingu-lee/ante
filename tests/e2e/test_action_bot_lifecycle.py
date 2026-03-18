"""E2E 테스트 — 봇 라이프사이클 액션.

봇 생성 → 시작 → 중지 → 삭제 전체 흐름을 검증한다.
각 상태 전환 후 API 교차 검증을 포함한다.

Note: 프론트엔드 봇 생성 폼이 strategy_name/mode/budget/symbols 필드를
전송하지만, 백엔드 BotCreateRequest는 strategy_id/bot_type만 수용하므로
UI를 통한 생성은 422 에러가 발생한다. 생성은 API 직접 호출로 수행하고,
이후 시작/중지/삭제 액션을 UI를 통해 검증한다.
"""

from __future__ import annotations

import httpx
import pytest
from playwright.sync_api import Page, expect

SCENARIO = "action-bot-lifecycle"

pytestmark = [pytest.mark.e2e, pytest.mark.playwright]

# 테스트 전반에서 공유할 봇 식별자
BOT_ID = "lifecycle-test-01"
BOT_NAME = "라이프사이클 테스트 봇"
STRATEGY_ID = "sma-cross"


# ── 헬퍼 ─────────────────────────────────────────────


def _go_to_bots(page: Page, base_url: str) -> None:
    """봇 관리 페이지로 이동."""
    page.goto(f"{base_url}/bots", wait_until="commit")
    page.wait_for_timeout(2000)


def _bot_card(page: Page, bot_name: str):  # noqa: ANN202
    """봇 이름으로 카드 영역(border rounded-lg)을 찾는다."""
    xpath = (
        "xpath=ancestor::div["
        "contains(@class,'rounded-lg') and contains(@class,'border')]"
    )
    return page.get_by_text(bot_name, exact=True).locator(xpath).first


def _api_get_bot(api_url: str, bot_id: str) -> dict:
    """API를 통해 봇 정보를 조회한다."""
    resp = httpx.get(f"{api_url}/bots/{bot_id}", timeout=10)
    assert resp.status_code == 200, f"GET /api/bots/{bot_id} 실패: {resp.status_code}"
    data = resp.json()
    # API 응답은 {"bot": {...}} 형태
    return data.get("bot", data)


def _ensure_bot_created(api_url: str) -> None:
    """테스트 대상 봇이 생성되어 있지 않으면 API로 생성한다."""
    check = httpx.get(f"{api_url}/bots/{BOT_ID}", timeout=10)
    if check.status_code == 200:
        return
    resp = httpx.post(
        f"{api_url}/bots",
        json={
            "bot_id": BOT_ID,
            "strategy_id": STRATEGY_ID,
            "name": BOT_NAME,
            "bot_type": "paper",
            "interval_seconds": 60,
        },
        timeout=10,
    )
    assert resp.status_code == 201, f"봇 생성 실패: {resp.text}"


# ── 봇 생성 ──────────────────────────────────────────


class TestBotCreate:
    """봇 생성 플로우 검증."""

    def test_create_bot_via_api(
        self,
        authenticated_page,  # noqa: ANN001
        base_url: str,
        api_url: str,
    ) -> None:
        """API로 봇을 생성하고 봇 목록 UI에 비활성 섹션에 나타나는지 검증한다.

        Note: 프론트엔드 봇 생성 폼이 백엔드 BotCreateRequest와 필드가
        불일치하므로(strategy_name vs strategy_id, mode vs bot_type 등)
        API 직접 호출로 봇을 생성한 뒤 UI 반영을 확인한다.
        """
        page: Page = authenticated_page

        # API로 봇 생성
        _ensure_bot_created(api_url)

        # 봇 목록 페이지에서 카드 표시 확인
        _go_to_bots(page, base_url)
        card = _bot_card(page, BOT_NAME)
        expect(card).to_be_visible()
        expect(card.get_by_text("생성됨")).to_be_visible()
        expect(card.get_by_text("모의")).to_be_visible()

    def test_create_bot_api_cross_validation(
        self,
        authenticated_page,  # noqa: ANN001
        base_url: str,
        api_url: str,
    ) -> None:
        """생성된 봇의 상태를 API로 교차 검증한다."""
        _ensure_bot_created(api_url)
        bot = _api_get_bot(api_url, BOT_ID)

        assert bot["bot_id"] == BOT_ID
        assert bot["name"] == BOT_NAME
        assert bot["status"] == "created"
        assert bot["bot_type"] == "paper"


# ── 봇 시작 ──────────────────────────────────────────


class TestBotStart:
    """봇 시작 액션 검증."""

    def test_start_bot_changes_status_to_running(
        self,
        authenticated_page,  # noqa: ANN001
        base_url: str,
        api_url: str,
    ) -> None:
        """비활성 봇의 시작 버튼을 클릭하면 상태가 '실행 중'으로 바뀐다."""
        page: Page = authenticated_page
        _ensure_bot_created(api_url)
        _go_to_bots(page, base_url)

        # 봇 카드에서 시작 버튼 클릭
        card = _bot_card(page, BOT_NAME)
        expect(card).to_be_visible()
        card.get_by_role("button", name="시작").click()
        page.wait_for_timeout(2000)

        # 페이지 새로고침 후 상태 확인
        _go_to_bots(page, base_url)
        card = _bot_card(page, BOT_NAME)
        expect(card.get_by_text("실행 중")).to_be_visible()

    def test_start_bot_api_cross_validation(
        self,
        authenticated_page,  # noqa: ANN001
        base_url: str,
        api_url: str,
    ) -> None:
        """시작된 봇의 상태를 API로 교차 검증한다."""
        _ensure_bot_created(api_url)
        bot = _api_get_bot(api_url, BOT_ID)

        assert bot["status"] == "running"


# ── 봇 중지 ──────────────────────────────────────────


class TestBotStop:
    """봇 중지 액션 검증."""

    def test_stop_bot_via_modal(
        self,
        authenticated_page,  # noqa: ANN001
        base_url: str,
        api_url: str,
    ) -> None:
        """실행 중인 봇의 중지 버튼을 클릭하고 모달에서 확인하면
        상태가 '중지됨'으로 바뀐다.
        """
        page: Page = authenticated_page
        _ensure_bot_created(api_url)
        _go_to_bots(page, base_url)

        # 실행 중 섹션에서 봇 카드 찾기
        card = _bot_card(page, BOT_NAME)
        expect(card).to_be_visible()
        card.get_by_role("button", name="중지").click()
        page.wait_for_timeout(500)

        # 중지 모달 확인 (BotStopModal: h2 "봇 중지")
        expect(page.locator("h2", has_text="봇 중지")).to_be_visible()

        # 중지 확인 버튼 클릭 (모달 내 마지막 "중지" 버튼)
        page.get_by_role("button", name="중지").last.click()
        page.wait_for_timeout(2000)

        # 페이지 새로고침 후 상태 확인
        _go_to_bots(page, base_url)
        card = _bot_card(page, BOT_NAME)
        expect(card.get_by_text("중지됨")).to_be_visible()

    def test_stop_bot_api_cross_validation(
        self,
        authenticated_page,  # noqa: ANN001
        base_url: str,
        api_url: str,
    ) -> None:
        """중지된 봇의 상태를 API로 교차 검증한다."""
        _ensure_bot_created(api_url)
        bot = _api_get_bot(api_url, BOT_ID)

        assert bot["status"] == "stopped"


# ── 봇 삭제 ──────────────────────────────────────────


class TestBotDelete:
    """봇 삭제 액션 검증."""

    def test_delete_bot_via_modal(
        self,
        authenticated_page,  # noqa: ANN001
        base_url: str,
        api_url: str,
    ) -> None:
        """중지된 봇의 삭제 버튼을 클릭하고 모달에서 확인하면 봇이 목록에서 사라진다."""
        page: Page = authenticated_page
        _ensure_bot_created(api_url)
        _go_to_bots(page, base_url)

        # 비활성 섹션에서 봇 카드 찾기
        card = _bot_card(page, BOT_NAME)
        expect(card).to_be_visible()
        card.get_by_role("button", name="삭제").click()
        page.wait_for_timeout(500)

        # 삭제 모달 확인 (BotDeleteModal: h2 "봇 삭제")
        expect(page.locator("h2", has_text="봇 삭제")).to_be_visible()

        # 삭제 확인 버튼 클릭 (보유 종목 없으므로 버튼 텍스트 "삭제")
        page.get_by_role("button", name="삭제").last.click()
        page.wait_for_timeout(2000)

        # 페이지 새로고침 후 목록에서 사라졌는지 확인
        _go_to_bots(page, base_url)
        expect(page.get_by_text(BOT_NAME)).not_to_be_visible()

    def test_delete_bot_api_cross_validation(
        self,
        authenticated_page,  # noqa: ANN001
        base_url: str,
        api_url: str,
    ) -> None:
        """삭제된 봇을 API로 조회하면 404 또는 deleted 상태임을 검증한다."""
        resp = httpx.get(f"{api_url}/bots/{BOT_ID}", timeout=10)

        # 봇이 삭제되었으므로 404이거나 status가 deleted여야 한다
        if resp.status_code == 200:
            data = resp.json()
            bot = data.get("bot", data)
            assert bot["status"] == "deleted", (
                f"삭제된 봇의 status가 'deleted'여야 하지만 '{bot['status']}'임"
            )
        else:
            assert resp.status_code == 404, (
                f"삭제된 봇 조회 시 404여야 하지만 {resp.status_code}를 반환함"
            )
