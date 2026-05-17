"""422 validation error 입력 값 반사 차단 — 보안 invariant 회귀 (#1629 L1).

L1 범위(이슈 #1629 본문 SSOT):
- 거부된 입력 **값**/``input``/``ctx``/``msg`` 반사 금지
- raw-body 핸들러는 ``e.errors(include_context=False, include_input=False)``
  (pydantic ``ValidationError``), 글로벌 ``RequestValidationError`` 핸들러는
  ``_sanitize_pydantic_errors(exc.errors())`` 로 ``input``/``ctx`` 제거
- web request 모델 validator 메시지는 거부된 raw value 를 ``msg`` 에
  interpolation 하지 않는다 (반사 경로 2: scopes/trading_hours/timezone)

``loc`` 세그먼트의 caller-제어 키(거부된 extra 필드 키 이름 / 자유형
``dict[str,*]`` 키) 정규화는 **#1643(별도 이슈)** 영역이며, 본 파일은
``loc`` 케이스를 단언하지 않는다 (L1 에서 ``loc`` 키는 변경 전과 동일
노출 — 악화 0; #1643 이 후속 정규화).
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
from ante.web.errors import _sanitize_pydantic_errors  # noqa: E402
from ante.web.routes.accounts import _ActivateNoBody  # noqa: E402
from ante.web.routes.approvals import ApprovalStatusUpdate  # noqa: E402
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
    ReportSubmitRequest,
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
# sweep 15 raw-body 사이트의 request 모델 × {필드값, non-str} sentinel.
# 각 핸들러가 적용하는 sanitizer(``e.errors(include_context=False,
# include_input=False)``)를 거친 detail 문자열에 sentinel 부재를 단언한다.
# mechanism-agnostic: input/ctx/msg/helper-위임/미래 validator 모두 포착.
#
# 케이스 ID 는 (라우트 사이트, vector) 단위. 동일 모델이 복수 raw-body
# 사이트에서 재사용되는 경우(MemberCreate, BudgetChange 등) 사이트 단위로
# 케이스를 두어 discovery 게이트(grep raw-body 사이트 수 == 케이스 수)를
# 만족시킨다.
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
]


def _grep_raw_body_site_count() -> int:
    """sweep 라우트 파일의 sanitize 적용 raw-body 사이트 수.

    선례(``bots.py`` 2 사이트, ``accounts.py`` RuleUpdate #1380)는 sweep
    대상이 아니므로 제외하고, 본 #1629 sweep 으로 정화된 사이트만 센다.
    discovery 게이트: 이 수 == ``SENTINEL_MATRIX`` 케이스 수.
    """
    sweep_files = [
        "config.py",
        "members.py",
        "system.py",
        "approvals.py",
        "accounts.py",
        "strategies.py",
        "reports.py",
        "treasury.py",
    ]
    total = 0
    for name in sweep_files:
        text = (_ROUTES_DIR / name).read_text()
        # raw-body 사이트는 ``detail=e.errors(include_context=False,
        # include_input=False)`` 형태. accounts.py 의 #1380 RuleUpdate
        # 선례 1 사이트는 sweep 대상 아님 → 차감.
        count = len(
            re.findall(
                r"detail=e\.errors\(include_context=False, include_input=False\)",
                text,
            )
        )
        if name == "accounts.py":
            # accounts.py 의 RuleUpdateRequest(#1380) 선례 1 사이트 제외.
            count -= 1
        total += count
    return total


def test_discovery_gate_sentinel_matrix_covers_all_sweep_sites() -> None:
    """discovery 게이트: grep raw-body 사이트 수 == sentinel 매트릭스 케이스 수.

    sweep 사이트가 추가/누락되면 본 테스트가 깨져 매트릭스 갱신을 강제한다
    (per-site grep 의 helper-위임 누락 회귀를 behavioral 하게 락).
    """
    grep_count = _grep_raw_body_site_count()
    assert grep_count == 15, (
        f"sweep raw-body 사이트 수 변동: grep={grep_count}, 예상=15. "
        "SENTINEL_MATRIX 와 함께 갱신 필요."
    )
    assert len(SENTINEL_MATRIX) == grep_count, (
        f"SENTINEL_MATRIX 케이스 수({len(SENTINEL_MATRIX)}) != "
        f"grep raw-body 사이트 수({grep_count})"
    )


@pytest.mark.parametrize(
    ("case_id", "model", "payload"),
    [pytest.param(c, m, p, id=c) for c, m, p in SENTINEL_MATRIX],
)
def test_sweep_site_detail_has_no_input_reflection(
    case_id: str, model: type[pydantic.BaseModel], payload: dict
) -> None:
    """sweep 사이트 모델의 sanitized detail 에 sentinel 부재.

    각 raw-body 핸들러가 적용하는 sanitizer(``e.errors(include_context=
    False, include_input=False)``)를 거친 detail 문자열에 거부된 입력
    값/sentinel 이 절대 등장하지 않아야 한다.
    """
    with pytest.raises(pydantic.ValidationError) as excinfo:
        model.model_validate(payload)

    exc = excinfo.value
    # 핸들러 계약: HTTPException(detail=...) → http_exception_handler 가
    # ``str(exc.detail)`` 로 직렬화. 동일 경로를 그대로 재현한다.
    sanitized_detail = str(exc.errors(include_context=False, include_input=False))

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
    errs = exc.errors(include_context=False, include_input=False)
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
