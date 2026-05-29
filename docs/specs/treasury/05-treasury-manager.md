# Treasury 모듈 세부 설계 - TreasuryManager

> 인덱스: [README.md](README.md) | 호환 문서: [treasury.md](treasury.md)

# TreasuryManager

계좌별 Treasury 인스턴스를 생성·관리하는 상위 계층이다.

```python
class TreasuryManager:
    """계좌별 Treasury 인스턴스 관리."""

    def __init__(self, db: Database, eventbus: EventBus) -> None: ...

    async def create_treasury(self, account: Account) -> Treasury:
        """Account 정보로 Treasury 인스턴스 생성 및 등록."""

    def get(self, account_id: str) -> Treasury:
        """계좌의 Treasury 인스턴스 반환."""

    def list_all(self) -> list[Treasury]:
        """전체 Treasury 인스턴스 목록."""

    async def initialize_all(self, accounts: list[Account]) -> None:
        """각 계좌에 대해 Treasury 인스턴스 생성·초기화."""

    async def get_total_summary(self) -> dict:
        """전 계좌 합산 요약."""
```

`get_total_summary()` 반환 예시:

```python
{
    "accounts": [
        {"account_id": "domestic", "currency": "KRW", "total_evaluation": 15_000_000},
        {"account_id": "us-stock", "currency": "USD", "total_evaluation": 8_500.00},
    ],
}
```

원화 환산 합산은 Treasury의 책임이 아니다. Treasury는 각 계좌의 통화 기준 잔고만 관리하고, 환율 적용은 별도 서비스에서 수행한다.

소스: `src/ante/treasury/manager.py`

### 이벤트 연동

Treasury는 아래 이벤트를 구독하여 자금 정산을 수행한다 (priority 80: 거래 기록/전략 통보보다 먼저).

**계좌별 이벤트 필터링**: 모든 이벤트 핸들러는 `event.account_id != self._account_id`이면 즉시 반환하여 다른 계좌의 이벤트를 무시한다.

| 구독 이벤트 | priority | 처리 내용 |
|------------|----------|----------|
| OrderValidatedEvent | 80 | 룰 검증 통과 후 자금 예약. 예산 부족 시 OrderRejectedEvent 발행, 성공 시 OrderApprovedEvent 발행 |
| OrderFilledEvent | 80 | 매수: fill(delta)마다 실비용만큼 예약 차감(비례 정산), terminal에서만 잔여 예약 회수. 매도: 회수 금액을 가용 예산에 복원. 거래 이력 기록 (부분체결 비례 정산 #1947 — [03-treasury-model.md](03-treasury-model.md) 참조) |
| OrderCancelledEvent | 80 | **잔여 예약**만 해제 (부분체결 후 취소 시 기체결분 보존) |
| OrderFailedEvent | 80 | **잔여 예약**만 해제 (부분체결 후 실패 시 기체결분 보존) |
| BotStoppedEvent | 80 | 봇 중지 시 해당 봇의 각 주문 **잔여 예약** 일괄 회수 (기체결분 보존) |

> 매수 부분체결 비례 정산(per-fill 차감 · terminal 잔여 회수 · `OrderTracker` terminal 판정 · tracker 부재 시 full-fill fallback)의 상세 의미는 [03-treasury-model.md](03-treasury-model.md) "매수 부분체결 비례 정산"을 따른다. buy 한정 — 매도는 예약 부재로 per-fill 누적 가산이 이미 정확하다(#1947, D5).
