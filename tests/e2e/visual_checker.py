"""시각 검증 유틸리티 — 스크린샷 분석 + DOM 검증.

Playwright 페이지의 시각적 품질을 검증한다:
- 스크린샷 촬영 및 저장
- DOM 기반 레이아웃 이상 감지 (오버플로우, 빈 영역)
- 텍스트 추출 및 기본 오탈자 검사
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class VisualIssue:
    """시각 검증에서 발견된 이슈."""

    page_url: str
    issue_type: str  # "overflow" | "empty_area" | "typo" | "error_text"
    description: str
    severity: str = "warning"  # "warning" | "error"


@dataclass
class VisualReport:
    """시각 검증 결과 리포트."""

    page_url: str
    screenshot_path: str | None = None
    issues: list[VisualIssue] = field(default_factory=list)
    texts_extracted: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        """에러 수준 이슈가 없으면 통과."""
        return not any(i.severity == "error" for i in self.issues)

    def summary(self) -> str:
        """사람 읽기용 요약."""
        status = "PASS" if self.passed else "FAIL"
        lines = [f"[{status}] {self.page_url}"]
        if self.screenshot_path:
            lines.append(f"  screenshot: {self.screenshot_path}")
        for issue in self.issues:
            lines.append(
                f"  [{issue.severity}] {issue.issue_type}: {issue.description}"
            )
        return "\n".join(lines)


# ── 한국어 오탈자 패턴 (일반적인 깨진 텍스트) ──────────


# 인코딩 깨짐 패턴 (연속된 특수문자, □, ?, replacement char)
_BROKEN_TEXT_PATTERNS = [
    re.compile(r"[\ufffd]{2,}"),  # Unicode replacement character
    re.compile(r"[□]{2,}"),  # 빈 사각형
    re.compile(r"[?]{5,}"),  # 연속 물음표
]

# 에러 메시지 패턴
_ERROR_TEXT_PATTERNS = [
    re.compile(r"undefined", re.IGNORECASE),
    re.compile(r"\[object Object\]"),
    re.compile(r"NaN"),
    re.compile(r"Error:", re.IGNORECASE),
    re.compile(r"Cannot read propert", re.IGNORECASE),
]


async def capture_and_verify(
    page,  # noqa: ANN001  (Playwright Page)
    output_dir: Path,
    page_name: str,
) -> VisualReport:
    """페이지 스크린샷 촬영 + 시각 검증 수행.

    Args:
        page: Playwright Page 객체.
        output_dir: 스크린샷 저장 디렉토리.
        page_name: 페이지 식별자 (파일명에 사용).

    Returns:
        VisualReport 검증 결과.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    url = page.url

    # 1. 스크린샷 촬영
    screenshot_path = output_dir / f"{page_name}.png"
    await page.screenshot(path=str(screenshot_path), full_page=True)

    report = VisualReport(page_url=url, screenshot_path=str(screenshot_path))

    # 2. DOM 기반 레이아웃 검증
    overflow_issues = await _check_overflow(page, url)
    report.issues.extend(overflow_issues)

    # 3. 빈 영역 검증 (body가 비어있는 경우)
    empty_issues = await _check_empty_content(page, url)
    report.issues.extend(empty_issues)

    # 4. 텍스트 추출 + 오탈자/에러 검사
    texts = await _extract_visible_text(page)
    report.texts_extracted = texts
    text_issues = _check_text_issues(texts, url)
    report.issues.extend(text_issues)

    return report


async def _check_overflow(page, url: str) -> list[VisualIssue]:  # noqa: ANN001
    """수평 오버플로우 감지."""
    issues = []

    has_overflow = await page.evaluate(
        "() => document.documentElement.scrollWidth"
        " > document.documentElement.clientWidth"
    )

    if has_overflow:
        issues.append(
            VisualIssue(
                page_url=url,
                issue_type="overflow",
                description="수평 스크롤 오버플로우 감지",
                severity="warning",
            )
        )

    return issues


async def _check_empty_content(page, url: str) -> list[VisualIssue]:  # noqa: ANN001
    """#root 내부 콘텐츠가 비어있는지 확인."""
    issues = []

    root_text = await page.evaluate("""() => {
        const root = document.getElementById('root');
        return root ? root.innerText.trim() : '';
    }""")

    if not root_text:
        issues.append(
            VisualIssue(
                page_url=url,
                issue_type="empty_area",
                description="#root 내부 콘텐츠 비어있음 (렌더링 실패 가능)",
                severity="error",
            )
        )

    return issues


async def _extract_visible_text(page) -> list[str]:  # noqa: ANN001
    """페이지의 보이는 텍스트를 추출."""
    text = await page.evaluate("""() => {
        const root = document.getElementById('root');
        return root ? root.innerText : document.body.innerText;
    }""")
    return [line.strip() for line in text.split("\n") if line.strip()]


def _check_text_issues(texts: list[str], url: str) -> list[VisualIssue]:
    """텍스트에서 깨진 문자/에러 메시지를 검사."""
    issues = []
    full_text = " ".join(texts)

    for pattern in _BROKEN_TEXT_PATTERNS:
        if pattern.search(full_text):
            issues.append(
                VisualIssue(
                    page_url=url,
                    issue_type="typo",
                    description=f"깨진 텍스트 패턴 감지: {pattern.pattern}",
                    severity="error",
                )
            )

    for pattern in _ERROR_TEXT_PATTERNS:
        match = pattern.search(full_text)
        if match:
            context = full_text[max(0, match.start() - 20) : match.end() + 20]
            issues.append(
                VisualIssue(
                    page_url=url,
                    issue_type="error_text",
                    description=f"에러 텍스트 감지: ...{context}...",
                    severity="warning",
                )
            )

    return issues
