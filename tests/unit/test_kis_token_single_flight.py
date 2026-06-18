"""KIS OAuth2 토큰 single-flight + shared cache + EGW00133 backoff 단위 테스트.

#2399 (축 iii) invariant T1–T7:
- T1 single-flight, lock key=app_key (account_id 아님) + double-check.
- T2 in-process shared cache + near-expiry(5분) miss.
- T3 토큰 발급 응답 msg_cd/error_code alias 파싱 (200+body / non-200 양 분기).
- T4 단일 cadence: ``_authenticate`` 내부 sleep 없이 EGW00133 즉시 raise.
- T5 classify(AuthenticationError)=(False,False) 불변 + EGW00133 ∉ TRANSIENT.
- T6 reason 구조적 보존(error_code).
- T7 known-limitation(멀티프로세스) — 주석/스펙 anchor.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

import ante.broker.kis as kis_mod
from ante.broker import KISAdapter, TokenRateLimitError
from ante.broker.error_codes import (
    TOKEN_RATE_LIMIT_MSG_CODE,
    TRANSIENT_MSG_CODES,
    get_error_message,
    is_retryable_msg_code,
)
from ante.broker.exceptions import AuthenticationError
from ante.broker.kis import (
    KISErrorClassifier,
    _is_cached_token_fresh,
    _record_token_cooldown,
    _reset_token_cache,
    _token_cache,
    _token_cooldowns,
    _token_locks,
)

KIS_CONFIG = {
    "app_key": "shared_key",
    "app_secret": "secret_a",
    "account_no": "1111111101",
    "is_paper": True,
}

# attempt4 P2: ``_token_cache`` 키는 config fingerprint (app_key, app_secret, env)다.
# 기존 테스트가 직접 캐시를 조회/주입할 때 쓰는 기본 config 의 fingerprint.
_DEFAULT_CACHE_KEY = ("shared_key", "secret_a", "paper")


@pytest.fixture(autouse=True)
def _reset_module_token_cache():
    """매 테스트 전후 module-level 토큰 캐시/lock dict 초기화 (T1 closed-loop/T2 격리).

    pytest-asyncio auto mode 에서 이전 테스트의 closed event loop 에 묶인 Lock 이
    재사용되지 않도록, 그리고 shared 캐시가 테스트 간 오염되지 않도록 격리한다.
    """
    _reset_token_cache()
    yield
    _reset_token_cache()


# ── 토큰 발급 HTTP 응답 mock ───────────────────────────────


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
    """``self._session.post(...)`` 호출 횟수를 세는 mock session.

    매 호출마다 ``responses`` 큐에서 하나를 pop 한다(소진 시 마지막 반복). post
    호출 횟수(=토큰 발급 HTTP 시도)는 ``post_count`` 로 관측한다.
    """

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


def _success_response(token: str = "tok-1") -> _FakeResponse:
    return _FakeResponse(status=200, json_body={"access_token": token})


# ── T1: single-flight, lock key=app_key ────────────────────


class TestSingleFlight:
    async def test_concurrent_same_app_key_issues_once(self):
        """동일 app_key 다중 adapter 동시 _authenticate → HTTP 발급 1회 수렴 (T1)."""
        session = _FakeSession([_success_response("tok-shared")])
        # 동일 app_key, 서로 다른 account_no(=다른 adapter 인스턴스).
        adapters = [_make_adapter(session, account_no=f"acct-{i}") for i in range(5)]

        await asyncio.gather(*(a._authenticate() for a in adapters))

        # single-flight: 5개 동시 발급이 HTTP 발급 1회로 수렴.
        assert session.post_count == 1
        # 모든 adapter 가 동일 토큰으로 hydrate.
        assert all(a.access_token == "tok-shared" for a in adapters)

    async def test_lock_key_is_app_key_not_account_id(self):
        """lock key 회귀 락: 다른 account 라도 동일 app_key 면 공유 캐시로 수렴 (T1).

        만약 lock/캐시 key 를 account_id 로 잘못 잡으면 동일 app_key 다른 account
        adapter 가 미수렴하여 발급 2회 이상 → 이 테스트가 잡는다.
        """
        session = _FakeSession([_success_response("tok-shared")])
        a1 = _make_adapter(session, account_no="acct-A")
        a2 = _make_adapter(session, account_no="acct-B")

        await asyncio.gather(a1._authenticate(), a2._authenticate())

        assert session.post_count == 1
        # lock dict 키가 app_key 인지 직접 확인(account_id 아님 — rate-limit 단위).
        assert set(_token_locks.keys()) == {"shared_key"}
        # 캐시 dict 키는 config fingerprint(app_key+secret+env) — 같은 config 1개 키.
        assert set(_token_cache.keys()) == {_DEFAULT_CACHE_KEY}

    async def test_different_app_keys_issue_separately(self):
        """다른 app_key 는 각각 발급(lock/캐시 분리) — single-flight 가 과수렴 안 함."""
        s1 = _FakeSession([_success_response("tok-1")])
        s2 = _FakeSession([_success_response("tok-2")])
        a1 = _make_adapter(s1, app_key="key-1")
        a2 = _make_adapter(s2, app_key="key-2")

        await asyncio.gather(a1._authenticate(), a2._authenticate())

        assert s1.post_count == 1
        assert s2.post_count == 1
        assert a1.access_token == "tok-1"
        assert a2.access_token == "tok-2"

    async def test_double_check_reuses_cache_after_lock(self):
        """lock 대기 중 타 코루틴이 발급했으면 double-check 재사용(추가 발급 없음)."""
        session = _FakeSession([_success_response("tok-shared")])
        a1 = _make_adapter(session, account_no="acct-A")
        a2 = _make_adapter(session, account_no="acct-B")

        # 첫 발급.
        await a1._authenticate()
        assert session.post_count == 1
        # 두 번째 adapter 는 캐시 hit → 발급 skip(fast-path). lock 안 double-check
        # 경로도 보장된다(아래 closed-loop/재사용 테스트가 lock 경로를 직접 잠근다).
        await a2._authenticate()
        assert session.post_count == 1
        assert a2.access_token == "tok-shared"


# ── T2: in-process shared cache + near-expiry miss ─────────


class TestSharedCache:
    async def test_second_adapter_cache_hit_skips_issue(self):
        """2번째 adapter 는 shared 캐시 hit 으로 발급 skip (T2)."""
        session = _FakeSession([_success_response("tok-shared")])
        a1 = _make_adapter(session, account_no="acct-A")
        await a1._authenticate()
        assert session.post_count == 1

        a2 = _make_adapter(session, account_no="acct-B")
        await a2._authenticate()
        assert session.post_count == 1  # 재발급 없음
        assert a2.access_token == "tok-shared"

    async def test_near_expiry_token_is_cache_miss(self):
        """만료 5분 전 토큰은 cache miss → 재발급 (_ensure_authenticated 기준, T2)."""
        session = _FakeSession([_success_response("tok-new")])
        # near-expiry: 만료까지 3분 남음(5분 여유보다 짧음) → miss.
        _token_cache[_DEFAULT_CACHE_KEY] = (
            "tok-old",
            datetime.now(UTC) + timedelta(minutes=3),
        )
        adapter = _make_adapter(session)

        await adapter._authenticate()

        # near-expiry 라 재발급됨.
        assert session.post_count == 1
        assert adapter.access_token == "tok-new"
        assert _token_cache[_DEFAULT_CACHE_KEY][0] == "tok-new"

    def test_is_cached_token_fresh_boundary(self):
        """_is_cached_token_fresh: 만료 5분 전 경계 — near-expiry miss 회귀 락 (T2)."""
        now = datetime(2026, 1, 1, tzinfo=UTC)
        # 만료까지 6분 → 신선(여유 5분 초과).
        assert _is_cached_token_fresh(now + timedelta(minutes=6), now=now) is True
        # 만료까지 4분 → near-expiry miss.
        assert _is_cached_token_fresh(now + timedelta(minutes=4), now=now) is False

    async def test_ensure_authenticated_uses_shared_cache(self):
        """_ensure_authenticated 재발급 경로도 single-flight/shared 캐시 적용 (T2)."""
        session = _FakeSession([_success_response("tok-shared")])
        a1 = _make_adapter(session, account_no="acct-A")
        await a1._authenticate()
        assert session.post_count == 1

        # 토큰/만료 미보유 새 adapter 의 _ensure_authenticated → 캐시 hit, 발급 skip.
        a2 = _make_adapter(session, account_no="acct-B")
        await a2._ensure_authenticated()
        assert session.post_count == 1
        assert a2.access_token == "tok-shared"

    async def test_ensure_authenticated_near_expiry_reissues_single_flight(self):
        """_ensure_authenticated near-expiry 재발급도 single-flight 수렴 (T2)."""
        session = _FakeSession([_success_response("tok-new")])
        # 캐시에 near-expiry 토큰.
        _token_cache[_DEFAULT_CACHE_KEY] = (
            "tok-old",
            datetime.now(UTC) + timedelta(minutes=2),
        )
        adapters = [_make_adapter(session, account_no=f"acct-{i}") for i in range(4)]
        # 각 adapter 인스턴스에도 near-expiry 토큰을 심어 _ensure_authenticated 진입.
        for a in adapters:
            a.access_token = "tok-old"
            a.token_expires_at = datetime.now(UTC) + timedelta(minutes=2)

        await asyncio.gather(*(a._ensure_authenticated() for a in adapters))

        # near-expiry 재발급이 single-flight 로 1회 수렴.
        assert session.post_count == 1
        assert all(a.access_token == "tok-new" for a in adapters)


# ── T1 closed-loop lock 재사용 회귀 ────────────────────────


class TestClosedLoopLockReuse:
    async def test_lock_recreated_after_reset(self):
        """reset 후 lock dict 가 비고, 다음 발급이 새 Lock 으로 동작 (closed-loop)."""
        session1 = _FakeSession([_success_response("tok-1")])
        a1 = _make_adapter(session1)
        await a1._authenticate()
        assert "shared_key" in _token_locks

        # reset(autouse fixture 가 다음 테스트에서 하는 일을 명시 모사).
        _reset_token_cache()
        assert _token_locks == {}
        assert _token_cache == {}

        # 새 발급 — 새 Lock 으로 정상 single-flight.
        session2 = _FakeSession([_success_response("tok-2")])
        a2 = _make_adapter(session2)
        await a2._authenticate()
        assert session2.post_count == 1
        assert a2.access_token == "tok-2"


# ── T3: msg_cd/error_code alias 파싱 (200+body / non-200) ──


class TestTokenErrorParsing:
    async def test_http_200_error_body_msg_cd(self):
        """HTTP 200 + error 바디(access_token 부재, msg_cd) → 파싱 (T3 200+body)."""
        session = _FakeSession(
            [
                _FakeResponse(
                    status=200,
                    json_body={
                        "rt_cd": "1",
                        "msg_cd": "EGW00121",
                        "msg1": "기타 오류",
                    },
                )
            ]
        )
        adapter = _make_adapter(session)
        with pytest.raises(AuthenticationError) as ei:
            await adapter._authenticate()
        assert ei.value.error_code == "EGW00121"

    async def test_non_200_error_body_error_code_alias(self):
        """non-200 + error_code alias 바디 → 파싱 (T3 non-200, error_code alias)."""
        session = _FakeSession(
            [
                _FakeResponse(
                    status=403,
                    json_body={
                        "error_code": "EGW00121",
                        "error_description": "토큰 오류",
                    },
                )
            ]
        )
        adapter = _make_adapter(session)
        with pytest.raises(AuthenticationError) as ei:
            await adapter._authenticate()
        assert ei.value.error_code == "EGW00121"

    async def test_non_200_non_json_body_fallback(self):
        """non-200 + 비 JSON 바디 → text fallback, error_code 빈값 (T3 방어)."""
        session = _FakeSession(
            [_FakeResponse(status=500, text_body="<html>500</html>")]
        )
        adapter = _make_adapter(session)
        with pytest.raises(AuthenticationError) as ei:
            await adapter._authenticate()
        assert ei.value.error_code == ""
        assert "500" in str(ei.value)


# ── T4: EGW00133 즉시 raise (단일 cadence, nested 차단) ────


class TestEGW00133ImmediateRaise:
    async def test_egw00133_non_200_raises_token_rate_limit(self):
        """non-200 EGW00133 → TokenRateLimitError 즉시 raise + 내부 sleep 없음 (T4)."""
        session = _FakeSession(
            [
                _FakeResponse(
                    status=403,
                    json_body={
                        "msg_cd": "EGW00133",
                        "msg1": "접근토큰 발급 잠시 후 다시 시도",
                    },
                )
            ]
        )
        adapter = _make_adapter(session)

        slept: list[float] = []

        async def _no_sleep(d: float) -> None:
            slept.append(d)

        # _authenticate 내부에 sleep 이 있으면 곱셈 위험 → 없어야 한다.
        orig_sleep = asyncio.sleep
        asyncio.sleep = _no_sleep  # type: ignore[assignment]
        try:
            with pytest.raises(TokenRateLimitError) as ei:
                await adapter._authenticate()
        finally:
            asyncio.sleep = orig_sleep  # type: ignore[assignment]

        assert ei.value.error_code == "EGW00133"
        # 핵심: _authenticate 내부 sleep 0회(곱셈 원천 제거).
        assert slept == []

    async def test_egw00133_http_200_body_raises_token_rate_limit(self):
        """HTTP 200 + EGW00133 바디 → TokenRateLimitError (T3 200+body × T4)."""
        session = _FakeSession(
            [
                _FakeResponse(
                    status=200,
                    json_body={"rt_cd": "1", "error_code": "EGW00133"},
                )
            ]
        )
        adapter = _make_adapter(session)
        with pytest.raises(TokenRateLimitError) as ei:
            await adapter._authenticate()
        assert ei.value.error_code == "EGW00133"

    async def test_token_rate_limit_is_authentication_error(self):
        """TokenRateLimitError 는 AuthenticationError 서브클래스 (T5 동일 분류)."""
        assert issubclass(TokenRateLimitError, AuthenticationError)
        err = TokenRateLimitError("x", error_code="EGW00133")
        assert isinstance(err, AuthenticationError)
        assert err.error_code == "EGW00133"


# ── T5: classify 불변 + TRANSIENT set SSOT ────────────────


class TestClassifyAndTransientInvariant:
    def test_classify_authentication_error_unchanged(self):
        """classify(AuthenticationError)=(False,False) 불변 (must_fix J 회귀 락)."""
        assert KISErrorClassifier.classify(AuthenticationError("x")) == (False, False)

    def test_classify_token_rate_limit_same_as_auth(self):
        """classify(TokenRateLimitError)=(False,False) — 서브클래스 동일 분류 (T5)."""
        err = TokenRateLimitError("x", error_code="EGW00133")
        assert KISErrorClassifier.classify(err) == (False, False)

    def test_egw00201_in_transient(self):
        """EGW00201 ∈ TRANSIENT_MSG_CODES (일반 지수 backoff, 회귀 락 T5)."""
        assert "EGW00201" in TRANSIENT_MSG_CODES
        assert is_retryable_msg_code("EGW00201") is True

    def test_egw00133_not_in_transient(self):
        """EGW00133 ∉ TRANSIENT_MSG_CODES (auth-only, 회귀 락 T5)."""
        assert "EGW00133" not in TRANSIENT_MSG_CODES
        assert TOKEN_RATE_LIMIT_MSG_CODE == "EGW00133"
        # 일반 재시도 경로에서도 non-retryable(누수 방어).
        assert is_retryable_msg_code("EGW00133") is False

    def test_korean_error_messages(self):
        """EGW00133/EGW00201 한글 메시지 등록 (스펙 표 §105)."""
        assert get_error_message("EGW00133") == "접근토큰 발급은 1분당 1회만 허용"
        assert get_error_message("EGW00201") == "초당 거래 건수 초과"


# ── attempt4 P2: 캐시 키 = config fingerprint (lock/cooldown = app_key 유지) ──


class TestTokenCacheConfigFingerprint:
    """``_token_cache`` 키만 config fingerprint(app_key+secret+env)로 좁히고,
    ``_token_locks``/``_token_cooldowns`` 는 app_key(rate-limit 단위)를 유지하는지
    검증한다(attempt4 P2 — config 변경 재검증 + 동일 config 공유 보존).
    """

    async def test_changed_secret_is_cache_miss_reissues(self):
        """같은 app_key·다른 app_secret → cache miss → 토큰 endpoint 재호출(발급).

        ``AccountService._reconnect_broker`` 가 변경된 credentials(app_secret)로 새
        어댑터 ``connect()``→``_authenticate()`` 를 호출하면, 같은 app_key 기존 토큰을
        hydrate 하지 않고 **실제 발급**으로 새 설정을 검증해야 한다(이전엔 stale
        hydrate 로 토큰 endpoint 미호출하던 회귀 락).
        """
        # 1) secret_a 로 토큰 발급 → 캐시 populate.
        s1 = _FakeSession([_success_response("tok-a")])
        a1 = _make_adapter(s1, app_secret="secret_a")
        await a1._authenticate()
        assert s1.post_count == 1
        assert a1.access_token == "tok-a"

        # 2) 같은 app_key·다른 app_secret(secret_b) → cache miss → 재발급(endpoint).
        s2 = _FakeSession([_success_response("tok-b")])
        a2 = _make_adapter(s2, app_secret="secret_b")
        await a2._authenticate()
        # 핵심: 토큰 endpoint 가 다시 호출됐다(stale hydrate 가 아님).
        assert s2.post_count == 1
        assert a2.access_token == "tok-b"
        # 두 config 가 별도 캐시 엔트리로 공존(같은 app_key, 다른 fingerprint).
        assert _token_cache[("shared_key", "secret_a", "paper")][0] == "tok-a"
        assert _token_cache[("shared_key", "secret_b", "paper")][0] == "tok-b"

    async def test_changed_env_is_cache_miss_reissues(self):
        """같은 app_key·환경 전환(모의→실전) → cache miss → 토큰 endpoint 재호출.

        ``broker_config`` 의 ``is_paper`` 전환(base_url 모의↔실전)이 바뀌면 같은
        app_key·secret 라도 다른 fingerprint → 새 발급으로 환경을 재검증한다.
        """
        # 1) 모의(is_paper=True) 발급.
        s1 = _FakeSession([_success_response("tok-paper")])
        a1 = KISAdapter(
            {
                "app_key": "shared_key",
                "app_secret": "secret_a",
                "account_no": "1111111101",
                "is_paper": True,
            }
        )
        a1._session = s1  # type: ignore[assignment]
        await a1._authenticate()
        assert s1.post_count == 1

        # 2) 실전(is_paper=False) — 같은 app_key·secret, 다른 환경 → cache miss → 발급.
        s2 = _FakeSession([_success_response("tok-live")])
        a2 = KISAdapter(
            {
                "app_key": "shared_key",
                "app_secret": "secret_a",
                "account_no": "1111111101",
                "is_paper": False,
            }
        )
        a2._session = s2  # type: ignore[assignment]
        await a2._authenticate()
        assert s2.post_count == 1
        assert a2.access_token == "tok-live"
        # 모의/실전 별도 캐시 엔트리.
        assert _token_cache[("shared_key", "secret_a", "paper")][0] == "tok-paper"
        assert _token_cache[("shared_key", "secret_a", "live")][0] == "tok-live"

    async def test_same_config_shares_token_single_flight(self):
        """같은 app_key+secret+env 어댑터 2개 → 같은 키 → single-flight 1회·공유.

        동일 config 공유 어댑터(국내/해외 등)는 캐시 키가 같아 토큰을 공유한다
        (원래 #2399 single-flight 목표 보존 — config fingerprint 가 과수렴을 깨지
        않는다).
        """
        session = _FakeSession([_success_response("tok-shared")])
        a1 = _make_adapter(session, app_secret="secret_a", account_no="acct-A")
        a2 = _make_adapter(session, app_secret="secret_a", account_no="acct-B")

        await asyncio.gather(a1._authenticate(), a2._authenticate())

        # single-flight 1회 발급 + 토큰 공유.
        assert session.post_count == 1
        assert a1.access_token == "tok-shared"
        assert a2.access_token == "tok-shared"
        # 캐시 엔트리는 동일 config fingerprint 1개.
        assert set(_token_cache.keys()) == {("shared_key", "secret_a", "paper")}

    async def test_lock_is_app_key_across_different_configs(self):
        """같은 app_key·다른 config 동시 발급도 lock=app_key 라 single-flight 직렬화.

        캐시 키는 config 별로 갈려도 lock 은 app_key 단위(KIS rate-limit 단위)를
        유지하므로, 같은 app_key 의 동시 발급은 lock 으로 직렬화된다(T1 회귀 락).
        """
        s_a = _FakeSession([_success_response("tok-a")])
        s_b = _FakeSession([_success_response("tok-b")])
        a1 = _make_adapter(s_a, app_secret="secret_a")
        a2 = _make_adapter(s_b, app_secret="secret_b")

        await asyncio.gather(a1._authenticate(), a2._authenticate())

        # lock dict 키는 app_key 단독(config fingerprint 가 아님).
        assert set(_token_locks.keys()) == {"shared_key"}
        # 캐시는 config 별로 2개 엔트리(다른 secret).
        assert set(_token_cache.keys()) == {
            ("shared_key", "secret_a", "paper"),
            ("shared_key", "secret_b", "paper"),
        }

    async def test_cooldown_is_app_key_across_different_configs(self):
        """EGW00133 cooldown 은 app_key 단위라 같은 app_key·다른 secret 발급도 차단.

        cooldown 은 KIS rate-limit(접근토큰 발급 1분 1회) 단위인 app_key 당이므로,
        secret 가 달라도 같은 app_key 의 후속 발급은 cooldown 으로 HTTP 미호출 차단
        된다(T4 cooldown=app_key 회귀 락).
        """
        # secret_a 에 대해 cooldown 직접 기록(EGW00133 수신 모사).
        _record_token_cooldown("shared_key")
        assert set(_token_cooldowns.keys()) == {"shared_key"}

        # 같은 app_key·다른 secret 발급 시도 → cooldown(app_key 단위) 차단, HTTP 미호출.
        s = _FakeSession([_success_response("tok-should-not-issue")])
        a = _make_adapter(s, app_secret="secret_b")
        with pytest.raises(TokenRateLimitError):
            await a._authenticate()
        assert s.post_count == 0
        assert a.access_token is None


# ── T7: known-limitation 주석 anchor ──────────────────────


class TestKnownLimitationAnchor:
    def test_multiprocess_limitation_documented(self):
        """멀티프로세스 토큰 공유 미해결(v1) known-limitation 주석/스펙 anchor (T7)."""
        # in-process module 캐시뿐임을 module docstring/주석으로 명시.
        src = kis_mod.__file__
        with open(src, encoding="utf-8") as f:
            content = f.read()
        assert "멀티프로세스" in content
        assert "in-process" in content
