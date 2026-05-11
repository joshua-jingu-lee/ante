"""09-public-paths.md SSOT 와 코드 상수 drift 회귀 검증 (#1405).

spec ``docs/specs/web-api/09-public-paths.md`` 는 default-deny 인증 게이트의
면제 경로 SSOT 다. 본 테스트는 그 spec 의 두 표 (PUBLIC_PATHS 정확 일치,
PUBLIC_PREFIXES 접두어 일치) 와 ``gate-exempt-self-auth`` 카테고리 행을
파싱해, 코드 (``src/ante/web/middleware/require_auth.py``) 상수와 정확히
일치하는지 검사한다.

회귀 시 nightmare 시나리오:
    - spec 에 PUBLIC_PATHS 행을 추가했는데 코드 상수에 반영을 빠뜨려, 의도된
      공개 라우트가 default-deny 로 401 차단되는 회귀.
    - 반대로 코드에서 PUBLIC_PATHS 에 새 경로를 몰래 추가했는데 spec 에는
      등록하지 않아 게이트 면제 의도가 문서화되지 않는 drift.
    - ``gate-exempt-self-auth`` 카테고리가 spec 에서 사라졌는데 코드 상수가
      남아 있어 self-auth 라우트가 게이트 없이 통과되는 회귀.

본 테스트는 spec 표 파싱에 fail-loud 정책을 적용한다 (표가 비어 있거나
형식이 깨졌으면 즉시 실패). spec 변경 시 본 파서도 함께 갱신해야 한다.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_SPEC_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "specs"
    / "web-api"
    / "09-public-paths.md"
)


# ── helpers ────────────────────────────────────────────────────────────────


_BACKTICK = re.compile(r"`([^`]+)`")


def _strip_backticks(cell: str) -> str:
    """마크다운 셀에서 ```...``` 백틱을 제거하고 inner 텍스트만 반환.

    셀이 ``` `/api/foo` `` 형태면 ``/api/foo`` 를 반환. 백틱이 없으면 셀
    raw 그대로 strip 하여 반환.
    """
    match = _BACKTICK.search(cell)
    if match is None:
        return cell.strip()
    return match.group(1).strip()


def _parse_table_rows(
    lines: list[str], header_match: str
) -> list[tuple[str, str, str]]:
    """spec 의 한 테이블에서 (col1, col2, col3) 데이터 행을 추출.

    Args:
        lines: spec 파일 라인 리스트.
        header_match: 헤더 행에서 식별자로 쓸 부분 문자열
            (예: ``"| 경로 | 카테고리 |"``). 이 부분을 포함하는 헤더 행을
            찾으면, 그 다음 ``|---|---|---|`` 구분 행을 건너뛰고, ``|`` 로
            시작하지 않는 행을 만날 때까지 데이터 행을 수집한다.

    Returns:
        (col1, col2, col3) 튜플 리스트. col1 은 ``_strip_backticks`` 로
        백틱을 제거한 상태. col2, col3 은 raw strip.
    """
    rows: list[tuple[str, str, str]] = []
    in_table = False
    seen_separator = False
    for line in lines:
        stripped = line.strip()
        if not in_table:
            if header_match in stripped:
                in_table = True
                seen_separator = False
            continue
        # 헤더 다음 라인은 ``|---|...|`` separator.
        if not seen_separator:
            if stripped.startswith("|") and set(stripped.replace("|", "").strip()) <= {
                "-",
                " ",
                ":",
            }:
                seen_separator = True
                continue
            # separator 가 아닌 다른 라인이 먼저 오면 표 형식이 깨진 것.
            pytest.fail(
                f"spec 09-public-paths.md 의 '{header_match}' 표 separator 가 "
                "예상 위치에 없음. spec 파싱 동기화 필요."
            )
        # 표 종료 조건: ``|`` 로 시작하지 않는 행 (빈 줄 포함).
        if not stripped.startswith("|"):
            break
        # 데이터 행 파싱. 앞뒤 ``|`` 제거 후 split.
        # 일부 셀에 escape 된 ``\|`` 가 들어갈 가능성은 본 spec 범위 밖이므로
        # naive split 으로 충분.
        parts = [p.strip() for p in stripped.strip("|").split("|")]
        if len(parts) < 3:
            pytest.fail(
                f"spec 09-public-paths.md 의 '{header_match}' 표 행 컬럼 수 부족: "
                f"{stripped!r}"
            )
        col1 = _strip_backticks(parts[0])
        col2 = parts[1]
        col3 = parts[2]
        rows.append((col1, col2, col3))
    if not in_table:
        pytest.fail(
            f"spec 09-public-paths.md 에서 헤더 '{header_match}' 표를 찾지 못함."
        )
    if not rows:
        pytest.fail(
            f"spec 09-public-paths.md 의 '{header_match}' 표 데이터 행이 비어 있음."
        )
    return rows


# ── fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def spec_lines() -> list[str]:
    if not _SPEC_PATH.is_file():
        pytest.fail(f"spec 파일을 찾지 못함: {_SPEC_PATH}")
    return _SPEC_PATH.read_text(encoding="utf-8").splitlines()


# ── tests ──────────────────────────────────────────────────────────────────


def test_public_paths_match_spec(spec_lines: list[str]) -> None:
    """``PUBLIC_PATHS`` 정확 일치 + ``GATE_EXEMPT_SELF_AUTH_PATHS`` 행이 spec
    "PUBLIC_PATHS (정확 일치)" 표 와 일치한다.

    spec 표는 ``public`` 카테고리 행과 ``gate-exempt-self-auth`` 카테고리 행을
    한 표에서 분리하므로, 본 테스트도 카테고리 컬럼으로 분기해 비교한다.
    """
    from ante.web.middleware.require_auth import (
        GATE_EXEMPT_SELF_AUTH_PATHS,
        PUBLIC_PATHS,
    )

    rows = _parse_table_rows(spec_lines, "| 경로 | 카테고리 |")

    spec_public: set[str] = set()
    spec_gate_exempt: set[str] = set()
    unknown_category: list[tuple[str, str]] = []
    for path, category, _ in rows:
        cat = category.strip()
        if cat == "public":
            spec_public.add(path)
        elif cat == "gate-exempt-self-auth":
            spec_gate_exempt.add(path)
        else:
            unknown_category.append((path, cat))

    if unknown_category:
        pytest.fail(
            "spec 09-public-paths.md 의 PUBLIC_PATHS 표에 알 수 없는 카테고리: "
            f"{unknown_category}. 본 파서 또는 spec 갱신 필요."
        )

    if spec_public != set(PUBLIC_PATHS):
        only_in_spec = sorted(spec_public - set(PUBLIC_PATHS))
        only_in_code = sorted(set(PUBLIC_PATHS) - spec_public)
        pytest.fail(
            "PUBLIC_PATHS 코드 상수와 09-public-paths.md SSOT drift 발생:\n"
            f"  spec only (코드 누락): {only_in_spec}\n"
            f"  code only (spec 누락): {only_in_code}"
        )

    if spec_gate_exempt != set(GATE_EXEMPT_SELF_AUTH_PATHS):
        only_in_spec = sorted(spec_gate_exempt - set(GATE_EXEMPT_SELF_AUTH_PATHS))
        only_in_code = sorted(set(GATE_EXEMPT_SELF_AUTH_PATHS) - spec_gate_exempt)
        pytest.fail(
            "GATE_EXEMPT_SELF_AUTH_PATHS 코드 상수와 09-public-paths.md SSOT "
            "drift 발생:\n"
            f"  spec only (코드 누락): {only_in_spec}\n"
            f"  code only (spec 누락): {only_in_code}"
        )


def test_public_prefixes_match_spec(spec_lines: list[str]) -> None:
    """``PUBLIC_PREFIXES`` 접두어 튜플이 spec "PUBLIC_PREFIXES (접두어 일치)"
    표 와 일치한다.

    spec 은 ``/assets/*`` 형식으로 wildcard 표기, 코드는 ``/assets/`` 처럼
    trailing slash 가 명시된 prefix 를 사용한다. 비교를 위해 spec 항목 끝의
    ``*`` 를 제거해 normalize 한다.
    """
    from ante.web.middleware.require_auth import PUBLIC_PREFIXES

    rows = _parse_table_rows(spec_lines, "| 접두어 | 카테고리 |")

    spec_prefixes: set[str] = set()
    for prefix, category, _ in rows:
        # spec 은 ``/assets/*`` 표기. trailing ``*`` 만 normalize 한다.
        normalized = prefix.rstrip("*")
        if not normalized.endswith("/"):
            pytest.fail(
                "spec 09-public-paths.md PUBLIC_PREFIXES 표의 접두어가 trailing "
                f"slash 로 끝나지 않음: {prefix!r}. 코드 상수와 정합 불가."
            )
        spec_prefixes.add(normalized)
        # 카테고리가 ``public`` 이외이면 본 파서 가정이 깨진 것.
        if category.strip() != "public":
            pytest.fail(
                "spec 09-public-paths.md PUBLIC_PREFIXES 표에 ``public`` 이외 "
                f"카테고리 항목 발견: {prefix!r} → {category!r}. 본 테스트 갱신 필요."
            )

    if spec_prefixes != set(PUBLIC_PREFIXES):
        only_in_spec = sorted(spec_prefixes - set(PUBLIC_PREFIXES))
        only_in_code = sorted(set(PUBLIC_PREFIXES) - spec_prefixes)
        pytest.fail(
            "PUBLIC_PREFIXES 코드 상수와 09-public-paths.md SSOT drift 발생:\n"
            f"  spec only (코드 누락): {only_in_spec}\n"
            f"  code only (spec 누락): {only_in_code}"
        )
