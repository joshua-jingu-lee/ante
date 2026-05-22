"""Treasury transaction_type vocabulary drift regression.

이슈 #1476 (split of #1443/A): code/spec vocabulary 정규화.

5-value vocabulary: ``allocate``, ``deallocate``, ``release``, ``fill``,
``bot_stopped_release``.

본 테스트는 vocabulary가 drift 없이 일관되게 유지되는지를 검증한다:

1. 코드 SSOT 동결 -- ``TRANSACTION_TYPE_VOCABULARY``가 5-value frozenset인지.
2. 코드 truth -- ``src/ante/treasury`` 내 모든 ``tx_type="..."`` /
   ``tx_type, "..."`` literal writer가 vocabulary에 속하는지.
3. 스펙 동기화 -- ``docs/specs/treasury/06-database-schema.md`` 주석에 5개 값이
   모두 substring으로 명시되는지.
새 writer가 vocabulary 밖 값을 도입하거나 spec이 누락하면 이 테스트가
즉시 FAIL하여 contract-drift를 차단한다.
"""

from __future__ import annotations

import re
from pathlib import Path

from ante.treasury.treasury import TRANSACTION_TYPE_VOCABULARY

EXPECTED_VOCABULARY = frozenset(
    {"allocate", "deallocate", "release", "fill", "bot_stopped_release"}
)

REPO_ROOT = Path(__file__).resolve().parents[2]
TREASURY_SRC_DIR = REPO_ROOT / "src" / "ante" / "treasury"
SPEC_PATH = REPO_ROOT / "docs" / "specs" / "treasury" / "06-database-schema.md"


def test_vocabulary_constant_is_frozen_to_5_values() -> None:
    """코드 SSOT (``TRANSACTION_TYPE_VOCABULARY``)가 5-value로 동결되어야 한다."""
    assert TRANSACTION_TYPE_VOCABULARY == EXPECTED_VOCABULARY


def test_vocabulary_constant_is_immutable_frozenset() -> None:
    """타입이 ``frozenset``이어야 한다 (런타임 mutation 차단)."""
    assert isinstance(TRANSACTION_TYPE_VOCABULARY, frozenset)


def _collect_tx_type_literals_in_treasury_sources() -> set[str]:
    """``src/ante/treasury`` 하위에서 ``_log_transaction`` writer가 사용하는
    transaction type literal을 수집한다.

    두 가지 호출 스타일을 모두 커버한다:
      - keyword: ``tx_type="allocate"``
      - positional: ``self._log_transaction(bot_id, "allocate", amount)``

    keyword는 직접 정규식으로, positional은 ``_log_transaction(`` 호출의 두 번째
    인자 위치 string literal을 정규식으로 추출한다.
    """
    keyword_pattern = re.compile(r'tx_type\s*=\s*"([^"]+)"')
    positional_pattern = re.compile(
        r'_log_transaction\(\s*[^,()]+,\s*"([^"]+)"',
        flags=re.DOTALL,
    )

    found: set[str] = set()
    for py_path in TREASURY_SRC_DIR.rglob("*.py"):
        text = py_path.read_text(encoding="utf-8")
        for match in keyword_pattern.finditer(text):
            found.add(match.group(1))
        for match in positional_pattern.finditer(text):
            found.add(match.group(1))
    return found


def test_all_treasury_writers_use_vocabulary_values() -> None:
    """모든 ``_log_transaction`` writer가 vocabulary에 속한 값만 사용해야 한다.

    새 transaction type을 도입하려는 writer가 vocabulary/spec 갱신 없이
    추가되면 즉시 FAIL.
    """
    literals = _collect_tx_type_literals_in_treasury_sources()
    assert literals, (
        "Treasury source에서 _log_transaction tx_type literal을 하나도 발견하지 "
        "못했다. 수집 정규식이나 호출 사이트를 점검하라."
    )
    unknown = literals - TRANSACTION_TYPE_VOCABULARY
    assert not unknown, (
        f"vocabulary에 없는 transaction type literal이 코드에 존재한다: "
        f"{sorted(unknown)}. spec/TRANSACTION_TYPE_VOCABULARY를 함께 "
        f"갱신하라."
    )


def test_all_writer_literals_are_covered_by_vocabulary_subset() -> None:
    """수집된 writer literal이 vocabulary의 부분집합이어야 한다 (대칭 확인)."""
    literals = _collect_tx_type_literals_in_treasury_sources()
    assert literals.issubset(TRANSACTION_TYPE_VOCABULARY)


def test_spec_database_schema_lists_all_vocabulary_values() -> None:
    """``06-database-schema.md`` 주석이 5개 값 모두를 substring으로 명시해야 한다."""
    assert SPEC_PATH.exists(), f"spec 파일이 없다: {SPEC_PATH}"
    text = SPEC_PATH.read_text(encoding="utf-8")
    missing = [value for value in EXPECTED_VOCABULARY if f"'{value}'" not in text]
    assert not missing, (
        f"spec ({SPEC_PATH.relative_to(REPO_ROOT)})에 누락된 값: {sorted(missing)}. "
        f"transaction_type 주석을 갱신하라."
    )


def test_spec_database_schema_does_not_contain_dead_reserve_value() -> None:
    """제거된 ``'reserve'`` 값이 spec transaction_type 주석에 남아 있지 않아야 한다.

    ``'reserve'``는 코드 writer가 없는 dead value였다. spec 본문 주석에 다시
    노출되면 contract drift이므로 차단한다 (다른 단락에서 ``reserved`` 컬럼 등은
    별개 단어이므로 quoted literal만 검사한다).
    """
    text = SPEC_PATH.read_text(encoding="utf-8")
    assert "'reserve'" not in text, (
        "spec에서 dead transaction type literal 'reserve'를 제거하라."
    )
