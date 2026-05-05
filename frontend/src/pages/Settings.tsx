import { useState } from 'react'
import {
  useSystemStatus,
  useHaltSystem,
  useClearHaltSystem,
  useConfigs,
  useUpdateConfig,
} from '../hooks/useSystemStatus'
import { useAccounts } from '../hooks/useAccounts'
import { PageSkeleton } from '../components/common/Skeleton'
import ApiKeyStatusPanel from '../components/data/ApiKeyStatusPanel'

/** 거래 설정: 섹션별 그룹 */
const TRADING_CONFIG_GROUPS = [
  {
    title: '리스크 관리',
    configs: [
      { key: 'risk.max_mdd_pct', label: '최대 낙폭 제한 (%)', desc: '이 비율 초과 시 거래 자동 중지 · 예: 15 → 고점 대비 15% 하락 시 정지' },
      { key: 'risk.max_position_pct', label: '종목당 최대 비중 (%)', desc: '단일 종목에 투입 가능한 최대 예산 비율 · 예: 30 → 예산의 30%까지 한 종목에 투자' },
      { key: 'rule.daily_loss_limit', label: '일일 손실 한도 (%)', desc: '일일 손실이 이 비율 초과 시 전체 거래 정지 · 예: 5 → 당일 손실 5% 초과 시 정지' },
      { key: 'rule.max_exposure_percent', label: '총 노출 한도 (%)', desc: '잔고 대비 최대 투자 비율 · 예: 20 → 총 잔고의 20%까지만 투자' },
      { key: 'rule.max_unrealized_loss', label: '미실현 손실 한도 (%)', desc: '배정 예산 대비 미실현 손실 초과 시 추가 매수 차단 · 예: 10 → 평가손실 10% 초과 시 매수 불가' },
      { key: 'rule.max_trades_per_hour', label: '시간당 최대 거래 수', desc: '봇당 시간당 거래 횟수 제한 · 예: 10 → 봇 1개가 1시간에 최대 10회 거래' },
      { key: 'rule.allowed_hours', label: '거래 허용 시간', desc: '장중 거래 허용 시간대 (KST) · 예: 09:00-15:30 → 오전 9시~오후 3시 30분만 거래' },
    ],
  },
  {
    title: '봇 기본 설정',
    configs: [
      { key: 'bot.default_interval_sec', label: '봇 기본 실행 간격 (초)', desc: '봇 생성 시 기본값 (10~3600) · 예: 60 → 봇이 60초마다 전략 실행' },
    ],
  },
  {
    title: '거래 비용',
    configs: [
      { key: 'broker.commission_rate', label: '매매 수수료율 (%)', desc: '매수/매도 시 증권사 수수료 · 예: 0.015 → 100만원 거래 시 수수료 150원' },
      { key: 'broker.sell_tax_rate', label: '매도 세금율 (%)', desc: '증권거래세 + 농특세 · 예: 0.23 → 100만원 매도 시 세금 2,300원' },
    ],
  },
]

/** 표시 및 알림 설정 */
type DisplayConfig = {
  key: string
  label: string
  desc: string
  type: 'select' | 'toggle'
  options?: string[]
  defaultOption?: string
  disabledByTelegram?: boolean
}

const DISPLAY_CONFIGS: DisplayConfig[] = [
  { key: 'system.log_level', label: '시스템 로그 수준', desc: 'system.log_level · 로그 출력 상세도', type: 'select', options: ['DEBUG', 'INFO', 'WARNING', 'ERROR'] },
  { key: 'notification.telegram_enabled', label: '텔레그램 알림', desc: '텔레그램 알림 및 명령 수신 사용', type: 'toggle' },
  { key: 'notification.min_level', label: '알림 최소 레벨', desc: 'notification.min_level · 이 레벨 미만은 발송하지 않음 (CRITICAL은 항상 발송)', type: 'select', options: ['critical', 'error', 'warning', 'info'], defaultOption: 'info' },
]

function formatTradingMode(mode: string | undefined) {
  const normalized = mode?.toLowerCase()
  if (normalized === 'live') return '실거래'
  if (normalized === 'virtual') return '가상거래'
  return mode || '-'
}

function formatKisEndpoint(brokerConfig: Record<string, unknown> | undefined) {
  const isPaper = brokerConfig?.is_paper
  if (isPaper === true) return 'KIS 모의투자'
  if (isPaper === false) return 'KIS 실전투자'
  return '-'
}

export default function Settings() {
  const { data: status, isLoading: statusLoading } = useSystemStatus()
  // CLI/다른 세션의 system halt/clear-halt를 설정 화면 상태에 반영하기 위해 30초 폴링.
  const { data: accounts, isLoading: accountsLoading } = useAccounts(undefined, {
    refetchInterval: 30_000,
  })
  const haltMutation = useHaltSystem()
  const clearHaltMutation = useClearHaltSystem()
  const { data: configs } = useConfigs()
  const updateConfig = useUpdateConfig()
  const [rowValues, setRowValues] = useState<Record<string, string>>({})
  const [showHaltModal, setShowHaltModal] = useState(false)
  const [showClearHaltModal, setShowClearHaltModal] = useState(false)
  const [haltReason, setHaltReason] = useState('')

  if (statusLoading) return <PageSkeleton />

  // 시스템 상태는 계좌 집계로 산출 (전역 거래 상태 enum은 SSOT 아님).
  // - active > 0 && suspended === 0 이면 ACTIVE.
  // - accounts 로딩 중에는 false negative 방지를 위해 "확인 중" 처리.
  const activeCount = accounts?.filter((a) => a.status === 'active').length ?? 0
  const suspendedCount = accounts?.filter((a) => a.status === 'suspended').length ?? 0
  const isActive = !accountsLoading && activeCount > 0 && suspendedCount === 0
  const configMap = new Map((configs ?? []).map((c) => [c.key, c.value]))
  const primaryAccount = accounts?.[0]

  const getConfigValue = (key: string) => configMap.get(key) ?? ''

  const handleHalt = () => {
    haltMutation.mutate({ reason: haltReason })
    setShowHaltModal(false)
    setHaltReason('')
  }

  const handleClearHalt = () => {
    clearHaltMutation.mutate({})
    setShowClearHaltModal(false)
  }

  const getRowValue = (key: string) =>
    rowValues[key] !== undefined ? rowValues[key] : getConfigValue(key)

  const setRowValue = (key: string, value: string) =>
    setRowValues((prev) => ({ ...prev, [key]: value }))

  const saveRow = (key: string) => {
    updateConfig.mutate({ key, value: getRowValue(key) })
  }

  return (
    <>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
        {/* 시스템 상태 */}
        <div className="bg-surface border border-border rounded-lg p-5">
          <h3 className="text-[15px] font-semibold mb-4">시스템 상태</h3>
          {accountsLoading ? (
            <div className="flex items-center justify-between py-3">
              <div className="flex items-center gap-2 text-[13px] text-text-muted">
                <span className="w-2 h-2 rounded-full bg-border" />
                계좌 상태 확인 중…
              </div>
            </div>
          ) : isActive ? (
            <div className="flex items-center justify-between py-3">
              <div>
                <div className="flex items-center gap-2 text-[13px] text-text-muted">
                  <span className="w-2 h-2 rounded-full bg-positive" />
                  현재 모든 봇의 거래가 정상 운용 중입니다.
                </div>
                <div className="text-[12px] text-text-muted mt-1">
                  활성 계좌 {activeCount}개 · 정지 계좌 {suspendedCount}개
                </div>
              </div>
              <button
                onClick={() => setShowHaltModal(true)}
                className="px-4 py-2 rounded-lg text-[13px] font-medium bg-negative text-on-primary border-none cursor-pointer hover:bg-negative-hover whitespace-nowrap"
              >
                비상 거래 정지
              </button>
            </div>
          ) : (
            <div className="flex items-center justify-between py-3">
              <div>
                <div className="flex items-center gap-2 text-[13px] text-negative font-semibold">
                  <span className="w-2 h-2 rounded-full bg-negative" />
                  거래가 정지되었습니다
                </div>
                <div className="text-[12px] text-text-muted mt-1">
                  활성 계좌 {activeCount}개 · 정지 계좌 {suspendedCount}개
                </div>
                {(status?.haltTime || status?.haltReason) && (
                  <div className="text-[12px] text-text-muted mt-1">
                    {status.haltTime && `정지 시각: ${status.haltTime}`}
                    {status.haltTime && status.haltReason && ' · '}
                    {status.haltReason && `사유: ${status.haltReason}`}
                  </div>
                )}
              </div>
              <button
                onClick={() => setShowClearHaltModal(true)}
                className="px-4 py-2 rounded-lg text-[13px] font-medium bg-positive text-on-primary border-none cursor-pointer hover:bg-positive-hover whitespace-nowrap"
              >
                거래 재개
              </button>
            </div>
          )}
        </div>

        {/* 거래소 연결 */}
        <div className="bg-surface border border-border rounded-lg p-5">
          <h3 className="text-[15px] font-semibold mb-4">거래소 연결</h3>
          <div>
            <div className="flex justify-between py-2 border-b border-border text-[13px]">
              <span className="text-text-muted">이름</span>
              <span>한국투자증권</span>
            </div>
            <div className="flex justify-between py-2 border-b border-border text-[13px]">
              <span className="text-text-muted">거래소</span>
              <span>{getConfigValue('broker.exchange') || 'KRX (한국거래소)'}</span>
            </div>
            <div className="flex justify-between py-2 border-b border-border text-[13px]">
              <span className="text-text-muted">통화</span>
              <span>{getConfigValue('broker.currency') || 'KRW'}</span>
            </div>
            <div className="flex justify-between py-2 border-b border-border text-[13px]">
              <span className="text-text-muted">거래 모드</span>
              <span className="inline-flex items-center px-2 py-0.5 rounded-[10px] text-[11px] font-semibold bg-primary/15 text-primary">
                {formatTradingMode(primaryAccount?.trading_mode)}
              </span>
            </div>
            <div className="flex justify-between py-2 border-b border-border text-[13px]">
              <span className="text-text-muted">KIS 엔드포인트</span>
              <span className="inline-flex items-center px-2 py-0.5 rounded-[10px] text-[11px] font-semibold bg-warning-bg text-warning">
                {formatKisEndpoint(primaryAccount?.broker_config)}
              </span>
            </div>
            <div className="flex justify-between py-2 border-b border-border text-[13px]">
              <span className="text-text-muted">계좌번호</span>
              <span className="font-mono text-[12px]">{getConfigValue('broker.account_no') || '-'}</span>
            </div>
            <div className="flex justify-between py-2 text-[13px]">
              <span className="text-text-muted">수수료율</span>
              <span>{getConfigValue('broker.commission_rate') ? `${getConfigValue('broker.commission_rate')}%` : '-'}</span>
            </div>
          </div>
        </div>
      </div>

      {/* 외부 데이터 API 키 상태 (BD-7) */}
      <div className="mb-6">
        <ApiKeyStatusPanel />
      </div>

      {/* 거래 설정 */}
      <div className="bg-surface border border-border rounded-lg p-5 mb-6">
        <h3 className="text-[15px] font-semibold mb-4">거래 설정</h3>
        <div className="overflow-x-auto">
          <table className="w-full border-collapse">
            <thead>
              <tr>
                <th className="text-left px-3 py-2.5 text-[12px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">설정</th>
                <th className="text-left px-3 py-2.5 text-[12px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">값</th>
                <th className="text-right px-3 py-2.5 text-[12px] font-semibold text-text-muted uppercase tracking-wider border-b border-border"></th>
              </tr>
            </thead>
            <tbody>
              {TRADING_CONFIG_GROUPS.map((group) => (
                <>
                  <tr key={`section-${group.title}`}>
                    <td colSpan={3} className="px-3 pt-5 pb-2 text-[12px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">
                      {group.title}
                    </td>
                  </tr>
                  {group.configs.map((cfg) => (
                    <tr key={cfg.key} className="hover:bg-surface-hover">
                      <td className="px-3 py-3 border-b border-border">
                        <div className="text-[13px] font-medium">{cfg.label}</div>
                        <div className="text-[11px] text-text-muted mt-0.5">{cfg.key} · {cfg.desc}</div>
                      </td>
                      <td className="px-3 py-3 border-b border-border">
                        <input
                          value={getRowValue(cfg.key)}
                          onChange={(e) => setRowValue(cfg.key, e.target.value)}
                          className="w-[120px] bg-bg border border-border rounded px-2 py-1 text-text text-[13px] focus:outline-none focus:border-primary"
                          onKeyDown={(e) => e.key === 'Enter' && saveRow(cfg.key)}
                        />
                      </td>
                      <td className="px-3 py-3 border-b border-border text-right">
                        <button
                          onClick={() => saveRow(cfg.key)}
                          className="px-2.5 py-1 rounded text-[12px] font-medium bg-transparent text-text-muted border border-border cursor-pointer hover:bg-surface-hover hover:text-text"
                        >
                          저장
                        </button>
                      </td>
                    </tr>
                  ))}
                </>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* 표시 및 알림 */}
      <div className="bg-surface border border-border rounded-lg p-5">
        <h3 className="text-[15px] font-semibold mb-4">표시 및 알림</h3>
        <div>
          {/* 금액 단위 위치 토글 */}
          <div className="flex items-center justify-between py-2 border-b border-border">
            <div>
              <div className="text-[13px] font-medium">금액 단위 위치</div>
              <div className="text-[12px] text-text-muted mt-0.5">금액 표시 시 통화 단위(원)의 위치를 설정합니다</div>
            </div>
            <div className="flex gap-2">
              <CurrencyFormatButton
                label={'\u20A9 1,000,000'}
                active={getConfigValue('display.currency_position') === 'prefix'}
                onClick={() => updateConfig.mutate({ key: 'display.currency_position', value: 'prefix' })}
              />
              <CurrencyFormatButton
                label="1,000,000 원"
                active={getConfigValue('display.currency_position') !== 'prefix'}
                onClick={() => updateConfig.mutate({ key: 'display.currency_position', value: 'suffix' })}
              />
            </div>
          </div>
          {DISPLAY_CONFIGS.map((cfg, idx) => {
            const isTelegramOff = cfg.disabledByTelegram && String(getConfigValue('notification.telegram_enabled')) === 'false'
            return (
            <div
              key={cfg.key}
              className={`flex items-center justify-between py-2 ${
                idx < DISPLAY_CONFIGS.length - 1 ? 'border-b border-border' : ''
              } ${isTelegramOff ? 'opacity-40 pointer-events-none' : ''}`}
            >
              <div>
                <div className="text-[13px] font-medium">{cfg.label}</div>
                <div className="text-[12px] text-text-muted mt-0.5">{cfg.desc}</div>
              </div>
              {cfg.type === 'select' && (
                <select
                  value={getConfigValue(cfg.key) || cfg.defaultOption || cfg.options![1]}
                  onChange={(e) => updateConfig.mutate({ key: cfg.key, value: e.target.value })}
                  className="bg-bg border border-border rounded px-2 py-1 text-text text-[13px] cursor-pointer"
                  disabled={isTelegramOff}
                >
                  {cfg.options!.map((opt) => (
                    <option key={opt} value={opt}>{opt}</option>
                  ))}
                </select>
              )}
              {cfg.type === 'toggle' && (
                <button
                  onClick={() => {
                    const current = getConfigValue(cfg.key)
                    updateConfig.mutate({ key: cfg.key, value: current === 'true' ? 'false' : 'true' })
                  }}
                  disabled={isTelegramOff}
                  className={`relative w-10 h-[22px] rounded-[11px] border-none cursor-pointer transition-colors ${
                    getConfigValue(cfg.key) === 'true' ? 'bg-positive' : 'bg-border'
                  }`}
                >
                  <span className={`absolute top-[2px] w-[18px] h-[18px] bg-on-primary rounded-full transition-transform ${
                    getConfigValue(cfg.key) === 'true' ? 'left-[20px]' : 'left-[2px]'
                  }`} />
                </button>
              )}
            </div>
            )
          })}
        </div>
      </div>

      {/* 비상 거래 정지 모달 */}
      {showHaltModal && (
        <div className="fixed inset-0 bg-overlay flex items-center justify-center z-[200]">
          <div className="bg-surface border border-border rounded-lg p-6 w-[480px]">
            <h3 className="text-[18px] font-bold text-negative mb-5">비상 거래 정지</h3>
            <p className="text-[13px] text-text-muted mb-4">
              모든 봇의 거래가 즉시 중단됩니다.<br />
              실행 중인 사이클이 완료된 후 정지되며, 보유 포지션은 유지됩니다.
            </p>
            <div className="mb-4">
              <label className="block text-[12px] font-semibold text-text-muted mb-1.5">정지 사유</label>
              <input
                type="text"
                value={haltReason}
                onChange={(e) => setHaltReason(e.target.value)}
                placeholder="예: 긴급 시장 변동"
                className="w-full bg-bg border border-border rounded-lg px-3 py-2.5 text-text text-[14px] placeholder:text-text-muted focus:outline-none focus:border-primary"
              />
            </div>
            <div className="bg-warning-bg text-warning px-3.5 py-2.5 rounded text-[12px] mb-4">
              ⚠ 이 작업은 실행 중인 모든 봇에 영향을 줍니다.
            </div>
            <div className="flex justify-end gap-2 pt-4 border-t border-border mt-6">
              <button onClick={() => { setShowHaltModal(false); setHaltReason('') }} className="px-4 py-2 rounded-lg text-[13px] font-medium bg-transparent text-text-muted border border-border cursor-pointer hover:bg-surface-hover">취소</button>
              <button onClick={handleHalt} className="px-4 py-2 rounded-lg text-[13px] font-medium bg-negative text-on-primary border-none cursor-pointer hover:bg-negative-hover">거래 정지 확인</button>
            </div>
          </div>
        </div>
      )}

      {/* 거래 재개(정지 해제) 확인 모달 */}
      {showClearHaltModal && (
        <div className="fixed inset-0 bg-overlay flex items-center justify-center z-[200]">
          <div className="bg-surface border border-border rounded-lg p-6 w-[480px]">
            <h3 className="text-[18px] font-bold text-positive mb-5">거래 재개</h3>
            <p className="text-[13px] text-text-muted mb-4">
              모든 정지된 계좌를 ACTIVE 상태로 되돌립니다.
            </p>
            <div className="bg-warning-bg text-warning px-3.5 py-2.5 rounded text-[12px] mb-4">
              ⚠ 계좌 상태만 복구됩니다. 봇은 자동으로 재시작되지 않으므로 필요 시 봇 관리에서 개별 시작해야 합니다.
            </div>
            <div className="flex justify-end gap-2 pt-4 border-t border-border mt-6">
              <button onClick={() => setShowClearHaltModal(false)} className="px-4 py-2 rounded-lg text-[13px] font-medium bg-transparent text-text-muted border border-border cursor-pointer hover:bg-surface-hover">취소</button>
              <button onClick={handleClearHalt} className="px-4 py-2 rounded-lg text-[13px] font-medium bg-positive text-on-primary border-none cursor-pointer hover:bg-positive-hover">거래 재개 확인</button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}

function CurrencyFormatButton({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className={`px-2.5 py-1 rounded-lg text-[12px] font-medium border cursor-pointer transition-colors ${
        active
          ? 'bg-primary text-on-primary border-primary'
          : 'bg-transparent text-text-muted border-border hover:bg-surface-hover'
      }`}
    >
      {label}
    </button>
  )
}
