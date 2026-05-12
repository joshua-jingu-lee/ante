"""Scope vocabulary spec ↔ code drift 검증 (#1439).

``docs/specs/member/02-design-decisions.md`` 의 "권한 범위 (Scope)" 매트릭스
(L177-194) 와 ``src/ante/member/scopes.py`` 의 ``SCOPE_VOCABULARY`` 가 어긋나지
않도록 정적으로 잠근다.

본 테스트가 잠그는 invariant:

1. spec doc 매트릭스의 모든 valid cell (``—`` 가 아닌 cell) 은
   ``SCOPE_VOCABULARY`` 에 등록되어 있어야 한다.
2. ``SCOPE_VOCABULARY`` 는 spec doc 매트릭스의 valid cell 집합과 정확히
   같거나(== ) 의도적 superset 이어야 한다. superset 이라면 본 테스트가
   안내 메시지로 추가 원소를 보고하고, 그 자체가 회귀로 보이지 않게 별도
   허용 리스트(``_INTENTIONAL_EXTRAS``)를 갱신해야 한다.

매트릭스 파싱 전략 (Stop Conditions: spec doc 매트릭스 파싱이 fragile 하면
하드코딩 fallback): 매트릭스의 각 라인을 명시적 정규식으로 파싱한다. 파싱이
실패하면 즉시 fail 하여 fragile 한 형식 변경을 잠근다. spec doc 의 매트릭스
구조는 D-015 (default-deny auth gate) 결정 이후 안정화되어 있어 broad-match
보다 직접 파싱이 더 정확하다.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from ante.member.scopes import SCOPE_VOCABULARY

SPEC_DOC_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "specs"
    / "member"
    / "02-design-decisions.md"
)


# 매트릭스 도메인 행: ``| `account` | ... |`` 형식.
# 컬럼: domain | read | write | admin | run
_DOMAIN_ROW_RE = re.compile(
    r"^\|\s*`(?P<domain>[a-z_]+)`\s*"
    r"\|\s*(?P<read>[^|]*?)\s*"
    r"\|\s*(?P<write>[^|]*?)\s*"
    r"\|\s*(?P<admin>[^|]*?)\s*"
    r"\|\s*(?P<run>[^|]*?)\s*"
    r"\|\s*$"
)

# ``—`` (em-dash) 단독 cell 만 invalid 표기. 빈 cell 도 invalid 로 본다.
_EMPTY_CELL_RE = re.compile(r"^\s*(?:—|-)?\s*$")


# 의도적 vocabulary > spec_matrix 인 scope (현재는 없음). 발생 시 본 리스트에
# 등록 + 따로 회귀 사유를 주석으로 명시한다. spec 갱신을 후속 이슈로 처리하는
# 케이스에 한해 사용.
_INTENTIONAL_EXTRAS: frozenset[str] = frozenset(set())


def _parse_spec_matrix() -> frozenset[str]:
    """spec doc 의 권한 범위 매트릭스를 파싱해 valid scope 집합을 반환한다.

    매트릭스 시작은 헤더 ``| 도메인 | read | write | admin | run |`` 행이고,
    종료는 비-row (빈 줄 또는 ``> note`` 같은 인용) 행이다.
    """
    text = SPEC_DOC_PATH.read_text(encoding="utf-8")
    lines = text.splitlines()

    # 매트릭스 헤더 시점 찾기.
    header_idx: int | None = None
    for idx, line in enumerate(lines):
        # 헤더 행 형식. ``| 도메인 | read | write | admin | run |``.
        stripped = line.strip()
        if (
            stripped.startswith("|")
            and "도메인" in stripped
            and "read" in stripped
            and "write" in stripped
            and "admin" in stripped
            and "run" in stripped
        ):
            header_idx = idx
            break
    assert header_idx is not None, (
        "spec doc 매트릭스 헤더를 찾지 못했습니다. "
        f"형식 변경 가능성 확인 필요: {SPEC_DOC_PATH}"
    )

    # 헤더 다음 줄은 separator ``|--------|...``. 그 다음 줄부터 도메인 행.
    matrix_start = header_idx + 2
    scopes: set[str] = set()
    domains_seen: set[str] = set()

    for line in lines[matrix_start:]:
        if not line.strip().startswith("|"):
            # 매트릭스 종료 (빈 줄 또는 다른 블록).
            break
        m = _DOMAIN_ROW_RE.match(line)
        if not m:
            # 매트릭스 내부의 형식 변형. fail-fast 로 fragile parsing 잠금.
            pytest.fail(f"매트릭스 도메인 행 파싱 실패 — 형식 변경 가능성: {line!r}")
        domain = m.group("domain")
        assert domain not in domains_seen, (
            f"매트릭스 도메인 중복: {domain!r} ({SPEC_DOC_PATH})"
        )
        domains_seen.add(domain)
        for level_name in ("read", "write", "admin", "run"):
            cell = m.group(level_name)
            if _EMPTY_CELL_RE.match(cell):
                continue
            scopes.add(f"{domain}:{level_name}")

    assert scopes, "spec doc 매트릭스에서 valid scope 를 하나도 파싱하지 못했습니다."
    return frozenset(scopes)


class TestScopeDrift:
    def test_spec_matrix_subset_of_vocabulary(self) -> None:
        """spec doc 매트릭스의 모든 valid cell 이 ``SCOPE_VOCABULARY`` 에 있어야 한다.

        매트릭스에 새 cell 이 추가되었는데 ``SCOPE_VOCABULARY`` 가 갱신되지
        않았다면 본 어서션이 fail 한다.
        """
        spec_scopes = _parse_spec_matrix()
        missing = spec_scopes - SCOPE_VOCABULARY
        assert not missing, (
            f"spec doc 매트릭스에 있지만 SCOPE_VOCABULARY 에 없는 scope: "
            f"{sorted(missing)} — ``src/ante/member/scopes.py`` 갱신 필요"
        )

    def test_vocabulary_subset_of_spec_matrix_or_intentional(self) -> None:
        """``SCOPE_VOCABULARY`` 의 원소는 spec doc 매트릭스 또는 의도적
        ``_INTENTIONAL_EXTRAS`` 둘 중 하나에 속해야 한다.

        ``SCOPE_VOCABULARY`` 가 spec doc 의 superset 으로 늘어났다면 본
        어서션이 fail 한다. follow-up 이슈로 spec 매트릭스를 갱신하거나
        ``_INTENTIONAL_EXTRAS`` 에 의도적으로 등록해야 한다.
        """
        spec_scopes = _parse_spec_matrix()
        extra = SCOPE_VOCABULARY - spec_scopes - _INTENTIONAL_EXTRAS
        assert not extra, (
            f"SCOPE_VOCABULARY 에 있지만 spec doc 매트릭스에 없는 scope: "
            f"{sorted(extra)} — spec 갱신 또는 _INTENTIONAL_EXTRAS 등록 필요"
        )

    def test_vocabulary_equals_spec_matrix(self) -> None:
        """현재 시점 invariant: vocabulary == spec_matrix (extras 없음).

        ``_INTENTIONAL_EXTRAS`` 가 비어 있는 한 본 테스트는 위 두 테스트의
        합집합을 한 줄로 잠근다. 추후 의도적 extras 가 추가되면 본 테스트는
        ``_INTENTIONAL_EXTRAS`` 를 반영해 갱신한다.
        """
        spec_scopes = _parse_spec_matrix()
        assert SCOPE_VOCABULARY - _INTENTIONAL_EXTRAS == spec_scopes
