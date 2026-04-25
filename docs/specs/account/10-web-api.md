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
GET    /api/accounts/:id/credentials      — 인증 정보 마스킹 조회
DELETE /api/accounts/:id                  — 계좌 삭제 (cold-path 전용, 런타임 서버에서는 409)
POST   /api/system/kill-switch            — 전체/계좌별 Kill Switch (action=halt|activate, account_id? 생략 시 전체)
```

### 런타임 차단 규칙

Web API는 서버 프로세스 내부에서 실행되므로 계좌 구조 변경 요청은 기본적으로 런타임 요청이다.
따라서 다음 요청은 1.0에서 409 Conflict를 반환한다.

- `POST /api/accounts`
- `DELETE /api/accounts/:id`
- `PUT /api/accounts/:id` 중 `credentials`, `broker_config`, `buy_commission_rate`,
  `sell_commission_rate`, `broker_type`, `exchange`, `currency`, `trading_mode`를 포함한 요청

에러 코드는 `ACCOUNT_STRUCTURAL_CHANGE_REQUIRES_STOPPED_SERVER`이다. 계좌 생성/삭제와
브로커 재초기화성 변경은 서버를 정지한 뒤 cold-path CLI로 수행하고, 서버 재시작 시 새
계좌 topology가 반영된다.

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
