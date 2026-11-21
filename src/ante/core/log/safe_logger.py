"""Reserved-key 를 안전하게 처리하는 Logger 서브클래스."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from ._record_keys import ANTE_RESERVED as _ANTE_RESERVED
from ._record_keys import LOGRECORD_ATTRS as _LOGRECORD_RESERVED


def _sanitize_extra(
    extra: Mapping[str, object] | None,
) -> dict[str, object] | None:
    """예약 키 충돌을 제거한 extra dict 반환."""
    if extra is None:
        return None
    cleaned: dict[str, object] = {}
    for key, val in extra.items():
        if key in _LOGRECORD_RESERVED or key in _ANTE_RESERVED:
            continue
        cleaned[key] = val
    return cleaned


def _safe_make_record(
    self: logging.Logger,
    name: str,
    level: int,
    fn: str,
    lno: int,
    msg: object,
    args: Any,
    exc_info: Any,
    func: str | None = None,
    extra: Mapping[str, object] | None = None,
    sinfo: str | None = None,
) -> logging.LogRecord:
    """``Logger.makeRecord`` 대체 구현."""
    return logging.Logger.makeRecord(
        self,
        name,
        level,
        fn,
        lno,
        msg,
        args,
        exc_info,
        func,
        _sanitize_extra(extra),
        sinfo,
    )


class AnteLogger(logging.Logger):
    """예약 키 안전 처리 Logger."""

    def makeRecord(  # noqa: N802
        self,
        name: str,
        level: int,
        fn: str,
        lno: int,
        msg: object,
        args: Any,
        exc_info: Any,
        func: str | None = None,
        extra: Mapping[str, object] | None = None,
        sinfo: str | None = None,
    ) -> logging.LogRecord:
        return _safe_make_record(
            self, name, level, fn, lno, msg, args, exc_info, func, extra, sinfo
        )


def install_safe_logger() -> None:
    """전역 Logger 클래스를 ``AnteLogger`` 로 등록한다.

    - 이후 ``logging.getLogger(name)`` 호출은 ``AnteLogger`` 인스턴스를 반환.
    - root logger 는 별도 ``RootLogger`` 인스턴스이므로 ``makeRecord`` 를
      바운드 메서드로 직접 교체한다.
    - 이미 캐시된 logger 들은 ``manager.loggerDict`` 에 남아있으므로 그들도
      같은 방식으로 교체한다.

    재호출해도 안전하다(멱등).
    """
    logging.setLoggerClass(AnteLogger)

    logging.root.makeRecord = _safe_make_record.__get__(  # type: ignore[method-assign]
        logging.root, type(logging.root)
    )

    for existing in logging.Logger.manager.loggerDict.values():
        if isinstance(existing, logging.Logger) and not isinstance(
            existing, AnteLogger
        ):
            existing.makeRecord = _safe_make_record.__get__(  # type: ignore[method-assign]
                existing, type(existing)
            )
