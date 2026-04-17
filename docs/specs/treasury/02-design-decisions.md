# Treasury 모듈 세부 설계 - 설계 결정

> 인덱스: [README.md](README.md) | 호환 문서: [treasury.md](treasury.md)

# 설계 결정

### 역할 범위

Treasury는 **현금(예산) 흐름만** 추적한다:

- 포지션 추적 → **Trade 모듈** 전담
- 미실현 손익 기반 리스크 모니터링 → **Rule Engine** 전담
- Treasury는 "이 봇의 남은 예산이 주문 금액을 감당할 수 있는가"만 판단

이 분리를 통해:
- AI 전략별로 리스크 임계값을 다르게 설정 가능 (Rule Engine의 전략별 룰)
- Treasury는 단순하고 예측 가능한 예산 관리에 집중
- 자금 제약과 리스크 제약이 분리되어 전략 자유도 극대화
