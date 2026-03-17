"""E2E 테스트 — 멤버 관리 페이지 흐름.

사람/에이전트 멤버 목록 조회, 에이전트 등록, 상세 조회, 상태 변경을 검증한다.
"""

from __future__ import annotations

import re

import pytest
from playwright.sync_api import expect

SCENARIO = "member-management"

pytestmark = [pytest.mark.e2e, pytest.mark.playwright]


class TestMemberListPage:
    """멤버 관리 페이지 — 목록 검증."""

    def test_page_title(self, authenticated_page, base_url: str) -> None:
        """멤버 관리 페이지 타이틀이 표시된다."""
        page = authenticated_page
        page.goto(f"{base_url}/members")
        page.wait_for_load_state("domcontentloaded")

        heading = page.get_by_role("heading", name="멤버 관리")
        expect(heading).to_be_visible()

    def test_human_section_count(self, authenticated_page, base_url: str) -> None:
        """사람 섹션에 2명이 표시된다."""
        page = authenticated_page
        page.goto(f"{base_url}/members")
        page.wait_for_load_state("domcontentloaded")

        section = page.get_by_text("사람")
        expect(section).to_be_visible()

        # 사람 섹션 내 멤버 카드 2개 (owner, admin-01)
        human_cards = page.locator("text=사람").locator("..").locator("[class*=card]")
        expect(human_cards).to_have_count(2)

    def test_agent_section_count(self, authenticated_page, base_url: str) -> None:
        """에이전트 섹션에 6명이 표시된다."""
        page = authenticated_page
        page.goto(f"{base_url}/members")
        page.wait_for_load_state("domcontentloaded")

        section = page.get_by_text("에이전트")
        expect(section).to_be_visible()

        agent_cards = (
            page.locator("text=에이전트").locator("..").locator("[class*=card]")
        )
        expect(agent_cards).to_have_count(6)

    def test_owner_card_has_crown_and_master_role(
        self, authenticated_page, base_url: str
    ) -> None:
        """owner 카드에 왕관 표시와 master 역할이 보인다."""
        page = authenticated_page
        page.goto(f"{base_url}/members")
        page.wait_for_load_state("domcontentloaded")

        owner_card = page.get_by_text("owner").locator("..")
        expect(owner_card).to_be_visible()
        # 왕관 이모지 또는 아이콘 확인
        expect(owner_card).to_contain_text(
            re.compile(r"👑|crown|master", re.IGNORECASE)
        )

    def test_admin_card_visible(self, authenticated_page, base_url: str) -> None:
        """admin-01 카드가 표시된다."""
        page = authenticated_page
        page.goto(f"{base_url}/members")
        page.wait_for_load_state("domcontentloaded")

        admin_card = page.get_by_text("admin-01")
        expect(admin_card).to_be_visible()

    def test_agent_status_active_count(self, authenticated_page, base_url: str) -> None:
        """active 상태 에이전트가 4개 표시된다."""
        page = authenticated_page
        page.goto(f"{base_url}/members")
        page.wait_for_load_state("domcontentloaded")

        # 에이전트 섹션 내 active 배지
        active_badges = (
            page.locator("text=에이전트").locator("..").locator("text=active")
        )
        expect(active_badges).to_have_count(4)

    def test_agent_status_suspended_count(
        self, authenticated_page, base_url: str
    ) -> None:
        """suspended 상태 에이전트가 1개 표시된다."""
        page = authenticated_page
        page.goto(f"{base_url}/members")
        page.wait_for_load_state("domcontentloaded")

        suspended_badges = (
            page.locator("text=에이전트").locator("..").locator("text=suspended")
        )
        expect(suspended_badges).to_have_count(1)

    def test_agent_status_revoked_count(
        self, authenticated_page, base_url: str
    ) -> None:
        """revoked 상태 에이전트가 1개 표시된다."""
        page = authenticated_page
        page.goto(f"{base_url}/members")
        page.wait_for_load_state("domcontentloaded")

        revoked_badges = (
            page.locator("text=에이전트").locator("..").locator("text=revoked")
        )
        expect(revoked_badges).to_have_count(1)


class TestAgentRegistration:
    """에이전트 등록 모달 흐름."""

    def test_open_register_modal(self, authenticated_page, base_url: str) -> None:
        """에이전트 등록 버튼 클릭 시 모달이 열린다."""
        page = authenticated_page
        page.goto(f"{base_url}/members")
        page.wait_for_load_state("domcontentloaded")

        page.get_by_role("button", name=re.compile("에이전트 등록|등록")).click()

        modal = page.get_by_role("dialog")
        expect(modal).to_be_visible()

    def test_register_form_fields(self, authenticated_page, base_url: str) -> None:
        """등록 모달에 ID, 이름, 소속, 권한 체크박스 필드가 있다."""
        page = authenticated_page
        page.goto(f"{base_url}/members")
        page.wait_for_load_state("domcontentloaded")

        page.get_by_role("button", name=re.compile("에이전트 등록|등록")).click()

        modal = page.get_by_role("dialog")
        expect(modal).to_be_visible()

        # 필수 입력 필드 존재 확인
        expect(modal.get_by_label(re.compile("ID|아이디"))).to_be_visible()
        expect(modal.get_by_label(re.compile("이름|Name"))).to_be_visible()
        expect(modal.get_by_label(re.compile("소속|팀"))).to_be_visible()

        # 권한 체크박스가 하나 이상 존재
        checkboxes = modal.get_by_role("checkbox")
        expect(checkboxes.first).to_be_visible()

    def test_submit_agent_registration(self, authenticated_page, base_url: str) -> None:
        """에이전트 등록 폼을 채우고 제출하면 새 에이전트가 목록에 추가된다."""
        page = authenticated_page
        page.goto(f"{base_url}/members")
        page.wait_for_load_state("domcontentloaded")

        page.get_by_role("button", name=re.compile("에이전트 등록|등록")).click()
        modal = page.get_by_role("dialog")
        expect(modal).to_be_visible()

        # 폼 작성
        modal.get_by_label(re.compile("ID|아이디")).fill("new-agent-e2e")
        modal.get_by_label(re.compile("이름|Name")).fill("E2E 테스트 에이전트")
        modal.get_by_label(re.compile("소속|팀")).fill("e2e-team")

        # 첫 번째 권한 체크박스 선택
        modal.get_by_role("checkbox").first.check()

        # 제출
        modal.get_by_role("button", name=re.compile("등록|확인|저장")).click()

        # 모달 닫힘 확인
        expect(modal).to_be_hidden(timeout=5000)

        # 목록에 새 에이전트가 표시됨
        page.wait_for_load_state("domcontentloaded")
        expect(page.get_by_text("new-agent-e2e")).to_be_visible()


class TestAgentDetail:
    """에이전트 상세 페이지."""

    def test_agent_detail_page(self, authenticated_page, base_url: str) -> None:
        """strategy-dev-01 상세 페이지에 토큰 접두어, 생성자, 권한 목록이 표시된다."""
        page = authenticated_page
        page.goto(f"{base_url}/members/strategy-dev-01")
        page.wait_for_load_state("domcontentloaded")

        # 에이전트 이름 확인
        expect(page.get_by_text("strategy-dev-01")).to_be_visible()

        # 토큰 접두어 표시
        expect(
            page.get_by_text(re.compile("토큰|token", re.IGNORECASE))
        ).to_be_visible()

        # 생성자(created_by) 표시
        expect(
            page.get_by_text(re.compile("생성자|created", re.IGNORECASE))
        ).to_be_visible()

        # 권한 목록이 하나 이상 표시
        expect(
            page.get_by_text(re.compile("권한|scope", re.IGNORECASE))
        ).to_be_visible()


class TestAgentStatusChange:
    """에이전트 상태 변경 (일시정지, 해지)."""

    def test_suspend_agent(self, authenticated_page, base_url: str) -> None:
        """ops-agent-01을 일시정지할 수 있다."""
        page = authenticated_page
        page.goto(f"{base_url}/members/ops-agent-01")
        page.wait_for_load_state("domcontentloaded")

        # 일시정지 버튼 클릭
        suspend_btn = page.get_by_role(
            "button", name=re.compile("일시정지|중지|suspend")
        )
        expect(suspend_btn).to_be_visible()
        suspend_btn.click()

        # 확인 모달/다이얼로그 처리
        confirm_btn = page.get_by_role("button", name=re.compile("확인|승인"))
        if confirm_btn.is_visible(timeout=3000):
            confirm_btn.click()

        # 상태가 suspended로 변경
        page.wait_for_load_state("domcontentloaded")
        expect(page.get_by_text("suspended")).to_be_visible(timeout=5000)

    def test_revoked_agent_no_action(self, authenticated_page, base_url: str) -> None:
        """이미 revoked 상태인 old-agent-01에는 해지 버튼이 비활성화되어 있다."""
        page = authenticated_page
        page.goto(f"{base_url}/members/old-agent-01")
        page.wait_for_load_state("domcontentloaded")

        # revoked 상태 표시 확인
        expect(page.get_by_text("revoked")).to_be_visible()

        # 해지 버튼이 없거나 비활성화
        revoke_btn = page.get_by_role("button", name=re.compile("해지|revoke"))
        if revoke_btn.count() > 0:
            expect(revoke_btn).to_be_disabled()


class TestMemberFiltering:
    """소속 필터링."""

    def test_org_filter(self, authenticated_page, base_url: str) -> None:
        """소속 필터를 적용하면 해당 소속 에이전트만 표시된다."""
        page = authenticated_page
        page.goto(f"{base_url}/members")
        page.wait_for_load_state("domcontentloaded")

        # 소속 필터 선택
        filter_select = page.get_by_role("combobox").or_(
            page.locator("select").filter(has_text=re.compile("소속|팀|전체"))
        )
        expect(filter_select.first).to_be_visible()
        filter_select.first.click()

        # 첫 번째 소속 옵션 선택 (전체 제외)
        options = page.get_by_role("option")
        if options.count() > 1:
            options.nth(1).click()

        page.wait_for_load_state("domcontentloaded")

        # 필터링 후 카드 수가 전체(6)보다 적어야 함
        agent_cards = (
            page.locator("text=에이전트").locator("..").locator("[class*=card]")
        )
        count = agent_cards.count()
        assert (
            count < 6
        ), f"필터링 후에도 {count}개 카드가 표시됨 (전체 6개보다 적어야 함)"
