# Rule Engine 모듈 세부 설계 - 참고 구현체 분석

> 인덱스: [README.md](README.md) | 호환 문서: [rule-engine.md](rule-engine.md)

# 참고 구현체 분석

### FreqTrade의 보호 메커니즘

- 하드코딩된 보호 클래스들 (CooldownPeriod, MaxDrawdown, StopLossGuard)
- 설정 기반 파라미터화
- 모든 보호 조건을 AND로 평가

### NautilusTrader의 리스크 엔진

- 플러그인 방식 룰 인터페이스
- 룰별 평가 결과 (ACCEPT/REJECT/WARN)
- 평가 결과 누적 및 우선순위 처리

### Ante 룰 엔진 설계 방향

Ante는 NautilusTrader의 플러그인 방식을 채택하되, FreqTrade의 간결함을 유지하고 동적 관리를 추가:

- **룰 인터페이스**: ABC 기반 플러그인 시스템
- **2계층 평가**: 계좌 룰 → 전략별 룰 순차 평가
- **설정 기반 룰 로딩**: `load_rules_from_config()` / `load_strategy_rules_from_config()`로 설정 리스트에서 룰 인스턴스 생성
- **룰 레지스트리**: 룰 타입 문자열 → 클래스 매핑 (`RULE_REGISTRY`)으로 동적 인스턴스화
