"""E2E 테스트 — 백테스트 데이터 페이지 검증.

사이드바 진입, 페이지 타이틀, 필터 탭, 데이터셋 테이블 구조,
빈 상태 안내, 도움말 텍스트, 페이지 레이아웃을 검증한다.

DataCatalog는 파일시스템 기반이므로 Docker E2E 환경에서는
데이터셋이 0건(빈 상태)으로 표시된다.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import expect

from tests.e2e.pages import Header, Sidebar

SCENARIO = "backtest-data"

pytestmark = [pytest.mark.e2e, pytest.mark.playwright]


# ── 1. 사이드바에서 백테스트 데이터 페이지 진입 ──────


def test_navigate_via_sidebar(authenticated_page, base_url: str) -> None:  # noqa: ANN001
    """사이드바 '백테스트 데이터' 클릭으로 /backtest-data 페이지에 진입한다."""
    page = authenticated_page
    sidebar = Sidebar(page)

    sidebar.navigate_to("백테스트 데이터")
    page.wait_for_timeout(2000)

    expect(page).to_have_url(f"{base_url}/backtest-data")


# ── 2. 페이지 타이틀 표시 ────────────────────────────


def test_page_title(authenticated_page, base_url: str) -> None:  # noqa: ANN001
    """백테스트 데이터 페이지에 '백테스트 데이터' 타이틀이 표시된다."""
    page = authenticated_page
    page.goto(f"{base_url}/backtest-data", wait_until="commit")
    page.wait_for_timeout(2000)

    header = Header(page)
    header.expect_title("백테스트 데이터")


# ── 3. 필터 탭 표시 ──────────────────────────────────


def test_filter_tabs(authenticated_page, base_url: str) -> None:  # noqa: ANN001
    """타임프레임 필터 탭(전체 타임프레임, 1일, 1시간, 1분)이 표시된다."""
    page = authenticated_page
    page.goto(f"{base_url}/backtest-data", wait_until="commit")
    page.wait_for_timeout(2000)

    # 타임프레임 필터 — <select> 드롭다운으로 구현
    select = page.locator("select").first
    expect(select).to_be_visible()

    # 옵션 값 확인
    options = select.locator("option")
    option_texts = options.all_text_contents()
    for label in ["전체 타임프레임", "1일", "1시간", "1분"]:
        assert label in option_texts, (
            f"'{label}' 옵션이 select에 없습니다: {option_texts}"
        )


# ── 4. 데이터셋 테이블 컬럼 헤더 ─────────────────────


def test_table_column_headers(authenticated_page, base_url: str) -> None:  # noqa: ANN001
    """데이터셋 테이블에 주요 컬럼 헤더가 존재한다."""
    page = authenticated_page
    page.goto(f"{base_url}/backtest-data", wait_until="commit")
    page.wait_for_timeout(2000)

    table = page.locator("table").first
    expect(table).to_be_visible()

    for col_text in ["종목", "타임프레임", "시작일", "종료일", "행 수"]:
        expect(
            table.locator("th").get_by_text(col_text, exact=False).first
        ).to_be_visible()


# ── 5. 빈 상태 안내 메시지 ────────────────────────────


def test_empty_state_message(authenticated_page, base_url: str) -> None:  # noqa: ANN001
    """DataCatalog가 비어 있으면 '데이터셋이 없습니다' 메시지가 표시된다."""
    page = authenticated_page
    page.goto(f"{base_url}/backtest-data", wait_until="commit")
    page.wait_for_timeout(2000)

    expect(page.get_by_text("데이터셋이 없습니다", exact=False).first).to_be_visible()


# ── 6. 도움말 텍스트 표시 ─────────────────────────────


def test_help_text(authenticated_page, base_url: str) -> None:  # noqa: ANN001
    """데이터 수집 안내 도움말 텍스트가 표시된다."""
    page = authenticated_page
    page.goto(f"{base_url}/backtest-data", wait_until="commit")
    page.wait_for_timeout(2000)

    expect(page.get_by_text("ante data collect", exact=False).first).to_be_visible()


# ── 7. 푸터 총건수 및 페이지 레이아웃 ─────────────────


def test_page_layout_and_footer(authenticated_page, base_url: str) -> None:  # noqa: ANN001
    """페이지 레이아웃이 정상이고 푸터에 총 건수가 표시된다."""
    page = authenticated_page
    page.goto(f"{base_url}/backtest-data", wait_until="commit")
    page.wait_for_timeout(2000)

    # React 루트가 비어있지 않음
    expect(page.locator("#root")).not_to_be_empty()

    # 에러 표시 텍스트가 없어야 함
    error_locator = page.get_by_text("오류가 발생", exact=False)
    if error_locator.count() > 0:
        expect(error_locator.first).not_to_be_visible()

    # 푸터에 총 0건 표시
    expect(page.get_by_text("총 0건", exact=False).first).to_be_visible()
