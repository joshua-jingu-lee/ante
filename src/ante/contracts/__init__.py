"""Contract SSOT 공통 인프라.

이 package는 CLI(#1815)/IPC(#1819) 계열 contract surface가
공유할 vocabulary 등 공통 정의의 SSOT 위치다.

본 패키지에 등록된 SSOT:

- ``ante.contracts.vocab`` — ``ContractKind`` / ``EnvelopeForm`` / ``AuthMode``
  vocabulary (#1822). alias re-export 없음 — 소비자는 명시 import 한다.
- ``ante.contracts.errors`` — ``ErrorCategory`` Literal + ``ErrorSpec`` dataclass
  (#1839/#1840 normative).
- ``ante.contracts.error_registry`` — 대표 fault lock mapping (#1840).
  helper-internal — 외부 소비자는 ``error_spec_for_exception`` 을 호출한다.
- ``ante.contracts.helpers`` — ``error_spec_for_exception`` / ``emit_cli_error`` /
  ``ipc_error_payload`` CLI·IPC error helper (#1840).

본 ``__init__`` 모듈은 ``error_*`` helper 의 alias re-export 만 수행한다
(``ErrorSpec`` / ``ErrorCategory`` / 3 helper 함수). vocab module 은 의도적으로
re-export 하지 않으며, vocabulary 위치가 단일 SSOT 로 고정되도록 ``from
ante.contracts.vocab import ...`` 명시 import 형태를 유지한다.
"""

from __future__ import annotations

from ante.contracts.errors import ErrorCategory, ErrorSpec
from ante.contracts.helpers import (
    emit_cli_error,
    error_spec_for_exception,
    ipc_error_payload,
)

__all__ = [
    "ErrorCategory",
    "ErrorSpec",
    "emit_cli_error",
    "error_spec_for_exception",
    "ipc_error_payload",
]
