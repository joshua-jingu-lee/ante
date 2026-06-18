"""per-app_key EGW00133 cooldown at source 단위 테스트 (#2399 attempt3 + 메타 감사).

per-call-site 필터(B)가 라운드마다 "get_broker→토큰 재타격" 결함을 재생산하던
것을 발급 레이어 단일 chokepoint(A)에서 닫는 cooldown 동작을 검증한다.

핵심 불변식:
- EGW00133 1회 → 같은 app_key 후속 발급(다른 adapter/account 포함)이 cooldown 내
  **HTTP 미호출·즉시 TokenRateLimitError**(post_count 로 검증). cooldown 만료 후 재개.
- 유효 캐시 read 는 cooldown 무영향(T2 — hydrate 먼저).
- T1 single-flight(lock 밖 fast-path + lock 안 double-check), T4 단일 cadence,
  T5 classify(TokenRateLimitError)=(False,False) 불변(기존 single_flight 테스트 유지).
- runtime(_ensure_authenticated) 재발급이 cooldown 내 HTTP 미호출.
- _reset_token_cache 가 cooldown clear + 글로벌 적용(conftest 격리).
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from ante.broker import KISAdapter, TokenRateLimitError
from ante.broker.kis import (
    TOKEN_RATE_LIMIT_COOLDOWN_SECONDS,
    _record_token_cooldown,
    _reset_token_cache,
    _token_cache,
    _token_cooldown_until,
    _token_cooldowns,
)


class _FakeResponse:
    """aiohttp response 의 async-context-manager mock (토큰 발급 경로)."""

    def __init__(
        self,
        *,
        status: int = 200,
        json_body: dict[str, Any] | None = None,
        text_body: str | None = None,
    ) -> None:
        self.status = status
        self._json_body = json_body
        self._text_body = text_body

    async def __aenter__(self) -> _FakeResponse:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def json(self) -> dict[str, Any]:
        assert self._json_body is not None
        return self._json_body

    async def text(self) -> str:
        if self._text_body is not None:
            return self._text_body
        return json.dumps(self._json_body) if self._json_body is not None else ""


class _FakeSession:
    """``self._session.post(...)`` 호출 횟수(=발급 HTTP 시도)를 세는 mock session."""

    def __init__(self, responses: list[_FakeResponse]) -> None:
        self._responses = responses
        self.post_count = 0

    def post(self, *args: Any, **kwargs: Any) -> _FakeResponse:
        idx = min(self.post_count, len(self._responses) - 1)
        self.post_count += 1
        return self._responses[idx]


def _make_adapter(
    session: _FakeSession,
    *,
    app_key: str = "shared_key",
    app_secret: str = "secret_a",
    account_no: str = "1111111101",
) -> KISAdapter:
    config = {
        "app_key": app_key,
        "app_secret": app_secret,
        "account_no": account_no,
        "is_paper": True,
    }
    adapter = KISAdapter(config)
    adapter._session = session  # type: ignore[assignment]
    return adapter


def _egw00133_response() -> _FakeResponse:
    return _FakeResponse(
        status=403,
        json_body={"msg_cd": "EGW00133", "msg1": "접근토큰 발급 잠시 후 다시 시도"},
    )


def _success_response(token: str = "tok-1") -> _FakeResponse:
    return _FakeResponse(status=200, json_body={"access_token": token})


# attempt4 P2: ``_token_cache`` 키는 config fingerprint (app_key, app_secret, env)다.
# 기본 _make_adapter config(secret_a, is_paper=True)의 fingerprint.
_DEFAULT_CACHE_KEY = ("shared_key", "secret_a", "paper")


# ── cooldown 핵심: EGW00133 1회 → 후속 발급 차단(HTTP 미호출) ────────────


class TestCooldownAtSource:
    async def test_egw00133_records_cooldown_and_blocks_subsequent_issue(self) -> None:
        """EGW00133 1회 → 같은 app_key 후속 발급(다른 adapter)이 HTTP 미호출 차단."""
        # 첫 adapter: EGW00133 1회 → cooldown 기록.
        s1 = _FakeSession([_egw00133_response()])
        a1 = _make_adapter(s1, account_no="acct-A")
        with pytest.raises(TokenRateLimitError):
            await a1._authenticate()
        assert s1.post_count == 1  # 발급 HTTP 1회 시도(거절).
        # cooldown 이 기록됐다.
        assert _token_cooldown_until("shared_key") is not None

        # 같은 app_key 두 번째 adapter(다른 account) — cooldown 내라 HTTP 미호출.
        s2 = _FakeSession([_success_response("tok-should-not-issue")])
        a2 = _make_adapter(s2, account_no="acct-B")
        with pytest.raises(TokenRateLimitError):
            await a2._authenticate()
        # 핵심: 두 번째 adapter 는 발급 HTTP 를 **전혀** 시도하지 않았다.
        assert s2.post_count == 0
        assert a2.access_token is None

    async def test_cooldown_blocked_raise_carries_cooldown_until(self) -> None:
        """cooldown 내 차단 raise 는 기존 cooldown_until 을 동봉(연장 금지)."""
        until = _record_token_cooldown("shared_key")
        s = _FakeSession([_success_response()])
        a = _make_adapter(s, account_no="acct-B")
        with pytest.raises(TokenRateLimitError) as ei:
            await a._authenticate()
        assert s.post_count == 0
        # 기존 cooldown_until 을 그대로 노출(연장하지 않음).
        assert ei.value.cooldown_until == until
        assert ei.value.error_code == "EGW00133"

    async def test_cooldown_expiry_reopens_issue(self) -> None:
        """cooldown 만료 후 같은 app_key 발급 1회 재개."""
        # 이미 만료된 cooldown 을 직접 심는다(과거 시각).
        _token_cooldowns["shared_key"] = datetime.now(UTC) - timedelta(seconds=1)
        # 만료된 cooldown 은 None 으로 보고된다(자동 만료).
        assert _token_cooldown_until("shared_key") is None

        s = _FakeSession([_success_response("tok-reopen")])
        a = _make_adapter(s, account_no="acct-A")
        await a._authenticate()
        # 만료됐으므로 발급 1회 정상 진행.
        assert s.post_count == 1
        assert a.access_token == "tok-reopen"

    async def test_cooldown_duration_matches_constant(self) -> None:
        """기록된 cooldown 만료시각이 상수(60s) 근처(±2s)."""
        before = datetime.now(UTC)
        until = _record_token_cooldown("shared_key")
        delta = (until - before).total_seconds()
        assert (
            TOKEN_RATE_LIMIT_COOLDOWN_SECONDS - 2
            <= delta
            <= (TOKEN_RATE_LIMIT_COOLDOWN_SECONDS + 2)
        )


# ── T2: 유효 캐시 read 는 cooldown 무영향 ──────────────────


class TestCooldownDoesNotBlockValidCache:
    async def test_valid_cache_used_during_cooldown(self) -> None:
        """cooldown 중에도 유효 캐시 토큰 보유 adapter 는 정상 사용(발급 없음, T2)."""
        # 유효(신선) 캐시 토큰 + cooldown 동시 존재.
        _token_cache[_DEFAULT_CACHE_KEY] = (
            "tok-cached",
            datetime.now(UTC) + timedelta(hours=1),
        )
        _record_token_cooldown("shared_key")

        s = _FakeSession([_success_response("tok-should-not-issue")])
        a = _make_adapter(s, account_no="acct-A")
        # hydrate 가 cooldown 체크보다 먼저라 캐시 hit → 발급 skip, raise 없음.
        await a._authenticate()
        assert s.post_count == 0
        assert a.access_token == "tok-cached"

    async def test_ensure_authenticated_valid_cache_during_cooldown(self) -> None:
        """_ensure_authenticated 도 cooldown 중 유효 캐시 hit 시 발급 skip(T2)."""
        _token_cache[_DEFAULT_CACHE_KEY] = (
            "tok-cached",
            datetime.now(UTC) + timedelta(hours=1),
        )
        _record_token_cooldown("shared_key")

        s = _FakeSession([_success_response("tok-should-not-issue")])
        a = _make_adapter(s, account_no="acct-B")
        await a._ensure_authenticated()
        assert s.post_count == 0
        assert a.access_token == "tok-cached"


# ── runtime/IPC: _ensure_authenticated 재발급이 cooldown 내 HTTP 미호출 ──


class TestRuntimeReissueRespectsCooldown:
    async def test_ensure_authenticated_reissue_blocked_by_cooldown(self) -> None:
        """near-expiry 토큰의 runtime 재발급이 cooldown 내면 HTTP 미호출 차단."""
        _record_token_cooldown("shared_key")
        s = _FakeSession([_success_response("tok-new")])
        a = _make_adapter(s, account_no="acct-A")
        # 인스턴스에 near-expiry 토큰을 심어 _ensure_authenticated 가 재발급 경로 진입.
        a.access_token = "tok-old"
        a.token_expires_at = datetime.now(UTC) + timedelta(minutes=2)

        with pytest.raises(TokenRateLimitError):
            await a._ensure_authenticated()
        # 재발급 HTTP 미호출(cooldown source-level 차단).
        assert s.post_count == 0


# ── T1: single-flight 와 cooldown 상호작용(lock 안 double-check) ──────────


class TestSingleFlightCooldownInteraction:
    async def test_concurrent_authenticate_one_egw00133_blocks_rest(self) -> None:
        """동시 _authenticate N개 중 첫 발급 EGW00133 → 나머지 lock 안 cooldown 차단.

        single-flight lock 으로 1개만 HTTP 발급(EGW00133)하고, lock 대기하던 나머지는
        double-check 에서 cooldown 을 만나 추가 HTTP 없이 raise 한다(post_count==1).
        """
        # 모든 post 가 EGW00133 을 반환(첫 발급이 거절).
        session = _FakeSession([_egw00133_response()])
        adapters = [_make_adapter(session, account_no=f"acct-{i}") for i in range(5)]

        results = await asyncio.gather(
            *(a._authenticate() for a in adapters), return_exceptions=True
        )
        # 5개 모두 TokenRateLimitError.
        assert all(isinstance(r, TokenRateLimitError) for r in results)
        # 핵심: 발급 HTTP 는 1회만(single-flight + cooldown double-check).
        assert session.post_count == 1


# ── attempt3-b: self-healing burst 같은 app_key N계좌 → 발급 1회 ───────────


class TestSelfHealingBurstCooldown:
    async def test_same_app_key_multi_account_issues_once(self) -> None:
        """같은 app_key N계좌 순차 인증 → 첫 EGW00133 후 나머지 HTTP 미호출(cooldown).

        self-healing burst 가 같은 app_key 의 여러 계좌를 순차로 인증할 때, 첫
        계좌가 EGW00133 으로 cooldown 을 기록하면 나머지 계좌의 발급은 발급
        레이어가 HTTP 미호출·즉시 raise 한다(토큰 1/min 재타격 없음, 발급 시도 1회).
        ``_authenticate`` 는 connect 의 발급 경로 핵심이므로 동등한 source-level
        cooldown 을 직접 검증한다(connect 가 mock session 을 실 aiohttp session 으로
        덮어쓰는 것을 피해 _authenticate 를 직접 호출).
        """
        # 같은 app_key, 다른 account_no 3계좌. session 은 EGW00133 만 반환.
        session = _FakeSession([_egw00133_response()])
        adapters = [
            _make_adapter(session, app_key="burst_key", account_no=f"acct-{i}")
            for i in range(3)
        ]

        raised = 0
        for a in adapters:
            with pytest.raises(TokenRateLimitError):
                await a._authenticate()
            raised += 1
        assert raised == 3
        # 핵심: 발급 HTTP 는 첫 계좌 1회뿐(나머지는 cooldown 으로 HTTP 미호출).
        assert session.post_count == 1
        assert _token_cooldown_until("burst_key") is not None


# ── _reset_token_cache: cooldown clear + 글로벌 격리 ───────────────────────


class TestResetClearsCooldown:
    def test_reset_clears_cooldown(self) -> None:
        """_reset_token_cache 가 _token_cooldowns 도 clear (글로벌 conftest 격리)."""
        _record_token_cooldown("shared_key")
        _token_cache[_DEFAULT_CACHE_KEY] = ("t", datetime.now(UTC) + timedelta(hours=1))
        assert _token_cooldowns
        _reset_token_cache()
        assert _token_cooldowns == {}
        assert _token_cache == {}

    def test_global_conftest_isolates_cooldown(self) -> None:
        """글로벌 conftest autouse fixture 가 테스트 진입 시 cooldown 을 비운다.

        이전 테스트가 cooldown 을 남겼더라도 본 테스트 진입 시점엔 비어 있어야 한다
        (cross-test 오염 차단). 본 테스트는 진입 직후 상태만 관측한다.
        """
        assert _token_cooldowns == {}
