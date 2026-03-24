import { useState, useMemo, useCallback, useEffect, useRef } from 'react'
import type { Dataset } from '../types/data'
import { useDatasets, useDatasetDetail, useStorageInfo, useDeleteDataset } from '../hooks/useBacktestData'
import { formatNumber, formatDate } from '../utils/formatters'
import { Skeleton } from '../components/common/Skeleton'
import FeedStatusPanel from '../components/data/FeedStatusPanel'

const TF_LABELS: Record<string, string> = { '1d': '1일', '1h': '1시간', '1m': '1분', quarterly: '분기', annual: '연간' }

type DirPath = string[]

interface FileEntry {
  name: string
  isDir: boolean
  dataset?: Dataset
}

function formatSize(bytes: number): string {
  if (bytes >= 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024 / 1024).toFixed(1)} GB`
  if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(0)} MB`
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${bytes} B`
}

function pathToString(path: DirPath): string {
  if (path.length === 0) return '~/data'
  return `~/data/${path.join('/')}`
}

export default function BacktestData() {
  const [currentPath, setCurrentPath] = useState<DirPath>([])
  const [focusIndex, setFocusIndex] = useState(0)
  const [selectedDataset, setSelectedDataset] = useState<Dataset | null>(null)
  const [inputValue, setInputValue] = useState('')
  const [search, setSearch] = useState('')
  const [isSearching, setIsSearching] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<Dataset | null>(null)
  const searchRef = useRef<HTMLInputElement>(null)
  const fileListRef = useRef<HTMLDivElement>(null)

  // Fetch all datasets for building the directory tree
  const { data: allData, isLoading } = useDatasets({ limit: 10000 })
  const { data: storage } = useStorageInfo()
  const deleteMutation = useDeleteDataset()

  const allDatasets = allData?.items ?? []

  // Build directory tree from datasets
  const entries = useMemo((): FileEntry[] => {
    // If searching, return flat list of matching files
    if (isSearching && search.trim()) {
      const q = search.trim().toLowerCase()
      const matched = allDatasets.filter((ds) =>
        ds.symbol.toLowerCase().includes(q),
      )
      return matched.map((ds) => ({
        name: `${ds.data_type}/${ds.symbol}/${ds.timeframe}.parquet`,
        isDir: false,
        dataset: ds,
      }))
    }

    const depth = currentPath.length

    if (depth === 0) {
      // Root: show ohlcv/ and fundamental/ dirs
      const types = new Set(allDatasets.map((ds) => ds.data_type))
      return Array.from(types).sort().map((t) => ({
        name: `${t}/`,
        isDir: true,
      }))
    }

    if (depth === 1) {
      // Type level: show symbol dirs
      const dataType = currentPath[0]
      const symbols = new Set(
        allDatasets.filter((ds) => ds.data_type === dataType).map((ds) => ds.symbol),
      )
      return Array.from(symbols).sort().map((sym) => ({
        name: `${sym}/`,
        isDir: true,
      }))
    }

    if (depth === 2) {
      // Symbol level: show timeframe files
      const [dataType, symbol] = currentPath
      const files = allDatasets.filter(
        (ds) => ds.data_type === dataType && ds.symbol === symbol,
      )
      return files
        .sort((a, b) => a.timeframe.localeCompare(b.timeframe))
        .map((ds) => ({
          name: `${ds.timeframe}.parquet`,
          isDir: false,
          dataset: ds,
        }))
    }

    return []
  }, [allDatasets, currentPath, isSearching, search])

  // Full list including parent entry
  const fullList = useMemo(() => {
    if (isSearching && search.trim()) return entries
    const showParent = currentPath.length > 0
    return showParent ? [{ name: '../', isDir: true } as FileEntry, ...entries] : entries
  }, [entries, currentPath, isSearching, search])

  // Debounce search input (300ms)
  useEffect(() => {
    const timer = setTimeout(() => {
      setSearch(inputValue)
    }, 300)
    return () => clearTimeout(timer)
  }, [inputValue])

  // Reset focus on path/search change
  useEffect(() => {
    setFocusIndex(0)
  }, [currentPath, isSearching, search])

  const navigateUp = useCallback(() => {
    if (currentPath.length > 0) {
      setCurrentPath((prev) => prev.slice(0, -1))
      setSelectedDataset(null)
    }
  }, [currentPath])

  const handleEntryClick = useCallback((entry: FileEntry, index: number) => {
    setFocusIndex(index)
    if (entry.name === '../') {
      navigateUp()
    } else if (entry.isDir) {
      const dirName = entry.name.replace(/\/$/, '')
      setCurrentPath((prev) => [...prev, dirName])
      setSelectedDataset(null)
    } else if (entry.dataset) {
      // If from search results, navigate to the file's directory
      if (isSearching && search.trim()) {
        const ds = entry.dataset
        setCurrentPath([ds.data_type, ds.symbol])
        setIsSearching(false)
        setInputValue('')
        setSearch('')
      }
      setSelectedDataset(entry.dataset)
    }
  }, [navigateUp, isSearching, search])

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === '/') {
      e.preventDefault()
      searchRef.current?.focus()
      setIsSearching(true)
      return
    }

    if (e.key === 'Escape' && isSearching) {
      setIsSearching(false)
      setInputValue('')
      setSearch('')
      fileListRef.current?.focus()
      return
    }

    if (e.key === 'Backspace' && !isSearching) {
      e.preventDefault()
      navigateUp()
      return
    }

    if (e.key === 'ArrowUp') {
      e.preventDefault()
      setFocusIndex((prev) => Math.max(0, prev - 1))
      return
    }

    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setFocusIndex((prev) => Math.min(fullList.length - 1, prev + 1))
      return
    }

    if (e.key === 'Enter') {
      e.preventDefault()
      const entry = fullList[focusIndex]
      if (entry) handleEntryClick(entry, focusIndex)
      return
    }
  }, [fullList, focusIndex, handleEntryClick, navigateUp, isSearching])

  const handleSearchKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') {
      setIsSearching(false)
      setInputValue('')
      setSearch('')
      fileListRef.current?.focus()
    }
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      fileListRef.current?.focus()
    }
  }

  // Storage info string
  const DATA_TYPE_LABELS: Record<string, string> = { ohlcv: 'OHLCV', fundamental: 'Fundamental' }
  const storageStr = storage
    ? `전체 ${formatSize(storage.total_bytes ?? storage.total_mb * 1024 * 1024)}`
      + (storage.by_data_type && Object.keys(storage.by_data_type).length > 0
        ? ` — ${Object.entries(storage.by_data_type).map(([dt, mb]) => `${DATA_TYPE_LABELS[dt] ?? dt} ${mb.toFixed(1)} MB`).join(' · ')}`
        : storage.by_timeframe && Object.keys(storage.by_timeframe).length > 0
          ? ` — ${Object.entries(storage.by_timeframe).map(([tf, mb]) => `${TF_LABELS[tf] ?? tf} ${mb.toFixed(1)} MB`).join(' · ')}`
          : '')
    : ''

  return (
    <>
      {/* Feed 파이프라인 상태 */}
      <FeedStatusPanel />

      {/* 터미널 파일 탐색기 */}
      <div
        className="flex flex-col border border-border rounded-lg overflow-hidden font-mono"
        onKeyDown={handleKeyDown}
      >
        {/* 상단: 검색 바 + 용량 */}
        <div className="flex items-center gap-3 px-3.5 py-2.5 border-b border-border bg-surface">
          <input
            ref={searchRef}
            type="text"
            value={inputValue}
            onChange={(e) => {
              setInputValue(e.target.value)
              if (e.target.value.trim()) setIsSearching(true)
              else setIsSearching(false)
            }}
            onFocus={() => { if (inputValue.trim()) setIsSearching(true) }}
            onKeyDown={handleSearchKeyDown}
            placeholder="종목 코드 검색"
            className="w-[260px] px-2.5 py-1.5 text-[13px] bg-transparent border border-border rounded text-text font-mono placeholder:text-text-muted focus:outline-none focus:border-primary"
          />
          <span className="text-[11px] text-text-muted ml-auto whitespace-nowrap">
            {storageStr}
          </span>
        </div>

        {/* 하단: 2열 (파일 브라우저 + 상세 패널) */}
        <div className="flex min-h-[480px]">
          {/* 왼쪽: 파일 브라우저 */}
          <div className="w-[320px] min-w-[320px] border-r border-border flex flex-col bg-bg">
            {/* 경로 */}
            <div className="px-3.5 py-2 border-b border-border text-[12px] text-text-muted">
              <span className="text-primary">{pathToString(currentPath)}</span>
            </div>

            {/* 파일 리스트 */}
            <div
              ref={fileListRef}
              className="flex-1 overflow-y-auto py-1 focus:outline-none"
              tabIndex={0}
            >
              {isLoading ? (
                <div className="p-4 space-y-2">
                  <Skeleton className="h-5 w-full" />
                  <Skeleton className="h-5 w-3/4" />
                  <Skeleton className="h-5 w-5/6" />
                </div>
              ) : fullList.length === 0 ? (
                <div className="px-3.5 py-4 text-[13px] text-text-muted text-center">
                  {isSearching ? '검색 결과 없음' : '항목 없음'}
                </div>
              ) : (
                fullList.map((entry, idx) => {
                  const isFocused = idx === focusIndex
                  const isActive = !entry.isDir && entry.dataset?.id === selectedDataset?.id
                  const isParent = entry.name === '../'
                  return (
                    <div
                      key={`${entry.name}-${idx}`}
                      onClick={() => handleEntryClick(entry, idx)}
                      className={`flex items-center gap-2 px-3.5 py-1.5 text-[13px] cursor-pointer border-l-2 ${
                        isActive
                          ? 'text-positive border-l-positive'
                          : isFocused
                            ? 'bg-surface-hover border-l-primary'
                            : 'border-l-transparent'
                      } ${isParent ? 'text-text-muted' : entry.isDir ? 'text-primary' : 'text-text-muted'} hover:bg-surface-hover`}
                    >
                      <span className="flex-1 truncate">{entry.name}</span>
                    </div>
                  )
                })
              )}
            </div>
          </div>

          {/* 오른쪽: 터미널 스타일 상세 패널 */}
          <div className="flex-1 overflow-y-auto p-4 bg-bg text-[12px] leading-relaxed text-text-muted font-mono">
            {selectedDataset ? (
              <DatasetDetailPanel dataset={selectedDataset} onDelete={setDeleteTarget} />
            ) : (
              <pre>
                <span className="text-positive">$</span>{' '}
                <span className="text-text opacity-40">_</span>
              </pre>
            )}
          </div>
        </div>
      </div>

      {/* 삭제 확인 모달 */}
      {deleteTarget && (
        <DeleteConfirmModal
          deleteTarget={deleteTarget}
          deleteMutation={deleteMutation}
          onCancel={() => setDeleteTarget(null)}
          onSuccess={() => { setDeleteTarget(null); setSelectedDataset(null) }}
        />
      )}
    </>
  )
}

/* ── 삭제 확인 모달 ── */
function DeleteConfirmModal({ deleteTarget, deleteMutation, onCancel, onSuccess }: {
  deleteTarget: Dataset
  deleteMutation: ReturnType<typeof useDeleteDataset>
  onCancel: () => void
  onSuccess: () => void
}) {
  const { data: detail } = useDatasetDetail(deleteTarget.id)
  const rowCount = detail?.dataset?.row_count ?? deleteTarget.row_count

  return (
    <div className="fixed inset-0 bg-overlay flex items-center justify-center z-[200]">
      <div className="bg-surface border border-border rounded-lg p-6 w-[480px]">
        <h3 className="text-[18px] font-bold mb-5 text-negative">데이터셋 삭제</h3>
        <div className="mb-4 text-[13px] text-text-muted">
          <strong className="text-text">
            {deleteTarget.symbol}
            {deleteTarget.data_type === 'fundamental' ? ' — Fundamental' : ` — ${TF_LABELS[deleteTarget.timeframe] ?? deleteTarget.timeframe}`}
          </strong><br />
          기간: {formatDate(deleteTarget.start_date)} ~ {formatDate(deleteTarget.end_date)}{rowCount ? ` · ${formatNumber(rowCount)}건` : ''}<br /><br />
          삭제된 데이터는 복구할 수 없습니다.
        </div>
        <div className="bg-warning-bg text-warning px-3.5 py-2.5 rounded text-[12px] mb-4">
          이 데이터를 사용 중인 백테스트가 있을 수 있습니다.
        </div>
        <div className="flex justify-end gap-2 mt-6 pt-4 border-t border-border">
          <button onClick={onCancel} className="px-4 py-2 rounded text-[13px] font-medium bg-transparent text-text-muted border border-border cursor-pointer hover:bg-surface-hover hover:text-text">취소</button>
          <button
            onClick={() => deleteMutation.mutate(deleteTarget, { onSuccess })}
            disabled={deleteMutation.isPending}
            className="px-4 py-2 rounded text-[13px] font-medium bg-negative text-on-primary border border-negative cursor-pointer hover:bg-negative-hover disabled:opacity-50"
          >
            삭제
          </button>
        </div>
      </div>
    </div>
  )
}

/* ── 상세 패널 ── */
function DatasetDetailPanel({ dataset, onDelete }: { dataset: Dataset; onDelete: (ds: Dataset) => void }) {
  const ds = dataset
  const filePath = `${ds.data_type}/${ds.symbol}/${ds.timeframe}.parquet`
  const typeLabel = ds.data_type === 'ohlcv' ? 'OHLCV' : 'Fundamental'

  const { data: detail } = useDatasetDetail(ds.id)
  const preview = detail?.preview ?? []
  const detailDs = detail?.dataset
  const rowCount = detailDs?.row_count ?? ds.row_count
  const fileSize = detailDs?.file_size ?? ds.file_size

  const separator = '\u2500'.repeat(65)

  // Build preview table from actual data
  const previewColumns = preview.length > 0 ? Object.keys(preview[0]) : []

  return (
    <div className="space-y-4">
      <pre className="m-0 whitespace-pre overflow-x-auto">
        <span className="text-positive">$</span>{' '}
        <span className="text-text">ante data show {filePath}</span>
      </pre>
      <pre className="m-0 whitespace-pre overflow-x-auto">
        <span className="text-text font-semibold">{'File'}</span>{'       '}{filePath}{'\n'}
        <span className="text-text font-semibold">{'Symbol'}</span>{'     '}{ds.symbol}{'\n'}
        <span className="text-text font-semibold">{'Type'}</span>{'       '}{typeLabel}{'\n'}
        <span className="text-text font-semibold">{'Timeframe'}</span>{'  '}{ds.timeframe}{'\n'}
        <span className="text-text font-semibold">{'Period'}</span>{'     '}{ds.start_date} ~ {ds.end_date}{'\n'}
        <span className="text-text font-semibold">{'Rows'}</span>{'       '}<span className="text-text">{rowCount ? formatNumber(rowCount) : '-'}</span>{'\n'}
        <span className="text-text font-semibold">{'Size'}</span>{'       '}<span className="text-text">{fileSize ? formatSize(fileSize) : '-'}</span>
      </pre>
      <pre className="m-0 whitespace-pre overflow-x-auto text-text-muted">
        <span className="text-border">{separator}</span>{'\n'}
        {preview.length > 0 ? (
          <>
            <span className="text-text font-semibold">{previewColumns.map((c) => c.padEnd(14)).join('')}</span>{'\n'}
            <span className="text-border">{separator}</span>{'\n'}
            {preview.map((row, i) => (
              <span key={i}>
                {previewColumns.map((c) => String(row[c] ?? '').padEnd(14)).join('')}{'\n'}
              </span>
            ))}
          </>
        ) : (
          <>
            <span className="text-text-muted opacity-50">  미리보기 데이터가 없습니다</span>{'\n'}
          </>
        )}
        <span className="text-border">{separator}</span>
      </pre>
      <pre className="m-0 whitespace-pre overflow-x-auto">
        <span className="text-positive">$</span>{' '}
        <button
          onClick={() => onDelete(ds)}
          className="text-negative bg-transparent border-none cursor-pointer font-mono text-[12px] underline p-0"
        >
          삭제
        </button>
      </pre>
    </div>
  )
}
