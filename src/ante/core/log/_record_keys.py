"""LogRecord 속성 / Ante 예약 키 단일 소스."""

from __future__ import annotations

import logging


def _probe_logrecord_attrs() -> frozenset[str]:
    """실제 LogRecord 인스턴스의 ``__dict__`` 키를 추출한다."""
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
