"""Contract vocabulary SSOT (#1822).

CLI command registry(#1815)와 IPC CommandSpec metadata(#1819) 양쪽이
공유하는 contract vocabulary의 단일 코드 SSOT.

본 모듈은 다음 3개 Literal type alias만 정의한다.

- ``ContractKind`` : contract가 노출하는 result shape 종류
- ``EnvelopeForm`` : 응답 envelope 형태
- ``AuthMode``     : 인증 요구 모드 vocabulary

중요한 정렬:

- ``raw_legacy``는 ``EnvelopeForm``에만 존재하며 ``ContractKind``에는
  포함되지 않는다. legacy raw JSON 출력은 CLI registry(#1815)가
  ``kind="raw"`` + ``envelope="raw_legacy"`` 조합으로 표현한다.
- ``AuthMode``는 CLI registry ``AuthContract.mode``(#1815)의 vocabulary이며,
  본 모듈은 auth enforcement를 바꾸지 않는다.

본 모듈은 runtime behavior를 가지지 않는다. enum/dataclass/helper/
validator 추가는 의도적으로 제외한다 -- 필요해지면 별도 이슈로 분리한다.
"""

from __future__ import annotations

from typing import Literal

ContractKind = Literal["entity", "operation", "collection", "raw", "stream"]
"""Contract가 노출하는 result shape 종류."""

EnvelopeForm = Literal["standard", "raw_legacy"]
"""응답 envelope 형태. ``raw_legacy``는 후방 호환용."""

AuthMode = Literal["public", "authenticated", "scoped", "master"]
"""인증 요구 모드 vocabulary."""
