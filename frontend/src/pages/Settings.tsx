import { useState } from 'react'
import { useSystemStatus, useKillSwitch, useConfigs, useUpdateConfig } from '../hooks/useSystemStatus'
import LoadingSpinner from '../components/common/LoadingSpinner'

function formatUptime(seconds: number): string {
  const d = Math.floor(seconds / 86400)
  const h = Math.floor((seconds % 86400) / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  if (d > 0) return `${d}일 ${h}시간 ${m}분`
  if (h > 0) return `${h}시간 ${m}분`
  return `${m}분`
}

const CONFIG_HINTS: Record<string, string> = {
  'risk.max_mdd_pct': '고점 대비 N% 하락 시 정지',
  'risk.max_position_pct': '총 자산의 N%까지 한 종목 보유 가능',
  'risk.max_daily_loss_pct': '당일 손실 N% 초과 시 당일 거래 중지',
}

export default function Settings() {
  const { data: status, isLoading: statusLoading } = useSystemStatus()
  const killSwitch = useKillSwitch()
  const { data: configs, isLoading: configLoading } = useConfigs()
  const updateConfig = useUpdateConfig()
  const [editingKey, setEditingKey] = useState<string | null>(null)
  const [editValue, setEditValue] = useState('')
  const [showKillConfirm, setShowKillConfirm] = useState(false)

  if (statusLoading) return <LoadingSpinner />

  const isActive = status?.trading_status === 'ACTIVE'

  const handleKillSwitch = () => {
    if (isActive) {
      setShowKillConfirm(true)
    } else {
      killSwitch.mutate(false)
    }
  }

  const confirmKill = () => {
    killSwitch.mutate(true)
    setShowKillConfirm(false)
  }

  const startEdit = (key: string, value: string) => {
    setEditingKey(key)
    setEditValue(value)
  }

  const saveEdit = () => {
    if (editingKey) {
      updateConfig.mutate({ key: editingKey, value: editValue })
      setEditingKey(null)
    }
  }

  return (
    <div className="grid grid-cols-2 gap-6">
      {/* 좌측 — 시스템 상태 */}
      <div className="space-y-6">
        <div className="bg-surface border border-border rounded-lg p-5">
          <h3 className="text-[15px] font-semibold mb-4">시스템 상태</h3>
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <div className="text-[13px]">거래 상태</div>
                <span className={`inline-flex items-center px-2 py-0.5 rounded-[10px] text-[11px] font-semibold mt-1 ${isActive ? 'bg-positive-bg text-positive' : 'bg-negative-bg text-negative'}`}>
                  {isActive ? 'ACTIVE' : 'HALTED'}
                </span>
              </div>
              <button
                onClick={handleKillSwitch}
                className={`relative w-10 h-[22px] rounded-[11px] border-none cursor-pointer transition-colors ${isActive ? 'bg-positive' : 'bg-border'}`}
              >
                <span className={`absolute top-[2px] w-[18px] h-[18px] bg-white rounded-full transition-transform ${isActive ? 'left-[20px]' : 'left-[2px]'}`} />
              </button>
            </div>
            <div className="flex justify-between py-2 border-t border-border text-[13px]">
              <span className="text-text-muted">시스템 업타임</span>
              <span>{status ? formatUptime(status.uptime_seconds) : '-'}</span>
            </div>
            <div className="flex justify-between py-2 border-t border-border text-[13px]">
              <span className="text-text-muted">실행 중 봇</span>
              <span>{status?.running_bots ?? 0}개</span>
            </div>
            <div className="flex justify-between py-2 border-t border-border text-[13px]">
              <span className="text-text-muted">버전</span>
              <span className="font-mono">{status?.version ?? '-'}</span>
            </div>
          </div>
        </div>
      </div>

      {/* 우측 — 거래소 연결 */}
      <div className="space-y-6">
        <div className="bg-surface border border-border rounded-lg p-5">
          <h3 className="text-[15px] font-semibold mb-4">거래소 연결</h3>
          <div className="space-y-2">
            <div className="flex justify-between py-2 border-b border-border text-[13px]">
              <span className="text-text-muted">한국투자증권 API</span>
              <span className="flex items-center gap-1.5">
                <span className="w-2 h-2 rounded-full bg-positive" />
                연결됨
              </span>
            </div>
            <div className="flex justify-between py-2 text-[13px]">
              <span className="text-text-muted">모드</span>
              <span>모의투자</span>
            </div>
          </div>
        </div>
      </div>

      {/* 하단 — 거래 설정 (전체 폭) */}
      <div className="col-span-2">
        <div className="bg-surface border border-border rounded-lg p-5">
          <h3 className="text-[15px] font-semibold mb-4">거래 설정</h3>
          {configLoading ? (
            <LoadingSpinner />
          ) : (
            <div className="space-y-0">
              {(configs ?? []).map((cfg) => (
                <div key={cfg.key} className="flex items-center justify-between py-3 border-b border-border last:border-b-0">
                  <div>
                    <div className="text-[13px] font-mono">{cfg.key}</div>
                    <div className="text-[11px] text-text-muted mt-0.5">
                      {CONFIG_HINTS[cfg.key] || cfg.description || ''}
                    </div>
                  </div>
                  {editingKey === cfg.key ? (
                    <div className="flex gap-2 items-center">
                      <input
                        value={editValue}
                        onChange={(e) => setEditValue(e.target.value)}
                        className="w-24 bg-bg border border-border rounded px-2 py-1 text-text text-[13px] focus:outline-none focus:border-primary"
                        autoFocus
                      />
                      <button onClick={saveEdit} className="px-2.5 py-1 rounded text-[12px] bg-primary text-white border-none cursor-pointer">저장</button>
                      <button onClick={() => setEditingKey(null)} className="px-2.5 py-1 rounded text-[12px] bg-transparent text-text-muted border border-border cursor-pointer">취소</button>
                    </div>
                  ) : (
                    <button
                      onClick={() => startEdit(cfg.key, cfg.value)}
                      className="text-[13px] font-mono text-text bg-transparent border-none cursor-pointer hover:text-primary"
                    >
                      {cfg.value}
                    </button>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Kill Switch 확인 모달 */}
      {showKillConfirm && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-[200]">
          <div className="bg-surface border border-border rounded-lg p-6 w-[400px]">
            <h3 className="text-[18px] font-bold mb-4">거래 중지 확인</h3>
            <p className="text-[13px] text-negative mb-4">전체 거래가 중단됩니다. 모든 실행 중인 봇이 정지됩니다.</p>
            <div className="flex justify-end gap-2 pt-4 border-t border-border">
              <button onClick={() => setShowKillConfirm(false)} className="px-4 py-2 rounded-lg text-[13px] font-medium bg-transparent text-text-muted border border-border cursor-pointer hover:bg-surface-hover">취소</button>
              <button onClick={confirmKill} className="px-4 py-2 rounded-lg text-[13px] font-medium bg-negative text-white border-none cursor-pointer hover:bg-negative-hover">중지</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
