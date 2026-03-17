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
    { label: '순손익', value: formatKRW(perf.net_pnl), hint: '총 손익 - 수수료', color: perf.net_pnl >= 0 ? 'text-positive' : 'text-negative' },
    { label: '총 거래 수', value: formatNumber(perf.total_trades), hint: '전체 거래 횟수' },
    { label: '승률', value: formatPercent(perf.win_rate), hint: '수익 거래 비율' },
    { label: '활성 거래일', value: `${perf.active_days}일`, hint: '실제 거래가 발생한 날 수' },
    { label: '수익 팩터', value: perf.profit_factor == null ? '-' : perf.profit_factor === Infinity ? '∞' : perf.profit_factor.toFixed(2), hint: '총 이익 / 총 손실' },
    { label: '샤프 비율', value: perf.sharpe_ratio != null ? perf.sharpe_ratio.toFixed(2) : '-', hint: '위험 대비 수익 효율' },
    { label: 'MDD', value: formatPercent(perf.max_drawdown), hint: '고점 대비 최대 하락 폭' },
    { label: '수수료 합계', value: formatKRW(perf.total_commission), hint: '총 거래 수수료' },
    { label: '평균 수익', value: formatKRW(perf.avg_profit), hint: '수익 거래의 평균 이익' },
    { label: '평균 손실', value: formatKRW(perf.avg_loss), hint: '손실 거래의 평균 손실', color: perf.avg_loss > 0 ? 'text-negative' : undefined },
    { label: '실현 손익', value: formatKRW(perf.total_pnl), hint: '수수료 차감 전 확정 손익', color: perf.total_pnl >= 0 ? 'text-positive' : 'text-negative' },
    { label: '미실현 손익', value: '-', hint: '현재 보유 포지션 기준 (추후 지원)' },
  ]

  return (
    <div className="bg-surface border border-border rounded-lg p-5 mb-6">
      <h3 className="text-[15px] font-semibold mb-4">성과 지표</h3>
      <div className="grid grid-cols-4 gap-4">
        {metrics.map((m) => (
          <div key={m.label} className="bg-bg rounded-lg p-4">
            <div className="text-[12px] text-text-muted mb-1">
              {m.label}
              <HintTooltip text={m.hint} />
            </div>
            <div className={`text-[20px] font-bold ${m.color ?? ''}`}>{m.value}</div>
          </div>
        ))}
      </div>
    </div>
  )
}
