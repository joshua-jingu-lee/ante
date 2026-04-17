# Account 모듈 세부 설계 - Web API 엔드포인트

> 인덱스: [README.md](README.md) | 호환 문서: [account.md](account.md)

# Web API 엔드포인트

### 계좌 전용 엔드포인트

```
GET    /api/accounts                      — 계좌 목록
POST   /api/accounts                      — 계좌 생성
GET    /api/accounts/:id                  — 계좌 상세
PUT    /api/accounts/:id                  — 계좌 수정
POST   /api/accounts/:id/suspend          — 계좌 정지
POST   /api/accounts/:id/activate         — 계좌 재활성화
DELETE /api/accounts/:id                  — 계좌 삭제
POST   /api/system/halt                    — 전체 Kill Switch (모든 ACTIVE → SUSPENDED)
POST   /api/system/activate               — 전체 복구 (모든 SUSPENDED → ACTIVE)
```

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
