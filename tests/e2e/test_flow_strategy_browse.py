"""E2E 테스트 — 전략 목록 탐색 및 상세 페이지 검증.

전략 테이블, 상태별 뱃지, 필터 탭, 상세 페이지 네비게이션을
Playwright sync API로 검증한다.

시드 데이터:
  - 전략 A (registered): sma-cross-01, "SMA 크로스"
  - 전략 B (active): rsi-reversal-01, "RSI 반등"
  - 전략 C (active): momentum-v2, "모멘텀 돌파 전략 v2"
  - 전략 D (inactive): mean-revert-01, "평균회귀"
"""

from __future__ import annotations

import re

import pytest
from playwright.sync_api import Page, expect

SCENARIO = "strategy-browse"

pytestmark = [pytest.mark.e2e, pytest.mark.playwright]


# ── 헬퍼 ─────────────────────────────────────────────


def _go_to_strategies(page: Page, base_url: str) -> None:
    """전략 목록 페이지로 이동."""
    page.goto(f"{base_url}/strategies", wait_until="commit")
    page.wait_for_timeout(2000)


# ── 전략 목록 페이지 ────────────────────────────────────


class TestStrategyList:
    """전략 목록 페이지 검증."""

    def test_page_title(self, authenticated_page, base_url: str) -> None:
        """페이지 헤더에 '전략과 성과' 제목이 표시된다."""
        _go_to_strategies(authenticated_page, base_url)

        expect(
            authenticated_page.get_by_text("전략과 성과", exact=False).first
        ).to_be_visible()

    def test_strategy_names_displayed(self, authenticated_page, base_url: str) -> None:
        """전략 테이블에 4개 전략 이름이 모두 표시된다."""
        _go_to_strategies(authenticated_page, base_url)

        for name in ["SMA 크로스", "RSI 반등", "모멘텀 돌파 전략 v2", "평균회귀"]:
            expect(
                authenticated_page.get_by_text(name, exact=False).first
            ).to_be_visible()

    def test_table_columns_visible(self, authenticated_page, base_url: str) -> None:
        """전략 테이블에 주요 컬럼 헤더가 표시된다."""
        _go_to_strategies(authenticated_page, base_url)

        page = authenticated_page
        for col in ["전략명", "버전", "제출자", "상태", "실행 봇", "누적 수익률"]:
            expect(page.get_by_text(col, exact=False).first).to_be_visible()

    def test_status_badges(self, authenticated_page, base_url: str) -> None:
        """전략 상태에 따라 올바른 뱃지 텍스트가 표시된다.

        registered -> '등록됨', active -> '활성', inactive -> '비활성'
        """
        _go_to_strategies(authenticated_page, base_url)

        page = authenticated_page
        # 등록됨 뱃지 (SMA 크로스 - registered)
        expect(page.get_by_text("등록됨", exact=True).first).to_be_visible()
        # 활성 뱃지 (RSI 반등, 모멘텀 돌파 전략 v2 - active)
        expect(page.get_by_text("활성", exact=True).first).to_be_visible()
        # 비활성 뱃지 (평균회귀 - inactive)
        expect(page.get_by_text("비활성", exact=True).first).to_be_visible()

    def test_filter_tabs_visible(self, authenticated_page, base_url: str) -> None:
        """상태 필터 탭(전체, 운용중, 대기, 중지)이 표시된다."""
        _go_to_strategies(authenticated_page, base_url)

        page = authenticated_page
        for label in ["전체", "운용중", "대기", "중지"]:
            expect(page.get_by_role("button", name=label)).to_be_visible()

    def test_filter_active_strategies(self, authenticated_page, base_url: str) -> None:
        """'운용중' 필터를 클릭하면 active 전략만 표시된다."""
        _go_to_strategies(authenticated_page, base_url)

        page = authenticated_page
        page.get_by_role("button", name="운용중").click()
        page.wait_for_timeout(1000)

        # active 전략은 보여야 한다
        expect(page.get_by_text("RSI 반등", exact=False).first).to_be_visible()
        expect(
            page.get_by_text("모멘텀 돌파 전략 v2", exact=False).first
        ).to_be_visible()

        # registered/inactive 전략은 숨겨져야 한다
        expect(page.get_by_text("SMA 크로스", exact=False)).to_be_hidden()
        expect(page.get_by_text("평균회귀", exact=False)).to_be_hidden()

    def test_filter_inactive_strategies(
        self, authenticated_page, base_url: str
    ) -> None:
        """'중지' 필터를 클릭하면 inactive 전략만 표시된다."""
        _go_to_strategies(authenticated_page, base_url)

        page = authenticated_page
        page.get_by_role("button", name="중지").click()
        page.wait_for_timeout(1000)

        # inactive 전략만 보여야 한다
        expect(page.get_by_text("평균회귀", exact=False).first).to_be_visible()

        # 나머지는 숨겨져야 한다
        expect(page.get_by_text("SMA 크로스", exact=False)).to_be_hidden()
        expect(page.get_by_text("RSI 반등", exact=False)).to_be_hidden()


# ── 전략 상세 페이지 ──────────────────────────────────


class TestStrategyDetail:
    """전략 상세 페이지 검증."""

    def test_navigate_to_detail(self, authenticated_page, base_url: str) -> None:
        """전략 테이블 행 클릭으로 상세 페이지에 진입한다."""
        _go_to_strategies(authenticated_page, base_url)

        page = authenticated_page
        # 모멘텀 돌파 전략 v2 행 클릭
        page.get_by_text("모멘텀 돌파 전략 v2", exact=False).first.click()
        page.wait_for_timeout(2000)

        expect(page).to_have_url(re.compile(r"/strategies/momentum-v2"))

    def test_detail_page_direct(self, authenticated_page, base_url: str) -> None:
        """전략 상세 페이지에 전략 이름과 정보가 표시된다."""
        page = authenticated_page
        page.goto(f"{base_url}/strategies/momentum-v2", wait_until="commit")
        page.wait_for_timeout(2000)

        # 전략 이름
        expect(
            page.get_by_text("모멘텀 돌파 전략 v2", exact=False).first
        ).to_be_visible()
