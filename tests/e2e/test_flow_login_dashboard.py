"""E2E 테스트 — 로그인 → 대시보드 흐름.

비인증 리다이렉트, 로그인 폼 유효성, 로그인 성공/실패,
대시보드 포트폴리오/승인대기 섹션, 사이드바, 사용자 메뉴, 로그아웃을 검증한다.
"""

from __future__ import annotations

import os
import re

import pytest
from playwright.sync_api import expect

from tests.e2e.pages import Header, LoginPage, Sidebar

SCENARIO = "login-dashboard"

pytestmark = [pytest.mark.e2e, pytest.mark.playwright]


# ── 1. 비인증 사용자 → /login 리다이렉트 ─────────────


def test_unauthenticated_redirect(page, base_url: str, seed_scenario: str) -> None:  # noqa: ANN001, ARG001
    """비인증 상태에서 / 접속 시 /login으로 리다이렉트된다."""
    page.goto(base_url)
    page.wait_for_load_state("networkidle")

    expect(page).to_have_url(f"{base_url}/login")
    expect(page.get_by_text("AI-Native Trading Engine")).to_be_visible()


# ── 2. 로그인 폼 유효성 검증 ─────────────────────────


def test_login_form_validation(page, base_url: str, seed_scenario: str) -> None:  # noqa: ANN001, ARG001
    """빈 폼 → 비활성, ID만 → 비활성, ID+PW → 활성."""
    login = LoginPage(page, base_url)
    login.goto()

    # 빈 폼: 버튼 비활성
    login.expect_submit_disabled()

    # ID만 입력: 여전히 비활성
    login.member_id_input.fill("owner")
    login.expect_submit_disabled()

    # ID + PW 입력: 활성
    login.password_input.fill("anything")
    login.expect_submit_enabled()


# ── 3. 패스워드 표시 토글 ────────────────────────────


def test_password_toggle(page, base_url: str, seed_scenario: str) -> None:  # noqa: ANN001, ARG001
    """패스워드 마스킹 ↔ 평문 토글이 동작한다."""
    login = LoginPage(page, base_url)
    login.goto()

    login.password_input.fill("testpass")

    # 기본: 마스킹
    expect(login.password_input).to_have_attribute("type", "password")

    # 토글 클릭: 평문
    login.password_toggle.click()
    # 토글 후 type이 text로 변경되어야 함
    expect(page.locator('input[type="text"]').last).to_have_value("testpass")

    # 다시 토글: 마스킹 복원
    login.password_toggle.click()
    expect(login.password_input).to_have_attribute("type", "password")


# ── 4. 로그인 실패 ───────────────────────────────────


def test_login_failure(page, base_url: str, seed_scenario: str) -> None:  # noqa: ANN001, ARG001
    """잘못된 인증정보로 로그인 시 에러 메시지가 표시된다."""
    login = LoginPage(page, base_url)
    login.goto()

    login.login("wrong_user", "wrong_pass")

    login.expect_error("ID 또는 패스워드가 올바르지 않습니다")
    expect(page).to_have_url(f"{base_url}/login")


# ── 5. 로그인 성공 → 대시보드 이동 ───────────────────


def test_login_success(page, base_url: str, seed_scenario: str) -> None:  # noqa: ANN001, ARG001
    """올바른 인증정보로 로그인하면 대시보드로 이동한다."""
    password = os.environ.get("E2E_TEST_PASSWORD", "test1234")
    login = LoginPage(page, base_url)
    login.goto()

    login.fill_credentials("owner", password)
    login.submit()

    # 로그인 중... 텍스트 확인 (빠르게 사라질 수 있으므로 soft check)
    # 대시보드로 이동
    login.expect_redirect_to_dashboard()

    header = Header(page)
    header.expect_title("대시보드")
    header.expect_system_status("ACTIVE")

    # 사용자 정보 확인
    user_info = header.get_user_info()
    assert "owner" in user_info


# ── 6. 대시보드 포트폴리오 섹션 ──────────────────────


def test_dashboard_portfolio(authenticated_page, base_url: str) -> None:  # noqa: ANN001
    """대시보드에 총 자산과 기간 선택 버튼이 표시된다."""
    page = authenticated_page

    # 총 자산 표시
    expect(page.get_by_text("10,000,000")).to_be_visible(timeout=5000)

    # 기간 선택 버튼 존재
    for label in ["1일", "1주", "1개월", "3개월", "전체"]:
        expect(page.get_by_role("button", name=label)).to_be_visible()


# ── 7. 기간 선택 전환 동작 ───────────────────────────


def test_period_switch(authenticated_page, base_url: str) -> None:  # noqa: ANN001
    """기간 선택 버튼 클릭 시 활성 상태가 전환된다."""
    page = authenticated_page

    month_btn = page.get_by_role("button", name="1개월")
    month_btn.click()

    # 1개월 버튼이 활성 스타일(파란 배경)을 가져야 함
    expect(month_btn).to_have_class(re.compile(r"bg-"))

    # 페이지가 에러 없이 유지됨
    expect(page.locator("#root")).not_to_be_empty()


# ── 8. 승인 대기 섹션 ───────────────────────────────


def test_pending_approvals(authenticated_page, base_url: str) -> None:  # noqa: ANN001
    """승인 대기 섹션에 2건이 표시되고 전체 보기 링크가 있다."""
    page = authenticated_page

    # 승인 대기 제목
    expect(page.get_by_text("승인 대기")).to_be_visible(timeout=5000)

    # 뱃지에 2건 표시
    expect(page.get_by_text("2건")).to_be_visible()

    # "전체 보기 →" 링크가 /approvals로 연결
    view_all = page.get_by_text("전체 보기 →")
    expect(view_all).to_be_visible()
    expect(view_all).to_have_attribute("href", "/approvals")


# ── 9. 사이드바 네비게이션 ───────────────────────────


def test_sidebar_navigation(authenticated_page, base_url: str) -> None:  # noqa: ANN001
    """사이드바에 7개 메뉴 항목이 표시되고 결재함에 뱃지가 있다."""
    page = authenticated_page
    sidebar = Sidebar(page)

    # 7개 메뉴 항목
    sidebar.expect_menu_count(7)

    # 주요 메뉴 텍스트 존재 확인
    for label in [
        "대시보드",
        "결재함",
        "자금관리",
        "전략과 성과",
        "봇 관리",
        "백테스트 데이터",
        "멤버 관리",
    ]:
        expect(page.get_by_text(label)).to_be_visible()

    # 결재함 뱃지 확인
    badge_text = sidebar.get_badge_text("결재함")
    assert badge_text is not None
    assert "2" in badge_text


# ── 10. 사용자 메뉴 ──────────────────────────────────


def test_user_menu(authenticated_page, base_url: str) -> None:  # noqa: ANN001
    """사용자 메뉴에 설정과 로그아웃이 표시된다."""
    page = authenticated_page
    header = Header(page)

    header.open_user_menu()

    # 드롭다운에 설정, 로그아웃 표시
    expect(page.get_by_text("설정")).to_be_visible(timeout=3000)
    expect(page.get_by_text("로그아웃")).to_be_visible()


# ── 11. 로그아웃 → /login 이동 ───────────────────────


def test_logout(authenticated_page, base_url: str) -> None:  # noqa: ANN001
    """로그아웃 시 /login 페이지로 이동한다."""
    page = authenticated_page
    header = Header(page)

    header.open_user_menu()
    header.click_logout()

    page.wait_for_load_state("networkidle")
    expect(page).to_have_url(f"{base_url}/login")

    # 로그아웃 후 / 접속 시 다시 /login으로 리다이렉트
    page.goto(base_url)
    page.wait_for_load_state("networkidle")
    expect(page).to_have_url(f"{base_url}/login")
