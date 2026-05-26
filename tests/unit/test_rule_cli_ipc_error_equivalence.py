"""Rule CLI direct path ↔ IPC path error code equivalence lock (#1843 sub-PR 6).

본 모듈은 #1816 의 7차 migration domain (rule) 의 대표 fault 1 건이
IPC envelope path 에서 **안정 public code** 를 노출함을 lock 한다.
#1842/#1843 sub-PR 1-5 의 1:1 동형 패턴.

검증 대상 fault:

- ``RuleConfigError`` → ``RULE_CONFIG_ERROR`` (validation; 본 PR 신규 부여)

``RuleConfigError`` 는 현재 코드베이스에서 직접 raise 되는 callsite 가 없는
prepared contract lock 이다 (정의만 존재하며 향후 Rule Engine config 입력
검증에서 raise 될 예정). 본 test 는 raise 시 helper / IPC server 가 동일
안정 코드를 surface 하도록 lock 한다.

IPC path 는 ``ante.contracts.ipc_error_payload`` helper (server.py:322 의
``getattr(e, "code", "EXECUTION_ERROR")`` 와 동일 코드를 생성 — 실측 ``.code``
가 일치하는 한 contract 동등성, #1842 plan v2 #6) 로 직접 직렬화한다.
"""

from __future__ import annotations

from ante.contracts import ipc_error_payload
from ante.rule.exceptions import RuleConfigError


def _ipc_envelope_code(exc: BaseException) -> str:
    """주어진 exception 을 IPC envelope 으로 직렬화했을 때의 ``code``.

    IPC server.py:322 가 적용하는 ``getattr(e, "code", "EXECUTION_ERROR")``
    fallback 과 helper(``ipc_error_payload``)의 registry-first resolution 은
    실측 ``.code`` 가 일치하는 한 동일 코드를 생성한다 (#1842 plan v2 #6).
    """

    payload = ipc_error_payload(exc)
    return payload["code"]


# ── RuleConfigError ↔ RULE_CONFIG_ERROR ─────────────────────────────────────


class TestRuleConfigErrorEquivalence:
    """``RuleConfigError`` 는 IPC envelope 에서 ``RULE_CONFIG_ERROR``.

    Rule Engine config 입력 invariant 위반 (rule_type/params 등) 의 안정
    코드. helper registry-first lookup 과 server.py:322 ``getattr(e, "code",
    ...)`` 가 동일 코드를 surface 한다.
    """

    def test_ipc_envelope_rule_config_error(self) -> None:
        exc = RuleConfigError("rule_type 'invalid' 은 허용되지 않습니다.")
        assert _ipc_envelope_code(exc) == "RULE_CONFIG_ERROR"

    def test_class_level_code(self) -> None:
        """``getattr(e, "code")`` 가 typed 코드를 반환 — server.py:322 fallback
        과 helper registry-first 가 동일 코드를 생성하는 invariant."""
        exc = RuleConfigError("invalid config")
        assert getattr(exc, "code", None) == "RULE_CONFIG_ERROR"
