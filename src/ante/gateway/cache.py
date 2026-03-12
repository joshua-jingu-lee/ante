"""ResponseCache — TTL 기반 응답 캐시."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any


@dataclass
class CacheEntry:
    """캐시 항목."""

    data: Any
    created_at: float
    ttl_seconds: float


class ResponseCache:
    """TTL 기반 응답 캐시. 동일 시세 조회 등 중복 API 호출 방지."""

    DEFAULT_TTL: dict[str, float] = {
        "price": 5,
        "ohlcv": 60,
        "balance": 30,
        "positions": 30,
    }

    def __init__(self) -> None:
        self._cache: dict[str, CacheEntry] = {}

    def get(self, key: str) -> Any | None:
        """캐시 조회. 만료 시 None."""
        entry = self._cache.get(key)
        if entry is None:
            return None
        if time.monotonic() - entry.created_at > entry.ttl_seconds:
            del self._cache[key]
            return None
        return entry.data

    def set(self, key: str, data: Any, ttl: float | None = None) -> None:
        """캐시 저장."""
        self._cache[key] = CacheEntry(
            data=data,
            created_at=time.monotonic(),
            ttl_seconds=ttl or 30,
        )

    def make_key(self, endpoint: str, params: dict | None = None) -> str:
        """요청을 캐시 키로 변환."""
        param_str = "&".join(f"{k}={v}" for k, v in sorted((params or {}).items()))
        return f"{endpoint}?{param_str}"

    def invalidate(self, pattern: str = "") -> None:
        """패턴에 매칭되는 캐시 무효화. 빈 문자열이면 전체 초기화."""
        if not pattern:
            self._cache.clear()
        else:
            keys_to_delete = [k for k in self._cache if pattern in k]
            for k in keys_to_delete:
                del self._cache[k]

    @property
    def size(self) -> int:
        """캐시 항목 수."""
        return len(self._cache)
