"""사이드바 네비게이션 헬퍼."""

from __future__ import annotations

import re

from playwright.sync_api import Page, expect

# 사이드바 메뉴 항목: (표시 텍스트, URL 경로)
MENU_ITEMS = [
    ("대시보드", "/"),
    ("결재함", "/approvals"),
    ("자금관리", "/treasury"),
    ("전략과 성과", "/strategies"),
    ("봇 관리", "/bots"),
    ("백테스트 데이터", "/backtest-data"),
    ("멤버 관리", "/members"),
]


class Sidebar:
    """사이드바 조작."""

    def __init__(self, page: Page) -> None:
        self.page = page

    @property
    def nav(self):  # noqa: ANN201
        return self.page.locator("nav")

    def navigate_to(self, label: str) -> None:
        """메뉴 항목을 클릭하여 해당 페이지로 이동."""
        self.page.get_by_text(label, exact=False).click()
        self.page.wait_for_load_state("networkidle")

    def expect_menu_count(self, count: int) -> None:
        """사이드바 메뉴 항목 수를 검증."""
        links = self.nav.locator("a")
        expect(links).to_have_count(count)

    def expect_active(self, label: str) -> None:
        """특정 메뉴가 활성(현재 페이지) 상태인지 검증."""
        link = self.nav.get_by_text(label, exact=False)
        expect(link).to_have_class(re.compile(r"bg-"))  # 활성 메뉴는 bg-* 클래스를 가짐

    def get_badge_text(self, label: str) -> str | None:
        """메뉴 항목 옆 뱃지 텍스트를 반환."""
        menu_item = self.nav.get_by_text(label, exact=False).locator("..")
        badge = menu_item.locator("span.bg-negative")
        if badge.count() > 0:
            return badge.first.inner_text()
        return None
