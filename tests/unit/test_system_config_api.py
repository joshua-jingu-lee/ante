"""시스템 설정 API 테스트 (halt/activate + 동적 설정)."""

from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import AsyncMock

import pytest

httpx = pytest.importorskip("httpx", reason="httpx required for web API tests")

from fastapi.testclient import TestClient  # noqa: E402

from ante.config.dynamic import validate_value  # noqa: E402
from ante.web.app import create_app  # noqa: E402

# ── Member / Session fakes (#1373 update_config 인증 가드 추가) ──────────


@dataclass
class _FakeMember:
    member_id: str
    type: str = "human"
    role: str = "master"
    status: str = "active"
    scopes: list[str] = field(default_factory=list)


class _FakeMemberService:
    """``require_config_write`` 통과를 위한 최소 stub.

    ``master-token`` Bearer 또는 ``master-session-id`` 쿠키로 master 호출자를
    인식한다. 기존 valid update / 404 케이스는 master 인증 fixture 에 묶어
    #1373 가드와 정합시킨다.
    """

    def __init__(self) -> None:
        self._members = {
            "master-user": _FakeMember(member_id="master-user"),
            "human-admin": _FakeMember(
                member_id="human-admin", role="default", type="human"
            ),
            "agent-config": _FakeMember(
                member_id="agent-config",
                role="default",
                type="agent",
                scopes=["config:write"],
            ),
        }
        self._tokens = {
            "master-token": "master-user",
            "human-token": "human-admin",
            "agent-config-token": "agent-config",
        }

    async def authenticate(self, token: str) -> _FakeMember:
        member_id = self._tokens.get(token)
        if member_id is None:
            raise PermissionError("invalid token")
        return self._members[member_id]

    async def update_last_active(self, member_id: str) -> None:
        return None

    async def get(self, member_id: str) -> _FakeMember | None:
        return self._members.get(member_id)


class _FakeSessionService:
    def __init__(self) -> None:
        self._sessions = {
            "master-session-id": "master-user",
            "human-session-id": "human-admin",
            "agent-config-session-id": "agent-config",
        }

    async def validate(self, session_id: str) -> dict | None:
        member_id = self._sessions.get(session_id)
        if member_id is None:
            return None
        return {"member_id": member_id, "created_at": "2026-05-09 00:00:00"}


class FakeDynamicConfig:
    """테스트용 DynamicConfigService stub."""

    def __init__(self) -> None:
        self._configs: dict[str, dict] = {}

    async def get_all(self) -> list[dict]:
        return [
            {
                "key": key,
                "value": item["value"],
                "category": item["category"],
                "updated_at": "2025-01-01T00:00:00",
            }
            for key, item in self._configs.items()
        ]

    async def exists(self, key: str) -> bool:
        return key in self._configs

    async def get(self, key: str, default: object = None) -> object:
        if key in self._configs:
            return self._configs[key]["value"]
        return default

    async def set(
        self,
        key: str,
        value: object,
        category: str = "",
        changed_by: str = "",
    ) -> None:
        # 실제 DynamicConfigService.set 과 동일하게 서비스 경계에서 invariant
        # 를 검증한다 (#1379). web 라우트가 ValueError 를 422 로 매핑하는지
        # 검증하려면 fake stub 도 같은 invariant 를 강제해야 한다.
        validate_value(key, value)
        self._configs[key] = {"value": value, "category": category}


@pytest.fixture
def account_service():
    mock = AsyncMock()
    # Refs #1213: list[dict] 반환 타입 (account_id, previous_status, status, changed).
    mock.suspend_all = AsyncMock(
        return_value=[
            {
                "account_id": "domestic",
                "previous_status": "active",
                "status": "suspended",
                "changed": True,
            }
        ]
    )
    mock.activate_all = AsyncMock(
        return_value=[
            {
                "account_id": "domestic",
                "previous_status": "suspended",
                "status": "active",
                "changed": True,
            }
        ]
    )
    return mock


@pytest.fixture
def dynamic_config():
    return FakeDynamicConfig()


@pytest.fixture
def member_service():
    return _FakeMemberService()


@pytest.fixture
def session_service():
    return _FakeSessionService()


_MASTER_HEADERS = {"Authorization": "Bearer master-token"}


@pytest.fixture
def client(account_service, dynamic_config, member_service, session_service):
    app = create_app(
        account_service=account_service,
        dynamic_config=dynamic_config,
        member_service=member_service,
        session_service=session_service,
    )
    # 본 파일의 ``_FakeMemberService`` 는 ``master-token`` 만 인식한다.
    # ``RequireAuthMiddleware`` (#1403) default-deny 회귀를 막기 위해 client
    # 디폴트 헤더에 master-token 을 부착한다.
    test_client = TestClient(app)
    test_client.headers.update(_MASTER_HEADERS)
    return test_client


# ── #1373 master 인증 헤더 fixture ────────────────────────────────────────


class TestHaltClearHalt:
    """POST /api/system/halt + /api/system/clear-halt SSOT 응답 shape 검증.

    SSOT: ``docs/specs/web-api/04-system-endpoints.md`` Kill Switch 응답 SSOT.
    """

    def test_halt(self, client, account_service):
        """POST /halt로 전체 거래 중지. master 인증 필요 (#1375)."""
        resp = client.post(
            "/api/system/halt",
            json={"reason": "긴급 중지"},
            headers=_MASTER_HEADERS,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "halted"
        assert data["accounts_changed"] == 1
        assert "changed_at" in data
        assert data["accounts"] == [
            {
                "account_id": "domestic",
                "previous_status": "active",
                "status": "suspended",
                "changed": True,
            }
        ]
        account_service.suspend_all.assert_called_once()

    def test_clear_halt(self, client, account_service):
        """POST /clear-halt로 전역 정지 해제. master 인증 필요 (#1375)."""
        resp = client.post(
            "/api/system/clear-halt",
            json={"reason": "재개"},
            headers=_MASTER_HEADERS,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "halt_cleared"
        assert data["accounts_changed"] == 1
        assert "changed_at" in data
        assert data["accounts"] == [
            {
                "account_id": "domestic",
                "previous_status": "suspended",
                "status": "active",
                "changed": True,
            }
        ]
        account_service.activate_all.assert_called_once()

    def test_halt_clear_halt_lifecycle(self, client, account_service):
        """halt → clear-halt lifecycle. master 인증 필요 (#1375)."""
        resp = client.post(
            "/api/system/halt",
            json={"reason": ""},
            headers=_MASTER_HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "halted"

        resp = client.post(
            "/api/system/clear-halt",
            json={"reason": ""},
            headers=_MASTER_HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "halt_cleared"

    def test_legacy_activate_route_removed(self, client):
        """legacy POST /api/system/activate는 hard remove (SSOT 정책).

        legacy route 부재는 인증 여부와 무관하게 404 (FastAPI 가
        라우팅 단계에서 결정). 401/403 회귀와 분리된 invariant 다.
        """
        resp = client.post(
            "/api/system/activate",
            json={"reason": ""},
            headers=_MASTER_HEADERS,
        )
        assert resp.status_code == 404

    def test_legacy_kill_switch_route_absent(self, client):
        """legacy POST /api/system/kill-switch는 등록되지 않음 (SSOT 정책)."""
        resp = client.post(
            "/api/system/kill-switch",
            json={"action": "halt"},
            headers=_MASTER_HEADERS,
        )
        assert resp.status_code == 404


class TestDynamicConfig:
    def test_list_configs(self, client, dynamic_config):
        """설정 목록 조회."""
        dynamic_config._configs["risk.max_mdd"] = {
            "value": 0.1,
            "category": "risk",
        }
        resp = client.get("/api/config")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["configs"]) == 1
        assert data["configs"][0]["key"] == "risk.max_mdd"
        assert data["configs"][0]["value"] == 0.1

    def test_empty_configs(self, client):
        """빈 설정 목록."""
        resp = client.get("/api/config")
        assert resp.status_code == 200
        assert resp.json()["configs"] == []

    def test_update_config(self, client, dynamic_config):
        """설정 값 변경 (master 인증, #1373)."""
        dynamic_config._configs["risk.max_mdd"] = {
            "value": 0.1,
            "category": "risk",
        }
        resp = client.put(
            "/api/config/risk.max_mdd",
            json={"value": 0.05},
            headers=_MASTER_HEADERS,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["key"] == "risk.max_mdd"
        assert data["old_value"] == 0.1
        assert data["new_value"] == 0.05

    def test_update_config_human_succeeds(self, client, dynamic_config):
        """human 멤버 → 200 (scope 무관, spec predicate 정합, #1373)."""
        dynamic_config._configs["risk.max_mdd"] = {
            "value": 0.1,
            "category": "risk",
        }
        resp = client.put(
            "/api/config/risk.max_mdd",
            json={"value": 0.07},
            headers={"Authorization": "Bearer human-token"},
        )
        assert resp.status_code == 200
        assert resp.json()["new_value"] == 0.07

    def test_update_config_agent_with_config_write_succeeds(
        self, client, dynamic_config
    ):
        """agent + ``config:write`` ∈ scopes → 200 (#1373)."""
        dynamic_config._configs["risk.max_mdd"] = {
            "value": 0.1,
            "category": "risk",
        }
        resp = client.put(
            "/api/config/risk.max_mdd",
            json={"value": 0.08},
            headers={"Authorization": "Bearer agent-config-token"},
        )
        assert resp.status_code == 200
        assert resp.json()["new_value"] == 0.08

    def test_update_nonexistent(self, client):
        """존재하지 않는 설정 → 404 (master 인증, #1373)."""
        resp = client.put(
            "/api/config/nonexistent.key",
            json={"value": "test"},
            headers=_MASTER_HEADERS,
        )
        assert resp.status_code == 404

    # ── #1379 oracle A7: system.log_level enum 검증 ─────────────────────

    def test_config_update_invalid_log_level_returns_422(self, client, dynamic_config):
        """invalid system.log_level 값 → 422 (master 인증, #1379).

        oracle probe 가 ``ORACLE_INVALID_LEVEL`` 같은 값을 인증 토큰과 함께
        보내도 dynamic_config 가 영구 저장되어선 안 된다. 서비스 경계에서
        ``ValueError`` 가 발생하고 라우트가 이를 422 로 변환한다.
        """
        dynamic_config._configs["system.log_level"] = {
            "value": "INFO",
            "category": "system",
        }
        resp = client.put(
            "/api/config/system.log_level",
            json={"value": "ORACLE_INVALID_LEVEL"},
            headers=_MASTER_HEADERS,
        )
        assert resp.status_code == 422
        # 영구 저장은 일어나지 않아야 한다 — 기존 INFO 값이 유지.
        assert dynamic_config._configs["system.log_level"]["value"] == "INFO"

    def test_config_update_valid_log_level_succeeds(self, client, dynamic_config):
        """``_VALID_LOG_LEVELS`` 멤버(대문자) → 200 (master 인증, #1379)."""
        dynamic_config._configs["system.log_level"] = {
            "value": "INFO",
            "category": "system",
        }
        resp = client.put(
            "/api/config/system.log_level",
            json={"value": "DEBUG"},
            headers=_MASTER_HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["new_value"] == "DEBUG"
        assert dynamic_config._configs["system.log_level"]["value"] == "DEBUG"

    def test_config_update_lowercase_log_level_returns_422(
        self, client, dynamic_config
    ):
        """소문자 ``"debug"`` → 422 (대소문자 구분 정책, #1379).

        callback ``_on_log_level_changed`` 는 ``.upper()`` 정규화를 하지만
        web layer 는 사용자 입력을 그대로 검증하여 enum SSOT 와 정확
        일치만 통과시킨다. 입력 의도 변경(silent normalize)을 거부.
        """
        dynamic_config._configs["system.log_level"] = {
            "value": "INFO",
            "category": "system",
        }
        resp = client.put(
            "/api/config/system.log_level",
            json={"value": "debug"},
            headers=_MASTER_HEADERS,
        )
        assert resp.status_code == 422
        assert dynamic_config._configs["system.log_level"]["value"] == "INFO"

    def test_config_update_unknown_key_validation_skipped(self, client, dynamic_config):
        """invariant 가 정의되지 않은 키는 generic 동작 유지 (#1379).

        ``system.log_level`` 만 검증 대상이며, 다른 키는 follow-up scope.
        기존 동작이 회귀하지 않음을 잠근다.
        """
        dynamic_config._configs["risk.max_mdd"] = {
            "value": 0.1,
            "category": "risk",
        }
        resp = client.put(
            "/api/config/risk.max_mdd",
            json={"value": "anything-still-passes"},
            headers=_MASTER_HEADERS,
        )
        assert resp.status_code == 200

    # ── #1412 oracle A7: numeric finite invariant (write + read) ─────────

    @pytest.mark.parametrize(
        "raw_body",
        [
            '{"value": NaN, "category": "risk"}',
            '{"value": Infinity, "category": "risk"}',
            '{"value": -Infinity, "category": "risk"}',
        ],
    )
    def test_config_update_non_finite_numeric_returns_422(
        self, client, dynamic_config, raw_body
    ):
        """numeric NaN/Infinity/-Infinity 는 422 로 거부된다 (#1412).

        oracle probe 가 ``PUT /api/config/risk.max_mdd_pct`` body 에 NaN 을
        보내도 dynamic_config 에 영구 저장되어선 안 된다. 서비스 경계에서
        ``ValueError`` 가 발생하고 라우트가 422 로 변환한다.
        """
        dynamic_config._configs["risk.max_mdd_pct"] = {
            "value": 0.1,
            "category": "risk",
        }
        resp = client.put(
            "/api/config/risk.max_mdd_pct",
            content=raw_body,
            headers={**_MASTER_HEADERS, "Content-Type": "application/json"},
        )
        assert resp.status_code == 422
        # 영구 저장은 일어나지 않아야 한다 — 기존 0.1 값이 유지.
        assert dynamic_config._configs["risk.max_mdd_pct"]["value"] == 0.1

    def test_config_update_finite_numeric_regression(self, client, dynamic_config):
        """정상 finite numeric 값 0.1 → 200 (회귀 보존, #1412)."""
        dynamic_config._configs["risk.max_mdd_pct"] = {
            "value": 0.5,
            "category": "risk",
        }
        resp = client.put(
            "/api/config/risk.max_mdd_pct",
            json={"value": 0.1, "category": "risk"},
            headers=_MASTER_HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["new_value"] == 0.1
        assert dynamic_config._configs["risk.max_mdd_pct"]["value"] == 0.1

    def test_config_update_nan_unauth_returns_401_before_body_validation(
        self, client, dynamic_config
    ):
        """auth-first invariant: 인증 실패 + NaN body → 401 (#1412 + #1373).

        ``RequireAuthMiddleware`` 가 인증 가드를 body validation 보다 먼저
        실행해야 한다. NaN body 라도 401 이 먼저 반환되어야 한다.
        """
        dynamic_config._configs["risk.max_mdd_pct"] = {
            "value": 0.1,
            "category": "risk",
        }
        # 디폴트 master-token 헤더를 빈 헤더로 override 한다.
        resp = client.put(
            "/api/config/risk.max_mdd_pct",
            content='{"value": NaN, "category": "risk"}',
            headers={
                "Authorization": "",
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 401
        # 영구 저장도 일어나지 않아야 한다.
        assert dynamic_config._configs["risk.max_mdd_pct"]["value"] == 0.1


# ── #1412 oracle A7: read defense (legacy NaN row 격리) ─────────────────


class _FakeDynamicConfigWithReadDefense:
    """legacy NaN row 시뮬레이션을 위한 stub.

    실제 ``DynamicConfigService.get_all`` 의 read 경계에서 ConfigError 가
    발생한 상황을 재현하여, web 라우트가 422 로 변환하는지 검증한다.
    """

    def __init__(self, error_message: str) -> None:
        self._error_message = error_message

    async def get_all(self) -> list[dict]:
        from ante.config.exceptions import ConfigError

        raise ConfigError(self._error_message)


def test_list_configs_legacy_non_finite_row_returns_422(
    account_service, member_service, session_service
):
    """legacy non-finite numeric row 가 있을 때 GET /api/config → 422 (#1412).

    서비스 read 경계가 ``ConfigError`` 를 raise 하면 라우트는 이를 422
    problem+json 으로 변환한다. silent 500 폭증을 방지한다.
    """
    fake_config = _FakeDynamicConfigWithReadDefense(
        "Dynamic config의 numeric 값이 non-finite 입니다. "
        "key=risk.max_mdd_pct value=nan"
    )
    app = create_app(
        account_service=account_service,
        dynamic_config=fake_config,
        member_service=member_service,
        session_service=session_service,
    )
    test_client = TestClient(app)
    test_client.headers.update(_MASTER_HEADERS)

    resp = test_client.get("/api/config")
    assert resp.status_code == 422
    body = resp.json()
    assert "non-finite" in str(body)
