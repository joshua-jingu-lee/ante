import { Link } from 'react-router-dom'
import { useTreasurySummary, useBotBudgets } from '../hooks/useTreasury'
import AccountSummary from '../components/treasury/AccountSummary'
import BudgetTable from '../components/treasury/BudgetTable'
import AllocationForm from '../components/treasury/AllocationForm'
import LoadingSpinner from '../components/common/LoadingSpinner'

export default function Treasury() {
  const { data: summary, isLoading: summaryLoading } = useTreasurySummary()
  const { data: budgets, isLoading: budgetsLoading } = useBotBudgets()

  if (summaryLoading || budgetsLoading) return <LoadingSpinner />

  const botIds = (budgets ?? []).map((b) => b.bot_id)

  return (
    <>
      {summary && <AccountSummary summary={summary} />}
      <BudgetTable budgets={budgets ?? []} />
      {botIds.length > 0 && <AllocationForm botIds={botIds} />}
      <div className="mt-4">
        <Link
          to="/treasury/history"
          className="text-[13px] text-primary no-underline hover:underline"
        >
          거래 이력 보기 →
        </Link>
      </div>
    </>
  )
}
