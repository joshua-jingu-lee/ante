# CLI 모듈 세부 설계 - 미결 사항

> 인덱스: [README.md](README.md) | 호환 문서: [cli.md](cli.md)

# 미결 사항

### 스펙 미구현

- [x] `ante system start` / `ante system stop` — 시스템 시작·종료 커맨드 미구현. `python -m ante.main` 래핑으로 통일된 CLI 진입점 제공, graceful shutdown 지원 (P3) ([#461](https://github.com/joshua-jingu-lee/ante/issues/461))
- [x] `ante strategy` CLI 커맨드 구축 — `list`(stub 상태), `info`, `performance` 미구현. 등록된 전략 목록 조회, 개별 전략 메타데이터·파라미터 상세, 전략별 성과 집계(Agent 피드백용) (P2) ([#462](https://github.com/joshua-jingu-lee/ante/issues/462))

### 백테스트·리포트 플로우 개선

- [x] `ante backtest history <strategy_name>` 신규 — 전략별 백테스트 실행 이력 조회. `BacktestRunStore.list_by_strategy()` 기반 구현 완료 ([#493](https://github.com/joshua-jingu-lee/ante/issues/493))
- [x] `ante backtest run` 수정 — 실행 완료 시 `backtest_runs`에 이력 저장 + run_id 출력 구현 완료 ([#493](https://github.com/joshua-jingu-lee/ante/issues/493))
- [x] `ante report submit --run <run_id>` 옵션 추가 — `--run` 옵션으로 백테스트 run 참조 + 검증 구현 완료 ([#493](https://github.com/joshua-jingu-lee/ante/issues/493))
- [x] `ante notification list` 제거 — notification_history 테이블 제거 완료. CLI 커맨드 stub 처리됨

### `ante init` 통합 초기 설정

- [x] `ante init` 대화형 흐름 구현 완료 ([#557](https://github.com/joshua-jingu-lee/ante/issues/557))
- [x] `MemberService.bootstrap_master()` 토큰 동시 발급
- [x] KIS 연동 정보 미입력 시 `broker_type = "test"`인 "default" Account 자동 생성 (Test 계좌 폴백)
- [x] Telegram 설정 선택 입력 (스킵 시 알림 비활성)

### 구현되었으나 스펙 미반영
