"""CLI Click option callback validators."""

from __future__ import annotations

import math
import re
from datetime import date, datetime
from typing import TYPE_CHECKING

import click

if TYPE_CHECKING:
    from ante.cli.formatter import OutputFormatter


_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def validate_iso_date(
    ctx: click.Context | None,
    param: click.Parameter | None,
    value: str | None,
) -> str | None:
    """Click callback: strict ``YYYY-MM-DD`` ISO date validator.

    ``None`` 입력은 그대로 ``None``을 반환한다 (옵션 미지정 분기 보존).

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

    ``None`` 입력은 그대로 ``None``을 반환한다 (옵션 미지정 분기 보존).

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

    :func:`validate_positive_finite_amount`와의 차이는 **0 허용 boundary**다.

    ``None`` 입력은 그대로 ``None``을 반환한다 (옵션 미지정 분기 보존).

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

    - ``from_value``/``to_value`` 한쪽 또는 양쪽이 ``None`` → 통과 (옵션
      미지정/한쪽만 지정 분기 보존).
    - 둘 다 not ``None`` & 둘 다 ``date.fromisoformat`` 파싱 성공 &
      ``from_date > to_date`` → ``fmt.error(code="INVALID_DATE_RANGE")`` 후
      ``SystemExit(1)``.
    - 그 외(파싱 실패 포함) → 통과.
    """
    if from_value is None or to_value is None:
        return
    try:
        from_date = date.fromisoformat(from_value)
        to_date = date.fromisoformat(to_value)
    except (ValueError, TypeError):
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

    에러 코드는 SSOT
    (``InvalidAccountIdError.code == "VALIDATION_ERROR"``)를 그대로 재사용하며
    신 코드를 도입하지 않는다.

    Raises:
        SystemExit: invalid account_id일 때 exit code 1로 종료.
    """
    from ante.account.errors import InvalidAccountIdError
    from ante.account.scoping import validate_new_account_id

    try:
        return validate_new_account_id(account_id, context=context)
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

    **omitted-vs-provided 계약**: ``bot list --account``는 ``--account`` 미지정
    (``account_id is None``) 시 전체 봇을 반환하는 동작을 보존해야 한다(omitted
    보존). 그 호출 표면은 ``account_id is not None``일 때만 본
    helper를 호출해 provided 값만 검증한다. 본 helper 자체는 ``None``도
    invalid로 거부하므로(``require_account_id`` 계약), omitted 분기를 보존할
    책임은 호출 표면에 있다. positional required arg(``account info``/
    ``account credentials``)는 omitted가 없어 전 입력을 본 helper로 검증한다.
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
