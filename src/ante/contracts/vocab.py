"""Contract vocabulary SSOT."""

from __future__ import annotations

from typing import Literal

ContractKind = Literal["envelope", "stream"]
"""CLI 계약의 성공 출력이 envelope인지 stream인지."""

AuthMode = Literal["public", "authenticated", "scoped", "master"]
"""인증 요구 모드 vocabulary."""
