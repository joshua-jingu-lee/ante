"""E2E 테스트 — 설정 페이지 검증.

시스템 상태, 거래소 연결, 거래 설정, 표시 및 알림, 킬 스위치를 검증한다.

시드 데이터:
  - 시스템 상태: STOPPED (거래 정지)
  - 거래소: 한국투자증권, 모의투자
  - 거래 설정 10개 (기본값으로 표시)
  - 표시 및 알림 토글
"""

from __future__ import annotations

import pytest
from playwright.sync_api import expect

SCENARIO = "settings"

pytestmark = [pytest.mark.e2e, pytest.mark.playwright]


def _goto_settings(page, base_url: str) -> None:  # noqa: ANN001
    """설정 페이지로 이동하고 렌더링을 안정화한다."""
    page.goto(f"{base_url}/settings", wait_until="commit")
    page.wait_for_timeout(2000)


# ── 1. 설정 페이지 진입 및 제목 ──────────────────────


def test_settings_page_title(authenticated_page, base_url: str) -> None:  # noqa: ANN001
    """설정 페이지에 진입하면 '설정' 제목이 표시된다."""
    page = authenticated_page
    _goto_settings(page, base_url)

    expect(page).to_have_url(f"{base_url}/settings")
    expect(page.get_by_text("설정", exact=True).first).to_be_visible(timeout=5000)


# ── 2. 시스템 상태 섹션 ──────────────────────────────


def test_system_status_section(authenticated_page, base_url: str) -> None:  # noqa: ANN001
    """시스템 상태 섹션에 거래 상태와 거래 재개 버튼이 표시된다."""
    page = authenticated_page
    _goto_settings(page, base_url)

    # "시스템 상태" 섹션 제목
    expect(page.get_by_text("시스템 상태", exact=True).first).to_be_visible(
        timeout=5000
    )

    # 거래 정지 상태 메시지
    expect(page.get_by_text("거래가 정지되었습니다", exact=False).first).to_be_visible(
        timeout=5000
    )

    # 거래 재개 버튼
    resume_btn = page.get_by_role("button", name="거래 재개")
    expect(resume_btn).to_be_visible(timeout=5000)


# ── 3. 거래소 연결 정보 ──────────────────────────────


def test_exchange_connection_info(authenticated_page, base_url: str) -> None:  # noqa: ANN001
    """거래소 연결 섹션에 한국투자증권, 모의투자 정보가 표시된다."""
    page = authenticated_page
    _goto_settings(page, base_url)

    # "거래소 연결" 섹션 제목
    expect(page.get_by_text("거래소 연결", exact=True).first).to_be_visible(
        timeout=5000
    )

    # 거래소 이름
    expect(page.get_by_text("한국투자증권", exact=False).first).to_be_visible(
        timeout=5000
    )

    # 거래 모드
    expect(page.get_by_text("모의투자", exact=False).first).to_be_visible(timeout=5000)


# ── 4. 거래 설정 섹션 ────────────────────────────────


def test_trading_config_section(authenticated_page, base_url: str) -> None:  # noqa: ANN001
    """거래 설정 섹션에 설정 항목들이 표시된다."""
    page = authenticated_page
    _goto_settings(page, base_url)

    # "거래 설정" 섹션 제목
    expect(page.get_by_text("거래 설정", exact=True).first).to_be_visible(timeout=5000)

    # 주요 설정 항목 이름 확인 (일부만 검증)
    config_names = [
        "최대 낙폭 제한",
        "종목당 최대 비중",
        "일일 손실 한도",
        "총 노출 한도",
    ]
    for name in config_names:
        expect(page.get_by_text(name, exact=False).first).to_be_visible(timeout=5000)

    # 저장 버튼이 하나 이상 존재
    save_buttons = page.get_by_role("button", name="저장")
    assert save_buttons.count() >= 1, "저장 버튼이 존재하지 않음"


# ── 5. 거래 설정 항목 개수 ───────────────────────────


def test_trading_config_item_count(authenticated_page, base_url: str) -> None:  # noqa: ANN001
    """거래 설정 섹션에 10개의 설정 항목이 표시된다."""
    page = authenticated_page
    _goto_settings(page, base_url)

    # 저장 버튼 개수로 설정 항목 수 추정 (각 항목마다 저장 버튼 1개)
    save_buttons = page.get_by_role("button", name="저장")
    count = save_buttons.count()
    assert count >= 10, f"설정 항목이 10개 미만: {count}"


# ── 6. 표시 및 알림 섹션 ─────────────────────────────


def test_display_and_notification_section(authenticated_page, base_url: str) -> None:  # noqa: ANN001
    """표시 및 알림 섹션에 토글 항목들이 표시된다."""
    page = authenticated_page
    _goto_settings(page, base_url)

    # "표시 및 알림" 섹션 제목
    expect(page.get_by_text("표시 및 알림", exact=True).first).to_be_visible(
        timeout=5000
    )

    # 주요 토글 항목 확인
    toggle_items = ["체결 알림", "일일 리포트"]
    for item in toggle_items:
        expect(page.get_by_text(item, exact=False).first).to_be_visible(timeout=5000)


# ── 7. 킬 스위치 (거래 재개) 버튼 ────────────────────


def test_kill_switch_button(authenticated_page, base_url: str) -> None:  # noqa: ANN001
    """거래 재개 버튼이 존재하고 클릭 가능하다."""
    page = authenticated_page
    _goto_settings(page, base_url)

    resume_btn = page.get_by_role("button", name="거래 재개")
    expect(resume_btn).to_be_visible(timeout=5000)
    expect(resume_btn).to_be_enabled()
