"""E2E 테스트 — 전략 목록 탐색 및 상세 페이지 검증.

전략 카드 목록, 상태별 뱃지, 필터링, 상세 페이지(기본 정보·성과 요약·거래 이력)를
Playwright sync API로 검증한다.

시드 데이터:
  - 전략 A (registered): sma-cross-01, "SMA 크로스", 봇 없음
  - 전략 B (active, 거래 없음): rsi-reversal-01, "RSI 반등", 봇 있음
  - 전략 C (active, 거래 3건): momentum-v2, "모멘텀 돌파 전략 v2", 봇 있음
  - 전략 D (inactive): mean-revert-01, "평균회귀", 거래 6건
"""

from __future__ import annotations

import re

import pytest
from playwright.sync_api import expect

SCENARIO = "strategy-browse"

pytestmark = [pytest.mark.e2e, pytest.mark.playwright]


# ── 전략 목록 페이지 ────────────────────────────────


class TestStrategyList:
    """전략 목록 페이지 검증."""

    def test_strategy_cards_displayed(self, authenticated_page, base_url: str) -> None:
        """전략 목록 페이지에 4개 전략 카드가 표시된다."""
        page = authenticated_page
        page.goto(f"{base_url}/strategies")
        page.wait_for_load_state("domcontentloaded")

        # 4개 전략 이름이 모두 보여야 한다
        for name in ["SMA 크로스", "RSI 반등", "모멘텀 돌파 전략 v2", "평균회귀"]:
            expect(page.get_by_text(name, exact=False)).to_be_visible()

    def test_registered_status_badge(self, authenticated_page, base_url: str) -> None:
        """등록됨(registered) 상태 전략에 '등록됨' 뱃지가 표시된다."""
        page = authenticated_page
        page.goto(f"{base_url}/strategies")
        page.wait_for_load_state("domcontentloaded")

        # SMA 크로스 카드 영역에서 '등록됨' 뱃지 확인
        card = page.get_by_text("SMA 크로스", exact=False).locator("..").locator("..")
        expect(card.get_by_text("등록됨", exact=True)).to_be_visible()

    def test_active_status_badge(self, authenticated_page, base_url: str) -> None:
        """운용중(active) 상태 전략에 '운용중' 뱃지가 표시된다."""
        page = authenticated_page
        page.goto(f"{base_url}/strategies")
        page.wait_for_load_state("domcontentloaded")

        card = page.get_by_text("RSI 반등", exact=False).locator("..").locator("..")
        expect(card.get_by_text("운용중", exact=True)).to_be_visible()

    def test_inactive_status_badge(self, authenticated_page, base_url: str) -> None:
        """비활성(inactive) 상태 전략에 '비활성' 뱃지가 표시된다."""
        page = authenticated_page
        page.goto(f"{base_url}/strategies")
        page.wait_for_load_state("domcontentloaded")

        card = page.get_by_text("평균회귀", exact=False).locator("..").locator("..")
        expect(card.get_by_text("비활성", exact=True)).to_be_visible()

    def test_filter_by_status(self, authenticated_page, base_url: str) -> None:
        """상태별 필터를 적용하면 해당 상태 전략만 표시된다."""
        page = authenticated_page
        page.goto(f"{base_url}/strategies")
        page.wait_for_load_state("domcontentloaded")

        # '운용중' 필터 클릭
        page.get_by_role("button", name=re.compile("운용중")).click()
        page.wait_for_load_state("domcontentloaded")

        # 운용중 전략(RSI 반등, 모멘텀 돌파 전략 v2)은 보이고
        expect(page.get_by_text("RSI 반등", exact=False)).to_be_visible()
        expect(page.get_by_text("모멘텀 돌파 전략 v2", exact=False)).to_be_visible()

        # 등록됨/비활성 전략은 숨겨져야 한다
        expect(page.get_by_text("SMA 크로스", exact=False)).to_be_hidden()
        expect(page.get_by_text("평균회귀", exact=False)).to_be_hidden()


# ── 전략 C 상세 페이지 ──────────────────────────────


class TestStrategyDetailActive:
    """전략 C (momentum-v2) 상세 페이지 검증."""

    def test_basic_info(self, authenticated_page, base_url: str) -> None:
        """전략 상세 페이지에 기본 정보(이름, 버전, 작성자, 설명)가 표시된다."""
        page = authenticated_page
        page.goto(f"{base_url}/strategies/momentum-v2")
        page.wait_for_load_state("domcontentloaded")

        expect(page.get_by_text("모멘텀 돌파 전략 v2", exact=False)).to_be_visible()

        # 기본 정보 섹션 존재
        expect(page.get_by_text("기본 정보", exact=False)).to_be_visible()

    def test_back_link(self, authenticated_page, base_url: str) -> None:
        """상세 페이지에서 '← 전략과 성과' 링크로 목록 복귀가 가능하다."""
        page = authenticated_page
        page.goto(f"{base_url}/strategies/momentum-v2")
        page.wait_for_load_state("domcontentloaded")

        back_link = page.get_by_text("전략과 성과", exact=False)
        expect(back_link).to_be_visible()

        back_link.click()
        page.wait_for_load_state("domcontentloaded")
        expect(page).to_have_url(re.compile(r"/strategies/?$"))

    def test_performance_summary(self, authenticated_page, base_url: str) -> None:
        """전략 C 상세 페이지에 성과 요약이 표시되고 거래 3건이 반영된다."""
        page = authenticated_page
        page.goto(f"{base_url}/strategies/momentum-v2")
        page.wait_for_load_state("domcontentloaded")

        # 성과 요약 섹션
        expect(page.get_by_text("성과 요약", exact=False)).to_be_visible()

        # 거래 건수 3이 어딘가에 표시
        expect(page.get_by_text("3", exact=False)).to_be_visible()

    def test_trade_history_table(self, authenticated_page, base_url: str) -> None:
        """전략 C 상세 페이지에 거래 이력 테이블이 표시된다."""
        page = authenticated_page
        page.goto(f"{base_url}/strategies/momentum-v2")
        page.wait_for_load_state("domcontentloaded")

        # 거래 이력 섹션
        expect(page.get_by_text("거래 이력", exact=False)).to_be_visible()

        # 테이블에 행이 존재
        table = page.locator("table")
        rows = table.locator("tbody tr")
        expect(rows).to_have_count(3)


# ── 전략 D 상세 페이지 ──────────────────────────────


class TestStrategyDetailInactive:
    """전략 D (mean-revert-01, 비활성) 상세 페이지 검증."""

    def test_inactive_status_shown(self, authenticated_page, base_url: str) -> None:
        """비활성 전략의 상세 페이지에 '비활성' 상태가 표시된다."""
        page = authenticated_page
        page.goto(f"{base_url}/strategies/mean-revert-01")
        page.wait_for_load_state("domcontentloaded")

        expect(page.get_by_text("평균회귀", exact=False)).to_be_visible()
        expect(page.get_by_text("비활성", exact=True)).to_be_visible()
