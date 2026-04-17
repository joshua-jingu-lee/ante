# Strategy 모듈 세부 설계 - 설계 결정 - 봇의 전략 실행 흐름

> 인덱스: [03-design-decisions.md](03-design-decisions.md) | 모듈 인덱스: [README.md](README.md)

# 봇의 전략 실행 흐름

```
Bot 시작
  ↓
StrategyLoader.load(filepath) → Strategy 클래스
  ↓
Strategy(ctx=StrategyContext(...)) → 인스턴스 생성
  ↓
strategy.on_start()
  ↓
[주기적 루프]
  strategy.on_step(context) → signals: list[Signal]
    ↓
  signals가 있으면:
    Signal → OrderRequestEvent로 변환 → EventBus.publish()
      → RuleEngine 검증 → Treasury 자금 확보 → 주문 실행
  ↓
[체결 시]
  strategy.on_fill(fill_info) → follow_up_signals: list[Signal]
    → 후속 시그널이 있으면 OrderRequestEvent로 변환 (손절/익절 즉시 등록)
[외부 데이터/시그널 수신 시]
  strategy.on_data(data) → signals: list[Signal]
    → 시그널이 있으면 OrderRequestEvent로 변환 (즉시 매수/매도)
  ↓
[봇 종료 시]
  strategy.on_stop()
```

**핵심 원칙**:
- 전략은 Signal만 반환, 주문 실행은 Bot과 시스템이 담당
- 모든 주문은 반드시 RuleEngine을 거침 (전략이 검증을 우회 불가)

> 파일 구조: [docs/architecture/generated/project-structure.md](../../architecture/generated/project-structure.md) 참조
