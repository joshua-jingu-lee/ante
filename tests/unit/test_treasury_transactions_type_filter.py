"""``GET /api/treasury/transactions`` ``type`` query 정규 vocabulary 422 회귀.

이슈 #1477 (split of #1443/B): #1476이 동결한 5-value vocabulary
(``allocate``, ``deallocate``, ``release``, ``fill``, ``bot_stopped_release``)
외 값을 ``GET /api/treasury/transactions?type=...``에 넘기면 FastAPI/Pydantic
``Literal`` 좁힘에 의해 422로 거부되어야 한다.

원본 oracle A7 host probe signature:

    host_probe_failed:treasury_transaction_invalid_type_accepted:
      probe=treasury_transaction_invalid_type,expected_status=422,
      actual_status=200,type=oracle_invalid_type

수정 전 동작:
    ``type: str | None`` 시그니처라 임의 문자열이 그대로 SQL WHERE 절에 들어가고
    매치가 없는 경우 200 + ``{"items": [], "total": 0}``을 반환 → contract drift.

수정 후 동작:
    ``type: Literal[...]`` 좁힘으로 vocabulary 외 값은 FastAPI 입력 검증 단계에서
    422로 거부되어 핸들러 자체에 도달하지 않는다. ``treasury._db`` SQL spy 가
    한 번도 호출되지 않는 것으로 defense-in-depth를 확인한다.

본 테스트는 다음을 보장한다:

* 정규 5개 값 (``allocate``/``deallocate``/``release``/``fill``/
  ``bot_stopped_release``) → 200 회귀 (SQL은 정확한 ``transaction_type`` 값을
  WHERE 절 인자로 받음).
* invalid freeform (``oracle_invalid_type``, ``invalid``) → 422, SQL 미호출.
* 제거된 dead vocabulary (``reserve``) → 422, SQL 미호출.
* type 미지정 → 200, SQL은 ``transaction_type`` WHERE 없이 호출.
* live OpenAPI 스키마의 ``type`` query schema가 5-value enum을 노출.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

httpx = pytest.importorskip("httpx", reason="httpx required for web API tests")

from ante.treasury.treasury import TRANSACTION_TYPE_VOCABULARY  # noqa: E402
from ante.web.app import create_app  # noqa: E402
from ante.web.routes.treasury import (  # noqa: E402
    _TRANSACTION_TYPE_QUERY_VALUES,
    TransactionTypeQuery,
)
from tests.unit.conftest import (  # noqa: E402
    make_authed_client,
    make_master_member_service,
)

# ──────────────────────────────────────────────────────────────────────
# Vocabulary alignment guards (drift-checked at import).
# ──────────────────────────────────────────────────────────────────────

EXPECTED_VOCABULARY = frozenset(
    {"allocate", "deallocate", "release", "fill", "bot_stopped_release"}
)


def test_route_literal_aligns_with_treasury_vocabulary() -> None:
    """라우트의 ``TransactionTypeQuery`` Literal이 #1476 SSOT와 정확히 일치해야 한다.

    드리프트가 생기면 ``ante.web.routes.treasury`` 모듈 import 단계에서
    ``RuntimeError``로 차단되지만, 본 테스트로도 한 번 더 명시 검증한다.
    """
    assert _TRANSACTION_TYPE_QUERY_VALUES == TRANSACTION_TYPE_VOCABULARY
    assert _TRANSACTION_TYPE_QUERY_VALUES == EXPECTED_VOCABULARY


# ──────────────────────────────────────────────────────────────────────
# Fake DB / Treasury fixtures.
# ──────────────────────────────────────────────────────────────────────


@dataclass
class _SQLCall:
    """``db.fetch_*`` 호출 인자 기록용."""

    query: str
    params: tuple


class _SpyDB:
    """``treasury._db`` 자리에 들어가는 fake DB. SQL 호출과 params를 기록한다.

    transactions 라우트는 ``COUNT(*)`` + ``SELECT *`` 두 번 호출한다.
    valid type 회귀에서는 두 번 모두 호출되어야 하고, invalid type 422 거부
    경로에서는 한 번도 호출되어선 안 된다 (defense-in-depth).
    """

    def __init__(self) -> None:
        self.calls: list[_SQLCall] = []
        self.rows: list[dict[str, Any]] = []

    async def fetch_one(self, query: str, params: tuple) -> dict | None:
        self.calls.append(_SQLCall(query=query, params=tuple(params)))
        if "COUNT(*)" in query:
            return {"cnt": len(self.rows)}
        return None

    async def fetch_all(self, query: str, params: tuple) -> list[dict]:
        self.calls.append(_SQLCall(query=query, params=tuple(params)))
        return list(self.rows)


@pytest.fixture
def spy_db() -> _SpyDB:
    return _SpyDB()


@pytest.fixture
def treasury(spy_db: _SpyDB) -> MagicMock:
    """transactions 라우트가 사용하는 mock Treasury."""
    mock = MagicMock()
    mock._db = spy_db
    mock.get_summary.return_value = {
        "total_evaluation": 0.0,
        "account_balance": 0.0,
    }
    mock.get_latest_snapshot = AsyncMock(return_value=None)
    mock.get_snapshots = AsyncMock(return_value=[])
    mock.get_daily_snapshot = AsyncMock(return_value=None)
    return mock


@pytest.fixture
def client(treasury: MagicMock):
    app = create_app(
        treasury=treasury,
        member_service=make_master_member_service(),
    )
    return make_authed_client(app)


# ──────────────────────────────────────────────────────────────────────
# 422: invalid type (oracle A7 본문).
# ──────────────────────────────────────────────────────────────────────


class TestInvalidTypeRejected422:
    """vocabulary 외 ``type`` 값은 ``Literal`` 좁힘으로 422 거부되어야 한다.

    추가로 ``treasury._db`` SQL이 한 번도 호출되지 않아야 한다 — invalid 입력이
    SQL WHERE까지 전달되어 empty result로 200을 반환하던 원래 회귀가 방지됨을
    확인한다.
    """

    @pytest.mark.parametrize(
        "invalid_type",
        [
            "oracle_invalid_type",  # oracle A7 본문 시그니처
            "invalid",
            "reserve",  # #1476에서 제거된 dead value
            "ALLOCATE",  # 대문자 — case-sensitive Literal
            " allocate",  # leading space
            "allocate ",  # trailing space
            "buy",
            "sell",
            "",  # empty string — Literal 외 값
        ],
    )
    def test_invalid_type_returns_422_and_skips_sql(
        self,
        client,
        spy_db: _SpyDB,
        invalid_type: str,
    ) -> None:
        resp = client.get(
            "/api/treasury/transactions",
            params={"type": invalid_type, "limit": 1},
        )
        assert resp.status_code == 422, (
            f"type={invalid_type!r}는 vocabulary 외 값이므로 422여야 한다. "
            f"실제: {resp.status_code} ({resp.text})"
        )
        assert spy_db.calls == [], (
            "422 거부 시 SQL이 호출되어선 안 된다 (defense-in-depth). "
            f"실제 호출: {spy_db.calls}"
        )


# ──────────────────────────────────────────────────────────────────────
# 200: 정규 5-value vocabulary 회귀.
# ──────────────────────────────────────────────────────────────────────


class TestValidVocabularyRegression:
    """5개 정규 값과 무지정 호출이 200 회귀를 유지해야 한다."""

    @pytest.mark.parametrize(
        "valid_type",
        sorted(EXPECTED_VOCABULARY),
    )
    def test_valid_type_returns_200(
        self,
        client,
        spy_db: _SpyDB,
        valid_type: str,
    ) -> None:
        resp = client.get(
            "/api/treasury/transactions",
            params={"type": valid_type},
        )
        assert resp.status_code == 200, (
            f"type={valid_type!r}는 정규 vocabulary이므로 200이어야 한다. "
            f"실제: {resp.status_code} ({resp.text})"
        )
        # SQL이 최소 한 번 호출되어야 하고, 그 안의 WHERE 인자로 정확한 type 값이
        # 전달되어야 한다 (string equality, no sanitizer mutation).
        assert spy_db.calls, "valid type은 SQL 호출이 발생해야 한다."
        all_params = [p for call in spy_db.calls for p in call.params]
        assert valid_type in all_params, (
            f"SQL params에 type={valid_type!r}가 전달되지 않았다: {all_params}"
        )

    def test_no_type_param_returns_200_without_type_filter(
        self,
        client,
        spy_db: _SpyDB,
    ) -> None:
        """type 미지정은 200을 반환하고 ``transaction_type`` WHERE 절을 추가하지
        않아야 한다 (기존 caller 회귀 보호)."""
        resp = client.get("/api/treasury/transactions")
        assert resp.status_code == 200, resp.text
        assert spy_db.calls, "SQL 호출이 한 번도 일어나지 않았다."
        for call in spy_db.calls:
            assert "transaction_type" not in call.query, (
                f"type 미지정인데 transaction_type WHERE이 추가됐다: {call.query}"
            )


# ──────────────────────────────────────────────────────────────────────
# OpenAPI live schema: ``type`` query는 5-value enum으로 노출되어야 한다.
# ──────────────────────────────────────────────────────────────────────


class TestOpenAPISchemaExposesEnum:
    """live ``/openapi.json``의 GET ``/api/treasury/transactions`` ``type`` query
    schema가 정확히 5-value enum이어야 한다.

    frontend codegen이 ``TransactionType`` 유니온을 enum 정보 없이 ``string``으로
    내보내면 contract drift이므로 본 테스트가 즉시 FAIL.
    """

    def test_type_query_schema_is_5_value_enum(self, client) -> None:
        resp = client.get("/openapi.json")
        assert resp.status_code == 200, resp.text
        spec = resp.json()
        op = spec["paths"]["/api/treasury/transactions"]["get"]
        params = {p["name"]: p for p in op.get("parameters", [])}
        assert "type" in params, "GET transactions에 type query param이 없다."

        schema = params["type"]["schema"]
        # FastAPI는 Optional[Literal[...]]를 anyOf: [{enum:[...]}, {null}]로 직렬화한다.
        enum_values: list[str] | None = None
        if "anyOf" in schema:
            for branch in schema["anyOf"]:
                if isinstance(branch, dict) and "enum" in branch:
                    enum_values = list(branch["enum"])
                    break
        elif "enum" in schema:
            enum_values = list(schema["enum"])

        assert enum_values is not None, (
            f"type query schema에서 enum 노출을 찾지 못했다: {schema}"
        )
        assert set(enum_values) == EXPECTED_VOCABULARY, (
            f"OpenAPI type enum이 정규 vocabulary와 일치하지 않는다. "
            f"openapi={sorted(enum_values)}, expected={sorted(EXPECTED_VOCABULARY)}"
        )


# ──────────────────────────────────────────────────────────────────────
# Literal type alias가 모듈 레벨에서 노출되어야 frontend 코드가 import-by-name으로
# 좁힘을 검증할 수 있다.
# ──────────────────────────────────────────────────────────────────────


def test_transaction_type_query_alias_is_importable() -> None:
    """``TransactionTypeQuery`` Literal alias가 모듈 레벨로 노출되어야 한다.

    drift-checked test가 alias를 import해 SSOT alignment를 검증할 수 있도록 한다.
    """
    from typing import get_args

    args = set(get_args(TransactionTypeQuery))
    assert args == EXPECTED_VOCABULARY
