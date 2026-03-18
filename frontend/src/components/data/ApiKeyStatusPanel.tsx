import { useFeedStatus } from '../../hooks/useFeed'
import StatusBadge from '../common/StatusBadge'
import { Skeleton } from '../common/Skeleton'

const KEY_LABELS: Record<string, { name: string; desc: string }> = {
  ANTE_DATAGOKR_API_KEY: {
    name: 'data.go.kr',
    desc: '공공데이터포털 서비스키',
  },
  ANTE_DART_API_KEY: {
    name: 'DART',
    desc: '금융감독원 OpenAPI 인증키',
  },
}

export default function ApiKeyStatusPanel() {
  const { data: feedStatus, isLoading } = useFeedStatus()

  if (isLoading) {
    return (
      <div className="bg-surface border border-border rounded-lg p-5">
        <Skeleton className="h-5 w-40 mb-4" />
        <Skeleton className="h-16 w-full" />
      </div>
    )
  }

  if (!feedStatus) return null

  const { api_keys } = feedStatus

  return (
    <div className="bg-surface border border-border rounded-lg p-5">
      <h3 className="text-[15px] font-semibold mb-4">외부 데이터 API 키</h3>
      <div>
        {api_keys.map((apiKey, idx) => {
          const label = KEY_LABELS[apiKey.key]
          const isLast = idx === api_keys.length - 1
          return (
            <div
              key={apiKey.key}
              className={`flex items-center justify-between py-2.5 ${
                !isLast ? 'border-b border-border' : ''
              }`}
            >
              <div>
                <div className="text-[13px] font-medium">
                  {label?.name ?? apiKey.key}
                </div>
                <div className="text-[12px] text-text-muted mt-0.5">
                  {label?.desc ?? apiKey.key}
                  {apiKey.set && apiKey.source && (
                    <span className="ml-1.5 text-[11px]">
                      (source: {apiKey.source})
                    </span>
                  )}
                </div>
              </div>
              {apiKey.set ? (
                <StatusBadge variant="positive">설정됨</StatusBadge>
              ) : (
                <StatusBadge variant="warning">미설정</StatusBadge>
              )}
            </div>
          )
        })}
      </div>
      {api_keys.some((k) => !k.set) && (
        <div className="bg-info-bg rounded px-3.5 py-2.5 mt-3 text-[12px] text-info">
          API 키 설정: <code className="bg-[rgba(255,255,255,0.08)] px-1.5 py-0.5 rounded-sm text-[12px]">ante feed config set {'<KEY>'} {'<VALUE>'}</code>
        </div>
      )}
    </div>
  )
}
