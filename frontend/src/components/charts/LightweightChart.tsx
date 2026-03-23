import { useRef, useEffect } from 'react'
import { createChart, type IChartApi, type DeepPartial, type ChartOptions } from 'lightweight-charts'

interface LightweightChartProps {
  options?: DeepPartial<ChartOptions>
  onChartReady: (chart: IChartApi) => void
  className?: string
}

export default function LightweightChart({ options, onChartReady, className }: LightweightChartProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)

  useEffect(() => {
    const container = containerRef.current
    if (!container) return

    const chart = createChart(container, {
      width: container.clientWidth,
      height: container.clientHeight || 240,
      layout: {
        background: { color: 'transparent' },
        textColor: '#8b8fa3',
        fontSize: 11,
      },
      grid: {
        vertLines: { color: 'rgba(42, 42, 53, 0.5)' },
        horzLines: { color: 'rgba(42, 42, 53, 0.5)' },
      },
      crosshair: {
        vertLine: { color: 'rgba(139, 143, 163, 0.3)' },
        horzLine: { color: 'rgba(139, 143, 163, 0.3)' },
      },
      timeScale: {
        borderColor: '#2a2a35',
        timeVisible: false,
      },
      ...options,
    })

    chartRef.current = chart

    const resizeObserver = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const { width, height } = entry.contentRect
        chart.applyOptions({ width, height })
      }
    })
    resizeObserver.observe(container)

    onChartReady(chart)

    return () => {
      resizeObserver.disconnect()
      chart.remove()
      chartRef.current = null
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  return <div ref={containerRef} className={className} />
}
