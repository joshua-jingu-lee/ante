# Strategy 모듈 세부 설계 - 설계 결정 - 전략 등록 플로우

> 인덱스: [03-design-decisions.md](03-design-decisions.md) | 모듈 인덱스: [README.md](README.md)

# 전략 등록 플로우

```
Agent: 전략 파일 작성 (strategies/momentum_breakout.py)
  ↓
CLI: ante strategy submit strategies/momentum_breakout.py
  ↓
StrategyValidator.validate()
  ├─ 실패: 에러 메시지 출력, 등록 차단
  └─ 성공: (경고 있으면 함께 출력)
       ↓
     StrategyLoader.load()  — 실제 import 테스트
       ├─ 실패: 런타임 에러 출력, 등록 차단
       └─ 성공: StrategyMeta 추출
            ↓
          StrategyRegistry.register()
            ↓
          "전략 등록 완료: momentum_breakout_v1.0.0"
```

**단계별 설명**:
1. **정적 검증** (StrategyValidator): 코드 실행 없이 AST 분석
2. **로드 테스트** (StrategyLoader): 실제 import하여 런타임 오류 확인
3. **메타 추출 + 등록** (StrategyRegistry): meta 정보로 레코드 생성
