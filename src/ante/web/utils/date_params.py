"""ISO date-only (``YYYY-MM-DD``) 쿼리/패스 파라미터 검증 헬퍼 (#1440).

Portfolio history (``GET /api/portfolio/history``)와 Treasury snapshots/
transactions (``GET /api/treasury/snapshots``, ``GET /api/treasury/snapshots/
{date}``, ``GET /api/treasury/transactions``)는 모두 ``YYYY-MM-DD`` 형태의
date-only 입력만 받는다. 그러나 본 PR 이전에는 임의 문자열
(``oracle-not-a-date``)도 200으로 통과하여 정상 데이터셋과 구분되지 않는
contract drift가 있었다.

본 모듈은 세 종류의 헬퍼를 제공한다:

* :func:`validate_iso_date_only` — 입력을 ``YYYY-MM-DD`` 표준 형식으로 검증
  하고 그대로 돌려준다. 캘린더상 존재하지 않는 날짜(``2026-13-32``)도 거부.
  ``treasury_daily_snapshots.snapshot_date`` 컬럼이 ``YYYY-MM-DD`` 그대로
  저장되므로 portfolio history / treasury snapshots 라우트가 사용한다.

* :func:`validate_iso_date_param_for_sql_datetime` — 입력을 ``YYYY-MM-DD``로
  검증한 뒤, SQLite ``datetime('now')`` 포맷(``YYYY-MM-DD HH:MM:SS``)의
  boundary 문자열로 확장한다. ``treasury_transactions.created_at`` 컬럼은
  SQLite ``datetime('now')`` 기본값을 쓰므로 SQL 텍스트 비교가 정확한
  inclusive bound를 가지려면 boundary 확장이 필수다.

* :func:`reject_inverted_date_range` — 정규화된 start/end 값이 모두 not
  ``None``이고 ``start > end`` (불가능한 기간)이면 ``HTTPException(422)``로
  거부한다 (#1595, oracle A7). portfolio history / treasury transactions /
  treasury snapshots / bot logs 4개 read API가 inverted range를 400/422가
  아니라 200 empty로 silently 흡수하던 contract drift를 차단한다. start/end가
  각 endpoint 내에서 동일 타입(ISO ``YYYY-MM-DD`` str, SQLite boundary str,
  UTC-aware ``datetime``)이고 모두 ``>`` 비교가 시간 순서와 일치하므로 generic
  comparator 1개로 4곳을 모두 커버한다. 한쪽/양쪽이 ``None``(미지정)이면
  통과시켜 caller의 default 분기를 보존한다 — 검증 호출은 default 적용 **전**에
  배치해야 한다.

본 헬퍼는 ``ante.web.routes.bots._validate_iso_date_param``과 의도적으로
분리되어 있다. bot logs 페이지네이션은 ``EventHistoryStore``의 ISO 8601
datetime (``2026-05-13T12:00:00+00:00``) 텍스트 비교에 맞춘 별도 helper를
이미 가지며, 본 PR scope에서는 그 helper를 건드리지 않는다 (#1437 r1
finding 보존).

Codex r1 finding (#1440): ``datetime.strptime(value, "%Y-%m-%d")``는
``2026-5-1``이나 ``2026-05-1`` 같은 non-zero-padded month/day 입력도
정상 파싱한 뒤 ``strftime("%Y-%m-%d")``에서 ``2026-05-01``로 재정규화하여
silently 통과시킨다. spec와 path regex(``^\\d{4}-\\d{2}-\\d{2}$``)는 strict
10자 ``YYYY-MM-DD``만 허용하므로 query helper도 같은 strictness가 필요하다.
파싱 전에 정규식 검사를 추가해 non-zero-padded / 비표준 길이를 명시적으로
거부한다.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Protocol

from fastapi import HTTPException

__all__ = [
    "reject_inverted_date_range",
    "validate_iso_date_only",
    "validate_iso_date_param_for_sql_datetime",
]

# r1 fix (#1440): strict ``YYYY-MM-DD`` (zero-padded 10자) 정규식.
# ``datetime.strptime`` 이전 1차 차단으로 non-zero-padded (``2026-5-1``,
# ``2026-05-1``, ``2026-5-01``), short year (``26-05-01``), wrong delimiter
# (``2026/05/01``), trailing whitespace (``2026-05-01 ``) 등을 모두 거부한다.
# path 라우트의 ``Path(pattern=...)``와 동일한 strictness를 query helper도
# 갖도록 보장한다.
_ISO_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _parse_iso_date_only(value: str, field: str) -> str:
    """``value``를 ``YYYY-MM-DD`` 캘린더 유효 date로 검증.

    검증은 2단계:

    1. 정규식 ``^\\d{4}-\\d{2}-\\d{2}$`` — strict 10자 zero-padded만 허용.
       non-zero-padded month/day, short year, wrong delimiter, trailing
       whitespace 등을 1차 차단한다.
    2. ``datetime.strptime(..., "%Y-%m-%d")`` — 정규식을 통과한 입력 중
       존재하지 않는 캘린더 날짜(``2026-13-32``, ``2026-02-30``)를 거부.

    Returns:
        검증된 ``YYYY-MM-DD`` 문자열 (input value 그대로 — 정규식 통과
        시점에 이미 strict 포맷이므로 ``strftime`` 재정규화 불필요).

    Raises:
        HTTPException(422): 정규식 mismatch 또는 캘린더 invalid.
    """
    if not _ISO_DATE_PATTERN.fullmatch(value):
        raise HTTPException(
            status_code=422,
            detail=(
                f"invalid {field}: must be YYYY-MM-DD "
                f"(10 chars, zero-padded) ({value!r})"
            ),
        )
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=(f"invalid {field}: calendar invalid ({value!r}): {exc}"),
        ) from exc
    return value


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


class _Orderable(Protocol):
    """``>`` 비교가 가능한 값의 최소 구조 (generic comparator 제약).

    4개 endpoint가 정규화하는 타입은 ISO ``YYYY-MM-DD`` str, SQLite boundary
    str(``YYYY-MM-DD HH:MM:SS``), UTC-aware :class:`datetime` 셋이며 모두 같은
    타입끼리의 ``>`` 비교가 실제 시간 순서와 일치한다. 본 Protocol은 그
    공통 계약(``__gt__``)만 노출한다.

    ``other`` 인자는 :class:`typing.Any`로 둔다. typeshed의
    ``str.__gt__(self, value: str, /)``/``datetime.__gt__(self, value:
    datetime, /)``는 ``object``를 받지 않으므로, ``other: object``로 두면
    str/datetime이 본 Protocol을 구조적으로 만족하지 못해 mypy가 호출부
    (portfolio/treasury/bots)를 ``expected "None"``으로 거부한다 (#1595
    Codex r1). ``Any``는 모든 시그니처를 구조적으로 수용하므로 런타임
    동작을 바꾸지 않고 mypy ``src/`` 전체를 통과시킨다.
    """

    def __gt__(self, other: Any, /) -> bool: ...


def reject_inverted_date_range[T: _Orderable](
    start: T | None,
    end: T | None,
    *,
    start_field: str = "start_date",
    end_field: str = "end_date",
) -> None:
    """정규화된 ``start``/``end``가 inverted range면 ``HTTPException(422)``.

    4개 read API(portfolio history, treasury transactions, treasury
    snapshots, bot logs)는 FastAPI query 레벨에서 날짜 *형식*만 검증하고
    ``start_date > end_date`` 순서는 검증하지 않아, 불가능한 기간을 400/422가
    아니라 200 empty result로 silently 흡수했다 (#1595, oracle A7). 본 헬퍼는
    그 date-order invariant의 SSOT다.

    비교는 generic ``>`` 단 한 번이다. 각 endpoint가 start/end를 동일 타입으로
    정규화하고(ISO ``YYYY-MM-DD`` str / SQLite boundary str / UTC-aware
    :class:`datetime`) 그 타입의 ``>``가 실제 시간 순서와 일치하므로 (str은
    lexicographic, datetime은 native) 추가 파싱 없이 정확하다. 따라서
    호출부는 검증된/정규화된 값을 넘겨야 한다 (raw 입력 아님). bot logs처럼
    tz-aware datetime을 넘기는 경우 UTC-aware로 정규화된 뒤 비교되므로
    cross-offset 입력도 aware/naive ``TypeError`` 없이 실제 UTC 순서로
    판정된다.

    한쪽 또는 양쪽이 ``None``(사용자 미지정)이면 통과시킨다. 따라서 호출은
    각 endpoint의 default 적용 **이전**에 배치해야 미지정 케이스가 거부되지
    않고 기존 default 동작이 보존된다.

    Args:
        start: 정규화된 start 값 또는 ``None``.
        end: 정규화된 end 값 또는 ``None``.
        start_field: 에러 메시지에 사용할 start 필드명.
        end_field: 에러 메시지에 사용할 end 필드명.

    Raises:
        HTTPException(422): ``start``/``end``가 모두 not ``None``이고
            ``start > end`` (inverted range)일 때. detail에 두 필드명과 두
            값을 포함한다.
    """
    if start is None or end is None:
        return
    if start > end:
        raise HTTPException(
            status_code=422,
            detail=(
                f"invalid date range: {start_field} ({start!r}) must not be "
                f"after {end_field} ({end!r})"
            ),
        )
