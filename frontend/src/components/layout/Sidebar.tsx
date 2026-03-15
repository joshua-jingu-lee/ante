import { NavLink } from 'react-router-dom'
import { useApprovals } from '../../hooks/useApprovals'

const NAV_ITEMS = [
  { path: '/', icon: '⭐', label: '대시보드' },
  { path: '/approvals', icon: '📋', label: '결재함', showBadge: true },
  { path: '/treasury', icon: '💰', label: '자금관리' },
  { path: '/strategies', icon: '📈', label: '전략과 성과' },
  { path: '/bots', icon: '🤖', label: '봇 관리' },
  { path: '/backtest-data', icon: '📁', label: '백테스트 데이터' },
  { path: '/agents', icon: '🧑‍💼', label: '에이전트 관리' },
]

export default function Sidebar() {
  const { data: approvals } = useApprovals({ status: 'pending', limit: 0 })
  const pendingCount = approvals?.total ?? 0

  return (
    <aside className="fixed top-0 left-0 w-sidebar h-screen bg-surface border-r border-border flex flex-col z-[101]">
      <div className="h-header flex items-center justify-center gap-0 px-5 border-b border-border">
        <img src="/logo-a.svg" alt="A" className="w-8 h-8" />
        <img src="/logo-n.svg" alt="N" className="w-8 h-8" />
        <img src="/logo-t.svg" alt="T" className="w-8 h-8" />
        <img src="/logo-e.svg" alt="E" className="w-8 h-8" />
      </div>

      <nav className="flex-1 py-3 px-2 flex flex-col gap-0.5">
        {NAV_ITEMS.map((item) => (
          <NavLink
            key={item.path}
            to={item.path}
            end={item.path === '/'}
            className={({ isActive }) =>
              `flex items-center gap-2.5 px-3 py-2.5 rounded-lg text-[15px] font-medium no-underline transition-colors ${
                isActive
                  ? 'bg-primary text-white'
                  : 'text-text-muted hover:bg-surface-hover hover:text-text'
              }`
            }
          >
            <span className="text-[16px] w-5 text-center">{item.icon}</span>
            <span>{item.label}</span>
            {item.showBadge && pendingCount > 0 && (
              <span className="ml-auto bg-negative text-white text-[11px] px-1.5 py-0 rounded-[10px] font-semibold">
                {pendingCount}
              </span>
            )}
          </NavLink>
        ))}
      </nav>

      <div className="px-4 py-3 text-[11px] text-text-muted border-t border-border">
        Ante v0.1.0 · <a href="https://opensource.org/licenses/MIT" className="text-text-muted hover:text-text no-underline">MIT</a>
      </div>
    </aside>
  )
}
