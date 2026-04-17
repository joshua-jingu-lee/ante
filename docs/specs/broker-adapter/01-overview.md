# Broker Adapter 모듈 세부 설계 - 개요

> 인덱스: [README.md](README.md) | 호환 문서: [broker-adapter.md](broker-adapter.md)

# 개요

Broker Adapter는 Ante의 외부 증권사 API 연동 인터페이스로, 다양한 증권사의 API를 통일된 방식으로 사용할 수 있게 추상화합니다.
현재는 한국투자증권(KIS) Open API를 우선 지원하며, 향후 다른 증권사로의 확장을 고려한 모듈러 설계를 제공합니다.

- **BrokerAdapter 인터페이스**: 증권사별 구현체의 표준 계약 (ABC)
- **어댑터 계층 구조**: KISBaseAdapter(공통) → KISDomesticAdapter(국내) 분리
- **주문 처리 파이프라인**: 요청 → 검증 → 제출 → 체결 → 확인
- **API 관리**: rate limit, 에러 처리, 재시도 로직
- **실시간 데이터**: 웹소켓 기반 가격/체결 스트리밍
- **계좌 연동**: 잔고/포지션/주문 상태 조회
