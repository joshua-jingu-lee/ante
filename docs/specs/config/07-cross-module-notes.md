# Config 모듈 세부 설계 - 타 모듈 설계 시 참고

> 인덱스: [README.md](README.md) | 호환 문서: [config.md](config.md)

# 타 모듈 설계 시 참고

- **Web API 스펙 작성 시**: 외부 접근(포트포워딩) 대비 인증 계층 설계 필요 — 로그인, JWT/세션, API 보호. 인증 관련 정적 설정(`[auth]` 섹션)과 비밀값(`JWT_SECRET` 등)이 이 Config에 추가될 예정
