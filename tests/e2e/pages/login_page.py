"""로그인 페이지 헬퍼."""

from __future__ import annotations

from playwright.sync_api import Page, expect


class LoginPage:
    """로그인 페이지 조작."""

    def __init__(self, page: Page, base_url: str) -> None:
        self.page = page
        self.base_url = base_url

    def goto(self) -> None:
        self.page.goto(f"{self.base_url}/login", wait_until="commit")
        # React SPA 렌더링 안정화 대기 — 인증 리다이렉트 사이클이 끝날 때까지
        self.page.wait_for_selector(
            'input[type="text"]',
            state="visible",
            timeout=15000,
        )
        # SPA 라우터 안정화를 위한 추가 대기
        self.page.wait_for_timeout(500)

    @property
    def member_id_input(self):  # noqa: ANN201
        return self.page.locator('input[type="text"]')

    @property
    def password_input(self):  # noqa: ANN201
        return self.page.locator('input[type="password"]')

    @property
    def submit_button(self):  # noqa: ANN201
        return self.page.locator('button[type="submit"]')

    @property
    def password_toggle(self):  # noqa: ANN201
        return self.page.get_by_title("패스워드 표시")

    def fill_credentials(self, member_id: str, password: str) -> None:
        self.member_id_input.fill(member_id, force=True)
        self.password_input.fill(password, force=True)

    def submit(self) -> None:
        self.submit_button.click()

    def login(self, member_id: str, password: str) -> None:
        self.fill_credentials(member_id, password)
        self.submit()

    def expect_error(self, text: str) -> None:
        error = self.page.locator(f"text={text}")
        expect(error).to_be_visible(timeout=5000)

    def expect_submit_disabled(self) -> None:
        expect(self.submit_button).to_be_disabled()

    def expect_submit_enabled(self) -> None:
        expect(self.submit_button).to_be_enabled()

    def expect_redirect_to_dashboard(self) -> None:
        self.page.wait_for_url(f"{self.base_url}/", timeout=10000)
        self.page.wait_for_load_state("domcontentloaded")
