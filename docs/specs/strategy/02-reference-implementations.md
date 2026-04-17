# Strategy 모듈 세부 설계 - 참고 구현체 분석

> 인덱스: [README.md](README.md) | 호환 문서: [strategy.md](strategy.md)

# 참고 구현체 분석

| 구현체 | 전략 인터페이스 | 데이터 접근 | 주문 제출 | 파라미터 | 로딩 방식 | 검증 |
|--------|--------------|-----------|---------|---------|---------|------|
| NautilusTrader | Strategy ABC + StrategyConfig | 라이프사이클 콜백 (on_bar, on_tick) | self.submit_order() | StrategyConfig dataclass | 코드 등록 | 타입 체크 (Cython) |
| FreqTrade | IStrategy ABC | DataFrame 반환 방식 | DataFrame 컬럼 시그널 | DecimalParameter, IntParameter 등 | importlib 동적 로딩 | 클래스 검사 + dry-run |

**Ante의 위치**:
- NautilusTrader의 라이프사이클 콜백 패턴 채택 (이벤트 드리븐 아키텍처와 자연스러운 결합)
- FreqTrade의 동적 로딩 + AI Agent 생성 파일을 수용하는 구조
- 두 프레임워크에 없는 AST 기반 정적 검증 추가 (AI Agent가 생성한 코드의 안전성 보장)
