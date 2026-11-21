"""Contract vocabulary SSOT."""

from __future__ import annotations

from typing import Literal

ContractKind = Literal["entity", "operation", "collection", "raw", "stream"]
"""Contract가 노출하는 result shape 종류."""

EnvelopeForm = Literal["standard", "raw_legacy"]
"""응답 envelope 형태. ``raw_legacy``는 후방 호환용."""

AuthMode = Literal["public", "authenticated", "scoped", "master"]
"""인증 요구 모드 vocabulary."""
