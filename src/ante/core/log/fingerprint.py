"""Exception fingerprint 생성 유틸리티."""

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
    """
    if exc_tb is None:
        return f"{exc_type.__name__}@{logger_name}"

    ante_frames: list[tuple[str, str]] = []
    tb: TracebackType | None = exc_tb
    while tb is not None:
        frame = tb.tb_frame
        module = frame.f_globals.get("__name__", "")
        if module.startswith("ante."):
            ante_frames.append((module, frame.f_code.co_name))
        tb = tb.tb_next

    if ante_frames:
        module, func = ante_frames[-1]
        return f"{exc_type.__name__}@{module}:{func}"

    return f"{exc_type.__name__}@{logger_name}"
