"""account_id query 파라미터의 runtime-invalid 거부 헬퍼 (#1624).

account-scoped Web **READ** API 표면(portfolio value/history, trades list,
treasury summary/transactions/snapshots, strategy performance, bots list)은
모두 ``account_id`` query 파라미터를 받는다. Account ID 계약
(``docs/specs/account/14-account-id-contract.md`` **"Runtime invalid (어떤
시점에도 거부)"**)은 ``None``/``""``/``"default"``/``ACCOUNT_ID_PATTERN`` 불일치
값을 account-scoped 진입점에서 **항상** 거부하도록 정의한다.

그러나 본 PR 이전에는 *제공된*-invalid ``account_id`` (``?account_id=default``,
``?account_id=bad_id``, ``?account_id=``)가 ingress에서 거부되지 않고
404(`계좌를 찾을 수 없습니다`)/500(`An unexpected error occurred.`)/200
(empty-success)로 흘렀다 (oracle A7 contract-drift, fingerprint
``46e7221b5bac``). 클라이언트가 malformed/fallback account_id를 genuine
not-found/successful-empty/server-failure와 구분할 수 없는 SSOT 계약 위반이다.

본 모듈은 그 read-API ingress invariant의 SSOT다. 비교는 SSOT helper
:func:`ante.account.scoping.is_invalid_account_id` 단 한 번이며, 422
``HTTPException``으로 변환된다 (``ante.web.errors``가 자동으로
``application/problem+json``, ``type=/errors/validation``으로 정규화).

#1218 경계 보존
~~~~~~~~~~~~~~~

``account_id`` **미지정**(query 파라미터 부재 → ``account_id is None``)은
#1218(Edge resolver)이 확정한 **all-account/단일-treasury 집계** 분기다.
본 가드는 ``None``을 통과시켜 그 분기 동작·응답 schema를 보존한다
(``account_id is not None and is_invalid_account_id(account_id)`` 조건).
*제공된* 빈 문자열(``?account_id=`` → ``account_id == ""``)은 미지정이
아니라 "Runtime invalid"이므로 422로 거부한다 (provided-empty ≠ omitted).

**valid-pattern but absent**(예 ``acc-9999``, 패턴 일치·미존재)는
``is_invalid_account_id``가 ``False``이므로 가드를 통과한다 — invalid-format/
fallback ↔ genuine not-found 분리가 본 가드의 핵심이며, 미존재 의미론은
각 엔드포인트의 기존 lookup(404 / 200 empty)이 그대로 처리한다.

본 모듈은 ``ante.web.utils.date_params``와 동일하게 의도적으로 ``ante.web.*``
+ ``ante.account.scoping`` SSOT 외 의존성을 갖지 않는다. service/DB/IPC
lifecycle 계약은 본 헬퍼 scope 외다 (라우트 ingress 한정, #1623 split 영역
별개).
"""

from __future__ import annotations

from fastapi import HTTPException

from ante.account.scoping import is_invalid_account_id

__all__ = [
    "reject_invalid_account_id",
]


def reject_invalid_account_id(account_id: str | None) -> None:
    """*제공된* runtime-invalid ``account_id``면 ``HTTPException(422)``.

    Account ID 계약(``docs/specs/account/14-account-id-contract.md``
    "Runtime invalid")의 read-API ingress 가드. 각 account-scoped read 라우트
    핸들러가 lookup/SQL/service 호출 **이전**에 호출해야 한다.

    - ``account_id is None`` (query 파라미터 미지정): 통과시킨다. #1218이
      확정한 all-account/단일-treasury 집계 분기 보존 (동작·schema 불변).
    - ``account_id``가 제공됐고 :func:`is_invalid_account_id`가 ``True``
      (``""``/``"default"``/``ACCOUNT_ID_PATTERN`` 불일치): 422로 거부.
    - valid-pattern but absent (``acc-9999`` 등): ``is_invalid_account_id``가
      ``False`` → 통과. genuine not-found 의미론은 caller의 기존 lookup이
      처리한다.

    Args:
        account_id: 검증할 query 파라미터 값 또는 ``None`` (미지정).

    Raises:
        HTTPException(422): ``account_id``가 제공됐고 runtime-invalid일 때.
            detail은 형식 위반 시 SSOT 보존 메시지(``ante account create``
            CLI ``str(e)`` contract와 동일 형식), fallback 예약어(``default``)/
            빈 문자열은 그에 준하는 메시지를 사용한다. traceback은 노출하지
            않는다.
    """
    if account_id is None or not is_invalid_account_id(account_id):
        return
    raise HTTPException(
        status_code=422,
        detail=(
            f"account_id 형식이 올바르지 않습니다: '{account_id}'. "
            "영문, 숫자, 하이픈만 허용하며 3~30자여야 합니다. "
            "fallback 예약어('default')와 빈 문자열은 사용할 수 없습니다."
        ),
    )
