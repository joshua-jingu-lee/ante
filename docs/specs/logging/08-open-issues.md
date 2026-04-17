# Logging 세부 설계 - 미결 사항

> 인덱스: [README.md](README.md) | 호환 문서: [logging.md](logging.md)

# 미결 사항

- [ ] `JsonFormatter` 초기 구현 (`src/ante/core/log/formatter.py`) 및 단위 테스트
- [ ] `compute_fingerprint()` 구현 및 단위 테스트 (스택에서 `ante.*` 최근 프레임 선택, 폴백 동작)
- [ ] `setup_logging()` 구현 및 `main.py` 통합, 회귀 테스트 (`ANTE_LOG_JSONL` 미설정 시 기존 동작 유지)
- [ ] [config/03-design-decisions.md](../config/03-design-decisions.md)에 `ANTE_ENV`, `ANTE_LOG_JSONL` 환경변수 문서화
- [ ] 주요 에러 경로(`ante.broker.*`, `ante.bot.*`, `ante.web.*`)에 `extra={}` 컨텍스트 필드 점진 보강 — 후속 이슈로 분리
- [ ] 3일 이후 자동 gzip 압축 정책 구현 방식 결정 (`logging.handlers` 후킹 vs 별도 cron/launchd)
- [ ] 멀티 프로세스 환경 지원이 필요해지는 시점의 대안(`ConcurrentRotatingFileHandler` 도입 여부) 검토
- [ ] Fingerprint 규칙 변경 시 기존 GitHub 이슈와의 매칭을 유지하는 마이그레이션 절차
