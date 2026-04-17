# Web API 모듈 세부 설계 - 개요

> 인덱스: [README.md](README.md) | 호환 문서: [web-api.md](web-api.md)

# 개요

Web API는 **React 대시보드에 데이터를 제공하는 FastAPI 백엔드**이다.
웹 대시보드를 통한 시스템 모니터링·봇 관리·거래 조회를 지원하며, CLI와 동일한 서비스 계층을 공유해 기능 대칭을 유지한다.

**주요 기능**:
- **REST API**: 봇 관리, 거래 조회, 자금 관리, 리포트 관리 등 CRUD
- **정적 파일 서빙**: React 빌드 결과물 배포
- **세션 기반 인증**: 로그인 후 세션 쿠키 발급, 401 응답 통일
- **OpenAPI 자동 문서화**: 라우터 정의와 Pydantic 스키마로부터 OpenAPI 3.x 스펙 자동 생성 — Agent가 계약을 파싱 가능

## Web API가 하지 않는 것

- 도메인 로직 직접 구현 → 각 모듈 서비스(`AccountService`, `BotManager` 등)에 위임
- 알림 발송 → [notification.md](../notification/notification.md) 전담 (텔레그램 등 외부 채널)
- CLI 전용 명령 정의 → [cli.md](../cli/cli.md)에서 별도 관리 (서비스 계층은 공유)
- 인증 정책 결정 → Web API는 세션 발급·검증만 담당, 권한 모델은 [member.md](../member/member.md)
