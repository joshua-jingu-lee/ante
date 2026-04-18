"""JSONL 시스템 로그 Formatter.

`docs/specs/logging/03-json-schema.md` 에 정의된 스키마에 따라 한 라인
JSON 엔트리를 생성한다.
"""

import json
import logging
import os
import traceback
from datetime import UTC, datetime

from .fingerprint import compute_fingerprint

_RESERVED = {"ts", "level", "logger", "msg", "env", "exc"}
_STANDARD_EXTRA = (
    "account_id",
    "bot_id",
    "strategy_id",
    "order_id",
    "symbol",
    "request_id",
)
_LOGRECORD_BUILTIN = {
    "args",
    "asctime",
    "created",
    "exc_info",
    "exc_text",
    "filename",
    "funcName",
    "levelname",
    "levelno",
    "lineno",
    "message",
    "module",
    "msecs",
    "msg",
    "name",
    "pathname",
    "process",
    "processName",
    "relativeCreated",
    "stack_info",
    "taskName",
    "thread",
    "threadName",
}


class JsonFormatter(logging.Formatter):
    """LogRecord를 JSONL 한 줄로 직렬화한다."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC)
            .isoformat()
            .replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "env": os.environ.get("ANTE_ENV", "production"),
        }

        for key in _STANDARD_EXTRA:
            if hasattr(record, key):
                payload[key] = getattr(record, key)

        extras: dict[str, object] = {}
        for k, v in record.__dict__.items():
            if (
                k in _LOGRECORD_BUILTIN
                or k in _RESERVED
                or k in _STANDARD_EXTRA
                or k.startswith("_")
            ):
                continue
            extras[k] = v
        if extras:
            payload["extra"] = extras

        if record.exc_info:
            exc_type, exc_val, exc_tb = record.exc_info
            payload["exc"] = {
                "type": exc_type.__name__ if exc_type else "UnknownException",
                "message": str(exc_val) if exc_val is not None else "",
                "traceback": "".join(
                    traceback.format_exception(exc_type, exc_val, exc_tb)
                ),
                "fingerprint": compute_fingerprint(
                    exc_type if exc_type else type(exc_val) if exc_val else Exception,
                    exc_tb,
                    record.name,
                ),
            }

        return json.dumps(payload, ensure_ascii=False)
