# Strategy 모듈 세부 설계 - 설계 결정 - 전략 파일 동적 로딩

> 인덱스: [03-design-decisions.md](03-design-decisions.md) | 모듈 인덱스: [README.md](README.md)

# 전략 파일 동적 로딩

구현: `src/ante/strategy/loader.py` 참조

`importlib.util` 기반으로 전략 파일을 동적 로드하여 Strategy 하위 클래스를 반환한다.

**근거**:
- FreqTrade와 동일한 `importlib.util` 기반 동적 로딩
- 파일 1개 = 전략 1개 원칙 — 모호함 방지
- 클래스 자체를 반환 (인스턴스가 아닌) → Bot이 StrategyContext 주입하며 인스턴스화
