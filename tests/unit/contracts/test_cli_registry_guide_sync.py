"""CLI registry ↔ ``guide/cli.md`` generated reference sync tests (#1848 Family B).

#1815 epic 의 마지막 sub. ``scripts/generate_cli_reference.py`` 의
:func:`generate_cli_reference` 가 Click introspection 결과를 markdown 으로
출력한다. 본 generator 는 ``guide/cli.md`` 의 SSOT 다.

본 모듈은 두 invariant 를 강제한다:

* **Idempotency**: generator 를 같은 process / 같은 input 으로 두 번 실행하면
  output 이 byte-equal 해야 한다. 비결정적 ordering (dict iteration, set
  iteration, scope 출력) 회귀를 잡는다.

* **Determinism modulo timestamp**: 동일 process 안에서 두 번 호출하면
  ``> 마지막 갱신: YYYY-MM-DD`` 줄을 포함한 전체 output 이 동일하다 (같은
  process 의 ``datetime.now()`` 가 ms 단위까지 같지는 않지만 day precision
  만 출력하므로). 본 invariant 는 generator 의 timestamp emission 패턴에
  의존하지 않도록 timestamp 줄을 정규화한 비교도 함께 둔다.

본 PR (#1848) 는 ``guide/cli.md`` 의 *본문* 을 갱신하지 않는다 — committed
markdown 과 freshly generated output 의 비교는 별도 dedicated PR 이 처리
한다는 #1848 stop condition 을 따른다. 본 테스트는 generator 자신의 행동
invariant 만 검증한다.
"""

from __future__ import annotations

import io
import re
import sys
from pathlib import Path

import pytest

# ── fixtures / setup ───────────────────────────────────────────────────────


def _repo_root() -> Path:
    """본 test file 기준 repo root 절대 경로."""
    return Path(__file__).resolve().parent.parent.parent.parent


@pytest.fixture(scope="module")
def _scripts_on_path() -> None:
    """``scripts/`` 디렉토리를 ``sys.path`` 에 일시적으로 추가.

    ``generate_cli_reference`` 는 top-level script 라 package 가 아니다. test
    process 가 import 할 수 있도록 ``scripts/`` 경로를 path 에 넣는다.
    """
    scripts_dir = str(_repo_root() / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)


_TIMESTAMP_RE = re.compile(r"^> 마지막 갱신: \d{4}-\d{2}-\d{2}$", re.MULTILINE)


def _normalize_timestamp(markdown: str) -> str:
    """``> 마지막 갱신: YYYY-MM-DD`` 행을 ``<TIMESTAMP>`` 자리표시자로 치환.

    generator 의 day-precision timestamp 를 정규화해 본문 결정성만 비교한다.
    """
    return _TIMESTAMP_RE.sub("> 마지막 갱신: <TIMESTAMP>", markdown)


# ── tests ───────────────────────────────────────────────────────────────────


def test_generate_cli_reference_is_byte_equal_on_repeat(
    _scripts_on_path: None,
) -> None:
    """같은 process 에서 두 번 호출하면 output 이 byte-equal.

    Click introspection 의 비결정적 ordering 회귀를 잡는다. dict / set /
    scope ordering 변경, hidden command set 의 ordering 변화 같은 회귀가
    있으면 본 테스트가 FAIL 한다.

    timestamp 까지 포함해 완전 동치를 본다 — generator 가 same-day 안에서는
    같은 timestamp 를 emit 한다는 invariant 도 함께 강제한다.
    """
    from generate_cli_reference import generate_cli_reference  # noqa: PLC0415

    buf1 = io.StringIO()
    count1 = generate_cli_reference(buf1)
    buf2 = io.StringIO()
    count2 = generate_cli_reference(buf2)

    assert count1 == count2, (
        f"subcommand count 가 두 번의 호출에서 다름: "
        f"first={count1}, second={count2} (non-determinism 의심)"
    )

    output1 = buf1.getvalue()
    output2 = buf2.getvalue()
    assert output1 == output2, (
        "generate_cli_reference 가 같은 process 에서 두 번 호출되었는데 "
        f"output 이 다름 (lengths: first={len(output1)}, second={len(output2)}). "
        "Click introspection 의 비결정적 ordering 회귀 의심."
    )


def test_generate_cli_reference_body_is_deterministic(
    _scripts_on_path: None,
) -> None:
    """timestamp 를 정규화한 본문은 두 호출에서 byte-equal.

    :func:`test_generate_cli_reference_is_byte_equal_on_repeat` 와 같은
    invariant 를 timestamp 추출 후 다시 본다. timestamp regex 가 잡지 못
    하는 또 다른 비결정 source 가 있으면 본 테스트도 FAIL 한다 (defense-in-depth).
    """
    from generate_cli_reference import generate_cli_reference  # noqa: PLC0415

    buf1 = io.StringIO()
    generate_cli_reference(buf1)
    buf2 = io.StringIO()
    generate_cli_reference(buf2)

    norm1 = _normalize_timestamp(buf1.getvalue())
    norm2 = _normalize_timestamp(buf2.getvalue())
    assert norm1 == norm2, (
        "generate_cli_reference 의 timestamp 외 본문이 두 호출에서 다름. "
        "timestamp regex 가 잡지 못하는 추가 비결정성 의심."
    )


def test_generate_cli_reference_emits_expected_structural_anchors(
    _scripts_on_path: None,
) -> None:
    """generator output 의 핵심 구조 anchor 가 항상 등장한다.

    구조적 회귀 (예: 글로벌 옵션 섹션 누락, 명령어 요약 표 누락) 를 빠르게
    잡는다. 본 테스트는 본문 byte-level diff 가 아니라 anchor 존재 여부만
    본다 — committed ``guide/cli.md`` 본문과의 동기화는 별도 PR scope.
    """
    from generate_cli_reference import generate_cli_reference  # noqa: PLC0415

    buf = io.StringIO()
    count = generate_cli_reference(buf)
    output = buf.getvalue()

    # 최소한의 구조 anchor — generator 가 정상 동작하면 모두 등장한다.
    assert "# Ante CLI Reference" in output
    assert "## 글로벌 옵션" in output
    assert "## 명령어 요약" in output
    assert "> 마지막 갱신:" in output
    # 본 PR 시점 Click 트리는 105 leaf — 향후 leaf 추가/제거가 정상이므로
    # 정확한 수치보다 "두 자릿수 이상의 leaf 를 emit" 인지만 본다.
    assert count >= 50, (
        f"generate_cli_reference 가 expected 보다 적은 leaf 를 emit ({count} < 50). "
        "Click 트리 또는 generator hidden filter 회귀 의심."
    )


def test_generate_cli_reference_timestamp_normalization_smoke() -> None:
    """timestamp 정규화 regex 가 실제 generator output 패턴을 매치한다.

    :func:`_normalize_timestamp` 는 본 모듈의 invariant 강제 helper 다.
    regex 가 잘못 변경되어 매치하지 못하면 idempotency 검사가 false-pass
    하므로 regex 자체를 smoke test 한다.
    """
    sample = "> 마지막 갱신: 2026-05-27"
    normalized = _normalize_timestamp(sample)
    assert normalized == "> 마지막 갱신: <TIMESTAMP>"

    # multi-line 안에서도 정확히 timestamp 줄만 치환한다.
    sample_multi = "Header\n> 마지막 갱신: 2026-05-27\nBody"
    normalized_multi = _normalize_timestamp(sample_multi)
    assert normalized_multi == "Header\n> 마지막 갱신: <TIMESTAMP>\nBody"

    # timestamp 가 아닌 줄은 변하지 않는다.
    sample_noop = "> 다른 인용\n  > 마지막 갱신: 2026-05-27"
    # leading spaces 가 있으면 매치하지 않는다 (^ anchor + MULTILINE).
    normalized_noop = _normalize_timestamp(sample_noop)
    assert "  > 마지막 갱신: 2026-05-27" in normalized_noop
