import HintTooltip from '../common/HintTooltip'
import { formatPercent, formatNumber, formatKRW } from '../../utils/formatters'
import type { StrategyPerformance } from '../../types/strategy'

export default function PerformancePanel({ perf }: { perf: StrategyPerformance | null | undefined }) {
  const isEmpty = !perf || perf.total_trades === 0

  if (isEmpty) {
    return (
      <div className="bg-surface border border-border rounded-lg p-5 mb-6">
        <h3 className="text-[15px] font-semibold mb-4">성과 지표</h3>
        <div className="py-8 text-center text-text-muted text-[13px]">
          아직 성과 데이터가 없습니다
        </div>
      </div>
    )
  }

  const metrics = [
    { label: '총 거래 수', value: formatNumber(perf.total_trades), hint: '전체 거래 횟수' },
    { label: '승률', value: formatPercent(perf.win_rate), hint: '수익 거래 비율' },
    { label: '수익 팩터', value: perf.profit_factor.toFixed(2), hint: '총 이익 / 총 손실' },
    { label: '최대 낙폭', value: formatPercent(perf.max_drawdown), hint: '고점 대비 최대 하락 폭' },
    { label: '실현 손익', value: formatKRW(perf.realized_pnl), hint: '확정된 거래 손익 합계' },
    { label: '샤프 비율', value: perf.sharpe_ratio.toFixed(2), hint: '위험 대비 수익 효율' },
  ]

  return (
    <div className="bg-surface border border-border rounded-lg p-5 mb-6">
      <h3 className="text-[15px] font-semibold mb-4">성과 지표</h3>
      <div className="grid grid-cols-3 gap-4">
        {metrics.map((m) => (
          <div key={m.label} className="bg-bg rounded-lg p-4">
            <div className="text-[12px] text-text-muted mb-1">
              {m.label}
              <HintTooltip text={m.hint} />
            </div>
            <div className="text-[20px] font-bold">{m.value}</div>
          </div>
        ))}
      </div>
    </div>
  )
}
