import type { BotBudget } from '../../types/treasury'
import { formatKRW } from '../../utils/formatters'

const COLORS = [
  '#1E8EFF', // positive (blue)
  '#F5C518', // accent (gold)
  '#a78bfa', // info (purple)
  '#E85830', // negative (orange-red)
  '#F0A030', // warning (amber)
  '#34d399', // emerald
  '#f472b6', // pink
  '#60a5fa', // light blue
]

interface Props {
  budgets: BotBudget[]
}

export default function BudgetPieChart({ budgets }: Props) {
  const allocatedBudgets = budgets.filter((b) => b.allocated > 0)

  if (allocatedBudgets.length === 0) {
    return (
      <div className="flex items-center justify-center h-[240px] text-text-muted text-[13px] border border-dashed border-border rounded-lg">
        할당된 예산이 없습니다
      </div>
    )
  }

  const total = allocatedBudgets.reduce((sum, b) => sum + b.allocated, 0)

  // Build pie slices using SVG arc paths
  const slices: { botId: string; percentage: number; color: string; startAngle: number; endAngle: number }[] = []
  let currentAngle = -90 // Start from top

  allocatedBudgets.forEach((b, i) => {
    const percentage = (b.allocated / total) * 100
    const angle = (b.allocated / total) * 360
    slices.push({
      botId: b.bot_id,
      percentage,
      color: COLORS[i % COLORS.length],
      startAngle: currentAngle,
      endAngle: currentAngle + angle,
    })
    currentAngle += angle
  })

  return (
    <div className="flex items-center gap-6 h-[240px]">
      {/* SVG Pie Chart */}
      <div className="flex-shrink-0">
        <svg width="180" height="180" viewBox="-1 -1 2 2" style={{ transform: 'rotate(-90deg)' }}>
          {slices.map((slice) => {
            if (slice.percentage >= 99.99) {
              // Full circle
              return (
                <circle key={slice.botId} r="1" fill={slice.color} />
              )
            }

            const startRad = ((slice.startAngle + 90) * Math.PI) / 180
            const endRad = ((slice.endAngle + 90) * Math.PI) / 180

            const x1 = Math.cos(startRad)
            const y1 = Math.sin(startRad)
            const x2 = Math.cos(endRad)
            const y2 = Math.sin(endRad)

            const largeArc = slice.endAngle - slice.startAngle > 180 ? 1 : 0

            const d = [
              `M 0 0`,
              `L ${x1} ${y1}`,
              `A 1 1 0 ${largeArc} 1 ${x2} ${y2}`,
              `Z`,
            ].join(' ')

            return <path key={slice.botId} d={d} fill={slice.color} />
          })}
        </svg>
      </div>

      {/* Legend */}
      <div className="flex flex-col gap-2 overflow-y-auto max-h-[220px] min-w-0">
        {slices.map((slice) => {
          const budget = allocatedBudgets.find((b) => b.bot_id === slice.botId)!
          return (
            <div key={slice.botId} className="flex items-center gap-2 text-[13px]">
              <span
                className="w-3 h-3 rounded-sm flex-shrink-0"
                style={{ backgroundColor: slice.color }}
              />
              <span className="text-text truncate">{slice.botId}</span>
              <span className="text-text-muted ml-auto flex-shrink-0">
                {slice.percentage.toFixed(1)}%
              </span>
              <span className="text-text-muted flex-shrink-0">
                ({formatKRW(budget.allocated)})
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}
