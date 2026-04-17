# Backtest Engine 모듈 세부 설계 - 타 모듈 설계 시 참고

> 인덱스: [README.md](README.md) | 호환 문서: [backtest.md](backtest.md)

# 타 모듈 설계 시 참고

- **Strategy 스펙**: 백테스트 엔진은 Registry를 거치지 않고 StrategyLoader로 직접 로드
- **Data Pipeline 스펙**: BacktestDataProvider가 ParquetStore에서 직접 읽기
- **CLI 스펙**: `ante backtest run <파일경로>` 커맨드
- **Report Store 스펙**: 백테스트 결과를 리포트로 변환하여 저장. `detail_json` 내부 구조는 [report-store.md](../report-store/report-store.md)에 명시
