"""요청 모델 검증 실패 메시지의 기대값을 만드는 도우미 하나 (#2683).

#2680이 메시지 형식을 바꾸면 이 한 곳만 고친다.
"""

from __future__ import annotations


def validation_message(command: str, *errors: tuple[str, str]) -> str:
    fields = ", ".join(f"{loc}({kind})" for loc, kind in errors)
    return f"{command} 인자 검증 실패: {fields}"
