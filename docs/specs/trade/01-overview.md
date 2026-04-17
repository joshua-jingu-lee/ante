# Trade 모듈 세부 설계 - 개요

> 인덱스: [README.md](README.md) | 호환 문서: [trade.md](trade.md)

# 개요

Trade 모듈은 **모든 거래의 실행 기록을 영속적으로 저장하고, 봇/전략 단위의 성과 지표를 산출하는 거래 추적 계층**이다.
EventBus를 통해 주문 흐름 이벤트를 구독하여 자동으로 기록하며, 웹 대시보드와 CLI에서 거래 이력 및 성과를 조회할 수 있다.

> **포지션의 단일 소유자(Single Source of Truth)**: 포지션은 거래 기록/회계 관점에서 정의하며,
> Trade 모듈의 `positions` 테이블이 시스템 내 유일한 포지션 저장소이다.
> 다른 모듈(Rule Engine, Bot, Web API 등)이 포지션 정보가 필요하면 `TradeService`를 통해 조회한다.

**주요 기능**:
- **거래 기록 (TradeRecorder)**: OrderFilledEvent, OrderCancelEvent 등 주문 흐름 이벤트를 구독하여 SQLite에 영속 기록
- **포지션 관리 (PositionHistory)**: 종목별 포지션 변동(진입 → 추가 → 일부 청산 → 전량 청산) 추적 — **시스템 유일의 포지션 소스**
- **성과 산출 (PerformanceTracker)**: 봇/전략 단위 수익률, 승률, 최대 낙폭(MDD, Maximum Drawdown) 등 핵심 지표 계산
- **조회 API**: 봇, 전략, 종목, 기간별 필터링을 지원하는 거래/성과/포지션 조회 인터페이스

**EventBus 이벤트 히스토리와의 차이**:
- EventBus 이벤트 히스토리: 인메모리 링버퍼 + 30일 보존, 디버깅/감사 목적
- Trade 모듈: 영속 저장 (보존 기한 없음), 거래 분석/성과 추적 목적
