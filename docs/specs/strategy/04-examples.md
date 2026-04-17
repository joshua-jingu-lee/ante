# Strategy 모듈 세부 설계 - 사용 예시

> 인덱스: [README.md](README.md) | 호환 문서: [strategy.md](strategy.md)

# 사용 예시

전략 작성 예시 및 패턴(정량적 전략, 외부 시그널 반응 전략 등)은 다음을 참조:

→ `strategies/_examples/` 참조

### CLI 사용 (Agent 워크플로우)

```bash
# 전략 정적 검증
ante strategy validate strategies/momentum_breakout.py

# 전략 등록 (검증 + 로드 테스트 + 등록)
ante strategy submit strategies/momentum_breakout.py

# 등록된 전략 목록
ante strategy list --format json

# 전략 상세 조회
ante strategy info momentum_breakout_v1.0.0 --format json
```
