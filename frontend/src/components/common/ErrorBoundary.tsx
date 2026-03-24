import { Component, type ErrorInfo, type ReactNode } from 'react'

interface Props {
  children: ReactNode
}

interface State {
  hasError: boolean
  error: Error | null
}

export default class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props)
    this.state = { hasError: false, error: null }
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('ErrorBoundary caught:', error, errorInfo)
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="flex items-center justify-center min-h-screen bg-bg">
          <div className="text-center max-w-md px-6">
            <div className="text-[48px] mb-4">💥</div>
            <h1 className="text-[18px] font-semibold mb-2">예기치 않은 오류가 발생했습니다</h1>
            <p className="text-text-muted text-[14px] mb-6">
              {this.state.error?.message || '알 수 없는 오류'}
            </p>
            <button
              onClick={() => {
                this.setState({ hasError: false, error: null })
                window.location.href = '/'
              }}
              className="px-4 py-2 bg-primary text-on-primary rounded-lg border-none cursor-pointer text-[14px] hover:bg-primary-hover"
            >
              대시보드로 돌아가기
            </button>
          </div>
        </div>
      )
    }

    return this.props.children
  }
}
