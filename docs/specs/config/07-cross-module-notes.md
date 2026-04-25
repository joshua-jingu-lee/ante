# Config 모듈 세부 설계 - 타 모듈 설계 시 참고

> 인덱스: [README.md](README.md) | 호환 문서: [config.md](config.md)

# 타 모듈 설계 시 참고

- **Path-like 설정**: DB·data·PID·IPC socket·logs·secrets 경로는 [03-design-decisions.md](03-design-decisions.md)의 Ante instance/path contract를 SSOT로 삼는다. 다른 모듈은 CWD 기준 경로 조합을 문서화하지 않는다.
- **DataStore/DataFeed 스펙 작성 시**: canonical data root는 `data.path`이다. `parquet.base_path`는 legacy alias로만 언급한다.
- **CLI/IPC 스펙 작성 시**: 인스턴스 전환은 `--config-dir`/`ANTE_CONFIG_DIR`로 수행한다. `--db-path`와 `--data-path`는 개별 작업 대상 override이며 서버 인스턴스 경계를 바꾸지 않는다.
- **Web API 스펙 작성 시**: 외부 접근(포트포워딩) 대비 인증 계층 설계 필요 — 로그인, JWT/세션, API 보호. 인증 관련 정적 설정(`[auth]` 섹션)과 비밀값(`JWT_SECRET` 등)이 이 Config에 추가될 예정
