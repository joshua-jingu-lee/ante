"""Contract vocabulary SSOT."""

from __future__ import annotations

from typing import Literal

ContractKind = Literal["entity", "operation", "collection", "raw", "stream"]
"""Contract가 노출하는 result shape 종류."""

AuthMode = Literal["public", "authenticated", "scoped", "master"]
"""인증 요구 모드 vocabulary."""
