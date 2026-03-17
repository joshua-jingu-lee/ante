interface PaginationProps {
  total: number
  offset: number
  limit: number
  onPageChange: (offset: number) => void
}

export default function Pagination({ total, offset, limit, onPageChange }: PaginationProps) {
  const start = offset + 1
  const end = Math.min(offset + limit, total)
  const hasPrev = offset > 0
  const hasNext = offset + limit < total

  return (
    <div className="flex items-center justify-between pt-4 text-[13px]">
      <span className="text-text-muted">
        {total}건 중 {start}-{end}
      </span>
      <div className="flex gap-2">
        <button
          onClick={() => onPageChange(Math.max(0, offset - limit))}
          disabled={!hasPrev}
          className="px-3 py-1.5 rounded-lg text-[13px] font-medium border border-border bg-transparent text-text-muted hover:bg-surface-hover hover:text-text disabled:opacity-40 disabled:cursor-not-allowed"
        >
          ← 이전
        </button>
        <button
          onClick={() => onPageChange(offset + limit)}
          disabled={!hasNext}
          className="px-3 py-1.5 rounded-lg text-[13px] font-medium border border-border bg-transparent text-text-muted hover:bg-surface-hover hover:text-text disabled:opacity-40 disabled:cursor-not-allowed"
        >
          다음 →
        </button>
      </div>
    </div>
  )
}
