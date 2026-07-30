"""UTC ISO 8601 직렬화 / 압축 날짜 변환 helper.

Python ``datetime.isoformat()``은 UTC offset을 ``+00:00``으로 직렬화하므로,
응답 표면에서는 본 helper로 ``Z`` suffix로 통일한다 (Refs #1360).

Refs #2412: 공개 표면(CLI 옵션 / IPC args)의 ISO ``YYYY-MM-DD`` 를 broker
어댑터 경계의 압축 ``YYYYMMDD`` 로 바꾸는 :func:`iso_to_kis_date` 를 함께
보유한다. CLI(`ante.cli.commands.broker`)와 IPC(`ante.ipc.registry`) 두
소비자가 **동일 함수 하나**를 호출하는 source chokepoint 이며, 어느 한쪽
레이어에 두면 반대쪽이 역방향 import 를 강요받으므로 레이어 중립인 본
모듈이 소유한다.
"""

from __future__ import annotations

import re
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


class InvalidIsoDateError(ValueError):
    """ISO ``YYYY-MM-DD`` 형식/캘린더 위반 (Refs #2412).

    ``code`` class attribute 로 안정 코드를 보유한다. IPC server 의
    ``getattr(e, "code", "EXECUTION_ERROR")`` (``src/ante/ipc/server.py:559``)
    와 CLI ``emit_cli_error`` 의 ``.code`` fallback 이 이 값을 그대로
    surface 하므로, invalid 날짜가 ``EXECUTION_ERROR`` 로 접히지 않는다.
    코드 값은 #1633 SSOT(``InvalidAccountIdError.code``)와 동일한
    ``VALIDATION_ERROR`` 를 재사용하며 신규 코드를 도입하지 않는다.
    """

    code = "VALIDATION_ERROR"


# strict ``YYYY-MM-DD`` (zero-padded 10자). ``ante.cli._validators._ISO_DATE_RE``
# 와 동일 정책 — CLI click callback 이 이미 거른 값이 정상 경로지만, 본 helper
# 는 CLI 를 우회하는 IPC 직접 호출에도 같은 strictness 를 적용한다.
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def iso_to_kis_date(value: str | None) -> str | None:
    """공개 표면 ISO ``YYYY-MM-DD`` → broker 경계 압축 ``YYYYMMDD`` (Refs #2412).

    **왜 chokepoint 인가**: ``KISDomesticAdapter.get_order_history``
    (``src/ante/broker/kis.py``)의 3개월 경계 판정은
    ``start_date >= cutoff`` **문자열 사전순 비교**다. ISO 문자열이 변환 없이
    새면 ``'2026-07-01' >= '20260429'`` 가 무조건 ``False`` 가 되어
    (``'-'`` 0x2D < ``'4'`` 0x34) (i) 3개월 이내인데 ``before``(``*9215R``)
    분기가 오선택되고 (ii) ``INQR_STRT_DT=2026-07-01`` malformed 값이 KIS 로
    전송된다. **예외도 경고도 발생하지 않는다.** 따라서 어댑터 호출 직전
    **모든 경로**(IPC 핸들러 / CLI 직접 폴백)가 본 함수를 통과해야 한다.

    Args:
        value: ISO ``YYYY-MM-DD`` 문자열 또는 ``None``.

    Returns:
        압축 ``YYYYMMDD`` 문자열. ``value`` 가 ``None`` 이면 ``None``
        (옵션 미지정 분기 보존 — 어댑터 기본값 산출에 위임한다).

    Raises:
        InvalidIsoDateError: regex mismatch 또는 존재하지 않는 캘린더 날짜.
            이미 ``YYYYMMDD`` 인 값(``"20260701"``)도 거부한다 — 공개 표면의
            날짜 어휘는 ISO 단일이며, 압축형 우회 입력을 통과시키면 표면
            어휘가 조용히 이중화된다.
    """
    if value is None:
        return None
    if not isinstance(value, str) or not _ISO_DATE_RE.fullmatch(value):
        msg = f"{value!r}은(는) YYYY-MM-DD 형식이어야 합니다 (zero-padded)."
        raise InvalidIsoDateError(msg)
    try:
        datetime.strptime(value, "%Y-%m-%d")  # noqa: DTZ007 — date-only 검증
    except ValueError as exc:
        msg = f"{value!r}은(는) 유효한 달력 날짜가 아닙니다."
        raise InvalidIsoDateError(msg) from exc
    return value.replace("-", "")


__all__ = ["InvalidIsoDateError", "format_utc", "iso_to_kis_date"]
