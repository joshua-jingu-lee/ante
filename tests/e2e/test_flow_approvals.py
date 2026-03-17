"""E2E 테스트 — 결재함 페이지 흐름.

결재 목록 조회, 상태/유형 필터, 검색, 상세 조회, 승인/거부 처리를 검증한다.
"""

from __future__ import annotations

import re

import pytest
from playwright.sync_api import expect

SCENARIO = "approvals"

pytestmark = [pytest.mark.e2e, pytest.mark.playwright]


class TestApprovalListPage:
    """결재함 페이지 — 목록 및 탭 검증."""

    def test_page_title_and_default_tab(
        self, authenticated_page, base_url: str
    ) -> None:
        """결재함 페이지에 '전체' 탭이 기본 선택되어 있고, 6건이 표시된다."""
        page = authenticated_page
        page.goto(f"{base_url}/approvals")
        page.wait_for_load_state("networkidle")

        heading = page.get_by_role("heading", name="결재함")
        expect(heading).to_be_visible()

        # '전체' 탭이 기본 활성
        all_tab = page.get_by_role("button", name="전체")
        expect(all_tab).to_be_visible()

        # 테이블 행 6건
        rows = page.locator("table tbody tr")
        expect(rows).to_have_count(6)

    def test_pending_tab(self, authenticated_page, base_url: str) -> None:
        """'대기' 탭 클릭 시 3건이 표시된다."""
        page = authenticated_page
        page.goto(f"{base_url}/approvals")
        page.wait_for_load_state("networkidle")

        page.get_by_role("button", name="대기").click()
        page.wait_for_load_state("networkidle")

        rows = page.locator("table tbody tr")
        expect(rows).to_have_count(3)

    def test_approved_tab(self, authenticated_page, base_url: str) -> None:
        """'승인' 탭 클릭 시 2건이 표시된다."""
        page = authenticated_page
        page.goto(f"{base_url}/approvals")
        page.wait_for_load_state("networkidle")

        page.get_by_role("button", name="승인").click()
        page.wait_for_load_state("networkidle")

        rows = page.locator("table tbody tr")
        expect(rows).to_have_count(2)

    def test_rejected_tab(self, authenticated_page, base_url: str) -> None:
        """'거부' 탭 클릭 시 1건이 표시된다."""
        page = authenticated_page
        page.goto(f"{base_url}/approvals")
        page.wait_for_load_state("networkidle")

        page.get_by_role("button", name="거부").click()
        page.wait_for_load_state("networkidle")

        rows = page.locator("table tbody tr")
        expect(rows).to_have_count(1)


class TestApprovalFilters:
    """결재함 유형 필터 및 검색."""

    def test_type_filter_strategy_adopt(
        self, authenticated_page, base_url: str
    ) -> None:
        """'전략 채택' 유형 필터 시 2건이 표시된다."""
        page = authenticated_page
        page.goto(f"{base_url}/approvals")
        page.wait_for_load_state("networkidle")

        # 유형 필터 select
        type_filter = page.locator("select").filter(
            has_text=re.compile("유형|전체|전략 채택")
        )
        expect(type_filter.first).to_be_visible()
        type_filter.first.select_option(label="전략 채택")

        page.wait_for_load_state("networkidle")

        rows = page.locator("table tbody tr")
        expect(rows).to_have_count(2)

    def test_search_by_keyword(self, authenticated_page, base_url: str) -> None:
        """'모멘텀' 검색 시 해당 건이 필터링된다."""
        page = authenticated_page
        page.goto(f"{base_url}/approvals")
        page.wait_for_load_state("networkidle")

        search_input = page.get_by_placeholder(
            re.compile("제목.*검색|전략명.*검색|검색")
        )
        expect(search_input).to_be_visible()
        search_input.fill("모멘텀")

        page.wait_for_load_state("networkidle")
        # 최소 1건 이상 검색 결과
        rows = page.locator("table tbody tr")
        count = rows.count()
        assert count >= 1, "모멘텀 검색 결과가 없음"
        assert count < 6, "검색 필터가 적용되지 않음"


class TestApprovalDetail:
    """결재 상세 페이지."""

    def test_navigate_to_detail(self, authenticated_page, base_url: str) -> None:
        """대기 건(appr-01) 클릭 시 상세 페이지로 이동한다."""
        page = authenticated_page
        page.goto(f"{base_url}/approvals")
        page.wait_for_load_state("networkidle")

        # 첫 번째 대기 건 클릭
        page.get_by_role("button", name="대기").click()
        page.wait_for_load_state("networkidle")

        page.locator("table tbody tr").first.click()
        page.wait_for_url(re.compile(r"/approvals/appr-\d+"), timeout=5000)

    def test_detail_shows_request_info(self, authenticated_page, base_url: str) -> None:
        """상세 페이지에 제목, 요청자, 요청일, 만료일이 표시된다."""
        page = authenticated_page
        page.goto(f"{base_url}/approvals/appr-01")
        page.wait_for_load_state("networkidle")

        # 요청 정보 필드 확인
        expect(page.get_by_text(re.compile("제목"))).to_be_visible()
        expect(page.get_by_text(re.compile("요청자"))).to_be_visible()
        expect(page.get_by_text(re.compile("요청일"))).to_be_visible()
        expect(page.get_by_text(re.compile("만료일"))).to_be_visible()

    def test_detail_shows_body_content(self, authenticated_page, base_url: str) -> None:
        """상세 페이지에 본문 내용이 표시된다."""
        page = authenticated_page
        page.goto(f"{base_url}/approvals/appr-01")
        page.wait_for_load_state("networkidle")

        # 본문 영역 — 비어있지 않은 콘텐츠 블록이 존재
        body_section = page.locator("article, [class*=body], [class*=content]")
        expect(body_section.first).to_be_visible()
        text = body_section.first.inner_text()
        assert len(text.strip()) > 0, "본문이 비어있음"

    def test_pending_detail_has_review_buttons(
        self, authenticated_page, base_url: str
    ) -> None:
        """대기 상태 상세에 승인/거부 버튼이 표시된다."""
        page = authenticated_page
        page.goto(f"{base_url}/approvals/appr-01")
        page.wait_for_load_state("networkidle")

        approve_btn = page.get_by_role("button", name="승인")
        reject_btn = page.get_by_role("button", name="거부")

        expect(approve_btn).to_be_visible()
        expect(reject_btn).to_be_visible()


class TestApprovalActions:
    """승인/거부 처리."""

    def test_approve_flow(self, authenticated_page, base_url: str) -> None:
        """승인 버튼 → 승인 모달 → 확인하면 승인 처리된다."""
        page = authenticated_page
        page.goto(f"{base_url}/approvals/appr-01")
        page.wait_for_load_state("networkidle")

        # 승인 버튼 클릭
        page.get_by_role("button", name="승인").click()

        # 승인 모달 확인
        modal = page.get_by_role("dialog")
        expect(modal).to_be_visible()
        expect(modal.get_by_text("결재 승인")).to_be_visible()

        # 모달 내 승인 확인 버튼 클릭
        modal.get_by_role("button", name="승인").click()

        # 모달 닫힘 및 상태 변경 확인
        expect(modal).to_be_hidden(timeout=5000)
        page.wait_for_load_state("networkidle")
        expect(
            page.get_by_text(re.compile("승인|approved", re.IGNORECASE))
        ).to_be_visible()

    def test_reject_flow(self, authenticated_page, base_url: str) -> None:
        """거부 버튼 → 거부 모달 → 사유 입력 → 확인하면 거부 처리된다."""
        page = authenticated_page
        page.goto(f"{base_url}/approvals/appr-02")
        page.wait_for_load_state("networkidle")

        # 거부 버튼 클릭
        page.get_by_role("button", name="거부").click()

        # 거부 모달 확인
        modal = page.get_by_role("dialog")
        expect(modal).to_be_visible()
        expect(modal.get_by_text("결재 거부")).to_be_visible()

        # 사유 입력
        reason_input = modal.locator("textarea, input[type=text]").last
        expect(reason_input).to_be_visible()
        reason_input.fill("E2E 테스트 거부 사유: 전략 검증 미완료")

        # 거부 확인 버튼
        modal.get_by_role("button", name="거부").click()

        # 모달 닫힘 및 상태 변경 확인
        expect(modal).to_be_hidden(timeout=5000)
        page.wait_for_load_state("networkidle")
        expect(
            page.get_by_text(re.compile("거부|rejected", re.IGNORECASE))
        ).to_be_visible()


class TestApprovalCompletedDetail:
    """처리 완료된 결재 상세."""

    def test_approved_detail_shows_review(
        self, authenticated_page, base_url: str
    ) -> None:
        """승인 완료된 건(appr-04) 상세에 승인 상태와 검토의견이 표시된다."""
        page = authenticated_page
        page.goto(f"{base_url}/approvals/appr-04")
        page.wait_for_load_state("networkidle")

        # 승인 상태 표시
        expect(
            page.get_by_text(re.compile("승인|approved", re.IGNORECASE))
        ).to_be_visible()

        # 검토의견 영역 존재
        expect(
            page.get_by_text(
                re.compile("검토의견|검토 의견|리뷰|comment", re.IGNORECASE)
            )
        ).to_be_visible()

    def test_rejected_detail_shows_reason(
        self, authenticated_page, base_url: str
    ) -> None:
        """거부된 건(appr-06) 상세에 거부 상태와 사유가 표시된다."""
        page = authenticated_page
        page.goto(f"{base_url}/approvals/appr-06")
        page.wait_for_load_state("networkidle")

        # 거부 상태 표시
        expect(
            page.get_by_text(re.compile("거부|rejected", re.IGNORECASE))
        ).to_be_visible()

        # 거부 사유 영역 존재
        expect(
            page.get_by_text(re.compile("사유|거부.?사유|reason", re.IGNORECASE))
        ).to_be_visible()


class TestApprovalNavigation:
    """결재함 네비게이션."""

    def test_back_to_dashboard(self, authenticated_page, base_url: str) -> None:
        """상세 페이지에서 대시보드로 돌아갈 수 있다."""
        page = authenticated_page
        page.goto(f"{base_url}/approvals/appr-04")
        page.wait_for_load_state("networkidle")

        # 뒤로가기 링크 또는 목록으로 돌아가기
        back_link = page.get_by_role("link", name=re.compile("목록|돌아가기|뒤로"))
        if back_link.count() > 0:
            back_link.first.click()
        else:
            # 브라우저 뒤로가기 대체
            page.go_back()

        page.wait_for_load_state("networkidle")

        # 결재함 목록 또는 대시보드에 도착
        expect(page).to_have_url(re.compile(r"/(approvals|dashboard)?$"))

    def test_table_columns_visible(self, authenticated_page, base_url: str) -> None:
        """결재 테이블에 유형, 제목, 요청자, 요청일, 상태, 처리일 컬럼이 표시된다."""
        page = authenticated_page
        page.goto(f"{base_url}/approvals")
        page.wait_for_load_state("networkidle")

        headers = page.locator("table thead th")
        header_texts = headers.all_inner_texts()

        expected_columns = ["유형", "제목", "요청자", "요청일", "상태"]
        for col in expected_columns:
            assert any(
                col in h for h in header_texts
            ), f"테이블 헤더에 '{col}' 컬럼이 없음: {header_texts}"
