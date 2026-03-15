import HintTooltip from '../common/HintTooltip'
import { formatPercent, formatNumber } from '../../utils/formatters'
import type { BacktestMetrics as Metrics } from '../../types/approval'

const METRIC_DEFS: { key: keyof Metrics; label: string; hint: string; format: (v: number) => string }[] = [
  { key: 'sharpe_ratio', label: '샤프 비율', hint: '위험 대비 수익 효율. 높을수록 안정적인 수익', format: (v) => v.toFixed(2) },
  { key: 'max_drawdown', label: '최대 낙폭 (MDD)', hint: '고점 대비 최대 하락 폭', format: (v) => formatPercent(v) },
  { key: 'win_rate', label: '승률', hint: '수익 거래 비율', format: (v) => formatPercent(v) },
  { key: 'profit_factor', label: '수익 팩터', hint: '총 이익 / 총 손실. 1 이상이면 수익', format: (v) => v.toFixed(2) },
  { key: 'total_trades', label: '총 거래 수', hint: '백테스트 기간 중 총 거래 횟수', format: (v) => formatNumber(v) },
  { key: 'total_return', label: '총 수익률', hint: '백테스트 기간 총 수익률', format: (v) => formatPercent(v) },
]

export default function BacktestMetricsPanel({ metrics }: { metrics: Metrics }) {
  return (
    <div className="bg-surface border border-border rounded-lg p-5 mb-6">
      <h3 className="text-[15px] font-semibold mb-4">성과 지표</h3>
      <div className="grid grid-cols-3 gap-4">
        {METRIC_DEFS.map((def) => (
          <div key={def.key} className="bg-bg rounded-lg p-4">
            <div className="text-[12px] text-text-muted mb-1">
              {def.label}
              <HintTooltip text={def.hint} />
            </div>
            <div className="text-[20px] font-bold">{def.format(metrics[def.key])}</div>
          </div>
        ))}
      </div>
    </div>
  )
}
