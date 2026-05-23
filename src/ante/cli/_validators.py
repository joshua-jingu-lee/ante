"""CLI Click option callback validators.

Regex fullmatch 선검사 + ``datetime.strptime`` calendar parse를 CLI ingress에
적용하기 위한 헬퍼 모음. Click의 ``callback=`` 훅에 끼워서 invalid 입력을
``click.BadParameter``로 거부한다.

오라클 A7 finding(#1513): CLI ``audit list --from-date/--to-date``와
``treasury snapshot --date/--from/--to``가 ``not-a-date`` 같은 invalid 입력을
exit 0으로 처리하여 빈 결과/없는 snapshot이 실제 데이터 부재와 구별되지
않는 ingress drift가 있었다. 본 모듈이 그 drift를 닫는다.
"""

from __future__ import annotations

import math
import re
from datetime import date, datetime
from typing import TYPE_CHECKING

import click

if TYPE_CHECKING:
    from ante.cli.formatter import OutputFormatter

# `require_account_id`가 raise하는 `InvalidAccountIdError`에 대응하는 에러 코드.
# #1633 선결정으로 `InvalidAccountIdError.code == "VALIDATION_ERROR"`가 SSOT로
# 고정됐다(`src/ante/account/errors.py:68-77`). 본 모듈은 그 코드를 재사용만
# 하며 신 코드를 도입하지 않는다.

# Strict ``YYYY-MM-DD`` (zero-padded 10자) 정규식. ``datetime.strptime`` 단독은
# ``2026-5-1``이나 ``2026-05-1`` 같은 non-zero-padded 입력을 silently 통과
# 시키므로 정규식 선검사로 1차 차단한다.
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def validate_iso_date(
    ctx: click.Context | None,
    param: click.Parameter | None,
    value: str | None,
) -> str | None:
    """Click callback: strict ``YYYY-MM-DD`` ISO date validator.

    검증은 2단계로 이뤄진다:

    1. 정규식 ``^\\d{4}-\\d{2}-\\d{2}$`` ``fullmatch`` — strict 10자
       zero-padded만 허용. non-zero-padded month/day(``2026-5-1``),
       short year, wrong delimiter(``2026/05/01``), trailing whitespace
       등을 1차 차단한다.
    2. ``datetime.strptime(value, "%Y-%m-%d")`` — 정규식을 통과한 입력 중
       존재하지 않는 캘린더 날짜(``2026-13-01``, ``2026-02-30``,
       ``2026-02-29`` (평년))를 거부한다.

    ``None`` 입력은 그대로 ``None``을 반환한다 (옵션 미지정 분기 보존).
    invalid 입력은 ``click.BadParameter``로 raise되어 click 표준 경로에서
    text stderr + exit 2로 변환된다.

    Args:
        ctx: Click 컨텍스트 (``click.option(callback=...)`` 인자).
        param: Click 파라미터 메타데이터 (``click.option(callback=...)`` 인자).
        value: 사용자가 입력한 원시 문자열, 또는 ``None``.

    Returns:
        검증된 ``YYYY-MM-DD`` 문자열을 그대로 반환, 또는 ``None``
        (입력이 ``None``일 때).

    Raises:
        click.BadParameter: regex mismatch 또는 calendar invalid.
    """
    if value is None:
        return None
    if not _ISO_DATE_RE.fullmatch(value):
        raise click.BadParameter(
            f"{value!r}은(는) YYYY-MM-DD 형식이어야 합니다 (zero-padded).",
            ctx=ctx,
            param=param,
        )
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise click.BadParameter(
            f"{value!r}은(는) 유효한 달력 날짜가 아닙니다.",
            ctx=ctx,
            param=param,
        ) from exc
    return value


def validate_positive_finite_amount(
    ctx: click.Context | None,
    param: click.Parameter | None,
    value: float | None,
) -> float | None:
    """Click callback: 양수 finite float 검증 (NaN/Infinity/0/음수 거부).

    오라클 A7 finding(#1517): ``treasury allocate``/``deallocate``의 ``amount``
    인자가 ``type=float``만 갖춰 Python ``float('nan')``/``float('inf')``/0/
    음수도 그대로 통과시키고 IPC layer까지 비정상 numeric을 전파하던 ingress
    drift를 닫는다. 본 callback이 그 drift를 닫는다.

    검증은 두 단계:

    1. ``math.isnan(value) or math.isinf(value)`` — NaN/±Infinity 거부.
    2. ``value <= 0`` — 0과 음수 거부.

    ``None`` 입력은 그대로 ``None``을 반환한다 (옵션 미지정 분기 보존).
    invalid 입력은 ``click.BadParameter``로 raise되어 click 표준 경로에서
    text stderr + exit 2로 변환된다. ``--format json`` 모드에서도 click 표준
    경로를 따르므로 stderr는 text다 (JSON envelope 표준화는 Non-Goals).

    Args:
        ctx: Click 컨텍스트 (``click.argument(callback=...)`` 인자).
        param: Click 파라미터 메타데이터 (``click.argument(callback=...)`` 인자).
        value: 사용자가 입력한 float, 또는 ``None``.

    Returns:
        검증된 float을 그대로 반환, 또는 ``None`` (입력이 ``None``일 때).

    Raises:
        click.BadParameter: NaN/±Infinity 또는 0/음수.
    """
    if value is None:
        return None
    if math.isnan(value) or math.isinf(value):
        raise click.BadParameter(
            f"{value!r}은(는) finite number여야 합니다 (NaN/Infinity 거부).",
            ctx=ctx,
            param=param,
        )
    if value <= 0:
        raise click.BadParameter(
            f"{value!r}은(는) 양수여야 합니다.",
            ctx=ctx,
            param=param,
        )
    return value


def validate_nonnegative_finite_amount(
    ctx: click.Context | None,
    param: click.Parameter | None,
    value: float | None,
) -> float | None:
    """Click callback: 0 이상 finite float 검증 (NaN/Infinity/음수 거부).

    오라클 A7 finding(#1517 — ``treasury set-balance`` amount): ``type=float``만
    갖춰 ``float('nan')``/``float('inf')``/음수가 그대로 통과되던 ingress drift를
    닫는다. 오라클 A7 finding(#1723 — ``account create
    --market-order-reserve-buffer-rate``)도 동일 invariant를 요구하며, 본 SSOT는
    두 호출 표면 공유 callback이다.

    :func:`validate_positive_finite_amount`와의 차이는 **0 허용 boundary**다.
    ``Account.market_order_reserve_buffer_rate``는 ``docs/specs/account/03-data-
    model.md:55,147``에서 ``Decimal("0")`` 기본값을 명시하고 있어 0을 정상값으로
    수용해야 한다 (#1333 cold-path structural field).

    검증은 두 단계:

    1. ``math.isnan(value) or math.isinf(value)`` — NaN/±Infinity 거부.
    2. ``value < 0`` — 음수 거부.

    ``None`` 입력은 그대로 ``None``을 반환한다 (옵션 미지정 분기 보존).
    invalid 입력은 ``click.BadParameter``로 raise되어 click 표준 경로에서
    text stderr + exit 2로 변환된다. ``--format json`` 모드에서는
    ``AuthenticatedGroup.main`` middleware(``src/ante/cli/middleware.py:561-581``)가
    UsageError를 ``CLI_USAGE_ERROR`` JSON envelope + exit 1로 변환한다.

    Args:
        ctx: Click 컨텍스트 (``click.option(callback=...)`` 인자).
        param: Click 파라미터 메타데이터 (``click.option(callback=...)`` 인자).
        value: 사용자가 입력한 float, 또는 ``None``.

    Returns:
        검증된 float을 그대로 반환, 또는 ``None`` (입력이 ``None``일 때).

    Raises:
        click.BadParameter: NaN/±Infinity 또는 음수.
    """
    if value is None:
        return None
    if math.isnan(value) or math.isinf(value):
        raise click.BadParameter(
            f"{value!r}은(는) finite number여야 합니다 (NaN/Infinity 거부).",
            ctx=ctx,
            param=param,
        )
    if value < 0:
        raise click.BadParameter(
            f"{value!r}은(는) 0 이상이어야 합니다.",
            ctx=ctx,
            param=param,
        )
    return value


def reject_inverted_date_range(
    from_value: str | None,
    to_value: str | None,
    fmt: OutputFormatter,
    *,
    from_label: str = "시작일",
    to_label: str = "종료일",
) -> None:
    """공유 date-only 헬퍼: ``from > to`` inverted range를 거부한다.

    오라클 A7 finding(#1597): ``audit list``/``trade list``/
    ``treasury snapshot``/``report performance --period daily`` 4개 read/report
    명령이 inverted date range(시작일 > 종료일)를 non-zero가 아니라 exit 0 빈
    결과로 처리하여 실제 데이터 부재와 구별되지 않던 ingress drift가 있었다.
    ``backtest run``(``backtest.py:72-77``)은 이미 ``INVALID_DATE_RANGE`` +
    ``SystemExit(1)``로 거부하고 있으며, 본 헬퍼는 그 메시지 톤·종료 코드와
    동형으로 나머지 4곳에 일괄 적용해 drift를 닫는다.

    **date-only 계약**: 4개 명령의 date 옵션은 전부 기존
    :func:`validate_iso_date`(``_validators.py:62-78``)가 strict
    ``YYYY-MM-DD``로 검증·정규화한 뒤 본 헬퍼에 도달한다. 따라서 본 헬퍼는
    ``datetime.date.fromisoformat(value)`` **단일 타입**만 파싱한다
    (mixed date/datetime ``TypeError`` 차단). 형식 검증은 본 헬퍼의 책임이
    아니다 — invalid 형식은 ``validate_iso_date``의 ``click.BadParameter``
    경로에서 본 헬퍼 도달 전에 이미 거부된다. 방어적으로, 어떤 경로로 형식
    invalid가 들어오면 ``fromisoformat``이 ``ValueError``를 던지므로 그대로
    통과시켜 기존 click 표준 경로를 보존한다(형식 검증 책임을 넘지 않는다).

    동작:

    - ``from_value``/``to_value`` 한쪽 또는 양쪽이 ``None`` → 통과 (옵션
      미지정/한쪽만 지정 분기 보존).
    - 둘 다 not ``None`` & 둘 다 ``date.fromisoformat`` 파싱 성공 &
      ``from_date > to_date`` → ``fmt.error(code="INVALID_DATE_RANGE")`` 후
      ``SystemExit(1)``.
    - 그 외(파싱 실패 포함) → 통과.

    Args:
        from_value: 시작일 문자열(``YYYY-MM-DD``) 또는 ``None``.
        to_value: 종료일 문자열(``YYYY-MM-DD``) 또는 ``None``.
        fmt: ``get_formatter(ctx)``로 얻은 출력 포맷터. text/json 모드에 따라
            구조화된 에러를 출력한다.
        from_label: 에러 메시지의 시작일 라벨 (기본 ``"시작일"``).
        to_label: 에러 메시지의 종료일 라벨 (기본 ``"종료일"``).

    Raises:
        SystemExit: inverted range일 때 exit code 1로 종료.
    """
    if from_value is None or to_value is None:
        return
    try:
        from_date = date.fromisoformat(from_value)
        to_date = date.fromisoformat(to_value)
    except (ValueError, TypeError):
        # 형식 검증은 본 헬퍼 책임 아님 — validate_iso_date의 click 경로 보존.
        return
    if from_date > to_date:
        fmt.error(
            f"{from_label}({from_value})이(가) {to_label}({to_value}) 이후입니다.",
            code="INVALID_DATE_RANGE",
        )
        raise SystemExit(1)


def reject_invalid_new_account_id(
    account_id: str | None,
    fmt: OutputFormatter,
    *,
    context: str = "",
) -> str:
    """공유 helper: create-path 신규 ``account_id``를 service 진입 이전에 거부.

    오라클 #1724 finding(D follow-up — #1634 동형): cold-path
    ``account create``가 invalid ``account_id``(``default`` RESTRICTED,
    pattern 위반 ``bad_id``, ``""``/``None``)를 ``AccountService.create``
    SQL 진입 이전에 거부하지 않아 일부는 ``ACCOUNT_NOT_FOUND``로 오분류되고
    일부는 empty/``EXECUTION_ERROR``로 떨어지던 ingress drift가 있었다.
    본 helper가 그 drift를 닫는다.

    :func:`reject_invalid_account_id`와 byte-for-byte 동형이지만 내부
    delegate가 다르다 — :func:`ante.account.scoping.validate_new_account_id`
    (create-policy SSOT)를 호출하여 **형식 + RESTRICTED + INVALID_RUNTIME**
    세 단계를 한 번에 검사한다. ``require_account_id``(lookup-policy)와의
    차이는 RESTRICTED-aware라는 점이다 — ``test`` 같은 bootstrap seed id는
    lookup은 허용되지만 신규 생성은 금지된다.

    :func:`reject_invalid_account_id`와 마찬가지로
    :class:`ante.account.errors.InvalidAccountIdError`는 non-Click
    ``AccountError``이며, ``AuthenticatedGroup.main``
    (``src/ante/cli/middleware.py:568-596``)은 ``click.UsageError``/``Abort``만
    envelope 변환한다. 따라서 본 helper가 그 예외를 **명시적으로** catch해
    ``fmt.error(str(e), code=e.code)`` + ``SystemExit(1)``로 변환한다.
    에러 코드는 #1633 SSOT
    (``InvalidAccountIdError.code == "VALIDATION_ERROR"``)를 그대로 재사용하며
    신 코드를 도입하지 않는다.

    Args:
        account_id: 검증할 신규 account_id (또는 ``None``).
        fmt: ``get_formatter(ctx)``로 얻은 출력 포맷터. text/json 모드에 따라
            구조화된 에러를 출력한다.
        context: 호출 위치 식별자 (예: ``"cli.account.create"``). 현재
            ``validate_new_account_id``는 context를 사용하지 않지만 sibling
            helper 시그니처 정렬을 위해 보존한다.

    Returns:
        검증된 account_id. 호출 측 type narrow를 위해 ``str``로 반환된다.

    Raises:
        SystemExit: invalid account_id일 때 exit code 1로 종료.
    """
    from ante.account.errors import InvalidAccountIdError
    from ante.account.scoping import validate_new_account_id

    del context  # sibling 시그니처 정렬용 — validate_new_account_id가 사용하지 않음.
    try:
        return validate_new_account_id(account_id)
    except InvalidAccountIdError as e:
        fmt.error(str(e), code=e.code)
        raise SystemExit(1) from e


def reject_invalid_account_id(
    account_id: str | None,
    fmt: OutputFormatter,
    *,
    context: str = "",
) -> str:
    """공유 helper: provided invalid ``account_id``를 lookup/filter 이전에 거부.

    오라클 #1623 finding(Split A — #1634): read-only account-scoped CLI
    (``account info``/``account credentials``/``bot list --account``)가 invalid
    ``account_id``(``default``/``""``/패턴 위반)를 ``AccountService.get`` lookup
    이나 SQL filter 이전에 거부하지 않아, not-found 메시지로 오분류되거나
    exit 0 + empty success로 처리되던 ingress drift가 있었다. 본 helper가 그
    drift를 닫는다.

    내부적으로 :func:`ante.account.scoping.require_account_id`(account-id 계약
    SSOT)를 호출한다. ``require_account_id``가 raise하는
    :class:`ante.account.errors.InvalidAccountIdError`는 non-Click
    ``AccountError``이며, ``AuthenticatedGroup.main``
    (``src/ante/cli/middleware.py:568-596``)은 ``click.UsageError``/``Abort``만
    envelope 변환한다. 따라서 본 helper가 그 예외를 **명시적으로** catch해
    ``fmt.error(str(e), code="VALIDATION_ERROR")`` + ``SystemExit(1)``로
    변환한다(미catch 시 traceback/uncaught). 에러 코드는 #1633 SSOT
    (``InvalidAccountIdError.code == "VALIDATION_ERROR"``)를 ``e.code``로 그대로
    재사용하며 신 코드를 도입하지 않는다.

    **omitted-vs-provided 계약**: ``bot list --account``는 ``--account`` 미지정
    (``account_id is None``) 시 전체 봇을 반환하는 동작을 보존해야 한다(omitted
    보존, #1624 동형). 그 호출 표면은 ``account_id is not None``일 때만 본
    helper를 호출해 provided 값만 검증한다. 본 helper 자체는 ``None``도
    invalid로 거부하므로(``require_account_id`` 계약), omitted 분기를 보존할
    책임은 호출 표면에 있다. positional required arg(``account info``/
    ``account credentials``)는 omitted가 없어 전 입력을 본 helper로 검증한다.

    Args:
        account_id: 검증할 account_id (또는 ``None``).
        fmt: ``get_formatter(ctx)``로 얻은 출력 포맷터. text/json 모드에 따라
            구조화된 에러를 출력한다.
        context: ``require_account_id``에 전달할 호출 위치 식별자
            (예: ``"cli.account.info"``).

    Returns:
        검증된 account_id. 호출 측 type narrow를 위해 ``str``로 반환된다.

    Raises:
        SystemExit: invalid account_id일 때 exit code 1로 종료.
    """
    from ante.account.errors import InvalidAccountIdError
    from ante.account.scoping import require_account_id

    try:
        return require_account_id(account_id, context=context)
    except InvalidAccountIdError as e:
        fmt.error(str(e), code=e.code)
        raise SystemExit(1) from e


__all__ = [
    "reject_invalid_account_id",
    "reject_invalid_new_account_id",
    "reject_inverted_date_range",
    "validate_iso_date",
    "validate_nonnegative_finite_amount",
    "validate_positive_finite_amount",
]
