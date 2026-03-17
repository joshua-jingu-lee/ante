"""공통 E2E 테스트 유틸리티."""

from __future__ import annotations

from playwright.sync_api import Page, expect


def wait_for_page_load(page: Page) -> None:
    """페이지 로딩 완료 대기."""
    page.wait_for_load_state("domcontentloaded")
    expect(page.locator("#root")).not_to_be_empty()


def expect_modal(page: Page, title: str | None = None) -> None:
    """모달이 표시되는지 검증."""
    overlay = page.locator("div.fixed.inset-0.z-50")
    expect(overlay).to_be_visible(timeout=5000)

    if title:
        expect(page.get_by_text(title)).to_be_visible()


def close_modal(page: Page) -> None:
    """ESC 키로 모달 닫기."""
    page.keyboard.press("Escape")


def expect_toast(page: Page, text: str) -> None:
    """토스트 메시지가 표시되는지 검증."""
    toast = page.locator(f"text={text}")
    expect(toast).to_be_visible(timeout=5000)


def click_button(page: Page, text: str) -> None:
    """텍스트로 버튼을 찾아 클릭."""
    page.get_by_role("button", name=text).click()


def expect_text(page: Page, text: str) -> None:
    """텍스트가 페이지에 표시되는지 검증."""
    expect(page.get_by_text(text)).to_be_visible(timeout=5000)


def expect_no_text(page: Page, text: str) -> None:
    """텍스트가 페이지에 표시되지 않는지 검증."""
    expect(page.get_by_text(text)).not_to_be_visible(timeout=3000)
