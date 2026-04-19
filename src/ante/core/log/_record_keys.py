"""LogRecord 속성 / Ante 예약 키 단일 소스.

Python 버전별 ``LogRecord.__init__`` 이 설정하는 속성 집합이 다르다
(예: 3.12 부터 ``taskName`` 추가). formatter 와 safe_logger 가 각자 하드코딩된
목록을 유지하면 버전 업그레이드 시 한쪽만 수정되어 드리프트가 발생한다.

이 모듈은 **런타임 프로브**로 LogRecord 속성을 추출해 단일 소스를 제공한다.
formatter 와 safe_logger 는 반드시 이 모듈의 상수를 임포트해 사용한다.
"""

from __future__ import annotations

import logging


def _probe_logrecord_attrs() -> frozenset[str]:
    """실제 LogRecord 인스턴스의 ``__dict__`` 키를 추출한다.

    ``getMessage()`` / ``asctime`` 은 ``LogRecord.__init__`` 이 설정하지 않지만
    ``Formatter.format()`` 이 동적으로 주입하는 속성이므로 포함한다.
    """
    probe = logging.LogRecord(
        name="_probe",
        level=logging.INFO,
        pathname="_probe",
        lineno=0,
        msg="_probe",
        args=(),
        exc_info=None,
    )
    return frozenset(probe.__dict__.keys()) | {"message", "asctime"}


LOGRECORD_ATTRS: frozenset[str] = _probe_logrecord_attrs()
"""LogRecord 가 점유하는 모든 속성 이름 집합 (런타임 Python 버전 기준)."""

ANTE_RESERVED: frozenset[str] = frozenset(
    {"ts", "level", "logger", "msg", "env", "exc"}
)
"""JSONL 스펙 (`03-json-schema.md` §예약어 처리) 의 Ante 표준 필드."""
