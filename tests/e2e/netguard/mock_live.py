"""e2e 하위 프로세스에서 가상 전용 집합을 ``원래 집합 - {"mock"}``으로 다시 묶는다.

``sitecustomize``가 하네스의 환경 변수를 볼 때만 이 모듈을 import한다. 계좌 서비스는
import 때 집합을 자기 이름으로 묶으므로, 원래 집합을 묶은 ``ante.*`` 모듈의 이름을 모두
다시 묶는다. 판정 함수가 ``(mock, live)`` 계좌를 더는 거부하지 않을 때만 표지 파일에
pid를 남긴다. 어느 단계든 실패하면 제품의 거부가 그대로 남는다(fail-closed).
"""

from __future__ import annotations

import os
import sys

from ante.account import presets, service
from ante.account.models import Account, TradingMode

MARKER_ENV = "ANTE_E2E_MOCK_LIVE_MARKER"
OPENED_TYPE = "mock"

_original = presets.VIRTUAL_ONLY_BROKER_TYPES
_opened = _original - {OPENED_TYPE}

for _name, _module in list(sys.modules.items()):
    if _name != "ante" and not _name.startswith("ante."):
        continue
    if getattr(_module, "VIRTUAL_ONLY_BROKER_TYPES", None) is _original:
        _module.VIRTUAL_ONLY_BROKER_TYPES = _opened  # type: ignore[attr-defined]

service._reject_virtual_only_broker_in_live(
    Account(
        account_id="e2e-mock-live-probe",
        name="probe",
        exchange="TEST",
        currency="KRW",
        trading_mode=TradingMode.LIVE,
        broker_type=OPENED_TYPE,
    )
)

_marker_path = os.environ.get(MARKER_ENV)
if _marker_path:
    with open(_marker_path, "a", encoding="utf-8") as _fh:
        _fh.write(f"{os.getpid()}\n")
