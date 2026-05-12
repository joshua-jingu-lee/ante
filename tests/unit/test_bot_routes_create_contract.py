"""POST /api/bots — BotCreateRequest contract drift 회귀 (#1436).

배경:
    - ``BotCreateRequest``가 Pydantic ``extra='forbid'``를 선언하지 않아
      legacy ``bot_type`` 같은 미정의 키가 silent하게 무시됐다.
    - ``strategy_id`` 또는 ``strategy_name`` 필수 조건이 handler 런타임 422
      (L349-352)로만 표현되어 OpenAPI/Pydantic 스키마에 드러나지 않았다.
    - OpenAPI ``BOT_CREATE_REQUEST_SCHEMA``에 ``additionalProperties: false``가
      없어 frontend codegen이 strict contract을 받지 못했다.

본 모듈은 다음을 보장한다:
    1. extra key (``bot_type`` 포함)는 422로 거부된다.
    2. ``strategy_id``/``strategy_name`` 둘 다 None이면 422 (Pydantic 단계).
    3. ``strategy_id`` 단독, ``strategy_name`` 단독, 둘 다 전달 모두 정상 처리.
       둘 다 전달 시 handler가 ``strategy_id``를 우선 사용한다.
    4. OpenAPI 스키마는 ``additionalProperties: False``로 노출된다.
    5. (codex r3 FAIL) ``_require_strategy_identifier`` model_validator 가
       raise 하는 ``ValueError`` 는 ``e.errors()`` 의 ``ctx.error`` 에
       ``ValueError`` 객체로 노출되는데, ``HTTPException(detail=e.errors())``
       그대로 사용 시 ``str(detail)`` 경로에서 ``ValueError('...')`` Python
       repr 이 응답 body 에 새어 나간다. handler 는
       ``e.errors(include_context=False, include_input=False)`` 로
       sanitize 해야 한다.

Non-Goals:
    - generated TS ``BotCreateRequest`` union narrowing (OpenAPI ``anyOf +
      required`` 조합의 표현 한계로 첫 union arm 이 strategy 없이 valid
      로 인식되는 SDK 거동) 는 별도 follow-up 이슈로 다룬다. 본 PR 범위에서
      는 런타임 422 와 ``additionalProperties: false`` / ``anyOf`` 스키마
      contract 노출까지만 보장한다.
"""

from __future__ import annotations

import pytest

httpx = pytest.importorskip("httpx", reason="httpx required for web API tests")

from fastapi.testclient import TestClient  # noqa: E402

from ante.web.app import create_app  # noqa: E402
from ante.web.routes.bots import (  # noqa: E402
    BOT_CREATE_REQUEST_SCHEMA,
    BotCreateRequest,
)

# 기존 테스트 파일의 Fake 들을 재사용한다 — budget_error 테스트와 동일 패턴.
from tests.unit.test_bot_api import (  # noqa: E402
    _MASTER_HEADERS,
    FakeAccount,
    FakeAccountService,
    FakeBotManager,
    FakeStrategyRecord,
    FakeStrategyRegistry,
    _new_member_service,
)


@pytest.fixture(autouse=True)
def _mock_strategy_loader(monkeypatch):
    """StrategyLoader.load 모킹 — 파일 시스템 의존 제거."""

    class _FakeStrategy:
        pass

    monkeypatch.setattr(
        "ante.strategy.loader.StrategyLoader.load",
        staticmethod(lambda path: _FakeStrategy),
    )


@pytest.fixture
def bot_manager() -> FakeBotManager:
    return FakeBotManager()


@pytest.fixture
def account_service() -> FakeAccountService:
    svc = FakeAccountService()
    svc._accounts["test"] = FakeAccount(
        "test",
        status="active",
        credentials={"app_key": "test-key", "app_secret": "test-secret"},
    )
    return svc


@pytest.fixture
def strategy_registry() -> FakeStrategyRegistry:
    reg = FakeStrategyRegistry()
    reg._strategies["s1"] = FakeStrategyRecord("s1", name="s1")
    reg._strategies["s2"] = FakeStrategyRecord("s2", name="other-strategy")
    return reg


@pytest.fixture
def client(bot_manager, account_service, strategy_registry) -> TestClient:
    app = create_app(
        bot_manager=bot_manager,
        account_service=account_service,
        strategy_registry=strategy_registry,
        member_service=_new_member_service(),
    )
    c = TestClient(app)
    c.headers.update(_MASTER_HEADERS)
    return c


class TestBotCreateRequestExtraForbid:
    """Pydantic ``extra='forbid'`` — 미정의 키는 422 거부 (#1436)."""

    def test_legacy_bot_type_key_returns_422(self, client) -> None:
        """``bot_type``은 ``manager.py:124-125``에서 이미 silently 제거됐다.
        이제 schema 단계에서 명시적으로 422 거부된다."""
        resp = client.post(
            "/api/bots",
            json={
                "bot_id": "bot-x",
                "bot_type": "paper",  # legacy — 거부 대상
                "strategy_name": "s1",
                "account_id": "test",
            },
        )
        assert resp.status_code == 422

    def test_unknown_extra_key_returns_422(self, client) -> None:
        """임의 미정의 키도 거부."""
        resp = client.post(
            "/api/bots",
            json={
                "bot_id": "bot-x",
                "strategy_id": "s1",
                "unknown_field": "anything",
                "account_id": "test",
            },
        )
        assert resp.status_code == 422


class TestBotCreateRequestStrategyRequired:
    """strategy_id OR strategy_name 필수 — Pydantic ``model_validator`` 단계 422."""

    def test_no_strategy_identifier_returns_422(self, client) -> None:
        """둘 다 None이면 Pydantic이 사전 차단."""
        resp = client.post(
            "/api/bots",
            json={"bot_id": "bot-x", "account_id": "test"},
        )
        assert resp.status_code == 422
        # detail에 strategy 요구 메시지 포함 — Pydantic ValidationError 직렬화
        detail_blob = str(resp.json().get("detail", ""))
        assert "strategy_id" in detail_blob and "strategy_name" in detail_blob, (
            f"detail must mention strategy_id/strategy_name; got {detail_blob!r}"
        )

    def test_null_strategy_identifier_returns_422(self, client) -> None:
        """둘 다 명시적으로 null이면 동일하게 거부."""
        resp = client.post(
            "/api/bots",
            json={
                "bot_id": "bot-x",
                "strategy_id": None,
                "strategy_name": None,
                "account_id": "test",
            },
        )
        assert resp.status_code == 422

    def test_strategy_id_only_succeeds(self, client) -> None:
        """``strategy_id`` 단독 전달 — 정상 201."""
        resp = client.post(
            "/api/bots",
            json={
                "bot_id": "bot-id-only",
                "strategy_id": "s1",
                "account_id": "test",
            },
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["bot"]["bot_id"] == "bot-id-only"

    def test_strategy_name_only_succeeds(self, client) -> None:
        """``strategy_name`` 단독 전달 — registry 변환 후 정상 201."""
        resp = client.post(
            "/api/bots",
            json={
                "bot_id": "bot-name-only",
                "strategy_name": "s1",
                "account_id": "test",
            },
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["bot"]["bot_id"] == "bot-name-only"

    def test_both_strategy_identifiers_succeeds_id_wins(
        self, client, bot_manager
    ) -> None:
        """둘 다 전달 — Pydantic 통과하고 handler가 strategy_id를 우선 사용.

        ``strategy_id="s1"`` + ``strategy_name="other-strategy"``(s2 매핑)를 보낸다.
        handler가 strategy_id 우선이면 생성된 봇의 strategy_id가 "s1"이어야 한다.
        """
        resp = client.post(
            "/api/bots",
            json={
                "bot_id": "bot-both",
                "strategy_id": "s1",
                "strategy_name": "other-strategy",
                "account_id": "test",
            },
        )
        assert resp.status_code == 201, resp.text
        info = resp.json()["bot"]
        # handler L339-348 — strategy_id 가 None 이 아닐 때 strategy_name 분기를 skip
        assert info["strategy_id"] == "s1", (
            "strategy_id가 우선되어야 하지만 strategy_name이 우선되었음"
        )


class TestBotCreateRequestSchema:
    """OpenAPI 스키마 노출."""

    def test_schema_has_additional_properties_false(self) -> None:
        """frontend codegen이 strict contract을 받도록 노출."""
        assert BOT_CREATE_REQUEST_SCHEMA.get("additionalProperties") is False

    def test_pydantic_model_config_extra_forbid(self) -> None:
        """SSOT 정합 — Pydantic 모델 자체가 extra='forbid'."""
        assert BotCreateRequest.model_config.get("extra") == "forbid"

    def test_schema_has_any_of_strategy_identifier(self) -> None:
        """codex r1/r2 FAIL 회귀 — OpenAPI ``anyOf`` 로 strategy_id/strategy_name
        둘 중 하나 필수 조건이 표현되어야 한다.

        ``required: [bot_id]`` 만 노출된 상태로는 generated TS/SDK 가
        ``{bot_id: ...}`` payload 를 valid 로 인식하여 contract drift 가
        다시 발생한다. (r1)

        anyOf branches 는 ``type: object`` 와 ``properties`` 까지 명시되어야
        openapi-typescript 가 ``unknown`` 으로 붕괴되지 않고
        ``{strategy_id: string} | {strategy_name: string}`` 으로 narrow 된다.
        (r2)
        """
        any_of = BOT_CREATE_REQUEST_SCHEMA.get("anyOf")
        assert isinstance(any_of, list) and len(any_of) == 2, (
            f"anyOf must list two branches; got {any_of!r}"
        )
        required_sets = {tuple(sorted(branch.get("required", []))) for branch in any_of}
        assert ("strategy_id",) in required_sets, (
            f"anyOf must require strategy_id in one branch; got {required_sets!r}"
        )
        assert ("strategy_name",) in required_sets, (
            f"anyOf must require strategy_name in one branch; got {required_sets!r}"
        )

    def test_schema_any_of_branches_have_type_and_properties(self) -> None:
        """codex r2 FAIL 회귀 — anyOf 각 branch 는 ``type: object`` 와
        ``properties`` (해당 strategy 필드 schema) 를 명시해야 한다.

        빈 ``required`` 만 있는 branch 는 openapi-typescript 가 ``unknown``
        으로 표현하여 ``BotCreateRequest = unknown`` 으로 붕괴된다 — SDK
        차단 효과가 사라진다.
        """
        any_of = BOT_CREATE_REQUEST_SCHEMA["anyOf"]
        # strategy_id branch
        sid_branch = next(b for b in any_of if "strategy_id" in b.get("required", []))
        assert sid_branch.get("type") == "object", (
            f"strategy_id branch must declare type=object; got {sid_branch!r}"
        )
        sid_props = sid_branch.get("properties")
        assert isinstance(sid_props, dict) and "strategy_id" in sid_props, (
            f"strategy_id branch must include properties.strategy_id; "
            f"got {sid_branch!r}"
        )
        assert sid_props["strategy_id"].get("type") == "string", (
            f"strategy_id branch property must be typed as string; "
            f"got {sid_props['strategy_id']!r}"
        )
        # strategy_name branch
        sname_branch = next(
            b for b in any_of if "strategy_name" in b.get("required", [])
        )
        assert sname_branch.get("type") == "object", (
            f"strategy_name branch must declare type=object; got {sname_branch!r}"
        )
        sname_props = sname_branch.get("properties")
        assert isinstance(sname_props, dict) and "strategy_name" in sname_props, (
            f"strategy_name branch must include properties.strategy_name; "
            f"got {sname_branch!r}"
        )
        assert sname_props["strategy_name"].get("type") == "string", (
            f"strategy_name branch property must be typed as string; "
            f"got {sname_props['strategy_name']!r}"
        )

    def test_openapi_components_schema_exposes_any_of(self, client) -> None:
        """frontend codegen 입력인 ``/openapi.json`` 에서 ``anyOf`` 가 그대로
        노출되어 generated TS 타입이 strategy_id/strategy_name 중 하나를
        필수로 표현해야 한다.

        codex r2: 각 branch 의 ``type``/``properties`` 까지 노출되어야
        openapi-typescript 가 narrow 한 union 으로 생성한다.
        """
        resp = client.get("/openapi.json")
        assert resp.status_code == 200
        spec = resp.json()
        schema = spec.get("components", {}).get("schemas", {}).get("BotCreateRequest")
        assert schema is not None, (
            "BotCreateRequest must be registered in components.schemas"
        )
        any_of = schema.get("anyOf")
        assert isinstance(any_of, list) and len(any_of) == 2, (
            f"components.schemas.BotCreateRequest.anyOf must list two branches; "
            f"got {any_of!r}"
        )
        required_sets = {tuple(sorted(branch.get("required", []))) for branch in any_of}
        assert {("strategy_id",), ("strategy_name",)} == required_sets, (
            f"anyOf branches must require strategy_id and strategy_name "
            f"separately; got {required_sets!r}"
        )
        # codex r2: type/properties 까지 노출 검증
        for branch in any_of:
            assert branch.get("type") == "object", (
                f"openapi.json anyOf branch must declare type=object; got {branch!r}"
            )
            props = branch.get("properties")
            required = branch.get("required", [])
            assert isinstance(props, dict) and props, (
                f"openapi.json anyOf branch must declare non-empty properties; "
                f"got {branch!r}"
            )
            # 해당 branch 의 required 필드가 properties 안에 string 타입으로 있어야 함
            for field in required:
                assert field in props, (
                    f"openapi.json anyOf branch required field {field!r} "
                    f"must be present in properties; got {branch!r}"
                )
                assert props[field].get("type") == "string", (
                    f"openapi.json anyOf branch property {field!r} must be "
                    f"typed as string; got {props[field]!r}"
                )

    def test_pydantic_model_validator_rejects_missing_strategy(self) -> None:
        """모델 단위에서도 strategy 필수 — handler 우회 호출자도 차단된다."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError) as exc_info:
            BotCreateRequest.model_validate({"bot_id": "x"})
        msg = str(exc_info.value)
        assert "strategy_id" in msg and "strategy_name" in msg

    def test_pydantic_model_validator_accepts_strategy_id(self) -> None:
        model = BotCreateRequest.model_validate({"bot_id": "x", "strategy_id": "s1"})
        assert model.strategy_id == "s1"
        assert model.strategy_name is None

    def test_pydantic_model_validator_accepts_strategy_name(self) -> None:
        model = BotCreateRequest.model_validate({"bot_id": "x", "strategy_name": "s1"})
        assert model.strategy_name == "s1"
        assert model.strategy_id is None

    def test_pydantic_model_validator_accepts_both(self) -> None:
        """둘 다 전달은 OK — handler가 id 우선."""
        model = BotCreateRequest.model_validate(
            {"bot_id": "x", "strategy_id": "s1", "strategy_name": "s1-name"}
        )
        assert model.strategy_id == "s1"
        assert model.strategy_name == "s1-name"

    def test_pydantic_rejects_extra_keys(self) -> None:
        """SSOT 정합 — model_validate 단계에서도 거부."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            BotCreateRequest.model_validate(
                {"bot_id": "x", "strategy_id": "s1", "bot_type": "paper"}
            )


class TestBotCreateValidationErrorSerialization:
    """codex r3 FAIL 회귀 — ``ValidationError`` detail 이 JSON 직렬화 안전한
    형태로 노출되는지 보장한다.

    배경:
        - ``BotCreateRequest._require_strategy_identifier`` model_validator
          가 ``raise ValueError(...)`` 하면 Pydantic ``e.errors()`` 가
          ``ctx.error`` 필드에 ``ValueError`` 객체를 그대로 노출한다.
        - ``HTTPException(detail=e.errors())`` 를 그대로 사용하면 FastAPI/
          Starlette 가 detail 을 stringify 할 때 ``ValueError('...')`` 형태의
          Python repr 이 응답 body 에 포함되어 호출자가 구조적으로 파싱할
          수 없는 깨진 detail 이 된다. ``input`` 에 NaN/Inf 가 들어오면
          ``allow_nan=False`` JSONResponse 가 직렬화에 실패해 500 으로
          잘못 표면화될 수 있는 risk 도 있다.
        - Fix: handler 에서 ``e.errors(include_context=False,
          include_input=False)`` 사용으로 ctx/input 을 sanitize 한다
          (#1380 ``accounts.py`` ``RuleUpdateRequest`` 선례와 동일 패턴).
    """

    def test_missing_strategy_returns_422_without_valueerror_repr(self, client) -> None:
        """``{bot_id: x}`` 만 전달 — model_validator 가 ``ValueError`` 를
        raise 한다. 응답은 422 이고 detail 에 ``ValueError(`` 같은 Python
        repr 이 노출되지 않아야 한다 (codex r3 FAIL 회귀)."""
        resp = client.post(
            "/api/bots",
            json={"bot_id": "bot-x", "account_id": "test"},
        )
        # 1. 500 이 아닌 422 (가장 핵심: detail 직렬화 실패로 인한 500 회귀 방지).
        assert resp.status_code == 422, (
            f"detail 직렬화 실패로 500 이 반환됨 — codex r3 FAIL 회귀. "
            f"status={resp.status_code} body={resp.text!r}"
        )
        # 2. content-type 은 application/problem+json (RFC 7807).
        assert resp.headers.get("content-type", "").startswith(
            "application/problem+json"
        ), f"content-type 깨짐 — {resp.headers.get('content-type')!r}"
        # 3. body 가 JSON 정상 파싱 가능.
        body = resp.json()
        # 4. detail 에 Pydantic ctx.error 의 ``ValueError(...)`` Python repr
        #    이 노출되어서는 안 된다. ``include_context=False`` 가 적용되면
        #    ``ctx`` 키 자체가 제거되어 ``ValueError(`` substring 도 사라진다.
        detail_blob = str(body.get("detail", ""))
        assert "ValueError(" not in detail_blob, (
            f"detail 에 ValueError(...) Python repr 노출 — codex r3 FAIL "
            f"회귀. detail={detail_blob!r}"
        )
        # 5. detail 에 strategy 요구 메시지가 포함되어 호출자가 원인을 알 수 있어야 함.
        assert "strategy_id" in detail_blob and "strategy_name" in detail_blob, (
            f"detail 에서 strategy 메시지 사라짐 — {detail_blob!r}"
        )

    def test_extra_field_returns_422_with_clean_detail(self, client) -> None:
        """``extra='forbid'`` 케이스에서도 detail 이 깨끗하게 직렬화된다.
        (이 케이스는 ctx 가 None 이라 기본 동작도 안전하지만,
        ``include_context=False`` 적용 후에도 회귀 없이 동작함을 검증.)"""
        resp = client.post(
            "/api/bots",
            json={
                "bot_id": "bot-x",
                "strategy_id": "s1",
                "account_id": "test",
                "bot_type": "paper",  # extra='forbid' 거부
            },
        )
        assert resp.status_code == 422, resp.text
        body = resp.json()
        detail_blob = str(body.get("detail", ""))
        # ``extra='forbid'`` 에러 메시지 또는 키 이름이 detail 에 포함되어야 함.
        assert "bot_type" in detail_blob or "extra" in detail_blob.lower(), (
            f"detail 에 거부 사유가 없음 — {detail_blob!r}"
        )
        # ValueError repr leak 없음.
        assert "ValueError(" not in detail_blob
