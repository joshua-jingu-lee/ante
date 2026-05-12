"""``GET /api/audit``의 ``from_date``/``to_date`` ISO 8601 검증 테스트 (issue #1414).

oracle A7 시그니처에서 발견된 contract drift: ``from_date``/``to_date``가
임의 문자열(예: ``oracle-not-a-date``)을 200으로 수락하고 있었다. 본 PR은
핸들러 안에서 ``_validate_iso_date`` 헬퍼로 ISO 8601 파싱 가능성만 검증
하고, 파싱 실패 시 422로 거부한다.

핵심 invariants (Implementation Plan + Codex r1/r2 findings):
- 인증 누락 + 잘못된 날짜 → 401 (auth-first 우선순위, dependency 순서 회귀 방지).
- 인증된 master + 잘못된 날짜 → 422 (``AuditLogger.query`` 미호출).
- 인증된 master + 정상 date-only (``YYYY-MM-DD``) → 200, **원본 str(10자리)
  그대로 전달** → ``AuditLogger.query`` 내부의 ``T23:59:59`` 자동 확장 분기
  보존. Codex r1 finding: 1차 구현은 Pydantic datetime → ``isoformat()``으로
  변환했고, date-only가 ``"2026-05-10T00:00:00"`` (19자리)로 바뀌어 자정
  이후 데이터를 누락하는 silent semantic regression이 발생했다.
- 인증된 master + 정상 ISO 8601 datetime (``Z``/offset/naive) → 200, storage
  format(``%Y-%m-%dT%H:%M:%S``, naive UTC)으로 **정규화** 후 전달. Codex r2
  finding: ``AuditLogger``는 ``datetime.now(UTC).strftime(...)``로 Z 없는
  naive 포맷을 저장한다. ``Z``/offset 보존 시 SQL 텍스트 비교
  (``created_at >= '2026-05-10T00:00:00Z'`` vs storage
  ``'2026-05-10T00:00:00'``)에서 ASCII ``Z`` > digit이므로 정확히 같은 시각의
  row가 inclusive lower bound에서 누락되는 silent regression이 발생한다.
- OpenAPI ``parameters[from_date]``/``parameters[to_date]``는 ``string``
  스키마로 노출되며 description에 ISO 8601 형식을 명시한다.

SSOT: ``docs/specs/web-api/05-resource-endpoints.md`` (audit 라우트는
"필터: member_id, action, from_date, to_date, limit, offset" — free-form
허용 명시 없음 → ISO 8601 강제는 spec 위반이 아니다).
``docs/specs/audit/audit.md`` Web API 예시는 ``from_date=2026-03-12&to_date=
2026-03-19`` (date-only) — 본 회귀 테스트는 그 caller 패턴을 보호한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import AsyncMock

import pytest

httpx = pytest.importorskip("httpx", reason="httpx required for web API tests")

from fastapi.testclient import TestClient  # noqa: E402

from ante.web.app import create_app  # noqa: E402

# ── Member / Session fakes (#1359 / #1352 패턴) ─────────────────────────


@dataclass
class FakeMember:
    member_id: str
    type: str = "agent"
    role: str = "default"
    org: str = "default"
    name: str = ""
    emoji: str = ""
    status: str = "active"
    scopes: list[str] = field(default_factory=list)


class FakeMemberService:
    """``test_audit_routes_auth.py`` 패턴을 그대로 재사용한다."""

    def __init__(self) -> None:
        self._members: dict[str, FakeMember] = {}
        self._tokens: dict[str, str] = {}

    def add_member(
        self,
        member_id: str,
        token: str = "",
        role: str = "default",
        member_type: str = "agent",
        scopes: list[str] | None = None,
    ) -> FakeMember:
        member = FakeMember(
            member_id=member_id,
            role=role,
            type=member_type,
            scopes=list(scopes) if scopes else [],
        )
        self._members[member_id] = member
        if token:
            self._tokens[token] = member_id
        return member

    async def authenticate(self, token: str) -> FakeMember:
        member_id = self._tokens.get(token)
        if member_id is None:
            raise PermissionError("유효하지 않은 토큰")
        return self._members[member_id]

    async def update_last_active(self, member_id: str) -> None:
        return None

    async def get(self, member_id: str) -> FakeMember | None:
        return self._members.get(member_id)


# ── audit_logger fake ───────────────────────────────────────────────────


def _make_audit_logger() -> AsyncMock:
    """query/count call_args를 추적할 수 있는 mock audit logger."""
    mock = AsyncMock()
    mock.query = AsyncMock(
        return_value=[
            {
                "id": 1,
                "member_id": "agent-01",
                "action": "bot.create",
                "resource": "bot:bot-1",
                "detail": "",
                "ip": "127.0.0.1",
                "created_at": "2026-05-09T00:00:00",
            }
        ]
    )
    mock.count = AsyncMock(return_value=1)
    return mock


# ── fixtures ────────────────────────────────────────────────────────────


@pytest.fixture
def member_service() -> FakeMemberService:
    svc = FakeMemberService()
    svc.add_member(
        "master-user",
        token="master-token",
        role="master",
        member_type="human",
    )
    return svc


@pytest.fixture
def audit_logger() -> AsyncMock:
    return _make_audit_logger()


@pytest.fixture
def client(
    member_service: FakeMemberService,
    audit_logger: AsyncMock,
) -> TestClient:
    app = create_app(
        member_service=member_service,
        audit_logger=audit_logger,
    )
    return TestClient(app)


_MASTER_HEADERS = {"Authorization": "Bearer master-token"}


# ── 422: 잘못된 날짜 파라미터 (Issue #1414 본문) ──────────────────────


class TestInvalidDate422:
    """파싱 불가능한 ``from_date``/``to_date`` → 422, AuditLogger 미호출."""

    def test_invalid_from_date_returns_422(
        self, client: TestClient, audit_logger: AsyncMock
    ) -> None:
        """``GET /api/audit?from_date=oracle-not-a-date`` → 422."""
        resp = client.get(
            "/api/audit?from_date=oracle-not-a-date",
            headers=_MASTER_HEADERS,
        )
        assert resp.status_code == 422, (
            f"invalid from_date가 422가 아님 ({resp.status_code}: {resp.text})"
        )
        assert audit_logger.query.await_count == 0, (
            "422 차단 시 audit_logger.query가 호출되어선 안 된다"
        )
        assert audit_logger.count.await_count == 0

    def test_invalid_to_date_returns_422(
        self, client: TestClient, audit_logger: AsyncMock
    ) -> None:
        """``GET /api/audit?to_date=also-not-a-date`` → 422."""
        resp = client.get(
            "/api/audit?to_date=also-not-a-date",
            headers=_MASTER_HEADERS,
        )
        assert resp.status_code == 422, (
            f"invalid to_date가 422가 아님 ({resp.status_code}: {resp.text})"
        )
        assert audit_logger.query.await_count == 0
        assert audit_logger.count.await_count == 0

    def test_invalid_both_dates_returns_422(
        self, client: TestClient, audit_logger: AsyncMock
    ) -> None:
        """``from_date``+``to_date`` 모두 invalid → 422."""
        resp = client.get(
            "/api/audit?from_date=oracle-not-a-date&to_date=also-not-a-date",
            headers=_MASTER_HEADERS,
        )
        assert resp.status_code == 422, (
            f"양쪽 invalid date가 422가 아님 ({resp.status_code}: {resp.text})"
        )
        assert audit_logger.query.await_count == 0
        assert audit_logger.count.await_count == 0


# ── 200: 정상 ISO 8601 + str 보존 회귀 ────────────────────────────────


class TestValidIsoDate200:
    """정상 ISO 8601 입력은 200으로 통과하며 ``AuditLogger``로 올바른 형식이
    전달되어야 한다.

    - date-only(``YYYY-MM-DD``): **원본 str(10자리)** 그대로 전달 → 자동
      확장 분기 보존(Codex r1 finding).
    - ISO datetime(``Z``/offset/naive): **storage format
      (``%Y-%m-%dT%H:%M:%S``, naive UTC)으로 정규화** 후 전달 → inclusive
      boundary 보존(Codex r2 finding).
    """

    def test_z_suffix_normalized_to_storage_format(
        self, client: TestClient, audit_logger: AsyncMock
    ) -> None:
        """``Z`` suffix는 storage format(Z 제거)으로 정규화되어 전달된다.

        Codex r2 finding 핵심 회귀:
            ``AuditLogger.log``는
            ``datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S")``로 Z 없는
            naive 포맷을 저장한다. ``Z``를 그대로 SQL 비교에 넘기면
            ``'2026-05-10T00:00:00Z' > '2026-05-10T00:00:00'``(ASCII Z > digit)
            로 평가되어 정확히 같은 시각의 row가 inclusive lower bound에서
            누락된다. 본 테스트는 ``Z`` suffix가 storage format으로 정규화되어
            ``AuditLogger.query``에 도달하는지 확인한다.
        """
        resp = client.get(
            "/api/audit?from_date=2026-05-10T00:00:00Z",
            headers=_MASTER_HEADERS,
        )
        assert resp.status_code == 200, (
            f"Z suffix datetime이 200이 아님 ({resp.status_code}: {resp.text})"
        )
        assert audit_logger.query.await_count == 1
        call_kwargs = audit_logger.query.await_args.kwargs
        assert call_kwargs["from_date"] == "2026-05-10T00:00:00", (
            f"Z suffix가 storage format(Z 제거)으로 정규화되어야 함: "
            f"{call_kwargs['from_date']!r}"
        )
        # count에도 동일하게 정규화되어 전달되는지 확인
        count_kwargs = audit_logger.count.await_args.kwargs
        assert count_kwargs["from_date"] == "2026-05-10T00:00:00", (
            f"count에도 Z 제거 정규화 적용되어야 함: {count_kwargs['from_date']!r}"
        )

    def test_offset_normalized_to_utc(
        self, client: TestClient, audit_logger: AsyncMock
    ) -> None:
        """``+HH:MM`` offset이 UTC로 변환되고 timezone-naive로 평탄화된다.

        ``2026-05-10T12:00:00+09:00`` (KST 정오) → UTC 03:00:00 → storage
        format ``2026-05-10T03:00:00``.
        """
        # URL-encoded ``+09:00`` → ``%2B09%3A00``
        resp = client.get(
            "/api/audit?from_date=2026-05-10T12:00:00%2B09:00",
            headers=_MASTER_HEADERS,
        )
        assert resp.status_code == 200, (
            f"offset datetime이 200이 아님 ({resp.status_code}: {resp.text})"
        )
        assert audit_logger.query.await_count == 1
        call_kwargs = audit_logger.query.await_args.kwargs
        assert call_kwargs["from_date"] == "2026-05-10T03:00:00", (
            f"+09:00 offset이 UTC naive로 변환되어야 함 (12:00 KST → 03:00 UTC): "
            f"{call_kwargs['from_date']!r}"
        )

    def test_naive_datetime_preserved(
        self, client: TestClient, audit_logger: AsyncMock
    ) -> None:
        """timezone 없는 naive datetime은 UTC로 가정하고 그대로 storage format
        으로 통과한다(이미 19자리 ``%Y-%m-%dT%H:%M:%S``).
        """
        resp = client.get(
            "/api/audit?from_date=2026-05-10T12:34:56",
            headers=_MASTER_HEADERS,
        )
        assert resp.status_code == 200, (
            f"naive datetime이 200이 아님 ({resp.status_code}: {resp.text})"
        )
        assert audit_logger.query.await_count == 1
        call_kwargs = audit_logger.query.await_args.kwargs
        assert call_kwargs["from_date"] == "2026-05-10T12:34:56", (
            f"naive datetime이 storage format 그대로 전달되어야 함: "
            f"{call_kwargs['from_date']!r}"
        )

    def test_date_only_returns_200(
        self, client: TestClient, audit_logger: AsyncMock
    ) -> None:
        """date-only (``2026-05-10``) → 200. 10자리 str 그대로 전달되어
        ``AuditLogger.query`` 내부의 ``T23:59:59`` 자동 확장 분기를 보존한다.
        Codex r1 finding 핵심 회귀.
        """
        resp = client.get(
            "/api/audit?from_date=2026-05-10",
            headers=_MASTER_HEADERS,
        )
        assert resp.status_code == 200, (
            f"date-only가 200이 아님 ({resp.status_code}: {resp.text})"
        )
        assert audit_logger.query.await_count == 1
        call_kwargs = audit_logger.query.await_args.kwargs
        assert call_kwargs["from_date"] == "2026-05-10", (
            f"date-only str(10자리)가 변환 없이 그대로 전달되어야 함: "
            f"{call_kwargs['from_date']!r}"
        )

    def test_date_only_to_date_extended_to_end_of_day(
        self, client: TestClient, audit_logger: AsyncMock
    ) -> None:
        """date-only ``to_date``(10자리)가 ``AuditLogger``에 그대로 전달되어
        자정 이후 데이터 누락을 방지한다.

        Codex r1 finding 핵심 회귀:
            1차 구현은 Pydantic이 ``2026-05-10`` → ``datetime(2026,5,10,0,0,0)``
            으로 변환한 뒤 핸들러가 ``isoformat()`` → ``"2026-05-10T00:00:00"``
            (19자리)로 바꿔 ``AuditLogger.query``의
            ``if len(to_date) == 10: to_date + "T23:59:59"`` 자동 확장 분기를
            우회시켰다. 결과적으로 SQL ``created_at <= '2026-05-10T00:00:00'``
            로 좁혀져 자정 이후 데이터를 모두 누락. 본 테스트는 입력 str이
            10자리 그대로 ``AuditLogger.query``에 도달하는지 확인한다.

        Codex r2 finding 보강: date-only 입력에 한해 정규화를 적용하지 않는다.
        ``len(value) == 10`` 분기 진입을 보존하기 위해 ``_validate_iso_date``는
        ``date.fromisoformat`` 통과 시 원본을 즉시 반환한다.
        """
        resp = client.get(
            "/api/audit?to_date=2026-05-10",
            headers=_MASTER_HEADERS,
        )
        assert resp.status_code == 200, (
            f"date-only to_date가 200이 아님 ({resp.status_code}: {resp.text})"
        )
        assert audit_logger.query.await_count == 1
        call_kwargs = audit_logger.query.await_args.kwargs
        # 10자리 그대로 — AuditLogger 내부에서 자동 확장 분기 진입 가능
        assert call_kwargs["to_date"] == "2026-05-10", (
            f"date-only to_date가 10자리 그대로 전달되어야 함 (자동 확장 보존): "
            f"{call_kwargs['to_date']!r}"
        )
        assert len(call_kwargs["to_date"]) == 10, (
            f"to_date 길이가 10이어야 AuditLogger.query 분기 진입 가능: "
            f"len={len(call_kwargs['to_date'])}, value={call_kwargs['to_date']!r}"
        )
        # count도 동일하게 전달되는지 확인
        count_kwargs = audit_logger.count.await_args.kwargs
        assert count_kwargs["to_date"] == "2026-05-10", (
            f"count에도 date-only str 그대로 전달되어야 함: {count_kwargs['to_date']!r}"
        )

    def test_iso_datetime_to_date_normalized(
        self, client: TestClient, audit_logger: AsyncMock
    ) -> None:
        """ISO datetime ``to_date``(``Z`` suffix)도 storage format으로 정규화.

        Codex r2 finding 적용: ``Z`` 보존 시 inclusive upper bound도 SQL 텍스트
        비교에서 어긋난다(저장값보다 항상 크게 평가되어 자정 시각의 row 자체는
        포함되긴 하나, 동일 시각 비교 일관성이 깨짐). 정규화로 일관된 boundary
        를 보장한다.
        """
        resp = client.get(
            "/api/audit?to_date=2026-05-10T12:34:56Z",
            headers=_MASTER_HEADERS,
        )
        assert resp.status_code == 200, (
            f"ISO datetime to_date가 200이 아님 ({resp.status_code}: {resp.text})"
        )
        call_kwargs = audit_logger.query.await_args.kwargs
        assert call_kwargs["to_date"] == "2026-05-10T12:34:56", (
            f"ISO datetime to_date(Z)가 storage format으로 정규화되어야 함: "
            f"{call_kwargs['to_date']!r}"
        )

    def test_both_dates_passed_as_str(
        self, client: TestClient, audit_logger: AsyncMock
    ) -> None:
        """``from_date``+``to_date`` 둘 다 date-only로 보낼 때 양쪽 모두 원본
        str 보존."""
        resp = client.get(
            "/api/audit?from_date=2026-03-12&to_date=2026-03-19",
            headers=_MASTER_HEADERS,
        )
        assert resp.status_code == 200, (
            f"date-only 양쪽 전송이 200이 아님 ({resp.status_code}: {resp.text})"
        )
        call_kwargs = audit_logger.query.await_args.kwargs
        assert call_kwargs["from_date"] == "2026-03-12"
        assert call_kwargs["to_date"] == "2026-03-19"

    def test_compact_iso_date_normalized(
        self, client: TestClient, audit_logger: AsyncMock
    ) -> None:
        """비표준 compact ISO date(``20260510``)는 표준 ``YYYY-MM-DD``로 정규화.

        Codex r3 finding 핵심 회귀:
            Python 3.13의 ``date.fromisoformat()``은 ``20260510`` (no dashes)
            같은 비표준 ISO date도 수락한다. r2 구현은 검증 통과 시 원본 str
            (``20260510``, 8자리)을 그대로 반환했으므로 ``AuditLogger.query``의
            ``len(to_date) == 10`` 자동 확장 분기가 작동하지 않고, SQL
            ``created_at >= '20260510'`` 텍스트 비교가 ``YYYY-MM-DDT...``
            저장값과 어긋나는 silent regression을 만든다. 본 테스트는 r3
            정규화 (``date.isoformat()`` 호출)가 ``2026-05-10`` (10자리 표준
            형식)으로 변환하여 그 전제를 복원하는지 확인한다.
        """
        resp = client.get(
            "/api/audit?from_date=20260510",
            headers=_MASTER_HEADERS,
        )
        assert resp.status_code == 200, (
            f"compact ISO date가 200이 아님 ({resp.status_code}: {resp.text})"
        )
        assert audit_logger.query.await_count == 1
        call_kwargs = audit_logger.query.await_args.kwargs
        assert call_kwargs["from_date"] == "2026-05-10", (
            f"compact ISO date가 ``YYYY-MM-DD`` 표준 형식으로 정규화되어야 함: "
            f"{call_kwargs['from_date']!r}"
        )
        # count에도 동일 정규화
        count_kwargs = audit_logger.count.await_args.kwargs
        assert count_kwargs["from_date"] == "2026-05-10", (
            f"count에도 compact ISO date 정규화 적용되어야 함: "
            f"{count_kwargs['from_date']!r}"
        )

    def test_iso_week_date_normalized(
        self, client: TestClient, audit_logger: AsyncMock
    ) -> None:
        """ISO week date(``2026-W19-1``)도 표준 ``YYYY-MM-DD``로 정규화.

        Codex r3 finding 보강:
            Python 3.13은 ``2026-W19-1`` (ISO week date, 10자리이긴 하나 비표준
            포맷)도 ``date.fromisoformat``로 파싱한다. ``AuditLogger.query``의
            10자리 길이 분기는 통과하더라도 ``W`` 문자가 SQL 텍스트 비교
            (``YYYY-MM-DDT...``)와 어긋나는 회귀를 만들 수 있다. 본 테스트는
            정규화 후 결과가 10자리 ``YYYY-MM-DD`` 형식(``-`` 두 개 포함)임을
            확인한다.
        """
        # ``2026-W19-1`` → ISO week 19 of 2026, Monday → 2026-05-04
        resp = client.get(
            "/api/audit?from_date=2026-W19-1",
            headers=_MASTER_HEADERS,
        )
        assert resp.status_code == 200, (
            f"ISO week date가 200이 아님 ({resp.status_code}: {resp.text})"
        )
        assert audit_logger.query.await_count == 1
        call_kwargs = audit_logger.query.await_args.kwargs
        from_date_value = call_kwargs["from_date"]
        # 길이 / dash 개수 invariant 검증 — AuditLogger.query의 ``len == 10``
        # 분기와 ``YYYY-MM-DDT...`` 텍스트 비교 전제 보존.
        assert len(from_date_value) == 10, (
            f"정규화된 from_date 길이가 10이어야 함 (자동 확장 분기 진입 가능): "
            f"len={len(from_date_value)}, value={from_date_value!r}"
        )
        assert from_date_value.count("-") == 2, (
            f"정규화된 from_date에 ``-`` 두 개가 있어야 표준 ``YYYY-MM-DD``: "
            f"{from_date_value!r}"
        )
        # isocalendar 기준 명시 — ISO week 19 of 2026의 Monday는 2026-05-04
        assert from_date_value == "2026-05-04", (
            f"2026-W19-1 → 2026-05-04 (ISO week 19 Monday)로 정규화되어야 함: "
            f"{from_date_value!r}"
        )


# ── 401: auth-first invariant (Issue #1414 본문) ────────────────────


class TestAuthFirstWithInvalidDate:
    """인증 누락 + 잘못된 날짜 → 401 우선 (422 보다 dependency 우선순위 보존).

    FastAPI는 핸들러 매개변수 순서대로 dependency를 해결하므로 ``caller_id``
    (require_audit_read)가 ``from_date``/``to_date`` Query parsing 보다 먼저
    실행된다. 인증 정보가 없으면 401이 먼저 반환되어 "auth-first" invariant
    가 유지된다. 본 테스트는 그 회귀를 막는다.

    NOTE (#1414 r1): 422 검증을 핸들러 본문(헬퍼 호출)로 옮기면 Query
    parsing 단계는 항상 통과하므로, 잘못된 날짜로 호출해도 핸들러 진입
    전에 401이 발생하는지가 더더욱 중요하다.
    """

    def test_unauth_with_invalid_date_returns_401(
        self, client: TestClient, audit_logger: AsyncMock
    ) -> None:
        """unauth + ``from_date=garbage`` → 401, audit_logger 미호출."""
        resp = client.get("/api/audit?from_date=garbage")
        assert resp.status_code == 401, (
            f"unauth + invalid date가 401이 아님 ({resp.status_code}: {resp.text})"
        )
        assert audit_logger.query.await_count == 0
        assert audit_logger.count.await_count == 0


# ── OpenAPI 스키마 회귀 (contract-drift fix 검증) ──────────────────


class TestOpenAPIDateContract:
    """``/openapi.json``의 ``from_date``/``to_date`` 스키마 + 422 응답 분기
    회귀.

    issue #1414 r1: 1차 구현은 ``Annotated[datetime | None, Query(...)]``로
    좁혀 OpenAPI에 ``format: date-time``으로 노출했으나, 그 자동 변환이 SQL
    의 자동 확장 분기를 깨뜨려 회귀로 판정됐다. r2 구현은 타입을
    ``str | None``으로 복원하고 description에 ISO 8601 명시. 따라서 OpenAPI
    schema는 ``string`` 또는 anyOf ``string``/null이며, description에
    ISO 8601 키워드가 포함되어야 한다. 422 분기는 그대로 유지.
    """

    @staticmethod
    def _audit_get_operation() -> dict:
        app = create_app()
        schema = app.openapi()
        return schema["paths"]["/api/audit"]["get"]

    @staticmethod
    def _audit_query_params() -> dict[str, dict]:
        """``GET /api/audit`` query parameter 객체를 name → param 매핑으로."""
        operation = TestOpenAPIDateContract._audit_get_operation()
        return {
            param["name"]: param
            for param in operation.get("parameters", [])
            if param.get("in") == "query"
        }

    def test_from_date_param_is_string_type(self) -> None:
        params = self._audit_query_params()
        assert "from_date" in params, (
            f"GET /api/audit에 from_date param이 없음: {sorted(params.keys())}"
        )
        types = self._collect_types(params["from_date"]["schema"])
        assert "string" in types, (
            f"from_date 스키마에 string type이 없음: {params['from_date']['schema']}"
        )

    def test_to_date_param_is_string_type(self) -> None:
        params = self._audit_query_params()
        assert "to_date" in params, (
            f"GET /api/audit에 to_date param이 없음: {sorted(params.keys())}"
        )
        types = self._collect_types(params["to_date"]["schema"])
        assert "string" in types, (
            f"to_date 스키마에 string type이 없음: {params['to_date']['schema']}"
        )

    def test_from_date_description_mentions_iso_8601(self) -> None:
        """contract drift 방지: description에 ISO 8601 명시 — frontend
        codegen 산출물이 free-form string으로 노출되지 않도록 한다."""
        params = self._audit_query_params()
        description = params["from_date"].get("description", "") or ""
        assert "ISO 8601" in description, (
            f"from_date description에 'ISO 8601' 명시가 없음: {description!r}"
        )

    def test_to_date_description_mentions_iso_8601(self) -> None:
        params = self._audit_query_params()
        description = params["to_date"].get("description", "") or ""
        assert "ISO 8601" in description, (
            f"to_date description에 'ISO 8601' 명시가 없음: {description!r}"
        )

    def test_openapi_lists_422_response(self) -> None:
        """``GET /api/audit`` ``responses``에 422 항목이 있어야 한다.

        ``frontend/openapi.json`` codegen 산출물이 422 분기를 인식할 수 있도록
        contract에 명시한다. 핸들러가 직접 raise한 422도 OpenAPI에 노출된다.
        """
        operation = self._audit_get_operation()
        responses = operation.get("responses", {})
        assert "422" in responses, (
            f"GET /api/audit 응답에 422 항목이 없음: {sorted(responses.keys())}"
        )

    @staticmethod
    def _collect_types(schema: dict) -> set[str]:
        """``schema`` 트리에서 모든 ``type`` 값을 모아 반환한다.

        FastAPI는 ``str | None``을 ``anyOf: [{type: string}, {type: null}]``로
        펼치므로 anyOf branch까지 탐색해야 한다.
        """
        types: set[str] = set()
        if "type" in schema:
            types.add(schema["type"])
        for branch in schema.get("anyOf", []) or []:
            if isinstance(branch, dict) and "type" in branch:
                types.add(branch["type"])
        return types
