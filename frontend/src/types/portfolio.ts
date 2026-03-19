/**
 * Portfolio 도메인 타입.
 *
 * API 응답 타입은 api.generated.ts에서 자동 생성된 타입을 사용한다.
 * 프론트엔드 전용 타입(Period 등)만 이 파일에 직접 정의한다.
 */
import type {
  PortfolioValueResponse,
  PortfolioHistoryPoint as GeneratedPortfolioHistoryPoint,
  PortfolioHistoryResponse,
} from './api.generated'

// ── API 응답 타입 re-export ──────────────────────────────
export type PortfolioValue = PortfolioValueResponse
export type PortfolioHistoryPoint = GeneratedPortfolioHistoryPoint
export type { PortfolioHistoryResponse }

// ── 프론트엔드 전용 타입 ──────────────────────────────────
export type Period = '1d' | '1w' | '1m' | '3m' | 'all'
