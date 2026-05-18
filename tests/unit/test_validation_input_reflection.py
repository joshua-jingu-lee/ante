"""422 validation error 입력 반사 차단 — 보안 invariant 회귀 (#1629 L1 / #1650 L2).

L1 범위(이슈 #1629 본문 SSOT):
- 거부된 입력 **값**/``input``/``ctx``/``msg`` 반사 금지
- raw-body 핸들러는 공용 chokepoint ``sanitize_validation_errors(e)``
  (= ``e.errors(include_context=False, include_input=False)`` +
  ``_normalize_error_loc``, pydantic ``ValidationError``), 글로벌
  ``RequestValidationError`` 핸들러는 ``_sanitize_pydantic_errors(exc.
  errors())`` (= ``input``/``ctx`` 제거 + ``_normalize_error_loc``)
- web request 모델 validator 메시지는 거부된 raw value 를 ``msg`` 에
  interpolation 하지 않는다 (반사 경로 2: scopes/trading_hours/timezone)

L2 범위(이슈 #1650 본문 SSOT — #1643 Split A):
- Pydantic ``error["type"] == "extra_forbidden"`` 항목의 ``loc`` **말단
  세그먼트**(거부된 caller extra 필드 키 이름)는 고정 placeholder
  ``[extra]`` 로 정규화된다. 두 sanitization 경로(글로벌 ``_sanitize_
  pydantic_errors`` / raw-body chokepoint ``sanitize_validation_errors``)
  모두 적용한다. static ``loc`` prefix(``body`` 등)·``type``/``msg``/
  ``url``·HTTP 422·RFC7807 envelope 는 보존한다.
- **본 파일의 L2 보안 단언은 ``type=='extra_forbidden'`` loc 벡터에
  한정**한다. 비-``extra_forbidden`` caller-controlled ``loc``(자유형
  ``dict[str,*]`` 키, structured body, validator-합성 loc)는 #1650
  정규화 대상이 아니며 **#1651(spec-first 종합 정책)** 에서 다룬다.
- ``PUT /api/accounts/{id}`` raw body 의 수동 unknown-key 422 detail
  반사(F3 벡터, Pydantic ``extra_forbidden``/공용 chokepoint 미경유)는
  **#1654 로 해소**됐다 — caller-supplied unknown body key 이름을
  반사하지 않는 고정 메시지(L1 #1629 와 같은 방향 런타임 보장)이며,
  본 함수(``_normalize_error_loc``/``sanitize_validation_errors``)는
  여전히 미경유다. positive 반사-차단 lock 은
  ``test_f3_manual_unknown_key_detail_not_reflected``.
"""

from __future__ import annotations

import math
import re
import subprocess
from pathlib import Path

import pydantic
import pytest

httpx = pytest.importorskip("httpx", reason="httpx required for web API tests")

from fastapi.testclient import TestClient  # noqa: E402

from ante.web.app import create_app  # noqa: E402
from ante.web.errors import (  # noqa: E402
    _EXTRA_FORBIDDEN_LOC_PLACEHOLDER,
    _normalize_error_loc,
    _sanitize_pydantic_errors,
    sanitize_validation_errors,
)
from ante.web.routes.accounts import _ActivateNoBody  # noqa: E402
from ante.web.routes.approvals import ApprovalStatusUpdate  # noqa: E402
from ante.web.routes.bots import BotCreateRequest  # noqa: E402
from ante.web.routes.config import ConfigUpdateRequest  # noqa: E402
from ante.web.routes.members import (  # noqa: E402
    MemberCreateRequest,
    PasswordChangeRequest,
    ScopesUpdateRequest,
)
from ante.web.routes.system import HaltRequest  # noqa: E402
from ante.web.routes.treasury import (  # noqa: E402
    BalanceSetRequest,
    BudgetChangeRequest,
)
from ante.web.schemas import (  # noqa: E402
    AccountSuspendRequest,
    AccountUpdateRequest,
    BotUpdateRequest,
    ReportSubmitRequest,
    RuleUpdateRequest,
    StatusUpdateRequest,
    StrategyValidateRequest,
)
from tests.unit.conftest import (  # noqa: E402
    MASTER_AUTH_HEADERS,
    make_master_member_service,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ROUTES_DIR = _REPO_ROOT / "src" / "ante" / "web" / "routes"

# 고유 sentinel — 422 detail 어디에도 등장하면 안 된다.
SENTINEL = "SNTNL_1629_a1b2c3d4e5"
SENTINEL_OBJ = {"leaked": SENTINEL}


# ── 구조적 폐쇄 락: behavioral SENTINEL parametrized 매트릭스 ──────────
#
# 전체 18 raw-body chokepoint 사이트의 request 모델 × {필드값, non-str}
# sentinel. 각 핸들러가 적용하는 공용 chokepoint
# ``sanitize_validation_errors(e)`` (= ``e.errors(include_context=False,
# include_input=False)`` + ``_normalize_error_loc``)를 거친 detail
# 문자열에 sentinel 부재를 단언한다. mechanism-agnostic: input/ctx/msg/
# helper-위임/미래 validator 모두 포착.
#
# 케이스 ID 는 (라우트 사이트, vector) 단위. 동일 모델이 복수 raw-body
# 사이트에서 재사용되는 경우(MemberCreate, BudgetChange 등) 사이트 단위로
# 케이스를 두어 discovery 게이트(grep chokepoint 사이트 수 == 케이스 수)
# 를 만족시킨다. #1650 으로 chokepoint 가 전 raw-body 사이트(#1629 sweep
# 15 + bots POST/PUT 2 + accounts RuleUpdate #1380 1 = 18)를 단일 SSOT
# 로 흡수했으므로, 본 매트릭스도 18 사이트를 전수 커버한다.
#
# (case_id, model, payload)  — payload 는 ``model_validate`` 에서
# pydantic ``ValidationError`` 를 일으키고 sentinel 을 담는다.
SENTINEL_MATRIX: list[tuple[str, type[pydantic.BaseModel], dict]] = [
    # config.py:227  PUT /api/config/{key}  (ConfigUpdateRequest)
    (
        "config__configupdate__nonstr",
        ConfigUpdateRequest,
        {"value": "x", "category": SENTINEL_OBJ},
    ),
    # members.py:478  POST /api/members  (MemberCreateRequest)
    (
        "members_create__membercreate__fieldval",
        MemberCreateRequest,
        {"member_id": SENTINEL, "member_type": "INVALID_" + SENTINEL},
    ),
    # members.py:914  PATCH /api/members/{id}/password  (PasswordChangeRequest)
    (
        "members_password__passwordchange__nonstr",
        PasswordChangeRequest,
        {"old_password": SENTINEL_OBJ, "new_password": "x"},
    ),
    # members.py:1040  PUT /api/members/{id}/scopes  (ScopesUpdateRequest)
    # 반사 경로 2: scopes validator msg 거부값 미삽입.
    (
        "members_scopes__scopesupdate__fieldval",
        ScopesUpdateRequest,
        {"scopes": [SENTINEL]},
    ),
    # system.py:239  POST /api/system/halt  (HaltRequest, 공유 helper)
    (
        "system_halt__halt__nonstr",
        HaltRequest,
        {"reason": SENTINEL_OBJ},
    ),
    # approvals.py:272  PATCH /api/approvals/{id}/status  (ApprovalStatusUpdate)
    (
        "approvals_status__approvalstatus__fieldval",
        ApprovalStatusUpdate,
        {"status": SENTINEL},
    ),
    # accounts.py:653  PUT /api/accounts/{id}  (AccountUpdateRequest)
    # 반사 경로 2: trading_hours validator msg 거부값 미삽입.
    (
        "accounts_update__accountupdate__trading_hours",
        AccountUpdateRequest,
        {"trading_hours_start": SENTINEL},
    ),
    # accounts.py:881  POST /api/accounts/{id}/suspend  (AccountSuspendRequest)
    (
        "accounts_suspend__accountsuspend__nonstr",
        AccountSuspendRequest,
        {"reason": SENTINEL_OBJ},
    ),
    # accounts.py:1000  POST /api/accounts/{id}/activate  (_ActivateNoBody)
    (
        "accounts_activate__activatenobody__nonstr",
        _ActivateNoBody,
        {"reason": SENTINEL_OBJ},
    ),
    # strategies.py:221  POST /api/strategies/validate  (StrategyValidateRequest)
    (
        "strategies_validate__strategyvalidate__nonstr",
        StrategyValidateRequest,
        {"path": SENTINEL_OBJ},
    ),
    # strategies.py:473  PATCH /api/strategies/{id}/status  (StatusUpdateRequest)
    (
        "strategies_status__statusupdate__fieldval",
        StatusUpdateRequest,
        {"status": SENTINEL},
    ),
    # reports.py:190  POST /api/reports  (ReportSubmitRequest)
    (
        "reports_submit__reportsubmit__nonstr",
        ReportSubmitRequest,
        {"strategy_name": SENTINEL_OBJ},
    ),
    # treasury.py:545  POST /api/treasury/bots/{bot_id}/allocate
    (
        "treasury_allocate__budgetchange__fieldval",
        BudgetChangeRequest,
        {"amount": SENTINEL},
    ),
    # treasury.py:709  POST /api/treasury/bots/{bot_id}/deallocate
    (
        "treasury_deallocate__budgetchange__fieldval",
        BudgetChangeRequest,
        {"amount": SENTINEL},
    ),
    # treasury.py:879  POST /api/treasury/balance  (BalanceSetRequest)
    (
        "treasury_balance__balanceset__fieldval",
        BalanceSetRequest,
        {"balance": SENTINEL},
    ),
    # bots.py POST /api/bots  (BotCreateRequest, extra='forbid')
    # #1650: chokepoint 가 #1629 sweep 외 bots POST 사이트도 흡수.
    (
        "bots_create__botcreate__nonstr",
        BotCreateRequest,
        {"bot_id": SENTINEL_OBJ, "strategy_id": "s1"},
    ),
    # bots.py PUT /api/bots/{id}  (BotUpdateRequest, extra='forbid')
    (
        "bots_update__botupdate__nonstr",
        BotUpdateRequest,
        {"name": SENTINEL_OBJ},
    ),
    # accounts.py PUT /api/accounts/{id}/rules  (RuleUpdateRequest, #1380)
    # extra='forbid' 아님 — non-bool ``enabled`` 로 type-error 반사 경로.
    (
        "accounts_rules__ruleupdate__nonbool",
        RuleUpdateRequest,
        {"enabled": SENTINEL_OBJ},
    ),
]


_ALL_ROUTE_FILES = [
    "accounts.py",
    "approvals.py",
    "bots.py",
    "config.py",
    "members.py",
    "reports.py",
    "strategies.py",
    "system.py",
    "treasury.py",
]


def _grep_chokepoint_site_count() -> int:
    """전 라우트 파일의 공용 chokepoint 호출 raw-body 사이트 수.

    #1650 으로 모든 raw-body ``model_validate`` 422 사이트가 직접
    ``e.errors(include_context=False, include_input=False)`` 대신 공용
    chokepoint ``sanitize_validation_errors(e)`` 를 호출한다(직접 호출
    잔존 0 — SSOT). 본 grep 은 chokepoint 호출 사이트만 센다(하드코딩
    상수 없음 — 사이트 추가/삭제 시 자동 추종). discovery 게이트:
    이 수 == ``SENTINEL_MATRIX`` 케이스 수.
    """
    total = 0
    for name in _ALL_ROUTE_FILES:
        text = (_ROUTES_DIR / name).read_text()
        total += len(re.findall(r"detail=sanitize_validation_errors\(e\),", text))
    return total


def _grep_direct_unsanitized_errors_count() -> int:
    """raw-body 사이트에서 chokepoint 우회 직접 ``e.errors(...)`` 잔존 수.

    #1650 SSOT invariant: raw-body 사이트는 chokepoint 만 호출하므로
    ``detail=e.errors(include_context=False, include_input=False)`` 직접
    호출은 0 이어야 한다.
    """
    total = 0
    for name in _ALL_ROUTE_FILES:
        text = (_ROUTES_DIR / name).read_text()
        total += len(
            re.findall(
                r"detail=e\.errors\(include_context=False, include_input=False\)",
                text,
            )
        )
    return total


def test_discovery_gate_sentinel_matrix_covers_all_sweep_sites() -> None:
    """discovery 게이트: chokepoint 사이트 수 == sentinel 매트릭스 케이스 수.

    #1650 으로 게이트 기준을 (#1629 sweep 하드코딩 15) 에서 (공용
    chokepoint 호출 사이트 수) 로 재정의한다. raw-body 사이트가 추가/
    누락되면 본 테스트가 깨져 매트릭스 갱신을 강제한다(per-site
    chokepoint 위임 누락 회귀를 behavioral 하게 락). 추가로 chokepoint
    우회 직접 ``e.errors(include_input=False)`` 호출 잔존 0 을 단언한다
    (#1650 SSOT — 직접 호출 잔존 시 loc 정규화가 누락된다).
    """
    direct_count = _grep_direct_unsanitized_errors_count()
    assert direct_count == 0, (
        f"chokepoint 우회 직접 e.errors(include_input=False) 잔존: "
        f"{direct_count} (raw-body 사이트는 sanitize_validation_errors 만 호출)"
    )
    chokepoint_count = _grep_chokepoint_site_count()
    assert chokepoint_count > 0, "chokepoint 호출 사이트가 0 — grep 회귀 의심"
    assert len(SENTINEL_MATRIX) == chokepoint_count, (
        f"SENTINEL_MATRIX 케이스 수({len(SENTINEL_MATRIX)}) != "
        f"grep chokepoint raw-body 사이트 수({chokepoint_count}). "
        "raw-body 사이트 추가/삭제 시 SENTINEL_MATRIX 갱신 필요."
    )


@pytest.mark.parametrize(
    ("case_id", "model", "payload"),
    [pytest.param(c, m, p, id=c) for c, m, p in SENTINEL_MATRIX],
)
def test_sweep_site_detail_has_no_input_reflection(
    case_id: str, model: type[pydantic.BaseModel], payload: dict
) -> None:
    """sweep 사이트 모델의 sanitized detail 에 sentinel 부재 (L1).

    각 raw-body 핸들러가 적용하는 공용 chokepoint
    ``sanitize_validation_errors(e)`` (= ``e.errors(include_context=False,
    include_input=False)`` + ``_normalize_error_loc``)를 거친 detail
    문자열에 거부된 입력 값/sentinel 이 절대 등장하지 않아야 한다.
    """
    with pytest.raises(pydantic.ValidationError) as excinfo:
        model.model_validate(payload)

    exc = excinfo.value
    # 핸들러 계약: HTTPException(detail=sanitize_validation_errors(e)) →
    # http_exception_handler 가 ``str(exc.detail)`` 로 직렬화. 동일 경로를
    # 그대로 재현한다 (#1650 chokepoint).
    errs = sanitize_validation_errors(exc)
    sanitized_detail = str(errs)

    # sanitize 전(raw)에는 sentinel 이 새므로(테스트 자기검증) sanitize
    # 후에는 절대 부재여야 한다.
    raw_detail = str(exc.errors())
    assert SENTINEL in raw_detail, (
        f"[{case_id}] 테스트 자기검증 실패: raw detail 에 sentinel 부재 — "
        "payload 가 입력 반사 경로를 타지 않음"
    )
    assert SENTINEL not in sanitized_detail, (
        f"[{case_id}] sanitized 422 detail 에 sentinel 반사: {sanitized_detail}"
    )

    # detail 구조 보존: loc/type/msg 는 파싱 가능해야 한다.
    assert errs, f"[{case_id}] errors() 가 비어 있음"
    for e in errs:
        assert "loc" in e and "type" in e and "msg" in e, (
            f"[{case_id}] error dict 구조 손상: {e}"
        )
        assert "input" not in e, f"[{case_id}] input 키 잔존: {e}"
        assert "ctx" not in e, f"[{case_id}] ctx 키 잔존: {e}"


# ── _sanitize_pydantic_errors 단위 ──────────────────────────────────


def test_sanitize_pydantic_errors_removes_input_ctx_keeps_rest() -> None:
    """``input``/``ctx`` 제거, ``loc``/``type``/``msg``/``url`` 보존."""
    raw = [
        {
            "type": "string_type",
            "loc": ("body", "password"),
            "msg": "Input should be a valid string",
            "input": {"secret": "TOPSECRET"},
            "ctx": {"error": ValueError("TOPSECRET")},
            "url": "https://errors.pydantic.dev/2.12/v/string_type",
        },
        {
            "type": "missing",
            "loc": ("body", "member_id"),
            "msg": "Field required",
            "input": {"leaked": "X"},
        },
    ]
    out = _sanitize_pydantic_errors(raw)
    assert len(out) == 2
    for o in out:
        assert "input" not in o
        assert "ctx" not in o
        assert set(("loc", "type", "msg")).issubset(o.keys())
    assert out[0]["url"] == "https://errors.pydantic.dev/2.12/v/string_type"
    flat = str(out)
    assert "TOPSECRET" not in flat
    assert "leaked" not in flat


def test_sanitize_pydantic_errors_empty_list() -> None:
    assert _sanitize_pydantic_errors([]) == []


# ── #1650 L2: extra_forbidden loc 말단 정규화 ─────────────────────────
#
# 본 섹션의 보안 단언은 모두 ``type=='extra_forbidden'`` loc 벡터에
# 한정한다. 비-extra_forbidden caller-controlled loc 는 #1651(spec-first
# 종합 정책) 대상. PUT /api/accounts/{id} 수동 unknown-key 422 detail
# 반사(F3)는 #1654 로 해소(caller key 미반사 고정 메시지, 본 sanitizer
# 미경유) — positive lock 은 test_f3_manual_unknown_key_detail_not_reflected.

# extra='forbid' 요청모델 × extra-key sentinel. payload 는 미정의 caller
# extra 키(SENTINEL)를 담아 ``extra_forbidden`` 422 를 일으킨다. 현 모든
# extra='forbid' 요청모델은 flat BaseModel(#1643 v-series AST 실측).
EXTRA_FORBIDDEN_MATRIX: list[tuple[str, type[pydantic.BaseModel], dict]] = [
    (
        "activatenobody__extra_key",
        _ActivateNoBody,
        {SENTINEL: "x"},
    ),
    (
        "botcreate__extra_key",
        BotCreateRequest,
        {"bot_id": "b", "strategy_id": "s1", SENTINEL: "leak"},
    ),
    (
        "botupdate__extra_key",
        BotUpdateRequest,
        {"name": "n", SENTINEL: "leak"},
    ),
]


def test_normalize_error_loc_extra_forbidden_replaces_last_segment() -> None:
    """``extra_forbidden`` 항목의 ``loc`` 말단 caller 키만 placeholder 치환.

    static prefix(``body``)·``type``/``msg``/``url`` 보존. 컨테이너 타입
    (글로벌=list / raw-body pydantic=tuple) 유지. 비-extra_forbidden
    항목은 ``loc`` 완전 보존(#1650 한정 — #1651 미경유).
    """
    raw = [
        # 글로벌 RequestValidationError 형태(loc=list, prefix=body)
        {
            "type": "extra_forbidden",
            "loc": ["body", SENTINEL],
            "msg": "Extra inputs are not permitted",
            "url": "https://errors.pydantic.dev/2.12/v/extra_forbidden",
        },
        # raw-body pydantic 형태(loc=tuple, prefix 없음)
        {
            "type": "extra_forbidden",
            "loc": (SENTINEL,),
            "msg": "Extra inputs are not permitted",
        },
        # 비-extra_forbidden — loc 완전 보존(#1650 비대상)
        {
            "type": "missing",
            "loc": ("body", "member_id"),
            "msg": "Field required",
        },
    ]
    out = _normalize_error_loc(raw)
    # 1) 글로벌: list 유지, prefix 보존, 말단만 placeholder.
    assert out[0]["loc"] == ["body", _EXTRA_FORBIDDEN_LOC_PLACEHOLDER]
    assert isinstance(out[0]["loc"], list)
    assert out[0]["type"] == "extra_forbidden"
    assert out[0]["msg"] == "Extra inputs are not permitted"
    assert out[0]["url"].endswith("/extra_forbidden")
    # 2) raw-body: tuple 유지, 말단(유일 세그먼트)만 placeholder.
    assert out[1]["loc"] == (_EXTRA_FORBIDDEN_LOC_PLACEHOLDER,)
    assert isinstance(out[1]["loc"], tuple)
    # 3) 비-extra_forbidden: loc 불변(#1650 한정 — #1651 대상).
    assert out[2]["loc"] == ("body", "member_id")
    # sentinel 전수 부재.
    assert SENTINEL not in str(out)


def test_normalize_error_loc_empty_and_no_loc() -> None:
    """빈 loc / loc 부재 / 비-list-tuple loc 는 안전하게 통과(no-op)."""
    raw = [
        {"type": "extra_forbidden", "loc": (), "msg": "m"},
        {"type": "extra_forbidden", "msg": "no loc"},
        {"type": "extra_forbidden", "loc": "weird", "msg": "m"},
    ]
    out = _normalize_error_loc(raw)
    assert out[0]["loc"] == ()
    assert "loc" not in out[1]
    assert out[2]["loc"] == "weird"


def test_sanitize_pydantic_errors_composes_loc_normalization() -> None:
    """글로벌 경로: input/ctx 제거 후 extra_forbidden loc 정규화 합성.

    #1650 CV2 (a): synthetic ``extra_forbidden`` 에러(caller-key loc) →
    합성 글로벌 sanitizer → sentinel ∉ loc/detail · static prefix/type/
    msg 보존.
    """
    raw = [
        {
            "type": "extra_forbidden",
            "loc": ["body", SENTINEL],
            "msg": "Extra inputs are not permitted",
            "input": SENTINEL,
            "url": "https://errors.pydantic.dev/2.12/v/extra_forbidden",
        }
    ]
    out = _sanitize_pydantic_errors(raw)
    assert len(out) == 1
    o = out[0]
    assert "input" not in o and "ctx" not in o
    assert o["loc"] == ["body", _EXTRA_FORBIDDEN_LOC_PLACEHOLDER]
    assert o["type"] == "extra_forbidden"
    assert o["msg"] == "Extra inputs are not permitted"
    assert o["url"].endswith("/extra_forbidden")
    flat = str(out)
    assert SENTINEL not in flat


@pytest.mark.parametrize(
    ("case_id", "model", "payload"),
    [pytest.param(c, m, p, id=c) for c, m, p in EXTRA_FORBIDDEN_MATRIX],
)
def test_extra_forbidden_loc_placeholder_raw_body_path(
    case_id: str, model: type[pydantic.BaseModel], payload: dict
) -> None:
    """raw-body chokepoint: extra_forbidden loc 말단 caller 키 placeholder.

    raw-body ``model_validate`` 사이트가 호출하는 공용 chokepoint
    ``sanitize_validation_errors(e)`` 를 거치면 ``extra_forbidden`` 항목
    ``loc`` 말단(거부 caller 키 = SENTINEL)이 placeholder 로 치환되고
    detail 어디에도 sentinel 이 노출되지 않는다. ``type``/``msg`` 보존.
    """
    with pytest.raises(pydantic.ValidationError) as excinfo:
        model.model_validate(payload)
    exc = excinfo.value

    # 자기검증: sanitize 전 raw 에는 caller 키(SENTINEL) 가 loc 에 노출.
    raw = exc.errors()
    assert any(
        e.get("type") == "extra_forbidden" and SENTINEL in tuple(e.get("loc", ()))
        for e in raw
    ), f"[{case_id}] 자기검증 실패: raw loc 에 extra_forbidden caller 키 부재"

    errs = sanitize_validation_errors(exc)
    ef = [e for e in errs if e.get("type") == "extra_forbidden"]
    assert ef, f"[{case_id}] extra_forbidden 항목 부재: {errs}"
    for e in ef:
        loc = tuple(e.get("loc", ()))
        assert loc and loc[-1] == _EXTRA_FORBIDDEN_LOC_PLACEHOLDER, (
            f"[{case_id}] loc 말단이 placeholder 가 아님: {loc}"
        )
        assert SENTINEL not in loc, f"[{case_id}] caller 키 잔존: {loc}"
        assert e["type"] == "extra_forbidden", f"[{case_id}] type 변형: {e}"
        assert "msg" in e, f"[{case_id}] msg 손상: {e}"
    # detail 직렬화 어디에도 caller 키 부재.
    assert SENTINEL not in str(errs), (
        f"[{case_id}] sanitized detail 에 caller 키 반사: {errs}"
    )


# ── HTTP 회귀: probe 2 표면 + 글로벌 핸들러 + 반사 경로 2 + #1630 ────


class _StubReportStore:
    """report_store 가용성 가드 통과용 최소 stub.

    raw-body validation(``ReportSubmitRequest.model_validate``)이 422 로
    먼저 실패하므로 ``submit`` 은 호출되지 않는다.
    """

    async def submit(self, *args, **kwargs):  # pragma: no cover - 미호출
        raise AssertionError("validation 실패 전제 — submit 미호출이어야 함")


class _StubSessionService:
    """session_service 가용성 가드 통과용 최소 stub.

    typed ``body: LoginRequest`` native validation 이 글로벌 핸들러에서
    422 로 먼저 실패하므로 ``create`` 는 호출되지 않는다.
    """

    async def create(self, *args, **kwargs):  # pragma: no cover - 미호출
        raise AssertionError("native validation 실패 전제 — create 미호출")


@pytest.fixture
def app():
    return create_app(
        member_service=make_master_member_service(),
        report_store=_StubReportStore(),
        session_service=_StubSessionService(),
    )


@pytest.fixture
def client(app):
    c = TestClient(app)
    c.headers.update(MASTER_AUTH_HEADERS)
    return c


@pytest.fixture
def unauth_client(app):
    return TestClient(app)


def _assert_clean_422(resp, sentinel: str) -> dict:
    """422 + detail 에 sentinel 부재 + loc/msg 파싱 가능."""
    assert resp.status_code == 422, f"status={resp.status_code} body={resp.text}"
    body = resp.json()
    detail = str(body.get("detail", ""))
    assert sentinel not in detail, f"sentinel 반사: {detail}"
    # detail 은 errors() repr — loc/msg 토큰이 존재(파싱 가능)해야 한다.
    assert "loc" in detail and "msg" in detail, f"detail 구조 손상: {detail}"
    return body


def test_probe_members_password_extra_field_no_reflection(client) -> None:
    """probe 표면 1: PATCH /api/members/{id}/password extra field."""
    resp = client.patch(
        "/api/members/m-123/password",
        json={
            "old_password": "old-pw",
            "new_password": "new-pw",
            "recovery_key": SENTINEL,
        },
    )
    _assert_clean_422(resp, SENTINEL)


def test_probe_reports_submit_extra_field_no_reflection(client) -> None:
    """probe 표면 2: POST /api/reports extra field."""
    resp = client.post(
        "/api/reports",
        json={
            "strategy_name": "s",
            "strategy_version": "1",
            "strategy_path": "p",
            "backtest_period": "2024",
            "total_return_pct": 1.0,
            "total_trades": 1,
            "summary": "s",
            "rationale": "r",
            "api_secret": SENTINEL,
        },
    )
    _assert_clean_422(resp, SENTINEL)


def test_global_handler_native_query_validation_422_no_500_no_reflection(
    client,
) -> None:
    """글로벌 RequestValidationError(native query 타입) 회귀.

    ``GET /api/members?limit=<sentinel>`` 은 typed ``limit: int`` query 에
    sentinel string 을 넣어 FastAPI-native ``RequestValidationError`` 를
    유발한다(글로벌 ``validation_exception_handler`` 경로).

    - **422 유지 AND TypeError/500 미발생**: ``RequestValidationError.
      errors()`` 는 FastAPI 0.135.1 에서 ``include_*`` kwargs 미지원이라
      kwargs 사용 시 핸들러가 ``TypeError`` → 500 회귀. ``_sanitize_
      pydantic_errors`` 사후 sanitize 가 이를 방지한다 (Codex r1 [high]).
    - ``input``/``ctx`` 부재, sentinel 부재, loc/type/msg 보존.
    """
    resp = client.get("/api/members", params={"limit": SENTINEL})
    assert resp.status_code != 500, f"TypeError/500 회귀: {resp.text}"
    assert resp.status_code == 422, f"status={resp.status_code} {resp.text}"
    detail = str(resp.json().get("detail", ""))
    assert SENTINEL not in detail, f"query 값 반사: {detail}"
    assert "'input'" not in detail and '"input"' not in detail, detail
    assert "'ctx'" not in detail and '"ctx"' not in detail, detail
    # loc/type/msg 보존(파싱 가능) — 글로벌 핸들러도 구조 유지.
    assert "'loc'" in detail and "'type'" in detail and "'msg'" in detail, detail


def test_global_handler_native_query_validation_offset_422(client) -> None:
    """글로벌 native query 검증(다른 필드) → 422 유지·500 미발생.

    ``offset: int`` query 에 sentinel string → 글로벌 핸들러 422,
    input/ctx 부재.
    """
    resp = client.get("/api/members", params={"offset": SENTINEL})
    assert resp.status_code != 500, f"TypeError/500 회귀: {resp.text}"
    assert resp.status_code == 422, f"status={resp.status_code} {resp.text}"
    detail = str(resp.json().get("detail", ""))
    assert SENTINEL not in detail, detail
    assert "'input'" not in detail and "'ctx'" not in detail, detail


def test_reflection_path2_scopes_msg_no_sentinel(client) -> None:
    """반사 경로 2: PUT /api/members/{id}/scopes 거부값 msg 미삽입."""
    resp = client.put(
        "/api/members/m-1/scopes",
        json={"scopes": [SENTINEL]},
    )
    body = _assert_clean_422(resp, SENTINEL)
    # msg 에 SCOPE_VOCABULARY 미등록 안내는 있되 거부값(SENTINEL)은 없다.
    assert "SCOPE_VOCABULARY" in str(body["detail"])


def test_reflection_path2_account_update_trading_hours_msg(client) -> None:
    """반사 경로 2: AccountUpdate trading_hours invalid → msg 거부값 부재."""
    # PUT /api/accounts/{id} — account 미존재여도 model_validate 단계에서
    # trading_hours validator 가 422 를 먼저 던지는 raw-body 패턴.
    resp = client.put(
        "/api/accounts/acc-1",
        json={"trading_hours_start": SENTINEL},
    )
    # account_service 미주입이면 503 가능 → 그 경우 모델 검증 전 단계라
    # 본 테스트의 관심(반사 경로 2)은 422 일 때만 단언.
    if resp.status_code == 422:
        _assert_clean_422(resp, SENTINEL)


def test_reflection_path2_account_update_timezone_msg(client) -> None:
    """반사 경로 2: AccountUpdate timezone invalid → helper ValueError wrap.

    공유 helper(``account/timezone.py``)는 미변경, web validator 에서만
    value-free 메시지로 wrap 했는지 확인.
    """
    resp = client.put(
        "/api/accounts/acc-1",
        json={"timezone": SENTINEL},
    )
    if resp.status_code == 422:
        body = _assert_clean_422(resp, SENTINEL)
        assert "IANA" in str(body["detail"])


def test_nan_inf_input_no_500(client) -> None:
    """NaN/Inf input → 422 (500 아님). 선례 위험(#1380) 동시 폐쇄.

    ``BalanceSetRequest.balance`` 에 NaN 을 JSON 으로 직접 보낼 수 없으므로
    pydantic 검증 후 sanitized 직렬화 경로를 단위로 검증한다.
    """
    for bad in (math.nan, math.inf, -math.inf):
        with pytest.raises(pydantic.ValidationError) as ei:
            BudgetChangeRequest.model_validate({"amount": [bad]})
        # sanitized 형태가 allow_nan=False 직렬화 위험 없는 str 인지 확인.
        s = str(ei.value.errors(include_context=False, include_input=False))
        assert "nan" not in s.lower() or "input" not in s


def test_1630_auth_login_password_object_not_reflected(unauth_client) -> None:
    """#1630 동시 폐쇄: POST /api/auth/login {"password": {...}} 글로벌 422.

    typed ``body: LoginRequest`` 라 FastAPI-native RequestValidationError
    경로(글로벌 핸들러). password object 가 detail 에 반사되면 안 된다.
    """
    resp = unauth_client.post(
        "/api/auth/login",
        json={"member_id": "m1", "password": {"leaked": SENTINEL}},
    )
    assert resp.status_code != 500, f"500 회귀: {resp.text}"
    assert resp.status_code == 422, f"status={resp.status_code} {resp.text}"
    detail = str(resp.json().get("detail", ""))
    assert SENTINEL not in detail, f"password object 반사: {detail}"
    assert "'input'" not in detail and '"input"' not in detail, detail
    assert "'ctx'" not in detail and '"ctx"' not in detail, detail


def test_grep_invariant_no_unsanitized_errors_call() -> None:
    """grep invariant (a): sanitize 미적용 ``e.errors()`` 코드 0건.

    주석/문서 라인은 제외(``grep -v`` 후 코드 라인만). raw-body kwargs
    form / 글로벌 helper-wrapped 두 형태만 허용.
    """
    web_dir = _REPO_ROOT / "src" / "ante" / "web"
    out = subprocess.run(
        [
            "grep",
            "-rn",
            r"e\.errors()\|exc\.errors()",
            str(web_dir),
            "--include=*.py",
        ],
        capture_output=True,
        text=True,
    )
    offenders = []
    for line in out.stdout.splitlines():
        if "include_input=False" in line or "_sanitize_pydantic_errors" in line:
            continue
        # path:lineno:content
        parts = line.split(":", 2)
        if len(parts) < 3:
            continue
        content = parts[2].lstrip()
        # 주석/문서 라인(``#`` 또는 docstring 내부) 제외.
        if content.startswith(("#", '"', "`")):
            continue
        offenders.append(line)
    assert not offenders, f"sanitize 미적용 e.errors()/exc.errors(): {offenders}"


def test_grep_invariant_validator_msg_no_value_interpolation() -> None:
    """grep invariant (b): sweep 모델 validator msg 거부값 interpolation 0.

    ``members.py``/``schemas.py`` web request 모델 validator 의
    ``raise ValueError`` 메시지에 ``{scope!r}``/``{v!r}``/``{value!r}`` 등
    거부값 f-string interpolation 이 없어야 한다.
    """
    targets = [
        _REPO_ROOT / "src" / "ante" / "web" / "routes" / "members.py",
        _REPO_ROOT / "src" / "ante" / "web" / "schemas.py",
    ]
    bad_pat = re.compile(r"raise ValueError\([^)]*\{[^}]*!r\}")
    offenders: list[str] = []
    for t in targets:
        text = t.read_text()
        for m in bad_pat.finditer(text):
            offenders.append(f"{t.name}: {m.group(0)[:80]}")
        # f-string ValueError 에 거부값 변수 직접 삽입(scope/v/value) 패턴.
        for m in re.finditer(
            r'raise ValueError\(\s*f"[^"]*\{(scope|v|value)[!}\[]', text
        ):
            offenders.append(f"{t.name}: {m.group(0)[:80]}")
    assert not offenders, f"validator msg 거부값 interpolation: {offenders}"


# ── #1650 CV2 (b): 글로벌 RequestValidationError 경로 end-to-end ──────


class _EFBody(pydantic.BaseModel):
    """test-only ``extra='forbid'`` 요청 body 모델 (CV2 b).

    module-scope 정의라 FastAPI 가 typed body 로 추론한다(함수-로컬
    클래스는 query param 으로 오추론됨).
    """

    model_config = pydantic.ConfigDict(extra="forbid")
    name: str


def test_global_path_extra_forbidden_loc_placeholder_e2e() -> None:
    """CV2 (b): test-only ``extra='forbid'`` 미니 route + TestClient.

    typed ``body: _EFBody`` 라 미정의 caller 키는 FastAPI-native
    ``RequestValidationError`` (글로벌 ``validation_exception_handler``
    경로)로 ``extra_forbidden`` 422 를 일으킨다. 글로벌 핸들러는
    ``_sanitize_pydantic_errors`` (= input/ctx 제거 + ``_normalize_error_
    loc``) 를 적용하므로, 422 detail 에 caller 키(SENTINEL) 가 노출되지
    않고 ``loc`` 말단이 placeholder 로 치환되며 static prefix(``body``)·
    ``type``/``msg``·HTTP 422·RFC7807 envelope 가 보존된다.
    """
    from fastapi import FastAPI

    from ante.web.errors import register_exception_handlers

    mini = FastAPI()
    register_exception_handlers(mini)

    @mini.post("/ef")
    def _ef(body: _EFBody) -> dict:  # pragma: no cover - 422 전 미도달
        return {"ok": body.name}

    mini_client = TestClient(mini)
    resp = mini_client.post("/ef", json={"name": "n", SENTINEL: "leak"})

    assert resp.status_code == 422, f"status={resp.status_code} {resp.text}"
    body = resp.json()
    # RFC7807 envelope 보존.
    assert body["status"] == 422
    assert body["type"] == "/errors/validation"
    detail = str(body.get("detail", ""))
    # caller 키(SENTINEL) 가 loc/detail 어디에도 노출되지 않는다.
    assert SENTINEL not in detail, f"글로벌 경로 caller 키 반사: {detail}"
    # placeholder 가 loc 에 등장(말단 정규화 적용).
    assert _EXTRA_FORBIDDEN_LOC_PLACEHOLDER in detail, f"placeholder 미적용: {detail}"
    # type/msg/static prefix(body) 보존.
    assert "extra_forbidden" in detail, detail
    assert "'body'" in detail or '"body"' in detail, detail
    assert "'input'" not in detail and "'ctx'" not in detail, detail


# ── F3 (#1654): 수동 unknown-key 422 detail caller key 미반사 ─────────


def test_f3_manual_unknown_key_detail_not_reflected(client) -> None:
    """F3 (#1654): PUT /api/accounts/{id} 수동 unknown-key 422 detail 미반사.

    ``accounts.py`` 의 8단계 수동 unknown-key 가드는 unknown mutable 키를
    ``AccountUpdateRequest.model_validate`` **이전** 에 직접 처리해 422 를
    던진다(Pydantic ``extra_forbidden`` 미경유, ``e.errors()`` loc 없음,
    공용 chokepoint ``sanitize_validation_errors``/``_normalize_error_loc``
    미경유 — F3 벡터). #1654 는 이 detail-string 이 caller 가 보낸 unknown
    body key 이름을 그대로 반사하지 않도록(L1 #1629 와 같은 방향 런타임
    보장) 고정 메시지로 정렬한다. 거부 동작·status 422 는 불변이다.

    본 테스트는 positive 반사-차단 lock 이다(mechanism-agnostic): 유니크
    SENTINEL 을 unknown body key 로 보냈을 때 (a) status 422 유지 (b)
    전체 직렬화 응답(detail 및 임의 필드) 어디에도 SENTINEL 부재 (c)
    #1650 placeholder 토큰 미등장(F3 는 sanitizer 미경유). caller key 가
    detail 에 다시 등장하면(=본 단언 실패) #1654 회귀이므로 중단·재보고.
    """
    resp = client.put(
        "/api/accounts/acc-1",
        json={SENTINEL: "x"},
    )
    # 수동 unknown-key 가드는 model_validate·service 해소 이전 단계라
    # unknown body key 면 422 가 무조건 발화한다(503 선행 없음).
    assert resp.status_code == 422, f"status={resp.status_code} {resp.text}"
    # 전체 직렬화 응답(detail 포함 임의 필드) 어디에도 caller 가 보낸
    # unknown body key 이름(SENTINEL)이 반사되지 않는다.
    serialized = resp.text
    assert SENTINEL not in serialized, (
        f"#1654 회귀 — F3 수동 unknown-key 422 응답이 caller key 반사: {serialized}"
    )
    # F3 는 #1650 sanitizer/chokepoint 미경유이므로 placeholder 토큰도
    # 등장하지 않는다(메커니즘 동일성 회귀 — 고정 메시지일 뿐).
    detail = str(resp.json().get("detail", ""))
    assert _EXTRA_FORBIDDEN_LOC_PLACEHOLDER not in detail, (
        f"F3 경로에 #1650 placeholder 오적용(메커니즘 침범): {detail}"
    )
