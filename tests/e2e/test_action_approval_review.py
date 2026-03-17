"""E2E 테스트 — 결재 승인/거부 액션 플로우.

pending 상태의 결재를 승인 또는 거부하는 액션 흐름을 검증한다.
- 승인: 승인 버튼 클릭 → 확인 모달 → 승인 → 상태 변경 확인
- 거부: 거부 버튼 클릭 → 사유 입력 → 거부 → 상태 변경 및 거부 사유 확인
- API 교차 검증: 액션 후 API로 실제 상태 변경 확인
- 목록 카운트 검증: 승인/거부 후 대기 건수 감소 확인
"""

from __future__ import annotations

import httpx
import pytest
from playwright.sync_api import Page, expect

SCENARIO = "action-approval-review"

pytestmark = [pytest.mark.e2e, pytest.mark.playwright]


# ── 헬퍼 ─────────────────────────────────────────────


def _go_to_approval_detail(page: Page, base_url: str, approval_id: str) -> None:
    """결재 상세 페이지로 이동하고 데이터 로드를 대기한다."""
    page.goto(f"{base_url}/approvals/{approval_id}", wait_until="commit")
    page.wait_for_timeout(2000)


def _go_to_approvals(page: Page, base_url: str) -> None:
    """결재함 목록 페이지로 이동하고 데이터 로드를 대기한다."""
    page.goto(f"{base_url}/approvals", wait_until="commit")
    page.wait_for_timeout(2000)


def _api_get_approval(api_url: str, approval_id: str) -> dict:
    """API로 결재 상세를 조회하여 반환한다."""
    resp = httpx.get(f"{api_url}/approvals/{approval_id}", timeout=10)
    assert resp.status_code == 200, f"API 조회 실패: {resp.text}"
    return resp.json()["approval"]


# ── 승인 플로우 ──────────────────────────────────────


class TestApproveFlow:
    """결재 승인 액션 플로우."""

    def test_pending_detail_shows_approve_and_reject_buttons(
        self, authenticated_page: Page, base_url: str
    ) -> None:
        """pending 상태 상세 페이지에 승인/거부 버튼이 표시된다."""
        _go_to_approval_detail(authenticated_page, base_url, "appr-r01")
        page = authenticated_page

        approve_btn = page.get_by_role("button", name="승인")
        reject_btn = page.get_by_role("button", name="거부")

        expect(approve_btn).to_be_visible()
        expect(reject_btn).to_be_visible()

    def test_approve_opens_confirmation_modal(
        self, authenticated_page: Page, base_url: str
    ) -> None:
        """승인 버튼 클릭 시 '결재 승인' 확인 모달이 열린다."""
        _go_to_approval_detail(authenticated_page, base_url, "appr-r01")
        page = authenticated_page

        page.get_by_role("button", name="승인").click()
        page.wait_for_timeout(500)

        # 모달 내 '결재 승인' 제목 확인
        expect(page.get_by_text("결재 승인")).to_be_visible()
        # 모달 내 결재 제목 포함 확인
        expect(page.get_by_text("모멘텀 돌파 전략 v3 채택 요청")).to_be_visible()

    def test_approve_cancel_closes_modal(
        self, authenticated_page: Page, base_url: str
    ) -> None:
        """승인 확인 모달에서 취소 클릭 시 모달이 닫히고 버튼이 유지된다."""
        _go_to_approval_detail(authenticated_page, base_url, "appr-r01")
        page = authenticated_page

        page.get_by_role("button", name="승인").click()
        page.wait_for_timeout(500)

        # 모달 내 취소 버튼 클릭
        page.get_by_role("button", name="취소").click()
        page.wait_for_timeout(500)

        # 승인 버튼이 다시 표시됨 (상태 변경 없음)
        expect(page.get_by_role("button", name="승인")).to_be_visible()

    def test_approve_flow_changes_status_to_approved(
        self, authenticated_page: Page, base_url: str, api_url: str
    ) -> None:
        """승인 확인 후 페이지가 승인 상태로 변경되고, 승인/거부 버튼이 사라진다."""
        _go_to_approval_detail(authenticated_page, base_url, "appr-r01")
        page = authenticated_page

        # 승인 버튼 클릭
        page.get_by_role("button", name="승인").click()
        page.wait_for_timeout(500)

        # 모달 내 승인 버튼 클릭 (확인)
        # 모달 내 승인 버튼은 고유하게 찾기 위해 visible 우선
        modal_approve_btn = page.locator("button.bg-positive").last
        modal_approve_btn.click()
        page.wait_for_timeout(2000)

        # 승인 후 승인/거부 버튼이 사라진다 (pending 아님)
        expect(page.get_by_role("button", name="승인")).not_to_be_visible()
        expect(page.get_by_role("button", name="거부")).not_to_be_visible()

    def test_approve_api_cross_validation(
        self,
        authenticated_page: Page,
        base_url: str,
        api_url: str,  # noqa: ARG002
    ) -> None:
        """승인 완료 후 API로 조회해도 approved 상태임을 확인한다."""
        approval = _api_get_approval(api_url, "appr-r01")

        assert (
            approval["status"] == "approved"
        ), f"API 조회 결과 상태가 approved가 아님: {approval['status']}"
        assert approval["resolved_by"] is not None, "resolved_by가 없음"


# ── 거부 플로우 ──────────────────────────────────────


class TestRejectFlow:
    """결재 거부 액션 플로우."""

    def test_reject_opens_reason_modal(
        self, authenticated_page: Page, base_url: str
    ) -> None:
        """거부 버튼 클릭 시 거부 사유 입력 모달이 열린다."""
        _go_to_approval_detail(authenticated_page, base_url, "appr-r02")
        page = authenticated_page

        page.get_by_role("button", name="거부").click()
        page.wait_for_timeout(500)

        # 모달 내 '결재 거부' 제목 확인
        expect(page.get_by_text("결재 거부")).to_be_visible()
        # 거부 사유 입력 필드 확인
        expect(page.get_by_label("거부 사유")).to_be_visible()

    def test_reject_button_disabled_without_reason(
        self, authenticated_page: Page, base_url: str
    ) -> None:
        """거부 사유를 입력하지 않으면 거부 버튼이 비활성화된다."""
        _go_to_approval_detail(authenticated_page, base_url, "appr-r02")
        page = authenticated_page

        page.get_by_role("button", name="거부").first.click()
        page.wait_for_timeout(500)

        # 모달 내 거부 확인 버튼이 disabled 상태
        modal_reject_btn = page.locator("button.bg-negative")
        expect(modal_reject_btn).to_be_disabled()

    def test_reject_cancel_closes_modal(
        self, authenticated_page: Page, base_url: str
    ) -> None:
        """거부 모달에서 취소 클릭 시 모달이 닫히고 버튼이 유지된다."""
        _go_to_approval_detail(authenticated_page, base_url, "appr-r02")
        page = authenticated_page

        page.get_by_role("button", name="거부").click()
        page.wait_for_timeout(500)

        page.get_by_role("button", name="취소").click()
        page.wait_for_timeout(500)

        # 거부 버튼이 다시 표시됨 (상태 변경 없음)
        expect(page.get_by_role("button", name="거부")).to_be_visible()

    def test_reject_flow_with_reason_changes_status(
        self, authenticated_page: Page, base_url: str, api_url: str
    ) -> None:
        """거부 사유 입력 후 거부 확인 시 상태가 rejected로 변경된다."""
        _go_to_approval_detail(authenticated_page, base_url, "appr-r02")
        page = authenticated_page

        # 거부 버튼 클릭
        page.get_by_role("button", name="거부").click()
        page.wait_for_timeout(500)

        # 거부 사유 입력
        reason_input = page.get_by_placeholder("예: 변동성 구간 추가 검증 필요")
        expect(reason_input).to_be_visible()
        reason_input.fill("변동성 구간 추가 백테스트 필요")
        page.wait_for_timeout(300)

        # 모달 내 거부 확인 버튼 클릭
        page.locator("button.bg-negative").click()
        page.wait_for_timeout(2000)

        # 거부 후 승인/거부 버튼이 사라진다 (pending 아님)
        expect(page.get_by_role("button", name="승인")).not_to_be_visible()
        expect(page.get_by_role("button", name="거부")).not_to_be_visible()

    def test_rejected_detail_shows_reject_reason_banner(
        self, authenticated_page: Page, base_url: str
    ) -> None:
        """거부 완료 후 상세 페이지에 거부 사유 배너가 표시된다."""
        _go_to_approval_detail(authenticated_page, base_url, "appr-r02")
        page = authenticated_page

        expect(page.get_by_text("거부 사유")).to_be_visible()
        expect(page.get_by_text("변동성 구간 추가 백테스트 필요")).to_be_visible()

    def test_reject_api_cross_validation(
        self,
        authenticated_page: Page,
        base_url: str,
        api_url: str,  # noqa: ARG002
    ) -> None:
        """거부 완료 후 API로 조회해도 rejected 상태이고 reject_reason이 있음을 확인한다."""  # noqa: E501
        approval = _api_get_approval(api_url, "appr-r02")

        assert (
            approval["status"] == "rejected"
        ), f"API 조회 결과 상태가 rejected가 아님: {approval['status']}"
        assert (
            approval["reject_reason"] == "변동성 구간 추가 백테스트 필요"
        ), f"거부 사유 불일치: {approval['reject_reason']}"


# ── 목록 카운트 검증 ──────────────────────────────────


class TestApprovalListCountAfterActions:
    """승인/거부 액션 후 목록 건수 검증.

    시나리오 시드에 pending 2건이 있으며, 승인/거부 테스트 클래스가 먼저 실행된 후
    이 클래스가 실행된다고 가정한다.
    두 건 모두 처리된 상태에서 대기 탭이 0건임을 확인한다.
    """

    def test_pending_tab_shows_zero_after_both_actions(
        self, authenticated_page: Page, base_url: str
    ) -> None:
        """승인/거부 액션 후 목록의 '대기' 탭에 결재 건수가 0건이 된다."""
        _go_to_approvals(authenticated_page, base_url)
        page = authenticated_page

        page.get_by_role("button", name="대기").first.click()
        page.wait_for_timeout(1500)

        rows = page.locator("table tbody tr")
        count = rows.count()
        assert count == 0, f"대기 탭에 처리된 건이 남아 있음: {count}건"

    def test_total_count_shows_two_rows(
        self, authenticated_page: Page, base_url: str
    ) -> None:
        """전체 탭에는 처리된 2건이 모두 표시된다."""
        _go_to_approvals(authenticated_page, base_url)
        page = authenticated_page

        rows = page.locator("table tbody tr")
        expect(rows).to_have_count(2)
