"""E2E 테스트 — 봇 관리 플로우.

봇 목록 조회, 생성, 시작/중지, 삭제, 상세 페이지 등
봇 관리의 핵심 사용자 시나리오를 검증한다.
"""

from __future__ import annotations

import re

import pytest
from playwright.sync_api import expect

from tests.e2e.pages import expect_modal, expect_toast

SCENARIO = "bot-management"

pytestmark = [pytest.mark.e2e, pytest.mark.playwright]


# ── 헬퍼 ─────────────────────────────────────────────


def _go_to_bots(page, base_url: str) -> None:  # noqa: ANN001
    """봇 관리 페이지로 이동."""
    page.goto(f"{base_url}/bots")
    page.wait_for_load_state("networkidle")


def _section(page, title: str):  # noqa: ANN001, ANN202
    """섹션 제목으로 해당 섹션 영역을 찾는다."""
    return page.get_by_text(title, exact=False).locator("..")


def _bot_card(page, bot_name: str):  # noqa: ANN001, ANN202
    """봇 이름으로 카드 영역을 찾는다."""
    return (
        page.get_by_text(bot_name, exact=False)
        .locator(
            "xpath=ancestor::*["
            "contains(@class,'card') or contains(@class,'Card') "
            "or self::article or self::section or self::li]"
        )
        .first
    )


# ── 봇 목록 페이지 ───────────────────────────────────


class TestBotListPage:
    """봇 목록 페이지 검증."""

    def test_sections_displayed(
        self,
        authenticated_page,
        base_url: str,  # noqa: ANN001
    ) -> None:
        """'실행 중'과 '비활성' 섹션이 표시된다."""
        _go_to_bots(authenticated_page, base_url)

        expect(authenticated_page.get_by_text("실행 중")).to_be_visible()
        expect(authenticated_page.get_by_text("비활성")).to_be_visible()

    def test_running_section_has_bot_b(
        self,
        authenticated_page,
        base_url: str,  # noqa: ANN001
    ) -> None:
        """실행 중 섹션에 봇 B(모멘텀 추세 봇)가 표시된다."""
        _go_to_bots(authenticated_page, base_url)

        expect(authenticated_page.get_by_text("모멘텀 추세 봇")).to_be_visible()

    def test_bot_b_card_details(
        self,
        authenticated_page,
        base_url: str,  # noqa: ANN001
    ) -> None:
        """봇 B 카드에 이름, 상태, 전략, 모드가 표시된다."""
        _go_to_bots(authenticated_page, base_url)

        page = authenticated_page
        card = _bot_card(page, "모멘텀 추세 봇")

        expect(card.get_by_text("실행중")).to_be_visible()
        expect(card.get_by_text("momentum-v2")).to_be_visible()
        expect(card.get_by_text("실전")).to_be_visible()

    def test_inactive_section_bot_a(
        self,
        authenticated_page,
        base_url: str,  # noqa: ANN001
    ) -> None:
        """비활성 섹션에 봇 A(SMA 크로스 봇, 생성됨)가 표시된다."""
        _go_to_bots(authenticated_page, base_url)

        page = authenticated_page
        card = _bot_card(page, "SMA 크로스 봇")

        expect(card.get_by_text("생성됨")).to_be_visible()
        expect(card.get_by_text("모의")).to_be_visible()

    def test_inactive_section_bot_c(
        self,
        authenticated_page,
        base_url: str,  # noqa: ANN001
    ) -> None:
        """비활성 섹션에 봇 C(평균회귀 실전 봇, 중지됨)가 표시된다."""
        _go_to_bots(authenticated_page, base_url)

        page = authenticated_page
        card = _bot_card(page, "평균회귀 실전 봇")

        expect(card.get_by_text("중지됨")).to_be_visible()
        expect(card.get_by_text("실전")).to_be_visible()

    def test_inactive_section_bot_d(
        self,
        authenticated_page,
        base_url: str,  # noqa: ANN001
    ) -> None:
        """비활성 섹션에 봇 D(오류 테스트 봇, 오류)가 표시된다."""
        _go_to_bots(authenticated_page, base_url)

        page = authenticated_page
        card = _bot_card(page, "오류 테스트 봇")

        expect(card.get_by_text("오류")).to_be_visible()
        expect(card.get_by_text("모의")).to_be_visible()


# ── 봇 생성 ──────────────────────────────────────────


class TestBotCreate:
    """봇 생성 모달 검증."""

    def test_create_modal_open_close(
        self,
        authenticated_page,
        base_url: str,  # noqa: ANN001
    ) -> None:
        """봇 생성 모달을 열고 닫을 수 있다."""
        _go_to_bots(authenticated_page, base_url)
        page = authenticated_page

        # 모달 열기
        page.get_by_role("button", name="봇 생성").click()
        expect_modal(page, "봇 생성")

        # ESC로 모달 닫기
        page.keyboard.press("Escape")
        expect(
            page.get_by_text("봇 생성").locator(
                "xpath=ancestor::div[contains(@class,'fixed')]"
            )
        ).not_to_be_visible(timeout=3000)

    def test_create_bot_form_submit(
        self,
        authenticated_page,
        base_url: str,  # noqa: ANN001
    ) -> None:
        """봇 생성 폼을 작성하고 제출할 수 있다."""
        _go_to_bots(authenticated_page, base_url)
        page = authenticated_page

        # 모달 열기
        page.get_by_role("button", name="봇 생성").click()
        expect_modal(page, "봇 생성")

        # 폼 작성
        page.get_by_label("Bot ID").fill("bot-e2e-test-01")
        page.get_by_label("이름").fill("E2E 테스트 봇")

        # 전략 선택
        page.get_by_label("전략").select_option(index=1)

        # 봇 유형 선택 — 모의투자
        page.get_by_text("모의투자").click()

        # 실행 간격
        page.get_by_label("실행 간격").fill("60")

        # 배정예산
        page.get_by_label("배정예산").fill("1000000")

        # 제출
        page.get_by_role("button", name="생성").click()

        # 생성 성공 확인
        expect_toast(page, "생성")

        # 목록에 새 봇이 나타나는지 확인
        page.wait_for_load_state("networkidle")
        expect(page.get_by_text("E2E 테스트 봇")).to_be_visible(timeout=5000)


# ── 봇 시작/중지 ─────────────────────────────────────


class TestBotStartStop:
    """봇 시작/중지 검증."""

    def test_start_bot_a(
        self,
        authenticated_page,
        base_url: str,  # noqa: ANN001
    ) -> None:
        """봇 A를 시작하면 실행 중 섹션으로 이동한다."""
        _go_to_bots(authenticated_page, base_url)
        page = authenticated_page

        card = _bot_card(page, "SMA 크로스 봇")
        card.get_by_role("button", name="시작").click()

        # 시작 후 상태 변경 대기
        page.wait_for_load_state("networkidle")

        # 봇 A가 실행중 상태로 전환
        updated_card = _bot_card(page, "SMA 크로스 봇")
        expect(updated_card.get_by_text("실행중")).to_be_visible(timeout=5000)

    def test_stop_bot_b(
        self,
        authenticated_page,
        base_url: str,  # noqa: ANN001
    ) -> None:
        """봇 B를 중지하면 중지 모달이 표시되고, 확인 후 비활성 섹션으로 이동한다."""
        _go_to_bots(authenticated_page, base_url)
        page = authenticated_page

        card = _bot_card(page, "모멘텀 추세 봇")
        card.get_by_role("button", name="중지").click()

        # 중지 모달 표시 확인
        expect_modal(page, "봇 중지")

        # 확인 버튼 클릭
        page.get_by_role("button", name="중지").last.click()

        # 중지 후 상태 변경 대기
        page.wait_for_load_state("networkidle")

        # 봇 B가 중지됨 상태로 전환
        updated_card = _bot_card(page, "모멘텀 추세 봇")
        expect(updated_card.get_by_text("중지됨")).to_be_visible(timeout=5000)


# ── 봇 삭제 ──────────────────────────────────────────


class TestBotDelete:
    """봇 삭제 검증."""

    def test_delete_bot_d_no_positions(
        self,
        authenticated_page,
        base_url: str,  # noqa: ANN001
    ) -> None:
        """보유 종목 없는 봇 D를 삭제할 수 있다."""
        _go_to_bots(authenticated_page, base_url)
        page = authenticated_page

        card = _bot_card(page, "오류 테스트 봇")
        card.get_by_role("button", name="삭제").click()

        # 삭제 모달 표시 확인
        expect_modal(page, "봇 삭제")

        # 삭제 확인 버튼 클릭
        page.get_by_role("button", name="삭제").last.click()

        # 삭제 후 목록에서 사라지는지 확인
        page.wait_for_load_state("networkidle")
        expect(page.get_by_text("오류 테스트 봇")).not_to_be_visible(timeout=5000)

    def test_delete_bot_c_with_positions(
        self,
        authenticated_page,
        base_url: str,  # noqa: ANN001
    ) -> None:
        """보유 종목 있는 봇 C를 삭제할 때 포지션 처리 옵션을 선택한다."""
        _go_to_bots(authenticated_page, base_url)
        page = authenticated_page

        card = _bot_card(page, "평균회귀 실전 봇")
        card.get_by_role("button", name="삭제").click()

        # 삭제 모달 표시 확인
        expect_modal(page, "봇 삭제")

        # 포지션 정보가 표시되는지 확인
        modal = page.locator("div.fixed.inset-0.z-50")
        expect(modal.get_by_text("보유 종목")).to_be_visible()

        # 라디오 옵션 선택 (첫 번째 옵션)
        modal.get_by_role("radio").first.click()

        # 삭제 확인 버튼 클릭
        page.get_by_role("button", name="삭제").last.click()

        # 삭제 후 목록에서 사라지는지 확인
        page.wait_for_load_state("networkidle")
        expect(page.get_by_text("평균회귀 실전 봇")).not_to_be_visible(timeout=5000)


# ── 봇 상세 페이지 ───────────────────────────────────


class TestBotDetailPage:
    """봇 B 상세 페이지 검증."""

    def test_navigate_to_detail(
        self,
        authenticated_page,
        base_url: str,  # noqa: ANN001
    ) -> None:
        """봇 B의 ID 링크를 클릭하면 상세 페이지로 이동한다."""
        _go_to_bots(authenticated_page, base_url)
        page = authenticated_page

        # 봇 ID 링크 클릭
        page.get_by_text("bot-momentum-01").click()
        page.wait_for_load_state("networkidle")

        # URL 확인
        expect(page).to_have_url(re.compile(r"/bots/bot-momentum-01"))

        # 뒤로 가기 링크 확인
        expect(page.get_by_text("← 봇 관리")).to_be_visible()

    def test_detail_header(
        self,
        authenticated_page,
        base_url: str,  # noqa: ANN001
    ) -> None:
        """상세 페이지 헤더에 봇 이름과 상태가 표시된다."""
        page = authenticated_page
        page.goto(f"{base_url}/bots/bot-momentum-01")
        page.wait_for_load_state("networkidle")

        expect(page.get_by_text("모멘텀 추세 봇")).to_be_visible()
        expect(page.get_by_text("실행중")).to_be_visible()
        expect(page.get_by_text("실전")).to_be_visible()

    def test_detail_strategy_card(
        self,
        authenticated_page,
        base_url: str,  # noqa: ANN001
    ) -> None:
        """상세 페이지에 운용 전략 카드가 표시된다."""
        page = authenticated_page
        page.goto(f"{base_url}/bots/bot-momentum-01")
        page.wait_for_load_state("networkidle")

        expect(page.get_by_text("운용 전략")).to_be_visible()
        expect(page.get_by_text("momentum-v2")).to_be_visible()

    def test_detail_execution_settings_card(
        self,
        authenticated_page,
        base_url: str,  # noqa: ANN001
    ) -> None:
        """상세 페이지에 실행 설정 카드가 표시된다."""
        page = authenticated_page
        page.goto(f"{base_url}/bots/bot-momentum-01")
        page.wait_for_load_state("networkidle")

        expect(page.get_by_text("실행 설정")).to_be_visible()

    def test_detail_budget_card(
        self,
        authenticated_page,
        base_url: str,  # noqa: ANN001
    ) -> None:
        """상세 페이지에 예산 카드가 표시된다."""
        page = authenticated_page
        page.goto(f"{base_url}/bots/bot-momentum-01")
        page.wait_for_load_state("networkidle")

        expect(page.get_by_text("예산")).to_be_visible()

    def test_detail_positions_table(
        self,
        authenticated_page,
        base_url: str,  # noqa: ANN001
    ) -> None:
        """상세 페이지에 보유 종목 테이블이 표시된다."""
        page = authenticated_page
        page.goto(f"{base_url}/bots/bot-momentum-01")
        page.wait_for_load_state("networkidle")

        expect(page.get_by_text("보유 종목")).to_be_visible()

        # 테이블 컬럼 헤더
        expect(page.get_by_text("종목")).to_be_visible()
        expect(page.get_by_text("수량")).to_be_visible()
        expect(page.get_by_text("평균단가")).to_be_visible()
        expect(page.get_by_text("수익률")).to_be_visible()

        # 보유 종목 데이터
        expect(page.get_by_text("삼성전자")).to_be_visible()
        expect(page.get_by_text("NAVER")).to_be_visible()
        expect(page.get_by_text("카카오")).to_be_visible()

    def test_detail_execution_log(
        self,
        authenticated_page,
        base_url: str,  # noqa: ANN001
    ) -> None:
        """상세 페이지에 실행 로그 섹션이 표시된다."""
        page = authenticated_page
        page.goto(f"{base_url}/bots/bot-momentum-01")
        page.wait_for_load_state("networkidle")

        expect(page.get_by_text("실행 로그")).to_be_visible()

    def test_back_link_returns_to_list(
        self,
        authenticated_page,
        base_url: str,  # noqa: ANN001
    ) -> None:
        """뒤로 가기 링크를 클릭하면 봇 목록으로 돌아간다."""
        page = authenticated_page
        page.goto(f"{base_url}/bots/bot-momentum-01")
        page.wait_for_load_state("networkidle")

        page.get_by_text("← 봇 관리").click()
        page.wait_for_load_state("networkidle")

        expect(page).to_have_url(re.compile(r"/bots/?$"))
