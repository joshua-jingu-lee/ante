/**
 * Treasury 도메인 타입.
 *
 * API 응답 타입은 api.generated.ts에서 자동 생성된 타입을 사용한다.
 * generated TreasurySummaryResponse에 index signature가 있어
 * 동적 필드가 unknown이 되므로 프론트엔드에서 확장 정의한다.
 */
import type {
  TransactionItem,
  BudgetOperationResponse,
  BalanceSetResponse,
  TreasurySummaryResponse,
} from './api.generated'

// ── API 응답 타입 re-export (generated 완전 대응) ────────
export type { BudgetOperationResponse, BalanceSetResponse }
export type TreasuryTransaction = TransactionItem

// ── 프론트엔드 전용 타입 ──────────────────────────────────

/**
 * 자금관리 요약.
 * generated TreasurySummaryResponse를 기반으로, 백엔드가 extra="allow"로
 * 동적 반환하는 필드를 명시적으로 추가 정의한다.
 */
export interface TreasurySummary extends TreasurySummaryResponse {
  // KIS 계좌 추가 필드
  account_balance?: number
  purchasable_amount?: number
  account_number?: string
  is_demo_trading?: boolean
  last_sync_time?: string | null
  // Ante 관리자산 추가 필드
  total_reserved?: number
  total_available?: number
  bot_count?: number
  ante_purchase_amount?: number
  ante_eval_amount?: number
  ante_profit_loss?: number
  budget_exceeds_purchasable?: boolean
}

/** 봇별 예산 상세 -- 백엔드가 dict 기반 응답을 반환하므로 프론트엔드에서 명시 */
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
