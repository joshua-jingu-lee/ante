"""E2E 테스트 — 결재함 페이지 흐름.

결재 목록 조회, 상태/유형 필터, 검색, 상세 조회를 검증한다.
"""

from __future__ import annotations

import re

import pytest
from playwright.sync_api import Page, expect

SCENARIO = "approvals"

pytestmark = [pytest.mark.e2e, pytest.mark.playwright]


# ── 헬퍼 ─────────────────────────────────────────────


def _go_to_approvals(page: Page, base_url: str) -> None:
    """결재함 페이지로 이동하고 데이터 로드를 대기한다."""
    page.goto(f"{base_url}/approvals", wait_until="commit")
    page.wait_for_timeout(2000)


# ── 결재함 목록 페이지 ───────────────────────────────


class TestApprovalListPage:
    """결재함 페이지 — 목록 및 탭 검증."""

    def test_page_title_and_table_visible(
        self, authenticated_page, base_url: str
    ) -> None:
        """결재함 페이지에 제목 '결재함'과 테이블이 표시되고, 6건이 보인다."""
        _go_to_approvals(authenticated_page, base_url)
        page = authenticated_page

        # 헤더의 h1 타이틀
        heading = page.locator("h1").filter(has_text="결재함")
        expect(heading).to_be_visible()

        # 테이블 행 6건 (전체 탭 기본)
        rows = page.locator("table tbody tr")
        expect(rows).to_have_count(6)

    def test_table_columns_visible(self, authenticated_page, base_url: str) -> None:
        """결재 테이블에 유형, 제목, 요청자, 요청일, 상태, 처리일 컬럼이 표시된다."""
        _go_to_approvals(authenticated_page, base_url)
        page = authenticated_page

        headers = page.locator("table thead th")
        header_texts = headers.all_inner_texts()

        expected_columns = ["유형", "제목", "요청자", "요청일", "상태", "처리일"]
        for col in expected_columns:
            assert any(col in h for h in header_texts), (
                f"테이블 헤더에 '{col}' 컬럼이 없음: {header_texts}"
            )

    def test_pending_tab_filters_to_3(self, authenticated_page, base_url: str) -> None:
        """'대기' 탭 클릭 시 3건이 표시된다."""
        _go_to_approvals(authenticated_page, base_url)
        page = authenticated_page

        page.get_by_role("button", name="대기").first.click()
        page.wait_for_timeout(1500)

        rows = page.locator("table tbody tr")
        expect(rows).to_have_count(3)

    def test_approved_tab_filters_to_2(self, authenticated_page, base_url: str) -> None:
        """'승인' 탭 클릭 시 2건이 표시된다."""
        _go_to_approvals(authenticated_page, base_url)
        page = authenticated_page

        page.get_by_role("button", name="승인").first.click()
        page.wait_for_timeout(1500)

        rows = page.locator("table tbody tr")
        expect(rows).to_have_count(2)

    def test_rejected_tab_filters_to_1(self, authenticated_page, base_url: str) -> None:
        """'거부' 탭 클릭 시 1건이 표시된다."""
        _go_to_approvals(authenticated_page, base_url)
        page = authenticated_page

        page.get_by_role("button", name="거부").first.click()
        page.wait_for_timeout(1500)

        rows = page.locator("table tbody tr")
        expect(rows).to_have_count(1)


# ── 유형 필터 및 검색 ────────────────────────────────


class TestApprovalFilters:
    """결재함 유형 필터 및 검색."""

    def test_type_filter_strategy_adopt(
        self, authenticated_page, base_url: str
    ) -> None:
        """'전략 채택' 유형 필터 시 해당 건만 표시된다."""
        _go_to_approvals(authenticated_page, base_url)
        page = authenticated_page

        # 유형 필터 select
        type_select = page.locator("select").first
        expect(type_select).to_be_visible()
        type_select.select_option(value="strategy_adopt")
        page.wait_for_timeout(1500)

        rows = page.locator("table tbody tr")
        expect(rows).to_have_count(2)

    def test_search_filters_results(self, authenticated_page, base_url: str) -> None:
        """검색 입력 시 제목이 필터링된다."""
        _go_to_approvals(authenticated_page, base_url)
        page = authenticated_page

        search_input = page.get_by_placeholder("제목, 전략명 검색...")
        expect(search_input).to_be_visible()
        search_input.fill("모멘텀")
        page.wait_for_timeout(1000)

        # 모멘텀이 포함된 건만 표시 (appr-01, appr-02 등)
        rows = page.locator("table tbody tr")
        count = rows.count()
        assert count >= 1, "모멘텀 검색 결과가 없음"
        assert count < 6, "검색 필터가 적용되지 않음"


# ── 상세 페이지 ──────────────────────────────────────


class TestApprovalDetail:
    """결재 상세 페이지."""

    def test_navigate_to_detail(self, authenticated_page, base_url: str) -> None:
        """테이블 행 클릭 시 상세 페이지로 이동한다."""
        _go_to_approvals(authenticated_page, base_url)
        page = authenticated_page

        page.locator("table tbody tr").first.click()
        page.wait_for_timeout(2000)

        expect(page).to_have_url(re.compile(r"/approvals/appr-\d+"))

    def test_detail_shows_approval_info(
        self, authenticated_page, base_url: str
    ) -> None:
        """상세 페이지에 결재 정보(요청자, 유형, 상태, 요청일)가 표시된다."""
        page = authenticated_page
        page.goto(f"{base_url}/approvals/appr-01", wait_until="commit")
        page.wait_for_timeout(2000)

        # 결재 정보 카드 내 필드 확인
        expect(page.get_by_text("결재 정보")).to_be_visible()
        expect(page.get_by_text("요청자")).to_be_visible()
        expect(page.get_by_text("유형")).to_be_visible()
        expect(page.get_by_text("요청일")).to_be_visible()

    def test_pending_detail_has_review_buttons(
        self, authenticated_page, base_url: str
    ) -> None:
        """대기 상태 상세에 승인/거부 버튼이 표시된다."""
        page = authenticated_page
        page.goto(f"{base_url}/approvals/appr-01", wait_until="commit")
        page.wait_for_timeout(2000)

        approve_btn = page.get_by_role("button", name="승인")
        reject_btn = page.get_by_role("button", name="거부")

        expect(approve_btn).to_be_visible()
        expect(reject_btn).to_be_visible()

    def test_rejected_detail_shows_reason(
        self, authenticated_page, base_url: str
    ) -> None:
        """거부된 건(appr-06) 상세에 거부 사유가 표시된다."""
        page = authenticated_page
        page.goto(f"{base_url}/approvals/appr-06", wait_until="commit")
        page.wait_for_timeout(2000)

        expect(page.get_by_text("거부 사유")).to_be_visible()
        expect(page.get_by_text("리스크 한도 초과")).to_be_visible()
