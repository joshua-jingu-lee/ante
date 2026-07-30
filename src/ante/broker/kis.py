"""한국투자증권 (KIS) Open API 어댑터.

KIS REST API를 통해 주문, 조회를 처리한다.
실행 시 aiohttp 패키지가 필요하다.

계층 구조:
    BrokerAdapter (ABC)
    └── KISBaseAdapter (ABC) — KIS 공통 레이어 (인증, HTTP, 에러 처리)
        └── KISDomesticAdapter — 국내주식 전용
"""

from __future__ import annotations

import asyncio
import calendar
import json
import logging
from abc import abstractmethod
from collections import OrderedDict
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, NoReturn

from ante.broker.base import BrokerAdapter
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
    APIError,
    AuthenticationError,
    CircuitOpenError,
    ModifyOrgnoUnavailableError,
    OrderNotFoundError,
    RateLimitError,
    TokenRateLimitError,
)
from ante.broker.fill_scheduler import business_date_kst
from ante.broker.models import CommissionInfo

if TYPE_CHECKING:
    from ante.eventbus.bus import EventBus

logger = logging.getLogger(__name__)

# ── API 유형별 설정 ───────────────────────────────────

# 최대 재시도 횟수
DEFAULT_MAX_RETRIES_ORDER = 3
DEFAULT_MAX_RETRIES_QUERY = 2
DEFAULT_MAX_RETRIES_AUTH = 2

# 타임아웃 (초)
DEFAULT_TIMEOUT_ORDER = 10
DEFAULT_TIMEOUT_QUERY = 5
DEFAULT_TIMEOUT_AUTH = 10

# Backoff
DEFAULT_BACKOFF_BASE = 1.0

# 토큰 발급 빈도 제한(EGW00133) 흡수용 backoff 초 (#2399).
# KIS 공식 "접근토큰 발급 1분 1회". startup connect 루프(main._init_gateway)가
# 부팅 1회 경로에서만 이 backoff 를 소비한다(단일 cadence — adapter._authenticate 는
# 즉시 raise, self-healing 은 interval 60s 위임). config 노출하지 않는 adapter-local
# 상수다(global defaults 변경 금지 — test_kis_error_handling.py:268 가 broker retry
# key 부재를 잠금).
TOKEN_AUTH_BACKOFF_SECONDS = 60.0

# EGW00133 수신 시 해당 app_key 의 토큰 발급을 차단하는 cooldown 초
# (#2399 attempt3 + 메타 감사 — per-app_key cooldown at source).
# KIS 공식 "접근토큰 발급 1분 1회"에 정렬한 source-level cooldown 이다. EGW00133 을
# 한 번 받으면 그 app_key 의 발급 경로(startup/self-healing/runtime/IPC) 전부가 이
# cooldown 동안 **HTTP 미호출**로 즉시 ``TokenRateLimitError`` 를 raise 한다 —
# get_broker→토큰 재타격을 per-call-site 필터가 아니라 발급 레이어 단일 chokepoint
# 에서 닫는다(단일 cadence T4 의 근본 보장). self-healing interval(60s) ≥ 본
# cooldown(60s) 이라 self-healing 정상 동작과도 정합한다(다음 burst 에서 만료).
TOKEN_RATE_LIMIT_COOLDOWN_SECONDS = 60.0

# 토큰 cache hit 시 near-expiry 재발급 여유(분). ``_ensure_authenticated`` 의 "만료
# 5분 전 재발급" 기준(아래 ``_ensure_authenticated``)과 **동일**해야 한다 — shared
# 캐시 hit 판정도 near-expiry 토큰을 miss 로 보고 재발급한다(near-expiry 재사용 회귀
# 방지, #2399 T2).
_TOKEN_EXPIRY_MARGIN_MINUTES = 5

# Circuit Breaker
DEFAULT_CB_FAILURE_THRESHOLD = 5
DEFAULT_CB_RECOVERY_TIMEOUT = 60

# KIS 연속조회(CTX_AREA) 페이지네이션
# 응답 헤더 tr_cont 값: "F"/"M" = 다음 페이지 있음, "D"/"E" = 마지막 페이지.
_TR_CONT_HAS_NEXT = frozenset({"F", "M"})
# 무한 루프 방지용 최대 페이지 수 안전 상한.
DEFAULT_MAX_PAGINATION_PAGES = 100

# 주문 관련 tr_id (재시도 횟수 분류용)
_ORDER_TR_IDS = frozenset(
    {
        "VTTC0012U",
        "TTTC0012U",  # 매수
        "VTTC0011U",
        "TTTC0011U",  # 매도
        "VTTC0013U",
        "TTTC0013U",  # 취소 (#2346 라이브 A/B both_ok 2026-06-12, 신세대 0013U)
    }
)

# 거래소ID구분코드(EXCG_ID_DVSN_CD) 기본값.
# 에픽 #2354 일관성 목표의 공유 단일 출처 — order-cash(#2344) 외 후속 이슈
# (inquire-daily-ccld #2349 등)가 재사용할 예정이다. 국내 KRX 주문 기본값으로,
# NXT/SOR 등 다른 거래소 라우팅은 현재 미지원(요구 발생 시 config 표면화는 후속).
DEFAULT_EXCG_ID_DVSN_CD = "KRX"

# inquire-daily-ccld(주문/체결 이력) TR ID 매핑 (#2349).
# KIS 공식 현행은 3개월 경계(inner/before) × 모의/실전 4코드로 분기한다. 레거시
# 단일 코드(`*8001R` 세대)와 레거시 before(`*9115R` 세대)는 비채택.
# 출처: KIS open-trading-api examples_llm/domestic_stock/inquire_daily_ccld.
#   - inner(조회 기준일로부터 3개월 이내): 모의 VTTC0081R / 실전 TTTC0081R
#   - before(3개월 이전): 모의 VTSC9215R / 실전 CTSC9215R
_CCLD_TR_ID_INNER_PAPER = "VTTC0081R"
_CCLD_TR_ID_INNER_LIVE = "TTTC0081R"
_CCLD_TR_ID_BEFORE_PAPER = "VTSC9215R"
_CCLD_TR_ID_BEFORE_LIVE = "CTSC9215R"

# inquire-daily-ccld inner/before 판정의 3개월 경계(ante 로컬 normative 정책).
# 공식 예제는 pd_dv=inner|before 를 호출자 인자로 받을 뿐 경계를 계산하지 않으므로
# ante 가 정책을 소유한다(#2349). KST 오늘 기준 달력 3개월 전 동일 일자가 cutoff.
_CCLD_BOUNDARY_MONTHS = 3

# inquire-psbl-order(매수가능 조회) TR ID 매핑 (#2384).
# 출처: KIS open-trading-api examples_llm/domestic_stock/inquire_psbl_order.
_PSBL_ORDER_TR_ID_PAPER = "VTTC8908R"
_PSBL_ORDER_TR_ID_LIVE = "TTTC8908R"

# inquire-psbl-order 응답 필드 → get_buyable() 반환 키 SSOT 매핑 (#2384).
# purchasable_amount(주문가능액)의 SSOT는 order_buyable_amount←nrcvb_buy_amt다
# (미수 미사용 매수가능금액, 보수값). nrcvb_buy_amt 종목 불변성 가정이 oracle
# 검증에서 깨지면 ord_psbl_cash(주문가능현금, 종목 의존성 최소) 폴백으로 전환
# 가능하도록 필드명을 한 곳에 모은다. 폴백은 missing/parse-failure 또는 명시적
# config 전환에 한정하며 value==0 은 정상값이라 폴백 트리거가 아니다(#2384 G6).
_PSBL_ORDER_FIELD_BUYABLE_AMOUNT = "nrcvb_buy_amt"  # purchasable_amount SSOT
_PSBL_ORDER_FIELD_MAX_BUYABLE_AMOUNT = "max_buy_amt"
_PSBL_ORDER_FIELD_ORDER_CASH = "ord_psbl_cash"  # 종목무관 폴백 SSOT 후보
_PSBL_ORDER_FIELD_BUYABLE_QTY = "nrcvb_buy_qty"
_PSBL_ORDER_FIELD_MAX_BUYABLE_QTY = "max_buy_qty"

# 인증 경로
_AUTH_PATH = "/oauth2/tokenP"


# ── OAuth2 토큰 single-flight + in-process shared 캐시 (#2399) ──────────
#
# 동일 ``app_key`` 를 공유하는 다중 adapter(KIS 국내/해외 분리 D-ACC-02, 같은
# app_key)가 동시에 토큰을 발급하면 KIS 가 ``EGW00133`` (접근토큰 발급 1분 1회)을
# 돌려준다. 이를 막기 위해 토큰 캐시와 발급 lock 을 **module-level(프로세스 전역)**
# 으로 공유하고, 발급을 **app_key 단위** asyncio.Lock 으로 직렬화한다.
#
# - lock key = **app_key** (account_id 아님!). account_id 로 잡으면 동일 app_key
#   다중 adapter 가 미수렴하여 ``EGW00133`` 이 잔존한다(회귀 락 — T1).
# - 캐시 hit 시 발급 skip, double-check 로 대기 중 타 코루틴이 발급한 토큰 재사용.
#
# known-limitation (T7, v1): 본 캐시/lock 은 **in-process(단일 프로세스)** 한정이다.
# 멀티프로세스(CLI 8 site 가 각각 fresh AccountService 생성) 토큰 공유는 v1 미해결 —
# CLI cold-path 다발 동시 실행 시 ``EGW00133`` 잔존 가능. 영속(파일/DB) 토큰 스토어는
# 후속 후보(YAGNI, spec 07 OAuth2 §(7) anchor).
#
# 캐시 키 vs lock/cooldown 키 분리 (#2399 attempt4 P2 — config fingerprint):
# - ``_token_cache`` 키 = **(app_key, app_secret, env)** config fingerprint.
#   credentials(app_secret)/환경(모의 vs 실전 base_url)이 바뀌면 다른 키 → cache
#   miss → ``connect()``/``_authenticate()`` 가 새 토큰을 **실제 발급**하여 새 설정을
#   검증한다. 같은 app_key 기존 토큰을 hydrate 해 잘못된 secret/환경 전환을 성공한
#   재연결로 오판하던 회귀를 차단한다(``AccountService._reconnect_broker`` 가
#   변경된 ``credentials``/``broker_config`` 로 새 어댑터 ``connect()`` 를 호출하는
#   경로 보호). **동일 config(같은 app_key+secret+env) 공유 어댑터(국내/해외)는 같은
#   키 → single-flight 수렴·토큰 공유**(원래 #2399 목표 보존).
# - ``_token_locks`` / ``_token_cooldowns`` 키 = **app_key 유지**. single-flight
#   직렬화와 EGW00133(접근토큰 발급 1분 1회) cooldown 은 KIS rate-limit 단위인
#   **app_key 당**이라 secret/환경 무관하다. config fingerprint 로 좁히면 같은
#   app_key·다른 config 동시 발급이 rate-limit 을 공유하지 못해 EGW00133 잔존
#   위험이 생긴다(T1 lock=app_key / T4 cooldown=app_key 회귀 락).
_TokenCacheKey = tuple[str, str, str]
"""(app_key, app_secret, env) config fingerprint — ``_token_cache`` 키 타입."""

_token_cache: dict[_TokenCacheKey, tuple[str, datetime]] = {}
"""config fingerprint → (access_token, expires_at) in-process shared 캐시 (#2399 T2).

키는 ``(app_key, app_secret, env)`` 다(``env`` = 모의/실전 구분). 같은 config 는 같은
키로 single-flight 수렴·토큰 공유, 다른 secret/환경은 다른 키로 cache miss → 재발급
(config 변경 재검증, attempt4 P2)."""

_token_locks: dict[str, asyncio.Lock] = {}
"""app_key → 발급 직렬화 Lock (#2399 T1, lock key=app_key — rate-limit 단위)."""

_token_cooldowns: dict[str, datetime] = {}
"""app_key → cooldown_until (UTC) — EGW00133 source-level cooldown (#2399).

EGW00133(접근토큰 발급 1분 1회)을 받으면 ``_raise_token_error`` 가 ``app_key`` 에
``now(UTC) + TOKEN_RATE_LIMIT_COOLDOWN_SECONDS`` 를 기록한다. ``_authenticate`` 는
유효 캐시 hit(T2)이 아닌 발급 경로에서 lock 밖 fast-path + lock 안 double-check 로
cooldown 을 확인해, cooldown 내면 **HTTP 미호출·즉시 ``TokenRateLimitError``** 를
raise 한다. 모든 get_broker→토큰 발급 경로(startup/self-healing/runtime/IPC)가 이
단일 chokepoint 를 존중하므로 per-call-site 필터 없이 단일 cadence(T4)가 보장된다.
T2 불변: 유효 캐시 토큰 read 는 cooldown 과 무관(hydrate 먼저)하다."""


# lock dict 의 lazy 생성 경합(첫 Lock 생성 race)을 막는 동기 guard.
# ``_get_token_lock`` 이 ``setdefault`` 로 원자적으로 Lock 을 보장한다 — 동기 구간
# 이라 코루틴 yield 가 없어 race 가 없으나, 의도를 명시한다(T1 lock dict race).
def _get_token_lock(app_key: str) -> asyncio.Lock:
    """app_key 별 발급 Lock 을 lazy 생성/반환 (동기 구간, race-free).

    ``dict.setdefault`` 는 GIL 하 단일 bytecode 로 원자적이고 await 가 없어 코루틴
    yield 가 발생하지 않으므로, 동시 호출에서도 동일 app_key 는 **하나의** Lock 으로
    수렴한다(#2399 T1 lock dict 생성 race 원자화).
    """
    return _token_locks.setdefault(app_key, asyncio.Lock())


def _reset_token_cache() -> None:
    """module-level 토큰 캐시/lock/cooldown dict 초기화 (#2399, 테스트 격리용).

    pytest-asyncio auto mode 에서 이전 테스트의 closed event loop 에 묶인 Lock 이
    재사용되는 위험(T1 closed-loop)을 차단하기 위해, autouse fixture 가 매 테스트
    전후로 본 helper 를 호출한다. 프로덕션 경로는 호출하지 않는다.

    #2399 attempt3/메타: ``_token_cooldowns`` 도 함께 clear 한다. EGW00133 cooldown
    상태가 테스트 간 누출되면 후속 테스트의 발급이 cooldown 내로 오판돼 flaky 가
    되므로, 글로벌 conftest autouse fixture 가 본 helper 로 cooldown 까지 초기화한다.
    """
    _token_cache.clear()
    _token_locks.clear()
    _token_cooldowns.clear()


def _token_cooldown_until(app_key: str) -> datetime | None:
    """app_key 의 현재 EGW00133 cooldown 만료시각(UTC) 또는 ``None`` (#2399 attempt3).

    startup wrapper(``main._get_broker_with_auth_retry``)가 잔여 cooldown
    (``cooldown_until - now``)만큼 sleep 하기 위해 조회한다. 만료된 cooldown 은
    ``None`` 으로 보고(자동 만료) 다음 발급을 허용한다.
    """
    until = _token_cooldowns.get(app_key)
    if until is None:
        return None
    if datetime.now(UTC) >= until:
        return None
    return until


def _record_token_cooldown(app_key: str) -> datetime:
    """EGW00133 수신 시 app_key cooldown 기록 후 만료시각 반환 (#2399 attempt3).

    ``now(UTC) + TOKEN_RATE_LIMIT_COOLDOWN_SECONDS`` 를 기록한다. ``_raise_token_error``
    가 ``TokenRateLimitError`` raise **직전** 호출한다. cooldown 내 차단 경로
    (``_authenticate`` fast-path/double-check)는 기존 cooldown 을 **연장하지 않고**
    그대로 둔다(아래 ``_raise_token_rate_limit`` 참조).
    """
    until = datetime.now(UTC) + timedelta(seconds=TOKEN_RATE_LIMIT_COOLDOWN_SECONDS)
    _token_cooldowns[app_key] = until
    return until


def _raise_token_rate_limit(app_key: str, *, record: bool = True) -> NoReturn:
    """EGW00133 ``TokenRateLimitError`` raise (#2399 attempt3, cooldown_until 동봉).

    HTTP 발급에서 EGW00133 을 받은 경로(``_raise_token_error``, ``record=True`` —
    새 cooldown 기록)와 cooldown 내 발급 차단 경로(``_authenticate`` fast-path/
    double-check, ``record=False`` — 기존 cooldown 존중·연장 금지)가 동일한 raise
    동작을 공유한다(source-level 단일 chokepoint). 예외에 잔여 cooldown 만료시각
    (``cooldown_until``)을 실어 startup wrapper 가 잔여만큼 sleep 하게 한다.
    """
    if record:
        until: datetime | None = _record_token_cooldown(app_key)
    else:
        # cooldown 내 차단 — 기존 만료시각을 그대로 노출(연장 금지). 경합으로 이미
        # 만료됐으면(드묾) 새로 기록하지 않고 None 을 실어 보낸다(다음 발급 허용).
        until = _token_cooldown_until(app_key)
    msg = get_error_message(TOKEN_RATE_LIMIT_MSG_CODE)
    raise TokenRateLimitError(
        f"토큰 발급 빈도 제한 ({TOKEN_RATE_LIMIT_MSG_CODE}): {msg}",
        error_code=TOKEN_RATE_LIMIT_MSG_CODE,
        cooldown_until=until,
    )


def _is_cached_token_fresh(expires_at: datetime, *, now: datetime) -> bool:
    """캐시 토큰이 near-expiry 여유(만료 5분 전) 내에서 아직 신선한지 (#2399 T2).

    ``_ensure_authenticated`` 의 "만료 5분 전 재발급" 기준과 **동일**하다 —
    near-expiry 토큰은 hit 이 아니라 miss 로 보고 재발급한다.
    """
    return now < expires_at - timedelta(minutes=_TOKEN_EXPIRY_MARGIN_MINUTES)


# 취소(order-rvsecncl) 시 전송할 KRX_FWDG_ORD_ORGNO 캐시 상한.
# 어댑터 인스턴스(=계좌)당 미체결 주문 수를 넉넉히 덮으면서 무한 증가를 막는다.
# 초과 시 가장 오래된 항목부터 제거(LRU 근사: insertion-order eviction).
_KRX_FWDG_ORGNO_CACHE_MAXLEN = 1024


def _ccld_three_month_cutoff(today_kst: str) -> str:
    """inquire-daily-ccld inner/before 경계 cutoff ``YYYYMMDD`` (#2349, normative).

    KST 오늘(``today_kst``, ``YYYYMMDD``) 기준 **달력 3개월 전 동일 일자**를
    cutoff 로 산출한다. 대상 월에 동일 일자가 없으면(예: 5/31 → 2/31 부재) 그
    월의 **말일**로 보정한다(예: 2026-05-31 → 2026-02-28).

    ``INQR_STRT_DT >= cutoff`` 이면 inner(cutoff 당일 포함), ``< cutoff`` 이면
    before 로 판정한다(start-date 단독 기준). 공식 예제는 ``pd_dv`` 인자를 받을
    뿐 경계를 계산하지 않으므로 본 cutoff 산식은 ante 로컬 정책이다.
    """
    year = int(today_kst[:4])
    month = int(today_kst[4:6])
    day = int(today_kst[6:8])
    # 달력 3개월 전 (year, month) 산출.
    total = (year * 12 + (month - 1)) - _CCLD_BOUNDARY_MONTHS
    target_year, target_month = divmod(total, 12)
    target_month += 1
    # 말일 보정: 대상 월에 동일 일자가 없으면 그 월 말일로 clamp.
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
    """inquire-psbl-order 금액 필드 파싱 (#2384, primary missing/parse 시만 폴백).

    ``primary_field``(``nrcvb_buy_amt``)가 응답에 없거나 float 변환에 실패할 때만
    ``fallback_field``(``ord_psbl_cash``)로 폴백한다. ``primary_field`` 값이
    ``0``으로 정상 파싱되면 그대로 ``0.0``을 반환한다 — ``0``은 정상값일 수
    있으므로 폴백 트리거가 아니다(#2384 G6).
    """
    if primary_field in output:
        try:
            return float(output[primary_field])
        except (TypeError, ValueError):
            pass
    return _to_float(output.get(fallback_field))


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
        # 알 수 없는 에러는 재시도하지 않음
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
        return self._backoff_base * (2**attempt)

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


# ── KISBaseAdapter — KIS 공통 레이어 ─────────────────────


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

        # API 엔드포인트
        if self.is_paper:
            self.base_url = "https://openapivts.koreainvestment.com:29443"
            self.websocket_url = "ws://ops.koreainvestment.com:31000"
        else:
            self.base_url = "https://openapi.koreainvestment.com:9443"
            self.websocket_url = "ws://ops.koreainvestment.com:21000"

        # 인증
        self.access_token: str | None = None
        self.token_expires_at: datetime | None = None

        # HTTP 세션
        self._session: Any = None

        # Rate limiting
        self._request_times: list[datetime] = []
        self._rate_limit_per_minute: int = 5 if self.is_paper else 20

        # ── 재시도 설정 ────────────────────────────────
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

        # ── 타임아웃 설정 ──────────────────────────────
        self._timeout_order: float = config.get("timeout.order", DEFAULT_TIMEOUT_ORDER)
        self._timeout_query: float = config.get("timeout.query", DEFAULT_TIMEOUT_QUERY)
        self._timeout_auth: float = config.get("timeout.auth", DEFAULT_TIMEOUT_AUTH)

        # ── Circuit Breaker ────────────────────────────
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

        # ── 재시도 핸들러 ─────────────────────────────
        self._retry_handler = KISRetryHandler(backoff_base=self._backoff_base)

    @property
    def circuit_breaker(self) -> CircuitBreaker:
        """Circuit breaker 접근자."""
        return self._circuit_breaker

    # ── 연결 ───────────────────────────────────────

    async def connect(self) -> None:
        """KIS API 연결 및 인증.

        멱등(#2372): 이미 연결된 상태(``is_connected`` 이고 활성 session 보유)면
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
            # 인증 실패/취소 시 connect()가 소유한 session을 닫는다 (#2368).
            # connect() 성공 전까지 session은 connect()가 소유하므로,
            # 모든 호출자(CLI _get_broker/account service/runtime)가 공통으로
            # aiohttp Unclosed 경고/리소스 누수에서 벗어난다.
            session, self._session = self._session, None
            try:
                await session.close()
            except Exception:
                pass  # close 실패 swallow — 원본 예외 보존
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

    # ── 인증 ───────────────────────────────────────

    async def _authenticate(self) -> None:
        """OAuth2 접근 토큰 발급 — single-flight + shared 캐시 + cooldown (#2399).

        절차 (T1/T2/T4 source-level cooldown):
        1. **캐시 read**: module-level ``_token_cache`` 에 본 어댑터의 config
           fingerprint(app_key+secret+env, attempt4 P2) 신선한 토큰(near-expiry 5분
           여유 내)이 있으면 발급 skip — 인스턴스에 hydrate 후 반환. config 가 바뀐
           재연결은 다른 키라 cache miss → 새 발급으로 새 설정을 검증한다.
           **유효 캐시 read 는 cooldown 무영향**(T2 — hydrate 를 cooldown 체크보다
           먼저 둔다).
        2. **cooldown fast-path(lock 밖)**: cache miss 면 ``_token_cooldowns`` 를
           확인해 cooldown 내면 **HTTP 미호출·즉시 ``TokenRateLimitError``** raise
           (get_broker→토큰 재타격 source-level 차단, T4 단일 cadence).
        3. **app_key lock** 획득(account_id 아님 — 동일 app_key 다중 adapter 수렴).
        4. **double-check(캐시)**: lock 대기 중 타 코루틴이 발급했으면 재사용(skip).
        5. **cooldown double-check(lock 안)**: lock 대기 중 타 코루틴이 EGW00133 으로
           cooldown 을 기록했을 수 있으므로 한 번 더 확인 → cooldown 내면 즉시 raise.
        6. **발급 1회**: HTTP 호출 → 캐시 populate → 인스턴스 hydrate. 발급이
           EGW00133 이면 ``_issue_token``→``_raise_token_error`` 가 cooldown 기록 후
           ``TokenRateLimitError`` 를 **즉시 raise** 한다(내부 sleep/retry 없음).

        ~60s backoff cadence 는 호출부 단일 레이어(startup wrapper / self-healing
        interval)가 분담하고, 발급 차단 자체는 본 cooldown 이 source 에서 보장한다.
        """
        # (1) 캐시 read — lock 없이 fast-path. 신선하면 발급 skip(cooldown 무영향, T2).
        if self._hydrate_from_cache():
            return

        # (2) cooldown fast-path(lock 밖) — cooldown 내면 HTTP 미호출·즉시 raise (T4).
        # record=False: 기존 cooldown 존중(연장 금지, source 기록은 EGW00133 수신 시만).
        if _token_cooldown_until(self.app_key) is not None:
            _raise_token_rate_limit(self.app_key, record=False)

        # (3) app_key 단위 lock 으로 발급 직렬화 (T1).
        lock = _get_token_lock(self.app_key)
        async with lock:
            # (4) double-check(캐시) — 대기 중 타 코루틴이 발급했으면 재사용.
            if self._hydrate_from_cache():
                return
            # (5) cooldown double-check(lock 안) — 대기 중 타 코루틴이 EGW00133 으로
            # cooldown 을 기록했을 수 있다. cooldown 내면 즉시 raise(HTTP 미호출).
            if _token_cooldown_until(self.app_key) is not None:
                _raise_token_rate_limit(self.app_key, record=False)
            # (6) 발급 1회 → 캐시 populate → 인스턴스 hydrate. EGW00133 이면
            # _issue_token 이 cooldown 기록 후 TokenRateLimitError 를 즉시 raise.
            # 캐시 key 는 config fingerprint(attempt4 P2) — 같은 config 공유 어댑터는
            # 같은 키로 토큰 공유, 다른 secret/환경은 별도 키로 격리 발급된다.
            token, expires_at = await self._issue_token()
            _token_cache[self._token_cache_key()] = (token, expires_at)
            self.access_token = token
            self.token_expires_at = expires_at
            logger.info("KIS 토큰 발급 완료")

    def _token_cache_key(self) -> _TokenCacheKey:
        """``_token_cache`` config fingerprint 키 — (app_key, app_secret, env) (#2399).

        attempt4 P2: 캐시 키에 ``app_secret`` 과 환경(모의 vs 실전)을 포함해, 같은
        app_key 라도 credentials/환경이 바뀌면 다른 키로 cache miss → 새 토큰 발급으로
        새 설정을 검증한다(``AccountService._reconnect_broker`` 의 secret/환경 전환
        재검증). 환경 구분은 ``is_paper`` (base_url 도출 출처)를 그대로 쓴다 — 모의
        ``openapivts``/실전 ``openapi`` base_url 이 ``is_paper`` 로 1:1 결정되므로
        ``is_paper`` 가 환경의 SSOT 다. lock/cooldown 키(app_key)와 달리 본 키만
        config-specific 으로 좁힌다.
        """
        env = "paper" if self.is_paper else "live"
        return (self.app_key, self.app_secret, env)

    def _hydrate_from_cache(self) -> bool:
        """shared 캐시에 신선한 토큰이 있으면 인스턴스에 hydrate (#2399 T2).

        near-expiry(만료 5분 전) 토큰은 miss 로 보고 ``False`` 반환(재발급 유도).
        캐시 key 는 config fingerprint(app_key+secret+env)라, config 가 바뀐 어댑터는
        같은 app_key 라도 cache miss → 재발급(attempt4 P2 config 변경 재검증).
        """
        cached = _token_cache.get(self._token_cache_key())
        if cached is None:
            return False
        token, expires_at = cached
        if not _is_cached_token_fresh(expires_at, now=datetime.now(UTC)):
            return False
        self.access_token = token
        self.token_expires_at = expires_at
        return True

    async def _issue_token(self) -> tuple[str, datetime]:
        """KIS OAuth2 토큰 1회 발급 — msg_cd 파싱 + EGW00133 즉시 raise (#2399 T3/T4).

        토큰 발급 응답에서 KIS 에러코드를 파싱한다. alias 방어 (T3): 코드는
        ``msg_cd``/``error_code``, 메시지는 ``msg1``/``error_description`` 양쪽 키를
        모두 본다(KIS 토큰 엔드포인트 실제 형태 미확정). 응답 형태는 **HTTP 200 +
        error 바디(rt_cd≠"0" 또는 access_token 부재)** 와 **non-200** 양 분기 모두
        에러코드를 추출한다. (일반 API 응답 파싱은 ``_handle_response`` 가 담당 —
        본 메서드는 토큰 발급 경로 **한정**.)

        ``EGW00133`` 감지 시 ``TokenRateLimitError`` 즉시 raise(내부 sleep 없음).
        그 외 에러는 ``AuthenticationError`` 로 raise(코드가 있으면 보존).

        Returns:
            (access_token, expires_at) — 발급 성공 시.
        """
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
                    # non-200 분기: JSON body 에서 에러코드 추출 시도(실패 시 text).
                    body = await self._read_token_error_body(response)
                    self._raise_token_error(response.status, body)

                result = await response.json()
                token = result.get("access_token")
                if not token:
                    # HTTP 200 + error 바디 분기(rt_cd≠"0" 또는 토큰 부재).
                    self._raise_token_error(response.status, result)

                expires_at = datetime.now(UTC) + timedelta(hours=24)
                return token, expires_at

    @staticmethod
    async def _read_token_error_body(response: Any) -> dict[str, Any] | str:
        """non-200 토큰 응답 body 를 dict(가능 시) 또는 raw text 로 반환 (#2399 T3)."""
        text = await response.text()
        try:
            parsed = json.loads(text)
        except (ValueError, TypeError):
            return text
        if isinstance(parsed, dict):
            return parsed
        return text

    def _raise_token_error(self, status: int, body: dict[str, Any] | str) -> NoReturn:
        """토큰 발급 에러 raise — EGW00133 은 TokenRateLimitError (#2399 T3/T4).

        alias 처리(T3): 코드는 ``msg_cd``/``error_code``, 메시지는 ``msg1``/
        ``error_description`` 키를 순서대로 본다.

        #2399 attempt3: EGW00133 감지 시 ``TokenRateLimitError`` raise **직전**
        본 adapter 의 ``app_key`` cooldown 을 기록한다(source-level cooldown).
        """
        code = ""
        detail = ""
        if isinstance(body, dict):
            code = str(body.get("msg_cd") or body.get("error_code") or "")
            detail = str(body.get("msg1") or body.get("error_description") or "")
        text = body if isinstance(body, str) else (detail or json.dumps(body))

        if code == TOKEN_RATE_LIMIT_MSG_CODE:
            # cooldown 기록 후 raise — 같은 app_key 후속 발급(다른 adapter/account
            # 포함)이 cooldown 내 HTTP 미호출·즉시 raise 되도록 (T4 단일 cadence).
            _raise_token_rate_limit(self.app_key)
        raise AuthenticationError(
            f"인증 실패 (HTTP {status}): {text}",
            error_code=code,
        )

    async def _ensure_authenticated(self) -> None:
        """토큰 유효성 확인 및 재발급 (#2399: 재발급도 single-flight/캐시 적용).

        매 API 호출 전 진입점이므로, 캐시 hit 시 ``_authenticate`` 가 발급을 skip
        한다(공유 캐시 fast-path). near-expiry(만료 5분 전) 토큰은 miss 로 보고
        재발급한다 — 본 판정 기준이 ``_is_cached_token_fresh`` 와 동일하다(T2).
        """
        if (
            not self.access_token
            or not self.token_expires_at
            or datetime.now(UTC)
            >= self.token_expires_at - timedelta(minutes=_TOKEN_EXPIRY_MARGIN_MINUTES)
        ):
            await self._authenticate()

    # ── Rate Limiting ──────────────────────────────

    async def _rate_limit_wait(self) -> None:
        """Rate limit 준수 대기."""
        now = datetime.now(UTC)
        cutoff = now - timedelta(minutes=1)
        self._request_times = [t for t in self._request_times if t > cutoff]

        if len(self._request_times) >= self._rate_limit_per_minute:
            oldest = min(self._request_times)
            wait_seconds = 60 - (now - oldest).total_seconds()
            if wait_seconds > 0:
                logger.debug("Rate limit 대기: %.1f초", wait_seconds)
                await asyncio.sleep(wait_seconds)

        self._request_times.append(now)

    # ── 타임아웃 / 재시도 설정 ─────────────────────

    def _get_timeout(self, url: str) -> float:
        """URL 기반 타임아웃 결정."""
        if _AUTH_PATH in url:
            return self._timeout_auth
        return self._timeout_order  # 주문/조회 기본값

    def _get_max_retries(self, url: str, tr_id: str) -> int:
        """API 유형별 최대 재시도 횟수."""
        if _AUTH_PATH in url:
            return self._max_retries_auth
        if tr_id in _ORDER_TR_IDS:
            return self._max_retries_order
        return self._max_retries_query

    # ── 헤더/응답 처리 ─────────────────────────────

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
        """API 응답 처리 (에러 분류 포함).

        HTTP status != 200이면서 응답 body에 KIS business payload(``rt_cd`` /
        ``msg_cd``)가 함께 들어오는 경우 broker business error로 승격해
        ``APIError.error_code``에 ``msg_cd``를 보존한다.

        retryable 우선순위 (#1338):
            1. ``msg_cd`` ∈ ``PERMANENT_MSG_CODES`` → ``False`` (강제).
            2. HTTP status가 non-retryable(401/403/404/422 등) → ``False`` (강제).
            3. ``msg_cd`` ∈ ``TRANSIENT_MSG_CODES`` → ``True``.
            4. 그 외 unknown msg_cd는 HTTP status retryable에 따른다.

        JSON 파싱 실패, ``rt_cd`` 부재, ``rt_cd == "0"`` 등 KIS payload로
        판정되지 않는 경우는 generic ``HTTP <status>: <text>``로 fallback한다.
        """
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
                # msg1이 빈 문자열/공백이면 get_error_message(msg_cd)로 폴백해
                # error_message가 비어 있지 않도록 보장한다 (#2324). 이 분기는
                # msg_cd truthy일 때만 실행되므로 폴백은 항상 의미 있는 값이다.
                msg1 = str(payload.get("msg1") or "").strip()
                if not msg1:
                    msg1 = get_error_message(msg_cd)
                # retryable 우선순위 (#1338, Codex Plan Review v2):
                # 1. PERMANENT_MSG_CODES → false 강제.
                # 2. HTTP non-retryable (auth/client) → false 강제.
                # 3. TRANSIENT_MSG_CODES → true.
                # 4. 기본은 HTTP retryable.
                if msg_cd in PERMANENT_MSG_CODES:
                    retryable = False
                elif not is_retryable_http_status(response.status):
                    retryable = False
                elif msg_cd in TRANSIENT_MSG_CODES:
                    retryable = True
                # else: HTTP 기준 retryable 유지
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

        result = await response.json()
        rt_cd = result.get("rt_cd", "")
        if rt_cd != "0":
            msg_cd = result.get("msg_cd", "")
            # msg1이 빈 문자열/공백이면 get_error_message(msg_cd)로 폴백해
            # error_message가 비어 있지 않도록 보장한다 (#2324).
            msg1 = str(result.get("msg1") or "").strip()
            if not msg1:
                msg1 = get_error_message(msg_cd)
            retryable = is_retryable_msg_code(msg_cd)
            raise APIError(
                f"KIS API Error [{msg_cd}]: {msg1}",
                error_code=msg_cd,
                retryable=retryable,
            )
        return result

    async def _request(
        self,
        method: str,
        url: str,
        tr_id: str,
        params: dict[str, str] | None = None,
        json_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """API 요청 공통 래퍼 (circuit breaker + 재시도 + 타임아웃).

        body dict만 반환한다. 주문 접수/취소 등 비페이지 호출자가 사용하며,
        응답 ``tr_cont`` 헤더가 필요한 연속조회 경로는 ``_request_with_cont``
        를 사용한다.

        조율만 담당하며, 에러 분류는 KISErrorClassifier,
        재시도 전략은 KISRetryHandler에 위임한다.
        """
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
        """API 요청 공통 래퍼 (circuit breaker + 재시도 + 타임아웃).

        ``(body, tr_cont)`` 튜플을 반환하는 페이지네이션 전용 저수준 변형.
        circuit-breaker / 재시도 / rate-limit / 타임아웃 정책을 ``_request``
        와 **동일하게 공유**한다 (로직 중복 금지). ``cont_header`` 는 KIS 연속
        조회 요청 헤더 ``tr_cont`` 값("" 최초 / "N" 다음)이며, 반환 두 번째
        값은 응답 헤더 ``tr_cont`` ("F"/"M"=다음 있음 / "D"/"E"=마지막)이다.

        ``cb_exempt_timeout`` 은 **호출측 차단기 회계 opt-out** 이다(#2350).
        ``True`` 면 ``TimeoutError`` 계열(aiohttp timeout 포함, ``TimeoutError``
        하위)의 실패를 ``CircuitBreaker.record_failure()`` 에 **기록하지 않는다**.
        late-ccld(``get_order_history``) 조회 타임아웃이 어댑터 전역 단일 차단기를
        OPEN 시켜 무관한 treasury 잔고/포지션 동기화·주문 경로까지 broker-wide 로
        차단하는 cross-concern blast radius 를 끊기 위함이다. 회계 제외는
        ``TimeoutError`` 에 **한정**되며 HTTP 5xx/``APIError`` 등 다른 실패는
        기본값(``False``) 호출자와 동일하게 그대로 기록된다. ``check()`` 는 여전히
        통과하므로 다른 concern 이 연 차단기에는 종속한다(주문 경로 보호 무변경).
        """
        self._circuit_breaker.check()
        await self._ensure_authenticated()
        await self._rate_limit_wait()

        max_retries = self._get_max_retries(url, tr_id)
        timeout = self._timeout_order if tr_id in _ORDER_TR_IDS else self._timeout_query
        headers = self._get_headers(tr_id)
        if cont_header:
            headers["tr_cont"] = cont_header
        last_error: Exception | None = None

        for attempt in range(max_retries + 1):
            try:
                result = await self._send_http(
                    method, url, headers, params, json_data, timeout
                )
                self._circuit_breaker.record_success()
                return result
            except Exception as e:
                retryable, record_failure = KISErrorClassifier.classify(e)
                if not retryable:
                    raise
                # #2350: 차단기 회계 판정은 to_api_error() 변환 **전** raw 예외 e
                # 기준이다. cb_exempt_timeout 이면서 raw 예외가 TimeoutError 계열
                # (aiohttp timeout 포함 — TimeoutError 하위)일 때만 회계에서 제외하고,
                # 그 외 실패(HTTP 5xx/APIError 등)는 기존대로 기록한다.
                last_error = KISErrorClassifier.to_api_error(e, timeout)
                if record_failure and not (
                    cb_exempt_timeout and isinstance(e, TimeoutError)
                ):
                    self._circuit_breaker.record_failure()
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
        """단일 HTTP 요청 실행 (타임아웃 적용).

        ``(body, tr_cont)`` 튜플을 반환한다. ``tr_cont`` 는 KIS 연속조회 응답
        헤더이며, 헤더가 없으면 빈 문자열이다. GET/POST 양쪽 모두 헤더를
        캡처하되 의미 있는 값은 GET 조회 경로에서만 사용된다.
        """
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
        """KIS 연속조회(CTX_AREA + tr_cont)를 따라 전 페이지 행을 누적한다.

        ``base_params`` 는 첫 페이지 요청 파라미터이며 ``CTX_AREA_FK100`` /
        ``CTX_AREA_NK100`` 은 빈 문자열로 시작한다(호출자가 전달). ``row_key``
        로 지정한 단일 행 리스트(예: ``"output1"`` / ``"output"``)만 누적하며,
        ``output2`` 같은 summary/metadata 는 누적하지 않는다.

        ``cb_exempt_timeout`` 은 ``_request_with_cont`` 로 그대로 전파되는 차단기
        회계 opt-out 이다(#2350). late-ccld(``get_order_history``) 폴 경로만
        ``True`` 로 호출해 조회 타임아웃이 어댑터 전역 단일 차단기를 OPEN 시키지
        않게 한다. 다른 호출자는 기본값 ``False`` 로 무변경이다.

        연속 규약:
            - 최초 요청: 요청 헤더 ``tr_cont`` = "" + cursor = "".
            - 응답 헤더 ``tr_cont`` 가 "F"/"M" 이면 body 의 ``ctx_area_fk100`` /
              ``ctx_area_nk100`` 를 다음 요청 ``CTX_AREA_FK100`` /
              ``CTX_AREA_NK100`` 로 넣고 요청 헤더 ``tr_cont`` = "N" 로 재호출.
            - "D"/"E"(또는 그 외) 이면 마지막 페이지로 보고 종료.

        가드:
            - "F"/"M" 인데 다음 cursor 가 비어 있으면 무한루프/누락을 막기 위해
              ``logger.warning`` 후 중단(잔여 페이지 누락 가능성 surface).
            - 최대 페이지 수(``DEFAULT_MAX_PAGINATION_PAGES``) 도달 시
              ``logger.warning`` 후 중단.
        """
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
                # "D"/"E" 또는 헤더 부재 → 마지막 페이지.
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

    # ── 서브클래스 확장 포인트 ──────────────────────

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
        """주문 정정 (#2391, v1=price-only)."""
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


# ── KISDomesticAdapter — 국내주식 전용 ────────────────────


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

        # 수수료율 (buy/sell 분리)
        self._buy_commission_rate: float = config.get(
            "buy_commission_rate",
            config.get("commission_rate", 0.00015),
        )
        self._sell_commission_rate: float = config.get(
            "sell_commission_rate",
            # 하위호환: commission_rate + sell_tax_rate
            config.get("commission_rate", 0.00015)
            + config.get("sell_tax_rate", 0.0018),
        )

        # order-cash 응답에서 캡처한 KRX_FWDG_ORD_ORGNO 캐시 (#2345).
        # 취소(order-rvsecncl)는 원주문별 한국거래소전송주문조직번호를 전송해야
        # 한다. place_order 성공 응답의 output.KRX_FWDG_ORD_ORGNO(non-empty)를
        # (값, 제출 KST 영업일)로 broker_order_id(ODNO)에 매핑해 둔다. cancel_order
        # 는 순수 dict 조회(네트워크 없음)로 이를 주입한다.
        #
        # scope: 어댑터 인스턴스(=계좌, gateway._get_broker(account_id))당 분리.
        #   추가로 KIS odno 는 영업일 재사용 가능(OrderTracker 문서)하므로 캐시
        #   값에 제출 영업일을 함께 두고 취소 시 영업일 불일치면 miss 로 처리한다.
        # bounded: OrderedDict + maxlen 으로 무한 증가/stale 누적을 막는다.
        # known-limitation: in-process 한정(재기동 시 소실 → miss=필드 생략, 안전).
        self._krx_fwdg_orgno_cache: OrderedDict[str, tuple[str, str]] = OrderedDict()

    # ── 계좌 정보 조회 ─────────────────────────────

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
        # purchasable_amount(주문가능액)는 종목 컨텍스트가 필요해 무인자 잔고조회가
        # 산출할 수 없으므로 이 dict에 포함하지 않는다(#2384). psbl_sbst_amt는
        # 예수금 대용가능금액(대용증권 평가 기반)이라 주문가능액과 의미가 다르며
        # 현금-only 계좌에서 정상적으로 0이므로 substitute_amount 키로 보존한다.
        # 주문가능액 SSOT는 get_buyable()의 order_buyable_amount다.
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
        """매수가능 조회 (KIS ``inquire-psbl-order``, #2384).

        ``purchasable_amount``(주문가능액)의 SSOT다. 무인자 ``get_account_balance``
        (``inquire-balance``)는 종목 컨텍스트가 없어 주문가능액을 산출할 수 없으므로
        종목/단가/주문구분을 입력으로 받는 이 메서드가 별도로 조회한다. 모의
        rate-limit(5req/min) 안전을 위해 ``get_account_balance``와 분리한다.

        ORD_DVSN/ORD_UNPR: KIS 공식 샘플(`inquire_psbl_order.py`: pdno=005930,
        ord_unpr='55000', ord_dvsn='01')대로 시장가는 ``ORD_DVSN='01'``이며
        ``ORD_UNPR``은 실제 1주당 가격(필수, '0' 아님)이다. 시장가/``price=None``
        이면 ``get_current_price(symbol)``를 1회 호출해 단가로 사용한다.
        """
        tr_id = _PSBL_ORDER_TR_ID_PAPER if self.is_paper else _PSBL_ORDER_TR_ID_LIVE
        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/inquire-psbl-order"

        # ORD_UNPR은 [필수] 실제 1주당 가격이다(KIS 공식 샘플 확정). 시장가/미지정
        # 이면 현재가를 단가로 사용한다(Treasury 등 호출처에 별도 조회를 추가하지
        # 않고 get_buyable 내부에서 1회 조회).
        unit_price = price
        if unit_price is None:
            unit_price = await self.get_current_price(symbol)

        params = {
            "CANO": self.account_no[:8],
            "ACNT_PRDT_CD": self.account_no[8:10],
            "PDNO": self.normalize_symbol(symbol),
            "ORD_UNPR": str(int(unit_price)),
            "ORD_DVSN": self._map_order_type(order_type),
            "CMA_EVLU_AMT_ICLD_YN": "N",
            "OVRS_ICLD_YN": "N",
        }
        result = await self._request("GET", url, tr_id, params=params)
        output = result.get("output") or {}

        # nrcvb_buy_amt(미수 미사용 매수가능금액)가 order_buyable_amount=
        # purchasable_amount SSOT다. missing/parse-failure 시에만 ord_psbl_cash
        # (주문가능현금)로 폴백한다. nrcvb_buy_amt==0 은 정상값이라 폴백 트리거가
        # 아니다(#2384 G6).
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

    # ── 주문 처리 ──────────────────────────────────

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
        broker_order_id = output["ODNO"]
        # 취소 시 전송할 KRX_FWDG_ORD_ORGNO 를 order-cash 응답에서 직접 캡처한다
        # (#2345). 공식 order-cash 결과 컬럼(chk_order_cash.py)에 ODNO/ORD_TMD 와
        # 함께 KRX_FWDG_ORD_ORGNO 가 정의되어 있다. 응답 구조 변동에 방어적으로
        # 대응하기 위해 .get() 으로 읽고, non-empty 일 때만 캐시한다(오값 전송 금지).
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
        """order-cash 응답의 KRX_FWDG_ORD_ORGNO 를 제출 영업일과 함께 캐시 (#2345).

        non-empty 값만 저장한다. broker_order_id(ODNO) 키로 (값, 제출 KST 영업일)
        을 매핑하며, bounded(OrderedDict + maxlen)로 무한 증가를 막는다.
        취소 시 cancel_order 가 영업일 일치 여부까지 확인해 주입한다.
        """
        if not orgno:
            # 응답에 필드가 없거나 빈 값이면 캐시하지 않는다 → 취소 시 miss(생략).
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
            # 거래소ID구분코드 — KIS 공식 order-cash 현행 계약의 필수 필드(#2344).
            # 공식 order_cash.py 가 excg_id_dvsn_cd 누락 시 ValueError 로 가드한다.
            # market/limit·side 무관 공통(국내 KRX 기본).
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
        return mapping.get(order_type, "01")

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

        취소(order-rvsecncl)는 신세대 tr_id ``VTTC0013U``(모의)/``TTTC0013U``
        (실전)로 전송하며, 신세대 필수 필드 ``EXCG_ID_DVSN_CD``(공유 상수
        ``DEFAULT_EXCG_ID_DVSN_CD="KRX"``)를 포함한다(#2346 라이브 A/B both_ok
        2026-06-12).

        body 에 원주문별 ``KRX_FWDG_ORD_ORGNO``(한국거래소전송주문조직번호)를
        조건부로 전송한다(#2345). 값은 place_order 시 order-cash 응답에서 캡처해
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
            # 신세대(0013U) 필수 필드 — 공유 상수 재사용("KRX" 리터럴 금지, #2344).
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
        """주문 정정 (#2391, v1=price-only). cancel_order 미러링.

        정정(order-rvsecncl)은 취소와 **동일 엔드포인트**를 공유한다. 신세대 tr_id
        ``VTTC0013U``(모의)/``TTTC0013U``(실전)로 전송하며, 취소(``"02"``)와 달리
        ``RVSE_CNCL_DVSN_CD="01"``(정정)을 보낸다. v1 은 가격 정정(수량 불변)만
        지원하므로:

        - ``ORD_QTY`` = 원주문 수량(Gateway 가 ``record.ordered_qty`` 를 ``quantity``
          로 전달, 불변).
        - ``ORD_UNPR`` = 신규 정정 가격(``str(int(price))``). Gateway 가 finite
          ``price>0`` 을 보장한다.
        - ``QTY_ALL_ORD_YN="Y"`` (전량·수량 불변).
        - ``ORD_DVSN`` = ``_map_order_type("limit")`` ("00").
        - ``EXCG_ID_DVSN_CD`` = 공유 상수 ``DEFAULT_EXCG_ID_DVSN_CD``.
        - ``CNDT_PRIC`` (조건가) 미전송 (v1 지정가 정정 비대상).

        ``KRX_FWDG_ORD_ORGNO``(한국거래소전송주문조직번호)는 cancel 과 동일하게
        place_order(order-cash) 응답 캡처 캐시(``_krx_fwdg_orgno_cache``)에서 가져온다.
        취소는 miss 시 필드를 생략(전송)하지만, 정정은 oracle 검증 전이라 보수적으로
        **miss/stale → :class:`ModifyOrgnoUnavailableError` raise(전송 금지)** 한다.
        Gateway 가 이를 ``modify_orgno_unavailable`` 거부로 매핑한다.

        live A/B(실전 KIS) 검증은 사용자 oracle 후속이며, 현재는 mock+모의 매핑/분기
        만 검증한다(pending caveat).
        """
        tr_id = "VTTC0013U" if self.is_paper else "TTTC0013U"
        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/order-rvsecncl"

        cached = self._krx_fwdg_orgno_cache.get(order_id)
        if cached is None or cached[1] != business_date_kst():
            # 오값 전송 금지 — orgno 미상이면 정정 요청을 보내지 않는다(fail-closed).
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
            # 신세대(0013U) 필수 필드 — 공유 상수 재사용("KRX" 리터럴 금지, #2344).
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

    # ── 종목 마스터 ────────────────────────────────────

    async def get_instruments(self, exchange: str = "KRX") -> list[dict[str, Any]]:
        """KIS API에서 종목 마스터 데이터 조회 (코스피 + 코스닥)."""
        instruments: list[dict[str, Any]] = []

        # 코스피(J) + 코스닥(Q)
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

    # 마스터 파일 다운로드 설정 (KIS 공식 방식)
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
        """KIS 마스터 파일 다운로드로 종목 목록 조회.

        기존 CTPF1702R API가 404를 반환하여, KIS 공식 마스터 파일
        다운로드 방식으로 대체 (koreainvestment/open-trading-api 참조).
        """
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

    # ── 수수료 ────────────────────────────────────────

    def get_commission_info(self) -> CommissionInfo:
        """KIS 국내 수수료율 정보 반환."""
        return CommissionInfo(
            buy_commission_rate=self._buy_commission_rate,
            sell_commission_rate=self._sell_commission_rate,
        )

    # ── 대사용 조회 ────────────────────────────────

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

        tr_id 는 KST 3개월 경계(inner/before) × 모의/실전 4코드로 분기한다(#2349).
        조회 시작일(``INQR_STRT_DT``)이 KST 오늘 기준 3개월 전 cutoff 이상이면
        inner(``*0081R``), 미만이면 before(``*9215R``)다(start-date 단독 기준).
        교차 구간(``from < cutoff <= to``)은 split query 없이 start-date 기준
        before 단일 쿼리로 처리하며, 그 완전성은 bounded known-limitation 이다.
        자동 호출자 FillReconcileScheduler 는 항상 ≤7일 창이라 inner 고정이지만,
        사용자 표면 ``ante broker order-history`` (#2412) 는 임의 ``--from`` 을
        받으므로 before 분기와 교차 구간이 실제로 도달 가능하다 — 한계는 CLI
        ``--help`` / 스펙으로 노출하며 여기서 거부하지 않는다(정책 무변경).
        """
        # 기본 날짜 산출은 UTC 현행 유지(기존 동작 invariant). KST 는 경계 판정에만.
        now = datetime.now(UTC)
        start_date = from_date or (now - timedelta(days=7)).strftime("%Y%m%d")
        end_date = to_date or now.strftime("%Y%m%d")

        # 3개월 경계 판정: KST 오늘 기준 cutoff 와 start_date 비교(start-date 단독).
        cutoff = _ccld_three_month_cutoff(business_date_kst())
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
            # 거래소ID구분코드 hygiene(#2349). order-cash(#2344)의 40910000
            # 거절-fix 와 달리 이 엔드포인트는 hard-required 가 아니며, 데이터
            # 완전성(NXT 누락 방지)을 위한 optional 주입이다(공식 조건부 append).
            "EXCG_ID_DVSN_CD": DEFAULT_EXCG_ID_DVSN_CD,
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": "",
        }

        # #2350: late-ccld 조회 타임아웃은 차단기 회계에서 제외한다. 체결이력 폴이
        # 반복 타임아웃해도 어댑터 전역 단일 차단기가 OPEN 되지 않아, 같은 어댑터를
        # 공유하는 treasury 잔고/포지션 동기화·주문 경로가 broker-wide 로 차단되지
        # 않는다. 회계 제외는 TimeoutError 에 한정되며 5xx/APIError 등은 그대로
        # 기록된다(주문 경로 보호 무변경).
        rows = await self._request_paginated(
            "GET", url, tr_id, params, row_key="output1", cb_exempt_timeout=True
        )
        return self._fold_order_history(rows)

    @staticmethod
    def _fold_order_history(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """inquire-daily-ccld ``output1`` 행을 (odno, 영업일)별로 fold.

        KIS ``output1`` 은 조회 구분에 따라 주문별 누적 1행 또는 부분체결별 다행이
        올 수 있다 (#1946 R1-4). 같은 ``odno`` + ``ord_dt`` 행을 하나로 접되:

        - ``filled_quantity`` = 누적 체결수량 ``tot_ccld_qty`` 의 **max**
          (누적 행이면 마지막 값, 부분체결 행이면 단조 증가하므로 max 가 안전).
        - ``price`` = **실체결가** = ``tot_ccld_amt`` / ``tot_ccld_qty``
          (체결금액/체결수량). ``tot_ccld_amt`` 가 없으면 ``avg_prvs``(평균체결가),
          그것도 없으면 ``ord_unpr``(주문가) 순으로 fallback. 주문가(``ord_unpr``)를
          체결가로 쓰던 기존 매핑을 교정한다.

        ``broker_order_id``(odno) / 누적 체결qty / avg price / 영업일(ord_dt) 을
        반환에 포함해 FillApplier 의 ``(account_id, broker_order_id, submitted_date)``
        조회와 누적 체결 advance 를 가능하게 한다.
        """
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
            # 실체결가 우선순위: 체결금액/체결수량 → 평균체결가 → 주문가.
            if cum_qty > 0 and ccld_amt > 0:
                fill_price = ccld_amt / cum_qty
            elif avg_prvs > 0:
                fill_price = avg_prvs
            else:
                fill_price = ord_unpr

            key = (odno, ord_dt)
            existing = folded.get(key)
            if existing is None or cum_qty >= existing["filled_quantity"]:
                # 누적 체결qty 가 더 크거나 같은(최신) 행으로 갱신.
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


# ── 하위호환 별칭 ─────────────────────────────────────
# 기존 코드에서 KISAdapter를 참조하는 곳이 있으므로 별칭을 유지한다.
KISAdapter = KISDomesticAdapter
