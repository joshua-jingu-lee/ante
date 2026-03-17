"""E2E 테스트 — 멤버 관리 페이지 흐름.

Human/Agent 멤버 목록 조회, 카드 내용, 상태 필터를 검증한다.
"""

from __future__ import annotations

import re

import pytest
from playwright.sync_api import Page, expect

SCENARIO = "member-management"

pytestmark = [pytest.mark.e2e, pytest.mark.playwright]


# ── 헬퍼 ─────────────────────────────────────────────


def _go_to_members(page: Page, base_url: str) -> None:
    """멤버 관리 페이지로 이동 후 렌더링 안정화 대기."""
    page.goto(f"{base_url}/members", wait_until="commit")
    page.wait_for_timeout(2000)


def _member_card(page: Page, name: str):  # noqa: ANN202
    """멤버 이름으로 카드 영역(border rounded-lg)을 찾는다."""
    xpath = (
        "xpath=ancestor::div["
        "contains(@class,'rounded-lg') and contains(@class,'border')]"
    )
    return page.get_by_text(name, exact=True).locator(xpath).first


# ── 페이지 기본 구조 ────────────────────────────────


class TestMemberListPage:
    """멤버 관리 페이지 — 기본 구조 및 목록 검증."""

    def test_page_title(self, authenticated_page, base_url: str) -> None:
        """헤더에 '멤버 관리' 타이틀이 표시된다."""
        _go_to_members(authenticated_page, base_url)

        heading = authenticated_page.locator("h1", has_text="멤버 관리")
        expect(heading).to_be_visible()

    def test_human_section_visible(self, authenticated_page, base_url: str) -> None:
        """Human 멤버 섹션이 표시되고 인원수 뱃지가 2이다."""
        _go_to_members(authenticated_page, base_url)

        section = authenticated_page.get_by_text("Human 멤버", exact=False).first
        expect(section).to_be_visible()

        # 카운트 뱃지에 "2" 표시
        badge = section.locator("span", has_text="2")
        expect(badge).to_be_visible()

    def test_agent_section_visible(self, authenticated_page, base_url: str) -> None:
        """Agent 멤버 섹션이 표시되고 인원수 뱃지가 6이다."""
        _go_to_members(authenticated_page, base_url)

        section = authenticated_page.get_by_text("Agent 멤버", exact=False).first
        expect(section).to_be_visible()

        badge = section.locator("span", has_text="6")
        expect(badge).to_be_visible()

    def test_owner_card_has_crown_and_master_role(
        self, authenticated_page, base_url: str
    ) -> None:
        """owner 카드에 아바타 이모지와 Master 역할 뱃지가 표시된다."""
        _go_to_members(authenticated_page, base_url)

        card = _member_card(authenticated_page, "Owner")
        expect(card).to_be_visible()
        # Master 역할 뱃지
        expect(card.get_by_text("Master", exact=True)).to_be_visible()
        # member_id (소문자 "owner" — 대문자 "Owner"와 구분)
        expect(card.locator(".font-mono", has_text="owner")).to_be_visible()

    def test_admin_card_visible(self, authenticated_page, base_url: str) -> None:
        """admin-01 카드에 이름, Admin 뱃지, 활성 상태가 표시된다."""
        _go_to_members(authenticated_page, base_url)

        card = _member_card(authenticated_page, "운영 관리자")
        expect(card).to_be_visible()
        expect(card.get_by_text("Admin", exact=True)).to_be_visible()
        expect(card.get_by_text("admin-01")).to_be_visible()
        expect(card.get_by_text("활성")).to_be_visible()

    def test_agent_card_content(self, authenticated_page, base_url: str) -> None:
        """Agent 카드에 이모지, 이름, ID, 소속, 상태 뱃지가 표시된다."""
        _go_to_members(authenticated_page, base_url)

        card = _member_card(authenticated_page, "전략 리서치 1호")
        expect(card).to_be_visible()
        # 이모지
        expect(card.get_by_text("🦊")).to_be_visible()
        # member_id
        expect(card.get_by_text("strategy-dev-01")).to_be_visible()
        # 소속
        expect(card.get_by_text("strategy-lab")).to_be_visible()
        # 활성 상태
        expect(card.get_by_text("활성")).to_be_visible()

    def test_suspended_agent_visible(self, authenticated_page, base_url: str) -> None:
        """정지 상태인 ops-agent-01 카드에 '정지' 뱃지가 표시된다."""
        _go_to_members(authenticated_page, base_url)

        card = _member_card(authenticated_page, "봇 운영 1호")
        expect(card).to_be_visible()
        expect(card.get_by_text("정지")).to_be_visible()

    def test_revoked_agent_visible(self, authenticated_page, base_url: str) -> None:
        """폐기 상태인 old-agent-01 카드에 '폐기' 뱃지가 표시된다."""
        _go_to_members(authenticated_page, base_url)

        card = _member_card(authenticated_page, "구 리서치 에이전트")
        expect(card).to_be_visible()
        expect(card.get_by_text("폐기")).to_be_visible()

    def test_register_button_visible(self, authenticated_page, base_url: str) -> None:
        """Agent 섹션에 '+ 에이전트 등록' 버튼이 표시된다."""
        _go_to_members(authenticated_page, base_url)

        btn = authenticated_page.get_by_role("button", name=re.compile("에이전트 등록"))
        expect(btn).to_be_visible()

    def test_status_filter_tabs(self, authenticated_page, base_url: str) -> None:
        """상태 필터 탭(전체, active, suspended, revoked)이 표시된다."""
        _go_to_members(authenticated_page, base_url)

        page = authenticated_page
        expect(page.get_by_role("button", name="전체")).to_be_visible()
        expect(page.get_by_role("button", name="active")).to_be_visible()
        expect(page.get_by_role("button", name="suspended")).to_be_visible()
        expect(page.get_by_role("button", name="revoked")).to_be_visible()
