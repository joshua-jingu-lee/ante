"""한국투자증권 (KIS) Open API 어댑터."""

from __future__ import annotations

import asyncio
import calendar
import json
import logging
from abc import abstractmethod
from collections import OrderedDict, deque
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, NoReturn, cast

from ante.broker.base import BrokerAdapter, ensure_order_side
from ante.broker.circuit_breaker import CircuitBreaker
from ante.broker.error_codes import (
    PERMANENT_MSG_CODES,
    TOKEN_RATE_LIMIT_MSG_CODE,
    TRANSIENT_MSG_CODES,
    get_error_message,
    is_retryable_http_status,
    is_retryable_msg_code,
)
from ante.broker.exceptions import (
    ORDER_OUTCOME_UNKNOWN,
    APIError,
    AuthenticationError,
    BrokerError,
    CircuitOpenError,
    ModifyOrgnoUnavailableError,
    OrderNotFoundError,
    RateLimitError,
    TokenRateLimitError,
)
from ante.broker.fill_scheduler import business_date_kst
from ante.broker.models import CommissionInfo
from ante.core import clock
from ante.core.time import default_order_history_range

if TYPE_CHECKING:
    from ante.eventbus.bus import EventBus

logger = logging.getLogger(__name__)


DEFAULT_MAX_RETRIES_ORDER = 3
DEFAULT_MAX_RETRIES_QUERY = 2
DEFAULT_MAX_RETRIES_AUTH = 2

DEFAULT_TIMEOUT_ORDER = 10
DEFAULT_TIMEOUT_QUERY = 5
DEFAULT_TIMEOUT_AUTH = 10

DEFAULT_BACKOFF_BASE = 1.0

TOKEN_AUTH_BACKOFF_SECONDS = 60.0

TOKEN_RATE_LIMIT_COOLDOWN_SECONDS = 60.0

_TOKEN_EXPIRY_MARGIN_MINUTES = 5

DEFAULT_CB_FAILURE_THRESHOLD = 5
DEFAULT_CB_RECOVERY_TIMEOUT = 60

_TR_CONT_HAS_NEXT = frozenset({"F", "M"})
DEFAULT_MAX_PAGINATION_PAGES = 100

_ORDER_TR_IDS = frozenset(
    {
        "VTTC0012U",
        "TTTC0012U",
        "VTTC0011U",
        "TTTC0011U",
        "VTTC0013U",
        "TTTC0013U",
    }
)

_NEW_ORDER_TR_IDS = frozenset({"VTTC0012U", "TTTC0012U", "VTTC0011U", "TTTC0011U"})

_UNKNOWN_OUTCOME_HTTP_STATUSES = frozenset({500, 502, 503, 504})

_RT_CD_MISSING_ATTR = "_kis_rt_cd_missing"

_REGISTERED_MSG_CODES = (
    PERMANENT_MSG_CODES | TRANSIENT_MSG_CODES | {TOKEN_RATE_LIMIT_MSG_CODE}
)

DEFAULT_EXCG_ID_DVSN_CD = "KRX"

_CCLD_TR_ID_INNER_PAPER = "VTTC0081R"
_CCLD_TR_ID_INNER_LIVE = "TTTC0081R"
_CCLD_TR_ID_BEFORE_PAPER = "VTSC9215R"
_CCLD_TR_ID_BEFORE_LIVE = "CTSC9215R"

_CCLD_BOUNDARY_MONTHS = 3

_PSBL_ORDER_TR_ID_PAPER = "VTTC8908R"
_PSBL_ORDER_TR_ID_LIVE = "TTTC8908R"

_PSBL_ORDER_FIELD_BUYABLE_AMOUNT = "nrcvb_buy_amt"
_PSBL_ORDER_FIELD_MAX_BUYABLE_AMOUNT = "max_buy_amt"
_PSBL_ORDER_FIELD_ORDER_CASH = "ord_psbl_cash"
_PSBL_ORDER_FIELD_BUYABLE_QTY = "nrcvb_buy_qty"
_PSBL_ORDER_FIELD_MAX_BUYABLE_QTY = "max_buy_qty"

_AUTH_PATH = "/oauth2/tokenP"


_TokenCacheKey = tuple[str, str, str]
"""(app_key, app_secret, env) config fingerprint — ``_token_cache`` 키 타입."""

_token_cache: dict[_TokenCacheKey, tuple[str, datetime]] = {}
"""config fingerprint → (access_token, expires_at) in-process shared 캐시 (T2)."""

_token_locks: dict[str, asyncio.Lock] = {}
"""app_key → 발급 직렬화 Lock (T1, lock key=app_key — rate-limit 단위)."""

_token_cooldowns: dict[str, float] = {}
"""app_key → 단조 마감(``clock.monotonic()``) — EGW00133 source-level cooldown.

T2 불변: 유효 캐시 토큰 read 는 cooldown 과 무관(hydrate 먼저)하다."""


def _get_token_lock(app_key: str) -> asyncio.Lock:
    """app_key 별 발급 Lock 을 lazy 생성/반환 (동기 구간, race-free)."""
    return _token_locks.setdefault(app_key, asyncio.Lock())


def _reset_token_cache() -> None:
    """module-level 토큰 캐시/lock/cooldown dict 초기화 (테스트 격리용)."""
    _token_cache.clear()
    _token_locks.clear()
    _token_cooldowns.clear()


def _cooldown_wall_time(deadline: float) -> datetime:
    """단조 마감을 지금의 잔여로 환산한 UTC 순간 (now 를 먼저, 단조를 나중에 읽는다)."""
    now = clock.now(UTC)
    return now + timedelta(seconds=deadline - clock.monotonic())


def _token_cooldown_until(app_key: str) -> datetime | None:
    """app_key 의 현재 EGW00133 cooldown 만료시각(UTC) 또는 ``None``."""
    deadline = _token_cooldowns.get(app_key)
    if deadline is None:
        return None
    if clock.monotonic() >= deadline:
        return None
    return _cooldown_wall_time(deadline)


def _record_token_cooldown(app_key: str) -> datetime:
    """EGW00133 수신 시 app_key cooldown 기록 후 만료시각 반환."""
    deadline = clock.monotonic() + TOKEN_RATE_LIMIT_COOLDOWN_SECONDS
    _token_cooldowns[app_key] = deadline
    return _cooldown_wall_time(deadline)


def _raise_token_rate_limit(app_key: str, *, record: bool = True) -> NoReturn:
    """EGW00133 ``TokenRateLimitError`` raise (cooldown_until 동봉)."""
    if record:
        until: datetime | None = _record_token_cooldown(app_key)
    else:
        until = _token_cooldown_until(app_key)
    msg = get_error_message(TOKEN_RATE_LIMIT_MSG_CODE)
    raise TokenRateLimitError(
        f"토큰 발급 빈도 제한 ({TOKEN_RATE_LIMIT_MSG_CODE}): {msg}",
        error_code=TOKEN_RATE_LIMIT_MSG_CODE,
        cooldown_until=until,
    )


def _is_cached_token_fresh(expires_at: datetime, *, now: datetime) -> bool:
    """캐시 토큰이 near-expiry 여유(만료 5분 전) 내에서 아직 신선한지 (T2)."""
    return now < expires_at - timedelta(minutes=_TOKEN_EXPIRY_MARGIN_MINUTES)


_KRX_FWDG_ORGNO_CACHE_MAXLEN = 1024


def _ccld_three_month_cutoff(today_kst: str) -> str:
    """inquire-daily-ccld inner/before 경계 cutoff ``YYYYMMDD`` (normative)."""
    year = int(today_kst[:4])
    month = int(today_kst[4:6])
    day = int(today_kst[6:8])
    total = (year * 12 + (month - 1)) - _CCLD_BOUNDARY_MONTHS
    target_year, target_month = divmod(total, 12)
    target_month += 1
    last_day = calendar.monthrange(target_year, target_month)[1]
    target_day = min(day, last_day)
    return f"{target_year:04d}{target_month:02d}{target_day:02d}"


def _to_float(value: Any) -> float:
    """KIS 응답 값을 float 으로 안전 변환 (missing/parse-failure → 0.0)."""
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _parse_psbl_amount(
    output: dict[str, Any],
    primary_field: str,
    fallback_field: str,
) -> float:
    """psbl-order 금액 파싱(primary 누락·변환 실패면 폴백, 폴백도 실패면 0.0)."""
    if primary_field in output:
        try:
            return float(output[primary_field])
        except (TypeError, ValueError):
            pass
    return _to_float(output.get(fallback_field))


def _order_outcome_unknown(error: Exception) -> bool:
    """접수 여부를 알 수 없는 실패(무응답·끊김·미등록 코드 5xx·해석 못 한 200)인지."""
    import aiohttp

    if isinstance(
        error, (TimeoutError, ConnectionError, OSError, json.JSONDecodeError)
    ):
        return True
    if isinstance(
        error,
        (
            aiohttp.ClientConnectionError,
            aiohttp.ClientPayloadError,
            aiohttp.ContentTypeError,
        ),
    ):
        return True
    if isinstance(error, APIError):
        if getattr(error, _RT_CD_MISSING_ATTR, False):
            return True
        return (
            error.status_code in _UNKNOWN_OUTCOME_HTTP_STATUSES
            and error.error_code not in _REGISTERED_MSG_CODES
        )
    return False


class KISErrorClassifier:
    """KIS API 에러를 분류하여 재시도/즉시실패/서킷브레이크를 결정한다."""

    @staticmethod
    def classify(error: Exception) -> tuple[bool, bool]:
        """에러를 분류하여 (retryable, record_cb_failure) 튜플을 반환한다.

        Returns:
            retryable: 재시도 가능 여부
            record_cb_failure: circuit breaker에 실패 기록 여부
        """
        if isinstance(error, (CircuitOpenError, AuthenticationError)):
            return False, False
        if isinstance(error, TimeoutError):
            return True, True
        if isinstance(error, (ConnectionError, OSError)):
            return True, True
        if isinstance(error, RateLimitError):
            return True, True
        if isinstance(error, APIError):
            if not error.retryable:
                return False, False
            return True, True
        return False, False

    @staticmethod
    def to_api_error(error: Exception, timeout: float) -> Exception:
        """네트워크/타임아웃 에러를 APIError로 래핑한다."""
        if isinstance(error, TimeoutError):
            return APIError(f"타임아웃 ({timeout:.0f}초 초과)", retryable=True)
        if isinstance(error, (ConnectionError, OSError)):
            return APIError(str(error), retryable=True)
        return error

    @staticmethod
    def log_label(error: Exception) -> str:
        """에러 종류별 로그 라벨 반환."""
        if isinstance(error, TimeoutError):
            return "API 타임아웃"
        if isinstance(error, (ConnectionError, OSError)):
            return "네트워크 오류"
        if isinstance(error, RateLimitError):
            return "Rate limit"
        return "API 오류"


class KISRetryHandler:
    """지수 백오프 기반 재시도 전략을 관리한다."""

    def __init__(self, backoff_base: float = DEFAULT_BACKOFF_BASE) -> None:
        self._backoff_base = backoff_base

    def backoff_delay(self, attempt: int) -> float:
        """attempt 번째 시도의 백오프 대기 시간(초)."""
        return cast("float", self._backoff_base * (2**attempt))

    def should_retry(self, attempt: int, max_retries: int) -> bool:
        """재시도 여부 결정."""
        return attempt < max_retries

    async def wait_and_log(
        self,
        attempt: int,
        max_retries: int,
        tr_id: str,
        error: Exception,
    ) -> None:
        """백오프 대기 후 로그를 남긴다."""
        wait = self.backoff_delay(attempt)
        label = KISErrorClassifier.log_label(error)
        detail = (
            f": {error}"
            if not isinstance(error, (TimeoutError, RateLimitError))
            else ""
        )
        logger.warning(
            "%s [%s] 재시도 %d/%d (%.1f초 후)%s",
            label,
            tr_id,
            attempt + 1,
            max_retries,
            wait,
            detail,
        )
        await asyncio.sleep(wait)


class KISBaseAdapter(BrokerAdapter):
    """KIS Open API 공통 레이어 (인증, HTTP, 에러 처리, 재시도, 서킷브레이커).

    국내/해외 공통 로직을 추상화하는 중간 계층.
    시장별 서브클래스(KISDomesticAdapter, KISOverseasAdapter)가 이를 상속한다.
    """

    def __init__(
        self,
        config: dict[str, Any],
        eventbus: EventBus | None = None,
    ) -> None:
        super().__init__(config)

        self.app_key: str = config["app_key"]
        self.app_secret: str = config["app_secret"]
        self.account_no: str = config["account_no"]
        self.is_paper: bool = config.get("is_paper", True)
        self._eventbus = eventbus

        if self.is_paper:
            self.base_url = "https://openapivts.koreainvestment.com:29443"
            self.websocket_url = "ws://ops.koreainvestment.com:31000"
        else:
            self.base_url = "https://openapi.koreainvestment.com:9443"
            self.websocket_url = "ws://ops.koreainvestment.com:21000"

        self.access_token: str | None = None
        self.token_expires_at: datetime | None = None

        self._session: Any = None

        self._request_times: deque[float] = deque()
        self._rate_lock = asyncio.Lock()
        self._rate_limit_per_minute: int = 5 if self.is_paper else 20

        self._max_retries_order: int = config.get(
            "retry.max_retries_order", DEFAULT_MAX_RETRIES_ORDER
        )
        self._max_retries_query: int = config.get(
            "retry.max_retries_query", DEFAULT_MAX_RETRIES_QUERY
        )
        self._max_retries_auth: int = config.get(
            "retry.max_retries_auth", DEFAULT_MAX_RETRIES_AUTH
        )
        self._backoff_base: float = config.get(
            "retry.backoff_base_seconds", DEFAULT_BACKOFF_BASE
        )

        self._timeout_order: float = config.get("timeout.order", DEFAULT_TIMEOUT_ORDER)
        self._timeout_query: float = config.get("timeout.query", DEFAULT_TIMEOUT_QUERY)
        self._timeout_auth: float = config.get("timeout.auth", DEFAULT_TIMEOUT_AUTH)

        cb_threshold = config.get(
            "circuit_breaker.failure_threshold", DEFAULT_CB_FAILURE_THRESHOLD
        )
        cb_timeout = config.get(
            "circuit_breaker.recovery_timeout", DEFAULT_CB_RECOVERY_TIMEOUT
        )
        self._circuit_breaker = CircuitBreaker(
            failure_threshold=cb_threshold,
            recovery_timeout=cb_timeout,
            eventbus=eventbus,
            name="kis",
        )

        self._retry_handler = KISRetryHandler(backoff_base=self._backoff_base)

    @property
    def circuit_breaker(self) -> CircuitBreaker:
        """Circuit breaker 접근자."""
        return self._circuit_breaker

    async def connect(self) -> None:
        """KIS API 연결 및 인증.

        멱등: 이미 연결된 상태(``is_connected`` 이고 활성 session 보유)면
        새 session 을 만들지 않고 즉시 반환한다. ``get_broker`` 가 connect-성공-후
        -캐시하므로, 호출자(CLI ``_get_broker``·runtime startup)가 캐시된
        어댑터에 connect 를 재호출해도 기존 session 교체로 인한 누수가 없다.
        """
        if self.is_connected and self._session is not None:
            return

        try:
            import aiohttp
        except ImportError as e:
            raise ImportError("aiohttp 패키지가 필요합니다: pip install aiohttp") from e

        self._session = aiohttp.ClientSession()
        try:
            await self._authenticate()
        except BaseException:
            session, self._session = self._session, None
            try:
                await session.close()
            except Exception:
                pass
            raise
        self.is_connected = True
        logger.info("KIS API 연결 완료 (모의투자: %s)", self.is_paper)

    async def disconnect(self) -> None:
        """연결 해제."""
        if self._session:
            await self._session.close()
            self._session = None
        self.is_connected = False
        logger.info("KIS API 연결 해제")

    async def _authenticate(self) -> None:
        """OAuth2 접근 토큰 발급 — single-flight + shared 캐시 + cooldown."""
        if self._hydrate_from_cache():
            return

        if _token_cooldown_until(self.app_key) is not None:
            _raise_token_rate_limit(self.app_key, record=False)

        lock = _get_token_lock(self.app_key)
        async with lock:
            if self._hydrate_from_cache():
                return
            if _token_cooldown_until(self.app_key) is not None:
                _raise_token_rate_limit(self.app_key, record=False)
            token, expires_at = await self._issue_token()
            _token_cache[self._token_cache_key()] = (token, expires_at)
            self.access_token = token
            self.token_expires_at = expires_at
            logger.info("KIS 토큰 발급 완료")

    def _token_cache_key(self) -> _TokenCacheKey:
        """``_token_cache`` config fingerprint 키 — (app_key, app_secret, env)."""
        env = "paper" if self.is_paper else "live"
        return (self.app_key, self.app_secret, env)

    def _hydrate_from_cache(self) -> bool:
        """shared 캐시에 신선한 토큰이 있으면 인스턴스에 hydrate (T2)."""
        cached = _token_cache.get(self._token_cache_key())
        if cached is None:
            return False
        token, expires_at = cached
        if not _is_cached_token_fresh(expires_at, now=clock.now(UTC)):
            return False
        self.access_token = token
        self.token_expires_at = expires_at
        return True

    async def _issue_token(self) -> tuple[str, datetime]:
        """KIS OAuth2 토큰 1회 발급 — msg_cd 파싱 + EGW00133 즉시 raise (T3/T4)."""
        url = f"{self.base_url}/oauth2/tokenP"
        data = {
            "grant_type": "client_credentials",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
        }

        timeout = self._get_timeout(url)
        async with asyncio.timeout(timeout):
            async with self._session.post(
                url, json=data, headers={"content-type": "application/json"}
            ) as response:
                if response.status != 200:
                    body = await self._read_token_error_body(response)
                    self._raise_token_error(response.status, body)

                result = await response.json()
                token = result.get("access_token")
                if not token:
                    self._raise_token_error(response.status, result)

                expires_at = clock.now(UTC) + timedelta(hours=24)
                return token, expires_at

    @staticmethod
    async def _read_token_error_body(response: Any) -> dict[str, Any] | str:
        """non-200 토큰 응답 body 를 dict(가능 시) 또는 raw text 로 반환 (T3)."""
        text: str = await response.text()
        try:
            parsed = json.loads(text)
        except (ValueError, TypeError):
            return text
        if isinstance(parsed, dict):
            return parsed
        return text

    def _raise_token_error(self, status: int, body: dict[str, Any] | str) -> NoReturn:
        """토큰 발급 에러 raise — EGW00133 은 TokenRateLimitError (T3/T4)."""
        code = ""
        detail = ""
        if isinstance(body, dict):
            code = str(body.get("msg_cd") or body.get("error_code") or "")
            detail = str(body.get("msg1") or body.get("error_description") or "")
        text = body if isinstance(body, str) else (detail or json.dumps(body))

        if code == TOKEN_RATE_LIMIT_MSG_CODE:
            _raise_token_rate_limit(self.app_key)
        raise AuthenticationError(
            f"인증 실패 (HTTP {status}): {text}",
            error_code=code,
        )

    async def _ensure_authenticated(self) -> None:
        """토큰 유효성 확인 및 재발급 (재발급도 single-flight/캐시 적용)."""
        if (
            not self.access_token
            or not self.token_expires_at
            or clock.now(UTC)
            >= self.token_expires_at - timedelta(minutes=_TOKEN_EXPIRY_MARGIN_MINUTES)
        ):
            await self._authenticate()

    async def _rate_limit_wait(self) -> None:
        """단조 시계의 창 ``(t-60, t]`` 에서 분당 한도를 지키도록 줄 세워 대기."""
        async with self._rate_lock:
            while True:
                now = clock.monotonic()
                cutoff = now - 60.0
                while self._request_times and self._request_times[0] <= cutoff:
                    self._request_times.popleft()
                if len(self._request_times) < self._rate_limit_per_minute:
                    break
                wait_seconds = self._request_times[0] - cutoff
                logger.debug("Rate limit 대기: %.1f초", wait_seconds)
                await asyncio.sleep(wait_seconds)
            self._request_times.append(now)

    def _get_timeout(self, url: str) -> float:
        """URL 기반 타임아웃 결정."""
        if _AUTH_PATH in url:
            return self._timeout_auth
        return self._timeout_order

    def _get_max_retries(self, url: str, tr_id: str) -> int:
        """API 유형별 최대 재시도 횟수."""
        if _AUTH_PATH in url:
            return self._max_retries_auth
        if tr_id in _ORDER_TR_IDS:
            return self._max_retries_order
        return self._max_retries_query

    def _get_headers(self, tr_id: str = "") -> dict[str, str]:
        """API 요청 헤더 구성."""
        return {
            "Content-Type": "application/json",
            "authorization": f"Bearer {self.access_token}",
            "appKey": self.app_key,
            "appSecret": self.app_secret,
            "tr_id": tr_id,
            "custtype": "P",
        }

    async def _handle_response(self, response: Any) -> dict[str, Any]:
        """API 응답 처리 (에러 분류 포함)."""
        if response.status != 200:
            text = await response.text()
            if isinstance(text, bytes):
                text = text.decode("utf-8", errors="replace")
            retryable = is_retryable_http_status(response.status)
            msg_cd = ""
            msg1 = ""
            try:
                payload = json.loads(text) if text else {}
                if isinstance(payload, dict) and payload.get("rt_cd", "") not in (
                    "",
                    "0",
                ):
                    msg_cd = str(payload.get("msg_cd", ""))
                    msg1 = str(payload.get("msg1", text))
            except (ValueError, TypeError):
                pass
            if msg_cd:
                msg1 = str(payload.get("msg1") or "").strip()
                if not msg1:
                    msg1 = get_error_message(msg_cd)
                if msg_cd in PERMANENT_MSG_CODES:
                    retryable = False
                elif not is_retryable_http_status(response.status):
                    retryable = False
                elif msg_cd in TRANSIENT_MSG_CODES:
                    retryable = True
                raise APIError(
                    f"KIS API Error [{msg_cd}]: {msg1}",
                    error_code=msg_cd,
                    status_code=response.status,
                    retryable=retryable,
                )
            raise APIError(
                f"HTTP {response.status}: {text}",
                status_code=response.status,
                retryable=retryable,
            )

        result: dict[str, Any] = await response.json()
        rt_cd = result.get("rt_cd", "")
        if rt_cd != "0":
            msg_cd = result.get("msg_cd", "")
            msg1 = str(result.get("msg1") or "").strip()
            if not msg1:
                msg1 = get_error_message(msg_cd)
            retryable = is_retryable_msg_code(msg_cd)
            error = APIError(
                f"KIS API Error [{msg_cd}]: {msg1}",
                error_code=msg_cd,
                retryable=retryable,
            )
            if result.get("rt_cd") in (None, ""):
                setattr(error, _RT_CD_MISSING_ATTR, True)
            raise error
        return result

    async def _request(
        self,
        method: str,
        url: str,
        tr_id: str,
        params: dict[str, str] | None = None,
        json_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """API 요청 공통 래퍼 (circuit breaker + 재시도 + 타임아웃)."""
        body, _ = await self._request_with_cont(
            method, url, tr_id, params=params, json_data=json_data
        )
        return body

    async def _request_with_cont(
        self,
        method: str,
        url: str,
        tr_id: str,
        params: dict[str, str] | None = None,
        json_data: dict[str, Any] | None = None,
        cont_header: str = "",
        *,
        cb_exempt_timeout: bool = False,
    ) -> tuple[dict[str, Any], str]:
        """API 요청 공통 래퍼 (circuit breaker + 재시도 + 타임아웃)."""
        self._circuit_breaker.check()
        await self._ensure_authenticated()
        await self._rate_limit_wait()

        max_retries = self._get_max_retries(url, tr_id)
        timeout = self._timeout_order if tr_id in _ORDER_TR_IDS else self._timeout_query
        last_error: Exception | None = None

        for attempt in range(max_retries + 1):
            await self._ensure_authenticated()
            headers = self._get_headers(tr_id)
            if cont_header:
                headers["tr_cont"] = cont_header
            try:
                result = await self._send_http(
                    method, url, headers, params, json_data, timeout
                )
                self._circuit_breaker.record_success()
                return result
            except Exception as e:
                retryable, record_failure = KISErrorClassifier.classify(e)
                unknown = tr_id in _NEW_ORDER_TR_IDS and _order_outcome_unknown(e)
                if not retryable and not unknown:
                    raise
                last_error = KISErrorClassifier.to_api_error(e, timeout)
                if record_failure and not (
                    cb_exempt_timeout and isinstance(e, TimeoutError)
                ):
                    self._circuit_breaker.record_failure()
                if unknown:
                    cause = str(last_error) or type(e).__name__
                    raise APIError(
                        f"주문 접수 여부 미상 — 다시 보내지 않음: {cause}",
                        status_code=e.status_code if isinstance(e, APIError) else 0,
                        error_code=ORDER_OUTCOME_UNKNOWN,
                    ) from e
                if self._retry_handler.should_retry(attempt, max_retries):
                    await self._retry_handler.wait_and_log(
                        attempt, max_retries, tr_id, e
                    )
                    continue

        raise last_error  # type: ignore[misc]

    async def _send_http(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        params: dict[str, str] | None,
        json_data: dict[str, Any] | None,
        timeout: float,
    ) -> tuple[dict[str, Any], str]:
        """단일 HTTP 요청 실행 (타임아웃 적용)."""
        async with asyncio.timeout(timeout):
            if method == "GET":
                async with self._session.get(
                    url, headers=headers, params=params
                ) as resp:
                    body = await self._handle_response(resp)
                    return body, resp.headers.get("tr_cont", "")
            else:
                async with self._session.post(
                    url, headers=headers, json=json_data
                ) as resp:
                    body = await self._handle_response(resp)
                    return body, resp.headers.get("tr_cont", "")

    async def _request_paginated(
        self,
        method: str,
        url: str,
        tr_id: str,
        base_params: dict[str, str],
        row_key: str,
        *,
        cb_exempt_timeout: bool = False,
    ) -> list[dict[str, Any]]:
        """연속조회로 ``row_key`` 행 누적(cursor 누락·최대 페이지면 경고 후 중단)."""
        rows: list[dict[str, Any]] = []
        params = dict(base_params)
        cont_header = ""

        for page in range(1, DEFAULT_MAX_PAGINATION_PAGES + 1):
            body, tr_cont = await self._request_with_cont(
                method,
                url,
                tr_id,
                params=params,
                cont_header=cont_header,
                cb_exempt_timeout=cb_exempt_timeout,
            )
            page_rows = body.get(row_key) or []
            rows.extend(page_rows)

            if tr_cont not in _TR_CONT_HAS_NEXT:
                break

            next_fk = str(body.get("ctx_area_fk100", "") or "").strip()
            next_nk = str(body.get("ctx_area_nk100", "") or "").strip()
            if not next_fk and not next_nk:
                logger.warning(
                    "KIS 연속조회 cursor 누락 [%s] tr_cont=%s page=%d "
                    "(잔여 페이지 누락 가능)",
                    tr_id,
                    tr_cont,
                    page,
                )
                break

            params["CTX_AREA_FK100"] = next_fk
            params["CTX_AREA_NK100"] = next_nk
            cont_header = "N"
        else:
            logger.warning(
                "KIS 연속조회 최대 페이지(%d) 도달 [%s] (잔여 페이지 누락 가능)",
                DEFAULT_MAX_PAGINATION_PAGES,
                tr_id,
            )

        return rows

    @abstractmethod
    async def get_account_balance(self) -> dict[str, float]:
        """계좌 잔고 조회."""
        ...

    @abstractmethod
    async def get_positions(self) -> list[dict[str, Any]]:
        """보유 포지션 조회."""
        ...

    @abstractmethod
    async def get_current_price(self, symbol: str) -> float:
        """현재가 조회."""
        ...

    @abstractmethod
    async def get_buyable(
        self,
        symbol: str,
        price: float | None = None,
        order_type: str = "market",
    ) -> dict[str, float]:
        """매수가능 조회 (KIS ``inquire-psbl-order``)."""
        ...

    @abstractmethod
    async def place_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        order_type: str = "market",
        price: float | None = None,
        stop_price: float | None = None,
    ) -> str:
        """주문 접수."""
        ...

    @abstractmethod
    async def cancel_order(self, order_id: str) -> bool:
        """주문 취소."""
        ...

    @abstractmethod
    async def modify_order(
        self,
        order_id: str,
        *,
        quantity: float | None = None,
        price: float | None = None,
        order_type: str = "limit",
    ) -> bool:
        """주문 정정 (v1=price-only)."""
        ...

    @abstractmethod
    async def get_order_status(self, order_id: str) -> dict[str, Any]:
        """주문 상태 조회."""
        ...

    @abstractmethod
    async def get_pending_orders(self) -> list[dict[str, Any]]:
        """미체결 주문 목록 조회."""
        ...

    @abstractmethod
    async def get_account_positions(self) -> list[dict[str, Any]]:
        """대사용 보유 잔고 조회."""
        ...

    @abstractmethod
    async def get_order_history(
        self,
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> list[dict[str, Any]]:
        """주문/체결 이력 조회."""
        ...

    @abstractmethod
    async def get_instruments(self, exchange: str = "KRX") -> list[dict[str, Any]]:
        """종목 마스터 데이터 조회."""
        ...

    @abstractmethod
    def get_commission_info(self) -> CommissionInfo:
        """수수료율 정보 반환."""
        ...


class KISDomesticAdapter(KISBaseAdapter):
    """한국투자증권 국내주식 전용 어댑터.

    KISBaseAdapter를 상속하여 국내주식 API 경로, 주문 파라미터,
    시세 조회, 수수료 등 국내 전용 로직을 구현한다.
    """

    broker_id: str = "kis-domestic"
    broker_name: str = "한국투자증권 국내"
    broker_short_name: str = "KIS"

    def __init__(
        self,
        config: dict[str, Any],
        eventbus: EventBus | None = None,
    ) -> None:
        config.setdefault("exchange", "KRX")
        config.setdefault("currency", "KRW")
        super().__init__(config, eventbus)

        self._buy_commission_rate: float = config.get(
            "buy_commission_rate",
            config.get("commission_rate", 0.00015),
        )
        self._sell_commission_rate: float = config.get(
            "sell_commission_rate",
            config.get("commission_rate", 0.00015)
            + config.get("sell_tax_rate", 0.0018),
        )

        self._krx_fwdg_orgno_cache: OrderedDict[str, tuple[str, str]] = OrderedDict()

    def _balance_params(self) -> dict[str, str]:
        """잔고 조회 공통 파라미터."""
        return {
            "CANO": self.account_no[:8],
            "ACNT_PRDT_CD": self.account_no[8:10],
            "AFHR_FLPR_YN": "N",
            "OFL_YN": "",
            "INQR_DVSN": "01",
            "UNPR_DVSN": "01",
            "FUND_STTL_ICLD_YN": "N",
            "FNCG_AMT_AUTO_RDPT_YN": "N",
            "PRCS_DVSN": "00",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": "",
        }

    async def get_account_balance(self) -> dict[str, float]:
        """계좌 잔고 조회."""
        tr_id = "VTTC8434R" if self.is_paper else "TTTC8434R"
        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/inquire-balance"
        result = await self._request("GET", url, tr_id, params=self._balance_params())

        info = result["output2"][0] if result.get("output2") else {}
        return {
            "cash": float(info.get("dnca_tot_amt", 0)),
            "total_assets": float(info.get("tot_evlu_amt", 0)),
            "purchase_amount": float(info.get("pchs_amt_smtl_amt", 0)),
            "eval_amount": float(info.get("evlu_amt_smtl_amt", 0)),
            "total_profit_loss": float(info.get("evlu_pfls_smtl_amt", 0)),
            "substitute_amount": float(info.get("psbl_sbst_amt", 0)),
        }

    async def get_positions(self) -> list[dict[str, Any]]:
        """보유 포지션 조회 (CTX_AREA 연속조회로 전 페이지 누적)."""
        tr_id = "VTTC8434R" if self.is_paper else "TTTC8434R"
        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/inquire-balance"
        rows = await self._request_paginated(
            "GET", url, tr_id, self._balance_params(), row_key="output1"
        )

        positions = []
        for item in rows:
            qty = float(item.get("hldg_qty", 0))
            if qty > 0:
                positions.append(
                    {
                        "symbol": item["pdno"],
                        "name": item.get("prdt_name", ""),
                        "quantity": qty,
                        "avg_price": float(item.get("pchs_avg_pric", 0)),
                        "current_price": float(item.get("prpr", 0)),
                        "eval_amount": float(item.get("evlu_amt", 0)),
                        "profit_loss": float(item.get("evlu_pfls_amt", 0)),
                        "profit_loss_rate": float(item.get("evlu_erng_rt", 0)),
                    }
                )
        return positions

    async def get_current_price(self, symbol: str) -> float:
        """현재가 조회."""
        tr_id = "FHKST01010100"
        url = f"{self.base_url}/uapi/domestic-stock/v1/quotations/inquire-price"
        params = {
            "fid_cond_mrkt_div_code": "J",
            "fid_input_iscd": self.normalize_symbol(symbol),
        }
        result = await self._request("GET", url, tr_id, params=params)
        return float(result["output"]["stck_prpr"])

    async def get_buyable(
        self,
        symbol: str,
        price: float | None = None,
        order_type: str = "market",
    ) -> dict[str, float]:
        """매수가능 조회 (KIS ``inquire-psbl-order``).

        ``purchasable_amount``(주문가능액)의 SSOT다. 무인자 ``get_account_balance``
        (``inquire-balance``)는 종목 컨텍스트가 없어 주문가능액을 산출할 수 없으므로
        종목/단가/주문구분을 입력으로 받는 이 메서드가 별도로 조회한다. 모의
        rate-limit(5req/min) 안전을 위해 ``get_account_balance``와 분리한다.
        """
        tr_id = _PSBL_ORDER_TR_ID_PAPER if self.is_paper else _PSBL_ORDER_TR_ID_LIVE
        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/inquire-psbl-order"

        ord_dvsn = self._map_order_type(order_type)
        unit_price = price
        if unit_price is None:
            unit_price = await self.get_current_price(symbol)

        params = {
            "CANO": self.account_no[:8],
            "ACNT_PRDT_CD": self.account_no[8:10],
            "PDNO": self.normalize_symbol(symbol),
            "ORD_UNPR": str(int(unit_price)),
            "ORD_DVSN": ord_dvsn,
            "CMA_EVLU_AMT_ICLD_YN": "N",
            "OVRS_ICLD_YN": "N",
        }
        result = await self._request("GET", url, tr_id, params=params)
        output = result.get("output") or {}

        order_buyable_amount = _parse_psbl_amount(
            output,
            primary_field=_PSBL_ORDER_FIELD_BUYABLE_AMOUNT,
            fallback_field=_PSBL_ORDER_FIELD_ORDER_CASH,
        )
        return {
            "order_buyable_amount": order_buyable_amount,
            "max_buyable_amount": _to_float(
                output.get(_PSBL_ORDER_FIELD_MAX_BUYABLE_AMOUNT)
            ),
            "order_cash": _to_float(output.get(_PSBL_ORDER_FIELD_ORDER_CASH)),
            "order_buyable_qty": _to_float(output.get(_PSBL_ORDER_FIELD_BUYABLE_QTY)),
            "max_buyable_qty": _to_float(output.get(_PSBL_ORDER_FIELD_MAX_BUYABLE_QTY)),
        }

    async def place_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        order_type: str = "market",
        price: float | None = None,
        stop_price: float | None = None,
    ) -> str:
        """주문 접수. KIS는 stop order 미지원."""
        ensure_order_side(side)
        if order_type in ("stop", "stop_limit"):
            raise ValueError(
                f"KIS does not support {order_type} orders natively. "
                "Use StopOrderManager for stop order emulation."
            )

        if side == "buy":
            tr_id = "VTTC0012U" if self.is_paper else "TTTC0012U"
        else:
            tr_id = "VTTC0011U" if self.is_paper else "TTTC0011U"

        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/order-cash"
        order_data = self._build_order_data(symbol, side, quantity, order_type, price)

        result = await self._request("POST", url, tr_id, json_data=order_data)
        output = result["output"]
        broker_order_id: str = output["ODNO"]
        self._cache_krx_fwdg_orgno(broker_order_id, output.get("KRX_FWDG_ORD_ORGNO"))
        logger.info(
            "주문 접수: %s %s %s %.0f주 → %s",
            side,
            order_type,
            symbol,
            quantity,
            broker_order_id,
        )
        return broker_order_id

    def _cache_krx_fwdg_orgno(self, broker_order_id: str, orgno: str | None) -> None:
        """order-cash 응답의 KRX_FWDG_ORD_ORGNO 를 제출 영업일과 함께 캐시."""
        if not orgno:
            return
        cache = self._krx_fwdg_orgno_cache
        cache[broker_order_id] = (orgno, business_date_kst())
        cache.move_to_end(broker_order_id)
        while len(cache) > _KRX_FWDG_ORGNO_CACHE_MAXLEN:
            cache.popitem(last=False)

    def _build_order_data(
        self,
        symbol: str,
        side: str,
        quantity: float,
        order_type: str,
        price: float | None,
    ) -> dict[str, str]:
        """KIS 주문 데이터 구성."""
        data = {
            "CANO": self.account_no[:8],
            "ACNT_PRDT_CD": self.account_no[8:10],
            "PDNO": self.normalize_symbol(symbol),
            "ORD_DVSN": self._map_order_type(order_type),
            "ORD_QTY": str(int(quantity)),
            "ORD_UNPR": "0",
            "EXCG_ID_DVSN_CD": DEFAULT_EXCG_ID_DVSN_CD,
        }
        if order_type == "limit" and price is not None:
            data["ORD_UNPR"] = str(int(price))
        return data

    def _map_order_type(self, order_type: str) -> str:
        """KIS ORD_DVSN 코드 매핑."""
        mapping = {
            "market": "01",
            "limit": "00",
            "conditional": "02",
            "best": "03",
            "priority": "04",
        }
        if not isinstance(order_type, str) or order_type not in mapping:
            raise BrokerError(f"지원하지 않는 주문 유형: {order_type!r}")
        return mapping[order_type]

    def _map_order_status(self, status_code: str) -> str:
        """KIS 주문 상태 코드 매핑."""
        mapping = {
            "10": "pending",
            "11": "confirmed",
            "20": "partial_filled",
            "30": "filled",
            "40": "cancelled",
            "50": "rejected",
        }
        return mapping.get(status_code, "unknown")

    async def cancel_order(self, order_id: str) -> bool:
        """주문 취소.

        body 에 원주문별 ``KRX_FWDG_ORD_ORGNO``(한국거래소전송주문조직번호)를
        조건부로 전송한다. 값은 place_order 시 order-cash 응답에서 캡처해
        둔 인메모리 캐시에서 가져오며, 순수 dict 조회로 네트워크/추가 조회를 하지
        않는다. 캐시 miss 또는 제출 영업일 불일치(odno 재사용 등) 시에는 필드를
        생략한다(기존 동작 유지).
        """
        tr_id = "VTTC0013U" if self.is_paper else "TTTC0013U"
        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/order-rvsecncl"
        cancel_data = {
            "CANO": self.account_no[:8],
            "ACNT_PRDT_CD": self.account_no[8:10],
            "ORGN_ODNO": order_id,
            "ORD_DVSN": "01",
            "RVSE_CNCL_DVSN_CD": "02",
            "ORD_QTY": "0",
            "ORD_UNPR": "0",
            "QTY_ALL_ORD_YN": "Y",
            "EXCG_ID_DVSN_CD": DEFAULT_EXCG_ID_DVSN_CD,
        }
        cached = self._krx_fwdg_orgno_cache.get(order_id)
        if cached is not None and cached[1] == business_date_kst():
            cancel_data["KRX_FWDG_ORD_ORGNO"] = cached[0]
        else:
            logger.debug(
                "취소 KRX_FWDG_ORD_ORGNO 생략: %s (cache=%s)",
                order_id,
                "miss" if cached is None else "stale-date",
            )
        await self._request("POST", url, tr_id, json_data=cancel_data)
        logger.info("주문 취소 성공: %s", order_id)
        return True

    async def modify_order(
        self,
        order_id: str,
        *,
        quantity: float | None = None,
        price: float | None = None,
        order_type: str = "limit",
    ) -> bool:
        """주문 정정 (v1=price-only). cancel_order 미러링.

        ``KRX_FWDG_ORD_ORGNO``(한국거래소전송주문조직번호)는 cancel 과 동일하게
        place_order(order-cash) 응답 캡처 캐시(``_krx_fwdg_orgno_cache``)에서 가져온다.
        취소는 miss 시 필드를 생략(전송)하지만, 정정은 oracle 검증 전이라 보수적으로
        **miss/stale → :class:`ModifyOrgnoUnavailableError` raise(전송 금지)** 한다.
        Gateway 가 이를 ``modify_orgno_unavailable`` 거부로 매핑한다.
        """
        tr_id = "VTTC0013U" if self.is_paper else "TTTC0013U"
        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/order-rvsecncl"

        cached = self._krx_fwdg_orgno_cache.get(order_id)
        if cached is None or cached[1] != business_date_kst():
            logger.warning(
                "정정 KRX_FWDG_ORD_ORGNO 미상: %s (cache=%s) — 전송 차단",
                order_id,
                "miss" if cached is None else "stale-date",
            )
            raise ModifyOrgnoUnavailableError(
                f"주문 정정 KRX_FWDG_ORD_ORGNO 미상: {order_id}"
            )

        modify_data = {
            "CANO": self.account_no[:8],
            "ACNT_PRDT_CD": self.account_no[8:10],
            "KRX_FWDG_ORD_ORGNO": cached[0],
            "ORGN_ODNO": order_id,
            "ORD_DVSN": self._map_order_type(order_type),
            "RVSE_CNCL_DVSN_CD": "01",
            "ORD_QTY": str(int(quantity or 0)),
            "ORD_UNPR": str(int(price or 0)),
            "QTY_ALL_ORD_YN": "Y",
            "EXCG_ID_DVSN_CD": DEFAULT_EXCG_ID_DVSN_CD,
        }
        await self._request("POST", url, tr_id, json_data=modify_data)
        logger.info(
            "주문 정정 성공: %s → 신규가격 %s", order_id, modify_data["ORD_UNPR"]
        )
        return True

    async def get_order_status(self, order_id: str) -> dict[str, Any]:
        """주문 상태 조회 (CTX_AREA 연속조회로 전 페이지 확보 후 검색)."""
        tr_id = "VTTC8036R" if self.is_paper else "TTTC8036R"
        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/inquire-psbl-rvsecncl"
        params = {
            "CANO": self.account_no[:8],
            "ACNT_PRDT_CD": self.account_no[8:10],
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": "",
            "INQR_DVSN_1": "1",
            "INQR_DVSN_2": "0",
        }
        orders = await self._request_paginated(
            "GET", url, tr_id, params, row_key="output"
        )

        for order in orders:
            if order.get("odno") == order_id:
                return {
                    "order_id": order["odno"],
                    "symbol": order.get("pdno", ""),
                    "side": "buy" if order.get("sll_buy_dvsn_cd") == "02" else "sell",
                    "quantity": float(order.get("ord_qty", 0)),
                    "filled_quantity": float(order.get("tot_ccld_qty", 0)),
                    "remaining_quantity": float(order.get("rmn_qty", 0)),
                    "status": self._map_order_status(order.get("ord_stat_cd", "")),
                    "price": float(order.get("ord_unpr", 0)) or None,
                    "avg_fill_price": float(order.get("avg_prvs", 0)) or None,
                }

        raise OrderNotFoundError(f"Order {order_id} not found")

    async def get_pending_orders(self) -> list[dict[str, Any]]:
        """미체결 주문 목록 조회 (CTX_AREA 연속조회로 전 페이지 누적)."""
        tr_id = "VTTC8036R" if self.is_paper else "TTTC8036R"
        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/inquire-psbl-rvsecncl"
        params = {
            "CANO": self.account_no[:8],
            "ACNT_PRDT_CD": self.account_no[8:10],
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": "",
            "INQR_DVSN_1": "1",
            "INQR_DVSN_2": "0",
        }
        rows = await self._request_paginated(
            "GET", url, tr_id, params, row_key="output"
        )

        orders = []
        for order in rows:
            orders.append(
                {
                    "order_id": order.get("odno", ""),
                    "symbol": order.get("pdno", ""),
                    "side": "buy" if order.get("sll_buy_dvsn_cd") == "02" else "sell",
                    "quantity": float(order.get("ord_qty", 0)),
                    "filled_quantity": float(order.get("tot_ccld_qty", 0)),
                    "remaining_quantity": float(order.get("rmn_qty", 0)),
                    "status": self._map_order_status(order.get("ord_stat_cd", "")),
                }
            )
        return orders

    async def get_instruments(self, exchange: str = "KRX") -> list[dict[str, Any]]:
        """KIS API에서 종목 마스터 데이터 조회 (코스피 + 코스닥)."""
        instruments: list[dict[str, Any]] = []

        market_codes = [("J", "KOSPI"), ("Q", "KOSDAQ")]
        for mrkt_code, market_name in market_codes:
            try:
                items = await self._fetch_stock_list(mrkt_code)
                for item in items:
                    inst_type = self._classify_instrument_type(
                        item.get("std_pdno", ""),
                        item.get("prdt_name", ""),
                        item.get("rprs_mrkt_kor_name", market_name),
                    )
                    instruments.append(
                        {
                            "symbol": item.get("std_pdno", ""),
                            "name": item.get("prdt_name", ""),
                            "name_en": item.get("prdt_eng_name", ""),
                            "instrument_type": inst_type,
                            "listed": True,
                        }
                    )
                logger.info("KIS 종목 조회 완료: %s %d건", market_name, len(items))
            except Exception:
                logger.warning("KIS %s 종목 조회 실패", market_name, exc_info=True)

        return instruments

    _MASTER_FILES: dict[str, dict[str, str | int]] = {
        "J": {
            "url": "https://new.real.download.dws.co.kr/common/master/kospi_code.mst.zip",
            "filename": "kospi_code.mst",
            "tail_len": 228,
        },
        "Q": {
            "url": "https://new.real.download.dws.co.kr/common/master/kosdaq_code.mst.zip",
            "filename": "kosdaq_code.mst",
            "tail_len": 222,
        },
    }

    async def _fetch_stock_list(self, mrkt_code: str) -> list[dict[str, Any]]:
        """KIS 마스터 파일 다운로드로 종목 목록 조회."""
        import io
        import zipfile

        config = self._MASTER_FILES.get(mrkt_code)
        if config is None:
            raise ValueError(f"지원하지 않는 시장 코드: {mrkt_code}")

        url = str(config["url"])
        filename = str(config["filename"])
        tail_len = int(config["tail_len"])

        async with self._session.get(url) as resp:
            resp.raise_for_status()
            zip_data = await resp.read()

        with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
            raw = zf.read(filename)

        items: list[dict[str, Any]] = []
        for line in raw.decode("cp949").splitlines():
            if not line.strip():
                continue
            part1 = line[: len(line) - tail_len]
            short_code = part1[0:9].strip()
            name = part1[21:].strip()

            if len(short_code) == 6 and short_code.isdigit():
                items.append(
                    {
                        "std_pdno": short_code,
                        "prdt_name": name,
                        "prdt_eng_name": "",
                    }
                )

        return items

    @staticmethod
    def _classify_instrument_type(symbol: str, name: str, market: str) -> str:
        """종목명/코드 기반 instrument_type 분류."""
        name_upper = name.upper()
        if "ETF" in name_upper or "KODEX" in name_upper or "TIGER" in name_upper:
            return "etf"
        if "ETN" in name_upper:
            return "etn"
        return "stock"

    def get_commission_info(self) -> CommissionInfo:
        """KIS 국내 수수료율 정보 반환."""
        return CommissionInfo(
            buy_commission_rate=self._buy_commission_rate,
            sell_commission_rate=self._sell_commission_rate,
        )

    async def get_account_positions(self) -> list[dict[str, Any]]:
        """대사용 보유 잔고 조회."""
        positions = await self.get_positions()
        return [
            {
                "symbol": p["symbol"],
                "quantity": p["quantity"],
                "avg_price": p["avg_price"],
            }
            for p in positions
        ]

    async def get_order_history(
        self,
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> list[dict[str, Any]]:
        """주문/체결 이력 조회 (CTX_AREA 연속조회로 전 페이지 누적 후 fold).

        tr_id 는 KST 3개월 경계(inner/before) × 모의/실전 4코드로 분기한다.
        조회 시작일(``INQR_STRT_DT``)이 KST 오늘 기준 3개월 전 cutoff 이상이면
        inner(``*0081R``), 미만이면 before(``*9215R``)다(start-date 단독 기준).
        교차 구간(``from < cutoff <= to``)은 split query 없이 start-date 기준
        before 단일 쿼리로 처리하며, 그 완전성은 bounded known-limitation 이다.
        """
        now = clock.now(UTC)
        today = business_date_kst(now)
        default_start, default_end = default_order_history_range(now)
        start_date = from_date or default_start.strftime("%Y%m%d")
        end_date = to_date or default_end.strftime("%Y%m%d")

        cutoff = _ccld_three_month_cutoff(today)
        is_inner = start_date >= cutoff
        if is_inner:
            tr_id = _CCLD_TR_ID_INNER_PAPER if self.is_paper else _CCLD_TR_ID_INNER_LIVE
        else:
            tr_id = (
                _CCLD_TR_ID_BEFORE_PAPER if self.is_paper else _CCLD_TR_ID_BEFORE_LIVE
            )

        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/inquire-daily-ccld"

        params = {
            "CANO": self.account_no[:8],
            "ACNT_PRDT_CD": self.account_no[8:10],
            "INQR_STRT_DT": start_date,
            "INQR_END_DT": end_date,
            "SLL_BUY_DVSN_CD": "00",
            "INQR_DVSN": "00",
            "PDNO": "",
            "CCLD_DVSN": "00",
            "ORD_GNO_BRNO": "",
            "ODNO": "",
            "INQR_DVSN_3": "00",
            "INQR_DVSN_1": "",
            "EXCG_ID_DVSN_CD": DEFAULT_EXCG_ID_DVSN_CD,
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": "",
        }

        rows = await self._request_paginated(
            "GET", url, tr_id, params, row_key="output1", cb_exempt_timeout=True
        )
        return self._fold_order_history(rows)

    @staticmethod
    def _fold_order_history(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """inquire-daily-ccld ``output1`` 행을 (odno, 영업일)별로 fold."""
        folded: dict[tuple[str, str], dict[str, Any]] = {}
        for item in rows:
            odno = str(item.get("odno", ""))
            ord_dt = str(item.get("ord_dt", ""))
            if not odno:
                continue
            cum_qty = float(item.get("tot_ccld_qty", 0) or 0)
            ccld_amt = float(item.get("tot_ccld_amt", 0) or 0)
            avg_prvs = float(item.get("avg_prvs", 0) or 0)
            ord_unpr = float(item.get("ord_unpr", 0) or 0)
            if cum_qty > 0 and ccld_amt > 0:
                fill_price = ccld_amt / cum_qty
            elif avg_prvs > 0:
                fill_price = avg_prvs
            else:
                fill_price = ord_unpr

            key = (odno, ord_dt)
            existing = folded.get(key)
            if existing is None or cum_qty >= existing["filled_quantity"]:
                folded[key] = {
                    "order_id": odno,
                    "symbol": item.get("pdno", ""),
                    "side": "buy" if item.get("sll_buy_dvsn_cd") == "02" else "sell",
                    "quantity": float(item.get("ord_qty", 0) or 0),
                    "filled_quantity": cum_qty,
                    "price": fill_price,
                    "status": "filled" if cum_qty > 0 else "pending",
                    "timestamp": ord_dt,
                }
        return list(folded.values())


KISAdapter = KISDomesticAdapter
