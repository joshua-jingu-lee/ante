/**
 * Treasury 도메인 타입.
 *
 * `api.generated.ts`의 Treasury raw contract를
 * `frontend/src/api/treasury.ts` adapter가 UI/domain model로 변환한다.
 */

// ── 프론트엔드 전용 타입 ──────────────────────────────────

export interface TreasurySummaryView {
  total_allocated: number
  total_balance: number
  total_evaluation: number
  total_profit_loss: number
  unallocated: number
  commission_rate: number
  sell_tax_rate: number
  broker_id?: string
  broker_name?: string
  broker_short_name?: string
  exchange?: string
  account_no?: string
  is_virtual?: boolean
  synced_at?: string
  account_balance?: number
  purchasable_amount?: number
  account_number?: string
  /** KIS 모의/실전투자 엔드포인트 메타데이터. Account.trading_mode와 별개다. */
  is_demo_trading?: boolean
  last_sync_time?: string | null
  total_reserved?: number
  total_available?: number
  bot_count?: number
  ante_purchase_amount?: number
  ante_eval_amount?: number
  ante_profit_loss?: number
  budget_exceeds_purchasable?: boolean
}

export type TreasurySummary = TreasurySummaryView

/** 봇별 예산 상세 -- 백엔드가 dict 기반 응답을 반환하므로 프론트엔드에서 명시 */
export interface BotBudgetView {
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

export type BotBudget = BotBudgetView

export type TransactionType = 'allocate' | 'deallocate' | 'fill' | 'bot_stopped_release'

export interface TreasuryTransactionView {
  id: number
  type: string
  bot_id?: string | null
  amount: number
  description: string
  created_at: string
}

export type TreasuryTransaction = TreasuryTransactionView

/** 일별 자산 스냅샷 -- 백엔드 SnapshotItem 대응 */
export interface TreasurySnapshotView {
  account_id: string
  snapshot_date: string
  total_asset: number
  ante_eval_amount: number
  ante_purchase_amount: number
  unallocated: number
  account_balance: number
  total_allocated: number
  bot_count: number
  daily_pnl: number
  daily_return: number
  net_trade_amount: number
  unrealized_pnl: number
  created_at: string
}

export type TreasurySnapshot = TreasurySnapshotView
