import { useCallback } from 'react'
import { AreaSeries, HistogramSeries, type IChartApi } from 'lightweight-charts'
import LightweightChart from './LightweightChart'

export interface SnapshotDataPoint {
  snapshot_date: string
  total_asset: number
  daily_return: number
}

interface AssetTrendChartProps {
  data: SnapshotDataPoint[]
}

export default function AssetTrendChart({ data }: AssetTrendChartProps) {
  const handleChartReady = useCallback(
    (chart: IChartApi) => {
      // Area series (left axis) - total asset
      const areaSeries = chart.addSeries(AreaSeries, {
        lineColor: '#1E8EFF',
        topColor: 'rgba(30, 142, 255, 0.28)',
        bottomColor: 'rgba(30, 142, 255, 0.02)',
        lineWidth: 2,
        priceScaleId: 'left',
        priceFormat: {
          type: 'custom',
          formatter: (price: number) => {
            if (price >= 100_000_000) return `${(price / 100_000_000).toFixed(1)}억`
            if (price >= 10_000) return `${(price / 10_000).toFixed(0)}만`
            return price.toLocaleString()
          },
        },
      })

      // Histogram series (right axis) - daily return %
      const histogramSeries = chart.addSeries(HistogramSeries, {
        priceScaleId: 'right',
        priceFormat: {
          type: 'custom',
          formatter: (price: number) => `${price.toFixed(2)}%`,
        },
      })

      // Configure scales
      chart.priceScale('left').applyOptions({
        borderColor: '#2a2a35',
        scaleMargins: { top: 0.1, bottom: 0.25 },
      })
      chart.priceScale('right').applyOptions({
        borderColor: '#2a2a35',
        scaleMargins: { top: 0.7, bottom: 0.05 },
      })

      // Set data
      const areaData = data.map((d) => ({
        time: d.snapshot_date,
        value: d.total_asset,
      }))

      const histogramData = data.map((d) => {
        const pct = d.daily_return * 100
        return {
          time: d.snapshot_date,
          value: pct,
          color: pct >= 0 ? 'rgba(30, 142, 255, 0.6)' : 'rgba(232, 88, 48, 0.6)',
        }
      })

      areaSeries.setData(areaData as Parameters<typeof areaSeries.setData>[0])
      histogramSeries.setData(histogramData as Parameters<typeof histogramSeries.setData>[0])

      chart.timeScale().fitContent()
    },
    [data],
  )

  if (data.length === 0) {
    return (
      <div className="h-[240px] flex items-center justify-center text-[13px] text-text-muted">
        스냅샷 데이터가 없습니다.
      </div>
    )
  }

  return <LightweightChart key={data.length} onChartReady={handleChartReady} className="h-[240px]" />
}
