/** 원화 포맷 (예: 1,000,000원) */
export function formatKRW(value: number): string {
  return new Intl.NumberFormat('ko-KR', {
    style: 'currency',
    currency: 'KRW',
    maximumFractionDigits: 0,
  }).format(value)
}

/** 퍼센트 포맷 (예: +1.23%) */
export function formatPercent(value: number, digits = 2): string {
  const sign = value > 0 ? '+' : ''
  return `${sign}${(value * 100).toFixed(digits)}%`
}

/** 날짜 문자열을 Date로 파싱 (공백 구분자 호환) */
function parseDate(dateStr: string | undefined | null): Date {
  if (!dateStr) return new Date(NaN)
  return new Date(dateStr.replace(' ', 'T'))
}

/** 날짜 포맷 (예: 2025-01-01) */
export function formatDate(dateStr: string | undefined | null): string {
  const d = parseDate(dateStr)
  if (isNaN(d.getTime())) return '-'
  return d.toLocaleDateString('ko-KR', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  })
}

/** 날짜+시간 포맷 (예: 2025-01-01 14:30) */
export function formatDateTime(dateStr: string | undefined | null): string {
  const d = parseDate(dateStr)
  if (isNaN(d.getTime())) return '-'
  return d.toLocaleString('ko-KR', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

/** 숫자 포맷 (천 단위 콤마) */
export function formatNumber(value: number, digits = 0): string {
  return new Intl.NumberFormat('ko-KR', {
    maximumFractionDigits: digits,
  }).format(value)
}
