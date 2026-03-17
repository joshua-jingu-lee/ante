import { useNavigate } from 'react-router-dom'
import StatusBadge from '../common/StatusBadge'
import { MEMBER_STATUS_LABELS } from '../../utils/constants'
import type { Member, MemberStatus, HumanRole } from '../../types/member'

const STATUS_VARIANT: Record<MemberStatus, string> = {
  active: 'positive', suspended: 'warning', revoked: 'negative',
}

const ROLE_BADGE_STYLE: Record<HumanRole, string> = {
  owner: 'bg-primary/15 text-primary',
  master: 'bg-purple-500/15 text-purple-400',
  admin: 'bg-border text-text-muted',
}

const ROLE_LABELS: Record<HumanRole, string> = {
  owner: 'Owner',
  master: 'Master',
  admin: 'Admin',
}

interface MemberCardProps {
  member: Member
  onSuspend?: (id: string) => void
  onReactivate?: (id: string) => void
  onRevoke?: (id: string) => void
  onChangePassword?: (id: string) => void
}

export default function MemberCard({ member, onSuspend, onReactivate, onRevoke, onChangePassword }: MemberCardProps) {
  const navigate = useNavigate()
  const isOwner = member.member_id === 'owner'
  const role = member.role ?? (isOwner ? 'owner' : undefined)

  return (
    <div
      onClick={() => navigate(`/agents/${member.member_id}`)}
      className="bg-surface border border-border rounded-lg p-5 flex gap-4 items-start cursor-pointer hover:border-primary/50 transition-colors"
    >
      <div className="relative shrink-0">
        {role === 'owner' && (
          <div className="absolute -top-3 left-1/2 -translate-x-1/2 text-[16px] leading-none">
            {'👑'}
          </div>
        )}
        <div className="w-[56px] h-[56px] rounded-full bg-bg flex items-center justify-center text-[28px]">
          {member.emoji || (member.type === 'human' ? '👤' : '🤖')}
        </div>
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center justify-between mb-1">
          <div className="flex items-center gap-2">
            <span className="text-[15px] font-semibold">{member.name}</span>
            {role && (
              <span className={`text-[11px] font-medium px-1.5 py-0.5 rounded ${ROLE_BADGE_STYLE[role]}`}>
                {ROLE_LABELS[role]}
              </span>
            )}
          </div>
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
        {/* Human 멤버 액션 버튼 */}
        {member.type === 'human' && (onSuspend || onChangePassword) && (
          <div className="flex gap-2 justify-end" onClick={(e) => e.stopPropagation()}>
            {!isOwner && member.status === 'active' && onSuspend && (
              <button onClick={() => onSuspend(member.member_id)} className="px-2.5 py-1 rounded-lg text-[12px] bg-transparent text-warning border border-border cursor-pointer hover:bg-warning-bg">정지</button>
            )}
            {onChangePassword && (
              <button onClick={() => onChangePassword(member.member_id)} className="px-2.5 py-1 rounded-lg text-[12px] bg-transparent text-text-muted border border-border cursor-pointer hover:bg-surface-hover">비밀번호 변경</button>
            )}
          </div>
        )}
        {/* Agent 멤버 액션 버튼 */}
        {member.type === 'agent' && (onSuspend || onReactivate || onRevoke) && (
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
