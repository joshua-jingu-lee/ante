import { useNavigate } from 'react-router-dom'
import StatusBadge from '../common/StatusBadge'
import { MEMBER_STATUS_LABELS } from '../../utils/constants'
import type { Member, MemberStatus } from '../../types/member'

const STATUS_VARIANT: Record<MemberStatus, string> = {
  active: 'positive', suspended: 'warning', revoked: 'negative',
}

interface MemberCardProps {
  member: Member
  onSuspend?: (id: string) => void
  onReactivate?: (id: string) => void
  onRevoke?: (id: string) => void
}

export default function MemberCard({ member, onSuspend, onReactivate, onRevoke }: MemberCardProps) {
  const navigate = useNavigate()

  const isRevoked = member.status === 'revoked'

  return (
    <div
      onClick={() => navigate(`/agents/${member.member_id}`)}
      className={`bg-surface border border-border rounded-lg p-5 flex gap-4 items-start cursor-pointer hover:border-primary/50 transition-colors${isRevoked ? ' opacity-50' : ''}`}
    >
      <div className={`w-[56px] h-[56px] rounded-full bg-bg flex items-center justify-center text-[28px] shrink-0${isRevoked ? ' blur-[2px]' : ''}`}>
        {member.emoji || (member.type === 'human' ? '👤' : '🤖')}
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center justify-between mb-1">
          <span className="text-[15px] font-semibold">{member.name}</span>
          <StatusBadge variant={STATUS_VARIANT[member.status] as 'positive'}>{MEMBER_STATUS_LABELS[member.status]}</StatusBadge>
        </div>
        <div className="text-[13px] text-text-muted font-mono mb-2">{member.member_id}</div>
        <div className="text-[12px] text-text-muted mb-3">소속: {member.org}</div>
        {member.scopes && member.scopes.length > 0 && (
          <div className="flex flex-wrap gap-1 mb-3">
            {member.scopes.slice(0, 4).map((scope) => (
              <span key={scope} className="bg-bg text-text-muted text-[11px] px-2 py-0.5 rounded">{scope}</span>
            ))}
            {member.scopes.length > 4 && (
              <span className="text-text-muted text-[11px]">+{member.scopes.length - 4}</span>
            )}
          </div>
        )}
        {!isRevoked && (onSuspend || onReactivate || onRevoke) && (
          <div className="flex gap-2 justify-end" onClick={(e) => e.stopPropagation()}>
            {member.status === 'active' && onSuspend && (
              <button onClick={() => onSuspend(member.member_id)} className="px-2.5 py-1 rounded-lg text-[12px] bg-transparent text-warning border border-border cursor-pointer hover:bg-warning-bg">정지</button>
            )}
            {member.status === 'suspended' && onReactivate && (
              <button onClick={() => onReactivate(member.member_id)} className="px-2.5 py-1 rounded-lg text-[12px] bg-positive text-white border-none cursor-pointer hover:bg-positive-hover">재활성화</button>
            )}
            {member.status !== 'revoked' && onRevoke && (
              <button onClick={() => onRevoke(member.member_id)} className="px-2.5 py-1 rounded-lg text-[12px] bg-transparent text-negative border border-border cursor-pointer hover:bg-negative-bg">폐기</button>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
