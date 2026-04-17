# Web API 모듈 세부 설계 - 설계 결정

> 인덱스: [README.md](README.md) | 호환 문서: [web-api.md](web-api.md)

# 설계 결정

## FastAPI 애플리케이션

> 소스: [`src/ante/web/app.py`](../../../src/ante/web/app.py)

**근거** (D-008):
- FastAPI — 타입 힌트 기반 자동 문서화, asyncio 네이티브, 경량
- 의존성 주입 — `app.state`에 서비스 인스턴스 저장, 라우터에서 접근
- React SPA — 빌드된 정적 파일을 FastAPI가 서빙, 별도 웹서버 불필요

## 라우터 구성

| Prefix | 태그 | 설명 |
|--------|------|------|
| `/api/system` | system | 시스템 상태·헬스체크·킬스위치 (계좌별/전체) |
| `/api/accounts` | accounts | 계좌 CRUD + 정지·활성화 |
| `/api/auth` | auth | 세션 인증 (login/logout/me) |
| `/api/bots` | bots | 봇 CRUD + 제어 |
| `/api/trades` | trades | 거래 이력 조회 |
| `/api/strategies` | strategies | 전략 관리 |
| `/api/reports` | reports | 리포트 관리 |
| `/api/notifications` | notifications | ~~알림 이력 조회~~ (텔레그램으로 이관, 라우터 비활성) |
| `/api/data` | data | 데이터셋 조회·삭제 |
| `/api/approvals` | approvals | 결재 관리 (목록/상세/승인·거부) |
| `/api/treasury` | treasury | 자금 관리 (잔고/예산/일별 스냅샷) |
| `/api/portfolio` | portfolio | 포트폴리오 (총 자산·손익·수익률, 자산 추이 — 스냅샷 기반) |
| `/api/members` | members | 멤버(에이전트) 관리 |
| `/api/config` | config | 동적 설정 관리 |
| `/api/audit` | audit | 감사 로그 조회 |

## 인증

세션 기반 인증 구현 완료. `POST /api/auth/login`으로 로그인 후 세션 쿠키를 발급하며, 401 응답 통일. `GET /api/auth/me`로 현재 사용자 정보 조회, `POST /api/auth/logout`으로 로그아웃.

세션 저장·검증의 세부 인터페이스는 [03-session-service.md](03-session-service.md) 참조.

## CORS 설정

홈서버 환경이므로 개발 편의상 전체 origin 허용 (`allow_origins=["*"]`).

## OpenAPI 자동 문서화

FastAPI가 라우터 정의와 Pydantic 스키마(`schemas.py`)로부터 OpenAPI 3.x 스펙을 자동 생성한다. 별도 설정 없이 다음 경로에서 접근 가능:

| 경로 | 설명 |
|------|------|
| `/docs` | Swagger UI — 인터랙티브 API 탐색기. 엔드포인트별 파라미터 확인, 직접 요청 실행 가능 |
| `/redoc` | ReDoc — 읽기 전용 API 레퍼런스 문서 |
| `/openapi.json` | OpenAPI JSON 스키마 원본. Agent나 외부 도구가 API 계약을 파싱할 때 사용 |

> AI Agent는 `/openapi.json`을 조회하여 사용 가능한 엔드포인트, 파라미터, 응답 스키마를 자동으로 파악할 수 있다.
