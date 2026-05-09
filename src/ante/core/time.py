"""UTC ISO 8601 직렬화 helper.

SSOT: ``docs/specs/web-api/04-system-endpoints.md``의 Kill Switch 응답은
``changed_at``을 ``string (ISO 8601 UTC)``로 정의하며 ``Z`` suffix를 사용한다.
Python ``datetime.isoformat()``은 UTC offset을 ``+00:00``으로 직렬화하므로,
응답 표면에서는 본 helper로 ``Z`` suffix로 통일한다.

Web API (``ante.web.routes.system``)와 IPC registry
(``ante.ipc.registry``)는 동일한 Kill Switch envelope을 공유하므로 양쪽이
이 helper를 호출한다 (Refs #1360).
"""

from __future__ import annotations

from datetime import UTC, datetime


def format_utc(dt: datetime) -> str:
    """UTC ``datetime``을 ISO 8601 + ``Z`` suffix 문자열로 직렬화한다.

    Args:
        dt: tzinfo가 UTC인 ``datetime``. naive 또는 다른 timezone은 reject한다.

    Returns:
        ISO 8601 UTC 문자열 (suffix는 ``Z``).

    Raises:
        ValueError: ``dt``가 naive이거나 UTC가 아닌 경우.
    """
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) != UTC.utcoffset(dt):
        msg = (
            "format_utc는 UTC tzinfo가 명시된 datetime만 받는다. "
            f"got tzinfo={dt.tzinfo!r}"
        )
        raise ValueError(msg)
    return dt.isoformat().replace("+00:00", "Z")


__all__ = ["format_utc"]
