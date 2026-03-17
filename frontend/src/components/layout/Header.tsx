import { useState, useRef, useEffect } from 'react'
import { useLocation, useNavigate, Link } from 'react-router-dom'
import { useUser, useLogout } from '../../hooks/useAuth'
import { useSystemStatus } from '../../hooks/useSystemStatus'

const PAGE_TITLES: Record<string, string> = {
  '/': '대시보드',
  '/approvals': '결재함',
  '/treasury': '자금관리',
  '/treasury/history': '자금 거래 이력',
  '/strategies': '전략과 성과',
  '/bots': '봇 관리',
  '/backtest-data': '백테스트 데이터',
  '/members': '멤버 관리',
  '/settings': '설정',
}

function getPageTitle(pathname: string): string {
  if (PAGE_TITLES[pathname]) return PAGE_TITLES[pathname]
  if (pathname.startsWith('/approvals/')) return '결재 상세'
  if (pathname.startsWith('/strategies/')) return '전략 상세'
  if (pathname.startsWith('/bots/')) return '봇 상세'
  if (pathname.startsWith('/members/')) return '멤버 상세'
  return '대시보드'
}

function isDetailPage(pathname: string): boolean {
  return /^\/(approvals|strategies|bots|members)\/[^/]+/.test(pathname) || pathname === '/treasury/history'
}

export default function Header() {
  const location = useLocation()
  const navigate = useNavigate()
  const { data: user } = useUser()
  const { data: systemStatus } = useSystemStatus()
  const logoutMutation = useLogout()
  const [menuOpen, setMenuOpen] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)

  const title = getPageTitle(location.pathname)
  const showBack = isDetailPage(location.pathname)

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  return (
    <header className="fixed top-0 left-0 md:left-sidebar right-0 h-header bg-surface border-b border-border flex items-center justify-between px-4 md:px-6 z-[100]">
      <div className="flex items-center gap-4 ml-10 md:ml-0">
        {showBack && (
          <button
            onClick={() => navigate(-1)}
            className="bg-transparent border-none text-text-muted cursor-pointer text-[18px] p-1.5 rounded hover:text-text hover:bg-surface-hover"
          >
            ←
          </button>
        )}
        <h1 className="text-[16px] font-semibold">{title}</h1>
      </div>

      <div className="flex items-center gap-2 md:gap-4">
        <div className="hidden sm:flex items-center gap-1.5 text-[12px] text-text-muted">
          <span
            className={`w-2 h-2 rounded-full ${
              systemStatus?.trading_status === 'ACTIVE' ? 'bg-positive' : 'bg-negative'
            }`}
          />
          {systemStatus?.trading_status ?? '...'}
        </div>

        <div ref={menuRef} className="relative">
          <button
            onClick={() => setMenuOpen(!menuOpen)}
            className="flex items-center gap-2 px-2.5 py-1 rounded-lg cursor-pointer text-[13px] text-text-muted bg-transparent border-none hover:bg-surface-hover hover:text-text"
          >
            <span className="text-[22px] leading-none mt-0.5">🦁</span>
            <span className="hidden sm:inline">{user?.member_id ?? '...'} · {user?.role === 'master' ? '대표' : user?.role}</span>
          </button>

          {menuOpen && (
            <div className="absolute top-[calc(100%+6px)] right-0 bg-surface border border-border rounded-lg shadow-[0_8px_24px_rgba(0,0,0,0.3)] min-w-[200px] z-[200] py-3">
              <div className="px-4 pb-3 border-b border-border text-[12px] text-text-muted">
                <div className="font-medium text-text">{user?.name}</div>
                <div>{user?.org}</div>
              </div>
              <Link
                to="/settings"
                onClick={() => setMenuOpen(false)}
                className="block px-4 py-2 text-[13px] text-text no-underline hover:bg-surface-hover"
              >
                설정
              </Link>
              <button
                onClick={() => { setMenuOpen(false); logoutMutation.mutate() }}
                className="block w-full text-left px-4 py-2 text-[13px] text-negative bg-transparent border-none cursor-pointer hover:bg-surface-hover"
              >
                로그아웃
              </button>
            </div>
          )}
        </div>
      </div>
    </header>
  )
}
