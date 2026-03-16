import { Link } from 'react-router-dom'

export default function NotFound() {
  return (
    <div className="flex items-center justify-center min-h-[calc(100vh-var(--spacing-header)-48px)]">
      <div className="text-center">
        <div className="text-[64px] font-bold text-text-muted mb-2">404</div>
        <h1 className="text-[18px] font-semibold mb-2">페이지를 찾을 수 없습니다</h1>
        <p className="text-text-muted text-[14px] mb-6">
          요청하신 페이지가 존재하지 않거나 이동되었습니다.
        </p>
        <Link
          to="/"
          className="inline-block px-4 py-2 bg-primary text-white rounded-lg no-underline text-[14px] hover:bg-primary-hover"
        >
          대시보드로 돌아가기
        </Link>
      </div>
    </div>
  )
}
