"""Exception fingerprint 생성 유틸리티.

감시 에이전트가 "같은 근본 원인의 반복 발생"을 묶기 위해 사용하는 안정
식별자다. 라인번호에 의존하지 않고 리팩터링에 저항적인 ``module:function``
단위 해상도를 사용한다.

자세한 규칙은 ``docs/specs/logging/04-fingerprint.md`` 참조.
"""

from __future__ import annotations

from types import TracebackType


def compute_fingerprint(
    exc_type: type,
    exc_tb: TracebackType | None,
    logger_name: str,
) -> str:
    """Exception fingerprint 문자열을 생성한다.

    형식은 ``{exception class}@{최근 ante.* 프레임 module:function}``이다.
    traceback 체인을 오래된 호출 → 최근 호출 순으로 순회하면서 ``f_globals['__name__']``
    이 ``ante.`` 으로 시작하는 프레임을 수집한다. 가장 최근(= 가장 깊은) 프레임을
    선택한다. 해당 프레임이 없으면 ``{exception class}@{logger_name}`` 으로 폴백한다.

    파일 경로 대신 Python이 설정한 ``__name__`` 을 사용하므로 설치 경로나
    체크아웃 경로에 독립적이다.

    Args:
        exc_type: 발생한 예외의 클래스.
        exc_tb: 예외의 traceback. ``None``이면 logger 이름으로 폴백한다.
        logger_name: 폴백에 사용할 logger 이름.

    Returns:
        Fingerprint 문자열.
    """
    if exc_tb is None:
        return f"{exc_type.__name__}@{logger_name}"

    # 오래된 → 최근 순 순회, ante.* 프레임 수집
    ante_frames: list[tuple[str, str]] = []
    tb = exc_tb
    while tb is not None:
        frame = tb.tb_frame
        module = frame.f_globals.get("__name__", "")
        if module == "ante" or module.startswith("ante."):
            ante_frames.append((module, frame.f_code.co_name))
        tb = tb.tb_next

    if ante_frames:
        # 가장 최근 = 리스트의 마지막 원소
        module, func = ante_frames[-1]
        return f"{exc_type.__name__}@{module}:{func}"

    return f"{exc_type.__name__}@{logger_name}"
