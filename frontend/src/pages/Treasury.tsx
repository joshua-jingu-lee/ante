import { useTreasurySummary, useBotBudgets } from '../hooks/useTreasury'
import AccountSummary from '../components/treasury/AccountSummary'
import AnteSummary from '../components/treasury/AnteSummary'
import BudgetTable from '../components/treasury/BudgetTable'
import AllocationForm from '../components/treasury/AllocationForm'
import RecentTransactions from '../components/treasury/RecentTransactions'
import { PageSkeleton } from '../components/common/Skeleton'

export default function Treasury() {
  const { data: summary, isLoading: summaryLoading } = useTreasurySummary()
  const { data: budgets, isLoading: budgetsLoading } = useBotBudgets()

  if (summaryLoading || budgetsLoading) return <PageSkeleton />

  return (
    <>
      {summary && <AccountSummary summary={summary} />}
      {summary && <AnteSummary summary={summary} />}

      <div className="grid grid-cols-[1fr_1fr] gap-6 mb-6">
        {/* 파이 차트 자리 */}
        <div className="bg-surface border border-border rounded-lg p-5">
          <h3 className="text-[15px] font-semibold mb-4">Bot 예산 비중</h3>
          <div className="flex items-center justify-center h-[240px] text-text-muted text-[13px] border border-dashed border-border rounded-lg">
            📊 파이 차트 — Bot별 예산 비중
          </div>
        </div>

        {/* 예산 관리 폼 */}
        {(budgets ?? []).length > 0 && <AllocationForm budgets={budgets ?? []} />}
      </div>

      <BudgetTable budgets={budgets ?? []} />
      <RecentTransactions />
    </>
  )
}
