# Trade 모듈 세부 설계 - 알림 이벤트 정의 (Notification Events)

> 인덱스: [README.md](README.md) | 호환 문서: [trade.md](trade.md)

# 알림 이벤트 정의 (Notification Events)

Trade 모듈이 발행하는 `NotificationEvent` 목록. 분산 구조([#489](https://github.com/joshua-jingu-lee/ante/issues/489))에 따라 TradeRecorder가 직접 발행한다.

### 체결 완료 — 매수

**트리거**: `OrderFilledEvent` 수신, `side == "buy"`
**데이터 수집**: TradeRecord (체결 정보) + `PositionHistory.get_current(bot_id, symbol)` (누적 수량, 평단가)

```
👀 매수
봇 bot-001이 005930(삼성전자)을 매수했습니다.
수량: 100주 매수가: 72,000원
누적: 150주 평단가: 82,000원
전략: MACD 크로스
```

### 체결 완료 — 매도

**트리거**: `OrderFilledEvent` 수신, `side == "sell"`
**데이터 수집**: TradeRecord (체결 정보) + `PositionHistory.get_current(bot_id, symbol)` (잔여 수량, 평단가, 실현 손익)

```
👀 매도
봇 bot-001이 005930(삼성전자)을 매도했습니다.
수량: 50주 매도가: 92,000원
잔여: 100주 평단가: 82,000원
손익: 23,000,000원 (30.4%)
전략: MACD 크로스
```

### 주문 취소 실패

**트리거**: `OrderCancelledEvent` 수신, `success == false`
**데이터 수집**: 이벤트 필드 (bot_id, order_id, reason)

```
❌ 주문 취소 실패
봇: bot-001 / 주문: ORD-20260319-001
사유: 이미 체결된 주문입니다
증권사에서 해당 주문 상태를 확인하세요.
```

### 일일 성과 요약 (NotificationEvent)

**트리거**: `DailyReportScheduler` 실행 시, 당일 거래가 **1건 이상**일 때만 발행. 거래 0건이면 발행하지 않음 (기존 동작 유지).
**데이터 수집**:
- `PerformanceTracker.get_daily_summary(bot_id, today, today)` — 봇별 당일 요약
- `PositionHistory.get_all_positions()` — 보유 포지션 현황

```
📊 일일 성과 요약 (2026-03-19)
거래: 12건 (매수 7 / 매도 5)
실현 손익: +1,250,000원
보유 포지션: 4종목
```

### DailyReportScheduler

`ReconcileScheduler`와 동일한 asyncio 루프 패턴으로, 장 마감 후 일일 이벤트를 발행한다.

구현: `src/ante/trade/daily_report.py` 참조

#### 실행 시각

Account 모듈의 `trading_hours_end` + 30분을 실행 시각으로 사용한다. 스케줄러 생성 시 Account 정보를 주입받아 계산한다.

| 프리셋 | `trading_hours_end` | timezone | 실행 시각 |
|--------|--------------------|-----------|-----------|
| kis-domestic | 15:30 | Asia/Seoul | 16:00 KST |
| kis-overseas | 16:00 | America/New_York | 16:30 ET |

> 현재 구현체는 `DEFAULT_REPORT_TIME = time(16, 0)`으로 하드코딩되어 있다. Account 기반 시각 참조로 변경 필요.

#### 이벤트 발행

스케줄러는 매 실행 시 두 종류의 이벤트를 발행한다.

| 이벤트 | 발행 조건 | 목적 |
|--------|----------|------|
| `DailyReportEvent` | **매일 무조건** (휴장일·주말 포함) | Treasury 일별 자산 스냅샷, Rule Engine 일별 리스크 집계 등 하류 모듈 트리거 |
| `NotificationEvent` | 당일 거래 **1건 이상**일 때만 | 사용자 알림 (기존 동작 유지) |

> 시스템에 휴장일 판단 인프라가 없으므로 `DailyReportEvent`는 매일 발행한다.
> 향후 KIS 장운영시세 연동 시 휴장일 스킵 검토 — [phase2-ideas.md](../../temp/phase2-ideas.md#휴장일-캘린더) 참조.

#### DailyReportEvent 필드

| 필드 | 타입 | 설명 |
|------|------|------|
| `account_id` | `str` | 대상 계좌 ID |
| `report_date` | `str` | 대상 날짜 (YYYY-MM-DD, KST 기준) |
| `trade_count` | `int` | 당일 체결 거래 건수 |
| `has_trades` | `bool` | 거래 존재 여부 (`trade_count > 0`) |
| `daily_pnl` | `float` | 당일 손익 (시세 변동분만, 순매수금액 제거) |
| `daily_return` | `float` | 당일 수익률 (`daily_pnl / 전일 ante_eval_amount`) |
| `net_trade_amount` | `float` | 당일 순매수금액 (`Σ매수체결 - Σ매도체결`) |
| `unrealized_pnl` | `float` | 미실현 손익 (`ante_eval_amount - ante_purchase_amount`) |

> **산출 주체는 DailyReportScheduler(Trade 모듈)이다.**
> Treasury는 이 이벤트를 구독하여 성과 필드를 별도 계산 없이 그대로 `treasury_daily_snapshots`에 저장한다.
> 스펙: [treasury.md — 일별 자산 스냅샷](../treasury/treasury.md#일별-자산-스냅샷-daily-asset-snapshot--draft)

#### 일별 성과 산식

DailyReportScheduler가 이벤트 발행 시 아래 산식으로 성과 필드를 계산한다.

**수익률 기준**: Ante 관리 자산 평가액(`ante_eval_amount`) 기반. 미할당 현금은 포함하지 않아 현금 비중에 의한 수익률 희석을 방지한다.

```
순매수금액 = 당일 매수 체결금액 합계 - 당일 매도 체결금액 합계
당일 손익 = 오늘 ante_eval_amount - 순매수금액 - 어제 ante_eval_amount
당일 수익률 = 당일 손익 / 어제 ante_eval_amount
미실현 손익 = ante_eval_amount - ante_purchase_amount
```

| 필드 | 산식 | 비고 |
|------|------|------|
| `daily_pnl` | `오늘 ante_eval_amount - net_trade_amount - 어제 ante_eval_amount` | 순매수금액을 제거하여 시세 변동분만 산출 |
| `daily_return` | `daily_pnl / 어제 ante_eval_amount` | 어제 `ante_eval_amount`가 0이면 0 |
| `net_trade_amount` | `Σ(매수 체결가 × 수량) - Σ(매도 체결가 × 수량)` | 당일 FILLED 거래에서 산출 |
| `unrealized_pnl` | `ante_eval_amount - ante_purchase_amount` | 보유 종목의 평가손익 |

> 기간 수익률은 일별 수익률의 기하평균으로 산출: `(1 + r₁) × (1 + r₂) × ... × (1 + rₙ) - 1`

**첫 스냅샷 (전일 데이터 없음)**: `daily_pnl = 0`, `daily_return = 0`

> DailyReportScheduler는 전일 스냅샷을 Treasury에서 조회하여 `어제 ante_eval_amount`를 참조한다.
> Virtual 모드에서의 `ante_eval_amount` 갱신 정책: [treasury.md — D-TRS-01](../treasury/treasury.md#virtual-모드-자산-평가-동기화-d-trs-01)

#### 퍼블릭 메서드

| 메서드 | 파라미터 | 반환값 | 설명 |
|--------|---------|--------|------|
| `start` | — | `None` | 스케줄러 시작 |
| `stop` | — | `None` | 스케줄러 중지 |
| `run_once` | `target_date: date \| None` | `bool` | 수동 실행 (테스트/CLI용). True=알림 발행, False=거래 0건 스킵 |
