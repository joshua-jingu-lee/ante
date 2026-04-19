"""Reserved-key 를 안전하게 처리하는 Logger 서브클래스.

stdlib ``Logger.makeRecord()`` 는 ``extra`` 의 키가 ``LogRecord`` 속성과
충돌하면 ``KeyError("Attempt to overwrite ... in LogRecord")`` 를 던진다.
그러나 ``docs/specs/logging/03-json-schema.md`` §예약어 처리 는 표준 필드
(``ts``, ``level``, ``logger``, ``msg``, ``env``, ``exc``) 가 ``extra=`` 로
주입되어도 무시되어야 한다고 규정한다.

즉 formatter 단계의 필터링은 너무 늦다 — ``msg`` 같은 LogRecord 생성자가
직접 설정하는 속성은 ``makeRecord`` 단계에서 KeyError 가 먼저 난다.
이 모듈은 makeRecord 단계에서 위험 키를 선제적으로 제거해 호출자의
실수로부터 로그 구조를 보호한다.
"""

from __future__ import annotations

import logging
from typing import Any

from ._record_keys import ANTE_RESERVED as _ANTE_RESERVED
from ._record_keys import LOGRECORD_ATTRS as _LOGRECORD_RESERVED


def _sanitize_extra(extra: dict[str, Any] | None) -> dict[str, Any] | None:
    """예약 키 충돌을 제거한 extra dict 반환.

    - LogRecord 속성과 겹치는 키(``msg``, ``args``, ``name`` 등): 제거
      (formatter 가 표준 값을 생성한다).
    - Ante 예약 키 중 LogRecord 속성이 아닌 키(``ts``, ``env``, ``exc`` 등):
      제거 (formatter 가 표준 값을 생성한다).

    제거 대신 ``extra`` 하위로 옮기지 않는다 — 호출자의 실수를 무시하는 것이
    스펙 동작이다.
    """
    if not extra:
        return extra
    cleaned: dict[str, Any] = {}
    for key, val in extra.items():
        if key in _LOGRECORD_RESERVED or key in _ANTE_RESERVED:
            # 무시 (스펙: 호출자 실수로부터 로그 구조 보호)
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
    extra: dict[str, Any] | None = None,
    sinfo: str | None = None,
) -> logging.LogRecord:
    """``Logger.makeRecord`` 대체 구현.

    ``extra`` 의 위험 키를 선제 정규화한 뒤 stdlib 원본 구현에 위임한다.

    클래스 상속이 아니라 bound-method 교체 방식도 지원하기 위해 평범한
    함수로 정의한다 (``super()`` 는 서브클래스 mapping 에 의존하므로
    bound-method 교체 시 ``TypeError`` 가 발생한다).
    """
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

    def makeRecord(  # noqa: N802 — stdlib 메서드 오버라이드
        self,
        name: str,
        level: int,
        fn: str,
        lno: int,
        msg: object,
        args: Any,
        exc_info: Any,
        func: str | None = None,
        extra: dict[str, Any] | None = None,
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

    # root logger 의 makeRecord 를 patch — 별도 RootLogger 인스턴스라
    # setLoggerClass 만으로는 교체되지 않는다.
    logging.root.makeRecord = _safe_make_record.__get__(  # type: ignore[method-assign]
        logging.root, type(logging.root)
    )

    # 이미 만들어진 logger 들도 patch (Logger 인스턴스만 — PlaceHolder 제외).
    # AnteLogger 인스턴스는 makeRecord 를 이미 오버라이드하므로 건너뛴다.
    for existing in logging.Logger.manager.loggerDict.values():
        if isinstance(existing, logging.Logger) and not isinstance(
            existing, AnteLogger
        ):
            existing.makeRecord = _safe_make_record.__get__(  # type: ignore[method-assign]
                existing, type(existing)
            )
