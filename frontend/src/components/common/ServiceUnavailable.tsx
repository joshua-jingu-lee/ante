export default function ServiceUnavailable() {
  return (
    <div className="flex items-center justify-center py-16">
      <div className="text-center">
        <div className="text-[48px] mb-4">🔌</div>
        <h2 className="text-[18px] font-semibold mb-2">서비스에 연결할 수 없습니다</h2>
        <p className="text-text-muted text-[14px] mb-6">
          서버가 응답하지 않습니다. 잠시 후 다시 시도해 주세요.
        </p>
        <button
          onClick={() => window.location.reload()}
          className="px-4 py-2 bg-primary text-on-primary rounded-lg border-none cursor-pointer text-[14px] hover:bg-primary-hover"
        >
          새로고침
        </button>
      </div>
    </div>
  )
}
