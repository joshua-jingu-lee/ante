"""ISO date-only (``YYYY-MM-DD``) 쿼리/패스 파라미터 검증 헬퍼 (#1440).

Portfolio history (``GET /api/portfolio/history``)와 Treasury snapshots/
transactions (``GET /api/treasury/snapshots``, ``GET /api/treasury/snapshots/
{date}``, ``GET /api/treasury/transactions``)는 모두 ``YYYY-MM-DD`` 형태의
date-only 입력만 받는다. 그러나 본 PR 이전에는 임의 문자열
(``oracle-not-a-date``)도 200으로 통과하여 정상 데이터셋과 구분되지 않는
contract drift가 있었다.

본 모듈은 두 종류의 헬퍼를 제공한다:

* :func:`validate_iso_date_only` — 입력을 ``YYYY-MM-DD`` 표준 형식으로 검증
  하고 그대로 돌려준다. 캘린더상 존재하지 않는 날짜(``2026-13-32``)도 거부.
  ``treasury_daily_snapshots.snapshot_date`` 컬럼이 ``YYYY-MM-DD`` 그대로
  저장되므로 portfolio history / treasury snapshots 라우트가 사용한다.

* :func:`validate_iso_date_param_for_sql_datetime` — 입력을 ``YYYY-MM-DD``로
  검증한 뒤, SQLite ``datetime('now')`` 포맷(``YYYY-MM-DD HH:MM:SS``)의
  boundary 문자열로 확장한다. ``treasury_transactions.created_at`` 컬럼은
  SQLite ``datetime('now')`` 기본값을 쓰므로 SQL 텍스트 비교가 정확한
  inclusive bound를 가지려면 boundary 확장이 필수다.

본 헬퍼는 ``ante.web.routes.bots._validate_iso_date_param``과 의도적으로
분리되어 있다. bot logs 페이지네이션은 ``EventHistoryStore``의 ISO 8601
datetime (``2026-05-13T12:00:00+00:00``) 텍스트 비교에 맞춘 별도 helper를
이미 가지며, 본 PR scope에서는 그 helper를 건드리지 않는다 (#1437 r1
finding 보존).
"""

from __future__ import annotations

from datetime import datetime

from fastapi import HTTPException

__all__ = [
    "validate_iso_date_only",
    "validate_iso_date_param_for_sql_datetime",
]


def _parse_iso_date_only(value: str, field: str) -> str:
    """``value``를 ``YYYY-MM-DD`` 캘린더 유효 date로 검증.

    ``datetime.strptime(..., "%Y-%m-%d")``는 비표준 포맷(``20260510``,
    ``2026-W19-1``)을 거부하고, 존재하지 않는 캘린더 날짜(``2026-13-32``,
    ``2026-02-30``)도 거부한다.

    Returns:
        검증된 ``YYYY-MM-DD`` 문자열 (``strftime("%Y-%m-%d")``로 재정규화).

    Raises:
        HTTPException(422): 파싱 실패 또는 캘린더 invalid.
    """
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=(f"invalid {field}: must be YYYY-MM-DD ({value!r}): {exc}"),
        ) from exc
    return parsed.strftime("%Y-%m-%d")


def validate_iso_date_only(value: str | None, field: str) -> str | None:
    """``value``가 ISO date-only (``YYYY-MM-DD``)인지 검증하고 그대로 반환.

    ``None`` 입력은 그대로 ``None``을 반환한다 (caller의 default 분기 보존).
    캘린더상 존재하지 않는 날짜도 422로 거부된다 (e.g. ``2026-13-32``,
    ``2026-02-30``).

    Args:
        value: 입력 문자열 또는 ``None``.
        field: 에러 메시지에 사용할 필드명 (예: ``start_date``, ``date``).

    Returns:
        검증된 ``YYYY-MM-DD`` 문자열, 또는 ``None`` (입력이 ``None``일 때).

    Raises:
        HTTPException(422): 파싱 실패 또는 캘린더 invalid.
    """
    if value is None:
        return None
    return _parse_iso_date_only(value, field)


def validate_iso_date_param_for_sql_datetime(
    value: str | None,
    field: str,
    *,
    end_of_day: bool = False,
) -> str | None:
    """``value``를 ISO date-only로 검증한 뒤 SQLite ``datetime`` boundary로 확장.

    ``treasury_transactions.created_at`` 컬럼은 ``TEXT DEFAULT
    (datetime('now'))``로 정의되어 SQLite ``YYYY-MM-DD HH:MM:SS`` 포맷
    (T separator 없음, microseconds 없음, tz suffix 없음)을 가진다. SQL
    텍스트 비교 ``created_at >= ?``가 inclusive bound로 동작하려면 입력을
    같은 포맷의 boundary 문자열로 확장해야 한다.

    * ``end_of_day=False`` (기본): ``YYYY-MM-DD 00:00:00`` — start_date용
      lower bound (그 날 00:00부터 포함).
    * ``end_of_day=True``: ``YYYY-MM-DD 23:59:59`` — end_date용 upper bound
      (그 날 23:59:59까지 포함). SQLite ``datetime('now')`` 저장값은
      microseconds를 갖지 않으므로 ``23:59:59``로 충분하다.

    Args:
        value: 입력 문자열 또는 ``None``.
        field: 에러 메시지에 사용할 필드명.
        end_of_day: ``True``면 boundary를 ``23:59:59``로, 그 외엔
            ``00:00:00``으로 확장.

    Returns:
        SQLite datetime boundary 문자열 (``YYYY-MM-DD HH:MM:SS``), 또는
        ``None`` (입력이 ``None``일 때).

    Raises:
        HTTPException(422): 파싱 실패 또는 캘린더 invalid.
    """
    if value is None:
        return None
    normalized = _parse_iso_date_only(value, field)
    suffix = " 23:59:59" if end_of_day else " 00:00:00"
    return normalized + suffix
