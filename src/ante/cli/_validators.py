"""CLI Click option callback validators.

Web API의 ``src/ante/web/utils/date_params.py`` strict ISO date validator와
동일한 패턴(regex fullmatch 선검사 + ``datetime.strptime`` calendar parse)을
CLI ingress에도 적용하기 위한 헬퍼 모음. Click의 ``callback=`` 훅에 끼워서
invalid 입력을 ``click.BadParameter``로 거부한다.

오라클 A7 finding(#1513): CLI ``audit list --from-date/--to-date``와
``treasury snapshot --date/--from/--to``가 ``not-a-date`` 같은 invalid 입력을
exit 0으로 처리하여 빈 결과/없는 snapshot이 실제 데이터 부재와 구별되지
않는 ingress drift가 있었다. 본 모듈이 그 drift를 닫는다.
"""

from __future__ import annotations

import math
import re
from datetime import datetime

import click

# Web API helper(`src/ante/web/utils/date_params.py:56`)와 동일한 strict
# ``YYYY-MM-DD`` (zero-padded 10자) 정규식. ``datetime.strptime`` 단독은
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


__all__ = ["validate_iso_date", "validate_positive_finite_amount"]
