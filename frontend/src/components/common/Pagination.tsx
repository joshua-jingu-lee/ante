interface PaginationProps {
  total: number
  offset: number
  limit: number
  onPageChange: (offset: number) => void
}

export default function Pagination({ total, offset, limit, onPageChange }: PaginationProps) {
  const start = offset + 1
  const end = Math.min(offset + limit, total)
  const totalPages = Math.ceil(total / limit)
  const currentPage = Math.floor(offset / limit) + 1

  const btnBase =
    'w-8 h-8 flex items-center justify-center rounded-lg text-[13px] font-medium border cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed'
  const btnOutline = `${btnBase} border-border bg-transparent text-text-muted hover:bg-surface-hover hover:text-text`
  const btnActive = `${btnBase} border-primary bg-primary text-on-primary`

  // Build visible page numbers: show up to 5 pages centered around current
  const getPageNumbers = (): number[] => {
    if (totalPages <= 5) {
      return Array.from({ length: totalPages }, (_, i) => i + 1)
    }
    let startPage = Math.max(1, currentPage - 2)
    let endPage = Math.min(totalPages, startPage + 4)
    if (endPage - startPage < 4) {
      startPage = Math.max(1, endPage - 4)
    }
    return Array.from({ length: endPage - startPage + 1 }, (_, i) => startPage + i)
  }

  const pages = getPageNumbers()

  return (
    <div className="flex items-center justify-between pt-4 border-t border-border mt-4 text-[13px]">
      <span className="text-text-muted">
        총 {total}건 중 {start}-{end}
      </span>
      <div className="flex gap-1">
        <button
          onClick={() => onPageChange(0)}
          disabled={currentPage === 1}
          className={btnOutline}
          aria-label="첫 페이지"
        >
          &laquo;
        </button>
        <button
          onClick={() => onPageChange(Math.max(0, (currentPage - 2) * limit))}
          disabled={currentPage === 1}
          className={btnOutline}
          aria-label="이전 페이지"
        >
          &lsaquo;
        </button>
        {pages.map((page) => (
          <button
            key={page}
            onClick={() => onPageChange((page - 1) * limit)}
            className={page === currentPage ? btnActive : btnOutline}
          >
            {page}
          </button>
        ))}
        <button
          onClick={() => onPageChange(currentPage * limit)}
          disabled={currentPage === totalPages}
          className={btnOutline}
          aria-label="다음 페이지"
        >
          &rsaquo;
        </button>
        <button
          onClick={() => onPageChange((totalPages - 1) * limit)}
          disabled={currentPage === totalPages}
          className={btnOutline}
          aria-label="마지막 페이지"
        >
          &raquo;
        </button>
      </div>
    </div>
  )
}
