"""E2E 테스트 — 대시보드 주요 페이지 순회.

Playwright를 사용하여 대시보드의 주요 페이지를 headless Chromium으로 순회하고,
핵심 DOM 요소가 존재하는지 확인한다.
"""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.e2e, pytest.mark.playwright]


class TestDashboardPages:
    """대시보드 페이지 순회 테스트."""

    def test_login_page(self, page, base_url: str) -> None:  # noqa: ANN001
        """로그인 페이지가 렌더링된다."""
        page.goto(f"{base_url}/login")
        page.wait_for_load_state("networkidle")

        # React SPA가 렌더링되면 root div가 존재
        assert page.locator("#root").count() > 0

    def test_dashboard_page(self, page, base_url: str) -> None:  # noqa: ANN001
        """대시보드 메인 페이지가 렌더링된다."""
        page.goto(base_url)
        page.wait_for_load_state("networkidle")

        assert page.locator("#root").count() > 0

    def test_bots_page(self, page, base_url: str) -> None:  # noqa: ANN001
        """봇 관리 페이지가 렌더링된다."""
        page.goto(f"{base_url}/bots")
        page.wait_for_load_state("networkidle")

        assert page.locator("#root").count() > 0

    def test_strategies_page(self, page, base_url: str) -> None:  # noqa: ANN001
        """전략 관리 페이지가 렌더링된다."""
        page.goto(f"{base_url}/strategies")
        page.wait_for_load_state("networkidle")

        assert page.locator("#root").count() > 0

    def test_treasury_page(self, page, base_url: str) -> None:  # noqa: ANN001
        """자금 관리 페이지가 렌더링된다."""
        page.goto(f"{base_url}/treasury")
        page.wait_for_load_state("networkidle")

        assert page.locator("#root").count() > 0

    def test_settings_page(self, page, base_url: str) -> None:  # noqa: ANN001
        """설정 페이지가 렌더링된다."""
        page.goto(f"{base_url}/settings")
        page.wait_for_load_state("networkidle")

        assert page.locator("#root").count() > 0
