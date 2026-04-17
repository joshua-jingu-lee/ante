# Web API 모듈 세부 설계 - Pydantic 스키마

> 인덱스: [README.md](README.md) | 호환 문서: [web-api.md](web-api.md)

# Pydantic 스키마 (`schemas.py`)

| 클래스 | 설명 |
|--------|------|
| `StatusResponse` | 시스템 상태 응답 (status, version) |
| `HealthResponse` | 헬스체크 응답 (ok, checks). [04-system-endpoints.md — 헬스체크 상세](04-system-endpoints.md#헬스체크-상세-get-apisystemhealth) 참조 |
| `ErrorResponse` | RFC 7807 에러 응답 (type, title, detail, status, instance) |
| `ReportSubmitRequest` | 리포트 제출 요청 (strategy_name, strategy_version, backtest_result, summary, recommendation) |
| `LoginRequest` | 로그인 요청 (member_id, password) |
| `LoginResponse` | 로그인 응답 (member_id, name, type) |
| `MeResponse` | 현재 사용자 정보 응답 (member_id, name, type, emoji, role, login_at) |

> 파일 구조: [docs/architecture/generated/project-structure.md](../../architecture/generated/project-structure.md) 참조
