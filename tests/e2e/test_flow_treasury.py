"""E2E 테스트 — 자금관리(Treasury) 페이지 검증.

KIS 계좌 요약, Ante 관리자산 요약, Bot별 예산 테이블, 자금 변동 이력,
예산 할당 폼을 Playwright sync API로 검증한다.

시드 데이터:
  - 2 bots: seed-bot-live, seed-bot-paper
  - 예산 배분 및 자금 변동 이력 5건
"""

from __future__ import annotations

import re

import pytest
from playwright.sync_api import Page, expect

SCENARIO = "treasury"

pytestmark = [pytest.mark.e2e, pytest.mark.playwright]


# ── 헬퍼 ─────────────────────────────────────────────


def _go_to_treasury(page: Page, base_url: str) -> None:
    """자금관리 페이지로 이동."""
    page.goto(f"{base_url}/treasury", wait_until="commit")
    page.wait_for_timeout(2000)


# ── 페이지 타이틀 ───────────────────────────────────


class TestPageTitle:
    """자금관리 페이지 타이틀 검증."""

    def test_page_title(self, authenticated_page, base_url: str) -> None:  # noqa: ANN001
        """자금관리 페이지 제목이 '자금관리'로 표시된다."""
        _go_to_treasury(authenticated_page, base_url)

        expect(
            authenticated_page.get_by_text("자금관리", exact=True).first
        ).to_be_visible()


# ── KIS 계좌 요약 섹션 ──────────────────────────────


class TestKISAccountSummary:
    """KIS 계좌 요약 검증."""

    def test_kis_account_info(self, authenticated_page, base_url: str) -> None:  # noqa: ANN001
        """KIS 계좌 요약에 한국투자증권, 수수료 정보가 표시된다."""
        _go_to_treasury(authenticated_page, base_url)
        page = authenticated_page

        expect(page.get_by_text("한국투자증권", exact=False).first).to_be_visible()
        expect(page.get_by_text("수수료", exact=False).first).to_be_visible()

    def test_total_assets(self, authenticated_page, base_url: str) -> None:  # noqa: ANN001
        """총 자산 평가, 예수금 등 주요 금액이 표시된다."""
        _go_to_treasury(authenticated_page, base_url)
        page = authenticated_page

        expect(page.get_by_text("총 자산 평가", exact=False).first).to_be_visible()
        expect(page.get_by_text("100,000,000", exact=False).first).to_be_visible()
        expect(page.get_by_text("예수금", exact=False).first).to_be_visible()


# ── Ante 관리 자금 섹션 ──────────────────────────────


class TestAnteManagedSection:
    """Ante 관리 자금 섹션 검증."""

    def test_ante_managed_info(self, authenticated_page, base_url: str) -> None:  # noqa: ANN001
        """Ante 관리 자금 섹션에 Bot 운용 수와 배정예산이 표시된다."""
        _go_to_treasury(authenticated_page, base_url)
        page = authenticated_page

        expect(page.get_by_text("Ante 관리", exact=False).first).to_be_visible()
        expect(page.get_by_text("Bot 배정예산", exact=False).first).to_be_visible()
        expect(page.get_by_text("15,000,000", exact=False).first).to_be_visible()


# ── Bot별 예산 테이블 ───────────────────────────────


class TestBotBudgetTable:
    """Bot별 예산 배분 테이블 검증."""

    def test_bot_budget_table_rows(self, authenticated_page, base_url: str) -> None:  # noqa: ANN001
        """Bot별 예산 테이블에 2개 봇(seed-bot-live, seed-bot-paper)이 표시된다."""
        _go_to_treasury(authenticated_page, base_url)
        page = authenticated_page

        expect(page.get_by_text("seed-bot-live", exact=False).first).to_be_visible()
        expect(page.get_by_text("seed-bot-paper", exact=False).first).to_be_visible()

    def test_bot_budget_columns(self, authenticated_page, base_url: str) -> None:  # noqa: ANN001
        """Bot별 예산 테이블에 주요 컬럼(배정예산, 사용예산, 잔여예산)이 존재한다."""
        _go_to_treasury(authenticated_page, base_url)
        page = authenticated_page

        for header_text in ["배정예산", "사용예산", "잔여예산"]:
            expect(page.get_by_text(header_text, exact=False).first).to_be_visible()


# ── 최근 자금 변동 이력 ──────────────────────────────


class TestRecentTransactions:
    """최근 자금 변동 이력 테이블 검증."""

    def test_recent_transactions_visible(
        self, authenticated_page, base_url: str
    ) -> None:  # noqa: ANN001
        """최근 자금 변동 테이블이 표시되고 5건의 항목이 보인다."""
        _go_to_treasury(authenticated_page, base_url)
        page = authenticated_page

        expect(page.get_by_text("최근 자금 변동", exact=False).first).to_be_visible()

        # 테이블에 행이 존재 (5건)
        history_table = page.locator("table").last
        rows = history_table.locator("tbody tr")
        expect(rows).to_have_count(5)

    def test_transaction_table_columns(self, authenticated_page, base_url: str) -> None:  # noqa: ANN001
        """최근 자금 변동 테이블에 시각, 유형, BOT, 금액, 비고 컬럼이 있다."""
        _go_to_treasury(authenticated_page, base_url)
        page = authenticated_page

        history_table = page.locator("table").last
        for col in ["시각", "유형", "BOT", "금액", "비고"]:
            expect(history_table.get_by_text(col, exact=False).first).to_be_visible()


# ── 예산 관리 폼 ────────────────────────────────────


class TestBudgetManagementForm:
    """예산 할당/회수 폼 검증."""

    def test_budget_form_elements(self, authenticated_page, base_url: str) -> None:  # noqa: ANN001
        """예산 관리 폼에 Bot 선택 드롭다운, 금액 입력, 할당/회수 버튼이 존재한다."""
        _go_to_treasury(authenticated_page, base_url)
        page = authenticated_page

        # Bot 선택 드롭다운
        bot_select = page.locator("select").first
        expect(bot_select).to_be_visible()

        # 금액 입력 필드
        amount_input = page.locator("input").first
        expect(amount_input).to_be_visible()

        # 할당/회수 버튼
        expect(
            page.get_by_role("button", name=re.compile("할당")).first
        ).to_be_visible()
        expect(
            page.get_by_role("button", name=re.compile("회수")).first
        ).to_be_visible()
