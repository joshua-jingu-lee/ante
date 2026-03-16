"""E2E 테스트 — 대시보드 시각 검증 (스크린샷 + 분석).

각 페이지의 스크린샷을 촬영하고, 레이아웃 깨짐/빈 영역/에러 텍스트를 자동 감지한다.
검증 결과는 리포트로 출력되고, 스크린샷은 tests/e2e/screenshots/에 저장된다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = [pytest.mark.e2e, pytest.mark.playwright]

SCREENSHOT_DIR = Path(__file__).parent / "screenshots"

# 검증 대상 페이지 목록
PAGES = [
    ("dashboard", "/"),
    ("login", "/login"),
    ("bots", "/bots"),
    ("strategies", "/strategies"),
    ("treasury", "/treasury"),
    ("settings", "/settings"),
    ("agents", "/agents"),
    ("approvals", "/approvals"),
]


class TestVisualVerification:
    """대시보드 시각 검증 테스트."""

    @pytest.mark.parametrize("page_name,path", PAGES)
    def test_page_visual_check(
        self,
        page,  # noqa: ANN001
        base_url: str,
        page_name: str,
        path: str,
    ) -> None:
        """페이지 스크린샷 촬영 + 시각 검증."""
        from tests.e2e.visual_checker import capture_and_verify

        page.goto(f"{base_url}{path}")
        page.wait_for_load_state("networkidle")

        # async → sync 변환 (Playwright sync API에서는 불필요하지만 안전)
        import asyncio

        report = asyncio.get_event_loop().run_until_complete(
            capture_and_verify(page, SCREENSHOT_DIR, page_name)
        )

        # 리포트 출력
        print(f"\n{report.summary()}")

        # 에러 수준 이슈가 없어야 통과
        assert report.passed, f"시각 검증 실패: {page_name}\n{report.summary()}"

    def test_no_console_errors(
        self,
        page,  # noqa: ANN001
        base_url: str,
    ) -> None:
        """대시보드 로드 시 JavaScript 콘솔 에러가 없다."""
        errors: list[str] = []

        page.on(
            "console",
            lambda msg: errors.append(msg.text) if msg.type == "error" else None,
        )

        page.goto(base_url)
        page.wait_for_load_state("networkidle")

        # 네트워크 에러(API 미연결 등)는 E2E 환경에서 허용
        critical_errors = [
            e for e in errors if "net::ERR" not in e and "Failed to fetch" not in e
        ]

        assert not critical_errors, "JavaScript 콘솔 에러 감지:\n" + "\n".join(
            critical_errors
        )


class TestScreenshotReport:
    """스크린샷 리포트 생성."""

    def test_generate_full_report(
        self,
        page,  # noqa: ANN001
        base_url: str,
    ) -> None:
        """모든 페이지의 스크린샷을 촬영하고 종합 리포트를 생성한다."""
        import asyncio

        from tests.e2e.visual_checker import capture_and_verify

        reports = []

        for page_name, path in PAGES:
            page.goto(f"{base_url}{path}")
            page.wait_for_load_state("networkidle")

            report = asyncio.get_event_loop().run_until_complete(
                capture_and_verify(page, SCREENSHOT_DIR, page_name)
            )
            reports.append(report)

        # 종합 리포트 출력
        print("\n" + "=" * 60)
        print("대시보드 시각 검증 종합 리포트")
        print("=" * 60)

        total_issues = 0
        for report in reports:
            print(report.summary())
            total_issues += len(report.issues)
            print()

        print(f"총 {len(reports)}개 페이지, {total_issues}개 이슈 발견")
        print("=" * 60)

        # 리포트 파일 저장
        report_path = SCREENSHOT_DIR / "report.txt"
        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
        with open(report_path, "w", encoding="utf-8") as f:
            for report in reports:
                f.write(report.summary() + "\n\n")

        # 에러 수준 이슈가 있으면 실패
        error_count = sum(1 for r in reports for i in r.issues if i.severity == "error")
        assert error_count == 0, f"{error_count}개 에러 수준 이슈 발견"
