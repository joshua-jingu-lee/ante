# Rule Engine 모듈 세부 설계 - 개요

> 인덱스: [README.md](README.md) | 호환 문서: [rule-engine.md](rule-engine.md)

# 개요

Rule Engine은 Ante의 안전장치로, 모든 거래를 2계층 룰로 검증합니다.
계좌 룰(계좌 레벨)과 전략별 룰(봇 레벨)을 계좌별 독립 인스턴스에서 평가하여 거래를 승인/거부하며,
룰 위반 시 경고/차단/봇 중지/계좌 중지 등의 조치를 취합니다.

- **계좌별 인스턴스**: 각 Account마다 독립적인 RuleEngine 보유
- **2계층 구조**: 계좌 룰 + 전략별 룰
- **주문 검증**: OrderRequestEvent를 평가하여 OrderValidatedEvent/RejectedEvent 발행
- **계좌별 이벤트 필터링**: 각 RuleEngine이 자기 계좌의 이벤트만 처리
- **조건-액션 패턴**: 유연한 룰 정의와 실행
- **동적 관리**: 설정 기반 룰 추가/수정/활성화
- **우선순위 기반 실행**: 룰 우선순위 순서대로 평가
