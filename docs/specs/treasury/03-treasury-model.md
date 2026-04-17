# Treasury 모듈 세부 설계 - 자금 관리 모델

> 인덱스: [README.md](README.md) | 호환 문서: [treasury.md](treasury.md)

# 자금 관리 모델

### 계층 구조

```
전체 계좌 잔고 (Account Balance)
├── 봇별 할당 예산 (Bot Allocation)
│   ├── 봇 A: 500만원 (활성)
│   ├── 봇 B: 300만원 (활성)
│   └── 봇 C: 200만원 (중지)
└── 미할당 자금 (Unallocated)
```

### BotBudget 필드

| 필드 | 타입 | 설명 |
|------|------|------|
| bot_id | str | 봇 고유 ID |
| account_id | str | 소속 계좌 ID |
| allocated | float | 할당된 총 예산 |
| available | float | 가용 예산 |
| reserved | float | 주문 대기 중 예약된 금액 |
| spent | float | 체결로 투입된 금액 (누적) |
| returned | float | 매도 체결로 회수된 금액 (누적) |
| last_updated | datetime | 마지막 갱신 시각 |

**핵심 원리**: `available = allocated - reserved - spent + returned`

- `reserve_for_order()`: 주문 제출 시 available → reserved 이동
- `on_buy_filled()`: reserved → spent 이동 (실제 체결 금액 기준)
- `on_sell_filled()`: returned 증가, available 증가
- `release_reservation()`: 주문 취소/실패 시 reserved → available 복원

소스: `src/ante/treasury/models.py`
