# Treasury 모듈 세부 설계 - 데이터베이스 스키마

> 인덱스: [README.md](README.md) | 호환 문서: [treasury.md](treasury.md)

# 데이터베이스 스키마

테이블 정의: [`bot_budgets`](../../architecture/generated/db-schema.md#bot_budgets), [`treasury_transactions`](../../architecture/generated/db-schema.md#treasury_transactions), [`treasury_fill_dedup`](../../architecture/generated/db-schema.md#treasury_fill_dedup), [`treasury_state`](../../architecture/generated/db-schema.md#treasury_state), [`treasury_reservations`](../../architecture/generated/db-schema.md#treasury_reservations) (코드의 DDL에서 생성된다).

- `bot_budgets`: 봇별 예산 상태
- `bot_budgets.account_id`: 소속 계좌 ID, fallback default 없음
- `treasury_transactions`: 자금 거래 이력 (감사용)
- `treasury_transactions.account_id`: 소속 계좌 ID, fallback default 없음
- `treasury_transactions.transaction_type`: transaction_type vocabulary (5-value, SSOT): 'allocate'             : 봇에 예산 할당 'deallocate'           : 봇에서 예산 회수 'release'              : 봇 삭제 시 할당 예산 전액 환수 'fill'                 : 주문 체결로 인한 자금 이동 'bot_stopped_release'  : 봇 정지 때 회수한 잔여 예약(열린 주문의 예약 제외) 코드 SSOT: src/ante/treasury/treasury.py::TRANSACTION_TYPE_VOCABULARY
- `treasury_fill_dedup`: 체결 이벤트 멱등 dedup (#1957) OrderFilledEvent 의 outbox at-least-once 재전달에 대해 Treasury 정산을 진짜 exactly-once-effect 로 만든다. fill_dedup_key(= #1949 결정적 키)를 PRIMARY KEY 로 두고, _on_order_filled 가 정산 트랜잭션 안에서 INSERT OR IGNORE ... RETURNING 으로 신규 여부를 판정한다(행 반환=신규=정산 1회, 충돌=이미 처리=정산 0회 추가). dedup-insert ⟺ 정산이 1:1 원자 결합된다.
- `treasury_fill_dedup.fill_dedup_key`: order_id:canonical(confirmed_cumulative)
- `treasury_state`: 계좌별 상태 저장
- `treasury_state.account_id`: 계좌별 분리 (기존: key TEXT PK)
- `treasury_reservations`: 미종결 매수 주문의 잔여 예약 (#2770). 주문 하나에 한 행(PK `order_id`)이고 그 주문의 예약이 회수·정산으로 끝나면 지운다. `account_id` fallback 없음

> **`purchasable_amount` 컬럼 의미 (#2384)**: 이 컬럼이 보관하는 매수가능액의 SSOT 출처는 KIS `inquire-psbl-order`의 `nrcvb_buy_amt`(미수 미사용 매수가능금액, 보수값)다. `inquire-balance`의 `psbl_sbst_amt`(대용가능금액)와는 다른 값이며, **컬럼 셋·DDL은 변경되지 않는다**(의미만 재지정). `substitute_amount`(대용가능금액)는 broker-balance dict 전용으로 Treasury가 영속화하지 않으므로 신규 컬럼을 추가하지 않는다. 따라서 `docs/architecture/generated/db-schema.md`는 재생성이 불필요하다(treasury_state 6컬럼 동일: `account_id`/`account_balance`/`purchasable_amount`/`total_evaluation`/`currency`/`last_synced_at`).

> **마이그레이션**: 1.0 이전 fresh schema 기준으로 Treasury DB는 fallback
> account 값을 생성하지 않는다. 기존 invalid dev DB 데이터의 자동 보존/변환은
> 이 계약의 범위가 아니다.

> **`treasury_fill_dedup` 보존 (#1957)**: fill 이벤트당 1행으로 누적되나 PK
> 인덱스만 증가하며 키 충돌이 없어 정합성 위험이 아니다. 개인 홈서버 fill
> 볼륨상 장기 비이슈이므로 retention/prune(terminal 주문 dedup row 정리 또는
> N일 경과 삭제)은 **별도 follow-up 후보**로 분리한다(#1957 bounded scope).

> **참고**: `positions` 테이블은 Trade 모듈이 소유한다. [trade.md](../trade/trade.md) 참조.
