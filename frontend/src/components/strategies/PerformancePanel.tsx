import HintTooltip from '../common/HintTooltip'
import { formatPercent, formatNumber, formatKRW } from '../../utils/formatters'
import type { StrategyPerformance } from '../../types/strategy'

interface StatItem {
  label: string
  value: string
  hint: string
  color?: string
  sub?: string
  subColor?: string
}

export default function PerformancePanel({ perf }: { perf: StrategyPerformance | null | undefined }) {
  const isEmpty = !perf || perf.total_trades === 0

  if (isEmpty) {
    return (
      <div className="mb-6">
        <div className="bg-surface border border-border rounded-lg p-5">
          <div className="py-8 text-center text-text-muted text-[13px]">
            아직 성과 데이터가 없습니다
          </div>
        </div>
      </div>
    )
  }

  const row1: StatItem[] = [
    {
      label: '순손익',
      value: formatKRW(perf.net_pnl),
      hint: '실현 손익 + 미실현 손익의 합계',
      color: perf.net_pnl >= 0 ? 'text-positive' : 'text-negative',
      sub: perf.net_pnl !== 0 ? `(${perf.net_pnl >= 0 ? '+' : ''}${formatPercent(perf.win_rate).replace(/^[+-]/, perf.net_pnl >= 0 ? '+' : '-')})` : undefined,
      subColor: perf.net_pnl >= 0 ? 'text-positive' : 'text-negative',
    },
    { label: '총 거래 수', value: formatNumber(perf.total_trades), hint: '전체 거래 횟수' },
    { label: '승률', value: formatPercent(perf.win_rate), hint: '수익을 낸 거래 수 / 전체 거래 수' },
    { label: '활성 거래일', value: `${perf.active_days}일`, hint: '실제 매매가 발생한 날의 수' },
  ]

  const row2: StatItem[] = [
    { label: '수익 팩터', value: perf.profit_factor == null ? '-' : perf.profit_factor === Infinity ? '∞' : perf.profit_factor.toFixed(2), hint: '총 수익 / 총 손실. 1 이상이면 수익 우위' },
    { label: 'Sharpe Ratio', value: perf.sharpe_ratio != null ? perf.sharpe_ratio.toFixed(2) : '-', hint: '위험 대비 수익 효율. 높을수록 안정적인 수익' },
    {
      label: 'MDD',
      value: formatPercent(perf.max_drawdown),
      hint: '최대 낙폭. 고점 대비 가장 크게 떨어진 비율',
      color: 'text-negative',
      sub: perf.max_drawdown_amount ? `(${formatKRW(-Math.abs(perf.max_drawdown_amount))})` : undefined,
      subColor: 'text-negative',
    },
    { label: '수수료 합계', value: formatKRW(perf.total_commission), hint: '총 거래 수수료', color: 'text-text-muted' },
  ]

  const row3: StatItem[] = [
    { label: '평균 수익', value: formatKRW(perf.avg_profit), hint: '수익 거래의 평균 이익 금액', color: 'text-positive' },
    { label: '평균 손실', value: formatKRW(perf.avg_loss), hint: '손실 거래의 평균 손실 금액', color: 'text-negative' },
    { label: '실현 손익', value: formatKRW(perf.realized_pnl), hint: '매도 완료된 거래의 확정 손익', color: perf.realized_pnl >= 0 ? 'text-positive' : 'text-negative' },
    { label: '미실현 손익', value: '-', hint: '보유 중인 종목의 평가 손익 (미확정)' },
  ]

  return (
    <div className="mb-6">
      <StatsRow items={row1} />
      <StatsRow items={row2} />
      <StatsRow items={row3} last />
    </div>
  )
}

function StatsRow({ items, last }: { items: StatItem[]; last?: boolean }) {
  return (
    <div className={`grid grid-cols-4 gap-4 ${last ? '' : 'mb-4'}`}>
      {items.map((m) => (
        <div key={m.label} className="bg-surface border border-border rounded-lg p-4">
          <div className="text-[12px] text-text-muted mb-1">
            {m.label}
            <HintTooltip text={m.hint} />
          </div>
          <div className={`text-[20px] font-bold ${m.color ?? ''}`}>{m.value}</div>
          {m.sub && (
            <div className={`text-[13px] mt-[-4px] ${m.subColor ?? 'text-text-muted'}`}>{m.sub}</div>
          )}
        </div>
      ))}
    </div>
  )
}
