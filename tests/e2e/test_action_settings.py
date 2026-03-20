"""E2E 테스트 — 설정 변경·킬 스위치 액션 플로우.

설정값 편집·저장, 페이지 새로고침 후 영속성, 킬 스위치(ACTIVE→HALTED→ACTIVE),
알림 토글, API 교차 검증을 순서대로 검증한다.

시드 데이터:
  - 시스템 상태: ACTIVE (거래 정상 운용)
  - dynamic_config 12개 (거래 설정 10개 + 알림 2개)
  - 기존 변경 이력 2건
"""

from __future__ import annotations

import httpx
import pytest
from playwright.sync_api import Page, expect

SCENARIO = "action-settings"

pytestmark = [pytest.mark.e2e, pytest.mark.playwright]


# ── 헬퍼 ─────────────────────────────────────────────


def _goto_settings(page: Page, base_url: str) -> None:
    """설정 페이지로 이동하고 데이터가 로드될 때까지 대기한다."""
    page.goto(f"{base_url}/settings", wait_until="networkidle")
    # 거래 설정 테이블이 렌더링될 때까지 대기
    page.wait_for_selector("table", state="visible", timeout=10000)
    page.wait_for_timeout(1000)


def _api_get_system_status(api_url: str) -> dict:
    """API로 시스템 상태를 조회하여 반환한다."""
    resp = httpx.get(f"{api_url}/system/status", timeout=10)
    assert resp.status_code == 200, f"API 조회 실패: {resp.text}"
    return resp.json()


def _api_get_config(api_url: str) -> list[dict]:
    """API로 동적 설정 목록을 조회하여 반환한다."""
    resp = httpx.get(f"{api_url}/config", timeout=10)
    assert resp.status_code == 200, f"API 조회 실패: {resp.text}"
    data = resp.json()
    return data.get("configs", data)


def _find_config(configs: list[dict], key: str) -> dict | None:
    """설정 목록에서 key로 항목을 찾는다."""
    for cfg in configs:
        if cfg.get("key") == key:
            return cfg
    return None


def _api_set_system_state(api_url: str, action: str, reason: str = "") -> None:
    """API로 시스템 상태를 변경한다."""
    endpoint = "halt" if action == "halt" else "activate"
    resp = httpx.post(
        f"{api_url}/system/{endpoint}",
        json={"reason": reason},
        timeout=10,
    )
    assert resp.status_code == 200, f"시스템 상태 변경 실패: {resp.text}"


def _api_update_config(api_url: str, key: str, value: str) -> None:
    """API로 동적 설정 값을 변경한다."""
    resp = httpx.put(
        f"{api_url}/config/{key}",
        json={"value": value},
        timeout=10,
    )
    assert resp.status_code == 200, f"설정 변경 실패: {resp.text}"


def _find_toggle_button(page: Page, label_text: str):
    """표시 및 알림 섹션에서 라벨 텍스트에 해당하는 토글 버튼을 반환한다.

    DOM 구조:
      div.flex.items-center.justify-between
        div > div(label) + div(desc)
        button(toggle)
    """
    # XPath: 라벨 div → 부모 flex 컨테이너 → 토글 버튼
    xpath = (
        f"//div[contains(@class,'font-medium')"
        f" and contains(text(),'{label_text}')]"
        "/ancestor::div[contains(@class,'justify-between')]"
        "/button[contains(@class,'rounded')]"
    )
    return page.locator(f"xpath={xpath}").first


def _wait_for_config_loaded(page: Page, config_key: str) -> None:
    """설정 값이 입력 필드에 로드될 때까지 대기한다."""
    row = page.get_by_text(config_key, exact=False).locator("xpath=ancestor::tr")
    input_field = row.locator("input")
    # 입력 필드가 표시되고 값이 로드될 때까지 대기
    expect(input_field).to_be_visible(timeout=10000)
    # 값이 빈 문자열이 아닐 때까지 대기 (최대 5초)
    try:
        page.wait_for_function(
            """(key) => {
                const cells = document.querySelectorAll('td');
                for (const cell of cells) {
                    if (cell.textContent && cell.textContent.includes(key)) {
                        const row = cell.closest('tr');
                        if (row) {
                            const input = row.querySelector('input');
                            if (input && input.value) return true;
                        }
                    }
                }
                return false;
            }""",
            config_key,
            timeout=5000,
        )
    except Exception:
        pass  # 값이 비어있을 수도 있음 (최초 생성 시)


# ── 설정값 편집·저장 ──────────────────────────────────


class TestConfigEdit:
    """거래 설정값 편집·저장 플로우."""

    def test_config_input_is_editable(
        self, authenticated_page: Page, base_url: str
    ) -> None:
        """'최대 낙폭 제한' 설정 입력 필드가 편집 가능하다."""
        _goto_settings(authenticated_page, base_url)
        page = authenticated_page

        # risk.max_mdd_pct 행의 입력 필드
        row = page.get_by_text("risk.max_mdd_pct", exact=False).locator(
            "xpath=ancestor::tr"
        )
        input_field = row.locator("input")

        expect(input_field).to_be_visible()
        expect(input_field).to_be_editable()

    def test_config_edit_and_save_updates_value(
        self, authenticated_page: Page, base_url: str
    ) -> None:
        """설정값을 변경 후 저장 버튼 클릭 시 값이 반영된다."""
        _goto_settings(authenticated_page, base_url)
        page = authenticated_page

        # risk.max_mdd_pct 행 탐색
        row = page.get_by_text("risk.max_mdd_pct", exact=False).locator(
            "xpath=ancestor::tr"
        )
        input_field = row.locator("input")
        save_btn = row.locator("button", has_text="저장")

        # 새로운 값 입력 후 저장
        input_field.click(click_count=3)
        input_field.fill("12.5")
        save_btn.click()
        page.wait_for_timeout(1500)

        # 입력 필드에 변경된 값이 유지됨
        expect(input_field).to_have_value("12.5")

    def test_config_edit_with_enter_key(
        self, authenticated_page: Page, base_url: str
    ) -> None:
        """입력 필드에서 Enter 키 입력으로도 저장이 실행된다."""
        _goto_settings(authenticated_page, base_url)
        page = authenticated_page

        row = page.get_by_text("rule.daily_loss_limit", exact=False).locator(
            "xpath=ancestor::tr"
        )
        input_field = row.locator("input")

        # Enter 키로 저장
        input_field.click(click_count=3)
        input_field.fill("4.5")
        input_field.press("Enter")
        page.wait_for_timeout(1500)

        expect(input_field).to_have_value("4.5")

    def test_config_edit_persistence_after_refresh(
        self, authenticated_page: Page, base_url: str, api_url: str
    ) -> None:
        """저장된 설정값이 페이지 새로고침 후에도 유지된다."""
        page = authenticated_page

        # API로 직접 값을 변경하여 저장을 확실하게 보장
        _api_update_config(api_url, "rule.max_exposure_percent", "25.0")

        # 설정 페이지로 이동하여 저장된 값이 표시되는지 확인
        _goto_settings(page, base_url)
        _wait_for_config_loaded(page, "rule.max_exposure_percent")

        row = page.get_by_text("rule.max_exposure_percent", exact=False).locator(
            "xpath=ancestor::tr"
        )
        input_field = row.locator("input")
        expect(input_field).to_have_value("25.0", timeout=5000)

        # 페이지 새로고침
        page.reload(wait_until="networkidle")
        page.wait_for_selector("table", state="visible", timeout=10000)
        page.wait_for_timeout(1000)

        # 새로고침 후에도 저장된 값이 표시됨
        _wait_for_config_loaded(page, "rule.max_exposure_percent")
        row_after = page.get_by_text("rule.max_exposure_percent", exact=False).locator(
            "xpath=ancestor::tr"
        )
        input_after = row_after.locator("input")
        expect(input_after).to_have_value("25.0", timeout=5000)

    def test_config_edit_api_cross_validation(
        self,
        authenticated_page: Page,
        base_url: str,
        api_url: str,
    ) -> None:
        """설정값이 API와 UI 간에 일관되게 반영된다."""
        page = authenticated_page

        # API로 직접 값을 변경
        _api_update_config(api_url, "broker.commission_rate", "0.020")

        # API 교차 검증 — 저장된 값이 조회에 반영됨
        configs = _api_get_config(api_url)
        cfg = _find_config(configs, "broker.commission_rate")
        assert cfg is not None, "broker.commission_rate 설정을 API에서 찾을 수 없음"
        assert str(cfg["value"]) == "0.020", (
            f"API 반환 값이 예상과 다름: {cfg['value']}"
        )

        # UI에서도 변경된 값이 표시되는지 확인
        _goto_settings(page, base_url)
        _wait_for_config_loaded(page, "broker.commission_rate")

        row = page.get_by_text("broker.commission_rate", exact=False).locator(
            "xpath=ancestor::tr"
        )
        input_field = row.locator("input")
        expect(input_field).to_have_value("0.020", timeout=5000)


# ── 킬 스위치 (ACTIVE → HALTED) ──────────────────────


class TestKillSwitchHalt:
    """비상 거래 정지 (ACTIVE → HALTED) 플로우."""

    def test_active_state_shows_halt_button(
        self, authenticated_page: Page, base_url: str, api_url: str
    ) -> None:
        """ACTIVE 상태에서 '비상 거래 정지' 버튼이 표시된다."""
        # 시스템 상태를 확실히 ACTIVE로 설정
        _api_set_system_state(api_url, "activate")

        _goto_settings(authenticated_page, base_url)
        page = authenticated_page

        expect(
            page.get_by_text("현재 모든 봇의 거래가 정상 운용 중입니다.", exact=False)
        ).to_be_visible(timeout=5000)
        expect(page.get_by_role("button", name="비상 거래 정지")).to_be_visible()

    def test_halt_button_opens_confirm_modal(
        self, authenticated_page: Page, base_url: str, api_url: str
    ) -> None:
        """'비상 거래 정지' 버튼 클릭 시 확인 모달이 열린다."""
        _api_set_system_state(api_url, "activate")

        _goto_settings(authenticated_page, base_url)
        page = authenticated_page

        page.get_by_role("button", name="비상 거래 정지").click()
        page.wait_for_timeout(500)

        # 모달 제목 확인
        expect(page.get_by_text("비상 거래 정지", exact=True).first).to_be_visible()
        # 정지 사유 입력 필드 확인
        expect(page.get_by_placeholder("예: 긴급 시장 변동")).to_be_visible()

    def test_halt_modal_cancel_closes_modal(
        self, authenticated_page: Page, base_url: str, api_url: str
    ) -> None:
        """모달에서 취소 버튼 클릭 시 모달이 닫히고 상태가 변경되지 않는다."""
        _api_set_system_state(api_url, "activate")

        _goto_settings(authenticated_page, base_url)
        page = authenticated_page

        page.get_by_role("button", name="비상 거래 정지").click()
        page.wait_for_timeout(500)

        page.get_by_role("button", name="취소").click()
        page.wait_for_timeout(500)

        # 비상 거래 정지 버튼이 여전히 표시됨 (상태 미변경)
        expect(page.get_by_role("button", name="비상 거래 정지")).to_be_visible()

    def test_halt_with_reason_changes_state_to_stopped(
        self, authenticated_page: Page, base_url: str, api_url: str
    ) -> None:
        """정지 사유 입력 후 확인 시 시스템 상태가 거래 정지로 전환된다."""
        _api_set_system_state(api_url, "activate")

        _goto_settings(authenticated_page, base_url)
        page = authenticated_page

        # 비상 거래 정지 버튼 클릭
        page.get_by_role("button", name="비상 거래 정지").click()
        page.wait_for_timeout(500)

        # 정지 사유 입력
        reason_input = page.get_by_placeholder("예: 긴급 시장 변동")
        reason_input.fill("긴급 시장 급락 대응")
        page.wait_for_timeout(300)

        # 거래 정지 확인 버튼 클릭
        page.get_by_role("button", name="거래 정지 확인").click()
        page.wait_for_timeout(2000)

        # 정지 상태 메시지 확인
        expect(page.get_by_text("거래가 정지되었습니다", exact=False)).to_be_visible(
            timeout=5000
        )
        # 거래 재개 버튼이 표시됨
        expect(page.get_by_role("button", name="거래 재개")).to_be_visible()

    def test_halt_api_cross_validation(
        self,
        authenticated_page: Page,
        base_url: str,
        api_url: str,
    ) -> None:
        """정지 후 API 조회 시 trading_status가 HALTED임을 확인한다."""
        # 이전 테스트에서 HALTED 상태로 전환되었을 수 있으나,
        # 독립적으로 HALTED 상태를 보장한다.
        _api_set_system_state(api_url, "halt", reason="API 교차 검증용")

        status = _api_get_system_status(api_url)
        assert status["trading_status"] == "HALTED", (
            f"API 반환 상태가 HALTED가 아님: {status['trading_status']}"
        )


# ── 킬 스위치 (HALTED → ACTIVE) ──────────────────────


class TestKillSwitchResume:
    """거래 재개 (HALTED → ACTIVE) 플로우."""

    def test_stopped_state_shows_resume_button(
        self, authenticated_page: Page, base_url: str, api_url: str
    ) -> None:
        """HALTED 상태에서 '거래 재개' 버튼이 표시된다."""
        _api_set_system_state(api_url, "halt", reason="테스트 준비")

        _goto_settings(authenticated_page, base_url)
        page = authenticated_page

        expect(page.get_by_text("거래가 정지되었습니다", exact=False)).to_be_visible(
            timeout=5000
        )
        expect(page.get_by_role("button", name="거래 재개")).to_be_visible()

    def test_resume_changes_state_to_active(
        self, authenticated_page: Page, base_url: str, api_url: str
    ) -> None:
        """거래 재개 버튼 클릭 시 시스템 상태가 정상 운용으로 전환된다."""
        _api_set_system_state(api_url, "halt", reason="테스트 준비")

        _goto_settings(authenticated_page, base_url)
        page = authenticated_page

        # 거래 재개 버튼 클릭
        page.get_by_role("button", name="거래 재개").click()
        page.wait_for_timeout(2000)

        # 정상 운용 메시지 확인
        expect(
            page.get_by_text("현재 모든 봇의 거래가 정상 운용 중입니다.", exact=False)
        ).to_be_visible(timeout=5000)
        # 비상 거래 정지 버튼이 다시 표시됨
        expect(page.get_by_role("button", name="비상 거래 정지")).to_be_visible()

    def test_resume_api_cross_validation(
        self,
        authenticated_page: Page,
        base_url: str,
        api_url: str,
    ) -> None:
        """재개 후 API 조회 시 trading_status가 ACTIVE임을 확인한다."""
        # 독립적으로 ACTIVE 상태를 보장한다.
        _api_set_system_state(api_url, "activate")

        status = _api_get_system_status(api_url)
        assert status["trading_status"] == "ACTIVE", (
            f"API 반환 상태가 ACTIVE가 아님: {status['trading_status']}"
        )


# ── 알림 토글 ─────────────────────────────────────────


class TestNotificationToggle:
    """표시 및 알림 섹션 토글 변경 플로우."""

    def test_fill_alert_toggle_is_visible(
        self, authenticated_page: Page, base_url: str
    ) -> None:
        """'체결 알림' 토글이 표시된다."""
        _goto_settings(authenticated_page, base_url)
        page = authenticated_page

        expect(page.get_by_text("체결 알림", exact=False).first).to_be_visible()

    def test_daily_report_toggle_is_visible(
        self, authenticated_page: Page, base_url: str
    ) -> None:
        """'일일 리포트' 토글이 표시된다."""
        _goto_settings(authenticated_page, base_url)
        page = authenticated_page

        expect(page.get_by_text("일일 리포트", exact=False).first).to_be_visible()

    def test_daily_report_toggle_changes_state(
        self, authenticated_page: Page, base_url: str, api_url: str
    ) -> None:
        """'일일 리포트' 토글 클릭 시 notification.daily_report 값이 변경된다."""
        _goto_settings(authenticated_page, base_url)
        page = authenticated_page

        # 토글 전 API 값 확인 (seed: false)
        configs_before = _api_get_config(api_url)
        cfg_before = _find_config(configs_before, "notification.daily_report")
        assert cfg_before is not None, "notification.daily_report 설정이 없음"
        value_before = cfg_before["value"]

        # '일일 리포트' 텍스트가 포함된 행을 찾아 토글 버튼 클릭
        toggle_btn = _find_toggle_button(page, "일일 리포트")
        toggle_btn.scroll_into_view_if_needed()
        page.wait_for_timeout(300)
        toggle_btn.click()
        page.wait_for_timeout(2000)

        # 토글 후 API 교차 검증
        configs_after = _api_get_config(api_url)
        cfg_after = _find_config(configs_after, "notification.daily_report")
        assert cfg_after is not None, "notification.daily_report 설정이 없음"
        value_after = cfg_after["value"]

        assert str(value_before) != str(value_after), (
            f"토글 후 값이 변경되지 않음: before={value_before}, after={value_after}"
        )

    def test_fill_alert_toggle_changes_state(
        self, authenticated_page: Page, base_url: str, api_url: str
    ) -> None:
        """'체결 알림' 토글 클릭 시 notification.fill_alert 값이 변경된다."""
        _goto_settings(authenticated_page, base_url)
        page = authenticated_page

        # 토글 전 API 값 확인 (seed: true)
        configs_before = _api_get_config(api_url)
        cfg_before = _find_config(configs_before, "notification.fill_alert")
        assert cfg_before is not None, "notification.fill_alert 설정이 없음"
        value_before = cfg_before["value"]

        # '체결 알림' 텍스트가 포함된 행을 찾아 토글 버튼 클릭
        toggle_btn = _find_toggle_button(page, "체결 알림")
        toggle_btn.scroll_into_view_if_needed()
        page.wait_for_timeout(300)
        toggle_btn.click()
        page.wait_for_timeout(2000)

        # 토글 후 API 교차 검증
        configs_after = _api_get_config(api_url)
        cfg_after = _find_config(configs_after, "notification.fill_alert")
        assert cfg_after is not None, "notification.fill_alert 설정이 없음"
        value_after = cfg_after["value"]

        assert str(value_before) != str(value_after), (
            f"토글 후 값이 변경되지 않음: before={value_before}, after={value_after}"
        )
