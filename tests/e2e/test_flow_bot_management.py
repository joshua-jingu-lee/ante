"""E2E 테스트 — 봇 관리 플로우.

봇 목록 조회, 상세 페이지, 네비게이션 등
봇 관리의 핵심 사용자 시나리오를 검증한다.
"""

from __future__ import annotations

import re

import pytest
from playwright.sync_api import Page, expect

SCENARIO = "bot-management"

pytestmark = [pytest.mark.e2e, pytest.mark.playwright]


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


# ── 봇 목록 페이지 ───────────────────────────────────


class TestBotListPage:
    """봇 목록 페이지 검증."""

    def test_sections_displayed(
        self,
        authenticated_page,
        base_url: str,  # noqa: ANN001
    ) -> None:
        """'실행 중'과 '비활성' 섹션 제목이 표시된다."""
        _go_to_bots(authenticated_page, base_url)

        # 섹션 제목 (건수 뱃지 포함): "실행 중 1", "비활성 3"
        expect(
            authenticated_page.get_by_text("실행 중", exact=False).first
        ).to_be_visible()
        expect(
            authenticated_page.get_by_text("비활성", exact=False).first
        ).to_be_visible()

    def test_running_section_has_bot_b(
        self,
        authenticated_page,
        base_url: str,  # noqa: ANN001
    ) -> None:
        """실행 중 섹션에 봇 B(모멘텀 추세 봇)가 표시된다."""
        _go_to_bots(authenticated_page, base_url)

        expect(authenticated_page.get_by_text("모멘텀 추세 봇")).to_be_visible()

    def test_bot_b_card_details(
        self,
        authenticated_page,
        base_url: str,  # noqa: ANN001
    ) -> None:
        """봇 B 카드에 이름, 상태, 전략, 모드가 표시된다."""
        _go_to_bots(authenticated_page, base_url)

        page = authenticated_page
        card = _bot_card(page, "모멘텀 추세 봇")

        expect(card.get_by_text("실행 중", exact=True)).to_be_visible()
        expect(card.get_by_text("momentum-v2")).to_be_visible()
        expect(card.get_by_text("실전")).to_be_visible()

    def test_inactive_section_bot_a(
        self,
        authenticated_page,
        base_url: str,  # noqa: ANN001
    ) -> None:
        """비활성 섹션에 봇 A(SMA 크로스 봇, 생성됨)가 표시된다."""
        _go_to_bots(authenticated_page, base_url)

        page = authenticated_page
        card = _bot_card(page, "SMA 크로스 봇")

        expect(card.get_by_text("생성됨")).to_be_visible()
        expect(card.get_by_text("모의")).to_be_visible()

    def test_inactive_section_bot_c(
        self,
        authenticated_page,
        base_url: str,  # noqa: ANN001
    ) -> None:
        """비활성 섹션에 봇 C(평균회귀 실전 봇, 중지됨)가 표시된다."""
        _go_to_bots(authenticated_page, base_url)

        page = authenticated_page
        card = _bot_card(page, "평균회귀 실전 봇")

        expect(card.get_by_text("중지됨")).to_be_visible()
        expect(card.get_by_text("실전", exact=True).first).to_be_visible()

    def test_inactive_section_bot_d(
        self,
        authenticated_page,
        base_url: str,  # noqa: ANN001
    ) -> None:
        """비활성 섹션에 봇 D(오류 테스트 봇, 오류)가 표시된다."""
        _go_to_bots(authenticated_page, base_url)

        page = authenticated_page
        card = _bot_card(page, "오류 테스트 봇")

        expect(card.get_by_text("오류", exact=True)).to_be_visible()
        expect(card.get_by_text("모의")).to_be_visible()


# ── 봇 생성 ──────────────────────────────────────────


class TestBotCreate:
    """봇 생성 모달 검증."""

    def test_create_button_visible(
        self,
        authenticated_page,
        base_url: str,  # noqa: ANN001
    ) -> None:
        """봇 생성 버튼이 표시된다."""
        _go_to_bots(authenticated_page, base_url)

        expect(authenticated_page.get_by_role("button", name="봇 생성")).to_be_visible()


# ── 봇 상세 페이지 ───────────────────────────────────


class TestBotDetailPage:
    """봇 B 상세 페이지 검증."""

    def test_navigate_to_detail(
        self,
        authenticated_page,
        base_url: str,  # noqa: ANN001
    ) -> None:
        """봇 B의 ID 링크를 클릭하면 상세 페이지로 이동한다."""
        _go_to_bots(authenticated_page, base_url)
        page = authenticated_page

        # 봇 ID 링크 클릭
        page.get_by_text("bot-momentum-01").click()
        page.wait_for_timeout(2000)

        # URL 확인
        expect(page).to_have_url(re.compile(r"/bots/bot-momentum-01"))

        # 뒤로 가기 링크 확인
        expect(page.get_by_text("← 봇 관리")).to_be_visible()

    def test_detail_header(
        self,
        authenticated_page,
        base_url: str,  # noqa: ANN001
    ) -> None:
        """상세 페이지 헤더에 봇 이름과 상태가 표시된다."""
        page = authenticated_page
        page.goto(f"{base_url}/bots/bot-momentum-01", wait_until="commit")
        page.wait_for_timeout(2000)

        expect(page.get_by_text("모멘텀 추세 봇")).to_be_visible()
        expect(page.get_by_text("실행 중", exact=True).first).to_be_visible()
        expect(page.get_by_text("실전").first).to_be_visible()

    def test_detail_strategy_card(
        self,
        authenticated_page,
        base_url: str,  # noqa: ANN001
    ) -> None:
        """상세 페이지에 운용 전략 카드가 표시된다."""
        page = authenticated_page
        page.goto(f"{base_url}/bots/bot-momentum-01", wait_until="commit")
        page.wait_for_timeout(2000)

        expect(page.get_by_text("운용 전략")).to_be_visible()
        expect(page.get_by_text("momentum-v2").first).to_be_visible()

    def test_detail_execution_settings_card(
        self,
        authenticated_page,
        base_url: str,  # noqa: ANN001
    ) -> None:
        """상세 페이지에 실행 설정 카드가 표시된다."""
        page = authenticated_page
        page.goto(f"{base_url}/bots/bot-momentum-01", wait_until="commit")
        page.wait_for_timeout(2000)

        expect(page.get_by_text("실행 설정")).to_be_visible()
        expect(page.get_by_text("60초")).to_be_visible()

    def test_detail_budget_card(
        self,
        authenticated_page,
        base_url: str,  # noqa: ANN001
    ) -> None:
        """상세 페이지에 예산 카드가 표시된다."""
        page = authenticated_page
        page.goto(f"{base_url}/bots/bot-momentum-01", wait_until="commit")
        page.wait_for_timeout(2000)

        expect(page.get_by_role("heading", name="예산")).to_be_visible()
        expect(page.get_by_text("배정금액")).to_be_visible()

    def test_detail_positions_table(
        self,
        authenticated_page,
        base_url: str,  # noqa: ANN001
    ) -> None:
        """상세 페이지에 보유 종목 테이블이 표시된다."""
        page = authenticated_page
        page.goto(f"{base_url}/bots/bot-momentum-01", wait_until="commit")
        page.wait_for_timeout(2000)

        expect(page.get_by_text("보유 종목")).to_be_visible()

        # 테이블 컬럼 헤더
        expect(page.get_by_text("종목").first).to_be_visible()
        expect(page.get_by_text("수량").first).to_be_visible()
        expect(page.get_by_text("평균단가")).to_be_visible()

        # 보유 종목 데이터 (심볼 코드로 표시됨)
        expect(page.get_by_text("005930")).to_be_visible()
        expect(page.get_by_text("035420")).to_be_visible()

    def test_detail_execution_log(
        self,
        authenticated_page,
        base_url: str,  # noqa: ANN001
    ) -> None:
        """상세 페이지에 실행 로그 섹션이 표시된다."""
        page = authenticated_page
        page.goto(f"{base_url}/bots/bot-momentum-01", wait_until="commit")
        page.wait_for_timeout(2000)

        expect(page.get_by_text("실행 로그")).to_be_visible()

    def test_back_link_returns_to_list(
        self,
        authenticated_page,
        base_url: str,  # noqa: ANN001
    ) -> None:
        """뒤로 가기 링크를 클릭하면 봇 목록으로 돌아간다."""
        page = authenticated_page
        page.goto(f"{base_url}/bots/bot-momentum-01", wait_until="commit")
        page.wait_for_timeout(2000)

        page.get_by_text("← 봇 관리").click()
        page.wait_for_timeout(2000)

        expect(page).to_have_url(re.compile(r"/bots/?$"))
