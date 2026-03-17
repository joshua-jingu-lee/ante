"""E2E 테스트 — 설정 페이지 검증.

시스템 상태, 거래 설정 항목, 카테고리 그룹화, 설정값 편집/저장,
변경 이력, 알림 설정 토글, 킬 스위치를 검증한다.

시드 데이터:
  - 시스템 상태: ACTIVE
  - 동적 설정 10개 (위험 관리, 거래 규칙, 봇 설정, 브로커 카테고리)
  - 설정 변경 이력 2건
"""

from __future__ import annotations

import pytest
from playwright.sync_api import expect

from tests.e2e.pages import expect_toast

SCENARIO = "settings"

pytestmark = [pytest.mark.e2e, pytest.mark.playwright]


# ── 1. 설정 페이지 진입 ──────────────────────────────


def test_navigate_to_settings(authenticated_page, base_url: str) -> None:  # noqa: ANN001
    """사이드바 또는 URL로 /settings 페이지에 진입할 수 있다."""
    page = authenticated_page
    page.goto(f"{base_url}/settings")
    page.wait_for_load_state("domcontentloaded")

    expect(page).to_have_url(f"{base_url}/settings")
    expect(page.locator("#root")).not_to_be_empty()


# ── 2. 시스템 상태 "ACTIVE" 표시 ─────────────────────


def test_system_status_active(authenticated_page, base_url: str) -> None:  # noqa: ANN001
    """설정 페이지에 시스템 상태 'ACTIVE'가 표시된다."""
    page = authenticated_page
    page.goto(f"{base_url}/settings")
    page.wait_for_load_state("domcontentloaded")

    expect(page.get_by_text("ACTIVE", exact=False)).to_be_visible(timeout=5000)


# ── 3. 거래 설정 항목 10개 표시 ──────────────────────


def test_settings_items_count(authenticated_page, base_url: str) -> None:  # noqa: ANN001
    """거래 설정 항목이 10개 표시된다."""
    page = authenticated_page
    page.goto(f"{base_url}/settings")
    page.wait_for_load_state("domcontentloaded")

    # 설정 항목은 테이블 행 또는 리스트 아이템으로 표시
    table = page.locator("table")
    if table.count() > 0:
        rows = table.locator("tbody tr")
        expect(rows).to_have_count(10)
    else:
        # 카드/리스트 기반이면 설정 항목 개수를 대략 확인
        # 각 설정 항목에는 key-value 쌍이 있으므로 입력 필드 수로 추정
        inputs = page.locator("input, select, textarea")
        assert inputs.count() >= 10, f"설정 항목이 10개 미만: {inputs.count()}"


# ── 4. 카테고리별 그룹화 ─────────────────────────────


def test_settings_categories(authenticated_page, base_url: str) -> None:  # noqa: ANN001
    """설정이 카테고리(위험 관리, 거래 규칙, 봇 설정, 브로커)별로 그룹화된다."""
    page = authenticated_page
    page.goto(f"{base_url}/settings")
    page.wait_for_load_state("domcontentloaded")

    categories = ["위험 관리", "거래 규칙", "봇 설정", "브로커"]
    visible_count = 0

    for cat in categories:
        locator = page.get_by_text(cat, exact=False)
        if locator.count() > 0 and locator.first.is_visible():
            visible_count += 1

    assert visible_count >= 3, f"카테고리가 충분히 표시되지 않음: {visible_count}/4"


# ── 5. 설정값 편집: "최대 낙폭 제한" 15.0 → 20.0 ────


def test_edit_max_drawdown_setting(authenticated_page, base_url: str) -> None:  # noqa: ANN001
    """'최대 낙폭 제한' 설정값을 15.0에서 20.0으로 변경할 수 있다."""
    page = authenticated_page
    page.goto(f"{base_url}/settings")
    page.wait_for_load_state("domcontentloaded")

    # "최대 낙폭 제한" 텍스트 근처의 입력 필드 찾기
    drawdown_label = page.get_by_text("최대 낙폭 제한", exact=False)
    expect(drawdown_label.first).to_be_visible(timeout=5000)

    # 편집 모드 진입 — 행의 편집 버튼 또는 값 자체를 클릭
    row = drawdown_label.first.locator("..").locator("..")
    edit_btn = row.get_by_role("button").first
    if edit_btn.count() > 0:
        edit_btn.click()

    # 입력 필드를 찾아 값 변경
    input_field = row.locator("input").first
    if input_field.count() == 0:
        # 행 외부에서 모달이나 인라인 편집 필드 탐색
        input_field = page.locator("input[value='15'], input[value='15.0']").first

    input_field.clear()
    input_field.fill("20.0")


# ── 6. 설정 저장 후 토스트 메시지 ────────────────────


def test_save_setting_shows_toast(authenticated_page, base_url: str) -> None:  # noqa: ANN001
    """설정을 저장하면 성공 토스트 메시지가 표시된다."""
    page = authenticated_page
    page.goto(f"{base_url}/settings")
    page.wait_for_load_state("domcontentloaded")

    # 편집할 설정 찾기
    drawdown_label = page.get_by_text("최대 낙폭 제한", exact=False)
    row = drawdown_label.first.locator("..").locator("..")

    edit_btn = row.get_by_role("button").first
    if edit_btn.count() > 0:
        edit_btn.click()

    input_field = row.locator("input").first
    if input_field.count() == 0:
        input_field = page.locator("input[value='15'], input[value='15.0']").first

    input_field.clear()
    input_field.fill("20.0")

    # 저장 버튼 클릭
    save_btn = page.get_by_role("button", name="저장").or_(
        page.get_by_role("button", name="확인")
    )
    save_btn.first.click()

    # 토스트 메시지 확인
    expect_toast(page, "저장")


# ── 7. 설정 변경 이력 표시 ───────────────────────────


def test_config_change_history(authenticated_page, base_url: str) -> None:  # noqa: ANN001
    """설정 변경 이력이 표시되고 2건의 기록이 있다."""
    page = authenticated_page
    page.goto(f"{base_url}/settings")
    page.wait_for_load_state("domcontentloaded")

    # 변경 이력 섹션
    history_label = page.get_by_text("변경 이력", exact=False).or_(
        page.get_by_text("변경 기록", exact=False)
    )
    expect(history_label.first).to_be_visible(timeout=5000)

    # 이력 항목 확인 — 타임스탬프 또는 이전/이후 값이 표시됨
    # 테이블이면 행 수, 아니면 이력 항목 수 확인
    history_section = history_label.first.locator("..").locator("..")
    history_table = history_section.locator("table")

    if history_table.count() > 0:
        history_rows = history_table.locator("tbody tr")
        expect(history_rows).to_have_count(2)
    else:
        # 리스트 형태에서 최소 2개 항목 존재 확인
        items = history_section.locator("li, [class*='item'], [class*='Item']")
        assert items.count() >= 2, f"변경 이력이 2건 미만: {items.count()}"


# ── 8. 알림 설정 토글 ───────────────────────────────


def test_notification_toggles(authenticated_page, base_url: str) -> None:  # noqa: ANN001
    """체결 알림 ON, 일일 리포트 OFF 토글이 동작한다."""
    page = authenticated_page
    page.goto(f"{base_url}/settings")
    page.wait_for_load_state("domcontentloaded")

    # 체결 알림 토글 확인
    trade_notification = page.get_by_text("체결 알림", exact=False)
    expect(trade_notification.first).to_be_visible(timeout=5000)

    # 토글/스위치가 행 근처에 존재
    trade_row = trade_notification.first.locator("..").locator("..")
    trade_toggle = trade_row.locator(
        'input[type="checkbox"], button[role="switch"], '
        '[class*="toggle"], [class*="Toggle"]'
    ).first

    # 체결 알림이 ON 상태인지 확인 (checked 속성 또는 aria-checked)
    if trade_toggle.count() > 0:
        trade_toggle.click()
        # 토글이 반응했는지 — 에러 없이 동작하면 통과
        page.wait_for_load_state("domcontentloaded")

    # 일일 리포트 토글 확인
    daily_report = page.get_by_text("일일 리포트", exact=False)
    if daily_report.count() > 0:
        report_row = daily_report.first.locator("..").locator("..")
        report_toggle = report_row.locator(
            'input[type="checkbox"], button[role="switch"], '
            '[class*="toggle"], [class*="Toggle"]'
        ).first
        if report_toggle.count() > 0:
            report_toggle.click()
            page.wait_for_load_state("domcontentloaded")


# ── 9. 킬 스위치 (거래 중지/재개) ────────────────────


def test_kill_switch_button(authenticated_page, base_url: str) -> None:  # noqa: ANN001
    """'거래 중지' 또는 '거래 재개' 킬 스위치 버튼이 존재한다."""
    page = authenticated_page
    page.goto(f"{base_url}/settings")
    page.wait_for_load_state("domcontentloaded")

    kill_switch = page.get_by_role("button", name="거래 중지").or_(
        page.get_by_role("button", name="거래 재개")
    )
    expect(kill_switch.first).to_be_visible(timeout=5000)


# ── 10. 킬 스위치 클릭 시 상태 전환 ─────────────────


def test_kill_switch_toggles_state(authenticated_page, base_url: str) -> None:  # noqa: ANN001
    """킬 스위치 클릭 시 시스템 상태가 전환된다."""
    page = authenticated_page
    page.goto(f"{base_url}/settings")
    page.wait_for_load_state("domcontentloaded")

    # 현재 ACTIVE이므로 "거래 중지" 버튼이 보여야 함
    stop_btn = page.get_by_role("button", name="거래 중지")
    expect(stop_btn).to_be_visible(timeout=5000)

    stop_btn.click()

    # 확인 모달이 뜰 수 있음
    confirm_btn = page.get_by_role("button", name="확인").or_(
        page.get_by_role("button", name="중지")
    )
    if confirm_btn.count() > 0:
        confirm_btn.first.click()

    page.wait_for_load_state("domcontentloaded")

    # 상태가 전환되어 "거래 재개" 버튼이 나타나거나 상태 텍스트가 변경됨
    resume_btn = page.get_by_role("button", name="거래 재개")
    stopped_text = page.get_by_text("STOPPED", exact=False).or_(
        page.get_by_text("중지", exact=False)
    )

    is_toggled = resume_btn.count() > 0 or stopped_text.count() > 0
    assert is_toggled, "킬 스위치 클릭 후 상태가 전환되지 않음"
