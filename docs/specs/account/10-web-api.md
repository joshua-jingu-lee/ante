# Account 모듈 세부 설계 - Web API 엔드포인트

> 인덱스: [README.md](README.md) | 호환 문서: [account.md](account.md)

# Web API 엔드포인트

### 계좌 전용 엔드포인트

```
GET    /api/accounts                      — 계좌 목록
POST   /api/accounts                      — 계좌 생성 (cold-path 전용, 런타임 서버에서는 409)
GET    /api/accounts/:id                  — 계좌 상세
PUT    /api/accounts/:id                  — 계좌 수정 (런타임에는 비구조 필드만 허용)
POST   /api/accounts/:id/suspend          — 계좌 정지
POST   /api/accounts/:id/activate         — 계좌 재활성화
DELETE /api/accounts/:id                  — 계좌 삭제 (cold-path 전용, 런타임 서버에서는 409)
POST   /api/system/halt                   — 시스템 전역 정지 (모든 ACTIVE 계좌를 SUSPENDED로 전환)
POST   /api/system/clear-halt             — 시스템 전역 정지 해제 (모든 SUSPENDED 계좌를 ACTIVE로 복구; 봇 자동 재시작 아님)
```

### Account payload 필드 계약

Account Web API의 request/response schema는 Account 모델/DB 필드명을 그대로 사용한다.
표준 structural field는 다음과 같다 (#1333: 9 필드).

- `account_id`
- `exchange`
- `currency`
- `broker_type`
- `trading_mode`
- `credentials`
- `broker_config`
- `buy_commission_rate`
- `sell_commission_rate`
- `market_order_reserve_buffer_rate`

`credentials_ref`, `commission_rate`, `sell_tax_rate`는 Web API 필드가 아니다. 이 이름들은
legacy config migration 입력을 설명할 때만 사용하며, API alias로 허용하지 않는다.

### 런타임 차단 규칙

Web API는 서버 프로세스 내부에서 실행되므로 계좌 구조 변경 요청은 기본적으로 런타임 요청이다.
따라서 다음 요청은 1.0에서 409 Conflict를 반환한다.

- `POST /api/accounts`
- `DELETE /api/accounts/:id`
- `PUT /api/accounts/:id` 중 `credentials`, `broker_config`, `buy_commission_rate`,
  `sell_commission_rate`, `market_order_reserve_buffer_rate`, `broker_type`,
  `exchange`, `currency`, `trading_mode`를 포함한 요청 (#1333)

에러 코드는 `ACCOUNT_STRUCTURAL_CHANGE_REQUIRES_STOPPED_SERVER`이다. 계좌 생성/삭제와
브로커 재초기화성 변경은 서버를 정지한 뒤 cold-path CLI로 수행하고, 서버 재시작 시 새
계좌 topology가 반영된다.

`PUT /api/accounts/:id` 본문은 `Content-Type: application/json` (charset suffix 허용)
만 허용하며, 다른 media type은 415 Unsupported Media Type을 반환한다. structural 필드
키 검사(409)는 Content-Type 검사(415)보다 우선한다(invariant I4 — raw key 가드).

`PUT /api/accounts/:id` 요청 본문이 빈 dict(`{}`), 빈 body, 또는 `model_dump(exclude_none=True)` 결과가 빈 dict가 되는 페이로드(예: `{"name": null}`)는 422 Unprocessable Entity를 반환한다 (#1152). schema는 `minProperties: 1`로 표현되며, 이는 OpenAPI/runtime 계약이다 — `openapi-typescript`는 이를 TypeScript 타입 제약으로 내리지 않는다. 빈 body / 빈 dict 검사는 단계 6에서 Content-Type 415 게이트(단계 7)보다 앞서 실행되므로 비-application/json + `{}` 조합도 422로 떨어진다.

Account API의 `trading_hours_start`/`trading_hours_end`는 strict `HH:MM` 24시간 형식이다 (regex `^([01]\d|2[0-3]):[0-5]\d$`, OpenAPI `pattern`으로도 노출). 초/마이크로초 포함(`09:30:00`), invalid 시간(`99:99`), 그리고 `PUT`의 빈 문자열(`""`)은 422 Unprocessable Entity로 거부된다. `POST /api/accounts`의 `AccountCreateRequest`는 `""`를 default 의미(생략 동치)로 허용하여 CLI/seed 경로의 BrokerPreset fallback과 정합을 유지하지만, 런타임 `POST` 자체는 항상 409 cold-path로 차단된다 — 실제 검증 효과는 `PUT` 경로와 schema 소비자(CLI 등)에서 발생한다 (#1334).

### Legacy invalid timezone tolerant load (#1474)

#1473 (split #1419/A) 이전에 `PUT /api/accounts/:id` 가 invalid IANA timezone
(예: `Mars/Olympus`) 을 저장하던 시기의 DB row 호환을 위해 `_row_to_account`
는 tolerant load 를 적용한다.

- invalid IANA timezone 으로 저장된 row 는 `GET /api/accounts` /
  `GET /api/accounts/:id` 가 **fail 없이 200** 으로 응답한다.
- 응답 `account.timezone` 은 fallback `Asia/Seoul` 로 대체되고
  `account.timezone_invalid: true` 진단 플래그가 함께 노출된다.
- 정상 row 는 `account.timezone_invalid: false` 이며 fallback 대체가 일어나지
  않는다. 신규 row 는 `_validate_timezone_create` / `_validate_timezone_update`
  가 ingress 에서 invalid 를 거부하므로 `timezone_invalid: true` 로 들어갈
  경로가 없다.
- 원본 DB row 의 `timezone` 컬럼은 그대로 invalid 상태로 남는다 — 서비스가
  silent rewrite 하지 않는다. 운영자는 `ante account repair-timezone
  --account-id <id> --timezone <valid_iana>` 로 명시적으로 교정해야 한다
  ([09-cli.md](09-cli.md) Legacy invalid timezone row 복구 절차 참조).
- `timezone_invalid` 는 진단 전용 응답 필드다. `PUT /api/accounts/:id` 의
  update mutable 입력에 포함되지 않으며 (`additionalProperties: false`
  schema 의 unknown key 로 422 거부), `AccountUpdateRequest` 의 다른 필드와
  분리된 별도 cold-path 진입점 (`repair_timezone`) 으로만 변경된다.

### 기존 엔드포인트 계좌 필터

멀티 계좌 환경에서 모든 거래·잔고·봇 관련 API 응답에 계좌 컨텍스트를 포함한다.

| 필드 | 추가 대상 | 설명 |
|------|----------|------|
| `account_id` | 봇 목록/상세, 거래 내역, 잔고 조회, 결재 상세 | 소속 계좌 식별 |
| `currency` | 잔고 조회, 거래 내역, 성과 지표 | 금액의 통화 단위 |
| `exchange` | 봇 목록/상세, 종목 관련, 거래 내역 | 거래소 구분 |

```
GET /api/bots?account_id=domestic
GET /api/trades?account_id=domestic
GET /api/treasury/summary?account_id=domestic
GET /api/approvals?account_id=domestic
```

`account_id`를 생략하면 전 계좌 대상 조회 (목록은 합산, 금액은 계좌별 개별 표시).
