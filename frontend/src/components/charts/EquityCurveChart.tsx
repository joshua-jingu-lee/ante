import { useCallback } from 'react'
import { AreaSeries, type IChartApi } from 'lightweight-charts'
import LightweightChart from './LightweightChart'

export interface EquityDataPoint {
  date: string
  value: number
}

interface EquityCurveChartProps {
  data: EquityDataPoint[]
  className?: string
}

export default function EquityCurveChart({ data, className }: EquityCurveChartProps) {
  const handleChartReady = useCallback(
    (chart: IChartApi) => {
      const areaSeries = chart.addSeries(AreaSeries, {
        lineColor: '#1E8EFF',
        topColor: 'rgba(30, 142, 255, 0.28)',
        bottomColor: 'rgba(30, 142, 255, 0.02)',
        lineWidth: 2,
        priceFormat: {
          type: 'custom',
          formatter: (price: number) => {
            if (price >= 100_000_000) return `${(price / 100_000_000).toFixed(1)}억`
            if (price >= 10_000) return `${(price / 10_000).toFixed(0)}만`
            return price.toLocaleString()
          },
        },
      })

      const seriesData = data.map((d) => ({
        time: d.date,
        value: d.value,
      }))

      areaSeries.setData(seriesData as Parameters<typeof areaSeries.setData>[0])
      chart.timeScale().fitContent()
    },
    [data],
  )

  if (data.length === 0) {
    return (
      <div className={`flex items-center justify-center text-[13px] text-text-muted ${className ?? 'h-[240px]'}`}>
        아직 자산 추이 데이터가 없습니다
      </div>
    )
  }

  return <LightweightChart key={data.length} onChartReady={handleChartReady} className={className ?? 'h-[240px]'} />
}
