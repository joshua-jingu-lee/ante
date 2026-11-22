"""테스트가 등록에 주는 요청 모델.

등록은 ``request_model``을 반드시 받는다(#2683 ⑧). 인자 없이 부르는 픽스처
명령은 이 모델로 등록한다.
"""

from __future__ import annotations

from ante.ipc.requests import IPCRequest


class NoArgsRequest(IPCRequest):
    """인자가 없는 픽스처 명령의 요청 모델."""
