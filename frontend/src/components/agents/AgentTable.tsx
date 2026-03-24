import { useNavigate } from 'react-router-dom'
import StatusBadge from '../common/StatusBadge'
import { formatDateTime } from '../../utils/formatters'
import { MEMBER_STATUS_LABELS } from '../../utils/constants'
import type { Member, MemberStatus } from '../../types/member'

const STATUS_VARIANT: Record<MemberStatus, string> = {
  active: 'positive', suspended: 'warning', revoked: 'negative',
}

interface AgentTableProps {
  items: Member[]
  onSuspend: (id: string) => void
  onReactivate: (id: string) => void
  onRevoke: (id: string) => void
}

export default function AgentTable({ items, onSuspend, onReactivate, onRevoke }: AgentTableProps) {
  const navigate = useNavigate()

  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse">
        <thead>
          <tr>
            <th className="text-left px-3 py-2.5 text-[12px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">ID</th>
            <th className="text-left px-3 py-2.5 text-[12px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">이름</th>
            <th className="text-left px-3 py-2.5 text-[12px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">소속</th>
            <th className="text-left px-3 py-2.5 text-[12px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">상태</th>
            <th className="text-left px-3 py-2.5 text-[12px] font-semibold text-text-muted uppercase tracking-wider border-b border-border">마지막 활동</th>
            <th className="text-right px-3 py-2.5 text-[12px] font-semibold text-text-muted uppercase tracking-wider border-b border-border"></th>
          </tr>
        </thead>
        <tbody>
          {items.length === 0 ? (
            <tr><td colSpan={6} className="px-3 py-8 text-center text-text-muted text-[13px]">등록된 에이전트가 없습니다</td></tr>
          ) : (
            items.map((m) => (
              <tr key={m.member_id} onClick={() => navigate(`/agents/${m.member_id}`)} className="hover:bg-surface-hover cursor-pointer">
                <td className="px-3 py-3 border-b border-border text-[13px] font-mono font-medium">{m.member_id}</td>
                <td className="px-3 py-3 border-b border-border text-[13px]">{m.name}</td>
                <td className="px-3 py-3 border-b border-border text-[13px] text-text-muted">{m.org}</td>
                <td className="px-3 py-3 border-b border-border text-[13px]">
                  <StatusBadge variant={STATUS_VARIANT[m.status] as 'positive'}>{MEMBER_STATUS_LABELS[m.status]}</StatusBadge>
                </td>
                <td className="px-3 py-3 border-b border-border text-[13px] text-text-muted">
                  {m.last_active_at ? formatDateTime(m.last_active_at) : '-'}
                </td>
                <td className="px-3 py-3 border-b border-border text-[13px] text-right">
                  <div className="flex gap-2 justify-end" onClick={(e) => e.stopPropagation()}>
                    {m.status === 'active' && (
                      <button onClick={() => onSuspend(m.member_id)} className="px-2.5 py-1 rounded-lg text-[12px] bg-transparent text-warning border border-border cursor-pointer hover:bg-warning-bg">정지</button>
                    )}
                    {m.status === 'suspended' && (
                      <button onClick={() => onReactivate(m.member_id)} className="px-2.5 py-1 rounded-lg text-[12px] bg-positive text-on-primary border-none cursor-pointer hover:bg-positive-hover">재활성화</button>
                    )}
                    {m.status !== 'revoked' && (
                      <button onClick={() => onRevoke(m.member_id)} className="px-2.5 py-1 rounded-lg text-[12px] bg-transparent text-negative border border-border cursor-pointer hover:bg-negative-bg">폐기</button>
                    )}
                  </div>
                </td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  )
}
