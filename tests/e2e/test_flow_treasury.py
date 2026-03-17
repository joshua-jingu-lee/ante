"""E2E 테스트 — 자금관리(Treasury) 페이지 검증.

KIS 계좌 요약, Ante 관리자산 요약, Bot별 예산 테이블, 자금 변동 이력,
페이지네이션, 예산 할당 폼 및 확인 모달을 Playwright sync API로 검증한다.

시드 데이터:
  - 3 bots: bot-momentum-01 (stopped), bot-macd-cross (running), bot-rsi-01 (stopped)
  - 예산 배분 및 포지션 존재
  - 24건의 자금 변동 이력
"""

from __future__ import annotations

import re

import pytest
from playwright.sync_api import expect

SCENARIO = "treasury"

pytestmark = [pytest.mark.e2e, pytest.mark.playwright]


# ── 계좌 현황 섹션 ──────────────────────────────────


class TestAccountSummary:
    """KIS 계좌 요약 및 Ante 관리자산 요약 검증."""

    def test_kis_account_summary(self, authenticated_page, base_url: str) -> None:
        """자금관리 페이지에 KIS 계좌 요약(예수금, 매수가능금액)이 표시된다."""
        page = authenticated_page
        page.goto(f"{base_url}/treasury")
        page.wait_for_load_state("domcontentloaded")

        expect(page.get_by_text("계좌 현황", exact=False)).to_be_visible()
        expect(page.get_by_text("예수금", exact=False)).to_be_visible()
        expect(page.get_by_text("매수가능금액", exact=False)).to_be_visible()

    def test_ante_managed_assets_summary(
        self, authenticated_page, base_url: str
    ) -> None:
        """Ante 관리자산 요약(Bot 배정예산, 잔여예산, 보유종목 평가)이 표시된다."""
        page = authenticated_page
        page.goto(f"{base_url}/treasury")
        page.wait_for_load_state("domcontentloaded")

        expect(page.get_by_text("자금 운용", exact=False)).to_be_visible()


# ── Bot별 예산 테이블 ───────────────────────────────


class TestBotBudgetTable:
    """Bot별 예산 배분 테이블 검증."""

    def test_bot_budget_table_rows(self, authenticated_page, base_url: str) -> None:
        """Bot별 예산 테이블에 3개 봇이 표시된다."""
        page = authenticated_page
        page.goto(f"{base_url}/treasury")
        page.wait_for_load_state("domcontentloaded")

        # 3개 봇 이름이 모두 보여야 한다
        for bot_name in ["bot-momentum-01", "bot-macd-cross", "bot-rsi-01"]:
            expect(page.get_by_text(bot_name, exact=False)).to_be_visible()

    def test_bot_budget_columns(self, authenticated_page, base_url: str) -> None:
        """Bot별 예산 테이블에 주요 컬럼(배정, 사용, 잔여)이 존재한다."""
        page = authenticated_page
        page.goto(f"{base_url}/treasury")
        page.wait_for_load_state("domcontentloaded")

        # 테이블 헤더에 예산 관련 컬럼 확인
        for header_text in ["배정", "사용", "잔여"]:
            expect(page.get_by_text(header_text, exact=False)).to_be_visible()


# ── 자금 변동 이력 ──────────────────────────────────


class TestTransactionHistory:
    """자금 변동 이력 테이블 및 페이지네이션 검증."""

    def test_transaction_history_visible(
        self, authenticated_page, base_url: str
    ) -> None:
        """자금 변동 이력 테이블이 표시되고 최신 항목이 보인다."""
        page = authenticated_page
        page.goto(f"{base_url}/treasury")
        page.wait_for_load_state("domcontentloaded")

        # 이력 섹션 존재
        expect(page.get_by_text("변동 이력", exact=False)).to_be_visible()

        # 테이블에 행이 존재 (최신 8건 정도)
        history_table = page.locator("table").last
        rows = history_table.locator("tbody tr")
        expect(rows.first).to_be_visible()

    def test_transaction_history_first_page_count(
        self, authenticated_page, base_url: str
    ) -> None:
        """첫 페이지에 이력 8건이 표시된다."""
        page = authenticated_page
        page.goto(f"{base_url}/treasury")
        page.wait_for_load_state("domcontentloaded")

        history_table = page.locator("table").last
        rows = history_table.locator("tbody tr")
        expect(rows).to_have_count(8)

    def test_transaction_pagination(self, authenticated_page, base_url: str) -> None:
        """페이지네이션으로 다음 페이지 이력을 볼 수 있다."""
        page = authenticated_page
        page.goto(f"{base_url}/treasury")
        page.wait_for_load_state("domcontentloaded")

        # 다음 페이지 버튼 클릭
        next_button = page.get_by_role(
            "button", name=re.compile("다음|next|›", re.IGNORECASE)
        )
        expect(next_button).to_be_visible()
        next_button.click()
        page.wait_for_load_state("domcontentloaded")

        # 다음 페이지에도 행이 존재
        history_table = page.locator("table").last
        rows = history_table.locator("tbody tr")
        expect(rows.first).to_be_visible()


# ── 예산 할당 폼 ────────────────────────────────────


class TestBudgetAllocationForm:
    """예산 할당/회수 폼 및 확인 모달 검증."""

    def test_allocation_form_elements(self, authenticated_page, base_url: str) -> None:
        """예산 할당 폼에 Bot 선택, 금액 입력, 할당/회수 버튼이 존재한다."""
        page = authenticated_page
        page.goto(f"{base_url}/treasury")
        page.wait_for_load_state("domcontentloaded")

        # Bot 선택 드롭다운 또는 select
        bot_select = page.locator("select").first
        expect(bot_select).to_be_visible()

        # 금액 입력 필드
        amount_input = page.locator('input[type="number"]').first
        expect(amount_input).to_be_visible()

        # 할당/회수 버튼
        expect(page.get_by_role("button", name=re.compile("할당"))).to_be_visible()
        expect(page.get_by_role("button", name=re.compile("회수"))).to_be_visible()

    def test_allocation_confirmation_modal(
        self, authenticated_page, base_url: str
    ) -> None:
        """할당 버튼 클릭 시 확인 모달이 표시된다."""
        page = authenticated_page
        page.goto(f"{base_url}/treasury")
        page.wait_for_load_state("domcontentloaded")

        # Bot 선택
        bot_select = page.locator("select").first
        bot_select.select_option(index=1)

        # 금액 입력
        amount_input = page.locator('input[type="number"]').first
        amount_input.fill("100000")

        # 할당 버튼 클릭
        page.get_by_role("button", name=re.compile("할당")).click()

        # 확인 모달 표시
        expect(page.get_by_text("변경 확인", exact=False)).to_be_visible()
