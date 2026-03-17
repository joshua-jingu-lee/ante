"""헤더 컴포넌트 헬퍼."""

from __future__ import annotations

from playwright.sync_api import Page, expect


class Header:
    """헤더 조작."""

    def __init__(self, page: Page) -> None:
        self.page = page

    @property
    def _header(self):  # noqa: ANN201
        return self.page.locator("header")

    def get_title(self) -> str:
        """페이지 타이틀 텍스트."""
        return self._header.locator("h1").inner_text()

    def expect_title(self, text: str) -> None:
        expect(self._header.locator("h1")).to_contain_text(text)

    def get_user_info(self) -> str:
        """우측 사용자 정보 텍스트."""
        # 사용자 정보는 헤더 우측의 버튼에 표시
        user_button = self._header.locator("button").last
        return user_button.inner_text()

    def expect_system_status(self, status: str) -> None:
        """시스템 상태 텍스트 검증."""
        expect(self._header.get_by_text(status)).to_be_visible()

    def open_user_menu(self) -> None:
        """사용자 메뉴 드롭다운 열기."""
        self._header.locator("button").last.click()

    def click_logout(self) -> None:
        """로그아웃 버튼 클릭."""
        self.page.get_by_text("로그아웃").click()

    def click_settings(self) -> None:
        """설정 링크 클릭."""
        self.page.get_by_text("설정").click()
