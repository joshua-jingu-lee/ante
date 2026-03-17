"""E2E 테스트 — 에이전트 라이프사이클 액션 플로우.

에이전트 등록(register) → 정지(suspend) → 폐기(decommission) 흐름을 검증한다.
각 단계마다 API 교차 검증으로 DB 상태를 확인한다.
"""

from __future__ import annotations

import re

import httpx
import pytest
from playwright.sync_api import Page, expect

SCENARIO = "action-agent-lifecycle"

pytestmark = [pytest.mark.e2e, pytest.mark.playwright]

# 등록 테스트에서 사용하는 에이전트 고정값
NEW_AGENT_ID = "e2e-lifecycle-new-01"
NEW_AGENT_NAME = "라이프사이클 신규 에이전트"
NEW_AGENT_ORG = "e2e-lab"

# 정지/폐기 테스트 대상 (시드 데이터)
SEED_AGENT_ID = "lifecycle-agent-01"
SEED_AGENT_NAME = "라이프사이클 테스트 에이전트"


# ── 헬퍼 ─────────────────────────────────────────────


def _go_to_members(page: Page, base_url: str) -> None:
    """멤버 관리 페이지로 이동 후 렌더링 안정화 대기."""
    page.goto(f"{base_url}/members", wait_until="commit")
    page.wait_for_timeout(2000)


def _member_card(page: Page, name: str):  # noqa: ANN202
    """멤버 이름으로 카드 영역(border rounded-lg)을 찾는다."""
    xpath = (
        "xpath=ancestor::div["
        "contains(@class,'rounded-lg') and contains(@class,'border')]"
    )
    return page.get_by_text(name, exact=True).locator(xpath).first


def _api_get_member(api_url: str, member_id: str) -> dict:
    """API로 멤버 상세 정보를 조회한다."""
    resp = httpx.get(f"{api_url}/members/{member_id}", timeout=10)
    assert resp.status_code == 200, f"멤버 조회 실패: {resp.text}"
    return resp.json()["member"]


# ── 에이전트 등록 ─────────────────────────────────────


class TestAgentRegister:
    """에이전트 등록 플로우 검증."""

    def test_register_modal_opens(
        self,
        authenticated_page,  # noqa: ANN001
        base_url: str,
    ) -> None:
        """'+ 에이전트 등록' 버튼 클릭 시 등록 모달이 열린다."""
        _go_to_members(authenticated_page, base_url)
        page = authenticated_page

        btn = page.get_by_role("button", name=re.compile("에이전트 등록"))
        expect(btn).to_be_visible()
        btn.click()
        page.wait_for_timeout(500)

        # 모달 타이틀 확인
        expect(page.get_by_text("에이전트 등록", exact=True).last).to_be_visible()

    def test_register_modal_has_fields(
        self,
        authenticated_page,  # noqa: ANN001
        base_url: str,
    ) -> None:
        """등록 모달에 Agent ID, 이름, 소속, 권한 범위 필드가 표시된다."""
        _go_to_members(authenticated_page, base_url)
        page = authenticated_page

        page.get_by_role("button", name=re.compile("에이전트 등록")).click()
        page.wait_for_timeout(500)

        expect(page.get_by_text("Agent ID", exact=True)).to_be_visible()
        expect(page.get_by_text("이름", exact=True)).to_be_visible()
        expect(page.get_by_text("소속 (org)", exact=True)).to_be_visible()
        expect(page.get_by_text("권한 범위", exact=True)).to_be_visible()

    def test_register_modal_cancel(
        self,
        authenticated_page,  # noqa: ANN001
        base_url: str,
    ) -> None:
        """취소 버튼 클릭 시 모달이 닫힌다."""
        _go_to_members(authenticated_page, base_url)
        page = authenticated_page

        page.get_by_role("button", name=re.compile("에이전트 등록")).click()
        page.wait_for_timeout(500)

        page.get_by_role("button", name="취소").click()
        page.wait_for_timeout(500)

        # 모달이 사라졌는지 확인
        expect(page.locator("h2", has_text="에이전트 등록")).not_to_be_visible()

    def test_register_new_agent_shows_token(
        self,
        authenticated_page,  # noqa: ANN001
        base_url: str,
        api_url: str,
    ) -> None:
        """신규 에이전트를 등록하면 토큰 발급 완료 모달이 표시되고
        API에서 활성 상태로 확인된다."""
        _go_to_members(authenticated_page, base_url)
        page = authenticated_page

        # 등록 모달 열기
        page.get_by_role("button", name=re.compile("에이전트 등록")).click()
        page.wait_for_timeout(500)

        # 필드 입력
        page.get_by_placeholder("agent-research-01").fill(NEW_AGENT_ID)
        page.get_by_placeholder("리서치 에이전트").fill(NEW_AGENT_NAME)
        page.get_by_placeholder("research").fill(NEW_AGENT_ORG)

        # 권한 체크박스 선택 (data:read)
        page.locator("label", has_text="data:read").locator(
            "input[type='checkbox']"
        ).check()

        # 등록 버튼 클릭
        page.get_by_role("button", name="등록").click()
        page.wait_for_timeout(2000)

        # 토큰 발급 완료 모달 확인
        expect(page.get_by_text("에이전트 토큰 발급 완료")).to_be_visible()
        expect(page.get_by_text("이 토큰은 다시 확인할 수 없습니다")).to_be_visible()

        # API 교차 검증: 등록된 에이전트 상태 확인
        member = _api_get_member(api_url, NEW_AGENT_ID)
        assert member["member_id"] == NEW_AGENT_ID
        assert member["name"] == NEW_AGENT_NAME
        assert member["org"] == NEW_AGENT_ORG
        assert member["status"] == "active"
        assert member["type"] == "agent"
        assert "data:read" in member["scopes"]

        # 토큰 모달 닫기
        page.get_by_role("button", name="닫기").click()
        page.wait_for_timeout(500)

    def test_registered_agent_appears_in_list(
        self,
        authenticated_page,  # noqa: ANN001
        base_url: str,
    ) -> None:
        """등록된 에이전트가 Agent 멤버 목록에 표시된다."""
        _go_to_members(authenticated_page, base_url)
        page = authenticated_page

        card = _member_card(page, NEW_AGENT_NAME)
        expect(card).to_be_visible()
        expect(card.get_by_text(NEW_AGENT_ID)).to_be_visible()
        expect(card.get_by_text(NEW_AGENT_ORG)).to_be_visible()
        expect(card.get_by_text("활성")).to_be_visible()


# ── 에이전트 정지 ─────────────────────────────────────


class TestAgentSuspend:
    """에이전트 정지(active → suspended) 플로우 검증."""

    def test_suspend_button_visible_on_active_agent(
        self,
        authenticated_page,  # noqa: ANN001
        base_url: str,
    ) -> None:
        """활성 에이전트 카드에 '정지' 버튼이 표시된다."""
        _go_to_members(authenticated_page, base_url)

        card = _member_card(authenticated_page, SEED_AGENT_NAME)
        expect(card).to_be_visible()
        expect(card.get_by_role("button", name="정지")).to_be_visible()

    def test_suspend_agent_changes_status(
        self,
        authenticated_page,  # noqa: ANN001
        base_url: str,
        api_url: str,
    ) -> None:
        """'정지' 버튼 클릭 후 에이전트 상태가 'suspended'로 변경되고
        카드에 '정지' 뱃지가 표시된다."""
        _go_to_members(authenticated_page, base_url)
        page = authenticated_page

        card = _member_card(page, SEED_AGENT_NAME)
        expect(card).to_be_visible()

        # 정지 버튼 클릭
        card.get_by_role("button", name="정지").click()
        page.wait_for_timeout(2000)

        # UI 상태 확인: '정지' 상태 뱃지
        card_after = _member_card(page, SEED_AGENT_NAME)
        expect(card_after.get_by_text("정지")).to_be_visible()

        # API 교차 검증
        member = _api_get_member(api_url, SEED_AGENT_ID)
        assert member["status"] == "suspended"

    def test_suspend_button_disappears_after_suspend(
        self,
        authenticated_page,  # noqa: ANN001
        base_url: str,
    ) -> None:
        """정지된 에이전트 카드에는 '정지' 버튼이 표시되지 않는다."""
        _go_to_members(authenticated_page, base_url)

        card = _member_card(authenticated_page, SEED_AGENT_NAME)
        expect(card).to_be_visible()
        expect(card.get_by_role("button", name="정지")).not_to_be_visible()

    def test_reactivate_button_visible_after_suspend(
        self,
        authenticated_page,  # noqa: ANN001
        base_url: str,
    ) -> None:
        """정지된 에이전트 카드에는 '재활성화' 버튼이 표시된다."""
        _go_to_members(authenticated_page, base_url)

        card = _member_card(authenticated_page, SEED_AGENT_NAME)
        expect(card).to_be_visible()
        expect(card.get_by_role("button", name="재활성화")).to_be_visible()


# ── 에이전트 폐기 ─────────────────────────────────────


class TestAgentDecommission:
    """에이전트 폐기(suspended → revoked) 플로우 검증."""

    def test_revoke_button_visible_on_suspended_agent(
        self,
        authenticated_page,  # noqa: ANN001
        base_url: str,
    ) -> None:
        """정지된 에이전트 카드에 '폐기' 버튼이 표시된다."""
        _go_to_members(authenticated_page, base_url)

        card = _member_card(authenticated_page, SEED_AGENT_NAME)
        expect(card).to_be_visible()
        expect(card.get_by_role("button", name="폐기")).to_be_visible()

    def test_revoke_agent_changes_status(
        self,
        authenticated_page,  # noqa: ANN001
        base_url: str,
        api_url: str,
    ) -> None:
        """폐기 확인 다이얼로그를 수락하면 에이전트 상태가 'revoked'로 변경된다."""
        _go_to_members(authenticated_page, base_url)
        page = authenticated_page

        card = _member_card(page, SEED_AGENT_NAME)
        expect(card).to_be_visible()

        # confirm 다이얼로그 자동 수락
        page.on("dialog", lambda dialog: dialog.accept())

        # 폐기 버튼 클릭
        card.get_by_role("button", name="폐기").click()
        page.wait_for_timeout(2000)

        # UI 상태 확인: '폐기' 상태 뱃지
        card_after = _member_card(page, SEED_AGENT_NAME)
        expect(card_after.get_by_text("폐기")).to_be_visible()

        # API 교차 검증
        member = _api_get_member(api_url, SEED_AGENT_ID)
        assert member["status"] == "revoked"

    def test_revoked_agent_card_opacity(
        self,
        authenticated_page,  # noqa: ANN001
        base_url: str,
    ) -> None:
        """폐기된 에이전트 카드는 반투명(opacity-50)으로 표시된다."""
        _go_to_members(authenticated_page, base_url)

        card = _member_card(authenticated_page, SEED_AGENT_NAME)
        expect(card).to_be_visible()
        # MemberCard에서 revoked 상태 시 opacity-50 클래스 적용
        expect(card).to_have_class(re.compile(r"opacity-50"))

    def test_revoked_agent_has_no_action_buttons(
        self,
        authenticated_page,  # noqa: ANN001
        base_url: str,
    ) -> None:
        """폐기된 에이전트 카드에는 정지/재활성화/폐기 버튼이 표시되지 않는다."""
        _go_to_members(authenticated_page, base_url)

        card = _member_card(authenticated_page, SEED_AGENT_NAME)
        expect(card).to_be_visible()
        expect(card.get_by_role("button", name="정지")).not_to_be_visible()
        expect(card.get_by_role("button", name="재활성화")).not_to_be_visible()
        expect(card.get_by_role("button", name="폐기")).not_to_be_visible()

    def test_revoked_agent_api_state(
        self,
        authenticated_page,  # noqa: ANN001
        base_url: str,
        api_url: str,
    ) -> None:
        """API에서 폐기된 에이전트의 상태를 최종 확인한다."""
        _go_to_members(authenticated_page, base_url)

        member = _api_get_member(api_url, SEED_AGENT_ID)
        assert member["status"] == "revoked"
        assert member["type"] == "agent"
        assert member["member_id"] == SEED_AGENT_ID
