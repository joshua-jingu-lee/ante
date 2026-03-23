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

  const isRevoked = member.status === 'revoked'
  const isHuman = member.type === 'human'
  const isAgent = member.type === 'agent'

  const avatarColorClass = isHuman
    ? 'bg-info-bg text-info'
    : 'bg-positive-bg text-positive'

  return (
    <div
      onClick={() => isAgent ? navigate(`/agents/${member.member_id}`) : undefined}
      className={`bg-surface border border-border rounded-lg p-5 flex gap-5 transition-colors${isRevoked ? ' opacity-50' : ''}${isAgent ? ' cursor-pointer hover:border-primary/50' : ''}`}
    >
      {/* 프로필 아바타 */}
      <div className="relative shrink-0 flex items-start justify-center">
        {isOwner && (
          <div className="absolute -top-[13px] left-1/2 -translate-x-1/2 text-[16px] leading-none">
            {'👑'}
          </div>
        )}
        <div className={`w-[72px] h-[72px] rounded-full flex items-center justify-center text-[45px] shrink-0 transition-transform hover:scale-[1.15] hover:-rotate-[8deg] cursor-default ${avatarColorClass}${isRevoked ? ' opacity-50' : ''}`}>
          {member.emoji || (isHuman ? '👤' : '🤖')}
        </div>
      </div>

      {/* 카드 본문 */}
      <div className="flex-1 min-w-0">
        {/* 헤더: ID + 역할/상태 뱃지 */}
        <div className="flex items-center justify-between mb-[10px]">
          <div>
            <div className="text-[15px] font-semibold">{member.member_id}</div>
            <div className="text-[13px] text-text-muted">{member.name}</div>
          </div>
          {isHuman && role ? (
            <span className={`text-[11px] font-medium px-1.5 py-0.5 rounded ${ROLE_BADGE_STYLE[role]}`}>
              {ROLE_LABELS[role]}
            </span>
          ) : (
            <StatusBadge variant={STATUS_VARIANT[member.status] as 'positive'}>
              {MEMBER_STATUS_LABELS[member.status]}
            </StatusBadge>
          )}
        </div>

        {/* 메타 정보 */}
        <div className="flex flex-col gap-1.5 text-[13px] text-text-muted mb-4">
          {isHuman ? (
            <>
              <div className="flex justify-between">
                <span className="text-text-muted">상태</span>
                <StatusBadge variant={STATUS_VARIANT[member.status] as 'positive'}>
                  {MEMBER_STATUS_LABELS[member.status]}
                </StatusBadge>
              </div>
              <div className="flex justify-between">
                <span className="text-text-muted">소속</span>
                <span>{member.org}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-text-muted">마지막 활동</span>
                <span>{member.last_active_at || '-'}</span>
              </div>
            </>
          ) : (
            <>
              <div className="flex justify-between">
                <span className="text-text-muted">소속</span>
                <StatusBadge variant="muted">{member.org}</StatusBadge>
              </div>
              <div className="flex justify-between">
                <span className="text-text-muted">마지막 활동</span>
                <span>{member.last_active_at || '-'}</span>
              </div>
            </>
          )}
        </div>

        {/* 스코프 태그 (에이전트만) */}
        {isAgent && member.scopes && member.scopes.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {member.scopes.map((scope) => (
              <span key={scope} className="text-[11px] px-1.5 py-[1px] rounded-sm bg-bg border border-border text-text-muted">{scope}</span>
            ))}
          </div>
        )}

        {/* Human 멤버 액션 버튼 */}
        {!isRevoked && isHuman && (onSuspend || onChangePassword) && (
          <div className="flex gap-2 justify-end" onClick={(e) => e.stopPropagation()}>
            {!isOwner && member.status === 'active' && onSuspend && (
              <button onClick={() => onSuspend(member.member_id)} className="px-2.5 py-1 rounded-lg text-[12px] bg-transparent text-text-muted border border-border cursor-pointer hover:bg-surface-hover">정지</button>
            )}
            {onChangePassword && (
              <button onClick={() => onChangePassword(member.member_id)} className="px-2.5 py-1 rounded-lg text-[12px] bg-transparent text-text-muted border border-border cursor-pointer hover:bg-surface-hover">비밀번호 변경</button>
            )}
          </div>
        )}

        {/* Agent 멤버 액션 버튼 */}
        {!isRevoked && isAgent && (onSuspend || onReactivate || onRevoke) && (
          <div className="flex gap-2 justify-end mt-3" onClick={(e) => e.stopPropagation()}>
            {member.status === 'active' && onSuspend && (
              <button onClick={() => onSuspend(member.member_id)} className="px-2.5 py-1 rounded-lg text-[12px] bg-transparent text-text-muted border border-border cursor-pointer hover:bg-surface-hover">정지</button>
            )}
            {member.status === 'suspended' && onReactivate && (
              <button onClick={() => onReactivate(member.member_id)} className="px-2.5 py-1 rounded-lg text-[12px] bg-positive text-white border-none cursor-pointer hover:bg-positive-hover">재활성화</button>
            )}
            {onRevoke && (
              <button onClick={() => onRevoke(member.member_id)} className="px-2.5 py-1 rounded-lg text-[12px] bg-transparent text-negative border-none cursor-pointer hover:bg-negative-bg">폐기</button>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
