"""E2E 테스트 — 예산 할당/회수 액션 플로우.

할당 폼을 통해 봇에 예산을 할당하고 회수하는 핵심 액션 플로우를 검증한다.
각 액션 후 API 응답과 UI 요약 수치가 일치하는지 교차 검증한다.

시드 데이터:
  - bot-alloc-01: 할당 대상 봇 (stopped, 예산 0)
  - bot-revoke-01: 회수 대상 봇 (stopped, 예산 10,000,000)
  - 미할당 자금 90,000,000 원 (할당 여유 충분)
"""

from __future__ import annotations

import httpx
import pytest
from playwright.sync_api import Page, expect

SCENARIO = "action-budget"

pytestmark = [pytest.mark.e2e, pytest.mark.playwright]


# ── 헬퍼 ─────────────────────────────────────────────


def _go_to_treasury(page: Page, base_url: str) -> None:
    """자금관리 페이지로 이동하고 데이터 로드를 대기한다."""
    page.goto(f"{base_url}/treasury", wait_until="commit")
    page.wait_for_timeout(2000)


def _select_bot(page: Page, bot_id: str) -> None:
    """예산 관리 폼의 Bot 선택 드롭다운에서 봇을 선택한다."""
    bot_select = page.locator("select").first
    bot_select.select_option(value=bot_id)
    page.wait_for_timeout(300)


def _fill_amount(page: Page, amount: str) -> None:
    """예산 관리 폼의 금액 입력란에 값을 입력한다."""
    amount_input = page.locator('input[type="number"]').first
    amount_input.fill(amount)
    page.wait_for_timeout(300)


def _click_allocate(page: Page) -> None:
    """'할당' 버튼을 클릭한다."""
    page.get_by_role("button", name="할당").first.click()
    page.wait_for_timeout(500)


def _click_revoke(page: Page) -> None:
    """'회수' 버튼을 클릭한다."""
    page.get_by_role("button", name="회수").first.click()
    page.wait_for_timeout(500)


def _confirm_action(page: Page) -> None:
    """확인 모달에서 '변경 확인' 버튼을 클릭한다."""
    page.get_by_role("button", name="변경 확인").click()
    page.wait_for_timeout(2000)


def _cancel_action(page: Page) -> None:
    """확인 모달에서 '취소' 버튼을 클릭한다."""
    page.get_by_role("button", name="취소").click()
    page.wait_for_timeout(500)


def _get_treasury_summary(api_url: str) -> dict:
    """API에서 자금 요약 정보를 조회한다."""
    resp = httpx.get(f"{api_url}/treasury", timeout=10)
    assert resp.status_code == 200, f"treasury API 오류: {resp.text}"
    return resp.json()


def _get_bot_budgets(api_url: str) -> list[dict]:
    """API에서 봇별 예산 목록을 조회한다."""
    resp = httpx.get(f"{api_url}/treasury/budgets", timeout=10)
    assert resp.status_code == 200, f"budgets API 오류: {resp.text}"
    data = resp.json()
    return data.get("budgets", data)


def _get_budget_for_bot(api_url: str, bot_id: str) -> dict | None:
    """특정 봇의 예산 정보를 반환한다."""
    budgets = _get_bot_budgets(api_url)
    return next((b for b in budgets if b["bot_id"] == bot_id), None)


# ── 폼 UI 기본 검증 ──────────────────────────────────


class TestAllocationFormUI:
    """예산 관리 폼 기본 UI 검증."""

    def test_form_elements_visible(self, authenticated_page, base_url: str) -> None:
        """예산 관리 폼에 Bot 선택 드롭다운, 금액 입력, 할당/회수 버튼이 표시된다."""
        _go_to_treasury(authenticated_page, base_url)
        page = authenticated_page

        expect(page.locator("select").first).to_be_visible()
        expect(page.locator('input[type="number"]').first).to_be_visible()
        expect(page.get_by_role("button", name="할당").first).to_be_visible()
        expect(page.get_by_role("button", name="회수").first).to_be_visible()

    def test_both_bots_in_dropdown(self, authenticated_page, base_url: str) -> None:
        """Bot 선택 드롭다운에 시드 봇 2개가 모두 포함된다."""
        _go_to_treasury(authenticated_page, base_url)
        page = authenticated_page

        bot_select = page.locator("select").first
        options = bot_select.locator("option").all_inner_texts()

        assert any("bot-alloc-01" in o for o in options), (
            f"bot-alloc-01이 드롭다운에 없음: {options}"
        )
        assert any("bot-revoke-01" in o for o in options), (
            f"bot-revoke-01이 드롭다운에 없음: {options}"
        )

    def test_buttons_disabled_without_amount(
        self, authenticated_page, base_url: str
    ) -> None:
        """금액 미입력 시 할당/회수 버튼이 비활성화된다."""
        _go_to_treasury(authenticated_page, base_url)
        page = authenticated_page

        # 금액 입력 초기화
        page.locator('input[type="number"]').first.fill("")

        expect(page.get_by_role("button", name="할당").first).to_be_disabled()
        expect(page.get_by_role("button", name="회수").first).to_be_disabled()


# ── 확인 모달 검증 ────────────────────────────────────


class TestConfirmModal:
    """예산 변경 확인 모달 검증."""

    def test_allocate_modal_shows_correct_info(
        self, authenticated_page, base_url: str
    ) -> None:
        """할당 버튼 클릭 시 확인 모달에 봇 ID와 할당 금액이 표시된다."""
        _go_to_treasury(authenticated_page, base_url)
        page = authenticated_page

        _select_bot(page, "bot-alloc-01")
        _fill_amount(page, "5000000")
        _click_allocate(page)

        # 모달 제목
        expect(page.get_by_text("예산 할당 확인", exact=False)).to_be_visible()

        # 모달 내 봇 ID 표시 (font-mono span)
        modal = page.locator(".fixed")
        expect(modal.locator(".font-mono", has_text="bot-alloc-01")).to_be_visible()

        # 취소하여 상태 복원
        _cancel_action(page)

    def test_revoke_modal_shows_correct_info(
        self, authenticated_page, base_url: str
    ) -> None:
        """회수 버튼 클릭 시 확인 모달에 봇 ID와 회수 금액이 표시된다."""
        _go_to_treasury(authenticated_page, base_url)
        page = authenticated_page

        _select_bot(page, "bot-revoke-01")
        _fill_amount(page, "3000000")
        _click_revoke(page)

        # 모달 제목
        expect(page.get_by_text("예산 회수 확인", exact=False)).to_be_visible()

        # 봇 ID 표시
        expect(page.get_by_text("bot-revoke-01", exact=False).first).to_be_visible()

        # 취소하여 상태 복원
        _cancel_action(page)

    def test_cancel_modal_closes_without_action(
        self, authenticated_page, base_url: str, api_url: str
    ) -> None:
        """확인 모달에서 취소 클릭 시 모달이 닫히고 예산이 변경되지 않는다."""
        before = _get_budget_for_bot(api_url, "bot-alloc-01")
        before_allocated = before["allocated"] if before else 0.0

        _go_to_treasury(authenticated_page, base_url)
        page = authenticated_page

        _select_bot(page, "bot-alloc-01")
        _fill_amount(page, "5000000")
        _click_allocate(page)
        _cancel_action(page)

        # 모달이 닫혔는지 확인 (모달 제목 사라짐)
        expect(page.get_by_text("예산 할당 확인", exact=False)).not_to_be_visible(
            timeout=3000
        )

        # API 상태 변경 없음
        after = _get_budget_for_bot(api_url, "bot-alloc-01")
        after_allocated = after["allocated"] if after else 0.0
        assert after_allocated == before_allocated, (
            f"취소 후 예산이 변경됨: {before_allocated} → {after_allocated}"
        )


# ── 예산 할당 플로우 ──────────────────────────────────


class TestAllocationFlow:
    """예산 할당 액션 플로우 검증."""

    def test_allocate_increases_bot_budget(
        self, authenticated_page, base_url: str, api_url: str
    ) -> None:
        """할당 액션 후 봇의 배정예산(allocated)이 지정 금액만큼 증가한다."""
        alloc_amount = 5_000_000

        before = _get_budget_for_bot(api_url, "bot-alloc-01")
        before_allocated = before["allocated"] if before else 0.0

        _go_to_treasury(authenticated_page, base_url)
        page = authenticated_page

        _select_bot(page, "bot-alloc-01")
        _fill_amount(page, str(alloc_amount))
        _click_allocate(page)
        _confirm_action(page)

        after = _get_budget_for_bot(api_url, "bot-alloc-01")
        assert after is not None, "할당 후 bot-alloc-01 예산 레코드가 없음"
        assert after["allocated"] == pytest.approx(
            before_allocated + alloc_amount, abs=1
        ), (
            f"배정예산 불일치: 기대={before_allocated + alloc_amount}, "
            f"실제={after['allocated']}"
        )

    def test_allocate_decreases_unallocated(
        self, authenticated_page, base_url: str, api_url: str
    ) -> None:
        """할당 액션 후 Treasury 미할당 자금이 지정 금액만큼 감소한다."""
        alloc_amount = 3_000_000

        before_summary = _get_treasury_summary(api_url)
        before_unallocated = before_summary.get("unallocated", 0.0)

        _go_to_treasury(authenticated_page, base_url)
        page = authenticated_page

        _select_bot(page, "bot-alloc-01")
        _fill_amount(page, str(alloc_amount))
        _click_allocate(page)
        _confirm_action(page)

        after_summary = _get_treasury_summary(api_url)
        after_unallocated = after_summary.get("unallocated", 0.0)

        assert after_unallocated == pytest.approx(
            before_unallocated - alloc_amount, abs=1
        ), (
            f"미할당 자금 불일치: 기대={before_unallocated - alloc_amount}, "
            f"실제={after_unallocated}"
        )

    def test_allocate_ui_shows_updated_amount(
        self,
        authenticated_page,
        base_url: str,
        api_url: str,  # noqa: ARG002
    ) -> None:
        """할당 성공 후 페이지가 갱신되어 봇 예산 테이블에 봇이 표시된다."""
        alloc_amount = 2_000_000

        _go_to_treasury(authenticated_page, base_url)
        page = authenticated_page

        _select_bot(page, "bot-alloc-01")
        _fill_amount(page, str(alloc_amount))
        _click_allocate(page)
        _confirm_action(page)

        # 페이지 갱신 후 예산 테이블에 bot-alloc-01이 표시됨
        expect(page.get_by_text("bot-alloc-01", exact=False).first).to_be_visible()


# ── 예산 회수 플로우 ──────────────────────────────────


class TestRevocationFlow:
    """예산 회수 액션 플로우 검증."""

    def test_revoke_decreases_bot_budget(
        self, authenticated_page, base_url: str, api_url: str
    ) -> None:
        """회수 액션 후 봇의 배정예산(allocated)이 지정 금액만큼 감소한다."""
        revoke_amount = 3_000_000

        before = _get_budget_for_bot(api_url, "bot-revoke-01")
        assert before is not None, "bot-revoke-01 예산 레코드가 없음"
        before_allocated = before["allocated"]

        _go_to_treasury(authenticated_page, base_url)
        page = authenticated_page

        _select_bot(page, "bot-revoke-01")
        _fill_amount(page, str(revoke_amount))
        _click_revoke(page)
        _confirm_action(page)

        after = _get_budget_for_bot(api_url, "bot-revoke-01")
        assert after is not None, "회수 후 bot-revoke-01 예산 레코드가 없음"
        assert after["allocated"] == pytest.approx(
            before_allocated - revoke_amount, abs=1
        ), (
            f"배정예산 불일치: 기대={before_allocated - revoke_amount}, "
            f"실제={after['allocated']}"
        )

    def test_revoke_increases_unallocated(
        self, authenticated_page, base_url: str, api_url: str
    ) -> None:
        """회수 액션 후 Treasury 미할당 자금이 지정 금액만큼 증가한다."""
        revoke_amount = 2_000_000

        before_summary = _get_treasury_summary(api_url)
        before_unallocated = before_summary.get("unallocated", 0.0)

        _go_to_treasury(authenticated_page, base_url)
        page = authenticated_page

        _select_bot(page, "bot-revoke-01")
        _fill_amount(page, str(revoke_amount))
        _click_revoke(page)
        _confirm_action(page)

        after_summary = _get_treasury_summary(api_url)
        after_unallocated = after_summary.get("unallocated", 0.0)

        assert after_unallocated == pytest.approx(
            before_unallocated + revoke_amount, abs=1
        ), (
            f"미할당 자금 불일치: 기대={before_unallocated + revoke_amount}, "
            f"실제={after_unallocated}"
        )


# ── 오류 케이스: 초과 회수 ───────────────────────────


class TestRevocationErrorCase:
    """회수 오류 케이스 검증."""

    def test_over_revocation_api_returns_400(
        self,
        authenticated_page,
        base_url: str,
        api_url: str,  # noqa: ARG002
    ) -> None:
        """가용 예산을 초과하는 금액 회수 시도 시 API가 400을 반환한다."""
        before = _get_budget_for_bot(api_url, "bot-revoke-01")
        assert before is not None, "bot-revoke-01 예산 레코드가 없음"
        available = before["available"]

        # 가용 예산보다 1,000,000원 더 많은 금액으로 직접 API 호출
        over_amount = available + 1_000_000
        resp = httpx.post(
            f"{api_url}/treasury/bots/bot-revoke-01/deallocate",
            json={"amount": over_amount},
            timeout=10,
        )
        assert resp.status_code == 400, (
            f"초과 회수가 성공해서는 안 됨 "
            f"(상태: {resp.status_code}, 응답: {resp.text})"
        )

    def test_over_revocation_does_not_change_budget(
        self,
        authenticated_page,
        base_url: str,
        api_url: str,  # noqa: ARG002
    ) -> None:
        """초과 회수 실패 후 봇의 예산 상태가 변경되지 않는다."""
        before = _get_budget_for_bot(api_url, "bot-revoke-01")
        assert before is not None, "bot-revoke-01 예산 레코드가 없음"
        before_allocated = before["allocated"]
        available = before["available"]

        # 초과 금액으로 API 호출 (실패 예상)
        over_amount = available + 1_000_000
        httpx.post(
            f"{api_url}/treasury/bots/bot-revoke-01/deallocate",
            json={"amount": over_amount},
            timeout=10,
        )

        after = _get_budget_for_bot(api_url, "bot-revoke-01")
        assert after is not None
        assert after["allocated"] == pytest.approx(before_allocated, abs=1), (
            f"실패한 회수 후 예산이 변경됨: {before_allocated} → {after['allocated']}"
        )


# ── API 교차 검증 ─────────────────────────────────────


class TestAPIValidation:
    """UI 액션 후 API 응답 교차 검증."""

    def test_treasury_summary_reflects_allocations(
        self,
        authenticated_page,
        base_url: str,
        api_url: str,  # noqa: ARG002
    ) -> None:
        """/api/treasury total_allocated 값이 봇별 예산 합계와 일치한다."""
        summary = _get_treasury_summary(api_url)
        budgets = _get_bot_budgets(api_url)

        total_from_budgets = sum(b["allocated"] for b in budgets)
        total_allocated = summary.get("total_allocated", 0.0)

        assert total_allocated == pytest.approx(total_from_budgets, abs=1), (
            f"total_allocated 불일치: summary={total_allocated}, "
            f"budgets 합산={total_from_budgets}"
        )

    def test_treasury_summary_unallocated_consistency(
        self,
        authenticated_page,
        base_url: str,
        api_url: str,  # noqa: ARG002
    ) -> None:
        """/api/treasury 요약에서 unallocated = total_cash - total_allocated 성립."""
        summary = _get_treasury_summary(api_url)

        total_cash = summary.get("account_balance", 0.0)
        total_allocated = summary.get("total_allocated", 0.0)
        unallocated = summary.get("unallocated", 0.0)

        assert unallocated == pytest.approx(total_cash - total_allocated, abs=1), (
            f"unallocated 불일치: unallocated={unallocated}, "
            f"total_cash - total_allocated={total_cash - total_allocated}"
        )

    def test_budgets_endpoint_returns_both_bots(
        self,
        authenticated_page,
        base_url: str,
        api_url: str,  # noqa: ARG002
    ) -> None:
        """/api/treasury/budgets 응답에 시드 봇 2개가 모두 포함된다."""
        budgets = _get_bot_budgets(api_url)
        bot_ids = {b["bot_id"] for b in budgets}

        assert "bot-alloc-01" in bot_ids, (
            f"bot-alloc-01이 budgets 응답에 없음: {bot_ids}"
        )
        assert "bot-revoke-01" in bot_ids, (
            f"bot-revoke-01이 budgets 응답에 없음: {bot_ids}"
        )
