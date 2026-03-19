/**
 * Treasury 도메인 타입.
 *
 * [마이그레이션 가이드]
 * API 응답 타입은 api.generated.ts에서 자동 생성된다.
 * 현재 TreasurySummary는 백엔드가 extra="allow"로 동적 필드를 반환하므로
 * OpenAPI 스키마에 모든 필드가 선언되어 있지 않다.
 * 백엔드 스키마가 정비되면 아래 수동 타입을 generated 타입으로 교체한다.
 *
 * 교체 가능한 타입: TransactionItem, TransactionListResponse,
 *   BudgetOperationResponse, BalanceSetResponse
 * 교체 대기: TreasurySummary (백엔드 extra 필드 정비 후)
 */
import type {
  TransactionItem as GeneratedTransactionItem,
  BudgetOperationResponse,
  BalanceSetResponse,
} from './api.generated'

// ── generated 타입 re-export (완전 대응) ──────────────────
export type { BudgetOperationResponse, BalanceSetResponse }

// TransactionItem: generated 타입과 기존 타입이 호환됨
export type TreasuryTransaction = GeneratedTransactionItem

// ── 수동 타입 (백엔드 extra 필드 포함 — 추후 마이그레이션 대상) ──
export interface TreasurySummary {
  // KIS 계좌
  account_balance: number
  purchasable_amount: number
  total_evaluation: number
  total_profit_loss: number
  commission_rate: number
  sell_tax_rate: number
  // 브로커 메타정보
  broker_id: string
  broker_name: string
  broker_short_name: string
  exchange: string
  // KIS 계좌 헤더
  account_number: string
  is_demo_trading: boolean
  last_sync_time: string | null
  // Ante 관리자산
  total_allocated: number
  total_reserved: number
  total_available: number
  unallocated: number
  bot_count: number
  ante_purchase_amount: number
  ante_eval_amount: number
  ante_profit_loss: number
  budget_exceeds_purchasable: boolean
}

export interface BotBudget {
  bot_id: string
  allocated: number
  available: number
  reserved: number
  spent: number
  returned: number
  eval_amount: number
  position_pnl: number
  position_return: number
}

export type TransactionType = 'allocate' | 'deallocate' | 'fill' | 'bot_stopped_release'
