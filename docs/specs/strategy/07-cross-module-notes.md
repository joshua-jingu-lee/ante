# Strategy 모듈 세부 설계 - 타 모듈 설계 시 참고

> 인덱스: [README.md](README.md) | 호환 문서: [strategy.md](strategy.md)

# 타 모듈 설계 시 참고

- **Bot 스펙 작성 시**: Bot이 Strategy를 로드하고 on_step()을 호출하는 루프 설계, StrategyContext 생성 및 주입 방식
- **Rule Engine 스펙 작성 시**: `get_rules()` 반환값과 전역 룰의 병합/검증 로직
- **Backtest 스펙 작성 시**: `get_params()` 반환값을 활용한 파라미터 최적화, StrategyContext의 백테스트 모드 DataProvider. 백테스트 엔진은 Registry를 거치지 않고 StrategyLoader로 파일에서 직접 로드해야 함 — Agent가 등록 전 반복 검증(validate → backtest → 수정 → 반복)할 수 있도록
- **CLI 스펙 작성 시**: `ante strategy validate/submit/list/info` 커맨드 구현. `ante backtest run <파일경로>` 커맨드는 등록 없이 전략 파일을 직접 로드하여 백테스트 실행 — Agent의 반복 개발 루프 지원
- **Data Pipeline 스펙 작성 시**: StrategyContext.get_ohlcv/get_indicator의 실제 DataProvider 인터페이스
