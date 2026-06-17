# Broker Adapter 모듈 세부 설계 - KISBaseAdapter — KIS 공통 레이어

> 인덱스: [README.md](README.md) | 호환 문서: [broker-adapter.md](broker-adapter.md)

# KISBaseAdapter — KIS 공통 레이어

구현: `src/ante/broker/kis.py` 참조

KISBaseAdapter는 한국투자증권 Open API의 국내/해외 공통 로직을 추상화하는 중간 계층이다. `BrokerAdapter`를 상속하며, 시장별 서브클래스(`KISDomesticAdapter`, `KISOverseasAdapter`)가 이를 상속한다.

### 공통 로직

| 항목 | 설명 |
|------|------|
| OAuth2 인증 | 토큰 발급·갱신·만료 관리 (동일 APP KEY) |
| HTTP 클라이언트 | aiohttp 세션, 헤더 구성, 에러 파싱 |
| Rate Limiter 연동 | APIGateway의 rate limiter 사용 |
| CircuitBreaker | 장애 감지·차단·복구 상태 머신. **어댑터 전역 단일**(주문 경로 보호 우선)이며 주문·조회 모든 경로가 공유한다. **late-ccld(`get_order_history`) `TimeoutError`는 회계에서 제외**(호출측 opt-out)되어 체결이력 폴 타임아웃이 무관한 treasury 동기화·주문 경로를 broker-wide 로 차단하지 않는다(#2350, [10-commission-info.md](10-commission-info.md)). |
| 재시도 로직 | 지수 백오프 + 에러 분류 기반 재시도 |
| Base URL 결정 | `broker_config.is_paper`에 따라 실전/모의 도메인 분기 |
| `connect()` / `disconnect()` | API 연결·해제 |

> **is_paper 처리**: Account의 `broker_config`에서 `is_paper` 값을 읽는다 (기본값: `True`, 모의투자). `is_paper`는 KIS 모의투자/실전투자 엔드포인트를 결정하는 브로커 내부 설정이며, Account의 `trading_mode`와 독립적이다. `trading_mode`는 시스템이 브로커 API를 호출할지 여부(VIRTUAL=가상거래, LIVE=실거래)를 결정하고, `is_paper`는 호출 시 어떤 KIS 서버로 요청할지를 결정한다.

### KIS API 특성 요약

| 항목 | 실전투자 | 모의투자 |
|------|----------|----------|
| REST Base URL | `https://openapi.koreainvestment.com:9443` | `https://openapivts.koreainvestment.com:29443` |
| WebSocket URL | `ws://ops.koreainvestment.com:31000` | `ws://ops.koreainvestment.com:21000` |
| Rate Limit | 분당 20회 | 초당 5회 |
| 인증 방식 | OAuth2 (`client_credentials` grant) | 동일 |
| 토큰 유효기간 | 24시간 | 동일 |
| 인증 엔드포인트 | `/oauth2/tokenP` | 동일 |

### HTTP/Business 에러 분류 (`_handle_response`)

KIS API는 broker-side business failure(예: 원주문번호 오류, 잘못된 종목코드)를 HTTP 200 + `rt_cd != "0"`로만 돌려주지 않는다. 일부 endpoint는 동일한 business failure를 **HTTP 5xx + body에 `rt_cd` / `msg_cd`를 함께 담아** 응답한다 (#1338).

`KISBaseAdapter._handle_response`는 두 케이스 모두를 broker business error로 승격해 `APIError.error_code`에 `msg_cd`를 보존해야 한다. 그렇지 않으면 downstream(`OrderCancelFailedEvent.error_message`, fingerprinting, retry 정책)이 `IGW00022` 같은 안정적인 broker code 대신 generic `HTTP 500: {...}` 문자열로 오분류된다.

규약:

1. HTTP status != 200이면 응답 body를 텍스트(또는 bytes → utf-8)로 읽고 JSON 파싱을 시도한다.
2. 파싱 결과가 dict이고 `rt_cd not in ("", "0")`이면 broker business error로 승격해
   `APIError(error_code=msg_cd, status_code=<http>, retryable=...)` 형태로 raise한다.
3. JSON 파싱 실패, body 부재, 또는 `rt_cd == "0"`이면 generic `HTTP <status>: <text>` `APIError`로 fallback한다.
4. **retryable 우선순위**:
   1. `msg_cd` ∈ `PERMANENT_MSG_CODES` → `False` (강제, HTTP 기준 무시).
   2. HTTP status가 non-retryable(401/403/404/422 등) → `False` (강제, msg_cd 무시).
   3. `msg_cd` ∈ `TRANSIENT_MSG_CODES` → `True`.
   4. 그 외 unknown msg_cd → HTTP status retryable 기준에 위임.
5. **메시지 비공백 보장 (#2324)**: business error 승격 시 `msg1`이 빈 문자열/공백이면 `get_error_message(msg_cd)`로 폴백해 `APIError`의 error_message가 절대 비어 있으면 안 된다. 미등록 코드도 `알 수 없는 에러 ({msg_cd})`로 코드가 보존된 triage-able 메시지가 된다. (generic `HTTP <status>: <text>` fallback 경로는 해당 없음.)

HTTP 200 + `rt_cd != "0"` 경로는 기존 동작을 유지하며 별도로 `error_code = msg_cd`만 설정한다 (status_code 미설정).

### OAuth2 인증 — single-flight + shared cache + EGW00133 backoff (#2396)

> 계약 확정: #2396. 실제 동작은 구현 #2399(축 iii KIS token, 독립) 머지 후. 본 절은 스펙 계약만 정의한다.

**배경 (#2395)**: 현재 토큰 발급은 per-adapter라, 동일 APP KEY를 공유하는 여러 adapter(KIS 국내/해외 분리 [D-ACC-02](../account/02-design-decisions.md#d-acc-02-kis-국내해외가-같은-계좌번호인데-왜-분리하는가), 같은 app_key)가 동시에 토큰을 발급하면 KIS가 `EGW00133`(접근토큰 발급 1분 1회)을 돌려준다. startup race에서 이 압박이 broker connect 실패로 이어진다.

#### (1) single-flight (app_key 단위, in-process)

`_authenticate`(`src/ante/broker/kis.py`)를 **app_key별 `asyncio.Lock`**으로 직렬화하고 double-check를 적용한다.

- lock key = **app_key** (account_id 아님). 동일 app_key를 쓰는 다중 adapter(국내/해외)가 같은 lock으로 수렴해야 동시 발급(→ `EGW00133`)을 막을 수 있다. lock key를 account_id로 잡으면 동일 app_key 다중 adapter가 미수렴하여 `EGW00133`이 잔존한다(회귀 테스트 필수).

#### (2) shared 토큰 캐시 (v1 = in-process)

권고 v1은 **in-process module-level 캐시** `{app_key: (token, expires_at)}` + `asyncio.Lock`이다. adapter `_ensure_authenticated`가 캐시를 우선 조회한다.

#### (3) `_authenticate` msg_cd 파싱 ([must_fix K])

scope 정정: 일반 `_request` 경로는 이미 `msg_cd`를 파싱한다(위 `_handle_response`). **`_authenticate`(토큰 발급 경로)만** `msg_cd`를 미파싱한다(현재 `access_token`만 읽고, 실패 시 raw text로 `AuthenticationError`). 토큰 발급 응답에서 `msg_cd`를 파싱하도록 보강한다.

- 토큰 응답 형태 가정을 명시한다: HTTP 200 + error 바디 vs non-200. `status != 200` 분기 위치를 결정해 파싱 위치를 고정한다(구현 왕복 방지).

#### (4) `EGW00133` ~60s backoff (단일 cadence 레이어, normative)

> **정정 (#2399 adjudicated, rev4)**: 이전 문안은 "`connect`/`_authenticate` 내부 backoff"를 요구했으나, self-healing 의 반복 `connect` 호출과 곱해져 nested-backoff(최악 5×120s)를 유발하는 잠재 버그가 있다. 아래 **단일 cadence** 정의가 정본이다(additive 안전/정확성 개선).

`EGW00133`(KIS 공식 "토큰 발급 1분 1회", 토큰 24h 유효)의 ~60s backoff 는 **정확히 한 cadence 레이어**에만 둬서 곱해지지 않게 한다. 일반 지수 backoff(TRANSIENT)와도 **별도 분기**다.

- **`_authenticate` 는 EGW00133 시 즉시 `TokenRateLimitError`(`AuthenticationError` 서브클래스, `error_code="EGW00133"`)를 raise** 한다 — **내부 sleep/retry 루프 없음**(곱셈 원천 제거). 어떤 caller 루프 안에서도 60s 가 곱해지지 않는다. `connect()` 도 이 예외를 내부 재시도 없이 그대로 전파한다.
- ~60s backoff cadence 는 호출부 **단일 레이어**가 분담한다: (a) **startup**(`main._init_gateway` connect 루프)의 bounded retry(`DEFAULT_MAX_RETRIES_AUTH` × ~60s, 부팅 1회 경로), **또는** (b) **self-healing** loop 의 `interval`(60s) — EGW00133 시 그 계좌 burst 남은 attempt 를 break 하고 다음 interval 에 위임(burst 당 connect 시도 ≤1회).

#### (5) connect-path retry (readiness 연동)

`connect` → `_authenticate` 가 `EGW00133`(`TokenRateLimitError`)을 전파하면, **startup** 경로(`_init_gateway`)는 ~60s backoff 후 `max_retries_auth`([10-commission-info.md](10-commission-info.md) 인증 재시도 기본값) 내 흡수 재시도한다(startup race 완화 — 위 (4)(a) 단일 cadence). 소진 시 해당 계좌를 `not_ready(reason="EGW00133")`로 떨어뜨려 readiness 축([account/02-design-decisions.md — D-ACC-09](../account/02-design-decisions.md#d-acc-09-runtime-readiness-축은-accountstatus와-직교한다))과 연동한다(이 계좌 active 주문 차단). 런타임 회복은 self-healing loop 의 interval(60s) cadence 가 무기한 위임받는다(위 (4)(b)). reason 의 `EGW00133` 은 `AuthenticationError.error_code` 에서 **구조적으로** 추출한다(문자열 grep 금지).

#### (6) classify 불변 invariant ([must_fix J], normative)

`EGW00133` backoff 는 위 (4) **단일 cadence 레이어**(startup wrapper / self-healing interval)에만 있고 `_authenticate` 는 즉시 raise 하므로, gateway 재시도 핸들러·`_request_with_cont` 재시도 루프가 이중 적용하지 않는다. `KISErrorClassifier.classify`의 `AuthenticationError = (retryable=False, record_cb=False)` 분류는 **불변**이다(`TokenRateLimitError` 서브클래스도 동일 분류). classify 를 손대면 connect-path backoff 와 gateway 재시도 핸들러가 이중 적용되거나 `EGW00133`이 즉시 비재시도 전파되는 회귀가 발생한다.

#### (7) known-limitation (normative)

멀티프로세스(8 CLI site가 각각 fresh `AccountService`를 생성) 토큰 공유는 **v1 미해결**이다. in-process single-flight + 캐시는 **단일 서버 런타임 + 동일 프로세스 내 다중 adapter**만 수렴한다(서버 hot-path 해결). 토큰은 24h 유효하나, CLI cold-path 다발 동시 실행 시 `EGW00133`이 잔존할 수 있다.

영속(파일/DB) 토큰스토어는 멀티프로세스 공유가 가능하나 파일 lock / 동시쓰기 / 만료 경합 / 보안(secret 파일) 복잡도가 커서 **v1 범위 밖(YAGNI)**이며 known-limitation으로 명시하고 **후속 후보**로 anchor한다.

### `EGW00133` / `EGW00201` 에러 코드 등록 (#2396)

> 계약 확정: #2396. 실제 동작은 구현 #2399 머지 후.

`error_codes.py`([10-commission-info.md — 에러 코드 분류](10-commission-info.md#에러-코드-분류))에 등록한다(현재 0건 실측). **`EGW00201`만 `TRANSIENT_MSG_CODES`에 추가**한다(일반 지수 backoff). **`EGW00133`은 `TRANSIENT_MSG_CODES`에 넣지 않는다** — 이 set은 `_handle_response`가 `APIError.retryable=True`를 세팅해 일반 `KISRetryHandler` 지수 backoff로 보내는 전역 SSOT이므로, EGW00133을 넣으면 전용 ~60s token-only backoff가 아니라 generic/이중 retry를 탄다. `EGW00133`은 `KIS_ERROR_MESSAGES` 한글 등록 + **토큰 발급 경로 전용 분류(별도 상수 `TOKEN_RATE_LIMIT_MSG_CODE`)**로만 두고, `_authenticate` 가 감지 시 `TokenRateLimitError` 를 즉시 raise 한다(위 (4)). ~60s backoff 는 startup wrapper / self-healing interval 단일 cadence 가 소비한다. 두 코드 모두 `KIS_ERROR_MESSAGES`에 한글 메시지 등록.

| msg_cd | 분류 | 한글 메시지 | 처리 |
|---|---|---|---|
| `EGW00133` | **auth-only(토큰경로 전용, TRANSIENT_MSG_CODES 제외)** | 접근토큰 발급은 1분당 1회만 허용 | `_authenticate` 즉시 `TokenRateLimitError` raise → **단일 cadence ~60s backoff**(startup wrapper / self-healing interval, 위 (4)) |
| `EGW00201` | transient | 초당 거래 건수 초과 | 일반 TRANSIENT 지수 backoff |

`EGW00133`은 일반 TRANSIENT 지수 backoff가 아니라 **단일 cadence ~60s backoff**(startup wrapper / self-healing interval)임을 명시한다(위 (4)·(6) invariant). `EGW00201`은 일반 TRANSIENT 지수 backoff를 따른다.
