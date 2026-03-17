import type { ApprovalType } from '../../types/approval'

interface ExecutionContentProps {
  type: ApprovalType
  params?: Record<string, unknown>
}

const INFO_BANNERS: Record<ApprovalType, { text: string; variant: 'info' | 'warning' }> = {
  strategy_adopt: { text: '승인 시 해당 전략이 채택(registered) 상태로 전환됩니다.', variant: 'info' },
  budget_change: { text: '승인 시 Treasury에서 예산이 즉시 재배분됩니다.', variant: 'info' },
  bot_create: { text: '승인 시 BotManager에서 봇이 즉시 생성됩니다.', variant: 'info' },
  bot_stop: { text: '승인 시 해당 봇의 거래가 즉시 중지됩니다.', variant: 'warning' },
  rule_change: { text: '승인 시 RuleEngine에서 해당 봇의 규칙이 즉시 갱신됩니다.', variant: 'info' },
}

function InfoBanner({ type }: { type: ApprovalType }) {
  const banner = INFO_BANNERS[type]
  if (!banner) return null

  const isWarning = banner.variant === 'warning'
  return (
    <div className={`${isWarning ? 'bg-warning/10 text-warning' : 'bg-info/10 text-info'} p-3 rounded text-[12px] mb-4`}>
      {isWarning ? '\u26A0' : '\uD83D\uDCA1'} {banner.text}
    </div>
  )
}

function InfoRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex justify-between py-2 border-b border-border text-[13px]">
      <span className="text-text-muted">{label}</span>
      <span>{value}</span>
    </div>
  )
}

function formatCurrency(value: unknown): string {
  const num = Number(value)
  if (isNaN(num)) return String(value ?? '-')
  return `${num.toLocaleString()}원`
}

function StrategyAdoptContent({ params }: { params: Record<string, unknown> }) {
  return (
    <>
      <InfoRow label="대상 전략" value={<span className="font-mono text-[12px]">{String(params.strategy_name ?? '-')}</span>} />
      <InfoRow label="버전" value={String(params.version ?? '-')} />
    </>
  )
}

function BudgetChangeContent({ params }: { params: Record<string, unknown> }) {
  const current = Number(params.current_budget ?? 0)
  const requested = Number(params.requested_budget ?? 0)
  const diff = requested - current
  const pct = current > 0 ? ((diff / current) * 100).toFixed(0) : '-'
  const sign = diff >= 0 ? '+' : ''

  return (
    <>
      <InfoRow label="대상 봇" value={<span className="font-mono text-[12px]">{String(params.bot_id ?? '-')}</span>} />
      <InfoRow label="현재 예산" value={formatCurrency(current)} />
      <InfoRow label="요청 예산" value={formatCurrency(requested)} />
      <InfoRow label="변경폭" value={`${sign}${formatCurrency(diff)} (${sign}${pct}%)`} />
    </>
  )
}

function BotCreateContent({ params }: { params: Record<string, unknown> }) {
  return (
    <>
      <InfoRow label="전략명" value={<span className="font-mono text-[12px]">{String(params.strategy_name ?? '-')}</span>} />
      <InfoRow label="배정 예산" value={formatCurrency(params.budget)} />
      <InfoRow label="거래 모드" value={String(params.trade_mode ?? '-')} />
    </>
  )
}

function BotStopContent({ params }: { params: Record<string, unknown> }) {
  return (
    <>
      <InfoRow label="대상 봇" value={<span className="font-mono text-[12px]">{String(params.bot_id ?? '-')}</span>} />
      <InfoRow label="중지 사유" value={String(params.reason ?? '-')} />
    </>
  )
}

function RuleChangeContent({ params }: { params: Record<string, unknown> }) {
  const rules = (params.rules ?? []) as Array<{
    name: string
    current_value: string | number
    requested_value: string | number
  }>

  return (
    <>
      <InfoRow label="대상 봇" value={<span className="font-mono text-[12px]">{String(params.bot_id ?? '-')}</span>} />
      {rules.length > 0 && (
        <div className="mt-3">
          <div className="text-[12px] font-semibold text-text-muted mb-2">변경 규칙</div>
          <div className="overflow-x-auto">
            <table className="w-full border-collapse">
              <thead>
                <tr>
                  <th className="text-left px-3 py-2 text-[12px] font-semibold text-text-muted border-b border-border">규칙</th>
                  <th className="text-left px-3 py-2 text-[12px] font-semibold text-text-muted border-b border-border">현재 값</th>
                  <th className="text-center px-2 py-2 text-[12px] text-text-muted border-b border-border">&rarr;</th>
                  <th className="text-left px-3 py-2 text-[12px] font-semibold text-text-muted border-b border-border">요청 값</th>
                </tr>
              </thead>
              <tbody>
                {rules.map((rule) => (
                  <tr key={rule.name}>
                    <td className="px-3 py-2 border-b border-border text-[13px] font-mono">{rule.name}</td>
                    <td className="px-3 py-2 border-b border-border text-[13px]">{String(rule.current_value)}</td>
                    <td className="text-center px-2 py-2 border-b border-border text-[13px] text-text-muted">&rarr;</td>
                    <td className="px-3 py-2 border-b border-border text-[13px]">{String(rule.requested_value)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </>
  )
}

const CONTENT_COMPONENTS: Record<ApprovalType, React.FC<{ params: Record<string, unknown> }>> = {
  strategy_adopt: StrategyAdoptContent,
  budget_change: BudgetChangeContent,
  bot_create: BotCreateContent,
  bot_stop: BotStopContent,
  rule_change: RuleChangeContent,
}

export default function ExecutionContent({ type, params }: ExecutionContentProps) {
  const ContentComponent = CONTENT_COMPONENTS[type]
  if (!ContentComponent || !params) return null

  return (
    <div className="bg-surface border border-border rounded-lg p-5 mb-6">
      <h3 className="text-[15px] font-semibold mb-3">실행 내용</h3>
      <InfoBanner type={type} />
      <div className="space-y-0">
        <ContentComponent params={params} />
      </div>
    </div>
  )
}
