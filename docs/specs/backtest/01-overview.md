# Backtest Engine 모듈 세부 설계 - 개요

> 인덱스: [README.md](README.md) | 호환 문서: [backtest.md](backtest.md)

# 개요

Backtest Engine은 **전략을 과거 데이터로 검증하는 시뮬레이션 엔진**이다.
메인 프로세스와 별도 subprocess로 격리 실행(D-004)하여 CPU/메모리를 독립 관리하며,
라이브 봇 운영에 영향을 주지 않는다.

**주요 기능**:
- **Subprocess 격리**: 별도 프로세스에서 실행, 메인 시스템에 무영향
- **전략 직접 로딩**: StrategyLoader로 파일에서 직접 로드 (Registry 경유 불필요)
- **BacktestDataProvider**: Parquet에서 과거 데이터 제공
- **BacktestExecutor**: 가상 체결 시뮬레이션 (슬리피지, 수수료 포함)
- **결과 리포트**: JSON/Parquet 형식 결과 출력 (에이전트가 파싱 가능)
