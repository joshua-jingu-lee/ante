# Logging 세부 설계 - 미결 사항

> 인덱스: [README.md](README.md) | 호환 문서: [logging.md](logging.md)

본 절은 YAGNI 기준으로 현재 스코프에서 해결할 미결 사항을 추린 결과다. 제외된 항목은 제외 사유와 함께 기록하여, 필요가 실제로 발생하는 시점에 재고할 수 있도록 한다.

# 확정 미결사항

스테이징 환경 1차 도입 범위. 각 항목은 별도 이슈로 발행되어 구현된다.

- [ ] `JsonFormatter` 초기 구현 (`src/ante/core/log/formatter.py`) 및 단위 테스트
- [ ] `compute_fingerprint()` 구현 및 단위 테스트 (스택에서 `ante.*` 최근 프레임 선택, 폴백 동작)
- [ ] `setup_logging()` 구현 및 `main.py` 통합, 회귀 테스트 (`ANTE_LOG_JSONL` 미설정 시 기존 동작 유지)
- [ ] [config/03-design-decisions.md](../config/03-design-decisions.md)에 `ANTE_ENV`, `ANTE_LOG_JSONL` 환경변수 문서화

# 스코프 제외 (YAGNI)

요구사항이 실제로 발생하면 해당 시점에 이슈를 발행한다. 지금 스펙에 담지 않는다.

| 항목 | 제외 사유 |
|---|---|
| 에러 경로 `extra={}` 컨텍스트 필드 점진 보강 | [06-context-fields.md](06-context-fields.md) §주입 실패에 대한 내성에 원칙이 이미 기술되어 있다. 전체 경로를 미리 목록화하지 않고, 운용 중 필요성이 드러난 경로만 개별 이슈로 처리한다. |
| 멀티 프로세스 환경 지원 (`ConcurrentRotatingFileHandler`) | [05-handlers-and-rotation.md](05-handlers-and-rotation.md) §동시성에서 단일 프로세스 전제를 명시했다. 멀티 워커 구성은 현재·단기 로드맵에 없다. 필요해지는 시점에 대안을 결정한다. |
| Fingerprint 규칙 변경 마이그레이션 | 아직 배포 전이며 실제 문제가 관찰되지 않았다. 규칙을 바꿀 사유가 생겼을 때, 그 시점의 기존 이슈 볼륨에 맞춰 절차를 정한다. |
| 3일 이후 자동 gzip 압축 | 실측 로그 볼륨 데이터가 없고, 30일 자동 삭제라는 보호막이 이미 있어 무제한 축적되지 않는다. 맥미니 디스크 여유 대비 월 예상 축적량(약 300MB~1.5GB)이 즉각적 문제가 아니며, 필요해지면 `TimedRotatingFileHandler.rotator` 후킹으로 5라인 수준 도입이 가능하다. 실측에서 디스크 압박이 확인되는 시점에 재고한다. |
