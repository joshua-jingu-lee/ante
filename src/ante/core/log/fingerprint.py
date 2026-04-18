"""Exception fingerprint 생성 유틸리티.

감시 에이전트가 "같은 근본 원인의 반복 발생"을 묶기 위해 사용하는 안정
식별자다. 라인번호에 의존하지 않고 리팩터링에 저항적인 ``module:function``
단위 해상도를 사용한다.

자세한 규칙은 ``docs/specs/logging/04-fingerprint.md`` 참조.
"""

from __future__ import annotations

import re
import traceback
from types import TracebackType

_ANTE_MODULE_RE = re.compile(r"(ante/[^.]+)\.py$")


def compute_fingerprint(
    exc_type: type,
    exc_tb: TracebackType | None,
    logger_name: str,
) -> str:
    """Exception fingerprint 문자열을 생성한다.

    형식은 ``{exception class}@{최근 ante.* 프레임 module:function}``이다.
    스택을 최근 호출 → 먼 호출 순으로 순회하면서 모듈 경로가 ``ante/`` 접두어
    아래에 있는 첫 프레임을 선택한다. 해당 프레임이 없으면
    ``{exception class}@{logger_name}`` 으로 폴백한다.

    Args:
        exc_type: 발생한 예외의 클래스.
        exc_tb: 예외의 traceback. ``None``이면 logger 이름으로 폴백한다.
        logger_name: 폴백에 사용할 logger 이름.

    Returns:
        Fingerprint 문자열.
    """
    if exc_tb is None:
        return f"{exc_type.__name__}@{logger_name}"
    frames = traceback.extract_tb(exc_tb)
    for frame in reversed(frames):
        module = _module_path(frame.filename)
        if module:
            return f"{exc_type.__name__}@{module}:{frame.name}"
    return f"{exc_type.__name__}@{logger_name}"


def _module_path(filename: str) -> str | None:
    """파일 경로에서 ante 패키지 상대 경로를 추출하여 module 표기로 변환한다.

    예: ``/app/src/ante/broker/kis_stream.py`` → ``ante.broker.kis_stream``.
    ante 패키지 경로가 아니면 ``None``을 반환한다.
    """
    m = _ANTE_MODULE_RE.search(filename)
    if not m:
        return None
    return m.group(1).replace("/", ".")
