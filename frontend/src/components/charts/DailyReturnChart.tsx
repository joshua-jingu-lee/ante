import { useCallback } from 'react'
import { HistogramSeries, type IChartApi } from 'lightweight-charts'
import LightweightChart from './LightweightChart'
import type { EquityDataPoint } from './EquityCurveChart'

interface DailyReturnChartProps {
  data: EquityDataPoint[]
  className?: string
}

interface DailyReturnPoint {
  time: string
  value: number
  color: string
}

const POSITIVE_COLOR = 'rgba(30, 142, 255, 0.85)' // --color-positive
const NEGATIVE_COLOR = 'rgba(232, 88, 48, 0.85)' // --color-negative

function computeDailyReturns(data: EquityDataPoint[]): DailyReturnPoint[] {
  if (data.length < 2) return []

  const returns: DailyReturnPoint[] = []
  for (let i = 1; i < data.length; i++) {
    const prev = data[i - 1].value
    if (prev === 0) continue
    const pct = ((data[i].value - prev) / prev) * 100
    returns.push({
      time: data[i].date,
      value: pct,
      color: pct >= 0 ? POSITIVE_COLOR : NEGATIVE_COLOR,
    })
  }
  return returns
}

export default function DailyReturnChart({ data, className }: DailyReturnChartProps) {
  const handleChartReady = useCallback(
    (chart: IChartApi) => {
      const histogramSeries = chart.addSeries(HistogramSeries, {
        priceFormat: {
          type: 'custom',
          formatter: (price: number) => `${price.toFixed(2)}%`,
        },
      })

      const returns = computeDailyReturns(data)
      histogramSeries.setData(returns as Parameters<typeof histogramSeries.setData>[0])
      chart.timeScale().fitContent()
    },
    [data],
  )

  const returns = computeDailyReturns(data)
  if (returns.length === 0) {
    return (
      <div className={`flex items-center justify-center text-[13px] text-text-muted ${className ?? 'h-[180px]'}`}>
        일별 수익률 데이터가 부족합니다
      </div>
    )
  }

  return <LightweightChart key={data.length} onChartReady={handleChartReady} className={className ?? 'h-[180px]'} />
}
