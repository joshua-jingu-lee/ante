import { useState, useMemo } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getDatasets, getStorageInfo, deleteDataset } from '../api/data'
import type { DataType } from '../api/data'
import { formatNumber, formatDate } from '../utils/formatters'
import { TableSkeleton } from '../components/common/Skeleton'

const LIMIT = 15
const TF_OPTIONS = ['all', '1d', '1h', '1m'] as const
const TF_LABELS: Record<string, string> = { '1d': '1일', '1h': '1시간', '1m': '1분' }

const DATA_TYPE_OPTIONS: { value: DataType; label: string }[] = [
  { value: 'ohlcv', label: 'OHLCV (시세)' },
  { value: 'fundamental', label: 'Fundamental (재무)' },
]

export default function BacktestData() {
  const [search, setSearch] = useState('')
  const [dataType, setDataType] = useState<DataType>('ohlcv')
  const [timeframe, setTimeframe] = useState<string>('all')
  const [offset, setOffset] = useState(0)
  const [deleteTarget, setDeleteTarget] = useState<{ id: number; symbol: string; timeframe: string; data_type: DataType; start_date: string; end_date: string; row_count: number } | null>(null)
  const queryClient = useQueryClient()

  /* 자동완성용: 전체 데이터셋에서 고유 종목 목록 추출 */
  const { data: allDatasets } = useQuery({
    queryKey: ['datasets-all-symbols', dataType],
    queryFn: () => getDatasets({ data_type: dataType, limit: 1000 }),
  })

  const symbolOptions = useMemo(() => {
    if (!allDatasets?.items) return []
    return [...new Set(allDatasets.items.map((ds) => ds.symbol))]
  }, [allDatasets])

  const { data, isLoading } = useQuery({
    queryKey: ['datasets', search, dataType, timeframe, offset],
    queryFn: () =>
      getDatasets({
        symbol: search || undefined,
        data_type: dataType,
        timeframe: dataType === 'ohlcv' && timeframe !== 'all' ? timeframe : undefined,
        offset,
        limit: LIMIT,
      }),
  })

  const { data: storage } = useQuery({
    queryKey: ['storage'],
    queryFn: getStorageInfo,
  })

  const deleteMutation = useMutation({
    mutationFn: (target: { id: number; data_type: DataType }) => deleteDataset(target.id, target.data_type),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['datasets'] })
      queryClient.invalidateQueries({ queryKey: ['datasets-all-symbols'] })
      queryClient.invalidateQueries({ queryKey: ['storage'] })
      setDeleteTarget(null)
    },
  })

  const isFundamental = dataType === 'fundamental'

  return (
    <>
      {/* 안내 배너 */}
      <div className="bg-info-bg rounded px-3.5 py-2.5 mb-4 text-[12px] text-info">
        {'\u{1f4a1}'} 데이터 수집은 Agent에게 요청하거나 CLI(<code className="bg-[rgba(255,255,255,0.08)] px-1.5 py-0.5 rounded-sm text-[12px]">ante data collect</code>)를 사용하세요.
      </div>

      {/* 데이터셋 카드 */}
      <div className="bg-surface border border-border rounded-lg p-5">
        {/* 카드 헤더: 타이틀 + 필터를 한 줄 배치 */}
        <div className="flex items-center justify-between mb-4">
          <span className="text-[15px] font-semibold text-text">데이터셋</span>
          <div className="flex items-center gap-2">
            <input
              type="text"
              value={search}
              onChange={(e) => { setSearch(e.target.value); setOffset(0) }}
              list="symbol-list"
              placeholder="종목 검색"
              className="bg-bg border border-border rounded px-2 py-1 text-text text-[13px] w-40 placeholder:text-text-muted focus:outline-none focus:border-primary"
            />
            <datalist id="symbol-list">
              {symbolOptions.map((sym) => (
                <option key={sym} value={sym} />
              ))}
            </datalist>
            <select
              value={dataType}
              onChange={(e) => { setDataType(e.target.value as DataType); setTimeframe('all'); setOffset(0) }}
              className="bg-bg border border-border rounded px-2 py-1 text-text text-[13px] cursor-pointer focus:outline-none focus:border-primary"
            >
              {DATA_TYPE_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>{opt.label}</option>
              ))}
            </select>
            {!isFundamental && (
              <select
                value={timeframe}
                onChange={(e) => { setTimeframe(e.target.value); setOffset(0) }}
                className="bg-bg border border-border rounded px-2 py-1 text-text text-[13px] cursor-pointer focus:outline-none focus:border-primary"
              >
                <option value="all">전체 타임프레임</option>
                {TF_OPTIONS.filter((tf) => tf !== 'all').map((tf) => (
                  <option key={tf} value={tf}>{TF_LABELS[tf] ?? tf}</option>
                ))}
              </select>
            )}
          </div>
        </div>
        {isLoading ? (
          <TableSkeleton rows={5} cols={isFundamental ? 5 : 6} />
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full border-collapse">
                <thead>
                  <tr>
                    <th className="text-left px-3 py-2.5 text-[12px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">종목</th>
                    {!isFundamental && (
                      <th className="text-left px-3 py-2.5 text-[12px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">타임프레임</th>
                    )}
                    <th className="text-left px-3 py-2.5 text-[12px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">시작일</th>
                    <th className="text-left px-3 py-2.5 text-[12px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">종료일</th>
                    <th className="text-right px-3 py-2.5 text-[12px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">행 수</th>
                    <th className="text-right px-3 py-2.5 text-[12px] font-semibold text-text-muted uppercase tracking-wider border-b border-border"></th>
                  </tr>
                </thead>
                <tbody>
                  {(data?.items ?? []).length === 0 ? (
                    <tr><td colSpan={isFundamental ? 5 : 6} className="px-3 py-8 text-center text-text-muted text-[13px]">데이터셋이 없습니다</td></tr>
                  ) : (
                    (data?.items ?? []).map((ds, idx, arr) => {
                      const isLast = idx === arr.length - 1
                      const borderCls = isLast ? '' : 'border-b border-border'
                      return (
                      <tr key={ds.id} className="hover:bg-surface-hover">
                        <td className={`px-3 py-3 ${borderCls} text-[13px] font-mono font-medium`}>{ds.symbol}</td>
                        {!isFundamental && (
                          <td className={`px-3 py-3 ${borderCls} text-[13px]`}>{TF_LABELS[ds.timeframe] ?? ds.timeframe}</td>
                        )}
                        <td className={`px-3 py-3 ${borderCls} text-[13px] text-text-muted`}>{formatDate(ds.start_date)}</td>
                        <td className={`px-3 py-3 ${borderCls} text-[13px] text-text-muted`}>{formatDate(ds.end_date)}</td>
                        <td className={`px-3 py-3 ${borderCls} text-[13px] text-right`}>{formatNumber(ds.row_count)}</td>
                        <td className={`px-3 py-3 ${borderCls} text-[13px] text-right`}>
                          <button
                            onClick={() => setDeleteTarget({ id: ds.id, symbol: ds.symbol, timeframe: ds.timeframe, data_type: ds.data_type, start_date: ds.start_date, end_date: ds.end_date, row_count: ds.row_count })}
                            className="px-2.5 py-1 rounded text-[12px] bg-transparent text-negative border border-border cursor-pointer hover:bg-surface-hover hover:text-text"
                          >
                            삭제
                          </button>
                        </td>
                      </tr>
                      )
                    })
                  )}
                </tbody>
              </table>
            </div>

            <div className="flex items-center justify-between pt-3 text-[13px] text-text-muted">
              <span>
                총 {formatNumber(data?.total ?? 0)}건
                {(data?.total ?? 0) > 0 && ` 중 ${offset + 1}-${Math.min(offset + LIMIT, data?.total ?? 0)}`}
                {storage && ` · 전체 ${storage.total_mb >= 1024 ? `${(storage.total_mb / 1024).toFixed(1)} GB` : `${storage.total_mb.toFixed(1)} MB`}`}
                {storage?.by_timeframe && Object.keys(storage.by_timeframe).length > 0 && (
                  <> ({Object.entries(storage.by_timeframe).map(([tf, bytes], i) => (
                    <span key={tf}>{i > 0 && ' · '}{TF_LABELS[tf] ?? tf} {(bytes / 1024 / 1024).toFixed(0)} MB</span>
                  ))})</>
                )}
              </span>
              <div className="flex items-center gap-1">
                <button
                  onClick={() => setOffset(Math.max(0, offset - LIMIT))}
                  disabled={offset <= 0}
                  className="px-2.5 py-1 rounded text-[12px] font-medium border border-border bg-transparent text-text-muted hover:bg-surface-hover hover:text-text disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  &larr; 이전
                </button>
                <button
                  onClick={() => setOffset(offset + LIMIT)}
                  disabled={offset + LIMIT >= (data?.total ?? 0)}
                  className="px-2.5 py-1 rounded text-[12px] font-medium border border-border bg-transparent text-text-muted hover:bg-surface-hover hover:text-text disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  다음 &rarr;
                </button>
              </div>
            </div>
          </>
        )}
      </div>

      {/* 삭제 확인 모달 */}
      {deleteTarget && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-[200]">
          <div className="bg-surface border border-border rounded-lg p-6 w-[480px]">
            <h3 className="text-[18px] font-bold mb-5 text-negative">데이터셋 삭제</h3>
            <div className="mb-4 text-[13px] text-text-muted">
              <strong className="text-text">
                {deleteTarget.symbol}
                {deleteTarget.data_type === 'fundamental' ? ' — Fundamental' : ` — ${TF_LABELS[deleteTarget.timeframe] ?? deleteTarget.timeframe}`}
              </strong><br />
              기간: {formatDate(deleteTarget.start_date)} ~ {formatDate(deleteTarget.end_date)} · {formatNumber(deleteTarget.row_count)}건<br /><br />
              삭제된 데이터는 복구할 수 없습니다.
            </div>
            <div className="bg-warning-bg text-warning px-3.5 py-2.5 rounded text-[12px] mb-4">
              이 데이터를 사용 중인 백테스트가 있을 수 있습니다.
            </div>
            <div className="flex justify-end gap-2 mt-6 pt-4 border-t border-border">
              <button onClick={() => setDeleteTarget(null)} className="px-4 py-2 rounded text-[13px] font-medium bg-transparent text-text-muted border border-border cursor-pointer hover:bg-surface-hover hover:text-text">취소</button>
              <button
                onClick={() => deleteMutation.mutate({ id: deleteTarget.id, data_type: deleteTarget.data_type })}
                disabled={deleteMutation.isPending}
                className="px-4 py-2 rounded text-[13px] font-medium bg-negative text-white border border-negative cursor-pointer hover:bg-negative-hover disabled:opacity-50"
              >
                삭제
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
