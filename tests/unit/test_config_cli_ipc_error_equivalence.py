"""Config CLI direct path ↔ IPC path error code equivalence lock (#1843 sub-PR 6).

본 모듈은 #1816 의 7차 migration domain (config) 의 대표 fault 1 건이 CLI
direct path 와 IPC envelope path 양쪽에서 **동일한 public code** 를 노출함을
lock 한다. #1842/#1843 sub-PR 1-5 의 1:1 동형 패턴.

검증 대상 fault:

- ``ConfigValidationError`` → ``CONFIG_VALIDATION_ERROR`` (validation;
  #1673 oracle A7. ``ValueError`` 다중상속을 보존하며 helper registry-first
  lookup 이 동일 안정 코드를 surface)

IPC path 는 ``ante.contracts.ipc_error_payload`` helper (server.py:322 의
``getattr(e, "code", "EXECUTION_ERROR")`` 와 동일 코드를 생성 — 실측 ``.code``
가 일치하는 한 contract 동등성, #1842 plan v2 #6) 로 직접 직렬화한다.

CLI ``config set`` 직접 경로의 ``ClickException`` text-mode prefix UX lock 은
별도 follow-up 책임 (allowlist 의 ``config.py 176/179`` deferred entries) —
본 test 는 IPC envelope + class-level ``.code`` invariant 만 단언한다.
"""

from __future__ import annotations

from ante.config.exceptions import ConfigValidationError
from ante.contracts import ipc_error_payload


def _ipc_envelope_code(exc: BaseException) -> str:
    """주어진 exception 을 IPC envelope 으로 직렬화했을 때의 ``code``.

    IPC server.py:322 가 적용하는 ``getattr(e, "code", "EXECUTION_ERROR")``
    fallback 과 helper(``ipc_error_payload``)의 registry-first resolution 은
    실측 ``.code`` 가 일치하는 한 동일 코드를 생성한다 (#1842 plan v2 #6).
    """

    payload = ipc_error_payload(exc)
    return payload["code"]


# ── ConfigValidationError ↔ CONFIG_VALIDATION_ERROR ─────────────────────────


class TestConfigValidationErrorEquivalence:
    """``ConfigValidationError`` 는 양쪽에서 ``CONFIG_VALIDATION_ERROR``.

    #1673 oracle A7 의 invalid log_level 같은 서비스 경계 입력 오류는
    server.py:322 의 ``getattr(e, "code", "EXECUTION_ERROR")`` 가
    ``CONFIG_VALIDATION_ERROR`` 안정 코드를 envelope 에 노출한다.
    helper registry-first lookup 도 동일 코드를 resolve 한다.

    ``ValueError`` 다중상속은 보존되므로 기존 service-boundary 테스트의
    ``except ValueError`` 경로는 영향 없다.
    """

    def test_ipc_envelope_config_validation_error(self) -> None:
        exc = ConfigValidationError(
            "system.log_level은 _VALID_LOG_LEVELS 멤버여야 합니다 (대소문자 구분)."
        )
        assert _ipc_envelope_code(exc) == "CONFIG_VALIDATION_ERROR"

    def test_class_level_code(self) -> None:
        """``getattr(e, "code")`` 가 typed 코드를 반환 — server.py:322 fallback
        과 helper registry-first 가 동일 코드를 생성하는 invariant."""
        exc = ConfigValidationError("invalid value")
        assert getattr(exc, "code", None) == "CONFIG_VALIDATION_ERROR"

    def test_isinstance_value_error_preserved(self) -> None:
        """``ValueError`` 다중상속 보존 — 기존 service-boundary 테스트가
        ``except ValueError`` 로 잡는 contract 회귀 없음."""
        exc = ConfigValidationError("invalid value")
        assert isinstance(exc, ValueError)
