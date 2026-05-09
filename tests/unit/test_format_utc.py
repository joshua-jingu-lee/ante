"""``ante.core.time.format_utc`` 단위 테스트 (Refs #1360).

Web API와 IPC가 공유하는 UTC ISO 8601 직렬화 helper. SSOT는
``docs/specs/web-api/04-system-endpoints.md`` Kill Switch 응답에서 ``Z`` suffix를
요구한다. Python ``datetime.isoformat()``의 기본 ``+00:00``을 ``Z``로 치환한다.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from ante.core.time import format_utc


def test_format_utc_replaces_plus_zero_offset_with_z() -> None:
    dt = datetime(2026, 5, 8, 11, 33, 25, tzinfo=UTC)
    assert format_utc(dt) == "2026-05-08T11:33:25Z"


def test_format_utc_keeps_microseconds() -> None:
    dt = datetime(2026, 5, 8, 11, 33, 25, 123456, tzinfo=UTC)
    assert format_utc(dt) == "2026-05-08T11:33:25.123456Z"


def test_format_utc_does_not_contain_plus_offset() -> None:
    dt = datetime.now(UTC)
    result = format_utc(dt)
    assert "+00:00" not in result
    assert result.endswith("Z")


def test_format_utc_rejects_naive_datetime() -> None:
    """naive datetime은 UTC 보장이 불가능하므로 reject."""
    naive = datetime(2026, 5, 8, 11, 33, 25)
    with pytest.raises(ValueError):
        format_utc(naive)


def test_format_utc_rejects_non_utc_timezone() -> None:
    """다른 timezone offset은 reject (helper 이름이 ``format_utc``)."""
    kst = timezone(timedelta(hours=9))
    dt = datetime(2026, 5, 8, 20, 33, 25, tzinfo=kst)
    with pytest.raises(ValueError):
        format_utc(dt)
