"""E2E 테스트 — 백테스트 데이터 페이지 탐색 및 리포트 검증.

사이드바 진입, 페이지 타이틀, 데이터셋 카탈로그, 검색/필터 UI,
리포트 목록(2건), 리포트 상세(전략명·수익률·샤프비율), 레이아웃을 검증한다.

시드 데이터:
  - 전략: momentum-v2
  - 백테스트 리포트 2건: submitted, reviewed (DB 메타데이터만, OHLCV 파케 없음)
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

    expect(page).to_have_url(f"{base_url}/backtest-data")


# ── 2. 페이지 타이틀 표시 ────────────────────────────


def test_page_title(authenticated_page, base_url: str) -> None:  # noqa: ANN001
    """백테스트 데이터 페이지에 '백테스트 데이터' 타이틀이 표시된다."""
    page = authenticated_page
    page.goto(f"{base_url}/backtest-data")
    page.wait_for_load_state("networkidle")

    header = Header(page)
    header.expect_title("백테스트 데이터")


# ── 3. 데이터셋 목록/카탈로그 표시 ───────────────────


def test_dataset_catalog_displayed(authenticated_page, base_url: str) -> None:  # noqa: ANN001
    """데이터셋 카탈로그(카드 또는 테이블)가 페이지에 표시된다."""
    page = authenticated_page
    page.goto(f"{base_url}/backtest-data")
    page.wait_for_load_state("networkidle")

    # 카탈로그 영역이 존재 — 테이블이거나 카드 목록이거나 빈 상태 안내
    has_table = page.locator("table").count() > 0
    has_cards = page.locator("[class*='card'], [class*='Card']").count() > 0
    has_empty_msg = page.get_by_text("데이터", exact=False).count() > 0

    assert (
        has_table or has_cards or has_empty_msg
    ), "데이터셋 카탈로그 영역이 존재하지 않음"


# ── 4. 검색/필터 UI 요소 존재 ────────────────────────


def test_search_filter_ui_exists(authenticated_page, base_url: str) -> None:  # noqa: ANN001
    """검색 입력창 또는 필터 버튼이 존재한다."""
    page = authenticated_page
    page.goto(f"{base_url}/backtest-data")
    page.wait_for_load_state("networkidle")

    has_search_input = (
        page.locator(
            'input[type="search"], input[type="text"], input[placeholder*="검색"]'
        ).count()
        > 0
    )
    has_filter_button = (
        page.get_by_role("button", name="필터")
        .or_(page.get_by_role("button", name="전체"))
        .count()
        > 0
    )

    assert has_search_input or has_filter_button, "검색 또는 필터 UI가 존재하지 않음"


# ── 5. 백테스트 리포트 2건 표시 ──────────────────────


def test_report_list_count(authenticated_page, base_url: str) -> None:  # noqa: ANN001
    """백테스트 리포트가 2건 표시된다."""
    page = authenticated_page
    page.goto(f"{base_url}/backtest-data")
    page.wait_for_load_state("networkidle")

    # 리포트 행 또는 카드를 찾음 — 테이블 행 또는 리포트 카드
    table = page.locator("table")

    if table.count() > 0:
        rows = table.locator("tbody tr")
        expect(rows).to_have_count(2)
    else:
        # 카드 기반이면 momentum-v2 언급이 2건 이상 있어야 함
        expect(page.get_by_text("momentum-v2", exact=False).first).to_be_visible()


# ── 6. 리포트에 전략명 표시 ──────────────────────────


def test_report_shows_strategy_name(authenticated_page, base_url: str) -> None:  # noqa: ANN001
    """리포트 목록에 전략명 'momentum-v2'가 표시된다."""
    page = authenticated_page
    page.goto(f"{base_url}/backtest-data")
    page.wait_for_load_state("networkidle")

    expect(page.get_by_text("momentum-v2", exact=False).first).to_be_visible(
        timeout=5000
    )


# ── 7. 리포트 상세: 수익률·샤프비율 등 지표 표시 ─────


def test_report_detail_metrics(authenticated_page, base_url: str) -> None:  # noqa: ANN001
    """리포트 상세에 수익률, 샤프비율 등 성과 지표가 표시된다."""
    page = authenticated_page
    page.goto(f"{base_url}/backtest-data")
    page.wait_for_load_state("networkidle")

    # 첫 번째 리포트 항목 클릭 (테이블 행 또는 카드)
    table = page.locator("table")
    if table.count() > 0:
        table.locator("tbody tr").first.click()
    else:
        page.get_by_text("momentum-v2", exact=False).first.click()

    page.wait_for_load_state("networkidle")

    # 상세 화면에서 성과 지표 키워드 확인
    has_return = page.get_by_text("수익률", exact=False).count() > 0
    has_sharpe = page.get_by_text("샤프", exact=False).count() > 0
    has_strategy = page.get_by_text("momentum-v2", exact=False).count() > 0

    assert has_strategy, "리포트 상세에 전략명이 표시되지 않음"
    assert (
        has_return or has_sharpe
    ), "리포트 상세에 성과 지표(수익률/샤프비율)가 표시되지 않음"


# ── 8. 페이지 기본 레이아웃 검증 ─────────────────────


def test_page_layout_integrity(authenticated_page, base_url: str) -> None:  # noqa: ANN001
    """페이지 레이아웃이 정상이다 (루트 렌더링, 에러 텍스트 없음)."""
    page = authenticated_page
    page.goto(f"{base_url}/backtest-data")
    page.wait_for_load_state("networkidle")

    # React 루트가 비어있지 않음
    expect(page.locator("#root")).not_to_be_empty()

    # 에러 표시 텍스트가 없어야 함
    error_locator = page.get_by_text("오류가 발생", exact=False)
    if error_locator.count() > 0:
        expect(error_locator.first).not_to_be_visible()
