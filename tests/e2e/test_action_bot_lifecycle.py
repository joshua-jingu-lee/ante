"""E2E 테스트 — 봇 라이프사이클 액션.

봇 생성 → 시작 → 중지 → 삭제 전체 흐름을 검증한다.
각 상태 전환 후 API 교차 검증을 포함한다.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

SCENARIO = "action-bot-lifecycle"

pytestmark = [pytest.mark.e2e, pytest.mark.playwright]

# 테스트 전반에서 공유할 봇 식별자
BOT_ID = "lifecycle-test-01"
BOT_NAME = "라이프사이클 테스트 봇"
STRATEGY_NAME = "SMA 크로스"


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


def _api_get_bot(page: Page, base_url: str, bot_id: str) -> dict:
    """API를 통해 봇 정보를 조회한다."""
    resp = page.request.get(f"{base_url}/api/bots/{bot_id}")
    assert resp.status == 200, f"GET /api/bots/{bot_id} 실패: {resp.status}"
    return resp.json()


# ── 봇 생성 ──────────────────────────────────────────


class TestBotCreate:
    """봇 생성 플로우 검증."""

    def test_create_bot_via_modal(
        self,
        authenticated_page,  # noqa: ANN001
        base_url: str,
    ) -> None:
        """봇 생성 모달을 통해 봇을 생성하고 비활성 섹션에 나타나는지 검증한다."""
        page: Page = authenticated_page
        _go_to_bots(page, base_url)

        # 봇 생성 버튼 클릭
        page.get_by_role("button", name="봇 생성").click()
        page.wait_for_timeout(500)

        # 모달이 열렸는지 확인
        expect(page.get_by_text("봇 생성", exact=True).last).to_be_visible()

        # 폼 입력: Bot ID
        page.locator('input[placeholder="bot-momentum-01"]').fill(BOT_ID)

        # 폼 입력: 이름
        page.locator('input[placeholder="모멘텀 돌파 봇"]').fill(BOT_NAME)

        # 폼 입력: 전략 선택
        page.locator("select").select_option(label=f"{STRATEGY_NAME} 1.0.0")

        # 봇 유형: 모의투자 (기본값이므로 확인만)
        expect(page.get_by_role("button", name="모의투자")).to_be_visible()

        # 배정예산 입력
        page.locator('input[placeholder="5000000"]').fill("1000000")

        # 생성 버튼 클릭
        page.get_by_role("button", name="생성").click()
        page.wait_for_timeout(2000)

        # 모달이 닫히고 봇이 목록에 나타나는지 확인
        _go_to_bots(page, base_url)
        card = _bot_card(page, BOT_NAME)
        expect(card).to_be_visible()
        expect(card.get_by_text("생성됨")).to_be_visible()
        expect(card.get_by_text("모의")).to_be_visible()

    def test_create_bot_api_cross_validation(
        self,
        authenticated_page,  # noqa: ANN001
        base_url: str,
    ) -> None:
        """생성된 봇의 상태를 API로 교차 검증한다."""
        page: Page = authenticated_page
        bot = _api_get_bot(page, base_url, BOT_ID)

        assert bot["bot_id"] == BOT_ID
        assert bot["name"] == BOT_NAME
        assert bot["status"] == "created"
        assert bot["mode"] == "paper"


# ── 봇 시작 ──────────────────────────────────────────


class TestBotStart:
    """봇 시작 액션 검증."""

    def test_start_bot_changes_status_to_running(
        self,
        authenticated_page,  # noqa: ANN001
        base_url: str,
    ) -> None:
        """비활성 봇의 시작 버튼을 클릭하면 상태가 '실행 중'으로 바뀐다."""
        page: Page = authenticated_page
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
    ) -> None:
        """시작된 봇의 상태를 API로 교차 검증한다."""
        page: Page = authenticated_page
        bot = _api_get_bot(page, base_url, BOT_ID)

        assert bot["status"] == "running"


# ── 봇 중지 ──────────────────────────────────────────


class TestBotStop:
    """봇 중지 액션 검증."""

    def test_stop_bot_via_modal(
        self,
        authenticated_page,  # noqa: ANN001
        base_url: str,
    ) -> None:
        """실행 중인 봇의 중지 버튼을 클릭하고 모달에서 확인하면
        상태가 '중지됨'으로 바뀐다.
        """
        page: Page = authenticated_page
        _go_to_bots(page, base_url)

        # 실행 중 섹션에서 봇 카드 찾기
        card = _bot_card(page, BOT_NAME)
        expect(card).to_be_visible()
        card.get_by_role("button", name="중지").click()
        page.wait_for_timeout(500)

        # 중지 모달 확인
        expect(page.get_by_text("봇 중지", exact=True)).to_be_visible()

        # 중지 확인 버튼 클릭
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
    ) -> None:
        """중지된 봇의 상태를 API로 교차 검증한다."""
        page: Page = authenticated_page
        bot = _api_get_bot(page, base_url, BOT_ID)

        assert bot["status"] == "stopped"


# ── 봇 삭제 ──────────────────────────────────────────


class TestBotDelete:
    """봇 삭제 액션 검증."""

    def test_delete_bot_via_modal(
        self,
        authenticated_page,  # noqa: ANN001
        base_url: str,
    ) -> None:
        """중지된 봇의 삭제 버튼을 클릭하고 모달에서 확인하면 봇이 목록에서 사라진다."""
        page: Page = authenticated_page
        _go_to_bots(page, base_url)

        # 비활성 섹션에서 봇 카드 찾기
        card = _bot_card(page, BOT_NAME)
        expect(card).to_be_visible()
        card.get_by_role("button", name="삭제").click()
        page.wait_for_timeout(500)

        # 삭제 모달 확인
        expect(page.get_by_text("봇 삭제", exact=True)).to_be_visible()

        # 삭제 확인 버튼 클릭 (보유 종목 없으므로 "삭제" 텍스트)
        page.get_by_role("button", name="삭제").last.click()
        page.wait_for_timeout(2000)

        # 페이지 새로고침 후 목록에서 사라졌는지 확인
        _go_to_bots(page, base_url)
        expect(page.get_by_text(BOT_NAME)).not_to_be_visible()

    def test_delete_bot_api_cross_validation(
        self,
        authenticated_page,  # noqa: ANN001
        base_url: str,
    ) -> None:
        """삭제된 봇을 API로 조회하면 404 또는 deleted 상태임을 검증한다."""
        page: Page = authenticated_page
        resp = page.request.get(f"{base_url}/api/bots/{BOT_ID}")

        # 봇이 삭제되었으므로 404이거나 status가 deleted여야 한다
        if resp.status == 200:
            bot = resp.json()
            assert bot["status"] == "deleted", (
                f"삭제된 봇의 status가 'deleted'여야 하지만 '{bot['status']}'임"
            )
        else:
            assert resp.status == 404, (
                f"삭제된 봇 조회 시 404여야 하지만 {resp.status}를 반환함"
            )
